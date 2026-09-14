# -*- coding: utf-8 -*-

from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class HrInductionPlan(models.Model):
    _name = "hr.induction.plan"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Corporate Induction & PPDD Orientation Plan"
    _rec_name = "name"
    _order = "start_date desc"

    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    name = fields.Char(string="Induction Reference", copy=False, readonly=True, default=lambda self: _("New"))

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

    ppdd_coordinator_id = fields.Many2one("hr.employee", string="POMD Orientation Coordinator", tracking=True)
    scheduled_orientation_date = fields.Datetime(string="Scheduled Orientation Date",required=True, tracking=True)
    induction_completed_date = fields.Datetime(string="Induction Completed On", readonly=True)

    # ── LMS & Orientation Tasks ──────────────────────────────────────────────
    lms_task_ids = fields.One2many("hr.induction.lms.task", "induction_plan_id", string="POMD Orientation & LMS Trainings")
    total_lms_tasks = fields.Integer(string="Total Orientation Tasks", compute="_compute_lms_metrics", store=True)
    completed_lms_tasks = fields.Integer(string="Completed Tasks", compute="_compute_lms_metrics", store=True)
    lms_progress_percentage = fields.Float(string="Orientation Progress (%)", compute="_compute_lms_metrics", store=True, digits=(5, 2))

    # ── Segregation of Duties Audit Tracking ────────────────────────────────
    submitted_by_user_id = fields.Many2one("res.users", string="Submitted By User", readonly=True, copy=False)
    scheduled_by_user_id = fields.Many2one("res.users", string="Scheduled By User", readonly=True, copy=False)
    completed_by_user_id = fields.Many2one("res.users", string="Completed By User", readonly=True, copy=False)

    # ── Workflow State ────────────────────────────────────────────────────────
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("scheduled", "Orientation Scheduled"),
            ("in_progress", "LMS In-Progress"),
            ("completed", "Induction Completed"),
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

    @api.depends("lms_task_ids", "lms_task_ids.state")
    def _compute_lms_metrics(self):
        for rec in self:
            total = len(rec.lms_task_ids)
            completed = len(rec.lms_task_ids.filtered(lambda t: t.state == "completed"))
            rec.total_lms_tasks = total
            rec.completed_lms_tasks = completed
            rec.lms_progress_percentage = (completed / total * 100.0) if total > 0 else 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == _("New"):
                vals["name"] = self._get_next_reference()
            if not vals.get("submitted_by_user_id"):
                vals["submitted_by_user_id"] = self.env.user.id
        records = super().create(vals_list)
        for rec in records:
            rec._auto_generate_default_lms_tasks()
        return records

    @api.model
    def _get_fiscal_year_prefix(self):
        FISCAL_START_MONTH = 7
        FISCAL_START_DAY = 1
        today = fields.Date.context_today(self)
        start_year = today.year if (today.month, today.day) >= (FISCAL_START_MONTH, FISCAL_START_DAY) else today.year - 1
        end_year = start_year + 1
        return f"BB/IND/{str(start_year)[-2:]}-{str(end_year)[-2:]}/"

    @api.model
    def _get_next_reference(self):
        prefix = self._get_fiscal_year_prefix()
        self.env.cr.execute("""
            SELECT name FROM hr_induction_plan
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

    def _auto_generate_default_lms_tasks(self):
        self.ensure_one()
        if self.lms_task_ids:
            return
        start = self.start_date or fields.Date.context_today(self)
        templates = self.env["hr.induction.task.template"].search([])
        task_vals = []
        if templates:
            for tmpl in templates:
                due = start + timedelta(days=tmpl.days_offset) if tmpl.days_offset is not False else False
                task_vals.append({
                    "induction_plan_id": self.id,
                    "name": tmpl.name,
                    "training_type": tmpl.training_type,
                    "is_mandatory": tmpl.is_mandatory,
                    "due_date": due,
                    "state": "pending",
                })
        else:
            default_tasks = [
                ("Bunna Bank Culture, Vision & Core Values Orientation", "classroom", True, 1),
                ("PPDD HR Policies, Benefits & Code of Ethics", "document", True, 3),
                ("Information Security & Fraud Prevention Awareness", "lms_video", True, 5),
                ("Finacle Core Banking System Overview & Basics", "system_demo", True, 7),
                ("ERP Employee Self-Service (ESS) Training", "system_demo", True, 10),
            ]
            for name, ttype, is_mand, offset in default_tasks:
                due = start + timedelta(days=offset)
                task_vals.append({
                    "induction_plan_id": self.id,
                    "name": name,
                    "training_type": ttype,
                    "is_mandatory": is_mand,
                    "due_date": due,
                    "state": "pending",
                })
        if task_vals:
            self.env["hr.induction.lms.task"].create(task_vals)


    # -------------------------------------------------------------------------
    # Actions & Workflow with Segregation of Duties Enforcements
    # -------------------------------------------------------------------------
    def action_schedule_orientation(self):
        for rec in self:
            if rec.state != "draft":
                raise ValidationError(_("Orientation can only be scheduled from 'Draft' status."))
            if not rec.ppdd_coordinator_id:
                raise ValidationError(_(
                    "Prerequisite Missing: Please assign a 'PPDD Orientation Coordinator' before scheduling orientation."
                ))
            if not rec.scheduled_orientation_date:
                raise ValidationError(_(
                    "Prerequisite Missing: Please specify the 'Scheduled Orientation Date' before scheduling orientation."
                ))
            rec.write({
                "state": "scheduled",
                "scheduled_by_user_id": self.env.user.id,
            })
            rec.message_post(body=_("Corporate orientation scheduled for %s by %s.") % (rec.scheduled_orientation_date, self.env.user.name))

    def action_start_lms(self):
        for rec in self:
            if rec.state != "scheduled":
                raise ValidationError(_(
                    "Prerequisite Missing: Orientation session must be 'Scheduled' before starting LMS training (Current status: %s)."
                ) % rec.state)
            if not rec.lms_task_ids:
                raise ValidationError(_(
                    "Prerequisite Missing: No LMS or orientation tasks exist for this induction plan."
                ))
            rec.write({"state": "in_progress"})
            rec.message_post(body=_("LMS training and orientation in progress."))

    def action_mark_completed(self):
        current_user = self.env.user
        for rec in self:
            if rec.state != "in_progress":
                raise ValidationError(_(
                    "Corporate Induction can only be marked completed when it is 'LMS In-Progress' (Current status: %s)."
                ) % rec.state)

            # Segregation of Duties Check 1: Requesting employee cannot complete their own induction
            emp_user = rec.employee_id.sudo().user_id if rec.employee_id else False
            if emp_user and emp_user.id == current_user.id:
                raise ValidationError(_(
                    "Segregation of Duties Violation: You ('%s') are the new hire employee for this induction plan. "
                    "You are strictly prohibited from self-approving your corporate induction."
                ) % current_user.name)

            # Segregation of Duties Check 2: Initiator cannot be the sole completion approver
            if rec.submitted_by_user_id and rec.submitted_by_user_id.id == current_user.id and not self.env.su:
                raise ValidationError(_(
                    "Segregation of Duties Violation: You ('%s') created this corporate induction record. "
                    "To ensure segregation of duties, another PPDD Coordinator / HR Officer must verify and mark completion."
                ) % current_user.name)

            # Check mandatory LMS tasks
            uncompleted_mandatory = rec.lms_task_ids.filtered(lambda t: t.is_mandatory and t.state != "completed")
            if uncompleted_mandatory:
                raise ValidationError(_(
                    "Cannot mark Corporate Induction as completed! The following mandatory orientation tasks are incomplete:\n - %s"
                ) % "\n - ".join(uncompleted_mandatory.mapped("name")))

            rec.write({
                "state": "completed",
                "induction_completed_date": fields.Datetime.now(),
                "completed_by_user_id": current_user.id,
            })
            rec.message_post(
                body=_("Corporate Induction formally completed and signed off by PPDD/HR (%s).") % current_user.name
            )



class HrInductionLmsTask(models.Model):
    _name = "hr.induction.lms.task"
    _description = "Corporate Induction LMS & Orientation Task"
    _order = "due_date asc, id"

    induction_plan_id = fields.Many2one("hr.induction.plan", string="Induction Plan", required=True, ondelete="cascade")
    name = fields.Char(string="Task / Training Title", required=True)
    training_type = fields.Selection(
        [
            ("lms_video", "LMS Video Course"),
            ("document", "Policy Document"),
            ("classroom", "Classroom Orientation"),
            ("system_demo", "System Walkthrough"),
        ],
        string="Training Type", default="lms_video", required=True,
    )
    is_mandatory = fields.Boolean(string="Mandatory", default=True)
    due_date = fields.Date(string="Due Date")
    completed_date = fields.Datetime(string="Completed On", readonly=True)
    completed_by_user_id = fields.Many2one("res.users", string="Completed By", readonly=True, copy=False)
    state = fields.Selection([("pending", "Pending"), ("completed", "Completed")], string="Status", default="pending")
    notes = fields.Text(string="Notes / Remarks")

    is_overdue = fields.Boolean(
        string="Overdue", compute="_compute_is_overdue", store=False,
        help="True when the task is not yet completed and the due date has passed."
    )

    @api.depends("state", "due_date")
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_overdue = (
                rec.state == "pending"
                and bool(rec.due_date)
                and rec.due_date < today
            )

    def action_mark_completed(self):
        current_user = self.env.user
        for rec in self:
            if rec.induction_plan_id.state == "draft":
                raise ValidationError(_(
                    "Prerequisite Missing: Corporate Induction is still in 'Draft'. "
                    "Orientation must be scheduled and started before marking training modules completed."
                ))
            rec.write({
                "state": "completed",
                "completed_date": fields.Datetime.now(),
                "completed_by_user_id": current_user.id,
            })
            # ── Notify PPDD Coordinator & Buddy on task completion ─────────
            plan = rec.induction_plan_id
            partner_ids = []

            # Notify coordinator
            if plan.ppdd_coordinator_id and plan.ppdd_coordinator_id.user_id:
                partner_ids.append(plan.ppdd_coordinator_id.user_id.partner_id.id)

            # Notify supervisor
            if plan.supervisor_id and plan.supervisor_id.user_id:
                sup_partner = plan.supervisor_id.user_id.partner_id.id
                if sup_partner not in partner_ids:
                    partner_ids.append(sup_partner)

            body = _(
                "✅ Induction Task Completed\n"
                "Task: %s\n"
                "Type: %s\n"
                "Completed By: %s\n"
                "%s"
            ) % (
                rec.name,
                dict(rec._fields['training_type'].selection).get(rec.training_type, rec.training_type),
                current_user.name,
                ("Notes: " + rec.notes) if rec.notes else "",
            )

            plan.message_post(
                body=body,
                partner_ids=partner_ids,
                subtype_xmlid="mail.mt_comment",
            )

