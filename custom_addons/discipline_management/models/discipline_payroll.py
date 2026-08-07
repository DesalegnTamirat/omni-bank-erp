# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class DisciplinePayrollPenalty(models.Model):
    _name = 'discipline.payroll.penalty'
    _description = 'Disciplinary Payroll Salary Penalty Deduction'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'effective_date desc, id desc'

    name = fields.Char(string='Penalty Reference', compute='_compute_name', store=True)
    case_id = fields.Many2one('discipline.case', string='Disciplinary Case', required=True, ondelete='cascade', tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)

    # DIS-9: Penalty can be a percentage OR a day-count (for suspension without pay)
    penalty_type = fields.Selection([
        ('percentage', 'Salary Percentage Deduction'),
        ('suspension_without_pay', 'Suspension Without Pay (Daily Rate)'),
        ('managerial', 'Managerial Day-Count Deduction'),
    ], string='Penalty Calculation Type', required=True, default='percentage', tracking=True,
        help='FR-DIS-019: Percentage deduction for warning penalties. '
             'FR-DIS-021: Daily deduction for suspension without pay. '
             'Managerial: deducts based on working day count authorised by management.')

    penalty_percentage = fields.Float(string='Penalty Deduction (%)', tracking=True)

    # DIS-9: For daily-rate based deductions
    suspension_id = fields.Many2one('discipline.suspension', string='Linked Suspension', tracking=True,
                                    help='FR-DIS-021: Link to the suspension record to auto-fill days.')
    suspension_days = fields.Integer(string='Suspension Days Without Pay', tracking=True)
    managerial_days = fields.Integer(string='Managerial Deduction Days', tracking=True,
                                    help='Days authorised by management for penalty (e.g. annual leave offset).')

    # DIS-9: Calculated amounts
    calculated_amount = fields.Float(
        string='Calculated Gross Deduction (ETB)',
        compute='_compute_calculated_amount',
        store=True,
        tracking=True
    )
    daily_rate = fields.Float(
        string='Daily Rate (ETB)',
        compute='_compute_daily_rate',
        store=True,
        help='Basic wage / 30 working days per policy.'
    )

    effective_date = fields.Date(string='Effective Penalty Date', required=True, default=fields.Date.context_today, tracking=True)
    state = fields.Selection([
        ('pending', 'Pending Transmission'),
        ('transferred', 'Transmitted to Payroll'),
        ('deducted', 'Deducted in Payslip'),
        ('cancelled', 'Cancelled / Waived'),
    ], string='Status', default='pending', required=True, tracking=True)

    payslip_reference = fields.Char(string='Payslip Ref / ID', tracking=True)
    notes = fields.Text(string='Integration Notes')

    @api.depends('case_id.name', 'employee_id.name', 'penalty_type')
    def _compute_name(self):
        type_labels = {
            'percentage': 'PCT',
            'suspension_without_pay': 'SWP',
            'managerial': 'MGR',
        }
        for rec in self:
            if rec.case_id and rec.employee_id:
                label = type_labels.get(rec.penalty_type, 'PEN')
                rec.name = 'PENALTY/%s/%s/%s' % (label, rec.case_id.name, rec.employee_id.name)
            else:
                rec.name = 'PENALTY/NEW'

    def _get_employee_wage(self):
        """Helper: return current active contract basic wage, or 0."""
        self.ensure_one()
        contract = self.env['hr.contract'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'open'),
        ], limit=1)
        return contract.wage if contract else 0.0

    @api.depends('employee_id', 'penalty_percentage', 'penalty_type', 'suspension_days', 'managerial_days')
    def _compute_daily_rate(self):
        for rec in self:
            if not rec.employee_id:
                rec.daily_rate = 0.0
                continue
            wage = rec._get_employee_wage()
            # FR-DIS-021: Bank policy assumes 30 working days per calendar month
            rec.daily_rate = wage / 30.0 if wage else 0.0

    @api.depends('employee_id', 'penalty_percentage', 'penalty_type',
                 'suspension_days', 'managerial_days', 'daily_rate')
    def _compute_calculated_amount(self):
        for rec in self:
            if not rec.employee_id:
                rec.calculated_amount = 0.0
                continue
            wage = rec._get_employee_wage()
            if rec.penalty_type == 'percentage':
                # Standard % of gross monthly basic wage
                rec.calculated_amount = (wage * rec.penalty_percentage) / 100.0
            elif rec.penalty_type == 'suspension_without_pay':
                # DIS-9 / FR-DIS-021: days × daily_rate
                rec.calculated_amount = (rec.suspension_days or 0) * rec.daily_rate
            elif rec.penalty_type == 'managerial':
                # DIS-9: HR-authorised day count × daily_rate
                rec.calculated_amount = (rec.managerial_days or 0) * rec.daily_rate
            else:
                rec.calculated_amount = 0.0

    @api.onchange('suspension_id')
    def _onchange_suspension_id(self):
        """Auto-populate suspension days from linked suspension record."""
        if self.suspension_id:
            self.suspension_days = self.suspension_id.working_days_count
            self.penalty_type = 'suspension_without_pay'

    def action_transmit_to_payroll(self):
        """FR-DIS-023: Transmit penalty deduction data to Payroll."""
        for rec in self:
            if rec.calculated_amount <= 0:
                raise UserError(_('Calculated deduction amount is zero. Verify contract wage and penalty settings.'))
            rec.write({'state': 'transferred'})
            rec.case_id.message_post(
                body=_('Penalty deduction [%s] of ETB %.2f (%s) transmitted to Payroll for %s.') % (
                    rec.penalty_type, rec.calculated_amount, rec.penalty_percentage,
                    rec.employee_id.name
                )
            )

    def action_mark_deducted(self):
        for rec in self:
            if not rec.payslip_reference:
                raise UserError(_('Payslip Reference must be entered before marking as Deducted.'))
            rec.write({'state': 'deducted'})

    def action_cancel(self):
        for rec in self:
            if rec.state == 'deducted':
                raise UserError(_('Cannot cancel a penalty that has already been deducted from payslip.'))
            rec.write({'state': 'cancelled'})
            rec.case_id.message_post(body=_('Penalty deduction %s cancelled/waived.') % rec.name)

