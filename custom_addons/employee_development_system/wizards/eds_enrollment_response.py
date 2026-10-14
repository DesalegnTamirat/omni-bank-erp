# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class EdsEnrollmentResponseWizard(models.TransientModel):
    _name = 'eds.enrollment.response.wizard'
    _description = 'Training Invitation Response'

    enrollment_id = fields.Many2one('eds.enrollment', required=True, readonly=True)
    response = fields.Selection([
        ('accept', 'Accept invitation'),
        ('decline', 'Decline invitation'),
        ('replace', 'Replace with another employee'),
    ], required=True, default='accept')
    reason = fields.Text(string='Reason / Justification')
    replacement_employee_id = fields.Many2one('hr.employee', string='Replacement Employee')

    def action_submit(self):
        self.ensure_one()
        enrollment = self.enrollment_id
        if enrollment.state != 'invited':
            raise UserError(_('This invitation has already been answered.'))
        employee = enrollment.employee_id
        user = self.env.user
        is_employee = employee.user_id == user
        is_manager = user in (employee.parent_id.user_id, employee.coach_id.user_id)
        is_hr_manager = user.has_group('employee_development_system.group_eds_manager') or user.has_group(
            'employee_development_system.group_eds_admin')

        if self.response in ('accept', 'decline') and not is_employee:
            raise UserError(_('Only the invited employee can accept or decline.'))
        if self.response == 'replace' and not (is_manager or is_hr_manager):
            raise UserError(_('Only this employee’s manager or coach, or an L&D manager, can replace the invitation.'))
        if self.response in ('decline', 'replace') and not (self.reason or '').strip():
            raise UserError(_('Give a reason for declining or replacing the invitation.'))

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
            if not available:
                vals['waitlist_position'] = max(enrollment.session_id.enrollment_ids.mapped('waitlist_position') or [0]) + 1
            enrollment.write(vals)
        elif self.response == 'decline':
            enrollment.write({
                'state': 'declined', 'selected': False,
                'response_date': now, 'response_note': self.reason,
            })
        else:
            replacement = self.replacement_employee_id
            if not replacement or not replacement.active or replacement == employee:
                raise UserError(_('Select a different active employee as the replacement.'))
            if is_manager and not is_hr_manager and user not in (
                    replacement.parent_id.user_id, replacement.coach_id.user_id):
                raise UserError(_('A manager or coach may replace an employee only with someone on their team.'))
            if Enrollment.search_count([
                ('session_id', '=', enrollment.session_id.id),
                ('employee_id', '=', replacement.id),
                ('state', 'not in', ('cancelled', 'declined', 'replaced')),
            ]):
                raise UserError(_('The replacement employee is already on this session roster.'))
            enrollment.write({
                'state': 'replaced', 'selected': False,
                'replacement_employee_id': replacement.id,
                'response_date': now, 'response_note': self.reason,
            })
            new_invitation = Enrollment.create({
                'session_id': enrollment.session_id.id,
                'employee_id': replacement.id,
                'state': 'suggested', 'selected': True,
                'source_summary': _('Manager / coach replacement'),
                'replaces_enrollment_id': enrollment.id,
            })
            new_invitation.action_invite()

        enrollment.session_id.sudo().message_post(body=_('%s invitation response: %s. %s') % (
            employee.name, self.response, self.reason or ''))
        return {'type': 'ir.actions.act_window_close'}
