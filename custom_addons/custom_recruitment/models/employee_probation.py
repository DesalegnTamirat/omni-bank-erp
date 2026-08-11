# -*- coding: utf-8 -*-

from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

NON_MANAGERIAL_DURATION = 60
MANAGERIAL_DURATION = 75
NOTIFICATION_DAYS_EARLY = 15
NOTIFICATION_DAYS_URGENT = 5
PASS_SCORE_THRESHOLD_PCT = 70.0


class HrEmployeeProbation(models.Model):
    _name = "hr.employee.probation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Employee Probation Management"
    _rec_name = "name"
    _order = "probation_end_date asc"

    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True

    name = fields.Char(string="Reference", copy=False, readonly=True, default=lambda self: _("New"))

    # -- Employee & Position Details (Bunna Bank Probationer Form Header) --
    employee_id = fields.Many2one("hr.employee", string="Name of Probationer", required=True, tracking=True)
    job_position_id = fields.Many2one(
        "hr.job", string="Position Title", compute="_compute_from_employee", store=True, readonly=True
    )
    operating_unit_id = fields.Many2one(
        "operating.unit", string="Place of Assignment", compute="_compute_from_employee", store=True, readonly=True
    )
    department_id = fields.Many2one(
        "hr.department", string="Department", related="employee_id.department_id", store=True, readonly=True
    )
    supervisor_id = fields.Many2one("hr.employee", string="Immediate Supervisor / Evaluator", tracking=True)
    evaluator_name = fields.Char(string="Name of Evaluator", related="supervisor_id.name", readonly=True)
    evaluator_position = fields.Char(string="Evaluator Position", compute="_compute_evaluator_position", store=True)

    source_recruitment = fields.Selection(
        [("internal", "Internal Recruitment"), ("external", "External Recruitment")],
        string="Recruitment Source", default="external",
    )
    recruitment_reference = fields.Char(string="Recruitment Reference")

    # -- Duration & Category --
    employee_category = fields.Selection(
        [("Managerial", "Managerial"), ("Non Managerial", "Non Managerial")],
        string="Employee Category", required=True, default="Non Managerial", tracking=True,
        help="Drives statutory probation duration: 60 days for Non-Managerial, 75 days for Managerial.",
    )
    probation_start_date = fields.Date(string="Employment / Start Date", required=True, default=fields.Date.context_today)
    duration_days = fields.Integer(
        string="Probation Duration (Days)", compute="_compute_duration_days", store=True, readonly=True,
    )
    probation_end_date = fields.Date(
        string="Probation End Date", compute="_compute_probation_end_date", store=True, readonly=True,
    )

    # -- Extension --
    is_extended = fields.Boolean(string="Probation Extended", default=False, readonly=True, copy=False)
    extension_days = fields.Integer(string="Extension Days", default=0, copy=False)
    extension_reason = fields.Text(string="Extension Reason", copy=False)

    # -- Notifications --
    notification_sent = fields.Boolean(string="Supervisor Notified", default=False, readonly=True, copy=False)
    notification_date = fields.Datetime(string="Notification Sent On", readonly=True, copy=False)

    # -- Performance Scoring (Bunna Bank Evaluation Table) --
    criteria_line_ids = fields.One2many(
        "hr.employee.probation.criteria.line", "probation_id", string="Evaluation Criteria"
    )
    total_score = fields.Float(string="Total Score", compute="_compute_scores", store=True)
    max_possible_score = fields.Float(string="Max Possible Score", compute="_compute_scores", store=True)
    percentage_score = fields.Float(string="Evaluation Result Out of 100", compute="_compute_scores", store=True, digits=(5, 2))
    is_pass_score = fields.Boolean(string="Meets Passing Threshold (70%)", compute="_compute_scores", store=True)

    # -- Recommendation & Observation (Form Footer) --
    recommend_permanent = fields.Selection(
        [
            ("yes", "Yes - Recommend for Permanent Employment"),
            ("no", "No - Do Not Recommend for Permanent Employment"),
        ],
        string="Recommend for Permanent Employment?", tracking=True,
    )

    # -- Committee / Delegation --
    delegation_team_ids = fields.One2many(
        "hr.employee.probation.delegation.team", "probation_id", string="Delegation Committee"
    )
    committee_evaluated = fields.Boolean(string="Committee Evaluated", default=False, readonly=True, copy=False)
    in_charge_id = fields.Many2one("hr.employee", string="TDD In-Charge Officer")

    # -- Outcome & State --
    outcome = fields.Selection(
        [
            ("pending", "Pending"),
            ("satisfactory", "Satisfactory (Permanency Confirmation)"),
            ("extended", "Probation Extended"),
            ("unsatisfactory", "Unsatisfactory (Contract Termination)"),
            ("discipline", "Discipline Issue (Route to Legal/Discipline)"),
        ],
        string="Outcome", default="pending", required=True, tracking=True,
    )
    outcome_date = fields.Date(string="Outcome Recorded On", readonly=True, copy=False)
    outcome_notes = fields.Text(string="Comments & Observations")

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("in_progress", "In Progress"),
            ("notified", "Supervisor Notified"),
            ("evaluated", "Evaluated"),
            ("completed", "Completed / Permanency Confirmed"),
            ("extended", "Extended"),
            ("terminated", "Contract Terminated"),
        ],
        string="Status", default="draft", tracking=True, copy=False,
    )

    # -------------------------------------------------------------------------
    # Sequence & Reference Generation
    # -------------------------------------------------------------------------
    @api.model
    def _get_fiscal_year_prefix(self):
        """Computes the current fiscal-year prefix (July–June cycle)."""
        FISCAL_START_MONTH = 7
        FISCAL_START_DAY = 1
        today = fields.Date.context_today(self)
        start_year = today.year if (today.month, today.day) >= (FISCAL_START_MONTH, FISCAL_START_DAY) else today.year - 1
        end_year = start_year + 1
        return f"BB/PROB/{str(start_year)[-2:]}-{str(end_year)[-2:]}/"

    @api.model
    def _get_next_reference(self):
        prefix = self._get_fiscal_year_prefix()
        self.env.cr.execute("""
            SELECT name FROM hr_employee_probation
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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == _("New"):
                vals["name"] = self._get_next_reference()
        records = super().create(vals_list)
        for rec in records:
            if not rec.criteria_line_ids:
                rec.action_populate_criteria()
        return records

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

    @api.depends("supervisor_id", "supervisor_id.job_id")
    def _compute_evaluator_position(self):
        for rec in self:
            if rec.supervisor_id:
                rec.evaluator_position = getattr(rec.supervisor_id, 'job_title', False) or (
                    rec.supervisor_id.job_id.name if rec.supervisor_id.job_id else ""
                )
            else:
                rec.evaluator_position = ""

    @api.depends("employee_category")
    def _compute_duration_days(self):
        for rec in self:
            rec.duration_days = (
                MANAGERIAL_DURATION if rec.employee_category == "Managerial" else NON_MANAGERIAL_DURATION
            )

    @api.depends("probation_start_date", "duration_days", "extension_days")
    def _compute_probation_end_date(self):
        for rec in self:
            if rec.probation_start_date and rec.duration_days:
                total_days = rec.duration_days + (rec.extension_days or 0)
                rec.probation_end_date = rec.probation_start_date + timedelta(days=total_days)
            else:
                rec.probation_end_date = False

    @api.depends("criteria_line_ids.score", "criteria_line_ids.coefficient")
    def _compute_scores(self):
        for rec in self:
            total = sum(line.score for line in rec.criteria_line_ids)
            max_score = sum(5 * line.coefficient for line in rec.criteria_line_ids if line.coefficient)
            pct = (total / max_score * 100.0) if max_score > 0 else 0.0
            rec.total_score = total
            rec.max_possible_score = max_score
            rec.percentage_score = pct
            rec.is_pass_score = pct >= PASS_SCORE_THRESHOLD_PCT

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        for rec in self:
            if rec.employee_id:
                job = getattr(rec.employee_id, 'job_id', False) or getattr(rec.employee_id, 'job_position', False)
                if job and hasattr(job, 'employee_category') and job.employee_category:
                    rec.employee_category = job.employee_category
                if getattr(rec.employee_id, 'parent_id', False):
                    rec.supervisor_id = rec.employee_id.parent_id

    # -------------------------------------------------------------------------
    # Actions & Workflow
    # -------------------------------------------------------------------------
    def action_populate_criteria(self):
        """Populate evaluation criteria from master data (emp.probation.criteria)."""
        CriteriaMaster = self.env["emp.probation.criteria"]
        all_criteria = CriteriaMaster.search([], order="id asc")
        for rec in self:
            existing_criteria = rec.criteria_line_ids.mapped("criteria_id")
            to_add = all_criteria - existing_criteria
            lines = [(0, 0, {
                "criteria_id": c.id,
                "coefficient": c.coefficient or 1,
                "rating": "3",
            }) for c in to_add]
            if lines:
                rec.write({"criteria_line_ids": lines})

    def action_start(self):
        for rec in self:
            if not rec.probation_start_date:
                raise ValidationError(_("Please set the Probation Start Date before starting probation."))
            if not rec.criteria_line_ids:
                rec.action_populate_criteria()
            rec.state = "in_progress"
            rec.message_post(body=_("Probation started for %s.") % rec.employee_id.name)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Probation Started'),
                'message': _('Probation period is now In Progress.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},

            },
        }

    def _notify_supervisor(self, body):
        self.ensure_one()
        if self.supervisor_id and self.supervisor_id.user_id and self.supervisor_id.user_id.partner_id:
            partner = self.supervisor_id.user_id.partner_id
            channel = self.env["discuss.channel"]._get_or_create_chat(partners_to=[partner.id])
            channel.message_post(body=body, message_type="comment", subtype_xmlid="mail.mt_comment")

    def action_notify_supervisor(self):
        for rec in self:
            if rec.notification_sent:
                continue
            body = _(
                "Dear %(supervisor)s,<br/><br/>"
                "This is a reminder that the probation period of <b>%(employee)s</b> "
                "(%(position)s) is due to end on <b>%(end_date)s</b>.<br/>"
                "Please complete the Performance Evaluation Criteria Form (Bunna Bank S.C.) and record the outcome "
                "(Satisfactory / Unsatisfactory / Extension) before that date.<br/><br/>Thank you."
            ) % {
                "supervisor": rec.supervisor_id.name if rec.supervisor_id else _("Supervisor"),
                "employee": rec.employee_id.name,
                "position": rec.job_position_id.name if rec.job_position_id else "",
                "end_date": rec.probation_end_date,
            }
            rec._notify_supervisor(body)
            rec.message_post(body=_("Supervisor notified of upcoming probation end date."))
            rec.write({
                "notification_sent": True,
                "notification_date": fields.Datetime.now(),
                "state": "notified",
            })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Supervisor Notified'),
                'message': _('Supervisor has been notified successfully.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},

            },
        }

    @api.model
    def _cron_notify_upcoming_probation_end(self):
        target_date = fields.Date.context_today(self) + timedelta(days=NOTIFICATION_DAYS_URGENT)
        records = self.search([
            ("state", "in", ["draft", "in_progress"]),
            ("notification_sent", "=", False),
            ("outcome", "=", "pending"),
            ("probation_end_date", "<=", target_date),
        ])
        records.action_notify_supervisor()

    def action_committee_evaluate(self):
        """Committee evaluation voting mechanism."""
        for rec in self:
            if not rec.delegation_team_ids:
                raise UserError(_("No delegation committee assigned for evaluation."))
            current_user = self.env.user
            found = False
            for member in rec.delegation_team_ids:
                if member.status == "unavailable":
                    if member.alternate_committee_member == current_user:
                        member.approve = True
                        found = True
                        break
                elif member.employee_name == current_user:
                    member.approve = True
                    found = True
                    break
            if not found:
                raise UserError(_("You are not assigned as an active or alternate committee member for this probation."))

            all_approved = all(m.approve for m in rec.delegation_team_ids)
            if all_approved:
                rec.write({"committee_evaluated": True, "state": "evaluated"})
                rec.message_post(body=_("Committee evaluation complete. All members have approved."))
            else:
                rec.message_post(body=_("Committee vote registered by %s.") % current_user.name)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Committee Vote Registered'),
                'message': _('Evaluation vote saved successfully.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},

            },
        }

    def action_extend_probation(self):
        for rec in self:
            if rec.extension_days <= 0:
                raise UserError(_("Please specify the number of extension days (e.g. 30 days)."))
            if not rec.extension_reason:
                raise UserError(_("Please provide a business justification for the probation extension."))
            rec.write({
                "is_extended": True,
                "outcome": "extended",
                "state": "extended",
                "notification_sent": False,
            })
            rec.message_post(body=_(
                "Probation extended by %d days. Reason: %s. New end date: %s"
            ) % (rec.extension_days, rec.extension_reason, rec.probation_end_date))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Probation Extended'),
                'message': _('Probation period extended.'),
                'type': 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_record_outcome(self):
        """Record final probation outcome and execute HR contract updates."""
        for rec in self:
            if rec.outcome == "pending":
                raise UserError(_("Please select an Outcome (Satisfactory, Unsatisfactory, Extended, or Discipline Issue)."))

            today = fields.Date.context_today(self)
            rec.write({
                "outcome_date": today,
            })

            if rec.outcome == "satisfactory":
                rec.state = "completed"
                rec.recommend_permanent = "yes"
                if "hr.version" in self.env:
                    contracts = self.env["hr.version"].search([("employee_id", "=", rec.employee_id.id)])
                    if contracts:
                        contracts.write({"approval_status": "approved", "state": "open"})
                if hasattr(rec.employee_id, "employee_type"):
                    sel_keys = [k for k, _ in rec.employee_id._fields["employee_type"]._description_selection(self.env)]
                    target_key = "employee" if "employee" in sel_keys else ("permanent" if "permanent" in sel_keys else False)
                    if target_key:
                        rec.employee_id.write({"employee_type": target_key})
                rec.message_post(body=_("Probation completed successfully. Employee confirmed as permanent."))

            elif rec.outcome == "unsatisfactory":
                rec.state = "terminated"
                rec.recommend_permanent = "no"
                if "hr.version" in self.env:
                    contracts = self.env["hr.version"].search([("employee_id", "=", rec.employee_id.id)])
                    if contracts:
                        contracts.write({"state": "cancel"})
                rec.message_post(body=_("Probation completed: Unsatisfactory outcome. Contract terminated."))

            elif rec.outcome == "extended":
                rec.action_extend_probation()

            elif rec.outcome == "discipline":
                rec.state = "completed"
                rec.message_post(body=_("Probation outcome recorded as Discipline Issue. Routed for HR/Legal action."))

        outcome_label = dict(self[:1]._fields["outcome"].selection).get(self[:1].outcome, self[:1].outcome)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Outcome Recorded'),
                'message': _('Probation outcome recorded: %s.') % outcome_label,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }


class HrEmployeeProbationCriteriaLine(models.Model):
    _name = "hr.employee.probation.criteria.line"
    _description = "Employee Probation Criteria Line"

    probation_id = fields.Many2one("hr.employee.probation", string="Probation", ondelete="cascade", required=True)
    criteria_id = fields.Many2one("emp.probation.criteria", string="Evaluation Criteria", required=True)
    criteria_name = fields.Char(string="Criteria Name", related="criteria_id.emp_evaluation_criteria", readonly=True)
    description = fields.Text(string="Guideline Question / Scope", related="criteria_id.description", readonly=True)
    rating = fields.Selection([
        ("1", "1"),
        ("2", "2"),
        ("3", "3"),
        ("4", "4"),
        ("5", "5"),
    ], string="Rating (1-5)", default="3", required=True)
    coefficient = fields.Integer(string="Coefficient", related="criteria_id.coefficient", store=True, readonly=True)
    score = fields.Integer(string="Score", compute="_compute_score", store=True)

    @api.depends("rating", "coefficient")
    def _compute_score(self):
        for rec in self:
            if rec.rating and rec.coefficient:
                rec.score = int(rec.rating) * rec.coefficient
            else:
                rec.score = 0


class HrEmployeeProbationDelegationTeam(models.Model):
    _name = "hr.employee.probation.delegation.team"
    _description = "Employee Probation Delegation Team Member"

    probation_id = fields.Many2one("hr.employee.probation", string="Probation", ondelete="cascade", required=True)
    role = fields.Selection([
        ("chair_person", "Chair Person"),
        ("member", "Member"),
        ("secretary", "Secretary"),
        ("member_secretary", "Member & Secretary"),
    ], string="Role", default="member", required=True)
    employee_name = fields.Many2one("res.users", string="Committee Member", required=True)
    operating_unit = fields.Char(
        string="Work Unit", related="employee_name.employee_id.default_operating_unit_id.name", readonly=True
    )
    status = fields.Selection([
        ("active", "Active"), ("unavailable", "Unavailable")
    ], string="Status", default="active")
    alternate_committee_member = fields.Many2one("res.users", string="Alternate Approver")
    alter_operating_unit = fields.Char(
        string="Alt Work Unit", related="alternate_committee_member.employee_id.default_operating_unit_id.name", readonly=True
    )
    approve = fields.Boolean(string="Approved", default=False, readonly=True)
