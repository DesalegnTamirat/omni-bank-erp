# -*- coding: utf-8 -*-

from odoo import api, models, fields, _


class applicant_assessment(models.Model):
    _name = "applicant.assessment"
    _description = "Applicant Assessment"
    _rec_name = "assessor_name"

    vacancy_reference = fields.Char(string="Vacancy Reference")
    recruiting_position = fields.Many2one("hr.job", string="Recruiting Position")
    assessor_name = fields.Many2one("hr.employee", string="Assessor")
    assessment_date = fields.Date(string="Assessment Date")
    applicant_name = fields.Many2one("hr.applicant", string="Applicant Name")
    active = fields.Boolean(default=True)

    recruitment_type = fields.Selection(
        [('Internal', 'Internal Recruitment'), ('External', 'External Recruitment')],
        string="Recruitment Type",
        default='Internal'
    )
    weight = fields.Float(string="Weight")
    candidate_attendance = fields.Selection(
        [('present', 'Present'), ('absent', 'Absent')],
        string="Attendance",
        default='present'
    )
    marks_awarded = fields.Float(string="Marks Awarded")

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True
