# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class HrClearanceRejectWizard(models.TransientModel):
    _name = 'hr.clearance.reject.wizard'
    _description = 'Reject Clearance Line'

    clearance_line_id = fields.Many2one(
        'hr.resignation.clearance', required=True, ondelete='cascade')
    rejection_reason = fields.Text(required=True, string='Reason for Rejection')

    def action_confirm_reject(self):
        self.ensure_one()
        line = self.clearance_line_id
        line._check_clearance_permission()
        if line.state != 'pending':
            raise UserError(_(
                'Only Pending lines can be rejected. Current state: %s')
                % line._get_state_label())
        if not self.rejection_reason or not self.rejection_reason.strip():
            raise UserError(_('Please provide a rejection reason.'))

        line.write({
            'state':             'rejected',
            'rejected_by':       self.env.user.id,
            'rejected_date':     fields.Datetime.now(),
            'rejection_reason':  self.rejection_reason,
            'resolution_notes':  False,
            'resolved_by':       False,
            'resolved_date':     False,
        })
        line._close_clearance_activities(
            feedback=_('Rejected: %s') % self.rejection_reason)

        # Notify the employee, the direct manager, and HR via Discuss
        # popup + notification bell — no chatter clutter.
        resignation = line.resignation_id
        notify_partners = set()

        emp_user = resignation.employee_id.sudo().user_id
        if emp_user and emp_user.active:
            notify_partners.add(emp_user.partner_id.id)

        manager_user = resignation.coach_id.sudo().user_id
        if manager_user and manager_user.active:
            notify_partners.add(manager_user.partner_id.id)

        hr_group = self.env.ref('hr.group_hr_user', raise_if_not_found=False)
        if hr_group:
            for u in hr_group.sudo().all_user_ids.filtered(lambda u: u.active):
                notify_partners.add(u.partner_id.id)

        if notify_partners:
            resignation.message_notify(
                partner_ids=list(notify_partners),
                subject=_('Clearance Rejected: %s — %s') % (
                    resignation.employee_id.sudo().name,
                    line.work_unit_id.name or _('Clearance'),
                ),
                body=_(
                    'Clearance item <strong>%s</strong> has been <strong>REJECTED</strong> '
                    'by %s for %s (%s).<br/>Reason: %s'
                ) % (
                    line.work_unit_id.name or _('Clearance'),
                    self.env.user.name,
                    resignation.employee_id.sudo().name,
                    resignation.name,
                    self.rejection_reason,
                ),
            )

        return {'type': 'ir.actions.act_window_close'}