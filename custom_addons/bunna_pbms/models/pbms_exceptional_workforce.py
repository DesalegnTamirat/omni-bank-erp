# -*- coding: utf-8 -*-
import logging
from markupsafe import Markup
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)


class PbmsExceptionalWorkforceRequest(models.Model):
    """Exceptional Workforce Request (Mid-year workforce need not in the approved annual plan).

    Workflow:
    1. District / Department Director identifies exceptional need and initiates
       request with justification (position, job grade, branch/department, supporting docs).
    2. People Solutions Directorate reviews and assesses the request, escalates to CPCO.
    3. CPCO prepares and submits a memo with justification/recommendation to the CEO.
    4. CEO approves or rejects the request.
    5. CPCO records the CEO's decision in the system (on the CEO's behalf).
    6. People Operations & Management Directorate: system auto-initiates a vacancy request
       and routes it for recruitment action.
    """
    _name = "pbms.exceptional.workforce.request"
    _description = "Exceptional Workforce Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"
    _rec_name = "name"

    name = fields.Char(
        string="Request Number",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
        tracking=True,
    )
    request_date = fields.Date(
        string="Request Date",
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )
    initiator_id = fields.Many2one(
        "res.users",
        string="Initiator",
        default=lambda self: self.env.user,
        required=True,
        tracking=True,
    )
    initiator_role = fields.Selection(
        [
            ("district_director", "District Director"),
            ("department_director", "Department Director"),
            ("branch_manager", "Branch Manager"),
            ("other", "Other"),
        ],
        string="Initiator Role",
        default="district_director",
        required=True,
        tracking=True,
    )
    operating_unit_id = fields.Many2one(
        "operating.unit",
        string="Branch / Work Unit",
        required=True,
        default=lambda self: self.env.user.default_operating_unit_id or (self.env.user.operating_unit_ids[:1] if self.env.user.operating_unit_ids else False),
        tracking=True,
    )
    department_id = fields.Many2one(
        "hr.department",
        string="Department",
        default=lambda self: self.env.user.employee_id.department_id if self.env.user.employee_id else False,
        tracking=True,
    )
    eligible_job_ids = fields.Many2many(
        "hr.job",
        compute="_compute_eligible_job_ids",
        string="Eligible Positions",
        store=False,
    )
    job_id = fields.Many2one(
        "hr.job",
        string="Position / Job Title",
        required=True,
        tracking=True,
    )
    job_grade_id = fields.Many2one(
        "employee.grade",
        string="Job Grade",
        compute="_compute_job_grade_id",
        store=True,
        readonly=False,
        precompute=True,
        tracking=True,
    )
    headcount = fields.Integer(
        string="Required Headcount",
        default=1,
        required=True,
        tracking=True,
    )
    employment_type = fields.Selection(
        [
            ("permanent", "Permanent"),
            ("contractual", "Contractual"),
            ("internship", "Internship"),
        ],
        string="Employment Type",
        default="permanent",
        required=True,
        tracking=True,
    )
    sourcing_type = fields.Selection(
        [
            ("internal", "Internal"),
            ("external", "External"),
            ("both", "Both"),
        ],
        string="Sourcing Type",
        tracking=True,
        help="Sourcing method determined by People Solutions Directorate and above hierarchy.",
    )
    justification = fields.Text(
        string="Justification",
        required=True,
        tracking=True,
        help="Detailed business justification for exceptional mid-year hiring.",
    )
    supporting_doc_ids = fields.Many2many(
        "ir.attachment",
        "pbms_exceptional_workforce_attachment_rel",
        "request_id",
        "attachment_id",
        string="Supporting Documents",
        help="Upload supporting justification memos, committee notes, or business cases.",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        default=lambda self: self.env.company,
        required=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("people_solutions", "People Solutions Review"),
            ("cpco_review", "CPCO Review"),
            ("ceo_review", "Pending CEO Approval"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("returned", "Returned for Revision"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
        index=True,
    )
    color = fields.Integer(string="Color Index", default=0)

    # ---- People Solutions Directorate Review Stage ----
    people_solutions_reviewer_id = fields.Many2one(
        "res.users",
        string="People Solutions Reviewer",
        readonly=True,
        copy=False,
    )
    people_solutions_review_date = fields.Datetime(
        string="People Solutions Review Date",
        readonly=True,
        copy=False,
    )
    people_solutions_assessment = fields.Text(
        string="People Solutions Assessment & Remarks",
        tracking=True,
    )

    # ---- CPCO (Chief of People & Culture Office) Stage ----
    cpco_reviewer_id = fields.Many2one(
        "res.users",
        string="CPCO Officer",
        readonly=True,
        copy=False,
    )
    cpco_submission_date = fields.Datetime(
        string="CPCO Submission Date",
        readonly=True,
        copy=False,
    )
    cpco_memo = fields.Text(
        string="CPCO Recommendation Memo to CEO",
        tracking=True,
        help="Formal recommendation memo prepared and submitted by CPCO to the CEO.",
    )

    # ---- CEO Decision & Recording Stage ----
    ceo_approver_id = fields.Many2one(
        "res.users",
        string="CEO Approver",
        readonly=True,
        copy=False,
    )
    ceo_decision = fields.Selection(
        [
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        string="CEO Decision",
        readonly=True,
        copy=False,
        tracking=True,
    )
    ceo_decision_recorded_by = fields.Many2one(
        "res.users",
        string="Decision Recorded By",
        readonly=True,
        copy=False,
    )
    ceo_decision_date = fields.Datetime(
        string="CEO Decision Date",
        readonly=True,
        copy=False,
    )
    ceo_decision_remarks = fields.Text(
        string="CEO Decision Remarks",
        tracking=True,
    )
    rejection_reason = fields.Text(
        string="Rejection Reason",
        tracking=True,
    )
    return_reason = fields.Text(
        string="Return Reason",
        tracking=True,
    )

    # ---- Job Eligibility & Auto-Population Computes ----
    @api.model
    def _get_eligible_jobs_for_unit(self, unit_id):
        """Retrieve eligible jobs for a given operating unit.
        Prioritizes operating.unit.job.position configured positions exclusively.
        Falls back to active employee positions only if no positions are configured.
        """
        if not unit_id:
            return self.env["hr.job"].search([("active", "=", True)])
        job_ids = set()
        # 1. Look up configured positions in operating.unit.job.position
        if "operating.unit.job.position" in self.env:
            ou_positions = self.env["operating.unit.job.position"].search([
                ("operating_unit_id", "=", unit_id),
                ("active", "=", True),
            ])
            for pos in ou_positions:
                if pos.job_position_id and pos.job_position_id.active:
                    job_ids.add(pos.job_position_id.id)
        # 2. Look up positions of active employees in this work unit ONLY if none configured above
        if not job_ids and "hr.employee" in self.env:
            emp_domain = [
                ("active", "=", True),
                "|",
                ("operating_unit_ids", "in", [unit_id]),
                ("default_operating_unit_id", "=", unit_id),
            ]
            employees = self.env["hr.employee"].search(emp_domain)
            for emp in employees:
                j = getattr(emp, "job_position", False) or getattr(emp, "job_id", False)
                if j and j.active:
                    job_ids.add(j.id)

        if job_ids:
            return self.env["hr.job"].browse(list(job_ids))
        # Fallback if no positions configured or found for this unit
        return self.env["hr.job"].search([("active", "=", True)])

    @api.model
    def _get_grade_for_job_and_unit(self, job, operating_unit):
        """Determine grade for a job, checking operating.unit.job.position first."""
        if not job:
            return False
        grade = False
        if operating_unit and "operating.unit.job.position" in self.env:
            pos = self.env["operating.unit.job.position"].search([
                ("operating_unit_id", "=", operating_unit.id),
                ("job_position_id", "=", job.id),
                ("active", "=", True),
            ], limit=1)
            if pos and getattr(pos, "job_grade_id", False):
                grade = pos.job_grade_id
        if not grade:
            grade = (
                getattr(job, "grade", False)
                or getattr(job, "job_grade_id", False)
                or getattr(job, "grade_id", False)
            )
        return grade

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ou_id = res.get("operating_unit_id")
        if not ou_id:
            user = self.env.user
            ou = user.default_operating_unit_id or (user.operating_unit_ids[:1] if user.operating_unit_ids else False)
            if ou:
                ou_id = ou.id
                if "operating_unit_id" in fields_list:
                    res["operating_unit_id"] = ou_id
        if ou_id:
            jobs = self._get_eligible_jobs_for_unit(ou_id)
            res["eligible_job_ids"] = [(6, 0, jobs.ids)]
        res["can_district_edit"] = True
        res["can_district_submit"] = True
        res["can_edit"] = True
        res["can_view_sourcing_type"] = False
        res["can_edit_sourcing_type"] = False
        return res

    @api.depends("operating_unit_id")
    def _compute_eligible_job_ids(self):
        for rec in self:
            if rec.operating_unit_id:
                rec.eligible_job_ids = self._get_eligible_jobs_for_unit(rec.operating_unit_id.id)
            else:
                rec.eligible_job_ids = self.env["hr.job"].search([("active", "=", True)])

    @api.onchange("operating_unit_id")
    def _onchange_operating_unit_id(self):
        if self.operating_unit_id:
            jobs = self._get_eligible_jobs_for_unit(self.operating_unit_id.id)
            self.eligible_job_ids = jobs
            if self.job_id and self.job_id not in jobs:
                self.job_id = False
                self.job_grade_id = False
            return {"domain": {"job_id": [("id", "in", jobs.ids)]}}
        else:
            all_jobs = self.env["hr.job"].search([("active", "=", True)])
            self.eligible_job_ids = all_jobs
            self.job_id = False
            self.job_grade_id = False
            return {"domain": {"job_id": [("active", "=", True)]}}

    @api.depends("job_id", "operating_unit_id")
    def _compute_job_grade_id(self):
        for rec in self:
            rec.job_grade_id = self._get_grade_for_job_and_unit(rec.job_id, rec.operating_unit_id)

    @api.onchange("job_id")
    def _onchange_job_id(self):
        if self.job_id:
            self.job_grade_id = self._get_grade_for_job_and_unit(self.job_id, self.operating_unit_id)
        else:
            self.job_grade_id = False

    @api.constrains("job_id", "operating_unit_id")
    def _check_job_eligibility(self):
        for rec in self:
            if rec.operating_unit_id and rec.job_id and rec.eligible_job_ids:
                if rec.job_id not in rec.eligible_job_ids:
                    raise ValidationError(_(
                        "Position '%s' is not an eligible job position for Work Unit '%s'. "
                        "Please select an eligible position configured for this work unit."
                    ) % (rec.job_id.name, rec.operating_unit_id.display_name))

    @api.onchange("initiator_id")
    def _onchange_initiator_id(self):
        if self.initiator_id:
            emp = self.initiator_id.employee_id
            if emp and emp.department_id:
                self.department_id = emp.department_id
            ou = self.initiator_id.default_operating_unit_id or (self.initiator_id.operating_unit_ids[:1] if self.initiator_id.operating_unit_ids else False)
            if ou:
                self.operating_unit_id = ou
                return self._onchange_operating_unit_id()

    # ---- Computed Access & Action Flags ----
    can_district_edit = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)
    can_district_submit = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)
    can_people_solutions_edit = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)
    can_people_solutions_action = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)
    can_cpco_edit = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)
    can_cpco_action = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)
    can_ceo_edit = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)
    can_ceo_action = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)
    can_view_sourcing_type = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)
    can_edit_sourcing_type = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)
    can_edit = fields.Boolean(compute="_compute_access_flags", compute_sudo=False)

    @api.depends("state")
    def _compute_access_flags(self):
        user = self.env.user
        is_admin = user._pbms_is_sppmd_admin() or user._pbms_is_manager() or self.env.is_admin() or self.env.su
        is_district = user._pbms_is_district_reviewer() or is_admin
        is_solutions = user._pbms_is_people_solutions() or is_admin
        is_cpco = user._pbms_is_cpco() or is_admin
        is_ceo = user._pbms_is_ceo() or is_admin
        is_solutions_or_above = is_solutions or is_cpco or is_ceo or is_admin
        # Sourcing type is strictly displayed in People Solutions Directorate and above hierarchy
        # District Reviewers and standard users must NEVER see or edit sourcing_type.
        is_district_only = user._pbms_is_district_reviewer() and not (
            user._pbms_is_people_solutions()
            or user._pbms_is_cpco()
            or user._pbms_is_ceo()
            or user._pbms_is_sppmd_admin()
            or user._pbms_is_manager()
            or self.env.is_admin()
            or self.env.su
        )

        for rec in self:
            is_initiator = (rec.initiator_id == user) or (rec.create_uid == user) or (not rec.id)

            # District Reviewer stage: draft or returned
            c_dist = rec.state in ("draft", "returned") and (is_district or is_initiator)
            rec.can_district_edit = c_dist
            rec.can_district_submit = c_dist

            # People Solutions stage: people_solutions
            c_sol = rec.state == "people_solutions" and is_solutions
            rec.can_people_solutions_edit = c_sol
            rec.can_people_solutions_action = c_sol

            # CPCO stage: cpco_review
            c_cpco = rec.state == "cpco_review" and is_cpco
            rec.can_cpco_edit = c_cpco
            rec.can_cpco_action = c_cpco

            # CEO stage: ceo_review
            c_ceo = rec.state == "ceo_review" and is_ceo
            rec.can_ceo_edit = c_ceo
            rec.can_ceo_action = c_ceo

            # Sourcing type is only displayed in People Solutions Directorate and above hierarchy
            rec.can_view_sourcing_type = (
                not is_district_only
                and is_solutions_or_above
                and rec.state in ("people_solutions", "cpco_review", "ceo_review", "approved")
            )
            rec.can_edit_sourcing_type = (
                not is_district_only
                and (
                    (rec.state == "people_solutions" and is_solutions)
                    or (rec.state == "cpco_review" and is_cpco)
                    or (rec.state == "ceo_review" and is_ceo)
                    or is_admin
                )
            )

            # SPPMD Administrator can edit any non-finalized request; stage reviewers edit during their stage
            rec.can_edit = (is_admin and rec.state not in ("rejected",)) or c_dist or c_sol or c_cpco or c_ceo

    # ---- Recruitment Action (People Operations & Management) ----
    recruitment_request_id = fields.Integer(
        string="Linked Recruitment Request ID",
        readonly=True,
        copy=False,
    )
    recruitment_request_reference = fields.Char(
        string="Recruitment Request Reference",
        readonly=True,
        copy=False,
        tracking=True,
    )
    vacancy_reference = fields.Char(
        string="Job Vacancy Reference",
        readonly=True,
        copy=False,
        tracking=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("New"):
                seq = self.env["ir.sequence"].next_by_code("pbms.exceptional.workforce.request")
                vals["name"] = seq or _("New")
        return super().create(vals_list)

    def write(self, vals):
        if (
            self.env.su
            or self.env.is_admin()
            or self.env.user._pbms_is_sppmd_admin()
            or self.env.context.get("bypass_workforce_lock")
        ):
            return super().write(vals)

        # Technical, chatter, or activity updates pass through
        bypass_keys = {
            "message_follower_ids", "activity_ids", "message_ids",
            "recruitment_request_id", "recruitment_request_reference", "vacancy_reference",
            "color"
        }
        content_keys = set(vals.keys()) - bypass_keys
        if not content_keys:
            return super().write(vals)

        user = self.env.user
        is_admin = user._pbms_is_sppmd_admin() or user._pbms_is_manager() or self.env.is_admin()

        for rec in self:
            if rec.state in ("draft", "returned"):
                if not (user._pbms_is_district_reviewer() or rec.initiator_id == user or rec.create_uid == user or is_admin):
                    raise AccessError(_("Only the District Reviewer or initiator can edit this request while in Draft or Returned stage."))
            elif rec.state == "people_solutions":
                if not (user._pbms_is_people_solutions() or is_admin):
                    raise AccessError(_("Only People Solutions Directorate officers can edit this request during People Solutions Review."))
            elif rec.state == "cpco_review":
                if not (user._pbms_is_cpco() or is_admin):
                    raise AccessError(_("Only CPCO officers can edit this request during CPCO Review."))
            elif rec.state == "ceo_review":
                if not (user._pbms_is_ceo() or is_admin):
                    raise AccessError(_("Only the Chief Executive Officer (CEO) can edit this request during CEO Review."))
            elif rec.state in ("approved", "rejected"):
                raise AccessError(_("This Exceptional Workforce Request has been finalized (%s) and cannot be edited.") % rec.state)

        return super().write(vals)

    @api.constrains("headcount")
    def _check_headcount(self):
        for rec in self:
            if rec.headcount < 1:
                raise ValidationError(_("Required headcount must be at least 1."))

    # -------------------------------------------------------------------------
    # EMAIL NOTIFICATION TEMPLATES & DISPATCH
    # -------------------------------------------------------------------------
    def _get_exceptional_summary_table_html(self, extra_rows=""):
        self.ensure_one()
        role_label = dict(self._fields["initiator_role"].selection).get(self.initiator_role, self.initiator_role)
        emp_type_label = dict(self._fields["employment_type"].selection).get(self.employment_type, self.employment_type)
        sourcing_label = dict(self._fields["sourcing_type"].selection).get(self.sourcing_type, self.sourcing_type)
        dept_name = self.department_id.name if self.department_id else "N/A"
        grade_name = (self.job_grade_id.display_name or self.job_grade_id.grade_name or self.job_grade_id.grade_code or "N/A") if self.job_grade_id else "N/A"

        return (
            '<table style="width: 100%; border-collapse: collapse; margin: 16px 0; background-color: #FAFAFA; border-radius: 6px;">'
            f'<tr style="border-bottom: 1px solid #EEEEEE;">'
            f'<td style="padding: 10px; font-weight: bold; width: 35%; color: #555555;">Request Number:</td>'
            f'<td style="padding: 10px; font-weight: bold; color: #541718;">{self.name or "N/A"}</td></tr>'
            f'<tr style="border-bottom: 1px solid #EEEEEE;">'
            f'<td style="padding: 10px; font-weight: bold; color: #555555;">Work Unit / Branch:</td>'
            f'<td style="padding: 10px;">{self.operating_unit_id.display_name if self.operating_unit_id else "N/A"}</td></tr>'
            f'<tr style="border-bottom: 1px solid #EEEEEE;">'
            f'<td style="padding: 10px; font-weight: bold; color: #555555;">Department:</td>'
            f'<td style="padding: 10px;">{dept_name}</td></tr>'
            f'<tr style="border-bottom: 1px solid #EEEEEE;">'
            f'<td style="padding: 10px; font-weight: bold; color: #555555;">Initiator:</td>'
            f'<td style="padding: 10px;">{self.initiator_id.name} ({role_label})</td></tr>'
            f'<tr style="border-bottom: 1px solid #EEEEEE;">'
            f'<td style="padding: 10px; font-weight: bold; color: #555555;">Position / Job Title:</td>'
            f'<td style="padding: 10px; font-weight: bold; color: #425727;">{self.job_id.name if self.job_id else "N/A"}</td></tr>'
            f'<tr style="border-bottom: 1px solid #EEEEEE;">'
            f'<td style="padding: 10px; font-weight: bold; color: #555555;">Job Grade:</td>'
            f'<td style="padding: 10px;">{grade_name}</td></tr>'
            f'<tr style="border-bottom: 1px solid #EEEEEE;">'
            f'<td style="padding: 10px; font-weight: bold; color: #C17540;">Required Headcount:</td>'
            f'<td style="padding: 10px; font-weight: bold; color: #C17540;">{self.headcount} Position(s)</td></tr>'
            f'<tr style="border-bottom: 1px solid #EEEEEE;">'
            f'<td style="padding: 10px; font-weight: bold; color: #555555;">Employment / Sourcing:</td>'
            f'<td style="padding: 10px;">{emp_type_label} / {sourcing_label}</td></tr>'
            f'<tr style="border-bottom: 1px solid #EEEEEE;">'
            f'<td style="padding: 10px; font-weight: bold; color: #555555;">Business Justification:</td>'
            f'<td style="padding: 10px; color: #333333;">{self.justification or "N/A"}</td></tr>'
            f'{extra_rows}'
            '</table>'
        )

    def _get_exceptional_review_email_body(self, stage_name):
        self.ensure_one()
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        action_url = f"{base_url}/web#id={self.id}&model={self._name}&view_type=form"
        extra_rows = ""
        if self.people_solutions_assessment:
            extra_rows += (
                '<tr style="border-bottom: 1px solid #EEEEEE; background-color: #F7FAF5;">'
                '<td style="padding: 10px; font-weight: bold; color: #425727;">People Solutions Assessment:</td>'
                f'<td style="padding: 10px; color: #222222;">{self.people_solutions_assessment}</td></tr>'
            )
        if self.cpco_memo:
            extra_rows += (
                '<tr style="border-bottom: 1px solid #EEEEEE; background-color: #FFFBF0;">'
                '<td style="padding: 10px; font-weight: bold; color: #C17540;">CPCO Recommendation Memo:</td>'
                f'<td style="padding: 10px; color: #222222;">{self.cpco_memo}</td></tr>'
            )
        summary_table = self._get_exceptional_summary_table_html(extra_rows=extra_rows)

        return (
            f'<div style="margin: 0px; padding: 0px; font-family: \'Segoe UI\', Roboto, Helvetica, Arial, sans-serif; font-size: 14px; color: #333333;">'
            f'<table border="0" cellpadding="0" cellspacing="0" style="padding-top: 16px; background-color: #F1F1F1; width: 100%;">'
            f'<tr><td align="center">'
            f'<table border="0" cellpadding="0" cellspacing="0" style="padding: 24px; background-color: #FFFFFF; width: 600px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">'
            f'<tr><td style="padding-bottom: 20px; border-bottom: 2.5px solid #C17540;">'
            f'<h2 style="color: #541718; margin: 0; font-weight: 700;">Bunna Bank - Plan &amp; Budget Management System</h2>'
            f'<p style="color: #C17540; margin: 4px 0 0 0; font-size: 13px; font-weight: bold;">Action Required: Exceptional Workforce Request Pending Review ({stage_name})</p>'
            f'</td></tr>'
            f'<tr><td style="padding: 20px 0;">'
            f'<p>Dear Reviewer,</p>'
            f'<p>An <b>Exceptional Workforce Request</b> has progressed to stage <b>{stage_name}</b> and requires your review and action.</p>'
            f'{summary_table}'
            f'<div style="text-align: center; margin: 30px 0;">'
            f'<a href="{action_url}" '
            f'style="background-color: #C17540; color: #FFFFFF; padding: 12px 24px; text-decoration: none; border-radius: 4px; font-weight: bold; display: inline-block;">'
            f'Review Exceptional Request'
            f'</a>'
            f'</div>'
            f'</td></tr>'
            f'<tr><td style="border-top: 1px solid #EEEEEE; padding-top: 15px; font-size: 12px; color: #888888; text-align: center;">'
            f'Bunna Bank S.C. | People &amp; Culture / SPPMD<br/>'
            f'This is an automated system notification from Bunna PBMS.'
            f'</td></tr>'
            f'</table></td></tr></table></div>'
        )

    def _get_exceptional_approved_email_body(self):
        self.ensure_one()
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        action_url = f"{base_url}/web#id={self.id}&model={self._name}&view_type=form"
        extra_rows = ""
        if self.ceo_decision_remarks:
            extra_rows += (
                '<tr style="border-bottom: 1px solid #C8DCB8; background-color: #EDF3E8;">'
                '<td style="padding: 10px; font-weight: bold; color: #425727;">CEO Approval Remarks:</td>'
                f'<td style="padding: 10px; color: #222222; font-weight: bold;">{self.ceo_decision_remarks}</td></tr>'
            )
        if self.recruitment_request_reference:
            extra_rows += (
                '<tr style="border-bottom: 1px solid #C8DCB8; background-color: #EDF3E8;">'
                '<td style="padding: 10px; font-weight: bold; color: #425727;">Recruitment Reference:</td>'
                f'<td style="padding: 10px; color: #541718; font-weight: bold;">{self.recruitment_request_reference}</td></tr>'
            )
        summary_table = self._get_exceptional_summary_table_html(extra_rows=extra_rows)

        return (
            f'<div style="margin: 0px; padding: 0px; font-family: \'Segoe UI\', Roboto, Helvetica, Arial, sans-serif; font-size: 14px; color: #333333;">'
            f'<table border="0" cellpadding="0" cellspacing="0" style="padding-top: 16px; background-color: #F1F1F1; width: 100%;">'
            f'<tr><td align="center">'
            f'<table border="0" cellpadding="0" cellspacing="0" style="padding: 24px; background-color: #FFFFFF; width: 600px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">'
            f'<tr><td style="padding-bottom: 20px; border-bottom: 2.5px solid #425727;">'
            f'<h2 style="color: #541718; margin: 0; font-weight: 700;">Bunna Bank - Plan &amp; Budget Management System</h2>'
            f'<p style="color: #425727; margin: 4px 0 0 0; font-size: 13px; font-weight: bold;">Exceptional Workforce Request Approval Notification</p>'
            f'</td></tr>'
            f'<tr><td style="padding: 20px 0;">'
            f'<p>Dear Colleague / Stakeholder,</p>'
            f'<p>The following <b>Exceptional Workforce Request</b> has been officially <b style="color: #425727;">APPROVED</b> by the Chief Executive Officer (CEO).</p>'
            f'{summary_table}'
            f'<div style="background-color: #EDF3E8; border-left: 4px solid #425727; padding: 12px; margin: 16px 0; border-radius: 4px;">'
            f'<p style="margin: 0; color: #425727; font-weight: bold;">Recruitment Action Auto-Initiated:</p>'
            f'<p style="margin: 4px 0 0 0; color: #333333; font-size: 13px;">This approved requisition has been forwarded to the People Operations &amp; Management Directorate for recruitment processing.</p>'
            f'</div>'
            f'<div style="text-align: center; margin: 30px 0;">'
            f'<a href="{action_url}" '
            f'style="background-color: #425727; color: #FFFFFF; padding: 12px 24px; text-decoration: none; border-radius: 4px; font-weight: bold; display: inline-block;">'
            f'View Approved Request'
            f'</a>'
            f'</div>'
            f'</td></tr>'
            f'<tr><td style="border-top: 1px solid #EEEEEE; padding-top: 15px; font-size: 12px; color: #888888; text-align: center;">'
            f'Bunna Bank S.C. | People &amp; Culture / SPPMD<br/>'
            f'This is an automated system notification from Bunna PBMS.'
            f'</td></tr>'
            f'</table></td></tr></table></div>'
        )

    def _get_exceptional_returned_email_body(self, reason):
        self.ensure_one()
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        action_url = f"{base_url}/web#id={self.id}&model={self._name}&view_type=form"
        feedback_text = reason or self.return_reason or _("Please review feedback and make adjustments.")
        extra_rows = (
            '<tr style="border-bottom: 1px solid #EEEEEE; background-color: #FAF1EB;">'
            '<td style="padding: 10px; font-weight: bold; color: #C17540;">Return Reason / Feedback:</td>'
            f'<td style="padding: 10px; color: #333333; font-style: italic;">{feedback_text}</td></tr>'
        )
        summary_table = self._get_exceptional_summary_table_html(extra_rows=extra_rows)

        return (
            f'<div style="margin: 0px; padding: 0px; font-family: \'Segoe UI\', Roboto, Helvetica, Arial, sans-serif; font-size: 14px; color: #333333;">'
            f'<table border="0" cellpadding="0" cellspacing="0" style="padding-top: 16px; background-color: #F1F1F1; width: 100%;">'
            f'<tr><td align="center">'
            f'<table border="0" cellpadding="0" cellspacing="0" style="padding: 24px; background-color: #FFFFFF; width: 600px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">'
            f'<tr><td style="padding-bottom: 20px; border-bottom: 2.5px solid #C17540;">'
            f'<h2 style="color: #541718; margin: 0; font-weight: 700;">Bunna Bank - Plan &amp; Budget Management System</h2>'
            f'<p style="color: #C17540; margin: 4px 0 0 0; font-size: 13px; font-weight: bold;">Exceptional Workforce Request Returned for Revision</p>'
            f'</td></tr>'
            f'<tr><td style="padding: 20px 0;">'
            f'<p>Dear Initiator / Reviewer,</p>'
            f'<p>Your <b>Exceptional Workforce Request</b> has been <b>returned for revision</b>.</p>'
            f'<div style="background-color: #FAF1EB; border-left: 4px solid #C17540; padding: 14px; margin: 16px 0; border-radius: 4px;">'
            f'<h4 style="margin: 0 0 8px 0; color: #C17540;">Reviewer\'s Feedback / Return Reason:</h4>'
            f'<p style="margin: 0; font-style: italic; color: #333333;">{feedback_text}</p>'
            f'</div>'
            f'{summary_table}'
            f'<p style="margin-top: 16px;">Please make the required adjustments in the PBMS portal and resubmit.</p>'
            f'<div style="text-align: center; margin: 30px 0;">'
            f'<a href="{action_url}" '
            f'style="background-color: #C17540; color: #FFFFFF; padding: 12px 24px; text-decoration: none; border-radius: 4px; font-weight: bold; display: inline-block;">'
            f'Edit &amp; Resubmit Request'
            f'</a>'
            f'</div>'
            f'</td></tr>'
            f'<tr><td style="border-top: 1px solid #EEEEEE; padding-top: 15px; font-size: 12px; color: #888888; text-align: center;">'
            f'Bunna Bank S.C. | People &amp; Culture / SPPMD<br/>'
            f'This is an automated system notification from Bunna PBMS.'
            f'</td></tr>'
            f'</table></td></tr></table></div>'
        )

    def _get_exceptional_rejected_email_body(self, reason):
        self.ensure_one()
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        action_url = f"{base_url}/web#id={self.id}&model={self._name}&view_type=form"
        rej_reason = reason or self.rejection_reason or _("Request has been declined by reviewing authority.")
        extra_rows = (
            '<tr style="border-bottom: 1px solid #EEEEEE; background-color: #FDE8E8;">'
            '<td style="padding: 10px; font-weight: bold; color: #A82020;">Rejection Reason:</td>'
            f'<td style="padding: 10px; color: #A82020; font-weight: bold;">{rej_reason}</td></tr>'
        )
        summary_table = self._get_exceptional_summary_table_html(extra_rows=extra_rows)

        return (
            f'<div style="margin: 0px; padding: 0px; font-family: \'Segoe UI\', Roboto, Helvetica, Arial, sans-serif; font-size: 14px; color: #333333;">'
            f'<table border="0" cellpadding="0" cellspacing="0" style="padding-top: 16px; background-color: #F1F1F1; width: 100%;">'
            f'<tr><td align="center">'
            f'<table border="0" cellpadding="0" cellspacing="0" style="padding: 24px; background-color: #FFFFFF; width: 600px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">'
            f'<tr><td style="padding-bottom: 20px; border-bottom: 2.5px solid #A82020;">'
            f'<h2 style="color: #541718; margin: 0; font-weight: 700;">Bunna Bank - Plan &amp; Budget Management System</h2>'
            f'<p style="color: #A82020; margin: 4px 0 0 0; font-size: 13px; font-weight: bold;">Exceptional Workforce Request Rejection Notification</p>'
            f'</td></tr>'
            f'<tr><td style="padding: 20px 0;">'
            f'<p>Dear Colleague,</p>'
            f'<p>We regret to inform you that your <b>Exceptional Workforce Request</b> has been <b style="color: #A82020;">REJECTED</b>.</p>'
            f'<div style="background-color: #FDE8E8; border-left: 4px solid #A82020; padding: 14px; margin: 16px 0; border-radius: 4px;">'
            f'<h4 style="margin: 0 0 8px 0; color: #A82020;">Reason for Rejection:</h4>'
            f'<p style="margin: 0; color: #333333;">{rej_reason}</p>'
            f'</div>'
            f'{summary_table}'
            f'<div style="text-align: center; margin: 30px 0;">'
            f'<a href="{action_url}" '
            f'style="background-color: #541718; color: #FFFFFF; padding: 12px 24px; text-decoration: none; border-radius: 4px; font-weight: bold; display: inline-block;">'
            f'View Request Details'
            f'</a>'
            f'</div>'
            f'</td></tr>'
            f'<tr><td style="border-top: 1px solid #EEEEEE; padding-top: 15px; font-size: 12px; color: #888888; text-align: center;">'
            f'Bunna Bank S.C. | People &amp; Culture / SPPMD<br/>'
            f'This is an automated system notification from Bunna PBMS.'
            f'</td></tr>'
            f'</table></td></tr></table></div>'
        )

    def _send_exceptional_notification(self, subject, body_html, recipient_users, extra_partners=None):
        self.ensure_one()
        partner_ids = set()
        if recipient_users:
            partner_ids.update(recipient_users.mapped("partner_id").ids)
        if extra_partners:
            partner_ids.update(extra_partners.ids)
        partner_ids.discard(0)
        partner_ids.discard(False)

        # 1. Post Bunna Bank branded template card to chatter (Image 1)
        try:
            self.message_post(
                subject=subject,
                body=Markup(body_html),
                message_type="notification",
                subtype_xmlid="mail.mt_note",
            )
        except Exception as e:
            _logger.warning("Error posting chatter notification for %s: %s", self.name, str(e))

        # 2. Send single branded email directly to partners
        if partner_ids:
            try:
                mail_vals = {
                    "subject": subject,
                    "body_html": body_html,
                    "recipient_ids": [(6, 0, list(partner_ids))],
                    "auto_delete": False,
                }
                mail = self.env["mail.mail"].sudo().create(mail_vals)
                mail.send()
            except Exception as e:
                _logger.warning("Error sending exceptional workforce email for %s: %s", self.name, str(e))

    # -------------------------------------------------------------------------
    # WORKFLOW ACTIONS
    # -------------------------------------------------------------------------
    def action_submit(self):
        """District Reviewer initiates and submits request to People Solutions Directorate."""
        user = self.env.user
        is_admin = user._pbms_is_sppmd_admin() or user._pbms_is_manager() or self.env.is_admin() or self.env.su
        for rec in self:
            if not (user._pbms_is_district_reviewer() or rec.initiator_id == user or rec.create_uid == user or is_admin):
                raise AccessError(_("Only the District Reviewer or initiator can submit this exceptional workforce request."))
            if rec.state not in ("draft", "returned"):
                raise UserError(_("You can only submit requests in Draft or Returned stage."))
            if not rec.job_id:
                raise ValidationError(_("Please specify the Position / Job Title before submitting."))
            if not rec.justification:
                raise ValidationError(_("Business Justification is required before submitting the exceptional request."))

            rec.with_context(bypass_workforce_lock=True).write({
                "state": "people_solutions",
            })
            users = self._get_group_users("bunna_pbms.group_pbms_people_solutions")
            for u in users:
                rec.with_context(mail_activity_quick_update=True).activity_schedule(
                    activity_type_id=self.env.ref("mail.mail_activity_data_todo").id,
                    summary=_("Exceptional Workforce Request Review: %s") % rec.name,
                    note=_("Exceptional request for %s position(s) of '%s' submitted for assessment.") % (rec.headcount, rec.job_id.name),
                    user_id=u.id,
                )
            # Dispatch branded Bunna Bank notification
            subject = _("Action Required: Exceptional Workforce Request Pending Review - %s (%s)") % (
                rec.name, rec.operating_unit_id.display_name if rec.operating_unit_id else ""
            )
            body = rec._get_exceptional_review_email_body(_("People Solutions Review"))
            rec._send_exceptional_notification(subject, body, users)

    def action_people_solutions_escalate(self):
        """People Solutions Directorate reviews and assesses the request, escalates to CPCO."""
        user = self.env.user
        is_admin = user._pbms_is_sppmd_admin() or user._pbms_is_manager() or self.env.is_admin() or self.env.su
        for rec in self:
            if not (user._pbms_is_people_solutions() or is_admin):
                raise AccessError(_("Only People Solutions Directorate officers or Administrators can assess and escalate this request."))
            if rec.state != "people_solutions":
                raise UserError(_("Request is not in People Solutions Review stage."))
            if not rec.sourcing_type:
                raise ValidationError(_("Please select the Sourcing Type (Internal, External, or Both) before escalating this request to CPCO."))

            rec.with_context(bypass_workforce_lock=True).write({
                "state": "cpco_review",
                "people_solutions_reviewer_id": self.env.uid,
                "people_solutions_review_date": fields.Datetime.now(),
            })
            users = self._get_group_users("bunna_pbms.group_pbms_cpco")
            for u in users:
                rec.with_context(mail_activity_quick_update=True).activity_schedule(
                    activity_type_id=self.env.ref("mail.mail_activity_data_todo").id,
                    summary=_("CPCO Review: Exceptional Workforce Request %s") % rec.name,
                    note=_("Please prepare and submit memo to the CEO for '%s' (%s positions).") % (rec.job_id.name, rec.headcount),
                    user_id=u.id,
                )
            # Dispatch branded Bunna Bank notification
            subject = _("Action Required: Exceptional Workforce Request Pending Review (CPCO Review) - %s (%s)") % (
                rec.name, rec.operating_unit_id.display_name if rec.operating_unit_id else ""
            )
            body = rec._get_exceptional_review_email_body(_("CPCO Review"))
            rec._send_exceptional_notification(subject, body, users)

    def action_people_solutions_return(self, reason=False):
        """People Solutions returns request to District Reviewer for revision."""
        user = self.env.user
        is_admin = user._pbms_is_sppmd_admin() or user._pbms_is_manager() or self.env.is_admin() or self.env.su
        for rec in self:
            if not (user._pbms_is_people_solutions() or is_admin):
                raise AccessError(_("Only People Solutions Directorate officers or Administrators can return this request."))
            if rec.state != "people_solutions":
                raise UserError(_("Request is not in People Solutions Review stage."))
            feedback = reason or rec.return_reason or _("Please revise and resubmit.")
            rec.with_context(bypass_workforce_lock=True).write({
                "state": "returned",
                "return_reason": feedback,
            })
            target_user = rec.initiator_id or (rec.create_uid if rec.create_uid else False)
            if target_user:
                rec.with_context(mail_activity_quick_update=True).activity_schedule(
                    activity_type_id=self.env.ref("mail.mail_activity_data_todo").id,
                    summary=_("Exceptional Request Returned for Revision: %s") % rec.name,
                    note=_("Request returned by People Solutions for revision: %s") % feedback,
                    user_id=target_user.id,
                )
            # Dispatch branded return notification
            subject = _("Revision Required: Exceptional Workforce Request Returned - %s (%s)") % (
                rec.name, rec.operating_unit_id.display_name if rec.operating_unit_id else ""
            )
            body = rec._get_exceptional_returned_email_body(feedback)
            rec._send_exceptional_notification(subject, body, target_user)

    def action_people_solutions_reject(self, reason=False):
        """People Solutions rejects the request."""
        user = self.env.user
        is_admin = user._pbms_is_sppmd_admin() or user._pbms_is_manager() or self.env.is_admin() or self.env.su
        for rec in self:
            if not (user._pbms_is_people_solutions() or is_admin):
                raise AccessError(_("Only People Solutions Directorate officers or Administrators can reject this request."))
            if rec.state != "people_solutions":
                raise UserError(_("Request is not in People Solutions Review stage."))
            rej_reason = reason or rec.rejection_reason or _("Rejected during People Solutions assessment.")
            rec.with_context(bypass_workforce_lock=True).write({
                "state": "rejected",
                "rejection_reason": rej_reason,
            })
            target_user = rec.initiator_id or (rec.create_uid if rec.create_uid else False)
            # Dispatch branded rejection notification
            subject = _("Exceptional Workforce Request Rejected - %s (%s)") % (
                rec.name, rec.operating_unit_id.display_name if rec.operating_unit_id else ""
            )
            body = rec._get_exceptional_rejected_email_body(rej_reason)
            rec._send_exceptional_notification(subject, body, target_user)

    def action_cpco_submit_memo(self):
        """CPCO prepares and submits memo with justification/recommendation to the CEO."""
        user = self.env.user
        is_admin = user._pbms_is_sppmd_admin() or user._pbms_is_manager() or self.env.is_admin() or self.env.su
        for rec in self:
            if not (user._pbms_is_cpco() or is_admin):
                raise AccessError(_("Only CPCO (Chief of People & Culture Office) or Administrators can submit memo to the CEO."))
            if rec.state != "cpco_review":
                raise UserError(_("Request is not in CPCO Review stage."))
            if not rec.cpco_memo:
                raise ValidationError(_("Please provide the CPCO Recommendation Memo to the CEO before submitting."))

            rec.with_context(bypass_workforce_lock=True).write({
                "state": "ceo_review",
                "cpco_reviewer_id": self.env.uid,
                "cpco_submission_date": fields.Datetime.now(),
            })
            users = self._get_group_users("bunna_pbms.group_pbms_ceo")
            for u in users:
                rec.with_context(mail_activity_quick_update=True).activity_schedule(
                    activity_type_id=self.env.ref("mail.mail_activity_data_todo").id,
                    summary=_("CEO Decision Required: Exceptional Workforce Request %s") % rec.name,
                    note=_("Memo submitted by CPCO for '%s' (%s positions). Please review and approve/reject.") % (rec.job_id.name, rec.headcount),
                    user_id=u.id,
                )
            # Dispatch branded notification
            subject = _("Action Required: Exceptional Workforce Request Pending Approval (CEO Review) - %s (%s)") % (
                rec.name, rec.operating_unit_id.display_name if rec.operating_unit_id else ""
            )
            body = rec._get_exceptional_review_email_body(_("Pending CEO Approval"))
            rec._send_exceptional_notification(subject, body, users)

    def action_cpco_return(self, reason=False):
        """CPCO returns request to People Solutions for revision."""
        user = self.env.user
        is_admin = user._pbms_is_sppmd_admin() or user._pbms_is_manager() or self.env.is_admin() or self.env.su
        for rec in self:
            if not (user._pbms_is_cpco() or is_admin):
                raise AccessError(_("Only CPCO officers or Administrators can return this request."))
            if rec.state != "cpco_review":
                raise UserError(_("Request is not in CPCO Review stage."))
            feedback = reason or rec.return_reason or _("Please revise assessment/justification.")
            rec.with_context(bypass_workforce_lock=True).write({
                "state": "people_solutions",
                "return_reason": feedback,
            })
            users = self._get_group_users("bunna_pbms.group_pbms_people_solutions")
            for u in users:
                rec.with_context(mail_activity_quick_update=True).activity_schedule(
                    activity_type_id=self.env.ref("mail.mail_activity_data_todo").id,
                    summary=_("Exceptional Request Returned by CPCO: %s") % rec.name,
                    note=_("CPCO returned request for revision: %s") % feedback,
                    user_id=u.id,
                )
            # Dispatch branded return notification
            subject = _("Revision Required: Exceptional Workforce Request Returned by CPCO - %s (%s)") % (
                rec.name, rec.operating_unit_id.display_name if rec.operating_unit_id else ""
            )
            body = rec._get_exceptional_returned_email_body(feedback)
            rec._send_exceptional_notification(subject, body, users)

    def action_cpco_reject(self, reason=False):
        """CPCO rejects the request."""
        user = self.env.user
        is_admin = user._pbms_is_sppmd_admin() or user._pbms_is_manager() or self.env.is_admin() or self.env.su
        for rec in self:
            if not (user._pbms_is_cpco() or is_admin):
                raise AccessError(_("Only CPCO officers or Administrators can reject this request."))
            if rec.state != "cpco_review":
                raise UserError(_("Request is not in CPCO Review stage."))
            rej_reason = reason or rec.rejection_reason or _("Rejected during CPCO review.")
            rec.with_context(bypass_workforce_lock=True).write({
                "state": "rejected",
                "rejection_reason": rej_reason,
            })
            target_users = self.env["res.users"]
            if rec.initiator_id:
                target_users |= rec.initiator_id
            if rec.create_uid:
                target_users |= rec.create_uid
            target_users |= self._get_group_users("bunna_pbms.group_pbms_people_solutions")
            # Dispatch branded rejection notification
            subject = _("Exceptional Workforce Request Rejected by CPCO - %s (%s)") % (
                rec.name, rec.operating_unit_id.display_name if rec.operating_unit_id else ""
            )
            body = rec._get_exceptional_rejected_email_body(rej_reason)
            rec._send_exceptional_notification(subject, body, target_users)

    def action_ceo_approve(self, remarks=False):
        """CEO views, edits, and approves request.
        Decision is recorded & notified to CPCO.
        Recruitment action is automatically triggered for People Operations & Management Directorate.
        """
        user = self.env.user
        is_admin = user._pbms_is_sppmd_admin() or user._pbms_is_manager() or self.env.is_admin() or self.env.su
        for rec in self:
            if not (user._pbms_is_ceo() or is_admin):
                raise AccessError(_("Only the Chief Executive Officer (CEO) or Administrators can approve this request."))
            if rec.state != "ceo_review":
                raise UserError(_("Request is not in Pending CEO Approval stage."))

            approval_remarks = remarks or rec.ceo_decision_remarks or _("Approved by CEO.")
            rec.with_context(bypass_workforce_lock=True).write({
                "state": "approved",
                "ceo_decision": "approved",
                "ceo_approver_id": user.id,
                "ceo_decision_recorded_by": user.id,
                "ceo_decision_date": fields.Datetime.now(),
                "ceo_decision_remarks": approval_remarks,
            })

            # Record/affect in CPCO: Notify CPCO team of approval
            cpco_users = self._get_group_users("bunna_pbms.group_pbms_cpco")
            for u in cpco_users:
                rec.with_context(mail_activity_quick_update=True).activity_schedule(
                    activity_type_id=self.env.ref("mail.mail_activity_data_todo").id,
                    summary=_("CEO Decision: Approved - %s") % rec.name,
                    note=_(
                        "The CEO has APPROVED exceptional workforce request %s for '%s' (%s positions).<br/>Remarks: %s"
                    ) % (rec.name, rec.job_id.name, rec.headcount, approval_remarks),
                    user_id=u.id,
                )

            # Affect People Operations & Management Directorate: auto-initiate recruitment
            rec._auto_initiate_recruitment()

            # Target users for approval email: CPCO, People Operations, and Initiator
            stakeholder_users = cpco_users | self._get_group_users("bunna_pbms.group_pbms_people_operations")
            if rec.initiator_id:
                stakeholder_users |= rec.initiator_id
            if rec.create_uid:
                stakeholder_users |= rec.create_uid

            subject = _("Exceptional Workforce Request Approved: %s - %s (%s)") % (
                rec.name, rec.job_id.name if rec.job_id else "", rec.operating_unit_id.display_name if rec.operating_unit_id else ""
            )
            body = rec._get_exceptional_approved_email_body()
            rec._send_exceptional_notification(subject, body, stakeholder_users)

    def action_ceo_reject(self, reason=False):
        """CEO views, edits, and rejects request.
        Decision is recorded & notified to CPCO.
        """
        user = self.env.user
        is_admin = user._pbms_is_sppmd_admin() or user._pbms_is_manager() or self.env.is_admin() or self.env.su
        for rec in self:
            if not (user._pbms_is_ceo() or is_admin):
                raise AccessError(_("Only the Chief Executive Officer (CEO) or Administrators can reject this request."))
            if rec.state != "ceo_review":
                raise UserError(_("Request is not in Pending CEO Approval stage."))

            rej_reason = reason or rec.rejection_reason or rec.ceo_decision_remarks or _("Rejected by CEO.")
            rec.with_context(bypass_workforce_lock=True).write({
                "state": "rejected",
                "ceo_decision": "rejected",
                "ceo_approver_id": user.id,
                "ceo_decision_recorded_by": user.id,
                "ceo_decision_date": fields.Datetime.now(),
                "rejection_reason": rej_reason,
            })

            # Record/affect in CPCO: Notify CPCO team of rejection
            cpco_users = self._get_group_users("bunna_pbms.group_pbms_cpco")
            for u in cpco_users:
                rec.with_context(mail_activity_quick_update=True).activity_schedule(
                    activity_type_id=self.env.ref("mail.mail_activity_data_todo").id,
                    summary=_("CEO Decision: Rejected - %s") % rec.name,
                    note=_(
                        "The CEO has REJECTED exceptional workforce request %s for '%s'.<br/>Reason: %s"
                    ) % (rec.name, rec.job_id.name, rej_reason),
                    user_id=u.id,
                )

            stakeholder_users = cpco_users | self._get_group_users("bunna_pbms.group_pbms_people_solutions")
            if rec.initiator_id:
                stakeholder_users |= rec.initiator_id
            if rec.create_uid:
                stakeholder_users |= rec.create_uid

            subject = _("Exceptional Workforce Request Rejected by CEO: %s - %s (%s)") % (
                rec.name, rec.job_id.name if rec.job_id else "", rec.operating_unit_id.display_name if rec.operating_unit_id else ""
            )
            body = rec._get_exceptional_rejected_email_body(rej_reason)
            rec._send_exceptional_notification(subject, body, stakeholder_users)

    def action_record_ceo_approval(self, remarks=False):
        """Alias for action_ceo_approve."""
        return self.action_ceo_approve(remarks=remarks)

    def action_record_ceo_rejection(self, reason=False):
        """Alias for action_ceo_reject."""
        return self.action_ceo_reject(reason=reason)

    def action_return(self, comment=False):
        """Generic return router."""
        for rec in self:
            if rec.state == "people_solutions":
                rec.action_people_solutions_return(comment)
            elif rec.state == "cpco_review":
                rec.action_cpco_return(comment)
            else:
                raise UserError(_("Cannot return request from current stage %s.") % rec.state)

    def action_reject(self, reason=False):
        """Generic reject router."""
        for rec in self:
            if rec.state == "people_solutions":
                rec.action_people_solutions_reject(reason)
            elif rec.state == "cpco_review":
                rec.action_cpco_reject(reason)
            elif rec.state == "ceo_review":
                rec.action_ceo_reject(reason)
            else:
                raise UserError(_("Cannot reject request from current stage %s.") % rec.state)

    def _auto_initiate_recruitment(self):
        """System auto-initiates a vacancy request and routes it to People Operations & Management Directorate."""
        self.ensure_one()
        RecruitmentRequest = self.env.get("recruitment.request")
        req_ref = False
        req_id = False

        if RecruitmentRequest is not None:
            try:
                requested_by = False
                if self.initiator_id.employee_id:
                    requested_by = self.initiator_id.employee_id.id
                elif self.env.user.employee_id:
                    requested_by = self.env.user.employee_id.id
                else:
                    emp = self.env["hr.employee"].search([("user_id", "=", self.initiator_id.id)], limit=1)
                    if emp:
                        requested_by = emp.id

                dept_id = self.department_id.id if self.department_id else False
                if not dept_id and self.operating_unit_id and hasattr(self.operating_unit_id, "department_id") and self.operating_unit_id.department_id:
                    dept_id = self.operating_unit_id.department_id.id
                if not dept_id:
                    default_dept = self.env["hr.department"].search([], limit=1)
                    if default_dept:
                        dept_id = default_dept.id

                vals = {
                    "request_type": "unplanned",
                    "operating_unit_id": self.operating_unit_id.id,
                    "department_id": dept_id,
                    "job_position_id": self.job_id.id,
                    "job_grade_id": self.job_grade_id.id if self.job_grade_id else (self.job_id.grade.id if hasattr(self.job_id, "grade") and self.job_id.grade else False),
                    "required_headcount": self.headcount,
                    "employment_type": self.employment_type,
                    "sourcing_type": self.sourcing_type,
                    "justification": _("[Exceptional Request %s] %s") % (self.name, self.justification),
                    "requested_by": requested_by,
                    "state": "under_review",
                }

                rec_req = RecruitmentRequest.sudo().create(vals)
                req_ref = rec_req.reference
                req_id = rec_req.id
                self.write({
                    "recruitment_request_id": req_id,
                    "recruitment_request_reference": req_ref,
                })
                self.message_post(
                    body=_(
                        "<b>Recruitment Action Auto-Initiated:</b><br/>"
                        "Unplanned Recruitment Request <b>%s</b> created and routed to People Operations &amp; Management Directorate."
                    ) % req_ref
                )
            except Exception as e:
                _logger.warning("Could not auto-create recruitment.request record: %s", str(e))
                self.message_post(
                    body=_("<b>Notice:</b> Automated vacancy request generation encountered an issue: %s. Routed to People Operations for manual creation.") % str(e)
                )

        users = self._get_group_users("bunna_pbms.group_pbms_people_operations")
        if not users:
            users = self._get_group_users("bunna_pbms.group_pbms_manager")
        for u in users:
            self.with_context(mail_activity_quick_update=True).activity_schedule(
                activity_type_id=self.env.ref("mail.mail_activity_data_todo").id,
                summary=_("Recruitment Action: %s (%s)") % (self.name, self.job_id.name),
                note=_(
                    "Exceptional workforce request %s approved by CEO.<br/>"
                    "• Position: %s<br/>"
                    "• Headcount: %s<br/>"
                    "• Work Unit: %s<br/>"
                    "Please proceed with vacancy publishing and recruitment action."
                ) % (self.name, self.job_id.name, self.headcount, self.operating_unit_id.display_name),
                user_id=u.id,
            )

    def action_view_recruitment_request(self):
        self.ensure_one()
        RecruitmentRequest = self.env.get("recruitment.request")
        if RecruitmentRequest is not None and (self.recruitment_request_id or self.recruitment_request_reference):
            req = False
            if self.recruitment_request_id:
                req = RecruitmentRequest.browse(self.recruitment_request_id)
            if not req or not req.exists():
                req = RecruitmentRequest.search([("reference", "=", self.recruitment_request_reference)], limit=1)
            if req and req.exists():
                return {
                    "type": "ir.actions.act_window",
                    "name": _("Linked Recruitment Request"),
                    "res_model": "recruitment.request",
                    "res_id": req.id,
                    "view_mode": "form",
                    "target": "current",
                }
        raise UserError(_("No linked recruitment request found or recruitment module is not installed."))

    @api.model
    def _get_group_users(self, group_xmlid):
        group = self.env.ref(group_xmlid, raise_if_not_found=False)
        if not group:
            return self.env["res.users"]
        users = self.env["res.users"]
        if hasattr(group, "user_ids") and group.user_ids:
            users |= group.user_ids.filtered(lambda u: u.active)
        if hasattr(group, "users") and group.users:
            users |= group.users.filtered(lambda u: u.active)
        if not users:
            try:
                users = self.env["res.users"].search([
                    ("all_group_ids", "in", group.id),
                    ("active", "=", True),
                ])
            except Exception:
                users = self.env["res.users"].search([("active", "=", True)]).filtered(lambda u: u.has_group(group_xmlid))
        return users

    @api.model
    def _get_ceo_user(self):
        Config = self.env.get("pbms.planning.config")
        if Config is not None:
            cfg = Config.sudo().search([("ceo_user_id", "!=", False)], limit=1)
            if cfg and cfg.ceo_user_id:
                return cfg.ceo_user_id
        ceo_users = self._get_group_users("bunna_pbms.group_pbms_ceo")
        return ceo_users[0] if ceo_users else False

    @api.model
    def fields_get(self, allfields=None, attributes=None):
        res = super().fields_get(allfields=allfields, attributes=attributes)
        if "activity_ids" in res:
            res["activity_ids"]["exportable"] = False
        return res

    def export_data(self, fields_to_export):
        """Exclude activity_ids from export data to prevent multi-line activity spam in Excel/CSV."""
        clean_fields = [f for f in fields_to_export if not f.startswith("activity_ids")]
        return super().export_data(clean_fields if clean_fields else fields_to_export)

    def action_export_excel(self):
        """Export exceptional workforce requests to Excel (.xlsx) with official Bunna Bank branding."""
        import base64
        import io
        try:
            import xlsxwriter
        except ImportError:
            raise UserError(_("The 'xlsxwriter' Python library is required. Please install it on the server."))

        records = self
        if not records:
            active_ids = self.env.context.get("active_ids")
            if active_ids:
                records = self.browse(active_ids)
            else:
                active_id = self.env.context.get("active_id")
                if active_id:
                    records = self.browse([active_id])
                else:
                    records = self.search([], limit=1000)

        if not records:
            raise UserError(_("No exceptional workforce requests selected for export."))

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {"in_memory": True})
        ws = wb.add_worksheet("Exceptional Workforce")
        ws.freeze_panes(6, 4)

        # Base formatting matching Bunna Bank brand guidelines (#541718)
        fmt_bank_title = wb.add_format({
            "bold": True, "font_size": 14, "font_color": "#541718", "font_name": "Segoe UI",
            "align": "center", "valign": "vcenter"
        })
        fmt_doc_title = wb.add_format({
            "bold": True, "font_size": 12, "font_color": "#541718", "font_name": "Segoe UI",
            "align": "center", "valign": "vcenter"
        })
        fmt_fy_title = wb.add_format({
            "bold": True, "font_size": 11, "font_color": "#541718", "font_name": "Segoe UI",
            "align": "center", "valign": "vcenter"
        })
        fmt_th = wb.add_format({
            "bold": True, "bg_color": "#541718", "font_color": "#FFFFFF",
            "font_size": 10, "font_name": "Segoe UI", "align": "center", "valign": "vcenter",
            "text_wrap": True, "border": 1, "border_color": "#3D1011"
        })
        fmt_cell_text = wb.add_format({
            "font_size": 9, "font_name": "Segoe UI", "valign": "vcenter",
            "border": 1, "border_color": "#D9D9D9"
        })
        fmt_cell_int = wb.add_format({
            "font_size": 9, "font_name": "Segoe UI", "valign": "vcenter", "align": "right",
            "num_format": "#,##0", "border": 1, "border_color": "#D9D9D9"
        })
        fmt_cell_date = wb.add_format({
            "font_size": 9, "font_name": "Segoe UI", "valign": "vcenter", "align": "center",
            "border": 1, "border_color": "#D9D9D9"
        })
        fmt_tot_label = wb.add_format({
            "bold": True, "bg_color": "#541718", "font_color": "#FFFFFF",
            "font_size": 10, "font_name": "Segoe UI", "valign": "vcenter", "align": "left",
            "border": 1, "border_color": "#3D1011"
        })
        fmt_tot_int = wb.add_format({
            "bold": True, "bg_color": "#541718", "font_color": "#FFFFFF",
            "font_size": 10, "font_name": "Segoe UI", "valign": "vcenter", "align": "right",
            "num_format": "#,##0", "border": 1, "border_color": "#3D1011"
        })

        # Bunna Title Banner
        ws.merge_range(0, 0, 0, 11, "Bunna Bank S.C.", fmt_bank_title)
        ws.merge_range(1, 0, 1, 11, "Plan & Budget Management System (PBMS)", fmt_doc_title)
        ws.merge_range(2, 0, 2, 11, "Exceptional Workforce Requests Report", fmt_fy_title)

        headers = [
            "Request #", "Request Date", "Initiator", "Initiator Role",
            "Branch / Work Unit", "Department", "Position / Job Title",
            "Job Grade", "Required Headcount", "Employment Type",
            "Sourcing Type", "Status"
        ]
        for ci, h in enumerate(headers):
            ws.write(5, ci, h, fmt_th)

        row_cur = 6
        role_labels = dict(self._fields["initiator_role"].selection)
        emp_labels = dict(self._fields["employment_type"].selection)
        sourcing_labels = dict(self._fields["sourcing_type"].selection)
        state_labels = dict(self._fields["state"].selection)

        for rec in records:
            ws.write(row_cur, 0, rec.name or "", fmt_cell_text)
            ws.write(row_cur, 1, str(rec.request_date) if rec.request_date else "", fmt_cell_date)
            ws.write(row_cur, 2, rec.initiator_id.name if rec.initiator_id else "", fmt_cell_text)
            ws.write(row_cur, 3, role_labels.get(rec.initiator_role, rec.initiator_role or ""), fmt_cell_text)
            ws.write(row_cur, 4, rec.operating_unit_id.display_name if rec.operating_unit_id else "", fmt_cell_text)
            ws.write(row_cur, 5, rec.department_id.name if rec.department_id else "", fmt_cell_text)
            ws.write(row_cur, 6, rec.job_id.name if rec.job_id else "", fmt_cell_text)
            grade_name = (rec.job_grade_id.display_name or rec.job_grade_id.grade_name or rec.job_grade_id.grade_code or "") if rec.job_grade_id else ""
            ws.write(row_cur, 7, grade_name, fmt_cell_text)
            ws.write(row_cur, 8, rec.headcount or 0, fmt_cell_int)
            ws.write(row_cur, 9, emp_labels.get(rec.employment_type, rec.employment_type or ""), fmt_cell_text)
            ws.write(row_cur, 10, sourcing_labels.get(rec.sourcing_type, rec.sourcing_type or ""), fmt_cell_text)
            ws.write(row_cur, 11, state_labels.get(rec.state, rec.state or ""), fmt_cell_text)
            row_cur += 1

        # Totals Row
        ws.write(row_cur, 0, "TOTAL", fmt_tot_label)
        for ci in range(1, 8):
            ws.write(row_cur, ci, "", fmt_tot_label)
        if row_cur > 6:
            ws.write_formula(row_cur, 8, f"=SUM(I7:I{row_cur})", fmt_tot_int)
        else:
            ws.write(row_cur, 8, 0, fmt_tot_int)
        for ci in range(9, 12):
            ws.write(row_cur, ci, "", fmt_tot_label)

        # Auto column widths
        ws.set_column(0, 0, 16)
        ws.set_column(1, 1, 14)
        ws.set_column(2, 2, 20)
        ws.set_column(3, 3, 18)
        ws.set_column(4, 4, 24)
        ws.set_column(5, 5, 22)
        ws.set_column(6, 6, 26)
        ws.set_column(7, 7, 14)
        ws.set_column(8, 8, 18)
        ws.set_column(9, 9, 16)
        ws.set_column(10, 10, 16)
        ws.set_column(11, 11, 18)

        wb.close()
        output.seek(0)
        file_data = output.getvalue()

        file_name = "Bunna_Bank_Exceptional_Workforce_Requests.xlsx"
        attachment = self.env["ir.attachment"].create({
            "name": file_name,
            "type": "binary",
            "datas": base64.b64encode(file_data),
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        })
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

