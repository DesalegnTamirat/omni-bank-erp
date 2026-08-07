from odoo import api, fields, models

class acting(models.Model):
    _name = 'supplementary.role'  # Replace with your actual model name
    _description = 'Your Model Description'

    name = fields.Char(string='Name')
    employee_category = fields.Selection([
        ('managerial', 'Managerial'),
        ('non_managerial', 'Non-Managerial'),
    ], string='Employee Category')

    @api.model
    def action_print_report(self):
        if self.employee_category == 'managerial':
            return self.env['report'].get_action(self, 'cortex_hr_addons.report_managerial')
        elif self.employee_category == 'non_managerial':
            return self.env['report'].get_action(self, 'cortex_hr_addons.report_non_managerial')
        else:
            raise UserError("Unsupported employee category")
