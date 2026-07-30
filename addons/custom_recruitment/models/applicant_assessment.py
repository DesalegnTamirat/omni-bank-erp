from odoo import api, models,fields,_

class applicant_assessment(models.Model):
    _name = "applicant.assessment"
    _description = "Applicant Assessment"
    _rec_name = "assessor_name"
    vacancy_reference=fields.Char(string="Vacancy Reference")
    recruiting_position = fields.Many2one("hr.job",string="Recruiting Position")
    assessor_name = fields.Many2one("hr.employee","Assessor")
    assessment_date = fields.Date("Assessment Date")
    applicant_name = fields.Many2one("hr.applicant","Applicant Name")
    recruitment_type = fields.Selection(
        [('Internal', 'Internal Recruitment'), ('External', 'External Recruitment')], string="Recruitment Type", default='Internal')
    # assessment_criteria = fields.Many2one("assessment.criteria","Assessment Criteria")
    weight=fields.Float("Weight")
    candidate_attendance= fields.Selection(
        [('present', 'Present'), ('absent', 'Absent')], string="Attendance", default='present')
    marks_awarded=fields.Float("Marks Awarded")
