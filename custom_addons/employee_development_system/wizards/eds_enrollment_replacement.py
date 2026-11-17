# -*- coding: utf-8 -*-
"""A boss or coach decides whether a rejected invitation needs a replacement."""

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..models.eds_action_notification import (
    clear_action_activities, notify_action, role_users,
)
from ..models.eds_employee_projection import safe_employee_web_read


class EdsEnrollmentReplacementWizard(models.TransientModel):
    _name = 'eds.enrollment.replacement.wizard'
    _description = 'Manager Training Replacement Decision'

    def web_read(self, specification):
        return safe_employee_web_read(
            self, specification, super().web_read,
            ('replacement_employee_id',))

    enrollment_id = fields.Many2one('eds.enrollment', required=True, readonly=True)
    decision = fields.Selection([
        ('replace', 'Choose a replacement'),
        ('none', 'No replacement'),
    ], required=True, default='replace')
    replacement_employee_id = fields.Many2one(
        'hr.employee', string='Replacement Employee')
    allowed_replacement_employee_ids = fields.Many2many(
        'hr.employee', compute='_compute_allowed_replacement_employee_ids')
    decision_note = fields.Text(string='Manager Note')

    @api.depends('enrollment_id')
    @api.depends_context('uid')
    def _compute_allowed_replacement_employee_ids(self):
        Employee = self.env['hr.employee'].sudo()
        for wizard in self:
            source = wizard.enrollment_id
            if source:
                source.check_access('read')
            enrollment = source.sudo()
            if not enrollment:
                wizard.allowed_replacement_employee_ids = Employee.browse()
                continue
            already_selected = enrollment.session_id.enrollment_ids.mapped('employee_id').ids
            original_boss = enrollment.employee_id.sudo().parent_id.user_id
            team_field = ('parent_id.user_id' if original_boss
                          else 'coach_id.user_id')
            wizard.allowed_replacement_employee_ids = Employee.search([
                (team_field, '=', self.env.uid),
                ('company_id', '=', enrollment.session_id.company_id.id),
                ('active', '=', True),
                ('id', 'not in', already_selected),
            ])

    def _check_manager(self, enrollment):
        enrollment.check_access('read')
        employee = enrollment.employee_id.sudo()
        decision_user = employee.parent_id.user_id or employee.coach_id.user_id
        if self.env.uid != decision_user.id:
            raise UserError(_(
                'Only this employee’s boss can decide on a replacement '
                '(or the coach when no boss account exists).'))

    def _validate_replacement(self, enrollment):
        replacement = self.replacement_employee_id.sudo()
        original = enrollment.employee_id.sudo()
        session = enrollment.session_id.sudo()
        if not replacement or not replacement.active or replacement == original:
            raise UserError(_('Choose a different active employee from your team.'))
        if replacement.company_id != session.company_id:
            raise UserError(_('The replacement must belong to the session company.'))
        team_user = (replacement.parent_id.user_id
                     if original.parent_id.user_id
                     else replacement.coach_id.user_id)
        if self.env.uid != team_user.id:
            raise UserError(_('The replacement must belong to your own team.'))
        user = replacement.user_id
        if not user or not user.active or user.share or not user.partner_id:
            raise UserError(_(
                'The replacement needs an active internal user account to receive an invitation.'))
        if self.env['eds.enrollment'].sudo().search_count([
                ('session_id', '=', session.id),
                ('employee_id', '=', replacement.id)]):
            raise UserError(_(
                'This employee is already selected for the session, including a past invitation.'))
        if self.env['eds.nomination'].sudo().search_count([
                ('session_id', '=', session.id),
                ('employee_id', '=', replacement.id),
                ('state', 'not in', ('cancelled', 'rejected', 'withdrawn', 'declined'))]):
            raise UserError(_('This employee already has a nomination for the session.'))
        return replacement

    def action_submit(self):
        self.ensure_one()
        enrollment = self.enrollment_id
        self._check_manager(enrollment)
        # Prevent two managers from replacing the same rejected seat at once.
        self.env.cr.execute(
            'SELECT id FROM eds_enrollment WHERE id = %s FOR UPDATE', (enrollment.id,))
        enrollment.invalidate_recordset()
        if (enrollment.state != 'declined'
                or enrollment.manager_replacement_decision not in (False, 'pending')):
            raise UserError(_('This rejected invitation already has a manager decision.'))
        if self.decision not in ('replace', 'none'):
            raise UserError(_('Choose a replacement or No replacement.'))
        if self.decision == 'none' and self.replacement_employee_id:
            raise UserError(_('Clear the replacement employee when choosing No replacement.'))
        if self.decision == 'none' and not (self.decision_note or '').strip():
            raise UserError(_('Explain why no replacement is needed.'))

        now = fields.Datetime.now()
        session = enrollment.session_id.sudo()
        if self.decision == 'replace':
            replacement = self._validate_replacement(enrollment)
            new_enrollment = self.env['eds.enrollment'].sudo().with_context(
                eds_manual_roster=True).create({
                    'session_id': session.id,
                    'employee_id': replacement.id,
                    'state': 'suggested',
                    'selected': True,
                    'replaces_enrollment_id': enrollment.id,
                    'source_summary': _('Manager replacement for %s') % (
                        enrollment.employee_id.sudo().name),
                })
            enrollment.sudo().write({
                'state': 'replaced', 'selected': False,
                'replacement_employee_id': replacement.id,
                'manager_replacement_decision': 'replace',
                'manager_replacement_decided_by_id': self.env.uid,
                'manager_replacement_decided_at': now,
                'manager_replacement_note': (self.decision_note or '').strip(),
            })
            notify_action(
                new_enrollment.sudo(), role_users(session, 'group_eds_officer'),
                _('Invite manager-selected replacement'),
                _('%s replaced %s on session %s. Course: %s. '
                  'Review this suggested participant and send the invitation.') % (
                      replacement.name, enrollment.employee_id.sudo().name,
                      session.name, session.course_id.name or session.program_name or ''),
                map_url=session.google_maps_url)
        else:
            enrollment.sudo().write({
                'manager_replacement_decision': 'none',
                'manager_replacement_decided_by_id': self.env.uid,
                'manager_replacement_decided_at': now,
                'manager_replacement_note': self.decision_note.strip(),
            })
            notify_action(
                enrollment.sudo(), role_users(session, 'group_eds_officer'),
                _('No replacement for rejected invitation'),
                _('%s decided not to replace %s for session %s.') % (
                    self.env.user.name, enrollment.employee_id.sudo().name,
                    session.name),
                action_required=False, map_url=session.google_maps_url)
        clear_action_activities(enrollment.sudo())
        return {'type': 'ir.actions.act_window_close'}
