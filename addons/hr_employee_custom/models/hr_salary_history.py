from odoo import models, fields


class HrSalaryHistory(models.Model):
    _name = 'hr.salary.history'
    _description = 'Employee Salary History'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, ondelete='cascade')
    updated_on = fields.Date(string='Updated On')
    salary_element = fields.Char(string='Salary Element')
    current_value = fields.Float(string='Current Value')
    old_value = fields.Float(string='Old Value')