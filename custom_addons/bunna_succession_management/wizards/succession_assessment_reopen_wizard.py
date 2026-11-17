# -*- coding: utf-8 -*-
from odoo import fields, models


class SuccessionAssessmentReopenWizard(models.TransientModel):
    """Reopen a finalized assessment (SPMC only). A reason is mandatory and audited."""
    _name = 'succession.assessment.reopen.wizard'
    _description = 'Reopen Candidate Assessment'

    candidate_id = fields.Many2one('succession.candidate', required=True, readonly=True)
    reason = fields.Text(string='Reason', required=True)

    def action_confirm(self):
        self.ensure_one()
        self.candidate_id._reopen_assessment(self.reason)
        return {'type': 'ir.actions.act_window_close'}
