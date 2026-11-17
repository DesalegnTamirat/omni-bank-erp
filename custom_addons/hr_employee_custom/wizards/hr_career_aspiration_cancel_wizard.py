# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrCareerAspirationCancelWizard(models.TransientModel):
    _name = 'hr.career.aspiration.cancel.wizard'
    _description = 'Career Aspiration Cancellation Wizard'

    aspiration_id = fields.Many2one(
        'hr.career.aspiration',
        string="Career Aspiration",
        required=True,
        readonly=True,
        default=lambda self: self.env.context.get('default_aspiration_id') or self.env.context.get('active_id'),
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string="Employee",
        related='aspiration_id.employee_id',
        readonly=True,
    )
    target_job_id = fields.Many2one(
        'hr.job',
        string="Target Role",
        related='aspiration_id.target_job_id',
        readonly=True,
    )
    cancel_reason = fields.Selection([
        ('tenure', 'Tenure / Experience Requirement Not Met'),
        ('performance', 'Performance Improvement Needed (PMS)'),
        ('reorg', 'Organizational Restructuring / Department Readiness'),
        ('project', 'Priority Project Commitment in Current Role'),
        ('not_aligned', 'Career Goal No Longer Aligned with Organizational Needs'),
        ('other', 'Other Reason'),
    ], string="Cancellation Reason", required=True)

    cancel_justification = fields.Text(
        string="Justification / Details",
        required=True,
        help="Provide a detailed justification for cancelling this career aspiration."
    )

    def action_confirm_cancel(self):
        self.ensure_one()
        aspiration = self.aspiration_id
        if not aspiration:
            raise UserError(_("No career aspiration record found."))

        reason_label = dict(self._fields['cancel_reason'].selection).get(self.cancel_reason, self.cancel_reason)
        full_reason = "%s: %s" % (reason_label, self.cancel_justification)

        aspiration.with_context(force_write=True).write({
            'state': 'cancelled',
            'cancel_reason': self.cancel_reason,
            'cancel_justification': self.cancel_justification,
            'cancel_date': fields.Date.today(),
            'cancel_by_user_id': self.env.user.id,
        })
        aspiration.message_post(
            body=_('Career Aspiration %s has been cancelled.\n\nReason: %s') % (aspiration.name, full_reason)
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Career Aspiration Cancelled"),
                'message': _("Career Aspiration %s has been cancelled.") % aspiration.name,
                'type': 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }
