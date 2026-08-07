# -*- coding: utf-8 -*-
from odoo import fields, models, _


class EmployeeRecruitmentAvailable(models.Model):
    _inherit = 'employee.recruitment.available'

    _description = 'Available Internal Vacancies'
    _rec_name = 'vacancy_reference'

    active = fields.Boolean(default=True)

    vacancy_id = fields.Many2one(
        'job.vacancy', string='Vacancy', index=True, ondelete='set null'
    )
    vacancy_reference = fields.Char(string='Vacancy Reference')
    job_position = fields.Char(string='Job Position')
    job_location = fields.Char(string='Work Unit / Location')
    employee_grade = fields.Char(string='Grade')
    employee_category = fields.Char(string='Category')
    type_of_employment = fields.Char(string='Type of Employment')
    number_of_vacancies = fields.Integer(string='Number of Vacancies')
    vacancy_announced_on = fields.Date(string='Announced On')
    last_date_to_apply = fields.Date(string='Last Date to Apply')
    job_description = fields.Text(string='Job Description')


    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True
