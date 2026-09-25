from odoo import models, fields, api


class HrEmployeeCustom(models.Model):
    _inherit = 'hr.employee'

    job_grade = fields.Char(string='Job Grade')
    job_category = fields.Char(string='Job Category')
    operating_unit = fields.Many2one('operating.unit', string='Operating Unit')

    # Add gender field if it doesn't exist in base hr.employee
    # In Odoo 19, gender might not be a standard field
    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
    ], string='Gender')