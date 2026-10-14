# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class EdsPlanReturnWizard(models.TransientModel):
    """Wizard for returning an Annual L&D Plan with mandatory justification / remarks."""
    _name = 'eds.plan.return.wizard'
    _description = 'Annual L&D Plan Return Wizard'

    plan_id = fields.Many2one('eds.annual.plan', string='Annual Plan', required=True)
    target_state = fields.Selection([
        ('draft', 'Draft (Return to Creator)'),
        ('team_leader_review', 'Team Leader Review (Checker)'),
        ('director_review', 'Director Review'),
    ], string='Return Destination Stage', required=True, default='draft')
    stage_name = fields.Char(string='Action Description', readonly=True)
    reason = fields.Text(
        string='Return Justification / Remarks',
        required=True,
    )

    def action_confirm_return(self):
        self.ensure_one()
        if not self.reason or not self.reason.strip():
            raise UserError(_("Please provide a justification / reason for returning the plan."))
        return self.plan_id.action_return_plan_from_wizard(self.target_state, self.reason.strip())
