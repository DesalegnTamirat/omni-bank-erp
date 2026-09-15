# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class HrPayslipEmployees(models.TransientModel):
    """
    Batch Payslip Generator Wizard.
    Allows mass generation of payslips for employees by department, operating unit, or explicit selection.
    """
    _name = 'hr.payslip.employees'
    _description = 'Generate Payslips for All Selected Employees'

    department_id = fields.Many2one('hr.department', string='Filter by Department / Branch')
    employee_ids = fields.Many2many('hr.employee', string='Employees to Include', required=True)
    structure_id = fields.Many2one('hr.payroll.structure', string='Salary Structure')

    @api.onchange('department_id')
    def _onchange_department(self):
        if self.department_id:
            employees = self.env['hr.employee'].search([
                ('department_id', '=', self.department_id.id),
                ('active', '=', True)
            ])
            self.employee_ids = employees
        else:
            self.employee_ids = self.env['hr.employee'].search([('active', '=', True)])

    def compute_sheet(self):
        """Mass generate payslips and attach to the active hr.payslip.run."""
        self.ensure_one()
        active_id = self.env.context.get('active_id')
        if not active_id:
            raise UserError(_("No active Payrun batch found."))

        run = self.env['hr.payslip.run'].browse(active_id)
        default_struct = self.structure_id or run.struct_id or self.env['hr.payroll.structure'].search([('code', '=', 'ETH_BANK_STD')], limit=1)

        payslips_to_create = []
        for emp in self.employee_ids:
            # Check if payslip already exists in this run
            existing = self.env['hr.payslip'].search([
                ('employee_id', '=', emp.id),
                ('payslip_run_id', '=', run.id)
            ], limit=1)
            if existing:
                continue

            payslips_to_create.append({
                'employee_id': emp.id,
                'payslip_run_id': run.id,
                'period_id': run.period_id.id,
                'date_from': run.date_start,
                'date_to': run.date_end,
                'struct_id': default_struct.id if default_struct else False,
                'company_id': run.company_id.id,
            })

        slips = self.env['hr.payslip'].create(payslips_to_create)
        # Trigger calculation
        for slip in slips:
            slip._onchange_employee()
            slip.compute_sheet()

        return {'type': 'ir.actions.act_window_close'}
