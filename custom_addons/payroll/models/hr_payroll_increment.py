# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

import logging
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class PayrollIncrementCampaign(models.Model):
    """
    Annual Salary Increment Campaign Management Engine.
    
    Manages bank-wide annual compensation revisions effective July 1 (Hamle 1 Ethiopian Calendar).
    Supports multiple increment schemes (Flat multiplier, Grade step cofactor matrix, PMS performance tiers),
    service duration proration for mid-year joiners, and dual-mode retroactive back-increment arrears
    disbursement (Injected into regular monthly payroll or paid separately via dedicated CBS payment batch).
    """
    _name = 'payroll.increment.campaign'
    _description = 'Annual Salary Increment Campaign'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'effective_date desc, id desc'

    name = fields.Char(
        string='Campaign Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('payroll.increment.campaign') or _('New')
    )
    title = fields.Char(
        string='Campaign Title',
        required=True,
        tracking=True,
        help="E.g., FY 2025/2026 Annual Staff Salary Increment"
    )
    fiscal_year = fields.Char(
        string='Fiscal Year',
        required=True,
        default=lambda self: f"{fields.Date.today().year - 1}/{fields.Date.today().year}",
        tracking=True,
        help="Ethiopian / Gregorian Fiscal Year label (e.g. 2025/2026)"
    )
    effective_date = fields.Date(
        string='Effective Date',
        required=True,
        default=lambda self: date(fields.Date.today().year, 7, 1),
        tracking=True,
        help="Statutory & policy effective date (Default: July 1 of current year)."
    )
    approval_date = fields.Date(
        string='Board / Management Approval Date',
        default=fields.Date.context_today,
        tracking=True,
        help="Date when board or executive management formally approved the increment."
    )
    
    calculation_method = fields.Selection([
        ('flat_multiplier', 'Flat Basic Wage Multiple / Factor (e.g. 1.5x Step / Base %)'),
        ('grade_step_cofactor', 'Grade Step Increment Matrix & Cofactor'),
        ('pms_performance', 'PMS Performance Matrix & Rating Tier Multiplier'),
    ], string='Calculation Method', default='flat_multiplier', required=True, tracking=True)

    base_multiplier = fields.Float(
        string='Base Multiplier / Factor',
        default=1.5,
        digits=(16, 3),
        tracking=True,
        help="Multiplier applied to base salary, step increment, or salary factor (e.g. 1.5 for 1.5x increment)."
    )
    percentage_rate = fields.Float(
        string='Flat Percentage Rate (%)',
        default=0.0,
        digits=(16, 2),
        tracking=True,
        help="Optional percentage increase added to basic salary if flat percentage scheme is selected."
    )

    disbursement_mode = fields.Selection([
        ('monthly_payroll', 'Mode A: Injected into Regular Monthly Payroll (Retroactive Arrears Rule)'),
        ('separate_batch', 'Mode B: Paid Separately via Dedicated "Back Increment" CBS Batch'),
    ], string='Back-Increment Disbursement Mode', default='separate_batch', required=True, tracking=True,
       help="Determines how retroactive arrears from July 1 to approval month are disbursed to staff.")

    prorate_joiners = fields.Boolean(
        string='Prorate Mid-Year Joiners',
        default=True,
        help="Prorate increment for employees with less than 12 months service in the fiscal year."
    )
    min_service_months = fields.Integer(
        string='Minimum Service Months for Eligibility',
        default=3,
        help="Employees with fewer service months than this threshold receive 0% increment."
    )
    exclude_disciplined = fields.Boolean(
        string='Exclude Active Disciplinary Staff',
        default=True,
        help="Automatically disqualify or skip employees with active disciplinary sanctions."
    )

    department_ids = fields.Many2many(
        'hr.department',
        'payroll_increment_dept_rel',
        'campaign_id',
        'dept_id',
        string='Target Departments',
        help="Leave empty to apply bank-wide to all eligible employees."
    )
    operating_unit_ids = fields.Many2many(
        'operating.unit',
        'payroll_increment_ou_rel',
        'campaign_id',
        'ou_id',
        string='Target Branches / Operating Units',
        help="Leave empty to include all branches and head office."
    )

    line_ids = fields.One2many(
        'payroll.increment.line',
        'campaign_id',
        string='Employee Increment Schedules',
        copy=False
    )

    # Financial & Operational Aggregates
    total_beneficiaries = fields.Integer(string='Eligible Beneficiaries', compute='_compute_totals', store=True)
    total_current_basic = fields.Float(string='Total Current Monthly Basic (ETB)', compute='_compute_totals', store=True, digits=(16, 2))
    total_new_basic = fields.Float(string='Total New Monthly Basic (ETB)', compute='_compute_totals', store=True, digits=(16, 2))
    total_monthly_increment = fields.Float(string='Monthly Salary Increment Impact (ETB)', compute='_compute_totals', store=True, digits=(16, 2))
    total_retroactive_arrears = fields.Float(string='Total Back-Increment Arrears (ETB)', compute='_compute_totals', store=True, digits=(16, 2))
    total_annualized_budget_impact = fields.Float(string='Annualized Budget Impact (ETB)', compute='_compute_totals', store=True, digits=(16, 2))

    # Downstream Generated Records
    retroactive_batch_ids = fields.One2many('hr.payroll.retroactive', 'increment_campaign_id', string='Spawned Retroactive Batches', readonly=True)
    payment_batch_id = fields.Many2one('payroll.payment.batch', string='Generated Back-Increment CBS Payment Batch', readonly=True, copy=False)

    state = fields.Selection([
        ('draft', 'Draft (Initiation)'),
        ('computed', 'Computed & Simulation Ready'),
        ('verified', 'Verified by HR Compensation Lead'),
        ('approved', 'Approved by VP / Board'),
        ('applied', 'Applied & Contracts Versioned'),
        ('cancelled', 'Cancelled'),
    ], string='Campaign Status', default='draft', required=True, tracking=True)

    verified_by = fields.Many2one('res.users', string='Verified By', readonly=True, copy=False)
    approved_by = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    applied_by = fields.Many2one('res.users', string='Applied By', readonly=True, copy=False)

    notes = fields.Text(string='Campaign Rationale & Board Resolution Notes')

    @api.depends('line_ids', 'line_ids.current_basic', 'line_ids.new_basic', 'line_ids.increment_amount', 'line_ids.retroactive_arrears', 'line_ids.is_eligible')
    def _compute_totals(self):
        for rec in self:
            lines = rec.line_ids.filtered(lambda l: l.is_eligible)
            rec.total_beneficiaries = len(lines)
            rec.total_current_basic = sum(lines.mapped('current_basic'))
            rec.total_new_basic = sum(lines.mapped('new_basic'))
            rec.total_monthly_increment = sum(lines.mapped('increment_amount'))
            rec.total_retroactive_arrears = sum(lines.mapped('retroactive_arrears'))
            rec.total_annualized_budget_impact = (rec.total_monthly_increment * 12.0)

    def action_compute_increment_lines(self):
        """
        Populates and calculates increment lines for all active eligible employees across the bank.
        Computes new basic wage, service proration factor, and retroactive back-increment arrears
        from the July 1 effective date to the approval date.
        """
        self.ensure_one()
        if self.state not in ('draft', 'computed'):
            raise UserError(_("Increment lines can only be recomputed in Draft or Computed state."))

        # Clear existing lines
        self.line_ids.unlink()

        domain = [
            ('active', '=', True),
        ]
        if self.department_ids:
            domain.append(('department_id', 'in', self.department_ids.ids))
        if self.operating_unit_ids and 'operating_unit_id' in self.env['hr.employee']._fields:
            domain.append(('operating_unit_id', 'in', self.operating_unit_ids.ids))

        employees = self.env['hr.employee'].search(domain)
        if not employees:
            raise UserError(_("No eligible active employees found matching the campaign criteria."))

        # Determine elapsed retroactive months between July 1 and Approval Date
        eff_date = self.effective_date or date(fields.Date.today().year, 7, 1)
        app_date = self.approval_date or fields.Date.today()
        
        # Calculate full retroactive months elapsed
        retro_months = 0
        if app_date > eff_date:
            r_delta = relativedelta(app_date, eff_date)
            retro_months = max(0, r_delta.years * 12 + r_delta.months)

        new_lines = []
        for emp in employees:
            # 1. Fetch current active basic salary
            current_basic = emp.basic_salary or 0.0
            
            # If basic_salary is 0 on employee, check active running contract (hr.version)
            if current_basic <= 0.0:
                contract = self.env['hr.version'].search([
                    ('employee_id', '=', emp.id),
                    ('state', 'in', ['open', 'draft', 'probation'])
                ], order='id desc', limit=1)
                if contract:
                    current_basic = contract.wage or contract.base_salary or 0.0

            # 2. Check service duration & proration
            hire_date = emp.joining_date or emp.first_contract_date or eff_date
            service_months = 12
            proration_factor = 1.0
            is_eligible = True
            ineligibility_reason = False

            if hire_date:
                # Service months within the preceding 12 months up to July 1
                fy_start = eff_date - relativedelta(years=1)
                if hire_date > eff_date:
                    is_eligible = False
                    ineligibility_reason = _("Joined after campaign effective date (%s).") % eff_date
                elif hire_date > fy_start:
                    delta = relativedelta(eff_date, hire_date)
                    service_months = max(1, delta.years * 12 + delta.months + (1 if delta.days >= 15 else 0))
                    if service_months < self.min_service_months:
                        is_eligible = False
                        ineligibility_reason = _("Service duration (%d months) below minimum threshold (%d months).") % (service_months, self.min_service_months)
                    elif self.prorate_joiners:
                        proration_factor = min(1.0, service_months / 12.0)

            # 3. Check Disciplinary Action status
            if is_eligible and self.exclude_disciplined:
                if 'discipline.case' in self.env:
                    active_disc = self.env['discipline.case'].search_count([
                        ('employee_id', '=', emp.id),
                        ('state', 'in', ['approved', 'action_applied', 'in_progress'])
                    ])
                    if active_disc > 0:
                        is_eligible = False
                        ineligibility_reason = _("Excluded due to active disciplinary record.")

            # 4. Compute Increment Amount based on selected scheme
            raw_increment = 0.0
            grade = emp.grade_id or (emp.job_grade if 'job_grade' in emp._fields else False)
            pms_score = emp.pms_score if hasattr(emp, 'pms_score') and emp.pms_score else 0.0
            
            # Fetch PMS score from contract if not on employee
            if not pms_score:
                active_ver = self.env['hr.version'].search([
                    ('employee_id', '=', emp.id)
                ], order='id desc', limit=1)
                if active_ver and hasattr(active_ver, 'pms_score'):
                    pms_score = active_ver.pms_score or 0.0

            if self.calculation_method == 'flat_multiplier':
                if self.percentage_rate > 0.0:
                    raw_increment = current_basic * (self.percentage_rate / 100.0)
                else:
                    step_val = (current_basic * 0.05)
                    raw_increment = step_val * (self.base_multiplier or 1.5)

            elif self.calculation_method == 'grade_step_cofactor':
                step_val = 0.0
                if grade and hasattr(grade, 'increment_id') and grade.increment_id:
                    inc_row = grade.increment_id[0]
                    step_val = inc_row.amount_1 or (grade.base_salary * 0.05 if hasattr(grade, 'base_salary') else current_basic * 0.05)
                else:
                    step_val = current_basic * 0.05
                raw_increment = step_val * (self.base_multiplier or 1.0)

            elif self.calculation_method == 'pms_performance':
                perf_multiplier = 1.0
                if pms_score >= 120.0:
                    perf_multiplier = 2.0
                elif pms_score >= 100.0:
                    perf_multiplier = 1.5
                elif pms_score >= 85.0:
                    perf_multiplier = 1.25
                elif pms_score >= 75.0:
                    perf_multiplier = 1.0
                elif pms_score >= 50.0:
                    perf_multiplier = 0.5
                else:
                    perf_multiplier = 0.0

                base_step = current_basic * 0.05
                raw_increment = base_step * (self.base_multiplier or 1.0) * perf_multiplier

            # Apply service proration
            final_increment = round(raw_increment * proration_factor, 2) if is_eligible else 0.0
            new_basic = current_basic + final_increment if is_eligible else current_basic
            
            # Retroactive back-increment arrears: (New Basic - Old Basic) * Elapsed Closed Months
            retro_arrears = round(final_increment * retro_months, 2) if (is_eligible and retro_months > 0) else 0.0

            line_vals = {
                'campaign_id': self.id,
                'employee_id': emp.id,
                'department_id': emp.department_id.id if emp.department_id else False,
                'job_id': emp.job_id.id if emp.job_id else False,
                'grade_id': grade.id if grade else False,
                'current_basic': current_basic,
                'pms_score': pms_score,
                'service_months': service_months,
                'proration_factor': proration_factor,
                'is_eligible': is_eligible,
                'ineligibility_reason': ineligibility_reason,
                'increment_amount': final_increment,
                'new_basic': new_basic,
                'retroactive_months': retro_months,
                'retroactive_arrears': retro_arrears,
                'bank_account': emp.bank_account_number if hasattr(emp, 'bank_account_number') else (emp.account_number if hasattr(emp, 'account_number') else ''),
            }
            new_lines.append((0, 0, line_vals))

        self.write({
            'line_ids': new_lines,
            'state': 'computed',
        })
        self.message_post(
            body=_("Successfully computed Annual Salary Increment campaign with %d employee schedules.") % len(new_lines),
            subtype_xmlid='mail.mt_note'
        )
        return True

    def action_verify(self):
        """Moves campaign to Verified state after compensation review."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Cannot verify a campaign with no computed employee schedules."))
        self.write({
            'state': 'verified',
            'verified_by': self.env.user.id,
        })
        self.message_post(body=_("Campaign verified by Compensation Lead: %s") % self.env.user.name)

    def action_approve(self):
        """Moves campaign to Approved state following Board/VP authorization."""
        self.ensure_one()
        self.write({
            'state': 'approved',
            'approved_by': self.env.user.id,
        })
        self.message_post(body=_("Campaign formally approved by Board / VP: %s") % self.env.user.name)

    def action_apply_and_disburse(self):
        """
        Executes the approved increment campaign across the enterprise:
        1. Updates/Versions employee contracts (`hr.version`) with new basic wage anchored to July 1.
        2. Synchronizes master employee records (`hr.employee.basic_salary`).
        3. Spawns retroactive arrears according to the chosen disbursement mode:
           - Mode A: Generates `hr.payroll.retroactive` adjustments to inject into next monthly payroll.
           - Mode B: Spawns dedicated "Back Increment" CBS direct credit payment batch (`payroll.payment.batch`).
        4. Writes audit log entries for immutability.
        """
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_("Campaign must be in 'Approved' state prior to applying contract updates."))

        eligible_lines = self.line_ids.filtered(lambda l: l.is_eligible and l.increment_amount > 0.0)
        if not eligible_lines:
            raise UserError(_("No eligible increment lines found to apply."))

        # 1. Update Contracts & Master Employee Data
        updated_count = 0
        for line in eligible_lines:
            emp = line.employee_id
            
            # Update employee master
            emp.sudo().write({'basic_salary': line.new_basic})

            # Update / Version hr.version contract
            contract = self.env['hr.version'].search([
                ('employee_id', '=', emp.id),
                ('state', 'in', ['open', 'draft', 'probation'])
            ], order='id desc', limit=1)
            
            if contract:
                contract.sudo().write({
                    'wage': line.new_basic,
                    'base_salary': line.new_basic,
                })
            else:
                # Create contract version if none exists
                self.env['hr.version'].sudo().create({
                    'name': _("Contract - %s (July 1 Increment)") % emp.name,
                    'employee_id': emp.id,
                    'wage': line.new_basic,
                    'base_salary': line.new_basic,
                    'contract_date_start': self.effective_date,
                    'state': 'open',
                })
            updated_count += 1

        # 2. Handle Retroactive Back-Increment Arrears
        if self.disbursement_mode == 'monthly_payroll':
            # Mode A: Spawn hr.payroll.retroactive records
            for line in eligible_lines.filtered(lambda l: l.retroactive_arrears > 0.0):
                retro = self.env['hr.payroll.retroactive'].sudo().create({
                    'employee_id': line.employee_id.id,
                    'reason': 'backdated_increment',
                    'effective_date': self.effective_date,
                    'increment_campaign_id': self.id,
                    'notes': _("Auto-generated arrears from Annual Increment Campaign '%s' (%d months).") % (self.title, line.retroactive_months),
                })
                # Add breakdown line
                self.env['hr.payroll.retroactive.line'].sudo().create({
                    'retroactive_id': retro.id,
                    'component_code': 'BASIC',
                    'component_name': _("Basic Salary Arrears (July 1 Increment)"),
                    'original_amount': line.current_basic * line.retroactive_months,
                    'revised_amount': line.new_basic * line.retroactive_months,
                    'variance_amount': line.retroactive_arrears,
                    'adjustment_type': 'arrears',
                })
                retro.action_compute_diff()
                retro.action_confirm()
            self.message_post(body=_("Spawned individual retroactive adjustment batches for regular payroll injection."))

        elif self.disbursement_mode == 'separate_batch':
            # Mode B: Generate dedicated "Back Increment" CBS Direct Credit Payment Batch
            batch_lines = []
            for line in eligible_lines.filtered(lambda l: l.retroactive_arrears > 0.0):
                acc_num = line.bank_account or (line.employee_id.bank_account_number if hasattr(line.employee_id, 'bank_account_number') else '0000000000')
                batch_lines.append((0, 0, {
                    'employee_id': line.employee_id.id,
                    'beneficiary_name': line.employee_id.name,
                    'bank_account_number': acc_num or '0000000000',
                    'amount': line.retroactive_arrears,
                    'narrative': _("Back Increment Arrears (%s - %d Mos)") % (self.fiscal_year, line.retroactive_months),
                }))

            if batch_lines:
                pay_batch = self.env['payroll.payment.batch'].sudo().create({
                    'name': _("Back Increment CBS Payment Batch - %s") % self.title,
                    'payment_date': fields.Date.today(),
                    'export_format': 'cbs_csv',
                    'increment_campaign_id': self.id,
                    'line_ids': batch_lines,
                })
                self.payment_batch_id = pay_batch.id
                pay_batch.action_generate_export_file()
                self.message_post(body=_("Generated dedicated CBS Back-Increment Direct Credit Batch: %s") % pay_batch.name)

        # 3. Log Immutable Audit Log
        if 'hr.payroll.audit.log' in self.env:
            self.env['hr.payroll.audit.log'].sudo().log_event(
                event_type='override_approved',
                description=_("Applied July 1 Annual Salary Increment to %d employees. Total Monthly Increase: ETB %s, Total Retroactive Arrears: ETB %s.") % (
                    updated_count, f"{self.total_monthly_increment:,.2f}", f"{self.total_retroactive_arrears:,.2f}"
                ),
                model='payroll.increment.campaign',
                res_id=self.id,
            )

        self.write({
            'state': 'applied',
            'applied_by': self.env.user.id,
        })
        self.message_post(body=_("Increment successfully applied to %d employee contracts.") % updated_count)
        return True

    def action_reset_draft(self):
        """Resets campaign to draft."""
        self.ensure_one()
        if self.state == 'applied':
            raise UserError(_("Cannot reset an already applied campaign. Contract revisions must be reverted manually."))
        self.write({'state': 'draft'})


class PayrollIncrementLine(models.Model):
    """Individual Employee Annual Salary Increment Schedule Line."""
    _name = 'payroll.increment.line'
    _description = 'Employee Annual Increment Line'
    _order = 'department_id, employee_id'

    campaign_id = fields.Many2one('payroll.increment.campaign', string='Campaign', required=True, ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, index=True)
    department_id = fields.Many2one('hr.department', string='Department', store=True)
    job_id = fields.Many2one('hr.job', string='Job Position', store=True)
    grade_id = fields.Many2one('employee.grade', string='Grade')
    
    current_basic = fields.Float(string='Current Basic (ETB)', digits=(16, 2), required=True)
    pms_score = fields.Float(string='PMS Score', digits=(16, 2))
    service_months = fields.Integer(string='Service Months in FY', default=12)
    proration_factor = fields.Float(string='Proration Factor', default=1.0, digits=(16, 3))
    
    is_eligible = fields.Boolean(string='Eligible', default=True)
    ineligibility_reason = fields.Char(string='Ineligibility Reason')

    increment_amount = fields.Float(string='Monthly Increment (ETB)', digits=(16, 2), required=True)
    new_basic = fields.Float(string='New Basic Salary (ETB)', digits=(16, 2), required=True)
    
    retroactive_months = fields.Integer(string='Retroactive Months', default=0)
    retroactive_arrears = fields.Float(string='Back-Increment Arrears (ETB)', digits=(16, 2), default=0.0)
    
    bank_account = fields.Char(string='Bank Account Number')
