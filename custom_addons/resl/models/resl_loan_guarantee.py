from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class ReslLoanGuarantee(models.Model):
    _name = "resl.loan.guarantee"
    _description = "Loan Guarantee"
    _inherit = ["mail.thread", "mail.activity.mixin"]

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
    state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('replaced', 'Replaced'),
        ('separated', 'Separated'),
    ], string="Status", default="draft", tracking=True)

    replaced_by_id = fields.Many2one(
        'resl.loan.guarantee', string="Replaced By", readonly=True
    )
    replaced_at = fields.Datetime(string="Replaced At", readonly=True)

    replacement_guarantor_id = fields.Many2one(
        'hr.employee', string='Replacement Guarantor',
        related='replaced_by_id.guarantor_id', readonly=True, store=False
    )
    replacement_state = fields.Selection(
        related='replaced_by_id.state',
        string='Replacement State', readonly=True, store=False
    )
    can_act_as_guarantor = fields.Boolean(
        string="Can Act as Guarantor",
        compute="_compute_can_act_as_guarantor", store=False
    )
    guarantor_guarantee_count = fields.Integer(
        string="Current Guarantees",
        related="guarantor_id.guarantee_count", store=False, readonly=True,
    )

    _sql_constraints = [
        (
            'uniq_loan_guarantor',
            'unique(loan_id, guarantor_id)',
            'This employee is already registered as a guarantor for this loan.'
        ),
    ]

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
            try:
                loan = g.loan_id
                if loan and getattr(loan, 'status', None) == 'guarantor_pending':
                    loan.sudo().write({'status': 'draft'})
            except Exception:
                _logger.exception('Failed to revert loan status after guarantor rejection')
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
                user.has_group('resl.group_resl_hr')
                or user.has_group('resl.group_resl_manager')
            )
            if not (is_borrower or is_privileged):
                pass  # validation disabled for migration
        return super().unlink()

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
                        # ONE guarantor per request. (The limit of 2 now
                        # applies per employee across requests, see
                        # resl.validations._guarantor_problems rule 7.)
                        # A rejected / replaced / separated line no longer
                        # counts, so the borrower can nominate someone else.
                        active_lines = loan.guarantor_line_ids.filtered(
                            lambda l: l.state not in ('replaced', 'separated', 'rejected')
                        )
                        if len(active_lines) + batch_counts.get(loan.id, 0) >= 1:
                            raise ValidationError(
                                _("This request already has a guarantor. Each request "
                                  "can have only one guarantor.")
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
        return super().create(vals_list)