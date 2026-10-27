# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class LmsQuestionPool(models.Model):
    """Question category pool for randomized sampling (FR-LMS-015)."""
    _name = 'lms.question.pool'
    _description = 'LMS Question Pool'
    _order = 'name'

    name = fields.Char(string='Pool Name', required=True)
    code = fields.Char(string='Pool Code', required=True)
    description = fields.Text(string='Description / Domain')
    question_ids = fields.One2many('lms.question', 'pool_id', string='Questions in Pool')
    question_count = fields.Integer(string='Question Count', compute='_compute_count')

    def _compute_count(self):
        for rec in self:
            rec.question_count = len(rec.question_ids)

    def _is_locked(self):
        assessments = self.env['lms.assessment'].sudo().search([('pool_ids', 'in', self.ids)])
        return any(assessment.course_id.state in ('review', 'published', 'archived')
                   for assessment in assessments)

    def write(self, vals):
        if not self.env.su and self._is_locked():
            raise UserError(_('Create a new course revision to change a reviewed question pool.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.su and (self._is_locked() or self.question_ids._is_locked()):
            raise UserError(_('A question pool used by a reviewed course or exam cannot be deleted.'))
        return super().unlink()


class LmsQuestion(models.Model):
    """LMS Question Bank Item (FR-LMS-015, FR-LMS-017)."""
    _name = 'lms.question'
    _description = 'Exam Question Item'
    _order = 'sequence, id'

    name = fields.Char(string='Question Summary', required=True)
    pool_id = fields.Many2one('lms.question.pool', string='Question Pool', index=True)
    sequence = fields.Integer(default=10)

    question_type = fields.Selection([
        ('single_choice', 'Single Choice (Radio Button)'),
        ('multiple_choice', 'Multiple Choice (Checkboxes)'),
        ('true_false', 'True / False Statement'),
    ], string='Question Type', default='single_choice', required=True)

    question_text = fields.Html(string='Question Text', required=True)
    points = fields.Float(string='Score Points / Weight', default=1.0, required=True)
    difficulty = fields.Selection([
        ('easy', 'Basic / Easy'),
        ('medium', 'Intermediate / Medium'),
        ('hard', 'Advanced / Hard'),
    ], string='Difficulty Level', default='medium')

    answer_ids = fields.One2many('lms.question.answer', 'question_id', string='Answer Choices')
    explanation = fields.Html(
        string='Explanation / Rationale (Displayed Post-Grading)',
        groups='learning_management.group_lms_instructor',
    )
    session_line_ids = fields.One2many('lms.exam.session.line', 'question_id', string='Session Lines')

    active = fields.Boolean(default=True)

    def _is_locked(self):
        if not self:
            return False
        if self.env['lms.exam.session.line'].sudo().search_count([('question_id', 'in', self.ids)]):
            return True
        assessments = self.env['lms.assessment'].sudo().search([
            '|', ('fixed_question_ids', 'in', self.ids),
            ('pool_ids', 'in', self.mapped('pool_id').ids),
        ])
        return any(assessment.course_id.state in ('review', 'published', 'archived')
                   for assessment in assessments)

    def _validate_for_publication(self):
        for question in self:
            answers = question.answer_ids
            correct = answers.filtered('is_correct')
            if question.points <= 0 or len(answers) < 2 or not correct or len(correct) == len(answers):
                raise UserError(_('Question "%s" needs positive points and both correct and incorrect choices.') % question.name)
            if question.question_type in ('single_choice', 'true_false') and len(correct) != 1:
                raise UserError(_('Question "%s" must have exactly one correct choice.') % question.name)
            if question.question_type == 'true_false' and len(answers) != 2:
                raise UserError(_('True/false question "%s" must have two choices.') % question.name)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            for vals in vals_list:
                pool = self.env['lms.question.pool'].browse(vals.get('pool_id'))
                if pool and pool._is_locked():
                    raise UserError(_('Create a course revision before adding questions to this pool.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            target = self.env['lms.question.pool'].browse(vals['pool_id']) if vals.get('pool_id') else False
            if self._is_locked() or (target and target._is_locked()):
                raise UserError(_('Create a new course revision to edit a reviewed or attempted question.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.su and self._is_locked():
            raise UserError(_('Questions used by reviewed courses or exam attempts cannot be deleted.'))
        return super().unlink()

    @api.constrains('answer_ids')
    def _check_answers(self):
        for rec in self:
            if rec.answer_ids:
                correct = rec.answer_ids.filtered(lambda a: a.is_correct)
                if not correct:
                    raise ValidationError(_('Question "%s" must have at least one correct answer option.') % rec.name)


class LmsQuestionAnswer(models.Model):
    """Answer options for a question."""
    _name = 'lms.question.answer'
    _description = 'Question Answer Option'
    _order = 'sequence, id'
    _rec_name = 'answer_text'

    question_id = fields.Many2one('lms.question', string='Question', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    answer_text = fields.Char(string='Answer Option Text', required=True)
    is_correct = fields.Boolean(
        string='Is Correct Answer',
        default=False,
        groups='learning_management.group_lms_instructor'
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            for vals in vals_list:
                question = self.env['lms.question'].browse(vals.get('question_id'))
                if question and question._is_locked():
                    raise UserError(_('Create a course revision before adding answers to this question.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            target = self.env['lms.question'].browse(vals['question_id']) if vals.get('question_id') else False
            if self.mapped('question_id')._is_locked() or (target and target._is_locked()):
                raise UserError(_('Answers used by reviewed courses or exam attempts cannot be changed.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.su and self.mapped('question_id')._is_locked():
            raise UserError(_('Answers used by reviewed courses or exam attempts cannot be deleted.'))
        return super().unlink()
