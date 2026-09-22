# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


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
    explanation = fields.Html(string='Explanation / Rationale (Displayed Post-Grading)')
    session_line_ids = fields.One2many('lms.exam.session.line', 'question_id', string='Session Lines')

    active = fields.Boolean(default=True)

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

    question_id = fields.Many2one('lms.question', string='Question', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    answer_text = fields.Char(string='Answer Option Text', required=True)
    is_correct = fields.Boolean(
        string='Is Correct Answer',
        default=False,
        groups='learning_management.group_lms_instructor'
    )
