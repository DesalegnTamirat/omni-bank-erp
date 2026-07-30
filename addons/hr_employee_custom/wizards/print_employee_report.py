# -*- coding: utf-8 -*-
from odoo import fields, models, api, _


class PrintEmployeeReport(models.TransientModel):
    _name = 'print.employee.report'
    _description = 'Print Employee Report Wizard'

    employee_id = fields.Many2one(
        "hr.employee", string='Employee', required=True,
    )
    report_type = fields.Selection([
        ('standard', 'Standard Employee Report'),
        ('experience', 'Employee Experience Report'),
    ], string='Report Type', default='standard', required=True)

    def action_print_report(self):
        """Generate the appropriate PDF report."""
        self.ensure_one()
        if self.report_type == 'experience':
            return self.env.ref(
                'hr_employee_custom.action_report_employee_experience_letter'
            ).report_action(self.employee_id)
        else:
            # Standard report — open employee form for printing
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'hr.employee',
                'res_id': self.employee_id.id,
                'view_mode': 'form',
                'target': 'current',
            }
