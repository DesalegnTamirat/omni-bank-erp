# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError, AccessError

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

        is_hr_manager = self.env.user.has_group('hr_resignation.group_resignation_hr_manager')
        acting_hr_del = False
        if not is_hr_manager and self.reject_by in ('return', 'revoke'):
            acting_hr_del = rec._get_acting_hr_delegation(self.env.user)
            if not acting_hr_del and not self.env.user.has_group('base.group_system'):
                raise AccessError(_("Only HR Managers or their authorized acting delegates can return or revoke resignations."))

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

        if acting_hr_del:
            rec.message_post(
                body=_(
                    "<p><strong>Resignation %(action)s via HR Delegation</strong><br/>"
                    "Action performed by acting delegate <strong>%(delegate)s</strong> on behalf of HR Manager <strong>%(manager)s</strong> "
                    "under Delegation Reference <strong>%(ref)s</strong>.<br/>"
                    "Reason: %(reason)s</p>"
                ) % {
                    'action': 'Returned' if self.reject_by == 'return' else 'Revoked',
                    'delegate': self.env.user.name,
                    'manager': acting_hr_del.employee_id.name,
                    'ref': acting_hr_del.name or str(acting_hr_del.id),
                    'reason': self.rejection_reason,
                }
            )

        # Notify the employee
        emp_user = rec.employee_id.sudo().user_id
        if emp_user and emp_user.active:
            rec.message_notify(
                partner_ids=emp_user.partner_id.ids,
                subject=subject,
                body=body,
            )

        return {'type': 'ir.actions.act_window_close'}
