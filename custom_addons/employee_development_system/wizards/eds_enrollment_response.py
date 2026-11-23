# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..models.eds_action_notification import clear_action_activities, notify_action


class EdsEnrollmentResponseWizard(models.TransientModel):
    _name = 'eds.enrollment.response.wizard'
    _description = 'Training Invitation Response'

    enrollment_id = fields.Many2one('eds.enrollment', required=True, readonly=True)
    employee_name = fields.Char(related='enrollment_id.employee_id.name', string='Employee', readonly=True)
    is_manager_response = fields.Boolean(compute='_compute_is_manager_response')
    response = fields.Selection([
        ('accept', 'Accept invitation'),
        ('decline', 'Reject invitation'),
    ], required=True, default='accept')
    reason = fields.Text(string='Rejection Reason')
    commitment_required = fields.Boolean(
        related='enrollment_id.session_id.commitment_required', readonly=True)
    commitment_years = fields.Integer(
        related='enrollment_id.session_id.commitment_years', readonly=True)
    commitment_terms = fields.Text(
        related='enrollment_id.session_id.commitment_terms', readonly=True)
    accept_commitment = fields.Boolean(string='I accept this training commitment')
    invitation_revision = fields.Integer(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        for vals in vals_list:
            enrollment_id = vals.get('enrollment_id') or self.env.context.get(
                'default_enrollment_id')
            if enrollment_id:
                vals['invitation_revision'] = self.env[
                    'eds.enrollment'].browse(enrollment_id).invitation_revision
        return super().create(vals_list)

    def write(self, vals):
        if 'invitation_revision' in vals:
            raise UserError(_('Open a new invitation response instead of changing its revision.'))
        return super().write(vals)

    def action_submit(self):
        self.ensure_one()
        enrollment = self.enrollment_id
        if self.invitation_revision != enrollment.invitation_revision:
            raise UserError(_(
                'This invitation was replaced by a rescheduled invitation. '
                'Open the latest invitation and respond again.'))
        if enrollment.session_id.status == 'rescheduled':
            raise UserError(_(
                'The session is being rescheduled. Wait for the confirmed new invitation.'))
        if enrollment._expire_overdue() or enrollment._was_auto_rejected():
            return enrollment._expired_response_notice()
        if enrollment.state != 'invited':
            raise UserError(_('This invitation has already been answered.'))

        employee = enrollment.employee_id.sudo()
        user = self.env.user
        if not employee.user_id or employee.user_id.id != user.id:
            raise UserError(_(
                'No one can accept or reject an invitation on behalf of someone else. '
                'Only the invited employee (%s) can respond to this invitation.') % employee.name)

        if self.response not in ('accept', 'decline'):
            raise UserError(_('Choose Accept or Reject for this invitation.'))
        if self.response == 'decline' and not (self.reason or '').strip():
            raise UserError(_('Give a reason for rejecting the invitation.'))
        if self.response == 'accept' and enrollment.session_id.commitment_required \
                and not self.accept_commitment:
            raise UserError(_('Read and accept the training commitment before accepting this invitation.'))

        now = fields.Datetime.now()
        enrollment = enrollment.sudo()
        note = self.reason or ''

        if self.response == 'accept':
            enrolled = enrollment.session_id.enrollment_ids.filtered(lambda row: row.state == 'enrolled')
            available = len(enrolled) < enrollment.session_id.capacity
            vals = {
                'state': 'enrolled' if available else 'waitlisted',
                'response_date': now,
                'response_note': note,
                'reschedule_reconfirmation_required': False,
            }
            if enrollment.session_id.commitment_required:
                vals.update({
                    'commitment_years_at_accept': enrollment.session_id.commitment_years,
                    'commitment_terms_at_accept': enrollment.session_id.commitment_terms,
                    'commitment_accepted_at': now,
                    'commitment_accepted_by_id': user.id,
                })
            if available:
                vals['enrolled_date'] = fields.Date.context_today(enrollment)
            else:
                vals['waitlist_position'] = max(enrollment.session_id.enrollment_ids.mapped('waitlist_position') or [0]) + 1
            enrollment.with_context(
                eds_commitment_acceptance=True,
                eds_reschedule_acceptance=True).write(vals)
            if enrollment.nomination_id:
                enrollment.nomination_id.sudo().write({
                    'employee_confirmed': 'confirmed', 'confirmation_date': now,
                })
        elif self.response == 'decline':
            enrollment.write({
                'state': 'declined', 'selected': False,
                'response_date': now, 'response_note': note,
                'reschedule_reconfirmation_required': False,
                'manager_replacement_decision': 'pending',
            })
            if enrollment.nomination_id:
                enrollment.nomination_id.sudo().write({
                    'state': 'declined', 'employee_confirmed': 'declined',
                    'confirmation_date': now, 'decline_reason': self.reason,
                })

        enrollment.session_id.sudo().message_post(body=_('%s invitation response: %s. %s') % (
            employee.name, self.response, note))
        enrollment.message_post(body=_('Invitation response recorded: %s by %s. %s') % (
            self.response, employee.name, note))

        enrollment._notify_response_supervisors(self.response == 'accept')

        if self.response == 'decline':
            self.env['eds.enrollment'].sudo()._promote_waitlisted(enrollment.session_id)

        clear_action_activities(enrollment.sudo())
        return {'type': 'ir.actions.act_window_close'}
