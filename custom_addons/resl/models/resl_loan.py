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
    _inherit = ['mail.thread', 'mail.activity.mixin', 'resl.soft.delete.mixin']

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
        string='Previous Loan Amount',
        compute="_compute_loan_amount", store=True,
        currency_field='currency_id', readonly=True,
        help="Total of the employee's loans already disbursed BEFORE this request. "
             "0 on the employee's first request; from the second request on it equals "
             "the previous total loans taken. Fixed when the request is created.",
    )
    eligible_amount = fields.Monetary(
        string='Eligible Ceiling',
        compute="_compute_eligible_amount", store=True,
        currency_field='currency_id', readonly=True,
        help="Maximum RSSA amount: basic salary x loan term (3 or 6).",
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
        help="True when the request has all the guarantors it can/needs: one "
             "guarantor whose salary covers the borrower, or two guarantors. "
             "Find Guarantor is hidden while this is true and reappears when it "
             "is false again (e.g. after a rejection, or while a second "
             "guarantor is still needed).",
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
    # Borrower's work unit (operating unit), STORED so record rules can filter
    # on it in SQL. Refreshed by _compute_designated_approver, which also runs
    # live whenever a loan is opened / approved and from the routing cron.
    operating_unit_id = fields.Many2one(
        'operating.unit', string="Work Unit",
        compute='_compute_designated_approver', store=True, index=True,
        help="Operating unit of the borrower. Approvers / managers only see "
             "loans of their own work unit(s); Head Office roles see all.",
    )
    designated_approver_id = fields.Many2one(
        'res.users', string="Designated Approver",
        compute='_compute_designated_approver', store=True
    )
    designated_approver_role = fields.Char(
        string="Approver Role",
        compute='_compute_designated_approver', store=True
    )
    # Stage 2 of the chain: who DISBURSES the loan once it is approved.
    #   Branch / Sub-branch / Service Center -> Accountant of the borrower's OU
    #   District / Regional Office           -> RESL District (group)
    # Empty for Head Office / other (those keep the HR Auditor -> HR
    # Accountant hand-off).
    disbursement_officer_id = fields.Many2one(
        'res.users', string="Disbursement Officer",
        compute='_compute_designated_approver', store=True,
        help="The person responsible for disbursing this loan after it is approved.",
    )
    disbursement_officer_role = fields.Char(
        string="Disbursement Role",
        compute='_compute_designated_approver', store=True,
    )
    can_disburse = fields.Boolean(
        compute='_compute_can_disburse', store=False,
        help="True when the logged-in user is allowed to disburse this loan.",
    )
    can_approve = fields.Boolean(
        compute='_compute_can_approve', store=False,
        help="True when the logged-in user is the designated approver for this loan (or holds Loan Manager/HR override).",
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
    cbs_limit_set = fields.Boolean(
        string="OD Limit Set At Account Opening",
        copy=False, readonly=True, default=False,
        help="True when the sanction limit for this request was already set by the "
             "open-account call (new account), so extend-od-limit is skipped at disbursement.",
    )
    bank_account_number = fields.Char(
        string="Bank Account Number",
        tracking=True,
        help="Core Banking account number used for disbursement.",
    )

    # HR Auditor -> HR Accountant handoff (FR-RESL-020). The Auditor role
    # is deliberately read-only everywhere else (see ir.model.access.csv /
    # resl_rules.xml): it cannot approve, edit, or disburse anything. This
    # is the one exception — a lightweight "please disburse this" nudge
    # that raises an activity for HR Accountant, it does not itself move
    # money or change core_banking_status. Only HR Accountant recording
    # the disbursement (action_disburse_core_banking / _do_disburse)
    # actually changes core_banking_status to 'disbursed'.
    disbursement_requested = fields.Boolean(
        string="Disbursement Requested",
        readonly=True, copy=False,
        help="Set once an HR Auditor has asked HR Accountant to disburse "
             "this approved loan on Core Banking.",
    )
    disbursement_requested_by_id = fields.Many2one(
        'res.users', string="Disbursement Requested By",
        readonly=True, copy=False,
    )
    disbursement_requested_date = fields.Datetime(
        string="Disbursement Requested On",
        readonly=True, copy=False,
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
    guarantor_second_notice = fields.Char(
        string="Second Guarantor Notice",
        compute='_compute_guarantor_second_notice',
        help="Explains the two-guarantor rule: shown while a second guarantor is "
             "still needed, and while the request waits for both to accept.",
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
    def _compute_eligible_amount(self):
        for loan in self:
            salary = loan._employee_current_wage(loan.employee_id.sudo())
            # FR-RESL-005 (term-based ceiling): eligible amount = basic salary
            # x the chosen loan term (3 or 6 months). Until a term is picked,
            # the ceiling is 0 so the user is prompted to choose one first.
            term = int(loan.loan_term_months) if loan.loan_term_months else 0
            loan.eligible_amount = salary * term if salary and term else 0.0

    @api.depends('employee_id')
    def _compute_loan_amount(self):
        """Previous Loan Amount: total of this employee's loans disbursed
        BEFORE this request (earlier records only, never this loan itself).
        0 on the first request; frozen once the request exists."""
        Loan = self.env['resl.loan'].sudo()
        for loan in self:
            if not loan.employee_id:
                loan.loan_amount = 0.0
                continue
            domain = [
                ('employee_id', '=', loan.employee_id.id),
                ('core_banking_status', '=', 'disbursed'),
            ]
            own_id = loan._origin.id or (loan.id if isinstance(loan.id, int) else False)
            if own_id:
                domain.append(('id', '<', own_id))
            loan.loan_amount = sum(float(l.approved_amount or 0.0) for l in Loan.search(domain))

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

    @api.depends('guarantor_line_ids.state', 'guarantor_line_ids.guarantor_id', 'employee_id')
    def _compute_has_active_guarantor(self):
        """True when no further guarantor can/needs to be added: either one
        guarantor whose salary covers the borrower, or two guarantors. While the
        only guarantor's salary is NOT enough ('needs_second'), this stays False
        so Find Guarantor remains available for the second one."""
        Validations = self.env['resl.validations']
        for loan in self:
            loan.has_active_guarantor = bool(loan.employee_id) and \
                Validations.guarantor_slot_state(loan) == 'full'

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

    def _find_role_employee(self, include_keywords, ou=None, exclude_employee_ids=None,
                             exclude_keywords=None, match_any_ou=False):
        """Find one hr.employee (with a linked user) whose Job Position title
        matches one of `include_keywords` (case-insensitive substring match),
        optionally restricted to operating unit `ou`, and never matching any
        id in `exclude_employee_ids` or any title in `exclude_keywords`.

        Used to resolve the current holder of a named approval role (e.g.
        "Manager", "Director", "HO Approver") from job titles, since the
        role is defined by job position rather than by a fixed user.
        Returns an (possibly empty) hr.employee recordset, limit 1.
        """
        Employee = self.env['hr.employee'].sudo()
        domain = [('user_id', '!=', False)]
        if ou:
            # match_any_ou: a role holder that COVERS several operating units
            # (e.g. a Division Manager over many districts) is listed under
            # "Operating Units" (operating_unit_ids), and their own default
            # OU is often a different one. Accept either.
            if match_any_ou and 'operating_unit_ids' in Employee._fields:
                domain += ['|',
                           ('default_operating_unit_id', '=', ou.id),
                           ('operating_unit_ids', 'in', [ou.id])]
            else:
                domain.append(('default_operating_unit_id', '=', ou.id))
        if exclude_employee_ids:
            domain.append(('id', 'not in', list(exclude_employee_ids)))

        # Match the Job Position name OR the free-text Job Title, so a role
        # holder is found whichever of the two HR filled in.
        leaves = []
        for kw in include_keywords:
            leaves.append(('job_id.name', 'ilike', kw))
            if 'job_title' in Employee._fields:
                leaves.append(('job_title', 'ilike', kw))
        if len(leaves) > 1:
            domain += ['|'] * (len(leaves) - 1) + leaves
        elif leaves:
            domain += leaves

        for kw in (exclude_keywords or []):
            domain.append(('job_id.name', 'not ilike', kw))

        return Employee.search(domain, limit=1)

    def _find_role_employee_by_group(self, group_xmlid, ou=None, exclude_employee_ids=None,
                                     match_any_ou=False):
        """Find one hr.employee holding the given security group, optionally
        restricted to operating unit `ou`, never matching any id in
        `exclude_employee_ids`.

        HO Approver and HR Approver are NOT job titles: they are assigned to
        a user via the "Staff Loan (RESL)" role selector on Settings ->
        Users (res.groups group_resl_ho_approver / group_resl_hr_senior;
        see views/resl_groups.xml). _find_role_employee's job-title ilike
        matching can never find someone assigned that way, which is why
        routing was silently falling through to the reporting-line fallback
        (or finding nobody) even when an HO Approver was correctly assigned
        in Settings. This looks the person up the same way the selector
        assigns them: by group membership.
        Returns a (possibly empty) hr.employee recordset, limit 1.
        """
        try:
            group = self.env.ref(group_xmlid)
        except ValueError:
            return self.env['hr.employee']
        Employee = self.env['hr.employee'].sudo()
        # Odoo 19 renamed res.groups' "users" field to user_ids (direct
        # members) / all_user_ids (direct + via an implying group).
        domain = [('user_id', 'in', group.all_user_ids.ids)]
        if ou:
            if match_any_ou and 'operating_unit_ids' in Employee._fields:
                domain += ['|',
                           ('default_operating_unit_id', '=', ou.id),
                           ('operating_unit_ids', 'in', [ou.id])]
            else:
                domain.append(('default_operating_unit_id', '=', ou.id))
        if exclude_employee_ids:
            domain.append(('id', 'not in', list(exclude_employee_ids)))
        return Employee.search(domain, limit=1)

    @api.depends('employee_id', 'employee_id.default_operating_unit_id', 'employee_id.parent_id',
                 'employee_id.job_id', 'employee_id.user_id')
    def _compute_designated_approver(self):
        """
        FR-RESL-012 (v2): approval routing is driven strictly by the
        borrower's OWN operating unit's work_unit_type (the same
        work_unit_type visible via `SELECT work_unit_type FROM
        public.operating_unit`), with a fixed 2-level chain per tier. The
        level-1 role is always checked WITHIN the borrower's own operating
        unit; the level-2 role only ever comes into play when the borrower
        themselves holds the level-1 role, so that nobody ends up as the
        approver of their own request:

          Branch / Sub-branch / Service Center:
              1. Manager                    (always this work unit's Manager)
              2. Accountant (Disbursement)   -> approves FOR the Manager,
                 scoped to this Manager's own branch (its assigned RESL
                 Branch Accountant, same pattern as RESL District)

          District / Regional Office:
              1. Director                    (always this work unit's Director)
                 (also approves the RESL District user's own request)
              2. RESL District (Settings role) -> approves FOR the Director,
                 and disburses EVERY loan of its own district, its own included

          Head Office / other / not set:
              1. HO Approver
              2. HR Approver                 -> approves FOR the HO Approver
        """
        for loan in self:
            emp = loan.employee_id.sudo() if loan.employee_id else False
            if not emp:
                loan.operating_unit_id = False
                loan.designated_approver_id = False
                loan.designated_approver_role = False
                loan.manager_user_id = False
                loan.disbursement_officer_id = False
                loan.disbursement_officer_role = False
                continue

            ou = self.env['resl.validations'].get_employee_operating_unit(emp)
            work_unit_type = getattr(ou, 'work_unit_type', False) if ou else False
            loan.operating_unit_id = ou.id if ou else False

            approver_user = False
            approver_role = False
            exclude_self = [emp.id]

            # 1. Branch / Sub-branch / Service Center -> always the Manager
            #    of THAT work unit; if the borrower IS that Manager, the
            #    Accountant (Disbursement) of the same work unit approves.
            if work_unit_type in ('branch', 'sub_branch', 'service_center'):
                manager_emp = self._find_role_employee(
                    ['manager'], ou=ou, exclude_keywords=['accountant']
                )
                if manager_emp and manager_emp.id == emp.id:
                    approver_role = "Accountant (Disbursement)"
                    # No manual role assignment needed: found the same way
                    # Manager/Director are - by Job Position title, scoped
                    # to this Manager's own branch.
                    acct_emp = self._find_role_employee(
                        ['accountant'], ou=ou, exclude_employee_ids=exclude_self,
                    )
                    approver_user = acct_emp.user_id if acct_emp else False
                elif manager_emp:
                    approver_role = "Manager"
                    approver_user = manager_emp.user_id
                else:
                    approver_role = "Manager"
                    approver_user = emp.parent_id.user_id if emp.parent_id else False

            # 2. District Office / Regional Office -> always the Director of
            #    THAT work unit; if the borrower IS that Director, the
            #    Division Manager (Disbursement) approves instead.
            elif work_unit_type in ('district_office', 'regional_office'):
                director_emp = self._find_role_employee(['director'], ou=ou)
                if director_emp and director_emp.id == emp.id:
                    approver_role = "RESL District"
                    dm_emp = self._find_role_employee_by_group(
                        'resl.group_resl_district', ou=ou,
                        exclude_employee_ids=exclude_self, match_any_ou=True,
                    )
                    approver_user = dm_emp.user_id if dm_emp else False
                elif director_emp:
                    approver_role = "Director"
                    approver_user = director_emp.user_id
                else:
                    approver_role = "Director"
                    approver_user = emp.parent_id.user_id if emp.parent_id else False

            # 3. Head Office / other / not set -> the HO Approver; if the
            #    borrower IS the HO Approver, HR Approver approves instead.
            elif work_unit_type in ('head_office', 'other') or not work_unit_type:
                ho_scope = ou if work_unit_type == 'head_office' else None
                # Never pick the borrower as their own approver; prefer an HO
                # Approver in the borrower's own OU, else any HO Approver.
                ho_emp = self._find_role_employee_by_group(
                    'resl.group_resl_ho_approver', ou=ho_scope,
                    exclude_employee_ids=exclude_self,
                )
                if not ho_emp and ho_scope:
                    ho_emp = self._find_role_employee_by_group(
                        'resl.group_resl_ho_approver',
                        exclude_employee_ids=exclude_self,
                    )
                if ho_emp:
                    approver_role = "HO Approver"
                    approver_user = ho_emp.user_id
                else:
                    ho_group = self.env.ref('resl.group_resl_ho_approver', raise_if_not_found=False)
                    borrower_is_ho = bool(
                        ho_group and emp.user_id and emp.user_id in ho_group.sudo().all_user_ids
                    )
                    if borrower_is_ho:
                        # Borrower is the only HO Approver -> HR Approver approves.
                        approver_role = "HR Approver"
                        sr_emp = self._find_role_employee_by_group(
                            'resl.group_resl_hr_senior', exclude_employee_ids=exclude_self,
                        )
                        approver_user = sr_emp.user_id if sr_emp else False
                    else:
                        approver_role = "HO Approver"
                        approver_user = emp.parent_id.user_id if emp.parent_id else False

            # Fallback: reporting line, if the role-based lookup found no one
            if not approver_user and emp.parent_id and emp.parent_id.user_id:
                approver_user = emp.parent_id.user_id

            # Belt-and-braces: an approver must never be the borrower
            # themselves, whatever path produced approver_user above.
            if approver_user and emp.user_id and approver_user.id == emp.user_id.id:
                approver_user = False

            loan.designated_approver_role = approver_role
            loan.designated_approver_id = approver_user.id if approver_user else False
            loan.manager_user_id = approver_user.id if approver_user else False

            officer_user, officer_role = loan._resolve_disbursement_officer(emp, ou, work_unit_type)
            loan.disbursement_officer_id = officer_user.id if officer_user else False
            loan.disbursement_officer_role = officer_role or False

    def _resolve_disbursement_officer(self, emp, ou, work_unit_type):
        """Stage 2 of the approval chain: who disburses the loan.

          Branch / Sub-branch / Service Center -> the employee in the
              borrower's own operating unit whose Job Position title
              contains "accountant" (same lookup as Manager/Director - no
              manual Settings role assignment needed). Disburses EVERY
              loan of its own branch, including the Manager's and its own.
          District / Regional Office -> the user holding the "RESL District"
              role (Settings > Users > Staff Loan (RESL)) for the borrower's
              district (default OU or one of their assigned Operating
              Units). It disburses EVERY loan of its district, including
              the District Director's and its own.
          Head Office / other -> no fixed officer (returns nothing), so the
              existing HR Auditor -> HR Accountant hand-off applies.

        Returns (res.users record or False, role label or False).
        """
        label_acct = "Accountant (Disbursement)"
        if work_unit_type in ('branch', 'sub_branch', 'service_center'):
            # Borrower IS this branch's Accountant (by job title) -> they
            # disburse their own loan (the Manager already approved it -
            # a different person).
            if self._is_branch_accountant_employee(emp) and emp.user_id:
                return emp.user_id, label_acct
            # No manual role assignment needed: found by Job Position
            # title, same way Manager/Director are, scoped to this branch.
            acct = self._find_role_employee(['accountant'], ou=ou)
            return (acct.user_id if acct else False), label_acct
        if work_unit_type in ('district_office', 'regional_office'):
            label = "RESL District (Disbursement)"
            # Borrower IS the RESL District user -> they disburse their own loan.
            if self._is_resl_district_user(emp) and emp.user_id:
                return emp.user_id, label
            dm = self._find_role_employee_by_group(
                'resl.group_resl_district', ou=ou, match_any_ou=True,
            )
            return (dm.user_id if dm else False), label
        return False, False

    @api.model
    def _is_resl_district_user(self, employee):
        """True when the employee's user holds the RESL District role."""
        user = employee.sudo().user_id
        group = self.env.ref('resl.group_resl_district', raise_if_not_found=False)
        return bool(user and group and user in group.sudo().all_user_ids)

    @api.model
    def _is_branch_accountant_employee(self, employee):
        """True when the employee's own Job Position title contains
        "accountant" - found the same way as Manager/Director, no manual
        role assignment needed."""
        title = (employee.job_id.name or '') if employee.job_id else ''
        return 'accountant' in title.lower()

    def _live_disbursement_officer(self):
        """Disbursement officer resolved RIGHT NOW (not the stored value,
        which can be stale if the role holder or OU was set up after the
        loan was created). Falls back to the stored officer."""
        self.ensure_one()
        loan = self.sudo()
        emp = loan.employee_id
        if not emp:
            return self.env['res.users']
        ou = self.env['resl.validations'].get_employee_operating_unit(emp)
        wut = getattr(ou, 'work_unit_type', False) if ou else False
        res = loan._resolve_disbursement_officer(emp, ou, wut)
        return res[0] or loan.disbursement_officer_id

    @api.model
    def _cron_refresh_disbursement_routing(self):
        """Re-resolve the disbursement officer of every approved,
        not-yet-disbursed loan and hand it over (sets disbursement_requested
        + activity). Fixes loans approved before the routing existed or
        while the role holder was not yet set up."""
        try:
            with self.env.cr.savepoint():
                loans = self.sudo().search([
                    ('status', 'in', ('manager_review', 'approved')),
                    ('core_banking_status', '!=', 'disbursed'),
                ])
                for loan in loans:
                    try:
                        loan._compute_designated_approver()
                        if (loan.status == 'approved' and loan.disbursement_officer_id
                                and not loan.disbursement_requested):
                            loan._route_to_disbursement_officer(loan.approver_id or self.env.user)
                    except Exception:
                        _logger.exception('Failed to refresh disbursement routing for loan %s', loan.id)
        except Exception:
            _logger.exception('Failed to refresh RESL disbursement routing')

    def _user_can_approve(self, user):
        """Whether `user` is allowed to open/attempt approval on this loan
        at all - used for button visibility and the record-rule that lets
        a designated approver SEE the loan.

        This mirrors exactly what action_manager_approve/_reject's entry
        gate allows: the loan's designated_approver_id (resolved by job
        title / OU in _compute_designated_approver - this is what lets a
        Branch Manager / District Director / Division Manager / Accountant
        act purely from their job title, with no separate manual "Loan
        Manager" technical-group assignment required), OR Loan Manager /
        HR Officer group membership, OR an administrator. The borrower can
        never approve or reject their own request.

        NOTE: passing this check does not guarantee the approve/reject
        action itself will succeed - action_manager_approve additionally
        applies its own operating-unit scoping (same-OU fallback, head-
        office sol_id exception) for group-member approvers who are not
        the designated approver, exactly as before this fix. Nothing
        downstream of the entry gate changed.
        """
        self.ensure_one()
        loan = self.sudo()
        borrower_user = loan.employee_id.user_id
        if borrower_user and borrower_user.id == user.id:
            return False
        if user.has_group('base.group_system'):
            return True
        designated_user = loan.designated_approver_id or loan.manager_user_id
        if designated_user and designated_user.id == user.id:
            return True
        return bool(
            user.has_group('resl.group_resl_manager')
            or user.has_group('resl.group_resl_hr')
        )

    @api.depends('designated_approver_id', 'manager_user_id', 'status', 'employee_id')
    def _compute_can_approve(self):
        user = self.env.user
        for loan in self:
            loan.can_approve = bool(loan.id) and loan._user_can_approve(user)

    def _user_can_disburse(self, user):
        """Who may disburse this loan.

        * A loan with a designated disbursement officer (branch / district
          tiers): ONLY that officer (or a system administrator) — scoped
          to the borrower's own branch/district, not company-wide.
        * A loan with none (Head Office / other, or nobody found): the
          previous rule — HR Officer / HR Accountant / administrator.
        The borrower can never disburse their own loan, EXCEPT:
          - the RESL District user, who is the designated disbursement
            officer of their own loan (the District Director approves it,
            the RESL District user disburses it), or
          - the branch Accountant (by job title), who is the designated
            disbursement officer of their own loan (the Manager approves
            it, the Accountant disburses it) - matches the self-
            disbursement resolved in _resolve_disbursement_officer.
        Both exceptions still require someone ELSE to have approved it.
        """
        self.ensure_one()
        loan = self.sudo()
        officer = loan._live_disbursement_officer()
        borrower_user = loan.employee_id.user_id
        if borrower_user and borrower_user.id == user.id:
            is_self_officer = bool(
                officer
                and officer.id == user.id
                and loan.approver_id
                and loan.approver_id.id != user.id
            )
            return is_self_officer and (
                self._is_resl_district_user(loan.employee_id)
                or self._is_branch_accountant_employee(loan.employee_id)
            )
        if user.has_group('base.group_system'):
            return True
        if officer:
            return officer.id == user.id
        return bool(
            user.has_group('resl.group_resl_hr')
            or user.has_group('resl.group_resl_hr_accountant')
        )

    @api.depends('disbursement_officer_id', 'status', 'core_banking_status', 'employee_id',
                 'approver_id', 'disbursement_requested')
    def _compute_can_disburse(self):
        user = self.env.user
        for loan in self:
            ok = bool(loan.id) and loan._user_can_disburse(user)
            if ok and not loan.disbursement_requested:
                # HR Accountant path still waits for the HR Auditor's request;
                # a fixed officer (district / branch tier) does not.
                ok = bool(loan._live_disbursement_officer())
            loan.can_disburse = ok

    def _route_to_disbursement_officer(self, approver):
        """After level-1 approval, hand the loan to its disbursement officer:
        mark disbursement as requested (no HR Auditor click needed), raise an
        activity for the officer and leave a chatter note.
        Returns True if routed, False if the loan has no fixed officer (the
        manual HR Auditor -> HR Accountant flow then applies).
        """
        self.ensure_one()
        loan = self.sudo()
        officer = loan.disbursement_officer_id
        if not officer:
            try:
                ou = self.env['resl.validations'].get_employee_operating_unit(loan.employee_id)
                wut = getattr(ou, 'work_unit_type', False) if ou else False
                if wut in ('branch', 'sub_branch', 'service_center', 'district_office', 'regional_office'):
                    loan.message_post(body=_(
                        "No disbursement officer could be found for this loan "
                        "(operating unit: %(ou)s, unit type: %(t)s). Check that the "
                        "Division/District Manager or Accountant has a linked user, a matching "
                        "job title and this operating unit."
                    ) % {'ou': ou.name if ou else '-', 't': wut})
            except Exception:
                _logger.exception('Failed to post no-officer note for loan %s', loan.id)
            return False
        loan.write({
            'disbursement_requested': True,
            'disbursement_requested_by_id': approver.id,
            'disbursement_requested_date': fields.Datetime.now(),
        })
        note = _(
            "Loan %(loan)s for %(employee)s (%(amount)s %(currency)s) was approved by "
            "%(approver)s and is now waiting for disbursement by %(role)s."
        ) % {
            'loan': loan.name,
            'employee': loan.employee_id.name,
            'amount': '{:,.2f}'.format(loan.approved_amount or 0.0),
            'currency': loan.currency_id.name or '',
            'approver': approver.name,
            'role': loan.disbursement_officer_role or _("Disbursement Officer"),
        }
        try:
            loan.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=officer.id,
                summary=_("Disburse staff loan %s") % loan.name,
                note=note,
            )
        except Exception:
            _logger.exception('Failed to schedule disbursement activity for loan %s', loan.id)
        try:
            loan.message_post(body=note)
        except Exception:
            _logger.exception('Failed to post disbursement routing note for loan %s', loan.id)
        return True

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

    @api.depends('guarantor_line_ids.state', 'guarantor_line_ids.guarantor_id', 'employee_id')
    def _compute_all_guarantors_accepted(self):
        """True only when EVERY active guarantor accepted AND their salaries
        (one guarantor alone, or the two combined) cover the borrower. With two
        guarantors the requester therefore waits for both to accept."""
        Validations = self.env['resl.validations']
        for loan in self:
            active_lines = loan.guarantor_line_ids.filtered(
                lambda line: line.state in ('draft', 'pending', 'accepted')
            )
            loan.all_guarantors_accepted = bool(active_lines) and all(
                line.state == 'accepted' for line in active_lines
            ) and bool(Validations.guarantor_coverage(loan)['covered'])

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
            # Snapshot per loan: a DISBURSED loan keeps the running total as of
            # its own disbursement (earlier loans + itself) and is NOT changed by
            # loans disbursed after it. A loan not yet disbursed shows the current
            # total of everything disbursed so far.
            domain = [
                ('employee_id', '=', loan.employee_id.id),
                ('core_banking_status', '=', 'disbursed'),
            ]
            own_id = loan._origin.id or (loan.id if isinstance(loan.id, int) else False)
            if own_id and loan.core_banking_status == 'disbursed':
                domain.append(('id', '<=', own_id))
            loan.total_loans_taken = sum(
                float(l.approved_amount or 0.0) for l in self.env['resl.loan'].sudo().search(domain)
            )

    @api.depends('eligible_amount', 'total_loans_taken')
    def _compute_net_eligible_amount(self):
        for loan in self:
            loan.net_eligible_amount = max(
                0.0, (loan.eligible_amount or 0.0) - (loan.total_loans_taken or 0.0)
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

    @api.depends('guarantor_line_ids.state', 'guarantor_line_ids.guarantor_id', 'employee_id', 'status')
    def _compute_guarantor_second_notice(self):
        Validations = self.env['resl.validations']
        for loan in self:
            notice = False
            if loan.employee_id and loan.status in ('draft', 'guarantor_pending'):
                state = Validations.guarantor_slot_state(loan)
                lines = loan.guarantor_line_ids.filtered(
                    lambda l: l.state in ('draft', 'pending', 'accepted')
                )
                if state == 'needs_second':
                    notice = _(
                        "You need to select another guarantor. Click 'Find Guarantor' to "
                        "choose the second guarantor. The request is sent to both guarantors "
                        "once they are both selected."
                    )
                elif state == 'full' and len(lines) == 2 and loan.status == 'guarantor_pending' \
                        and not loan.all_guarantors_accepted:
                    accepted = len(lines.filtered(lambda l: l.state == 'accepted'))
                    notice = _(
                        "This request has two guarantors. Both must accept before it can "
                        "go further (%(done)s of 2 accepted)."
                    ) % {'done': accepted}
            loan.guarantor_second_notice = notice

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
        """Show the button only to the person the routing engine actually
        designated as approver for this loan (or a same-OU manager as a
        narrow fallback for the rare case where routing found no user).

        Previously this special-cased "borrower is themselves a
        Manager-type user" (e.g. an admin account) by showing the button
        to *any* HR Officer — not specifically the escalated approver
        _compute_designated_approver already resolves (HR Approver for an
        HO Approver borrower, Accountant for a Branch Manager borrower,
        Division Manager for a District Director borrower, etc). That was
        redundant with the routing computation and let any HR Officer see
        (and, combined with the matching bug in action_manager_approve,
        actually use) the Approve button on loans they were never
        supposed to approve.
        """
        user = self.env.user
        approver_emp = self.env['hr.employee'].search([('user_id', '=', user.id)], limit=1)
        for loan in self:
            if loan.status != 'manager_review':
                loan.show_approve_button = False
                continue

            # Stored routing fields only update when their dependencies
            # (employee_id / its Operating Unit / its manager) change, so a
            # request submitted before the approver's Staff Loan (RESL)
            # role was set in Settings — or before this routing logic was
            # fixed — can be left pointing at a stale user. Recompute live
            # here so the correct person's button appears immediately,
            # without a manual "recompute" action; since the fields are
            # stored, the refreshed value is also persisted for next time.
            loan.sudo()._compute_designated_approver()  # refresh as sudo: viewers may lack write access

            designated_user = loan.designated_approver_id or loan.manager_user_id
            if designated_user and designated_user.id == user.id:
                loan.show_approve_button = True
                continue

            # Narrow fallback: a same-operating-unit manager, for the case
            # where role-based routing didn't resolve to a specific user
            # (see the parent_id fallback in _compute_designated_approver).
            try:
                borrower_ou = getattr(loan.employee_id, 'default_operating_unit_id', False)
                approver_ou = getattr(approver_emp, 'default_operating_unit_id', False)
            except Exception:
                borrower_ou = approver_ou = False
            loan.show_approve_button = bool(
                user.has_group('resl.group_resl_manager')
                and borrower_ou and approver_ou
                and borrower_ou.id == approver_ou.id
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

        # FR-RESL-012 (v2): a request can only be routed to an approver when
        # the borrower's own operating unit has a recognised work_unit_type
        # (Branch/District/Head Office family). Nobody can request "out of"
        # their work unit — i.e. without a properly identified one.
        wut_ok, wut_reason = self.env['resl.validations'].check_work_unit_type(emp)
        if not wut_ok:
            blockers.append(wut_reason)

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

    # ── Soft delete ───────────────────────────────────────────────────────────

    def unlink(self):
        """Deleting a request from the front end only FLAGS it (del_flag) and
        its guarantor lines / replacement log; nothing is removed from the
        database. See resl.soft.delete.mixin."""
        if self.env.context.get('resl_hard_delete'):
            return super().unlink()
        lines = self.with_context(active_test=False).sudo().mapped('guarantor_line_ids')
        logs = self.env['resl.loan.replacement.log'].with_context(active_test=False).sudo().search(
            [('loan_id', 'in', self.ids)]
        )
        lines.filtered('active')._soft_delete()
        logs.filtered('active')._soft_delete()
        return self._soft_delete()

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

            # FR-RESL-007: guarantor salaries. A guarantor whose salary is below the
            # borrower's is no longer rejected outright; the request just waits for a
            # second guarantor (see the coverage check below) and is only sent once
            # one guarantor, or the two combined, cover the borrower's salary.

            # Two-guarantor rule: when the guarantor(s) chosen so far do not cover
            # the borrower's salary (a lone lower-salary guarantor), nothing is
            # sent yet. The request waits as a draft until a second guarantor is
            # chosen and their COMBINED salaries are equal to or greater than
            # the borrower's; then BOTH are notified at once.
            if not self.env['resl.validations'].guarantor_coverage(loan)['covered']:
                loan.sudo().message_post(body=_(
                    "Guarantor selected. Another guarantor is required before the "
                    "request is sent."
                ))
                continue

            pending_lines = loan.guarantor_line_ids.filtered(lambda l: l.state == 'draft')
            for line in pending_lines:
                line.sudo().write({'state': 'pending'})
                guarantor_user = line.guarantor_id.user_id if line.guarantor_id else False
                if guarantor_user:
                    loan.sudo().activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=guarantor_user.id,
                        note=f"Please accept or reject your guarantee for loan {loan.name}."
                    )
                    try:
                        if guarantor_user.partner_id:
                            loan.sudo().message_notify(
                                partner_ids=[guarantor_user.partner_id.id],
                                subject=_("Guarantee request for loan %s") % loan.name,
                                body=_("%(emp)s has asked you to guarantee loan %(loan)s. "
                                       "Please accept or reject it.") % {
                                    'emp': loan.employee_id.name, 'loan': loan.name},
                            )
                    except Exception:
                        _logger.exception("Failed to notify guarantor %s", line.guarantor_id.id)
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
            # Stored routing can be stale; refresh it before notifying.
            loan.sudo()._compute_designated_approver()
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

            if loan.status != 'manager_review':
                raise ValidationError("Loan must be in Manager Review stage to approve.")

            # Stored routing fields (designated_approver_id etc.) only
            # refresh when their @api.depends fields change, so a request
            # can be left pointing at a stale approver — e.g. it was
            # submitted before the correct person's Staff Loan (RESL) role
            # was set in Settings, or before their job title/OU was set
            # correctly. Recompute live BEFORE the permission gate below,
            # since a validly job-title-routed approver (e.g. a Branch
            # Manager) may never have been manually placed in the Loan
            # Manager technical group - being the resolved
            # designated_approver_id must be sufficient on its own.
            loan.sudo()._compute_designated_approver()  # refresh as sudo: viewers may lack write access

            designated_user = loan.designated_approver_id or loan.manager_user_id
            is_designated = bool(designated_user and designated_user.id == user.id)
            if not (
                is_designated
                or user.has_group('resl.group_resl_manager')
                or user.has_group('resl.group_resl_hr')
            ):
                raise ValidationError("Only Loan Manager group members or HR can approve.")

            # An approver can never approve their own request, regardless of
            # which group(s) they belong to (HR/POMD included).
            try:
                borrower_user = loan.sudo().employee_id.user_id
            except Exception:
                borrower_user = False
            if borrower_user and borrower_user.id == user.id:
                raise ValidationError(
                    _("You cannot approve your own loan request. It must be approved by the "
                      "next-level approver instead.")
                )

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
                        "If you are the correct approver but this is blocking you, check that "
                        "your Staff Loan (RESL) role (Settings > Users) and Operating Unit are "
                        "set correctly, then ask the borrower to re-save their employee record "
                        "so this loan's routing is recomputed."
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

            # The approver must pass the same employment checks as the requester.
            self.env['resl.validations'].check_actor_eligibility(
                loan, user, role=_("Approver"), raise_exception=True
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

            # Stage 2: send the approved loan to its disbursement officer
            # (Branch -> Accountant, District -> Division Manager).
            routed_to_officer = False
            try:
                routed_to_officer = loan._route_to_disbursement_officer(user)
            except Exception:
                _logger.exception("Failed to route loan %s to its disbursement officer", loan.id)

            # Notify HR after manager approval (only for loans without a
            # fixed disbursement officer, e.g. Head Office)
            try:
                if (not routed_to_officer
                        and user.has_group('resl.group_resl_manager')
                        and not user.has_group('resl.group_resl_hr')):
                    hr_group = self.env.ref('resl.group_resl_hr')
                    if hr_group:
                        for u in hr_group.sudo().all_user_ids:
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

            # Same reasoning as action_manager_approve: recompute routing
            # first, then allow the designated approver through even
            # without the Loan Manager technical group.
            loan.sudo()._compute_designated_approver()

            designated_user = loan.designated_approver_id or loan.manager_user_id
            is_designated = bool(designated_user and designated_user.id == user.id)
            if not (
                is_designated
                or user.has_group('resl.group_resl_manager')
                or user.has_group('resl.group_resl_hr')
            ):
                raise ValidationError("Only Loan Manager group members or HR can reject.")

            try:
                borrower_emp = loan.sudo().employee_id
            except Exception:
                borrower_emp = None

            # An approver can never reject their own request either.
            borrower_user = borrower_emp.user_id if borrower_emp else False
            if borrower_user and borrower_user.id == user.id:
                raise ValidationError(
                    _("You cannot reject your own loan request. It must be handled by the "
                      "next-level approver instead.")
                )

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

    def action_request_disbursement(self):
        """FR-RESL-020: HR Auditor forwards an approved, not-yet-disbursed
        loan to HR Accountant for Core Banking disbursement.

        HR Auditor is read-only everywhere else in this module (model
        access + record rules both deny write/create/unlink for
        group_resl_hr_auditor), so this action does NOT disburse anything
        or touch core_banking_status itself — it only raises an activity
        and a chatter note addressed to every HR Accountant, who remain
        the only ones able to actually record the disbursement via
        action_disburse_core_banking() / _do_disburse().
        """
        self.ensure_one()
        user = self.env.user
        if not (
            user.has_group('resl.group_resl_hr_auditor')
            or user.has_group('resl.group_resl_hr')
            or user.has_group('base.group_system')
        ):
            raise ValidationError(
                _("Only HR Auditor, HR Officer, or Administrators can request disbursement.")
            )
        if self.status != 'approved':
            raise ValidationError(_("Loan must be Approved before disbursement can be requested."))
        if self.core_banking_status == 'disbursed':
            raise ValidationError(_("This loan has already been disbursed on Core Banking."))

        accountant_group = self.env.ref('resl.group_resl_hr_accountant', raise_if_not_found=False)
        # Odoo 19: res.groups.all_user_ids replaces the old users/groups_id search.
        accountants = (
            accountant_group.sudo().all_user_ids.filtered('active')
            if accountant_group else self.env['res.users']
        )

        self.sudo().write({
            'disbursement_requested': True,
            'disbursement_requested_by_id': user.id,
            'disbursement_requested_date': fields.Datetime.now(),
        })

        note = _(
            "%(auditor)s (HR Auditor) requested Core Banking disbursement for "
            "loan %(loan)s — %(employee)s, %(amount)s %(currency)s."
        ) % {
            'auditor': user.name,
            'loan': self.name,
            'employee': self.sudo().employee_id.name,  # auditor has no hr.employee read access
            'amount': '{:,.2f}'.format(self.approved_amount or 0.0),
            'currency': self.currency_id.name or '',
        }

        for accountant in accountants:
            try:
                self.sudo().activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=accountant.id,
                    summary=_("Disburse staff loan %s") % self.name,
                    note=note,
                )
            except Exception:
                _logger.exception(
                    'Failed to schedule disbursement-request activity for loan %s', self.id
                )

        try:
            self.sudo().message_post(body=note)
        except Exception:
            _logger.exception('Failed to post disbursement-request message for loan %s', self.id)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Disbursement Requested'),
                'message': _('HR Accountant has been notified to disburse this loan.'),
                'type': 'success',
                'sticky': False,
            },
        }

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
        if not self._user_can_disburse(user):
            officer = self.sudo().disbursement_officer_id
            if officer:
                raise ValidationError(_(
                    "Only %(officer)s (%(role)s) can disburse this loan."
                ) % {'officer': officer.name, 'role': self.disbursement_officer_role or _('Disbursement Officer')})
            raise ValidationError(_("Only POMD / HR / HR Accountant or Administrators can record Core Banking disbursement."))
        # The disburser must pass the same employment checks as the requester.
        self.env['resl.validations'].check_actor_eligibility(
            self, user, role=_("Disburser"), raise_exception=True
        )
        if self.status != 'approved':
            raise ValidationError(_("Loan must be in Approved state for Core Banking disbursement."))
        if not self.disbursement_requested:
            if self._live_disbursement_officer():
                self.sudo().write({
                    'disbursement_requested': True,
                    'disbursement_requested_by_id': self.sudo().approver_id.id or user.id,
                    'disbursement_requested_date': fields.Datetime.now(),
                })
            else:
                raise ValidationError(_("Disbursement must first be requested by the HR Auditor."))
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
        # Final gate (also reached from the wizard's Confirm button): the
        # disburser must pass the same employment checks as the requester.
        self.env['resl.validations'].check_actor_eligibility(
            self, user, role=_("Disburser"), raise_exception=True
        )
        # The HR Accountant has no read access on hr.employee, but this flow
        # reads the borrower (name, sibling-loan recompute). The caller's
        # permission was already checked in action_disburse_core_banking, so
        # run the rest elevated; `user` above keeps the real actor.
        self = self.sudo()
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
        # Only this loan and the employee's NOT-yet-disbursed requests are
        # refreshed. Loans disbursed earlier keep the total they had.
        sibling_loans = self.search([
            ('employee_id', '=', self.employee_id.id),
            '|', ('id', '=', self.id), ('core_banking_status', '!=', 'disbursed'),
        ])
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
        if not (
            user.has_group('resl.group_resl_hr')
            or user.has_group('resl.group_resl_hr_accountant')
            or user.has_group('base.group_system')
        ):
            raise ValidationError(_("Only POMD / HR / HR Accountant or Administrators can update settlement status."))
        self.write({'settlement_status': 'settled'})
        self.message_post(body=_("Loan marked as fully settled by %s.") % user.name)


class ResUsers(models.Model):
    _inherit = 'res.users'

    # Job-title keywords that make someone a work-unit reviewer (same
    # keywords the routing in _compute_designated_approver uses).
    _RESL_REVIEWER_KEYWORDS = ('manager', 'director', 'accountant')

    resl_scope_operating_unit_ids = fields.Many2many(
        'operating.unit', compute='_compute_resl_scope_operating_unit_ids',
        string="RESL Review Scope (Work Units)",
        help="Work units whose staff-loan requests this user may see as a "
             "manager / approver. Empty for ordinary staff. Used by the "
             "'RESL Loan: work-unit reviewers' record rules.",
    )

    def _compute_resl_scope_operating_unit_ids(self):
        """Work units a user reviews loans for.

        A user is a work-unit reviewer when they hold the Loan Manager /
        RESL District group (directly or implied) OR their Job Position /
        Job Title is Manager / Director / Accountant (this is how the
        branch Accountant role is recognized - by job title, no manual
        group assignment, same as Manager/Director). Their scope is their
        own operating unit(s): default OU + every OU on their employee
        record (this matches the match_any_ou routing of RESL District).
        Head Office roles do not depend on this: they have an all-loans rule.
        """
        OU = self.env['operating.unit'].sudo()
        Employee = self.env['hr.employee'].sudo()
        validations = self.env['resl.validations']
        for user in self:
            ous = OU
            if not user.id:
                user.resl_scope_operating_unit_ids = ous
                continue
            emps = Employee.search([('user_id', '=', user.id)])
            is_reviewer = bool(
                user.has_group('resl.group_resl_manager')
                or user.has_group('resl.group_resl_district')
            )
            if not is_reviewer:
                for emp in emps:
                    title = ' '.join(filter(None, [
                        emp.job_id.name if emp.job_id else '',
                        getattr(emp, 'job_title', '') or '',
                    ])).lower()
                    if any(k in title for k in self._RESL_REVIEWER_KEYWORDS):
                        is_reviewer = True
                        break
            if is_reviewer:
                for emp in emps:
                    own = validations.get_employee_operating_unit(emp)
                    if own:
                        ous |= own
                    if 'operating_unit_ids' in emp._fields:
                        ous |= emp.operating_unit_ids
            user.resl_scope_operating_unit_ids = ous

    def write(self, vals):
        res = super().write(vals)
        # Assigning / removing the RESL District (or any RESL) role changes who
        # approves / disburses open loans: refresh their stored routing now.
        if 'group_ids' in vals:
            try:
                self.env['resl.loan']._cron_refresh_disbursement_routing()
            except Exception:
                _logger.exception('RESL routing refresh after group change failed')
        return res