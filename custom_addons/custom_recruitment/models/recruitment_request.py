# -*- coding: utf-8 -*-

from datetime import timedelta

from xlwt.ExcelFormulaLexer import false_pattern

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class RecruitmentRequest(models.Model):
    _name = "recruitment.request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Recruitment Request"
    _rec_name = "reference"
    _order = "request_date desc"

    def _default_operating_unit_id(self):
        return self.env.user.default_operating_unit_id.id or False

    def _default_department_id(self):
        employee = self.env["hr.employee"].search([
            ("user_id", "=", self.env.user.id),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        return employee.department_id.id if employee else False

    def _default_workforce_plan_id(self):
        unit_id = self._default_operating_unit_id()
        if not unit_id:
            return False
        plans = self.env["planning.work.unit.manpower"].search([
            ("work_unit_id", "=", unit_id),
            ("state", "=", "approved"),
            ("del_flg", "=", "N"),
        ])
        return plans.id if len(plans) == 1 else False

    # -- Reference --------------------------------------------------------
    reference = fields.Char(
        string="Request Number", copy=False, readonly=True,
        default=lambda self: _("New")
    )

    # -- : Classification ---------------------------------------------
    request_type = fields.Selection(
        [("planned", "Planned"), ("unplanned", "Unplanned")],
        string="Request Type", required=True, default="planned", tracking=True,
        help=": Planned requests must link to an approved workforce plan."
    )

    # -- : Basic request info -----------------------------------------
    request_date = fields.Date(
        string="Request Date", default=fields.Date.context_today, required=True
    )
    requested_by = fields.Many2one(
        "hr.employee", string="Requested By",
        default=lambda self: self.env["hr.employee"].search([
            ("user_id", "=", self.env.user.id),
            ("company_id", "=", self.env.company.id),
        ], limit=1),
        required=True, tracking=True, readonly= True,
    help="Defaults to the currently logged-in user's employee record "
             "and is read-only in Draft, so a request can't be filed on "
             "behalf of someone else."
    )
    operating_unit_id = fields.Many2one(
        "operating.unit", string="Work Unit", required=True, tracking=True,
        default=lambda self: self._default_operating_unit_id(),readonly= True,
        help="Defaults to the logged-in user's own Work Unit and is "
             "read-only in Draft."
    )

    workforce_plan_id = fields.Many2one(
        "planning.work.unit.manpower", string="Approved Workforce Plan",
        tracking=True,
        default=lambda self: self._default_workforce_plan_id(),readonly= True,
        domain="[('work_unit_id', '=', operating_unit_id), "
               "('state', '=', 'approved'), ('del_flg', '=', 'N')]",
        help=": Required for Planned requests. Only approved plans "
             "belonging to the selected Work Unit are selectable. "
             "Auto-filled when only one Approved plan exists for your Work Unit."
    )

    justification = fields.Text(
        string="Business Justification",
        help=" Mandatory for Unplanned requests."
    )

    job_position_id = fields.Many2one("hr.job", string="Job Position", required=True, tracking=True)
    job_grade_id = fields.Many2one("employee.grade", string="Job Grade")
    department_id = fields.Many2one(
        "hr.department", string="Department", required=True,
        default=lambda self: self._default_department_id(),readonly= True,
        help="Defaults to the logged-in user's own Department and is "
             "read-only in Draft."
    )
    employment_type = fields.Selection(
        [("permanent", "Permanent"), ("contractual", "Contractual"), ("internship", "Internship")],
        string="Employment Type", required=True, default="permanent"
    )
    required_headcount = fields.Integer(
        string="Required Headcount", default=1, required=True
    )
    sourcing_type = fields.Selection(
        [("internal", "Internal"), ("external", "External"), ("both", "Both")],
        string="Sourcing Type", default="internal", required=True
    )
    required_qualifications = fields.Text(string="Required Qualifications")
    job_description = fields.Text(string="Job Description")
    employee_category = fields.Selection(
        [("Managerial", "Managerial"), ("Non Managerial", "Non Managerial")],
        string="Job Category", default="Non Managerial", tracking=True,
        help="Determines whether Job Level (Junior/Senior) is required. "
             "Managerial positions do not have a job level."
    )
    job_level = fields.Selection(
        [("junior", "Junior"), ("senior", "Senior / Regular")],
        string="Job Level", tracking=True,
        help="Required for Non-Managerial positions. Hidden for Managerial positions."
    )

    # -- : Plan headcount visibility (computed, not stored) -----------
    plan_total_headcount = fields.Integer(
        string="Plan Headcount (this Job)", compute="_compute_plan_headcount_info",
        help="Total headcount approved on the linked workforce plan for this "
             "Job Position (and Grade, if specified)."
    )
    plan_consumed_headcount = fields.Integer(
        string="Already Requested (this Job)", compute="_compute_plan_headcount_info",
        help="Headcount already consumed by other active recruitment requests "
             "against the same plan and Job Position."
    )
    plan_remaining_headcount = fields.Integer(
        string="Vacant Post", compute="_compute_plan_headcount_info",
        help="Plan Headcount minus what other active requests have already "
             "consumed. This is the maximum you can still request."
    )

    is_replacement = fields.Boolean(
        string="Replacement Hiring",
        help=": Tick if this request is to replace an existing employee or position."
    )
    replaced_employee_id = fields.Many2one(
        "hr.employee", string="Employee Being Replaced",
        invisible="not is_replacement"
    )
    replacement_reason = fields.Char(
        string="Reason for Replacement",
        invisible="not is_replacement"
    )

    allowed_job_ids = fields.Many2many(
        "hr.job", compute="_compute_allowed_jobs", string="Allowed Job Positions",
        help="Job positions available on the approved workforce plan for this Work Unit."
    )
    allowed_grade_ids = fields.Many2many(
        "employee.grade", compute="_compute_allowed_grades", string="Allowed Job Grades",
        help="Job grades available on the approved workforce plan for the selected Job Position."
    )

    @api.depends("operating_unit_id", "workforce_plan_id", "request_type")
    def _compute_allowed_jobs(self):
        for rec in self:
            jobs = self.env["hr.job"]
            if rec.workforce_plan_id:
                jobs = rec.workforce_plan_id.manpower_line_ids.mapped("job_id")
            elif rec.operating_unit_id:
                plans = self.env["planning.work.unit.manpower"].search([
                    ("work_unit_id", "=", rec.operating_unit_id.id),
                    ("state", "=", "approved"),
                    ("del_flg", "=", "N"),
                ])
                jobs = plans.mapped("manpower_line_ids.job_id")
            rec.allowed_job_ids = jobs

    @api.depends("operating_unit_id", "workforce_plan_id", "job_position_id")
    def _compute_allowed_grades(self):
        for rec in self:
            if not rec.job_position_id:
                rec.allowed_grade_ids = self.env["employee.grade"]
                continue
            lines = self.env["planning.manpower.line"]
            if rec.workforce_plan_id:
                lines = rec.workforce_plan_id.manpower_line_ids.filtered(
                    lambda l: l.job_id == rec.job_position_id
                )
            elif rec.operating_unit_id:
                plans = self.env["planning.work.unit.manpower"].search([
                    ("work_unit_id", "=", rec.operating_unit_id.id),
                    ("state", "=", "approved"),
                    ("del_flg", "=", "N"),
                ])
                lines = plans.mapped("manpower_line_ids").filtered(
                    lambda l: l.job_id == rec.job_position_id
                )
            rec.allowed_grade_ids = lines.mapped("grade_id")

    # -- Workflow state ----------------------------------------------------
    state = fields.Selection(
        [("draft", "Draft"),
         ("submitted", "Submitted"),
         ("under_review", "Under Review"),
         ("approved", "Approved"),
         ("rejected", "Rejected"),
         ("cancelled", "Cancelled")],
        string="Status", default="draft", tracking=True, copy=False
    )

    _ACTIVE_STATES = ("submitted", "under_review", "approved")

    submitted_on = fields.Datetime(string="Submitted On", readonly=True, copy=False)
    reviewed_by = fields.Many2one("res.users", string="Reviewed By", readonly=True, copy=False)
    approved_by = fields.Many2one("res.users", string="Approved By", readonly=True, copy=False)
    approved_on = fields.Datetime(string="Approved On", readonly=True, copy=False)
    rejection_reason = fields.Text(string="Rejection Reason")

    last_date_to_apply = fields.Date(
        string="Last Date to Apply",
        help="Application deadline for the vacancy. If not set, defaults to 30 days from vacancy creation."
    )

    vacancy_id = fields.Many2one("job.vacancy", string="Linked Vacancy", readonly=True, copy=False)

    active = fields.Boolean(default=True, tracking=True)

    def unlink(self):
        """Never hard-delete recruitment requests - archive them instead so
        the audit trail (chatter, approvals, links to vacancies) is preserved.
        Users hitting the normal Delete action will have the record archived
        (active=False) rather than removed from the database."""
        for rec in self:
            if rec.state:
                raise UserError(_(
                    "Please archive the records instead of deleting them."
                ))
        self.write({"active": False})
        self.message_post(body=_("Recruitment request archived."))
        return True

    # ---------------------------------------------------------------------
    # Sequence generation
    # ---------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("reference") or vals["reference"] == _("New"):
                vals["reference"] = (
                        self.env["ir.sequence"].next_by_code("recruitment.request") or _("New")
                )
        return super().create(vals_list)

    def _get_matching_plan_lines(self, plan, job, grade):
        """Return the manpower lines on `plan` that correspond to `job`
        (and `grade`, if one is set on the request). If no grade is set on
        the request, all grades/categories for that job are summed."""
        if not plan or not job:
            return self.env["planning.manpower.line"]
        lines = plan.manpower_line_ids.filtered(lambda l: l.job_id == job)
        if grade:
            lines = lines.filtered(lambda l: l.grade_id == grade)
        return lines

    def _get_plan_total_headcount(self, plan, job, grade):
        return sum(self._get_matching_plan_lines(plan, job, grade).mapped("total_headcount"))

    def _get_plan_consumed_headcount(self, plan, job, grade, exclude=None):
        """Sum of required_headcount from other active (submitted / under
        review / approved) Planned requests referencing the same plan and
        job (and grade, if set), excluding `exclude` (normally self)."""
        if not plan or not job:
            return 0
        domain = [
            ("workforce_plan_id", "=", plan.id),
            ("job_position_id", "=", job.id),
            ("request_type", "=", "planned"),
            ("state", "in", list(self._ACTIVE_STATES)),
        ]
        if grade:
            domain.append(("job_grade_id", "=", grade.id))
        others = self.search(domain)
        if exclude:
            others = others - exclude
        return sum(others.mapped("required_headcount"))

    @api.depends(
        "workforce_plan_id", "job_position_id", "job_grade_id",
        "required_headcount", "request_type", "state",
    )
    def _compute_plan_headcount_info(self):
        for rec in self:
            plan = rec.workforce_plan_id
            job = rec.job_position_id
            grade = rec.job_grade_id
            if rec.request_type != "planned" or not plan or not job:
                rec.plan_total_headcount = 0
                rec.plan_consumed_headcount = 0
                rec.plan_remaining_headcount = 0
                continue
            total = rec._get_plan_total_headcount(plan, job, grade)
            consumed = rec._get_plan_consumed_headcount(plan, job, grade, exclude=rec)
            rec.plan_total_headcount = total
            rec.plan_consumed_headcount = consumed
            rec.plan_remaining_headcount = total - consumed

    # ---------------------------------------------------------------------
    # Constraints
    # ---------------------------------------------------------------------
    @api.constrains("request_type", "justification")
    def _check_unplanned_justification(self):
        """: Unplanned requests must have a business justification."""
        for rec in self:
            if rec.request_type == "unplanned" and not rec.justification:
                raise ValidationError(
                    _(": Business Justification is required for Unplanned recruitment requests.")
                )

    def _validate_against_workforce_plan(self):

        self.ensure_one()
        failures = []
        if self.request_type != "planned":
            return failures

        plan = self.workforce_plan_id
        if not plan:
            failures.append((
                "no_plan",
                _("There is no vacant post available within your work unit."
                  " Please contact HR if you have any justification of the request."),
            ))
            return failures

        # Plan must actually be approved (and not soft-deleted).
        if plan.state != "approved" or plan.del_flg != "N":
            failures.append((
                "plan_not_approved",
                _("Workforce Plan '%s' is not Approved (current status: %s).")
                % (plan.name, dict(plan._fields["state"].selection).get(plan.state)),
            ))

        # Plan must belong to the SAME work unit as the request.
        if plan.work_unit_id != self.operating_unit_id:
            failures.append((
                "work_unit_mismatch",
                _("Workforce Plan '%s' belongs to Work Unit '%s', not this "
                  "request's Work Unit '%s'.")
                % (plan.name, plan.work_unit_id.name, self.operating_unit_id.name),
            ))

        # : Position ID must exist in the Approved Workforce Plan.
        matching_lines = self._get_matching_plan_lines(plan, self.job_position_id, self.job_grade_id)
        if not matching_lines:
            if self.job_grade_id:
                failures.append((
                    "position_not_on_plan",
                    _("Job Position '%s' with Grade '%s' does not exist in "
                      "the Approved Workforce Plan  for '%s' list.So Please Contact People Operation Directorate teams")
                    % (self.job_position_id.name, self.job_grade_id.grade_name, plan.name),
                ))
            else:
                failures.append((
                    "position_not_on_plan",
                    _("Job Position '%s' does not exist in the Approved "
                      "Workforce Plan '%s'.")
                    % (self.job_position_id.name, plan.name),
                ))

        # : Requested Headcount must not exceed Approved Budgeted
        # Headcount (net of what other active requests already consumed).
        if matching_lines:
            plan_total = self._get_plan_total_headcount(plan, self.job_position_id, self.job_grade_id)
            consumed_by_others = self._get_plan_consumed_headcount(
                plan, self.job_position_id, self.job_grade_id, exclude=self
            )
            available = plan_total - consumed_by_others
            if self.required_headcount > available:
                failures.append((
                    "headcount_exceeds_budget",
                    _("Requested Headcount (%(req)s) for '%(job)s' exceeds "
                      "the Approved Budgeted Headcount remaining on plan "
                      "'%(plan)s'. Approved Budgeted Headcount: %(total)s, "
                      "already committed to other active requests: "
                      "%(consumed)s, remaining: %(avail)s.")
                    % {
                        "req": self.required_headcount,
                        "job": self.job_position_id.name,
                        "plan": plan.name,
                        "total": plan_total,
                        "consumed": consumed_by_others,
                        "avail": available,
                    },
                ))

        return failures

    def _check_workforce_plan_or_raise(self):
        """: prevent processing and surface specific reason(s)."""
        self.ensure_one()
        failures = self._validate_against_workforce_plan()
        if failures:
            reasons = "\n".join("- %s" % msg for _code, msg in failures)
            self.message_post(body=_(
                "Automated validation failed -- request cannot proceed:<br/>%s"
            ) % reasons.replace("\n", "<br/>"))
            raise UserError(_(
                "This request failed automated validation against the "
                "Approved Workforce Plan and cannot proceed:\n\n%s"
            ) % reasons)

    @api.constrains("required_headcount")
    def _check_headcount(self):
        for rec in self:
            if rec.required_headcount < 1:
                raise ValidationError(_("Required Headcount must be at least 1."))

    @api.constrains(
        "request_type", "workforce_plan_id", "job_position_id",
        "job_grade_id", "required_headcount",
    )
    def _check_headcount_against_plan_on_save(self):

        for rec in self:
            if rec.request_type != "planned":
                continue
            plan = rec.workforce_plan_id
            job = rec.job_position_id
            if not plan or not job or not rec.required_headcount:
                continue
            matching_lines = rec._get_matching_plan_lines(plan, job, rec.job_grade_id)
            if not matching_lines:
                continue  # "position not on plan" stays a Submit-time error
            plan_total = rec._get_plan_total_headcount(plan, job, rec.job_grade_id)
            consumed_by_others = rec._get_plan_consumed_headcount(
                plan, job, rec.job_grade_id, exclude=rec
            )
            available = plan_total - consumed_by_others
            if rec.required_headcount > available:
                raise ValidationError(_(
                    "Requested Headcount (%(req)s) for '%(job)s' exceeds the "
                    "Approved Budgeted Headcount remaining on plan '%(plan)s'. "
                    "Approved Budgeted Headcount: %(total)s, already committed "
                    "to other active requests: %(consumed)s, remaining: %(avail)s."
                ) % {
                                          "req": rec.required_headcount, "job": job.name,
                                          "plan": plan.name, "total": plan_total,
                                          "consumed": consumed_by_others, "avail": available,
                                      })

    @api.constrains("is_replacement", "replaced_employee_id")
    def _check_replacement(self):
        """: If replacement, employee or reason must be specified."""
        for rec in self:
            if rec.is_replacement and not rec.replaced_employee_id and not rec.replacement_reason:
                raise ValidationError(
                    _(": Please specify the employee being replaced or the reason for replacement.")
                )

    @api.constrains("employee_category", "job_level")
    def _check_job_level_required(self):
        """Job Level is required for Non-Managerial and must be empty for Managerial."""
        for rec in self:
            if rec.employee_category == "Non Managerial" and not rec.job_level:
                raise ValidationError(_(
                    "Job Level (Junior / Senior) is required for Non-Managerial recruitment requests."
                ))
            if rec.employee_category == "Managerial" and rec.job_level:
                raise ValidationError(_(
                    "Job Level does not apply to Managerial positions — please clear it before saving."
                ))

    # ---------------------------------------------------------------------
    # Onchange helpers (UX: clear plan / auto-sync fields from approved plan)
    # ---------------------------------------------------------------------
    @api.onchange("employee_category")
    def _onchange_employee_category_clear_job_level(self):
        """Clear Job Level whenever the category is switched to Managerial."""
        for rec in self:
            if rec.employee_category == "Managerial":
                rec.job_level = False

    @api.onchange("operating_unit_id")
    def _onchange_operating_unit_id(self):
        """If the Work Unit changes, auto-sync the approved workforce plan for that unit
        and clear selected job position if no longer valid under the new unit."""
        if self.operating_unit_id:
            plans = self.env["planning.work.unit.manpower"].search([
                ("work_unit_id", "=", self.operating_unit_id.id),
                ("state", "=", "approved"),
                ("del_flg", "=", "N"),
            ])
            if len(plans) == 1:
                self.workforce_plan_id = plans.id
            elif plans and self.workforce_plan_id not in plans:
                self.workforce_plan_id = plans[0].id
            elif not plans:
                self.workforce_plan_id = False

            if hasattr(self.operating_unit_id, "department") and self.operating_unit_id.department:
                self.department_id = self.operating_unit_id.department

        if self.workforce_plan_id and self.workforce_plan_id.work_unit_id != self.operating_unit_id:
            self.workforce_plan_id = False

        if self.job_position_id and self.allowed_job_ids and self.job_position_id not in self.allowed_job_ids:
            self.job_position_id = False

    @api.onchange("job_position_id", "workforce_plan_id", "operating_unit_id")
    def _onchange_job_position_id_sync_fields(self):
        """Auto-synchronize Department, Grade, Description, and Qualifications when
        Job Position is selected from the approved manpower plan."""
        if not self.job_position_id:
            return

        # Auto-sync department from job position or operating unit
        if self.job_position_id.department_id:
            self.department_id = self.job_position_id.department_id
        elif self.operating_unit_id and hasattr(self.operating_unit_id,
                                                "department") and self.operating_unit_id.department:
            self.department_id = self.operating_unit_id.department

        # Auto-sync description and requirements if empty
        if hasattr(self.job_position_id,
                   'description') and self.job_position_id.description and not self.job_description:
            self.job_description = self.job_position_id.description
        if hasattr(self.job_position_id,
                   'requirements') and self.job_position_id.requirements and not self.required_qualifications:
            self.required_qualifications = self.job_position_id.requirements

        # Auto-sync grade if exactly one grade planned
        lines = self.env["planning.manpower.line"]
        if self.workforce_plan_id:
            lines = self.workforce_plan_id.manpower_line_ids.filtered(lambda l: l.job_id == self.job_position_id)
        elif self.operating_unit_id:
            plans = self.env["planning.work.unit.manpower"].search([
                ("work_unit_id", "=", self.operating_unit_id.id),
                ("state", "=", "approved"),
                ("del_flg", "=", "N"),
            ])
            lines = plans.mapped("manpower_line_ids").filtered(lambda l: l.job_id == self.job_position_id)

        grades = lines.mapped("grade_id")
        if len(grades) == 1:
            self.job_grade_id = grades.id
        elif grades and self.job_grade_id not in grades:
            self.job_grade_id = False

    @api.onchange("workforce_plan_id", "job_position_id", "job_grade_id", "required_headcount")
    def _onchange_plan_headcount_warning(self):
        if self.request_type != "planned" or not self.workforce_plan_id or not self.job_position_id:
            return
        plan = self.workforce_plan_id
        matching_lines = self._get_matching_plan_lines(plan, self.job_position_id, self.job_grade_id)
        if not matching_lines:
            return {
                "warning": {
                    "title": _("Job Position not on Plan"),
                    "message": _(
                        "Job Position '%s' is not part of the Approved Workforce "
                        "Plan '%s'. You will not be able to save this request "
                        "until you correct this."
                    ) % (self.job_position_id.name, plan.name),
                }
            }
        total = self._get_plan_total_headcount(plan, self.job_position_id, self.job_grade_id)
        consumed = self._get_plan_consumed_headcount(
            plan, self.job_position_id, self.job_grade_id, exclude=self._origin
        )
        available = total - consumed
        if self.required_headcount and self.required_headcount > available:
            return {
                "warning": {
                    "title": _("Headcount Exceeds Plan"),
                    "message": _(
                        "Only %s headcount remain available on this plan for "
                        "'%s' (plan total: %s, already requested: %s)."
                    ) % (available, self.job_position_id.name, total, consumed),
                }
            }

    # ---------------------------------------------------------------------
    # Security Helper Methods
    # ---------------------------------------------------------------------
    def _check_hr_role_or_raise(self):
        is_hr = (
                self.env.user.has_group("hr.group_hr_user") or
                self.env.user.has_group("hr.group_hr_manager") or
                self.env.user.has_group("hr_recruitment.group_hr_recruitment_user") or
                self.env.user.has_group("hr_recruitment.group_hr_recruitment_manager")
        )
        if not is_hr:
            raise UserError(_("Only users with HR roles can review, approve, reject, or convert recruitment requests."))

    def _check_submission_work_unit(self):
        self.ensure_one()
        is_hr = (
                self.env.user.has_group("hr.group_hr_user") or
                self.env.user.has_group("hr.group_hr_manager") or
                self.env.user.has_group("hr_recruitment.group_hr_recruitment_user") or
                self.env.user.has_group("hr_recruitment.group_hr_recruitment_manager")
        )
        if is_hr:
            return

        user_emp = self.env.user.employee_id
        user_ou = user_emp.default_operating_unit_id if user_emp else False
        user_ous = getattr(self.env.user, "operating_unit_ids", self.env["operating.unit"])
        if user_emp and hasattr(user_emp, "operating_unit_ids"):
            user_ous |= user_emp.operating_unit_ids

        if self.operating_unit_id and self.operating_unit_id != user_ou and self.operating_unit_id not in user_ous:
            raise UserError(_(
                "You can only submit recruitment requests for your own Work Unit (%s)."
            ) % (user_ou.name if user_ou else _("Unassigned")))

    # ---------------------------------------------------------------------
    # Workflow actions
    # ---------------------------------------------------------------------
    def action_submit(self):
        """User submits the request, which routes it to HR for verification.
        Validates work unit membership, position ID and headcount against
        the Approved Workforce Plan."""
        for rec in self:
            rec._check_submission_work_unit()
            rec._check_workforce_plan_or_raise()
            rec.write({
                "state": "submitted",
                "submitted_on": fields.Datetime.now(),
            })
            rec.message_post(body=_(
                "Recruitment request submitted and routed to People Operations Management Directorate for verification."))
            rec._notify_hr()

        # Reload the form to reflect status change immediately
        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }

    def action_start_review(self):
        for rec in self:
            rec._check_hr_role_or_raise()
            rec.write({"state": "under_review", "reviewed_by": self.env.uid})
            rec.message_post(body=_("Request is now under HR review."))

        # Reload the form to reflect status change immediately
        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }

    def action_approve(self):
        for rec in self:
            rec._check_hr_role_or_raise()
            # Re-run checks at approval time since other requests may have consumed headcount.
            rec._check_workforce_plan_or_raise()
            rec.write({
                "state": "approved",
                "approved_by": self.env.uid,
                "approved_on": fields.Datetime.now(),
            })
            rec.message_post(body=_("Recruitment request approved. Eligible for vacancy creation."))

        # Reload the form to reflect status change immediately
        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }

    def action_reject(self):
        for rec in self:
            rec._check_hr_role_or_raise()
            if not rec.rejection_reason:
                raise UserError(_("Please enter a Rejection Reason before rejecting."))
            rec.write({"state": "rejected"})
            rec.message_post(body=_("Request rejected. Reason: %s") % rec.rejection_reason)

        # Reload the form to reflect status change immediately
        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }

    def action_cancel(self):
        for rec in self:
            if rec.state in ("approved",):
                raise UserError(_("Approved requests cannot be cancelled."))
            rec.write({"state": "cancelled"})
            rec.message_post(body=_("Recruitment request cancelled."))

        # Reload the form to reflect status change immediately
        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }

    def action_reset_draft(self):
        for rec in self:
            if rec.state not in ("rejected", "cancelled"):
                raise UserError(_("Only rejected or cancelled requests can be reset to Draft."))
            rec.write({"state": "draft", "rejection_reason": False})
            rec.message_post(body=_("Request reset to Draft."))

        # Reload the form to reflect status change immediately
        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }

    def action_create_vacancy(self):
        """Create a Job Vacancy directly from an approved request."""
        self.ensure_one()
        self._check_hr_role_or_raise()
        if self.state != "approved":
            raise UserError(_("Only approved requests can be converted to a vacancy."))
        if self.vacancy_id:
            return {
                "type": "ir.actions.act_window",
                "res_model": "job.vacancy",
                "res_id": self.vacancy_id.id,
                "view_mode": "form",
                "target": "current",
            }

        # Default last_date_to_apply to 30 days from now if not set
        last_date = self.last_date_to_apply
        if not last_date:
            last_date = fields.Date.today() + timedelta(days=30)

        vacancy = self.env["job.vacancy"].create({
            "recruitment_request_id": self.id,
            "recruitment_reference": self.reference,
            "job_position": self.job_position_id.id,
            "operating_unit_id": self.operating_unit_id.id,
            "responsible": self.requested_by.id,
            "no_of_vacancies": self.required_headcount,
            "type_of_employment": "Permanent" if self.employment_type == "permanent" else "Contractual",
            "sourcing_type": self.sourcing_type,
            "recruitment_type": "Internal" if self.sourcing_type == "internal" else "External",
            "vacancy_description": self.job_description or "",
            "last_date_to_apply": last_date,
            "employee_category": self.employee_category,
            "job_level": self.job_level if self.employee_category == "Non Managerial" else False,
        })
        self.write({"vacancy_id": vacancy.id})
        self.message_post(body=_("Vacancy %s created from this request.") % vacancy.reference)
        return {
            "type": "ir.actions.act_window",
            "res_model": "job.vacancy",
            "res_id": vacancy.id,
            "view_mode": "form",
            "target": "current",
        }

    # ---------------------------------------------------------------------
    # Notifications
    # ---------------------------------------------------------------------
    def _notify_hr(self):
        """Notify HR managers of new recruitment request. Uses chat for
        1-2 recipients (Odoo's chat limit) and group channel for 3+ recipients."""
        self.ensure_one()
        hr_group = self.env.ref("hr.group_hr_manager", raise_if_not_found=False)
        if not hr_group:
            return
        # Odoo 19: group_ids (renamed from groups_id)
        hr_users = self.env["res.users"].search([("group_ids", "in", [hr_group.id])])
        partners = hr_users.mapped("partner_id")
        if partners:
            body = _(
                "A new Recruitment Request <b>%(ref)s</b> has been submitted by <b>%(user)s</b> "
                "for the position <b>%(pos)s</b> in <b>%(unit)s</b>. Please review."
            ) % {
                       "ref": self.reference,
                       "user": self.requested_by.name,
                       "pos": self.job_position_id.name or "",
                       "unit": self.operating_unit_id.name or "",
                   }
            # Use chat for 1-2 people, group for 3+ people
            if len(partners) <= 2:
                channel = self.env["discuss.channel"]._get_or_create_chat(
                    partners_to=partners.ids
                )
            else:
                # Create the group channel first, then add members via write
                channel = self.env["discuss.channel"].create({
                    "name": _("Recruitment Request Review - %s") % self.reference,
                    "channel_type": "group",
                })
                # Add partners using write with proper ORM syntax
                channel.write({
                    "channel_partner_ids": [(4, partner_id) for partner_id in partners.ids],
                })
            channel.message_post(
                body=body, message_type="comment", subtype_xmlid="mail.mt_comment"
            )
