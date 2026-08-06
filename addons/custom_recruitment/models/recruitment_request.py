# -*- coding: utf-8 -*-

from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class RecruitmentRequest(models.Model):
    _name = "recruitment.request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Recruitment Request"
    _rec_name = "reference"
    _order = "request_date desc"

    def _default_operating_unit_id(self):
        employee = self.env.user.employee_id
        return employee.default_operating_unit_id.id if employee else False

    def _default_department_id(self):
        employee = self.env.user.employee_id
        return employee.department_id.id if employee else False

    def _default_workforce_plan_id(self):
        """Auto-select the Approved Workforce Plan for the requester's own
        Work Unit when there is exactly one candidate. If there are zero
        or several (e.g. multiple fiscal years both Approved), leave it
        blank for the user to choose explicitly."""
        unit_id = self._default_operating_unit_id
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
        default=lambda self: self.env.user.employee_id,
        required=True, tracking=True,
        help="Defaults to the currently logged-in user's employee record "
             "and is read-only in Draft, so a request can't be filed on "
             "behalf of someone else."
    )
    operating_unit_id = fields.Many2one(
        "operating.unit", string="Work Unit", required=True, tracking=True,
        default=lambda self: self._default_operating_unit_id,
        help="Defaults to the logged-in user's own Work Unit and is "
             "read-only in Draft."
    )


    workforce_plan_id = fields.Many2one(
        "planning.work.unit.manpower", string="Approved Workforce Plan",
        tracking=True,
        default=lambda self: self._default_workforce_plan_id,
        domain="[('work_unit_id', '=', operating_unit_id), "
               "('state', '=', 'approved'), ('del_flg', '=', 'N')]",
        help=": Required for Planned requests. Only approved plans "
             "belonging to the selected Work Unit are selectable. "
             "Auto-filled when only one Approved plan exists for your Work Unit."
    )

    # -- : Justification (required for Unplanned) ---------------------
    justification = fields.Text(
        string="Business Justification",
        help=" Mandatory for Unplanned requests."
    )

    # -- : Job Information --------------------------------------------
    job_position_id = fields.Many2one("hr.job", string="Job Position", required=True, tracking=True)
    job_grade_id = fields.Many2one("employee.grade", string="Job Grade")
    department_id = fields.Many2one(
        "hr.department", string="Department", required=True,
        default=lambda self: self._default_department_id,
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

    # -- : Replacement Hiring -----------------------------------------
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

    # States considered to still be "actively consuming" plan headcount.
    _ACTIVE_STATES = ("submitted", "under_review", "approved")

    # -- Approval tracking -------------------------------------------------
    submitted_on = fields.Datetime(string="Submitted On", readonly=True, copy=False)
    reviewed_by = fields.Many2one("res.users", string="Reviewed By", readonly=True, copy=False)
    approved_by = fields.Many2one("res.users", string="Approved By", readonly=True, copy=False)
    approved_on = fields.Datetime(string="Approved On", readonly=True, copy=False)
    rejection_reason = fields.Text(string="Rejection Reason")

    # -- Vacancy Application Deadline -----------------------------------
    last_date_to_apply = fields.Date(
        string="Last Date to Apply",
        help="Application deadline for the vacancy. If not set, defaults to 30 days from vacancy creation."
    )

    # -- Linked vacancy (after approval) ----------------------------------
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

    # ---------------------------------------------------------------------
    # Plan headcount helpers  quantity validation)
    # ---------------------------------------------------------------------
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
        """ /  / : automated validation run
        when a Planned request is routed for verification (i.e. on
        Submit, and re-checked on Approve since concurrent requests may
        have consumed headcount in the meantime).

        This is deliberately NOT an @api.constrains -- a Work Unit must be
        able to save an incomplete Draft while still filling in the
        request . Validation only fires at the point the
        system routes the request onward for verification .

        Returns a list of (code, message) failure tuples. Empty list =
        passed. Each failure is specific per  ("provide
        specific failure reason").
        """
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
        """Block save (not just Submit) once a Planned request has enough
        info to check headcount against the plan. Records still missing
        plan/job/headcount can be saved as an incomplete Draft ;
        once those are filled in, saving is blocked if headcount exceeds
        what's left on the plan /008)."""
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

    # ---------------------------------------------------------------------
    # Onchange helpers (UX: clear plan / warn before hitting the hard
    # constraint on save)
    # ---------------------------------------------------------------------
    @api.onchange("job_position_id", "workforce_plan_id")
    def _onchange_job_position_id_autofill_grade(self):
        """Auto-populate Job Grade from the linked Workforce Plan's
        manpower lines when a Job Position is picked. Grade only lives on
        the plan lines (hr.job itself carries no grade), so this only
        fires once a plan is selected (Planned requests)."""
        if not self.job_position_id or not self.workforce_plan_id:
            return
        lines = self.workforce_plan_id.manpower_line_ids.filtered(
            lambda l: l.job_id == self.job_position_id
        )
        grades = lines.mapped("grade_id")
        if len(grades) == 1:
            # Exactly one grade planned for this job on this plan -> auto-fill.
            self.job_grade_id = grades
        elif len(grades) > 1:
            # Multiple grades exist for this job on the plan (e.g. Grade I
            # and Grade II both budgeted) -> can't guess, ask the user to
            # pick, but tell them what's available.
            self.job_grade_id = False
            return {
                "warning": {
                    "title": _("Multiple Grades Available"),
                    "message": _(
                        "Job Position '%s' has more than one Grade planned "
                        "on Workforce Plan '%s' (%s). Please select the "
                        "correct Grade manually."
                    ) % (
                                   self.job_position_id.name,
                                   self.workforce_plan_id.name,
                                   ", ".join(grades.mapped("grade_name")),
                               ),
                }
            }

    @api.onchange("operating_unit_id")
    def _onchange_operating_unit_id(self):
        """If the Work Unit changes, drop a previously selected plan that
        no longer matches it (the domain will also filter it, but this
        catches records that were already saved)."""
        if self.workforce_plan_id and self.workforce_plan_id.work_unit_id != self.operating_unit_id:
            self.workforce_plan_id = False

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
    # Workflow actions
    # ---------------------------------------------------------------------
    def action_submit(self):
        """/005: User submits the request, which routes it to
        People Operations Management Directorate for verification.
        /007/008: before routing, run the automated Position ID
        and Headcount checks against the Approved Workforce Plan; if
        either fails, block the submission and surface the specific
        reason instead of transitioning state."""
        for rec in self:
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
            rec.write({"state": "under_review", "reviewed_by": self.env.uid})
            rec.message_post(body=_("Request is now under HR review."))

        # Reload the form to reflect status change immediately
        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }

    def action_approve(self):
        for rec in self:
            # Re-run the /007 checks at approval time too, since
            # other requests against the same plan may have consumed
            # headcount between submission and approval.
            rec._check_workforce_plan_or_raise
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
            "job_position": self.job_position_id.id,
            "operating_unit_id": self.operating_unit_id.id,
            "responsible": self.requested_by.id,
            "no_of_vacancies": self.required_headcount,
            "type_of_employment": "Permanent" if self.employment_type == "permanent" else "Contractual",
            "sourcing_type": self.sourcing_type,
            "recruitment_type": "Internal" if self.sourcing_type == "internal" else "External",
            "vacancy_description": self.job_description or "",
            "last_date_to_apply": last_date,
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
