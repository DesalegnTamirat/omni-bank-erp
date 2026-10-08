import re
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

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
    # Read live from hr.version every time the wizard is (re)loaded — never
    # typed in by the user.
    od_account = fields.Char(
        string='Bank Account Number',
        compute='_compute_od_account',
        readonly=True,
        help="Core Banking account number stored on the employee's HR version (od_account).",
    )
    has_account = fields.Boolean(compute='_compute_od_account')

    # ── Helpers ───────────────────────────────────────────────────────────

    @api.model
    def _get_employee_version(self, loan):
        """Current hr.version of the loan's borrower (Odoo 19)."""
        return loan._get_latest_contract(loan.employee_id, sudo=True)

    @api.model
    def _read_od_account(self, loan):
        """Return the employee's od_account from hr_version, or False if empty.

        Read directly from the hr_version table (no ORM cache, no 'active'
        filter, no record rules) so it always matches what is in the database.
        Preference order:
          1. the version the employee currently points to
             (hr_employee.current_version_id),
          2. otherwise the most recent version of that employee that has a value.
        """
        employee = loan.employee_id.sudo()
        if not employee:
            return False
        self.env.cr.execute("""
            SELECT TRIM(v.od_account)
              FROM hr_version v
              JOIN hr_employee e ON e.id = v.employee_id
             WHERE v.employee_id = %s
               AND COALESCE(TRIM(v.od_account), '') <> ''
             ORDER BY (v.id = e.current_version_id) DESC,
                      v.date_version DESC NULLS LAST,
                      v.id DESC
             LIMIT 1
        """, (employee.id,))
        row = self.env.cr.fetchone()
        return (row[0] or '').strip() or False if row else False

    @api.depends('loan_id')
    def _compute_od_account(self):
        for wiz in self:
            account = wiz._read_od_account(wiz.loan_id) if wiz.loan_id else False
            wiz.od_account = account or False
            wiz.has_account = bool(account)

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        # Automatically bind to the loan that launched this wizard
        active_id = self.env.context.get('active_id') or self.env.context.get('default_loan_id')
        if active_id and 'loan_id' in fields_list:
            defaults['loan_id'] = active_id
        return defaults

    # ── Account opening (external API) ────────────────────────────────────

    def _call_account_opening_api(self, loan):
        """Open a new OD account on Core Banking and return its number.

        Endpoint, username and password come from the cbs_integration table
        (see resl.cbs.client).  Raises UserError with a readable message on
        failure.
        """
        return self.env['resl.cbs.client'].sudo().open_account(loan)

    def action_create_account(self):
        """Open a new bank account via the API, save it to hr.version.od_account,
        then reload the wizard so it shows the account and the Confirm button."""
        self.ensure_one()
        loan = self.loan_id
        if not loan._user_can_disburse(self.env.user):
            raise UserError(_("You are not the designated disbursement officer for this loan."))
        if self._read_od_account(loan):
            raise UserError(_("This employee already has an account."))

        account_number, created = self._call_account_opening_api(loan)
        account_number = (account_number or '').strip()
        if not account_number:
            raise UserError(_("The account opening service did not return an account number."))

        version = self._get_employee_version(loan)
        if not version or 'od_account' not in version._fields:
            raise UserError(_("Cannot save the account: the employee has no HR version with an od_account field."))
        version.sudo().write({'od_account': account_number})
        # New account: the opening call already set the sanction limit, so the
        # extend call is skipped at confirmation. Linked existing account: its
        # limit was not touched, so extend-od-limit is still required.
        loan.sudo().write({'cbs_limit_set': bool(created)})
        loan.sudo().message_post(body=(
            _("Bank account %(acc)s was opened for %(emp)s by %(user)s with a sanction limit of %(limit)s.") if created else
            _("%(emp)s already had an active account %(acc)s on Core Banking; it was linked "
              "to the employee record by %(user)s instead of opening a new one.")
        ) % {'acc': account_number, 'emp': loan.employee_id.name, 'user': self.env.user.name,
             'limit': '{:,.2f}'.format(self.env['resl.cbs.client'].sudo()._new_sanction_limit(loan)[0]) if created else ''})

        self.invalidate_recordset(['od_account', 'has_account'])
        # Re-open the same wizard record so the view refreshes.
        return {
            'type': 'ir.actions.act_window',
            'name': _('Confirm Core Banking Disbursement'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    # ── Disbursement ──────────────────────────────────────────────────────

    def action_confirm_disburse(self):
        """Disburse to the employee's od_account (read server-side from hr.version)."""
        self.ensure_one()
        loan = self.loan_id
        if not loan._user_can_disburse(self.env.user):
            raise ValidationError(_("You are not the designated disbursement officer for this loan."))
        if loan.status != 'approved':
            raise ValidationError(_("This loan is not ready for disbursement."))
        if not loan.disbursement_requested:
            if loan._live_disbursement_officer():
                loan.sudo().write({
                    'disbursement_requested': True,
                    'disbursement_requested_by_id': loan.sudo().approver_id.id or self.env.user.id,
                    'disbursement_requested_date': fields.Datetime.now(),
                })
            else:
                raise ValidationError(_("This loan is not ready for disbursement."))
        account_number = self._read_od_account(loan)
        if not account_number:
            raise ValidationError(_(
                'This employee has no bank account yet. Please create one first.'
            ))
        if not re.fullmatch(r'\d{%d}' % ACCOUNT_NUMBER_LENGTH, account_number):
            raise ValidationError(
                _('The Core Banking account number must be exactly %s digits.')
                % ACCOUNT_NUMBER_LENGTH
            )

        # Existing account: set / extend the OD sanction limit on Core Banking.
        # A newly opened account already got its limit in the open-account call
        # (cbs_limit_set), so nothing is sent here for it. Done before anything is
        # written locally: if CBS refuses, nothing is marked as disbursed.
        if not loan.cbs_limit_set:
            amount, wage, term = self.env['resl.cbs.client'].sudo().extend_od_limit(loan, account_number)
            loan.sudo().message_post(body=_(
                "New sanction limit %(amount)s (basic salary %(wage)s x %(term)s) set on account "
                "%(acc)s via Core Banking by %(user)s. Total loans taken so far: %(taken)s."
            ) % {'amount': '{:,.2f}'.format(amount), 'wage': '{:,.2f}'.format(wage), 'term': term,
                 'acc': account_number, 'user': self.env.user.name,
                 'taken': '{:,.2f}'.format(loan._employee_total_disbursed(loan.employee_id.sudo()) + (loan.approved_amount or 0.0))})

        # Store the account number on the loan record so it is permanently visible.
        loan.sudo().write({'bank_account_number': account_number})
        # Delegate to the loan's disbursement logic (status checks, message_post,
        # sibling recompute, and the success notification).
        return loan._do_disburse()