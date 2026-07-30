from odoo import models, fields


class HrReinstatedHistory(models.Model):
    _name = 'hr.reinstated.history'
    _description = 'Employee Reinstated History'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, ondelete='cascade')
    new_job_grade_id = fields.Many2one('employee.grade', string='New Job Grade')
    job_title = fields.Char(string='Job Title')
    new_salary = fields.Float(string='New Salary')
    date = fields.Date(string='Date')