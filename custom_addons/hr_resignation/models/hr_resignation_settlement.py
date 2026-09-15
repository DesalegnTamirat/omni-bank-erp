# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
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
                resignation = self.env['hr.resignation'].browse(vals['resignation_id'])
                if resignation.settlement_id:
                    vals['settlement_id'] = resignation.settlement_id.id
            elif vals.get('settlement_id') and not vals.get('resignation_id'):
                settlement = self.env['hr.resignation.settlement'].browse(vals['settlement_id'])
                if settlement.resignation_id:
                    vals['resignation_id'] = settlement.resignation_id.id
        return super().create(vals_list)

    def write(self, vals):
        if 'resignation_id' in vals and not 'settlement_id' in vals:
            resignation = self.env['hr.resignation'].browse(vals['resignation_id'])
            if resignation.settlement_id:
                vals['settlement_id'] = resignation.settlement_id.id
        elif 'settlement_id' in vals and not 'resignation_id' in vals:
            settlement = self.env['hr.resignation.settlement'].browse(vals['settlement_id'])
            if settlement.resignation_id:
                vals['resignation_id'] = settlement.resignation_id.id
        return super().write(vals)


class HrResignationSettlement(models.Model):
    _name = 'hr.resignation.settlement'
    _description = 'Resignation Final Settlement'
    _rec_name = 'employee_id'

    resignation_id = fields.Many2one('hr.resignation', ondelete='cascade')
    employee_id    = fields.Many2one('hr.employee', required=True)

    # reads authorization from resignation submission
    settlement_authorized = fields.Boolean(
        related='resignation_id.debt_settlement_authorized',
        string='Debt Settlement Authorized', readonly=True)

    # Service Period
    service_years = fields.Float(
        compute='_compute_service_years', store=True, digits=(16, 2),
        string='Years of Service')
    service_months_total = fields.Integer(
        compute='_compute_service_years', store=True,
        string='Total Months of Service')

    # Eligibility Context
    separation_reason       = fields.Char(compute='_compute_eligibility_context', store=True, string='Separation Reason')
    employment_type         = fields.Char(compute='_compute_eligibility_context', store=True, string='Employment Type')
    has_disciplinary_case   = fields.Boolean(compute='_compute_eligibility_context', store=True, string='Active Disciplinary Case')
    is_misconduct_dismissal = fields.Boolean(compute='_compute_eligibility_context', store=True, string='Dismissed for Misconduct')
    is_company_terminated   = fields.Boolean(compute='_compute_eligibility_context', store=True, string='Company Terminated')

    # Salary Parameters
    basic_salary = fields.Float(string='Basic Salary', related='resignation_id.basic_salary', readonly=True, digits=(16, 2))
    worked_days_final_month = fields.Integer(string='Worked Days in Final Month')
    total_days_in_month = fields.Integer(string='Total Days in Month', default=31)
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
        ('waiting_approval', 'Waiting Approval'),
        ('confirmed', 'Confirmed'), 
        ('paid', 'Paid')
    ], default='draft', tracking=True)
    notes = fields.Text(string='HR Notes')
    
    is_hr_manager = fields.Boolean(compute='_compute_is_hr_manager')

    # Tracking Fields
    processed_by_id = fields.Many2one('res.users', string='Processed By', readonly=True, tracking=True)
    processed_date = fields.Datetime(string='Date Processed', readonly=True)
    confirmed_by_id = fields.Many2one('res.users', string='Confirmed By', readonly=True, tracking=True)
    confirmed_date = fields.Datetime(string='Date Confirmed', readonly=True)
    paid_by_id = fields.Many2one('res.users', string='Paid By', readonly=True, tracking=True)
    paid_date = fields.Datetime(string='Date Paid', readonly=True)

    def _compute_is_hr_manager(self):
        is_mgr = self.env.user.has_group('hr_resignation.group_resignation_hr_manager') or self.env.user.has_group('base.group_system')
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

    @api.depends('resignation_id.release_date', 'resignation_id.joined_date', 'employee_id.start_date')
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
                    
            end   = rec.resignation_id.release_date or fields.Date.today()
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
            rec.employment_type         = emp.employee_type if emp and 'employee_type' in emp._fields else 'employee'
            rec.is_company_terminated   = rec.resignation_id.initiated_by == 'company' or bool(sep and getattr(sep, 'is_company_terminated', False))
            rec.is_misconduct_dismissal = bool(sep and getattr(sep, 'is_misconduct_dismissal', False))
            rec.has_disciplinary_case   = False
            if emp and 'hr.disciplinary.action' in self.env:
                rec.has_disciplinary_case = bool(self.env['hr.disciplinary.action'].search([('employee_name', '=', emp.id), ('state', 'not in', ('cancel', 'done'))], limit=1))

    @api.depends('service_years', 'is_company_terminated', 'is_misconduct_dismissal', 'employee_id', 'resignation_id.resignation_type_id')
    def _compute_pf_eligible(self):

        for rec in self:
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
                if 'employee_category' in emp.job_id._fields:
                    job_category = emp.job_id.employee_category
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
            
            if sep_type and sep_type.pays_severance and 'employee_category' in emp.job_id._fields:
                job_category = emp.job_id.employee_category
                if job_category and 'manager' in job_category.lower():
                    first_year_days = 30
                    subsequent_year_days = 15 # 1/2 of monthly salary
                else:
                    first_year_days = 30
                    subsequent_year_days = 10 # 1/3 of monthly salary
            
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
            if rec.basic_salary <= 0:
                rec.accrued_leave_pay = 0.0
                rec.income_tax_leave = 0.0
                continue
                
            total_days = (rec.resignation_id.total_accrued_leave or 0.0) + (rec.resignation_id.total_scheduled_leave or 0.0)
            daily_rate = rec.basic_salary / 30.0
            rec.accrued_leave_pay = daily_rate * total_days
            
            # Tax calculation chunked by 30 days
            days_remaining = total_days
            total_tax = 0.0
            while days_remaining > 0:
                chunk = min(30.0, days_remaining)
                chunk_amount = daily_rate * chunk
                total_tax += rec._calculate_tax_for_amount(chunk_amount)
                days_remaining -= chunk
            
            rec.income_tax_leave = total_tax

    @api.depends('basic_salary', 'resignation_id.release_date')
    def _compute_remaining_salary(self):
        import calendar
        for rec in self:
            release_date = rec.resignation_id.release_date
            if not release_date or rec.basic_salary <= 0:
                rec.remaining_salary = 0.0
                rec.remaining_salary_notes = 'No release date or salary found.'
            else:
                days_in_month = calendar.monthrange(release_date.year, release_date.month)[1]
                proportion = release_date.day / days_in_month
                rec.remaining_salary = rec.basic_salary * proportion
                rec.remaining_salary_notes = f"Prorated: {release_date.day}/{days_in_month} days"

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
        brackets = self.env['hr.resignation.tax.bracket'].search([])
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

    @api.depends('severance_amount', 'resignation_id.joined_date', 'resignation_id.release_date', 'basic_salary', 'resignation_id.job_category')
    def _compute_income_tax_severance(self):
        for rec in self:
            if rec.severance_amount <= 0:
                rec.income_tax_severance = 0.0
                continue
                
            start_date = rec.resignation_id.joined_date
            end_date = rec.resignation_id.release_date or fields.Date.today()
            if not start_date or not end_date:
                rec.income_tax_severance = rec._calculate_tax_for_amount(rec.severance_amount)
                continue
                
            is_manager = False
            if rec.resignation_id.job_category and 'manager' in rec.resignation_id.job_category.lower():
                is_manager = True
                
            current_date = start_date
            year = 1
            total_tax = 0.0
            
            while current_date < end_date:
                next_date = current_date + relativedelta(years=1)
                
                if next_date > end_date:
                    days = (end_date - current_date).days
                    fraction = days / 365.0
                    if year == 1:
                        amt = rec.basic_salary * fraction
                    else:
                        multiplier = 0.5 if is_manager else (1.0/3.0)
                        amt = rec.basic_salary * multiplier * fraction
                    total_tax += rec._calculate_tax_for_amount(amt)
                    break
                else:
                    if year == 1:
                        amt = rec.basic_salary
                    else:
                        multiplier = 0.5 if is_manager else (1.0/3.0)
                        amt = rec.basic_salary * multiplier
                    total_tax += rec._calculate_tax_for_amount(amt)
                    current_date = next_date
                    year += 1
                    
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
            lines.append((0, 0, {'name': 'Remaining Salary', 'line_type': 'earning', 'is_taxable': True, 'amount': rec.remaining_salary, 'resignation_id': rec.resignation_id.id}))
            lines.append((0, 0, {'name': 'Accrued Leave Pay', 'line_type': 'earning', 'is_taxable': True, 'amount': rec.accrued_leave_pay, 'resignation_id': rec.resignation_id.id}))
            if rec.income_tax_leave > 0:
                lines.append((0, 0, {'name': 'Leave Income Tax', 'line_type': 'tax', 'is_taxable': False, 'amount': rec.income_tax_leave, 'resignation_id': rec.resignation_id.id}))
            lines.append((0, 0, {'name': 'Provident Fund', 'line_type': 'earning', 'is_taxable': False, 'amount': rec.pf_amount, 'resignation_id': rec.resignation_id.id}))
            
            lines.append((0, 0, {'name': 'Income Tax (Salary)', 'line_type': 'tax', 'is_taxable': False, 'amount': rec.income_tax_deduction, 'resignation_id': rec.resignation_id.id}))
            lines.append((0, 0, {'name': 'Pension Deduction', 'line_type': 'deduction', 'is_taxable': False, 'amount': rec.pension_deduction, 'resignation_id': rec.resignation_id.id}))
                
            if rec.notice_period_accepted == 'no' and rec.resignation_id.notice_period > 0:
                lines.append((0, 0, {'name': 'Notice Period Liability (1 Month Salary)', 'line_type': 'deduction', 'is_taxable': False, 'amount': rec.basic_salary, 'resignation_id': rec.resignation_id.id}))

            if rec.outstanding_debt_deduction and rec.settlement_authorized:
                lines.append((0, 0, {'name': 'Outstanding Debts', 'line_type': 'deduction', 'is_taxable': False, 'amount': rec.outstanding_debt_deduction, 'resignation_id': rec.resignation_id.id}))
                
            if rec.rssa_payment:
                lines.append((0, 0, {'name': 'RSSA Payment', 'line_type': 'earning', 'is_taxable': True, 'amount': rec.rssa_payment, 'resignation_id': rec.resignation_id.id}))
            if rec.other_benefits:
                lines.append((0, 0, {'name': 'Other Benefits', 'line_type': 'earning', 'is_taxable': True, 'amount': rec.other_benefits, 'resignation_id': rec.resignation_id.id}))
                
            rec.write({'line_ids': lines})

    @api.depends('pf_eligible', 'pf_ineligible_reason', 'severance_eligible', 'severance_ineligible_reason',
                 'service_years', 'has_disciplinary_case', 'employment_type', 'separation_reason', 'settlement_authorized')
    def _compute_eligibility_notes(self):
        for rec in self:
            rec.eligibility_notes = '\n'.join([
                '-- Separation Context',
                'Separation Reason : %s' % (rec.separation_reason or 'N/A'),
                'Employment Type   : %s' % (rec.employment_type or 'N/A'),
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
            rec._compute_service_years()
            rec._compute_eligibility_context()
            rec._compute_pf_eligible()
            rec._compute_severance_eligible()
            rec._compute_outstanding_debt()
            rec._compute_remaining_salary()
            rec._compute_salary_deductions()
            rec._compute_accrued_leave_pay()
            rec._compute_total()
        return {
            'type': 'ir.actions.client',
            'tag':  'display_notification',
            'params': {'title': 'Recalculated', 'message': 'All benefit amounts recalculated.', 'type': 'success', 'sticky': False},
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
            rec.paid_date = False

    def action_confirm_settlement(self):
        """HR Officer (POMD) submits for approval → waiting_approval.
           HR Manager can bypass directly to confirmed."""
        is_hr_manager = (
            self.env.user.has_group('hr_resignation.group_resignation_hr_manager')
            or self.env.user.has_group('base.group_system')
        )
        is_hr_officer = (
            self.env.user.has_group('hr.group_hr_user')
            or self.env.user.has_group('hr_resignation.group_pomd_officer')
        )

        if not is_hr_manager and not is_hr_officer:
            raise UserError(_(
                'Only an HR Officer or HR Manager can process a settlement.'
            ))

        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft settlements can be submitted.'))
            if rec.outstanding_debt_deduction > 0 and not rec.settlement_authorized:
                raise UserError(_('Cannot submit: Outstanding debts must be settled first.'))

            if is_hr_manager:
                # HR Manager can confirm directly without waiting for approval
                rec.state = 'confirmed'
                rec.processed_by_id = self.env.user.id
                rec.processed_date = fields.Datetime.now()
                rec.confirmed_by_id = self.env.user.id
                rec.confirmed_date = fields.Datetime.now()
            else:
                # HR Officer submits for HR Manager approval
                rec.state = 'waiting_approval'
                rec.processed_by_id = self.env.user.id
                rec.processed_date = fields.Datetime.now()

    def action_approve_settlement(self):
        """Only HR Manager can approve a settlement that is waiting for approval."""
        if not self.env.user.has_group('hr_resignation.group_resignation_hr_manager') \
                and not self.env.user.has_group('base.group_system'):
            raise UserError(_('Only an HR Manager can approve the settlement.'))
        for rec in self:
            if rec.state != 'waiting_approval':
                raise UserError(_('Settlement must be in Waiting Approval state to approve.'))
            rec.state = 'confirmed'
            rec.confirmed_by_id = self.env.user.id
            rec.confirmed_date = fields.Datetime.now()

    def action_mark_paid(self):
        """HR Manager or HR Officer can mark a confirmed settlement as paid."""
        is_hr = (
            self.env.user.has_group('hr_resignation.group_resignation_hr_manager')
            or self.env.user.has_group('hr.group_hr_user')
            or self.env.user.has_group('hr_resignation.group_pomd_officer')
            or self.env.user.has_group('base.group_system')
        )
        if not is_hr:
            raise UserError(_(
                'Only an HR Officer or HR Manager can make the final payment.'
            ))
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_('Only confirmed settlements can be marked as paid.'))
            rec.state = 'paid'
            rec.paid_by_id = self.env.user.id
            rec.paid_date = fields.Datetime.now()
            if rec.resignation_id and rec.resignation_id.state == 'cleared':
                rec.resignation_id.state = 'settled'

    def write(self, vals):
        return super().write(vals)
