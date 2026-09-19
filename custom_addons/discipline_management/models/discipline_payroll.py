# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class DisciplinePayrollPenalty(models.Model):
    _name = 'discipline.payroll.penalty'
    _description = 'Disciplinary Payroll Salary Penalty Deduction'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'effective_date desc, id desc'

    name = fields.Char(string='Penalty Reference', compute='_compute_name', store=True)
    case_id = fields.Many2one('discipline.case', string='Disciplinary Case', required=True, ondelete='cascade', tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    penalty_percentage = fields.Float(string='Penalty Deduction (%)', required=True, tracking=True)
    calculated_amount = fields.Float(string='Calculated Amount (ETB)', compute='_compute_calculated_amount', store=True)
    
    effective_date = fields.Date(string='Effective Penalty Date', required=True, default=fields.Date.context_today, tracking=True)
    state = fields.Selection([
        ('pending', 'Pending Transmission'),
        ('transferred', 'Transmitted to Payroll'),
        ('deducted', 'Deducted in Payslip'),
        ('cancelled', 'Cancelled / Waived'),
    ], string='Status', default='pending', required=True, tracking=True)

    payslip_reference = fields.Char(string='Payslip Ref / ID', tracking=True)
    notes = fields.Text(string='Integration Notes')

    @api.depends('case_id.name', 'employee_id.name')
    def _compute_name(self):
        for rec in self:
            if rec.case_id and rec.employee_id:
                rec.name = _('PENALTY/%s/%s') % (rec.case_id.name, rec.employee_id.name)
            else:
                rec.name = _('PENALTY/NEW')

    @api.depends('employee_id', 'penalty_percentage')
    def _compute_calculated_amount(self):
        for rec in self:
            # Estimate based on employee basic wage if contract exists
            contract = self.env['hr.contract'].search([
                ('employee_id', '=', rec.employee_id.id),
                ('state', '=', 'open')
            ], limit=1)
            wage = contract.wage if contract else 0.0
            rec.calculated_amount = (wage * rec.penalty_percentage) / 100.0

    def action_transmit_to_payroll(self):
        """FR-DIS-023: Transmit penalty deduction data to Payroll."""
        for rec in self:
            rec.write({'state': 'transferred'})
            rec.case_id.message_post(body=_('Penalty deduction payload of %s%% transmitted to Payroll for %s.') % (rec.penalty_percentage, rec.employee_id.name))

    def action_mark_deducted(self):
        for rec in self:
            rec.write({'state': 'deducted'})
