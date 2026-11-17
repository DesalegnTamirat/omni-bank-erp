# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SuccessionCandidateAssessmentWizard(models.TransientModel):
    """
    Dynamic Assessment Entry Wizard for Succession Candidates.
    Records scores for Succession Competency Assessment evaluators (Manager, Self, SPMC)
    and any dynamic assessment tests (Written Exam, Interview, PMS, Case Study, etc.).
    """
    _name = 'succession.candidate.assessment.wizard'
    _description = 'Record Candidate Assessment Scores'

    candidate_id = fields.Many2one('succession.candidate', string='Succession Candidate', required=True, readonly=True, index=True)
    employee_id = fields.Many2one(related='candidate_id.employee_id', string='Candidate (Employee)', readonly=True, index=True)
    critical_position_id = fields.Many2one(
        related='candidate_id.critical_position_id', string='Target Critical Position', readonly=True, index=True)

    assessment_scope = fields.Selection(
        related='candidate_id.assessment_scope',
        string='Configured Evaluation Scope',
        readonly=True)

    # =========================================================================
    # 1. Succession Competency Assessment (Multi-Rater)
    # =========================================================================
    has_competency_eval = fields.Boolean(string='Manager Evaluation Active', default=True)
    competency_score = fields.Float(string='Manager Rating Score (%)', readonly=True)
    competency_eval_status = fields.Char(string='Manager Evaluation Status', readonly=True)



    # SPMC Committee Evaluation (Read-only summary of committee ratings)
    has_spmc_eval = fields.Boolean(string='SPMC Evaluation Active', default=False)
    spmc_score = fields.Float(string='SPMC Committee Score (%)', readonly=True)
    spmc_recommendation = fields.Selection([
        ('strongly_recommend', 'Strongly Recommend'),
        ('recommend', 'Recommend'),
        ('develop', 'Recommend with Development'),
        ('not_recommend', 'Not Recommended at this Time'),
    ], string='SPMC Recommendation', readonly=True)

    # Composite Succession Competency Score
    avg_competency_score = fields.Float(
        string='Competency Assessment Score (%)', readonly=True)

    # =========================================================================
    # 2. Dynamic Assessment Components Lines (Written Exam, Interview, PMS, etc.)
    # =========================================================================
    line_ids = fields.One2many(
        'succession.candidate.assessment.wizard.line', 'wizard_id',
        string='Assessment Components')

    # Qualitative Feedback
    evaluator_remarks = fields.Text(
        string='Evaluator Observations / Assessment Notes',
        help='Detailed evaluation observations, panel feedback, or governance notes.')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        cand_id = self.env.context.get('default_candidate_id') or self.env.context.get('active_id')
        if cand_id:
            cand = self.env['succession.candidate'].browse(cand_id)
            if not cand.assessment_criteria_synced:
                raise UserError(_(
                    "Assessment Plan has not been synchronized with this employee. "
                    "Please synchronize the Assessment Plan from the Critical Position before recording scores."
                ))
            cand._ensure_assessment_results()
            cand._compute_pms_score()
            res['candidate_id'] = cand.id
            res['evaluator_remarks'] = cand.ppdd_notes or ''

            # Active evaluators from candidate's plan
            res['has_competency_eval'] = bool(cand.plan_include_manager)
            res['has_spmc_eval'] = bool(cand.plan_include_spmc)

            # Manager Competency Rating
            res['competency_score'] = cand.competency_eval_score or 0.0
            scored_cnt = len(cand.eval_line_ids.filtered(lambda l: l.score))
            total_cnt = len(cand.eval_line_ids)
            if total_cnt and scored_cnt == total_cnt:
                res['competency_eval_status'] = f"Complete: All {total_cnt} role competencies rated ({cand.competency_eval_score:.1f}%)"
            elif total_cnt:
                res['competency_eval_status'] = f"In Progress: {scored_cnt} of {total_cnt} role competencies rated ({cand.competency_eval_score:.1f}%)"
            else:
                res['competency_eval_status'] = "No competencies loaded for role"

            # SPMC summaries
            res['spmc_score'] = cand.spmc_score or 0.0
            res['spmc_recommendation'] = cand.spmc_recommendation or False
            res['avg_competency_score'] = cand.succession_competency_score or 0.0

            cand.invalidate_recordset(['assessment_result_ids'])
            source_map = dict(self.env['succession.assessment.component']._fields.get('evaluation_type', self.env['succession.assessment.component']._fields['source']).selection or [])
            lines_data = []
            for r in cand.assessment_result_ids:
                if r.waived:
                    score_val = 0.0
                elif r.component_id.source == 'pms':
                    score_val = cand.latest_pms_score
                elif r.component_id.source == 'competency_eval':
                    score_val = cand.succession_competency_score
                else:
                    score_val = r.score or 0.0
                lines_data.append((0, 0, {
                    'result_id': r.id,
                    'component_id': r.component_id.id,
                    'component_name': r.component_id.name,
                    'component_source': r.component_id.source,
                    'source_display': source_map.get(getattr(r.component_id, 'evaluation_type', r.component_id.source), r.component_id.name),
                    'weight': r.weight or r.component_id.weight or 0.0,
                    'max_score': r.max_score or r.component_id.max_score or 100.0,
                    'score': score_val,
                    'pms_score': cand.latest_pms_score if r.component_id.source == 'pms' else 0.0,
                    'waived': r.waived,
                    'applicability_status': 'not_applicable' if r.waived else 'applicable',
                    'waiver_reason': r.waiver_reason or '',
                }))
            res['line_ids'] = lines_data
        return res

    def action_open_competency_eval(self):
        """Open the interactive competency evaluation modal."""
        self.ensure_one()
        return self.candidate_id.action_start_competency_evaluation()

    def action_save(self):
        """Save entered scores and update candidate calculation."""
        self.ensure_one()
        cand = self.candidate_id
        if cand.assessment_done:
            raise UserError(_('Assessment results are locked because this candidate is already assessed.'))
        if not cand.assessment_criteria_synced:
            raise UserError(_(
                "Assessment Plan has not been synchronized with this employee. "
                "Please synchronize the Assessment Plan from the Critical Position before saving scores."
            ))

        cand._ensure_assessment_results()
        cand.invalidate_recordset(['assessment_result_ids'])

        # Update Dynamic Component Lines (Exam, Interview, etc.)
        for line in self.line_ids:
            if line.result_id:
                vals = {}
                if line.waived:
                    vals['score'] = 0.0
                    vals['score_entered'] = False
                elif line.component_source == 'manual':
                    max_s = line.max_score or 100.0
                    if line.score < 0.0 or line.score > max_s:
                        raise ValidationError(_(
                            'Score for "%(name)s" must be between 0 and %(max)s.'
                        ) % {'name': line.component_name, 'max': max_s})
                    score_entered = bool(line.score > 0.0 or line.result_id.score_entered)
                    vals.update({
                        'score': line.score,
                        'score_entered': score_entered,
                    })
                    if score_entered:
                        vals.update({
                            'entered_by_id': self.env.user.id,
                            'entered_date': fields.Datetime.now(),
                        })
                if vals:
                    line.result_id.write(vals)

                # Sync candidate plan booleans
                if line.component_source == 'pms':
                    cand.write({
                        'plan_include_pms': not line.waived,
                        'pms_exemption_reason': line.waiver_reason if line.waived else False,
                    })
                elif 'exam' in (line.component_name or '').lower():
                    cand.write({
                        'plan_include_exam': not line.waived,
                        'exam_exemption_reason': line.waiver_reason if line.waived else False,
                    })

        if self.evaluator_remarks:
            cand.write({'ppdd_notes': self.evaluator_remarks})

        # Recompute candidate scores
        cand._compute_succession_competency_score()
        cand._refresh_assessment_scores()
        return {
            'type': 'ir.actions.client',
            'tag': 'bunna_close_eval_modals',
            'params': {
                'notification': {
                    'title': _('Assessment Scores Saved'),
                    'message': _('Assessment scores and remarks successfully saved for %s.') % (cand.employee_id.name or cand.display_name),
                    'type': 'success',
                    'sticky': False,
                },
            },
        }

    action_apply_scores = action_save


class SuccessionCandidateAssessmentWizardLine(models.TransientModel):
    _name = 'succession.candidate.assessment.wizard.line'
    _description = 'Assessment Wizard Component Score Line'

    wizard_id = fields.Many2one('succession.candidate.assessment.wizard', required=True, ondelete='cascade', index=True)
    result_id = fields.Many2one('succession.candidate.assessment.result', string='Candidate Result', index=True)
    component_id = fields.Many2one('succession.assessment.component', string='Component', index=True)
    component_name = fields.Char(
        string='Assessment Component',
        compute='_compute_component_info', store=True, readonly=True)
    component_source = fields.Selection([
        ('manual', 'Assessment Test / Examination'),
        ('pms', 'Annual PMS Appraisal'),
        ('competency_eval', 'Role Competencies Assessment (Multi-Rater)'),
    ], string='Source', compute='_compute_component_info', store=True, readonly=True)
    source_display = fields.Char(
        string='Evaluation Method',
        compute='_compute_component_info', store=True, readonly=True)
    weight = fields.Float(string='Weight (%)', readonly=True)
    max_score = fields.Float(string='Max Score', readonly=True)
    score = fields.Float(string='Score (0–100)')
    pms_score = fields.Float(string='Audited PMS Score (0–100)', readonly=True)
    waived = fields.Boolean(string='Not Applicable (N/A)', readonly=True)
    applicability_status = fields.Selection([
        ('applicable', 'Applicable'),
        ('not_applicable', 'Not Applicable (N/A)'),
    ], string='Plan Status', compute='_compute_applicability_status', store=True)
    waiver_reason = fields.Char(string='Plan Justification / Exemption Reason', readonly=True)

    @api.depends('waived')
    def _compute_applicability_status(self):
        for line in self:
            line.applicability_status = 'not_applicable' if line.waived else 'applicable'

    @api.depends('component_id', 'result_id', 'result_id.component_id')
    def _compute_component_info(self):
        source_labels = {
            'manual': 'Assessment Test / Examination',
            'pms': 'Annual PMS Appraisal',
            'competency_eval': 'Role Competencies Assessment (Multi-Rater)',
        }
        for line in self:
            comp = line.component_id or (line.result_id.component_id if line.result_id else False)
            if comp:
                line.component_name = comp.name
                line.component_source = comp.source
                line.source_display = source_labels.get(comp.source, 'Manual Entry')
            else:
                line.component_name = line.component_name or ''
                line.component_source = line.component_source or 'manual'
                line.source_display = line.source_display or 'Manual Entry'

    @api.onchange('waived')
    def _onchange_waived(self):
        for line in self:
            if line.waived:
                line.score = 0.0
