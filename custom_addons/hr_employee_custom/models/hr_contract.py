

import threading
import itertools
import pytz

from collections import defaultdict
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
from odoo.fields import Domain

import logging
_logger = logging.getLogger(__name__)


class HrPayrollStructureType(models.Model):
    """Extend Salary Structure Type (base model is in hr module)."""
    _inherit = 'hr.payroll.structure.type'


class HrContract(models.Model):
    """
    Extends hr.version (Odoo 19's versioned employee contract model) with
    organisation-specific fields: contract state workflow, notice period,
    probation tracking, allowances/deductions, bank accounts, and work-entry
    generation helpers migrated from the legacy Odoo 14 hr.contract.

    Field-name mapping from the old standalone model:
        date_start  → contract_date_start   (on hr.version)
        date_end    → contract_date_end      (on hr.version)
    All other fields that exist on hr.version are inherited directly.
    Custom fields (state, allowances, etc.) are added here.
    """
    _inherit = 'hr.version'

    # ─────────────────────────────────────────────────────────────────────────
    # SEQUENCE / NAME  (hr.version already has 'name'; we set a default)
    # ─────────────────────────────────────────────────────────────────────────
    # 'name' is inherited from hr.version.  We override its default so that
    # new records created via this extension get an auto-sequence reference.
    name = fields.Char(default='New', copy=False)

    # ─────────────────────────────────────────────────────────────────────────
    # CLASSIFICATION  (fields not present on hr.version)
    # ─────────────────────────────────────────────────────────────────────────
    job_category = fields.Selection([
        ('managerial', 'Managerial'),
        ('non_managerial', 'Non Managerial'),
    ], string='Job Category', tracking=True)

    employee_category = fields.Many2one(
        'hr.contract.type',
        string='Contract Employee Category',
        tracking=True,
        help="Employee category linked to the contract type.",
    )

    # hr.version already has contract_type_id (Many2one → hr.contract.type).
    # We expose it via an alias so existing code using type_id still works.
    type_id = fields.Many2one(
        related='contract_type_id',
        string='Contract Type (alias)',
        readonly=False,
        store=False,
    )

    grade_id = fields.Many2one(
        'employee.grade',
        string='Employee Grade',
        related='employee_id.grade_id',
        readonly=True,
        store=False,
        help="Grade of the employee (edit from the Employee record).",
    )

    job_description = fields.Text(
        string='Job Description',
        help="Describe the job role and responsibilities covered by this contract.",
    )

    operating_unit_id = fields.Many2one(
        'operating.unit',
        string='Operating Unit',
        tracking=True,
    )


    visa_expire = fields.Date(
        string='Visa Expiration Date',
        related='employee_id.visa_expire',
        store=True,
        readonly=True,
        groups='hr.group_hr_user',
    )



    first_contract_date = fields.Date(
        related='employee_id.first_contract_date',
        string='First Contract Date',
    )

    # ─────────────────────────────────────────────────────────────────────────
    # NOTICE PERIOD  (custom — not on hr.version)
    # ─────────────────────────────────────────────────────────────────────────
    notice_period = fields.Integer(string='Notice Period (Days)', default=0)

    # ─────────────────────────────────────────────────────────────────────────
    # PROBATION  (custom — not on hr.version)
    # ─────────────────────────────────────────────────────────────────────────
    probation_period = fields.Integer(
        string='Probation Period (Months)', default=0,
        help='Probation duration in months.',
    )
    probation_start_date = fields.Date(string='Probation Start Date')
    probation_end_date = fields.Date(
        string='Probation End Date',
        compute='_compute_probation_end_date',
        store=True,
        readonly=False,
    )
    probation_notice_sent = fields.Boolean(
        string='Probation Notice Sent',
        default=False,
        copy=False,
        help="Tracks if notice of upcoming probation end has already been dispatched.",
    )

    # ─────────────────────────────────────────────────────────────────────────
    # WAGE  (hr.version has wage; add custom companion fields)
    # ─────────────────────────────────────────────────────────────────────────
    wage_type = fields.Selection([
        ('monthly', 'Monthly Fixed'),
        ('hourly',  'Hourly'),
    ], string='Wage Type', default='monthly')
    base_salary = fields.Float(string='Base Salary', digits=(16, 2))
    factor      = fields.Float(string='Factor',       digits=(16, 3), default=1.0)

    # ─────────────────────────────────────────────────────────────────────────
    # BANK / FINANCIAL ACCOUNTS  (custom)
    # ─────────────────────────────────────────────────────────────────────────
    employee_tin       = fields.Char(string='Employee TIN')
    salary_account     = fields.Char(string='Salary Account')
    od_account         = fields.Char(string='OD Account')
    pf_account         = fields.Char(string='PF Account')
    asbeza_account     = fields.Char(string='ASBEZA Account')
    indemnity_account  = fields.Char(string='Indemnity Account')

    indemnity_account_balance = fields.Float(
        string='Indemnity Account Balance', digits=(16, 2))
    pf_contribution_balance   = fields.Float(
        string='PF Contribution Balance',   digits=(16, 2))
    cost_sharing_balance      = fields.Float(
        string='Cost Sharing Balance',       digits=(16, 2))

    # ─────────────────────────────────────────────────────────────────────────
    # BOOLEAN FLAGS  (custom)
    # ─────────────────────────────────────────────────────────────────────────
    member_of_labour_union   = fields.Boolean(string='Member of Labour Union',   default=False)
    company_car_provided     = fields.Boolean(string='Company Car Provided',     default=False)
    cash_indemnity_applicable = fields.Boolean(string='Cash Indemnity Applicable', default=False)
    wrapping_applicable      = fields.Boolean(string='Wrapping Applicable',      default=False)
    from_transfer            = fields.Boolean(string='Transferred',              default=False)

    # ─────────────────────────────────────────────────────────────────────────
    # PMS / PERFORMANCE  (custom)
    # ─────────────────────────────────────────────────────────────────────────
    pms_score       = fields.Float(string='PMS Score',       digits=(16, 2))
    pms_rank        = fields.Float(string='PMS Rank',        digits=(16, 2))
    penalty_amount  = fields.Float(string='Penalty Amount',  digits=(16, 2))
    allowance_amount = fields.Float(string='Allowance Amount', digits=(16, 2))

    # ─────────────────────────────────────────────────────────────────────────
    # MONTHLY ALLOWANCES  (custom)
    # ─────────────────────────────────────────────────────────────────────────
    cost_sharing                = fields.Float(string='Cost Sharing',                digits=(16, 2))
    od_deduction                = fields.Float(string='OD Deduction',                digits=(16, 2))
    asbeza_deduction            = fields.Float(string='ASBEZA Deduction',            digits=(16, 2))
    labour_union_contribution   = fields.Float(string='Labour Union Contribution',   digits=(16, 2))
    other_allowance             = fields.Float(string='Other Allowance',             digits=(16, 2))
    other_deductions            = fields.Float(string='Other Deductions',            digits=(16, 2))
    other_advances              = fields.Float(string='Other Advances',              digits=(16, 2))
    wellness_allowance          = fields.Float(string='Wellness Allowance',          digits=(16, 2))
    representation_allowance    = fields.Float(string='Representation Allowance',    digits=(16, 2))
    cash_indemnity              = fields.Float(string='Cash Indemnity',              digits=(16, 2))
    cash_indemnity_bank         = fields.Float(string='Cash Indemnity Bank',         digits=(16, 2))
    acting_allowance            = fields.Float(string='Acting Allowance',            digits=(16, 2))
    fuel_allowance              = fields.Float(string='Fuel Allowance',              digits=(16, 2))
    transportation_allowance    = fields.Float(string='Transportation Allowance',    digits=(16, 2))
    hardship_allowance          = fields.Float(string='Hardship Allowance',          digits=(16, 2))
    wrapping_allowance          = fields.Float(string='Wrapping Allowance',          digits=(16, 2))
    mobile_allowance            = fields.Float(string='Mobile Allowance',            digits=(16, 2))
    special_car_allowance       = fields.Float(string='Special Car Allowance',       digits=(16, 2))
    housing_allowance           = fields.Float(string='Housing Allowance',           digits=(16, 2))
    overtime                    = fields.Float(string='Overtime Allowance',          digits=(16, 2))
    vacation_allowance          = fields.Float(string='Vacation Allowance',          digits=(16, 2))
    disturbance_allowance       = fields.Float(string='Disturbance Allowance',       digits=(16, 2))

    # ─────────────────────────────────────────────────────────────────────────
    # NOTES  (hr.version has additional_note; add plain text notes field)
    # ─────────────────────────────────────────────────────────────────────────
    notes = fields.Text('Notes')

    # ─────────────────────────────────────────────────────────────────────────
    # STATE WORKFLOW  (custom — hr.version has no state)
    # ─────────────────────────────────────────────────────────────────────────
    state = fields.Selection([
        ('draft',     'New'),
        ('probation', 'Probation'),
        ('open',      'Running'),
        ('close',     'Expired'),
        ('cancel',    'Cancelled'),
    ], string='Status',
       group_expand='_group_expand_states',
       copy=False,
       tracking=True,
       help='Status of the contract',
       default='draft',
    )

    kanban_state = fields.Selection([
        ('normal',  'Grey'),
        ('done',    'Green'),
        ('blocked', 'Red'),
    ], string='Kanban State', default='normal', tracking=True, copy=False)

    # ─────────────────────────────────────────────────────────────────────────
    # WORK ENTRY tracking fields  (custom)
    # ─────────────────────────────────────────────────────────────────────────
    date_generated_from = fields.Datetime(
        string='Generated From', readonly=True, required=True,
        default=lambda self: datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0),
        copy=False,
    )
    date_generated_to = fields.Datetime(
        string='Generated To', readonly=True, required=True,
        default=lambda self: datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0),
        copy=False,
    )
    last_generation_date = fields.Date(string='Last Generation Date', readonly=True)
    work_entry_source = fields.Selection(
        [('calendar', 'Working Schedule')],
        required=True, default='calendar',
        help='Defines the source for work entries generation.',
    )

    # ─────────────────────────────────────────────────────────────────────────
    # COMPUTE METHODS
    # ─────────────────────────────────────────────────────────────────────────

    def _group_expand_states(self, states, domain):
        return [key for key, val in type(self).state.selection]

    def _calculate_working_days_end_date(self, start_date, target_working_days=60):
        """Calculate end date by adding target_working_days, excluding Sundays and public holidays."""
        if not start_date or target_working_days <= 0:
            return start_date

        calendar = (
            getattr(self, 'resource_calendar_id', False)
            or (self.employee_id.resource_calendar_id if self.employee_id else False)
            or self.env.company.resource_calendar_id
            or False
        )

        leave_domain = [('resource_id', '=', False)]
        if calendar:
            leave_domain.append(('calendar_id', 'in', [False, calendar.id]))

        holiday_leaves = self.env['resource.calendar.leaves'].search(leave_domain)
        holiday_ranges = []
        for h in holiday_leaves:
            if h.date_from and h.date_to:
                holiday_ranges.append((h.date_from.date(), h.date_to.date()))

        curr_date = start_date
        counted_days = 0
        max_days_limit = 500
        iterations = 0

        while counted_days < target_working_days and iterations < max_days_limit:
            iterations += 1
            # Working day: exclude Sundays (weekday 6)
            is_workday = curr_date.weekday() != 6
            is_holiday = any(start_d <= curr_date <= end_d for start_d, end_d in holiday_ranges)

            if is_workday and not is_holiday:
                counted_days += 1

            if counted_days < target_working_days:
                curr_date += timedelta(days=1)

        return curr_date

    @api.depends('probation_start_date', 'probation_period', 'employee_id', 'employee_id.grade_id', 'job_categoryy')
    def _compute_probation_end_date(self):
        for rec in self:
            if not rec.probation_start_date:
                rec.probation_end_date = False
                continue

            grade = getattr(rec, 'job_grade', False) or (rec.employee_id.grade_id if rec.employee_id else False)
            cat_name = (grade.category.category_name or '').strip().lower() if (grade and grade.category) else ''
            is_managerial = 'manager' in cat_name or (getattr(rec, 'job_categoryy', '') == 'Managerial')
            default_days = 75 if is_managerial else 60
            target_days = rec.probation_period or default_days

            rec.probation_end_date = rec._calculate_working_days_end_date(rec.probation_start_date, target_days)

    # ─────────────────────────────────────────────────────────────────────────
    # ONCHANGE
    # ─────────────────────────────────────────────────────────────────────────

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id and self.employee_id.grade_id:
            if hasattr(self, 'job_grade'):
                self.job_grade = self.employee_id.grade_id
            grade = self.employee_id.grade_id
            cat_name = (grade.category.category_name or '').strip().lower() if (grade and grade.category) else ''
            is_managerial = 'manager' in cat_name
            self.job_categoryy = 'Managerial' if is_managerial else ('Non Managerial' if cat_name else False)
            default_days = 75 if is_managerial else 60
            if not self.probation_period or self.probation_period in (60, 75):
                self.probation_period = default_days
            if self.probation_start_date:
                self.probation_end_date = self._calculate_working_days_end_date(self.probation_start_date, self.probation_period or default_days)

    @api.onchange('contract_date_start')
    def _onchange_contract_date_start(self):
        """Auto-fill probation start date from contract start date."""
        if self.contract_date_start and not self.probation_start_date:
            self.probation_start_date = self.contract_date_start
        grade = getattr(self, 'job_grade', False) or (self.employee_id.grade_id if self.employee_id else False)
        cat_name = (grade.category.category_name or '').strip().lower() if (grade and grade.category) else ''
        is_managerial = 'manager' in cat_name or (getattr(self, 'job_categoryy', '') == 'Managerial')
        default_days = 75 if is_managerial else 60
        if not self.probation_period or self.probation_period in (60, 75):
            self.probation_period = default_days
        if self.probation_start_date:
            self.probation_end_date = self._calculate_working_days_end_date(self.probation_start_date, self.probation_period or default_days)

    @api.onchange('probation_start_date', 'probation_period')
    def _onchange_probation_dates(self):
        grade = getattr(self, 'job_grade', False) or (self.employee_id.grade_id if self.employee_id else False)
        cat_name = (grade.category.category_name or '').strip().lower() if (grade and grade.category) else ''
        is_managerial = 'manager' in cat_name or (getattr(self, 'job_categoryy', '') == 'Managerial')
        default_days = 75 if is_managerial else 60
        if not self.probation_period:
            self.probation_period = default_days
        if self.probation_start_date:
            self.probation_end_date = self._calculate_working_days_end_date(self.probation_start_date, self.probation_period or default_days)

    @api.onchange('operating_unit_id')
    def _onchange_operating_unit_id_filter_job(self):
        if self.operating_unit_id:
            lines = self.env['operating.unit.job.position'].sudo().search([
                ('operating_unit_id', '=', self.operating_unit_id.id),
                ('active', '=', True)
            ])
            job_ids = lines.mapped('job_position_id').filtered(lambda j: j.active).ids
            if self.job_id and self.job_id.id not in job_ids:
                self.job_id = False
            return {'domain': {
                'job_id': [('operating_unit_job_ids.operating_unit_id', '=', self.operating_unit_id.id)]
            }}
        return {'domain': {'job_id': []}}

    @api.onchange('structure_type_id')
    def _onchange_structure_type_id(self):
        if self.structure_type_id.default_resource_calendar_id:
            self.resource_calendar_id = (
                self.structure_type_id.default_resource_calendar_id)

    # ─────────────────────────────────────────────────────────────────────────
    # CONSTRAINTS
    # ─────────────────────────────────────────────────────────────────────────

    @api.constrains('employee_id', 'state', 'kanban_state',
                    'contract_date_start', 'contract_date_end')
    def _check_current_contract(self):
        """Two active contracts cannot overlap for the same employee."""
        for contract in self.filtered(
            lambda c: (
                c.state not in ['draft', 'cancel']
                or (c.state == 'draft' and c.kanban_state == 'done')
            ) and c.employee_id
        ):
            domain = [
                ('id', '!=', contract.id),
                ('employee_id', '=', contract.employee_id.id),
                ('company_id', '=', contract.company_id.id),
                '|',
                    ('state', 'in', ['open', 'probation', 'close']),
                    '&',
                        ('state', '=', 'draft'),
                        ('kanban_state', '=', 'done'),
            ]
            if not contract.contract_date_end:
                end_domain = [
                    '|',
                    ('contract_date_end', '>=', contract.contract_date_start),
                    ('contract_date_end', '=', False),
                ]
                full_domain = Domain(domain) & Domain(end_domain)
            else:
                start_domain = [('contract_date_start', '<=', contract.contract_date_end)]
                end_domain = [
                    '|',
                    ('contract_date_end', '>', contract.contract_date_start),
                    ('contract_date_end', '=', False),
                ]
                full_domain = Domain(domain) & Domain(start_domain) & Domain(end_domain)
            if self.search_count(full_domain):
                raise ValidationError(_(
                    'An employee can only have one active contract at a time. '
                    '(Excluding Draft and Cancelled contracts)'
                ))

    # ─────────────────────────────────────────────────────────────────────────
    # CREATE / WRITE
    # ─────────────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('hr.contract') or 'New'
                )
            if 'job_grade' in self._fields and not vals.get('job_grade'):
                grade = False
                if vals.get('employee_id'):
                    emp = self.env['hr.employee'].browse(vals['employee_id'])
                    grade = emp.job_grade or getattr(emp, 'grade_id', False) or getattr(emp, 'grade', False)
                if not grade and self.env.context.get('default_job_grade'):
                    grade = self.env['employee.grade'].browse(self.env.context['default_job_grade'])
                if not grade:
                    grade = self.env['employee.grade'].search([], order='id asc', limit=1)
                if grade:
                    vals['job_grade'] = grade.id if hasattr(grade, 'id') else grade

            # Auto-fill probation values based on job category if not supplied
            grade_obj = False
            if vals.get('job_grade'):
                grade_obj = self.env['employee.grade'].browse(vals['job_grade'])
            elif vals.get('employee_id'):
                emp = self.env['hr.employee'].browse(vals['employee_id'])
                grade_obj = getattr(emp, 'grade_id', False) or getattr(emp, 'job_grade', False)
            cat_name = (grade_obj.category.category_name or '').strip().lower() if (grade_obj and grade_obj.category) else ''
            is_managerial = 'manager' in cat_name
            default_days = 75 if is_managerial else 60
            if not vals.get('probation_period'):
                vals['probation_period'] = default_days
            if vals.get('contract_date_start') and not vals.get('probation_start_date'):
                vals['probation_start_date'] = vals['contract_date_start']
        records = super().create(vals_list)
        for rec in records:
            if rec.state == 'open':
                rec._assign_open_contract()
        open_records = records.filtered(
            lambda c: c.state in ('open', 'probation')
            or (c.state == 'draft' and c.kanban_state == 'done')
        )
        for rec in open_records.filtered(
            lambda c: c.employee_id and c.resource_calendar_id
        ):
            rec.employee_id.resource_calendar_id = rec.resource_calendar_id
        return records

    def write(self, vals):
        if 'probation_end_date' in vals or 'notice_period' in vals:
            if 'probation_notice_sent' not in vals:
                vals['probation_notice_sent'] = False
        res = super().write(vals)
        if any(f in vals for f in ('notice_period', 'probation_end_date', 'probation_start_date')):
            today = date.today()
            for rec in self:
                if rec.probation_end_date and not rec.probation_notice_sent and rec.employee_id:
                    notice_days = rec.notice_period if rec.notice_period and rec.notice_period > 0 else 5
                    target_date = rec.probation_end_date - timedelta(days=notice_days)
                    if target_date <= today <= rec.probation_end_date:
                        rec._send_probation_ending_notification(notice_days)
        if vals.get('state') == 'open':
            self._assign_open_contract()
        if vals.get('state') == 'close':
            for rec in self.filtered(lambda c: not c.contract_date_end):
                rec.contract_date_end = max(date.today(), rec.contract_date_start or date.today())
        calendar = vals.get('resource_calendar_id')
        if calendar and not self.env.context.get('skip_calendar_sync'):
            employees = self.filtered(
                lambda c: c.state in ('open', 'probation')
                or (c.state == 'draft' and c.kanban_state == 'done')
            ).mapped('employee_id').filtered(lambda e: e.resource_calendar_id.id != calendar)
            if employees:
                employees.with_context(skip_calendar_sync=True).write({'resource_calendar_id': calendar})

        if 'state' in vals and 'kanban_state' not in vals:
            super().write({'kanban_state': 'normal'})
        if vals.get('contract_date_end') or vals.get('contract_date_start'):
            self.sudo()._remove_work_entries()
        if vals.get('state') in ['draft', 'cancel']:
            self._cancel_work_entries()
        return res

    # ─────────────────────────────────────────────────────────────────────────
    # CONTRACT HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _assign_open_contract(self):
        for rec in self:
            rec.employee_id.sudo().write({'contract_id': rec.id})

    # ─────────────────────────────────────────────────────────────────────────
    # STATE ACTION BUTTONS
    # ─────────────────────────────────────────────────────────────────────────

    def action_start_probation(self):
        """New → Probation"""
        self.write({'state': 'probation'})

    def action_start_running(self):
        """Probation → Running — requires probation_end_date to have passed."""
        today = date.today()
        for rec in self:
            if rec.state == 'probation':
                if not rec.probation_end_date:
                    raise UserError(_(
                        'Cannot approve contract "%s": Probation End Date is not set.',
                        rec.name
                    ))
                if rec.probation_end_date > today:
                    raise UserError(_(
                        'Cannot approve contract "%s": Probation period ends on %s. '
                        'You can only approve after that date.',
                        rec.name,
                        rec.probation_end_date.strftime('%d/%m/%Y'),
                    ))
            rec.write({'state': 'open'})
            rec._assign_open_contract()

    def action_expire(self):
        """Running → Expired"""
        if not self.env.user.has_group('hr.group_hr_manager') and not self.env.su:
            raise UserError(_('Only employees with Administrator access in Employee Master can expire contracts.'))
        for rec in self:
            vals = {'state': 'close'}
            if not rec.contract_date_end:
                vals['contract_date_end'] = date.today()
            rec.write(vals)

    def action_cancel(self):
        """Any → Cancelled"""
        if not self.env.user.has_group('hr.group_hr_manager') and not self.env.su:
            raise UserError(_('Only employees with Administrator access in Employee Master can cancel contracts.'))
        self.write({'state': 'cancel'})

    def action_reset_to_new(self):
        """Cancelled / Expired → New"""
        if not self.env.user.has_group('hr.group_hr_manager') and not self.env.su:
            raise UserError(_('Only employees with Administrator access in Employee Master can reset contracts.'))
        self.write({'state': 'draft'})

    # ─────────────────────────────────────────────────────────────────────────
    # CHATTER SUBTYPES
    # ─────────────────────────────────────────────────────────────────────────

    def _track_subtype(self, init_values):
        """Disable all tracking to prevent mail flood during upgrades."""
        return False

    def _message_track(self, fields_iter, initial_values_dict):
        return {}

    # ─────────────────────────────────────────────────────────────────────────
    # STATE UPDATE CRON
    # ─────────────────────────────────────────────────────────────────────────

    @api.model
    def update_state(self):
        """Daily cron: warn about expiring contracts and auto-close expired ones."""
        from_cron = 'from_cron' in self.env.context
        today = date.today()

        # Check and send upcoming probation ending notices
        self._cron_check_probation_notice()

        contracts_expiring = self.search([
            ('state', '=', 'open'),
            ('kanban_state', '!=', 'blocked'),
            '|',
            '&',
            ('contract_date_end', '<=', fields.Date.to_string(today + relativedelta(days=7))),
            ('contract_date_end', '>=', fields.Date.to_string(today + relativedelta(days=1))),
            '&',
            ('visa_expire', '<=', fields.Date.to_string(today + relativedelta(days=60))),
            ('visa_expire', '>=', fields.Date.to_string(today + relativedelta(days=1))),
        ])
        for rec in contracts_expiring:
            rec.activity_schedule(
                'mail.mail_activity_data_todo',
                rec.contract_date_end,
                _('The contract of %s is about to expire.', rec.employee_id.name),
                user_id=rec.hr_responsible_id.id or self.env.uid,
            )
        if contracts_expiring:
            contracts_expiring._safe_write_for_cron({'kanban_state': 'blocked'}, from_cron)

        contracts_to_close = self.search([
            ('state', '=', 'open'),
            '|',
            ('contract_date_end', '<=', fields.Date.to_string(today)),
            ('visa_expire', '<=', fields.Date.to_string(today)),
        ])
        if contracts_to_close:
            contracts_to_close._safe_write_for_cron({'state': 'close'}, from_cron)

        contracts_to_open = self.search([
            ('state', '=', 'draft'),
            ('kanban_state', '=', 'done'),
            ('contract_date_start', '<=', fields.Date.to_string(today)),
        ])
        if contracts_to_open:
            contracts_to_open._safe_write_for_cron({'state': 'open'}, from_cron)

        contracts_probation_done = self.search([
            ('state', '=', 'probation'),
            ('probation_end_date', '<=', fields.Date.to_string(today)),
        ])
        if contracts_probation_done:
            contracts_probation_done._safe_write_for_cron({'state': 'open'}, from_cron)

        for rec in self.search([
            ('contract_date_end', '=', False),
            ('state', '=', 'close'),
            ('employee_id', '!=', False),
        ]):
            next_rec = self.search([
                ('employee_id', '=', rec.employee_id.id),
                ('state', 'not in', ['cancel', 'new']),
                ('contract_date_start', '>', rec.contract_date_start),
            ], order='contract_date_start asc', limit=1)
            if next_rec:
                rec._safe_write_for_cron(
                    {'contract_date_end': next_rec.contract_date_start - relativedelta(days=1)},
                    from_cron,
                )
        return True

    @api.model
    def _cron_check_probation_notice(self):
        """Check all active or probation contracts approaching probation_end_date and send notification."""
        today = date.today()
        contracts = self.search([
            ('state', 'in', ['draft', 'probation', 'open']),
            ('probation_end_date', '!=', False),
            ('probation_notice_sent', '=', False),
            ('employee_id', '!=', False),
        ])
        for rec in contracts:
            notice_days = rec.notice_period if rec.notice_period and rec.notice_period > 0 else 5
            target_notify_date = rec.probation_end_date - timedelta(days=notice_days)
            if target_notify_date <= today <= rec.probation_end_date:
                rec._send_probation_ending_notification(notice_days)

    def _send_probation_ending_notification(self, notice_days=5):
        self.ensure_one()
        emp = self.employee_id
        if not emp or not self.probation_end_date:
            return

        today = date.today()
        days_remaining = (self.probation_end_date - today).days

        partners = self.env['res.partner']
        users = self.env['res.users']

        # 1. The Employee
        if emp.user_id:
            users |= emp.user_id
            if emp.user_id.partner_id:
                partners |= emp.user_id.partner_id
        if emp.work_contact_id:
            partners |= emp.work_contact_id

        # 2. Manager (parent_id)
        if emp.parent_id:
            if emp.parent_id.user_id:
                users |= emp.parent_id.user_id
                if emp.parent_id.user_id.partner_id:
                    partners |= emp.parent_id.user_id.partner_id
            if emp.parent_id.work_contact_id:
                partners |= emp.parent_id.work_contact_id

        # 3. Coach (coach_id)
        if emp.coach_id:
            if emp.coach_id.user_id:
                users |= emp.coach_id.user_id
                if emp.coach_id.user_id.partner_id:
                    partners |= emp.coach_id.user_id.partner_id
            if emp.coach_id.work_contact_id:
                partners |= emp.coach_id.work_contact_id

        # 4. Explicitly ensure employee 4561 (Mahlet Mulatu Libassie) is included if coach or manager or employee
        emp_4561 = self.env['hr.employee'].browse(4561)
        if emp_4561.exists():
            if emp.id == 4561 or (emp.coach_id and emp.coach_id.id == 4561) or (emp.parent_id and emp.parent_id.id == 4561):
                if emp_4561.user_id:
                    users |= emp_4561.user_id
                    if emp_4561.user_id.partner_id:
                        partners |= emp_4561.user_id.partner_id
                if emp_4561.work_contact_id:
                    partners |= emp_4561.work_contact_id

        # HR Responsible
        if self.hr_responsible_id:
            users |= self.hr_responsible_id
            if self.hr_responsible_id.partner_id:
                partners |= self.hr_responsible_id.partner_id

        job_title_str = getattr(emp, 'job_title', False) or (self.job_id.name if self.job_id else '')
        days_text = f"{days_remaining} day(s) remaining" if days_remaining >= 0 else "Ended"
        subject = _("Probation Period Ending Notice: %s", emp.name)
        body = _(
            "<p><strong>Probation Period Ending Notice</strong></p>"
            "<ul>"
            "<li><strong>Employee:</strong> %s</li>"
            "<li><strong>Job Title:</strong> %s</li>"
            "<li><strong>Probation End Date:</strong> %s (%s)</li>"
            "<li><strong>Notice Period:</strong> %s day(s)</li>"
            "</ul>"
            "<p>Please review and complete the employee's probation evaluation before the probation end date.</p>",
            emp.name,
            job_title_str,
            self.probation_end_date.strftime('%d/%m/%Y'),
            days_text,
            notice_days,
        )

        try:
            self.message_post(
                body=body,
                subject=subject,
                partner_ids=partners.ids,
                message_type='notification',
                subtype_xmlid='mail.mt_comment',
            )
        except Exception as e:
            _logger.warning("Failed to post probation notice chatter message: %s", e)

        # Schedule activity for Manager, Coach, and HR Responsible
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        for user in users:
            try:
                existing = self.env['mail.activity'].search([
                    ('res_model', '=', 'hr.version'),
                    ('res_id', '=', self.id),
                    ('user_id', '=', user.id),
                    ('summary', '=', 'Probation Period Ending Notice'),
                ], limit=1)
                if not existing:
                    self.activity_schedule(
                        activity_type_id=activity_type.id if activity_type else False,
                        date_deadline=self.probation_end_date,
                        summary=_("Probation Period Ending Notice"),
                        note=_(
                            "The probation period for %s will end on %s. "
                            "Please finalize and submit the probation evaluation."
                        ) % (emp.name, self.probation_end_date.strftime('%d/%m/%Y')),
                        user_id=user.id,
                    )
            except Exception as e:
                _logger.warning("Failed to schedule probation notice activity for user %s: %s", user.id, e)

        self.write({'probation_notice_sent': True})

    def _safe_write_for_cron(self, vals, from_cron=False):
        if from_cron:
            auto_commit = not getattr(threading.current_thread(), 'testing', False)
            for rec in self:
                try:
                    with self.env.cr.savepoint():
                        rec.write(vals)
                except ValidationError as e:
                    _logger.warning(e)
                else:
                    if auto_commit:
                        self.env.cr.commit()
        else:
            self.write(vals)

    # ─────────────────────────────────────────────────────────────────────────
    # WORK ENTRY METHODS
    # ─────────────────────────────────────────────────────────────────────────

    def _get_default_work_entry_type(self):
        return self.env.ref(
            'hr_work_entry.work_entry_type_attendance',
            raise_if_not_found=False,
        )

    def _get_leave_work_entry_type(self, leave):
        return leave.work_entry_type_id

    def _get_leave_work_entry_type_dates(self, leave, date_from, date_to, employee):
        return self._get_leave_work_entry_type(leave)

    def _get_more_vals_attendance_interval(self, interval):
        return []

    def _get_more_vals_leave_interval(self, interval, leaves):
        return []

    def _get_bypassing_work_entry_type_codes(self):
        return []

    def _get_leave_domain(self, start_dt, end_dt):
        return [
            ('time_type', '=', 'leave'),
            ('calendar_id', 'in', [False] + self.resource_calendar_id.ids),
            ('resource_id', 'in', [False] + self.employee_id.resource_id.ids),
            ('date_from', '<=', end_dt),
            ('date_to', '>=', start_dt),
            ('company_id', 'in', [False, self.company_id.id]),
        ]

    def _get_attendance_intervals(self, start_dt, end_dt):
        employees_by_calendar = defaultdict(lambda: self.env['hr.employee'])
        for rec in self:
            employees_by_calendar[rec.resource_calendar_id] |= rec.employee_id
        result = {}
        for calendar, employees in employees_by_calendar.items():
            result.update(calendar._attendance_intervals_batch(
                start_dt, end_dt,
                resources=employees.resource_id,
                tz=pytz.timezone(calendar.tz),
            ))
        return result

    def has_static_work_entries(self):
        self.ensure_one()
        return self.work_entry_source == 'calendar'

    def _remove_work_entries(self):
        """Remove work entries outside the contract period."""
        if 'hr.work.entry' not in self.env:
            return
        all_we_to_unlink = self.env['hr.work.entry']
        for rec in self:
            date_start = fields.Datetime.to_datetime(rec.contract_date_start)
            if rec.date_generated_from < date_start:
                we_to_remove = self.env['hr.work.entry'].search([
                    ('date_stop', '<=', date_start),
                    ('contract_id', '=', rec.id),
                ])
                if we_to_remove:
                    rec.date_generated_from = date_start
                    all_we_to_unlink |= we_to_remove
            if not rec.contract_date_end:
                continue
            date_end = datetime.combine(rec.contract_date_end, datetime.max.time())
            if rec.date_generated_to > date_end:
                we_to_remove = self.env['hr.work.entry'].search([
                    ('date_start', '>=', date_end),
                    ('contract_id', '=', rec.id),
                ])
                if we_to_remove:
                    rec.date_generated_to = date_end
                    all_we_to_unlink |= we_to_remove
        all_we_to_unlink.unlink()

    def _cancel_work_entries(self):
        if not self or 'hr.work.entry' not in self.env:
            return
        base_domain = Domain([('state', '!=', 'validated')])
        for rec in self:
            date_start = fields.Datetime.to_datetime(rec.contract_date_start)
            contract_domain = Domain([
                ('contract_id', '=', rec.id),
                ('date_start', '>=', date_start),
            ])
            if rec.contract_date_end:
                date_end = datetime.combine(rec.contract_date_end, datetime.max.time())
                contract_domain &= Domain([('date_stop', '<=', date_end)])
            base_domain &= contract_domain
        work_entries = self.env['hr.work.entry'].search(base_domain)
        if work_entries:
            work_entries.unlink()

    def _generate_work_entries(self, date_start, date_stop, force=False):
        """Generate work entries. Requires hr_work_entry module."""
        if 'hr.work.entry' not in self.env:
            raise UserError(_('Work Entries module (hr_work_entry) is not installed.'))
        self = self.with_context(tracking_disable=True)
        canceled = self.filtered(lambda c: c.state == 'cancel')
        if canceled:
            raise UserError(
                _('Generating work entries from cancelled contracts is not allowed.')
                + '\n%s' % ', '.join(canceled.mapped('name'))
            )
        date_start = fields.Datetime.to_datetime(date_start)
        date_stop = datetime.combine(
            fields.Datetime.to_datetime(date_stop), datetime.max.time())
        self.write({'last_generation_date': fields.Date.today()})

        intervals_to_generate = defaultdict(lambda: self.env['hr.version'])
        self.filtered(
            lambda c: c.date_generated_from == c.date_generated_to
        ).write({'date_generated_from': date_start, 'date_generated_to': date_start})

        for rec in self:
            c_start = fields.Datetime.to_datetime(rec.contract_date_start)
            c_stop  = datetime.combine(
                fields.Datetime.to_datetime(rec.contract_date_end or datetime.max.date()),
                datetime.max.time(),
            )
            if date_start > c_stop or date_stop < c_start:
                continue
            ds = max(date_start, c_start)
            de = min(date_stop,  c_stop)
            if force:
                intervals_to_generate[(ds, de)] |= rec
                continue
            is_static = rec.has_static_work_entries()
            lgf = min(rec.date_generated_from, c_stop)
            if lgf > ds:
                if is_static:
                    rec.date_generated_from = ds
                intervals_to_generate[(ds, lgf)] |= rec
            lgt = max(rec.date_generated_to, c_start)
            if lgt < de:
                if is_static:
                    rec.date_generated_to = de
                intervals_to_generate[(lgt, de)] |= rec

        vals_list = []
        for (df, dt_), contracts in intervals_to_generate.items():
            vals_list.extend(contracts._get_work_entries_values(df, dt_))
        if not vals_list:
            return self.env['hr.work.entry']
        return self.env['hr.work.entry'].create(vals_list)

    def _get_work_entries_values(self, date_start, date_stop):
        contract_vals = self._get_contract_work_entries_values(date_start, date_stop)
        mapped = defaultdict(lambda: ([], []))
        for x in contract_vals:
            mapped[x['contract_id']][0].append(x['date_start'])
            mapped[x['contract_id']][1].append(x['date_stop'])
        for rec in self:
            if contract_vals:
                ds_list = mapped[rec.id][0]
                if ds_list:
                    dsm = min(ds_list)
                    if dsm < rec.date_generated_from:
                        rec.date_generated_from = dsm
                de_list = mapped[rec.id][1]
                if de_list:
                    dem = max(de_list)
                    if dem > rec.date_generated_to:
                        rec.date_generated_to = dem
        return contract_vals

    def _get_contract_work_entries_values(self, date_start, date_stop):
        start_dt = pytz.utc.localize(date_start) if not date_start.tzinfo else date_start
        end_dt   = pytz.utc.localize(date_stop)  if not date_stop.tzinfo  else date_stop
        contract_vals = []
        attendances_by_resource = self._get_attendance_intervals(start_dt, end_dt)
        resource_calendar_leaves = self.env['resource.calendar.leaves'].search(
            self._get_leave_domain(start_dt, end_dt))
        leaves_by_resource = defaultdict(lambda: self.env['resource.calendar.leaves'])
        for leave in resource_calendar_leaves:
            leaves_by_resource[leave.resource_id.id] |= leave

        tz_dates = {}
        for rec in self:
            employee = rec.employee_id
            calendar = rec.resource_calendar_id
            resource = employee.resource_id
            tz = pytz.timezone(calendar.tz)
            attendances = attendances_by_resource.get(resource.id)
            if not attendances:
                continue
            resources_list = [self.env['resource.resource'], resource]
            result = defaultdict(list)
            for leave in itertools.chain(
                leaves_by_resource[False], leaves_by_resource[resource.id]
            ):
                for res in resources_list:
                    if res and leave.calendar_id and leave.calendar_id != calendar and not leave.resource_id:
                        continue
                    tz_used = tz if tz else pytz.timezone((res or rec).tz)
                    start = tz_dates.setdefault((tz_used, start_dt), start_dt.astimezone(tz_used))
                    end   = tz_dates.setdefault((tz_used, end_dt),   end_dt.astimezone(tz_used))
                    dt0 = leave.date_from.astimezone(tz_used)
                    dt1 = leave.date_to.astimezone(tz_used)
                    result[res.id].append((max(start, dt0), min(end, dt1), leave))
            leaves = result.get(resource.id, [])
            default_wet = rec._get_default_work_entry_type()
            for interval in attendances:
                wet = (
                    'work_entry_type_id' in interval[2]
                    and interval[2].work_entry_type_id[:1]
                ) or default_wet
                contract_vals.append(dict([
                    ('name',              '%s: %s' % (wet.name, employee.name)),
                    ('date_start',        interval[0].astimezone(pytz.utc).replace(tzinfo=None)),
                    ('date_stop',         interval[1].astimezone(pytz.utc).replace(tzinfo=None)),
                    ('work_entry_type_id', wet.id),
                    ('employee_id',       employee.id),
                    ('contract_id',       rec.id),
                    ('company_id',        rec.company_id.id),
                    ('state',             'draft'),
                ] + rec._get_more_vals_attendance_interval(interval)))
        return contract_vals

    @api.model
    def _cron_generate_missing_work_entries(self):
        """Monthly cron to fill missing work entries."""
        if 'hr.work.entry' not in self.env:
            return
        today = fields.Date.today()
        start = today + relativedelta(day=1, hour=0)
        stop  = today + relativedelta(months=1, day=31, hour=23, minute=59, second=59)
        contracts = self.env['hr.employee']._get_all_contracts(start, stop, states=['open', 'close'])
        contracts_todo = contracts.filtered(
            lambda c: (
                (c.date_generated_from > start or c.date_generated_to < stop)
                and (not c.last_generation_date or c.last_generation_date < today)
            )
        )
        if not contracts_todo:
            return
        count = len(contracts_todo)
        contracts_todo = contracts_todo.filtered(
            lambda c: c.company_id == contracts_todo[0].company_id)
        BATCH_SIZE = 100
        contracts_todo = contracts_todo.sorted(
            key=lambda c: 1 if c.has_static_work_entries() else 100)
        contracts_todo[:BATCH_SIZE]._generate_work_entries(start, stop, False)
        if count > BATCH_SIZE:
            self.env.ref(
                'hr_employee_custom.ir_cron_generate_missing_work_entries',
                raise_if_not_found=False,
            )

    @api.model
    def _has_field_access(self, field, operation):
        """Allow read access to contract fields for internal users / Employees User group.
        Record-level rules still strictly restrict which contracts the user can see."""
        if not field.groups or self.env.su:
            return True
        if operation == 'read':
            user = self.env.user
            if user and len(user) == 1 and (
                user._has_group('base.group_user')
                or user._has_group('hr_employee_custom.group_hr_employee_user')
            ):
                return True
        return super()._has_field_access(field, operation)


