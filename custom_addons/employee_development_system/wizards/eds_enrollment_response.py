# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError

from ..models.eds_action_notification import clear_action_activities, notify_action


class EdsEnrollmentResponseWizard(models.TransientModel):
    _name = 'eds.enrollment.response.wizard'
    _description = 'Training Invitation Response'

    enrollment_id = fields.Many2one('eds.enrollment', required=True, readonly=True)
    response = fields.Selection([
        ('accept', 'Accept invitation'),
        ('decline', 'Reject invitation'),
        ('replace', 'Suggest a replacement'),
    ], required=True, default='accept')
    reason = fields.Text(string='Reason / Justification')
    replacement_employee_id = fields.Many2one('hr.employee', string='Replacement Employee')

    def action_submit(self):
        self.ensure_one()
        enrollment = self.enrollment_id
        if enrollment._expire_overdue() or enrollment._was_auto_rejected():
            return enrollment._expired_response_notice()
        if enrollment.state != 'invited':
            raise UserError(_('This invitation has already been answered.'))
        employee = enrollment.employee_id
        user = self.env.user
        if employee.user_id != user:
            raise UserError(_('Only the invited employee can respond to this invitation.'))
        if self.response in ('decline', 'replace') and not (self.reason or '').strip():
            raise UserError(_('Give a reason for rejecting or replacing the invitation.'))

        now = fields.Datetime.now()
        Enrollment = self.env['eds.enrollment'].sudo()
        enrollment = enrollment.sudo()
        if self.response == 'accept':
            enrolled = enrollment.session_id.enrollment_ids.filtered(lambda row: row.state == 'enrolled')
            available = len(enrolled) < enrollment.session_id.capacity
            vals = {
                'state': 'enrolled' if available else 'waitlisted',
                'response_date': now,
                'response_note': self.reason,
            }
            if available:
                vals['enrolled_date'] = fields.Date.context_today(enrollment)
            else:
                vals['waitlist_position'] = max(enrollment.session_id.enrollment_ids.mapped('waitlist_position') or [0]) + 1
            enrollment.write(vals)
        elif self.response == 'decline':
            enrollment.write({
                'state': 'declined', 'selected': False,
                'response_date': now, 'response_note': self.reason,
            })
        elif self.response == 'replace':
            replacement = self.replacement_employee_id
            if not replacement or not replacement.active or replacement == employee:
                raise UserError(_('Select a different active employee as the replacement.'))
            if replacement.company_id != enrollment.session_id.company_id:
                raise UserError(_('The suggested employee must belong to the session company.'))
            if Enrollment.search_count([
                ('session_id', '=', enrollment.session_id.id),
                ('employee_id', '=', replacement.id),
                ('state', 'not in', ('cancelled', 'declined', 'replaced')),
            ]):
                raise UserError(_('The suggested employee is already on this session roster.'))
            enrollment.write({
                'state': 'replaced', 'selected': False,
                'replacement_employee_id': replacement.id,
                'response_date': now, 'response_note': self.reason,
            })

        enrollment.session_id.sudo().message_post(body=_('%s invitation response: %s. %s') % (
            employee.name, self.response, self.reason or ''))
        if self.response in ('decline', 'replace'):
            session = enrollment.session_id
            officer_group = self.env.ref('employee_development_system.group_eds_officer')
            officers = officer_group.sudo().user_ids.filtered(
                lambda officer: officer.active and not officer.share
                and session.company_id in officer.company_ids)
            if self.response == 'replace':
                title = _('Review suggested training replacement')
                message = _('%s suggested %s as a replacement for %s: %s. Review the roster and decide whether to invite them.') % (
                    employee.name, enrollment.replacement_employee_id.name, session.name, self.reason)
            else:
                title = _('Replace declined training seat')
                message = _('%s rejected the invitation to %s: %s. Review the roster and invite a replacement.') % (
                    employee.name, session.name, self.reason)
            notify_action(session.sudo(), officers, title, message)
            if self.response == 'decline':
                Enrollment._promote_waitlisted(session)
        clear_action_activities(enrollment.sudo())
        return {'type': 'ir.actions.act_window_close'}
