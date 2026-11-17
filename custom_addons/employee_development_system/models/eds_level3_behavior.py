# -*- coding: utf-8 -*-
"""Session snapshots and coach answers for Level 3 behavior reviews."""

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from .eds_action_notification import clear_action_activities


LEVEL3_ANSWER_TYPES = [
    ('scale_1_5', '5-Point Rating'),
    ('scale_1_10', '10-Point Rating'),
    ('yes_no', 'Yes / No'),
    ('text', 'Open Text'),
]


def _require_assigned_coach(records, evaluations):
    """Enforce the assignee even when another EDS group grants model access."""
    if records.env.su or records.env.user.has_group(
            'employee_development_system.group_eds_officer'):
        return
    if any(review.manager_id.sudo().user_id.id != records.env.uid
           for review in evaluations.sudo()):
        raise AccessError(_('Only the assigned coach may open or edit this review.'))


class EdsSessionLevel3Behavior(models.Model):
    _inherit = 'eds.session'

    level3_behavior_question_ids = fields.One2many(
        'eds.session.level3.behavior.question', 'session_id',
        string='Level 3 Behavior Questions')

    def _ensure_level3_behavior_questions(self):
        """Take the published course template once; later edits are session-local."""
        Question = self.env['eds.session.level3.behavior.question']
        for session in self:
            if session.level3_behavior_question_ids:
                continue
            instrument = session.course_id.level3_instrument_id
            if not instrument or instrument.state != 'published':
                continue
            Question.create([{
                'session_id': session.id,
                'sequence': question.sequence,
                'prompt': question.name,
                'question_type': question.question_type,
                'source_question_id': question.id,
            } for question in instrument.question_ids])

    def action_prepare_level3_behavior_questions(self):
        self._require_ld_delivery_access()
        self.ensure_one()
        self.check_access('write')
        self._ensure_level3_behavior_questions()
        return {
            'type': 'ir.actions.client', 'tag': 'bunna_refresh_form',
            'params': {'res_model': self._name, 'res_id': self.id},
        }

    def _apply_level3_behavior_questions(self):
        Answer = self.env['eds.evaluation.level3.answer']
        for session in self:
            for review in session.level3_review_ids.filtered(
                    lambda row: row.status == 'pending'
                    and not row.notification_sent_at):
                current_question_ids = set(session.level3_behavior_question_ids.ids)
                review.behavior_answer_ids.filtered(
                    lambda answer: not answer.answered
                    and answer.question_id.id not in current_question_ids).unlink()
                existing = {answer.question_id.id: answer
                            for answer in review.behavior_answer_ids
                            if answer.question_id}
                for question in session.level3_behavior_question_ids:
                    answer = existing.get(question.id)
                    if answer:
                        if not answer.answered:
                            answer.write({
                                'question_text': question.prompt,
                                'question_type': question.question_type,
                                'sequence': question.sequence,
                            })
                    else:
                        Answer.create({
                            'evaluation_id': review.id,
                            'question_id': question.id,
                            'question_text': question.prompt,
                            'question_type': question.question_type,
                            'sequence': question.sequence,
                        })

    def action_apply_level3_behavior_questions(self):
        self._require_ld_delivery_access()
        self.ensure_one()
        self.check_access('write')
        self._apply_level3_behavior_questions()
        return {
            'type': 'ir.actions.client', 'tag': 'bunna_refresh_form',
            'params': {'res_model': self._name, 'res_id': self.id},
        }

    def _distribute_completion_evaluations(self):
        self._ensure_level3_behavior_questions()
        return super()._distribute_completion_evaluations()

    def action_send_level3_reviews(self):
        self._require_ld_delivery_access()
        self._apply_level3_behavior_questions()
        return super().action_send_level3_reviews()


class EdsSessionLevel3BehaviorQuestion(models.Model):
    _name = 'eds.session.level3.behavior.question'
    _description = 'Session Level 3 Behavior Question'
    _order = 'sequence, id'

    session_id = fields.Many2one('eds.session', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(
        'res.company', related='session_id.company_id', store=True, readonly=True)
    sequence = fields.Integer(default=10)
    prompt = fields.Char(string='Behavior Question', required=True)
    question_type = fields.Selection(
        LEVEL3_ANSWER_TYPES, string='Answer Format', required=True,
        default='scale_1_5')
    source_question_id = fields.Many2one(
        'eds.evaluation.instrument.question', ondelete='set null', readonly=True)

    _session_source_unique = models.Constraint(
        'UNIQUE(session_id, source_question_id)',
        'This template question has already been loaded for the session.')

    def write(self, vals):
        if not self.env.su and any(
                question.session_id.level3_review_ids.filtered(
                    lambda review: review.notification_sent_at)
                for question in self):
            raise UserError(_(
                'A Level 3 review has already been sent. Its session questions '
                'cannot be changed.'))
        return super().write(vals)

    def unlink(self):
        if any(question.session_id.level3_review_ids.filtered(
                lambda review: review.notification_sent_at) for question in self):
            raise UserError(_(
                'A Level 3 review has already been sent. Its session questions '
                'cannot be removed.'))
        return super().unlink()


class EdsEvaluationLevel3Behavior(models.Model):
    _inherit = 'eds.evaluation.level3'

    behavior_answer_ids = fields.One2many(
        'eds.evaluation.level3.answer', 'evaluation_id',
        string='Configured Behavior Questions')

    def check_access(self, operation):
        result = super().check_access(operation)
        if operation in ('read', 'write', 'unlink'):
            _require_assigned_coach(self, self)
        return result

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('behavior_answer_ids') or not vals.get('session_id'):
                continue
            session = self.env['eds.session'].browse(vals['session_id'])
            vals['behavior_answer_ids'] = [(0, 0, {
                'question_id': question.id,
                'question_text': question.prompt,
                'question_type': question.question_type,
                'sequence': question.sequence,
            }) for question in session.level3_behavior_question_ids]
        return super().create(vals_list)

    @api.depends('line_ids.score_pct', 'behavior_answer_ids.score_pct',
                 'behavior_answer_ids.answered',
                 'behavior_answer_ids.question_type')
    def _compute_behavior_score(self):
        for review in self:
            scores = list(review.line_ids.mapped('score_pct'))
            scores.extend(answer.score_pct
                          for answer in review.behavior_answer_ids
                          if answer.answered and answer.question_type != 'text')
            review.behavior_score = round(sum(scores) / len(scores), 2) if scores else 0.0

    def write(self, vals):
        _require_assigned_coach(self, self)
        if not self.env.su and not self.env.user.has_group(
                'employee_development_system.group_eds_officer'):
            allowed = {
                'observation_notes', 'overall_result', 'business_impact_observed',
                'recommended_support', 'sign_manager_name', 'sign_trainee_name',
                'line_ids', 'behavior_answer_ids',
            }
            if set(vals) - allowed:
                raise AccessError(_(
                    'Only L&D staff may change the assignment or workflow of a '
                    'Level 3 review.'))
            if any(review.status == 'completed' for review in self):
                raise AccessError(_('Completed Level 3 reviews cannot be edited.'))
        return super().write(vals)

    def action_submit_level3(self):
        for review in self:
            review.check_access('write')
            if review.status == 'completed':
                raise UserError(_('This Level 3 review has already been submitted.'))
            if not review.line_ids and not review.behavior_answer_ids:
                raise ValidationError(_(
                    'Add a competency observation or configured behavior question '
                    'before submitting the review.'))
            unrated = review.line_ids.filtered(
                lambda line: not line.frequency_rating and not line.observed_level)
            if unrated:
                raise ValidationError(_(
                    'Rate every mapped competency before submitting the review.'))
            unanswered = review.behavior_answer_ids.filtered(lambda row: not row.answered)
            if unanswered:
                raise ValidationError(_(
                    'Answer all configured behavior questions before submitting.'))
            review.sudo().write({
                'status': 'completed',
                'completed_date': fields.Date.context_today(review),
            })
            clear_action_activities(review)
            review.message_post(body=_(
                'Level 3 behavioral evaluation completed by %s with score %.1f%%.')
                % (review.manager_id.sudo().name, review.behavior_score))


class EdsEvaluationLevel3Answer(models.Model):
    _name = 'eds.evaluation.level3.answer'
    _description = 'Level 3 Configured Behavior Answer'
    _order = 'sequence, id'

    evaluation_id = fields.Many2one(
        'eds.evaluation.level3', required=True, ondelete='cascade', index=True)
    question_id = fields.Many2one(
        'eds.session.level3.behavior.question', ondelete='set null', readonly=True)
    sequence = fields.Integer(default=10)
    question_text = fields.Char(string='Behavior Question', required=True)
    question_type = fields.Selection(
        LEVEL3_ANSWER_TYPES, string='Answer Format', required=True)
    rating_5 = fields.Selection(
        [(str(value), str(value)) for value in range(1, 6)], string='Rating (1–5)')
    rating_10 = fields.Selection(
        [(str(value), str(value)) for value in range(1, 11)], string='Rating (1–10)')
    yes_no = fields.Selection([('yes', 'Yes'), ('no', 'No')], string='Yes / No')
    text_answer = fields.Text(string='Open Response')
    answered = fields.Boolean(compute='_compute_result', store=True)
    score_pct = fields.Float(string='Score (%)', compute='_compute_result', store=True)

    _evaluation_question_unique = models.Constraint(
        'UNIQUE(evaluation_id, question_id)',
        'This Level 3 question already has an answer row for this review.')

    def check_access(self, operation):
        result = super().check_access(operation)
        if operation in ('read', 'write', 'unlink'):
            _require_assigned_coach(self, self.mapped('evaluation_id'))
        return result

    @api.depends('question_type', 'rating_5', 'rating_10', 'yes_no', 'text_answer')
    def _compute_result(self):
        for answer in self:
            answer.answered = False
            answer.score_pct = 0.0
            if answer.question_type == 'scale_1_5' and answer.rating_5:
                answer.answered = True
                answer.score_pct = int(answer.rating_5) * 20.0
            elif answer.question_type == 'scale_1_10' and answer.rating_10:
                answer.answered = True
                answer.score_pct = int(answer.rating_10) * 10.0
            elif answer.question_type == 'yes_no' and answer.yes_no:
                answer.answered = True
                answer.score_pct = 100.0 if answer.yes_no == 'yes' else 0.0
            elif answer.question_type == 'text' and (answer.text_answer or '').strip():
                answer.answered = True

    def write(self, vals):
        _require_assigned_coach(self, self.mapped('evaluation_id'))
        if not self.env.su and not self.env.user.has_group(
                'employee_development_system.group_eds_officer'):
            if set(vals) - {'rating_5', 'rating_10', 'yes_no', 'text_answer'}:
                raise AccessError(_(
                    'Only L&D staff may change Level 3 question wording or assignment.'))
            if any(answer.evaluation_id.status == 'completed' for answer in self):
                raise AccessError(_('Completed Level 3 answers cannot be edited.'))
        return super().write(vals)


class EdsEvaluationLevel3CompetencyGuard(models.Model):
    _inherit = 'eds.evaluation.level3.line'

    def check_access(self, operation):
        result = super().check_access(operation)
        if operation in ('read', 'write', 'unlink'):
            _require_assigned_coach(self, self.mapped('evaluation_id'))
        return result

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.user.has_group(
                'employee_development_system.group_eds_officer'):
            raise AccessError(_('Only L&D staff may add competency observations.'))
        return super().create(vals_list)

    def write(self, vals):
        _require_assigned_coach(self, self.mapped('evaluation_id'))
        if not self.env.su and not self.env.user.has_group(
                'employee_development_system.group_eds_officer'):
            if set(vals) - {'frequency_rating', 'observed_level', 'comment'}:
                raise AccessError(_(
                    'Only L&D staff may change mapped Level 3 competencies.'))
            if any(line.evaluation_id.status == 'completed' for line in self):
                raise AccessError(_('Completed Level 3 observations cannot be edited.'))
        return super().write(vals)
