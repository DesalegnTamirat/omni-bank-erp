# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

from odoo import api, models, _


class ReportPayrollSummary(models.AbstractModel):
    """QWeb Report Parser for Monthly Payroll Summary."""
    _name = 'report.payroll.report_payroll_summary'
    _description = 'Payroll Summary Report Parser'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['hr.payslip.run'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'hr.payslip.run',
            'docs': docs,
            'company': self.env.company,
        }


class ReportStatutoryTaxPension(models.AbstractModel):
    """QWeb Report Parser for Statutory Tax and Pension Schedules."""
    _name = 'report.payroll.report_statutory_tax_pension'
    _description = 'Statutory Tax and Pension Report Parser'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['hr.payslip.run'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'hr.payslip.run',
            'docs': docs,
            'company': self.env.company,
        }
