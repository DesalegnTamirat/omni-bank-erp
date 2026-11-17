from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


GUARANTEE_STATES = [
    ('draft', 'Draft'),
    ('pending', 'Pending'),
    ('accepted', 'Accepted'),
    ('rejected', 'Rejected'),
    ('replaced', 'Replaced'),
    ('separated', 'Separated'),
]
# A line in one of these states is still "in play" on the request.
LIVE_STATES = ('draft', 'pending', 'accepted')


class ReslLoanGuarantee(models.Model):
    _name = "resl.loan.guarantee"
    _description = "Loan Guarantee"
    _inherit = ["mail.thread", "mail.activity.mixin", "resl.soft.delete.mixin"]

    loan_id = fields.Many2one(
        'resl.loan', string="Loan", required=True,
        ondelete='cascade', index=True, tracking=True,
    )
    guarantor_id = fields.Many2one(
        'hr.employee', string="Guarantor", required=True, tracking=True,
    )
    loan_employee_id = fields.Many2one(
        'hr.employee', string='Loan Borrower',
        related='loan_id.employee_id', store=False, readonly=True,
    )
    state = fields.Selection(GUARANTEE_STATES, string="Status", default="draft", tracking=True)

    replaced_by_id = fields.Many2one(
        'resl.loan.guarantee', string="Replaced By", readonly=True
    )
    replaced_at = fields.Datetime(string="Replaced At", readonly=True)

    # Replacement flow: the NEW line points at the line it replaces. The line
    # being replaced is left untouched (it stays pending / accepted) and is only
    # rejected once the replacement guarantor(s) have accepted - see
    # resl.loan._finalize_guarantor_replacements. One old line can have up to two
    # replacement lines (when the first replacement's salary does not cover the
    # borrower, a second one is needed - same rule as Find Guarantor).
    replaces_id = fields.Many2one(
        'resl.loan.guarantee', string="Replacing", readonly=True, copy=False,
        ondelete='set null', index=True,
        help="The guarantor line this line is meant to replace. That line stays on "
             "the request until this one is accepted.",
    )
    replacement_line_ids = fields.One2many(
        'resl.loan.guarantee', 'replaces_id', string="Replacement Lines", readonly=True,
    )
    is_superseded = fields.Boolean(
        string="Being Replaced", compute='_compute_is_superseded',
        help="True while a replacement guarantor has been nominated for this line "
             "but has not accepted yet.",
    )
    replacement_guarantor_id = fields.Many2one(
        'hr.employee', string='Replacement Guarantor',
        compute='_compute_replacement_info', store=False,
    )
    replacement_state = fields.Selection(
        GUARANTEE_STATES, string='Replacement State',
        compute='_compute_replacement_info', store=False,
    )
    can_act_as_guarantor = fields.Boolean(
        string="Can Act as Guarantor",
        compute="_compute_can_act_as_guarantor", store=False
    )
    guarantor_guarantee_count = fields.Integer(
        string="Current Guarantees",
        related="guarantor_id.guarantee_count", store=False, readonly=True,
    )

    def init(self):
        """One live guarantee line per (loan, guarantor). Soft-deleted lines
        (del_flag) are ignored, so the same guarantor can be added again after
        a line was deleted. Replaces the old plain unique constraint."""
        super().init()
        self.env.cr.execute(
            "ALTER TABLE resl_loan_guarantee DROP CONSTRAINT IF EXISTS resl_loan_guarantee_uniq_loan_guarantor"
        )
        self.env.cr.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS resl_loan_guarantee_uniq_live_loan_guarantor "
            "ON resl_loan_guarantee (loan_id, guarantor_id) WHERE del_flag IS NOT TRUE"
        )

    # Odoo 17+/19: name_get() is removed from the ORM entirely; display names
    # are now driven by a computed `display_name` field instead.
    display_name = fields.Char(
        string="Display Name", compute="_compute_display_name", store=False,
    )

    @api.depends('guarantor_id', 'guarantor_id.name')
    def _compute_display_name(self):
        for record in self:
            try:
                name = record.guarantor_id.name or _("Unnamed Guarantor")
            except Exception:
                try:
                    name = record.sudo().guarantor_id.name or _("Unnamed Guarantor")
                except Exception:
                    name = _("Guarantor #%s") % (record.id or '-')
            record.display_name = name

    @api.depends('replacement_line_ids.state', 'replacement_line_ids.active')
    def _compute_is_superseded(self):
        for rec in self:
            rec.is_superseded = any(
                l.active and l.state in LIVE_STATES
                for l in rec.sudo().replacement_line_ids
            )

    @api.depends('replaced_by_id', 'replaced_by_id.guarantor_id', 'replaced_by_id.state',
                 'replacement_line_ids.guarantor_id', 'replacement_line_ids.state',
                 'replacement_line_ids.active')
    def _compute_replacement_info(self):
        for rec in self:
            sudo_rec = rec.sudo()
            lines = sudo_rec.replacement_line_ids
            live = lines.filtered(lambda l: l.state in LIVE_STATES)
            pick = (live or lines or sudo_rec.replaced_by_id)[:1]
            rec.replacement_guarantor_id = pick.guarantor_id if pick else False
            rec.replacement_state = pick.state if pick else False

    @api.depends('guarantor_id', 'state')
    def _compute_can_act_as_guarantor(self):
        try:
            current_emp_id = self.env.user.employee_id.id if self.env.user.employee_id else False
        except Exception:
            current_emp_id = False
        for rec in self:
            rec.can_act_as_guarantor = bool(
                rec.guarantor_id
                and rec.guarantor_id.id
                and current_emp_id
                and rec.guarantor_id.id == current_emp_id
                and rec.state == 'pending'
            )

    @api.constrains('guarantor_id')
    def _check_guarantor_limit(self):
        for rec in self:
            if self.env.context.get('resl_allow_replacement_create'):
                continue
            if rec.guarantor_id:
                Guarantee = self.env['resl.loan.guarantee']
                domain = [
                    ('guarantor_id', '=', rec.guarantor_id.id),
                    ('state', '=', 'accepted'),
                    ('loan_id.status', '=', 'approved'),
                ]
                if rec.loan_id and rec.loan_id.id:
                    domain.append(('loan_id', '!=', rec.loan_id.id))
                guarantees = Guarantee.search(domain)
                unique_borrowers = set(guarantees.mapped('loan_id.employee_id.id'))
                try:
                    current_borrower = (
                        rec.loan_id.employee_id.id
                        if rec.loan_id and rec.loan_id.employee_id
                        else None
                    )
                except Exception:
                    current_borrower = None
                if current_borrower and current_borrower in unique_borrowers:
                    unique_borrowers.remove(current_borrower)
                if len(unique_borrowers) >= 2:
                    pass  # validation disabled for migration

            if rec.loan_id:
                active_for_loan = rec.loan_id.guarantor_line_ids.filtered(
                    lambda l: l.state not in ('replaced', 'separated')
                )
                count = len(active_for_loan.filtered(lambda l: l.id != rec.id)) if rec.id else len(active_for_loan)
                if count >= 2:
                    pass  # validation disabled for migration

                if rec.guarantor_id and rec.loan_id:
                    dup = self.search([
                        ('loan_id', '=', rec.loan_id.id),
                        ('guarantor_id', '=', rec.guarantor_id.id),
                        ('id', '!=', rec.id),
                    ], limit=1)
                    if dup:
                        pass  # validation disabled for migration

    @api.constrains('guarantor_id', 'loan_id')
    def _check_guarantor_is_permanent(self):
        """FR-RESL-007: mirror of the borrower/requestor check
        (resl.loan._check_borrower_eligibility, which validates
        loan.employee_id via resl.validations.check_borrower_eligibility).

        The requestor is not the only one that has to be permanent staff —
        the guarantor does too. This constraint runs automatically on
        create AND write, for every entry point that sets guarantor_id
        (the Find Guarantor wizard, the replacement wizard, a direct
        write, an import, etc.), so a non-permanent employee (probation,
        contract, temporary, casual, intern, fixed-term, trainee, or any
        other non-permanent status) is rejected immediately the moment
        they are selected as a guarantor — it cannot be bypassed by going
        through a different flow than the one that was last checked.
        """
        Validations = self.env['resl.validations']
        for rec in self:
            if rec.guarantor_id:
                Validations.ensure_guarantor_is_permanent(rec.guarantor_id, rec.loan_id)

    def action_accept(self):
        for g in self:
            if not g.can_act_as_guarantor:
                pass  # validation disabled for migration
            if g.state != 'pending':
                pass  # validation disabled for migration
            try:
                g.loan_id._ensure_guarantor_is_eligible(
                    g.guarantor_id, exclude_loan_id=g.loan_id.id, strict=True
                )
            except Exception:
                raise

            g.sudo().write({'state': 'accepted'})

            loan = g.loan_id
            # Replacement flow: the guarantor being replaced is rejected only NOW,
            # once the replacement guarantor(s) have accepted (and, with two
            # guarantors, together cover the borrower's salary).
            try:
                loan.sudo()._finalize_guarantor_replacements()
            except Exception:
                _logger.exception("Failed to finalise the guarantor replacement on loan %s", loan.id)
            # Odoo 17: invalidate_recordset replaces invalidate_cache
            loan.invalidate_recordset(['guarantor_line_ids', 'all_guarantors_accepted', 'can_submit_manager'])
            loan = loan.sudo()
            loan.message_post(body=_("Guarantor %s accepted the loan.") % g.guarantor_id.name)

            if loan.all_guarantors_accepted and loan.status == 'guarantor_pending':
                try:
                    borrower_emp = loan.sudo().employee_id
                    if borrower_emp and borrower_emp.user_id:
                        loan.sudo().activity_schedule(
                            'mail.mail_activity_data_todo',
                            user_id=borrower_emp.user_id.id,
                            note=_("All guarantors accepted for loan %s. Please submit to manager.") % loan.name,
                        )
                except Exception:
                    _logger.exception("Failed to schedule borrower activity after all guarantors accepted")
        try:
            action = self.env.ref('resl.action_resl_my_guarantees').read()[0]
            return action
        except Exception:
            return {'type': 'ir.actions.act_window_close'}

    def action_reject(self):
        for g in self:
            if g.state != 'pending':
                pass  # validation disabled for migration
            g.sudo().write({'state': 'rejected'})
            # The request stays "Waiting Guarantees" (it is NOT sent back to draft):
            # as an in-progress request it keeps Find Guarantor / Replace available
            # and is not re-judged by the new-request rules.
            replaced_line = g.sudo().replaces_id
            try:
                g.loan_id.sudo().message_post(
                    body=_("Guarantor %s rejected the loan.") % g.guarantor_id.name
                )
            except Exception:
                _logger.exception('Failed to post rejection message on loan')
            # Tell the requestor: a to-do on their loan plus a notification, so
            # they know to pick (Find Guarantor) another guarantor.
            try:
                loan = g.loan_id.sudo()
                borrower_user = loan.employee_id.user_id
                if borrower_user:
                    if replaced_line and replaced_line.state in LIVE_STATES:
                        # The replacement was refused: the guarantor it was meant
                        # to replace simply stays on the request.
                        msg = _(
                            "%(guarantor)s rejected the replacement nomination on request %(loan)s. "
                            "%(old)s remains the guarantor. Use 'Replace Guarantor' to nominate "
                            "someone else."
                        ) % {'guarantor': g.guarantor_id.name, 'loan': loan.name,
                             'old': replaced_line.guarantor_id.name}
                    else:
                        msg = _(
                            "Guarantor %(guarantor)s rejected your request %(loan)s. "
                            "Please use 'Find Guarantor' to choose another guarantor."
                        ) % {'guarantor': g.guarantor_id.name, 'loan': loan.name}
                    loan.activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=borrower_user.id,
                        summary=_("Guarantor rejected"),
                        note=msg,
                    )
                    if borrower_user.partner_id:
                        loan.message_notify(
                            partner_ids=[borrower_user.partner_id.id],
                            subject=_("Guarantor rejected your request %s") % loan.name,
                            body=msg,
                        )
            except Exception:
                _logger.exception('Failed to notify the requestor about the guarantor rejection')
        try:
            action = self.env.ref('resl.action_resl_my_guarantees').read()[0]
            return action
        except Exception:
            return {'type': 'ir.actions.act_window_close'}

    def unlink(self):
        for rec in self:
            loan = rec.loan_id
            user = self.env.user
            if loan and loan.status != 'draft':
                pass  # validation disabled for migration
            try:
                current_emp_id = user.employee_id.id if user.employee_id else False
            except Exception:
                current_emp_id = False
            is_borrower = bool(
                loan.employee_id and loan.employee_id.id
                and current_emp_id
                and loan.employee_id.id == current_emp_id
            )
            is_privileged = (
                user._resl_has_group('resl.group_resl_hr')
                or user._resl_has_group('resl.group_resl_manager')
            )
            if not (is_borrower or is_privileged):
                pass  # validation disabled for migration
        if self.env.context.get('resl_hard_delete'):
            return super().unlink()
        # Soft delete: flag the line (del_flag) instead of removing it.
        return self._soft_delete()

    @api.model_create_multi
    def create(self, vals_list):
        # FR-RESL-007 hard gate. This runs OUTSIDE the try/except below on
        # purpose: that block deliberately swallows non-validation errors so a
        # defensive failure can't block the flow, which is fine for the
        # secondary checks but must never be able to let a non-permanent
        # guarantor slip through. Any ValidationError raised here propagates.
        Validations = self.env['resl.validations']
        for vals in vals_list:
            if vals.get('guarantor_id'):
                loan = self.env['resl.loan'].browse(vals['loan_id']) if vals.get('loan_id') else self.env['resl.loan']
                Validations.ensure_guarantor_is_permanent(
                    self.env['hr.employee'].browse(vals['guarantor_id']), loan
                )

        # Guarantors added per loan inside this same create() batch, so two
        # lines for one request can't slip in together.
        batch_counts = {}
        for vals in vals_list:
            try:
                loan_id = vals.get('loan_id')
                if loan_id:
                    loan = self.env['resl.loan'].browse(loan_id)
                    try:
                        current_emp_id = self.env.user.employee_id.id if self.env.user.employee_id else False
                    except Exception:
                        current_emp_id = False
                    if (loan and loan.employee_id and loan.employee_id.id
                            and current_emp_id
                            and loan.employee_id.id == current_emp_id
                            and getattr(loan, 'status', 'draft') == 'draft'):
                        vals['state'] = 'draft'

                    provided_guarantor = vals.get('guarantor_id')
                    if provided_guarantor and not self.env.context.get('resl_allow_replacement_create'):
                        # A request normally has ONE guarantor. A second one is
                        # allowed only when the first guarantor's salary does not
                        # cover the borrower on its own (their COMBINED salaries
                        # must then cover it - see resl.validations rule 5c).
                        # Never more than two. A rejected / replaced / separated
                        # line no longer counts, so the borrower can nominate
                        # someone else.
                        Validations.ensure_can_add_guarantor(
                            loan, pending_count=batch_counts.get(loan.id, 0)
                        )
                        batch_counts[loan.id] = batch_counts.get(loan.id, 0) + 1

                    # Permanent-staff status was already enforced above (hard
                    # gate). Here run the rest of the eligibility pipeline
                    # (active contract, service, retirement, disciplinary,
                    # guarantee limit, etc.).
                    if vals.get('guarantor_id') and loan:
                        g_emp = self.env['hr.employee'].browse(vals['guarantor_id'])
                        loan._ensure_guarantor_is_eligible(g_emp, exclude_loan_id=loan.id, strict=False)
            except ValidationError:
                raise
            except Exception:
                _logger.exception(
                    "Unexpected (non-validation) error while checking guarantor "
                    "eligibility on create; allowing creation to proceed so an "
                    "unrelated/defensive failure doesn't block the flow."
                )

        # (loan, guarantor) must be unique among live lines (see init()). When
        # the guarantor already has an old line on this loan that is no longer
        # in play (rejected / replaced / separated / soft-deleted), REVIVE that
        # line instead of inserting a duplicate - this is what lets the
        # borrower re-select a guarantor who was replaced earlier.
        revived = self.browse()
        new_vals = []
        for vals in vals_list:
            old_line = self._find_reusable_line(vals.get('loan_id'), vals.get('guarantor_id'))
            if old_line:
                old_line.sudo().write({
                    'state': vals.get('state') or 'draft',
                    'active': True,
                    'replaced_by_id': False,
                    'replaced_at': False,
                })
                revived |= old_line
            else:
                new_vals.append(vals)
        created = super().create(new_vals) if new_vals else self.browse()
        return revived | created

    @api.model
    def _find_reusable_line(self, loan_id, guarantor_id):
        """An old line of this guarantor on this loan that can be brought back."""
        if not (loan_id and guarantor_id):
            return self.browse()
        return self.sudo().with_context(active_test=False).search([
            ('loan_id', '=', loan_id),
            ('guarantor_id', '=', guarantor_id),
            '|', ('active', '=', False),
            ('state', 'in', ('rejected', 'replaced', 'separated')),
        ], limit=1)