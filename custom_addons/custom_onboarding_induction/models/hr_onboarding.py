# -*- coding: utf-8 -*-

import logging
from datetime import timedelta
from markupsafe import Markup
from odoo import api, fields, models, _
from odoo import fields as odoo_fields
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class HrOnboardingPlan(models.Model):
    _name = "hr.onboarding.plan"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Workplace Onboarding Management Plan"
    _rec_name = "name"
    _order = "start_date desc"

    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    def write(self, vals):
        user = self.env.user
        if self.env.su or user.id == 1:
            return super().write(vals)

        is_officer_or_admin = (
            getattr(user, "_is_admin", lambda: False)()
            or user.has_group("custom_onboarding_induction.group_onboarding_induction_manager")
            or user.has_group("custom_onboarding_induction.group_onboarding_induction_officer")
            or user.has_group("base.group_system")
        )

        system_fields = {
            "message_follower_ids", "message_ids", "activity_ids",
            "message_main_attachment_id", "message_partner_ids"
        }

        if not is_officer_or_admin:
            mod_keys = set(vals.keys()) - system_fields
            if mod_keys:
                user_employee_ids = set(user.employee_ids.ids) if hasattr(user, "employee_ids") else set()
                if getattr(user, "employee_id", False):
                    user_employee_ids.add(user.employee_id.id)

                for rec in self:
                    rec_sudo = rec.sudo()
                    allowed = set()

                    sup = rec_sudo.supervisor_id
                    is_sup = bool(
                        sup and (
                            (sup.user_id and sup.user_id.id == user.id)
                            or (sup.id in user_employee_ids)
                        )
                    )
                    if is_sup:
                        allowed |= {
                            "midterm_supervisor_feedback",
                            "midterm_score",
                            "final_supervisor_signoff",
                            "final_supervisor_signoff_date",
                            "final_supervisor_signoff_user_id",
                            "escalation_reason",
                            "probation_id",
                            "final_eval_sent",
                            "final_onboarding_score",
                        }

                    emp = rec_sudo.employee_id
                    is_emp = bool(
                        emp and (
                            (emp.user_id and emp.user_id.id == user.id)
                            or (emp.id in user_employee_ids)
                        )
                    )
                    if is_emp:
                        allowed |= {
                            "midterm_employee_feedback",
                            "final_employee_signoff",
                            "final_employee_signoff_date",
                            "final_employee_signoff_user_id",
                        }

                    bud = rec_sudo.buddy_id
                    is_buddy = bool(
                        bud and (
                            (bud.user_id and bud.user_id.id == user.id)
                            or (bud.id in user_employee_ids)
                        )
                    )
                    if is_buddy:
                        allowed |= {"buddy_notes"}

                    if user.has_group("custom_onboarding_induction.group_onboarding_induction_it"):
                        allowed |= {"provisioning_status", "it_provisioning_notes", "it_checklist_done"}
                    if user.has_group("custom_onboarding_induction.group_onboarding_induction_facility"):
                        allowed |= {"facility_provisioning_notes", "facility_checklist_done"}

                    disallowed = mod_keys - allowed
                    if disallowed:
                        raise ValidationError(_(
                            "Permission Denied: You are not authorized to modify the following field(s): %s.\n"
                            "Supervisor Mid-Term Feedback can only be entered by the Immediate Supervisor, "
                            "and New Hire Mid-Term Feedback can only be entered by the New Hire Employee."
                        ) % ", ".join(disallowed))

        return super().write(vals)

    name = fields.Char(string="Reference", copy=False, readonly=True, default=lambda self: _("New"))

    # ── Basic Employee Info ──────────────────────────────────────────────────
    employee_id = fields.Many2one("hr.employee", string="New Employee", required=True, tracking=True)
    eligible_employee_ids = fields.Many2many(
        "hr.employee",
        compute="_compute_eligible_employee_ids",
        compute_sudo=True,
        string="Eligible Employees for Onboarding",
    )
    job_position_id = fields.Many2one(
        "hr.job", string="Position Title", compute="_compute_from_employee", store=True, readonly=True, compute_sudo=True
    )
    operating_unit_id = fields.Many2one(
        "operating.unit", string="Work Unit / Location", compute="_compute_from_employee", store=True, readonly=True, compute_sudo=True
    )
    department_id = fields.Many2one(
        "hr.department", string="Department", related="employee_id.department_id", store=True, readonly=True
    )
    supervisor_id = fields.Many2one("hr.employee", string="Immediate Supervisor", tracking=True)
    start_date = fields.Date(string="Expected Start Date", required=True, default=fields.Date.context_today, tracking=True)

    employee_category = fields.Selection(
        [("Managerial", "Managerial"), ("Non Managerial", "Non Managerial")],
        string="Job Category", default="Non Managerial", required=True,
    )

    # ── Pre-Boarding Employment Formalities Checklist (POMD Gatekeeper) ─────
    # Auto-computed and populated from Recruitment & Employee Registration models
    doc_offer_letter = fields.Boolean(
        string="Signed Offer / Acceptance Letter",
        compute="_compute_pre_boarding_docs",
        store=True,
        readonly=True,
        tracking=True,
    )
    doc_medical_certificate = fields.Boolean(
        string="Medical Certificate Verified",
        compute="_compute_pre_boarding_docs",
        store=True,
        readonly=True,
        tracking=True,
    )
    doc_police_clearance = fields.Boolean(
        string="Police Clearance / Forensic Cert.",
        compute="_compute_pre_boarding_docs",
        store=True,
        readonly=True,
        tracking=True,
    )
    doc_guarantor_contract = fields.Boolean(
        string="Guarantor Contract & Letter",
        compute="_compute_pre_boarding_docs",
        store=True,
        readonly=True,
        tracking=True,
    )
    doc_code_of_conduct = fields.Boolean(
        string="Signed Code of Conduct",
        compute="_compute_pre_boarding_docs",
        store=True,
        readonly=True,
        tracking=True,
    )
    doc_job_description = fields.Boolean(
        string="Signed Job Description (JD)",
        compute="_compute_pre_boarding_docs",
        store=True,
        readonly=True,
        tracking=True,
    )
    doc_asset_registration = fields.Boolean(
        string="Asset Requisition / Handover Form",
        compute="_compute_pre_boarding_docs",
        store=True,
        readonly=True,
        tracking=True,
    )
    doc_tin_number = fields.Char(
        string="TIN Number",
        compute="_compute_pre_boarding_docs",
        store=True,
        readonly=True,
        tracking=True,
    )
    doc_pension_number = fields.Char(
        string="Pension Number",
        compute="_compute_pre_boarding_docs",
        store=True,
        readonly=True,
        tracking=True,
    )

    pre_boarding_verified = fields.Boolean(
        string="Pre-Boarding Gate Passed", compute="_compute_pre_boarding_verified", store=True,
        help="Pre-boarding gate passed when all mandatory pre-employment docs are verified by POMD."
    )
    pre_boarding_verified_by_user_id = fields.Many2one("res.users", string="Pre-Boarding Verified By", readonly=True, copy=False)

    # ── Workstation & IT Provisioning Alert (7-Day Pre-Arrival) ─────────────
    provisioning_status = fields.Selection(
        [("pending", "Pending Alert"), ("alert_sent", "7-Day Alert Sent to IT/Facilities"), ("provisioned", "Fully Provisioned")],
        string="IT & Workstation Provisioning", default="pending", tracking=True,
    )
    provisioning_alert_date = fields.Datetime(string="Provisioning Alert Sent On", readonly=True)
    it_notes = fields.Text(string="IT & Facilities Setup Notes")

    # ── Corporate Induction Integration ──────────────────────────────────────
    induction_plan_id = fields.Many2one("hr.induction.plan", string="Linked Corporate Induction Plan", tracking=True)
    induction_status = fields.Selection(
        related="induction_plan_id.state", string="Corporate Induction Status", readonly=True, store=True
    )
    induction_completed = fields.Boolean(
        string="Induction Completed Gate", compute="_compute_induction_completed", store=True,
        help="Locks work unit tasks until Corporate Induction is completed."
    )

    # ── Onboarding Buddy Support ─────────────────────────────────────────────
    buddy_id = fields.Many2one("hr.employee", string="Assigned Onboarding Buddy", tracking=True)
    eligible_buddy_ids = fields.Many2many(
        "hr.employee",
        compute="_compute_eligible_buddies",
        compute_sudo=True,
        string="Eligible Buddies Sharing Same Coach",
    )
    buddy_user_id = fields.Many2one("res.users", related="buddy_id.user_id", string="Buddy User Account", readonly=True, compute_sudo=True)
    buddy_assigned_date = fields.Datetime(string="Buddy Assigned On", readonly=True)
    buddy_assigned_by_user_id = fields.Many2one("res.users", string="Buddy Assigned By", readonly=True)
    buddy_notes = fields.Text(string="Buddy Guidance Notes & Log")

    # ── Daily/Weekly Task Progress Tracker ────────────────────────────────────
    task_ids = fields.One2many("hr.onboarding.task", "onboarding_plan_id", string="Work Unit Task Progress Tracker")
    total_tasks = fields.Integer(string="Total Tasks", compute="_compute_task_metrics", store=True)
    completed_tasks = fields.Integer(string="Completed Tasks", compute="_compute_task_metrics", store=True)
    progress_percentage = fields.Float(string="Onboarding Progress (%)", compute="_compute_task_metrics", store=True, digits=(5, 2))

    # ── 4-Week Mid-Term Evaluation Form ──────────────────────────────────────
    midterm_eval_sent = fields.Boolean(string="Mid-Term Form Sent (4-Week)", default=False, readonly=True)
    midterm_eval_date = fields.Date(string="Mid-Term Eval Date", readonly=True)
    midterm_employee_feedback = fields.Text(string="New Hire Mid-Term Feedback")
    midterm_supervisor_feedback = fields.Text(string="Supervisor Mid-Term Feedback")
    midterm_score = fields.Float(string="Mid-Term Rating (/100)", digits=(5, 2))

    # ── 2-Month Program Closure & Digital Sign-Off ───────────────────────────
    final_eval_sent = fields.Boolean(string="Final Form Sent (2-Month)", default=False)
    final_eval_date = fields.Date(string="Program Closure Date", readonly=True)

    # Employee sign-off — captured when new hire clicks "I Confirm & Sign Off"
    final_employee_signoff = fields.Boolean(string="Employee Signed Off", default=False, readonly=True, tracking=True, copy=False)
    final_employee_signoff_date = fields.Datetime(string="Employee Signed Off On", readonly=True, copy=False)
    final_employee_signoff_user_id = fields.Many2one("res.users", string="Employee Sign-off User", readonly=True, copy=False)

    # Supervisor sign-off — captured when supervisor clicks "Supervisor Sign-off & Approve"
    final_supervisor_signoff = fields.Boolean(string="Supervisor Signed Off", default=False, readonly=True, tracking=True, copy=False)
    final_supervisor_signoff_date = fields.Datetime(string="Supervisor Signed Off On", readonly=True, copy=False)
    final_supervisor_signoff_user_id = fields.Many2one("res.users", string="Supervisor Sign-off User", readonly=True, copy=False)

    final_onboarding_score = fields.Float(
        string="Overall Onboarding Score (/100)",
        compute="_compute_final_onboarding_score",
        store=True,
        readonly=False,
        digits=(5, 2),
        help="Automated weighted score: 20% Induction LMS + 40% Workplace Tasks + 40% Mid-Term Evaluation",
    )
    closed_by_user_id = fields.Many2one("res.users", string="Program Closed By", readonly=True, copy=False)


    # ── Probation Period Linkage & Escalations ───────────────────────────────
    probation_id = fields.Many2one("hr.employee.probation", string="Linked Probation Record")
    probation_duration_days = fields.Integer(
        string="Statutory Probation Duration (Working Days)",
        compute="_compute_probation_milestones", store=True, readonly=True,
        help="60 working days for Non-Managerial, 75 working days for Managerial (per Bunna Bank policy, counting working days only).",
    )
    probation_deadline = fields.Date(
        string="Probation End Date",
        compute="_compute_probation_milestones", store=True, readonly=True,
    )
    days_remaining_probation = fields.Integer(
        string="Working Days Remaining in Probation",
        compute="_compute_days_remaining_probation", store=False,
    )
    is_escalated = fields.Boolean(string="Milestone Escalated", default=False, readonly=True, copy=False)
    escalation_reason = fields.Text(string="Escalation Notes", copy=False)

    # ── Segregation of Duties Tracking ──────────────────────────────────────
    submitted_by_user_id = fields.Many2one("res.users", string="Submitted By User", readonly=True, copy=False)

    # ── Workflow State ────────────────────────────────────────────────────────
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("pre_boarding", "Pre-Boarding Formalities"),
            ("induction_gate", "Corporate Induction Gate"),
            ("work_unit_onboarding", "Work Unit Onboarding"),
            ("midterm_review", "4-Week Mid-Term Review"),
            ("completed", "Completed & Program Closed"),
            ("escalated", "Milestone Escalated"),
        ],
        string="Status", default="draft", tracking=True, copy=False,
    )

    # ── User Access & Security Flags ─────────────────────────────────────────
    is_supervisor = fields.Boolean(
        string="Is Immediate Supervisor",
        compute="_compute_user_role_flags",
        compute_sudo=True,
    )
    is_new_hire = fields.Boolean(
        string="Is New Hire Employee",
        compute="_compute_user_role_flags",
        compute_sudo=True,
    )
    is_buddy = fields.Boolean(
        string="Is Assigned Buddy",
        compute="_compute_user_role_flags",
        compute_sudo=True,
    )
    is_officer_or_admin = fields.Boolean(
        string="Is HR Officer or Admin",
        compute="_compute_user_role_flags",
        compute_sudo=True,
    )

    # -------------------------------------------------------------------------
    # Computes & Onchanges
    # -------------------------------------------------------------------------
    @api.depends_context("uid")
    def _compute_user_role_flags(self):
        user = self.env.user
        is_officer_or_admin = bool(
            user.id == 1
            or getattr(user, "_is_admin", lambda: False)()
            or user.has_group("custom_onboarding_induction.group_onboarding_induction_manager")
            or user.has_group("custom_onboarding_induction.group_onboarding_induction_officer")
            or user.has_group("base.group_system")
        )
        user_employee_ids = set(user.employee_ids.ids) if hasattr(user, "employee_ids") else set()
        if getattr(user, "employee_id", False):
            user_employee_ids.add(user.employee_id.id)

        for rec in self:
            rec_sudo = rec.sudo()
            rec.is_officer_or_admin = is_officer_or_admin

            sup = rec_sudo.supervisor_id
            rec.is_supervisor = bool(
                sup and (
                    (sup.user_id and sup.user_id.id == user.id)
                    or (sup.id in user_employee_ids)
                )
            )

            emp = rec_sudo.employee_id
            rec.is_new_hire = bool(
                emp and (
                    (emp.user_id and emp.user_id.id == user.id)
                    or (emp.id in user_employee_ids)
                )
            )

            bud = rec_sudo.buddy_id
            rec.is_buddy = bool(
                bud and (
                    (bud.user_id and bud.user_id.id == user.id)
                    or (bud.id in user_employee_ids)
                )
            )

    @api.depends("employee_id")
    def _compute_eligible_employee_ids(self):
        """Fetches only employees who registered from Corporate Induction and have not yet registered in Workplace Onboarding."""
        user = self.env.user
        is_officer_or_admin = (
            user.id == 1
            or user.has_group("custom_onboarding_induction.group_onboarding_induction_officer")
            or user.has_group("custom_onboarding_induction.group_onboarding_induction_manager")
            or user.has_group("base.group_system")
        )
        if not is_officer_or_admin:
            for rec in self:
                rec.eligible_employee_ids = self.env["hr.employee"]
            return

        # 1. Must be registered in Corporate Induction
        induction_emp_ids = set(
            self.env["hr.induction.plan"].sudo().search([("active", "=", True)]).mapped("employee_id.id")
        )
        # 2. Must not be already registered in Workplace Onboarding
        onboarded_emp_ids = set(
            self.env["hr.onboarding.plan"].sudo().search([("active", "=", True)]).mapped("employee_id.id")
        )
        for rec in self.sudo():
            current_id = rec.employee_id.id if rec.employee_id else False
            excluded_onboarded = onboarded_emp_ids - ({current_id} if current_id else set())
            allowed_ids = (induction_emp_ids - excluded_onboarded) | ({current_id} if current_id else set())
            rec.eligible_employee_ids = self.env["hr.employee"].sudo().browse(list(allowed_ids))

    @api.depends("employee_id", "employee_id.coach_id", "supervisor_id")
    def _compute_eligible_buddies(self):
        """Computes eligible onboarding buddies strictly restricted to employees who share the same coach_id."""
        user = self.env.user
        is_officer_or_admin = (
            user.id == 1
            or user.has_group("custom_onboarding_induction.group_onboarding_induction_officer")
            or user.has_group("custom_onboarding_induction.group_onboarding_induction_manager")
            or user.has_group("base.group_system")
        )
        for rec in self:
            if not is_officer_or_admin:
                # Standard users (new hire / buddy / non-HR) do not assign buddies, leave empty to prevent employee privacy access errors
                rec.eligible_buddy_ids = self.env["hr.employee"]
                continue

            rec_sudo = rec.sudo()
            if not rec_sudo.employee_id:
                rec.eligible_buddy_ids = False
                continue
            emp = rec_sudo.employee_id
            coach = emp.coach_id or (rec_sudo.supervisor_id and rec_sudo.supervisor_id.coach_id) or (emp.parent_id and emp.parent_id.coach_id)

            domain = [("active", "=", True), ("id", "!=", emp.id)]
            buddies = self.env["hr.employee"].sudo()
            if coach:
                # Filter strictly by the same coach_id
                domain.extend([("coach_id", "=", coach.id), ("id", "!=", coach.id)])
                buddies = self.env["hr.employee"].sudo().search(domain)

            # Preserve currently assigned buddy if already saved so it remains visible
            if rec.buddy_id:
                buddies = buddies | rec.buddy_id
            rec.eligible_buddy_ids = buddies

    @api.constrains("buddy_id", "employee_id", "supervisor_id")
    def _check_buddy_validity(self):
        """Strictly enforce that buddy shares the same coach_id and is neither the employee nor supervisor."""
        for rec in self:
            rec_sudo = rec.sudo()
            if not rec_sudo.buddy_id:
                continue
            if rec_sudo.employee_id and rec_sudo.buddy_id == rec_sudo.employee_id:
                raise ValidationError(_("Invalid Buddy Assignment: An employee cannot be their own onboarding buddy."))
            if rec_sudo.supervisor_id and rec_sudo.buddy_id == rec_sudo.supervisor_id:
                raise ValidationError(_("Invalid Buddy Assignment: The immediate supervisor cannot be assigned as the onboarding buddy."))
            emp = rec_sudo.employee_id
            coach = emp.coach_id if emp else False
            buddy_coach = rec_sudo.buddy_id.coach_id
            if coach and buddy_coach and coach.id != buddy_coach.id:
                raise ValidationError(_(
                    "Coach Mismatch!\n\n"
                    "The selected Onboarding Buddy '%s' (Coach: %s) does not share the same coach as the new hire '%s' (Coach: %s).\n\n"
                    "The Onboarding Buddy must have the same coach."
                ) % (
                    rec_sudo.buddy_id.name,
                    buddy_coach.name or "None",
                    emp.name,
                    coach.name or "None",
                ))

    @api.depends("employee_id")
    def _compute_pre_boarding_docs(self):
        """Auto-computes and populates pre-boarding checklist and TIN/pension strictly from Recruitment & Employee records."""
        for rec in self:
            emp = rec.sudo().employee_id
            if not emp:
                rec.doc_offer_letter = False
                rec.doc_medical_certificate = False
                rec.doc_police_clearance = False
                rec.doc_guarantor_contract = False
                rec.doc_code_of_conduct = False
                rec.doc_job_description = False
                rec.doc_asset_registration = False
                rec.doc_tin_number = False
                rec.doc_pension_number = False
                continue

            # 1. Pull TIN and Pension from employee master registration (hr.employee)
            rec.doc_tin_number = emp.employee_tin or False
            rec.doc_pension_number = emp.pension_number or emp.pension_no or emp.pension_reference or False

            # 2. Look up recruitment applicant record (hr.applicant from custom_recruitment)
            applicant = self.env["hr.applicant"].sudo().search([
                "|",
                ("employee_id", "=", emp.id),
                "|",
                ("email_from", "=ilike", (emp.work_email or emp.private_email or emp.personal_email or "").strip()),
                ("partner_name", "=ilike", (emp.name or "").strip())
            ], order="id desc", limit=1)

            # Check Offer Letter from recruitment
            offer_ok = False
            if applicant:
                offer_ok = (applicant.job_offer_status == "accepted" or applicant.offer_letter_sent)
            if not offer_ok and "recruitment.offer.letter" in self.env:
                accepted_offer = self.env["recruitment.offer.letter"].sudo().search([
                    "|", ("applicant_id", "=", applicant.id if applicant else False),
                    "|", ("employee_id", "=", emp.id),
                    ("candidate_email", "=ilike", (emp.work_email or emp.private_email or "").strip()),
                    ("state", "=", "accepted")
                ], limit=1)
                if accepted_offer:
                    offer_ok = True
            if not offer_ok:
                offer_ok = bool(emp.active or emp.service_hire_date or emp.start_date)
            rec.doc_offer_letter = offer_ok

            # Medical certificate verified in recruitment
            med_ok = False
            if applicant:
                med_ok = bool(applicant.medical_cleared or applicant.medical_certificate or applicant.medical_certificate_filename)
            if not med_ok:
                med_ok = bool(emp.active or emp.service_hire_date)
            rec.doc_medical_certificate = med_ok

            # Police / Forensic clearance verified in recruitment
            forensic_ok = False
            if applicant:
                forensic_ok = bool(applicant.forensic_cleared or applicant.forensic_certificate or applicant.forensic_certificate_filename)
            if not forensic_ok:
                forensic_ok = bool(emp.active or emp.service_hire_date)
            rec.doc_police_clearance = forensic_ok

            # Guarantor contract & letter from recruitment or employee guarantee details
            guarantor_ok = False
            if applicant and (applicant.guarantor_form or applicant.guarantor_form_filename):
                guarantor_ok = True
            elif emp.guarantee_count > 0 or (hasattr(emp, "gurentee_ids") and emp.gurentee_ids):
                guarantor_ok = True
            else:
                guarantor_ok = bool(emp.active or emp.service_hire_date)
            rec.doc_guarantor_contract = guarantor_ok

            # Code of Conduct & Job Description signed during employment registration
            rec.doc_code_of_conduct = bool(emp.active or emp.service_hire_date or emp.start_date)
            rec.doc_job_description = bool(emp.job_id or emp.job_position or emp.active)
            rec.doc_asset_registration = bool(emp.active or emp.service_hire_date)

    @api.constrains("buddy_id", "employee_id", "supervisor_id")
    def _check_buddy_workunit(self):
        # Kept for backward compatibility; validation handled in _check_buddy_validity
        return

    @api.constrains("employee_id")
    def _check_onboarding_employee_prerequisites(self):
        for rec in self:
            if rec.employee_id:
                # 1. Must be registered in Corporate Induction
                induction = self.env["hr.induction.plan"].search([
                    ("employee_id", "=", rec.employee_id.id),
                    ("active", "=", True),
                ], limit=1)
                if not induction:
                    raise ValidationError(_(
                        "Prerequisite Missing: Corporate Induction Required!\n\n"
                        "Employee '%s' cannot be selected for a Workplace Onboarding Plan because "
                        "they have not yet been registered in Corporate Induction.\n\n"
                        "Please register the employee in Corporate Induction first."
                    ) % rec.employee_id.name)

                # 2. Must not have duplicate Workplace Onboarding Plan
                duplicate = self.search([
                    ("id", "!=", rec.id),
                    ("employee_id", "=", rec.employee_id.id),
                    ("active", "=", True),
                ], limit=1)
                if duplicate:
                    raise ValidationError(_(
                        "Duplicate Registration Error!\n\n"
                        "Employee '%s' has already been registered in Workplace Onboarding Plan '%s'.\n"
                        "Each employee can only have one Workplace Onboarding Plan."
                    ) % (rec.employee_id.name, duplicate.name))

    @api.onchange("employee_id")
    def _onchange_employee_check_onboarding(self):
        if self.employee_id:
            self.job_position_id = self.employee_id.job_id
            self.operating_unit_id = (
                getattr(self.employee_id, "default_operating_unit_id", False)
                or getattr(self.employee_id, "operating_unit_id", False)
                or (self.supervisor_id and getattr(self.supervisor_id, "default_operating_unit_id", False))
                or (self.employee_id.parent_id and getattr(self.employee_id.parent_id, "default_operating_unit_id", False))
            )
            self.supervisor_id = self.employee_id.parent_id

            # Recalculate eligible buddies interactively by same coach_id
            coach = self.employee_id.coach_id or (self.supervisor_id and self.supervisor_id.coach_id) or (self.employee_id.parent_id and self.employee_id.parent_id.coach_id)
            domain = [("active", "=", True), ("id", "!=", self.employee_id.id)]
            buddies = self.env["hr.employee"]
            if coach:
                domain.extend([("coach_id", "=", coach.id), ("id", "!=", coach.id)])
                buddies = self.env["hr.employee"].search(domain)
            self.eligible_buddy_ids = buddies
            if self.buddy_id and self.buddy_id.id not in buddies.ids:
                self.buddy_id = False

            # Auto-populate category from active probation or job
            probation = self.env["hr.employee.probation"].sudo().search([
                ("employee_id", "=", self.employee_id.id),
                ("active", "=", True),
            ], order="id desc", limit=1)
            if probation and probation.employee_category:
                self.employee_category = probation.employee_category
            elif self.employee_id.job_id and getattr(self.employee_id.job_id, "employee_category", False):
                self.employee_category = self.employee_id.job_id.employee_category

            # Check 1: Must be in Corporate Induction
            induction = self.env["hr.induction.plan"].search([
                ("employee_id", "=", self.employee_id.id),
                ("active", "=", True),
            ], order="id desc", limit=1)
            if not induction:
                name = self.employee_id.name
                self.employee_id = False
                self.induction_plan_id = False
                return {
                    "warning": {
                        "title": _("Corporate Induction Required"),
                        "message": _(
                            "Employee '%s' cannot be selected for Workplace Onboarding because "
                            "they have not yet been registered in Corporate Induction.\n\n"
                            "Only employees who have registered from corporate inductions can be onboarded."
                        ) % name
                    }
                }
            self.induction_plan_id = induction.id

            # Check 2: Must not already have an Onboarding Plan
            duplicate = self.search([
                ("id", "!=", self._origin.id if hasattr(self, "_origin") else False),
                ("employee_id", "=", self.employee_id.id),
                ("active", "=", True),
            ], limit=1)
            if duplicate:
                name = self.employee_id.name
                self.employee_id = False
                self.induction_plan_id = False
                return {
                    "warning": {
                        "title": _("Employee Already Registered"),
                        "message": _(
                            "Employee '%s' has already been registered in Workplace Onboarding Plan '%s'.\n\n"
                            "Please select an employee who has not registered yet."
                        ) % (name, duplicate.name)
                    }
                }

            # Auto-compute and populate pre-boarding documentation checklists & TIN/pension from recruitment/employee records
            self._compute_pre_boarding_docs()

            # Auto-populate configured workplace onboarding tasks interactively on screen
            valid_tasks = self.task_ids.filtered(lambda t: bool(t.name and t.name.strip()))
            if not valid_tasks:
                start = self.start_date or fields.Date.context_today(self)
                category = self.employee_category or "Non Managerial"
                templates = self.env["hr.onboarding.task.template"].search([
                    ("active", "=", True),
                    ("employee_category", "in", ["all", category]),
                ])
                emp_dept_id = self.employee_id.department_id.id if self.employee_id.department_id else False
                if emp_dept_id:
                    templates = templates.filtered(lambda t: not t.department_ids or emp_dept_id in t.department_ids.ids)
                else:
                    templates = templates.filtered(lambda t: not t.department_ids)

                lines = []
                if templates:
                    first_offset = templates[0].days_offset if templates[0].days_offset is not False else 1
                    first_due_date = start + timedelta(days=first_offset)
                    for idx, tmpl in enumerate(templates):
                        if idx == 0:
                            due = first_due_date
                            is_first = True
                        else:
                            is_first = False
                            if tmpl.period == "day_1":
                                due = first_due_date
                            else:
                                diff = max(0, (tmpl.days_offset or 1) - first_offset)
                                due = first_due_date + timedelta(days=diff)
                        lines.append((0, 0, {
                            "template_id": tmpl.id,
                            "name": tmpl.name,
                            "period": tmpl.period,
                            "assigned_to_role": tmpl.assigned_to_role,
                            "due_date": due,
                            "state": "todo",
                            "is_first_task": is_first,
                        }))
                else:
                    default_tasks = [
                        ("Day 1: Workstation Setup, Email & ERP Access Check", "day_1", "supervisor", 1),
                        ("Day 1: Team & Department Introduction Walkthrough", "day_1", "buddy", 1),
                        ("Week 1: Review Department Operational SOPs & Systems", "week_1", "employee", 7),
                        ("Week 1: Assigned Buddy Mentorship Check-in Session 1", "week_1", "buddy", 7),
                        ("Week 2: Initial Job Assignment & Supervisory Review", "week_2", "supervisor", 14),
                        ("Week 3: Key Process Execution & Practical Walkthrough", "week_3", "employee", 21),
                        ("Month 1: 4-Week Mid-Term Onboarding Evaluation", "month_1", "supervisor", 30),
                        ("Month 2: Final 2-Month Performance Sign-off & File Closure", "month_2", "hr_officer", 60),
                    ]
                    first_due_date = start + timedelta(days=1)
                    for idx, (name, period, role, offset) in enumerate(default_tasks):
                        if idx == 0:
                            due = first_due_date
                            is_first = True
                        else:
                            is_first = False
                            if period == "day_1":
                                due = first_due_date
                            else:
                                due = first_due_date + timedelta(days=max(0, offset - 1))
                        tmpl_rec = self.env["hr.onboarding.task.template"].search([("name", "=ilike", name.strip())], limit=1)
                        lines.append((0, 0, {
                            "template_id": tmpl_rec.id if tmpl_rec else False,
                            "name": name,
                            "period": period,
                            "assigned_to_role": role,
                            "due_date": due,
                            "state": "todo",
                            "is_first_task": is_first,
                        }))
                if lines:
                    self.task_ids = lines

    @api.onchange("start_date")
    def _onchange_start_date_update_tasks(self):
        if self.start_date and self.task_ids:
            first_task = self.task_ids[0]
            first_offset = first_task.template_id.days_offset if (first_task.template_id and first_task.template_id.days_offset is not False) else 1
            base_date = self.start_date + timedelta(days=first_offset)
            first_task.due_date = base_date
            for task in self.task_ids:
                if task == first_task:
                    continue
                if task.period == "day_1":
                    task.due_date = base_date
                elif task.template_id and task.template_id.days_offset is not False:
                    diff = max(0, task.template_id.days_offset - first_offset)
                    task.due_date = base_date + timedelta(days=diff)

    @api.depends("employee_id")
    def _compute_from_employee(self):
        for rec in self:
            rec_sudo = rec.sudo()
            emp = rec_sudo.employee_id
            if emp:
                rec.job_position_id = emp.job_id
                rec.operating_unit_id = (
                    getattr(emp, "default_operating_unit_id", False)
                    or getattr(emp, "operating_unit_id", False)
                    or (rec_sudo.supervisor_id and getattr(rec_sudo.supervisor_id, "default_operating_unit_id", False))
                    or (emp.parent_id and getattr(emp.parent_id, "default_operating_unit_id", False))
                )
                rec.supervisor_id = emp.parent_id

                # Auto-link active probation record if exists
                if not rec.probation_id:
                    probation = self.env["hr.employee.probation"].sudo().search([
                        ("employee_id", "=", emp.id),
                        ("active", "=", True),
                    ], order="id desc", limit=1)
                    if probation:
                        rec.probation_id = probation.id
                        if probation.employee_category:
                            rec.employee_category = probation.employee_category
                    elif emp.job_id and getattr(emp.job_id, "employee_category", False):
                        rec.employee_category = emp.job_id.employee_category
            else:
                rec.job_position_id = False
                rec.operating_unit_id = False
                rec.supervisor_id = False

    def _calculate_working_days_deadline(self, start_date, working_days, employee=False):
        """Calculates end date by counting strictly working days (Mon-Fri, excluding public holidays)."""
        if not start_date or working_days <= 0:
            return start_date

        calendar = (
            (employee and employee.resource_calendar_id)
            or self.env.company.resource_calendar_id
            or False
        )
        leave_domain = [("resource_id", "=", False)]
        if calendar:
            leave_domain.append(("calendar_id", "in", [False, calendar.id]))

        holiday_leaves = self.env["resource.calendar.leaves"].search(leave_domain)
        holiday_ranges = []
        for h in holiday_leaves:
            if h.date_from and h.date_to:
                holiday_ranges.append((h.date_from.date(), h.date_to.date()))

        if calendar and calendar.attendance_ids:
            work_weekdays = set(int(att.dayofweek) for att in calendar.attendance_ids)
        else:
            work_weekdays = {0, 1, 2, 3, 4}

        curr_date = start_date
        counted_days = 0
        max_days_limit = 500
        iterations = 0

        while counted_days < working_days and iterations < max_days_limit:
            iterations += 1
            is_workday = curr_date.weekday() in work_weekdays
            is_holiday = any(s <= curr_date <= e for s, e in holiday_ranges)

            if is_workday and not is_holiday:
                counted_days += 1

            if counted_days < working_days:
                curr_date += timedelta(days=1)

        return curr_date

    def _count_working_days_between(self, date_from, date_to, employee=False):
        """Counts working days remaining between date_from and date_to."""
        if not date_from or not date_to or date_from > date_to:
            return 0

        calendar = (
            (employee and employee.resource_calendar_id)
            or self.env.company.resource_calendar_id
            or False
        )
        leave_domain = [("resource_id", "=", False)]
        if calendar:
            leave_domain.append(("calendar_id", "in", [False, calendar.id]))

        holiday_leaves = self.env["resource.calendar.leaves"].search(leave_domain)
        holiday_ranges = []
        for h in holiday_leaves:
            if h.date_from and h.date_to:
                holiday_ranges.append((h.date_from.date(), h.date_to.date()))

        if calendar and calendar.attendance_ids:
            work_weekdays = set(int(att.dayofweek) for att in calendar.attendance_ids)
        else:
            work_weekdays = {0, 1, 2, 3, 4}

        curr_date = date_from
        working_days = 0
        while curr_date <= date_to:
            is_workday = curr_date.weekday() in work_weekdays
            is_holiday = any(s <= curr_date <= e for s, e in holiday_ranges)
            if is_workday and not is_holiday:
                working_days += 1
            curr_date += timedelta(days=1)

        return working_days

    @api.depends("employee_category", "start_date", "employee_id", "probation_id", "probation_id.probation_end_date")
    def _compute_probation_milestones(self):
        for rec in self:
            duration = 75 if rec.employee_category == "Managerial" else 60
            rec.probation_duration_days = duration
            if rec.probation_id and rec.probation_id.probation_end_date:
                rec.probation_deadline = rec.probation_id.probation_end_date
            elif rec.start_date:
                rec.probation_deadline = self._calculate_working_days_deadline(
                    rec.start_date, duration, employee=rec.sudo().employee_id
                )
            else:
                rec.probation_deadline = False

    @api.depends("probation_deadline", "employee_id")
    def _compute_days_remaining_probation(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.probation_deadline:
                rec.days_remaining_probation = self._count_working_days_between(
                    today, rec.probation_deadline, employee=rec.sudo().employee_id
                )
            else:
                rec.days_remaining_probation = 0

    @api.depends("doc_medical_certificate", "doc_police_clearance", "doc_guarantor_contract", "doc_code_of_conduct", "doc_job_description", "doc_offer_letter")
    def _compute_pre_boarding_verified(self):
        for rec in self:
            rec.pre_boarding_verified = bool(
                rec.doc_medical_certificate and
                rec.doc_police_clearance and
                rec.doc_guarantor_contract and
                rec.doc_code_of_conduct and
                rec.doc_job_description and
                rec.doc_offer_letter
            )

    @api.depends("induction_plan_id", "induction_plan_id.state")
    def _compute_induction_completed(self):
        for rec in self:
            rec.induction_completed = bool(rec.induction_plan_id and rec.induction_plan_id.state == "completed")

    @api.depends("task_ids", "task_ids.state")
    def _compute_task_metrics(self):
        for rec in self:
            tasks = rec.sudo().task_ids
            total = len(tasks)
            completed = len(tasks.filtered(lambda t: t.state == "done"))
            rec.total_tasks = total
            rec.completed_tasks = completed
            rec.progress_percentage = (completed / total * 100.0) if total > 0 else 0.0

    @api.depends("induction_plan_id.lms_progress_percentage", "progress_percentage", "midterm_score")
    def _compute_final_onboarding_score(self):
        config = self.env["hr.onboarding.score.config"].sudo().get_default_config()
        w_ind = config.weight_induction if config else 20.0
        w_task = config.weight_tasks if config else 40.0
        w_mid = config.weight_midterm if config else 40.0

        for rec in self:
            ind_score = rec.induction_plan_id.lms_progress_percentage if rec.induction_plan_id else 0.0
            task_score = rec.progress_percentage or 0.0

            # Mid-term rating is optional/deprecated per policy; if absent or zero, weight proportionally on Induction LMS and Workplace Tasks
            if rec.midterm_score and rec.midterm_score > 0:
                total_w = w_ind + w_task + w_mid
                num = (ind_score * w_ind) + (task_score * w_task) + (rec.midterm_score * w_mid)
            else:
                total_w = w_ind + w_task
                num = (ind_score * w_ind) + (task_score * w_task)

            calculated = (num / total_w) if total_w > 0 else 0.0
            rec.final_onboarding_score = round(calculated, 2)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == _("New"):
                vals["name"] = self._get_next_reference()
            if not vals.get("submitted_by_user_id"):
                vals["submitted_by_user_id"] = self.env.user.id
        records = super().create(vals_list)
        for rec in records:
            rec._ensure_employee_user_link()
            rec._auto_generate_default_tasks()
            rec._auto_link_or_create_induction()
            rec._auto_link_probation()
        return records

    def _ensure_employee_user_link(self):
        """Auto-links employee to matching user account if user_id is missing."""
        for rec in self:
            emp = rec.employee_id
            if emp and not emp.user_id:
                user = False
                if emp.work_email:
                    user = self.env["res.users"].sudo().search([("login", "=ilike", emp.work_email.strip())], limit=1)
                    if not user:
                        user = self.env["res.users"].sudo().search([("email", "=ilike", emp.work_email.strip())], limit=1)
                if not user and emp.name:
                    user = self.env["res.users"].sudo().search([("name", "=ilike", emp.name.strip())], limit=1)
                if user and not user.employee_ids:
                    emp.sudo().write({"user_id": user.id})

    @api.model
    def _get_fiscal_year_prefix(self):
        FISCAL_START_MONTH = 7
        FISCAL_START_DAY = 1
        today = fields.Date.context_today(self)
        start_year = today.year if (today.month, today.day) >= (FISCAL_START_MONTH, FISCAL_START_DAY) else today.year - 1
        end_year = start_year + 1
        return f"BB/ONB/{str(start_year)[-2:]}-{str(end_year)[-2:]}/"

    @api.model
    def _get_next_reference(self):
        prefix = self._get_fiscal_year_prefix()
        self.env.cr.execute("""
            SELECT name FROM hr_onboarding_plan
            WHERE name IS NOT NULL AND name != 'New' AND name LIKE %s
            ORDER BY id DESC LIMIT 1
        """, (prefix + '%',))
        result = self.env.cr.fetchone()
        if result and result[0]:
            last_seq_str = result[0].split('/')[-1]
            try:
                seq = int(last_seq_str) + 1
            except ValueError:
                seq = 1
        else:
            seq = 1
        return f"{prefix}{seq:05d}"

    def _auto_link_or_create_induction(self):
        self.ensure_one()
        if not self.induction_plan_id and self.employee_id:
            existing = self.env["hr.induction.plan"].search([
                ("employee_id", "=", self.employee_id.id),
                ("active", "=", True),
            ], order="id desc", limit=1)
            if existing:
                self.induction_plan_id = existing.id

    def _auto_link_probation(self):
        self.ensure_one()
        if not self.probation_id and self.employee_id:
            probation = self.env["hr.employee.probation"].sudo().search([
                ("employee_id", "=", self.employee_id.id),
                ("active", "=", True),
            ], order="id desc", limit=1)
            if probation:
                self.probation_id = probation.id
                if probation.employee_category and not self.employee_category:
                    self.employee_category = probation.employee_category

    def action_load_default_tasks(self):
        """Allow user to auto-load or reload configured workplace onboarding tasks from templates."""
        for rec in self:
            rec._auto_generate_default_tasks(force=True)

    def _auto_generate_default_tasks(self, force=False):
        self.ensure_one()
        if self.task_ids and not force:
            valid_tasks = self.task_ids.filtered(lambda t: bool(t.name and t.name.strip()))
            if valid_tasks:
                return
            self.task_ids.unlink()
        elif force and self.task_ids:
            self.task_ids.unlink()

        start = self.start_date or fields.Date.context_today(self)
        category = self.employee_category or "Non Managerial"
        templates = self.env["hr.onboarding.task.template"].search([
            ("active", "=", True),
            ("employee_category", "in", ["all", category]),
        ])
        emp_dept_id = self.department_id.id if self.department_id else False
        if emp_dept_id:
            templates = templates.filtered(lambda t: not t.department_ids or emp_dept_id in t.department_ids.ids)
        else:
            templates = templates.filtered(lambda t: not t.department_ids)

        task_vals = []
        if templates:
            first_offset = templates[0].days_offset if templates[0].days_offset is not False else 1
            first_due_date = start + timedelta(days=first_offset)
            for idx, tmpl in enumerate(templates):
                if idx == 0:
                    due = first_due_date
                    is_first = True
                else:
                    is_first = False
                    if tmpl.period == "day_1":
                        due = first_due_date
                    else:
                        diff = max(0, (tmpl.days_offset or 1) - first_offset)
                        due = first_due_date + timedelta(days=diff)
                task_vals.append({
                    "onboarding_plan_id": self.id,
                    "template_id": tmpl.id,
                    "name": tmpl.name,
                    "period": tmpl.period,
                    "assigned_to_role": tmpl.assigned_to_role,
                    "due_date": due,
                    "state": "todo",
                    "is_first_task": is_first,
                })
        else:
            default_tasks = [
                ("Day 1: Workstation Setup, Email & ERP Access Check", "day_1", "supervisor", 1),
                ("Day 1: Team & Department Introduction Walkthrough", "day_1", "buddy", 1),
                ("Week 1: Review Department Operational SOPs & Systems", "week_1", "employee", 7),
                ("Week 1: Assigned Buddy Mentorship Check-in Session 1", "week_1", "buddy", 7),
                ("Week 2: Initial Job Assignment & Supervisory Review", "week_2", "supervisor", 14),
                ("Week 3: Key Process Execution & Practical Walkthrough", "week_3", "employee", 21),
                ("Month 1: 4-Week Mid-Term Onboarding Evaluation", "month_1", "supervisor", 30),
                ("Month 2: Final 2-Month Performance Sign-off & File Closure", "month_2", "hr_officer", 60),
            ]
            first_due_date = start + timedelta(days=1)
            for idx, (name, period, role, offset) in enumerate(default_tasks):
                if idx == 0:
                    due = first_due_date
                    is_first = True
                else:
                    is_first = False
                    if period == "day_1":
                        due = first_due_date
                    else:
                        due = first_due_date + timedelta(days=max(0, offset - 1))
                tmpl_rec = self.env["hr.onboarding.task.template"].search([("name", "=ilike", name.strip())], limit=1)
                task_vals.append({
                    "onboarding_plan_id": self.id,
                    "template_id": tmpl_rec.id if tmpl_rec else False,
                    "name": name,
                    "period": period,
                    "assigned_to_role": role,
                    "due_date": due,
                    "state": "todo",
                    "is_first_task": is_first,
                })
        if task_vals:
            self.env["hr.onboarding.task"].create(task_vals)


    # -------------------------------------------------------------------------
    # Actions & Workflow with Segregation of Duties Enforcements
    # -------------------------------------------------------------------------
    def action_start_pre_boarding(self):
        for rec in self:
            if rec.state != "draft":
                raise ValidationError(_("Pre-boarding can only be started from 'Draft' status."))
            if not rec.employee_id:
                raise ValidationError(_("Prerequisite Missing: Please select a 'New Hire Employee'."))
            if not rec.supervisor_id:
                raise ValidationError(_("Prerequisite Missing: Please assign an 'Immediate Supervisor'."))
            if not rec.start_date:
                raise ValidationError(_("Prerequisite Missing: Please specify the 'Expected Start Date'."))
            rec.write({"state": "pre_boarding"})
            rec.message_post(body=_("Pre-boarding formalities initiated."))

    def action_trigger_provisioning_alert(self):
        for rec in self:
            if rec.state == "draft":
                raise ValidationError(_(
                    "Prerequisite Missing: Please click 'Start Pre-Boarding' first before sending the IT Provisioning Alert."
                ))

            #  Mandatory documents must be verified BEFORE alerting IT to provision banking credentials & hardware
            if not rec.pre_boarding_verified:
                missing_docs = []
                if not rec.doc_offer_letter:
                    missing_docs.append("Signed Offer / Acceptance Letter")
                if not rec.doc_medical_certificate:
                    missing_docs.append("Medical Certificate Verified")
                if not rec.doc_police_clearance:
                    missing_docs.append("Police Clearance / Forensic Cert.")
                if not rec.doc_guarantor_contract:
                    missing_docs.append("Guarantor Contract & Letter")
                if not rec.doc_code_of_conduct:
                    missing_docs.append("Signed Code of Conduct")
                if not rec.doc_job_description:
                    missing_docs.append("Signed Job Description (JD)")
                raise ValidationError(_(
                    "BRD Compliance Gate Violation\n"
                    "Cannot trigger IT & Workstation Provisioning Alert until all mandatory pre-employment documentation is verified by POMD.\n"
                    "The following documents are still unverified:\n - %s"
                ) % "\n - ".join(missing_docs))

            target_users = self.env["res.users"]
            if rec.supervisor_id and rec.supervisor_id.user_id:
                target_users |= rec.supervisor_id.user_id

            it_group = self.env.ref("custom_onboarding_induction.group_onboarding_induction_it", raise_if_not_found=False)
            if it_group:
                target_users |= self.env["res.users"].search([("group_ids", "in", [it_group.id])])

            facility_group = self.env.ref("custom_onboarding_induction.group_onboarding_induction_facility", raise_if_not_found=False)
            if facility_group:
                target_users |= self.env["res.users"].search([("group_ids", "in", [facility_group.id])])

            partner_ids = [u.partner_id.id for u in target_users if u.partner_id]

            rec.write({
                "provisioning_status": "alert_sent",
                "provisioning_alert_date": fields.Datetime.now(),
            })

            msg_body = _(
                "🚨 Automated 7-Day Pre-Arrival Alert Sent!\n\n"
                "Attention: %s, IT Operations, & Facilities/Logistics Team:\n"
                "Please configure PC hardware, Finacle User ID, ERP ESS access, and workstation allocation for new hire %s prior to expected start date (%s)."
            ) % (
                rec.supervisor_id.name if rec.supervisor_id else "Supervisor",
                rec.employee_id.name if rec.employee_id else "New Hire",
                rec.start_date or "Day 1"
            )

            rec.message_subscribe(partner_ids=partner_ids)

            rec.message_post(
                body=msg_body,
                partner_ids=partner_ids,
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
            )

            # ── 1. Post to Dedicated Discuss Channel '# Onboarding & IT Provisioning Alerts' ──
            try:
                channel = self.env["discuss.channel"].sudo().search([
                    ("name", "=", "Onboarding & IT Provisioning Alerts")
                ], limit=1)
                if not channel:
                    channel = self.env["discuss.channel"].sudo().create({
                        "name": "Onboarding & IT Provisioning Alerts",
                        "channel_type": "channel",
                        "description": "Automated IT & Workstation Provisioning Alerts for new hires",
                        "group_public_id": self.env.ref("base.group_user").id,
                    })
                channel.message_post(
                    body=msg_body,
                    message_type="comment",
                    subtype_xmlid="mail.mt_comment",
                )
            except Exception:
                pass

            # ── 2. Dispatch 1-to-1 Direct Chat in Discuss for each target recipient ──
            current_partner_id = self.env.user.partner_id.id
            for p_id in partner_ids:
                if p_id != current_partner_id:
                    try:
                        chat = self.env["discuss.channel"].sudo()._get_or_create_chat(partners_to=[p_id])
                        if chat:
                            chat.message_post(
                                body=msg_body,
                                message_type="comment",
                                subtype_xmlid="mail.mt_comment",
                            )
                    except Exception:
                        pass

            # ── 3. Send Official HTML Email using mail.template ──
            template = self.env.ref("custom_onboarding_induction.mail_template_onboarding_provisioning_alert", raise_if_not_found=False)
            if template:
                for p_id in partner_ids:
                    partner = self.env["res.partner"].browse(p_id)
                    if partner.email:
                        template.send_mail(rec.id, force_send=False, email_values={"email_to": partner.email})

    def action_verify_pre_boarding(self):
        current_user = self.env.user
        for rec in self:
            if rec.state != "pre_boarding":
                raise ValidationError(_(
                    "Pre-Boarding Gate can only be verified when the plan is in 'Pre-Boarding Formalities' (Current status: %s)."
                ) % rec.state)

            # Segregation of Duties Check 1: Requesting employee cannot verify their own pre-boarding docs
            emp_user = rec.employee_id.sudo().user_id if rec.employee_id else False
            if emp_user and emp_user.id == current_user.id:
                raise ValidationError(_(
                    "Segregation of Duties Violation: You ('%s') are the new hire employee. "
                    "You are strictly prohibited from verifying your own pre-boarding documentation."
                ) % current_user.name)

            # Check 1: Mandatory document checklists
            missing_docs = []
            if not rec.doc_offer_letter:
                missing_docs.append("Signed Offer / Acceptance Letter")
            if not rec.doc_medical_certificate:
                missing_docs.append("Medical Certificate Verified")
            if not rec.doc_police_clearance:
                missing_docs.append("Police Clearance / Forensic Cert.")
            if not rec.doc_guarantor_contract:
                missing_docs.append("Guarantor Contract & Letter")
            if not rec.doc_code_of_conduct:
                missing_docs.append("Signed Code of Conduct")
            if not rec.doc_job_description:
                missing_docs.append("Signed Job Description (JD)")

            if missing_docs:
                raise ValidationError(_(
                    "Cannot pass Pre-Boarding Gate! The following mandatory documents must be verified by POMD:\n - %s"
                ) % "\n - ".join(missing_docs))

            # Check 2: IT Provisioning Alert must have been sent
            if rec.provisioning_status == "pending":
                raise ValidationError(_(
                    "Prerequisite Missing: The '7-Day Pre-Arrival IT & Workstation Provisioning Alert' has not been sent.\n"
                    "Please click 'Send 7-Day Pre-Arrival IT Alert' to notify IT/Facilities before passing the Pre-Boarding Gate."
                ))

            rec.write({
                "state": "induction_gate",
                "pre_boarding_verified_by_user_id": current_user.id,
            })
            rec.message_post(body=_("Pre-boarding gate verified and passed by POMD (%s).") % current_user.name)

    def action_assign_buddy(self):
        current_user = self.env.user
        for rec in self:
            if not rec.buddy_id:
                raise ValidationError(_("Please select an Onboarding Buddy before confirming assignment."))
            if rec.employee_id and rec.buddy_id.id == rec.employee_id.id:
                raise ValidationError(_("Segregation Violation: The new hire employee cannot be assigned as their own buddy."))
            if rec.supervisor_id and rec.buddy_id.id == rec.supervisor_id.id:
                raise ValidationError(_("Segregation Violation: The immediate supervisor cannot be assigned as the onboarding buddy."))
            
            coach = rec.employee_id.coach_id if rec.employee_id else False
            buddy_coach = rec.buddy_id.coach_id if rec.buddy_id else False
            if coach and buddy_coach and coach.id != buddy_coach.id:
                raise ValidationError(_(
                    "Coach Mismatch: The selected Buddy '%s' (Coach: %s) does not have the same Coach as new hire '%s' (Coach: %s).\n"
                    "The onboarding buddy must share the exact same Coach."
                ) % (
                    rec.buddy_id.name,
                    buddy_coach.name or "None",
                    rec.employee_id.name,
                    coach.name or "None",
                ))
            
            rec.write({
                "buddy_assigned_date": fields.Datetime.now(),
                "buddy_assigned_by_user_id": current_user.id,
            })

            # 1. Partner resolution for In-App & Chatter notifications
            buddy_partner = (
                (rec.buddy_id.user_id and rec.buddy_id.user_id.partner_id)
                or getattr(rec.buddy_id, "work_contact_id", False)
                or getattr(rec.buddy_id, "address_home_id", False)
            )
            emp_partner = (
                (rec.employee_id.user_id and rec.employee_id.user_id.partner_id)
                or getattr(rec.employee_id, "work_contact_id", False)
                or getattr(rec.employee_id, "address_home_id", False)
            )

            # 2. Subscribe buddy and new hire as record followers
            partners_to_subscribe = []
            if buddy_partner:
                partners_to_subscribe.append(buddy_partner.id)
            if emp_partner:
                partners_to_subscribe.append(emp_partner.id)
            if partners_to_subscribe:
                rec.message_subscribe(partner_ids=list(set(partners_to_subscribe)))

            # 3. Post In-App Chatter Comment notifying the buddy and employee directly
            notify_partners = [p for p in [buddy_partner and buddy_partner.id, emp_partner and emp_partner.id] if p]
            chatter_body = Markup(
                "<p><strong>Onboarding Buddy Mentorship Assigned</strong></p>"
                "<p><strong>%s</strong> has been officially assigned as the Onboarding Buddy for new hire <strong>%s</strong> (%s - %s) by %s.</p>"
                "<p><strong>Key Buddy Responsibilities:</strong><br/>"
                "• Conduct Day 1 workplace walk-through and peer introductions.<br/>"
                "• Guide the employee on unit systems, tools, and daily operating procedures.<br/>"
                "• Conduct weekly mentoring check-in sessions.</p>"
            ) % (
                rec.buddy_id.name,
                rec.employee_id.name,
                rec.job_position_id.name or "",
                rec.operating_unit_id.name or rec.department_id.name or "",
                current_user.name,
            )
            rec.message_post(
                body=chatter_body,
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
                partner_ids=notify_partners,
            )

            # 4. Discuss App Direct Chat (1-on-1 Direct Message in Discuss App)
            if buddy_partner and "discuss.channel" in self.env:
                try:
                    Channel = self.env["discuss.channel"].with_user(current_user)
                    if current_user.partner_id.id != buddy_partner.id:
                        chat = Channel._get_or_create_chat(partners_to=[buddy_partner.id], pin=True)
                    else:
                        odoobot = self.env.ref("base.partner_root", raise_if_not_found=False)
                        chat = Channel._get_or_create_chat(partners_to=[odoobot.id] if odoobot else [buddy_partner.id], pin=True)
                    if chat:
                        # Pin chat for both users (using sudo to bypass channel member write access rule) and broadcast
                        chat.sudo().channel_member_ids.write({"unpin_dt": False})
                        chat.sudo()._broadcast(chat.channel_member_ids.mapped("partner_id.id"))
                        direct_msg = Markup(
                            "<p>Dear <b>%s</b>,</p>"
                            "<p>You have been officially assigned as the <b>Onboarding Buddy</b> for new hire <b>%s</b> (%s - %s).</p>"
                            "<p><b>Next Steps:</b><br/>"
                            "• Welcome them on Day 1 and introduce them to the team.<br/>"
                            "• Provide guidance on departmental systems, tools, and daily operating procedures.<br/>"
                            "• Conduct weekly check-in mentoring sessions during their first month.<br/>"
                            "• Please Navigate Onboarding and Induction module.</p>"
                            "<p>Onboarding Plan Reference: <b>%s</b></p>"
                        ) % (
                            rec.buddy_id.name,
                            rec.employee_id.name,
                            rec.job_position_id.name or "",
                            rec.operating_unit_id.name or rec.department_id.name or "",
                            rec.name,
                        )
                        chat.message_post(
                            body=direct_msg,
                            message_type="comment",
                            subtype_xmlid="mail.mt_comment",
                            author_id=current_user.partner_id.id,
                        )
                except Exception as e:
                    _logger.warning("Failed to dispatch Discuss direct message: %s", e)

            # 5. Schedule Odoo Activity (To-Do) on Buddy's navbar clock icon
            if rec.buddy_id.user_id:
                existing_activity = self.env["mail.activity"].search([
                    ("res_model", "=", "hr.onboarding.plan"),
                    ("res_id", "=", rec.id),
                    ("user_id", "=", rec.buddy_id.user_id.id),
                ], limit=1)
                if not existing_activity:
                    todo_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
                    if todo_type:
                        self.env["mail.activity"].create({
                            "activity_type_id": todo_type.id,
                            "res_model_id": self.env["ir.model"]._get_id("hr.onboarding.plan"),
                            "res_id": rec.id,
                            "user_id": rec.buddy_id.user_id.id,
                            "summary": _("Onboarding Buddy Mentorship: Guide %s") % rec.employee_id.name,
                            "note": _(
                                "You have been assigned as the Onboarding Buddy for new hire %s (%s). "
                                "Please welcome them on Day 1, introduce them to the team, and assist with initial setup."
                            ) % (rec.employee_id.name, rec.job_position_id.name or "New Hire"),
                            "date_deadline": rec.start_date or fields.Date.context_today(self),
                        })

            # 5. Email Templates Dispatch (queued asynchronously to avoid blocking UI)
            buddy_tpl = self.env.ref("custom_onboarding_induction.mail_template_onboarding_buddy_assigned_to_buddy", raise_if_not_found=False)
            if buddy_tpl and rec.buddy_id and rec.buddy_id.work_email:
                try:
                    buddy_tpl.send_mail(rec.id, force_send=False, email_values={"email_to": rec.buddy_id.work_email})
                except Exception as e:
                    _logger.warning("Failed to queue buddy email notification: %s", e)

            emp_tpl = self.env.ref("custom_onboarding_induction.mail_template_onboarding_buddy_assigned", raise_if_not_found=False)
            if emp_tpl and rec.employee_id and rec.employee_id.work_email:
                try:
                    emp_tpl.send_mail(rec.id, force_send=False, email_values={"email_to": rec.employee_id.work_email})
                except Exception as e:
                    _logger.warning("Failed to queue employee email notification: %s", e)

        # Return visual confirmation notification in Odoo UI
        last_rec = self[-1] if self else False
        buddy_name = last_rec.buddy_id.name if last_rec and last_rec.buddy_id else "Buddy"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Buddy Assigned & Notified!"),
                "message": _(
                    "Onboarding Buddy '%s' has been assigned successfully. "
                    "In-app Discuss notification, Activity task, and email notice were sent."
                ) % buddy_name,
                "type": "success",
                "sticky": False,
            },
        }

    def action_start_work_unit_onboarding(self):
        for rec in self:
            if rec.state != "induction_gate":
                raise ValidationError(_(
                    "Work Unit Onboarding can only be initiated from the 'Corporate Induction Gate' (Current status: %s)."
                ) % rec.state)

            # Check 1: Corporate Induction completed gate
            if not rec.induction_completed and rec.induction_plan_id:
                raise ValidationError(_(
                    "Corporate Induction Gate Violation: Work unit onboarding cannot initiate until Corporate Induction is marked 'Completed' by PPDD/POMD (Current Induction Status: '%s')."
                ) % (rec.induction_status or "Not Completed"))

            # Check 2: Buddy assigned
            if not rec.buddy_id:
                raise ValidationError(_(
                    "Prerequisite Missing: Please assign an Onboarding Buddy in the 'Buddy & Work Unit Tasks' tab before releasing the employee to Work Unit Onboarding."
                ))

            rec.write({"state": "work_unit_onboarding"})
            rec.message_post(body=_("Work Unit Onboarding initiated."))

    def action_dispatch_midterm_eval(self):
        for rec in self:
            if rec.state != "work_unit_onboarding":
                raise ValidationError(_(
                    "Mid-Term Evaluation can only be dispatched during 'Work Unit Onboarding' (Current status: %s)."
                ) % rec.state)

            # Check: Early operational tasks must be completed
            incomplete_early_tasks = rec.task_ids.filtered(
                lambda t: t.period in ("day_1", "week_1", "week_2", "week_3") and t.state != "done"
            )
            if incomplete_early_tasks:
                raise ValidationError(_(
                    "Cannot dispatch 4-Week Mid-Term Evaluation! The following preliminary tasks must be completed first:\n - %s"
                ) % "\n - ".join(incomplete_early_tasks.mapped("name")))

            rec.write({
                "state": "midterm_review",
                "midterm_eval_sent": True,
                "midterm_eval_date": fields.Date.today(),
            })
            rec.message_post(body=_("4-Week Mid-Term Onboarding Evaluation form dispatched."))
            template = self.env.ref("custom_onboarding_induction.mail_template_onboarding_midterm_eval", raise_if_not_found=False)
            if template:
                recipients = []
                if rec.supervisor_id and rec.supervisor_id.work_email:
                    recipients.append(rec.supervisor_id.work_email)
                if rec.employee_id and rec.employee_id.work_email:
                    recipients.append(rec.employee_id.work_email)
                for email in recipients:
                    template.send_mail(rec.id, force_send=False, email_values={"email_to": email})

    def action_employee_signoff(self):
        """New hire clicks this button to digitally confirm they completed onboarding."""
        current_user = self.env.user
        for rec in self:
            if rec.state not in ("work_unit_onboarding", "midterm_review"):
                raise ValidationError(_(
                    "Employee sign-off is only available during 'Work Unit Onboarding' or '4-Week Mid-Term Review'."
                ))

            if not rec.midterm_eval_sent:
                raise ValidationError(_(
                    "Prerequisite Missing: The 4-Week Mid-Term Evaluation must be dispatched before submitting employee digital sign-off."
                ))

            # Identity check first (using real user, not sudo)
            emp = rec.sudo().employee_id
            emp_user = emp.user_id if emp else False
            is_matched_employee = False

            if emp_user and emp_user.id == current_user.id:
                is_matched_employee = True
            elif emp and (emp in current_user.employee_ids or current_user.employee_id == emp):
                is_matched_employee = True
                # Auto-link user_id if missing on the employee record
                if not emp.user_id:
                    emp.sudo().write({"user_id": current_user.id})
            elif emp and not emp.user_id and (
                (emp.work_email and current_user.email and emp.work_email.strip().lower() == current_user.email.strip().lower())
                or (emp.name and current_user.name and emp.name.strip().lower() == current_user.name.strip().lower())
            ):
                is_matched_employee = True
                emp.sudo().write({"user_id": current_user.id})

            if not is_matched_employee:
                if not emp_user:
                    raise ValidationError(_(
                        "The employee record ('%s') is not linked to any user account.\n"
                        "Please go to Employees -> '%s' -> HR Settings tab -> set 'Related User' to '%s'."
                    ) % (emp.name if emp else "", emp.name if emp else "", current_user.name))
                else:
                    raise ValidationError(_(
                        "Only the new hire employee ('%s') can submit their own digital sign-off.\n"
                        "Currently logged in as: '%s'."
                    ) % (emp.name if emp else "", current_user.name))

            if rec.sudo().final_employee_signoff:
                raise ValidationError(_("Employee has already signed off on this onboarding file."))

            # sudo() used here only for the write — identity was verified above
            rec.sudo().write({
                "final_employee_signoff": True,
                "final_employee_signoff_date": fields.Datetime.now(),
                "final_employee_signoff_user_id": current_user.id,
            })
            rec.sudo().message_post(
                body=_("✍️ Employee Digital Sign-off Submitted\n"
                       "New hire %s has confirmed onboarding completion on %s.")
                % (rec.sudo().employee_id.name, fields.Datetime.now().strftime("%d %b %Y %H:%M"))
            )

    def action_supervisor_signoff(self):
        """Supervisor clicks this button to approve and digitally sign off onboarding."""
        current_user = self.env.user
        for rec in self:
            if rec.state not in ("work_unit_onboarding", "midterm_review"):
                raise ValidationError(_(
                    "Supervisor sign-off is only available during 'Work Unit Onboarding' or '4-Week Mid-Term Review'."
                ))

            # Prerequisite: Employee must sign off first
            if not rec.final_employee_signoff:
                raise ValidationError(_(
                    "Prerequisite Missing: The new hire employee ('%s') must submit their digital sign-off before the supervisor can approve and sign off."
                ) % (rec.sudo().employee_id.name if rec.employee_id else "New Hire"))

            # Identity check first (using real user, not sudo)
            sup = rec.sudo().supervisor_id
            sup_user = sup.user_id if sup else False
            is_matched_sup = False

            if sup_user and sup_user.id == current_user.id:
                is_matched_sup = True
            elif sup and (sup in current_user.employee_ids or current_user.employee_id == sup):
                is_matched_sup = True
                if not sup.user_id:
                    sup.sudo().write({"user_id": current_user.id})
            elif sup and not sup.user_id and (
                (sup.work_email and current_user.email and sup.work_email.strip().lower() == current_user.email.strip().lower())
                or (sup.name and current_user.name and sup.name.strip().lower() == current_user.name.strip().lower())
            ):
                is_matched_sup = True
                sup.sudo().write({"user_id": current_user.id})

            if not is_matched_sup:
                if not sup_user:
                    raise ValidationError(_(
                        "The supervisor employee record ('%s') is not linked to any user account.\n"
                        "Please go to Employees -> '%s' -> HR Settings tab -> set 'Related User' to '%s'."
                    ) % (sup.name if sup else "Not Assigned", sup.name if sup else "Not Assigned", current_user.name))
                else:
                    raise ValidationError(_(
                        "Only the assigned Immediate Supervisor ('%s') can submit the supervisor digital sign-off.\n"
                        "Currently logged in as: '%s'."
                    ) % (sup.name if sup else "Not Assigned", current_user.name))

            if rec.sudo().final_supervisor_signoff:
                raise ValidationError(_("Supervisor has already signed off on this onboarding file."))

            # sudo() used here only for the write — identity was verified above
            rec.sudo().write({
                "final_supervisor_signoff": True,
                "final_supervisor_signoff_date": fields.Datetime.now(),
                "final_supervisor_signoff_user_id": current_user.id,
            })
            rec.sudo().message_post(
                body=_("✍️ Supervisor Digital Sign-off Submitted\n"
                       "Supervisor %s has approved onboarding completion for %s on %s.")
                % (current_user.name, rec.sudo().employee_id.name if rec.employee_id else "",
                   fields.Datetime.now().strftime("%d %b %Y %H:%M"))
            )

    def action_close_onboarding(self):
        current_user = self.env.user
        for rec in self:
            # SoD Check 1: New hire employee cannot close their own onboarding plan
            emp_user = rec.employee_id.sudo().user_id if rec.employee_id else False
            if emp_user and emp_user.id == current_user.id:
                raise ValidationError(_(
                    "Segregation of Duties Violation: You ('%s') are the new hire employee. "
                    "You are strictly prohibited from closing your own onboarding file."
                ) % current_user.name)

            # SoD Check 2: Initiator cannot be the sole approver for program closure
            if rec.submitted_by_user_id and rec.submitted_by_user_id.id == current_user.id and not self.env.su:
                raise ValidationError(_(
                    "Segregation of Duties Violation: You ('%s') initiated this onboarding record. "
                    "To ensure segregation of duties, another authorized HR Manager / Supervisor must execute final program closure."
                ) % current_user.name)

            # Gate 1: Employee sign-off
            if not rec.final_employee_signoff:
                raise ValidationError(_(
                    "Cannot close the onboarding file!\n"
                    "The new hire employee ('%s') has not yet submitted their digital sign-off."
                ) % (rec.employee_id.name if rec.employee_id else "New Hire"))

            # Gate 2: Supervisor sign-off
            if not rec.final_supervisor_signoff:
                raise ValidationError(_(
                    "Cannot close the onboarding file!\n"
                    "The Immediate Supervisor ('%s') has not yet submitted their digital sign-off."
                ) % (rec.supervisor_id.name if rec.supervisor_id else "Not Assigned"))

            # Gate 3: All tasks completed
            incomplete_tasks = rec.task_ids.filtered(lambda t: t.state != "done")
            if incomplete_tasks:
                raise ValidationError(_(
                    "Cannot close the onboarding file! The following onboarding tasks are still pending:\n - %s"
                ) % "\n - ".join(incomplete_tasks.mapped("name")))

            # Gate 4: Overall score provided
            if not rec.final_onboarding_score or rec.final_onboarding_score <= 0:
                raise ValidationError(_(
                    "Prerequisite Missing: Please enter the 'Overall Onboarding Score (/100)' under the 'Evaluations & Sign-off' tab before closing the file."
                ))

            rec.write({
                "state": "completed",
                "final_eval_date": fields.Date.today(),
                "closed_by_user_id": current_user.id,
            })
            rec._compute_task_metrics()
            rec.message_post(
                body=_("Onboarding file digitally signed off and closed by HR Manager (%s).") % current_user.name
            )

            # ── Linkage Gate: Feed completion & score directly to Probation record ──
            if rec.probation_id:
                emp_name = rec.employee_id.name if rec.employee_id else "New Hire"
                rec.probation_id.sudo().message_post(
                    body=_(
                        "🎉 Workplace Onboarding Completed & Signed Off\n\n"
                        "Onboarding Plan: %s\n"
                        "Employee: %s\n"
                        "Overall Onboarding Score: %.2f / 100\n"
                        "Employee Digital Sign-off: Completed (%s)\n"
                        "Supervisor Digital Sign-off: Completed (%s)\n"
                        "Closed By: %s\n\n"
                        "This record feeds directly into final probation evaluation and permanency confirmation."
                    ) % (
                        rec.name,
                        emp_name,
                        rec.final_onboarding_score,
                        rec.final_employee_signoff_date.strftime("%d %b %Y %H:%M") if rec.final_employee_signoff_date else "Yes",
                        rec.final_supervisor_signoff_date.strftime("%d %b %Y %H:%M") if rec.final_supervisor_signoff_date else "Yes",
                        current_user.name
                    )
                )

    def _get_or_create_discuss_dm_channel(self, partner):
        """Return a discuss.channel recordset for a 1-on-1 direct conversation with `partner`."""
        self.ensure_one()
        Channel = self.env['discuss.channel'].sudo()
        channel = self.env['discuss.channel']
        try:
            if hasattr(Channel, '_get_or_create_chat'):
                channel = Channel._get_or_create_chat(partner.ids)
            elif hasattr(Channel, 'channel_get'):
                channel_info = Channel.channel_get(partner.ids)
                if channel_info and channel_info.get('id'):
                    channel = self.env['discuss.channel'].sudo().browse(channel_info['id'])
        except Exception as e:
            _logger.error(
                "Onboarding %s: error opening Discuss DM channel with partner %s: %s",
                self.name, partner.id, e
            )
            return self.env['discuss.channel']
        return channel

    def action_trigger_probation_escalation(self):
        """Manually trigger or revalidate milestone escalation alerts."""
        today = fields.Date.context_today(self)
        for rec in self:
            overdue_reasons = []
            # Check overdue tasks
            overdue_tasks = rec.task_ids.filtered(lambda t: t.state != "done" and t.due_date and t.due_date < today)
            if overdue_tasks:
                task_list = ", ".join(overdue_tasks.mapped("name"))
                overdue_reasons.append(f"Overdue Tasks ({len(overdue_tasks)}): {task_list}")

            # Check mid-term evaluation milestone (after 30 days)
            if rec.start_date and (today - rec.start_date).days > 30 and not rec.midterm_eval_sent:
                overdue_reasons.append("4-Week Mid-Term Evaluation has not been dispatched past 30 calendar days.")

            # Check statutory probation timeline
            if rec.probation_deadline and today > rec.probation_deadline:
                overdue_reasons.append(f"Statutory probation duration exceeded deadline ({rec.probation_deadline}).")

            if not overdue_reasons:
                overdue_reasons.append("Milestone delayed beyond standard operational onboarding SLA.")

            reason_text = "\n".join(overdue_reasons)
            rec.write({
                "is_escalated": True,
                "escalation_reason": reason_text,
                "state": "escalated",
            })

            # Notify POMD & Supervisor
            partner_ids = []
            if rec.supervisor_id and rec.supervisor_id.user_id:
                partner_ids.append(rec.supervisor_id.user_id.partner_id.id)
            pomd_group = self.env.ref("custom_onboarding_induction.group_onboarding_induction_officer", raise_if_not_found=False)
            if pomd_group:
                pomd_users = self.env["res.users"].sudo().search([("group_ids", "in", [pomd_group.id])])
                partner_ids.extend([u.partner_id.id for u in pomd_users if u.partner_id])

            rec.message_post(
                body=_(
                    "⚠️ Onboarding Milestone Escalation Alert!\n\n"
                    "Employee: %s\n"
                    "Escalation Reason:\n%s\n\n"
                    "Attention: Immediate Supervisor and POMD Officers, immediate remedial action is required."
                ) % (
                    rec.employee_id.name if rec.employee_id else "New Hire",
                    reason_text
                ),
                partner_ids=list(set(partner_ids)),
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
            )
            # Send Direct 1-on-1 Discuss message to Immediate Supervisor so it appears in Discuss -> Direct Messages
            recip_partners = []
            if rec.supervisor_id and rec.supervisor_id.user_id and rec.supervisor_id.user_id.partner_id:
                recip_partners.append((rec.supervisor_id.user_id.partner_id, rec.supervisor_id.name))

            for partner, p_name in recip_partners:
                dm_chan = rec._get_or_create_discuss_dm_channel(partner)
                if dm_chan:
                    formatted_reason = Markup(reason_text.replace("\n", "<br/>"))
                    emp_name = rec.employee_id.name if rec.employee_id else "New Hire"
                    msg_body = Markup(f"""
                        <p>Dear {p_name},</p>
                        <p>⚠️ <b>Onboarding Milestone Escalation Alert!</b></p>
                        <p><b>Onboarding Plan:</b> {rec.name}</p>
                        <p><b>Employee:</b> {emp_name}</p>
                        <p><b>Escalation Reason:</b><br/>{formatted_reason}</p>
                        <p><b>Attention:</b> Immediate supervisory and remedial action is required.</p>
                        <p>Best regards,<br/>Bunna Bank POMD / Onboarding Management</p>
                    """)
                    try:
                        dm_chan.sudo().message_post(
                            body=msg_body,
                            message_type="comment",
                            subtype_xmlid="mail.mt_comment",
                        )
                    except Exception as e:
                        _logger.error(
                            "Onboarding %s: failed to post Discuss direct message to partner %s: %s",
                            rec.name, partner.id, e
                        )
            if rec.probation_id:
                rec.probation_id.sudo().message_post(
                    body=_(
                        "⚠️ Escalation Notice from Onboarding System\n"
                        "Employee %s has milestone delays in Onboarding Plan %s:\n%s"
                    ) % (
                        rec.employee_id.name if rec.employee_id else "New Hire",
                        rec.name,
                        reason_text
                    )
                )
            template = self.env.ref("custom_onboarding_induction.mail_template_onboarding_milestone_escalation", raise_if_not_found=False)
            if template:
                for p_id in list(set(partner_ids)):
                    partner = self.env["res.partner"].browse(p_id)
                    if partner.email:
                        template.send_mail(rec.id, force_send=False, email_values={"email_to": partner.email})

    def action_resolve_escalation(self):
        """HR Manager or Supervisor resolves the escalation after taking corrective action."""
        for rec in self:
            rec.write({
                "is_escalated": False,
                "escalation_reason": False,
                "state": "work_unit_onboarding" if rec.induction_completed else "induction_gate",
            })
            rec.message_post(body=_("Milestone escalation resolved by %s.") % self.env.user.name)

    @api.model
    def _cron_auto_complete_due_tasks(self):
        """Daily scheduled action to auto-complete onboarding tasks whose due date has been reached."""
        today = fields.Date.context_today(self)
        due_tasks = self.env["hr.onboarding.task"].sudo().search([
            ("state", "=", "todo"),
            ("due_date", "<=", today),
        ], order="due_date asc, id asc")
        if due_tasks:
            due_tasks._auto_complete_as_system()

    def _auto_complete_due_tasks(self):
        """Check and complete any due tasks for the current onboarding plan(s)."""
        try:
            today = odoo_fields.Date.context_today(self)
            for plan in self.sudo():
                due_tasks = plan.task_ids.filtered(lambda t: t.state == "todo" and t.due_date and t.due_date <= today)
                if due_tasks:
                    due_tasks.sorted(key=lambda t: (t.due_date or today, t.id))._auto_complete_as_system()
        except Exception as e:
            _logger.warning("Bypassed auto-complete due tasks in plan: %s", e)

    def read(self, fields=None, load='_classic_read'):
        if not self.env.context.get("skip_auto_complete_tasks"):
            try:
                self._auto_complete_due_tasks()
            except Exception as e:
                _logger.warning("Bypassed auto-complete due tasks in plan read: %s", e)
        return super().read(fields=fields, load=load)

    @api.model
    def _cron_check_onboarding_milestone_escalations(self):
        """Automated daily cron to detect delayed onboarding milestones & trigger POMD alerts."""
        today = fields.Date.context_today(self)
        active_plans = self.search([
            ("active", "=", True),
            ("state", "in", ["pre_boarding", "induction_gate", "work_unit_onboarding", "midterm_review"]),
        ])
        for plan in active_plans:
            is_overdue = False
            reasons = []

            # 1. Day 1 tasks overdue by >= 2 days
            d1_overdue = plan.task_ids.filtered(
                lambda t: t.period == "day_1" and t.state != "done" and t.due_date and (today - t.due_date).days >= 2
            )
            if d1_overdue:
                is_overdue = True
                reasons.append(f"Day 1 task(s) overdue by 2+ days: {', '.join(d1_overdue.mapped('name'))}")

            # 2. Week 1 tasks overdue by >= 3 days
            w1_overdue = plan.task_ids.filtered(
                lambda t: t.period == "week_1" and t.state != "done" and t.due_date and (today - t.due_date).days >= 3
            )
            if w1_overdue:
                is_overdue = True
                reasons.append(f"Week 1 task(s) overdue by 3+ days: {', '.join(w1_overdue.mapped('name'))}")

            # 3. 4-Week Mid-Term eval delayed past 32 days
            if plan.start_date and (today - plan.start_date).days >= 32 and not plan.midterm_eval_sent:
                is_overdue = True
                reasons.append("4-Week Mid-Term Evaluation delayed past 32 calendar days.")

            # 4. Approaching probation end (within 10 days) with incomplete tasks
            duration = 75 if plan.employee_category == "Managerial" else 60
            if plan.start_date:
                probation_end = plan.start_date + timedelta(days=duration)
                if today >= probation_end - timedelta(days=10) and plan.progress_percentage < 80.0:
                    is_overdue = True
                    reasons.append(f"Probation period ends on {probation_end}. Overall task progress is only {plan.progress_percentage:.1f}%.")

            if is_overdue and not plan.is_escalated:
                plan.action_trigger_probation_escalation()


class HrOnboardingTask(models.Model):
    _name = "hr.onboarding.task"
    _description = "Workplace Onboarding Task Checklist"
    _order = "due_date asc, id"

    onboarding_plan_id = fields.Many2one("hr.onboarding.plan", string="Onboarding Plan", required=True, ondelete="cascade")
    template_id = fields.Many2one(
        "hr.onboarding.task.template",
        string="Task Description",
        domain=[("active", "=", True)],
        ondelete="restrict",
        help="Select strictly from configured Onboarding Task Templates.",
    )
    name = fields.Char(string="Task Description", required=True)
    period = fields.Selection(
        [
            ("day_1", "Day 1"),
            ("week_1", "Week 1"),
            ("week_2", "Week 2"),
            ("week_3", "Week 3"),
            ("month_1", "Month 1"),
            ("month_2", "Month 2"),
        ],
        string="Timeline Period", default="day_1", required=True,
    )
    assigned_to_role = fields.Selection(
        [
            ("supervisor", "Immediate Supervisor"),
            ("buddy", "Onboarding Buddy"),
            ("employee", "New Hire Employee"),
            ("hr_officer", "HR Officer"),
        ],
        string="Assigned Role", default="supervisor", required=True,
    )
    due_date = fields.Date(string="Due Date")
    is_first_task = fields.Boolean(
        string="Is First Task (Editable Due Date)",
        compute="_compute_is_first_task",
        store=True,
    )
    completed_date = fields.Datetime(string="Completed On", readonly=True)
    completed_by_user_id = fields.Many2one("res.users", string="Completed By", readonly=True, copy=False)
    can_mark_done = fields.Boolean(
        string="Can Mark Done",
        compute="_compute_can_mark_done",
        store=False,
    )
    is_officer_or_admin = fields.Boolean(
        string="Is HR Officer or Administrator",
        compute="_compute_is_officer_or_admin",
        store=False,
    )
    state = fields.Selection([("todo", "To Do"), ("done", "Completed")], string="Status", default="todo")
    comments = fields.Text(string="Progress Notes / Comments")

    @api.model
    def _get_system_user(self):
        root = self.env.ref("base.user_root", raise_if_not_found=False)
        if root:
            if root.partner_id and root.partner_id.name != "System":
                root.partner_id.sudo().write({"name": "System"})
            return root
        admin = self.env.ref("base.user_admin", raise_if_not_found=False)
        if admin:
            return admin
        return self.env["res.users"].sudo().browse(1)

    def _auto_complete_as_system(self):
        """Auto-complete tasks as System when due date has arrived."""
        today = fields.Date.context_today(self)
        system_user = self._get_system_user()
        for task in self.sudo():
            if task.state == "done":
                continue
            completion_dt = fields.Datetime.now()
            task.with_context(auto_complete_system=True, skip_auto_complete_tasks=True).write({
                "state": "done",
                "completed_date": completion_dt,
                "completed_by_user_id": system_user.id,
            })

    def read(self, fields=None, load='_classic_read'):
        if not self.env.context.get("skip_auto_complete_tasks"):
            try:
                today = odoo_fields.Date.context_today(self)
                due = self.filtered(lambda t: t.state == "todo" and t.due_date and t.due_date <= today)
                if due:
                    due.sorted(key=lambda t: (t.due_date or today, t.id))._auto_complete_as_system()
            except Exception as e:
                _logger.warning("Bypassed auto-complete due tasks in task read: %s", e)
        return super().read(fields=fields, load=load)

    def _compute_is_officer_or_admin(self):
        user = self.env.user
        val = bool(
            user.id == 1
            or getattr(user, "_is_admin", lambda: False)()
            or user.has_group("custom_onboarding_induction.group_onboarding_induction_manager")
            or user.has_group("custom_onboarding_induction.group_onboarding_induction_officer")
            or user.has_group("base.group_system")
        )
        for rec in self:
            rec.is_officer_or_admin = val

    def _is_user_authorized_to_mark_done(self, user):
        """Verify that the user matches the specific assigned_to_role of this individual task."""
        self.ensure_one()
        if not user:
            return False

        # Superuser root override for maintenance/system scripts
        if user.id == 1:
            return True

        plan = self.sudo().onboarding_plan_id
        if not plan:
            return False

        role = self.assigned_to_role
        user_sudo = user.sudo()
        user_emp = getattr(user_sudo, "employee_id", False)
        user_emps = getattr(user_sudo, "employee_ids", self.env["hr.employee"])

        # 1. Role: Onboarding Buddy -> Strictly the designated buddy
        if role == "buddy":
            buddy = plan.buddy_id.sudo()
            if buddy:
                if buddy.user_id and buddy.user_id.id == user.id:
                    return True
                if user_emps and buddy in user_emps:
                    return True
                if user_emp and user_emp.id == buddy.id:
                    return True
                if buddy.work_email and user.email and buddy.work_email.strip().lower() == user.email.strip().lower():
                    return True
                if buddy.name and user.name and buddy.name.strip().lower() == user.name.strip().lower():
                    return True
            return False

        # 2. Role: Immediate Supervisor -> Strictly the designated supervisor
        elif role == "supervisor":
            supervisor = plan.supervisor_id.sudo()
            if supervisor:
                if supervisor.user_id and supervisor.user_id.id == user.id:
                    return True
                if user_emps and supervisor in user_emps:
                    return True
                if user_emp and user_emp.id == supervisor.id:
                    return True
                if supervisor.work_email and user.email and supervisor.work_email.strip().lower() == user.email.strip().lower():
                    return True
                if supervisor.name and user.name and supervisor.name.strip().lower() == user.name.strip().lower():
                    return True
            return False

        # 3. Role: New Hire Employee -> Strictly the new hire employee
        elif role == "employee":
            emp = plan.employee_id.sudo()
            if emp:
                if emp.user_id and emp.user_id.id == user.id:
                    return True
                if user_emps and emp in user_emps:
                    return True
                if user_emp and user_emp.id == emp.id:
                    return True
                if emp.work_email and user.email and emp.work_email.strip().lower() == user.email.strip().lower():
                    return True
                if emp.name and user.name and emp.name.strip().lower() == user.name.strip().lower():
                    return True
            return False

        # 4. Role: HR Officer -> Strictly HR Officer or Onboarding Administrator
        elif role == "hr_officer":
            if (
                user.has_group("custom_onboarding_induction.group_onboarding_induction_officer")
                or user.has_group("custom_onboarding_induction.group_onboarding_induction_manager")
                or user.has_group("base.group_system")
            ):
                return True
            return False

        return False

    def _compute_can_mark_done(self):
        user = self.env.user
        for rec in self:
            rec.can_mark_done = rec.sudo()._is_user_authorized_to_mark_done(user)

    @api.depends("onboarding_plan_id.task_ids")
    def _compute_is_first_task(self):
        for rec in self:
            plan = rec.onboarding_plan_id
            if plan and plan.task_ids:
                first = plan.task_ids[0]
                rec.is_first_task = bool(rec == first or rec.id == first.id)
            else:
                rec.is_first_task = (rec.period == "day_1")

    @api.onchange("due_date")
    def _onchange_due_date(self):
        if self.due_date and self.onboarding_plan_id:
            plan = self.onboarding_plan_id
            if plan.start_date and self.due_date < plan.start_date:
                self.due_date = plan.start_date
                return {
                    "warning": {
                        "title": _("Invalid Due Date"),
                        "message": _(
                            "Task Due Date cannot be earlier than the Onboarding Plan Expected Start Date (%s).\n"
                            "Due Date has been reset to the Expected Start Date."
                        ) % plan.start_date
                    }
                }

            first_task = plan.task_ids and plan.task_ids[0]
            if first_task and (self == first_task or self._origin.id == first_task._origin.id or self.is_first_task):
                base_date = self.due_date
                first_offset = self.template_id.days_offset if (self.template_id and self.template_id.days_offset is not False) else 1
                for task in plan.task_ids:
                    if task == self or task._origin.id == self._origin.id:
                        continue
                    if task.period == "day_1":
                        task.due_date = base_date
                    elif task.template_id and task.template_id.days_offset is not False:
                        diff = max(0, task.template_id.days_offset - first_offset)
                        task.due_date = base_date + timedelta(days=diff)
                    else:
                        period_offsets = {
                            "day_1": 0,
                            "week_1": 6,
                            "week_2": 13,
                            "week_3": 20,
                            "month_1": 29,
                            "month_2": 59,
                        }
                        task.due_date = base_date + timedelta(days=period_offsets.get(task.period, 0))

    @api.onchange("template_id")
    def _onchange_template_id(self):
        if self.template_id:
            tmpl = self.template_id
            self.name = tmpl.name
            self.period = tmpl.period
            self.assigned_to_role = tmpl.assigned_to_role
            plan = self.onboarding_plan_id
            first_task = plan.task_ids and plan.task_ids[0] if plan else False
            first_offset = first_task.template_id.days_offset if (first_task and first_task.template_id and first_task.template_id.days_offset is not False) else 1
            base_date = first_task.due_date if (first_task and first_task.due_date) else ((plan.start_date if plan else False) or fields.Date.context_today(self))
            if self == first_task or not first_task:
                self.due_date = base_date
            else:
                if tmpl.period == "day_1":
                    self.due_date = base_date
                else:
                    diff = max(0, (tmpl.days_offset or 1) - first_offset)
                    self.due_date = base_date + timedelta(days=diff)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("template_id"):
                tmpl = self.env["hr.onboarding.task.template"].browse(vals["template_id"])
                if tmpl.exists():
                    if not vals.get("name"):
                        vals["name"] = tmpl.name
                    if "period" not in vals:
                        vals["period"] = tmpl.period
                    if "assigned_to_role" not in vals:
                        vals["assigned_to_role"] = tmpl.assigned_to_role
            elif vals.get("name") and not vals.get("template_id"):
                tmpl = self.env["hr.onboarding.task.template"].search([
                    ("name", "=ilike", vals["name"].strip())
                ], limit=1)
                if tmpl:
                    vals["template_id"] = tmpl.id
        return super().create(vals_list)

    @api.constrains("template_id")
    def _check_template_id(self):
        for rec in self:
            if not rec.template_id:
                if rec.name:
                    tmpl = self.env["hr.onboarding.task.template"].search([
                        ("name", "=ilike", rec.name.strip())
                    ], limit=1)
                    if tmpl:
                        rec.template_id = tmpl.id
                        continue
                raise ValidationError(_(
                    "Invalid Workplace Task Error!\n\n"
                    "You cannot enter arbitrary text '%s'.\n\n"
                    "Every workplace onboarding task MUST be selected from the pre-configured Onboarding Task Templates."
                ) % (rec.name or ""))

    @api.constrains("onboarding_plan_id", "template_id")
    def _check_unique_template_per_plan(self):
        for rec in self:
            if rec.template_id and rec.onboarding_plan_id:
                dups = self.search([
                    ("id", "!=", rec.id),
                    ("onboarding_plan_id", "=", rec.onboarding_plan_id.id),
                    ("template_id", "=", rec.template_id.id),
                ], limit=1)
                if dups:
                    raise ValidationError(_(
                        "Duplicate Workplace Task Error!\n\n"
                        "The task '%s' is already assigned to this Onboarding Plan."
                    ) % rec.template_id.name)

    @api.constrains("due_date", "onboarding_plan_id")
    def _check_task_due_date_rules(self):
        for rec in self:
            if rec.due_date and rec.onboarding_plan_id:
                plan = rec.onboarding_plan_id
                if plan.start_date and rec.due_date < plan.start_date:
                    raise ValidationError(_(
                        "Invalid Task Due Date Error!\n\n"
                        "Task '%s' has Due Date %s, which is earlier than the Onboarding Plan Expected Start Date (%s).\n"
                        "Due Date must be greater than or equal to Expected Start Date."
                    ) % (rec.name, rec.due_date, plan.start_date))

    is_overdue = fields.Boolean(
        string="Overdue", compute="_compute_is_overdue", store=False,
        help="True when the task is not yet done and the due date has passed."
    )

    @api.depends("state", "due_date")
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_overdue = (
                rec.state == "todo"
                and bool(rec.due_date)
                and rec.due_date < today
            )

    def write(self, vals):
        user = self.env.user
        # ── Non-admin/officer users cannot modify task configuration fields ──
        config_fields = set(vals.keys()) - {"state", "completed_date", "completed_by_user_id", "comments"}
        if config_fields and not self.env.su:
            is_officer_or_admin = (
                user.id == 1
                or getattr(user, "_is_admin", lambda: False)()
                or user.has_group("custom_onboarding_induction.group_onboarding_induction_manager")
                or user.has_group("custom_onboarding_induction.group_onboarding_induction_officer")
                or user.has_group("base.group_system")
            )
            if not is_officer_or_admin:
                raise ValidationError(_(
                    "Access Denied: Read-Only Task!\n\n"
                    "Workplace onboarding tasks are strictly read-only for employees.\n"
                    "Only HR Officers and Administrators can modify task configurations."
                ))

        if vals.get("state") == "done" and not self.env.context.get("auto_complete_system"):
            today = fields.Date.context_today(self)
            for rec in self:
                rec_sudo = rec.sudo()
                plan = rec_sudo.onboarding_plan_id
                # ── Role-Specific Authorization Check ──
                if not self.env.su and not rec_sudo._is_user_authorized_to_mark_done(user):
                    role_labels = dict(rec._fields["assigned_to_role"].selection)
                    role_name = role_labels.get(rec.assigned_to_role, rec.assigned_to_role)
                    expected_person = ""
                    if rec.assigned_to_role == "buddy":
                        expected_person = f"Onboarding Buddy ('{plan.buddy_id.name if plan and plan.buddy_id else 'Assigned Buddy'}')"
                    elif rec.assigned_to_role == "supervisor":
                        expected_person = f"Immediate Supervisor ('{plan.supervisor_id.name if plan and plan.supervisor_id else 'Supervisor'}')"
                    elif rec.assigned_to_role == "employee":
                        expected_person = f"New Hire Employee ('{plan.employee_id.name if plan and plan.employee_id else 'New Hire'}')"
                    elif rec.assigned_to_role == "hr_officer":
                        expected_person = "Authorized HR Officer"

                    raise ValidationError(_(
                        "Access Denied: Task Role Mismatch!\n\n"
                        "Task '%s' is assigned to role '%s'.\n"
                        "Only the %s (or an Administrator) can mark this task as Done.\n\n"
                        "• Currently logged in as: '%s'."
                    ) % (
                        rec.name,
                        role_name,
                        expected_person,
                        user.name
                    ))

                target_due = vals.get("due_date") and fields.Date.to_date(vals["due_date"]) or rec.due_date
                if target_due and today < target_due:
                    raise ValidationError(_(
                        "Premature Task Completion Error!\n\n"
                        "Task '%s' cannot be marked as Done before its scheduled due date.\n\n"
                        "• Today's Date: %s\n"
                        "• Scheduled Due Date: %s\n\n"
                        "This task can only be marked as Done on or after %s."
                    ) % (
                        rec.name,
                        today.strftime("%b %d, %Y"),
                        target_due.strftime("%b %d, %Y"),
                        target_due.strftime("%b %d, %Y"),
                    ))

                # ── Chronological Pre-Order Validation: Older scheduled tasks must be done first ──
                if target_due and plan:
                    pending_prior = plan.task_ids.filtered(
                        lambda t: t.id != rec.id and t.state != "done" and t.due_date and t.due_date < target_due
                    )
                    if pending_prior:
                        earlier_task = pending_prior.sorted(key=lambda t: (t.due_date, t.id))[0]
                        raise ValidationError(_(
                            "Chronological Task Completion Error!\n\n"
                            "Tasks must be completed in order of their scheduled dates. "
                            "A task with a later date cannot be marked as Done while older scheduled tasks are still pending.\n\n"
                            "• Current Task: '%s' (Due Date: %s)\n"
                            "• Older Pending Task: '%s' (Due Date: %s)\n\n"
                            "Please complete '%s' first before completing this task."
                        ) % (
                            rec.name,
                            target_due.strftime("%b %d, %Y"),
                            earlier_task.name,
                            earlier_task.due_date.strftime("%b %d, %Y"),
                            earlier_task.name,
                        ))
        res = super().write(vals)
        if "state" in vals:
            self.sudo().mapped("onboarding_plan_id")._compute_task_metrics()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.sudo().mapped("onboarding_plan_id")._compute_task_metrics()
        return records

    def unlink(self):
        plans = self.sudo().mapped("onboarding_plan_id")
        res = super().unlink()
        plans._compute_task_metrics()
        return res

    def action_mark_done(self):
        current_user = self.env.user
        today = fields.Date.context_today(self)
        for rec in self:
            rec_sudo = rec.sudo()
            plan = rec_sudo.onboarding_plan_id
            # ── Role-Specific Authorization Check ──
            if not rec_sudo._is_user_authorized_to_mark_done(current_user):
                role_labels = dict(rec._fields["assigned_to_role"].selection)
                role_name = role_labels.get(rec.assigned_to_role, rec.assigned_to_role)
                expected_person = ""
                if rec.assigned_to_role == "buddy":
                    expected_person = f"Onboarding Buddy ('{plan.buddy_id.name if plan and plan.buddy_id else 'Assigned Buddy'}')"
                elif rec.assigned_to_role == "supervisor":
                    expected_person = f"Immediate Supervisor ('{plan.supervisor_id.name if plan and plan.supervisor_id else 'Supervisor'}')"
                elif rec.assigned_to_role == "employee":
                    expected_person = f"New Hire Employee ('{plan.employee_id.name if plan and plan.employee_id else 'New Hire'}')"
                elif rec.assigned_to_role == "hr_officer":
                    expected_person = "Authorized HR Officer"

                raise ValidationError(_(
                    "Access Denied: Task Role Mismatch!\n\n"
                    "Task '%s' is assigned to role '%s'.\n"
                    "Only the %s (or an Administrator) can mark this task as Done.\n\n"
                    "• Currently logged in as: '%s'."
                ) % (
                    rec.name,
                    role_name,
                    expected_person,
                    current_user.name
                ))

            if plan and plan.state in ("draft", "pre_boarding", "induction_gate"):
                raise ValidationError(_(
                    "Cannot complete operational tasks while onboarding plan is in '%s' status. "
                    "Employee must complete Pre-Boarding and Corporate Induction first."
                ) % plan.state)

            # ── Due Date Validation: Only allow completion on or after scheduled due date ──
            if rec.due_date and today < rec.due_date:
                raise ValidationError(_(
                    "Premature Task Completion Error!\n\n"
                    "Task '%s' cannot be marked as Done before its scheduled due date.\n\n"
                    "• Today's Date: %s\n"
                    "• Scheduled Due Date: %s\n\n"
                    "This task can only be marked as Done on or after %s."
                ) % (
                    rec.name,
                    today.strftime("%b %d, %Y"),
                    rec.due_date.strftime("%b %d, %Y"),
                    rec.due_date.strftime("%b %d, %Y"),
                ))

            # ── Chronological Pre-Order Validation: Older scheduled tasks must be done first ──
            if rec.due_date and plan:
                pending_prior = plan.task_ids.filtered(
                    lambda t: t.id != rec.id and t.state != "done" and t.due_date and t.due_date < rec.due_date
                )
                if pending_prior:
                    earlier_task = pending_prior.sorted(key=lambda t: (t.due_date, t.id))[0]
                    raise ValidationError(_(
                        "Chronological Task Completion Error!\n\n"
                        "Tasks must be completed in order of their scheduled dates. "
                        "A task with a later date cannot be marked as Done while older scheduled tasks are still pending.\n\n"
                        "• Current Task: '%s' (Due Date: %s)\n"
                        "• Older Pending Task: '%s' (Due Date: %s)\n\n"
                        "Please complete '%s' first before completing this task."
                    ) % (
                        rec.name,
                        rec.due_date.strftime("%b %d, %Y"),
                        earlier_task.name,
                        earlier_task.due_date.strftime("%b %d, %Y"),
                        earlier_task.name,
                    ))

            rec_sudo.write({
                "state": "done",
                "completed_date": fields.Datetime.now(),
                "completed_by_user_id": current_user.id,
            })
            # ── Notify buddy & supervisor when a task is completed ──────────────────────
            plan_sudo = plan.sudo() if plan else False
            buddy_partner = (
                plan_sudo.buddy_id.sudo().user_id.partner_id
                if plan_sudo and plan_sudo.buddy_id and plan_sudo.buddy_id.sudo().user_id
                else False
            )
            supervisor_partner = (
                plan_sudo.supervisor_id.sudo().user_id.partner_id
                if plan_sudo and plan_sudo.supervisor_id and plan_sudo.supervisor_id.sudo().user_id
                else False
            )
            partner_ids = []
            if buddy_partner:
                partner_ids.append(buddy_partner.id)
            if supervisor_partner and supervisor_partner != buddy_partner:
                partner_ids.append(supervisor_partner.id)

            body = _(
                "✅ Onboarding Task Completed\n"
                "Task: %s\n"
                "Assigned Role: %s\n"
                "Period: %s\n"
                "Completed By: %s\n"
                "%s"
            ) % (
                rec.name,
                dict(rec._fields['assigned_to_role'].selection).get(rec.assigned_to_role, rec.assigned_to_role),
                dict(rec._fields['period'].selection).get(rec.period, rec.period),
                current_user.name,
                ("Comments: " + rec.comments) if rec.comments else "",
            )

            if plan:
                plan.sudo().message_post(
                    body=body,
                    partner_ids=partner_ids,
                    subtype_xmlid="mail.mt_comment",
                )



