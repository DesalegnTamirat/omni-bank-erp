# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

import logging
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class BrowsableObject(object):
    """Encapsulation helper providing dict-like and attribute-like dot access for rule execution."""
    def __init__(self, pool, cr, uid, dict_data):
        self.dict_data = dict_data

    def __getattr__(self, name):
        return self.dict_data.get(name, 0.0)

    def __getitem__(self, name):
        return self.dict_data.get(name, 0.0)

    def get(self, name, default=0.0):
        return self.dict_data.get(name, default)


class RuleResult(object):
    """Container for individual computed rule results."""
    def __init__(self, code, total, amount, quantity, rate):
        self.code = code
        self.total = total
        self.amount = amount
        self.quantity = quantity
        self.rate = rate


class HrPayslip(models.Model):
    """
    Enterprise Core Payslip Model (Module 8 - Compensation Management).
    
    Coordinates multi-segment proration, attendance and discipline ingestion,
    statutory tax/pension rule execution, and 3-tier approval lifecycle.
    """
    _name = 'hr.payslip'
    _description = 'Employee Enterprise Payslip'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_from desc, id desc'

    name = fields.Char(string='Payslip Name', compute='_compute_name', store=True)
    number = fields.Char(
        string='Reference Number',
        copy=False,
        readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('hr.payslip') or _('New'),
        help="Unique generated payslip serial reference."
    )
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True, index=True)
    contract_id = fields.Many2one('hr.version', string='Contract / Version', required=False, tracking=True)
    struct_id = fields.Many2one('hr.payroll.structure', string='Salary Structure', required=True, tracking=True)
    
    date_from = fields.Date(string='Period From', required=True, default=lambda self: fields.Date.today().replace(day=1), tracking=True)
    date_to = fields.Date(string='Period To', required=True, tracking=True)
    period_id = fields.Many2one('hr.payroll.period', string='Payroll Accounting Period', tracking=True)
    
    payslip_run_id = fields.Many2one('hr.payslip.run', string='Payroll Batch Run', ondelete='cascade', index=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)
    operating_unit_id = fields.Many2one('operating.unit', string='Operating Unit / Branch')

    # State Workflow
    state = fields.Selection([
        ('draft', 'Draft / Calculation'),
        ('verify', 'Under Verification (Sr Controller)'),
        ('done', 'Approved & Finalized'),
        ('paid', 'Disbursed / Paid'),
        ('cancel', 'Cancelled / Voided'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False)

    # Sub-Period Proration Segments (FR-PAY-002, 006, 012, 017, 020)
    segment_ids = fields.One2many('hr.payslip.segment', 'payslip_id', string='Proration Time Slices', copy=True)
    
    # Financial Lines & Inputs
    line_ids = fields.One2many('hr.payslip.line', 'slip_id', string='Computed Payslip Lines', copy=False)
    input_line_ids = fields.One2many('hr.payslip.input', 'payslip_id', string='Variable Financial Inputs', copy=True)

    # Key Monetary Summaries (Stored for instant query & reporting)
    basic_wage = fields.Float(string='Basic Wage (ETB)', digits=(16, 2), tracking=True)
    gross_wage = fields.Float(string='Gross Earnings (ETB)', digits=(16, 2), tracking=True)
    net_wage = fields.Float(string='Net Payable (ETB)', digits=(16, 2), tracking=True)
    
    income_tax = fields.Float(string='Personal Income Tax (ETB)', digits=(16, 2))
    pension_ee = fields.Float(string='Employee Pension 7% (ETB)', digits=(16, 2))
    pension_er = fields.Float(string='Employer Pension 11% (ETB)', digits=(16, 2))
    
    hardship_wage = fields.Float(string='Hardship Allowance (ETB)', digits=(16, 2))
    acting_wage = fields.Float(string='Acting Allowance (ETB)', digits=(16, 2))
    discipline_deductions = fields.Float(string='Disciplinary Deductions (ETB)', digits=(16, 2))
    absence_deductions = fields.Float(string='Absence Deductions (ETB)', digits=(16, 2))
    retroactive_arrears = fields.Float(string='Retroactive Arrears (ETB)', digits=(16, 2))
    retroactive_recoveries = fields.Float(string='Retroactive Recoveries (ETB)', digits=(16, 2))

    # Diagnostics & Exception Tracking
    exception_ids = fields.One2many('hr.payroll.exception', 'payslip_id', string='Detected Anomalies')
    has_critical_exceptions = fields.Boolean(
        string='Has Critical Exception',
        compute='_compute_exceptions_status',
        store=True
    )

    bank_account = fields.Char(string='Salary Bank Account')
    employee_tin = fields.Char(string='TIN Number')
    notes = fields.Text(string='Internal Notes')

    @api.depends('employee_id.name', 'date_from', 'date_to')
    def _compute_name(self):
        for rec in self:
            emp_name = rec.employee_id.name or 'Employee'
            d_from = rec.date_from or ''
            d_to = rec.date_to or ''
            rec.name = f"Salary Slip - {emp_name} ({d_from} ~ {d_to})"

    @api.depends('exception_ids.severity', 'exception_ids.is_resolved')
    def _compute_exceptions_status(self):
        for rec in self:
            unresolved_critical = rec.exception_ids.filtered(lambda e: e.severity == 'critical' and not e.is_resolved)
            rec.has_critical_exceptions = bool(unresolved_critical)

    @api.onchange('employee_id', 'date_from', 'date_to')
    def _onchange_employee(self):
        """Auto-populate contract, default structure, bank account, and TIN from employee master."""
        if not self.employee_id:
            return

        # Find contract/version
        ContractModel = self.env.get('hr.version')
        if ContractModel:
            contract = ContractModel.search([
                ('employee_id', '=', self.employee_id.id),
            ], limit=1)
            if contract:
                self.contract_id = contract.id
                self.bank_account = getattr(contract, 'salary_account', False) or getattr(self.employee_id, 'salary_account', False)
                self.employee_tin = getattr(contract, 'employee_tin', False) or getattr(self.employee_id, 'tin', False)

        if not self.struct_id:
            default_struct = self.env['hr.payroll.structure'].search([('code', '=', 'ETH_BANK_STD')], limit=1)
            if default_struct:
                self.struct_id = default_struct.id

    # ─────────────────────────────────────────────────────────────────────────
    # DYNAMIC TIME SLICE & PRORATION ENGINE (FR-PAY-002, 006, 008, 012, 017)
    # ─────────────────────────────────────────────────────────────────────────
    def _generate_proration_segments(self):
        """
        Calculates mid-month proration time slices based on employee lifecycle events.
        Handles join dates, branch transfers (hardship), promotions, and demotions.
        """
        self.ensure_one()
        self.segment_ids.unlink()

        start_dt = self.date_from
        end_dt = self.date_to
        total_days = 30  # Standard bank divisor

        emp = self.employee_id
        contract = self.contract_id
        base_wage = getattr(contract, 'wage', 0.0) or getattr(contract, 'base_salary', 0.0) or getattr(emp, 'basic_salary', 0.0) or 0.0
        trans_alw = getattr(contract, 'transportation_allowance', 0.0) or 0.0
        house_alw = getattr(contract, 'housing_allowance', 0.0) or 0.0

        # Scenario 1: Mid-Month Joiner (FR-PAY-012)
        join_date = getattr(emp, 'joining_date', False) or getattr(emp, 'first_contract_date', False) or start_dt
        if join_date and start_dt < join_date <= end_dt:
            # Days worked from join date through end of period
            worked_days = (end_dt - join_date).days + 1
            self.env['hr.payslip.segment'].create({
                'payslip_id': self.id,
                'name': _("Mid-Month Joiner (%s ~ %s)") % (join_date, end_dt),
                'segment_type': 'joiner',
                'date_start': join_date,
                'date_end': end_dt,
                'days_count': worked_days,
                'total_period_days': total_days,
                'basic_salary': base_wage,
                'transport_allowance': trans_alw,
                'housing_allowance': house_alw,
                'hardship_percentage': self._get_location_hardship_rate(emp.department_id),
            })
            return

        # Scenario 2: Mid-Month Branch Transfer (FR-PAY-005, 006, 007, 008)
        TransferModel = self.env.get('hr.job.transfer') or self.env.get('transfer.form')
        transfer = False
        if TransferModel:
            transfer = TransferModel.search([
                ('employee_id', '=', emp.id),
                ('state', 'in', ['approved', 'done']),
                ('effective_date', '>', start_dt),
                ('effective_date', '<=', end_dt),
            ], order='effective_date asc', limit=1)

        if transfer and hasattr(transfer, 'effective_date') and transfer.effective_date:
            trans_date = transfer.effective_date
            pre_days = (trans_date - start_dt).days
            post_days = (end_dt - trans_date).days + 1
            
            old_branch = getattr(transfer, 'previous_department_id', emp.department_id)
            new_branch = getattr(transfer, 'department_id', emp.department_id)
            
            old_hardship = self._get_location_hardship_rate(old_branch)
            new_hardship = self._get_location_hardship_rate(new_branch)

            # Pre-Transfer Segment
            self.env['hr.payslip.segment'].create({
                'payslip_id': self.id,
                'name': _("Pre-Transfer: %s (%s ~ %s)") % (old_branch.name if old_branch else 'HQ', start_dt, trans_date - relativedelta(days=1)),
                'segment_type': 'pre_transfer',
                'date_start': start_dt,
                'date_end': trans_date - relativedelta(days=1),
                'days_count': pre_days,
                'total_period_days': total_days,
                'basic_salary': base_wage,
                'transport_allowance': trans_alw,
                'housing_allowance': house_alw,
                'hardship_percentage': old_hardship,
            })

            # Post-Transfer Segment
            self.env['hr.payslip.segment'].create({
                'payslip_id': self.id,
                'name': _("Post-Transfer: %s (%s ~ %s)") % (new_branch.name if new_branch else 'Branch', trans_date, end_dt),
                'segment_type': 'post_transfer',
                'date_start': trans_date,
                'date_end': end_dt,
                'days_count': post_days,
                'total_period_days': total_days,
                'basic_salary': base_wage,
                'transport_allowance': trans_alw,
                'housing_allowance': house_alw,
                'hardship_percentage': new_hardship,
            })
            return

        # Scenario 3: Standard Full Period Single Segment
        self.env['hr.payslip.segment'].create({
            'payslip_id': self.id,
            'name': _("Standard Period (%s ~ %s)") % (start_dt, end_dt),
            'segment_type': 'standard',
            'date_start': start_dt,
            'date_end': end_dt,
            'days_count': 30,
            'total_period_days': 30,
            'basic_salary': base_wage,
            'transport_allowance': trans_alw,
            'housing_allowance': house_alw,
            'hardship_percentage': self._get_location_hardship_rate(emp.department_id),
        })

    def _get_location_hardship_rate(self, department):
        """Lookup hardship percentage for a given branch or department."""
        if not department:
            return 0.0
        code = getattr(department, 'code', '') or getattr(department, 'name', '')
        rate_rec = self.env['hr.hardship.allowance.rate'].search([
            ('code', '=', code), ('active', '=', True)
        ], limit=1)
        if rate_rec:
            return rate_rec.rate_percentage
        return 0.0

    # ─────────────────────────────────────────────────────────────────────────
    # ERP INTEGRATION PAYLOAD HOOKS (ATTENDANCE, DISCIPLINE, ACTING, RETRO)
    # ─────────────────────────────────────────────────────────────────────────
    def get_hardship_allowance_amount(self):
        """Calculate hardship allowance."""
        self.ensure_one()
        if self.segment_ids:
            return sum(s.prorated_hardship_allowance for s in self.segment_ids)
        base = getattr(self.contract_id, 'wage', 0.0) or getattr(self.employee_id, 'basic_salary', 0.0)
        rate = self._get_location_hardship_rate(self.employee_id.department_id)
        return round((base * rate) / 100.0, 2)

    def get_acting_allowance_amount(self):
        """FR-PAY-026, 027, 028: Ingest managerial acting assignment."""
        self.ensure_one()
        ActingModel = self.env.get('hr.acting.assignment')
        if not ActingModel:
            return getattr(self.contract_id, 'acting_allowance', 0.0) or 0.0
        
        assign = ActingModel.search([
            ('employee_id', '=', self.employee_id.id),
            ('state', 'in', ['approved', 'capped']),
            ('start_date', '<=', self.date_to),
        ], order='start_date desc', limit=1)

        if assign:
            return assign.get_monthly_payout_amount(self.date_to)
        return getattr(self.contract_id, 'acting_allowance', 0.0) or 0.0

    def get_approved_overtime_amount(self):
        """Ingest approved overtime from attendance.payroll.payload."""
        self.ensure_one()
        PayloadModel = self.env.get('attendance.payroll.payload')
        total_ot_amt = 0.0
        base_wage = getattr(self.contract_id, 'wage', 0.0) or getattr(self.employee_id, 'basic_salary', 0.0) or 0.0
        hourly_rate = base_wage / (30.0 * 8.0) if base_wage > 0 else 0.0

        if PayloadModel:
            payloads = PayloadModel.search([
                ('employee_id', '=', self.employee_id.id),
                ('payload_type', '=', 'overtime'),
                ('state', 'in', ['pending', 'transferred']),
                ('effective_date', '>=', self.date_from),
                ('effective_date', '<=', self.date_to),
            ])
            for p in payloads:
                # Ethiopian standard overtime rate factor: 1.5x regular hourly
                total_ot_amt += (p.hours * hourly_rate * 1.5)
                p.write({'state': 'transferred', 'payslip_reference': self.number or self.name})
        
        return round(total_ot_amt, 2)

    def get_unauthorized_absence_deduction(self):
        """Ingest unauthorized absence deductions from attendance.payroll.payload."""
        self.ensure_one()
        PayloadModel = self.env.get('attendance.payroll.payload')
        total_abs_ded = 0.0
        base_wage = getattr(self.contract_id, 'wage', 0.0) or getattr(self.employee_id, 'basic_salary', 0.0) or 0.0
        daily_rate = base_wage / 30.0 if base_wage > 0 else 0.0

        if PayloadModel:
            payloads = PayloadModel.search([
                ('employee_id', '=', self.employee_id.id),
                ('payload_type', '=', 'unauthorized_absence'),
                ('state', 'in', ['pending', 'transferred']),
                ('effective_date', '>=', self.date_from),
                ('effective_date', '<=', self.date_to),
            ])
            for p in payloads:
                # Deduct based on daily hours / 8
                days_absent = (p.hours or 8.0) / 8.0
                total_abs_ded += (days_absent * daily_rate)
                p.write({'state': 'transferred', 'payslip_reference': self.number or self.name})

        return round(total_abs_ded, 2)

    def get_disciplinary_penalties_amount(self):
        """FR-PAY-023, 024, 025: Ingest penalties from discipline.payroll.penalty."""
        self.ensure_one()
        PenaltyModel = self.env.get('discipline.payroll.penalty')
        total_penalty = 0.0
        if PenaltyModel:
            penalties = PenaltyModel.search([
                ('employee_id', '=', self.employee_id.id),
                ('state', 'in', ['pending', 'transferred']),
                ('effective_date', '>=', self.date_from),
                ('effective_date', '<=', self.date_to),
            ])
            for pen in penalties:
                total_penalty += pen.calculated_amount
                pen.write({'state': 'transferred', 'payslip_reference': self.number or self.name})

        return round(total_penalty, 2)

    def get_retroactive_arrears_amount(self):
        """FR-PAY-029: Ingest approved retroactive arrears."""
        self.ensure_one()
        RetroModel = self.env.get('hr.payroll.retroactive')
        if not RetroModel:
            return 0.0
        retros = RetroModel.search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'approved'),
            ('total_arrears', '>', 0)
        ])
        total = sum(r.total_arrears for r in retros)
        for r in retros:
            r.write({'state': 'injected', 'target_payslip_id': self.id})
        return round(total, 2)

    def get_retroactive_recovery_amount(self):
        """FR-PAY-029: Ingest approved retroactive recoveries."""
        self.ensure_one()
        RetroModel = self.env.get('hr.payroll.retroactive')
        if not RetroModel:
            return 0.0
        retros = RetroModel.search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'approved'),
            ('total_recoveries', '>', 0)
        ])
        total = sum(r.total_recoveries for r in retros)
        for r in retros:
            r.write({'state': 'injected', 'target_payslip_id': self.id})
        return round(total, 2)

    # ─────────────────────────────────────────────────────────────────────────
    # CORE CALCULATION ENGINE & CONFLICT RESOLUTION MATRIX (FR-PAY-033)
    # ─────────────────────────────────────────────────────────────────────────
    def compute_sheet(self):
        """
        Executes complete payroll calculation for this payslip.
        Applies Priority Resolution Matrix, generates dynamic segments, computes salary rules,
        populates computed monetary summary fields, and runs exception scanner.
        """
        for payslip in self:
            if payslip.state in ['done', 'paid']:
                raise UserError(_("Cannot recompute finalized or paid payslip %s.") % payslip.number)

            # Clean previous lines
            payslip.line_ids.unlink()

            # 1. Generate Sub-Period Proration Segments
            payslip._generate_proration_segments()

            # 2. Setup Evaluation Context
            rules_dict = {}
            categories_dict = {}
            inputs_dict = {inp.code: inp.amount for inp in payslip.input_line_ids}

            localdict = {
                'payslip': payslip,
                'employee': payslip.employee_id,
                'contract': payslip.contract_id,
                'rules': BrowsableObject(self.env.cr, self.env.uid, self.env.user, rules_dict),
                'categories': BrowsableObject(self.env.cr, self.env.uid, self.env.user, categories_dict),
                'inputs': inputs_dict,
                'segments': payslip.segment_ids,
            }

            # 3. Retrieve all active rules ordered by sequence
            rules = payslip.struct_id.get_all_rules()

            lines_to_create = []
            for rule in rules:
                if not rule._satisfies_condition(localdict):
                    continue

                amount, qty, rate = rule._compute_rule(localdict)
                total = round((qty * amount * rate) / 100.0, 2)

                # Store in execution context
                rule_res = RuleResult(rule.code, total, amount, qty, rate)
                rules_dict[rule.code] = rule_res
                localdict['rules'] = BrowsableObject(self.env.cr, self.env.uid, self.env.user, rules_dict)

                # Accumulate category totals
                cat_code = rule.category_id.code
                categories_dict[cat_code] = categories_dict.get(cat_code, 0.0) + total
                localdict['categories'] = BrowsableObject(self.env.cr, self.env.uid, self.env.user, categories_dict)

                lines_to_create.append({
                    'slip_id': payslip.id,
                    'salary_rule_id': rule.id,
                    'name': rule.name,
                    'code': rule.code,
                    'sequence': rule.sequence,
                    'appears_on_payslip': rule.appears_on_payslip,
                    'amount': amount,
                    'quantity': qty,
                    'rate': rate,
                    'total': total,
                })

            self.env['hr.payslip.line'].create(lines_to_create)

            # 4. Populate Stored Summary Totals
            payslip.basic_wage = rules_dict.get('BASIC', RuleResult('BASIC', 0, 0, 0, 0)).total
            payslip.gross_wage = categories_dict.get('GROSS', 0.0)
            payslip.net_wage = rules_dict.get('NET', RuleResult('NET', 0, 0, 0, 0)).total
            payslip.income_tax = rules_dict.get('INCOME_TAX', RuleResult('INCOME_TAX', 0, 0, 0, 0)).total
            payslip.pension_ee = rules_dict.get('PENSION_EE', RuleResult('PENSION_EE', 0, 0, 0, 0)).total
            payslip.pension_er = rules_dict.get('PENSION_ER', RuleResult('PENSION_ER', 0, 0, 0, 0)).total
            
            payslip.hardship_wage = rules_dict.get('HARDSHIP', RuleResult('HARDSHIP', 0, 0, 0, 0)).total
            payslip.acting_wage = rules_dict.get('ACTING_ALW', RuleResult('ACTING_ALW', 0, 0, 0, 0)).total
            payslip.discipline_deductions = rules_dict.get('DISC_PEN', RuleResult('DISC_PEN', 0, 0, 0, 0)).total
            payslip.absence_deductions = rules_dict.get('ABS_DED', RuleResult('ABS_DED', 0, 0, 0, 0)).total
            payslip.retroactive_arrears = rules_dict.get('RETRO_ARREARS', RuleResult('RETRO_ARREARS', 0, 0, 0, 0)).total
            payslip.retroactive_recoveries = rules_dict.get('RETRO_RECOVER', RuleResult('RETRO_RECOVER', 0, 0, 0, 0)).total

            # 5. Execute Pre-Flight Exception Scanner (FR-PAY-036)
            self.env['hr.payroll.exception'].scan_payslip_for_exceptions(payslip)

        return True

    # ─────────────────────────────────────────────────────────────────────────
    # WORKFLOW STATE ACTIONS & SECURITY GATES
    # ─────────────────────────────────────────────────────────────────────────
    def action_payslip_verify(self):
        """Submit for Senior Controller Verification."""
        for slip in self:
            if not slip.line_ids:
                slip.compute_sheet()
            slip.write({'state': 'verify'})

    def action_payslip_done(self):
        """Final Approval & Commitment (Division Manager)."""
        for slip in self:
            if slip.has_critical_exceptions:
                raise UserError(_("Cannot finalize payslip %s: Critical un-resolved exceptions detected. Review Exception tab.") % slip.number)
            
            # Mark disciplinary penalties as deducted
            PenaltyModel = self.env.get('discipline.payroll.penalty')
            if PenaltyModel:
                penalties = PenaltyModel.search([
                    ('employee_id', '=', slip.employee_id.id),
                    ('state', '=', 'transferred'),
                    ('effective_date', '>=', slip.date_from),
                    ('effective_date', '<=', slip.date_to),
                ])
                for p in penalties:
                    p.write({'state': 'deducted', 'payslip_reference': slip.number})

            # Mark attendance payloads as processed
            PayloadModel = self.env.get('attendance.payroll.payload')
            if PayloadModel:
                payloads = PayloadModel.search([
                    ('employee_id', '=', slip.employee_id.id),
                    ('state', '=', 'transferred'),
                    ('effective_date', '>=', slip.date_from),
                    ('effective_date', '<=', slip.date_to),
                ])
                for p in payloads:
                    p.write({'state': 'processed', 'payslip_reference': slip.number})

            slip.write({'state': 'done'})
            self.env['hr.payroll.audit.log'].log_event(
                event_type='payslip_computed',
                description=f"Payslip {slip.number} finalized. Net Wage: ETB {slip.net_wage:.2f}",
                employee=slip.employee_id,
                approver=self.env.user,
                new_val=slip.net_wage,
                model='hr.payslip',
                res_id=slip.id
            )

    def action_payslip_cancel(self):
        """Void/cancel payslip."""
        for slip in self:
            slip.write({'state': 'cancel'})

    def action_payslip_draft(self):
        """Reset to draft."""
        for slip in self:
            slip.write({'state': 'draft'})

    @api.model
    def _cron_sync_pending_erp_payloads(self):
        """Periodic background sync from Attendance and Discipline models."""
        _logger.info("Executing periodic ERP payload sync for active payroll cycles.")
