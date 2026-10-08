# -*- coding: utf-8 -*-

from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


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

    name = fields.Char(string="Reference", copy=False, readonly=True, default=lambda self: _("New"))

    # ── Basic Employee Info ──────────────────────────────────────────────────
    employee_id = fields.Many2one("hr.employee", string="New Employee", required=True, tracking=True)
    job_position_id = fields.Many2one(
        "hr.job", string="Position Title", compute="_compute_from_employee", store=True, readonly=True
    )
    operating_unit_id = fields.Many2one(
        "operating.unit", string="Work Unit / Location", compute="_compute_from_employee", store=True, readonly=True
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
    doc_offer_letter = fields.Boolean(string="Signed Offer / Acceptance Letter", default=True, tracking=True)
    doc_medical_certificate = fields.Boolean(string="Medical Certificate Verified", default=False, tracking=True)
    doc_police_clearance = fields.Boolean(string="Police Clearance / Forensic Cert.", default=False, tracking=True)
    doc_guarantor_contract = fields.Boolean(string="Guarantor Contract & Letter", default=False, tracking=True)
    doc_code_of_conduct = fields.Boolean(string="Signed Code of Conduct", default=False, tracking=True)
    doc_job_description = fields.Boolean(string="Signed Job Description (JD)", default=False, tracking=True)
    doc_asset_registration = fields.Boolean(string="Asset Requisition / Handover Form", default=False, tracking=True)
    doc_tin_number = fields.Char(string="TIN Number", tracking=True)
    doc_pension_number = fields.Char(string="Pension Number", tracking=True)

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
    buddy_user_id = fields.Many2one("res.users", related="buddy_id.user_id", string="Buddy User Account", readonly=True)
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
    final_eval_sent = fields.Boolean(string="Final Form Sent (2-Month)", default=False, readonly=True)
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
    probation_id = fields.Many2one("hr.employee.probation", string="Linked Probation Record", readonly=True)
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

    # -------------------------------------------------------------------------
    # Computes & Onchanges
    # -------------------------------------------------------------------------
    @api.depends("employee_id")
    def _compute_from_employee(self):
        for rec in self:
            if rec.employee_id:
                rec.job_position_id = rec.employee_id.job_id
                rec.operating_unit_id = rec.employee_id.operating_unit_id
                if not rec.supervisor_id and rec.employee_id.parent_id:
                    rec.supervisor_id = rec.employee_id.parent_id
            else:
                rec.job_position_id = False
                rec.operating_unit_id = False

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
            total = len(rec.task_ids)
            completed = len(rec.task_ids.filtered(lambda t: t.state == "done"))
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
            mid_score = rec.midterm_score or 0.0

            calculated = (
                (ind_score * (w_ind / 100.0)) +
                (task_score * (w_task / 100.0)) +
                (mid_score * (w_mid / 100.0))
            )
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
            rec._auto_generate_default_tasks()
            rec._auto_link_or_create_induction()
        return records

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
                ("state", "!=", "completed"),
            ], limit=1)
            if existing:
                self.induction_plan_id = existing.id
            else:
                new_induction = self.env["hr.induction.plan"].create({
                    "employee_id": self.employee_id.id,
                    "supervisor_id": self.supervisor_id.id if self.supervisor_id else False,
                    "start_date": self.start_date,
                    "submitted_by_user_id": self.env.user.id,
                })
                self.induction_plan_id = new_induction.id

    def _auto_generate_default_tasks(self):
        self.ensure_one()
        if self.task_ids:
            return
        start = self.start_date or fields.Date.context_today(self)
        templates = self.env["hr.onboarding.task.template"].search([])
        task_vals = []
        if templates:
            for tmpl in templates:
                due = start + timedelta(days=tmpl.days_offset) if tmpl.days_offset is not False else False
                task_vals.append({
                    "onboarding_plan_id": self.id,
                    "name": tmpl.name,
                    "period": tmpl.period,
                    "assigned_to_role": tmpl.assigned_to_role,
                    "due_date": due,
                    "state": "todo",
                })
        else:
            default_tasks = [
                ("Day 1: Workstation Setup, Email & ERP Access Check", "day_1", "supervisor"),
                ("Day 1: Team & Department Introduction Walkthrough", "day_1", "buddy"),
                ("Week 1: Review Department Operational SOPs & Systems", "week_1", "employee"),
                ("Week 1: Assigned Buddy Mentorship Check-in Session 1", "week_1", "buddy"),
                ("Week 2: Initial Job Assignment & Supervisory Review", "week_2", "supervisor"),
                ("Week 3: Key Process Execution & Practical Walkthrough", "week_3", "employee"),
                ("Month 1: 4-Week Mid-Term Onboarding Evaluation", "month_1", "supervisor"),
                ("Month 2: Final 2-Month Performance Sign-off & File Closure", "month_2", "hr_officer"),
            ]
            period_offsets = {
                "day_1": 1,
                "week_1": 7,
                "week_2": 14,
                "week_3": 21,
                "month_1": 30,
                "month_2": 60,
            }
            for name, period, role in default_tasks:
                offset = period_offsets.get(period, 0)
                due = start + timedelta(days=offset)
                task_vals.append({
                    "onboarding_plan_id": self.id,
                    "name": name,
                    "period": period,
                    "assigned_to_role": role,
                    "due_date": due,
                    "state": "todo",
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
            rec.write({
                "buddy_assigned_date": fields.Datetime.now(),
                "buddy_assigned_by_user_id": current_user.id,
            })
            rec.message_post(
                body=_("Onboarding Buddy '%s' assigned to new hire by %s.") % (rec.buddy_id.name, current_user.name)
            )

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

            # Prerequisite: Midterm rating must be entered
            if not rec.midterm_score or rec.midterm_score <= 0:
                raise ValidationError(_(
                    "Prerequisite Missing: Please provide the 'Mid-Term Rating (/100)' under the 'Evaluations & Sign-off' tab before submitting supervisor sign-off."
                ))

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
            rec.message_post(
                body=_("Onboarding file digitally signed off and closed by HR Manager (%s).") % current_user.name
            )


class HrOnboardingTask(models.Model):
    _name = "hr.onboarding.task"
    _description = "Workplace Onboarding Task Checklist"
    _order = "due_date asc, id"

    onboarding_plan_id = fields.Many2one("hr.onboarding.plan", string="Onboarding Plan", required=True, ondelete="cascade")
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
    completed_date = fields.Datetime(string="Completed On", readonly=True)
    completed_by_user_id = fields.Many2one("res.users", string="Completed By", readonly=True, copy=False)
    state = fields.Selection([("todo", "To Do"), ("done", "Completed")], string="Status", default="todo")
    comments = fields.Text(string="Progress Notes / Comments")

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

    def action_mark_done(self):
        current_user = self.env.user
        for rec in self:
            if rec.onboarding_plan_id.state in ("draft", "pre_boarding", "induction_gate"):
                raise ValidationError(_(
                    "Cannot complete operational tasks while onboarding plan is in '%s' status. "
                    "Employee must complete Pre-Boarding and Corporate Induction first."
                ) % rec.onboarding_plan_id.state)

            rec.write({
                "state": "done",
                "completed_date": fields.Datetime.now(),
                "completed_by_user_id": current_user.id,
            })
            # ── Notify buddy when a task is completed ──────────────────────
            plan = rec.onboarding_plan_id
            buddy_partner = (
                plan.buddy_id.user_id.partner_id
                if plan.buddy_id and plan.buddy_id.user_id
                else False
            )
            supervisor_partner = (
                plan.supervisor_id.user_id.partner_id
                if plan.supervisor_id and plan.supervisor_id.user_id
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

            plan.message_post(
                body=body,
                partner_ids=partner_ids,
                subtype_xmlid="mail.mt_comment",
            )
