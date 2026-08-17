# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EdsTnaUnlockWizard(models.TransientModel):
    _name = 'eds.tna.unlock.wizard'
    _description = 'TNA Cycle Unlock Wizard'

    cycle_id = fields.Many2one('eds.tna.cycle', string='TNA Cycle', required=True)
    change_justification = fields.Text(string='Change Justification & Mandate', required=True)

    def action_confirm_unlock(self):
        self.ensure_one()
        if not (self.env.su or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('Only EDS Administrators can unlock a locked TNA cycle.'))
        
        cycle = self.cycle_id
        cycle.write({
            'state': 'approved',
        })
        
        self.env['eds.tna.unlock.history'].create({
            'cycle_id': cycle.id,
            'unlocked_by_id': self.env.user.id,
            'unlock_date': fields.Datetime.now(),
            'justification': self.change_justification,
        })
        
        cycle.message_post(
            body=_('TNA Cycle %s unlocked by %s. Reason: %s') % (
                cycle.name, self.env.user.name, self.change_justification
            )
        )
        return {'type': 'ir.actions.act_window_close'}
