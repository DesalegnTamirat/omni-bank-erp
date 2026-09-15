# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _


class HrPayslipLine(models.Model):
    """
    Individual Computed Payslip Item Line.
    Represents an atomic calculated component (Basic, Allowance, Tax, Pension, Penalty, Net) on an employee's payslip.
    """
    _name = 'hr.payslip.line'
    _description = 'Payslip Calculation Line Item'
    _order = 'sequence, id'

    slip_id = fields.Many2one(
        'hr.payslip',
        string='Payslip',
        required=True,
        ondelete='cascade',
        index=True
    )
    salary_rule_id = fields.Many2one(
        'hr.salary.rule',
        string='Salary Rule',
        required=True,
        index=True
    )
    category_id = fields.Many2one(
        'hr.salary.rule.category',
        string='Category',
        related='salary_rule_id.category_id',
        store=True,
        index=True
    )
    name = fields.Char(string='Description', required=True)
    code = fields.Char(string='Rule Code', required=True, index=True)
    sequence = fields.Integer(string='Sequence', default=50)
    appears_on_payslip = fields.Boolean(
        string='Visible on Slip',
        default=True
    )

    rate = fields.Float(string='Rate (%)', digits=(16, 4), default=100.0)
    amount = fields.Float(string='Unit Amount (ETB)', digits=(16, 2), default=0.0)
    quantity = fields.Float(string='Quantity / Units', digits=(16, 4), default=1.0)
    total = fields.Float(
        string='Line Total (ETB)',
        compute='_compute_total',
        store=True,
        digits=(16, 2)
    )

    note = fields.Text(string='Line Notes')

    @api.depends('quantity', 'amount', 'rate')
    def _compute_total(self):
        """Compute the final financial monetary line total."""
        for line in self:
            line.total = float(round((line.quantity * line.amount * line.rate) / 100.0, 2))
