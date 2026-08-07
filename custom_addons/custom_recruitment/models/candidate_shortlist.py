from odoo import api, models, fields, _


class CandidateShortlist(models.Model):
    _name = "candidate.shortlist"
    _description = "Candidate Shortlist"
    _rec_name = "recruitment_reference"

    recruitment_reference = fields.Char(string="Recruitment Reference")
    job_position = fields.Char(string="Job Applied For")
    employee_id = fields.Many2one("hr.employee", "Employee Name")
    employee_name = fields.Char(string="Employee Name")
    active = fields.Boolean(default=True)
    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True
    employee_number = fields.Char(string="Employee Number")
    employee_gender= fields.Char(string="Gender")
    current_position=fields.Char(string="Position")
    educational_qualification = fields.Char(string="Educational Qualification")
    CGPA = fields.Float(string="CGPA")
    relevant_experience = fields.Float(string="Relevant Experience")
    supervisory_experience = fields.Float(string="Supervisory Experience")
    written_warning = fields.Float(string="Months since Written Warning")
    demoted = fields.Boolean(string='Demoted Employee', default=False)
    service_in_company = fields.Float(string="Service in Company")
    last_promotion = fields.Float(string="Months since last Promotion")
    pms_score = fields.Float(string="PMS Score")
    job_category = fields.Char(string="Current Category")
    current_location = fields.Char(string="Current Location")
    current_work_unit = fields.Char(string="Current Work Unit")
    applicant_id = fields.Many2one("hr.applicant", "Applicant Name")
    applicant_email = fields.Char(string="Applicant email")
    notify_candidate = fields.Boolean(string='Notify Candidate', default=False)
