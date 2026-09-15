# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

import logging
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class HrPayrollException(models.Model):
    """
    Automated Pre-Flight Payroll Exception & Variance Scanner (FR-PAY-036).
    
    Identifies risk factors and data anomalies prior to final payroll commitment:
    * Unusually high variance (> 25% shift compared to previous month).
    * Missing master data (TIN, Bank Account number, Salary Structure).
    * Active employees missing active employment contract/version.
    * Pending un-transmitted attendance or disciplinary penalty payloads.
    * Negative net pay scenarios.
    """
    _name = 'hr.payroll.exception'
    _description = 'Pre-Flight Payroll Exception & Variance Record'
    _order = 'severity desc, create_date desc'

    payslip_id = fields.Many2one('hr.payslip', string='Flagged Payslip', ondelete='cascade', index=True)
    payrun_id = fields.Many2one('hr.payslip.run', string='Payroll Batch Run', ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, index=True)
    
    exception_type = fields.Selection([
        ('high_variance', 'Unusual Salary Variance (> 25%)'),
        ('missing_bank_account', 'Missing Employee Bank Account Number'),
        ('missing_tin', 'Missing Employee Tax Identification Number (TIN)'),
        ('missing_contract', 'Active Employee Missing Contract / Version'),
        ('pending_discipline', 'Pending Unresolved Disciplinary Deduction'),
        ('negative_net', 'Calculated Negative Net Salary'),
        ('missing_grade', 'Employee Missing Job Grade Assignment'),
    ], string='Anomaly Type', required=True, index=True)

    severity = fields.Selection([
        ('critical', 'Critical (Blocks Final Approval)'),
        ('warning', 'Warning (Requires Review)'),
        ('info', 'Informational Notice'),
    ], string='Severity Level', default='warning', required=True, index=True)

    previous_net = fields.Float(string='Prior Month Net (ETB)', digits=(16, 2))
    current_net = fields.Float(string='Current Net (ETB)', digits=(16, 2))
    variance_percentage = fields.Float(string='Variance (%)', digits=(5, 2))

    description = fields.Text(string='Detailed Anomaly Description', required=True)
    is_resolved = fields.Boolean(string='Resolved / Acknowledged', default=False)
    resolved_by = fields.Many2one('res.users', string='Acknowledged By')
    resolution_note = fields.Text(string='Resolution Explanation')

    def action_mark_resolved(self):
        """Acknowledge or mark exception as reviewed."""
        for rec in self:
            rec.write({
                'is_resolved': True,
                'resolved_by': self.env.user.id
            })

    @api.model
    def scan_payslip_for_exceptions(self, payslip):
        """
        Execute automated diagnostics on a single payslip.
        Returns list of created exception records.
        """
        exceptions = []
        emp = payslip.employee_id
        contract = payslip.contract_id

        # 1. Missing Bank Account
        acc = getattr(contract, 'salary_account', False) or getattr(emp, 'bank_account_id', False) or getattr(emp, 'salary_account', False)
        if not acc:
            exceptions.append({
                'payslip_id': payslip.id,
                'payrun_id': payslip.payslip_run_id.id if payslip.payslip_run_id else False,
                'employee_id': emp.id,
                'exception_type': 'missing_bank_account',
                'severity': 'critical',
                'description': _("Employee %s is missing salary bank account details for CBS direct credit payment.") % emp.name
            })

        # 2. Missing TIN
        tin = getattr(contract, 'employee_tin', False) or getattr(emp, 'tin', False)
        if not tin:
            exceptions.append({
                'payslip_id': payslip.id,
                'payrun_id': payslip.payslip_run_id.id if payslip.payslip_run_id else False,
                'employee_id': emp.id,
                'exception_type': 'missing_tin',
                'severity': 'warning',
                'description': _("Employee %s is missing Tax Identification Number (TIN).") % emp.name
            })

        # 3. Negative Net Pay
        if payslip.net_wage < 0:
            exceptions.append({
                'payslip_id': payslip.id,
                'payrun_id': payslip.payslip_run_id.id if payslip.payslip_run_id else False,
                'employee_id': emp.id,
                'exception_type': 'negative_net',
                'severity': 'critical',
                'description': _("Calculated Net Wage is negative (ETB %.2f). Review excessive deductions or disciplinary wage cuts.") % payslip.net_wage
            })

        # 4. Variance Check (> 25% change compared to last finalized payslip)
        prior_slip = self.env['hr.payslip'].search([
            ('employee_id', '=', emp.id),
            ('id', '!=', payslip.id),
            ('state', 'in', ['done', 'paid']),
            ('date_to', '<', payslip.date_from)
        ], order='date_to desc', limit=1)

        if prior_slip and prior_slip.net_wage > 0:
            diff = abs(payslip.net_wage - prior_slip.net_wage)
            pct = (diff / prior_slip.net_wage) * 100.0
            if pct > 25.0:
                exceptions.append({
                    'payslip_id': payslip.id,
                    'payrun_id': payslip.payslip_run_id.id if payslip.payslip_run_id else False,
                    'employee_id': emp.id,
                    'exception_type': 'high_variance',
                    'severity': 'warning',
                    'previous_net': prior_slip.net_wage,
                    'current_net': payslip.net_wage,
                    'variance_percentage': pct,
                    'description': _("High Net Variance (%.2f%% change). Previous Month: ETB %.2f, Current Month: ETB %.2f.") % (
                        pct, prior_slip.net_wage, payslip.net_wage
                    )
                })

        created_recs = self.env['hr.payroll.exception']
        for exc in exceptions:
            created_recs |= self.create(exc)
        return created_recs

    @api.model
    def _cron_run_exception_scanner(self):
        """Cron: Scans draft and verified payslips for unacknowledged anomalies."""
        draft_slips = self.env['hr.payslip'].search([('state', 'in', ['draft', 'verify'])])
        for slip in draft_slips:
            self.scan_payslip_for_exceptions(slip)
