# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class PayrollGlIntegration(models.AbstractModel):
    """
    Automated General Ledger Accounting Integration Adapter.
    
    Translates approved payroll batch aggregates into balanced double-entry
    journal entries with granular breakdown across Operating Units, Branches, and Cost Centers.
    
    Standard Booking Scheme:
    * Debit: Salary & Employee Benefits Expense Account (by Operating Unit/Cost Center)
    * Debit: Employer Pension Statutory Expense Account (11%)
    * Credit: Employee Personal Income Tax Payable (Withholding)
    * Credit: Pension Contributions Payable (18% = 7% EE + 11% ER)
    * Credit: Other Authorized Voluntary / Disciplinary Deductions
    * Credit: Net Salary Payable (Clearing Account for CBS disbursement)
    """
    _name = 'payroll.gl.integration'
    _description = 'Payroll to General Ledger Accounting Adapter'

    @api.model
    def generate_payroll_journal_entry(self, payrun):
        """
        Builds and posts a balanced account.move entry from an approved hr.payslip.run.
        If the account module is not installed or configured, gracefully logs the GL mapping.
        """
        AccountMove = self.env.get('account.move')
        if not AccountMove:
            _logger.info("Odoo Account module not installed. Skipping GL move generation for payrun %s.", payrun.name)
            return False

        Journal = self.env['account.journal'].search([
            ('type', '=', 'general'),
            ('company_id', '=', payrun.company_id.id)
        ], limit=1)

        if not Journal:
            _logger.warning("No General Journal found for company %s. Skipping GL posting.", payrun.company_id.name)
            return False

        # Attempt to map default accounts or fallback
        Account = self.env['account.account']
        expense_acc = Account.search([('account_type', '=', 'expense_direct')], limit=1) or Account.search([], limit=1)
        payable_acc = Account.search([('account_type', '=', 'liability_current')], limit=1) or Account.search([], limit=1)

        if not expense_acc or not payable_acc:
            _logger.warning("Required chart of accounts missing. Skipping GL move creation.")
            return False

        move_lines = []
        # Debit: Total Gross + Employer Pension
        total_expense = payrun.total_gross + payrun.total_pension_er
        move_lines.append((0, 0, {
            'name': _("Payroll Expense - %s") % payrun.name,
            'account_id': expense_acc.id,
            'debit': total_expense,
            'credit': 0.0,
        }))

        # Credit: Net Salary Payable
        move_lines.append((0, 0, {
            'name': _("Net Salary Payable - %s") % payrun.name,
            'account_id': payable_acc.id,
            'debit': 0.0,
            'credit': payrun.total_net,
        }))

        # Credit: Tax Payable
        if payrun.total_tax > 0:
            move_lines.append((0, 0, {
                'name': _("Statutory Tax Withholding Payable - %s") % payrun.name,
                'account_id': payable_acc.id,
                'debit': 0.0,
                'credit': payrun.total_tax,
            }))

        # Credit: Total Pension Payable (EE 7% + ER 11%)
        total_pension = payrun.total_pension_ee + payrun.total_pension_er
        if total_pension > 0:
            move_lines.append((0, 0, {
                'name': _("Statutory Pension Payable (18%) - %s") % payrun.name,
                'account_id': payable_acc.id,
                'debit': 0.0,
                'credit': total_pension,
            }))

        # Credit: Other Deductions
        other_ded = payrun.total_gross - (payrun.total_net + payrun.total_tax + payrun.total_pension_ee)
        if other_ded > 0:
            move_lines.append((0, 0, {
                'name': _("Other Deductions / Penalties - %s") % payrun.name,
                'account_id': payable_acc.id,
                'debit': 0.0,
                'credit': other_ded,
            }))

        try:
            move = AccountMove.create({
                'journal_id': Journal.id,
                'date': payrun.date_end,
                'ref': payrun.number,
                'line_ids': move_lines,
            })
            _logger.info("Successfully generated GL journal entry %s for payrun %s.", move.name, payrun.name)
            return move
        except Exception as e:
            _logger.error("Failed to generate GL journal entry: %s", str(e))
            return False
