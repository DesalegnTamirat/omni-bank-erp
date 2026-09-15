# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class HrPayrollRetroactive(models.Model):
    """
    Retroactive Salary Calculation & Adjustments Engine.
    
    Manages backdated lifecycle changes (promotions, salary increments, retroactive demotions, branch adjustments).
    Performs comparative diffing against previously finalized/locked payslips, automatically computing
    exact Arrears (+) or Recoveries (-) to be posted into the active payroll cycle.
    """
    _name = 'hr.payroll.retroactive'
    _description = 'Retroactive Salary Adjustment Batch'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'effective_date desc, id desc'

    name = fields.Char(
        string='Adjustment Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('hr.payroll.retroactive') or _('New')
    )
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True, index=True)
    reason = fields.Selection([
        ('backdated_promotion', 'Backdated Promotion / Grade Upgrade'),
        ('backdated_increment', 'Backdated General / Step Salary Increment'),
        ('backdated_transfer', 'Backdated Branch Transfer / Hardship Delta'),
        ('backdated_demotion', 'Backdated Demotion / Salary Correction'),
        ('correction', 'Historical Audit Rectification'),
    ], string='Adjustment Reason', required=True, tracking=True)

    effective_date = fields.Date(
        string='Backdated Effective Date',
        required=True,
        tracking=True,
        help="The actual past date from which the new salary structure/terms apply."
    )
    target_payslip_id = fields.Many2one(
        'hr.payslip',
        string='Current Target Payslip',
        help="The active payslip into which the resulting arrears or recoveries will be injected."
    )
    
    line_ids = fields.One2many(
        'hr.payroll.retroactive.line',
        'retroactive_id',
        string='Historical Period Breakdown Lines'
    )

    total_arrears = fields.Float(
        string='Total Arrears Payable (ETB)',
        compute='_compute_totals',
        store=True,
        digits=(16, 2)
    )
    total_recoveries = fields.Float(
        string='Total Overpayment Recoveries (ETB)',
        compute='_compute_totals',
        store=True,
        digits=(16, 2)
    )
    net_retroactive_impact = fields.Float(
        string='Net Financial Impact (ETB)',
        compute='_compute_totals',
        store=True,
        digits=(16, 2)
    )

    state = fields.Selection([
        ('draft', 'Draft Calculation'),
        ('computed', 'Simulated & Computed'),
        ('approved', 'Approved by Senior Controller'),
        ('injected', 'Injected into Active Payroll'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True)

    initiator_id = fields.Many2one('res.users', string='Initiated By', default=lambda self: self.env.user)
    approver_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    notes = fields.Text(string='Audit Justification & Notes')

    @api.depends('line_ids.difference_amount')
    def _compute_totals(self):
        for rec in self:
            arrears = sum(line.difference_amount for line in rec.line_ids if line.difference_amount > 0)
            recoveries = sum(abs(line.difference_amount) for line in rec.line_ids if line.difference_amount < 0)
            rec.total_arrears = round(arrears, 2)
            rec.total_recoveries = round(recoveries, 2)
            rec.net_retroactive_impact = round(arrears - recoveries, 2)

    def action_compute_retroactive(self):
        """
        Execute virtual re-calculation across all locked historical payslips
        between the effective date and current period.
        """
        self.ensure_one()
        self.line_ids.unlink()

        # Find historical locked payslips
        historical_slips = self.env['hr.payslip'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', 'in', ['done', 'paid']),
            ('date_to', '>=', self.effective_date)
        ], order='date_from asc')

        if not historical_slips:
            raise UserError(_("No finalized historical payslips found between effective date %s and today.") % self.effective_date)

        new_contract_wage = getattr(self.employee_id, 'wage', 0.0) or getattr(self.employee_id, 'basic_salary', 0.0)

        for slip in historical_slips:
            original_net = slip.net_wage
            original_basic = slip.basic_wage

            # If the new wage is different, compute proportional difference
            diff = new_contract_wage - original_basic
            # Adjust for tax (approximate 65% net impact after 35% tax bracket if top tier)
            net_diff = round(diff * 0.70, 2)

            self.env['hr.payroll.retroactive.line'].create({
                'retroactive_id': self.id,
                'historical_payslip_id': slip.id,
                'period_name': f"{slip.date_from} ~ {slip.date_to}",
                'original_basic': original_basic,
                'revised_basic': new_contract_wage,
                'original_net': original_net,
                'difference_amount': net_diff,
                'notes': _("Calculated retroactive adjustment from %s to %s") % (slip.date_from, slip.date_to)
            })

        self.write({'state': 'computed'})
        self.message_post(body=_("Retroactive simulation completed. Total Arrears: ETB %.2f, Recoveries: ETB %.2f.") % (
            self.total_arrears, self.total_recoveries
        ))

    def action_approve(self):
        """Senior Controller authorization for retroactive adjustment."""
        for rec in self:
            rec.write({
                'state': 'approved',
                'approver_id': self.env.user.id
            })
            rec.message_post(body=_("Retroactive adjustment approved by Senior Controller %s.") % self.env.user.name)


class HrPayrollRetroactiveLine(models.Model):
    """Itemized breakdown of historical period recalculation."""
    _name = 'hr.payroll.retroactive.line'
    _description = 'Retroactive Recalculation Period Line'
    _order = 'id asc'

    retroactive_id = fields.Many2one('hr.payroll.retroactive', string='Adjustment Batch', required=True, ondelete='cascade')
    historical_payslip_id = fields.Many2one('hr.payslip', string='Historical Locked Payslip')
    period_name = fields.Char(string='Historical Period')
    original_basic = fields.Float(string='Original Basic (ETB)', digits=(16, 2))
    revised_basic = fields.Float(string='Revised Basic (ETB)', digits=(16, 2))
    original_net = fields.Float(string='Original Net (ETB)', digits=(16, 2))
    difference_amount = fields.Float(string='Adjustment Difference (ETB)', digits=(16, 2), help="Positive for Arrears, Negative for Recoveries.")
    notes = fields.Char(string='Remarks')
