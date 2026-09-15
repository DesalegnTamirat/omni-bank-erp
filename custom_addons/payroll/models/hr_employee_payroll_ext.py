# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _


class HrEmployee(models.Model):
    """
    Employee Master Payroll Extensions.
    Adds direct linkages, smart statistics, and historical compensation views to hr.employee.
    """
    _inherit = 'hr.employee'

    basic_salary = fields.Float(string='Basic Salary (ETB)', digits=(16, 2), tracking=True)
    salary_account = fields.Char(string='Salary Bank Account', tracking=True)
    bank_account_number = fields.Char(string='Bank Account Number', related='salary_account', readonly=False)
    tin = fields.Char(string='TIN Number', tracking=True)
    joining_date = fields.Date(string='Joining Date', tracking=True)
    pms_score = fields.Float(string='PMS Rating Score', digits=(16, 2), tracking=True)

    payslip_ids = fields.One2many('hr.payslip', 'employee_id', string='Payslips')
    payslip_count = fields.Integer(string='Payslips Count', compute='_compute_payroll_metrics')
    
    acting_assignment_ids = fields.One2many('hr.acting.assignment', 'employee_id', string='Acting Assignments')
    active_acting_assignment_id = fields.Many2one(
        'hr.acting.assignment',
        string='Current Acting Assignment',
        compute='_compute_payroll_metrics'
    )
    
    hardship_history_ids = fields.One2many('hr.hardship.allowance.history', 'employee_id', string='Hardship History')
    retroactive_adjustment_ids = fields.One2many('hr.payroll.retroactive', 'employee_id', string='Retroactive Adjustments')

    latest_net_wage = fields.Float(string='Latest Net Salary (ETB)', compute='_compute_payroll_metrics', digits=(16, 2))

    def _compute_payroll_metrics(self):
        """Compute summary statistics for employee form view."""
        for emp in self:
            emp.payslip_count = len(emp.payslip_ids)
            latest_slip = self.env['hr.payslip'].search([
                ('employee_id', '=', emp.id),
                ('state', 'in', ['done', 'paid'])
            ], order='date_to desc', limit=1)
            emp.latest_net_wage = latest_slip.net_wage if latest_slip else 0.0

            active_acting = emp.acting_assignment_ids.filtered(lambda a: a.state in ['approved', 'capped'])
            emp.active_acting_assignment_id = active_acting[0].id if active_acting else False

    def action_view_employee_payslips(self):
        """Action for smart button to view payslips of this employee."""
        self.ensure_one()
        return {
            'name': _('Payslips of %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payslip',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }
