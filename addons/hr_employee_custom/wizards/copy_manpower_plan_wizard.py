from odoo import models, fields, api, _
from odoo.exceptions import UserError


class CopyManpowerPlanWizard(models.TransientModel):
    _name = 'copy.manpower.plan.wizard'
    _description = 'Copy Manpower Plan Wizard'

    def action_copy_current_plan(self):
        # Add your copy logic here
        return {'type': 'ir.actions.act_window_close'}