# -*- coding: utf-8 -*-
from odoo import models, fields, tools

class HrExitAnalytics(models.Model):
    _name = 'hr.exit.analytics'
    _description = 'Anonymous Exit Interview Analytics'
    _auto = False
    _rec_name = 'question_name'

    resignation_type_id = fields.Many2one('hr.separation.type', string='Separation Type', readonly=True)
    department_id = fields.Many2one('hr.department', string='Department', readonly=True)
    question_name = fields.Char(string='Question', readonly=True)
    question_type = fields.Selection([
        ('rating',       'Rating'),
        ('satisfaction', 'Satisfaction'),
        ('agreement',    'Agreement'),
        ('boolean',      'Yes / No'),
        ('boolean_agree','Agree / Disagree'),
        ('custom',       'Custom Choices'),
        ('checkbox',     'Multiple Choices'),
        ('text',         'Open-ended Text'),
    ], string='Question Type', readonly=True)
    answer = fields.Char(string='Answer', readonly=True)
    count = fields.Integer(string='Count', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    l.id AS id,
                    r.resignation_type_id,
                    e.department_id,
                    l.question_name,
                    l.question_type,
                    l.answer,
                    1 AS count
                FROM hr_exit_interview_line l
                JOIN hr_exit_interview i ON i.id = l.interview_id
                JOIN hr_resignation r ON r.id = i.resignation_id
                JOIN hr_employee e ON e.id = r.employee_id
                WHERE i.state = 'completed'
            )
        """ % self._table)
