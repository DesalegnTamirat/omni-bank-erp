from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class ReslLoanReplacementWizard(models.TransientModel):
    _name = 'resl.loan.replacement.wizard'
    _description = 'Guarantor Replacement Wizard'

    loan_id = fields.Many2one(
        comodel_name='resl.loan', string='Loan', required=True
    )
    loan_employee_id = fields.Many2one(
        comodel_name='hr.employee', string='Borrower',
        related='loan_id.employee_id', readonly=True, store=False
    )
    # Single old guarantee (borrower flow)
    old_guarantee_id = fields.Many2one(
        'resl.loan.guarantee', string='Current Guarantor Line',
        domain="[('loan_id','=',loan_id)]",
    )
    # Multi old guarantees (HR flow)
    old_guarantee_ids = fields.Many2many(
        'resl.loan.guarantee', string='Current Guarantor Lines (HR)',
        domain="[('loan_id','=',loan_id)]",
    )
    guarantor_name = fields.Char(
        string='Current Guarantor', compute='_compute_guarantor_name'
    )
    # Not required at the database level on purpose: the dialog stays open after
    # the first replacement when a second guarantor is needed, and the field is
    # then cleared. The form view makes it required for the user, and
    # action_confirm checks it again.
    new_guarantor_id = fields.Many2one(
        'hr.employee', string='New Guarantor'
    )
    replacement_reason = fields.Text(string='Replacement Reason')
    manual_request = fields.Boolean(string='Manual Request', default=False)
    is_hr_action = fields.Boolean(string='HR Action', default=False)

    # Two-guarantor rule (same as Find Guarantor)
    notice = fields.Char(string='Notice', readonly=True)
    second_step = fields.Boolean(
        string='Second Guarantor Step', default=False,
        help="True once the first replacement guarantor was selected and a second "
             "one is still needed to cover the borrower's salary.",
    )
    candidate_note = fields.Char(
        string='Eligibility', compute='_compute_candidate_note',
        help="Eligibility of the employee picked as the new guarantor.",
    )
    cand_name = fields.Char(string='Employee Name', compute='_compute_candidate_note')
    cand_job_title = fields.Char(string='Job Title', compute='_compute_candidate_note')
    cand_is_eligible = fields.Boolean(string='Eligible', compute='_compute_candidate_note')
    # Replacement guarantor(s) already selected (shown above the candidate row,
    # exactly like the Find Guarantor dialog).
    sel1_name = fields.Char(compute='_compute_selected_rows')
    sel1_job_title = fields.Char(compute='_compute_selected_rows')
    sel1_note = fields.Char(compute='_compute_selected_rows')
    sel2_name = fields.Char(compute='_compute_selected_rows')
    sel2_job_title = fields.Char(compute='_compute_selected_rows')
    sel2_note = fields.Char(compute='_compute_selected_rows')
    selected_replacements = fields.Char(
        string='Already Selected', compute='_compute_selected_replacements',
    )

    @api.depends('old_guarantee_id', 'old_guarantee_ids')
    def _compute_guarantor_name(self):
        for rec in self:
            names = []
            if rec.old_guarantee_id and rec.old_guarantee_id.guarantor_id:
                names.append(rec.old_guarantee_id.guarantor_id.name or '')
            for g in rec.old_guarantee_ids:
                if g.guarantor_id and g.guarantor_id.name:
                    names.append(g.guarantor_id.name)
            rec.guarantor_name = ', '.join(names) if names else ''

    @api.depends('old_guarantee_id', 'second_step')
    def _compute_selected_replacements(self):
        for rec in self:
            lines = rec.old_guarantee_id.sudo().replacement_line_ids.filtered(
                lambda l: l.state in ('draft', 'pending', 'accepted')
            )
            rec.selected_replacements = ', '.join(lines.mapped('guarantor_id.name')) or False

    @api.depends('old_guarantee_id', 'second_step', 'loan_id')
    def _compute_selected_rows(self):
        for rec in self:
            lines = list(rec.old_guarantee_id.sudo().replacement_line_ids.filtered(
                lambda l: l.active and l.state in ('draft', 'pending', 'accepted')
            ))
            needs_second = bool(rec.second_step)
            for idx, prefix in enumerate(('sel1', 'sel2')):
                line = lines[idx] if idx < len(lines) else False
                emp = line.guarantor_id.sudo() if line else False
                rec[prefix + '_name'] = emp.name if emp else False
                rec[prefix + '_job_title'] = (emp.job_title or '') if emp else False
                rec[prefix + '_note'] = (
                    (_("Selected - waiting for the second guarantor") if needs_second else _("Selected"))
                    if emp else False
                )

    @api.depends('new_guarantor_id', 'old_guarantee_id', 'loan_id')
    def _compute_candidate_note(self):
        """Eligibility of the picked employee, judged with the same rules (and
        the same 'as if the guarantor being replaced were gone' view) that are
        enforced when the replacement is confirmed."""
        Validations = self.env['resl.validations']
        for rec in self:
            note = False
            ok = False
            emp, loan, old = rec.new_guarantor_id, rec.loan_id, rec.old_guarantee_id
            if emp and loan and old:
                try:
                    v = Validations.with_context(resl_replacing_line_ids=old.ids)
                    ok, reason = v.guarantor_eligibility(loan, emp.sudo(), exclude_loan_id=loan.id)
                    if not ok:
                        note = reason
                    else:
                        # Same checks that the confirm step enforces.
                        try:
                            v.ensure_can_add_replacement(loan, old)
                        except ValidationError as e:
                            ok, note = False, e.args[0] if e.args else str(e)
                    if ok:
                        note = _("Eligible")
                        cov = v.guarantor_coverage(loan)
                        g_wage = float(loan._employee_current_wage(emp.sudo()) or 0.0)
                        if cov['borrower_wage'] and cov['total_wage'] + g_wage < cov['borrower_wage']:
                            note = _("Eligible, but you need to select another guarantor")
                except Exception:
                    _logger.exception("Eligibility hint failed for %s", emp.id)
                    note = False
                    ok = False
            rec.cand_name = emp.sudo().name if emp else False
            rec.cand_job_title = (emp.sudo().job_title or '') if emp else False
            rec.cand_is_eligible = bool(ok)
            rec.candidate_note = note

    def _reopen(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Replace Guarantor'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_confirm(self):
        self.ensure_one()
        loan = self.loan_id
        new_emp = self.new_guarantor_id
        if not new_emp:
            raise ValidationError(_("Please select the new guarantor."))
        old_lines = self.old_guarantee_id
        if not old_lines:
            separated = loan.guarantor_line_ids.filtered(lambda l: l.state == 'separated')
            if len(separated) == 1:
                old_lines = separated
        if not old_lines and self.is_hr_action:
            old_lines = self.old_guarantee_ids
        if not old_lines:
            raise ValidationError(_("Please choose which guarantor you want to replace."))
        for old_line in old_lines:
            if old_line.loan_id.id != loan.id:
                raise ValidationError(_("The selected guarantor does not belong to this request."))

        ctx = dict(self.env.context or {})
        ctx.update({
            'default_is_hr_action': self.is_hr_action,
            'default_manual_request': self.manual_request,
        })
        # sudo: the permission was checked above; it lets read-only HO roles
        # (e.g. auditor / accountant) complete the replacement they are allowed to make.
        for old_line in old_lines:
            loan.sudo().with_context(**ctx).nominate_replacement(old_line.id, new_emp.id)

        # Log the replacement(s)
        log_obj = self.env['resl.loan.replacement.log'].sudo()
        for old_line in old_lines:
            try:
                log_obj.create({
                    'loan_id': loan.id,
                    'old_guarantor_id': old_line.guarantor_id.id,
                    'new_guarantor_id': new_emp.id,
                    'action_by': self.env.uid,
                    'is_hr_action': self.is_hr_action,
                    'reason': self.replacement_reason or '',
                })
            except Exception:
                _logger.exception("Failed to create replacement log entry")

        # Two-guarantor rule: when the guarantor just selected earns less than the
        # borrower, nothing was sent. KEEP THE DIALOG OPEN so the second
        # replacement guarantor can be picked straight away.
        loan.invalidate_recordset()
        loan.guarantor_line_ids.invalidate_recordset()
        if self.env['resl.validations'].guarantor_slot_state(loan) == 'needs_second':
            self.write({
                'notice': _(
                    "%s was selected, but you need to select another guarantor. "
                    "Select the second guarantor below; the request is sent to both "
                    "guarantors once they are both selected."
                ) % new_emp.name,
                'new_guarantor_id': False,
                'second_step': True,
            })
            return self._reopen()

        return {'type': 'ir.actions.act_window_close'}
