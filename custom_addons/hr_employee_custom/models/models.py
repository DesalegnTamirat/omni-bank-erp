# from odoo import models, fields, api


# class hr_employee_custom(models.Model):
#     _name = 'hr_employee_custom.hr_employee_custom'
#     _description = 'hr_employee_custom.hr_employee_custom'

#     name = fields.Char()
#     value = fields.Integer()
#     value2 = fields.Float(compute="_value_pc", store=True)
#     description = fields.Text()
#
#     @api.depends('value')
#     def _value_pc(self):
#         for record in self:
#             record.value2 = float(record.value) / 100

