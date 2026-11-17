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
    eligible_employee_ids = fields.Many2many(
        "hr.employee",
        compute="_compute_eligible_employee_ids",
        compute_sudo=True,
        string="Eligible Employees for Induction",
    )
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
    def _compute_eligible_employee_ids(self):
        """Fetches only employees who have not been registered in Corporate Induction yet."""
        user = self.env.user
        is_officer_or_admin = (
            user.id == 1
            or user.has_group("custom_onboarding_induction.group_onboarding_induction_officer")
            or user.has_group("custom_onboarding_induction.group_onboarding_induction_manager")
            or user.has_group("base.group_system")
        )
        if not is_officer_or_admin:
            for rec in self:
                rec.eligible_employee_ids = rec.employee_id or self.env["hr.employee"]
            return

        registered_emp_ids = set(
            self.env["hr.induction.plan"].sudo().search([("active", "=", True)]).mapped("employee_id.id")
        )
        for rec in self.sudo():
            current_id = rec.employee_id.id if rec.employee_id else False
            excluded = registered_emp_ids - ({current_id} if current_id else set())
            domain = [("id", "not in", list(excluded))]
            rec.eligible_employee_ids = self.env["hr.employee"].sudo().search(domain)

    @api.constrains("employee_id")
    def _check_unique_induction_employee(self):
        for rec in self:
            if rec.employee_id:
                duplicate = self.search([
                    ("id", "!=", rec.id),
                    ("employee_id", "=", rec.employee_id.id),
                    ("active", "=", True),
                ], limit=1)
                if duplicate:
                    raise ValidationError(_(
                        "Duplicate Registration Error!\n\n"
                        "Employee '%s' has already been registered in Corporate Induction Plan '%s'.\n"
                        "Each employee can only have one Corporate Induction Plan."
                    ) % (rec.employee_id.name, duplicate.name))

    @api.onchange("employee_id")
    def _onchange_employee_check_registered(self):
        if self.employee_id:
            duplicate = self.search([
                ("id", "!=", self._origin.id if hasattr(self, "_origin") else False),
                ("employee_id", "=", self.employee_id.id),
                ("active", "=", True),
            ], limit=1)
            if duplicate:
                name = self.employee_id.name
                self.employee_id = False
                return {
                    "warning": {
                        "title": _("Employee Already Registered"),
                        "message": _(
                            "Employee '%s' has already been registered in Corporate Induction Plan '%s'.\n\n"
                            "Please select an employee who has not registered yet."
                        ) % (name, duplicate.name)
                    }
                }
            # Auto-populate configured LMS task lines interactively on screen
            valid_tasks = self.lms_task_ids.filtered(lambda t: bool(t.name and t.name.strip()))
            if not valid_tasks:
                start = self.start_date or fields.Date.context_today(self)
                emp_category = "Non Managerial"
                probation = self.env["hr.employee.probation"].sudo().search([
                    ("employee_id", "=", self.employee_id.id),
                    ("active", "=", True),
                ], order="id desc", limit=1)
                if probation and probation.employee_category:
                    emp_category = probation.employee_category

                templates = self.env["hr.induction.task.template"].search([
                    ("active", "=", True),
                    ("employee_category", "in", ["all", emp_category]),
                ])
                emp_dept_id = self.employee_id.department_id.id if self.employee_id.department_id else False
                if emp_dept_id:
                    templates = templates.filtered(lambda t: not t.department_ids or emp_dept_id in t.department_ids.ids)
                else:
                    templates = templates.filtered(lambda t: not t.department_ids)

                lines = []
                if templates:
                    for tmpl in templates:
                        due = start + timedelta(days=tmpl.days_offset) if tmpl.days_offset is not False else False
                        lines.append((0, 0, {
                            "template_id": tmpl.id,
                            "name": tmpl.name,
                            "training_type": tmpl.training_type,
                            "is_mandatory": tmpl.is_mandatory,
                            "due_date": due,
                            "state": "pending",
                        }))
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
                        tmpl_rec = self.env["hr.induction.task.template"].search([("name", "=ilike", name.strip())], limit=1)
                        lines.append((0, 0, {
                            "template_id": tmpl_rec.id if tmpl_rec else False,
                            "name": name,
                            "training_type": ttype,
                            "is_mandatory": is_mand,
                            "due_date": due,
                            "state": "pending",
                        }))
                if lines:
                    self.lms_task_ids = lines

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

    # ── Scheduled Orientation Date & Anti-Backdating Validations ──────
    @api.constrains('scheduled_orientation_date', 'start_date', 'state')
    def _check_scheduled_orientation_date_no_backdate(self):
        """
        Enforces strict anti-backdating business rules:
        1. Scheduled Orientation Date cannot be earlier than today in draft/scheduled status.
        2. Scheduled Orientation Date cannot be earlier than the employee's Expected Start Date.
        """
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.scheduled_orientation_date and rec.state in ('draft', 'scheduled'):
                scheduled_local_dt = fields.Datetime.context_timestamp(self, rec.scheduled_orientation_date)
                scheduled_date = scheduled_local_dt.date()

                if scheduled_date < today:
                    raise ValidationError(_(
                        "Validation Error: Backdating Not Allowed!\n\n"
                        "The Scheduled Orientation Date (%s) cannot be backdated to a past date.\n"
                        "Today is %s. Please select today or a future date for the corporate orientation."
                    ) % (
                        scheduled_local_dt.strftime('%B %d, %Y %I:%M %p'),
                        today.strftime('%B %d, %Y')
                    ))

                if rec.start_date and scheduled_date < rec.start_date:
                    raise ValidationError(_(
                        "Validation Error: Inconsistent Orientation Schedule!\n\n"
                        "The Scheduled Orientation Date (%s) cannot be earlier than the employee's Expected Start Date (%s)."
                    ) % (
                        scheduled_local_dt.strftime('%B %d, %Y %I:%M %p'),
                        rec.start_date.strftime('%B %d, %Y')
                    ))

    @api.onchange('scheduled_orientation_date')
    def _onchange_scheduled_orientation_date(self):
        """Instant interactive UI feedback when user selects a backdated date in the datepicker."""
        if self.scheduled_orientation_date and self.state in ('draft', 'scheduled'):
            today = fields.Date.context_today(self)
            scheduled_local_dt = fields.Datetime.context_timestamp(self, self.scheduled_orientation_date)
            scheduled_date = scheduled_local_dt.date()

            if scheduled_date < today:
                invalid_str = scheduled_local_dt.strftime('%B %d, %Y %I:%M %p')
                self.scheduled_orientation_date = False
                return {
                    'warning': {
                        'title': _("Backdating Not Allowed"),
                        'message': _(
                            "The Scheduled Orientation Date (%s) cannot be backdated to a past date.\n\n"
                            "Today is %s. Please select today or a future date."
                        ) % (invalid_str, today.strftime('%B %d, %Y'))
                    }
                }

            if self.start_date and scheduled_date < self.start_date:
                invalid_str = scheduled_local_dt.strftime('%B %d, %Y %I:%M %p')
                self.scheduled_orientation_date = False
                return {
                    'warning': {
                        'title': _("Inconsistent Orientation Schedule"),
                        'message': _(
                            "The Scheduled Orientation Date (%s) cannot be earlier than the employee's Expected Start Date (%s)."
                        ) % (invalid_str, self.start_date.strftime('%B %d, %Y'))
                    }
                }


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

    def action_load_default_lms_tasks(self):
        """Allow user to auto-load or reload configured orientation tasks from templates."""
        for rec in self:
            rec._auto_generate_default_lms_tasks(force=True)

    def _auto_generate_default_lms_tasks(self, force=False):
        self.ensure_one()
        if self.lms_task_ids and not force:
            valid_tasks = self.lms_task_ids.filtered(lambda t: bool(t.name and t.name.strip()))
            if valid_tasks:
                return
            self.lms_task_ids.unlink()
        elif force and self.lms_task_ids:
            self.lms_task_ids.unlink()

        start = self.start_date or fields.Date.context_today(self)

        # Check linked probation or employee to determine category
        emp_category = "Non Managerial"
        if self.employee_id:
            probation = self.env["hr.employee.probation"].sudo().search([
                ("employee_id", "=", self.employee_id.id),
                ("active", "=", True),
            ], order="id desc", limit=1)
            if probation and probation.employee_category:
                emp_category = probation.employee_category

        # Role & Grade specific template search (FR-OB-005)
        templates = self.env["hr.induction.task.template"].search([
            ("active", "=", True),
            ("employee_category", "in", ["all", emp_category]),
        ])
        emp_dept_id = self.employee_id.department_id.id if self.employee_id and self.employee_id.department_id else False
        if emp_dept_id:
            templates = templates.filtered(lambda t: not t.department_ids or emp_dept_id in t.department_ids.ids)
        else:
            templates = templates.filtered(lambda t: not t.department_ids)

        task_vals = []
        if templates:
            for tmpl in templates:
                due = start + timedelta(days=tmpl.days_offset) if tmpl.days_offset is not False else False
                task_vals.append({
                    "induction_plan_id": self.id,
                    "template_id": tmpl.id,
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
                tmpl_rec = self.env["hr.induction.task.template"].search([("name", "=ilike", name.strip())], limit=1)
                task_vals.append({
                    "induction_plan_id": self.id,
                    "template_id": tmpl_rec.id if tmpl_rec else False,
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
        today = fields.Date.context_today(self)
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
            
            # Prevent backdating
            scheduled_local_dt = fields.Datetime.context_timestamp(self, rec.scheduled_orientation_date)
            scheduled_date = scheduled_local_dt.date()
            if scheduled_date < today:
                raise ValidationError(_(
                    "Validation Error: Backdating Not Allowed!\n\n"
                    "The Scheduled Orientation Date (%s) cannot be backdated to a past date.\n"
                    "Today is %s. Please select today or a future date before scheduling orientation."
                ) % (
                    scheduled_local_dt.strftime('%B %d, %Y %I:%M %p'),
                    today.strftime('%B %d, %Y')
                ))

            if rec.start_date and scheduled_date < rec.start_date:
                raise ValidationError(_(
                    "Validation Error: Inconsistent Orientation Schedule!\n\n"
                    "The Scheduled Orientation Date (%s) cannot be earlier than the employee's Expected Start Date (%s)."
                ) % (
                    scheduled_local_dt.strftime('%B %d, %Y %I:%M %p'),
                    rec.start_date.strftime('%B %d, %Y')
                ))

            rec.write({
                "state": "scheduled",
                "scheduled_by_user_id": self.env.user.id,
            })
            rec.message_post(body=_("Corporate orientation scheduled for %s by %s.") % (
                scheduled_local_dt.strftime('%B %d, %Y %I:%M %p'), self.env.user.name
            ))

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
    template_id = fields.Many2one(
        "hr.induction.task.template",
        string="Orientation / LMS Training Module",
        domain=[("active", "=", True)],
        ondelete="restrict",
        help="Select strictly from configured Induction Task Templates.",
    )
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
    is_officer_or_admin = fields.Boolean(
        string="Is HR Officer or Administrator",
        compute="_compute_is_officer_or_admin",
        store=False,
    )
    notes = fields.Text(string="Notes / Remarks")

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

    @api.onchange("template_id")
    def _onchange_template_id(self):
        if self.template_id:
            tmpl = self.template_id
            self.name = tmpl.name
            self.training_type = tmpl.training_type
            self.is_mandatory = tmpl.is_mandatory
            plan = self.induction_plan_id
            start = (plan.start_date or (plan.employee_id and plan.employee_id.first_contract_date)) if plan else False
            if not start:
                start = fields.Date.context_today(self)
            self.due_date = start + timedelta(days=tmpl.days_offset) if tmpl.days_offset is not False else False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("template_id"):
                tmpl = self.env["hr.induction.task.template"].browse(vals["template_id"])
                if tmpl.exists():
                    if not vals.get("name"):
                        vals["name"] = tmpl.name
                    if "training_type" not in vals:
                        vals["training_type"] = tmpl.training_type
                    if "is_mandatory" not in vals:
                        vals["is_mandatory"] = tmpl.is_mandatory
            elif vals.get("name") and not vals.get("template_id"):
                tmpl = self.env["hr.induction.task.template"].search([
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
                    tmpl = self.env["hr.induction.task.template"].search([
                        ("name", "=ilike", rec.name.strip())
                    ], limit=1)
                    if tmpl:
                        rec.template_id = tmpl.id
                        continue
                raise ValidationError(_(
                    "Invalid Orientation Task Error!\n\n"
                    "You cannot enter arbitrary text '%s'.\n\n"
                    "Every orientation training line MUST be selected from the pre-configured Induction Task Templates."
                ) % (rec.name or ""))

    @api.constrains("induction_plan_id", "template_id")
    def _check_unique_template_per_plan(self):
        for rec in self:
            if rec.template_id and rec.induction_plan_id:
                dups = self.search([
                    ("id", "!=", rec.id),
                    ("induction_plan_id", "=", rec.induction_plan_id.id),
                    ("template_id", "=", rec.template_id.id),
                ], limit=1)
                if dups:
                    raise ValidationError(_(
                        "Duplicate Training Module Error!\n\n"
                        "The module '%s' is already assigned to this Corporate Induction Plan."
                    ) % rec.template_id.name)

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

    def write(self, vals):
        user = self.env.user
        config_fields = set(vals.keys()) - {"state", "completed_date", "completed_by_user_id", "notes"}
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
                    "Access Denied: Read-Only Induction Task!\n\n"
                    "Orientation tasks are strictly read-only for employees.\n"
                    "Only HR Officers and Administrators can modify induction task details."
                ))

        if vals.get("state") == "completed":
            today = fields.Date.context_today(self)
            for rec in self:
                target_due = vals.get("due_date") and fields.Date.to_date(vals["due_date"]) or rec.due_date
                if target_due and today < target_due:
                    raise ValidationError(_(
                        "Premature Induction Task Completion Error!\n\n"
                        "Orientation task '%s' cannot be marked as Completed before its scheduled due date.\n\n"
                        "• Today's Date: %s\n"
                        "• Scheduled Due Date: %s\n\n"
                        "This task can only be completed on or after %s."
                    ) % (
                        rec.name,
                        today.strftime("%b %d, %Y"),
                        target_due.strftime("%b %d, %Y"),
                        target_due.strftime("%b %d, %Y"),
                    ))

                # ── Chronological Pre-Order Validation: Older scheduled modules must be completed first ──
                if target_due and rec.induction_plan_id:
                    pending_prior = rec.induction_plan_id.task_ids.filtered(
                        lambda t: t.id != rec.id and t.state != "completed" and t.due_date and t.due_date < target_due
                    )
                    if pending_prior:
                        earlier_task = pending_prior.sorted(key=lambda t: (t.due_date, t.id))[0]
                        raise ValidationError(_(
                            "Chronological Induction Task Completion Error!\n\n"
                            "Orientation modules must be completed in order of their scheduled dates. "
                            "A module with a later date cannot be completed while older scheduled modules are still pending.\n\n"
                            "• Current Module: '%s' (Due Date: %s)\n"
                            "• Older Pending Module: '%s' (Due Date: %s)\n\n"
                            "Please complete '%s' first before completing this module."
                        ) % (
                            rec.name,
                            target_due.strftime("%b %d, %Y"),
                            earlier_task.name,
                            earlier_task.due_date.strftime("%b %d, %Y"),
                            earlier_task.name,
                        ))
        return super().write(vals)

    def action_mark_completed(self):
        current_user = self.env.user
        today = fields.Date.context_today(self)
        for rec in self:
            rec_sudo = rec.sudo()
            plan = rec_sudo.induction_plan_id
            if plan and plan.state == "draft":
                raise ValidationError(_(
                    "Prerequisite Missing: Corporate Induction is still in 'Draft'. "
                    "Orientation must be scheduled and started before marking training modules completed."
                ))
            if rec.due_date and today < rec.due_date:
                raise ValidationError(_(
                    "Premature Induction Task Completion Error!\n\n"
                    "Orientation task '%s' cannot be marked as Completed before its scheduled due date.\n\n"
                    "• Today's Date: %s\n"
                    "• Scheduled Due Date: %s\n\n"
                    "This task can only be completed on or after %s."
                ) % (rec.name, today.strftime("%b %d, %Y"), rec.due_date.strftime("%b %d, %Y"), rec.due_date.strftime("%b %d, %Y")))

            # ── Chronological Pre-Order Validation: Older scheduled modules must be completed first ──
            if rec.due_date and plan:
                pending_prior = plan.task_ids.filtered(
                    lambda t: t.id != rec.id and t.state != "completed" and t.due_date and t.due_date < rec.due_date
                )
                if pending_prior:
                    earlier_task = pending_prior.sorted(key=lambda t: (t.due_date, t.id))[0]
                    raise ValidationError(_(
                        "Chronological Induction Task Completion Error!\n\n"
                        "Orientation modules must be completed in order of their scheduled dates. "
                        "A module with a later date cannot be completed while older scheduled modules are still pending.\n\n"
                        "• Current Module: '%s' (Due Date: %s)\n"
                        "• Older Pending Module: '%s' (Due Date: %s)\n\n"
                        "Please complete '%s' first before completing this module."
                    ) % (
                        rec.name,
                        rec.due_date.strftime("%b %d, %Y"),
                        earlier_task.name,
                        earlier_task.due_date.strftime("%b %d, %Y"),
                        earlier_task.name,
                    ))

            rec_sudo.write({
                "state": "completed",
                "completed_date": fields.Datetime.now(),
                "completed_by_user_id": current_user.id,
            })
            # ── Notify PPDD Coordinator & Buddy on task completion ─────────
            partner_ids = []

            # Notify coordinator
            if plan and plan.ppdd_coordinator_id and plan.ppdd_coordinator_id.user_id:
                partner_ids.append(plan.ppdd_coordinator_id.user_id.partner_id.id)

            # Notify supervisor
            if plan and plan.supervisor_id and plan.supervisor_id.user_id:
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

            if plan:
                plan.sudo().message_post(
                    body=body,
                    partner_ids=partner_ids,
                    subtype_xmlid="mail.mt_comment",
                )

