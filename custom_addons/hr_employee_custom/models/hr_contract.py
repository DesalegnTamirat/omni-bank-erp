

import threading
import itertools
import pytz

from collections import defaultdict
from datetime import date, datetime
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
        string='Employee Category',
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
    overtime                    = fields.Float(string='Overtime',                    digits=(16, 2))
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

    @api.depends('probation_start_date', 'probation_period')
    def _compute_probation_end_date(self):
        for rec in self:
            if rec.probation_start_date and rec.probation_period:
                rec.probation_end_date = (
                    rec.probation_start_date
                    + relativedelta(months=rec.probation_period)
                )
            else:
                rec.probation_end_date = False
    # ─────────────────────────────────────────────────────────────────────────
    # ONCHANGE
    # ─────────────────────────────────────────────────────────────────────────

    @api.onchange('contract_date_start')
    def _onchange_contract_date_start(self):
        """Auto-fill probation start date from contract start date."""
        if self.contract_date_start and not self.probation_start_date:
            self.probation_start_date = self.contract_date_start

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
        res = super().write(vals)
        if vals.get('state') == 'open':
            self._assign_open_contract()
        if vals.get('state') == 'close':
            for rec in self.filtered(lambda c: not c.contract_date_end):
                rec.contract_date_end = max(date.today(), rec.contract_date_start or date.today())
        calendar = vals.get('resource_calendar_id')
        if calendar:
            self.filtered(
                lambda c: c.state in ('open', 'probation')
                or (c.state == 'draft' and c.kanban_state == 'done')
            ).mapped('employee_id').write({'resource_calendar_id': calendar})
        if 'state' in vals and 'kanban_state' not in vals:
            super(HrContract, self).write({'kanban_state': 'normal'})
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
        for rec in self:
            vals = {'state': 'close'}
            if not rec.contract_date_end:
                vals['contract_date_end'] = date.today()
            rec.write(vals)

    def action_cancel(self):
        """Any → Cancelled"""
        self.write({'state': 'cancel'})

    def action_reset_to_new(self):
        """Cancelled / Expired → New"""
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
