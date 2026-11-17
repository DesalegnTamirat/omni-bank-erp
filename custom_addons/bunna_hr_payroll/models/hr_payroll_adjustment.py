# -*- coding: utf-8 -*-

import re
import logging
import requests
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)

# Protected types that are strictly synchronized via API and locked from manual modification
PROTECTED_CODES = {'OD', 'ASBEZA', 'CIAB', 'CIA', 'CIA-ALL', 'CASH_INDEMNITY'}
PROTECTED_NAMES = {'OD', 'ASBEZA', 'CASH INDEMNITY', 'CASH INDEMNITY ALLOWANCE', 'CASH INDEMNITY BANK'}


def is_protected_adjustment(name=None, code=None, rule_code=None):
    """Check if adjustment is one of OD, ASBEZA, or Cash Indemnity."""
    if code and str(code).strip().upper() in PROTECTED_CODES:
        return True
    if rule_code and str(rule_code).strip().upper() in PROTECTED_CODES:
        return True
    if name:
        clean_name = str(name).strip().upper()
        for p in PROTECTED_NAMES:
            if clean_name == p or clean_name.startswith(p + ' ') or clean_name.startswith(p + '-'):
                return True
    return False


class HrPayrollAdjustment(models.Model):
    _name = 'hr.payroll.adjustment'
    _description = 'Payroll Adjustment'
    _order = 'creation_date desc, id desc'

    name = fields.Char(
        string='Particulars',
        required=True,
        help='Name or title of the payroll adjustment batch (e.g. "OD Deduction April 2026", "Audit & Finance", "Cash Indemnity April 2026")'
    )
    code = fields.Char(
        string='Rule Code',
        help='Salary Rule Code linked to this adjustment (e.g. OTHER, OD, ASBEZA, CIAB, CIA, CIA-ALL, CS, LU, COD)'
    )
    salary_rule_id = fields.Many2one(
        'hr.salary.rule',
        string='Salary Element',
        help='Select the salary rule that represents this adjustment in the payroll computation',
        ondelete='set null'
    )
    payroll_period_id = fields.Many2one(
        'hr.payroll.period',
        string='Payroll Period',
        help='Payroll Period associated with this adjustment batch',
        ondelete='set null',
        index=True
    )
    period_id = fields.Many2one(
        'hr.payroll.period',
        string='Payroll Period',
        compute='_compute_period_id',
        inverse='_inverse_period_id',
        store=True,
        index=True
    )

    @api.depends('payroll_period_id')
    def _compute_period_id(self):
        for rec in self:
            rec.period_id = rec.payroll_period_id

    def _inverse_period_id(self):
        for rec in self:
            if rec.period_id and not rec.payroll_period_id:
                rec.payroll_period_id = rec.period_id
    default_bank_account = fields.Char(
        string='Default Deduction Account',
        size=13,
        help='Standard 13-digit destination account for batch transfer'
    )
    creation_date = fields.Datetime(
        string='Creation Date',
        default=fields.Datetime.now,
        readonly=True,
        copy=False,
        help='Timestamp when this adjustment record was first created'
    )
    last_change_date = fields.Datetime(
        string='Last Change Date',
        default=fields.Datetime.now,
        readonly=True,
        copy=False,
        help='Timestamp when this adjustment record was last updated'
    )
    is_api_synced = fields.Boolean(
        string='API Synced',
        default=False,
        readonly=True,
        help='Indicates this adjustment was synchronized via external API (e.g. OD, ASBEZA, Cash Indemnity).'
    )
    api_sync_label = fields.Char(
        string='API Synced',
        compute='_compute_api_sync_label',
        store=True,
        help='Status indicator: Synced or Manual'
    )
    active = fields.Boolean(
        string='Active',
        default=True,
        help='If unchecked, all employee lines in this adjustment will be excluded from payslips.'
    )
    comments = fields.Text(
        string='Comments / Description',
        help='Additional remarks or internal notes'
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True
    )
    line_ids = fields.One2many(
        'hr.payroll.adjustment.line',
        'adjustment_id',
        string='Adjustment Details',
        copy=True
    )
    total_amount = fields.Float(
        string='Total Amount',
        compute='_compute_totals',
        store=True,
        digits=(16, 2)
    )
    employee_count = fields.Integer(
        string='Employee Count',
        compute='_compute_totals',
        store=True
    )

    @api.depends('is_api_synced', 'code', 'name', 'salary_rule_id.code')
    def _compute_api_sync_label(self):
        for rec in self:
            rule_code = rec.salary_rule_id.code if rec.salary_rule_id else False
            if rec.is_api_synced or is_protected_adjustment(name=rec.name, code=rec.code, rule_code=rule_code):
                rec.api_sync_label = 'Synced'
            else:
                rec.api_sync_label = 'Manual'

    @api.constrains('default_bank_account')
    def _check_default_bank_account(self):
        for rec in self:
            if rec.default_bank_account:
                clean_acc = rec.default_bank_account.strip()
                if len(clean_acc) != 13 or not clean_acc.isdigit():
                    raise ValidationError(_(
                        "The Default Deduction Account must be exactly 13 numeric digits."
                    ))

    @api.depends('line_ids.amount', 'line_ids.active')
    def _compute_totals(self):
        for rec in self:
            active_lines = rec.line_ids.filtered(lambda l: l.active)
            rec.total_amount = sum(active_lines.mapped('amount'))
            rec.employee_count = len(active_lines)

    @api.onchange('salary_rule_id')
    def _onchange_salary_rule_id(self):
        if self.salary_rule_id:
            self.code = self.salary_rule_id.code or 'OTHER'

    # ─────────────────────────────────────────────────────────────────────────
    # CRUD VALIDATIONS: PREVENT MANUAL CREATION/EDITING OF OD, ASBEZA & CASH INDEMNITY
    # ─────────────────────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        from_api = self.env.context.get('from_api', False)
        for vals in vals_list:
            vals['creation_date'] = fields.Datetime.now()
            vals['last_change_date'] = fields.Datetime.now()
            rule_code = False
            if vals.get('salary_rule_id'):
                rule = self.env['hr.salary.rule'].browse(vals['salary_rule_id'])
                rule_code = rule.code
            if not from_api and is_protected_adjustment(name=vals.get('name'), code=vals.get('code'), rule_code=rule_code):
                raise ValidationError(_(
                    "OD, ASBEZA, and Cash Indemnity adjustments cannot be created manually.\n"
                    "These records are strictly received via API synchronization."
                ))
            if from_api or is_protected_adjustment(name=vals.get('name'), code=vals.get('code'), rule_code=rule_code):
                vals['is_api_synced'] = True
        return super().create(vals_list)

    def write(self, vals):
        from_api = self.env.context.get('from_api', False)
        if not from_api:
            for rec in self:
                rule_code = rec.salary_rule_id.code if rec.salary_rule_id else False
                if rec.is_api_synced or is_protected_adjustment(name=rec.name, code=rec.code, rule_code=rule_code):
                    raise ValidationError(_(
                        "Adjustments for OD, ASBEZA, and Cash Indemnity are synchronized via API.\n"
                        "Editing or modifying these records manually is not allowed."
                    ))
                target_code = vals.get('code')
                target_rule_code = False
                if vals.get('salary_rule_id'):
                    rule = self.env['hr.salary.rule'].browse(vals['salary_rule_id'])
                    target_rule_code = rule.code
                if is_protected_adjustment(name=vals.get('name'), code=target_code, rule_code=target_rule_code):
                    raise ValidationError(_(
                        "Cannot rename or change an adjustment to OD, ASBEZA, or Cash Indemnity manually."
                    ))
        vals['last_change_date'] = fields.Datetime.now()
        res = super().write(vals)
        if 'active' in vals:
            for rec in self:
                rec.line_ids._sync_to_contracts()
        return res

    def unlink(self):
        from_api = self.env.context.get('from_api', False)
        if not from_api:
            for rec in self:
                rule_code = rec.salary_rule_id.code if rec.salary_rule_id else False
                if rec.is_api_synced or is_protected_adjustment(name=rec.name, code=rec.code, rule_code=rule_code):
                    raise ValidationError(_(
                        "Adjustments for OD, ASBEZA, and Cash Indemnity are synchronized via API and cannot be deleted manually."
                    ))
        lines = self.mapped('line_ids')
        employees = lines.mapped('employee_id')
        res = super().unlink()
        if employees and 'hr.payroll.adjustment.line' in self.env:
            self.env['hr.payroll.adjustment.line']._sync_to_contracts_for_employees(employees)
        return res

    @api.model
    def sync_payroll_adjustments(self, particulars, records, code='OTHER', rule_id=False, default_account=False, period_id=False):
        """
        API Method to synchronize or create a batch adjustment with employee lines from an external DB.
        """
        self_api = self.with_context(from_api=True)
        norm_code = (code or 'OTHER').strip().upper()

        # Resolve period_id if not explicitly provided
        resolved_period_id = False
        if period_id:
            if isinstance(period_id, int):
                resolved_period_id = period_id
            elif hasattr(period_id, 'id'):
                resolved_period_id = period_id.id
            elif isinstance(period_id, str):
                p_rec = self.env['hr.payroll.period'].search([
                    '|', ('name', '=', period_id.strip()),
                         ('name', 'ilike', period_id.strip())
                ], limit=1)
                if p_rec:
                    resolved_period_id = p_rec.id

        if not resolved_period_id and particulars:
            all_periods = self.env['hr.payroll.period'].search([])
            for p in all_periods:
                if p.name and p.name.strip().lower() in particulars.lower():
                    resolved_period_id = p.id
                    break

        if not resolved_period_id:
            open_periods = self.env['hr.payroll.period'].search([('state', '=', 'open')], limit=1)
            if open_periods:
                resolved_period_id = open_periods.id

        adjustment = self_api.search([('name', '=', particulars)], limit=1)
        if not adjustment:
            create_vals = {
                'name': particulars,
                'code': norm_code,
                'salary_rule_id': rule_id or False,
                'default_bank_account': default_account or False,
                'is_api_synced': True,
                'active': True,
            }
            if resolved_period_id:
                create_vals['payroll_period_id'] = resolved_period_id
                create_vals['period_id'] = resolved_period_id
            adjustment = self_api.create(create_vals)
        else:
            vals = {
                'code': norm_code,
                'is_api_synced': True,
                'active': True,
                'last_change_date': fields.Datetime.now()
            }
            if default_account:
                vals['default_bank_account'] = default_account
            if resolved_period_id and (not adjustment.payroll_period_id or not adjustment.period_id):
                vals['payroll_period_id'] = resolved_period_id
                vals['period_id'] = resolved_period_id
            adjustment.write(vals)

        # Deactivate previous OD adjustments & lines when a new OD adjustment is synced
        is_od = (norm_code == 'OD' or 'OD' in particulars.upper().split() or particulars.upper().startswith('OD'))
        if is_od:
            other_ods = self_api.search([
                ('id', '!=', adjustment.id),
                ('active', '=', True),
                '|', ('code', '=', 'OD'),
                     ('name', 'ilike', 'OD')
            ])
            if other_ods:
                other_ods.write({'active': False})
                other_ods.mapped('line_ids').write({'active': False})

        for rec in records:
            emp = False
            if rec.get('employee_id'):
                emp = self.env['hr.employee'].browse(rec['employee_id'])
            elif rec.get('employee_identification'):
                emp = self.env['hr.employee'].search([
                    '|',
                    ('employee_identification', '=', str(rec['employee_identification']).strip()),
                    ('identification_id', '=', str(rec['employee_identification']).strip())
                ], limit=1)

            if not emp or not emp.exists():
                continue

            amount = float(rec.get('amount') or 0.0)
            net_amount = float(rec.get('net_amount') or rec.get('netAmount') or 0.0)
            balance = float(rec.get('balance') or 0.0)
            salary_amount = float(rec.get('salary_amount') or rec.get('salaryAmount') or 0.0)
            tax_amount = float(rec.get('tax_amount') or rec.get('taxAmount') or 0.0)
            ciamount = float(rec.get('ciamount') or rec.get('ci_amount') or rec.get('ciAmount') or 0.0)

            comments = rec.get('comments', '')
            bank_account = str(rec.get('bank_account') or default_account or adjustment.default_bank_account or '').strip()
            active = rec.get('active', True)

            existing_line = self.env['hr.payroll.adjustment.line'].with_context(from_api=True).search([
                ('adjustment_id', '=', adjustment.id),
                ('employee_id', '=', emp.id)
            ], limit=1)

            line_vals = {
                'adjustment_id': adjustment.id,
                'employee_id': emp.id,
                'bank_account': bank_account,
                'amount': amount,
                'net_amount': net_amount,
                'balance': balance,
                'salary_amount': salary_amount,
                'tax_amount': tax_amount,
                'ciamount': ciamount,
                'comments': comments,
                'active': active,
            }

            if existing_line:
                existing_line.write(line_vals)
            else:
                self.env['hr.payroll.adjustment.line'].with_context(from_api=True).create(line_vals)

        if adjustment.line_ids:
            adjustment.line_ids._sync_to_contracts()

        return adjustment.id

    def _run_init_sql(self, sql):
        with self.env.cr.savepoint():
            self.env.cr.execute(sql)

    @api.model
    def init(self):
        super().init()
        try:
            self._run_init_sql("""
                DO $$
                BEGIN
                    IF EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'hr_other_deduction') THEN
                        ALTER TABLE hr_other_deduction RENAME TO hr_payroll_adjustment;
                    END IF;

                    IF EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'hr_other_deduction_line') THEN
                        ALTER TABLE hr_other_deduction_line RENAME TO hr_payroll_adjustment_line;
                    END IF;

                    IF EXISTS (SELECT FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'hr_payroll_adjustment_line' AND column_name = 'deduction_id') THEN
                        ALTER TABLE hr_payroll_adjustment_line RENAME COLUMN deduction_id TO adjustment_id;
                    END IF;

                    IF EXISTS (SELECT FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'hr_payroll_adjustment' AND column_name = 'deduction_type_id') THEN
                        ALTER TABLE hr_payroll_adjustment RENAME COLUMN deduction_type_id TO salary_rule_id;
                    END IF;
                END $$;

                CREATE EXTENSION IF NOT EXISTS pgcrypto;
                CREATE OR REPLACE FUNCTION cbs_encode(p_text text)
                RETURNS text
                LANGUAGE sql IMMUTABLE SECURITY DEFINER AS $$
                SELECT CASE
                WHEN p_text IS NULL OR p_text LIKE 'enc:%' THEN p_text
                ELSE 'enc:' || encode(pgp_sym_encrypt(p_text, 'q7Tz-Lp3VmX9kRw2YbN8hJdF5sCgE1aU4oIuW6tHyMxKjBnZ0rQe'), 'base64')
                END;
                $$;

                CREATE OR REPLACE FUNCTION cbs_decode(p_text text)
                RETURNS text
                LANGUAGE sql IMMUTABLE SECURITY DEFINER AS $$
                SELECT CASE
                WHEN p_text IS NULL THEN NULL
                WHEN p_text LIKE 'enc:%' THEN pgp_sym_decrypt(decode(substring(p_text from 5), 'base64'), 'q7Tz-Lp3VmX9kRw2YbN8hJdF5sCgE1aU4oIuW6tHyMxKjBnZ0rQe')
                ELSE p_text
                END;
                $$;

                DO $$
                BEGIN
                    IF to_regclass('public.hr_payroll_adjustment') IS NOT NULL THEN
                        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'hr_payroll_adjustment' AND column_name = 'payroll_period_id') THEN
                            ALTER TABLE hr_payroll_adjustment ADD COLUMN payroll_period_id integer;
                        END IF;

                        IF NOT EXISTS (SELECT FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'hr_payroll_adjustment' AND column_name = 'period_id') THEN
                            ALTER TABLE hr_payroll_adjustment ADD COLUMN period_id integer;
                        END IF;

                        UPDATE hr_payroll_adjustment 
                        SET payroll_period_id = period_id 
                        WHERE payroll_period_id IS NULL AND period_id IS NOT NULL;

                        UPDATE hr_payroll_adjustment 
                        SET period_id = payroll_period_id 
                        WHERE period_id IS NULL AND payroll_period_id IS NOT NULL;

                        UPDATE hr_payroll_adjustment 
                        SET is_api_synced = True, api_sync_label = 'Synced' 
                        WHERE code IN ('OD', 'ASBEZA', 'CIAB', 'CIA', 'CIA-ALL', 'CASH_INDEMNITY') 
                           OR name ILIKE '%OD%' 
                           OR name ILIKE '%ASBEZA%' 
                           OR name ILIKE '%Cash Indemnity%';
                        
                        UPDATE hr_payroll_adjustment 
                        SET is_api_synced = False, api_sync_label = 'Manual' 
                        WHERE is_api_synced IS NULL OR is_api_synced = False;
                    END IF;
                END $$;

                DO $$
                BEGIN
                    IF to_regclass('public.hr_payroll_adjustment_line') IS NOT NULL THEN
                        ALTER TABLE hr_payroll_adjustment_line ADD COLUMN IF NOT EXISTS net_amount numeric(16, 2) DEFAULT 0.0;
                        ALTER TABLE hr_payroll_adjustment_line ADD COLUMN IF NOT EXISTS balance numeric(16, 2) DEFAULT 0.0;
                        ALTER TABLE hr_payroll_adjustment_line ADD COLUMN IF NOT EXISTS salary_amount numeric(16, 2) DEFAULT 0.0;
                        ALTER TABLE hr_payroll_adjustment_line ADD COLUMN IF NOT EXISTS tax_amount numeric(16, 2) DEFAULT 0.0;
                        ALTER TABLE hr_payroll_adjustment_line ADD COLUMN IF NOT EXISTS ciamount numeric(16, 2) DEFAULT 0.0;
                        ALTER TABLE hr_payroll_adjustment_line ADD COLUMN IF NOT EXISTS payroll_period_id integer;
                        ALTER TABLE hr_payroll_adjustment_line ADD COLUMN IF NOT EXISTS period_id integer;

                        UPDATE hr_payroll_adjustment_line l
                        SET payroll_period_id = a.payroll_period_id,
                            period_id = a.payroll_period_id
                        FROM hr_payroll_adjustment a
                        WHERE l.adjustment_id = a.id
                          AND (l.payroll_period_id IS NULL OR l.period_id IS NULL)
                          AND a.payroll_period_id IS NOT NULL;
                    END IF;
                END $$;
            """)
        except Exception as e:
            _logger.warning("Could not initialize pgcrypto / migration in hr.payroll.adjustment: %s", e)

    def action_fetch_cbs_od_asbeza(self, *args, **kwargs):
        """
        Triggered by user to call CBS API for OD & ASBEZA.
        Reads credentials from cbs_integration, calls login to get access token,
        then calls /api/v2/payroll/load-deduction to populate the remote deduction table.
        """
        self.env.cr.execute("""
            SELECT endpoint, username, cbs_decode(password) as plain_pwd
            FROM cbs_integration
            WHERE environment = 'CBS' AND status = 'true'
            LIMIT 1;
        """)
        row = self.env.cr.fetchone()
        if not row or not row[0]:
            raise UserError(_("No active CBS configuration found in 'cbs_integration' with environment='CBS' and status='true'."))

        endpoint = (row[0] or '').strip().rstrip('/')
        username = (row[1] or '').strip()
        password = row[2] or ''

        # 1. Login to get access token
        login_url = f"{endpoint}/api/auth/login"
        try:
            login_res = requests.post(
                login_url,
                params={'username': username, 'password': password},
                headers={'Content-Type': 'application/json'},
                timeout=20
            )
        except Exception as e:
            raise UserError(_("Failed to connect to CBS Login API at %s:\n%s") % (login_url, str(e)))

        if login_res.status_code != 200:
            err_msg = login_res.text
            try:
                err_json = login_res.json()
                err_msg = err_json.get('message') or err_msg
            except Exception:
                pass
            raise UserError(_("CBS Login failed (HTTP %s):\n%s") % (login_res.status_code, err_msg))

        login_data = login_res.json()
        token = login_data.get('accessToken') or login_data.get('access_token') or login_data.get('token')
        if not token:
            raise UserError(_("CBS Login succeeded but did not return an access token."))

        # Determine active open Payroll Period
        open_periods = self.env['hr.payroll.period'].search([('state', '=', 'open')])
        if not open_periods:
            raise UserError(_(
                "No OPEN Payroll Period found.\n\n"
                "Please configure and open a Payroll Period before fetching OD & ASBEZA from CBS."
            ))
        if len(open_periods) > 1:
            names = ", ".join(open_periods.mapped('name'))
            raise UserError(_(
                "Multiple OPEN Payroll Periods found (%s).\n\n"
                "There must be exactly ONE active open Payroll Period to fetch OD & ASBEZA. "
                "Please ensure only one matching period is open."
            ) % names)

        period = open_periods[0]
        period_id_int = int(period.id)
        if period_id_int <= 0:
            raise UserError(_("Invalid Payroll Period ID: %s. It must be a positive number.") % period_id_int)

        # 2. Call load-deduction
        load_url = f"{endpoint}/api/v2/payroll/load-deduction"
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        params = {
            'payrollPeriodId': period_id_int,
            'payroll_period_id': period_id_int,
        }
        payload = {
            'payrollPeriodId': period_id_int,
            'payroll_period_id': period_id_int,
        }
        try:
            load_res = requests.post(load_url, headers=headers, params=params, json=payload, timeout=120)
        except Exception as e:
            raise UserError(_("Failed to call CBS Load Deduction API at %s:\n%s") % (load_url, str(e)))

        if load_res.status_code != 200:
            err_msg = load_res.text
            try:
                err_json = load_res.json()
                err_msg = err_json.get('message') or err_json.get('error') or err_msg
            except Exception:
                pass
            raise UserError(_("CBS Load Deduction failed (HTTP %s):\n%s") % (load_res.status_code, err_msg))

        res_data = load_res.json() if load_res.text else {}
        rows = res_data.get('rowsInserted', 0)
        status = res_data.get('status', 'success')

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('CBS OD & ASBEZA Synchronized'),
                'message': _('CBS API completed successfully for period "%s": %s rows inserted into remote deduction table (Status: %s).') % (period.name, rows, status),
                'sticky': False,
                'type': 'success',
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_open_fetch_cash_indemnity_wizard(self, *args, **kwargs):
        """Open the popup wizard to fetch Cash Indemnity from CBS with fromDate, toDate, workingDays."""
        return {
            'name': _('Fetch Cash Indemnity from CBS'),
            'type': 'ir.actions.act_window',
            'res_model': 'cbs.cash.indemnity.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }


class HrPayrollAdjustmentLine(models.Model):
    _name = 'hr.payroll.adjustment.line'
    _description = 'Payroll Adjustment Employee Line'
    _order = 'adjustment_id, employee_id'

    _sql_constraints = [
        ('unique_adjustment_employee', 'unique(adjustment_id, employee_id)',
         'An employee can only appear once in a given adjustment detail batch!')
    ]

    adjustment_id = fields.Many2one(
        'hr.payroll.adjustment',
        string='Adjustment Batch',
        required=True,
        ondelete='cascade',
        index=True
    )
    payroll_period_id = fields.Many2one(
        'hr.payroll.period',
        string='Payroll Period',
        related='adjustment_id.payroll_period_id',
        store=True,
        readonly=True,
        index=True
    )
    period_id = fields.Many2one(
        'hr.payroll.period',
        string='Payroll Period',
        related='adjustment_id.period_id',
        store=True,
        readonly=True,
        index=True
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        index=True
    )
    employee_identification = fields.Char(
        string='Employee ID',
        related='employee_id.employee_identification',
        store=True,
        readonly=True
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        related='employee_id.department_id',
        store=True,
        readonly=True
    )
    bank_account = fields.Char(
        string='Adjustment Account (13 Digits)',
        size=13,
        required=True,
        help='13 numeric digits bank account'
    )
    adjustment_type = fields.Selection([
        ('percentage', 'Percentage'),
        ('fixed', 'Fixed Amount')
    ], string='Adjustment Type', default='fixed', required=True)

    amount = fields.Float(
        string='Adjustment Amount',
        required=True,
        digits=(16, 2),
        help='Adjustment amount for this employee'
    )
    ciamount = fields.Float(
        string='CI Amount',
        digits=(16, 2),
        default=0.0,
        help='Cash Indemnity Allowance amount from CBS API (added to CIA)'
    )
    tax_amount = fields.Float(
        string='Tax Amount',
        digits=(16, 2),
        default=0.0,
        help='Cash Indemnity Tax amount from CBS API (added directly to Income Tax)'
    )
    salary_amount = fields.Float(
        string='Salary Amount',
        digits=(16, 2),
        default=0.0,
        help='Cash Indemnity Salary amount from CBS API (added to Net Salary)'
    )
    net_amount = fields.Float(
        string='Net Amount',
        digits=(16, 2),
        default=0.0,
        help='Net amount returned by CBS API'
    )
    balance = fields.Float(
        string='Balance',
        digits=(16, 2),
        default=0.0,
        help='Remaining balance returned by CBS API'
    )
    comments = fields.Char(
        string='Comments',
        help='Specific circular, installment or reference note'
    )
    creation_date = fields.Datetime(
        string='Created',
        default=fields.Datetime.now,
        readonly=True,
        copy=False
    )
    last_change_date = fields.Datetime(
        string='Last Modified',
        default=fields.Datetime.now,
        readonly=True,
        copy=False
    )
    is_api_synced = fields.Boolean(
        string='API Synced',
        related='adjustment_id.is_api_synced',
        store=True,
        readonly=True
    )
    active = fields.Boolean(
        string='Active',
        default=True,
        help='Toggle to temporarily include or exclude this line from payroll processing'
    )
    code = fields.Char(
        string='Rule Code',
        related='adjustment_id.code',
        store=True,
        readonly=True
    )

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            acc = getattr(self.employee_id, 'bank_account_number', False) or \
                  getattr(self.employee_id, 'account_number', False) or \
                  getattr(self.employee_id, 'bank_account', False) or ''
            if acc:
                self.bank_account = str(acc).strip()
            elif self.adjustment_id and self.adjustment_id.default_bank_account:
                self.bank_account = self.adjustment_id.default_bank_account

    @api.constrains('bank_account')
    def _check_bank_account(self):
        for rec in self:
            if rec.bank_account:
                clean_acc = rec.bank_account.strip()
                if len(clean_acc) != 13 or not clean_acc.isdigit():
                    raise ValidationError(_(
                        "Employee %s deduction/adjustment account must be exactly 13 numeric digits (found '%s')."
                    ) % (rec.employee_id.name, rec.bank_account))

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount < 0:
                raise ValidationError(_("Adjustment amount cannot be negative."))

    def _sync_to_contracts(self):
        """Update active employee contract/version totals when adjustment lines change."""
        employees = self.mapped('employee_id')
        self._sync_to_contracts_for_employees(employees)

    @api.model
    def _sync_to_contracts_for_employees(self, employees):
        if not employees:
            return
        Version = self.env['hr.version'] if 'hr.version' in self.env else False
        if not Version:
            return

        for emp in employees:
            lines = self.search([
                ('employee_id', '=', emp.id),
                ('active', '=', True),
                ('adjustment_id.active', '=', True)
            ])
            od_amt = sum(lines.filtered(lambda l: l.code == 'OD' or (l.adjustment_id and l.adjustment_id.code == 'OD')).mapped('amount'))
            asbeza_amt = sum(lines.filtered(lambda l: l.code == 'ASBEZA' or (l.adjustment_id and l.adjustment_id.code == 'ASBEZA')).mapped('amount'))
            other_amt = sum(lines.filtered(lambda l: not l.code or l.code == 'OTHER' or (l.adjustment_id and l.adjustment_id.code == 'OTHER')).mapped('amount'))
            cs_amt = sum(lines.filtered(lambda l: l.code == 'CS' or (l.adjustment_id and l.adjustment_id.code == 'CS')).mapped('amount'))
            lu_amt = sum(lines.filtered(lambda l: l.code == 'LU' or (l.adjustment_id and l.adjustment_id.code == 'LU')).mapped('amount'))
            ciab_amt = sum(lines.filtered(lambda l: l.code == 'CIAB' or (l.adjustment_id and l.adjustment_id.code == 'CIAB')).mapped('amount'))
            cia_lines = lines.filtered(lambda l: l.code in ('CIA', 'CIA-ALL', 'CASH_INDEMNITY') or (l.adjustment_id and l.adjustment_id.code in ('CIA', 'CIA-ALL', 'CASH_INDEMNITY')) or (l.ciamount and l.ciamount > 0))
            cia_all_amt = sum(l.ciamount for l in cia_lines if l.ciamount)
            cod_amt = sum(lines.filtered(lambda l: l.code == 'COD' or (l.adjustment_id and l.adjustment_id.code == 'COD')).mapped('amount'))

            running_versions = Version.search([
                ('employee_id', '=', emp.id),
                ('state', 'in', ('draft', 'approved'))
            ])
            if running_versions:
                vals = {
                    'other_deductions': other_amt,
                }
                if hasattr(running_versions[0], 'od_deduction'):
                    vals['od_deduction'] = od_amt
                if hasattr(running_versions[0], 'asbeza_deduction'):
                    vals['asbeza_deduction'] = asbeza_amt
                if hasattr(running_versions[0], 'cost_sharing'):
                    vals['cost_sharing'] = cs_amt
                if hasattr(running_versions[0], 'labour_union_contribution'):
                    vals['labour_union_contribution'] = lu_amt
                if hasattr(running_versions[0], 'cash_indemnity_bank'):
                    vals['cash_indemnity_bank'] = ciab_amt
                if hasattr(running_versions[0], 'court_deductions'):
                    vals['court_deductions'] = cod_amt
                if cia_all_amt > 0 and hasattr(running_versions[0], 'cash_indemnity'):
                    vals['cash_indemnity'] = cia_all_amt

                running_versions.sudo().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        from_api = self.env.context.get('from_api', False)
        for vals in vals_list:
            vals['creation_date'] = fields.Datetime.now()
            vals['last_change_date'] = fields.Datetime.now()
            if not from_api and vals.get('adjustment_id'):
                parent = self.env['hr.payroll.adjustment'].browse(vals['adjustment_id'])
                if parent.is_api_synced or is_protected_adjustment(name=parent.name, code=parent.code):
                    raise ValidationError(_(
                        "Employees for OD, ASBEZA, and Cash Indemnity cannot be added or edited manually.\n"
                        "They are automatically received via API."
                    ))
        records = super().create(vals_list)
        records._sync_to_contracts()
        return records

    def write(self, vals):
        from_api = self.env.context.get('from_api', False)
        if not from_api:
            for rec in self:
                if rec.is_api_synced or is_protected_adjustment(name=rec.adjustment_id.name, code=rec.code):
                    raise ValidationError(_(
                        "Adjustment lines for OD, ASBEZA, and Cash Indemnity are synced via API and cannot be edited manually."
                    ))
        vals['last_change_date'] = fields.Datetime.now()
        res = super().write(vals)
        if any(f in vals for f in ('amount', 'ciamount', 'salary_amount', 'tax_amount', 'net_amount', 'balance', 'active', 'employee_id')):
            self._sync_to_contracts()
        return res

    def unlink(self):
        from_api = self.env.context.get('from_api', False)
        if not from_api:
            for rec in self:
                if rec.is_api_synced or is_protected_adjustment(name=rec.adjustment_id.name, code=rec.code):
                    raise ValidationError(_(
                        "Adjustment lines for OD, ASBEZA, and Cash Indemnity are synced via API and cannot be deleted manually."
                    ))
        employees = self.mapped('employee_id')
        res = super().unlink()
        self._sync_to_contracts_for_employees(employees)
        return res
