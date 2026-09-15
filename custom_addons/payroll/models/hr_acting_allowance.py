# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

import logging
from datetime import date
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class HrActingAssignment(models.Model):
    """
    Managerial Acting Assignment Lifecycle & Allowance Gatekeeper (FR-PAY-026, 027, 028).
    
    Enforces the bank's strict acting compensation governance:
    * Eligibility: Formal assignment to managerial job position in an acting capacity.
    * Month 1: 0% payout (buffer/probationary period).
    * Months 2 to 6: 100% full acting allowance payment.
    * Month 7+: Automatic hard-stop of payment and notification trigger for permanent decision.
    """
    _name = 'hr.acting.assignment'
    _description = 'Managerial Acting Role Assignment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_date desc, id desc'

    name = fields.Char(string='Reference', compute='_compute_name', store=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True, index=True)
    acting_job_id = fields.Many2one('hr.job', string='Acting Managerial Position', required=True, tracking=True)
    acting_grade_id = fields.Many2one('employee.grade', string='Acting Grade Level')
    
    start_date = fields.Date(string='Effective Start Date', required=True, default=fields.Date.context_today, tracking=True)
    end_date = fields.Date(string='Planned / Actual End Date', tracking=True)
    
    # Duration tracking (FR-PAY-027)
    elapsed_months = fields.Integer(string='Elapsed Active Months', compute='_compute_duration_metrics', store=True)
    current_cycle_status = fields.Selection([
        ('month_1_buffer', 'Month 1: Buffer Period (0% Allowance)'),
        ('active_paying', 'Months 2-6: Active Payout (100% Allowance)'),
        ('month_7_capped', 'Month 7+: Exceeded Limit (0% Auto-Capped)'),
        ('ended', 'Assignment Ended'),
    ], string='Payment Policy Status', compute='_compute_duration_metrics', store=True, tracking=True)
    
    payout_multiplier = fields.Float(
        string='Allowance Payout Multiplier',
        compute='_compute_duration_metrics',
        store=True,
        digits=(3, 2),
        help="0.0 for Month 1 and Month 7+; 1.0 for Months 2 to 6."
    )

    # Financial Base Amount
    fixed_allowance_amount = fields.Float(
        string='Configured Monthly Allowance (ETB)',
        digits=(16, 2),
        tracking=True,
        help="If specified, pays this fixed amount. Otherwise computes the grade delta."
    )

    state = fields.Selection([
        ('draft', 'Draft Request'),
        ('approved', 'Approved & Active'),
        ('capped', 'Auto-Capped (Month 7 Alert)'),
        ('completed', 'Completed / Terminated'),
        ('cancelled', 'Cancelled'),
    ], string='Assignment State', default='draft', required=True, tracking=True)

    approver_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    approval_date = fields.Date(string='Approval Date', readonly=True)
    notes = fields.Text(string='Justification & Terms')

    @api.depends('employee_id.name', 'acting_job_id.name', 'start_date')
    def _compute_name(self):
        for rec in self:
            if rec.employee_id and rec.acting_job_id:
                rec.name = f"ACT/{rec.employee_id.name}/{rec.acting_job_id.name}/{rec.start_date}"
            else:
                rec.name = "ACT/NEW"

    @api.constrains('acting_job_id', 'employee_id')
    def _check_managerial_role(self):
        """FR-PAY-026: Restrict Acting Allowance exclusively to managerial roles."""
        for rec in self:
            job_title = (rec.acting_job_id.name or '').lower()
            is_managerial = any(term in job_title for term in ['manager', 'director', 'chief', 'head', 'vp', 'supervisor', 'controller'])
            if not is_managerial:
                raise ValidationError(_("Acting allowance is strictly restricted to managerial job roles. Position '%s' does not qualify as managerial.") % rec.acting_job_id.name)

    @api.depends('start_date', 'end_date', 'state')
    def _compute_duration_metrics(self):
        """
        Evaluate duration and determine exact payment schedule (FR-PAY-028).
        """
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.start_date:
                rec.elapsed_months = 0
                rec.current_cycle_status = 'month_1_buffer'
                rec.payout_multiplier = 0.0
                continue

            ref_date = min(rec.end_date, today) if rec.end_date else today
            rdelta = relativedelta(ref_date, rec.start_date)
            months = (rdelta.years * 12) + rdelta.months + (1 if rdelta.days > 0 else 0)
            rec.elapsed_months = max(1, months)

            if rec.state in ['completed', 'cancelled']:
                rec.current_cycle_status = 'ended'
                rec.payout_multiplier = 0.0
            elif rec.elapsed_months == 1:
                rec.current_cycle_status = 'month_1_buffer'
                rec.payout_multiplier = 0.0
            elif 2 <= rec.elapsed_months <= 6:
                rec.current_cycle_status = 'active_paying'
                rec.payout_multiplier = 1.0
            else:  # Month 7+
                rec.current_cycle_status = 'month_7_capped'
                rec.payout_multiplier = 0.0

    def action_approve(self):
        """Approve and activate acting assignment."""
        for rec in self:
            rec.write({
                'state': 'approved',
                'approver_id': self.env.user.id,
                'approval_date': fields.Date.today()
            })
            rec.message_post(body=_("Managerial acting assignment approved by %s.") % self.env.user.name)

    def action_terminate(self):
        """End acting assignment."""
        for rec in self:
            rec.write({
                'state': 'completed',
                'end_date': fields.Date.today()
            })
            rec.message_post(body=_("Managerial acting assignment officially terminated."))

    def get_monthly_payout_amount(self, for_date=None):
        """
        Public calculation API called during payslip execution.
        Returns the exact calculated acting allowance for the target date taking into account
        the 1-month buffer and 6-month cap.
        """
        self.ensure_one()
        if self.state not in ['approved', 'capped']:
            return 0.0

        eval_date = for_date or fields.Date.today()
        rdelta = relativedelta(eval_date, self.start_date)
        month_idx = (rdelta.years * 12) + rdelta.months + 1

        if month_idx == 1 or month_idx > 6:
            return 0.0

        if self.fixed_allowance_amount > 0:
            return self.fixed_allowance_amount

        # Default standard: 20% of employee's basic wage
        base_wage = getattr(self.employee_id, 'wage', 0.0) or getattr(self.employee_id, 'basic_salary', 0.0)
        return round(base_wage * 0.20, 2)

    @api.model
    def _cron_check_acting_durations(self):
        """Daily monitor checking for acting assignments reaching 7+ months cap."""
        today = fields.Date.context_today(self)
        active_assignments = self.search([('state', '=', 'approved')])
        for assign in active_assignments:
            assign._compute_duration_metrics()
            if assign.elapsed_months >= 7 and assign.state == 'approved':
                assign.write({'state': 'capped'})
                assign.message_post(body=_(
                    "ALERT: Acting assignment has exceeded 6 months (Elapsed: %d months). "
                    "Automatic payroll payout is stopped per bank policy. Please formalize permanent appointment or end assignment."
                ) % assign.elapsed_months)
