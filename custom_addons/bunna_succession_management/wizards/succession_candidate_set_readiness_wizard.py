# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError, ValidationError


class SuccessionCandidateSetReadinessWizard(models.TransientModel):
    _name = 'succession.candidate.set.readiness.wizard'
    _description = 'PPDD Set Candidate Readiness Level & Complete Assessment'

    candidate_id = fields.Many2one('succession.candidate', string='Candidate', required=True, readonly=True, index=True)
    employee_id = fields.Many2one(related='candidate_id.employee_id', string='Employee', readonly=True, index=True)
    critical_position_id = fields.Many2one(
        related='candidate_id.critical_position_id', string='Critical Position', readonly=True, index=True)
    
    # Diagnostic Assessment Metrics
    final_assessment_score = fields.Float(
        related='candidate_id.final_assessment_score', string='Final Assessment Score (%)', readonly=True)
    assessment_result = fields.Selection(
        related='candidate_id.assessment_result', string='Assessment Result', readonly=True)
    assessment_status = fields.Selection(
        related='candidate_id.assessment_status', string='Assessment Status', readonly=True)
    competency_match_percent = fields.Float(
        related='candidate_id.competency_match_percent', string='Competency Match (%)', readonly=True)
    competency_gap_count = fields.Integer(
        related='candidate_id.competency_gap_count', string='Identified Gaps', readonly=True)
    latest_pms_score = fields.Float(
        related='candidate_id.latest_pms_score', string='PMS Appraisal Score', readonly=True)
    nine_box_label = fields.Char(
        related='candidate_id.nine_box_label', string='9-Box Placement', readonly=True)

    # Official PPDD Decision
    readiness_level_id = fields.Many2one(
        'succession.readiness.level',
        string='Assigned Readiness Level (Official)',
        required=True,
        domain="[('active', '=', True)]",
        index=True,
        help="Official readiness level decided and calibrated by PPDD following assessment review.")
    
    calibration_notes = fields.Text(
        string='Justification / Note')

    def action_confirm_readiness(self):
        self.ensure_one()
        if not self.readiness_level_id:
            raise ValidationError(_('Please select an official Readiness Level before completing the assessment.'))
        
        cand = self.candidate_id

        # Validate that all evaluations and scorecard lines are completed
        cand._validate_assessment_complete()

        is_ready = self.readiness_level_id.is_ready_for_deployment

        # Update candidate with PPDD's chosen readiness level and notes in a single atomic write
        cand_vals = {
            'readiness_level_id': self.readiness_level_id.id,
            'manager_override': True,
            'assessment_done': True,
            'assessment_date': fields.Datetime.now(),
            'assessment_by_id': self.env.user.id,
            'state': 'assessed',
        }
        if self.calibration_notes:
            cand_vals['ppdd_notes'] = self.calibration_notes
        cand.with_context(force_write=True).write(cand_vals)

        # Summary notification text
        if is_ready:
            next_step_msg = '<b>Next Step:</b> Candidate is marked <i>Ready Now (Deployment Ready)</i>. Eligible for SPMC Final Approval to join the active Talent Pool bench.'
        else:
            next_step_msg = '<b>Next Step:</b> Candidate has development needs. Please proceed to <b>Tab 3 (Successor Development Plan)</b> to establish targeted development interventions.'

        cand.message_post(body=_(
            '<b>Assessment Completed &amp; Official Readiness Level Set by PPDD</b><br/>'
            '<ul>'
            '<li><b>Assigned Readiness Level:</b> %(level)s</li>'
            '<li><b>Assessment Score:</b> %(score).2f%%</li>'
            '<li><b>Competency Match:</b> %(match).1f%% (%(gaps)d gaps)</li>'
            '<li><b>PPDD Officer:</b> %(user)s</li>'
            '%(notes)s'
            '</ul>'
            '<p class="mt-2 text-primary">%(next_step)s</p>'
        ) % {
            'level': self.readiness_level_id.name,
            'score': cand.final_assessment_score,
            'match': cand.competency_match_percent,
            'gaps': cand.competency_gap_count,
            'user': self.env.user.name,
            'notes': ('<li><b>Justification / Note:</b> %s</li>' % self.calibration_notes) if self.calibration_notes else '',
            'next_step': next_step_msg,
        })

        cand._log_candidate_event(
            'candidate_assessed',
            'PPDD assigned readiness level %s to candidate %s' % (self.readiness_level_id.name, cand.employee_id.name)
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Readiness Level Assigned & Assessment Finalized'),
                'message': _('Candidate %s is now Assessed as "%s". %s') % (
                    cand.employee_id.name,
                    self.readiness_level_id.name,
                    'Eligible for SPMC Approval.' if is_ready else 'Proceed to Successor Development Plan.'
                ),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'}
            }
        }
