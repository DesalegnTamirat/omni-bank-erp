# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class EdsPrerequisiteWarningWizard(models.TransientModel):
    _name = 'eds.prerequisite.warning.wizard'
    _description = 'Missing Course Prerequisites Warning'

    enrollment_ids = fields.Many2many('eds.enrollment', readonly=True)
    warning_text = fields.Text(string='Employees and Missing Prerequisites', readonly=True)

    def action_send_anyway(self):
        self.ensure_one()
        if not self.env.user.has_group('employee_development_system.group_eds_officer'):
            raise UserError(_('Only L&D staff may send training invitations.'))
        invitations = self.enrollment_ids.filtered(
            lambda row: row.selected and row.state == 'suggested')
        if invitations.mapped('session_id').filtered(
            lambda session: session.status not in ('scheduled', 'rescheduled')
        ):
            raise UserError(_('A session is no longer scheduled. Review the roster and try again.'))
        invitations.action_invite()
        sessions = invitations.mapped('session_id')
        if len(sessions) == 1:
            return {
                'type': 'ir.actions.client', 'tag': 'bunna_refresh_form',
                'params': {'res_model': 'eds.session', 'res_id': sessions.id},
            }
        return {'type': 'ir.actions.client', 'tag': 'reload'}
