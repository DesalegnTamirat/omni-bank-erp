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
from datetime import timedelta
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _, SUPERUSER_ID
from markupsafe import Markup
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class ReslLoan(models.Model):
    _name = 'resl.loan'
    _description = 'Staff Loan Request'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'resl.soft.delete.mixin']

    name = fields.Char(string='Reference', required=True, default='New')
    custom_saved = fields.Boolean(
        string='Is Saved', default=False, copy=False, index=True,
        help="False for a request that Odoo's web client auto-saved while the "
             "user was still on the New form (tab switch, navigating away, ...). "
             "Such a request is hidden everywhere, has no reference number and is "
             "deleted by a cron. It becomes True when the requester clicks Save "
             "or picks a guarantor in Find Guarantor.",
    )

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
        string='Guarantors', copy=True
    )

    def init(self):
        """Backfill the new 'submitted' progress stage for loans already
        waiting for manager review (stored compute is not re-run on upgrade)."""
        super().init()
        # Existing requests (those that already have a reference) count as saved.
        self.env.cr.execute(
            "UPDATE resl_loan SET custom_saved = TRUE "
            "WHERE custom_saved IS NOT TRUE AND name IS NOT NULL AND name != 'New'"
        )
        self.env.cr.execute(
            "UPDATE resl_loan SET progress_status = 'submitted' "
            "WHERE status = 'manager_review' AND progress_status IS DISTINCT FROM 'submitted'"
        )

    has_replaceable_guarantor = fields.Boolean(
        string="Has Replaceable Guarantor",
        compute="_compute_has_replaceable_guarantor", store=False,
        help="True while the request has at least one guarantor that is still in "
             "play (not rejected / replaced), i.e. someone who can be replaced.",
    )
    employee_service_duration = fields.Char(
        string="Length of Service", compute="_compute_employee_service_duration",
        help="Time since the employee's contract start date, in years, months and days.",
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
    can_reject_approved = fields.Boolean(
        compute='_compute_can_reject_approved', store=False,
        help="True when the logged-in user (HR Auditor, HR Accountant, the loan's "
             "disbursement officer such as the Branch Accountant, or an Admin) may "
             "reject this approved, not-yet-disbursed request.",
    )
    can_ho_replace = fields.Boolean(
        compute='_compute_role_flags', store=False,
        help="Current user (or someone who delegated to them) holds an HO / HR replace-guarantor role.",
    )
    can_audit_request = fields.Boolean(
        compute='_compute_role_flags', store=False,
        help="Current user (or their delegator) is an HR Auditor.",
    )
    can_hr_accountant = fields.Boolean(
        compute='_compute_role_flags', store=False,
        help="Current user (or their delegator) is an HR Officer / HR Accountant.",
    )
    is_my_disbursement = fields.Boolean(
        compute='_compute_is_my_disbursement', search='_search_is_my_disbursement',
        help="Routed to me (or to someone who delegated to me) for disbursement.",
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
    # Reporting helpers: WHO requested / disbursed and in which capacity, for all
    # three tiers (Branch, District, Head Office). Stored so they can be grouped,
    # filtered and pivoted on the loan reports.
    disbursement_level = fields.Selection([
        ('branch', 'Branch'),
        ('district', 'District'),
        ('head_office', 'Head Office'),
    ], string="Disbursement Level", compute='_compute_disbursement_roles', store=True,
        help="Which tier handles this loan's disbursement: Branch (Branch Accountant), "
             "District (RESL District officer) or Head Office (HR Auditor requests, "
             "HR Accountant disburses).")
    disbursement_requested_by_role = fields.Char(
        string="Requested By (Role)", compute='_compute_disbursement_roles', store=True,
        exportable=False,
        help="Capacity of the person who requested disbursement: HR Auditor at Head "
             "Office, the approver at branch / district level (the request is sent "
             "automatically when the approver approves).",
    )
    disbursed_by_role = fields.Char(
        string="Disbursed By (Role)", compute='_compute_disbursement_roles', store=True,
        exportable=False,
        help="Capacity of the person who disbursed: Branch Accountant, District "
             "officer or HR Accountant.",
    )

    # Export helpers: guarantor names with their status, as plain text.
    guarantors_summary = fields.Char(
        string="Guarantors (Current)", compute='_compute_guarantors_summary',
        help="Current guarantors with their status, e.g. 'Abebe (Accepted); Sara (Pending)'. "
             "Replaced / separated guarantors are not included (see 'Replaced Guarantors').",
    )
    replaced_guarantors_summary = fields.Char(
        string="Replaced Guarantors", compute='_compute_guarantors_summary',
        help="Previous guarantors that were replaced or separated, with who replaced them. "
             "Leave this column out of the export if the previous guarantors are not needed.",
    )

    # Justification of the last rejection (mandatory for every approver-side
    # rejection: approver, HR Auditor, HR Accountant, disbursement officer).
    # Guarantors may reject without a comment.
    rejection_reason = fields.Text(string="Last Rejection Comment", readonly=True, copy=False)
    rejected_by_id = fields.Many2one('res.users', string="Last Rejected By", readonly=True, copy=False)
    rejected_by_role = fields.Char(string="Last Rejected By (Role)", readonly=True, copy=False)
    rejected_on = fields.Datetime(string="Last Rejected On", readonly=True, copy=False)

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
        ('submitted', 'Submitted'),
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
                    or loan._user_can_replace_any_stage(user)
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

    @api.depends('employee_id')
    def _compute_employee_service_duration(self):
        for loan in self:
            emp = loan.employee_id.sudo() if loan.employee_id else False
            loan.employee_service_duration = loan._service_duration_text(emp) if emp else ''

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

    @api.depends('guarantor_line_ids.guarantor_id.user_id', 'guarantor_line_ids.state',
                 'guarantor_line_ids.replaced_by_id')
    def _compute_is_guarantor(self):
        for loan in self:
            loan.is_guarantor = any(
                g.guarantor_id.user_id == self.env.user
                and g.state != 'replaced' and not g.replaced_by_id
                for g in loan.guarantor_line_ids
            )

    @api.depends('guarantor_line_ids.state')
    def _compute_has_replaceable_guarantor(self):
        for loan in self:
            # sudo: a Branch Manager / District Director opens employees'
            # loans through the designated-approver rule but has no record
            # rule on the guarantee lines, so without sudo the lines read as
            # empty and the Replace Guarantor button was hidden for them.
            loan.has_replaceable_guarantor = any(
                line.state not in ('replaced', 'rejected')
                for line in loan.sudo().guarantor_line_ids
            )

    @api.depends('guarantor_line_ids.state', 'guarantor_line_ids.guarantor_id', 'employee_id',
                 'guarantor_line_ids.replaces_id')
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
                             exclude_keywords=None, match_any_ou=False, order=None):
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

        return Employee.search(domain, order=order, limit=1)

    def _find_role_employee_by_group(self, group_xmlid, ou=None, exclude_employee_ids=None,
                                     match_any_ou=False, order=None):
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
        return Employee.search(domain, order=order, limit=1)

    @api.depends('employee_id', 'employee_id.default_operating_unit_id',
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
                    ['manager'], ou=ou,
                    exclude_keywords=['accountant', self._BRANCH_ACCOUNTANT_TITLE]
                )
                if manager_emp and manager_emp.id == emp.id:
                    approver_role = "Accountant (Disbursement)"
                    # Branch Accountant = job title "Branch Sales and
                    # Service Supervisor-I" OR the "Branch Accountant"
                    # role assigned in Settings, scoped to this branch.
                    acct_emp = self._find_branch_accountant(
                        ou, exclude_employee_ids=exclude_self,
                    )
                    approver_user = acct_emp.user_id if acct_emp else False
                elif manager_emp:
                    approver_role = "Manager"
                    approver_user = manager_emp.user_id
                else:
                    # No Manager found for this work unit: leave unrouted.
                    # The reporting-line manager is NOT part of the RESL flow.
                    approver_role = "Manager"
                    approver_user = False

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
                    approver_user = False

            # 3. Head Office / other / not set -> the HO Approver; if the
            #    borrower IS the HO Approver, HR Approver approves instead.
            elif work_unit_type in ('head_office', 'other') or not work_unit_type:
                ho_scope = ou if work_unit_type == 'head_office' else None
                ho_group = self.env.ref('resl.group_resl_ho_approver', raise_if_not_found=False)
                borrower_is_ho = bool(
                    ho_group and emp.user_id and emp.user_id in ho_group.sudo().all_user_ids
                )
                if borrower_is_ho:
                    # The borrower IS an HO Approver: the HR Approver approves
                    # FOR them (see group_resl_hr_senior), even when other HO
                    # Approvers exist. Only if no HR Approver can be found does
                    # it fall back to another HO Approver.
                    sr_emp = self._find_role_employee_by_group(
                        'resl.group_resl_hr_senior', exclude_employee_ids=exclude_self,
                    )
                    if sr_emp:
                        approver_role = "HR Approver"
                        approver_user = sr_emp.user_id
                    else:
                        ho_emp = self._find_role_employee_by_group(
                            'resl.group_resl_ho_approver', exclude_employee_ids=exclude_self,
                        )
                        approver_role = "HO Approver" if ho_emp else "HR Approver"
                        approver_user = ho_emp.user_id if ho_emp else False
                else:
                    # Normal Head Office request -> the HO Approver (never the
                    # borrower). Prefer one in the borrower's own OU, else any.
                    ho_emp = self._find_role_employee_by_group(
                        'resl.group_resl_ho_approver', ou=ho_scope,
                        exclude_employee_ids=exclude_self,
                    )
                    if not ho_emp and ho_scope:
                        ho_emp = self._find_role_employee_by_group(
                            'resl.group_resl_ho_approver',
                            exclude_employee_ids=exclude_self,
                        )
                    approver_role = "HO Approver"
                    approver_user = ho_emp.user_id if ho_emp else False

            # NOTE: there is intentionally NO reporting-line (parent_id)
            # fallback. A borrower's line manager only takes part in the
            # RESL flow when they actually hold a RESL role (HO Approver,
            # HR, ...), are the Branch Manager / Accountant / District
            # Director resolved above, or are a guarantor.

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

    @api.model
    def _recompute_all_routing(self):
        """Re-resolve the STORED routing fields (work unit, designated
        approver, disbursement officer) of every loan. Called on module
        upgrade so old records that were routed to the reporting-line
        manager stop being visible to that manager."""
        loans = self.sudo().with_context(active_test=False).search([])
        loans._compute_designated_approver()
        return True

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
            # The branch has exactly ONE Branch Accountant (first by name
            # when several qualify). If the borrower is that person they
            # disburse their own loan (the Manager already approved it); a
            # second Supervisor-I in the branch is NOT an officer.
            acct = self._find_branch_accountant(ou)
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

    # Job titles that act as the Branch Accountant. Level 1 is
    # "Branch Sales and Service Supervisor-I"; level 2 ("...Supervisor-II",
    # also typed "-Il") is used ONLY when the branch has no level-1 holder.
    # Matched case-insensitively on the Job Position name or free-text Job
    # Title, and EXACTLY on the level token, so "-I" never matches "-II".
    _BRANCH_ACCOUNTANT_TITLE = 'branch sales and service supervisor'
    _BRANCH_ACCT_LEVEL1 = ('i', '1')
    _BRANCH_ACCT_LEVEL2 = ('ii', 'il', 'll', '2')

    @api.model
    def _branch_accountant_level(self, employee):
        """1 for Supervisor-I, 2 for Supervisor-II/-Il, 0 for anything else."""
        import re
        employee = employee.sudo()
        titles = [(employee.job_id.name or '') if employee.job_id else '']
        if 'job_title' in employee._fields:
            titles.append(employee.job_title or '')
        best = 0
        for t in titles:
            m = re.search(re.escape(self._BRANCH_ACCOUNTANT_TITLE) + r'[\s\-_]*([a-z0-9]+)\b',
                          t.lower())
            if not m:
                continue
            tok = m.group(1)
            if tok in self._BRANCH_ACCT_LEVEL1:
                return 1
            if tok in self._BRANCH_ACCT_LEVEL2:
                best = 2
        return best

    @api.model
    def _find_branch_accountant(self, ou, exclude_employee_ids=None):
        """The Branch Accountant of operating unit `ou`, in this order:
          1. an employee titled "Branch Sales and Service Supervisor-I";
          2. else a user holding the "Branch Accountant" role (Settings ->
             Users -> Staff Loan (RESL));
          3. else an employee titled "Branch Sales and Service Supervisor-II".
        Always scoped to that single operating unit. When several people
        qualify at the winning step, exactly ONE is picked - first in
        alphabetical order of employee name - so only that person is the
        approver / disbursement officer (notified, with access); the others
        get nothing. Returns an hr.employee recordset."""
        Employee = self.env['hr.employee'].sudo()
        cands = self._find_role_employee_all(
            [self._BRANCH_ACCOUNTANT_TITLE], ou=ou,
            exclude_employee_ids=exclude_employee_ids,
        )
        lvl1 = cands.filtered(lambda e: self._branch_accountant_level(e) == 1)
        if lvl1:
            return lvl1[:1]
        emp = self._find_role_employee_by_group(
            'resl.group_resl_branch_accountant', ou=ou,
            exclude_employee_ids=exclude_employee_ids,
            order='name asc, id asc',
        )
        if emp:
            return emp
        lvl2 = cands.filtered(lambda e: self._branch_accountant_level(e) == 2)
        return lvl2[:1] if lvl2 else Employee

    @api.model
    def _find_role_employee_all(self, include_keywords, ou=None, exclude_employee_ids=None):
        """Like _find_role_employee but returns ALL matches, ordered by name."""
        Employee = self.env['hr.employee'].sudo()
        domain = [('user_id', '!=', False)]
        if ou:
            domain.append(('default_operating_unit_id', '=', ou.id))
        if exclude_employee_ids:
            domain.append(('id', 'not in', list(exclude_employee_ids)))
        leaves = []
        for kw in include_keywords:
            leaves.append(('job_id.name', 'ilike', kw))
            if 'job_title' in Employee._fields:
                leaves.append(('job_title', 'ilike', kw))
        if len(leaves) > 1:
            domain += ['|'] * (len(leaves) - 1) + leaves
        elif leaves:
            domain += leaves
        return Employee.search(domain, order='name asc, id asc')

    @api.model
    def _is_branch_accountant_employee(self, employee):
        """True when the employee is a Branch Accountant by title
        (Supervisor-I / -II) or holds the "Branch Accountant" role. Whether
        they are THE accountant of a branch is decided by
        _find_branch_accountant."""
        employee = employee.sudo()
        if self._branch_accountant_level(employee):
            return True
        user = employee.user_id
        group = self.env.ref('resl.group_resl_branch_accountant', raise_if_not_found=False)
        return bool(user and group and user in group.sudo().all_user_ids)

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
        if user.has_group('base.group_system') or user._resl_is_admin():
            return True
        designated_user = loan.designated_approver_id or loan.manager_user_id
        if designated_user and designated_user.id in user._resl_effective_user_ids():
            return True
        return bool(
            user._resl_has_group('resl.group_resl_manager')
            or user._resl_has_group('resl.group_resl_hr')
        )

    def _compute_is_my_disbursement(self):
        ids = self.env.user._resl_effective_user_ids()
        for loan in self:
            loan.is_my_disbursement = loan.disbursement_officer_id.id in ids

    def _search_is_my_disbursement(self, operator, value):
        ids = self.env.user._resl_effective_user_ids()
        positive = (operator == '=') == bool(value)
        return [('disbursement_officer_id', 'in' if positive else 'not in', ids)]

    def _compute_role_flags(self):
        user = self.env.user
        ho = user._resl_has_group  # delegation-aware
        audit = ho('resl.group_resl_hr_auditor') or user._resl_is_admin()
        hr_acct = ho('resl.group_resl_hr') or ho('resl.group_resl_hr_accountant')
        for loan in self:
            loan.can_ho_replace = loan._user_can_replace_any_stage(user)
            loan.can_audit_request = audit
            loan.can_hr_accountant = hr_acct

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
        if user.has_group('base.group_system') or user._resl_is_admin():
            return True
        if officer:
            return officer.id in user._resl_effective_user_ids()
        return bool(
            user._resl_has_group('resl.group_resl_hr')
            or user._resl_has_group('resl.group_resl_hr_accountant')
        )

    @api.depends('disbursement_officer_id', 'status', 'core_banking_status', 'employee_id',
                 'approver_id', 'disbursement_requested')
    def _compute_can_disburse(self):
        user = self.env.user
        for loan in self:
            ok = bool(loan.id) and loan._user_can_disburse(user)
            if ok and not loan.disbursement_requested:
                # Head Office flow: nobody (administrator included) can
                # disburse before the HR Auditor requested it. Only a fixed
                # officer (district / branch tier) goes straight to disbursing.
                ok = bool(loan._live_disbursement_officer())
            loan.can_disburse = ok

    @api.depends('disbursement_officer_role', 'disbursement_requested',
                 'disbursement_requested_by_id', 'disbursed_by_id', 'core_banking_status',
                 'designated_approver_role')
    def _compute_disbursement_roles(self):
        env = self.env
        def _users(xmlid):
            grp = env.ref(xmlid, raise_if_not_found=False)
            return grp.sudo().all_user_ids if grp else env['res.users']
        auditors = _users('resl.group_resl_hr_auditor')
        hr_accountants = _users('resl.group_resl_hr_accountant')
        for loan in self:
            officer_role = loan.disbursement_officer_role or ''
            if officer_role.startswith('Accountant'):
                level, disb_label = 'branch', 'Branch Accountant'
            elif officer_role.startswith('RESL District'):
                level, disb_label = 'district', 'District Officer (RESL District)'
            else:
                level, disb_label = 'head_office', 'HR Accountant'
            loan.disbursement_level = level

            req_user = loan.disbursement_requested_by_id
            if loan.disbursement_requested and req_user:
                if level == 'head_office':
                    loan.disbursement_requested_by_role = (
                        'HR Auditor' if req_user in auditors else 'HR Officer / Admin'
                    )
                else:
                    loan.disbursement_requested_by_role = (
                        'Approver (%s)' % loan.designated_approver_role
                        if loan.designated_approver_role else 'Approver'
                    )
            else:
                loan.disbursement_requested_by_role = False

            disb_user = loan.disbursed_by_id
            if disb_user and loan.core_banking_status == 'disbursed':
                if level == 'head_office' and disb_user not in hr_accountants:
                    disb_label = 'HR Officer / Admin'
                loan.disbursed_by_role = disb_label
            else:
                loan.disbursed_by_role = False

    @api.depends('guarantor_line_ids.state', 'guarantor_line_ids.guarantor_id',
                 'guarantor_line_ids.replaced_by_id', 'guarantor_line_ids.replaces_id')
    def _compute_guarantors_summary(self):
        labels = dict(self.env['resl.loan.guarantee']._fields['state'].selection)
        for loan in self:
            current, replaced = [], []
            for line in loan.sudo().guarantor_line_ids.sorted('id'):
                name = line.guarantor_id.name or ''
                is_replaced = line.state in ('replaced', 'separated') or (
                    line.replaced_by_id and line.state == 'rejected')
                if is_replaced:
                    by = line.replaced_by_id.guarantor_id.name
                    replaced.append("%s (%s%s)" % (
                        name, labels.get(line.state, line.state),
                        ", replaced by %s" % by if by else ""))
                else:
                    extra = ", being replaced" if line.is_superseded else ""
                    current.append("%s (%s%s)" % (name, labels.get(line.state, line.state), extra))
            loan.guarantors_summary = "; ".join(current) or False
            loan.replaced_guarantors_summary = "; ".join(replaced) or False

    # ── Mandatory rejection comment (approver side) ───────────────────────────

    @api.model
    def _clean_rejection_reason(self, reason):
        reason = (reason or '').strip()
        if not reason:
            raise ValidationError(_(
                "A comment (justification) is required to reject a request."
            ))
        return reason

    def _rejection_vals(self, user, reason, role_label):
        return {
            'rejection_reason': reason,
            'rejected_by_id': user.id,
            'rejected_by_role': role_label,
            'rejected_on': fields.Datetime.now(),
        }

    def _text_with_reason(self, text, reason):
        """`text` plus the justification, safe to post as HTML."""
        return Markup("%s<br/><b>%s</b> %s") % (text, _("Justification:"), reason)

    def _open_reject_wizard(self, kind):
        """Ask the approver for the (mandatory) justification before rejecting."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reject Request'),
            'res_model': 'resl.loan.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_loan_id': self.id, 'default_reject_kind': kind},
        }

    def _reject_role(self, user):
        """Which stage `user` acts at when sending an approved request back:
        'officer' (fixed disbursement officer, e.g. Branch Accountant),
        'accountant' (HR Accountant), 'auditor' (HR Auditor), 'admin', or
        False when they have no right to."""
        self.ensure_one()
        loan = self.sudo()
        if loan.status != 'approved' or loan.core_banking_status == 'disbursed':
            return False
        borrower_user = loan.employee_id.user_id
        if borrower_user and borrower_user.id == user.id:
            return False
        officer = loan._live_disbursement_officer()
        if officer:
            # Fixed officer tier (branch / district): the loan was handed to
            # the officer automatically after approval.
            if officer.id in user._resl_effective_user_ids():
                return 'officer'
        else:
            # Head Office flow: HR Auditor requests -> HR Accountant disburses.
            # The STAGE of the loan decides where a rejection goes, not who
            # clicks. Once the HR Auditor requested disbursement the loan sits
            # with HR Accountant, so a rejection there ALWAYS returns to the
            # HR Auditor (also when the rejecting user is an Admin /
            # system administrator rather than a pure HR Accountant).
            is_admin = user.has_group('base.group_system') or user._resl_is_admin()
            if loan.disbursement_requested:
                if user._resl_has_group('resl.group_resl_hr_accountant') or is_admin:
                    return 'accountant'
            elif user._resl_has_group('resl.group_resl_hr_auditor'):
                return 'auditor'
        if user.has_group('base.group_system') or user._resl_is_admin():
            return 'admin'
        return False

    def _user_can_reject_approved(self, user):
        self.ensure_one()
        return bool(self._reject_role(user))

    @api.depends('status', 'core_banking_status', 'disbursement_officer_id', 'employee_id',
                 'disbursement_requested')
    def _compute_can_reject_approved(self):
        user = self.env.user
        for loan in self:
            loan.can_reject_approved = bool(loan.id) and loan._user_can_reject_approved(user)

    def action_save_request(self):
        """Header 'Save' button on a new request. The web client saves the
        record before calling any object button, so there is nothing to do
        here beyond flagging the request as really saved."""
        self.sudo().write({'custom_saved': True})
        return True

    def action_reject_after_approval(self):
        """Button: opens the rejection dialog. A comment (justification) is
        mandatory; the actual work is done by _do_reject_after_approval."""
        self.ensure_one()
        if self.status != 'approved':
            raise ValidationError(_("Only an approved request waiting for disbursement can be sent back here."))
        if self.core_banking_status == 'disbursed':
            raise ValidationError(_("This loan has already been disbursed and can no longer be rejected."))
        if not self._reject_role(self.env.user):
            raise ValidationError(_(
                "Only the HR Auditor, HR Accountant or the disbursement officer of this "
                "request can reject it at this stage."
            ))
        return self._open_reject_wizard('after_approval')

    def _do_reject_after_approval(self, reason):
        """Send an approved request back one step instead of closing it:

        * HR Accountant      -> back to the HR Auditor (who can request
                                disbursement again),
        * HR Auditor         -> back to the approver (HO Approver) for review,
        * Disbursement officer (Branch Accountant etc.) / Admin
                             -> back to the approver for review.
        """
        reason = self._clean_rejection_reason(reason)
        for loan in self:
            user = self.env.user
            if loan.status != 'approved':
                raise ValidationError(_("Only an approved request waiting for disbursement can be sent back here."))
            if loan.core_banking_status == 'disbursed':
                raise ValidationError(_("This loan has already been disbursed and can no longer be rejected."))
            role = loan._reject_role(user)
            if not role:
                raise ValidationError(_(
                    "Only the HR Auditor, HR Accountant or the disbursement officer of this "
                    "request can reject it at this stage."
                ))
            sloan = loan.sudo()
            try:
                # Pending to-dos (disburse / request) are no longer relevant.
                sloan.activity_ids.unlink()
            except Exception:
                _logger.exception('Failed to clear activities of loan %s', loan.id)

            reset = {
                'disbursement_requested': False,
                'disbursement_requested_by_id': False,
                'disbursement_requested_date': False,
            }
            role_name = {
                'accountant': 'HR Accountant', 'auditor': 'HR Auditor',
                'officer': sloan.disbursement_officer_role or 'Disbursement Officer',
                'admin': 'Admin',
            }[role]
            if role == 'accountant':
                # Back to the HR Auditor: they can press Request Disbursement again.
                sloan.write(dict(reset, **sloan._rejection_vals(user, reason, role_name)))
                sloan.message_post(body=self._text_with_reason(_(
                    "Disbursement request rejected by %(user)s (HR Accountant) and returned "
                    "to the HR Auditor, who can request disbursement again."
                ) % {'user': user.name}, reason))
                auditor_group = self.env.ref('resl.group_resl_hr_auditor', raise_if_not_found=False)
                auditors = auditor_group.sudo().all_user_ids.filtered('active') if auditor_group else self.env['res.users']
                for auditor in auditors:
                    for notify_user in auditor._resl_notify_users():
                        try:
                            sloan.activity_schedule(
                                'mail.mail_activity_data_todo',
                                user_id=notify_user.id,
                                summary=_("Disbursement rejected for loan %s") % sloan.name,
                                note=self._text_with_reason(
                                    _("The HR Accountant (%s) rejected the disbursement request. "
                                      "Review it and request disbursement again.") % user.name,
                                    reason),
                            )
                        except Exception:
                            _logger.exception('Failed to notify HR Auditor for loan %s', loan.id)
            else:
                # Back to the approver for a new decision.
                sloan.write(dict(reset, status='manager_review',
                                 **sloan._rejection_vals(user, reason, role_name)))
                sloan._compute_designated_approver()
                role_label = {
                    'auditor': _("HR Auditor"), 'officer': _("Disbursement Officer"), 'admin': _("Admin"),
                }[role]
                sloan.message_post(body=self._text_with_reason(_(
                    "Request rejected by %(user)s (%(role)s) and returned to the approver for review."
                ) % {'user': user.name, 'role': role_label}, reason))
                target = sloan.designated_approver_id or sloan.manager_user_id
                if target:
                    for notify_user in target._resl_notify_users():
                        try:
                            sloan.activity_schedule(
                                'mail.mail_activity_data_todo',
                                user_id=notify_user.id,
                                summary=_("Loan %s returned for review") % sloan.name,
                                note=self._text_with_reason(
                                    _("%(user)s (%(role)s) rejected this request at the disbursement "
                                      "stage. Please review it again.") % {'user': user.name, 'role': role_label},
                                    reason),
                            )
                        except Exception:
                            _logger.exception('Failed to notify approver for loan %s', loan.id)
                try:
                    ids = sloan.guarantor_line_ids.mapped('guarantor_id.id')
                    if ids:
                        self.env['hr.employee'].sudo().recompute_all_guarantee_counts(ids)
                except Exception:
                    _logger.exception('Failed to refresh guarantee counts for loan %s', loan.id)

    def _notify_hr_auditors(self, approver):
        """After HO / HR approval of a loan without a fixed disbursement
        officer, hand it to the HR Auditors (activity + chatter note). The HR
        Auditor then uses "Request Disbursement" to pass it to HR Accountant."""
        self.ensure_one()
        loan = self.sudo()
        group = self.env.ref('resl.group_resl_hr_auditor', raise_if_not_found=False)
        auditors = group.sudo().all_user_ids.filtered('active') if group else self.env['res.users']
        note = _(
            "Loan %(loan)s for %(employee)s (%(amount)s %(currency)s) was approved by "
            "%(approver)s and is now waiting for HR Auditor review. The HR Auditor must "
            "request disbursement before HR Accountant can disburse it."
        ) % {
            'loan': loan.name,
            'employee': loan.employee_id.name,
            'amount': '{:,.2f}'.format(loan.approved_amount or 0.0),
            'currency': loan.currency_id.name or '',
            'approver': approver.name,
        }
        for auditor in auditors:
            try:
                for notify_user in auditor._resl_notify_users():
                    loan.activity_schedule(
                        'mail.mail_activity_data_todo',
                        user_id=notify_user.id,
                        summary=_("Review approved staff loan %s") % loan.name,
                        note=note,
                    )
            except Exception:
                _logger.exception('Failed to schedule HR Auditor activity for loan %s', loan.id)
        loan.message_post(body=note)

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
            # The officer AND whoever they currently delegate to.
            for notify_user in officer.sudo()._resl_notify_users():
                loan.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=notify_user.id,
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
            user._resl_has_group('resl.group_resl_manager')
            or user._resl_has_group('resl.group_resl_hr')
        )
        for loan in self:
            loan.is_manager_reviewer = bool(
                is_group_manager or (loan.manager_user_id.id in user._resl_effective_user_ids())
            )

    @api.depends('guarantor_line_ids.state', 'guarantor_line_ids.guarantor_id', 'employee_id',
                 'guarantor_line_ids.replaces_id')
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

    def action_discard_request(self):
        """The requester discards their own request at any stage before it is
        submitted to the manager. The record is DELETED from the database
        (not soft-deleted): its guarantor lines and replacement log go with it
        (ondelete cascade) and so do its to-dos and chatter. Called by the
        Discard widget (static/src/js/discard_button.js)."""
        user = self.env.user
        try:
            current_emp_id = user.employee_id.id if user.employee_id else False
        except Exception:
            current_emp_id = False
        # The ORM hides never-saved ("New") rows from searches unless asked.
        loans = self.with_context(
            resl_include_unsaved=True, resl_hard_delete=True, active_test=False
        ).sudo().browse(self.ids).exists()
        for loan in loans:
            if not (loan.employee_id and current_emp_id and loan.employee_id.id == current_emp_id):
                raise ValidationError(_("Only the requester can discard this request."))
            if loan.status not in ('draft', 'guarantor_pending'):
                raise ValidationError(_(
                    "This request has already been submitted and can no longer be discarded."
                ))
        guarantor_ids = loans.mapped('guarantor_line_ids.guarantor_id').ids
        loans.unlink()
        try:
            if guarantor_ids:
                self.env['hr.employee'].sudo().recompute_all_guarantee_counts(guarantor_ids)
        except Exception:
            _logger.exception("Failed to refresh guarantee counts after discarding a request")
        return True

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

    @api.depends('guarantor_line_ids.state', 'guarantor_line_ids.guarantor_id', 'employee_id', 'status',
                 'guarantor_line_ids.replaces_id')
    def _compute_guarantor_second_notice(self):
        Validations = self.env['resl.validations']
        for loan in self:
            notice = False
            if loan.employee_id and loan.status in ('draft', 'guarantor_pending'):
                state = Validations.guarantor_slot_state(loan)
                all_live = loan.guarantor_line_ids.filtered(
                    lambda l: l.state in ('draft', 'pending', 'accepted')
                )
                # A guarantor being replaced is not counted: only the guarantors
                # that will stay on the request are.
                lines = all_live.filtered(lambda l: not l.is_superseded)
                being_replaced = all_live - lines
                if state == 'needs_second':
                    notice = _(
                        "You need to select another guarantor. Click 'Find Guarantor' to "
                        "choose the second guarantor. The request is sent to both guarantors "
                        "once they are both selected."
                    )
                    if being_replaced:
                        notice = _(
                            "The replacement guarantor's salary does not cover this request, so "
                            "another guarantor is needed. Use 'Replace Guarantor' (choose the "
                            "guarantor being replaced) or 'Find Guarantor' to select the second "
                            "one. The request is sent to both once they are selected."
                        )
                elif state == 'full' and len(lines) == 2 and loan.status == 'guarantor_pending' \
                        and not loan.all_guarantors_accepted:
                    accepted = len(lines.filtered(lambda l: l.state == 'accepted'))
                    notice = _(
                        "This request has two guarantors. Both must accept before it can "
                        "go further (%(done)s of 2 accepted)."
                    ) % {'done': accepted}
                elif being_replaced and not loan.all_guarantors_accepted:
                    notice = _(
                        "Waiting for the replacement guarantor to accept. %(names)s stays on "
                        "the request until then."
                    ) % {'names': ", ".join(being_replaced.sudo().mapped('guarantor_id.name'))}
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
            elif loan.status == 'manager_review':
                # Submitted to the manager, waiting for approval.
                loan.progress_status = 'submitted'
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
                user._resl_has_group('resl.group_resl_hr')
                or user._resl_has_group('resl.group_resl_manager')
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
            if designated_user and designated_user.id in user._resl_effective_user_ids():
                loan.show_approve_button = True
                continue
            if user._resl_is_admin():
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
                user._resl_has_group('resl.group_resl_manager')
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

    # ── Who may replace a guarantor ───────────────────────────────────────────
    # * The requester: while the request is not yet approved (draft, waiting
    #   for guarantors, manager review) or when a replacement is required.
    # * At ANY step, even after disbursement: the HO Approver, HR Approver,
    #   the Branch Manager / District Director of the borrower's work unit,
    #   and Administrators.
    # * NOT allowed any more: Branch Accountant (Branch Sales and Service
    #   Supervisor-I), HR Auditor, HR Accountant, HR Officer, RESL District.
    _HO_REPLACEMENT_GROUPS = (
        'resl.group_resl_ho_approver',
        'resl.group_resl_hr_senior',      # HR Approver
    )
    _REQUESTER_REPLACE_STATUSES = ('draft', 'guarantor_pending', 'manager_review')

    def _user_is_ho_replacer(self, user=None):
        """Role-based (not per-loan) replacers: HO Approver, HR Approver, Admin."""
        user = user or self.env.user
        return bool(
            any(user._resl_has_group(g) for g in self._HO_REPLACEMENT_GROUPS)
            or user._resl_is_admin()
        )

    def _user_is_unit_head_of_loan(self, user=None):
        """True when `user` (or someone delegating to them) is a Branch
        Manager / District Director of this loan's work unit - i.e. holds a
        "manager" (branch tiers) or "director" (district / regional tiers)
        job title with that work unit as Default Operating Unit. Any such
        holder qualifies (not only the first one routing happens to pick)."""
        self.ensure_one()
        user = user or self.env.user
        loan = self.sudo()
        emp = loan.employee_id
        if not emp:
            return False
        ou = self.env['resl.validations'].get_employee_operating_unit(emp)
        wut = getattr(ou, 'work_unit_type', False) if ou else False
        if not ou:
            return False
        if wut in ('branch', 'sub_branch', 'service_center'):
            keyword, excl = 'manager', ('accountant', self._BRANCH_ACCOUNTANT_TITLE)
        elif wut in ('district_office', 'regional_office'):
            keyword, excl = 'director', ()
        else:
            return False
        heads = self.env['hr.employee'].sudo().search([
            ('user_id', 'in', list(user._resl_effective_user_ids())),
            ('default_operating_unit_id', '=', ou.id),
        ])
        for h in heads:
            titles = [(h.job_id.name or '') if h.job_id else '']
            if 'job_title' in h._fields:
                titles.append(h.job_title or '')
            if any(keyword in t.lower() and not any(x in t.lower() for x in excl)
                   for t in titles):
                return True
        return False

    def _user_can_replace_any_stage(self, user=None):
        self.ensure_one()
        user = user or self.env.user
        return self._user_is_ho_replacer(user) or self._user_is_unit_head_of_loan(user)

    def _check_can_replace_guarantor(self):
        self.ensure_one()
        if self.env.su or self._user_can_replace_any_stage():
            return True
        emp = self.env.user.employee_id
        is_requester = bool(emp and self.employee_id and self.employee_id.id == emp.id)
        if is_requester and (
            self.status in self._REQUESTER_REPLACE_STATUSES or self.needs_guarantor_replacement
        ):
            return True
        raise ValidationError(_(
            "You can no longer replace the guarantor on this request. "
            "Only the requester (until approval), the Branch Manager / District "
            "Director or Head Office can do so."
        ))

    def _replaceable_guarantee_lines(self):
        return self.guarantor_line_ids.filtered(lambda l: l.state not in ('replaced', 'rejected'))

    # ── Replacement wizard actions ────────────────────────────────────────────

    def action_request_replacement(self):
        self.ensure_one()
        self._check_can_replace_guarantor()
        if not self.guarantor_line_ids:
            pass  # validation disabled for migration; re-enable after data import
        ctx = dict(self.env.context or {})
        ctx['default_loan_id'] = self.id

        # The wizard needs to know WHICH guarantor line is being replaced. With
        # a single guarantor it is pre-selected; with two, the user picks one
        # in the wizard (both are offered).
        lines = self._replaceable_guarantee_lines()
        if len(lines) == 1:
            ctx['default_old_guarantee_id'] = lines.id

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
                'name': _('Replace Guarantor'),
                'res_model': 'resl.loan.replacement.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': ctx,
            }

    def action_nominate_replacement(self):
        self.ensure_one()
        self._check_can_replace_guarantor()
        ctx = dict(self.env.context or {})
        ctx['default_loan_id'] = self.id
        lines = self._replaceable_guarantee_lines()
        separated = lines.filtered(lambda l: l.state == 'separated')
        if len(separated) == 1:
            ctx['default_old_guarantee_id'] = separated.id
        elif len(lines) == 1:
            ctx['default_old_guarantee_id'] = lines.id
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
        """Handle borrower/manual and HR-initiated guarantor replacement.

        Same two-guarantor rule as Find Guarantor:
          * the new guarantor is judged as if the guarantor being replaced were
            already gone;
          * if the new guarantor's salary covers the borrower, the request goes
            to them straight away;
          * if it does NOT, nothing is sent yet: the new line waits as a draft
            until a second replacement guarantor is nominated (same call again)
            and their COMBINED salaries cover the borrower - then both are
            notified at once.
        The guarantor being replaced is NOT rejected here. It stays on the
        request and is rejected only once the replacement guarantor(s) accepted
        (see _finalize_guarantor_replacements). Exception: a line that is
        already out of play (separated guarantor, or one still in draft) is
        released immediately.
        """
        self.ensure_one()
        Guarantee = self.env['resl.loan.guarantee']
        Validations = self.env['resl.validations']
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

        # Judge everything as if the guarantor being replaced were already gone.
        replacing_ctx = {'resl_replacing_line_ids': old_line.ids}
        self.with_context(**replacing_ctx)._ensure_guarantor_is_eligible(
            new_emp, exclude_loan_id=self.id, strict=True
        )
        Validations.with_context(**replacing_ctx).ensure_can_add_replacement(self, old_line)

        # The same person cannot be nominated while still a current guarantor.
        current_dupe = Guarantee.sudo().search([
            ('loan_id', '=', self.id),
            ('guarantor_id', '=', new_emp.id),
            ('state', 'not in', ('replaced', 'rejected')),
        ], limit=1)
        if current_dupe:
            raise ValidationError(_(
                "%s is already a guarantor of this loan and cannot be nominated again."
            ) % new_emp.name)
        # A guarantor who was rejected / replaced earlier may be nominated again.
        # The DB allows one live line per (loan, guarantor), so archive (soft
        # delete) the stale line first; the row and its chatter are kept.
        Guarantee.sudo().search([
            ('loan_id', '=', self.id),
            ('guarantor_id', '=', new_emp.id),
            ('state', 'in', ('replaced', 'rejected')),
        ]).write({'active': False})

        # Created as a DRAFT: it is only sent to the guarantor (pending) below,
        # once the guarantor(s) chosen cover the borrower's salary.
        new_line = Guarantee.with_context(
            resl_allow_replacement_create=True, **replacing_ctx
        ).create({
            'loan_id': self.id,
            'guarantor_id': new_emp.id,
            'state': 'draft',
            'replaces_id': old_line.id,
        })
        # (an older line of this guarantor may have been revived instead of
        # created, so make sure the link is really set)
        new_line.sudo().write({'replaces_id': old_line.id})

        if old_line.state in ('draft', 'separated'):
            # Nobody is relying on this line any more: release it right away.
            old_line.sudo().write({
                'replaced_by_id': new_line.id,
                'replaced_at': fields.Datetime.now(),
                'state': 'rejected',
            })
            self._cleanup_replaced_guarantor(old_line)

        self.invalidate_recordset(['guarantor_line_ids'])
        self.guarantor_line_ids.invalidate_recordset()

        # Two-guarantor rule: send only once the guarantor(s) chosen cover the
        # borrower. Otherwise the new line waits (draft) for the second one.
        covered = Validations.guarantor_coverage(self)['covered']
        if covered:
            self._send_draft_guarantor_requests()
            note_msg = _(
                "Replacement requested: %(new)s replacing %(old)s. %(old)s stays on the "
                "request until %(new)s accepts."
            ) % {'new': new_emp.name, 'old': old_line.guarantor_id.name}
        else:
            note_msg = _(
                "Replacement guarantor %(new)s selected for %(old)s. Another guarantor is "
                "required before the request is sent."
            ) % {'new': new_emp.name, 'old': old_line.guarantor_id.name}
        self.sudo().message_post(body=note_msg)

        if not is_system_action:
            vals = {'needs_guarantor_replacement': False}
            # Only a request still in progress goes back to "Waiting Guarantees".
            # An approved / disbursed loan keeps its status when HO replaces a guarantor.
            if self.status in ('draft', 'guarantor_pending', 'manager_review'):
                vals['status'] = 'guarantor_pending'
            self.sudo().write(vals)
        else:
            try:
                self.sudo().write({'needs_guarantor_replacement': False})
            except Exception:
                _logger.exception('Failed to clear needs_guarantor_replacement for loan %s', self.id)

        # Odoo 17: use invalidate_recordset instead of invalidate_cache
        self.invalidate_recordset(['guarantor_line_ids', 'all_guarantors_accepted', 'can_submit_manager'])
        return new_line

    def _send_draft_guarantor_requests(self):
        """Turn every draft guarantor line of the request into a pending one and
        notify the guarantors (they can now accept / reject)."""
        self.ensure_one()
        loan = self.sudo()
        for line in loan.guarantor_line_ids.filtered(lambda l: l.state == 'draft'):
            line.write({'state': 'pending'})
            guarantor_user = line.guarantor_id.user_id if line.guarantor_id else False
            if not guarantor_user:
                continue
            try:
                loan.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=guarantor_user.id,
                    note=_("You have been nominated as guarantor for loan %s. Please review.") % loan.name,
                )
                if guarantor_user.partner_id:
                    loan.message_notify(
                        partner_ids=[guarantor_user.partner_id.id],
                        subject=_("Guarantee request for loan %s") % loan.name,
                        body=_("%(emp)s has asked you to guarantee loan %(loan)s. "
                               "Please accept or reject it.") % {
                            'emp': loan.employee_id.name, 'loan': loan.name},
                    )
            except Exception:
                _logger.exception("Failed to notify nominated guarantor %s", line.guarantor_id.id)

    def _cleanup_replaced_guarantor(self, old_line):
        """The replaced guarantor must no longer see this request (record rules
        hide it), so drop their pending to-do: it would point at a record
        they can no longer open."""
        self.ensure_one()
        try:
            old_user = old_line.guarantor_id.user_id
            if old_user:
                self.sudo().activity_ids.filtered(
                    lambda a: a.user_id.id == old_user.id
                ).unlink()
                self.sudo().message_unsubscribe(partner_ids=old_user.partner_id.ids)
        except Exception:
            _logger.exception("Failed to clean up the replaced guarantor's activities.")

    def _finalize_guarantor_replacements(self):
        """Reject the guarantor(s) being replaced once their replacement(s)
        accepted.

        Called every time a guarantor accepts. A line being replaced (pending /
        accepted, with a live replacement line) is rejected only when EVERY
        guarantor that remains on the request (the replacements plus anybody
        that is not being replaced) has accepted AND together they cover the
        borrower's salary. Until then the old guarantor stays on the request and
        the request keeps waiting for guarantees.
        """
        Validations = self.env['resl.validations']
        finished = self.env['resl.loan.guarantee']
        for loan in self.sudo():
            lines = loan.guarantor_line_ids
            superseded = lines.filtered(
                lambda l: l.state in ('pending', 'accepted') and l.is_superseded
            )
            if not superseded:
                continue
            current = lines.filtered(
                lambda l: l.state in ('draft', 'pending', 'accepted') and not l.is_superseded
            )
            if not current or any(l.state != 'accepted' for l in current):
                continue
            if not Validations.guarantor_coverage(loan)['covered']:
                continue
            affected_ids = set(current.mapped('guarantor_id').ids)
            for old in superseded:
                new_line = old.replacement_line_ids.filtered(lambda l: l.state == 'accepted')[:1]
                old.write({
                    'state': 'rejected',
                    'replaced_by_id': new_line.id if new_line else False,
                    'replaced_at': fields.Datetime.now(),
                })
                affected_ids.add(old.guarantor_id.id)
                try:
                    loan.message_post(body=_(
                        "Guarantor %(old)s was replaced by %(new)s and removed from the request "
                        "after %(new)s accepted."
                    ) % {'old': old.guarantor_id.name,
                         'new': new_line.guarantor_id.name if new_line else _("the new guarantor")})
                except Exception:
                    _logger.exception("Failed to post replacement message on loan %s", loan.id)
                loan._cleanup_replaced_guarantor(old)
            finished |= superseded
            try:
                self.env['hr.employee'].sudo().recompute_all_guarantee_counts(list(affected_ids))
            except Exception:
                _logger.exception('Failed to refresh guarantee counts for loan %s', loan.id)
            loan.invalidate_recordset(['guarantor_line_ids', 'all_guarantors_accepted', 'can_submit_manager'])
        return finished

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

    def _service_start_date(self, employee):
        """Contract start date used for the length of service (same source as
        _months_of_service), or False."""
        if not employee:
            return False
        contract = self._get_latest_contract(employee, sudo=True)
        if not contract:
            return False
        date_field = 'contract_date_start' if hasattr(contract, 'contract_date_start') else 'date_start'
        start = getattr(contract, date_field, False)
        if not start:
            return False
        return fields.Date.from_string(start) if isinstance(start, str) else start

    def _service_duration_text(self, employee):
        """Length of service as '2 years, 3 months, 10 days'."""
        start = self._service_start_date(employee)
        if not start:
            return ''
        today = fields.Date.context_today(self)
        today = fields.Date.from_string(today) if isinstance(today, str) else today
        if start > today:
            return ''
        delta = relativedelta(today, start)

        def _unit(n, one, many):
            return "%d %s" % (n, one if n == 1 else many)

        # Only show the units that are not zero: "7 months, 8 days", not
        # "0 years, 7 months, 8 days".
        parts = [
            _unit(n, one, many)
            for n, one, many in (
                (delta.years, _("year"), _("years")),
                (delta.months, _("month"), _("months")),
                (delta.days, _("day"), _("days")),
            ) if n
        ]
        return ", ".join(parts) if parts else _("0 days")

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
            ('custom_saved', '=', True),  # an auto-saved, never-saved New form is not a request
            ('name', '!=', 'New'),
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

    # ── Show the validations when "New" is clicked ───────────────────────────

    @api.model
    def _new_request_block_reasons(self, emp):
        """Every reason this employee cannot start a new request (empty = free)."""
        if not emp:
            return []
        emp = emp.sudo()
        virtual = self.new({'employee_id': emp.id})
        _ok, reasons = self.env['resl.validations'].check_borrower_eligibility(
            virtual, emp, raise_exception=False
        )
        reasons = list(reasons or []) + list(self._request_blockers(emp))
        seen, unique = set(), []
        for r in reasons:
            if r not in seen:
                seen.add(r)
                unique.append(r)
        return unique

    @api.model
    def _raise_if_new_request_blocked(self, emp):
        """Show the validation message(s) instead of opening a new request."""
        if self.env.context.get('resl_skip_new_check') or not emp:
            return
        reasons = self._new_request_block_reasons(emp)
        if reasons:
            raise ValidationError(
                _("You cannot create a new loan request:") + "\n\n• " + "\n• ".join(reasons)
            )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # Every "New" (whatever list/kanban/menu it is clicked from): a blocked
        # employee gets the validation message and the form never opens.
        if 'employee_id' in fields_list and res.get('employee_id'):
            self._raise_if_new_request_blocked(
                self.env['hr.employee'].sudo().browse(res['employee_id'])
            )
        return res

    def onchange(self, values, field_names, fields_spec):
        # First load of a brand-new form (no record, no changed field): same
        # check, in case the client does not go through default_get.
        if not self.ids and not field_names and 'employee_id' in (fields_spec or {}):
            emp = self.env.user.employee_id
            if emp:
                self._raise_if_new_request_blocked(emp)
        return super().onchange(values, field_names, fields_spec)

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
        # A deleted request must not keep notifying anyone: drop its pending to-dos.
        self.sudo().mapped('activity_ids').unlink()
        return self._soft_delete()

    # ── Create / Write overrides ──────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        """
        Odoo 17: override create with @api.model_create_multi for batch support.
        Single-record callers still work transparently.
        """
        result = self.env['resl.loan']
        # Refreshing / leaving an unsaved New form makes the web client
        # auto-create a fresh draft each time. Drop this user's earlier
        # never-saved drafts so they do not pile up in the table.
        if any(not v.get('custom_saved') for v in vals_list):
            self._purge_unsaved_drafts_of_user()
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

            # The reference number is only taken once the request is really
            # saved (Save button / Find Guarantor): an auto-saved New form
            # stays 'New' and burns no number. See _assign_loan_reference.
            if vals.get('name', 'New') == 'New' and vals.get('custom_saved'):
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
            user._resl_has_group('resl.group_resl_manager')
            or user._resl_has_group('resl.group_resl_hr')
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
        if vals.get('custom_saved'):
            self._assign_loan_reference()
        return res

    def _assign_loan_reference(self):
        """Give every saved request that still is 'New' its sequence number."""
        Sequence = self.env['ir.sequence'].sudo()
        for loan in self.sudo():
            if loan.custom_saved and (not loan.name or loan.name == 'New'):
                seq = Sequence.search([('code', '=', 'resl.loan')], limit=1)
                loan.name = seq.next_by_id() if seq else 'LOAN/NEW'

    @api.model
    def _search(self, domain, *args, **kwargs):
        """Requests that were only auto-saved by the web client (custom_saved
        False) are invisible to every search, list, kanban, report and
        count - and to the 'one pending request' rules. Direct reads by id
        (the form that is being filled in) are not affected. Pass context
        resl_include_unsaved=True to see them (cron clean-up)."""
        # Lookups BY ID (record-rule / access checks, reading the record that was
        # just auto-saved, the pager) must still find the record, otherwise Odoo
        # reports an Access Error on the form the user is filling in.
        # Only POSITIVE id lookups: a search that EXCLUDES an id
        # ('id', '!=', x) - e.g. the one-pending-request rule - must still hide
        # unsaved requests.
        _d = str(domain)
        by_id = "'id', 'in'" in _d or "'id', '='" in _d
        if not by_id and not self.env.context.get('resl_include_unsaved'):
            try:
                from odoo.fields import Domain  # Odoo 19
                base = Domain(domain if domain is not None else [])
                domain = base & Domain('custom_saved', '=', True) & Domain('name', '!=', 'New')
            except ImportError:
                from odoo.osv import expression
                domain = expression.AND([
                    domain or [], [('custom_saved', '=', True), ('name', '!=', 'New')]
                ])
        return super()._search(domain, *args, **kwargs)

    @api.model
    def _purge_unsaved_drafts_of_user(self):
        """Hard-delete the current user's auto-saved drafts that were never
        saved (custom_saved False, still 'New')."""
        stale = self.sudo().with_context(
            resl_include_unsaved=True, resl_hard_delete=True, active_test=False
        ).search([
            ('create_uid', '=', self.env.uid),
            ('custom_saved', '=', False),
            ('name', '=', 'New'),
            ('status', '=', 'draft'),
        ])
        if stale:
            stale.unlink()

    @api.model
    def _cron_cleanup_unsaved_requests(self):
        """Delete requests the web client auto-saved but nobody ever saved
        (older than 1 hour)."""
        threshold = fields.Datetime.now() - timedelta(hours=1)
        abandoned = self.sudo().with_context(
            resl_include_unsaved=True, resl_hard_delete=True, active_test=False
        ).search([
            '|', ('custom_saved', '=', False), ('name', '=', 'New'),
            ('status', '=', 'draft'),
            ('create_date', '<', threshold),
        ])
        if abandoned:
            _logger.info("RESL: cleaning up %d abandoned unsaved requests", len(abandoned))
            abandoned.unlink()

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

            sloan = loan.sudo()
            sloan.write({'status': 'manager_review'})

            # Recompute designated approver live
            try:
                sloan._compute_designated_approver()
            except Exception:
                _logger.exception("Error computing designated approver on submit for loan %s", loan.id)

            approver_user = sloan.designated_approver_id or sloan.manager_user_id

            # Fallback discovery if exact job-title lookup was empty:
            if not approver_user:
                emp = sloan.employee_id
                ou = sloan.operating_unit_id or self.env['resl.validations'].get_employee_operating_unit(emp)
                work_unit_type = getattr(ou, 'work_unit_type', False) if ou else False

                # 1. Branch fallback: find any manager in the same operating unit
                if work_unit_type in ('branch', 'sub_branch', 'service_center') and ou:
                    mgr_candidates = self.env['hr.employee'].sudo().search([
                        ('default_operating_unit_id', '=', ou.id),
                        ('user_id', '!=', False),
                        ('user_id', '!=', emp.user_id.id if emp.user_id else False),
                        '|', ('job_id.name', 'ilike', 'manager'), ('job_title', 'ilike', 'manager'),
                    ], limit=1)
                    if mgr_candidates:
                        approver_user = mgr_candidates.user_id
                        sloan.write({
                            'designated_approver_id': approver_user.id,
                            'designated_approver_role': 'Manager',
                        })

                # 2. District fallback: search for director or RESL District group in that district
                elif work_unit_type in ('district_office', 'regional_office') and ou:
                    dist_candidates = self.env['hr.employee'].sudo().search([
                        ('default_operating_unit_id', '=', ou.id),
                        ('user_id', '!=', False),
                        ('user_id', '!=', emp.user_id.id if emp.user_id else False),
                        '|', ('job_id.name', 'ilike', 'director'), ('job_title', 'ilike', 'director'),
                    ], limit=1)
                    if dist_candidates:
                        approver_user = dist_candidates.user_id
                        sloan.write({
                            'designated_approver_id': approver_user.id,
                            'designated_approver_role': 'Director',
                        })
                    else:
                        dist_grp = self.env.ref('resl.group_resl_district', raise_if_not_found=False)
                        if dist_grp and dist_grp.all_user_ids:
                            approver_user = dist_grp.all_user_ids.filtered(lambda u: u.id != emp.user_id.id)[:1]
                            if approver_user:
                                sloan.write({
                                    'designated_approver_id': approver_user.id,
                                    'designated_approver_role': 'RESL District',
                                })

                # 3. Head Office fallback: look for any HO Approver / HR Senior / HR Officer
                if not approver_user:
                    ho_group = self.env.ref('resl.group_resl_ho_approver', raise_if_not_found=False)
                    if ho_group and ho_group.all_user_ids:
                        approver_user = ho_group.all_user_ids.filtered(lambda u: u.id != emp.user_id.id)[:1]
                        if approver_user:
                            sloan.write({
                                'designated_approver_id': approver_user.id,
                                'designated_approver_role': 'HO Approver',
                            })

            approver_title = sloan.designated_approver_role or _("Manager")
            sloan.message_post(body=_("Loan submitted to %(role)s (%(approver)s) by %(user)s.") % {
                'role': approver_title,
                'approver': approver_user.name if approver_user else _("Unassigned"),
                'user': user.name,
            })

            # Send Activity and Inbox Message to Approver and all Delegated Users
            if approver_user:
                notify_users = list(approver_user.sudo()._resl_notify_users())
                if approver_user not in notify_users:
                    notify_users.append(approver_user)

                # Ensure approver is subscribed to chatter
                partner_ids = [u.partner_id.id for u in notify_users if u.partner_id]
                if partner_ids:
                    sloan.message_subscribe(partner_ids=partner_ids)

                for notify_user in notify_users:
                    try:
                        sloan.activity_schedule(
                            'mail.mail_activity_data_todo',
                            user_id=notify_user.id,
                            summary=_("Staff Loan Review Required: %s") % sloan.name,
                            note=_("Loan %(loan)s submitted by %(borrower)s for your review as %(role)s. "
                                   "Requested Amount: %(amount)s %(currency)s.") % {
                                'loan': sloan.name,
                                'borrower': sloan.employee_id.name,
                                'role': approver_title,
                                'amount': '{:,.2f}'.format(sloan.requested_amount or 0.0),
                                'currency': sloan.currency_id.name or '',
                            }
                        )
                    except Exception:
                        _logger.exception("Failed to schedule manager review activity for user %s on loan %s", notify_user.id, sloan.id)

                    if notify_user.partner_id:
                        try:
                            sloan.message_notify(
                                partner_ids=[notify_user.partner_id.id],
                                subject=_("Action Required: Staff Loan Review (%s)") % sloan.name,
                                body=_("Staff loan %(loan)s requested by %(borrower)s is waiting for your approval as %(role)s.") % {
                                    'loan': sloan.name,
                                    'borrower': sloan.employee_id.name,
                                    'role': approver_title,
                                }
                            )
                        except Exception:
                            _logger.exception("Failed to send message notification to approver partner %s", notify_user.partner_id.id)
            else:
                _logger.warning("RESL: No approver could be found for loan %s (work unit: %s)", loan.name, sloan.operating_unit_id.name if sloan.operating_unit_id else 'None')

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
            is_designated = bool(designated_user and designated_user.id in user._resl_effective_user_ids())
            if not (
                is_designated
                or user._resl_has_group('resl.group_resl_manager')
                or user._resl_has_group('resl.group_resl_hr')
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
            if not allow and designated_user and designated_user.id in user._resl_effective_user_ids():
                allow = True
            if not allow and user._resl_is_admin():
                allow = True  # RESL Administrator: no routing / work-unit restriction

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
                            and user._resl_has_group('resl.group_resl_head_office')):
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
                user._resl_has_group('resl.group_resl_manager')
                or user._resl_has_group('resl.group_resl_hr')
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

            # Head Office flow (no fixed disbursement officer): the approved loan
            # goes to the HR Auditor, who then requests disbursement.
            if not routed_to_officer:
                try:
                    loan._notify_hr_auditors(user)
                except Exception:
                    _logger.exception("Failed to notify HR Auditors for loan %s", loan.id)

            # Notify HR after manager approval (only for loans without a
            # fixed disbursement officer, e.g. Head Office)
            try:
                if (not routed_to_officer
                        and user._resl_has_group('resl.group_resl_manager')
                        and not user._resl_has_group('resl.group_resl_hr')):
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
        """Button: opens the rejection dialog. A comment (justification) is
        mandatory for the approver; the actual work is done by
        _do_manager_reject."""
        self.ensure_one()
        if self.status != 'manager_review':
            raise ValidationError(_("Only a request waiting for approval can be rejected here."))
        return self._open_reject_wizard('manager')

    def _do_manager_reject(self, reason):
        reason = self._clean_rejection_reason(reason)
        for loan in self:
            user = self.env.user

            # Same reasoning as action_manager_approve: recompute routing
            # first, then allow the designated approver through even
            # without the Loan Manager technical group.
            loan.sudo()._compute_designated_approver()

            designated_user = loan.designated_approver_id or loan.manager_user_id
            is_designated = bool(designated_user and designated_user.id in user._resl_effective_user_ids())
            if not (
                is_designated
                or user._resl_has_group('resl.group_resl_manager')
                or user._resl_has_group('resl.group_resl_hr')
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
            if designated_user and designated_user.id in user._resl_effective_user_ids():
                allow = True
            if not allow and user._resl_is_admin():
                allow = True  # RESL Administrator: no routing / work-unit restriction

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
                            and user._resl_has_group('resl.group_resl_head_office')):
                        allow = True
                        used_head_office_exception = True
            if not allow:
                raise ValidationError(
                    "Approver and borrower must be in the same operating unit to reject this loan."
                )
            loan.sudo().write(dict(
                {'status': 'rejected'},
                **loan._rejection_vals(user, reason, loan.designated_approver_role or 'Approver')
            ))
            try:
                if used_head_office_exception:
                    text = _("Loan rejected by %s via head-office sol_id exception.") % user.name
                else:
                    text = _("Loan rejected by %s.") % user.name
                loan.sudo().message_post(body=self._text_with_reason(text, reason))
            except Exception:
                _logger.exception('Failed to post rejection message for loan %s', loan.id)
            # Tell the requester why, so they can act on it.
            try:
                borrower_user = loan.sudo().employee_id.user_id
                if borrower_user and borrower_user.partner_id:
                    loan.sudo().message_notify(
                        partner_ids=[borrower_user.partner_id.id],
                        subject=_("Your loan request %s was rejected") % loan.name,
                        body=self._text_with_reason(
                            _("Your loan request %(loan)s was rejected by %(user)s.") % {
                                'loan': loan.name, 'user': user.name},
                            reason),
                    )
            except Exception:
                _logger.exception('Failed to notify the requester about the rejection of loan %s', loan.id)

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
            user._resl_has_group('resl.group_resl_hr_auditor')
            or user._resl_has_group('resl.group_resl_hr')
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
                # Reload the open form right away so the "Request
                # Disbursement" button (invisible once
                # disbursement_requested is True) disappears without a
                # manual page refresh.
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
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
            user._resl_has_group('resl.group_resl_hr')
            or user._resl_has_group('resl.group_resl_hr_accountant')
            or user.has_group('base.group_system')
        ):
            raise ValidationError(_("Only POMD / HR / HR Accountant or Administrators can update settlement status."))
        self.write({'settlement_status': 'settled'})
        self.message_post(body=_("Loan marked as fully settled by %s.") % user.name)


class ResUsers(models.Model):
    _inherit = 'res.users'

    resl_scope_operating_unit_ids = fields.Many2many(
        'operating.unit', compute='_compute_resl_scope_operating_unit_ids',
        string="RESL Review Scope (Work Units)",
        help="Work units whose staff-loan requests this user may see because "
             "they hold a RESL role (Loan Manager / RESL District / Branch "
             "Accountant ...). Empty for everybody else: a Job Position / Job "
             "Title (Manager, Director, ...) does NOT grant visibility. Used by "
             "the 'RESL Loan: work-unit reviewers' record rules.",
    )

    def _compute_resl_scope_operating_unit_ids(self):
        """Work units a user may see staff-loan requests for.

        ONLY users holding a RESL role (Loan Manager baseline right, which
        HR / HO Approver / Branch Accountant / RESL District / Head Office
        all imply, or RESL District itself) get a scope. Their scope is
        their own operating unit(s): default OU + every OU on their employee
        record.

        A Job Position / Job Title (Operating-Unit Manager, Director,
        Accountant, ...) does NOT grant any visibility any more. Someone who
        is merely the manager of the borrower's unit sees a request only
        when they are actually part of its flow:
          - the borrower, or a guarantor (employee rule),
          - the designated approver (designated-approver rule),
          - the disbursement officer (disbursement-officer rule),
          - or hold a RESL role (this scope / the Head Office rules).
        """
        OU = self.env['operating.unit'].sudo()
        Employee = self.env['hr.employee'].sudo()
        validations = self.env['resl.validations']
        for user in self:
            ous = OU
            if not user.id:
                user.resl_scope_operating_unit_ids = ous
                continue
            # The user's own role AND the roles of everyone who currently
            # delegates to them (hr_employee_delegation, start/end date).
            for actor in user._resl_effective_users():
                actor = actor.sudo()
                is_reviewer = bool(
                    actor.has_group('resl.group_resl_manager')
                    or actor.has_group('resl.group_resl_district')
                )
                if not is_reviewer:
                    continue
                for emp in Employee.search([('user_id', '=', actor.id)]):
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