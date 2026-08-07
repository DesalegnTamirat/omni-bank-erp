from odoo import api, models,fields,_
class ApplicantShortlist(models.Model):
    _name = "applicant.shortlist"
    _description = "Applicant Shortlist"
    _rec_name = "recruitment_reference"

    recruitment_reference = fields.Char(string="Recruitment Reference")
    job_position = fields.Char(string="Job Applied For")
    applicant_id=fields.Many2one("hr.applicant", "Applicant Name")
    applicant_name = fields.Char(string="Applicant Name")
    active = fields.Boolean(default=True)
    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True
    applicant_gender= fields.Char(string="Gender")
    educational_qualification = fields.Char(string="Educational Qualification")
    CGPA = fields.Float(string="CGPA")
    years_of_experience = fields.Float(string="Years of Experience")
    banking_experience = fields.Float(string="Banking Experience")
    current_working = fields.Char(string="Working Status")
    current_company = fields.Char(string="Current Company")
    current_location = fields.Char(string="Current Location")
    join_immediately= fields.Boolean(string='Join Immediately', default=True)
    available_date= fields.Date(string="Available Date")
    applicant_email = fields.Char(string="Applicant email")
    notify_candidate = fields.Boolean(string='Notify Candidate', default=False)
