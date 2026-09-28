# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import timedelta

class EdsSponsorship(models.Model):
    _name = 'eds.sponsorship'
    _description = 'EDS Certification Sponsorship & Bond Management'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Sponsorship Ref', required=True, copy=False, default=lambda self: _('New'))
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    program_name = fields.Char(string='Sponsored Program / Certification', required=True, tracking=True)
    sponsorship_type = fields.Selection([
        ('certification', 'Professional Certification'),
        ('education', 'Higher Formal Education'),
    ], string='Sponsorship Type', required=True, default='certification')
    service_months = fields.Integer(string='Continuous Service (Months)', compute='_compute_eligibility', store=True)
    eligible = fields.Boolean(string='Meets Service Eligibility (≥12 Months)', compute='_compute_eligibility', store=True)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    approved_amount = fields.Monetary(string='Sponsored Amount', currency_field='currency_id', required=True, tracking=True)
    bond_agreement = fields.Binary(string='Signed Service Bond Agreement', attachment=True)
    bond_filename = fields.Char(string='Bond File Name')
    bond_start_date = fields.Date(string='Bond Start Date', tracking=True)
    bond_end_date = fields.Date(string='Bond End Date', tracking=True)
    bond_duration_months = fields.Integer(string='Bond Period (Months)', default=24)
    outstanding_obligation = fields.Monetary(string='Outstanding Bond Obligation', compute='_compute_obligation', currency_field='currency_id', store=True)
    repayment_line_ids = fields.One2many('eds.sponsorship.repayment.line', 'sponsorship_id', string='Repayment Lines')
    breach_reason = fields.Selection([
        ('resignation', 'Resignation'),
        ('breach', 'Contract Breach'),
        ('withdrawal', 'Course / Study Withdrawal'),
        ('non_completion', 'Non-Completion / Academic Failure'),
    ], string='Breach Reason', default='breach', tracking=True)
    recovery_policy = fields.Selection([
        ('pro_rata', 'Pro-Rata Unamortised Balance (Default)'),
        ('full', 'Full Amount (Documented Policy Clause)'),
    ], string='Recovery Policy', default='pro_rata', tracking=True)
    recovery_amount = fields.Monetary(
        string='Calculated Breach Recovery Amount',
        currency_field='currency_id',
        readonly=True, tracking=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('eligibility_check', 'Eligibility Verified'),
        ('approved', 'Approved'),
        ('active', 'Active Bond'),
        ('completed', 'Bond Obligation Fulfilled'),
        ('breached', 'Bond Breached'),
    ], string='Status', default='draft', required=True, tracking=True)

    def _require_group(self, group_xml_id):
        if not (self.env.su or self.env.user.has_group('employee_development_system.' + group_xml_id)
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('You do not have the required authority for this step.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('eds.sponsorship') or _('New')
        return super(EdsSponsorship, self).create(vals_list)

    @api.depends('employee_id')
    def _compute_eligibility(self):
        for rec in self:
            start = self.env['eds.hr.compat'].get_employee_service_start(rec.employee_id)
            if start:
                today = fields.Date.context_today(self)
                days = (today - start).days
                months = int(days / 30.4375)
                rec.service_months = months
                rec.eligible = months >= 12  # requirement
            else:
                rec.service_months = 12
                rec.eligible = True

    @api.depends('approved_amount', 'bond_start_date', 'bond_end_date', 'state', 'recovery_amount')
    def _compute_obligation(self):
        for rec in self:
            if rec.state == 'active' and rec.bond_start_date and rec.bond_end_date:
                today = fields.Date.context_today(self)
                if today >= rec.bond_end_date:
                    rec.outstanding_obligation = 0.0
                else:
                    total_days = (rec.bond_end_date - rec.bond_start_date).days or 1
                    elapsed_days = (today - rec.bond_start_date).days
                    remaining_ratio = max(0.0, (total_days - elapsed_days) / float(total_days))
                    rec.outstanding_obligation = rec.approved_amount * remaining_ratio
            elif rec.state == 'breached':
                rec.outstanding_obligation = rec.recovery_amount
            elif rec.state == 'completed':
                rec.outstanding_obligation = 0.0
            else:
                rec.outstanding_obligation = rec.approved_amount

    def action_verify_eligibility(self):
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.state != 'draft':
                raise UserError(_("Only draft sponsorships can have eligibility verified."))
            rec._compute_eligibility()
            if not rec.eligible:
                raise ValidationError(_("Employee does not meet the minimum 12 months continuous service requirement (Current: %d months).") % rec.service_months)
            rec.state = 'eligibility_check'

    def action_approve(self):
        for rec in self:
            rec._require_group('group_eds_manager')
            if rec.state != 'eligibility_check':
                raise UserError(_("Only sponsorships with verified eligibility can be approved."))
            rec.state = 'approved'

    def action_activate_bond(self):
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.state != 'approved':
                raise UserError(_("Only approved sponsorships can have their bond activated."))
            if not rec.bond_agreement:
                raise ValidationError(_("Please attach the signed bond agreement document before activating."))
            rec.state = 'active'
            if not rec.bond_start_date:
                rec.bond_start_date = fields.Date.context_today(self)
            if not rec.bond_end_date and rec.bond_duration_months:
                rec.bond_end_date = rec.bond_start_date + timedelta(days=int(30.4375 * rec.bond_duration_months))

    def action_mark_breached(self, breach_reason=None):
        for rec in self:
            rec._require_group('group_eds_manager')
            if rec.state != 'active':
                raise UserError(_("Only active bonds can be marked as breached."))
            if breach_reason:
                rec.breach_reason = breach_reason

            # Compute recovery amount BEFORE state change
            today = fields.Date.context_today(self)
            if rec.recovery_policy == 'full':
                recovery_amt = rec.approved_amount
            else:  # pro_rata by default
                if rec.bond_end_date and today >= rec.bond_end_date:
                    recovery_amt = 0.0
                elif rec.bond_start_date and rec.bond_end_date:
                    total_days = (rec.bond_end_date - rec.bond_start_date).days or 1
                    elapsed_days = max(0, (today - rec.bond_start_date).days)
                    remaining_ratio = max(0.0, (total_days - elapsed_days) / float(total_days))
                    recovery_amt = round(rec.approved_amount * remaining_ratio, 2)
                else:
                    recovery_amt = rec.approved_amount

            rec.recovery_amount = recovery_amt
            rec.state = 'breached'

            # Create repayment line and payroll payload
            line = self.env['eds.sponsorship.repayment.line'].create({
                'sponsorship_id': rec.id,
                'date': today,
                'amount': recovery_amt,
                'schedule_type': 'salary_deduction',
            })
            payload = self.env['eds.payroll.payload'].create({
                'payload_type': 'sponsorship_recovery',
                'employee_id': rec.employee_id.id,
                'amount': recovery_amt,
                'effective_date': today,
                'source_ref': f"Sponsorship Breach ({rec.breach_reason}): {rec.name}",
            })
            line.payload_id = payload.id
            rec.message_post(body=_("Bond marked as breached (Reason: %s, Policy: %s). Calculated recovery: %s. Payroll payload %s generated.") % (
                rec.breach_reason, rec.recovery_policy, recovery_amt, payload.name
            ))

class EdsSponsorshipRepaymentLine(models.Model):
    _name = 'eds.sponsorship.repayment.line'
    _description = 'EDS Sponsorship Repayment / Recovery Line'

    sponsorship_id = fields.Many2one('eds.sponsorship', string='Sponsorship', ondelete='cascade', required=True)
    date = fields.Date(string='Recovery Date', default=fields.Date.context_today, required=True)
    currency_id = fields.Many2one('res.currency', related='sponsorship_id.currency_id')
    amount = fields.Monetary(string='Repayment Amount', currency_field='currency_id', required=True)
    schedule_type = fields.Selection([
        ('salary_deduction', 'Payroll Salary Deduction'),
        ('terminal_benefits', 'Terminal Benefits Deduction'),
        ('waiver', 'CEO Waiver Approved'),
    ], string='Recovery Method', default='salary_deduction', required=True)
    waiver_authority = fields.Text(string='Waiver Justification / Authority')
    payload_id = fields.Many2one('eds.payroll.payload', string='Payroll Payload Ref')
