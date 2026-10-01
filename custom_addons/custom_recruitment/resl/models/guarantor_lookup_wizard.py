from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class ReslGuarantorLookup(models.TransientModel):
    _name = 'resl.guarantor.lookup'
    _description = 'Guarantor Employee Lookup Wizard'

    loan_id = fields.Many2one('resl.loan', string='Loan')
    query = fields.Char(string='Search Query')
    line_ids = fields.One2many(
        'resl.guarantor.lookup.line', 'wizard_id', string='Results'
    )

    def action_search(self):
        self.ensure_one()
        query = (self.query or '').strip()
        domain = [('active', '=', True)]
        if query:
            domain += ['|', ('name', 'ilike', query), ('job_title', 'ilike', query)]
        employees = self.env['hr.employee'].sudo().search(domain, limit=50)
        # Exclude the borrower. Normally that's loan_id.employee_id, but the
        # loan may not exist yet (a brand-new, unsaved request) — fall back
        # to the current user's own employee record, since create() would
        # default employee_id to exactly that once the loan is made.
        borrower_emp = (
            self.loan_id.employee_id if self.loan_id and self.loan_id.employee_id
            else self.env.user.employee_id
        )
        if borrower_emp:
            employees = employees.filtered(lambda e: e.id != borrower_emp.id)
        # Remove stale lines
        self.line_ids.unlink()

        # FR-RESL-007 / 18.2: evaluate EVERY candidate with the same rules that
        # are enforced when a guarantor is selected (permanent staff, active
        # contract, 3+ months service, retirement, disciplinary/suspension,
        # max 2 guarantees), so the requester sees who is eligible BEFORE
        # clicking "Select as Guarantor". Eligible people are listed first.
        Validations = self.env['resl.validations']
        loan = self.loan_id
        # A rejected (or replaced/separated) line no longer counts as
        # "already registered" — the employee can be found and re-selected
        # for the same request again. Only a draft/pending/accepted line
        # still blocks them from being picked a second time.
        taken_ids = set(
            loan.guarantor_line_ids.filtered(lambda l: l.state not in ('rejected', 'replaced', 'separated'))
            .mapped('guarantor_id').ids
        ) if loan else set()
        # One guarantor per request: once the request has an active guarantor,
        # nobody else can be added to it.
        has_active_guarantor = bool(loan and loan.guarantor_line_ids.filtered(
            lambda l: l.state not in ('replaced', 'separated', 'rejected')
        ))
        rows = []
        for emp in employees:
            if emp.id in taken_ids:
                ok, note = False, _("Already registered as a guarantor for this loan")
            elif has_active_guarantor:
                ok, note = False, _("This request already has a guarantor")
            elif loan:
                ok, note = Validations.guarantor_eligibility(loan, emp, exclude_loan_id=loan.id)
            else:
                ok, note = True, ""
            rows.append({
                'wizard_id': self.id,
                'employee_id': emp.id,
                'name': emp.name,
                'job_title': emp.job_title or '',
                'is_eligible': ok,
                'eligibility_note': _("Eligible") if ok else note,
            })
        rows.sort(key=lambda r: (not r['is_eligible'], (r['name'] or '').lower()))
        self.env['resl.guarantor.lookup.line'].create(rows)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'resl.guarantor.lookup',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_clear(self):
        self.ensure_one()
        self.line_ids.unlink()
        self.query = False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'resl.guarantor.lookup',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


class ReslGuarantorLookupLine(models.TransientModel):
    _name = 'resl.guarantor.lookup.line'
    _description = 'Guarantor Lookup Result Line'

    wizard_id = fields.Many2one('resl.guarantor.lookup', string='Wizard', ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', string='Employee', readonly=True)
    name = fields.Char(string='Employee Name', readonly=True)
    job_title = fields.Char(string='Job Title', readonly=True)
    is_eligible = fields.Boolean(string='Eligible', readonly=True)
    eligibility_note = fields.Char(string='Eligibility', readonly=True)

    def action_select(self):
        """Add selected employee as a guarantor on the linked loan.

        The loan may not exist yet: "Find Guarantor" is reachable from a
        brand-new, unsaved request (see the resl_find_guarantor_button
        widget), so wizard.loan_id can be empty. Nothing about the loan is
        user-entered before this point — employee_id defaults to the
        current user and every other field is computed — so creating it
        here with no values is exactly what clicking Save would have done.
        This is intentionally the ONLY place besides an explicit Save that
        turns the request into a real draft record.
        """
        self.ensure_one()
        wizard = self.wizard_id
        if not wizard or not self.employee_id:
            raise ValidationError(_("Wizard or loan context is missing."))

        loan = wizard.loan_id
        just_created = False
        if not loan:
            loan = self.env['resl.loan'].create({})
            just_created = True

        existing_line = loan.guarantor_line_ids.filtered(
            lambda l: l.guarantor_id == self.employee_id
        )
        # Only a still-active line (draft/pending/accepted) blocks re-selection.
        # A rejected (or replaced/separated) line for this employee doesn't —
        # they can be chosen again for the same request.
        active_existing = existing_line.filtered(
            lambda l: l.state not in ('rejected', 'replaced', 'separated')
        )
        if active_existing:
            raise ValidationError(_(
                "%s is already registered as a guarantor for this loan."
            ) % self.employee_id.name)

        # Full guarantor validation, raised to the user right here:
        # permanent staff (FR-RESL-007), active contract, 3+ months of service,
        # retirement, disciplinary/suspension status and the 2-guarantee limit.
        # A non-permanent guarantor gets the "must be permanent staff" error.
        # The same rules are also enforced on resl.loan.guarantee itself, so no
        # other route can bypass them.
        self.env['resl.validations'].ensure_guarantor_is_eligible(
            loan, self.employee_id, exclude_loan_id=loan.id
        )

        rejected_line = existing_line.filtered(lambda l: l.state == 'rejected')
        if rejected_line:
            # Reuse the old (rejected) line instead of creating a new one:
            # loan_id/guarantor_id together are unique, so a second row for
            # the same pair would violate that constraint. Reviving it back
            # to draft also keeps the full accept/reject history on one
            # record instead of losing it.
            rejected_line[0].sudo().write({'state': 'draft'})
        else:
            # Create guarantee line in draft state
            self.env['resl.loan.guarantee'].with_context(
                resl_allow_guarantee_create=True
            ).create({
                'loan_id': loan.id,
                'guarantor_id': self.employee_id.id,
                'state': 'draft',
            })

        # There is no separate "Request Guarantors" button anymore: picking
        # a guarantor here IS the request. Immediately run the same
        # validation/transition that button used to trigger — this flips
        # the freshly (re)created 'draft' line to 'pending', notifies the
        # guarantor, and moves the loan to 'guarantor_pending'. If this
        # raises (e.g. borrower no longer eligible), the whole selection is
        # rolled back and the error is shown to the user right here.
        loan.action_request_guarantors()

        # Always close the dialog itself here. Returning a fresh
        # act_window (target='main') directly from this button while the
        # "Find Guarantor" dialog is still open races with the web
        # client's own reload of the dialog's line_ids list: the dialog
        # gets torn down by the navigation while that reload is still in
        # flight, which is what throws "Component is destroyed". Instead,
        # pass the new loan's id back via `infos` and let
        # find_guarantor_button.js navigate to it in `onClose`, once the
        # dialog has actually finished closing.
        return {
            'type': 'ir.actions.act_window_close',
            'infos': {'new_loan_id': loan.id} if just_created else {},
        }