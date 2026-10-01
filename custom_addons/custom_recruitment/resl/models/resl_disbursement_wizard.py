import re

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

ACCOUNT_NUMBER_LENGTH = 13


class ReslDisbursementWizard(models.TransientModel):
    _name = 'resl.loan.disbursement.wizard'
    _description = 'Core Banking Disbursement — Account Confirmation'

    loan_id = fields.Many2one(
        'resl.loan',
        string='Loan',
        required=True,
        readonly=True,
    )
    approved_amount = fields.Monetary(
        string='Approved Loan Amount',
        related='loan_id.approved_amount',
        currency_field='currency_id',
        readonly=True,
    )
    currency_id = fields.Many2one(
        related='loan_id.currency_id',
        readonly=True,
    )
    employee_name = fields.Char(
        string='Employee',
        related='loan_id.employee_id.name',
        readonly=True,
    )
    account_number = fields.Char(
        string='Bank Account Number',
        # Not required at the field/view level on purpose: a hard "required"
        # here makes Odoo run field validation on EVERY object button in
        # this form, including "I don't have an account" — which blocked
        # that link with a "Missing required fields" error before the user
        # ever had a chance to open the portal. Validation instead happens
        # explicitly in action_confirm_disburse below.
        help="Enter the employee's 13-digit Core Banking account number to disburse to.",
    )

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        # Automatically bind to the loan that launched this wizard
        active_id = self.env.context.get('active_id') or self.env.context.get('default_loan_id')
        if active_id and 'loan_id' in fields_list:
            defaults['loan_id'] = active_id
        return defaults

    def action_confirm_disburse(self):
        """Validate account number and trigger the actual disbursement."""
        self.ensure_one()
        account_number = (self.account_number or '').strip()
        if not account_number:
            raise ValidationError(_('Please enter the bank account number before disbursing.'))
        if not re.fullmatch(r'\d{%d}' % ACCOUNT_NUMBER_LENGTH, account_number):
            raise ValidationError(
                _('The Core Banking account number must be exactly %s digits.')
                % ACCOUNT_NUMBER_LENGTH
            )
        self.account_number = account_number

        loan = self.loan_id
        # Store the account number on the loan record so it is permanently visible.
        loan.sudo().write({'bank_account_number': self.account_number.strip()})
        # Delegate to the loan's disbursement logic (which handles all
        # status checks, message_post, sibling recompute, and the success
        # notification).
        return loan._do_disburse()

    def action_open_account_portal(self):
        """Open the Bunna Bank onboarding portal in a new browser tab.

        The wizard remains open so HR can return and enter the account
        number once the employee has completed registration.
        """
        return {
            'type': 'ir.actions.act_url',
            'url': 'https://onboardingportal.bunnabanksc.com/',
            'target': 'new',
        }