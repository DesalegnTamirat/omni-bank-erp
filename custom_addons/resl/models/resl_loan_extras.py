# -*- coding: utf-8 -*-
"""Small additions on resl.loan:
  * newest requests first (by request date) in every list / kanban / search,
  * the requester is told when the loan has been disbursed.
"""
import logging

from odoo import _, fields, models

_logger = logging.getLogger(__name__)


class ReslLoanExtras(models.Model):
    _inherit = 'resl.loan'

    # newest request first; id desc breaks ties between requests of one day
    _order = 'request_date desc, id desc'

    def _do_disburse(self):
        was_disbursed = {loan.id: loan.sudo().core_banking_status == 'disbursed' for loan in self}
        res = super()._do_disburse()
        for loan in self:
            if not was_disbursed.get(loan.id) and loan.sudo().core_banking_status == 'disbursed':
                try:
                    loan._notify_requester_disbursed()
                except Exception:
                    # never undo a real disbursement because a notification failed
                    _logger.exception("Could not notify the requester of loan %s about the disbursement", loan.id)
        return res

    def _notify_requester_disbursed(self):
        """To-do + inbox/e-mail notification to the borrower."""
        self.ensure_one()
        loan = self.sudo()
        borrower_user = loan.employee_id.user_id
        if not borrower_user:
            return
        amount = '{:,.2f} {}'.format(loan.approved_amount or 0.0, loan.currency_id.name or '')
        account = (_(" to account %s") % loan.bank_account_number) if loan.bank_account_number else ''
        body = _("Your loan %(loan)s has been disbursed: %(amount)s%(account)s on %(date)s.") % {
            'loan': loan.name, 'amount': amount, 'account': account,
            'date': loan.disbursement_date or fields.Date.context_today(loan),
        }
        loan.activity_schedule(
            'mail.mail_activity_data_todo',
            user_id=borrower_user.id,
            summary=_("Loan disbursed: %s") % loan.name,
            note=body,
        )
        if borrower_user.partner_id:
            loan.message_notify(
                partner_ids=[borrower_user.partner_id.id],
                subject=_("Loan %s disbursed") % loan.name,
                body=body,
            )
