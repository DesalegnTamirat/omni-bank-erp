# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import requests
from dateutil.relativedelta import relativedelta


class HrResignationSettlementLine(models.Model):
    _name = 'hr.resignation.settlement.line'
    _description = 'Settlement Line'

    settlement_id = fields.Many2one('hr.resignation.settlement', string='Settlement', ondelete='cascade', index=True)
    resignation_id = fields.Many2one('hr.resignation', string='Resignation', index=True, ondelete='cascade')
    name = fields.Char(string='Description', required=True)
    line_type = fields.Selection([
        ('earning', 'Earning'),
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

    resignation_id = fields.Many2one('hr.resignation', ondelete='cascade')
    employee_id    = fields.Many2one('hr.employee', required=True)
    
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

    # CBS Integration Fields
    cbs_user_id = fields.Char(related='employee_id.employee_identification', string='CBS Employee ID', readonly=True, compute_sudo=True)
    cbs_start_date = fields.Date(string='Calculation Start Date')
    cbs_end_date = fields.Date(string='Calculation End Date')
    cbs_working_days = fields.Integer(string='Applicable Working Days', default=25)
    cbs_indemnity_amount = fields.Float(string='Amount', readonly=True, copy=False)
    cbs_sync_status = fields.Char(string='Verification Status', readonly=True, copy=False)
    
    # CBS Provident Fund Integration
    cbs_pf_account = fields.Char(related='employee_id.current_version_id.pf_account', string='PF Account Number', readonly=True, compute_sudo=True)
    cbs_pf_sync_status = fields.Char(string='PF Verification Status', readonly=True, copy=False)
    
    # CBS Cash Indemnity Integration
    cbs_indemnity_account = fields.Char(related='employee_id.current_version_id.indemnity_account', string='Cash Indemnity Account', readonly=True, compute_sudo=True)

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
        compute='_compute_worked_days_default', store=True, readonly=False,
        help="Auto-filled from the employee's release date. POMD can override this value."
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

    # Accrued Leave
    accrued_leave_pay = fields.Float(string='Accrued leave pay', compute='_compute_accrued_leave_pay', store=True, readonly=False, digits=(16, 2))
    income_tax_leave = fields.Float(string='Income Tax (Leave)', compute='_compute_accrued_leave_pay', store=True, readonly=False, digits=(16, 2))

    # Financial Fields
    remaining_salary = fields.Float(string='Remaining Salary', compute='_compute_remaining_salary', store=True, readonly=False, digits=(16, 2))
    remaining_salary_notes = fields.Char(string='Remaining Salary Notes', compute='_compute_remaining_salary', store=True)
    remaining_housing_allowance = fields.Float(string='Remaining Housing Allowance', compute='_compute_remaining_salary', store=True, readonly=False, digits=(16, 2))
    remaining_representation_allowance = fields.Float(string='Remaining Representation Allowance', compute='_compute_remaining_salary', store=True, readonly=False, digits=(16, 2))
    remaining_special_car_allowance = fields.Float(string='Remaining Special Car Allowance', compute='_compute_remaining_salary', store=True, readonly=False, digits=(16, 2))
    remaining_fuel_allowance = fields.Float(string='Remaining Fuel Allowance', compute='_compute_remaining_salary', store=True, readonly=False, digits=(16, 2))
    remaining_transportation_allowance = fields.Float(string='Remaining Transportation Allowance', compute='_compute_remaining_salary', store=True, readonly=False, digits=(16, 2))
    remaining_cash_indemnity = fields.Float(string='Remaining Cash Indemnity', compute='_compute_cash_indemnity', store=True, readonly=False, digits=(16, 2))
    remaining_hardship_allowance = fields.Float(string='Remaining Hardship Allowance', compute='_compute_remaining_salary', store=True, readonly=False, digits=(16, 2))
    remaining_mobile_allowance = fields.Float(string='Remaining Mobile Allowance', compute='_compute_remaining_salary', store=True, readonly=False, digits=(16, 2))
    remaining_acting_allowance = fields.Float(string='Remaining Acting Allowance', compute='_compute_remaining_salary', store=True, readonly=False, digits=(16, 2))
    remaining_disturbance_allowance = fields.Float(string='Remaining Disturbance Allowance', compute='_compute_remaining_salary', store=True, readonly=False, digits=(16, 2))
    remaining_total_tax_exemption = fields.Float(string='Remaining Tax Exemption', compute='_compute_remaining_salary', store=True, readonly=False, digits=(16, 2))
    remaining_cash_indemnity_bank = fields.Float(string='Remaining Cash Indemnity Bank', compute='_compute_cash_indemnity', store=True, readonly=False, digits=(16, 2))
    cash_indemnity_working_days = fields.Integer(string='Cash Indemnity Working Days', compute='_compute_cash_indemnity_days', store=True, readonly=False)
    accrued_leave_notes = fields.Char(string='Accrued Leave Notes')
    rssa_payment = fields.Float(string='RSSA Payment', digits=(16, 2))
    other_benefits = fields.Float(string='Other Benefits', default=0.0, digits=(16, 2))
    
    notice_period_accepted = fields.Selection(related='resignation_id.notice_period_accepted', readonly=True)
    liability = fields.Float(related='resignation_id.liability', readonly=True, digits=(16, 2))
    
    # Unified Lines
    line_ids = fields.One2many('hr.resignation.settlement.line', 'settlement_id', string='Settlement Lines')
    total_payment = fields.Float(string='Gross Total', compute='_compute_total', store=True, digits=(16, 2))
    
    taxable_gross = fields.Float(string='Taxable Gross', compute='_compute_summary', store=True, digits=(16, 2))
    total_earnings = fields.Float(string='Total Earnings', compute='_compute_summary', store=True, digits=(16, 2))
    total_deductions_taxes = fields.Float(string='Total Deductions & Taxes', compute='_compute_summary', store=True, digits=(16, 2))
    
    # Deductions
    debt_mortgage_loan = fields.Float(string='Mortgage Loan Debt', default=0.0, digits=(16, 2))
    debt_personal_loan = fields.Float(string='Personal Loan Debt', default=0.0, digits=(16, 2))
    debt_rssa_loan = fields.Float(string='RSSA Loan Debt', default=0.0, digits=(16, 2))
    
    outstanding_debt_deduction = fields.Float(string='Total Outstanding Debt', compute='_compute_outstanding_debt', store=True, readonly=True, digits=(16, 2))
    income_tax_deduction = fields.Float(string='Income Tax Deduction', compute='_compute_salary_deductions', store=True, readonly=False, digits=(16, 2))
    income_tax_severance = fields.Float(string='Income Tax (Severance)', compute='_compute_income_tax_severance', store=True, readonly=False, digits=(16, 2))
    pension_deduction = fields.Float(string='Pension Deduction', compute='_compute_salary_deductions', store=True, readonly=False, digits=(16, 2))
    net_payment = fields.Float(string='Net Payment to Employee', compute='_compute_summary', store=True, digits=(16, 2))

    # Audit trail
    eligibility_notes = fields.Text(compute='_compute_eligibility_notes', store=True, string='Eligibility Assessment')

    state = fields.Selection([
        ('draft', 'Draft'), 
        ('waiting_audit', 'Waiting Audit'),
        ('waiting_payment', 'Waiting Payment'),
        ('paid', 'Paid')
    ], default='draft', tracking=True)
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

    @api.depends('service_years', 'is_company_terminated', 'is_misconduct_dismissal', 'employee_id', 'resignation_id.resignation_type_id')
    @api.onchange('pf_eligible')
    def _onchange_pf_eligible(self):
        if self.pf_eligible != 'yes':
            self.pf_amount = 0.0

    @api.onchange('severance_eligible')
    def _onchange_severance_eligible(self):
        if self.severance_eligible != 'yes':
            self.cbs_indemnity_amount = 0.0

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



    @api.depends('debt_mortgage_loan', 'debt_personal_loan', 'debt_rssa_loan')
    def _compute_outstanding_debt(self):
        for rec in self:
            rec.outstanding_debt_deduction = rec.debt_mortgage_loan + rec.debt_personal_loan + rec.debt_rssa_loan

    @api.depends('service_years', 'is_misconduct_dismissal', 'has_disciplinary_case', 'resignation_id.resignation_type_id')
    def _compute_severance_eligible(self):
        for rec in self:
            sep_type = rec.resignation_id.resignation_type_id
            emp = rec.employee_id
            min_years = 5.0 # Fallback default
            
            if sep_type and sep_type.pays_severance:
                # Find matching rule for the employee's job category (Managerial / Non Managerial)
                if 'employee_category' in emp.job_position._fields:
                    job_category = emp.job_position.employee_category
                    if job_category:
                        rule = sep_type.severance_rule_ids.filtered(lambda r: r.employee_category == job_category)
                        if rule:
                            min_years = rule[0].min_service_years
            
            if sep_type and not sep_type.pays_severance:
                rec.severance_eligible          = 'no'
                rec.severance_ineligible_reason = 'Severance is disabled for this Separation Type.'
            elif rec.service_years < min_years:
                rec.severance_eligible          = 'no'
                rec.severance_ineligible_reason = 'Minimum %.1f years required. Actual: %.2f years.' % (min_years, rec.service_years)
            elif rec.is_misconduct_dismissal:
                rec.severance_eligible          = 'no'
                rec.severance_ineligible_reason = 'Dismissed for misconduct — not eligible.'
            elif rec.has_disciplinary_case:
                rec.severance_eligible          = 'no'
                rec.severance_ineligible_reason = 'Active disciplinary case — not eligible.'
            else:
                rec.severance_eligible          = 'yes'
                rec.severance_ineligible_reason = ''

    @api.depends('severance_eligible', 'service_years', 'basic_salary', 'resignation_id.resignation_type_id')
    def _compute_severance_amount(self):
        for rec in self:
            if rec.severance_eligible != 'yes' or rec.basic_salary <= 0:
                rec.severance_amount = 0.0
                rec.years_for_severance = 0.0
                continue
                
            emp = rec.employee_id
            sep_type = rec.resignation_id.resignation_type_id
            
            first_year_days = 30
            subsequent_year_days = 10
            max_months = 12
            
            # Fetch dynamic rules from the Separation Type configuration instead of hardcoding
            if sep_type and sep_type.pays_severance and 'employee_category' in emp.job_position._fields:
                job_category = emp.job_position.employee_category
                if job_category:
                    rule = sep_type.severance_rule_ids.filtered(lambda r: r.employee_category == job_category)
                    if rule:
                        first_year_days = rule[0].first_year_days
                        subsequent_year_days = rule[0].subsequent_year_days
                        max_months = rule[0].max_severance_months
            
            years = rec.service_years
            rec.years_for_severance = years
            
            daily_rate = rec.basic_salary / 30.0
            
            if years <= 1.0:
                days_to_pay = first_year_days * years
            else:
                days_to_pay = first_year_days + (subsequent_year_days * (years - 1.0))
                
            amount = daily_rate * days_to_pay
            max_amount = rec.basic_salary * max_months
            
            rec.severance_amount = min(amount, max_amount)

    @api.depends('resignation_id.total_accrued_leave', 'resignation_id.total_scheduled_leave', 'basic_salary')
    def _compute_accrued_leave_pay(self):
        for rec in self:
            if rec.resignation_id and not rec.resignation_id.payment_request_leave_pay:
                rec.accrued_leave_pay = 0.0
                rec.income_tax_leave = 0.0
                continue
            if rec.basic_salary <= 0:
                rec.accrued_leave_pay = 0.0
                rec.income_tax_leave = 0.0
                continue
                
            working_days = (rec.resignation_id.total_accrued_leave or 0.0) + (rec.resignation_id.total_scheduled_leave or 0.0)
            
            # Convert working days to calendar days using standard Ethiopian factor (1.3273)
            # This ensures that when divided by 30 (calendar days), the rate is correct.
            total_days = working_days * 1.3273
            
            daily_rate = rec.basic_salary / 30.0
            rec.accrued_leave_pay = daily_rate * total_days
            
            # Tax calculation chunked by 30 days
            days_remaining = total_days
            total_tax = 0.0
            while days_remaining > 0:
                if days_remaining < 0.001:
                    break
                chunk = min(30.0, days_remaining)
                chunk_amount = daily_rate * chunk
                total_tax += rec._calculate_tax_for_amount(chunk_amount)
                days_remaining -= chunk
            
            rec.income_tax_leave = total_tax

    @api.depends('settlement_date')
    def _compute_worked_days_default(self):
        """Auto-fill worked days from release date day. POMD can override the stored value."""
        for rec in self:
            release_date = rec.settlement_date
            if release_date:
                rec.worked_days_final_month = release_date.day
            else:
                rec.worked_days_final_month = 0

    @api.depends('basic_salary', 'worked_days_final_month', 'resignation_id.current_version_id')
    def _compute_remaining_salary(self):
        for rec in self:
            if rec.resignation_id and not rec.resignation_id.payment_request_unpaid_salary:
                rec.remaining_salary = 0.0
                rec.remaining_housing_allowance = 0.0
                rec.remaining_representation_allowance = 0.0
                rec.remaining_special_car_allowance = 0.0
                rec.remaining_fuel_allowance = 0.0
                rec.remaining_transportation_allowance = 0.0
                rec.remaining_hardship_allowance = 0.0
                rec.remaining_mobile_allowance = 0.0
                rec.remaining_acting_allowance = 0.0
                rec.remaining_disturbance_allowance = 0.0
                rec.remaining_total_tax_exemption = 0.0
                rec.remaining_salary_notes = 'Salary payment disabled by Gatekeeper configuration.'
                continue

            worked_days = rec.worked_days_final_month
            basic = rec.basic_salary

            if not worked_days or basic <= 0:
                proportion = 0.0
                rec.remaining_salary = 0.0
                rec.remaining_salary_notes = 'No worked days or salary entered.'
            else:
                # Fixed 30-day month basis
                daily_rate = basic / 30.0
                rec.remaining_salary = daily_rate * worked_days
                proportion = worked_days / 30.0
                rec.remaining_salary_notes = f"{worked_days} days × ({basic:,.2f} ÷ 30) = {rec.remaining_salary:,.2f}"

            contract = rec.resignation_id.current_version_id
            if contract:
                def get_prorated(field):
                    return getattr(contract, field, 0.0) * proportion

                rec.remaining_housing_allowance = get_prorated('housing_allowance')
                rec.remaining_representation_allowance = get_prorated('representation_allowance')
                rec.remaining_special_car_allowance = get_prorated('special_car_allowance')
                rec.remaining_fuel_allowance = get_prorated('fuel_allowance')
                rec.remaining_transportation_allowance = get_prorated('transportation_allowance')
                rec.remaining_hardship_allowance = get_prorated('hardship_allowance')
                rec.remaining_mobile_allowance = get_prorated('mobile_allowance')
                rec.remaining_acting_allowance = get_prorated('acting_allowance')
                rec.remaining_disturbance_allowance = get_prorated('disturbance_allowance')
                rec.remaining_total_tax_exemption = get_prorated('total_tax_exemption') if hasattr(contract, 'total_tax_exemption') else 0.0
            else:
                rec.remaining_housing_allowance = 0.0
                rec.remaining_representation_allowance = 0.0
                rec.remaining_special_car_allowance = 0.0
                rec.remaining_fuel_allowance = 0.0
                rec.remaining_transportation_allowance = 0.0
                rec.remaining_hardship_allowance = 0.0
                rec.remaining_mobile_allowance = 0.0
                rec.remaining_acting_allowance = 0.0
                rec.remaining_disturbance_allowance = 0.0
                rec.remaining_total_tax_exemption = 0.0

    @api.depends('cbs_start_date', 'cbs_end_date')
    def _compute_cash_indemnity_days(self):
        """
        Placeholder logic for cash indemnity working days calculation.
        You can customize this method to apply any specific logic you need.
        """
        for rec in self:
            if rec.cbs_start_date and rec.cbs_end_date and rec.cbs_end_date >= rec.cbs_start_date:
                rec.cash_indemnity_working_days = (rec.cbs_end_date - rec.cbs_start_date).days + 1
            else:
                rec.cash_indemnity_working_days = 0

    @api.depends('cash_indemnity_working_days', 'resignation_id.current_version_id')
    def _compute_cash_indemnity(self):
        """
        Dedicated compute method for cash indemnity amounts.
        You can replace the proportion formula with your custom logic.
        """
        for rec in self:
            contract = rec.resignation_id.current_version_id
            if contract and rec.cash_indemnity_working_days > 0:
                # Replace this multiplier with your custom logic if needed
                indemnity_proportion = rec.cash_indemnity_working_days / 30.0
                
                rec.remaining_cash_indemnity = getattr(contract, 'cash_indemnity', 0.0) * indemnity_proportion
                rec.remaining_cash_indemnity_bank = getattr(contract, 'cash_indemnity_bank', 0.0) * indemnity_proportion
            else:
                rec.remaining_cash_indemnity = 0.0
                rec.remaining_cash_indemnity_bank = 0.0

    @api.depends('remaining_salary', 'remaining_housing_allowance', 'remaining_representation_allowance',
                 'remaining_special_car_allowance', 'remaining_fuel_allowance', 'remaining_transportation_allowance',
                 'remaining_cash_indemnity', 'remaining_hardship_allowance', 'remaining_mobile_allowance',
                 'remaining_acting_allowance', 'remaining_disturbance_allowance', 'remaining_cash_indemnity_bank',
                 'remaining_total_tax_exemption')
    def _compute_salary_deductions(self):
        for rec in self:
            gross = (rec.remaining_salary + rec.remaining_housing_allowance +
                     rec.remaining_representation_allowance + rec.remaining_special_car_allowance +
                     rec.remaining_fuel_allowance + rec.remaining_transportation_allowance +
                     rec.remaining_cash_indemnity + rec.remaining_hardship_allowance +
                     rec.remaining_mobile_allowance + rec.remaining_acting_allowance +
                     rec.remaining_disturbance_allowance + rec.remaining_cash_indemnity_bank +
                     rec.remaining_total_tax_exemption)
            if gross > 0:
                rec.income_tax_deduction = rec._calculate_tax_for_amount(gross)
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

    @api.depends('severance_amount', 'basic_salary')
    def _compute_income_tax_severance(self):
        for rec in self:
            if rec.severance_amount <= 0 or rec.basic_salary <= 0:
                rec.income_tax_severance = 0.0
                continue
                
            daily_rate = rec.basic_salary / 30.0
            total_days_awarded = rec.severance_amount / daily_rate
            
            # According to the Excel standard, Severance Tax is chunked by 30-day periods
            # (equivalent to 1 month of salary) and taxed iteratively.
            days_remaining = total_days_awarded
            total_tax = 0.0
            
            while days_remaining > 0:
                # To prevent endless loops from float precision, round slightly
                if days_remaining < 0.001:
                    break
                    
                chunk = min(30.0, days_remaining)
                chunk_amount = daily_rate * chunk
                total_tax += rec._calculate_tax_for_amount(chunk_amount)
                days_remaining -= chunk
                
            rec.income_tax_severance = total_tax

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

    @api.depends('total_earnings')
    def _compute_total(self):
        for rec in self:
            rec.total_payment = rec.total_earnings

    def action_generate_lines(self):
        for rec in self:
            rec.line_ids.unlink()
            lines = []
            
            # --- SEVERANCE PAY & TAX ---
            if rec.severance_amount > 0:
                lines.append((0, 0, {'name': 'Severance Pay', 'line_type': 'earning', 'is_taxable': True, 'amount': rec.severance_amount, 'resignation_id': rec.resignation_id.id}))
                if rec.income_tax_severance > 0:
                    lines.append((0, 0, {'name': 'Severance Income Tax', 'line_type': 'tax', 'is_taxable': False, 'amount': rec.income_tax_severance, 'resignation_id': rec.resignation_id.id}))
            
            # --- OTHER STANDARD LINES ---
            def add_line(name, amount, is_taxable=True):
                if amount > 0:
                    lines.append((0, 0, {'name': name, 'line_type': 'earning', 'is_taxable': is_taxable, 'amount': amount, 'resignation_id': rec.resignation_id.id}))

            add_line('Remaining Salary', rec.remaining_salary)
            add_line('Housing Allowance', rec.remaining_housing_allowance)
            add_line('Representation Allowance', rec.remaining_representation_allowance)
            add_line('Special Car Allowance', rec.remaining_special_car_allowance)
            add_line('Fuel Allowance', rec.remaining_fuel_allowance)
            add_line('Transportation Allowance', rec.remaining_transportation_allowance)
            add_line('Hardship Allowance', rec.remaining_hardship_allowance)
            add_line('Mobile Allowance', rec.remaining_mobile_allowance)
            add_line('Acting Allowance', rec.remaining_acting_allowance)
            add_line('Disturbance Allowance', rec.remaining_disturbance_allowance)
            add_line('Total Tax Exemption', rec.remaining_total_tax_exemption)
            add_line('Accrued Leave Pay', rec.accrued_leave_pay)
            if rec.income_tax_leave > 0:
                lines.append((0, 0, {'name': 'Leave Income Tax', 'line_type': 'tax', 'is_taxable': False, 'amount': rec.income_tax_leave, 'resignation_id': rec.resignation_id.id}))
            if rec.pf_amount > 0:
                lines.append((0, 0, {'name': 'Provident Fund', 'line_type': 'earning', 'is_taxable': False, 'amount': rec.pf_amount, 'resignation_id': rec.resignation_id.id}))
            
            lines.append((0, 0, {'name': 'Income Tax (Salary)', 'line_type': 'tax', 'is_taxable': False, 'amount': rec.income_tax_deduction, 'resignation_id': rec.resignation_id.id}))
            lines.append((0, 0, {'name': 'Pension Deduction', 'line_type': 'deduction', 'is_taxable': False, 'amount': rec.pension_deduction, 'resignation_id': rec.resignation_id.id}))
                
            liability_amount = rec.resignation_id.liability or 0.0
            lines.append((0, 0, {'name': 'Notice Period Liability (1 Month Salary)' if liability_amount > 0 else 'Notice Period Liability', 'line_type': 'deduction', 'is_taxable': False, 'amount': liability_amount, 'resignation_id': rec.resignation_id.id}))

            if rec.outstanding_debt_deduction and rec.settlement_authorized:
                lines.append((0, 0, {'name': 'Outstanding Debts', 'line_type': 'deduction', 'is_taxable': False, 'amount': rec.outstanding_debt_deduction, 'resignation_id': rec.resignation_id.id}))
                
            if rec.rssa_payment:
                lines.append((0, 0, {'name': 'RSSA Payment', 'line_type': 'earning', 'is_taxable': True, 'amount': rec.rssa_payment, 'resignation_id': rec.resignation_id.id}))
            if rec.other_benefits:
                lines.append((0, 0, {'name': 'Other Benefits', 'line_type': 'earning', 'is_taxable': True, 'amount': rec.other_benefits, 'resignation_id': rec.resignation_id.id}))
                
            rec.write({'line_ids': lines, 'is_processed': True})

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
    # ACTIONS
    # ==================================================================

    def action_recalculate(self):
        for rec in self:
            # 1. Run internal Odoo HR calculations first
            rec._compute_service_years()
            rec._compute_eligibility_context()
            rec._compute_pf_eligible()
            rec._compute_severance_eligible()
            rec._compute_outstanding_debt()
            rec._compute_remaining_salary()
            rec._compute_salary_deductions()
            rec._compute_accrued_leave_pay()
            
            # 1.5 Generate standard HR lines and set is_processed (must run after computations!)
            rec.action_generate_lines()
            
            # Automatically create the PF line in the breakdown if it was fetched!
            # Note: We do NOT automatically fetch CBS Indemnity here anymore, 
            # POMD will trigger it separately via its own button.
            rec.action_fetch_cbs_pf()
            if rec.pf_amount > 0:
                existing_pf_line = rec.line_ids.filtered(lambda l: l.name == 'Provident Fund (CBS)')
                if existing_pf_line:
                    existing_pf_line.amount = rec.pf_amount
                else:
                    self.env['hr.resignation.settlement.line'].sudo().create({
                        'settlement_id': rec.id,
                        'name': 'Provident Fund (CBS)',
                        'line_type': 'earning',
                        'amount': rec.pf_amount,
                    })
            
            # 3. Finally, sum up the total (which now safely includes the API values)
            rec._compute_total()
        for rec in self:
            rec.is_processed = True
            
        return {
            'type': 'ir.actions.client',
            'tag': 'reload'
        }

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
            rec.is_processed = False
            rec.paid_date = False
            rec.cbs_indemnity_amount = 0.0
            rec.pf_amount = 0.0
            rec.cbs_sync_status = False
            rec.cbs_pf_sync_status = False

    def action_fetch_cbs_pf(self):
        for rec in self:
            if rec.pf_eligible != 'yes':
                rec.pf_amount = 0.0
                rec.cbs_pf_sync_status = "Not Eligible for PF"
                continue
                
            pf_account = rec.cbs_pf_account
            if not pf_account:
                raise UserError("This employee does not have a Provident Fund Account Number set in their HR Version profile.")

            # 1. Get credentials securely from the cbs_integration table
            base_url = 'http://10.1.11.242:7001'
            username = ''
            password = ''
            try:
                self.env.cr.execute("SELECT username, password FROM cbs_integration LIMIT 1")
                row = self.env.cr.fetchone()
                if row:
                    username = row[0]
                    password = row[1]
                else:
                    raise UserError("The cbs_integration table is empty.")
            except Exception as e:
                self.env.cr.rollback()
                IrConfig = self.env['ir.config_parameter'].sudo()
                base_url = IrConfig.get_param('cbs.api.url', 'http://10.1.11.242:7001')
                username = IrConfig.get_param('cbs.api.username', '')
                password = IrConfig.get_param('cbs.api.password', '')

            # 2. Login to CBS to get Token
            login_url = f"{base_url.rstrip('/')}/api/auth/login"
            try:
                login_resp = requests.post(login_url, params={'username': username, 'password': password}, timeout=15)
                login_resp.raise_for_status()
                token = login_resp.json().get('accessToken')
            except requests.exceptions.HTTPError as e:
                if login_resp.status_code == 401:
                    raise UserError("Unable to confirm permission to load allowance data. Please contact administrator.")
                raise UserError(f"Unable to load allowance data from the external system (Error Code ({login_resp.status_code}).")
            except requests.exceptions.Timeout:
                raise UserError("The external allowance system took too long to respond. Please try again later.")
            except Exception as e:
                raise UserError("Unable to connect to the external allowance system. Please check your network connection.")

            # 3. Fetch the PF Amount from CBS
            # Exact PF endpoint provided by user
            fetch_url = f"{base_url.rstrip('/')}/api/cbs/pf-account-balance/{pf_account}"
            headers = {'Authorization': f'Bearer {token}'}

            try:
                resp = requests.get(fetch_url, headers=headers)
                if resp.status_code == 404:
                    rec.pf_amount = 0.0
                    rec.cbs_pf_sync_status = f"404 Not Found for Account {pf_account}"
                else:
                    resp.raise_for_status()
                    data = resp.json()
                    safe_data = {k.lower(): v for k, v in data.items()}
                    
                    # Exact JSON key provided by user
                    fetched_amount = safe_data.get('clr_bal_amt') or safe_data.get('balance') or safe_data.get('amount') or 0.0
                    rec.pf_amount = float(fetched_amount)
                    
                    from datetime import datetime
                    now_str = datetime.now().strftime("%b %d, %I:%M %p")
                    rec.cbs_pf_sync_status = f"✅ PF Successfully Fetched (Today at {now_str})"
            except requests.exceptions.HTTPError as e:
                raise UserError(f"Unable to load Provident Fund data from the external system (Error Code: {resp.status_code}).")
            except requests.exceptions.Timeout:
                raise UserError("The external system took too long to calculate the Provident Fund. Please try again later.")
            except Exception as e:
                raise UserError("The connection to the external system was lost while fetching Provident Fund data.")

    def action_fetch_cbs_indemnity(self):
        for rec in self:
            if rec.severance_eligible != 'yes':
                rec.cbs_indemnity_amount = 0.0
                rec.cbs_sync_status = "Not Eligible for Severance/Indemnity"
                continue
                
            cbs_user_id = rec.employee_id.sudo().employee_identification
            if not cbs_user_id:
                raise UserError("This employee does not have a System ID set (employee_identification)!")

            if not rec.cbs_start_date or not rec.cbs_end_date:
                raise UserError("Please set both the Indemnity Start Date and Indemnity End Date before calculating the Cash Indemnity.")
                
            # Use the dedicated cash indemnity working days for the API, not the standard final month days
            api_working_days = rec.cash_indemnity_working_days

            # 1. Get credentials securely from the cbs_integration table
            base_url = 'http://10.1.11.242:7001'
            username = ''
            password = ''
            
            # Try to query the raw database table directly
            try:
                self.env.cr.execute("SELECT username, password FROM cbs_integration LIMIT 1")
                row = self.env.cr.fetchone()
                if row:
                    username = row[0]
                    password = row[1]
                else:
                    raise UserError("The cbs_integration table is empty.")
            except Exception as e:
                # Fallback to ir.config_parameter
                self.env.cr.rollback()
                IrConfig = self.env['ir.config_parameter'].sudo()
                base_url = IrConfig.get_param('cbs.api.url', 'http://10.1.11.242:7001')
                username = IrConfig.get_param('cbs.api.username', '')
                password = IrConfig.get_param('cbs.api.password', '')

            # 2. Login to CBS to get Token
            login_url = f"{base_url.rstrip('/')}/api/auth/login"
            try:
                login_resp = requests.post(login_url, params={'username': username, 'password': password}, timeout=15)
                login_resp.raise_for_status()
                token = login_resp.json().get('accessToken')
            except requests.exceptions.HTTPError as e:
                if login_resp.status_code == 401:
                    raise UserError("Unable to confirm permission to load allowance data. Please contact administrator.")
                raise UserError(f"Unable to load allowance data from the external system (Error Code ({login_resp.status_code}).")
            except requests.exceptions.Timeout:
                raise UserError("The external allowance system took too long to respond. Please try again later.")
            except Exception as e:
                raise UserError("Unable to connect to the external allowance system. Please check your network connection.")

            # 3. Fetch the Amount from CBS
            fetch_url = f"{base_url.rstrip('/')}/api/cbs/cash-indemnity"
            params = {
                'empId': cbs_user_id,
                'formDate': rec.cbs_start_date.strftime('%Y-%m-%d'),
                'toDate': rec.cbs_end_date.strftime('%Y-%m-%d') if rec.cbs_end_date else rec.create_date.strftime('%Y-%m-%d'),
                'workingDays': api_working_days
            }
            headers = {'Authorization': f'Bearer {token}'}

            try:
                resp = requests.get(fetch_url, params=params, headers=headers)
                if resp.status_code == 404:
                    rec.cbs_indemnity_amount = 0.0
                    rec.cbs_sync_status = f"404 Not Found for {cbs_user_id} between {rec.cbs_start_date} and {rec.cbs_end_date}"
                else:
                    resp.raise_for_status()
                    data = resp.json()
                    # Case-insensitive JSON parsing for Amount
                    rec.cbs_sync_status = f"Raw JSON: {str(data)[:100]}"
                    
                    # Convert all keys to lowercase for safe matching
                    safe_data = {k.lower(): v for k, v in data.items()}
                    fetched_amount = safe_data.get('amount') or safe_data.get('computedindemnity') or safe_data.get('indemnityamount') or 0.0
                    
                    rec.cbs_indemnity_amount = float(fetched_amount)
                    
                    from datetime import datetime
                    now_str = datetime.now().strftime("%b %d, %I:%M %p")
                    rec.cbs_sync_status = f"✅ Successfully Fetched (Today at {now_str})"
            except requests.exceptions.HTTPError as e:
                raise UserError(f"Unable to load Cash Indemnity data from the external system (Error Code: {resp.status_code}).")
            except requests.exceptions.Timeout:
                raise UserError("The external system took too long to calculate the Cash Indemnity. Please try again later.")
            except Exception as e:
                raise UserError("The connection to the external system was lost while fetching Cash Indemnity data.")
                
            # 4. Insert or Update the Line in the Settlement Breakdown
            existing_line = rec.line_ids.filtered(lambda l: l.name == 'Cash Indemnity')
            if existing_line:
                existing_line.amount = rec.cbs_indemnity_amount
            else:
                self.env['hr.resignation.settlement.line'].sudo().create({
                    'settlement_id': rec.id,
                    'name': 'Cash Indemnity',
                    'line_type': 'earning',
                    'amount': rec.cbs_indemnity_amount,
                })
            
            # Totals will auto-compute via @api.depends on line_ids

    def action_confirm_settlement(self):
        if not self.env.user.has_group('hr_resignation.group_pomd_officer') and not self.env.user.has_group('hr_resignation.group_resignation_hr_manager') and not self.env.user.has_group('base.group_system') and not self.env.user.has_group('hr_resignation.group_resignation_admin'):
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

    def action_audit_confirm(self):
        for rec in self:
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
        if partners:
            rec.resignation_id._send_notification(partners, 'Settlement Returned', msg)

    def action_mark_paid(self):
        """HR Manager / Authorized Officer checks all details and executes settlement payment."""
        is_authorized = (
            self.env.user.has_group('hr_resignation.group_resignation_hr_manager')
            or self.env.user.has_group('hr_resignation.group_pomd_officer')
            or self.env.user.has_group('base.group_system')
        )
        if not is_authorized:
            raise UserError(_('Only an HR Manager or POMD Officer can execute the payment.'))

        for rec in self:
            if rec.state != 'waiting_payment':
                raise UserError(_('Only settlements in Waiting Payment state can be paid.'))

            rec.state = 'paid'
            rec.paid_by_id = self.env.user.id
            rec.paid_date = fields.Datetime.now()
            if rec.resignation_id and rec.resignation_id.state in ('cleared', 'clearance_in_progress'):
                rec.resignation_id.state = 'settled'

    def write(self, vals):
        return super().write(vals)
