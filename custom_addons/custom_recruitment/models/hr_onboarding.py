# -*- coding: utf-8 -*-

from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class HrOnboardingPlan(models.Model):
    _name = "hr.onboarding.plan"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Onboarding and Induction Management Plan"
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

    # ── Pre-Boarding Employment Formalities Checklist ──────────────────────
    doc_medical_certificate = fields.Boolean(string="Medical Certificate Verified", default=False, tracking=True)
    doc_police_clearance = fields.Boolean(string="Police Clearance / Forensic Cert.", default=False, tracking=True)
    doc_guarantor_contract = fields.Boolean(string="Guarantor Contract & Letter", default=False, tracking=True)
    doc_code_of_conduct = fields.Boolean(string="Signed Code of Conduct", default=False, tracking=True)
    doc_job_description = fields.Boolean(string="Signed Job Description (JD)", default=False, tracking=True)
    doc_tin_number = fields.Char(string="TIN Number", tracking=True)
    doc_pension_number = fields.Char(string="Pension Number", tracking=True)
    doc_offer_letter = fields.Boolean(string="Signed Offer / Acceptance Letter", default=True)

    pre_boarding_verified = fields.Boolean(
        string="Pre-Boarding Gate Passed", compute="_compute_pre_boarding_verified", store=True,
        help="Pre-boarding gate passed when all mandatory pre-employment docs are verified."
    )

    # ── Workstation & IT Provisioning Alert ──────────────────────────────────
    provisioning_status = fields.Selection(
        [("pending", "Pending Alert"), ("alert_sent", "Alert Sent to IT/Facilities"), ("provisioned", "Fully Provisioned")],
        string="IT & Workstation Provisioning", default="pending", tracking=True,
    )
    provisioning_alert_date = fields.Datetime(string="Provisioning Alert Sent On", readonly=True)
    it_notes = fields.Text(string="IT & Facilities Setup Notes")

    # ── PPDD General Induction & Gatekeeper ──────────────────────────────────
    induction_status = fields.Selection(
        [("pending", "Pending Induction"), ("in_progress", "Induction In Progress"), ("induction_completed", "Induction Completed")],
        string="POMD Induction Status", default="pending", tracking=True,
    )
    induction_completed_date = fields.Datetime(string="Induction Completed On", readonly=True)
    lms_task_ids = fields.One2many("hr.onboarding.lms.task", "onboarding_plan_id", string="PPDD Orientation & LMS Trainings")

    # ── Onboarding Buddy Support ─────────────────────────────────────────────
    buddy_id = fields.Many2one("hr.employee", string="Assigned Onboarding Buddy", tracking=True)
    buddy_user_id = fields.Many2one("res.users", related="buddy_id.user_id", string="Buddy User Account", readonly=True)
    buddy_assigned_date = fields.Datetime(string="Buddy Assigned On", readonly=True)
    buddy_notes = fields.Text(string="Buddy Guidance Notes & Log")

    # ── Daily/Weekly Task Progress Tracker ────────────────────────────────────
    task_ids = fields.One2many("hr.onboarding.task", "onboarding_plan_id", string="Onboarding Task Progress Tracker")
    total_tasks = fields.Integer(string="Total Tasks", compute="_compute_task_metrics", store=True)
    completed_tasks = fields.Integer(string="Completed Tasks", compute="_compute_task_metrics", store=True)
    progress_percentage = fields.Float(string="Onboarding Progress (%)", compute="_compute_task_metrics", store=True, digits=(5, 2))

    # ── 4-Week Mid-Term Evaluation Form ──────────────────────────────────────
    midterm_eval_sent = fields.Boolean(string="Mid-Term Form Sent (4-Week)", default=False, readonly=True)
    midterm_eval_date = fields.Date(string="Mid-Term Eval Date", readonly=True)
    midterm_employee_feedback = fields.Text(string="New Hire Mid-Term Feedback")
    midterm_supervisor_feedback = fields.Text(string="Supervisor Mid-Term Feedback")
    midterm_score = fields.Float(string="Mid-Term Rating (/100)", digits=(5, 2))

    # ── 2-Month Program Closure & Sign-Off ───────────────────────────────────
    final_eval_sent = fields.Boolean(string="Final Form Sent (2-Month)", default=False, readonly=True)
    final_eval_date = fields.Date(string="Program Closure Date", readonly=True)
    final_employee_signoff = fields.Boolean(string="Digital Sign-off (Employee)", default=False, tracking=True)
    final_supervisor_signoff = fields.Boolean(string="Digital Sign-off (Supervisor)", default=False, tracking=True)
    final_onboarding_score = fields.Float(string="Overall Onboarding Score (/100)", digits=(5, 2))

    # ── Probation Period Linkage & Escalations ───────────────────────────────
    probation_id = fields.Many2one("hr.employee.probation", string="Linked Probation Record", readonly=True)
    is_escalated = fields.Boolean(string="Milestone Escalated", default=False, readonly=True, copy=False)
    escalation_reason = fields.Text(string="Escalation Notes", copy=False)

    # ── Workflow State ────────────────────────────────────────────────────────
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("pre_boarding", "Pre-Boarding Formalities"),
            ("induction", "General Induction (POMD/PPDD)"),
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
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == _("New"):
                vals["name"] = self._get_next_reference()
        records = super().create(vals_list)
        for rec in records:
            rec._auto_generate_default_tasks()
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
            _, _, numeric_part = result[0].rpartition('/')
            try:
                next_number = int(numeric_part) + 1
            except ValueError:
                next_number = 1
        else:
            next_number = 1
        return f"{prefix}{str(next_number).zfill(5)}"

    @api.depends("employee_id")
    def _compute_from_employee(self):
        for rec in self:
            if rec.employee_id:
                rec.job_position_id = getattr(rec.employee_id, 'job_id', False) or getattr(rec.employee_id, 'job_position', False) or False
                rec.operating_unit_id = getattr(rec.employee_id, 'default_operating_unit_id', False) or False
                if not rec.supervisor_id and getattr(rec.employee_id, 'parent_id', False):
                    rec.supervisor_id = rec.employee_id.parent_id
            else:
                rec.job_position_id = False
                rec.operating_unit_id = False

    @api.depends("doc_medical_certificate", "doc_police_clearance", "doc_guarantor_contract", "doc_code_of_conduct", "doc_job_description")
    def _compute_pre_boarding_verified(self):
        for rec in self:
            rec.pre_boarding_verified = (
                rec.doc_medical_certificate and
                rec.doc_police_clearance and
                rec.doc_guarantor_contract and
                rec.doc_code_of_conduct and
                rec.doc_job_description
            )

    @api.depends("task_ids.state")
    def _compute_task_metrics(self):
        for rec in self:
            total = len(rec.task_ids)
            completed = len(rec.task_ids.filtered(lambda t: t.state == "done"))
            rec.total_tasks = total
            rec.completed_tasks = completed
            rec.progress_percentage = (completed / total * 100.0) if total > 0 else 0.0

    # -------------------------------------------------------------------------
    # Default Tasks & Setup
    # -------------------------------------------------------------------------
    def _auto_generate_default_tasks(self):
        """Generate default onboarding tasks and LMS training mapping."""
        self.ensure_one()
        # Default LMS tasks (PPDD Orientation)
        lms_defaults = [
            ("Bunna Bank Culture & Values Orientation Video", "video", True),
            ("Signed Code of Conduct & Ethics Training", "policy", True),
            ("Core ERP & Finacle Banking System Training", "system", True),
            ("Information Security & Compliance Training", "compliance", True),
        ]
        lms_lines = [(0, 0, {
            "name": name,
            "training_type": ttype,
            "is_mandatory": mandatory,
        }) for name, ttype, mandatory in lms_defaults]
        self.write({"lms_task_ids": lms_lines})

        # Default Onboarding Tracker Tasks
        tracker_defaults = [
            ("Week 1", "Workstation Setup & Hardware Verification", "supervisor"),
            ("Week 1", "Team Introduction & Facility Tour", "buddy"),
            ("Week 1", "PPDD General Orientation & LMS System Modules", "new_hire"),
            ("Week 2", "Core Finacle User Account Login & System Training", "new_hire"),
            ("Week 2", "Review Work Unit Operating Procedures & JDs", "buddy"),
            ("Week 3", "First Weekly Mentorship Check-in & Review", "buddy"),
            ("Week 4", "4-Week Mid-Term Performance Review", "supervisor"),
            ("Week 6", "Mid-Probation Progress Review", "supervisor"),
            ("Week 8", "Program Closure & Final Onboarding Sign-off", "supervisor"),
        ]
        task_lines = [(0, 0, {
            "week_stage": stage,
            "name": task_name,
            "assigned_to_role": role,
        }) for stage, task_name, role in tracker_defaults]
        self.write({"task_ids": task_lines})

    # -------------------------------------------------------------------------
    # Actions & Workflow Transitions
    # -------------------------------------------------------------------------
    def action_start_pre_boarding(self):
        """Initiate pre-boarding formalities."""
        for rec in self:
            rec.state = "pre_boarding"
            rec.message_post(body=_("Pre-boarding formalities initiated by POMD."))
        return True

    def action_trigger_provisioning_alert(self):
        """Alert IT & Facilities 7 days prior to start date."""
        for rec in self:
            body = _(
                "URGENT: Pre-Arrival Workstation & IT Provisioning Alert<br/><br/>"
                "New Hire: <b>%(emp)s</b><br/>"
                "Position: <b>%(pos)s</b><br/>"
                "Work Unit: <b>%(unit)s</b><br/>"
                "Start Date: <b>%(start)s</b><br/><br/>"
                "Please configure PC workstation, Finacle user accounts, ERP credentials, and office tools."
            ) % {
                "emp": rec.employee_id.name,
                "pos": rec.job_position_id.name if rec.job_position_id else "",
                "unit": rec.operating_unit_id.name if rec.operating_unit_id else "",
                "start": rec.start_date,
            }
            if rec.supervisor_id and rec.supervisor_id.user_id:
                partner = rec.supervisor_id.user_id.partner_id
                channel = self.env["discuss.channel"]._get_or_create_chat(partners_to=[partner.id])
                channel.message_post(body=body, message_type="comment", subtype_xmlid="mail.mt_comment")

            rec.write({
                "provisioning_status": "alert_sent",
                "provisioning_alert_date": fields.Datetime.now(),
            })
            rec.message_post(body=_("Automated workstation & IT provisioning alert triggered."))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('IT Alert Sent'),
                'message': _('7-Day Pre-arrival IT & Workstation alert triggered.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_mark_induction_completed(self):
        """POMD marks general induction as completed."""
        for rec in self:
            if not rec.pre_boarding_verified:
                raise UserError(_("Pre-Boarding Gate Failed: Cannot mark induction completed until all critical pre-employment documents (Medical, Police Clearance, Guarantor Contract, Code of Conduct, JD) are verified."))

            rec.write({
                "induction_status": "induction_completed",
                "induction_completed_date": fields.Datetime.now(),
                "state": "work_unit_onboarding",
            })

            # Notify supervisor to assign buddy
            if rec.supervisor_id and rec.supervisor_id.user_id:
                body = _(
                    "Dear %(supervisor)s,<br/><br/>"
                    "POMD has completed the General Induction for <b>%(employee)s</b>.<br/>"
                    "Please assign an <b>Onboarding Buddy</b> in the ERP system to initiate work unit onboarding."
                ) % {
                    "supervisor": rec.supervisor_id.name,
                    "employee": rec.employee_id.name,
                }
                partner = rec.supervisor_id.user_id.partner_id
                channel = self.env["discuss.channel"]._get_or_create_chat(partners_to=[partner.id])
                channel.message_post(body=body, message_type="comment", subtype_xmlid="mail.mt_comment")

            rec.message_post(body=_("General Induction completed by POMD. Work Unit onboarding unlocked."))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Induction Completed'),
                'message': _('Induction marked completed. Work unit onboarding unlocked.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_assign_buddy(self, buddy_employee_id):
        """Supervisor assigns Onboarding Buddy."""
        self.ensure_one()
        buddy = self.env["hr.employee"].browse(buddy_employee_id)
        if not buddy:
            raise UserError(_("Please select a valid employee to assign as Onboarding Buddy."))

        self.write({
            "buddy_id": buddy.id,
            "buddy_assigned_date": fields.Datetime.now(),
        })

        if buddy.user_id:
            body = _(
                "Dear %(buddy)s,<br/><br/>"
                "You have been assigned as the <b>Onboarding Buddy</b> for new hire <b>%(employee)s</b> (%(position)s).<br/>"
                "Please access your Onboarding Checklist in ERP to log weekly check-ins and mentor guidance notes."
            ) % {
                "buddy": buddy.name,
                "employee": self.employee_id.name,
                "position": self.job_position_id.name if self.job_position_id else "",
            }
            partner = buddy.user_id.partner_id
            channel = self.env["discuss.channel"]._get_or_create_chat(partners_to=[partner.id])
            channel.message_post(body=body, message_type="comment", subtype_xmlid="mail.mt_comment")

        self.message_post(body=_("Onboarding Buddy assigned: <b>%s</b>.") % buddy.name)

    def action_dispatch_midterm_eval(self):
        """Dispatch 4-Week Mid-Term Evaluation Form."""
        for rec in self:
            rec.write({
                "midterm_eval_sent": True,
                "midterm_eval_date": fields.Date.context_today(self),
                "state": "midterm_review",
            })
            rec.message_post(body=_("4-Week Mid-Term Evaluation Form dispatched to New Hire and Supervisor."))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Mid-Term Form Dispatched'),
                'message': _('4-Week Mid-Term Evaluation Form dispatched.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_close_onboarding(self):
        """Program Closure & Digital Sign-off at 2 Months."""
        for rec in self:
            if not rec.final_employee_signoff or not rec.final_supervisor_signoff:
                raise UserError(_("Digital Sign-off Gate: Both New Hire and Supervisor must complete their digital sign-off before closing the onboarding file."))

            rec.write({
                "final_eval_sent": True,
                "final_eval_date": fields.Date.context_today(self),
                "state": "completed",
            })

            # Link & update Probation metrics
            rec.action_sync_to_probation()
            rec.message_post(body=_("Onboarding program formally closed with full digital sign-off."))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Onboarding Closed'),
                'message': _('Onboarding program successfully completed and closed.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_sync_to_probation(self):
        """Link Onboarding metrics to Probation Record."""
        for rec in self:
            prob = self.env["hr.employee.probation"].search([("employee_id", "=", rec.employee_id.id)], limit=1)
            if prob:
                rec.probation_id = prob.id
                prob.message_post(body=_(
                    "Onboarding Progress Synced: Overall Onboarding Score: <b>%.2f%%</b>. Tasks Completed: %d/%d."
                ) % (rec.progress_percentage, rec.completed_tasks, rec.total_tasks))

    @api.model
    def _cron_check_onboarding_escalations(self):
        """Escalation CRON for delayed onboarding milestones."""
        target_date = fields.Date.context_today(self) - timedelta(days=14)
        delayed_plans = self.search([
            ("state", "in", ["pre_boarding", "induction", "work_unit_onboarding"]),
            ("start_date", "<=", target_date),
            ("progress_percentage", "<", 50.0),
            ("is_escalated", "=", False),
        ])
        for plan in delayed_plans:
            plan.write({
                "is_escalated": True,
                "escalation_reason": _("Delayed Onboarding: Progress is under 50% after 14 days from start date."),
            })
            plan.message_post(body=_("ESCALATION ALERT: Onboarding milestone delayed. Progress: %.2f%%.") % plan.progress_percentage)


class HrOnboardingTask(models.Model):
    _name = "hr.onboarding.task"
    _description = "Onboarding Task Progress Tracker"
    _order = "week_stage asc, id asc"

    onboarding_plan_id = fields.Many2one("hr.onboarding.plan", string="Onboarding Plan", ondelete="cascade", required=True)
    week_stage = fields.Selection([
        ("Week 1", "Week 1: Orientation & Setup"),
        ("Week 2", "Week 2: Systems & Tools"),
        ("Week 3", "Week 3: Work Unit Processes"),
        ("Week 4", "Week 4: Mid-Term Review"),
        ("Week 6", "Week 6: Advanced Walkthrough"),
        ("Week 8", "Week 8: Program Closure"),
    ], string="Stage", default="Week 1", required=True)
    name = fields.Char(string="Task Description", required=True)
    assigned_to_role = fields.Selection([
        ("new_hire", "New Hire"),
        ("buddy", "Onboarding Buddy"),
        ("supervisor", "Supervisor"),
    ], string="Assigned To", default="new_hire", required=True)
    state = fields.Selection([("todo", "To Do"), ("done", "Completed")], string="Status", default="todo", required=True)
    completed_date = fields.Datetime(string="Completed On", readonly=True)
    completed_by_user_id = fields.Many2one("res.users", string="Completed By", readonly=True)
    notes = fields.Text(string="Task Comments / Guidance Notes")

    def action_mark_done(self):
        for rec in self:
            rec.write({
                "state": "done",
                "completed_date": fields.Datetime.now(),
                "completed_by_user_id": self.env.uid,
            })


class HrOnboardingLmsTask(models.Model):
    _name = "hr.onboarding.lms.task"
    _description = "PPDD Induction & LMS Video Training Task"

    onboarding_plan_id = fields.Many2one("hr.onboarding.plan", string="Onboarding Plan", ondelete="cascade", required=True)
    name = fields.Char(string="Training / Video Title", required=True)
    training_type = fields.Selection([
        ("video", "Orientation Video"),
        ("policy", "Policy Review"),
        ("system", "System Training (Finacle/ERP)"),
        ("compliance", "Compliance Course"),
    ], string="Training Type", default="video", required=True)
    is_mandatory = fields.Boolean(string="Mandatory", default=True)
    state = fields.Selection([("pending", "Pending"), ("completed", "Completed")], string="Status", default="pending", required=True)
    completed_date = fields.Datetime(string="Completed On", readonly=True)

    def action_mark_completed(self):
        for rec in self:
            rec.write({
                "state": "completed",
                "completed_date": fields.Datetime.now(),
            })
