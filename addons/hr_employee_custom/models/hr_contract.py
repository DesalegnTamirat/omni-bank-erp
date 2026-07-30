# -*- coding: utf-8 -*-
# Part of custom HR Contract module for Odoo 19.
# Migrated and extended from Odoo 14 hr_contract module.

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
    """Employee Contract — Odoo 19 custom extension."""
    _name = 'hr.contract'
    _description = 'Employee Contract'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    # ─────────────────────────────────────────────────────────────────────────
    # SEQUENCE / NAME
    # ─────────────────────────────────────────────────────────────────────────
    name = fields.Char(
        'Contract Reference', required=True, copy=False,
        readonly=True, default='New')
    active = fields.Boolean(default=True)

    # ─────────────────────────────────────────────────────────────────────────
    # EMPLOYEE / JOB INFO
    # ─────────────────────────────────────────────────────────────────────────
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', tracking=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    department_id = fields.Many2one(
        'hr.department',
        compute='_compute_employee_contract', store=True, readonly=False,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        string='Department', tracking=True)
    job_id = fields.Many2one(
        'hr.job',
        compute='_compute_employee_contract', store=True, readonly=False,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        string='Job Position', tracking=True)
    company_id = fields.Many2one(
        'res.company',
        compute='_compute_employee_contract', store=True, readonly=False,
        default=lambda self: self.env.company, required=True)
    company_country_id = fields.Many2one(
        'res.country', string='Company Country',
        related='company_id.country_id', readonly=True)
    grade_id = fields.Many2one(
        'employee.grade', string='Employee Grade',
        related='employee_id.grade_id', readonly=True, store=False,
        help="Grade of the employee, shown here for reference only "
             "(edit it from the Employee record).")
    job_description = fields.Text(
        string='Job Description',
        help="Describe the job role, responsibilities and duties covered "
             "by this contract.")

    # ─────────────────────────────────────────────────────────────────────────
    # CLASSIFICATION
    # ─────────────────────────────────────────────────────────────────────────
    job_category = fields.Selection([
        ('managerial', 'Managerial'),
        ('non_managerial', 'Non Managerial'),
    ], string='Job Category', tracking=True)

    employee_category = fields.Many2one(
        'hr.contract.type',
        string='Employee Category',
        tracking=True,
        help="Employee category linked to the contract type."
    )

    type_id = fields.Many2one(
        'hr.contract.type', string='Contract Type',
        required=False,
        default=lambda self: self.env['hr.contract.type'].search([], limit=1),
        help="Employee category/type", tracking=True)

    structure_type_id = fields.Many2one(
        'hr.payroll.structure.type', string='Salary Structure Type',
        domain="['|', ('country_id', '=', False), ('country_id', '=', company_country_id)]")

    operating_unit_id = fields.Many2one(
        'operating.unit', string='Operating Unit',
        compute='_compute_employee_contract', store=True, readonly=False,
        tracking=True)

    # ─────────────────────────────────────────────────────────────────────────
    # DATES / DURATION
    # ─────────────────────────────────────────────────────────────────────────
    date_start = fields.Date(
        'Start Date', required=True, default=fields.Date.today,
        tracking=True, help='Start date of the contract.')
    date_end = fields.Date(
        'End Date', tracking=True,
        help='End date of the contract (fixed-term). Leave empty for open-ended.')
    first_contract_date = fields.Date(
        related='employee_id.first_contract_date', string='First Contract Date')
    notice_period = fields.Integer(string='Notice Period (Days)', default=0)

    # Probation
    probation_period = fields.Integer(
        string='Probation Period (Months)', default=0,
        help='Probation duration in months.')
    probation_start_date = fields.Date(string='Probation Start Date')
    probation_end_date = fields.Date(
        string='Probation End Date',
        compute='_compute_probation_end_date', store=True, readonly=False)

    # Trial (Odoo standard compatibility)
    trial_date_end = fields.Date(
        'End of Trial Period',
        help='End date of the trial period (if there is one).')

    # ─────────────────────────────────────────────────────────────────────────
    # WORKING SCHEDULE
    # ─────────────────────────────────────────────────────────────────────────
    resource_calendar_id = fields.Many2one(
        'resource.calendar', 'Working Schedule',
        compute='_compute_employee_contract', store=True, readonly=False,
        default=lambda self: self.env.company.resource_calendar_id.id,
        copy=False, index=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]")
    calendar_mismatch = fields.Boolean(compute='_compute_calendar_mismatch')

    # ─────────────────────────────────────────────────────────────────────────
    # WAGE / SALARY
    # ─────────────────────────────────────────────────────────────────────────
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        related='company_id.currency_id', readonly=True)
    wage = fields.Monetary(
        'Wage', required=True, tracking=True,
        help="Employee's monthly gross wage.")
    wage_type = fields.Selection([
        ('monthly', 'Monthly Fixed'),
        ('hourly', 'Hourly'),
    ], string='Wage Type', default='monthly')
    base_salary = fields.Float(string='Base Salary', digits=(16, 2))
    factor = fields.Float(string='Factor', digits=(16, 3), default=1.0)

    # ─────────────────────────────────────────────────────────────────────────
    # BANK / FINANCIAL ACCOUNTS
    # ─────────────────────────────────────────────────────────────────────────
    employee_tin = fields.Char(string='Employee TIN')
    salary_account = fields.Char(string='Salary Account')
    od_account = fields.Char(string='OD Account')
    pf_account = fields.Char(string='PF Account')
    asbeza_account = fields.Char(string='ASBEZA Account')
    indemnity_account = fields.Char(string='Indemnity Account')

    # Balances
    indemnity_account_balance = fields.Float(
        string='Indemnity Account Balance', digits=(16, 2))
    pf_contribution_balance = fields.Float(
        string='PF Contribution Balance', digits=(16, 2))
    cost_sharing_balance = fields.Float(
        string='Cost Sharing Balance', digits=(16, 2))

    # ─────────────────────────────────────────────────────────────────────────
    # BOOLEAN FLAGS
    # ─────────────────────────────────────────────────────────────────────────
    member_of_labour_union = fields.Boolean(
        string='Member of Labour Union', default=False)
    company_car_provided = fields.Boolean(
        string='Company Car Provided', default=False)
    cash_indemnity_applicable = fields.Boolean(
        string='Cash Indemnity Applicable', default=False)
    wrapping_applicable = fields.Boolean(
        string='Wrapping Applicable', default=False)
    from_transfer = fields.Boolean(
        string='Transferred', default=False)

    # ─────────────────────────────────────────────────────────────────────────
    # PMS / PERFORMANCE
    # ─────────────────────────────────────────────────────────────────────────
    pms_score = fields.Float(string='PMS Score', digits=(16, 2))
    pms_rank = fields.Float(string='PMS Rank', digits=(16, 2))
    penalty_amount = fields.Float(string='Penalty Amount', digits=(16, 2))
    allowance_amount = fields.Float(string='Allowance Amount', digits=(16, 2))

    # ─────────────────────────────────────────────────────────────────────────
    # MONTHLY ALLOWANCES (Salary Information Tab)
    # ─────────────────────────────────────────────────────────────────────────
    cost_sharing = fields.Float(string='Cost Sharing', digits=(16, 2))
    od_deduction = fields.Float(string='OD Deduction', digits=(16, 2))
    asbeza_deduction = fields.Float(string='ASBEZA Deduction', digits=(16, 2))
    labour_union_contribution = fields.Float(
        string='Labour Union Contribution', digits=(16, 2))
    other_allowance = fields.Float(string='Other Allowance', digits=(16, 2))
    other_deductions = fields.Float(string='Other Deductions', digits=(16, 2))
    other_advances = fields.Float(string='Other Advances', digits=(16, 2))
    wellness_allowance = fields.Float(
        string='Wellness Allowance', digits=(16, 2))
    representation_allowance = fields.Float(
        string='Representation Allowance', digits=(16, 2))
    cash_indemnity = fields.Float(
        string='Cash Indemnity', digits=(16, 2))
    cash_indemnity_bank = fields.Float(
        string='Cash Indemnity Bank', digits=(16, 2))
    acting_allowance = fields.Float(
        string='Acting Allowance', digits=(16, 2))
    fuel_allowance = fields.Float(
        string='Fuel Allowance', digits=(16, 2))
    transportation_allowance = fields.Float(
        string='Transportation Allowance', digits=(16, 2))
    hardship_allowance = fields.Float(
        string='Hardship Allowance', digits=(16, 2))
    wrapping_allowance = fields.Float(
        string='Wrapping Allowance', digits=(16, 2))
    mobile_allowance = fields.Float(
        string='Mobile Allowance', digits=(16, 2))
    special_car_allowance = fields.Float(
        string='Special Car Allowance', digits=(16, 2))
    housing_allowance = fields.Float(
        string='Housing Allowance', digits=(16, 2))
    overtime = fields.Float(
        string='Overtime', digits=(16, 2))
    vacation_allowance = fields.Float(
        string='Vacation Allowance', digits=(16, 2))
    disturbance_allowance = fields.Float(
        string='Disturbance Allowance', digits=(16, 2))
    #
    # # Legacy C1–C50 fields (payroll rule compatibility)
    # c2 = fields.Float(string='C2', help='Contract Element C2')
    # c3 = fields.Float(string='C3', help='Contract Element C3')
    # c4 = fields.Float(string='C4', help='Contract Element C4')
    # c5 = fields.Float(string='C5', help='Contract Element C5')
    # c6 = fields.Float(string='C6', help='Contract Element C6')
    # c7 = fields.Float(string='C7', help='Contract Element C7')
    # c8 = fields.Float(string='C8', help='Contract Element C8')
    # c9 = fields.Float(string='C9', help='Contract Element C9')
    # c10 = fields.Float(string='C10', help='Contract Element C10')
    # c11 = fields.Float(string='C11', help='Contract Element C11')
    # c12 = fields.Float(string='C12', help='Contract Element C12')
    # c13 = fields.Float(string='C13', help='Contract Element C13')
    # c14 = fields.Float(string='C14', help='Contract Element C14')
    # c15 = fields.Float(string='C15', help='Contract Element C15')
    # c16 = fields.Float(string='C16', help='Contract Element C16')
    # c17 = fields.Float(string='C17', help='Contract Element C17')
    # c18 = fields.Float(string='C18', help='Contract Element C18')
    # c19 = fields.Float(string='C19', help='Contract Element C19')
    # c20 = fields.Float(string='C20', help='Contract Element C20')
    # c21 = fields.Float(string='C21', help='Contract Element C21')
    # c22 = fields.Float(string='C22', help='Contract Element C22')
    # c23 = fields.Float(string='C23', help='Contract Element C23')
    # c24 = fields.Float(string='C24', help='Contract Element C24')
    # c25 = fields.Float(string='C25', help='Contract Element C25')
    # c26 = fields.Float(string='C26', help='Contract Element C26')
    # c27 = fields.Float(string='C27', help='Contract Element C27')
    # c28 = fields.Float(string='C28', help='Contract Element C28')
    # c29 = fields.Float(string='C29', help='Contract Element C29')
    # c30 = fields.Float(string='C30', help='Contract Element C30')
    # c31 = fields.Float(string='C31', help='Contract Element C31')
    # c32 = fields.Float(string='C32', help='Contract Element C32')
    # c33 = fields.Float(string='C33', help='Contract Element C33')
    # c34 = fields.Float(string='C34', help='Contract Element C34')
    # c35 = fields.Float(string='C35', help='Contract Element C35')
    # c36 = fields.Float(string='C36', help='Contract Element C36')
    # c37 = fields.Float(string='C37', help='Contract Element C37')
    # c38 = fields.Float(string='C38', help='Contract Element C38')
    # c39 = fields.Float(string='C39', help='Contract Element C39')
    # c40 = fields.Float(string='C40', help='Contract Element C40')
    # c41 = fields.Float(string='C41', help='Contract Element C41')
    # c42 = fields.Float(string='C42', help='Contract Element C42')
    # c43 = fields.Float(string='C43', help='Contract Element C43')
    # c44 = fields.Float(string='C44', help='Contract Element C44')
    # c45 = fields.Float(string='C45', help='Contract Element C45')
    # c46 = fields.Float(string='C46', help='Contract Element C46')
    # c47 = fields.Float(string='C47', help='Contract Element C47')
    # c48 = fields.Float(string='C48', help='Contract Element C48')
    # c49 = fields.Float(string='C49', help='Contract Element C49')
    # c50 = fields.Float(string='C50', help='Contract Element C50')

    # ─────────────────────────────────────────────────────────────────────────
    # HR INFO
    # ─────────────────────────────────────────────────────────────────────────
    hr_responsible_id = fields.Many2one(
        'res.users', 'HR Responsible', tracking=True,
        help="Person responsible for validating the employee's contracts.")
    notes = fields.Text('Notes')

    # Visa / Permit (standard Odoo fields relayed)
    permit_no = fields.Char(
        'Work Permit No', related='employee_id.permit_no', readonly=False)
    visa_no = fields.Char(
        'Visa No', related='employee_id.visa_no', readonly=False)
    visa_expire = fields.Date(
        'Visa Expire Date', related='employee_id.visa_expire', readonly=False)

    # ─────────────────────────────────────────────────────────────────────────
    # STATE
    # ─────────────────────────────────────────────────────────────────────────
    state = fields.Selection([
        ('draft', 'New'),
        ('probation', 'Probation'),
        ('open', 'Running'),
        ('close', 'Expired'),
        ('cancel', 'Cancelled'),
    ], string='Status', group_expand='_group_expand_states',
        copy=False, tracking=True,
        help='Status of the contract', default='draft')

    kanban_state = fields.Selection([
        ('normal', 'Grey'),
        ('done', 'Green'),
        ('blocked', 'Red'),
    ], string='Kanban State', default='normal', tracking=True, copy=False)

    # ─────────────────────────────────────────────────────────────────────────
    # WORK ENTRY (Odoo 19 compatible — optional, won't break without hr_work_entry)
    # ─────────────────────────────────────────────────────────────────────────
    date_generated_from = fields.Datetime(
        string='Generated From', readonly=True, required=True,
        default=lambda self: datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0),
        copy=False)
    date_generated_to = fields.Datetime(
        string='Generated To', readonly=True, required=True,
        default=lambda self: datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0),
        copy=False)
    last_generation_date = fields.Date(
        string='Last Generation Date', readonly=True)
    work_entry_source = fields.Selection(
        [('calendar', 'Working Schedule')],
        required=True, default='calendar',
        help='Defines the source for work entries generation.')

    # ─────────────────────────────────────────────────────────────────────────
    # COMPUTE METHODS
    # ─────────────────────────────────────────────────────────────────────────

    def _group_expand_states(self, states, domain):
        return [key for key, val in type(self).state.selection]

    @api.depends('employee_id.resource_calendar_id', 'resource_calendar_id')
    def _compute_calendar_mismatch(self):
        for contract in self:
            contract.calendar_mismatch = (
                contract.resource_calendar_id
                != contract.employee_id.resource_calendar_id
            )

    @api.depends('employee_id')
    def _compute_employee_contract(self):
        for contract in self.filtered('employee_id'):
            contract.job_id = contract.employee_id.job_id
            contract.department_id = contract.employee_id.department_id
            contract.resource_calendar_id = contract.employee_id.resource_calendar_id
            contract.company_id = contract.employee_id.company_id
            dept = contract.employee_id.department_id
            if dept and hasattr(dept, 'operating_unit_id'):
                contract.operating_unit_id = dept.operating_unit_id

    @api.depends('probation_start_date', 'probation_period')
    def _compute_probation_end_date(self):
        for contract in self:
            if contract.probation_start_date and contract.probation_period:
                contract.probation_end_date = (
                    contract.probation_start_date
                    + relativedelta(months=contract.probation_period)
                )
            else:
                contract.probation_end_date = False

    # ─────────────────────────────────────────────────────────────────────────
    # ONCHANGE
    # ─────────────────────────────────────────────────────────────────────────

    @api.onchange('date_start')
    def _onchange_date_start(self):
        if self.date_start and not self.probation_start_date:
            self.probation_start_date = self.date_start

    @api.onchange('structure_type_id')
    def _onchange_structure_type_id(self):
        if self.structure_type_id.default_resource_calendar_id:
            self.resource_calendar_id = (
                self.structure_type_id.default_resource_calendar_id)

    # ─────────────────────────────────────────────────────────────────────────
    # CONSTRAINTS
    # ─────────────────────────────────────────────────────────────────────────

    @api.constrains('employee_id', 'state', 'kanban_state', 'date_start', 'date_end')
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
            if not contract.date_end:
                start_domain = []
                end_domain = [
                    '|',
                    ('date_end', '>=', contract.date_start),
                    ('date_end', '=', False),
                ]
            else:
                start_domain = [('date_start', '<=', contract.date_end)]
                end_domain = [
                    '|',
                    ('date_end', '>', contract.date_start),
                    ('date_end', '=', False),
                ]
            # Odoo 19: use Domain instead of expression.AND
            domain = (Domain(domain) & Domain(start_domain) & Domain(end_domain))
            if self.search_count(domain):
                raise ValidationError(_(
                    'An employee can only have one active contract at a time. '
                    '(Excluding Draft and Cancelled contracts)'
                ))

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        if self.filtered(lambda c: c.date_end and c.date_start > c.date_end):
            raise ValidationError(_(
                'Contract start date must be earlier than contract end date.'
            ))

    # ─────────────────────────────────────────────────────────────────────────
    # SEQUENCE / CREATE / WRITE
    # ─────────────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'hr.contract') or 'New'
        contracts = super().create(vals_list)
        for contract in contracts:
            if contract.state == 'open':
                contract._assign_open_contract()
        open_contracts = contracts.filtered(
            lambda c: c.state in ('open', 'probation')
            or (c.state == 'draft' and c.kanban_state == 'done')
        )
        for contract in open_contracts.filtered(
            lambda c: c.employee_id and c.resource_calendar_id
        ):
            contract.employee_id.resource_calendar_id = contract.resource_calendar_id
        return contracts

    def write(self, vals):
        res = super().write(vals)
        if vals.get('state') == 'open':
            self._assign_open_contract()
        if vals.get('state') == 'close':
            for contract in self.filtered(lambda c: not c.date_end):
                contract.date_end = max(date.today(), contract.date_start)
        calendar = vals.get('resource_calendar_id')
        if calendar:
            self.filtered(
                lambda c: c.state in ('open', 'probation')
                or (c.state == 'draft' and c.kanban_state == 'done')
            ).mapped('employee_id').write({'resource_calendar_id': calendar})
        if 'state' in vals and 'kanban_state' not in vals:
            # Use super() to avoid re-triggering this write() override
            super(HrContract, self).write({'kanban_state': 'normal'})
        if vals.get('date_end') or vals.get('date_start'):
            self.sudo()._remove_work_entries()
        if vals.get('state') in ['draft', 'cancel']:
            self._cancel_work_entries()
        return res

    # ─────────────────────────────────────────────────────────────────────────
    # CONTRACT HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _assign_open_contract(self):
        for contract in self:
            contract.employee_id.sudo().write({'contract_id': contract.id})

    def _get_contract_wage(self):
        self.ensure_one()
        return self[self._get_contract_wage_field()]

    def _get_contract_wage_field(self):
        self.ensure_one()
        return 'wage'

    # ─────────────────────────────────────────────────────────────────────────
    # STATE ACTION BUTTONS
    # ─────────────────────────────────────────────────────────────────────────

    def action_start_probation(self):
        """New → Probation"""
        self.write({'state': 'probation'})

    def action_start_running(self):
        """Probation → Running — requires probation_end_date to have passed"""
        today = date.today()
        for contract in self:
            if contract.state == 'probation':
                if not contract.probation_end_date:
                    raise UserError(_(
                        'Cannot approve contract "%s": Probation End Date is not set.',
                        contract.name
                    ))
                if contract.probation_end_date > today:
                    raise UserError(_(
                        'Cannot approve contract "%s": Probation period ends on %s. '
                        'You can only approve after that date.',
                        contract.name,
                        contract.probation_end_date.strftime('%d/%m/%Y')
                    ))
            contract.write({'state': 'open'})
            contract._assign_open_contract()

    def action_expire(self):
        """Running → Expired"""
        for contract in self:
            vals = {'state': 'close'}
            if not contract.date_end:
                vals['date_end'] = date.today()
            contract.write(vals)

    def action_cancel(self):
        """Any → Cancelled"""
        self.write({'state': 'cancel'})

    def action_reset_to_new(self):
        """Cancelled / Expired → New"""
        self.write({'state': 'draft'})

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
            ('date_end', '<=', fields.Date.to_string(
                today + relativedelta(days=7))),
            ('date_end', '>=', fields.Date.to_string(
                today + relativedelta(days=1))),
            '&',
            ('visa_expire', '<=', fields.Date.to_string(
                today + relativedelta(days=60))),
            ('visa_expire', '>=', fields.Date.to_string(
                today + relativedelta(days=1))),
        ])
        for contract in contracts_expiring:
            contract.activity_schedule(
                'mail.mail_activity_data_todo',
                contract.date_end,
                _('The contract of %s is about to expire.',
                  contract.employee_id.name),
                user_id=contract.hr_responsible_id.id or self.env.uid,
            )
        if contracts_expiring:
            contracts_expiring._safe_write_for_cron(
                {'kanban_state': 'blocked'}, from_cron)

        contracts_to_close = self.search([
            ('state', '=', 'open'),
            '|',
            ('date_end', '<=', fields.Date.to_string(today)),
            ('visa_expire', '<=', fields.Date.to_string(today)),
        ])
        if contracts_to_close:
            contracts_to_close._safe_write_for_cron(
                {'state': 'close'}, from_cron)

        contracts_to_open = self.search([
            ('state', '=', 'draft'),
            ('kanban_state', '=', 'done'),
            ('date_start', '<=', fields.Date.to_string(today)),
        ])
        if contracts_to_open:
            contracts_to_open._safe_write_for_cron(
                {'state': 'open'}, from_cron)

        contracts_probation_done = self.search([
            ('state', '=', 'probation'),
            ('probation_end_date', '<=', fields.Date.to_string(today)),
        ])
        if contracts_probation_done:
            contracts_probation_done._safe_write_for_cron(
                {'state': 'open'}, from_cron)

        contract_ids = self.search([
            ('date_end', '=', False),
            ('state', '=', 'close'),
            ('employee_id', '!=', False),
        ])
        for contract in contract_ids:
            next_contract = self.search([
                ('employee_id', '=', contract.employee_id.id),
                ('state', 'not in', ['cancel', 'new']),
                ('date_start', '>', contract.date_start),
            ], order='date_start asc', limit=1)
            if next_contract:
                contract._safe_write_for_cron(
                    {'date_end': next_contract.date_start - relativedelta(days=1)},
                    from_cron)

        return True

    def _safe_write_for_cron(self, vals, from_cron=False):
        if from_cron:
            auto_commit = not getattr(threading.current_thread(), 'testing', False)
            for contract in self:
                try:
                    with self.env.cr.savepoint():
                        contract.write(vals)
                except ValidationError as e:
                    _logger.warning(e)
                else:
                    if auto_commit:
                        self.env.cr.commit()
        else:
            self.write(vals)

    # ─────────────────────────────────────────────────────────────────────────
    # CHATTER SUBTYPES
    # ─────────────────────────────────────────────────────────────────────────

    def _track_subtype(self, init_values):
        """Disable all tracking on hr.contract to prevent mail flood during upgrades."""
        return False

    def _message_track(self, fields_iter, initial_values_dict):
        return {}

    # ─────────────────────────────────────────────────────────────────────────
    # WORK ENTRY METHODS (Odoo 19 — graceful if hr_work_entry not installed)
    # ─────────────────────────────────────────────────────────────────────────

    def _get_default_work_entry_type(self):
        return self.env.ref(
            'hr_work_entry.work_entry_type_attendance',
            raise_if_not_found=False)

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
        for contract in self:
            employees_by_calendar[contract.resource_calendar_id] |= contract.employee_id
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
        for contract in self:
            date_start = fields.Datetime.to_datetime(contract.date_start)
            if contract.date_generated_from < date_start:
                we_to_remove = self.env['hr.work.entry'].search([
                    ('date_stop', '<=', date_start),
                    ('contract_id', '=', contract.id),
                ])
                if we_to_remove:
                    contract.date_generated_from = date_start
                    all_we_to_unlink |= we_to_remove
            if not contract.date_end:
                continue
            date_end = datetime.combine(contract.date_end, datetime.max.time())
            if contract.date_generated_to > date_end:
                we_to_remove = self.env['hr.work.entry'].search([
                    ('date_start', '>=', date_end),
                    ('contract_id', '=', contract.id),
                ])
                if we_to_remove:
                    contract.date_generated_to = date_end
                    all_we_to_unlink |= we_to_remove
        all_we_to_unlink.unlink()

    def _cancel_work_entries(self):
        if not self or 'hr.work.entry' not in self.env:
            return
        # Odoo 19: use Domain instead of expression.AND
        base_domain = Domain([('state', '!=', 'validated')])
        for contract in self:
            date_start = fields.Datetime.to_datetime(contract.date_start)
            contract_domain = Domain([
                ('contract_id', '=', contract.id),
                ('date_start', '>=', date_start),
            ])
            if contract.date_end:
                date_end = datetime.combine(
                    contract.date_end, datetime.max.time())
                contract_domain &= Domain([('date_stop', '<=', date_end)])
            base_domain &= contract_domain
        work_entries = self.env['hr.work.entry'].search(base_domain)
        if work_entries:
            work_entries.unlink()

    def _generate_work_entries(self, date_start, date_stop, force=False):
        """Generate work entries for this contract. Requires hr_work_entry module."""
        if 'hr.work.entry' not in self.env:
            raise UserError(_('Work Entries module (hr_work_entry) is not installed.'))
        self = self.with_context(tracking_disable=True)
        canceled_contracts = self.filtered(lambda c: c.state == 'cancel')
        if canceled_contracts:
            raise UserError(
                _('Generating work entries from cancelled contracts is not allowed.')
                + '\n%s' % ', '.join(canceled_contracts.mapped('name')))

        date_start = fields.Datetime.to_datetime(date_start)
        date_stop = datetime.combine(
            fields.Datetime.to_datetime(date_stop), datetime.max.time())
        self.write({'last_generation_date': fields.Date.today()})

        intervals_to_generate = defaultdict(lambda: self.env['hr.contract'])
        self.filtered(
            lambda c: c.date_generated_from == c.date_generated_to
        ).write({
            'date_generated_from': date_start,
            'date_generated_to': date_start,
        })

        for contract in self:
            contract_start = fields.Datetime.to_datetime(contract.date_start)
            contract_stop = datetime.combine(
                fields.Datetime.to_datetime(
                    contract.date_end or datetime.max.date()),
                datetime.max.time())
            if date_start > contract_stop or date_stop < contract_start:
                continue
            date_start_we = max(date_start, contract_start)
            date_stop_we = min(date_stop, contract_stop)
            if force:
                intervals_to_generate[(date_start_we, date_stop_we)] |= contract
                continue
            is_static = contract.has_static_work_entries()
            last_gen_from = min(contract.date_generated_from, contract_stop)
            if last_gen_from > date_start_we:
                if is_static:
                    contract.date_generated_from = date_start_we
                intervals_to_generate[(date_start_we, last_gen_from)] |= contract
            last_gen_to = max(contract.date_generated_to, contract_start)
            if last_gen_to < date_stop_we:
                if is_static:
                    contract.date_generated_to = date_stop_we
                intervals_to_generate[(last_gen_to, date_stop_we)] |= contract

        vals_list = []
        for interval, contracts in intervals_to_generate.items():
            date_from, date_to = interval
            vals_list.extend(contracts._get_work_entries_values(date_from, date_to))

        if not vals_list:
            return self.env['hr.work.entry']
        return self.env['hr.work.entry'].create(vals_list)

    def _get_work_entries_values(self, date_start, date_stop):
        """Generate work entry values list between date_start and date_stop."""
        contract_vals = self._get_contract_work_entries_values(
            date_start, date_stop)
        mapped_contract_dates = defaultdict(lambda: ([], []))
        for x in contract_vals:
            mapped_contract_dates[x['contract_id']][0].append(x['date_start'])
            mapped_contract_dates[x['contract_id']][1].append(x['date_stop'])
        for contract in self:
            if contract_vals:
                dates_stop = mapped_contract_dates[contract.id][1]
                if dates_stop:
                    date_stop_max = max(dates_stop)
                    if date_stop_max > contract.date_generated_to:
                        contract.date_generated_to = date_stop_max
                dates_start = mapped_contract_dates[contract.id][0]
                if dates_start:
                    date_start_min = min(dates_start)
                    if date_start_min < contract.date_generated_from:
                        contract.date_generated_from = date_start_min
        return contract_vals

    def _get_contract_work_entries_values(self, date_start, date_stop):
        start_dt = (pytz.utc.localize(date_start)
                    if not date_start.tzinfo else date_start)
        end_dt = (pytz.utc.localize(date_stop)
                  if not date_stop.tzinfo else date_stop)
        contract_vals = []
        bypassing_codes = self._get_bypassing_work_entry_type_codes()
        attendances_by_resource = self._get_attendance_intervals(start_dt, end_dt)
        resource_calendar_leaves = self.env['resource.calendar.leaves'].search(
            self._get_leave_domain(start_dt, end_dt))
        leaves_by_resource = defaultdict(
            lambda: self.env['resource.calendar.leaves'])
        for leave in resource_calendar_leaves:
            leaves_by_resource[leave.resource_id.id] |= leave

        tz_dates = {}
        for contract in self:
            employee = contract.employee_id
            calendar = contract.resource_calendar_id
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
                    if (res and leave.calendar_id
                            and leave.calendar_id != calendar
                            and not leave.resource_id):
                        continue
                    tz_used = tz if tz else pytz.timezone(
                        (res or contract).tz)
                    start = tz_dates.setdefault(
                        (tz_used, start_dt), start_dt.astimezone(tz_used))
                    end = tz_dates.setdefault(
                        (tz_used, end_dt), end_dt.astimezone(tz_used))
                    dt0 = leave.date_from.astimezone(tz_used)
                    dt1 = leave.date_to.astimezone(tz_used)
                    result[res.id].append(
                        (max(start, dt0), min(end, dt1), leave))
            mapped_leaves = {
                r.id: result[r.id] for r in resources_list}
            leaves = mapped_leaves.get(resource.id, [])
            default_work_entry_type = contract._get_default_work_entry_type()
            for interval in attendances:
                work_entry_type = (
                    'work_entry_type_id' in interval[2]
                    and interval[2].work_entry_type_id[:1]
                ) or default_work_entry_type
                contract_vals.append(dict([
                    ('name', '%s: %s' % (work_entry_type.name, employee.name)),
                    ('date_start',
                     interval[0].astimezone(pytz.utc).replace(tzinfo=None)),
                    ('date_stop',
                     interval[1].astimezone(pytz.utc).replace(tzinfo=None)),
                    ('work_entry_type_id', work_entry_type.id),
                    ('employee_id', employee.id),
                    ('contract_id', contract.id),
                    ('company_id', contract.company_id.id),
                    ('state', 'draft'),
                ] + contract._get_more_vals_attendance_interval(interval)))
        return contract_vals

    @api.model
    def _cron_generate_missing_work_entries(self):
        """Monthly cron to fill missing work entries."""
        if 'hr.work.entry' not in self.env:
            return
        today = fields.Date.today()
        start = today + relativedelta(day=1, hour=0)
        stop = today + relativedelta(months=1, day=31, hour=23, minute=59, second=59)
        contracts = self.env['hr.employee']._get_all_contracts(
            start, stop, states=['open', 'close'])
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
