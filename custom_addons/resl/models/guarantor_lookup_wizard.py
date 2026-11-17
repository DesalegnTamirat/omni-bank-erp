from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class ReslGuarantorLookup(models.TransientModel):
    _name = 'resl.guarantor.lookup'
    _description = 'Guarantor Employee Lookup Wizard'

    loan_id = fields.Many2one('resl.loan', string='Loan')
    employee_id = fields.Many2one(
        'hr.employee', string='Select Employee',
        help="Pick the employee you want as guarantor. He/she is added to the "
             "list below with the eligibility result; then click "
             "'Select as Guarantor'.",
    )
    borrower_id = fields.Many2one(
        'hr.employee', string='Borrower', compute='_compute_borrower_id',
        help="The requester. He/she cannot guarantee his/her own request.",
    )
    notice = fields.Char(string='Notice', readonly=True)
    pre_agreed = fields.Boolean(
        help="Opened from a New (unsaved) request whose Part A was already agreed. "
             "The request is created when the guarantor is selected.",
    )
    loan_created_here = fields.Boolean(
        help="True when this dialog itself created the (previously unsaved) request, "
             "so closing it must navigate to that request.",
    )
    # Guarantors ALREADY selected on this request (real lines, written by the
    # server). They stay listed while a second guarantor is being picked.
    line_ids = fields.One2many(
        'resl.guarantor.lookup.line', 'wizard_id', string='Selected Guarantors'
    )
    # The candidate currently picked in 'Select Employee' (computed, never
    # stored): shown on one line together with its own 'Select as Guarantor'
    # button.
    cand_name = fields.Char(string='Employee Name', compute='_compute_candidate')
    cand_job_title = fields.Char(string='Job Title', compute='_compute_candidate')
    cand_is_eligible = fields.Boolean(string='Eligible', compute='_compute_candidate')
    cand_note = fields.Char(string='Eligibility / Reason', compute='_compute_candidate')

    # Guarantor(s) already selected, exposed as plain fields so the view can draw
    # them in the SAME table (and row layout) as the candidate row, which carries
    # the real 'Select as Guarantor' button. At most two guarantors per request.
    sel1_name = fields.Char(compute='_compute_selected_rows')
    sel1_job_title = fields.Char(compute='_compute_selected_rows')
    sel1_note = fields.Char(compute='_compute_selected_rows')
    sel2_name = fields.Char(compute='_compute_selected_rows')
    sel2_job_title = fields.Char(compute='_compute_selected_rows')
    sel2_note = fields.Char(compute='_compute_selected_rows')

    @api.depends('line_ids', 'line_ids.name', 'line_ids.job_title',
                 'line_ids.eligibility_note')
    def _compute_selected_rows(self):
        for wiz in self:
            lines = list(wiz.line_ids)
            for idx, prefix in enumerate(('sel1', 'sel2')):
                line = lines[idx] if idx < len(lines) else False
                wiz[prefix + '_name'] = line.name if line else False
                wiz[prefix + '_job_title'] = line.job_title if line else False
                wiz[prefix + '_note'] = line.eligibility_note if line else False

    @api.depends('employee_id', 'loan_id')
    def _compute_candidate(self):
        for wiz in self:
            if wiz.employee_id:
                row = wiz._build_row(wiz.employee_id.sudo())
                wiz.cand_name = row['name']
                wiz.cand_job_title = row['job_title']
                wiz.cand_is_eligible = row['is_eligible']
                wiz.cand_note = row['eligibility_note']
            else:
                wiz.cand_name = False
                wiz.cand_job_title = False
                wiz.cand_is_eligible = False
                wiz.cand_note = False

    def _selected_rows(self, loan=None):
        """Line values for the guarantors already on the request."""
        loan = loan or self.loan_id
        if not loan:
            return []
        lines = loan.sudo().guarantor_line_ids.filtered(
            lambda l: l.active and l.state not in ('rejected', 'replaced', 'separated')
            # a guarantor that is being replaced is not one of the selected ones
            and not l.is_superseded
        )
        needs_second = self.env['resl.validations'].guarantor_slot_state(loan) == 'needs_second'
        note = (
            _("Selected - waiting for the second guarantor") if needs_second
            else _("Selected")
        )
        return [{
            'employee_id': l.guarantor_id.id,
            'name': l.guarantor_id.name,
            'job_title': l.guarantor_id.job_title or '',
            'is_eligible': True,
            'eligibility_note': note,
        } for l in lines]

    def _refresh_selected_lines(self):
        """Rebuild the 'already selected' lines from the request."""
        self.ensure_one()
        self.line_ids.unlink()
        rows = self._selected_rows()
        if rows:
            self.write({'line_ids': [(0, 0, r) for r in rows]})

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # Re-opened on a request that already has a guarantor (e.g. one is
        # still missing): list it straight away.
        loan_id = res.get('loan_id') or self.env.context.get('default_loan_id')
        if loan_id:
            loan = self.env['resl.loan'].browse(loan_id).exists()
            if 'line_ids' in fields_list:
                rows = self._selected_rows(loan) if loan else []
                if rows:
                    res['line_ids'] = [(0, 0, r) for r in rows]
        return res

    @api.depends('loan_id')
    def _compute_borrower_id(self):
        # Normally loan_id.employee_id, but the loan may not exist yet (a
        # brand-new, unsaved request) - fall back to the current user's own
        # employee record, since create() would default employee_id to
        # exactly that once the loan is made.
        for wiz in self:
            wiz.borrower_id = (
                wiz.loan_id.employee_id if wiz.loan_id and wiz.loan_id.employee_id
                else self.env.user.employee_id
            )

    def _build_row(self, emp):
        """Eligibility row for ONE candidate, judged with the same rules that
        are enforced when a guarantor is selected (FR-RESL-007 / 18.2:
        permanent staff, active contract, 3+ months service, retirement,
        disciplinary/suspension, max 2 guarantees)."""
        self.ensure_one()
        Validations = self.env['resl.validations']
        loan = self.loan_id
        borrower_emp = (
            loan.employee_id if loan and loan.employee_id else self.env.user.employee_id
        )
        # A rejected (or replaced/separated) line no longer counts as
        # "already registered": the employee can be re-selected for the same
        # request. Only a draft/pending/accepted line still blocks.
        taken_ids = set(
            loan.guarantor_line_ids.filtered(
                lambda l: l.state not in ('rejected', 'replaced', 'separated')
            ).mapped('guarantor_id').ids
        ) if loan else set()
        # One guarantor per request, unless a second is needed to cover the
        # borrower's salary (see guarantor_slot_state): once "full", nobody
        # else can be added.
        has_active_guarantor = bool(
            loan and Validations.guarantor_slot_state(loan) == 'full'
        )
        virtual_loan = (
            self.env['resl.loan'].new({'employee_id': borrower_emp.id})
            if (not loan and borrower_emp) else False
        )
        if borrower_emp and emp.id == borrower_emp.id:
            ok, note = False, _("The requester cannot be his/her own guarantor")
        elif emp.id in taken_ids:
            ok, note = False, _("Already registered as a guarantor for this loan")
        elif has_active_guarantor:
            ok, note = False, _("This request already has a guarantor")
        elif loan:
            ok, note = Validations.guarantor_eligibility(loan, emp, exclude_loan_id=loan.id)
        elif virtual_loan:
            # Brand-new, unsaved request: judge the candidate against an
            # in-memory loan for the borrower so the same rules (salary,
            # service, contract...) show up right after picking the employee.
            try:
                ok, note = Validations.guarantor_eligibility(virtual_loan, emp)
            except Exception:
                _logger.exception("Eligibility check failed for %s on a new request", emp.id)
                ok, note = True, ""
        else:
            ok, note = True, ""
        eligible_note = _("Eligible")
        if ok and not has_active_guarantor:
            # Two-guarantor rule: if choosing this person means the request
            # will need a second guarantor, say so right in the list. Worded
            # neutrally on purpose: no salary figures shown.
            ref_loan = loan or virtual_loan
            if ref_loan and borrower_emp and not (
                loan and Validations.guarantor_slot_state(loan) == 'needs_second'
            ):
                b_wage = float(ref_loan._employee_current_wage(borrower_emp.sudo()) or 0.0)
                g_wage = float(ref_loan._employee_current_wage(emp.sudo()) or 0.0)
                if b_wage and g_wage < b_wage:
                    eligible_note = _("Eligible, but you need to select another guarantor")
        return {
            'employee_id': emp.id,
            'name': emp.name,
            'job_title': emp.job_title or '',
            'is_eligible': ok,
            'eligibility_note': eligible_note if ok else note,
        }

    def action_select_guarantor(self):
        """Footer button: make the employee chosen in 'Select Employee' the
        guarantor of the request."""
        self.ensure_one()
        if not self.employee_id:
            raise ValidationError(_("Please select an employee first."))
        return self._select_employee(self.employee_id)

    def _select_employee(self, employee):
        """Add `employee` as a guarantor on the linked loan.

        The loan may not exist yet: "Find Guarantor" is reachable from a
        brand-new, unsaved request (see the resl_find_guarantor_button
        widget), so self.loan_id can be empty. Nothing about the loan is
        user-entered before this point - employee_id defaults to the current
        user and every other field is computed - so creating it here with no
        values is exactly what clicking Save would have done. This is
        intentionally the ONLY place besides an explicit Save that turns the
        request into a real draft record.
        """
        self.ensure_one()
        wizard = self
        employee = employee.sudo()

        loan = wizard.loan_id
        if not loan:
            # New form: picking a guarantor creates the draft request
            # (same as pressing Save would).
            loan = self.env['resl.loan'].create({
                'custom_saved': True,
            })
            wizard.write({'loan_id': loan.id, 'loan_created_here': True})

        # Picking a guarantor IS the save: a request the web client auto-saved
        # earlier (custom_saved False) becomes a real request now.
        if not loan.custom_saved:
            loan.sudo().write({'custom_saved': True})

        # A line the requester deleted earlier is only flagged (del_flag), so
        # it is revived below instead of duplicated.
        existing_line = loan.with_context(active_test=False).guarantor_line_ids.filtered(
            lambda l: l.guarantor_id == employee
        )
        # Only a still-active line (draft/pending/accepted) blocks re-selection.
        # A rejected (or replaced/separated) line for this employee doesn't.
        active_existing = existing_line.filtered(
            lambda l: l.active and l.state not in ('rejected', 'replaced', 'separated')
        )
        if active_existing:
            raise ValidationError(_(
                "%s is already registered as a guarantor for this loan."
            ) % employee.name)

        # Full guarantor validation, raised to the user right here: permanent
        # staff (FR-RESL-007), active contract, 3+ months of service,
        # retirement, disciplinary/suspension status and the 2-guarantee
        # limit. The same rules are also enforced on resl.loan.guarantee
        # itself, so no other route can bypass them.
        # One guarantor, or two when the first one's salary alone does not
        # cover the borrower (never more). Checked here too because a rejected
        # line is revived below without going through create().
        self.env['resl.validations'].ensure_can_add_guarantor(loan)
        self.env['resl.validations'].ensure_guarantor_is_eligible(
            loan, employee, exclude_loan_id=loan.id
        )

        # Any old line that is not live (rejected, replaced, separated or
        # soft-deleted) is reused: loan_id/guarantor_id together are unique.
        # Reviving it also keeps the full accept/reject history on one record.
        rejected_line = existing_line - active_existing
        if rejected_line:
            rejected_line[0].sudo().write({
                'state': 'draft', 'active': True,
                'replaced_by_id': False, 'replaced_at': False,
            })
        else:
            self.env['resl.loan.guarantee'].with_context(
                resl_allow_guarantee_create=True
            ).create({
                'loan_id': loan.id,
                'guarantor_id': employee.id,
                'state': 'draft',
            })

        # Picking a guarantor here IS the request: run the same validation /
        # transition the old "Request Guarantors" button triggered (flips the
        # draft line to 'pending', notifies the guarantor and moves the loan
        # to 'guarantor_pending'). If this raises, the whole selection is
        # rolled back and the error is shown right here.
        loan.action_request_guarantors()

        # Two-guarantor rule: when the guarantor just selected earns less than
        # the borrower, nothing was sent. KEEP THE DIALOG OPEN so the requester
        # can pick the second guarantor straight away, and tell them so.
        loan.invalidate_recordset()
        if self.env['resl.validations'].guarantor_slot_state(loan) == 'needs_second':
            wizard.notice = _(
                "%s was added, but you need to select another guarantor. "
                "Select the second guarantor below; the request is sent to both "
                "guarantors once they are both selected."
            ) % employee.name
            wizard.employee_id = False
            wizard._refresh_selected_lines()
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'resl.guarantor.lookup',
                'res_id': wizard.id,
                'view_mode': 'form',
                'target': 'new',
            }

        wizard.notice = False
        # Always close the dialog itself here. Returning a fresh act_window
        # directly from this button while the dialog is still open races with
        # the web client's own reload of the dialog ("Component is
        # destroyed"). Pass the new loan's id back via `infos` instead and let
        # find_guarantor_button.js navigate to it in `onClose`.
        return {
            'type': 'ir.actions.act_window_close',
            'infos': {'new_loan_id': loan.id} if wizard.loan_created_here else {},
        }

    def action_close(self):
        """Close the dialog. If this dialog created the request (it was opened
        from an unsaved 'New' form), hand its id back so the form behind it
        navigates to the real record instead of staying on 'New'."""
        self.ensure_one()
        infos = {'new_loan_id': self.loan_id.id} if (self.loan_created_here and self.loan_id) else {}
        return {'type': 'ir.actions.act_window_close', 'infos': infos}

    def action_clear(self):
        self.ensure_one()
        # Only resets the picked candidate; guarantors already selected stay.
        self.employee_id = False
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
    # Not readonly on purpose: these rows are created by the wizard's onchange
    # (employee picked in the dropdown) and the web client does not send
    # readonly fields back when it saves. The list shows them read-only.
    employee_id = fields.Many2one('hr.employee', string='Employee')
    name = fields.Char(string='Employee Name')
    job_title = fields.Char(string='Job Title')
    is_eligible = fields.Boolean(string='Eligible')
    eligibility_note = fields.Char(string='Eligibility')

    def action_select(self):
        """Row button kept for compatibility: same as the footer button."""
        self.ensure_one()
        if not self.wizard_id or not self.employee_id:
            raise ValidationError(_("Wizard or loan context is missing."))
        return self.wizard_id._select_employee(self.employee_id)