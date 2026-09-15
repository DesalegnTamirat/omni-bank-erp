# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PayrollCutoffOverrideWizard(models.TransientModel):
    """
    Cut-Off Override Submission Wizard (FR-PAY-030, 031).
    Allows HR Accountants to submit urgent late changes for locked periods.
    """
    _name = 'payroll.cutoff.override.wizard'
    _description = 'Submit Post-Cutoff Override Request'

    period_id = fields.Many2one('hr.payroll.period', string='Locked Pay Period', required=True)
    employee_id = fields.Many2one('hr.employee', string='Affected Employee', required=True)
    override_category = fields.Selection([
        ('late_joiner', 'Emergency Late Joiner Addition'),
        ('salary_adjustment', 'Critical Late Salary Adjustment'),
        ('disciplinary_correction', 'Urgent Disciplinary Deduction Rectification'),
        ('separation_payout', 'Expedited Separation Final Settlement'),
        ('other_exception', 'Other Executive Exceptional Override'),
    ], string='Override Category', required=True, default='salary_adjustment')

    financial_impact_estimate = fields.Float(string='Estimated Financial Impact (ETB)', digits=(16, 2), required=True)
    justification = fields.Text(string='Business Justification & Audit Rationale', required=True)

    def action_submit_override(self):
        """Create and submit formal override request."""
        self.ensure_one()
        override = self.env['hr.payroll.cutoff.override'].create({
            'period_id': self.period_id.id,
            'employee_id': self.employee_id.id,
            'override_category': self.override_category,
            'financial_impact_estimate': self.financial_impact_estimate,
            'justification': self.justification,
            'state': 'submitted',
        })
        return {
            'name': _('Cut-Off Override Request'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.payroll.cutoff.override',
            'res_id': override.id,
            'view_mode': 'form',
            'target': 'current',
        }
