# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class HrPayrollCutoffOverride(models.Model):
    """
    Formally Audited Cut-Off Override Governance Model.
    
    When payroll is locked post-cutoff date, no standard HR data modifications can enter the pay cycle.
    Emergency late changes (urgent bonus, executive joining, critical correction) must follow this formal,
    segregated override request and multi-tier approval workflow.
    """
    _name = 'hr.payroll.cutoff.override'
    _description = 'Payroll Cut-Off Exception Override Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'request_date desc, id desc'

    name = fields.Char(
        string='Override Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('hr.payroll.cutoff.override') or _('New')
    )
    period_id = fields.Many2one('hr.payroll.period', string='Locked Pay Period', required=True, tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Affected Employee', required=True, tracking=True)
    
    override_category = fields.Selection([
        ('late_joiner', 'Emergency Late Joiner Addition'),
        ('salary_adjustment', 'Critical Late Salary Adjustment'),
        ('disciplinary_correction', 'Urgent Disciplinary Deduction Rectification'),
        ('separation_payout', 'Expedited Separation Final Settlement'),
        ('other_exception', 'Other Executive Exceptional Override'),
    ], string='Override Category', required=True, tracking=True)

    financial_impact_estimate = fields.Float(string='Estimated Financial Impact (ETB)', digits=(16, 2), tracking=True)
    justification = fields.Text(string='Business Justification & Audit Rationale', required=True, tracking=True)

    state = fields.Selection([
        ('submitted', 'Submitted by HR Accountant'),
        ('verified', 'Verified by Sr Controller'),
        ('approved', 'Approved by Division Manager'),
        ('rejected', 'Rejected'),
    ], string='Status', default='submitted', required=True, tracking=True)

    initiator_id = fields.Many2one('res.users', string='Initiator (HR Accountant)', default=lambda self: self.env.user, readonly=True)
    request_date = fields.Date(string='Submission Date', default=fields.Date.context_today, readonly=True)
    
    verifier_id = fields.Many2one('res.users', string='Verified By (Senior Controller)', readonly=True)
    verification_date = fields.Date(string='Verification Date', readonly=True)
    
    approver_id = fields.Many2one('res.users', string='Final Approver (Division Manager)', readonly=True)
    approval_date = fields.Date(string='Approval Date', readonly=True)
    
    rejection_reason = fields.Text(string='Rejection Justification')

    def action_verify(self):
        """Senior Controller verification step."""
        for rec in self:
            if not self.env.user.has_group('payroll.group_payroll_verifier'):
                raise UserError(_("Only Senior Payroll Controllers can verify cut-off override requests."))
            rec.write({
                'state': 'verified',
                'verifier_id': self.env.user.id,
                'verification_date': fields.Date.today()
            })
            rec.message_post(body=_("Cut-off override verified by Senior Controller %s.") % self.env.user.name)

    def action_approve(self):
        """Division Manager final authorization."""
        for rec in self:
            if not self.env.user.has_group('payroll.group_payroll_manager'):
                raise UserError(_("Only People Service & Reward Division Managers can approve cut-off overrides."))
            rec.write({
                'state': 'approved',
                'approver_id': self.env.user.id,
                'approval_date': fields.Date.today()
            })
            # Log in immutable audit trail
            self.env['hr.payroll.audit.log'].create({
                'event_type': 'override_approved',
                'model_name': 'hr.payroll.cutoff.override',
                'res_id': rec.id,
                'employee_id': rec.employee_id.id,
                'initiator_id': rec.initiator_id.id,
                'approver_id': self.env.user.id,
                'new_value': f"Approved Override: {rec.override_category} (Impact: ETB {rec.financial_impact_estimate:.2f})",
                'description': f"Cutoff override approved for period {rec.period_id.name}. Justification: {rec.justification}"
            })
            rec.message_post(body=_("Cut-off override officially authorized by Division Manager %s.") % self.env.user.name)

    def action_reject(self):
        """Reject override request."""
        for rec in self:
            rec.write({'state': 'rejected'})
            rec.message_post(body=_("Cut-off override rejected by %s.") % self.env.user.name)
