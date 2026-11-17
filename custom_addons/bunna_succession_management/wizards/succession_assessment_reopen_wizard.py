# -*- coding: utf-8 -*-
from odoo import fields, models, _


class SuccessionAssessmentReopenWizard(models.TransientModel):
    """Reopen a finalized assessment (SPMC only). A reason is mandatory and audited."""
    _name = 'succession.assessment.reopen.wizard'
    _description = 'Reopen Candidate Assessment'

    candidate_id = fields.Many2one('succession.candidate', required=True, readonly=True, index=True)
    reason = fields.Text(string='Reason', required=True)

    def action_confirm(self):
        self.ensure_one()
        cand = self.candidate_id
        cand._reopen_assessment(self.reason)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Assessment Reopened'),
                'message': _('Assessment for %s has been successfully reopened for revision.') % (cand.employee_id.name or cand.display_name),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
