from odoo import api, models, fields, _
from odoo.exceptions import ValidationError
from odoo.exceptions import UserError
from datetime import date


class InternalJobPosition(models.Model):
    _name = "employee.recruitment.available"
    _description = "Internal Job Position"
    _rec_name = "operating_unit"
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    vacancy_reference = fields.Char(string="Vacancy Reference", readonly=True)
    vacancy_id = fields.Integer(string="Vacancy ID")
    recruitment_reference = fields.Char(string="Recruitment Reference", readonly=True)
    employee_applicant = fields.Char("Employee Applicant", readonly=True)
    operating_unit = fields.Char("Operating Unit", readonly=True)
    job_location = fields.Char("Work Unit")
    job_position = fields.Char("Job Position", readonly=True)
    employee_grade = fields.Char("Grade", readonly=True)
    employee_category = fields.Char("Employee Category", readonly=True)
    type_of_employment = fields.Char("Type of Employment")
    number_of_vacancies = fields.Integer("Number of Vacancies")
    vacancy_announced_on = fields.Date("Vacancy Announced On", readonly=True)
    last_date_to_apply = fields.Date("Last Date to Apply", readonly=True)
    job_description = fields.Text("Job Description", readonly=True)
    application_reason = fields.Text("Application Reason")
    allowance_difference = fields.Float("Difference in Allowance")
    employee_id = fields.Integer("Employee Id")
    preferred_location = fields.Many2one('operating.unit', string="Preferred Location")
    employee_user_id = fields.Integer("Employee User Id")
    job_position_id = fields.Integer("Job Position Id")
    application_status = fields.Char("Application Status", default='New')
    employee_vacancy_ids = fields.One2many('employee.vacancy.available', 'vacancy_id', 'Vacancy Info')
    rejection_reason = fields.Text("Rejection Reason")

    def apply(self):
        p_id = self.id
        today = date.today()
        # today = today. strftime("%Y-%m-%d")
        n = 0
        x = 0
        for val in self.employee_vacancy_ids:
            if val:
                x = x + 1
                if val.location_preference > 0:
                    n = n + 1
        if x > 0:
            if n > 0:
                if self.last_date_to_apply < today:
                    raise ValidationError('You Cannot Apply after the Last Date to Apply ')
                else:
                    self.env.cr.execute('SELECT internal_application(%s)', (p_id,))
            else:
                raise ValidationError('Please enter your preferences of work units')

    def accept_promotion(self):
        p_id = self.employee_id
        self.env.cr.execute('SELECT employee_notify_promotion_acceptance(%s)', (p_id,))

    def reject_promotion(self):
        p_id = self.employee_id
        self.env.cr.execute('SELECT employee_notify_promotion_rejection(%s)', (p_id,))


class InternalJobVacancy(models.Model):
    _name = "employee.vacancy.available"
    _description = "Internal Job Vacancies"
    _rec_name = "operating_unit"
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    vacancy_id = fields.Many2one('employee.recruitment.available', string="Employee Vacancy")
    employee_applicant = fields.Char("Employee Applicant")
    operating_unit = fields.Char("Work Unit", readonly=True)
    number_of_vacancies = fields.Integer("Number of Vacancies")
    location_preference = fields.Integer(string="Location Preference", help='Provide Location Preference',
                                         required=True)
