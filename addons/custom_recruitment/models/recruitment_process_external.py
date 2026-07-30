from odoo import api, models, fields, _


class RecruitmentProcessExternal(models.Model):
    _name = "employee.recruitment.external"
    _inherit = "mail.thread"
    _description = "external Recruitment process"
    _rec_name = "job_position"

    vacancy_reference = fields.Char(string="Vacancy Reference")
    vacancy_id = fields.Integer(string="Vacancy ID")
    recruitment_reference = fields.Char(string="Recruitment Reference")
    job_position = fields.Many2one("hr.job", string="Job Position")
    job_location = fields.Char(string="Work Unit")
    workunit_id = fields.Integer(string="Work Unit Id")
    job_grade_id =fields.Integer(string="Work Unit Id")
    job_grade = fields.Char(string="Grade")
    job_category = fields.Char(string="Category")
    relevant_experience=fields.Float(string="Relevant Experience")
    supervisory_experience = fields.Float(string="Supervisory Experience")
    highest_cgpa=fields.Float(string="Highest CGPA")
    vacancy_announced_on = fields.Date(string="Vacancy Announced On")
    last_date_to_apply = fields.Date(string="Last Date To Apply")
    responsible = fields.Many2one('hr.employee', string="Responsible", required=True)
    no_of_vacancies=fields.Integer(string="Number of Vacancies")
    status = fields.Selection([('notify', 'Notified')], string="Status")
    eligible_emp_external = fields.One2many("external.recruitment.eligible.employees", "external_recruitment_id",
                                            string="External Recruitment")

    def notify(self):
        p_id = self.id
        # self.env.cr.execute('SELECT notify_external_applicant(%s)', (p_id,))
        self.env.cr.execute('SELECT external_applicant(%s)', (p_id,))
        self.status = 'notify'
        return self.status


class EligibleEmployeesexternal(models.Model):
    _name = "external.recruitment.eligible.employees"
    _description = "Eligible Employees"

    applicant_name = fields.Many2one("hr.applicant", string="Applicant Name")
    applicant_email = fields.Char(string="E Mail")
    applicant_phone = fields.Char(string="Phone")
    applicant_id = fields.Integer(string="Applicant Id")
    date_of_birth = fields.Char(string="Date of Birth")
    applicant_age = fields.Char(string="Age")
    gender = fields.Char(string="Gender")
    working_status = fields.Char(string="Working Status")
    current_company = fields.Char(string="Current Company")
    join_immediately = fields.Char(string="Willing to Join Immediately")
    preferred_location = fields.Char(string="Preferred Location")
    date_of_availability = fields.Date(string="Available From")
    highest_cgpa = fields.Float(string="Highest CGPA")
    relevant_experience = fields.Float(string="Relevant Experience")
    supervisory_experience = fields.Float(string="Supervisory Experience")
    banking_experience = fields.Float(string="Banking Experience")
    non_banking_experience = fields.Float(string="Non Banking Experience")
    total_experience = fields.Float(string="Total Experience")
    ex_bunna = fields.Boolean(string="Ex Bunna")
    preferred_location = fields.Char(string="Preferred Location")
    select_flag = fields.Boolean(string="Select")
    job_position=fields.Integer(string="job position")
    external_recruitment_id = fields.Many2one("employee.recruitment.external", string="External Recruitment")
