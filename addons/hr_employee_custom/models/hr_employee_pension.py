from odoo import models, fields


class HrEmployeePension(models.Model):
    _inherit = 'hr.employee'

    pension_employee_percentage = fields.Float(string='Employee Contribution (%)')
    pension_employer_percentage = fields.Float(string='Employer Contribution (%)')
    pension_fund = fields.Char(string='Pension Fund')
    pension_start_date = fields.Date(string='Pension Start Date')
    pension_reference = fields.Char(string='Pension Reference')
    pension_notes = fields.Text(string='Notes')