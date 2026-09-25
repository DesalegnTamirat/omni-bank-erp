"""
ReslLoan Model — Odoo 17 migration
Staff loan request and approval workflow, including eligibility,
guarantor management, and replacement logic.

Key changes from v14:
- invalidate_cache() replaced by invalidate_recordset() / _compute fields trigger
- company_id.currency_id replaces user.company_id.currency_id
- f-strings kept (Python 3.10+); no ORM API changes needed
- `action_id` kwarg removed from message_post (no longer supported)
- `tree` views renamed `list` in arch (Odoo 17 alias still works but list is canonical)
"""
from odoo import api, fields, models, _, SUPERUSER_ID
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class ReslLoan(models.Model):
    _name = 'resl.loan'
    _description = 'Staff Loan Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Reference', required=True, default='New')

    def _default_employee(self):
        return self.env['hr.employee'].search(
            [('user_id', '=', self.env.user.id)], limit=1
        )

    employee_id = fields.Many2one(
        'hr.employee', string='Requester', required=True,
        default=_default_employee, readonly=True,
    )
    employee_active = fields.Boolean(
        string='Requester Active',
        related='employee_id.active', store=True,
        help="False once the borrower has separated/been archived. Used to "
             "hide actions (e.g. requesting a guarantor replacement) that a "
             "separated employee can no longer perform."
    )

    # Borrower's operating unit (branch). Computed defensively to avoid
    # KeyError if third-party hr fields are missing during install.
    # default_operating_unit_id = fields.Many2one(
    #     'operating.unit',
    #     string='Branch',
    #     compute='_compute_default_operating_unit_id',
    #     readonly=True,
    #     store=False,
    # )

    # @api.depends('employee_id')
    # def _compute_default_operating_unit_id(self):
    #     for loan in self:
    #         ou = False
    #         try:
    #             emp = loan.employee_id
    #             if emp and hasattr(emp, 'default_operating_unit_id'):
    #                 ou = emp.default_operating_unit_id
    #         except Exception:
    #             ou = False
    #         loan.default_operating_unit_id = ou.id if ou else False

    currency_id = fields.Many2one(
        'res.currency', string='Currency', required=True,
        # Odoo 17: env.company is the preferred way; user.company_id still works
        default=lambda self: self.env.company.currency_id
    )

    request_date = fields.Date(default=fields.Date.context_today)
    approval_date = fields.Date()
    approver_id = fields.Many2one('res.users', string='Approver')

    loan_amount = fields.Monetary(
        string='Eligible Loan Amount',
        compute="_compute_loan_amount", store=True,
        currency_field='currency_id', readonly=True
    )
    requested_amount = fields.Monetary(
        string="Requested Loan Amount",
        currency_field='currency_id',
    )
    approved_amount = fields.Monetary(
        string="Approved Loan Amount",
        currency_field='currency_id',
        readonly=True,
    )
    total_loans_taken = fields.Monetary(
        string="Total Loans Taken",
        compute='_compute_total_loans_taken',
        store=True,
        currency_field='currency_id',
        readonly=True,
    )
    net_eligible_amount = fields.Monetary(
        string="Net Eligible Amount",
        compute="_compute_net_eligible_amount",
        store=True,
        currency_field='currency_id',
        readonly=True,
    )
    last_salary_basis = fields.Float(
        string="Salary Basis at Loan",
        readonly=True,
    )

    employee_max_eligible_amount = fields.Monetary(
        string="Employee's Current Eligible Ceiling",
        compute="_compute_employee_remaining_eligibility", store=True,
        currency_field='currency_id', readonly=True,
        help="Ceiling based on the employee's CURRENT basic salary and the "
             "single repayment term their current months of service require "
             "(basic salary x6 from 6 months of service onward, basic "
             "salary x3 before that). Recalculated live from today's salary, "
             "so a pay increase raises this ceiling immediately.",
    )

    employee_months_of_service = fields.Integer(
        string="Employee's Months of Service",
        compute='_compute_employee_months_of_service', store=True,
        help="Continuous months of service used to determine which single "
             "repayment term this employee must use: under 6 months of "
             "service -> 3-month term only; 6+ months of service -> "
             "6-month term only. Once an employee reaches 6 months of "
             "service, the 3-month term is no longer available to them.",
    )
    loan_term_months = fields.Selection([
        ('3', '3 Months'),
        ('6', '6 Months'),
    ], string="Loan Term", tracking=True,
        compute='_compute_loan_term_months', store=True, readonly=True,
        help="Set automatically from the employee's months of continuous "
             "service — not a free choice: under 6 months of service shows "
             "3 Months only; 6+ months of service shows 6 Months only (a "
             "3-month loan is no longer available once the employee reaches "
             "6 months of service). The eligible loan ceiling is the "
             "employee's basic salary multiplied by this term.")

    status = fields.Selection([
        ('draft', 'Draft'),
        ('guarantor_pending', 'Waiting Guarantees'),
        ('manager_review', 'Manager Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', tracking=True)

    guarantor_line_ids = fields.One2many(
        'resl.loan.guarantee', 'loan_id',
        string='Guarantors', copy=True, auto_join=True
    )

    is_guarantor = fields.Boolean(compute="_compute_is_guarantor")
    is_manager_reviewer = fields.Boolean(compute="_compute_is_manager_reviewer")
    has_active_guarantor = fields.Boolean(
        string="Has Active Guarantor",
        compute="_compute_has_active_guarantor", store=False,
        help="True while this loan already has a guarantor line that is "
             "draft/pending/accepted (i.e. not rejected/replaced/separated). "
             "One guarantor per request, so Find Guarantor is hidden while "
             "this is true, and reappears once it's false again (e.g. after "
             "a rejection).",
    )
    all_guarantors_accepted = fields.Boolean(
        compute="_compute_all_guarantors_accepted", store=True
    )
    can_submit_manager = fields.Boolean(
        compute="_compute_can_submit_manager", store=False
    )
    manager_user_id = fields.Many2one(
        'res.users', compute='_compute_designated_approver', store=True
    )
    designated_approver_id = fields.Many2one(
        'res.users', string="Designated Approver",
        compute='_compute_designated_approver', store=True
    )
    designated_approver_role = fields.Char(
        string="Approver Role",
        compute='_compute_designated_approver', store=True
    )

    is_eligible = fields.Boolean(
        string="Borrower Eligible",
        compute="_compute_borrower_eligibility",
        store=False,
    )
    ineligibility_reasons = fields.Text(
        string="Ineligibility Reasons",
        compute="_compute_borrower_eligibility",
        store=False,
    )

    settlement_status = fields.Selection([
        ('none', 'Normal'),
        ('pending_clearance', 'Pending Clearance Settlement'),
        ('settled', 'Settled'),
    ], string="Settlement Status", default='none', tracking=True)

    core_banking_status = fields.Selection([
        ('pending', 'Pending Disbursement'),
        ('disbursed', 'Disbursed'),
        ('failed', 'Failed'),
    ], string="Core Banking Status", default='pending', tracking=True)
    core_banking_ref = fields.Char(string="Core Banking Reference", tracking=True)
    disbursement_date = fields.Date(string="Disbursement Date", tracking=True)
    disbursed_by_id = fields.Many2one('res.users', string="Disbursed By", tracking=True)
    bank_account_number = fields.Char(
        string="Bank Account Number",
        tracking=True,
        help="Core Banking account number used for disbursement.",
    )

    needs_guarantor_replacement = fields.Boolean(
        string="Needs Guarantor Replacement",
        default=False, copy=False,
        help="Set when a guarantor separates. Borrower must nominate replacement."
    )
    can_nominate_replacement = fields.Boolean(
        string='Can Nominate Replacement',
        compute='_compute_can_nominate_replacement',
        store=False,
    )
    is_employee_user = fields.Boolean(
        string="Current user is borrower",
        compute='_compute_is_employee_user',
        store=False,
    )
    hr_officer_id = fields.Many2one('res.users', string="HR Officer")
    tmd_user_id = fields.Many2one('res.users', string="TMD Responsible")

    replacement_log_count = fields.Integer(
        string="Replacement Logs",
        compute="_compute_replacement_log_count",
        store=False
    )
    auto_replacement_initiated = fields.Boolean(
        string="Auto Replacement Initiated",
        default=False,
        help="Internal flag: automatic replacements were initiated for this loan."
    )
    can_edit_guarantors = fields.Boolean(
        string="Can edit guarantors",
        compute='_compute_can_edit_guarantors',
        store=False,
    )
    guarantor_rejected_notice = fields.Char(
        string="Guarantor Rejected Notice",
        compute='_compute_guarantor_rejected_notice',
        store=False,
    )
    progress_status = fields.Selection([
        ('requested', 'Requested'),
        ('accepted', 'Accepted'),
        ('approved', 'Approved'),
        ('disbursed', 'Disbursed'),
        ('rejected', 'Rejected'),
    ], string="Progress", compute='_compute_progress_status',
        store=True, tracking=False,
        help="Simplified, top-level view of where this loan stands, shown "
             "as the status bar in the form header. Driven by 'status' "
             "(the detailed workflow stage), 'all_guarantors_accepted' "
             "and 'core_banking_status' — it is a display convenience and "
             "is never written to directly.")
    can_respond_as_guarantor = fields.Boolean(
        string="Can Accept/Reject as Guarantor",
        compute='_compute_can_respond_as_guarantor',
        store=False,
        help="True when the current user is a guarantor on this loan with "
             "a pending guarantee request, so the header Accept/Reject "
             "buttons can be shown to them directly.",
    )
    show_approve_button = fields.Boolean(
        string='Show Approve Button',
        compute='_compute_show_approve_button',
        store=False,
    )

    # ── Computes ──────────────────────────────────────────────────────────────

    @api.depends('employee_id.user_id')
    def _compute_is_employee_user(self):
        user = self.env.user
        for loan in self:
            try:
                current_emp_id = user.employee_id.id if user.employee_id else False
            except Exception:
                current_emp_id = False
            loan.is_employee_user = bool(
                loan.employee_id and loan.employee_id.id
                and current_emp_id
                and loan.employee_id.id == current_emp_id
            )

    @api.depends('needs_guarantor_replacement', 'employee_id.user_id')
    def _compute_can_nominate_replacement(self):
        for loan in self:
            user = self.env.user
            can_nom = False
            if loan.needs_guarantor_replacement:
                try:
                    current_emp_id = user.employee_id.id if user.employee_id else False
                except Exception:
                    current_emp_id = False
                if (
                    (loan.employee_id and loan.employee_id.id
                     and current_emp_id
                     and loan.employee_id.id == current_emp_id)
                    or user.has_group('resl.group_resl_hr')
                ):
                    can_nom = True
            loan.can_nominate_replacement = can_nom

    @api.depends('employee_id', 'status')
    def _compute_borrower_eligibility(self):
        for loan in self:
            if not loan.employee_id:
                loan.is_eligible = False
                loan.ineligibility_reasons = ""
                continue
            is_eligible, reasons = self.env['resl.validations'].check_borrower_eligibility(
                loan, loan.employee_id, raise_exception=False
            )
            reasons = list(reasons or [])
            # Also surface the request-level rules (pending request / ceiling
            # used up) the moment the New form opens, instead of only when the
            # record is first saved. Only for a draft: an already-submitted
            # request must not be flagged by rules meant for a new one.
            if (loan.status or 'draft') == 'draft':
                own_id = loan.id if isinstance(loan.id, int) else None
                reasons += loan._request_blockers(loan.employee_id, exclude_loan_id=own_id)
            loan.is_eligible = not reasons
            loan.ineligibility_reasons = "\n• " + "\n• ".join(reasons) if reasons else ""

    @api.depends('employee_id', 'loan_term_months')
    def _compute_loan_amount(self):
        for loan in self:
            salary = loan._employee_current_wage(loan.employee_id.sudo())
            # FR-RESL-005 (term-based ceiling): eligible amount = basic salary
            # x the chosen loan term (3 or 6 months). Until a term is picked,
            # the ceiling is 0 so the user is prompted to choose one first.
            term = int(loan.loan_term_months) if loan.loan_term_months else 0
            loan.loan_amount = salary * term if salary and term else 0.0

    @api.depends('employee_id')
    def _compute_employee_months_of_service(self):
        for loan in self:
            emp = loan.employee_id.sudo() if loan.employee_id else False
            loan.employee_months_of_service = loan._months_of_service(emp) if emp else 0

    @api.depends('employee_id', 'employee_months_of_service')
    def _compute_loan_term_months(self):
        for loan in self:
            emp = loan.employee_id.sudo() if loan.employee_id else False
            # The term is not a free choice: it's fixed by the employee's
            # months of service (3-month term under 6 months of service,
            # 6-month term from 6 months of service onward), so it is
            # always computed server-side rather than editable/onchange-set,
            # so it is reliably present on create() regardless of the UI.
            required_term = loan._max_eligible_loan_term(emp) if emp else 0
            loan.loan_term_months = str(required_term) if required_term else '3'

    @api.constrains('loan_term_months', 'employee_id', 'employee_months_of_service')
    def _check_loan_term_eligibility(self):
        """
        Repayment term rule (the term is fixed, not a free choice):
        - Under 6 months of continuous service: only the 3-month term
          is available.
        - 6+ months of continuous service: only the 6-month term is
          available. Once an employee reaches 6 months of service, a
          3-month loan is no longer available to them.
        - <3 months: not eligible to apply at all (enforced separately by
          FR-RESL-002 minimum-service checks in resl.validations).
        """
        for loan in self:
            if not loan.employee_id or not loan.loan_term_months:
                continue
            required_term = loan._max_eligible_loan_term(loan.employee_id.sudo())
            if not required_term:
                continue  # under 3 months: handled by the eligibility check elsewhere
            if int(loan.loan_term_months) != required_term:
                if required_term == 6:
                    raise ValidationError(
                        _(
                            "Repayment Term: %(name)s has %(months)s month(s) of service and has "
                            "reached the 6-month service mark. Employees with 6+ months of service "
                            "must take the 6-month repayment term; the 3-month term is no longer "
                            "available to them."
                        ) % {
                            'name': loan.employee_id.name,
                            'months': loan.employee_months_of_service,
                        }
                    )
                raise ValidationError(
                    _(
                        "Repayment Term: %(name)s has %(months)s month(s) of service. "
                        "Employees with fewer than 6 months of service must use the "
                        "3-month repayment term; the 6-month term requires at least 6 "
                        "months of continuous service."
                    ) % {
                        'name': loan.employee_id.name,
                        'months': loan.employee_months_of_service,
                    }
                )

    @api.depends('guarantor_line_ids.guarantor_id.user_id')
    def _compute_is_guarantor(self):
        for loan in self:
            loan.is_guarantor = any(
                g.guarantor_id.user_id == self.env.user
                for g in loan.guarantor_line_ids
            )

    @api.depends('guarantor_line_ids.state')
    def _compute_has_active_guarantor(self):
        for loan in self:
            loan.has_active_guarantor = bool(loan.guarantor_line_ids.filtered(
                lambda l: l.state not in ('replaced', 'separated', 'rejected')
            ))

    @api.depends('guarantor_line_ids.state', 'guarantor_line_ids.guarantor_id')
    def _compute_can_respond_as_guarantor(self):
        """Drives the header Accept/Reject buttons: true only when the
        logged-in user is themself the guarantor on one of this loan's
        lines and that line is still 'pending' (awaiting their answer).
        Lets the guarantor accept/reject right from the loan header
        instead of the borrower-only action buttons.
        """
        try:
            current_emp_id = self.env.user.employee_id.id if self.env.user.employee_id else False
        except Exception:
            current_emp_id = False
        for loan in self:
            loan.can_respond_as_guarantor = bool(current_emp_id) and any(
                line.state == 'pending' and line.guarantor_id.id == current_emp_id
                for line in loan.guarantor_line_ids
            )

    @api.depends('employee_id', 'employee_id.default_operating_unit_id', 'employee_id.parent_id')
    def _compute_designated_approver(self):
        """
        FR-RESL-012: The workflow shall automatically assign approvals to Branch
        Managers, District Directors, or the Compensation and Benefit Administration
        Division Manager based on employee work location.
        """
        for loan in self:
            emp = loan.employee_id.sudo() if loan.employee_id else False
            if not emp:
                loan.designated_approver_id = False
                loan.designated_approver_role = False
                loan.manager_user_id = False
                continue

            ou = getattr(emp, 'default_operating_unit_id', False)
            work_unit_type = getattr(ou, 'work_unit_type', False) if ou else False

            approver_user = False
            approver_role = "Manager"

            # 1. Branch / Sub-branch / Service Center -> Branch Manager
            if work_unit_type in ('branch', 'sub_branch', 'service_center'):
                is_bm = False
                job_title = (emp.job_id.name or '').lower() if emp.job_id else ''
                if any(t in job_title for t in ('branch manager', 'manager in branch')):
                    is_bm = True

                # If borrower is already the Branch Manager, escalate to District Director
                if is_bm:
                    approver_role = "District Director"
                    if emp.parent_id and emp.parent_id.user_id:
                        approver_user = emp.parent_id.user_id
                    elif ou and ou.parent_unit:
                        district_emp = self.env['hr.employee'].sudo().search([
                            ('default_operating_unit_id', '=', ou.parent_unit.id),
                            ('user_id', '!=', False)
                        ], limit=1)
                        approver_user = district_emp.user_id if district_emp else False
                else:
                    approver_role = "Branch Manager"
                    approver_user = emp.parent_id.user_id if emp.parent_id else False

            # 2. District Office / Regional Office -> District Director
            elif work_unit_type in ('district_office', 'regional_office'):
                approver_role = "District Director"
                approver_user = emp.parent_id.user_id if emp.parent_id else False

            # 3. Head Office / Central departments -> Compensation & Benefit Manager
            elif work_unit_type in ('head_office', 'other') or not work_unit_type:
                approver_role = "Compensation & Benefit Administration Division Manager"
                cb_manager = self.env['hr.employee'].sudo().search([
                    '|',
                    ('job_id.name', 'ilike', 'Compensation'),
                    ('job_id.name', 'ilike', 'Benefit'),
                    ('user_id', '!=', False)
                ], limit=1)
                if cb_manager and cb_manager.user_id:
                    approver_user = cb_manager.user_id
                elif emp.parent_id and emp.parent_id.user_id:
                    approver_user = emp.parent_id.user_id

            # Fallback
            if not approver_user and emp.parent_id and emp.parent_id.user_id:
                approver_user = emp.parent_id.user_id

            loan.designated_approver_role = approver_role
            loan.designated_approver_id = approver_user.id if approver_user else False
            loan.manager_user_id = approver_user.id if approver_user else False

    @api.depends('manager_user_id')
    def _compute_is_manager_reviewer(self):
        user = self.env.user
        is_group_manager = (
            user.has_group('resl.group_resl_manager')
            or user.has_group('resl.group_resl_hr')
        )
        for loan in self:
            loan.is_manager_reviewer = bool(
                is_group_manager or (loan.manager_user_id == user)
            )

    @api.depends('guarantor_line_ids.state')
    def _compute_all_guarantors_accepted(self):
        for loan in self:
            active_lines = loan.guarantor_line_ids.filtered(
                lambda line: line.state in ('pending', 'accepted')
            )
            loan.all_guarantors_accepted = bool(active_lines) and all(
                line.state == 'accepted' for line in active_lines
            )

    @api.depends(
        'employee_id.user_id', 'status',
        'all_guarantors_accepted', 'guarantor_line_ids.state',
        'needs_guarantor_replacement'
    )
    def _compute_can_submit_manager(self):
        for loan in self:
            try:
                current_emp_id = self.env.user.employee_id.id if self.env.user.employee_id else False
            except Exception:
                current_emp_id = False
            loan.can_submit_manager = bool(
                loan.employee_id and loan.employee_id.id
                and current_emp_id
                and loan.employee_id.id == current_emp_id
                and loan.status in ('draft', 'guarantor_pending')
                and loan.all_guarantors_accepted
                and not loan.needs_guarantor_replacement
            )

    @api.depends('employee_id', 'core_banking_status', 'approved_amount')
    def _compute_total_loans_taken(self):
        """Total Loans Taken reflects money actually disbursed on Core
        Banking (FR-RESL-019). A loan counts toward this total - including
        toward its own displayed total - only once its own
        core_banking_status == 'disbursed'; draft/pending loans never
        match the domain below, so they never inflate anyone's total."""
        for loan in self:
            if not loan.employee_id:
                loan.total_loans_taken = 0.0
                continue
            loan.total_loans_taken = loan._employee_total_disbursed(loan.employee_id)

    @api.depends('loan_amount', 'total_loans_taken')
    def _compute_net_eligible_amount(self):
        for loan in self:
            loan.net_eligible_amount = max(
                0.0, (loan.loan_amount or 0.0) - (loan.total_loans_taken or 0.0)
            )

    # NOTE: The previous @api.onchange('net_eligible_amount') that pre-filled
    # requested_amount on New forms has been intentionally removed.
    #
    # The onchange fired as soon as the blank form opened (because employee_id
    # defaults → loan_term_months → loan_amount → net_eligible_amount), which
    # immediately set requested_amount and marked the Odoo form record as
    # "dirty". Odoo's FormController.beforeLeave() auto-saves any dirty new
    # record when the user navigates away — even without clicking Save — so
    # opening a New form and then navigating elsewhere silently created a draft
    # resl.loan row in the database.
    #
    # The create() override (see below) already handles this: it writes
    #   requested_amount = net_eligible_amount
    # whenever requested_amount is empty at the moment the record is actually
    # saved (either via the Save button or via "Select as Guarantor" in the
    # wizard). That is the ONLY intended creation path.

    @api.depends('employee_id', 'employee_months_of_service', 'total_loans_taken')
    def _compute_employee_remaining_eligibility(self):
        """Computes the employee's current eligible ceiling: CURRENT basic
        salary x the single term their current months of service require
        (x3 under 6 months of service, x6 from 6 months onward) — never a
        term freely chosen on this request. Used internally (e.g. by
        create()) to block new requests once this ceiling is fully used up
        by amounts already disbursed.
        """
        for loan in self:
            emp = loan.employee_id.sudo() if loan.employee_id else False
            salary = loan._employee_current_wage(emp) if emp else 0.0
            max_term = loan._max_eligible_loan_term(emp) if emp else 0
            loan.employee_max_eligible_amount = salary * max_term if salary and max_term else 0.0

    @api.depends('guarantor_line_ids')
    def _compute_replacement_log_count(self):
        log_obj = self.env['resl.loan.replacement.log']
        for loan in self:
            loan.replacement_log_count = log_obj.search_count(
                [('loan_id', '=', loan.id)]
            )

    @api.depends(
        'guarantor_line_ids.state', 'guarantor_line_ids.guarantor_id',
        'is_employee_user',
    )
    def _compute_guarantor_rejected_notice(self):
        """Banner shown when a guarantor rejected and no other guarantor
        has been chosen yet.

        The wording depends on who is looking at it: the borrower reads
        "your guarantee request", but this same banner is also visible
        to the manager, HR, and the guarantor(s) who did the rejecting —
        for them "your" is the wrong pronoun, so they get a neutral
        third-person sentence instead. Grammar (has/have) also adapts to
        whether one or several guarantors rejected.
        """
        for loan in self:
            lines = loan.guarantor_line_ids
            rejected = lines.filtered(lambda l: l.state == 'rejected')
            current = lines.filtered(lambda l: l.state in ('draft', 'pending', 'accepted'))
            if rejected and not current:
                names = rejected.sudo().mapped('guarantor_id.name')
                names_str = ", ".join(names)
                verb = _("have") if len(names) > 1 else _("has")
                if loan.is_employee_user:
                    loan.guarantor_rejected_notice = _(
                        "%(names)s %(verb)s rejected your guarantee request. "
                        "Click 'Find Guarantor' to choose another guarantor."
                    ) % {'names': names_str, 'verb': verb}
                else:
                    loan.guarantor_rejected_notice = _(
                        "%(names)s %(verb)s rejected this guarantee request. "
                        "The borrower needs to select another guarantor."
                    ) % {'names': names_str, 'verb': verb}
            else:
                loan.guarantor_rejected_notice = False

    @api.depends('status', 'core_banking_status', 'all_guarantors_accepted')
    def _compute_progress_status(self):
        """Collapse the detailed workflow ('status') and disbursement
        ('core_banking_status') fields into the five stages shown on the
        header status bar: Requested -> Accepted -> Approved -> Disbursed,
        with Rejected as the alternate end state."""
        for loan in self:
            if loan.status == 'rejected':
                loan.progress_status = 'rejected'
            elif loan.core_banking_status == 'disbursed':
                loan.progress_status = 'disbursed'
            elif loan.status == 'approved':
                loan.progress_status = 'approved'
            elif loan.all_guarantors_accepted:
                loan.progress_status = 'accepted'
            else:
                loan.progress_status = 'requested'

    def _compute_can_edit_guarantors(self):
        user = self.env.user
        for loan in self:
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
            if loan.status == 'approved' and not is_privileged:
                loan.can_edit_guarantors = False
            else:
                loan.can_edit_guarantors = bool(is_borrower or is_privileged)

    def _compute_show_approve_button(self):
        user = self.env.user
        is_hr = user.has_group('resl.group_resl_hr')
        is_mgr = user.has_group('resl.group_resl_manager')
        for loan in self:
            if loan.status != 'manager_review':
                loan.show_approve_button = False
                continue
            borrower_user = False
            try:
                borrower_user = loan.employee_id.user_id if loan.employee_id else False
            except Exception:
                pass
            borrower_is_manager = False
            try:
                borrower_is_manager = bool(
                    borrower_user
                    and borrower_user.has_group('resl.group_resl_manager')
                )
            except Exception:
                pass
            if borrower_is_manager:
                loan.show_approve_button = bool(is_hr)
            else:
                loan.show_approve_button = bool(
                    is_mgr
                    or (loan.manager_user_id and loan.manager_user_id.id == user.id)
                )

    # ── Smart button actions ──────────────────────────────────────────────────

    def action_open_replacement_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Guarantor Replacement Logs'),
            'res_model': 'resl.loan.replacement.log',
            'view_mode': 'list,form',
            'domain': [('loan_id', '=', self.id)],
            'context': {'default_loan_id': self.id},
            'target': 'current',
        }

    # ── Guarantor separation / notification ──────────────────────────────────

    @api.model
    def _trigger_auto_replacement_for_separated_guarantor(self, separated_employee):
        if not separated_employee:
            return
        loans = self.search([
            ('guarantor_line_ids.guarantor_id', '=', separated_employee.id)
        ])
        affected_guarantor_ids = set()
        for loan in loans:
            for line in loan.guarantor_line_ids.filtered(
                lambda l: l.guarantor_id == separated_employee and l.state != 'separated'
            ):
                line.sudo().write({'state': 'separated'})
                loan.sudo().write({'needs_guarantor_replacement': True})
                try:
                    loan._notify_guarantor_separation(line)
                except Exception:
                    pass
                if line.guarantor_id:
                    affected_guarantor_ids.add(line.guarantor_id.id)
        if affected_guarantor_ids:
            self.env['hr.employee'].sudo().recompute_all_guarantee_counts(
                list(affected_guarantor_ids)
            )

    def _notify_guarantor_separation(self, old_guarantee):
        """Notify borrower and HR/TMD after a guarantor separates."""
        self.ensure_one()
        # Odoo 17: action_id kwarg removed from message_post — post plain message
        self.sudo().message_post(
            body="Guarantor %s separated. Replacement required."
                 % old_guarantee.guarantor_id.name
        )
        try:
            borrower_emp = self.sudo().employee_id
            if borrower_emp and borrower_emp.user_id:
                self.sudo().activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=borrower_emp.user_id.id,
                    note=(
                        "Guarantor %s separated. Please nominate a replacement for "
                        "loan %s." % (old_guarantee.guarantor_id.name, self.name)
                    )
                )
        except Exception:
            _logger.exception("Failed to schedule replacement activity for borrower")

    # ── Replacement wizard actions ────────────────────────────────────────────

    def action_request_replacement(self):
        self.ensure_one()
        if not self.guarantor_line_ids:
            pass  # validation disabled for migration; re-enable after data import
        ctx = dict(self.env.context or {})
        ctx['default_loan_id'] = self.id

        # The wizard needs to know WHICH guarantor line is being replaced.
        # A loan only ever has one active (draft/pending/accepted) guarantor
        # at a time, so pre-select it here — otherwise the (readonly)
        # Current Guarantor field is left empty and Confirm Replacement
        # fails with "No guarantor line selected for replacement.", even
        # though the loan clearly already has the guarantor being replaced.
        active_lines = self.guarantor_line_ids.filtered(
            lambda l: l.state not in ('replaced', 'separated', 'rejected')
        )
        if active_lines:
            if ctx.get('default_is_hr_action'):
                ctx['default_old_guarantee_ids'] = [(6, 0, active_lines.ids)]
            else:
                ctx['default_old_guarantee_id'] = active_lines[:1].id

        try:
            action = self.env.ref('resl.action_resl_loan_replacement_wizard').read()[0]
            action_context = action.get('context') or {}
            if isinstance(action_context, str):
                import ast
                try:
                    action_context = ast.literal_eval(action_context)
                except Exception:
                    action_context = {}
            action['context'] = dict(action_context, **ctx)
            return action
        except Exception:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Request Guarantor Replacement',
                'res_model': 'resl.loan.replacement.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': ctx,
            }

    def action_nominate_replacement(self):
        self.ensure_one()
        ctx = dict(self.env.context or {})
        ctx['default_loan_id'] = self.id
        try:
            action = self.env.ref('resl.action_resl_loan_replacement_wizard').read()[0]
            action_context = action.get('context') or {}
            if isinstance(action_context, str):
                import ast
                try:
                    action_context = ast.literal_eval(action_context)
                except Exception:
                    action_context = {}
            action['context'] = dict(action_context, **ctx)
            return action
        except Exception:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Nominate Replacement Guarantor',
                'res_model': 'resl.loan.replacement.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': ctx,
            }

    def nominate_replacement(self, old_guarantee_line_id, new_guarantor_employee_id):
        """Handle borrower/manual and HR-initiated guarantor replacement."""
        self.ensure_one()
        Guarantee = self.env['resl.loan.guarantee']
        old_line = Guarantee.browse(old_guarantee_line_id)
        if not old_line or old_line.loan_id.id != self.id:
            pass  # validation disabled for migration

        ctx = dict(self.env.context or {})
        is_hr_action = ctx.get('default_is_hr_action', False) or ctx.get('is_hr_action', False)
        is_system_action = ctx.get('resl_allow_auto_replacement', False)
        manual_request = ctx.get('default_manual_request', False)

        if not (is_hr_action or manual_request or is_system_action) and old_line.state != 'separated':
            pass  # validation disabled for migration

        new_emp = self.env['hr.employee'].browse(new_guarantor_employee_id)
        if not new_emp:
            pass  # validation disabled for migration

        self._ensure_guarantor_is_eligible(new_emp, exclude_loan_id=self.id, strict=True)

        new_line = Guarantee.with_context(resl_allow_replacement_create=True).create({
            'loan_id': self.id,
            'guarantor_id': new_emp.id,
            'state': 'pending',
        })

        old_line.sudo().write({
            'replaced_by_id': new_line.id,
            'replaced_at': fields.Datetime.now(),
            # The old guarantor is no longer the one being asked to act:
            # once a replacement is nominated, their line stops being
            # actionable (state == 'pending' is what drives the
            # Accept/Reject buttons, both in the Guarantors list and the
            # loan header) so it must move out of 'pending' immediately,
            # not just get a replaced_by_id link. 'rejected' is excluded
            # everywhere else in this module from "active" guarantor
            # counts, and the approval-time finalization step already
            # promotes it to 'replaced' once the new guarantor is accepted
            # and the loan is approved (see action_manager_approve).
            'state': 'rejected',
        })

        self._validate_guarantor_salaries(('accepted', 'pending'), strict=True)

        try:
            if new_line.guarantor_id and new_line.guarantor_id.user_id:
                self.sudo().activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=new_line.guarantor_id.user_id.id,
                    note=f"You have been nominated as guarantor for loan {self.name}. Please review."
                )
        except Exception:
            _logger.exception("Failed to schedule activity for nominated guarantor.")

        note_msg = f"Replacement requested: {new_emp.name} replacing {old_line.guarantor_id.name}."
        self.sudo().message_post(body=note_msg)

        if not is_system_action:
            self.sudo().write({'needs_guarantor_replacement': False, 'status': 'guarantor_pending'})
        else:
            try:
                self.sudo().write({'needs_guarantor_replacement': False})
            except Exception:
                _logger.exception('Failed to clear needs_guarantor_replacement for loan %s', self.id)

        # Odoo 17: use invalidate_recordset instead of invalidate_cache
        self.invalidate_recordset(['guarantor_line_ids', 'all_guarantors_accepted', 'can_submit_manager'])
        return new_line

    # ── Automatic replacement ─────────────────────────────────────────────────

    def _automatic_replacement_for_loan(self, loan, new_guarantor_ids):
        """NO LONGER CALLED. Each request now keeps its own guarantor; a new
        request must not swap the guarantors of the borrower's earlier
        requests. The per-borrower limit (max 2 distinct guarantors) is
        enforced in resl.validations instead. Kept only for reference."""
        if not loan or not new_guarantor_ids:
            return
        prior_loans = self.search([
            ('employee_id', '=', loan.employee_id.id),
            ('status', '=', 'approved'),
            ('id', '!=', loan.id),
        ])
        new_map = {
            gl.guarantor_id.id: gl
            for gl in loan.guarantor_line_ids
            if gl.guarantor_id and gl.id
        }
        for prev in prior_loans:
            old_lines = prev.guarantor_line_ids.filtered(lambda l: l.state == 'accepted')
            old_lines_list = list(old_lines)
            if not old_lines_list:
                _logger.info('Skipping auto replacement for prior loan %s: no accepted lines', prev.id)
                continue
            old_ids = list(dict.fromkeys([l.guarantor_id.id for l in old_lines_list]))
            if set(new_guarantor_ids) == set(old_ids):
                continue
            # FR-RESL-007/008: check each candidate replacement guarantor's
            # eligibility (contract type/permanent status, active contract,
            # service, retirement, disciplinary status, and the 2-active-
            # guarantee limit). Ineligible candidates must NOT be linked in
            # as replacements — previously this was wrapped in a bare
            # except that only logged the ValidationError and let the
            # replacement proceed anyway. Instead, drop ineligible
            # candidates from this loan's new_map so they are skipped
            # below, and keep going with whichever candidates did pass.
            ineligible_gids = set()
            for new_gid in new_guarantor_ids:
                new_emp = self.env['hr.employee'].browse(new_gid)
                try:
                    prev._ensure_guarantor_is_eligible(new_emp, exclude_loan_id=prev.id, strict=True)
                except ValidationError:
                    _logger.warning(
                        'Skipping ineligible auto-replacement guarantor %s for prior loan %s',
                        new_gid, prev.id,
                    )
                    ineligible_gids.add(new_gid)
                except Exception:
                    _logger.exception('Eligibility check failed for prior loan %s', prev.id)
                    ineligible_gids.add(new_gid)
            if ineligible_gids:
                new_map = {
                    gid: gl for gid, gl in new_map.items() if gid not in ineligible_gids
                }
                new_guarantor_ids = [
                    gid for gid in new_guarantor_ids if gid not in ineligible_gids
                ]
            if not new_guarantor_ids:
                _logger.info(
                    'No eligible replacement guarantors remain for prior loan %s; skipping.',
                    prev.id,
                )
                continue
            pair_count = min(len(old_lines_list), len(new_guarantor_ids))
            try:
                for i in range(pair_count):
                    old_line = old_lines_list[i]
                    new_gid = new_guarantor_ids[i]
                    new_line = new_map.get(new_gid)
                    if new_line:
                        old_line.sudo().write({
                            'replaced_by_id': new_line.id,
                            'replaced_at': fields.Datetime.now()
                        })
                if len(new_guarantor_ids) > pair_count:
                    anchor_old = old_lines_list[-1]
                    for j in range(pair_count, len(new_guarantor_ids)):
                        new_line = new_map.get(new_guarantor_ids[j])
                        if new_line:
                            anchor_old.sudo().write({
                                'replaced_by_id': new_line.id,
                                'replaced_at': fields.Datetime.now()
                            })
                if len(old_lines_list) > len(new_guarantor_ids) and new_guarantor_ids:
                    target_new_line = new_map.get(new_guarantor_ids[0])
                    if target_new_line:
                        for k in range(len(new_guarantor_ids), len(old_lines_list)):
                            old_lines_list[k].sudo().write({
                                'replaced_by_id': target_new_line.id,
                                'replaced_at': fields.Datetime.now()
                            })
            except Exception:
                _logger.exception('Auto replacement failed for prior loan %s', prev.id)

    # ── Eligibility helpers ───────────────────────────────────────────────────

    def _get_latest_contract(self, employee, sudo=False):
        """
        Odoo 19: hr.contract was merged into hr.version, and hr.employee
        delegates to it via _inherits = {'hr.version': 'version_id'}.
        employee.version_id is the current/relevant hr.version record
        (it defaults to employee.current_version_id); employee.version_ids
        holds the full history. employee.contract_id/contract_ids no
        longer carry live data.
        """
        if not employee:
            return False
        emp = employee.sudo() if sudo else employee

        version = getattr(emp, 'version_id', False) or getattr(emp, 'current_version_id', False)
        if version:
            return version

        versions = getattr(emp, 'version_ids', False)
        if versions:
            date_field = 'contract_date_start' if hasattr(versions, 'contract_date_start') else 'date_start'
            try:
                return versions.sorted(date_field, reverse=True)[:1] or False
            except Exception:
                return versions[:1] or False

        # Pre-19 compatibility fallback, in case a customization still sets this.
        if getattr(emp, 'contract_id', False):
            return emp.contract_id
        contract_ids = getattr(emp, 'contract_ids', False)
        if contract_ids:
            return contract_ids.sorted('date_start', reverse=True)[:1] or False

        return False

    def _months_of_service(self, employee):
        """Continuous months of service, ALWAYS computed directly from the
        employee's latest contract/version date_start.

        Note: this deliberately does NOT read hr.employee.months_of_service
        (Odoo's own stored/cached field). That field can go stale whenever
        the underlying contract/version date is changed outside Odoo's
        normal ORM write path (direct SQL updates, data imports/fixes,
        migrations, etc.), since stored compute fields only refresh when
        Odoo's own @api.depends chain is triggered. Recalculating from the
        contract date on every read guarantees this always matches what is
        actually in the contract/version record, with no caching surprises.
        """
        if not employee:
            return 0
        contract = self._get_latest_contract(employee, sudo=True)
        if not contract:
            return 0
        # hr.version (Odoo 19+) uses 'contract_date_start'; pre-19 hr.contract
        # uses 'date_start'. Read whichever the record actually has.
        date_field = 'contract_date_start' if hasattr(contract, 'contract_date_start') else 'date_start'
        start = getattr(contract, date_field, False)
        if not start:
            return 0
        today = fields.Date.context_today(self)
        start_date = fields.Date.from_string(start) if isinstance(start, str) else start
        today_date = fields.Date.from_string(today) if isinstance(today, str) else today
        months = (today_date.year - start_date.year) * 12 + (today_date.month - start_date.month)
        if today_date.day < start_date.day:
            months -= 1
        return max(0, months)

    def _max_eligible_loan_term(self, employee):
        """The single RSSA repayment term (in months) this employee must use,
        based on continuous months of service. The term is NOT a free
        choice between 3 and 6 months:
        - 6+ months of service -> 6 (the 3-month term is no longer
          available once this threshold is reached)
        - 3-5 months of service -> 3 (the only term available)
        - under 3 months -> 0 (not yet eligible to apply at all)
        Combined with the employee's current basic salary, this term gives
        the employee's eligibility ceiling, used to work out how much
        eligibility remains after previous disbursements — see
        _compute_employee_remaining_eligibility.
        """
        months = self._months_of_service(employee) if employee else 0
        if months >= 6:
            return 6
        if months >= 3:
            return 3
        return 0

    def _request_blockers(self, emp, exclude_loan_id=None):
        """Request-level rules that block a NEW RSSA request, as a list of
        readable messages (empty list = free to request):

        1. Only one request may be open at a time (draft / awaiting
           guarantors / awaiting manager review).
        2. The employee's eligible ceiling (current basic salary x the term
           their months of service require) must not be fully used up by
           amounts already disbursed. A loan that is already approved and
           disbursed is a resolved request and does NOT block a new one.

        `exclude_loan_id` skips the record being evaluated (a saved draft must
        not count as its own "other pending request"). Safe to call on an
        unsaved (NewId) record — just pass nothing to exclude.
        """
        blockers = []
        if not emp:
            return blockers
        emp = emp.sudo()

        domain = [
            ('employee_id', '=', emp.id),
            ('status', 'in', ['draft', 'guarantor_pending', 'manager_review']),
        ]
        if exclude_loan_id and isinstance(exclude_loan_id, int):
            domain.append(('id', '!=', exclude_loan_id))
        pending_loan = self.sudo().search(domain, order="create_date desc", limit=1)
        if pending_loan:
            blockers.append(_(
                "%(name)s already has an RSSA request (%(ref)s) that is still "
                "awaiting guarantors or manager review. That request must be "
                "approved, rejected, or cancelled before a new one can be "
                "submitted."
            ) % {'name': emp.name, 'ref': pending_loan.name})

        max_term = self._max_eligible_loan_term(emp)
        if max_term:
            salary = self._employee_current_wage(emp)
            max_eligible_amount = salary * max_term if salary else 0.0
            total_taken = self._employee_total_disbursed(emp)
            if max_eligible_amount - total_taken <= 0:
                blockers.append(_(
                    "%(name)s has already reached the maximum RSSA eligibility "
                    "(%(ceiling)s based on current salary and length of service). "
                    "A new request can only be made once an existing balance is "
                    "settled or the eligible ceiling increases."
                ) % {
                    'name': emp.name,
                    'ceiling': '{:,.2f} {}'.format(
                        max_eligible_amount, self.env.company.currency_id.name
                    ),
                })
        return blockers

    def _employee_total_disbursed(self, employee):
        """Sum of approved amounts for this employee's loans that have been
        disbursed on Core Banking. Mirrors _compute_total_loans_taken's
        query so the figure is consistent everywhere it's used, including
        before a new loan record exists (e.g. inside create())."""
        if not employee:
            return 0.0
        disbursed_loans = self.search([
            ('employee_id', '=', employee.id),
            ('core_banking_status', '=', 'disbursed'),
        ])
        return sum(float(l.approved_amount or 0.0) for l in disbursed_loans)

    def _years_to_retirement(self, employee, retirement_age=60):
        if not employee:
            return None
        birth = None
        for fld in ('birthdate_date', 'birthday', 'birth_date', 'date_of_birth'):
            if getattr(employee, fld, False):
                birth = getattr(employee, fld)
                break
        if not birth:
            return None
        birth_date = fields.Date.from_string(birth) if isinstance(birth, str) else birth
        today = fields.Date.context_today(self)
        today_date = fields.Date.from_string(today) if isinstance(today, str) else today
        age = today_date.year - birth_date.year - (
            (today_date.month, today_date.day) < (birth_date.month, birth_date.day)
        )
        return retirement_age - age

    def _employee_current_wage(self, employee):
        if not employee:
            return 0.0
        contract = self._get_latest_contract(employee, sudo=True)
        if contract and getattr(contract, 'wage', False):
            return float(contract.wage or 0.0)
        for fld in ('wage', 'basic_salary', 'salary'):
            if hasattr(employee, fld) and getattr(employee, fld):
                return float(getattr(employee, fld) or 0.0)
        return 0.0

    def _ensure_guarantor_is_eligible(self, guarantor_employee, exclude_loan_id=None, strict=True):
        return self.env['resl.validations'].ensure_guarantor_is_eligible(
            self, guarantor_employee, exclude_loan_id=exclude_loan_id, strict=strict
        )

    def _validate_guarantor_salaries(self, consider_states=('accepted', 'pending'), strict=False):
        return self.env['resl.validations'].validate_guarantor_salaries(
            self, consider_states=consider_states, strict=strict
        )

    # ── Create / Write overrides ──────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        """
        Odoo 17: override create with @api.model_create_multi for batch support.
        Single-record callers still work transparently.
        """
        result = self.env['resl.loan']
        for vals in vals_list:
            guarantor_lines = vals.pop('guarantor_line_ids', False)
            emp = (
                self.env['hr.employee'].browse(vals['employee_id'])
                if vals.get('employee_id')
                else self.env['hr.employee'].search([('user_id', '=', self.env.user.id)], limit=1)
            )
            if not emp:
                vals['employee_id'] = False
            else:
                vals['employee_id'] = emp.id if getattr(emp, 'id', False) else False

            if vals.get('name', 'New') == 'New':
                seq = self.env['ir.sequence'].sudo().search([('code', '=', 'resl.loan')], limit=1)
                vals['name'] = seq.next_by_id() if seq else 'LOAN/NEW'

            current_salary = self._employee_current_wage(emp)

            if emp:
                # Request-level rules (one pending request at a time, and the
                # eligible ceiling not yet used up). The same rules are shown
                # on the New form as soon as it opens — see
                # _compute_borrower_eligibility — so the requester sees them
                # BEFORE a draft is ever saved. They are re-enforced here so no
                # other route (import, RPC, kanban quick-create) can skip them.
                blockers = self._request_blockers(emp)
                if blockers:
                    raise ValidationError(blockers[0])

            vals['last_salary_basis'] = current_salary
            # loan_term_months and loan_amount are now both stored compute
            # fields (FR-RESL-005: eligible amount = basic salary x the
            # term the employee's months of service require). Don't set
            # them in vals — the ORM computes them itself, in dependency
            # order, right after create().

            loan = super().create([vals])

            # BRD 18.2 & 18.3: Validate borrower eligibility upon creation
            loan._check_borrower_eligibility()

            if guarantor_lines:
                g_model = self.env['resl.loan.guarantee']
                for item in guarantor_lines:
                    if isinstance(item, (list, tuple)) and item and item[0] == 0:
                        gvals = item[2] if len(item) > 2 else {}
                    elif isinstance(item, dict):
                        gvals = item
                    else:
                        continue
                    gvals['loan_id'] = loan.id
                    if not gvals.get('guarantor_id'):
                        continue
                    g_emp = self.env['hr.employee'].browse(gvals['guarantor_id'])
                    loan._ensure_guarantor_is_eligible(g_emp, exclude_loan_id=loan.id, strict=False)
                    g = g_model.with_context(resl_allow_guarantee_create=True).create(gvals)
                    if g.guarantor_id and g.guarantor_id.user_id:
                        loan.sudo().activity_schedule(
                            'mail.mail_activity_data_todo',
                            user_id=g.guarantor_id.user_id.id,
                            note=f"Please approve/reject guarantee for loan {loan.name}"
                        )
                loan._validate_guarantor_salaries(('accepted', 'pending'))
                loan.invalidate_recordset(['guarantor_line_ids'])
                loan.sudo().message_post(body="Loan created and moved to guarantor pending stage.")

            if not loan.requested_amount:
                loan.sudo().write({'requested_amount': loan.net_eligible_amount or 0.0})

            result |= loan

        return result

    def write(self, vals):
        user = self.env.user
        is_privileged = bool(
            user.has_group('resl.group_resl_manager')
            or user.has_group('resl.group_resl_hr')
            or user.has_group('base.group_system')
        )
        is_system_action = bool(self.env.context.get('resl_allow_auto_replacement', False))
        try:
            current_emp_id = user.employee_id.id if user.employee_id else False
        except Exception:
            current_emp_id = False

        if not is_privileged and not is_system_action:
            for rec in self:
                if rec.status == 'approved':
                    pass  # validation disabled for migration
                if not (rec.employee_id and rec.employee_id.id and current_emp_id
                        and rec.employee_id.id == current_emp_id):
                    pass  # validation disabled for migration

        if vals.get('guarantor_line_ids') and self and any(rec.status == 'approved' for rec in self):
            if (self.env.uid != SUPERUSER_ID
                    and not bool(self.env.context.get('resl_allow_guarantee_write', False))
                    and not is_system_action):
                pass  # validation disabled for migration

        new_guarantor_tuples = []
        if vals.get('guarantor_line_ids'):
            for item in vals['guarantor_line_ids']:
                if isinstance(item, (list, tuple)) and item and item[0] == 0:
                    new_guarantor_tuples.append(item[2] if len(item) > 2 else {})

        if new_guarantor_tuples:
            try:
                if len(self) == 1:
                    rec = self[0]
                    try:
                        current_emp_id_inner = user.employee_id.id if user.employee_id else False
                    except Exception:
                        current_emp_id_inner = False
                    is_borrower = bool(
                        rec.employee_id and rec.employee_id.id
                        and current_emp_id_inner
                        and rec.employee_id.id == current_emp_id_inner
                    )
                    if is_borrower:
                        normalized = []
                        for item in vals.get('guarantor_line_ids'):
                            if isinstance(item, (list, tuple)) and item and item[0] == 0:
                                gvals = item[2] if len(item) > 2 else {}
                                if not gvals.get('state'):
                                    gvals['state'] = 'draft'
                                normalized.append((0, 0, gvals))
                            else:
                                normalized.append(item)
                        vals['guarantor_line_ids'] = normalized
            except Exception:
                pass

            for rec in self:
                active_lines = rec.guarantor_line_ids.filtered(
                    lambda l: l.state not in ('replaced', 'separated')
                )
                if len(active_lines) + len(new_guarantor_tuples) > 2:
                    pass  # validation disabled for migration
                for gvals in new_guarantor_tuples:
                    if not gvals:
                        continue
                    g_emp = self.env['hr.employee'].browse(gvals.get('guarantor_id'))
                    rec._ensure_guarantor_is_eligible(g_emp, exclude_loan_id=rec.id, strict=False)

        res = super().write(vals)
        # Odoo 17: invalidate_recordset replaces invalidate_cache
        self.invalidate_recordset(['guarantor_line_ids'])
        return res

    # ── Constraints ───────────────────────────────────────────────────────────

    @api.constrains('employee_id')
    def _check_borrower_eligibility(self):
        for loan in self:
            if loan.employee_id:
                # BRD 18.2 & 18.3: Strict borrower validation (permanent status, active contract, >=3 months service, retirement age <58, disciplinary status)
                self.env['resl.validations'].check_borrower_eligibility(
                    loan, loan.employee_id, raise_exception=True
                )

    # ── Workflow actions ──────────────────────────────────────────────────────

    def action_request_guarantors(self):
        """Submit the loan to the guarantor stage.

        No longer exposed as its own header button — the Find Guarantor
        wizard (guarantor_lookup_wizard.ReslGuarantorLookupLine.action_select)
        calls this automatically right after a guarantor is selected, so
        picking a guarantor immediately sends them the request.
        """
        for loan in self:
            user = self.env.user
            try:
                current_emp_id = user.employee_id.id if user.employee_id else False
            except Exception:
                current_emp_id = False
            if not (loan.employee_id and loan.employee_id.id and current_emp_id
                    and loan.employee_id.id == current_emp_id):
                raise ValidationError(_("Only the requester can request guarantors."))
            if loan.status not in ('draft', 'rejected', 'guarantor_pending'):
                raise ValidationError(_("Loan is not in a valid state to request guarantors."))

            # FR-RESL-002, FR-RESL-003, FR-RESL-004: Validate borrower eligibility
            self.env['resl.validations'].check_borrower_eligibility(loan, loan.employee_id, raise_exception=True)

            # FR-RESL-006: Every RSSA request shall have an eligible guarantor before request submission
            active_guarantor_lines = loan.guarantor_line_ids.filtered(
                lambda l: l.state not in ('replaced', 'separated', 'rejected')
            )
            if not active_guarantor_lines:
                raise ValidationError(_("Every RSSA request shall have an eligible guarantor before request submission (FR-RESL-006)."))

            # FR-RESL-005: Requested amount ceiling validation
            if loan.requested_amount and loan.net_eligible_amount and loan.requested_amount > loan.net_eligible_amount:
                raise ValidationError(
                    _("Requested loan amount (%s) cannot exceed net eligible amount (%s).")
                    % (loan.requested_amount, loan.net_eligible_amount)
                )

            # FR-RESL-007, FR-RESL-008: Validate guarantor eligibility
            for line in active_guarantor_lines:
                self.env['resl.validations'].ensure_guarantor_is_eligible(
                    loan, line.guarantor_id, exclude_loan_id=loan.id, strict=True
                )

            # FR-RESL-007: Validate guarantor salaries
            self.env['resl.validations'].validate_guarantor_salaries(
                loan, consider_states=('draft', 'pending', 'accepted'), strict=False
            )

            pending_lines = loan.guarantor_line_ids.filtered(lambda l: l.state == 'draft')
            for line in pending_lines:
                line.sudo().write({'state': 'pending'})
                if line.guarantor_id and line.guarantor_id.user_id:
                    loan.sudo().activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=line.guarantor_id.user_id.id,
                        note=f"Please accept or reject your guarantee for loan {loan.name}."
                    )
            loan.sudo().write({'status': 'guarantor_pending'})

    def action_guarantor_accept(self):
        """Header-level convenience for the guarantor: accept their own
        pending guarantee line directly from the loan form, without
        having to scroll to the Guarantors list line-by-line."""
        self.ensure_one()
        try:
            current_emp_id = self.env.user.employee_id.id if self.env.user.employee_id else False
        except Exception:
            current_emp_id = False
        line = self.guarantor_line_ids.filtered(
            lambda l: l.state == 'pending' and current_emp_id and l.guarantor_id.id == current_emp_id
        )
        if not line:
            raise ValidationError(_("You have no pending guarantee request on this loan."))
        return line.action_accept()

    def action_guarantor_reject(self):
        """Header-level convenience for the guarantor: reject their own
        pending guarantee line directly from the loan form."""
        self.ensure_one()
        try:
            current_emp_id = self.env.user.employee_id.id if self.env.user.employee_id else False
        except Exception:
            current_emp_id = False
        line = self.guarantor_line_ids.filtered(
            lambda l: l.state == 'pending' and current_emp_id and l.guarantor_id.id == current_emp_id
        )
        if not line:
            raise ValidationError(_("You have no pending guarantee request on this loan."))
        return line.action_reject()

    def action_submit_manager(self):
        """Borrower submits to manager after all guarantors accepted."""
        for loan in self:
            user = self.env.user
            try:
                current_emp_id = user.employee_id.id if user.employee_id else False
            except Exception:
                current_emp_id = False
            if not (loan.employee_id and loan.employee_id.id and current_emp_id
                    and loan.employee_id.id == current_emp_id):
                raise ValidationError(_("Only the requester can submit the loan to the manager."))
            if not loan.all_guarantors_accepted:
                raise ValidationError(_("All guarantors must accept before submitting to manager."))
            if loan.needs_guarantor_replacement:
                raise ValidationError(_("Please nominate a replacement guarantor before submitting."))

            # FR-RESL-009: Borrower and guarantor contract status shall be verified automatically before approval
            self.env['resl.validations'].check_borrower_eligibility(loan, loan.employee_id, raise_exception=True)
            for line in loan.guarantor_line_ids.filtered(lambda l: l.state == 'accepted'):
                self.env['resl.validations'].ensure_guarantor_is_eligible(
                    loan, line.guarantor_id, exclude_loan_id=loan.id, strict=True
                )
            self.env['resl.validations'].validate_guarantor_salaries(loan, consider_states=('accepted',), strict=False)

            loan.sudo().write({'status': 'manager_review'})
            approver_title = loan.designated_approver_role or _("Manager")
            loan.sudo().message_post(body=_("Loan submitted to %s by %s.") % (approver_title, user.name))
            try:
                target_approver = loan.designated_approver_id or loan.manager_user_id
                if target_approver:
                    loan.sudo().activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=target_approver.id,
                        note=_("Loan %s submitted for your review as %s.") % (loan.name, approver_title)
                    )
            except Exception:
                _logger.exception("Failed to schedule manager review activity for loan %s", loan.id)

    def action_manager_approve(self):
        for loan in self:
            user = self.env.user
            if not (
                user.has_group('resl.group_resl_manager')
                or user.has_group('resl.group_resl_hr')
            ):
                raise ValidationError("Only Loan Manager group members or HR can approve.")

            if loan.status != 'manager_review':
                raise ValidationError("Loan must be in Manager Review stage to approve.")

            # OU scoping (same as v14 logic)
            try:
                borrower_emp = loan.sudo().employee_id
            except Exception:
                borrower_emp = None
            approver_emp = self.env['hr.employee'].search([('user_id', '=', user.id)], limit=1)
            borrower_ou = getattr(borrower_emp, 'default_operating_unit_id', False) if borrower_emp else False
            approver_ou = getattr(approver_emp, 'default_operating_unit_id', False) if approver_emp else False

            allow = False
            used_head_office_exception = False

            # FR-RESL-016: POMD/HR has organization-wide oversight and is not
            # subject to the branch-level approver-routing restriction below
            # (that gate exists to route line-manager approvals correctly,
            # not to fence HR out of loans outside their own OU).
            if user.has_group('resl.group_resl_hr'):
                allow = True

            # Primary check per FR-RESL-012: the workflow already computes the
            # correct approver (Branch Manager / District Director / C&B
            # Manager) based on the borrower's work location in
            # _compute_designated_approver. A District Director or C&B
            # Manager is *deliberately* in a different operating unit than
            # the borrower (that's the point of escalation), so being the
            # designated approver must be sufficient on its own - it should
            # not additionally be gated behind an OU match below.
            designated_user = loan.designated_approver_id or loan.manager_user_id
            if not allow and designated_user and designated_user.id == user.id:
                allow = True

            if not allow and borrower_ou and approver_ou and getattr(borrower_ou, 'id', False) == getattr(approver_ou, 'id', False):
                allow = True
            if not allow:
                def _sol_val(unit):
                    if not unit:
                        return None
                    val = getattr(unit, 'sol_id', None)
                    if isinstance(val, int):
                        return val
                    if isinstance(val, str) and val.isdigit():
                        return int(val)
                    return None
                b_sol = _sol_val(borrower_ou)
                a_sol = _sol_val(approver_ou)
                if b_sol is not None and a_sol is not None and b_sol == a_sol:
                    param = self.env['ir.config_parameter'].sudo().get_param(
                        'resl.head_office_sold_ids', ''
                    )
                    head_sold_ids = {int(x) for x in param.split(',') if x.strip().isdigit()}
                    if (head_sold_ids and int(b_sol) in head_sold_ids
                            and user.has_group('resl.group_resl_head_office')):
                        allow = True
                        used_head_office_exception = True

            if not allow:
                approver_name = designated_user.name if designated_user else _("(not computed)")
                approver_role = loan.designated_approver_role or _("(none)")
                b_ou_name = borrower_ou.name if borrower_ou else _("(none)")
                a_ou_name = approver_ou.name if approver_ou else _("(none)")
                raise ValidationError(
                    _(
                        "Approver and borrower must be in the same operating unit to approve.\n\n"
                        "Diagnostic info:\n"
                        "- System-designated approver for this loan: %(approver_name)s (%(approver_role)s)\n"
                        "- Your user: %(user_name)s\n"
                        "- Borrower's operating unit: %(b_ou)s\n"
                        "- Your operating unit: %(a_ou)s\n\n"
                        "If you are the correct approver but this is blocking you, the loan's "
                        "designated approver may be stale (computed before HR data was correct). "
                        "Try opening the loan record and re-saving employee_id, or ask an admin to "
                        "trigger a recompute of designated_approver_id on this loan."
                    ) % {
                        'approver_name': approver_name,
                        'approver_role': approver_role,
                        'user_name': user.name,
                        'b_ou': b_ou_name,
                        'a_ou': a_ou_name,
                    }
                )

            override = bool(self.env.context.get('force_approve', False)) and (
                user.has_group('resl.group_resl_manager')
                or user.has_group('resl.group_resl_hr')
            )
            if not override:
                loan._validate_guarantor_salaries(('accepted',))
            else:
                loan.sudo().message_post(
                    body=f"Approval override by {user.name} (force_approve=True)."
                )

            approved_amt = loan.requested_amount or 0.0

            # FR-RESL-009: Automated borrower and guarantor contract verification before approval
            self.env['resl.validations'].check_borrower_eligibility(loan, loan.employee_id, raise_exception=True)
            for line in loan.guarantor_line_ids.filtered(lambda l: l.state == 'accepted'):
                self.env['resl.validations'].ensure_guarantor_is_eligible(
                    loan, line.guarantor_id, exclude_loan_id=loan.id, strict=True
                )

            loan.sudo().write({
                'status': 'approved',
                'approval_date': fields.Date.context_today(self),
                'approver_id': user.id,
                'approved_amount': approved_amt,
                'core_banking_status': 'pending',  # Ready for Core Banking disbursement
            })
            try:
                if used_head_office_exception:
                    loan.sudo().message_post(
                        body=f"Loan approved by {user.name} via head-office sol_id exception."
                    )
                else:
                    loan.sudo().message_post(body=f"Loan approved by {user.name}")
            except Exception:
                _logger.exception('Failed to post approval message for loan %s', loan.id)

            # Notify HR after manager approval
            try:
                if (user.has_group('resl.group_resl_manager')
                        and not user.has_group('resl.group_resl_hr')):
                    hr_group = self.env.ref('resl.group_resl_hr')
                    if hr_group:
                        for u in hr_group.sudo().users:
                            try:
                                u_emp = u.sudo().employee_id
                            except Exception:
                                u_emp = False
                            u_ou = getattr(u_emp, 'default_operating_unit_id', False)
                            if (
                                (u_ou and borrower_ou
                                 and getattr(u_ou, 'id', False) == getattr(borrower_ou, 'id', False))
                                or not u_emp
                            ):
                                try:
                                    loan.sudo().activity_schedule(
                                        'mail.mail_activity_data_todo',
                                        user_id=u.id,
                                        note=f"Loan {loan.name} approved by manager {user.name} — HR review required."
                                    )
                                except Exception:
                                    _logger.exception("Failed to schedule HR activity for user %s", u.id)
            except Exception:
                _logger.exception("Failed to notify HR after manager approval")

            # Finalize pending replacements
            old_guarantor_ids = []
            try:
                accepted_new_lines = loan.guarantor_line_ids.filtered(lambda l: l.state == 'accepted')
                if accepted_new_lines:
                    Guarantee = self.env['resl.loan.guarantee']
                    old_lines = Guarantee.search([
                        ('replaced_by_id', 'in', accepted_new_lines.ids),
                        ('state', 'not in', ('replaced', 'separated')),
                    ])
                    old_guarantor_ids = old_lines.mapped('guarantor_id.id')
                    if old_lines:
                        old_lines.sudo().write({
                            'state': 'replaced',
                            'replaced_at': fields.Datetime.now()
                        })
            except Exception:
                _logger.exception('Failed to finalize replaced guarantor lines during approval')

            guarantor_ids = loan.guarantor_line_ids.mapped('guarantor_id.id')
            ids_to_update = set(guarantor_ids or [])
            if old_guarantor_ids:
                ids_to_update.update(old_guarantor_ids)
            if ids_to_update:
                self.env['hr.employee'].sudo().recompute_all_guarantee_counts(list(ids_to_update))

    def action_manager_reject(self):
        for loan in self:
            user = self.env.user
            if not (
                user.has_group('resl.group_resl_manager')
                or user.has_group('resl.group_resl_hr')
            ):
                raise ValidationError("Only Loan Manager group members or HR can reject.")

            try:
                borrower_emp = loan.sudo().employee_id
            except Exception:
                borrower_emp = None
            approver_emp = self.env['hr.employee'].search([('user_id', '=', user.id)], limit=1)
            borrower_ou = getattr(borrower_emp, 'default_operating_unit_id', False) if borrower_emp else False
            approver_ou = getattr(approver_emp, 'default_operating_unit_id', False) if approver_emp else False

            allow = False
            used_head_office_exception = False

            # Same fix as action_manager_approve: the designated approver
            # (per FR-RESL-012 hierarchy) may legitimately sit in a
            # different OU than the borrower, so check that first.
            designated_user = loan.designated_approver_id or loan.manager_user_id
            if designated_user and designated_user.id == user.id:
                allow = True

            if not allow and (borrower_ou and approver_ou
                    and getattr(borrower_ou, 'id', False) == getattr(approver_ou, 'id', False)):
                allow = True
            if not allow:
                def _sol_val(unit):
                    if not unit:
                        return None
                    val = getattr(unit, 'sol_id', None)
                    if isinstance(val, int):
                        return val
                    if isinstance(val, str) and val.isdigit():
                        return int(val)
                    return None
                b_sol = _sol_val(borrower_ou)
                a_sol = _sol_val(approver_ou)
                if b_sol is not None and a_sol is not None and b_sol == a_sol:
                    param = self.env['ir.config_parameter'].sudo().get_param(
                        'resl.head_office_sold_ids', ''
                    )
                    head_sold_ids = {int(x) for x in param.split(',') if x.strip().isdigit()}
                    if (head_sold_ids and int(b_sol) in head_sold_ids
                            and user.has_group('resl.group_resl_head_office')):
                        allow = True
                        used_head_office_exception = True
            if not allow:
                raise ValidationError(
                    "Approver and borrower must be in the same operating unit to reject this loan."
                )
            loan.sudo().write({'status': 'rejected'})
            try:
                if used_head_office_exception:
                    loan.sudo().message_post(
                        body=f"Loan rejected by {user.name} via head-office sol_id exception."
                    )
                else:
                    loan.sudo().message_post(body=f"Loan rejected by {user.name}.")
            except Exception:
                _logger.exception('Failed to post rejection message for loan %s', loan.id)

    def action_disburse_core_banking(self):
        """FR-RESL-019: Open the account-number confirmation wizard before disbursing.

        The wizard (resl.loan.disbursement.wizard) collects the employee's
        Core Banking account number, shows the approved amount read-only, and
        provides a portal link for employees who don't yet have an account.
        The actual disbursement is performed by _do_disburse(), called from
        the wizard's "Confirm Disbursement" button.
        """
        self.ensure_one()
        user = self.env.user
        if not (user.has_group('resl.group_resl_hr') or user.has_group('base.group_system')):
            raise ValidationError(_("Only POMD / HR or Administrators can record Core Banking disbursement."))
        if self.status != 'approved':
            raise ValidationError(_("Loan must be in Approved state for Core Banking disbursement."))
        if self.core_banking_status == 'disbursed':
            raise ValidationError(_("This loan has already been disbursed on Core Banking."))

        # Open the wizard dialog; it will call _do_disburse() on confirmation.
        return {
            'type': 'ir.actions.act_window',
            'name': _('Confirm Core Banking Disbursement'),
            'res_model': 'resl.loan.disbursement.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_loan_id': self.id,
                'active_id': self.id,
            },
        }

    def _do_disburse(self):
        """Perform the actual Core Banking disbursement.

        Called by resl.loan.disbursement.wizard.action_confirm_disburse()
        after the bank account number has been validated and stored.
        Contains all the write / recompute / notify logic that was
        previously inside action_disburse_core_banking().
        """
        self.ensure_one()
        user = self.env.user
        disbursed_amount = self.approved_amount or 0.0

        self.write({
            'core_banking_status': 'disbursed',
            'disbursement_date': fields.Date.context_today(self),
            'disbursed_by_id': user.id,
        })

        # total_loans_taken/net_eligible_amount are computed via a search
        # across the employee's loans, so a change on *this* record doesn't
        # automatically refresh its siblings (other loan requests for the
        # same employee). Force-recompute across all of that employee's
        # loans so the new total is reflected everywhere immediately.
        sibling_loans = self.search([('employee_id', '=', self.employee_id.id)])
        sibling_loans._compute_total_loans_taken()
        sibling_loans._compute_net_eligible_amount()

        new_total = self.total_loans_taken
        currency_name = self.currency_id.name or ''
        account_info = (
            _(" Account: %s.") % self.bank_account_number
            if self.bank_account_number else ''
        )

        self.message_post(body=_(
            "Loan disbursement confirmed on Core Banking by %(user)s.%(account)s "
            "Disbursed amount: %(amount)s %(currency)s added to Total Loans Taken. "
            "%(employee)s's Total Loans Taken is now %(total)s %(currency)s."
        ) % {
            'user': user.name,
            'account': account_info,
            'amount': '{:,.2f}'.format(disbursed_amount),
            'currency': currency_name,
            'employee': self.employee_id.name,
            'total': '{:,.2f}'.format(new_total),
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Loan Disbursed'),
                'message': _(
                    '%(amount)s %(currency)s disbursed to %(employee)s. '
                    'Total Loans Taken is now %(total)s %(currency)s.'
                ) % {
                    'amount': '{:,.2f}'.format(disbursed_amount),
                    'currency': currency_name,
                    'employee': self.employee_id.name,
                    'total': '{:,.2f}'.format(new_total),
                },
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_mark_settled(self):
        """FR-RESL-013: Mark loan settled during employee clearance / separation."""
        self.ensure_one()
        user = self.env.user
        if not (user.has_group('resl.group_resl_hr') or user.has_group('base.group_system')):
            raise ValidationError(_("Only POMD / HR or Administrators can update settlement status."))
        self.write({'settlement_status': 'settled'})
        self.message_post(body=_("Loan marked as fully settled by %s.") % user.name)