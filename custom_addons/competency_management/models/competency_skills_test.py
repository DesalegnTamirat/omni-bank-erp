# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class CompetencySkillsTest(models.Model):
    """Formal Skills Test / Examination record feeding into competency assessment (FR-ASM-003)."""
    _name = 'competency.skills.test'
    _description = 'Competency Skills Test / Examination'
    _order = 'test_date desc, id desc'

    name = fields.Char(string='Test Title / Reference', required=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    competency_id = fields.Many2one('competency.competency', string='Target Competency', required=True)
    test_date = fields.Date(string='Test Date', default=fields.Date.context_today, required=True)
    score_percent = fields.Float(string='Score (%)', required=True)
    verified_level = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Verified Proficiency Level', compute='_compute_verified_level', store=True, readonly=False)
    status = fields.Selection([
        ('pass', 'Pass'),
        ('fail', 'Fail'),
    ], string='Result', compute='_compute_status', store=True)
    meets_competency_requirements = fields.Boolean(
        string='Meets Competency Requirements',
        compute='_compute_status',
        store=True,
        help='Automatically set to False if test score is under 50% threshold.'
    )
    examiner_id = fields.Many2one('res.users', string='Examiner / Evaluator', default=lambda self: self.env.user)
    notes = fields.Text(string='Examiner Remarks')

    @api.depends('score_percent')
    def _compute_verified_level(self):
        for rec in self:
            if rec.score_percent >= 85:
                rec.verified_level = '4'
            elif rec.score_percent >= 70:
                rec.verified_level = '3'
            elif rec.score_percent >= 50:
                rec.verified_level = '2'
            else:
                rec.verified_level = '1'

    @api.depends('score_percent')
    def _compute_status(self):
        for rec in self:
            is_pass = rec.score_percent >= 50.0
            rec.status = 'pass' if is_pass else 'fail'
            rec.meets_competency_requirements = is_pass

    @api.constrains('score_percent', 'status', 'meets_competency_requirements')
    def _check_passing_threshold(self):
        for rec in self:
            if rec.score_percent < 50.0:
                if rec.status == 'pass' or rec.meets_competency_requirements:
                    raise ValidationError(_('Competitive Threshold Violation: Exam scores below 50%% (%s%% achieved) automatically fail and cannot meet competency requirements.') % rec.score_percent)
