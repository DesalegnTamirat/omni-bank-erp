# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PayrollRetroactiveWizard(models.TransientModel):
    """
    Backdated Salary Retroactive Calculation Wizard.
    Facilitates comparative backdated recalculation against locked historical payslips.
    """
    _name = 'payroll.retroactive.wizard'
    _description = 'Generate Backdated Retroactive Adjustment'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    reason = fields.Selection([
        ('backdated_promotion', 'Backdated Promotion / Grade Upgrade'),
        ('backdated_increment', 'Backdated General / Step Salary Increment'),
        ('backdated_transfer', 'Backdated Branch Transfer / Hardship Delta'),
        ('backdated_demotion', 'Backdated Demotion / Salary Correction'),
        ('correction', 'Historical Audit Rectification'),
    ], string='Adjustment Reason', required=True, default='backdated_promotion')
    effective_date = fields.Date(string='Backdated Effective Date', required=True)
    notes = fields.Text(string='Justification & Background')

    def action_generate_retroactive(self):
        """Generate and compute retroactive adjustment batch."""
        self.ensure_one()
        retro = self.env['hr.payroll.retroactive'].create({
            'employee_id': self.employee_id.id,
            'reason': self.reason,
            'effective_date': self.effective_date,
            'notes': self.notes,
        })
        retro.action_compute_retroactive()
        return {
            'name': _('Retroactive Salary Adjustment'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payroll.retroactive',
            'res_id': retro.id,
            'view_mode': 'form',
            'target': 'current',
        }
