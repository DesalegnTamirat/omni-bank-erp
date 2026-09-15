# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _


class HrPayrollAuditLog(models.Model):
    """
    Immutable Payroll Transaction Audit Ledger.
    
    Provides bank auditors, regulatory inspectors, and executive leadership with an unalterable,
    comprehensive chronological journal of all payroll adjustments, retroactive calculations,
    acting approvals, disciplinary deductions, and cut-off overrides.
    """
    _name = 'hr.payroll.audit.log'
    _description = 'Immutable Payroll Transaction Audit Ledger'
    _order = 'timestamp desc, id desc'

    timestamp = fields.Datetime(string='Audit Timestamp', default=fields.Datetime.now, readonly=True, index=True)
    event_type = fields.Selection([
        ('payslip_computed', 'Payslip Computed / Recomputed'),
        ('payrun_verified', 'Payrun Verified (Sr Controller)'),
        ('payrun_approved', 'Payrun Approved (Division Manager)'),
        ('override_approved', 'Cut-Off Override Approved'),
        ('retroactive_applied', 'Retroactive Adjustment Injected'),
        ('discipline_deducted', 'Disciplinary Penalty Deducted'),
        ('acting_status_change', 'Acting Allowance State Transition'),
        ('gl_posted', 'General Ledger Journal Entry Posted'),
        ('cbs_exported', 'CBS Direct Credit Batch File Exported'),
    ], string='Event Category', required=True, readonly=True, index=True)

    model_name = fields.Char(string='Source Model', readonly=True)
    res_id = fields.Integer(string='Source Record ID', readonly=True)
    employee_id = fields.Many2one('hr.employee', string='Affected Employee', readonly=True, index=True)
    
    initiator_id = fields.Many2one('res.users', string='Initiator / Operator', readonly=True)
    approver_id = fields.Many2one('res.users', string='Approver / Authorizer', readonly=True)
    
    previous_value = fields.Text(string='Previous State / Value', readonly=True)
    new_value = fields.Text(string='New State / Value', readonly=True)
    
    ip_address = fields.Char(string='Origin IP Address', readonly=True)
    description = fields.Text(string='Transaction Audit Narrative', required=True, readonly=True)

    @api.model
    def log_event(self, event_type, description, employee=None, initiator=None, approver=None,
                  prev_val=None, new_val=None, model=None, res_id=None):
        """Standard logging interface for cross-module audit transactions."""
        return self.create({
            'event_type': event_type,
            'description': description,
            'employee_id': employee.id if employee else False,
            'initiator_id': initiator.id if initiator else self.env.user.id,
            'approver_id': approver.id if approver else False,
            'previous_value': str(prev_val) if prev_val is not None else False,
            'new_value': str(new_val) if new_val is not None else False,
            'model_name': model,
            'res_id': res_id,
        })
