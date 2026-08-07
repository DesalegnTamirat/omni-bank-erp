from odoo import fields, models, api, _
class EmployeeCategory(models.Model):
    _name = "employee.category"
    _description = "To set Employee Category from  Configuration level"
    _rec_name = 'category_name'
    category_name=fields.Char(string="Category")