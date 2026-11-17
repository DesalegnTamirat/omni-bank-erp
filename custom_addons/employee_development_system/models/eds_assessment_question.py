# -*- coding: utf-8 -*-
"""Session-specific pre/post questions and participant responses."""

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class EdsAssessmentQuestion(models.Model):
    _name = 'eds.assessment.question'
    _description = 'EDS Pre / Post Assessment Question'
    _order = 'sequence, create_date desc, id desc'
    _rec_name = 'question_text'

    def _default_assessment_type(self):
        return self.env.context.get('default_assessment_type', 'pre')

    session_id = fields.Many2one('eds.session', string='Session', required=True,
                                 ondelete='cascade', index=True)
    assessment_type = fields.Selection([
        ('pre', 'Pre-Training Assessment'),
        ('post', 'Post-Training Assessment'),
    ], string='Assessment Type', default=_default_assessment_type, required=True)
    sequence = fields.Integer(default=10)
    question_text = fields.Text(string='Question', required=True)
    max_points = fields.Float(string='Maximum Points', default=1.0, required=True)
    answer_ids = fields.One2many('eds.assessment.answer', 'question_id', string='Answers')
    company_id = fields.Many2one(related='session_id.company_id', store=True,
                                 string='Company')

    @api.constrains('question_text', 'max_points')
    def _check_question(self):
        for question in self:
            if not (question.question_text or '').strip():
                raise ValidationError(_('An assessment question cannot be blank.'))
            if question.max_points <= 0:
                raise ValidationError(_('Maximum points must be greater than zero.'))

    @api.model
    def seed_from_instrument(self, session, assessment_type):
        """Copy a published Level-2 instrument when no session bank exists.

        The instrument's questions are prompts, not an answer key. L&D can
        adjust this session-specific bank before distributing it.
        """
        session.ensure_one()
        if assessment_type not in ('pre', 'post'):
            raise ValidationError(_('Only pre and post assessments have question banks.'))
        existing = self.search([
            ('session_id', '=', session.id),
            ('assessment_type', '=', assessment_type),
        ])
        if existing:
            return existing
        instrument = session.course_id.level2_instrument_id
        if not instrument or instrument.state != 'published' or not instrument.question_ids:
            return self.browse()
        return self.create([{
            'session_id': session.id,
            'assessment_type': assessment_type,
            'sequence': item.sequence,
            'question_text': item.name,
            'max_points': item.weight if item.weight > 0 else 1.0,
        } for item in instrument.question_ids])

    def _check_bank_not_distributed(self):
        for question in self:
            if self.env['eds.assessment'].search_count([
                ('session_id', '=', question.session_id.id),
                ('assessment_type', '=', question.assessment_type),
                ('state', 'in', ('distributed', 'submitted', 'graded')),
                ('entry_method', '!=', 'score_only'),
            ]) or self.env['eds.assessment.answer'].search_count([
                ('assessment_id.session_id', '=', question.session_id.id),
                ('assessment_id.assessment_type', '=', question.assessment_type),
                '|', ('answer_text', '!=', False), ('is_graded', '=', True),
            ]):
                raise ValidationError(_(
                    'The %s question bank for session %s has been sent or answered. '
                    'Keep its questions unchanged so recorded answers retain their meaning.'
                ) % (question.assessment_type, question.session_id.display_name))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._check_bank_not_distributed()
        return records

    def write(self, vals):
        if {'session_id', 'assessment_type', 'sequence', 'question_text', 'max_points'} & vals.keys():
            self._check_bank_not_distributed()
        if {'session_id', 'assessment_type'} & vals.keys() and self.mapped('answer_ids'):
            raise ValidationError(_(
                'A question with participant answers cannot move to another session or assessment type.'
            ))
        result = super().write(vals)
        if {'session_id', 'assessment_type'} & vals.keys():
            self._check_bank_not_distributed()
        return result

    def unlink(self):
        self._check_bank_not_distributed()
        answers = self.mapped('answer_ids')
        if answers:
            if answers.filtered(lambda answer: answer.assessment_id.state != 'draft'
                                or (answer.answer_text or '').strip()
                                or answer.is_graded):
                raise ValidationError(_(
                    'A question with recorded answers cannot be deleted.'
                ))
            # Loading blank rows to start manual entry must not prevent staff
            # from correcting an unused question bank before anyone answers.
            answers.unlink()
        return super().unlink()


class EdsAssessmentAnswer(models.Model):
    _name = 'eds.assessment.answer'
    _description = 'EDS Pre / Post Assessment Answer'
    _order = 'question_id, create_date desc, id desc'

    assessment_id = fields.Many2one('eds.assessment', required=True,
                                    ondelete='cascade', index=True)
    question_id = fields.Many2one('eds.assessment.question', required=True,
                                  ondelete='restrict', index=True)
    question_text = fields.Text(related='question_id.question_text', string='Question')
    max_points = fields.Float(related='question_id.max_points', string='Maximum Points')
    answer_text = fields.Text(string='Answer')
    awarded_points = fields.Float(string='Awarded Points')
    is_graded = fields.Boolean(string='Graded', default=False)
    comments = fields.Text(string='Grading Comments')
    company_id = fields.Many2one(related='assessment_id.company_id', store=True,
                                 string='Company')

    _assessment_question_uniq = models.Constraint(
        'UNIQUE(assessment_id, question_id)',
        'Each assessment question may have only one answer per participant.',
    )

    def _is_staff(self):
        return self.env.su or self.env.user.has_group(
            'employee_development_system.group_eds_officer')

    @api.constrains('assessment_id', 'question_id', 'awarded_points', 'is_graded')
    def _check_answer(self):
        for answer in self:
            if (answer.question_id.session_id != answer.assessment_id.session_id
                    or answer.question_id.assessment_type != answer.assessment_id.assessment_type):
                raise ValidationError(_(
                    'The answer question must belong to the same session and assessment type.'
                ))
            if answer.is_graded and not (0 <= answer.awarded_points <= answer.question_id.max_points):
                raise ValidationError(_(
                    'Awarded points must be between zero and the question maximum.'
                ))

    @api.model_create_multi
    def create(self, vals_list):
        if not self._is_staff():
            raise AccessError(_('Only L&D staff may create assessment answer rows.'))
        if self.env['eds.assessment'].browse([
                vals['assessment_id'] for vals in vals_list if vals.get('assessment_id')
        ]).filtered(lambda row: row.state == 'graded'):
            raise ValidationError(_('Reopen a graded assessment before adding answer rows.'))
        return super().create(vals_list)

    def write(self, vals):
        if {'assessment_id', 'question_id'} & vals.keys():
            raise ValidationError(_(
                'An answer cannot be reassigned to another participant or question.'
            ))
        if not self._is_staff():
            if set(vals) != {'answer_text'}:
                raise AccessError(_('Employees may edit only their own assessment answer text.'))
            for answer in self:
                assessment = answer.assessment_id
                if (assessment.state != 'distributed'
                        or assessment.employee_id.sudo().user_id.id != self.env.uid):
                    raise AccessError(_('This assessment is not open for your answers.'))
        previous_assessments = self.mapped('assessment_id')
        vals = dict(vals)
        if vals.get('is_graded') is False and 'awarded_points' not in vals:
            vals['awarded_points'] = 0.0
        if ('answer_text' in vals
                and not {'awarded_points', 'is_graded'} & vals.keys()):
            # A grade belongs to the answer as it was read by the grader.
            # Editing that text later must require a new grade, including in a
            # submitted assessment that has not yet been finalized.
            for answer in self:
                line_vals = dict(vals)
                if (answer.answer_text or '') != (vals['answer_text'] or ''):
                    line_vals.update({'awarded_points': 0.0, 'is_graded': False})
                super(EdsAssessmentAnswer, answer).write(line_vals)
            result = True
        else:
            result = super().write(vals)
        if {'answer_text', 'awarded_points', 'is_graded', 'question_id'} & vals.keys():
            previous_assessments.filtered(
                lambda assessment: assessment.entry_method != 'score_only'
                and assessment.state == 'graded'
            ).with_context(eds_assessment_invalidate=True).write({
                'state': 'submitted', 'score': 0.0,
            })
        return result

    def unlink(self):
        if not self._is_staff():
            raise AccessError(_('Only L&D staff may remove assessment answer rows.'))
        assessments = self.mapped('assessment_id')
        result = super().unlink()
        assessments.filtered(
            lambda assessment: assessment.entry_method != 'score_only'
            and assessment.state == 'graded'
        ).with_context(eds_assessment_invalidate=True).write({
            'state': 'submitted', 'score': 0.0,
        })
        return result
