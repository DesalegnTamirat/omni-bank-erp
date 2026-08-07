# -*- coding: utf-8 -*-
# Acting / Supplementary Role – Module 2 BRD Requirements:
#     Acting Role Request & District Director Approval Workflow
#     Automated Employee Profile & Benefit Adjustment
#     Acting Assignment Expiry & Termination Notification Workflow

from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class ActingRoleAssignment(models.Model):
    """: Acting / Supplementary Role assignment.

    Distinct from a permanent Transfer/Promotion: this is a temporary
    assignment to a vacant post, approved by the District Director, with
    automatic benefit adjustment and automatic reversion when the acting
    period ends or a permanent candidate is placed.
    """
    _name = "acting.role.assignment"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Acting / Supplementary Role Assignment "
    _rec_name = "name"
    _order = "request_date desc"

    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({"active": False})
        return True

    name = fields.Char(string="Reference", copy=False, readonly=True, default=lambda self: _("New"))

    # : Request Initiation ----------------------
    employee_id = fields.Many2one(
        "hr.employee", string="Acting Employee", required=True, tracking=True,
        help="The employee proposed to temporarily fill the vacant post.",
    )
    requested_by = fields.Many2one(
        "res.users", string="Requested By", default=lambda self: self.env.user, readonly=True,
    )
    request_date = fields.Date(string="Request Date", default=fields.Date.context_today, required=True)

    target_vacancy_id = fields.Many2one(
        "job.vacancy", string="Vacant Post", required=True,
        help="The vacant post the employee will act in .",
    )
    target_job_position_id = fields.Many2one(
        "hr.job", string="Acting Position", related="target_vacancy_id.job_position", store=True, readonly=True,
    )
    target_operating_unit_id = fields.Many2one(
        "operating.unit", string="Work Unit / Branch",
        related="target_vacancy_id.operating_unit_id", store=True, readonly=True,
    )

    # : District Director Approval Workflow --------------
    district_director_id = fields.Many2one(
        "hr.employee", string="District Director",
        help="The District Director responsible for reviewing this Acting Role request.",
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("active", "Active"),
            ("expired", "Expired / Terminated"),
        ],
        string="Status", default="draft", tracking=True, copy=False,
    )
    approval_date = fields.Date(string="Approval Date", readonly=True, copy=False)
    rejection_reason = fields.Text(string="Rejection Reason")

    # : Automated Employee Profile & Benefit Adjustment --------
    acting_allowance_percent = fields.Float(
        string="Acting Allowance (%)",
        help="Percentage of the target position's pay used to compute the Acting Allowance .",
    )
    acting_allowance_amount = fields.Float(
        string="Acting Allowance Amount", compute="_compute_acting_allowance", store=True,
    )
    # Snapshot of the employee's substantive (permanent) position, captured at
    # approval time, so the system can automatically revert to it on expiry.
    substantive_job_position_id = fields.Many2one(
        "hr.job", string="Substantive (Original) Position", readonly=True, copy=False,
    )
    substantive_operating_unit_id = fields.Many2one(
        "operating.unit", string="Substantive (Original) Work Unit", readonly=True, copy=False,
    )

    # : Expiry & Termination -----------------------
    acting_start_date = fields.Date(string="Acting Start Date")
    acting_end_date = fields.Date(
        string="Acting End Date",
        help="Planned end date of the acting period. The system alerts HR when this date is reached, "
             "a permanent candidate is assigned, or termination is initiated .",
    )
    permanent_candidate_assigned = fields.Boolean(
        string="Permanent Candidate Assigned", default=False,
        help="Set to True once a permanent placement (Transfer/Promotion/External Hire) has filled the post, "
             "which also triggers automatic termination of the acting assignment .",
    )
    expiry_notified = fields.Boolean(string="Expiry Notification Sent", default=False, copy=False)
    termination_date = fields.Date(string="Termination Date", readonly=True, copy=False)

    # ---------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("acting.role.assignment") or _("New")
        return super().create(vals_list)

    @api.depends("acting_allowance_percent", "target_vacancy_id")
    def _compute_acting_allowance(self):
        for rec in self:
            base_pay = 0.0
            try:
                base_pay = rec.target_vacancy_id.job_position.contract_ids[:1].wage or 0.0
            except Exception:
                base_pay = 0.0
            rec.acting_allowance_amount = round(base_pay * (rec.acting_allowance_percent or 0.0) / 100.0, 2)

    # ---------------------------------------
    # Workflow Actions
    # ---------------------------------------
    def action_submit(self):
        """: route the Acting Role request to the District Director."""
        for rec in self:
            if not rec.target_vacancy_id:
                raise ValidationError(_("Please select a vacant post before submitting."))
            if not rec.district_director_id:
                raise ValidationError(_("Please select the District Director responsible for approval."))
            rec.state = "submitted"
            rec.message_post(
                body=_("Acting Role request submitted to District Director %s for review.")
                % rec.district_director_id.name
            )

    def action_approve(self):
        """ / : District Director approves; system automatically
        updates the employee's profile data and computes Acting Benefits."""
        for rec in self:
            if rec.state != "submitted":
                raise UserError(_("Only submitted requests can be approved."))

            emp = rec.employee_id
            # Snapshot substantive position so it can be restored on expiry.
            rec.write({
                "substantive_job_position_id": emp.job_position if emp else False,
                "substantive_operating_unit_id": emp.default_operating_unit_id if emp else False,
                "state": "approved",
                "approval_date": fields.Date.context_today(rec),
            })

            # : Automated Employee Profile & Benefit Adjustment
            if emp:
                emp_vals = {}
                if rec.target_job_position_id:
                    emp_vals["job_position"] = rec.target_job_position_id.id
                if rec.target_operating_unit_id:
                    emp_vals["default_operating_unit_id"] = rec.target_operating_unit_id.id
                if emp_vals:
                    emp.write(emp_vals)

            rec.state = "active"
            rec.message_post(
                body=_(
                    "Acting Role assignment approved by District Director. Employee profile updated to "
                    "reflect the supplementary position. Acting Allowance: %.2f."
                ) % rec.acting_allowance_amount
            )

    def action_reject(self):
        """: District Director rejects the Acting Role request."""
        for rec in self:
            if rec.state != "submitted":
                raise UserError(_("Only submitted requests can be rejected."))
            rec.state = "rejected"
            rec.message_post(body=_("Acting Role request rejected. Reason: %s") % (rec.rejection_reason or _("N/A")))

    def action_terminate(self):
        """: HR finalizes termination — revert employee profile, benefits,
        and system access to the substantive position."""
        for rec in self:
            if rec.state != "active":
                raise UserError(_("Only Active acting assignments can be terminated."))

            emp = rec.employee_id
            if emp:
                emp_vals = {}
                if rec.substantive_job_position_id:
                    emp_vals["job_position"] = rec.substantive_job_position_id.id
                if rec.substantive_operating_unit_id:
                    emp_vals["default_operating_unit_id"] = rec.substantive_operating_unit_id.id
                if emp_vals:
                    emp.write(emp_vals)

            rec.write({
                "state": "expired",
                "termination_date": fields.Date.context_today(rec),
            })
            rec.message_post(
                body=_(
                    "Acting Role assignment terminated. Employee profile, benefits, and access rights "
                    "reverted to the substantive position ."
                )
            )

    # ---------------------------------------
    # Scheduled Actions / Cron
    # ---------------------------------------
    @api.model
    def _cron_check_acting_role_expiry(self):
        """: track acting period duration and alert HR when the end
        date is reached or a permanent candidate has been assigned."""
        today = date.today()

        # Alert HR when the planned end date is reached (not yet notified).
        due = self.search([
            ("state", "=", "active"),
            ("acting_end_date", "<=", today),
            ("expiry_notified", "=", False),
        ])
        for rec in due:
            rec.expiry_notified = True
            hr_group = self.env.ref("hr.group_hr_user", raise_if_not_found=False)
            body = _(
                "Acting Role assignment <b>%(ref)s</b> for <b>%(employee)s</b> in "
                "<b>%(position)s</b> has reached its planned end date (%(end_date)s). "
                "Please finalize termination or extend the assignment ."
            ) % {
                "ref": rec.name,
                "employee": rec.employee_id.name,
                "position": rec.target_job_position_id.name if rec.target_job_position_id else "",
                "end_date": rec.acting_end_date,
            }
            rec.message_post(body=body)

        # Auto-terminate when a permanent candidate has been assigned.
        auto_terminate = self.search([
            ("state", "=", "active"),
            ("permanent_candidate_assigned", "=", True),
        ])
        for rec in auto_terminate:
            rec.action_terminate
