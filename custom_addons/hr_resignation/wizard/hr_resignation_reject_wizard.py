# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError

class HrResignationRejectWizard(models.TransientModel):
    _name = 'hr.resignation.reject.wizard'
    _description = 'Resignation Rejection Wizard'

    resignation_id   = fields.Many2one('hr.resignation', required=True)
    reject_by        = fields.Selection([
        ('manager', 'Manager'),
        ('hr',      'HR'),
        ('return',  'Return'),
        ('revoke',  'Revoke'),
    ], required=True)
    rejection_reason = fields.Text(required=True, string='Reason')

    def action_confirm_reject(self):
        self.ensure_one()
        rec = self.resignation_id
        rec.rejection_reason = self.rejection_reason

        if self.reject_by == 'return':
            rec.state = 'returned'
            if rec.current_version_id and hasattr(rec.current_version_id, 'has_approved_resignation'):
                rec.current_version_id.has_approved_resignation = False
            subject = _('Resignation Returned: %s') % rec.name
            body = _('Dear %s,\n\nYour resignation request (%s) has been returned by HR for the following reason:\n\n%s') % (rec.employee_id.sudo().name, rec.name, self.rejection_reason)
        elif self.reject_by == 'revoke':
            rec.state = 'revoked'
            if rec.current_version_id and hasattr(rec.current_version_id, 'has_approved_resignation'):
                rec.current_version_id.has_approved_resignation = False
            subject = _('Resignation Revoked: %s') % rec.name
            body = _('Dear %s,\n\nYour resignation request (%s) has been revoked by HR.\n\nReason: %s') % (rec.employee_id.sudo().name, rec.name, self.rejection_reason)
        else:
            return {'type': 'ir.actions.act_window_close'}

        # Notify the employee
        emp_user = rec.employee_id.sudo().user_id
        if emp_user and emp_user.active:
            rec.message_notify(
                partner_ids=emp_user.partner_id.ids,
                subject=subject,
                body=body,
            )

        return {'type': 'ir.actions.act_window_close'}
