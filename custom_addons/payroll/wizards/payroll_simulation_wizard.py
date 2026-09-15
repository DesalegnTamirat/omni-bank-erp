# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PayrollSimulationWizard(models.TransientModel):
    """
    Enterprise Payroll Simulation & Budgetary Impact Wizard (FR-PAY-034).
    
    Allows HR and Financial planning leaders to execute non-committal virtual dry-runs
    evaluating projected wage bills, statutory liabilities, and department variance.
    """
    _name = 'payroll.simulation.wizard'
    _description = 'Payroll Financial Simulation Wizard'

    period_id = fields.Many2one('hr.payroll.period', string='Target Pay Period', required=True)
    department_id = fields.Many2one('hr.department', string='Optional Department Filter')
    include_pending_promotions = fields.Boolean(string='Include Pending Approved Promotions', default=True)
    include_pending_increments = fields.Boolean(string='Include Pending Salary Increments', default=True)
    
    # Projected Financial Metrics
    projected_headcount = fields.Integer(string='Projected Headcount', readonly=True)
    projected_basic_wage = fields.Float(string='Projected Basic Wage (ETB)', readonly=True, digits=(16, 2))
    projected_gross_cost = fields.Float(string='Projected Gross Earnings (ETB)', readonly=True, digits=(16, 2))
    projected_net_payout = fields.Float(string='Projected Net Disbursement (ETB)', readonly=True, digits=(16, 2))
    projected_tax_liability = fields.Float(string='Projected Personal Tax (ETB)', readonly=True, digits=(16, 2))
    projected_pension_cost = fields.Float(string='Projected Total Pension (18%)', readonly=True, digits=(16, 2))
    
    variance_vs_previous_month = fields.Float(string='Variance vs Prior Month (ETB)', readonly=True, digits=(16, 2))
    variance_pct = fields.Float(string='Variance Ratio (%)', readonly=True, digits=(5, 2))
    simulation_notes = fields.Text(string='Simulation Summary Analysis', readonly=True)
    is_simulated = fields.Boolean(string='Simulation Executed', default=False)

    def action_run_simulation(self):
        """Execute simulation calculations across target active employees."""
        self.ensure_one()
        domain = [('active', '=', True)]
        if self.department_id:
            domain.append(('department_id', '=', self.department_id.id))

        employees = self.env['hr.employee'].search(domain)
        count = len(employees)
        if count == 0:
            raise UserError(_("No active employees found matching the filter criteria."))

        total_basic = 0.0
        total_gross = 0.0
        total_net = 0.0
        total_tax = 0.0
        total_pension = 0.0

        for emp in employees:
            wage = getattr(emp, 'wage', 0.0) or getattr(emp, 'basic_salary', 0.0) or 0.0
            total_basic += wage
            # Estimated gross with standard allowances (approx 1.25x base)
            gross = wage * 1.25
            total_gross += gross
            
            # Tax approximation (approx 20% effective tax rate on gross)
            tax = max(0.0, (gross - 600.0) * 0.20)
            total_tax += tax
            
            # Pension: 18% total (7% EE + 11% ER)
            pension = wage * 0.18
            total_pension += pension
            
            # Net: Gross minus Tax minus EE Pension (7%)
            net = gross - tax - (wage * 0.07)
            total_net += net

        # Compare with prior month finalized run
        prior_run = self.env['hr.payslip.run'].search([('state', 'in', ['approved', 'posted', 'disbursed'])], order='date_end desc', limit=1)
        prior_gross = prior_run.total_gross if prior_run else 0.0
        diff = total_gross - prior_gross if prior_gross > 0 else 0.0
        pct = (diff / prior_gross * 100.0) if prior_gross > 0 else 0.0

        self.write({
            'projected_headcount': count,
            'projected_basic_wage': round(total_basic, 2),
            'projected_gross_cost': round(total_gross, 2),
            'projected_net_payout': round(total_net, 2),
            'projected_tax_liability': round(total_tax, 2),
            'projected_pension_cost': round(total_pension, 2),
            'variance_vs_previous_month': round(diff, 2),
            'variance_pct': round(pct, 2),
            'is_simulated': True,
            'simulation_notes': _(
                "SIMULATION PROJECTION REPORT:\n"
                "- Headcount Evaluated: %d active staff\n"
                "- Projected Total Gross: ETB %.2f (Shift: %+.2f%%)\n"
                "- Projected Net Disbursement: ETB %.2f\n"
                "- Estimated Tax Withholding: ETB %.2f\n"
                "- Estimated Pension Liability: ETB %.2f\n"
            ) % (count, total_gross, pct, total_net, total_tax, total_pension)
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'payroll.simulation.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
