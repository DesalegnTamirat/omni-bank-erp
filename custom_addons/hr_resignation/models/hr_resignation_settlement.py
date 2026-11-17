# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import time
import requests
import logging
from datetime import timedelta
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)

_CBS_TOKEN_CACHE = {
    'token': None,
    'expiry': 0.0,
    'base_url': None,
}

class HrResignationSettlementLine(models.Model):
    _name = 'hr.resignation.settlement.line'
    _description = 'Settlement Line'

    settlement_id = fields.Many2one('hr.resignation.settlement', string='Settlement', ondelete='cascade', index=True)
    resignation_id = fields.Many2one('hr.resignation', string='Resignation', index=True, ondelete='cascade')
    name = fields.Char(string='Description', required=True)
    line_type = fields.Selection([
        ('earning', 'Entitlement'),
        ('deduction', 'Deduction'),
        ('tax', 'Tax')
    ], string='Type', default='earning', required=True)
    is_taxable = fields.Boolean(string='Taxable?', default=False)
    amount = fields.Float(string='Amount', default=0.0, digits=(16, 2))
    notes = fields.Char(string='Notes')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('resignation_id') and not vals.get('settlement_id'):
                resignation = self.env['hr.resignation'].sudo().browse(vals['resignation_id'])
                if resignation.settlement_id:
                    vals['settlement_id'] = resignation.settlement_id.id
            elif vals.get('settlement_id') and not vals.get('resignation_id'):
                settlement = self.env['hr.resignation.settlement'].sudo().browse(vals['settlement_id'])
                if settlement.resignation_id:
                    vals['resignation_id'] = settlement.resignation_id.id
        return super().create(vals_list)

    def write(self, vals):
        if 'resignation_id' in vals and not 'settlement_id' in vals:
            resignation = self.env['hr.resignation'].sudo().browse(vals['resignation_id'])
            if resignation.settlement_id:
                vals['settlement_id'] = resignation.settlement_id.id
        elif 'settlement_id' in vals and not 'resignation_id' in vals:
            settlement = self.env['hr.resignation.settlement'].sudo().browse(vals['settlement_id'])
            if settlement.resignation_id:
                vals['resignation_id'] = settlement.resignation_id.id
        return super().write(vals)


class HrResignationSettlement(models.Model):
    _name = 'hr.resignation.settlement'
    _description = 'Resignation Final Settlement'
    _rec_name = 'employee_id'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    resignation_id = fields.Many2one('hr.resignation', ondelete='cascade', index=True)
    employee_id    = fields.Many2one('hr.employee', required=True, index=True)
    
    def init(self):
        super().init()
        self.env.cr.execute(
            "CREATE INDEX IF NOT EXISTS hr_settlement_res_state_idx "
            "ON hr_resignation_settlement (resignation_id, state)"
        )
    
    employee_sudo_name = fields.Char(
        string='Employee',
        compute='_compute_employee_sudo_name',
        help='Bypasses strict hierarchy rules to display employee name.'
    )
    
    @api.depends('employee_id')
    def _compute_employee_sudo_name(self):
        for rec in self:
            rec.employee_sudo_name = rec.employee_id.sudo().name if rec.employee_id else ''

    related_release_date = fields.Date(related='resignation_id.release_date')
    def _default_settlement_date(self):
        resignation_id = self.env.context.get('default_resignation_id')
        if resignation_id:
            resignation = self.env['hr.resignation'].sudo().browse(resignation_id)
            if resignation.release_date:
                return resignation.release_date
        return fields.Date.context_today(self)

    settlement_date = fields.Date(
        string='Settlement Date',
        default=_default_settlement_date,
        help="Date used for final calculations. Defaults to the official Release Date."
    )
    date_change_justification = fields.Text(string='Date Change Justification')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            res_id = vals.get('resignation_id')
            if res_id:
                res = self.env['hr.resignation'].sudo().browse(res_id)
                if not vals.get('cbs_start_date') and res.application_date:
                    vals['cbs_start_date'] = res.application_date
                if not vals.get('cbs_end_date'):
                    vals['cbs_end_date'] = res.release_date or vals.get('settlement_date')
        records = super().create(vals_list)
        for rec in records:
            if rec.employee_id and rec.employee_id.employee_identification:
                try:
                    rec.action_fetch_cbs_employee_accounts()
                except Exception:
                    pass
        return records

    # CBS Integration Fields
    cbs_user_id = fields.Char(related='employee_id.employee_identification', string='CBS Employee ID', readonly=True, compute_sudo=True)
    cbs_start_date = fields.Date(string='Calculation Start Date', compute='_compute_cbs_dates', store=True, readonly=False)
    cbs_end_date = fields.Date(string='Calculation End Date', compute='_compute_cbs_dates', store=True, readonly=False)
    cbs_working_days = fields.Integer(string='Applicable Working Days', default=25)

    @api.depends('resignation_id.application_date', 'resignation_id.release_date', 'settlement_date')
    def _compute_cbs_dates(self):
        for rec in self:
            res = rec.resignation_id
            app_date = res.application_date if res and res.application_date else False
            rel_date = rec.settlement_date or (res and res.release_date) or False
            if app_date:
                rec.cbs_start_date = app_date
            elif not rec.cbs_start_date:
                rec.cbs_start_date = fields.Date.today()
            if rel_date:
                rec.cbs_end_date = rel_date
            elif not rec.cbs_end_date:
                rec.cbs_end_date = fields.Date.today()

            # Clean up any legacy technical timeout/connection error messages
            if rec.cbs_sync_status and any(w in rec.cbs_sync_status for w in ['CBS Timeout', 'took >', '[Notice]', 'Connection Error']):
                rec.cbs_sync_status = False
            if rec.cbs_pf_sync_status and any(w in rec.cbs_pf_sync_status for w in ['CBS Timeout', 'took >', '[Notice]', 'Connection Error']):
                rec.cbs_pf_sync_status = False

    @api.onchange('resignation_id')
    def _onchange_resignation_id_cbs_dates(self):
        if self.resignation_id:
            if self.resignation_id.application_date:
                self.cbs_start_date = self.resignation_id.application_date
            if self.resignation_id.release_date:
                self.cbs_end_date = self.resignation_id.release_date
            elif self.settlement_date:
                self.cbs_end_date = self.settlement_date
    cbs_indemnity_amount = fields.Float(string='Calculated Indemnity Amount', readonly=True, copy=False)
    cbs_indemnity_balance = fields.Float(string='Cash Indemnity Balance', readonly=True, copy=False)
    cbs_sync_status = fields.Char(string='Verification Status', readonly=True, copy=False)
    
    # CBS Provident Fund Integration
    cbs_pf_account = fields.Char(
        string='PF Account Number',
        compute='_compute_default_cbs_accounts',
        store=True,
        readonly=False,
        copy=False
    )
    cbs_pf_sync_status = fields.Char(string='PF Verification Status', readonly=True, copy=False)
    
    # CBS Cash Indemnity Integration
    cbs_indemnity_account = fields.Char(
        string='Cash Indemnity Account',
        compute='_compute_default_cbs_accounts',
        store=True,
        readonly=False,
        copy=False
    )

    @api.depends('employee_id')
    def _compute_default_cbs_accounts(self):
        for rec in self:
            ver = rec.employee_id.current_version_id if rec.employee_id else False
            if not rec.cbs_pf_account:
                rec.cbs_pf_account = ver.pf_account if ver else False
            if not rec.cbs_indemnity_account:
                rec.cbs_indemnity_account = ver.indemnity_account if ver else False

    # Tracks whether the POMD Officer has explicitly clicked "Process Settlement"
    # Only when this is True does "Submit for Approval" become visible
    is_processed = fields.Boolean(string='Is Processed', default=False, copy=False)

    # reads authorization from resignation submission
    settlement_authorized = fields.Boolean(
        related='resignation_id.debt_settlement_authorized',
        string='Debt Settlement Authorized', readonly=True)

    # Service Period
    service_years = fields.Float(
        compute='_compute_service_years', store=True, digits=(16, 2),
        string='Years of Service')
    joined_date = fields.Date(related='resignation_id.joined_date', string='Joined Date', readonly=True)
    application_date = fields.Date(related='resignation_id.application_date', string='Resignation Application Date', readonly=True)
    release_date = fields.Date(related='resignation_id.release_date', string='Release Date', readonly=True)
    service_months_total = fields.Integer(
        compute='_compute_service_years', store=True,
        string='Total Months of Service')

    # Eligibility Context
    separation_reason       = fields.Char(compute='_compute_eligibility_context', store=True, string='Separation Reason')
    job_category            = fields.Char(compute='_compute_eligibility_context', store=True, string='Job Category')
    has_disciplinary_case   = fields.Boolean(compute='_compute_eligibility_context', store=True, string='Active Disciplinary Case')
    is_misconduct_dismissal = fields.Boolean(compute='_compute_eligibility_context', store=True, string='Dismissed for Misconduct')
    is_company_terminated   = fields.Boolean(compute='_compute_eligibility_context', store=True, string='Company Terminated')

    # Salary Parameters
    basic_salary = fields.Float(string='Basic Salary', related='resignation_id.basic_salary', readonly=True, digits=(16, 2))
    worked_days_final_month = fields.Integer(
        string='Worked Days in Final Month',
        compute='_compute_worked_days_default', store=True,
        help="Auto-filled from the employee's release date."
    )
    total_days_in_month = fields.Integer(string='Total Days in Month', default=30)  # kept for DB compatibility, not shown in view
    years_for_severance = fields.Float(string='Years for Severance', digits=(16, 2))

    # Provident Fund
    pf_eligible          = fields.Selection([('yes', 'Yes'), ('no', 'No')], compute='_compute_pf_eligible', store=True, string='PF Eligible')
    pf_ineligible_reason = fields.Char(compute='_compute_pf_eligible', store=True, string='PF Ineligibility Reason')
    pf_amount            = fields.Float(digits=(16, 2), string='Provident Fund')

    # Severance
    severance_eligible          = fields.Selection([('yes', 'Yes'), ('no', 'No')], compute='_compute_severance_eligible', store=True, string='Severance Eligible')
    severance_ineligible_reason = fields.Char(compute='_compute_severance_eligible', store=True, string='Severance Ineligibility Reason')
    severance_amount            = fields.Float(string='Severance Pay', compute='_compute_severance_amount', store=True, readonly=False, digits=(16, 2))
    net_severance_amount        = fields.Float(string='Net Severance Pay', compute='_compute_severance_amount', store=True, digits=(16, 2))
    severance_breakdown_html    = fields.Html(string='Severance Computation Details', compute='_compute_severance_amount', store=True, readonly=True, sanitize=False)

    # Accrued Leave
    accrued_leave_pay = fields.Float(string='Accrued leave pay', compute='_compute_accrued_leave_pay', store=True, readonly=False, digits=(16, 2))
    income_tax_leave = fields.Float(string='Income Tax (Leave)', compute='_compute_accrued_leave_pay', store=True, readonly=False, digits=(16, 2))
    net_accrued_leave_pay = fields.Float(string='Net Accrued Leave Pay', compute='_compute_accrued_leave_pay', store=True, digits=(16, 2))
    accrued_leave_breakdown_html = fields.Html(string='Accrued Leave Computation Details', compute='_compute_accrued_leave_pay', store=True, readonly=True, sanitize=False)

    # Financial Fields
    remaining_salary = fields.Float(string='Remaining Salary', compute='_compute_remaining_salary', store=True, readonly=False, digits=(16, 2))
    remaining_salary_notes = fields.Char(string='Remaining Salary Notes', compute='_compute_remaining_salary', store=True)
    cash_indemnity_working_days = fields.Integer(string='Cash Indemnity Working Days', compute='_compute_cash_indemnity_days', store=True, readonly=False)
    accrued_leave_notes = fields.Char(string='Accrued Leave Notes')
    rssa_payment = fields.Float(string='RSSA Payment', digits=(16, 2))
    other_benefits = fields.Float(string='Other Benefits', default=0.0, digits=(16, 2))
    
    notice_period_accepted = fields.Selection(related='resignation_id.notice_period_accepted', readonly=True)
    liability = fields.Float(related='resignation_id.liability', readonly=True, digits=(16, 2))
    
    # Unified Lines
    line_ids = fields.One2many('hr.resignation.settlement.line', 'settlement_id', string='Settlement Lines')
    total_payment = fields.Float(string='Gross Total', compute='_compute_summary', store=True, digits=(16, 2))
    
    taxable_gross = fields.Float(string='Taxable Gross', compute='_compute_summary', store=True, digits=(16, 2))
    total_earnings = fields.Float(string='Total Earnings', compute='_compute_summary', store=True, digits=(16, 2))
    total_deductions_taxes = fields.Float(string='Total Deductions & Taxes', compute='_compute_summary', store=True, digits=(16, 2))
    
    # Deductions
    debt_mortgage_loan = fields.Float(string='Mortgage Loan Debt', default=0.0, digits=(16, 2))
    debt_personal_loan = fields.Float(string='Personal Loan Debt', default=0.0, digits=(16, 2))
    debt_rssa_loan = fields.Float(string='RSSA Loan Debt', default=0.0, digits=(16, 2))
    debt_guaranteed_loan = fields.Float(string='Guaranteed Loan Debt', default=0.0, digits=(16, 2))
    debt_guaranteed_notes = fields.Text(string='Guaranteed Loan Details')
    rssa_od_guarantor = fields.Char(
        string='OD/RSSA Loan Guarantor(s)',
        compute='_compute_guarantor_summary',
        store=False,
    )
    guaranteed_other_status = fields.Text(
        string='Loans Guaranteed for Others',
        compute='_compute_guarantor_summary',
        store=False,
    )
    
    outstanding_debt_deduction = fields.Float(string='Total Outstanding Debt', compute='_compute_outstanding_debt', store=True, readonly=True, digits=(16, 2))
    income_tax_deduction = fields.Float(string='Income Tax Deduction', compute='_compute_salary_deductions', store=True, readonly=False, digits=(16, 2))
    income_tax_severance = fields.Float(string='Income Tax (Severance)', compute='_compute_severance_amount', store=True, readonly=False, digits=(16, 2))
    pension_deduction = fields.Float(string='Pension Deduction', compute='_compute_salary_deductions', store=True, readonly=False, digits=(16, 2))
    net_payment = fields.Float(string='Net Payment to Employee', compute='_compute_summary', store=True, digits=(16, 2))

    # Audit trail
    eligibility_notes = fields.Text(compute='_compute_eligibility_notes', store=True, string='Eligibility Assessment')

    state = fields.Selection([
        ('draft', 'Draft'), 
        ('waiting_audit', 'Waiting Audit'),
        ('waiting_payment', 'Waiting Payment'),
        ('paid', 'Paid')
    ], default='draft', tracking=True, index=True)
    notes = fields.Text(string='HR Notes')
    
    is_hr_manager = fields.Boolean(compute='_compute_is_hr_manager')

    # Tracking Fields
    processed_by_id = fields.Many2one('res.users', string='Processed By', readonly=True, tracking=True)
    processed_date = fields.Datetime(string='Date Processed', readonly=True)
    audited_by_id = fields.Many2one('res.users', string='Audited By', readonly=True, tracking=True)
    audited_date = fields.Datetime(string='Date Audited', readonly=True)
    confirmed_by_id = fields.Many2one('res.users', string='Confirmed By', readonly=True, tracking=True)
    confirmed_date = fields.Datetime(string='Date Confirmed', readonly=True)
    paid_by_id = fields.Many2one('res.users', string='Paid By', readonly=True, tracking=True)
    paid_date = fields.Datetime(string='Date Paid', readonly=True)

    def _compute_is_hr_manager(self):
        is_mgr = self.env.user.has_group('hr_resignation.group_resignation_hr_manager')
        for rec in self:
            rec.is_hr_manager = is_mgr

    # ==================================================================
    # HELPER
    # ==================================================================

    def _get_active_contract(self, employee):
        return self.env['hr.version'].sudo().search([
            ('employee_id', '=', employee.id),
            ('state', 'in', ('open', 'probation', 'close')),
        ], limit=1, order='contract_date_start desc')

    # ==================================================================
    # COMPUTES
    # ==================================================================

    @api.depends('settlement_date', 'resignation_id')
    def _compute_service_years(self):
        for rec in self:
            emp = rec.employee_id.sudo()
            if not emp:
                rec.service_years = 0.0
                rec.service_months_total = 0
                continue
                
            start = rec.resignation_id.joined_date
            if not start:
                if hasattr(emp, 'first_contract_date') and emp.first_contract_date:
                    start = emp.first_contract_date
                elif hasattr(emp, 'contract_id') and emp.contract_id and emp.contract_id.date_start:
                    start = emp.contract_id.date_start
                elif emp.start_date:
                    start = emp.start_date
                else:
                    start = emp.create_date.date()
                    
            end   = rec.settlement_date or fields.Date.today()
            if start and end and end >= start:
                d = relativedelta(end, start)
                rec.service_years        = d.years + d.months / 12.0
                rec.service_months_total = d.years * 12 + d.months
            else:
                rec.service_years        = 0.0
                rec.service_months_total = 0


    @api.depends('resignation_id.resignation_type_id', 'resignation_id.initiated_by', 'employee_id')
    def _compute_eligibility_context(self):
        for rec in self:
            sep = rec.resignation_id.resignation_type_id
            emp = rec.employee_id.sudo()
            rec.separation_reason       = sep.name if sep else ''
            rec.job_category            = emp.job_position.employee_category if emp and 'job_position' in emp._fields and emp.job_position and 'employee_category' in emp.job_position._fields else 'N/A'
            rec.is_company_terminated   = rec.resignation_id.initiated_by == 'company' or bool(sep and getattr(sep, 'is_company_terminated', False))
            rec.is_misconduct_dismissal = bool(sep and getattr(sep, 'is_misconduct_dismissal', False))
            rec.has_disciplinary_case   = False
            if emp and 'hr.disciplinary.action' in self.env:
                rec.has_disciplinary_case = bool(self.env['hr.disciplinary.action'].sudo().search([('employee_name', '=', emp.id), ('state', 'not in', ('cancel', 'completed'))], limit=1))

    @api.onchange('pf_eligible')
    def _onchange_pf_eligible(self):
        pass

    @api.onchange('severance_eligible')
    def _onchange_severance_eligible(self):
        pass

    @api.depends('resignation_id.payment_request_pf', 'resignation_id.resignation_type_id', 'service_years', 'employee_id')
    def _compute_pf_eligible(self):

        for rec in self:
            if rec.resignation_id and not rec.resignation_id.payment_request_pf:
                rec.pf_eligible = 'no'
                rec.pf_ineligible_reason = 'PF payment disabled by Gatekeeper configuration.'
                continue
                
            # Check probation completion via hr.version contract
            contract = self._get_active_contract(rec.employee_id)
            still_on_probation = contract and contract.state == 'probation'

            # Fetch minimum years from separation type, default to 2.0
            sep_type = rec.resignation_id.resignation_type_id
            min_years = sep_type.pf_min_service_years if sep_type else 2.0

            if sep_type and not sep_type.pays_provident_fund:
                rec.pf_eligible          = 'no'
                rec.pf_ineligible_reason = 'PF is disabled for this Separation Type.'
            elif rec.service_years < min_years:
                rec.pf_eligible          = 'no'
                rec.pf_ineligible_reason = (
                    'Minimum %.1f years required (Joined to Request date). '
                    'Actual: %.2f years.' % (min_years, rec.service_years)
                )
            elif still_on_probation:
                rec.pf_eligible          = 'no'
                rec.pf_ineligible_reason = (
                    'Employee has not completed probation — PF not yet eligible.'
                )
            elif rec.is_misconduct_dismissal:
                rec.pf_eligible          = 'no'
                rec.pf_ineligible_reason = 'Dismissed for misconduct — not eligible.'
            elif rec.is_company_terminated:
                rec.pf_eligible          = 'no'
                rec.pf_ineligible_reason = 'Company-terminated — not eligible.'
            else:
                rec.pf_eligible          = 'yes'
                rec.pf_ineligible_reason = ''



    @api.depends('debt_mortgage_loan', 'debt_personal_loan', 'debt_rssa_loan', 'debt_guaranteed_loan')
    def _compute_outstanding_debt(self):
        for rec in self:
            rec.outstanding_debt_deduction = (
                rec.debt_mortgage_loan +
                rec.debt_personal_loan +
                rec.debt_rssa_loan +
                rec.debt_guaranteed_loan
            )

    @api.depends('service_years', 'is_misconduct_dismissal', 'has_disciplinary_case', 'resignation_id.resignation_type_id', 'job_category', 'employee_id.job_position')
    def _compute_severance_eligible(self):
        for rec in self:
            sep_type = rec.resignation_id.resignation_type_id
            emp = rec.employee_id
            min_years = 5.0  # Fallback default
            
            job_pos = getattr(emp, 'job_position', False) or getattr(emp, 'job_id', False)
            cat_name = (rec.job_category or (getattr(job_pos, 'employee_category', '') if job_pos else '') or '').strip()
            is_mgr = 'manager' in cat_name.lower() and 'non' not in cat_name.lower()
            
            if sep_type and sep_type.pays_severance and sep_type.severance_rule_ids:
                matching_rules = sep_type.severance_rule_ids.filtered(
                    lambda r: (r.employee_category or '').strip().lower() == ('managerial' if is_mgr else 'non managerial')
                )
                if matching_rules:
                    min_years = matching_rules[0].min_service_years
            
            if sep_type and not sep_type.pays_severance:
                rec.severance_eligible          = 'no'
                rec.severance_ineligible_reason = 'Severance is disabled for this Separation Type.'
            elif rec.service_years < min_years:
                rec.severance_eligible          = 'no'
                rec.severance_ineligible_reason = 'Minimum %.1f years required (%s). Actual: %.2f years.' % (
                    min_years, 'Managerial' if is_mgr else 'Non-Managerial', rec.service_years
                )
            elif rec.is_misconduct_dismissal:
                rec.severance_eligible          = 'no'
                rec.severance_ineligible_reason = 'Dismissed for misconduct — not eligible.'
            elif rec.has_disciplinary_case:
                rec.severance_eligible          = 'no'
                rec.severance_ineligible_reason = 'Active disciplinary case — not eligible.'
            else:
                rec.severance_eligible          = 'yes'
                rec.severance_ineligible_reason = ''

    @api.depends(
        'severance_eligible', 'service_years', 'basic_salary', 'joined_date',
        'settlement_date', 'resignation_id.release_date', 'resignation_id.expected_last_day',
        'resignation_id.resignation_type_id', 'job_category', 'employee_id.job_position', 'employee_id.job_id'
    )
    def _compute_severance_amount(self):
        for rec in self:
            if rec.severance_eligible != 'yes' or rec.basic_salary <= 0:
                rec.severance_amount = 0.0
                rec.income_tax_severance = 0.0
                rec.net_severance_amount = 0.0
                rec.years_for_severance = 0.0
                if rec.severance_ineligible_reason:
                    rec.severance_breakdown_html = f"""
                    <div class="alert alert-secondary text-center p-3 my-2" role="alert">
                        <h6 class="mb-1"><i class="fa fa-info-circle me-1"></i> Not Eligible for Severance Pay</h6>
                        <small class="text-muted">{rec.severance_ineligible_reason}</small>
                    </div>
                    """
                else:
                    rec.severance_breakdown_html = False
                continue

            emp = rec.employee_id
            sep_type = rec.resignation_id.resignation_type_id
            job_pos = getattr(emp, 'job_position', False) or getattr(emp, 'job_id', False)
            cat_name = (rec.job_category or (getattr(job_pos, 'employee_category', '') if job_pos else '') or '').strip()
            is_manager = 'manager' in cat_name.lower() and 'non' not in cat_name.lower()
            category_label = 'Managerial Level' if is_manager else 'Non-Managerial Level'

            max_months = 12

            if sep_type and sep_type.pays_severance and sep_type.severance_rule_ids:
                matching_rules = sep_type.severance_rule_ids.filtered(
                    lambda r: (r.employee_category or '').strip().lower() == ('managerial' if is_manager else 'non managerial')
                )
                if matching_rules:
                    max_months = matching_rules[0].max_severance_months

            # Determine start and release / settlement dates
            start_date = rec.joined_date
            if not start_date and emp:
                start_date = getattr(emp, 'first_contract_date', False) or getattr(emp, 'start_date', False)
            end_date = rec.settlement_date or (rec.resignation_id and rec.resignation_id.release_date) or (rec.resignation_id and rec.resignation_id.expected_last_day) or fields.Date.today()

            if not start_date or not end_date or end_date < start_date:
                rec.severance_amount = 0.0
                rec.income_tax_severance = 0.0
                rec.net_severance_amount = 0.0
                rec.years_for_severance = 0.0
                rec.severance_breakdown_html = '<div class="alert alert-warning">Missing employment start date or settlement date.</div>'
                continue

            # Calculate tenure: full years and remaining calendar days (inclusive of end date)
            next_day = end_date + timedelta(days=1)
            rd = relativedelta(next_day, start_date)
            full_years = rd.years
            last_anniv = start_date + relativedelta(years=full_years)
            rem_days = (end_date - last_anniv).days + 1
            if rem_days < 0:
                rem_days = 0

            rec.years_for_severance = full_years + (rem_days / 365.0)
            basic = rec.basic_salary
            denom = 2.0 if is_manager else 3.0
            group_size = 2 if is_manager else 3
            rate_fraction_str = '1/2' if is_manager else '1/3'

            tranches = []

            # 1. First Full Year
            if full_years >= 1:
                y1_end = start_date + relativedelta(years=1) - timedelta(days=1)
                g1 = basic
                t1 = rec._calculate_tax_for_amount(g1)
                tranches.append({
                    'num': 1,
                    'desc': 'FOR THE SERVICE OF YEAR 1 (1st Full Year of service = 1 month salary)',
                    'period': f"{start_date.strftime('%b %d, %Y')} – {y1_end.strftime('%b %d, %Y')}",
                    'factor': '1.0 Month (30 Days)',
                    'gross': g1,
                    'tax': t1,
                    'net': g1 - t1,
                })

                subsequent_years = full_years - 1
                num_groups = subsequent_years // group_size
                odd_years = subsequent_years % group_size

                # Grouped subsequent years (pairs of 2 for Managerial, trios of 3 for Non-Managerial)
                for i in range(1, num_groups + 1):
                    if is_manager:
                        ys = 2 * i
                        ye = ys + 1
                        y_label = f"{ys}, {ye}"
                        factor_str = '2 Years × 15 Days = 1.0 Month'
                    else:
                        ys = 3 * i - 1
                        ye = ys + 2
                        y_label = f"{ys}, {ys+1} & {ye}"
                        factor_str = '3 Years × 10 Days = 1.0 Month'

                    p_start = start_date + relativedelta(years=ys - 1)
                    p_end = start_date + relativedelta(years=ye) - timedelta(days=1)
                    g = basic
                    t = rec._calculate_tax_for_amount(g)
                    tranches.append({
                        'num': len(tranches) + 1,
                        'desc': f"FOR THE SERVICE OF YEAR {y_label} ({rate_fraction_str} of basic salary each)",
                        'period': f"{p_start.strftime('%b %d, %Y')} – {p_end.strftime('%b %d, %Y')}",
                        'factor': factor_str,
                        'gross': g,
                        'tax': t,
                        'net': g - t,
                    })

                # Remaining years after full groups (odd_years) + fractional days (rem_days):
                # calculate in ONE final tranche by converting remaining years to days (365/yr)
                if odd_years > 0 or rem_days > 0:
                    ys = full_years - odd_years + 1 if odd_years > 0 else full_years + 1
                    p_start = start_date + relativedelta(years=ys - 1) if odd_years > 0 else last_anniv
                    p_end = end_date
                    total_rem_days = (odd_years * 365) + rem_days
                    g = round((basic / denom / 365.0) * total_rem_days, 2)
                    t = round(rec._calculate_tax_for_amount(g), 2)
                    if odd_years > 0 and rem_days > 0:
                        yr_lbl = f"{odd_years} Yr{'s' if odd_years > 1 else ''}"
                        year_span = f"{ys} to {full_years}" if odd_years > 1 else f"{ys}"
                        desc_str = (
                            f"FOR THE SERVICE OF YEAR {year_span} & remaining "
                            f"({rate_fraction_str} of basic salary for {total_rem_days} Days: {yr_lbl} × 365 + {rem_days} Days)"
                        )
                        factor_str = f"Prorated ({total_rem_days}/365 Days)"
                    elif odd_years > 0:
                        y_label = f"{ys}" if odd_years == 1 else f"{ys} & {full_years}"
                        days_awarded = (15 if is_manager else 10) * odd_years
                        desc_str = f"FOR THE SERVICE OF YEAR {y_label} ({rate_fraction_str} of basic salary each)"
                        factor_str = (
                            f"{odd_years} Year{'s' if odd_years > 1 else ''} × "
                            f"{15 if is_manager else 10} Days = {days_awarded} Days ({total_rem_days}/365 Days)"
                        )
                    else:
                        desc_str = f"FOR THE SERVICE OF YEAR {full_years} years & remaining ({rate_fraction_str} of basic salary for {rem_days} Days)"
                        factor_str = f"Prorated ({rem_days}/365 Days)"

                    tranches.append({
                        'num': len(tranches) + 1,
                        'desc': desc_str,
                        'period': f"{p_start.strftime('%b %d, %Y')} – {p_end.strftime('%b %d, %Y')}",
                        'factor': factor_str,
                        'gross': g,
                        'tax': t,
                        'net': g - t,
                    })
            elif rem_days > 0:
                # Less than 1 full year
                g = round((basic / 365.0) * rem_days, 2)
                t = rec._calculate_tax_for_amount(g)
                tranches.append({
                    'num': 1,
                    'desc': f"FOR THE SERVICE OF YEAR 1 ({rem_days} Days)",
                    'period': f"{start_date.strftime('%b %d, %Y')} – {end_date.strftime('%b %d, %Y')}",
                    'factor': f"Prorated ({rem_days}/365 Days)",
                    'gross': g,
                    'tax': t,
                    'net': g - t,
                })

            raw_gross = sum(t['gross'] for t in tranches)
            raw_tax = sum(t['tax'] for t in tranches)
            raw_net = raw_gross - raw_tax

            # Check statutory cap
            max_cap = basic * max_months
            is_capped = raw_gross > max_cap
            if is_capped:
                final_gross = max_cap
                tax_ratio = max_cap / raw_gross if raw_gross > 0 else 1.0
                final_tax = round(raw_tax * tax_ratio, 2)
                final_net = round(final_gross - final_tax, 2)
            else:
                final_gross = round(raw_gross, 2)
                final_tax = round(raw_tax, 2)
                final_net = round(raw_net, 2)

            rec.severance_amount = final_gross
            rec.income_tax_severance = final_tax
            rec.net_severance_amount = final_net

            # Render HTML breakdown table
            rows_html = ""
            for t in tranches:
                rows_html += f"""
                <tr style="border-bottom: 1px solid #dee2e6;">
                    <td style="text-align: center; font-weight: bold; color: #495057;">{t['num']}</td>
                    <td>
                        <div style="font-weight: 600; color: #212529;">{t['desc']}</div>
                    </td>
                    <td style="font-size: 0.9em; color: #6c757d; white-space: nowrap;">{t['period']}</td>
                    <td style="text-align: center;"><span class="badge bg-light text-dark border">{t['factor']}</span></td>
                    <td style="text-align: right; font-family: monospace;">{t['gross']:,.2f}</td>
                    <td style="text-align: right; font-family: monospace; color: #dc3545;">{t['tax']:,.2f}</td>
                    <td style="text-align: right; font-family: monospace; font-weight: bold; color: #198754;">{t['net']:,.2f}</td>
                </tr>
                """

            rec.severance_breakdown_html = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; padding: 5px 0;">
                <!-- Top Metrics Cards -->
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 16px;">
                    <div style="background: #f8f9fa; border: 1px solid #e9ecef; border-left: 4px solid #0d6efd; border-radius: 6px; padding: 10px 14px;">
                        <div style="font-size: 0.75em; text-transform: uppercase; color: #6c757d; font-weight: bold;">Employee Category</div>
                        <div style="font-size: 1.15em; font-weight: bold; color: #0d6efd; margin-top: 2px;">{category_label}</div>
                        <div style="font-size: 0.8em; color: #495057; margin-top: 3px;">
                            Formula: <strong>1 mo. Yr 1 + {rate_fraction_str} mo./yr</strong> (Severance.xlsx)
                        </div>
                    </div>
                    
                    <div style="background: #f8f9fa; border: 1px solid #e9ecef; border-left: 4px solid #0dcaf0; border-radius: 6px; padding: 10px 14px;">
                        <div style="font-size: 0.75em; text-transform: uppercase; color: #6c757d; font-weight: bold;">Tenure &amp; Dates</div>
                        <div style="font-size: 1.15em; font-weight: bold; color: #212529; margin-top: 2px;">{full_years} Yrs + {rem_days} Days</div>
                        <div style="font-size: 0.8em; color: #6c757d; margin-top: 3px;">
                            {start_date.strftime('%b %d, %Y')} to {end_date.strftime('%b %d, %Y')}
                        </div>
                    </div>

                    <div style="background: #f8f9fa; border: 1px solid #e9ecef; border-left: 4px solid #198754; border-radius: 6px; padding: 10px 14px;">
                        <div style="font-size: 0.75em; text-transform: uppercase; color: #6c757d; font-weight: bold;">Severance Summary</div>
                        <div style="display: flex; justify-content: space-between; margin-top: 2px;">
                            <span style="font-size: 0.85em; color: #495057;">Gross Entitlement:</span>
                            <strong style="font-family: monospace;">{final_gross:,.2f} ETB</strong>
                        </div>
                        <div style="display: flex; justify-content: space-between; margin-top: 2px;">
                            <span style="font-size: 0.85em; color: #dc3545;">Total Income Tax:</span>
                            <strong style="font-family: monospace; color: #dc3545;">- {final_tax:,.2f} ETB</strong>
                        </div>
                        <div style="display: flex; justify-content: space-between; margin-top: 3px; padding-top: 3px; border-top: 1px dashed #ced4da;">
                            <span style="font-weight: bold; color: #198754; font-size: 0.9em;">Net Severance:</span>
                            <strong style="font-family: monospace; color: #198754; font-size: 1.1em;">{final_net:,.2f} ETB</strong>
                        </div>
                    </div>
                </div>

                <!-- Tranche Table -->
                <div style="overflow-x: auto; border: 1px solid #dee2e6; border-radius: 6px;">
                    <table class="table table-hover table-sm mb-0" style="width: 100%; border-collapse: collapse; margin-bottom: 0;">
                        <thead style="background: #f1f3f5; border-bottom: 2px solid #dee2e6;">
                            <tr>
                                <th style="padding: 8px 10px; text-align: center; width: 35px;">#</th>
                                <th style="padding: 8px 10px;">Severance Computation Tranche</th>
                                <th style="padding: 8px 10px;">Calendar Interval</th>
                                <th style="padding: 8px 10px; text-align: center;">Factor / Days</th>
                                <th style="padding: 8px 10px; text-align: right;">Gross Severance (ETB)</th>
                                <th style="padding: 8px 10px; text-align: right;">Income Tax (ETB)</th>
                                <th style="padding: 8px 10px; text-align: right;">Net Severance (ETB)</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows_html}
                        </tbody>
                        <tfoot style="background: #e9ecef; font-weight: bold; border-top: 2px solid #adb5bd;">
                            <tr>
                                <td colspan="4" style="padding: 10px; text-align: right; text-transform: uppercase; letter-spacing: 0.5px;">
                                    Total Severance Entitlement
                                </td>
                                <td style="padding: 10px; text-align: right; font-family: monospace; font-size: 1.05em; color: #0d6efd;">
                                    {final_gross:,.2f}
                                </td>
                                <td style="padding: 10px; text-align: right; font-family: monospace; font-size: 1.05em; color: #dc3545;">
                                    {final_tax:,.2f}
                                </td>
                                <td style="padding: 10px; text-align: right; font-family: monospace; font-size: 1.1em; color: #198754; background: #d1e7dd;">
                                    {final_net:,.2f}
                                </td>
                            </tr>
                        </tfoot>
                    </table>
                </div>

                <!-- Footnote / Statutory Reference -->
                <div style="margin-top: 10px; font-size: 0.8em; color: #6c757d; line-height: 1.4; padding: 6px 10px; background: #f8f9fa; border-radius: 4px; border: 1px solid #e9ecef;">
                    <strong>Note:</strong> Severance tax is computed individually per full-month salary tranche under the Ethiopian Progressive Tax schedule <em>(Tax = Amount × 35% - 2,050.00 ETB)</em>, and remaining days are taxed at the applicable progressive bracket. Statutory {max_months}-month severance cap = <strong>{max_cap:,.2f} ETB</strong> ({'Cap Applied' if is_capped else 'Within statutory limit'}).
                </div>
            </div>
            """

    @api.depends(
        'resignation_id.total_accrued_leave', 'resignation_id.total_scheduled_leave',
        'basic_salary', 'resignation_id.payment_request_leave_pay', 'resignation_id.resignation_type_id'
    )
    def _compute_accrued_leave_pay(self):
        for rec in self:
            sep_type = rec.resignation_id.resignation_type_id if rec.resignation_id else False
            if sep_type and not sep_type.allow_leave_encashment:
                rec.accrued_leave_pay = 0.0
                rec.income_tax_leave = 0.0
                rec.net_accrued_leave_pay = 0.0
                rec.accrued_leave_breakdown_html = f"""
                <div class="alert alert-secondary text-center p-3 my-2" role="alert">
                    <h6 class="mb-1"><i class="fa fa-info-circle me-1"></i> Leave Encashment Not Applicable</h6>
                    <small class="text-muted">Leave encashment is disabled for separation type: <strong>{sep_type.name}</strong>.</small>
                </div>
                """
                continue

            if rec.resignation_id and not rec.resignation_id.payment_request_leave_pay:
                rec.accrued_leave_pay = 0.0
                rec.income_tax_leave = 0.0
                rec.net_accrued_leave_pay = 0.0
                rec.accrued_leave_breakdown_html = """
                <div class="alert alert-secondary text-center p-3 my-2" role="alert">
                    <h6 class="mb-1"><i class="fa fa-info-circle me-1"></i> Leave Encashment Disabled</h6>
                    <small class="text-muted">Payment request for accrued leave was not selected on the resignation request.</small>
                </div>
                """
                continue

            if rec.basic_salary <= 0:
                rec.accrued_leave_pay = 0.0
                rec.income_tax_leave = 0.0
                rec.net_accrued_leave_pay = 0.0
                rec.accrued_leave_breakdown_html = """
                <div class="alert alert-warning text-center p-3 my-2" role="alert">
                    <h6 class="mb-1"><i class="fa fa-exclamation-triangle me-1"></i> Basic Salary Required</h6>
                    <small class="text-muted">Basic salary is 0.00 ETB. Please verify the active contract.</small>
                </div>
                """
                continue

            accrued_w_days = (rec.resignation_id.total_accrued_leave or 0.0) if rec.resignation_id else 0.0
            scheduled_w_days = (rec.resignation_id.total_scheduled_leave or 0.0) if rec.resignation_id else 0.0
            total_working_days = accrued_w_days + scheduled_w_days

            if total_working_days <= 0:
                rec.accrued_leave_pay = 0.0
                rec.income_tax_leave = 0.0
                rec.net_accrued_leave_pay = 0.0
                rec.accrued_leave_breakdown_html = """
                <div class="alert alert-info text-center p-3 my-2" role="alert">
                    <h6 class="mb-1"><i class="fa fa-info-circle me-1"></i> Zero Accrued Leave</h6>
                    <small class="text-muted">No accrued or scheduled leave days recorded for this employee.</small>
                </div>
                """
                continue

            # Ethiopian standard conversion factor: 1.3273 (converts working days to calendar days)
            conversion_factor = 1.3273
            total_calendar_days = total_working_days * conversion_factor
            daily_rate = round(rec.basic_salary / 30.0, 4)

            # Build 30-day tranches / chunks
            chunks = []
            days_rem = total_calendar_days
            chunk_num = 1

            while days_rem > 0.0001:
                chunk_cal_days = min(30.0, days_rem)
                chunk_work_days = chunk_cal_days / conversion_factor
                chunk_gross = round(daily_rate * chunk_cal_days, 2)
                chunk_tax = round(rec._calculate_tax_for_amount(chunk_gross), 2)
                chunk_net = round(chunk_gross - chunk_tax, 2)

                is_full = chunk_cal_days >= 29.99
                desc = f"Tranche {chunk_num}: Full Month Chunk (30.00 Calendar Days)" if is_full else f"Tranche {chunk_num}: Remaining Prorated Chunk ({chunk_cal_days:.2f} Calendar Days)"

                chunks.append({
                    'num': chunk_num,
                    'desc': desc,
                    'cal_days': chunk_cal_days,
                    'work_days': chunk_work_days,
                    'daily_rate': daily_rate,
                    'gross': chunk_gross,
                    'tax': chunk_tax,
                    'net': chunk_net,
                })
                days_rem -= chunk_cal_days
                chunk_num += 1

            total_gross = sum(c['gross'] for c in chunks)
            total_tax = sum(c['tax'] for c in chunks)
            total_net = total_gross - total_tax

            rec.accrued_leave_pay = total_gross
            rec.income_tax_leave = total_tax
            rec.net_accrued_leave_pay = total_net

            # Render HTML breakdown table matching Severance styling
            rows_html = ""
            for c in chunks:
                rows_html += f"""
                <tr style="border-bottom: 1px solid #dee2e6;">
                    <td style="text-align: center; font-weight: bold; color: #495057;">{c['num']}</td>
                    <td>
                        <div style="font-weight: 600; color: #212529;">{c['desc']}</div>
                    </td>
                    <td style="text-align: center;"><span class="badge bg-light text-dark border">{c['cal_days']:.2f} Days</span></td>
                    <td style="text-align: center;"><span class="badge bg-light text-dark border">{c['work_days']:.2f} Days</span></td>
                    <td style="text-align: right; font-family: monospace;">{c['daily_rate']:,.2f}</td>
                    <td style="text-align: right; font-family: monospace;">{c['gross']:,.2f}</td>
                    <td style="text-align: right; font-family: monospace; color: #dc3545;">{c['tax']:,.2f}</td>
                    <td style="text-align: right; font-family: monospace; font-weight: bold; color: #198754;">{c['net']:,.2f}</td>
                </tr>
                """

            rec.accrued_leave_breakdown_html = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; padding: 5px 0;">
                <!-- Top Metrics Cards -->
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; margin-bottom: 16px;">
                    <div style="background: #f8f9fa; border: 1px solid #e9ecef; border-left: 4px solid #0d6efd; border-radius: 6px; padding: 10px 14px;">
                        <div style="font-size: 0.75em; text-transform: uppercase; color: #6c757d; font-weight: bold;">Leave Working Days</div>
                        <div style="font-size: 1.15em; font-weight: bold; color: #0d6efd; margin-top: 2px;">{total_working_days:,.2f} Days</div>
                        <div style="font-size: 0.8em; color: #495057; margin-top: 3px;">
                            Accrued: <strong>{accrued_w_days:,.2f}</strong> | Sched: <strong>{scheduled_w_days:,.2f}</strong>
                        </div>
                    </div>
                    
                    <div style="background: #f8f9fa; border: 1px solid #e9ecef; border-left: 4px solid #0dcaf0; border-radius: 6px; padding: 10px 14px;">
                        <div style="font-size: 0.75em; text-transform: uppercase; color: #6c757d; font-weight: bold;">Calendar Equivalent</div>
                        <div style="font-size: 1.15em; font-weight: bold; color: #055160; margin-top: 2px;">{total_calendar_days:,.2f} Days</div>
                        <div style="font-size: 0.8em; color: #495057; margin-top: 3px;">
                            Factor: <strong>{conversion_factor}</strong> ({total_working_days:,.2f} × 1.3273)
                        </div>
                    </div>

                    <div style="background: #f8f9fa; border: 1px solid #e9ecef; border-left: 4px solid #6f42c1; border-radius: 6px; padding: 10px 14px;">
                        <div style="font-size: 0.75em; text-transform: uppercase; color: #6c757d; font-weight: bold;">Daily Salary Rate</div>
                        <div style="font-size: 1.15em; font-weight: bold; color: #6f42c1; margin-top: 2px;">{daily_rate:,.2f} ETB</div>
                        <div style="font-size: 0.8em; color: #495057; margin-top: 3px;">
                            Basic Salary: <strong>{rec.basic_salary:,.2f}</strong> ÷ 30
                        </div>
                    </div>

                    <div style="background: #f8f9fa; border: 1px solid #e9ecef; border-left: 4px solid #198754; border-radius: 6px; padding: 10px 14px;">
                        <div style="font-size: 0.75em; text-transform: uppercase; color: #6c757d; font-weight: bold;">Leave Summary</div>
                        <table style="width: 100%; font-size: 0.82em; margin-top: 2px;">
                            <tr>
                                <td style="color: #6c757d;">Gross Entitlement:</td>
                                <td style="text-align: right; font-weight: bold; font-family: monospace;">{total_gross:,.2f} ETB</td>
                            </tr>
                            <tr>
                                <td style="color: #dc3545;">Total Income Tax:</td>
                                <td style="text-align: right; color: #dc3545; font-family: monospace;">- {total_tax:,.2f} ETB</td>
                            </tr>
                            <tr style="border-top: 1px dashed #ced4da;">
                                <td style="font-weight: bold; color: #198754; padding-top: 2px;">Net Leave Pay:</td>
                                <td style="text-align: right; font-weight: bold; color: #198754; font-family: monospace; padding-top: 2px;">{total_net:,.2f} ETB</td>
                            </tr>
                        </table>
                    </div>
                </div>

                <!-- Tranche Breakdown Table -->
                <div style="overflow-x: auto; border: 1px solid #dee2e6; border-radius: 6px; background: #fff;">
                    <table class="table table-sm table-hover mb-0" style="width: 100%; font-size: 0.88em; border-collapse: collapse;">
                        <thead style="background: #f1f3f5; border-bottom: 2px solid #dee2e6; color: #495057;">
                            <tr>
                                <th style="width: 40px; text-align: center; padding: 8px;">#</th>
                                <th style="padding: 8px;">Leave Computation Chunk / Tranche</th>
                                <th style="text-align: center; padding: 8px;">Calendar Days</th>
                                <th style="text-align: center; padding: 8px;">Working Equivalent</th>
                                <th style="text-align: right; padding: 8px;">Daily Rate (ETB)</th>
                                <th style="text-align: right; padding: 8px;">Gross Leave (ETB)</th>
                                <th style="text-align: right; padding: 8px;">Income Tax (ETB)</th>
                                <th style="text-align: right; padding: 8px;">Net Leave (ETB)</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows_html}
                        </tbody>
                        <tfoot style="background: #e9ecef; font-weight: bold; border-top: 2px solid #adb5bd;">
                            <tr>
                                <td colspan="2" style="text-align: right; padding: 8px; text-transform: uppercase;">TOTAL ACCRUED LEAVE PAY</td>
                                <td style="text-align: center; padding: 8px; font-family: monospace;">{total_calendar_days:,.2f}</td>
                                <td style="text-align: center; padding: 8px; font-family: monospace;">{total_working_days:,.2f}</td>
                                <td style="text-align: right; padding: 8px; font-family: monospace;">-</td>
                                <td style="text-align: right; padding: 8px; font-family: monospace; color: #0d6efd;">{total_gross:,.2f}</td>
                                <td style="text-align: right; padding: 8px; font-family: monospace; color: #dc3545;">{total_tax:,.2f}</td>
                                <td style="text-align: right; padding: 8px; font-family: monospace; color: #198754;">{total_net:,.2f}</td>
                            </tr>
                        </tfoot>
                    </table>
                </div>
                
                <div style="font-size: 0.78em; color: #6c757d; margin-top: 8px; font-style: italic;">
                    Note: Accrued leave working days are converted to calendar days using the statutory 1.3273 conversion factor. Tax is computed individually per 30-day monthly salary tranche under the Ethiopian Progressive Tax schedule.
                </div>
            </div>
            """
    @api.depends('settlement_date', 'resignation_id.release_date', 'resignation_id.expected_last_day')
    def _compute_worked_days_default(self):
        """Auto-fill worked days from release date day or expected last day. POMD can override the stored value."""
        for rec in self:
            release_date = rec.settlement_date or (rec.resignation_id and rec.resignation_id.release_date) or (rec.resignation_id and rec.resignation_id.expected_last_day) or fields.Date.today()
            if release_date:
                rec.worked_days_final_month = release_date.day
            else:
                rec.worked_days_final_month = 30

    @api.depends('basic_salary', 'worked_days_final_month', 'resignation_id.payment_request_unpaid_salary')
    def _compute_remaining_salary(self):
        for rec in self:
            if rec.resignation_id and rec.resignation_id.resignation_type_id and not rec.resignation_id.resignation_type_id.allow_salary_payment:
                rec.remaining_salary = 0.0
                rec.remaining_salary_notes = 'Salary payment disabled by Gatekeeper configuration.'
                continue

            worked_days = rec.worked_days_final_month
            basic = rec.basic_salary

            if not worked_days or basic <= 0:
                rec.remaining_salary = 0.0
                rec.remaining_salary_notes = 'No worked days or salary entered.'
            else:
                # Fixed 30-day month basis
                daily_rate = basic / 30.0
                rec.remaining_salary = daily_rate * worked_days
                rec.remaining_salary_notes = f"{worked_days} days × ({basic:,.2f} ÷ 30) = {rec.remaining_salary:,.2f}"

    @api.depends('cbs_start_date', 'cbs_end_date')
    def _compute_cash_indemnity_days(self):
        """
        Placeholder logic for cash indemnity working days calculation.
        """
        for rec in self:
            if rec.cbs_start_date and rec.cbs_end_date and rec.cbs_end_date >= rec.cbs_start_date:
                rec.cash_indemnity_working_days = (rec.cbs_end_date - rec.cbs_start_date).days + 1
            else:
                rec.cash_indemnity_working_days = 0

    @api.depends('remaining_salary')
    def _compute_salary_deductions(self):
        for rec in self:
            if rec.remaining_salary > 0:
                rec.income_tax_deduction = rec._calculate_tax_for_amount(rec.remaining_salary)
                # Standard Ethiopian employee pension deduction is 7%
                rec.pension_deduction = rec.remaining_salary * 0.07
            else:
                rec.income_tax_deduction = 0.0
                rec.pension_deduction = 0.0

    def _calculate_tax_for_amount(self, amount):
        if amount <= 0:
            return 0.0
        tax = 0.0
        brackets = self.env['hr.resignation.tax.bracket'].sudo().search([])
        for bracket in brackets:
            if bracket.max_amount == 0.0:
                if amount >= bracket.min_amount:
                    tax = (amount * bracket.tax_rate) - bracket.deduction
                    break
            else:
                if bracket.min_amount <= amount <= bracket.max_amount:
                    tax = (amount * bracket.tax_rate) - bracket.deduction
                    break
        return max(0.0, tax)

    def _compute_income_tax_severance(self):
        """Handled directly inside _compute_severance_amount for exact per-tranche tax audit."""
        for rec in self:
            if not rec.income_tax_severance and rec.severance_amount > 0:
                rec._compute_severance_amount()

    @api.depends('line_ids.amount', 'line_ids.line_type', 'line_ids.is_taxable')
    def _compute_summary(self):
        for rec in self:
            taxable = 0.0
            earnings = 0.0
            deductions = 0.0
            for line in rec.line_ids:
                if line.line_type == 'earning':
                    earnings += line.amount
                    if line.is_taxable:
                        taxable += line.amount
                else:
                    deductions += line.amount
            
            rec.taxable_gross = taxable
            rec.total_earnings = earnings
            rec.total_deductions_taxes = deductions
            rec.net_payment = earnings - deductions
            rec.total_payment = earnings



    def _compute_total(self):
        """Maintained for backwards-compatibility; delegates to _compute_summary."""
        self._compute_summary()

    def _get_payroll_allowances(self):
        """
        Dynamically calculate allowances based on employee's Grade, Position,
        and configured Salary Rules (grade_rules and position_rules in bunna_hr_payroll).
        Returns a list of dicts: [{'name': ..., 'amount': ..., 'is_taxable': ..., 'notes': ...}]
        """
        self.ensure_one()
        emp = self.employee_id
        if not emp:
            return []

        worked_days = self.worked_days_final_month or 0
        if worked_days <= 0:
            return []
        proportion = worked_days / 30.0

        contract = self.resignation_id.current_version_id if self.resignation_id else False
        emp_grade = getattr(emp, 'grade_id', False) or getattr(emp, 'job_grade', False)
        if not emp_grade and contract and hasattr(contract, 'grade_id'):
            emp_grade = contract.grade_id

        emp_pos = getattr(emp, 'job_position', False) or getattr(emp, 'job_id', False)
        if not emp_pos and contract and hasattr(contract, 'job_id'):
            emp_pos = contract.job_id

        grade_code = ''
        if emp_grade:
            grade_code = (getattr(emp_grade, 'grade_code', '') or getattr(emp_grade, 'name', '') or '').strip().upper().replace('GRADE', '').strip()

        allowance_lines = []
        handled_rule_ids = set()

        SalaryRule = self.env['hr.salary.rule'].sudo()
        alw_rules = SalaryRule.search([
            '|', ('category_id.code', '=', 'ALW'),
            '|', ('grade_rules', '!=', False),
            ('position_rules', '!=', False)
        ])

        # Standard Bunna Bank grade-based maps
        housing_map = {
            'I': 500.0, 'II': 500.0, 'III': 500.0, 'IV': 500.0, 'V': 500.0, 'VI': 500.0,
            'VII': 1000.0, 'VIII': 1000.0, 'IX': 1000.0, 'X': 1000.0,
            'XI': 1500.0, 'XII': 1500.0,
            'XIII': 3000.0, 'XIII/T': 3000.0, 'XIV': 3000.0,
            'XV': 5000.0, 'XVI': 6000.0, 'XVII': 12000.0, 'XVIII': 12000.0,
            '1': 500.0, '2': 500.0, '3': 500.0, '4': 500.0, '5': 500.0, '6': 500.0,
            '7': 1000.0, '8': 1000.0, '9': 1000.0, '10': 1000.0,
            '11': 1500.0, '12': 1500.0, '13': 3000.0, '14': 3000.0,
            '15': 5000.0, '16': 6000.0, '17': 12000.0, '18': 12000.0,
        }
        liters_map = {
            'I': 40, 'II': 40, 'III': 40, 'IV': 40, 'V': 40,
            'VI': 60, 'VII': 60,
            'VIII': 80, 'IX': 80, 'X': 80,
            'XI': 100, 'XII': 100, 'XIII': 100, 'XIV': 100, 'XV': 100, 'XVI': 100,
            'XVII': 100, 'XVIII': 100, 'XIX': 100, 'XX': 100,
            '1': 40, '2': 40, '3': 40, '4': 40, '5': 40,
            '6': 60, '7': 60, '8': 80, '9': 80, '10': 80,
            '11': 100, '12': 100, '13': 100, '14': 100, '15': 100, '16': 100,
            '17': 100, '18': 100,
        }
        rep_map = {
            'XIII': 4342.0, 'XIV': 5052.0, 'XV': 6273.0, 'XVI': 8790.0, 'XVII': 14359.0, 'XVIII': 32717.0,
            '13': 4342.0, '14': 5052.0, '15': 6273.0, '16': 8790.0, '17': 14359.0, '18': 32717.0,
        }

        for rule in alw_rules:
            if rule.id in handled_rule_ids:
                continue
            rule_code = (rule.code or '').strip().upper()
            monthly_val = 0.0
            source_note = ''

            # 1. Match Grade Rules tab on the salary rule
            if emp_grade and hasattr(rule, 'grade_rules') and rule.grade_rules:
                matching_grade = rule.grade_rules.filtered(
                    lambda r: r.grade2 == emp_grade or (
                        r.grade2 and (r.grade2.grade_code or '').strip().upper() == (emp_grade.grade_code or '').strip().upper()
                    )
                )
                if matching_grade:
                    monthly_val = matching_grade[0].value or matching_grade[0].base_salary or 0.0
                    source_note = f"Grade Rule ({emp_grade.name or emp_grade.grade_code})"

            # 2. Match Position Rules tab on the salary rule
            if not monthly_val and emp_pos and hasattr(rule, 'position_rules') and rule.position_rules:
                matching_pos = rule.position_rules.filtered(lambda r: r.position == emp_pos)
                if matching_pos:
                    monthly_val = matching_pos[0].value or 0.0
                    source_note = f"Position Rule ({emp_pos.name})"

            # 3. Fallback to standard payroll scale logic if not directly set on tabs
            if not monthly_val:
                if rule_code == 'HOUSERENT' or 'HOUSING' in (rule.name or '').upper():
                    monthly_val = housing_map.get(grade_code, 0.0)
                    if monthly_val:
                        source_note = f"Housing Scale (Grade {grade_code})"
                elif rule_code == 'FUEL' or 'FUEL' in (rule.name or '').upper():
                    liters = liters_map.get(grade_code, 0)
                    monthly_val = liters * 86.0  # Standard fuel rate in payroll rules
                    if monthly_val:
                        source_note = f"Fuel Scale ({liters}L @ 86.00)"
                elif rule_code in ('RA', 'REPRESENTATION') or 'REPRESENTATION' in (rule.name or '').upper():
                    monthly_val = rep_map.get(grade_code, 0.0)
                    if monthly_val:
                        source_note = f"Representation Scale (Grade {grade_code})"
                elif rule_code in ('CIA-ALL', 'CASH_INDEMNITY') or 'CASH INDEMNITY' in (rule.name or '').upper():
                    if self.cbs_indemnity_amount > 0:
                        continue  # Handled via CBS calculation
                    if emp_pos and hasattr(rule, 'position_rules') and rule.position_rules:
                        m_pos = rule.position_rules.filtered(lambda r: r.position == emp_pos)
                        if m_pos:
                            monthly_val = m_pos[0].value or 0.0
                            source_note = f"Position Scale ({emp_pos.name})"

            if monthly_val > 0:
                prorated = round(monthly_val * proportion, 2)
                is_taxable = True
                if 'TRANSPORT' in rule_code or 'TRANSPORT' in (rule.name or '').upper():
                    is_taxable = False  # Exempt up to standard allowance threshold

                allowance_lines.append({
                    'name': rule.name,
                    'amount': prorated,
                    'is_taxable': is_taxable,
                    'notes': f"{source_note}: {worked_days}/30 days × {monthly_val:,.2f} = {prorated:,.2f}"
                })
                handled_rule_ids.add(rule.id)

        return allowance_lines

    def _get_payroll_adjustment_deductions(self):
        """
        Dynamically fetch active payroll adjustment deductions for the employee
        (e.g., Cost Sharing, Labour Union, ASBEZA, OD, Court Deductions).
        """
        self.ensure_one()
        emp = self.employee_id
        if not emp or 'hr.payroll.adjustment.line' not in self.env:
            return []

        adj_lines = self.env['hr.payroll.adjustment.line'].sudo().search([
            ('employee_id', '=', emp.id),
            ('active', '=', True),
            ('adjustment_id.active', '=', True),
        ])

        deduction_lines = []
        for adj in adj_lines:
            amt = adj.amount or 0.0
            if amt <= 0:
                continue

            code = (adj.code or (adj.adjustment_id and adj.adjustment_id.code) or '').strip().upper()
            adj_name = adj.adjustment_id.name if adj.adjustment_id else (adj.comments or 'Deduction')
            if code in ('CIA-ALL', 'CIAB', 'CASH_INDEMNITY') or 'CASH INDEMNITY' in adj_name.upper():
                continue

            deduction_lines.append({
                'name': adj_name,
                'amount': round(amt, 2),
                'is_taxable': False,
                'notes': adj.comments or f"Payroll Adjustment ({code or 'DED'})"
            })

        return deduction_lines

    def action_generate_lines(self):
        for rec in self:
            if rec.resignation_id and not rec.resignation_id.settlement_id:
                rec.resignation_id.sudo().write({'settlement_id': rec.id})
                
            rec.line_ids.unlink()
            
            line_vals_list = []
            settlement_id = rec.id
            resignation_id = rec.resignation_id.id if rec.resignation_id else False

            # Helper for adding lines
            def add_line(name, amount, line_type='earning', is_taxable=True, notes='', allow_zero=False):
                if amount > 0 or allow_zero:
                    line_vals_list.append({
                        'settlement_id': settlement_id,
                        'resignation_id': resignation_id,
                        'name': name,
                        'line_type': line_type,
                        'is_taxable': is_taxable,
                        'amount': round(amount, 2),
                        'notes': notes or False,
                    })

            # --- 1. SEVERANCE PAY & TAX ---
            if rec.severance_eligible == 'yes' and rec.severance_amount > 0:
                add_line('Severance Pay', rec.severance_amount, line_type='earning', is_taxable=True)
                if rec.income_tax_severance > 0:
                    add_line('Severance Income Tax', rec.income_tax_severance, line_type='tax', is_taxable=False)
            else:
                reason = rec.severance_ineligible_reason or 'Not Eligible for Severance'
                add_line('Severance Pay', 0.0, line_type='earning', is_taxable=True, notes=f"Not Eligible: {reason}", allow_zero=True)
            
            # --- 2. FINAL MONTH BASIC SALARY (PRORATED) ---
            if rec.remaining_salary > 0:
                add_line('Remaining Basic Salary', rec.remaining_salary, line_type='earning', is_taxable=True, notes=rec.remaining_salary_notes)
            else:
                add_line('Remaining Basic Salary', 0.0, line_type='earning', is_taxable=True, notes=rec.remaining_salary_notes or 'Not Eligible: 0 worked days or disabled by policy', allow_zero=True)

            # --- 3. DYNAMIC ALLOWANCES FROM SALARY RULES (GRADE & POSITION) ---
            allowances = rec._get_payroll_allowances()
            for alw in allowances:
                add_line(alw['name'], alw['amount'], line_type='earning', is_taxable=alw.get('is_taxable', True), notes=alw.get('notes', ''))

            # --- 4. ACCRUED LEAVE PAY & TAX ---
            if rec.accrued_leave_pay > 0:
                add_line('Accrued Leave Pay', rec.accrued_leave_pay, line_type='earning', is_taxable=True, notes=rec.accrued_leave_notes)
                if rec.income_tax_leave > 0:
                    add_line('Leave Income Tax', rec.income_tax_leave, line_type='tax', is_taxable=False)
            else:
                leave_reason = 'Not Eligible: No accrued leave days or encashment disabled'
                if rec.resignation_id and rec.resignation_id.resignation_type_id and not rec.resignation_id.resignation_type_id.allow_leave_encashment:
                    leave_reason = 'Not Eligible: Leave encashment disabled by Separation Type'
                add_line('Accrued Leave Pay', 0.0, line_type='earning', is_taxable=True, notes=leave_reason, allow_zero=True)

            # --- 5. PROVIDENT FUND ---
            if rec.pf_eligible == 'yes' and rec.pf_amount > 0:
                add_line('Provident Fund', rec.pf_amount, line_type='earning', is_taxable=False)
            else:
                reason = rec.pf_ineligible_reason or 'Not Eligible for Provident Fund'
                add_line('Provident Fund', 0.0, line_type='earning', is_taxable=False, notes=f"Not Eligible: {reason}", allow_zero=True)
            
            # --- 6. STATUTORY DEDUCTIONS & TAXES ---
            # Compute progressive income tax on total taxable salary + allowances
            taxable_salary_earnings = rec.remaining_salary + sum(alw['amount'] for alw in allowances if alw.get('is_taxable'))
            rec.income_tax_deduction = round(rec._calculate_tax_for_amount(taxable_salary_earnings), 2)
            rec.pension_deduction = round(rec.remaining_salary * 0.07, 2)

            if rec.income_tax_deduction > 0:
                add_line('Income Tax (Salary & Allowances)', rec.income_tax_deduction, line_type='tax', is_taxable=False)
            if rec.pension_deduction > 0:
                add_line('Pension Deduction (7%)', rec.pension_deduction, line_type='deduction', is_taxable=False)
                
            # --- 7. DYNAMIC PAYROLL ADJUSTMENTS (Cost Sharing, Union, ASBEZA, OD, etc.) ---
            adj_deductions = rec._get_payroll_adjustment_deductions()
            for ded in adj_deductions:
                add_line(ded['name'], ded['amount'], line_type='deduction', is_taxable=False, notes=ded.get('notes', ''))

            # --- 8. SEPARATION LIABILITIES ---
            liability_amount = rec.resignation_id.liability or 0.0
            if liability_amount > 0:
                add_line('Notice Period Liability (1 Month Salary)', liability_amount, line_type='deduction', is_taxable=False)

            if rec.settlement_authorized and rec.outstanding_debt_deduction > 0:
                if rec.debt_rssa_loan > 0:
                    add_line('Personal RSSA Overdraft Loan', rec.debt_rssa_loan, line_type='deduction', is_taxable=False, notes='CBS Live Overdraft')
                if rec.debt_guaranteed_loan > 0:
                    add_line('Guaranteed Loan Deduction (Separated Staff)', rec.debt_guaranteed_loan, line_type='deduction', is_taxable=False, notes=rec.debt_guaranteed_notes or 'Transferred liability for separated borrower')
                if rec.debt_personal_loan > 0:
                    add_line('Personal Loan Debt', rec.debt_personal_loan, line_type='deduction', is_taxable=False)
                if rec.debt_mortgage_loan > 0:
                    add_line('Mortgage Loan Debt', rec.debt_mortgage_loan, line_type='deduction', is_taxable=False)
                other_debt = rec.outstanding_debt_deduction - (rec.debt_rssa_loan + rec.debt_guaranteed_loan + rec.debt_personal_loan + rec.debt_mortgage_loan)
                if other_debt > 0.01:
                    add_line('Other Outstanding Debts', other_debt, line_type='deduction', is_taxable=False)
                
            if rec.rssa_payment:
                add_line('RSSA Payment', rec.rssa_payment, line_type='earning', is_taxable=True)
            if rec.other_benefits:
                add_line('Other Benefits', rec.other_benefits, line_type='earning', is_taxable=True)

            # --- 8. CASH INDEMNITY (IF ALREADY COMPUTED) ---
            if rec.cbs_indemnity_amount > 0:
                add_line('Cash Indemnity', rec.cbs_indemnity_amount, line_type='earning', is_taxable=True)
                
            if line_vals_list:
                self.env['hr.resignation.settlement.line'].sudo().create(line_vals_list)
            rec.invalidate_recordset(['line_ids'])
            rec._compute_summary()
            rec.is_processed = True

    @api.depends('pf_eligible', 'pf_ineligible_reason', 'severance_eligible', 'severance_ineligible_reason',
                 'service_years', 'has_disciplinary_case', 'job_category', 'joined_date', 'separation_reason', 'settlement_authorized')
    def _compute_eligibility_notes(self):
        for rec in self:
            rec.eligibility_notes = '\n'.join([
                '-- Separation Context',
                'Separation Reason : %s' % (rec.separation_reason or 'N/A'),
                'Job Category      : %s' % (rec.job_category or 'N/A'),
                'Joined Date       : %s' % (rec.joined_date or 'N/A'),
                'Years of Service  : %.2f' % rec.service_years,
                'Disciplinary Case : %s' % ('Yes' if rec.has_disciplinary_case else 'No'),
                'Misconduct Dismiss: %s' % ('Yes' if rec.is_misconduct_dismissal else 'No'),
                'Company Terminated: %s' % ('Yes' if rec.is_company_terminated else 'No'),
                '',
                '-- Eligibility Results',
                'PF Eligible       : %s' % ('Yes' if rec.pf_eligible == 'yes' else 'No -- ' + (rec.pf_ineligible_reason or '')),
                'Severance Eligible: %s' % ('Yes' if rec.severance_eligible == 'yes' else 'No -- ' + (rec.severance_ineligible_reason or '')),
                '',
                '-- Authorization',
                'Debt Settlement Authorized: %s' % ('Yes' if rec.settlement_authorized else 'No -- deductions will NOT be applied'),
            ])

    # ==================================================================
    # ACTIONS & NOTIFICATIONS
    # ==================================================================

    def _show_success_message(self, message, sticky=False, next_action=None):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': message,
                'type': 'success',
                'sticky': sticky,
                'next': next_action or {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_recalculate(self):
        for rec in self:
            # 0. Force refresh of basic salary, contract & accrued leave from resignation record
            if rec.resignation_id:
                rec.resignation_id._compute_employee_info()
                rec.resignation_id._compute_joined_date()
                if not rec.resignation_id.settlement_id:
                    rec.resignation_id.sudo().write({'settlement_id': rec.id})

            # 0.1 Synchronize settlement_date with official Release Date
            if rec.resignation_id and rec.resignation_id.release_date and not rec.settlement_date:
                rec.settlement_date = rec.resignation_id.release_date

            rel_date = rec.settlement_date or (rec.resignation_id and rec.resignation_id.release_date) or fields.Date.today()

            # 0.2 Auto-populate Cash Indemnity calculation date range:
            # startdate = resignation applied date, end date = release date
            if rec.resignation_id:
                if rec.resignation_id.application_date:
                    rec.cbs_start_date = rec.resignation_id.application_date
                if rec.resignation_id.release_date:
                    rec.cbs_end_date = rec.resignation_id.release_date
            if not rec.cbs_end_date:
                rec.cbs_end_date = rel_date
            if not rec.cbs_start_date:
                rec.cbs_start_date = (rec.resignation_id and rec.resignation_id.application_date) or rel_date
            rec._compute_cash_indemnity_days()

            # 1. Fetch live CBS accounts and balances (PF, Cash Indemnity, Personal OD, Guaranteed Loans)
            try:
                rec.action_fetch_cbs_employee_accounts()
            except Exception as e:
                _logger.warning("Error fetching CBS accounts in recalculate: %s", e)

            # 2. Run internal Odoo HR calculations
            rec._compute_service_years()
            rec._compute_eligibility_context()
            rec._compute_pf_eligible()
            rec._compute_severance_eligible()
            rec._compute_severance_amount()
            rec._sync_guaranteed_loan_liability()
            rec._compute_outstanding_debt()
            rec._compute_worked_days_default()
            rec._compute_remaining_salary()
            rec._compute_accrued_leave_pay()
            rec._compute_salary_deductions()

            # 3. Generate standard HR lines and set is_processed (runs instantly in ~0.05s)
            rec.action_generate_lines()
            
            # 3. Sum up the summary and totals
            rec._compute_summary()
            rec._compute_total()
            rec.is_processed = True
            
        return self._show_success_message(_("Standard settlement lines calculated successfully!"))

    def action_set_draft(self):
        is_hr = (
            self.env.user.has_group('hr.group_hr_user')
            or self.env.user.has_group('hr_resignation.group_pomd_officer')
            or self.env.user.has_group('hr_resignation.group_resignation_hr_manager')
            or self.env.user.has_group('base.group_system')
        )
        if not is_hr:
            raise UserError(_('Only an HR Officer or HR Manager can reset a settlement to draft.'))
        for rec in self:
            rec.state = 'draft'
            rec.processed_by_id = False
            rec.processed_date = False
            rec.confirmed_by_id = False
            rec.confirmed_date = False
            rec.paid_by_id = False
        return self._show_success_message(_("Settlement successfully reset to draft."))

    def action_reset_lines(self):
        """Clear all generated lines and reset is_processed so POMD can regenerate."""
        is_hr = (
            self.env.user.has_group('hr_resignation.group_pomd_officer')
            or self.env.user.has_group('hr_resignation.group_resignation_hr_manager')
            or self.env.user.has_group('base.group_system')
        )
        if not is_hr:
            raise UserError(_('Only POMD or HR Manager can reset settlement lines.'))
        for rec in self:
            rec.line_ids.unlink()
            rec.invalidate_recordset(['line_ids'])
            rec.is_processed = False
            rec.paid_date = False
            rec.cbs_indemnity_amount = 0.0
            rec.cbs_indemnity_balance = 0.0
            rec.pf_amount = 0.0
            rec.cbs_sync_status = False
            rec.cbs_pf_sync_status = False
            rec.severance_amount = 0.0
            rec.income_tax_severance = 0.0
            rec.net_severance_amount = 0.0
            rec.severance_breakdown_html = False
            rec.accrued_leave_pay = 0.0
            rec.income_tax_leave = 0.0
            rec.net_accrued_leave_pay = 0.0
            rec.accrued_leave_breakdown_html = False
            rec._compute_summary()
            rec._compute_total()
        return self._show_success_message(_("Settlement lines successfully reset."))


    def _get_cbs_api_token(self, feature_name="CBS", force_refresh=False):
        """
        Authenticate with CBS API and return (base_url, token).
        Uses memory cache to avoid redundant login HTTP requests on every single action.
        """
        global _CBS_TOKEN_CACHE
        now = time.time()
        if not force_refresh and _CBS_TOKEN_CACHE.get('token') and _CBS_TOKEN_CACHE.get('base_url') and now < _CBS_TOKEN_CACHE.get('expiry', 0):
            return _CBS_TOKEN_CACHE['base_url'], _CBS_TOKEN_CACHE['token']

        base_url = ''
        username = ''
        password = ''
        
        try:
            with self.env.cr.savepoint():
                # Check if table cbs_integration exists safely
                self.env.cr.execute("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'cbs_integration')")
                table_exists = self.env.cr.fetchone()[0]
                if not table_exists:
                    raise Exception("Table 'cbs_integration' does not exist in the database.")

                # Check if required columns exist safely
                self.env.cr.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'cbs_integration'")
                cols = [row[0] for row in self.env.cr.fetchall()]
                required_cols = ['username', 'password', 'endpoint', 'status', 'environment']
                missing_cols = [c for c in required_cols if c not in cols]
                if missing_cols:
                    raise Exception(f"Missing column(s) {', '.join(missing_cols)} in cbs_integration table.")

                self.env.cr.execute(
                    "SELECT username, cbs_decode(password), endpoint, environment FROM cbs_integration WHERE environment = 'CBS' AND (status = 'true' OR status = 't') LIMIT 1")
                row = self.env.cr.fetchone()
                if row:
                    username = row[0] or ''
                    password = row[1] or ''
                    base_url = row[2] or ''
                else:
                    raise Exception("No active CBS Integration found (environment='CBS' and status=True).")
        except Exception as e:
            err_str = str(e)
            if 'cbs_decode' in err_str:
                err_str = "PostgreSQL function 'cbs_decode()' is missing from database."
            raise Exception(err_str)
            
        if not base_url:
            raise Exception("The API endpoint is not configured in cbs_integration.")

        # Login to CBS to get Token with fast 0.8s connect timeout
        login_url = f"{base_url.rstrip('/')}/api/auth/login"
        try:
            login_resp = requests.post(login_url, params={'username': username, 'password': password}, timeout=(0.8, 2.0))
            if login_resp.status_code == 401:
                _CBS_TOKEN_CACHE['token'] = None
                raise Exception("Unable to confirm permission to load CBS data (401 Unauthorized).")
            login_resp.raise_for_status()
            token = login_resp.json().get('accessToken')
            if not token:
                raise Exception("No accessToken received from CBS authentication response.")
            
            # Cache token for 15 minutes
            _CBS_TOKEN_CACHE['token'] = token
            _CBS_TOKEN_CACHE['base_url'] = base_url
            _CBS_TOKEN_CACHE['expiry'] = now + 900
            return base_url, token
        except requests.exceptions.Timeout:
            raise Exception("The external CBS system took too long to respond (connection timeout).")
        except requests.exceptions.ConnectionError:
            raise Exception("Unable to connect to the external CBS system (server unreachable).")
        except requests.exceptions.HTTPError:
            raise Exception(f"Unable to load CBS data from the external system (HTTP {login_resp.status_code}).")
        except Exception as e:
            raise Exception(f"Unable to connect to the external CBS system: {str(e)}")

    def _sync_guaranteed_loan_liability(self):
        """Scan for accepted loan guarantees and check borrower OD/RSSA balance in CBS directly.
        Apportions liability dynamically across active/unseparated guarantors (e.g. 50/50 for 2 guarantors).
        """
        Resignation = self.env['hr.resignation']
        for rec in self:
            guaranteed_debt = 0.0
            guarantee_notes = []
            guaranteed_lines = self.env['resl.loan.guarantee'].sudo().search([
                ('guarantor_id', '=', rec.employee_id.id),
                ('state', 'in', ['accepted', 'separated']),
            ])
            for g_line in guaranteed_lines:
                loan = g_line.loan_id
                if not loan:
                    continue
                b_emp = loan.employee_id
                if not b_emp or b_emp.id == rec.employee_id.id:
                    continue

                if not Resignation._is_borrower_separated(b_emp):
                    # Active borrowers are responsible for their own loans;
                    # replacement guarantor flow in RESL applies instead of settlement deduction.
                    continue

                b_cbs_id = getattr(b_emp, 'employee_identification', False) or getattr(b_emp, 'identification_id', False) or ''
                b_cbs_id = str(b_cbs_id).strip() if b_cbs_id else ''
                b_unpaid = 0.0
                if b_cbs_id:
                    try:
                        base_url, token = self._get_cbs_api_token("Accounts")
                        b_url = f"{base_url.rstrip('/')}/api/cbs/employee-accounts/{b_cbs_id}"
                        headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
                        b_resp = requests.get(b_url, headers=headers, timeout=(1.5, 3.5))
                        if b_resp.status_code == 200:
                            b_data = b_resp.json() or {}
                            if isinstance(b_data, dict):
                                # If borrower not mapped in CBS or loan already settled, no liability
                                if b_data.get('status') == 'not_found':
                                    b_unpaid = 0.0
                                else:
                                    b_od = b_data.get('od_account') or {}
                                    b_status = str(b_od.get('status', '')).lower()
                                    if b_status == 'closed':
                                        b_unpaid = 0.0
                                    else:
                                        b_clr = b_od.get('CLR_BAL_AMT')
                                        if b_clr is not None:
                                            b_val = float(b_clr)
                                            # Only negative overdraft balance represents an active loan debt
                                            if b_val < 0:
                                                b_unpaid = abs(b_val)
                                            else:
                                                b_unpaid = 0.0
                        elif b_resp.status_code == 404:
                            b_unpaid = 0.0
                    except Exception as e:
                        _logger.warning("Failed to fetch borrower CBS OD loan for %s: %s", b_cbs_id, e)
                        b_unpaid = 0.0

                if b_unpaid > 0:
                    # Calculate this guarantor's fair share dynamically
                    live_guarantors = loan.guarantor_line_ids.filtered(
                        lambda l: l.guarantor_id and l.state in ('accepted', 'separated')
                    )
                    # Check guarantor status from hr_employee and res_users:
                    # Resigned only when BOTH employee is archived and user account disabled.
                    unseparated_guarantors = live_guarantors.filtered(
                        lambda l: l.guarantor_id.id == rec.employee_id.id
                        or not Resignation._is_employee_separated(l.guarantor_id)
                    )
                    guarantor_count = len(unseparated_guarantors) or 1
                    g_share = round(b_unpaid / guarantor_count, 2)

                    guaranteed_debt += g_share
                    if guarantor_count > 1:
                        pct = round(100.0 / guarantor_count)
                        guarantee_notes.append(
                            f"{b_emp.name} ({loan.name or 'OD Loan'}): {g_share:,.2f} ETB "
                            f"({pct}% share of live CBS balance {b_unpaid:,.2f} ETB split among {guarantor_count} guarantors)"
                        )
                    else:
                        guarantee_notes.append(
                            f"{b_emp.name} ({loan.name or 'OD Loan'}): {g_share:,.2f} ETB (100% of live CBS balance)"
                        )

            rec.debt_guaranteed_loan = guaranteed_debt
            rec.debt_guaranteed_notes = "; ".join(guarantee_notes) if guarantee_notes else False

    @api.depends('employee_id', 'resignation_id', 'resignation_id.rssa_od_guarantier', 'debt_guaranteed_loan', 'debt_guaranteed_notes')
    def _compute_guarantor_summary(self):
        """Describe both (1) who guarantees this employee's OD/RSSA loan and
        (2) any loans this employee is guaranteeing for other staff."""
        Resignation = self.env['hr.resignation']
        for rec in self:
            emp = rec.employee_id.sudo()
            if not emp:
                rec.rssa_od_guarantor = 'None'
                rec.guaranteed_other_status = 'None'
                continue

            # 1. Guarantors covering this employee's own OD/RSSA loan(s)
            own_info = []
            if 'resl.loan' in self.env:
                my_loans = self.env['resl.loan'].sudo().search([
                    ('employee_id', '=', emp.id),
                    ('status', 'not in', ['rejected']),
                ])
                for l in my_loans.mapped('guarantor_line_ids').filtered(lambda x: x.state in ('pending', 'accepted', 'separated')):
                    g = l.guarantor_id
                    if not g:
                        continue
                    is_resigned = Resignation._is_employee_separated(g)
                    own_info.append(f"{g.name} (Resigned)" if is_resigned else g.name)
            if own_info:
                rec.rssa_od_guarantor = ', '.join(sorted(set(own_info)))
            elif rec.resignation_id and rec.resignation_id.rssa_od_guarantier:
                rec.rssa_od_guarantor = rec.resignation_id.rssa_od_guarantier
            else:
                rec.rssa_od_guarantor = 'None'

            # 2. Loans this employee guaranteed for other staff
            if rec.debt_guaranteed_notes:
                rec.guaranteed_other_status = rec.debt_guaranteed_notes
            elif 'resl.loan.guarantee' in self.env:
                given_lines = self.env['resl.loan.guarantee'].sudo().search([
                    ('guarantor_id', '=', emp.id),
                    ('state', 'in', ['accepted', 'pending', 'separated']),
                ])
                given_notes = []
                for gl in given_lines:
                    loan = gl.loan_id
                    b_emp = loan.employee_id if loan else False
                    if not b_emp or b_emp.id == emp.id:
                        continue
                    is_b_sep = Resignation._is_borrower_separated(b_emp)
                    if is_b_sep:
                        status_lbl = 'Borrower Separated'
                    else:
                        status_lbl = 'Active (guarantor must be replaced in RESL)'
                    given_notes.append(f"{b_emp.name} ({loan.name or 'OD Loan'}): {status_lbl}")
                rec.guaranteed_other_status = '; '.join(given_notes) if given_notes else 'None'
            else:
                rec.guaranteed_other_status = 'None'

    def action_fetch_cbs_employee_accounts(self):
        """Fetch all CBS accounts (Provident Fund, Cash Indemnity) in a single API call
        from /api/cbs/employee-accounts/{employeeId}.
        """
        global _CBS_TOKEN_CACHE
        for rec in self:
            cbs_user_id = (
                getattr(rec.employee_id.sudo(), 'employee_identification', False)
                or getattr(rec.employee_id.sudo(), 'identification_id', False)
            )
            if not cbs_user_id:
                rec.cbs_pf_sync_status = False
                rec.cbs_sync_status = False
                if rec.resignation_id and rec.resignation_id.rssa:
                    rec.debt_rssa_loan = rec.resignation_id.rssa
                rec._sync_guaranteed_loan_liability()
                rec._compute_outstanding_debt()
                continue

            emp_id = str(cbs_user_id).strip()
            try:
                base_url, token = self._get_cbs_api_token("Accounts")
                fetch_url = f"{base_url.rstrip('/')}/api/cbs/employee-accounts/{emp_id}"
                headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}

                resp = requests.get(fetch_url, headers=headers, timeout=(0.5, 1.2))
                if resp.status_code == 401:
                    _CBS_TOKEN_CACHE['token'] = None
                    base_url, token = self._get_cbs_api_token("Accounts", force_refresh=True)
                    headers['Authorization'] = f'Bearer {token}'
                    resp = requests.get(fetch_url, headers=headers, timeout=(0.5, 1.2))

                if resp.status_code == 200:
                    data = resp.json() or {}

                    # 1. Provident Fund Account & Balance
                    pf_data = data.get('pf_account') or {}
                    if pf_data.get('ACCOUNT_NUMBER'):
                        rec.cbs_pf_account = str(pf_data.get('ACCOUNT_NUMBER')).strip()
                    clr_pf = pf_data.get('CLR_BAL_AMT')
                    rec.pf_amount = float(clr_pf) if clr_pf is not None else 0.0

                    # PF Response: If PF balance or account is present, keep it hidden (False).
                    # Only show if there's a specific message from API when no PF account is assigned.
                    if not rec.cbs_pf_account and isinstance(pf_data, dict) and pf_data.get('message'):
                        rec.cbs_pf_sync_status = pf_data.get('message')
                    else:
                        rec.cbs_pf_sync_status = False

                    # 2. Cash Indemnity Account & Balance
                    cia_data = data.get('cash_indemnity_account') or {}
                    if isinstance(cia_data, dict) and cia_data.get('status') == 'not_assigned':
                        rec.cbs_indemnity_account = False
                        rec.cbs_indemnity_balance = 0.0
                    elif isinstance(cia_data, dict):
                        if cia_data.get('ACCOUNT_NUMBER'):
                            rec.cbs_indemnity_account = str(cia_data.get('ACCOUNT_NUMBER')).strip()
                        clr_cia = cia_data.get('CLR_BAL_AMT')
                        rec.cbs_indemnity_balance = float(clr_cia) if clr_cia is not None else 0.0

                    # On initial view / account fetch, Cash Indemnity Response is hidden (False)
                    rec.cbs_sync_status = False

                    # 3. OD / RSSA Loan Balance (Only deduct if negative debt < 0; 0 or positive is NOT a loan debt)
                    od_data = data.get('od_account') or {}
                    if isinstance(od_data, dict) and od_data.get('status') == 'not_assigned':
                        rec.debt_rssa_loan = 0.0
                    elif isinstance(od_data, dict) and od_data.get('CLR_BAL_AMT') is not None:
                        try:
                            bal_od = float(od_data.get('CLR_BAL_AMT'))
                            if bal_od < 0:
                                rec.debt_rssa_loan = abs(bal_od)
                            else:
                                rec.debt_rssa_loan = 0.0
                        except (ValueError, TypeError):
                            rec.debt_rssa_loan = 0.0
                    elif rec.resignation_id and rec.resignation_id.rssa:
                        rec.debt_rssa_loan = rec.resignation_id.rssa
                    else:
                        rec.debt_rssa_loan = 0.0

                    # 3.1 Check Guaranteed Defaulted Loans for separated employees
                    rec._sync_guaranteed_loan_liability()
                    rec._compute_outstanding_debt()

                    # 4. Synchronize Account Numbers back to Employee Current Version if available
                    vals_to_update = {}
                    if rec.cbs_pf_account:
                        vals_to_update['pf_account'] = rec.cbs_pf_account
                    if rec.cbs_indemnity_account:
                        vals_to_update['indemnity_account'] = rec.cbs_indemnity_account

                    if vals_to_update and rec.employee_id.current_version_id:
                        try:
                            rec.employee_id.current_version_id.sudo().write(vals_to_update)
                        except Exception:
                            pass

                elif resp.status_code == 404:
                    if rec.resignation_id and rec.resignation_id.rssa:
                        rec.debt_rssa_loan = rec.resignation_id.rssa
                    rec._sync_guaranteed_loan_liability()
                    rec._compute_outstanding_debt()
                    # Do not show technical notices to users
                    rec.cbs_pf_sync_status = False
                    rec.cbs_sync_status = False
                else:
                    if rec.resignation_id and rec.resignation_id.rssa:
                        rec.debt_rssa_loan = rec.resignation_id.rssa
                    rec._sync_guaranteed_loan_liability()
                    rec._compute_outstanding_debt()
                    rec.cbs_pf_sync_status = False
                    rec.cbs_sync_status = False
            except Exception as e:
                _logger.warning("CBS fetch employee accounts error: %s", e)
                if rec.resignation_id and rec.resignation_id.rssa:
                    rec.debt_rssa_loan = rec.resignation_id.rssa
                rec._sync_guaranteed_loan_liability()
                rec._compute_outstanding_debt()
                # Never show technical timeouts or host URLs to users
                rec.cbs_pf_sync_status = False
                rec.cbs_sync_status = False

    def action_fetch_cbs_indemnity(self):
        global _CBS_TOKEN_CACHE
        for rec in self:
            cbs_user_id = (
                getattr(rec.employee_id.sudo(), 'employee_identification', False)
                or getattr(rec.employee_id.sudo(), 'identification_id', False)
            )
            if not cbs_user_id:
                rec.cbs_indemnity_amount = 0.0
                rec.cbs_sync_status = "No CBS Employee ID on profile."
                continue

            # 1. Start Date = Resignation Applied Date, End Date = Release Date
            if rec.resignation_id and rec.resignation_id.application_date:
                rec.cbs_start_date = rec.resignation_id.application_date
            elif not rec.cbs_start_date:
                rec.cbs_start_date = fields.Date.today()

            rel_date = rec.settlement_date or (rec.resignation_id and rec.resignation_id.release_date) or fields.Date.today()
            if rec.resignation_id and rec.resignation_id.release_date:
                rec.cbs_end_date = rec.resignation_id.release_date
            elif not rec.cbs_end_date:
                rec.cbs_end_date = rel_date
            rec._compute_cash_indemnity_days()

            emp_id = str(cbs_user_id).strip()
            base_url = ""
            cia_data = {}
            # 2. Check CBS Employee Accounts for cash indemnity account status first
            try:
                base_url, token = self._get_cbs_api_token("Accounts")
                acc_url = f"{base_url.rstrip('/')}/api/cbs/employee-accounts/{emp_id}"
                headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
                acc_resp = requests.get(acc_url, headers=headers, timeout=(0.5, 1.2))
                if acc_resp.status_code == 401:
                    _CBS_TOKEN_CACHE['token'] = None
                    base_url, token = self._get_cbs_api_token("Accounts", force_refresh=True)
                    headers['Authorization'] = f'Bearer {token}'
                    acc_resp = requests.get(acc_url, headers=headers, timeout=(0.5, 1.2))

                if acc_resp.status_code == 200:
                    acc_data = acc_resp.json() or {}
                    cia_data = acc_data.get('cash_indemnity_account') or {}
                    if isinstance(cia_data, dict):
                        if cia_data.get('ACCOUNT_NUMBER'):
                            rec.cbs_indemnity_account = str(cia_data.get('ACCOUNT_NUMBER')).strip()
                        clr_cia = cia_data.get('CLR_BAL_AMT')
                        if clr_cia is not None:
                            rec.cbs_indemnity_balance = float(clr_cia)
                        if cia_data.get('status') == 'not_assigned' or not rec.cbs_indemnity_account:
                            rec.cbs_indemnity_account = False
                            rec.cbs_indemnity_balance = 0.0
                            # If CBS reports not assigned, show the exact message from the API
                            api_msg = cia_data.get('message') or "No account number on file for this employee."
                            rec.cbs_indemnity_amount = 0.0
                            rec.cbs_sync_status = api_msg
                            # Remove indemnity line if exists
                            existing_line = rec.line_ids.filtered(lambda l: l.name == 'Cash Indemnity')
                            if existing_line:
                                existing_line.unlink()
                            rec._compute_summary()
                            rec._compute_total()
                            continue
            except Exception as e:
                _logger.warning("CBS check account error before indemnity calculation: %s", e)

            # 3. Call CBS Cash Indemnity Calculation Endpoint
            try:
                base_url, token = self._get_cbs_api_token("Cash Indemnity")
                fetch_url = f"{base_url.rstrip('/')}/api/cbs/cash-indemnity"
                api_working_days = rec.cash_indemnity_working_days or 25
                params = {
                    'empId': emp_id,
                    'formDate': rec.cbs_start_date.strftime('%Y-%m-%d'),
                    'toDate': rec.cbs_end_date.strftime('%Y-%m-%d'),
                    'workingDays': api_working_days
                }
                headers = {'Authorization': f'Bearer {token}'}

                resp = requests.get(fetch_url, params=params, headers=headers, timeout=(0.8, 1.5))
                if resp.status_code == 401:
                    _CBS_TOKEN_CACHE['token'] = None
                    base_url, token = self._get_cbs_api_token("Cash Indemnity", force_refresh=True)
                    headers['Authorization'] = f'Bearer {token}'
                    resp = requests.get(fetch_url, params=params, headers=headers, timeout=(0.8, 1.5))

                if resp.status_code == 200:
                    data = resp.json() or {}
                    safe_data = {k.lower(): v for k, v in data.items()} if isinstance(data, dict) else {}
                    fetched_amount = data.get('AMOUNT') if 'AMOUNT' in data else (safe_data.get('amount') or safe_data.get('computedindemnity') or safe_data.get('indemnityamount') or 0.0)
                    try:
                        fetched_amount = float(fetched_amount)
                    except (ValueError, TypeError):
                        fetched_amount = 0.0

                    if fetched_amount > 0:
                        rec.cbs_indemnity_amount = fetched_amount
                        # When calculated, it displays in Calculated Indemnity (ETB) and Response is hidden
                        rec.cbs_sync_status = False
                    else:
                        rec.cbs_indemnity_amount = 0.0
                        api_msg = data.get('message') or data.get('error') or data.get('detail') or safe_data.get('message')
                        if not api_msg and isinstance(cia_data, dict) and cia_data.get('message'):
                            api_msg = cia_data.get('message')
                        rec.cbs_sync_status = api_msg or "No cash indemnity amount calculated for this period."

                elif resp.status_code == 404:
                    rec.cbs_indemnity_amount = 0.0
                    api_msg = False
                    try:
                        err_json = resp.json()
                        api_msg = err_json.get('message') or err_json.get('error')
                    except Exception:
                        pass
                    if not api_msg and isinstance(cia_data, dict) and cia_data.get('message'):
                        api_msg = cia_data.get('message')
                    rec.cbs_sync_status = api_msg or "No indemnity records found in CBS for this employee."
                else:
                    rec.cbs_indemnity_amount = 0.0
                    api_msg = False
                    try:
                        err_json = resp.json()
                        api_msg = err_json.get('message') or err_json.get('error')
                    except Exception:
                        pass
                    rec.cbs_sync_status = api_msg or "Unable to calculate cash indemnity in CBS."

            except requests.exceptions.Timeout:
                rec.cbs_indemnity_amount = 0.0
                rec.cbs_sync_status = "CBS request timed out. Please try again."
            except requests.exceptions.ConnectionError:
                rec.cbs_indemnity_amount = 0.0
                rec.cbs_sync_status = "Unable to connect to CBS. Please check network connection."
            except Exception as e:
                rec.cbs_indemnity_amount = 0.0
                clean_err = str(e).replace("\n", " ")[:60]
                rec.cbs_sync_status = f"CBS Notice: {clean_err}"

            # 4. Insert or Update the Line in the Settlement Breakdown
            existing_line = rec.line_ids.filtered(lambda l: l.name == 'Cash Indemnity')
            if rec.cbs_indemnity_amount > 0:
                if existing_line:
                    existing_line.amount = rec.cbs_indemnity_amount
                else:
                    self.env['hr.resignation.settlement.line'].sudo().create({
                        'settlement_id': rec.id,
                        'resignation_id': rec.resignation_id.id if rec.resignation_id else False,
                        'name': 'Cash Indemnity',
                        'line_type': 'earning',
                        'is_taxable': True,
                        'amount': rec.cbs_indemnity_amount,
                        'notes': f"Calculated from CBS ({rec.cash_indemnity_working_days} working days)"
                    })
            elif existing_line and rec.cbs_indemnity_amount == 0:
                existing_line.unlink()

            rec._compute_summary()
            rec._compute_total()

    def action_confirm_settlement(self):
        if (not self.env.user.has_group('hr_resignation.group_pomd_officer') and not self.env.user.has_group('hr_resignation.group_resignation_hr_manager') and not self.env.user.has_group('base.group_system')
                and not self.env.user.has_group('hr_resignation.group_resignation_admin')):
            raise UserError(_('Only a POMD Officer or HR Manager can confirm the settlement amount.'))
        for rec in self:
            if rec.settlement_date and rec.resignation_id.release_date and rec.settlement_date != rec.resignation_id.release_date and not rec.date_change_justification:
                raise UserError(_('The Settlement Date differs from the official Release Date. You must provide a Date Change Justification.'))
            if rec.outstanding_debt_deduction > 0 and not rec.settlement_authorized:
                raise UserError(_('Cannot submit: Outstanding debts must be settled first.'))

            rec.state = 'waiting_audit'

            # Notify Auditor and HR Manager
            partners = []
            auditor_group = self.env.ref('hr_resignation.group_resignation_auditor', raise_if_not_found=False)
            if auditor_group:
                partners.extend(auditor_group.sudo().user_ids.mapped('partner_id').ids)
            hr_manager_group = self.env.ref('hr_resignation.group_resignation_hr_manager', raise_if_not_found=False)
            if hr_manager_group:
                partners.extend(hr_manager_group.sudo().user_ids.mapped('partner_id').ids)
            
            if partners:
                subject = _('Settlement Submitted for Audit: %s') % rec.employee_id.sudo().name
                body = _('The settlement process for %s has been submitted by the POMD Officer and is awaiting your Audit.') % rec.employee_id.sudo().name
                rec.message_post(body=body, message_type='notification')
                rec.resignation_id._send_notification(list(set(partners)), subject, body)

        return self._show_success_message(_("Settlement successfully submitted for audit!"))

    def action_audit_confirm(self):
        is_auditor = (
            self.env.user.has_group('hr_resignation.group_resignation_auditor')
            or self.env.user.has_group('hr_resignation.group_resignation_admin')
            or self.env.user.has_group('base.group_system')
        )
        if not is_auditor:
            raise UserError(_('Only an Auditor or Administrator can audit-confirm a settlement.'))

        for rec in self:
            if rec.state != 'waiting_audit':
                raise UserError(_('Only settlements in Waiting Audit state can be audit-confirmed.'))
            rec.state = 'waiting_payment'  
            rec.audited_by_id = self.env.user.id
            rec.audited_date = fields.Datetime.now()
            
            # Send notification to HR Manager group for payment execution
            manager_group = self.env.ref('hr_resignation.group_resignation_hr_manager', raise_if_not_found=False)
            managers = manager_group.user_ids.filtered(lambda u: u.active) if manager_group else []
            partners = [m.partner_id.id for m in managers if m.partner_id]
            body = f"The settlement for {rec.employee_id.sudo().name} has been AUDITED and submitted for your payment execution."
            rec.message_post(body=body, message_type='notification')
            if partners:
                rec.resignation_id._send_notification(partners, 'Settlement Audited', body)

        return self._show_success_message(_("Settlement audit confirmed and submitted for payment!"))

    def action_open_return_wizard(self):
        """Open the wizard to capture the return reason."""
        self.ensure_one()
        return {
            'name': 'Return Settlement for Revision',
            'type': 'ir.actions.act_window',
            'res_model': 'hr.settlement.return.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_settlement_id': self.id},
        }

    def action_return_to_draft(self, reason):
        """Auditor or HR Manager sends settlement back to draft with a reason."""
        for rec in self:
            if rec.state not in ('waiting_audit', 'waiting_payment'):
                continue
            
            pomd_partner = rec.processed_by_id.partner_id.id if rec.processed_by_id else False
            
            rec.state = 'draft'
            rec.is_processed = False
            rec.processed_by_id = False
            rec.processed_date = False
            rec.audited_by_id = False
            rec.audited_date = False
            
            # Post reason and notify POMD officer
            msg = f"<b>Settlement Returned for Revision</b><br/><b>Reason:</b> {reason}"
            partners = [pomd_partner] if pomd_partner else []
            rec.message_post(body=msg, message_type='notification')
            if partners and rec.resignation_id:
                rec.resignation_id._send_notification(partners, 'Settlement Returned', msg)

    def action_mark_paid(self):
        """HR Manager / Authorized Officer checks all details and executes settlement payment."""
        is_authorized = (
            self.env.user.has_group('hr_resignation.group_resignation_hr_manager')
            or self.env.user.has_group('hr_resignation.group_resignation_admin')
            or self.env.user.has_group('base.group_system')
        )
        if not is_authorized:
            raise UserError(_('Only an HR Manager or Administrator can execute the payment (segregation of duties from POMD maker).'))

        for rec in self:
            if rec.state != 'waiting_payment':
                raise UserError(_('Only settlements in Waiting Payment state can be paid.'))

            rec.state = 'paid'
            rec.paid_by_id = self.env.user.id
            rec.paid_date = fields.Datetime.now()
            if rec.resignation_id and rec.resignation_id.state in ('cleared', 'clearance_in_progress'):
                rec.resignation_id.state = 'settled'

        return self._show_success_message(_("Settlement payment successfully executed!"))
