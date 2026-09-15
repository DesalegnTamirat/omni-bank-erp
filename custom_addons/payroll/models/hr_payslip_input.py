# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _


class HrPayslipInput(models.Model):
    """
    Manual and Integrated Variable Payslip Inputs.
    Captures ad-hoc allowances, one-time bonuses, approved loan deductions,
    or imported external system financial variables.
    """
    _name = 'hr.payslip.input'
    _description = 'Variable Payslip Financial Input'
    _order = 'sequence, id'

    payslip_id = fields.Many2one(
        'hr.payslip',
        string='Payslip',
        required=True,
        ondelete='cascade',
        index=True
    )
    name = fields.Char(string='Description', required=True)
    code = fields.Char(string='Code', required=True, index=True)
    sequence = fields.Integer(string='Sequence', default=10)
    amount = fields.Float(string='Amount (ETB)', digits=(16, 2), default=0.0)
    contract_id = fields.Many2one('hr.version', string='Contract / Version')
    input_type = fields.Selection([
        ('manual', 'Manual Entry'),
        ('attendance', 'Attendance Payload Ingestion'),
        ('discipline', 'Disciplinary Penalty Ingestion'),
        ('separation', 'Separation Clearance Ingestion'),
        ('retroactive', 'Retroactive Adjustment'),
    ], string='Source Type', default='manual', required=True)
    note = fields.Text(string='Reference & Remarks')
