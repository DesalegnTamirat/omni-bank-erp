# -*- coding: utf-8 -*-

from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

DISCIPLINE_SELECTION = [
    ("none", "No Active Warning"),
    ("first_warning", "First Warning"),
    ("second_warning", "Second Warning"),
    ("last_written_warning", "Active Last Written Warning"),
]

DISCIPLINE_DEDUCTION = {
    "none": 0.0,
    "first_warning": 5.0,
    "second_warning": 10.0,
    "last_written_warning": 0.0,  # irrelevant - candidate is ineligible outright
}

MIN_SERVICE_YEARS = 1.0


class EmployeeTransferRequest(models.Model):
    _name = "employee.transfer.request"
    _inherit = ["mail.thread"]
    _description = "Employee-Initiated Transfer Request"
    _rec_name = "name"
    _order = "request_date desc"

    name = fields.Char(string="Reference", copy=False, readonly=True, default=lambda self: _("New"))

    employee_id = fields.Many2one("hr.employee", string="Requesting Employee", required=True, tracking=True)
    request_date = fields.Date(string="Request Date", default=fields.Date.context_today, required=True)

    # Current situation, pulled from the employee record ------------------------
    current_job_position_id = fields.Many2one(
        "hr.job", string="Current Job Position", compute="_compute_current_info", store=True
    )
    current_job_grade_id = fields.Many2one(
        "employee.grade", string="Current Grade", compute="_compute_current_info", store=True
    )
    current_operating_unit_id = fields.Many2one(
        "operating.unit", string="Current Location", compute="_compute_current_info", store=True
    )
    date_in_current_position = fields.Date(
        string="Date Joined Current Position",
        help="Used to validate the minimum 1-year-in-position service rule (FR-REC-064).",
    )
    date_in_current_location = fields.Date(
        string="Date Joined Current Location",
        help="Used to validate the minimum 1-year-in-location service rule (FR-REC-064).",
    )

    # Target ----------------------------------------------------------------------
    target_vacancy_id = fields.Many2one(
        "job.vacancy", string="Target Vacancy", required=True,
        domain="[('vacancy_status', '=', 'published')]",
    )
    target_job_grade_id = fields.Many2one(
        "employee.grade", string="Target Grade", related="target_vacancy_id.job_grade", store=True,
    )
    target_job_position_id = fields.Many2one(
        "hr.job", string="Target Position", related="target_vacancy_id.job_position", store=True,
    )

    # FR-REC-063 Grade Restriction --------------------------------------------------
    grade_restriction_ok = fields.Boolean(string="Grade/Position Match OK", compute="_compute_eligibility", store=True)

    # FR-REC-064 Service Rule --------------------------------------------------------
    service_years_current_position = fields.Float(
        string="Years in Current Position", compute="_compute_service_years", store=True
    )
    service_years_current_location = fields.Float(
        string="Years in Current Location", compute="_compute_service_years", store=True
    )
    service_rule_ok = fields.Boolean(string="Service Rule OK", compute="_compute_eligibility", store=True)

    # FR-REC-065 Discipline Impact -----------------------------------------------
    disciplinary_status = fields.Selection(
        DISCIPLINE_SELECTION, string="Disciplinary Status", default="none", required=True, tracking=True,
    )
    discipline_deduction_percent = fields.Float(
        string="Discipline Deduction (%)", compute="_compute_discipline_deduction", store=True
    )

    # FR-REC-066 Exchange Transfer -------------------------------------------------
    is_exchange_transfer = fields.Boolean(string="Exchange Transfer")
    exchange_partner_employee_id = fields.Many2one("hr.employee", string="Exchange Partner Employee")
    exchange_partner_disciplinary_status = fields.Selection(
        DISCIPLINE_SELECTION, string="Exchange Partner Disciplinary Status", default="none",
    )
    exchange_transfer_ok = fields.Boolean(string="Exchange Transfer OK", compute="_compute_eligibility", store=True)

    # Overall eligibility -----------------------------------------------------------
    eligibility_status = fields.Selection(
        [("eligible", "Eligible"), ("ineligible", "Ineligible")],
        string="Eligibility", compute="_compute_eligibility", store=True,
    )
    ineligibility_reason = fields.Text(string="Ineligibility Reason", compute="_compute_eligibility", store=True)

    # Ranking inputs (used by transfer.committee.minutes, FR-REC-069) --------------
    total_experience_years = fields.Float(string="Total Experience (Years)")
    pms_score = fields.Float(string="PMS Score", compute="_compute_pms_score", store=True, readonly=False)
    transfer_suitability_score = fields.Float(
        string="Transfer Suitability Score", readonly=True, copy=False,
        help="Populated by the Transfer Committee Minutes ranking (FR-REC-069/070).",
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("under_review", "Under Review"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("withdrawn", "Withdrawn"),
            ("refused", "Refused by Employee"),
        ],
        string="Status", default="draft", tracking=True, copy=False,
    )

    # FR-REC-068 -----------------------------------------------------------------
    is_flagged_for_hr = fields.Boolean(string="Flagged for HR", default=False, readonly=True, copy=False)
    refusal_reason = fields.Text(string="Refusal Reason")
    hr_notified_on_refusal = fields.Datetime(string="HR Notified On", readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("employee.transfer.request") or _("New")
        return super().create(vals_list)

    # ---------------------------------------------------------------------------
    # Computations
    # ---------------------------------------------------------------------------
    @api.depends("employee_id")
    def _compute_current_info(self):
        for rec in self:
            emp = rec.employee_id
            rec.current_job_position_id = emp.job_position if emp else False
            rec.current_job_grade_id = emp.job_grade if emp else False
            rec.current_operating_unit_id = emp.default_operating_unit_id if emp else False

    @api.depends("employee_id")
    def _compute_pms_score(self):
        for rec in self:
            try:
                rec.pms_score = rec.employee_id.contract_id.pms_score or 0.0
            except Exception:
                rec.pms_score = rec.pms_score or 0.0

    @api.depends("date_in_current_position", "date_in_current_location")
    def _compute_service_years(self):
        today = date.today()
        for rec in self:
            rec.service_years_current_position = (
                (today - rec.date_in_current_position).days / 365.25 if rec.date_in_current_position else 0.0
            )
            rec.service_years_current_location = (
                (today - rec.date_in_current_location).days / 365.25 if rec.date_in_current_location else 0.0
            )

    @api.depends(
        "disciplinary_status", "exchange_partner_disciplinary_status", "is_exchange_transfer",
        "current_job_grade_id", "current_job_position_id",
        "target_job_grade_id", "target_job_position_id",
        "service_years_current_position", "service_years_current_location",
    )
    def _compute_eligibility(self):
        for rec in self:
            reasons = []

            # FR-REC-063: same grade and/or position
            grade_match = bool(rec.current_job_grade_id) and rec.current_job_grade_id == rec.target_job_grade_id
            position_match = bool(rec.current_job_position_id) and rec.current_job_position_id == rec.target_job_position_id
            rec.grade_restriction_ok = grade_match or position_match
            if not rec.grade_restriction_ok:
                reasons.append(_("Target vacancy is not within the same Job Grade and/or Position."))

            # FR-REC-064: minimum 1 year in current position and location
            rec.service_rule_ok = (
                rec.service_years_current_position >= MIN_SERVICE_YEARS
                and rec.service_years_current_location >= MIN_SERVICE_YEARS
            )
            if not rec.service_rule_ok:
                reasons.append(_("Employee has less than 1 year of service in the current position and/or location."))

            # FR-REC-065: active Last Written Warning = ineligible
            if rec.disciplinary_status == "last_written_warning":
                reasons.append(_("Employee has an active Last Written Warning."))

            # FR-REC-066: exchange transfer requires zero active disciplinary records on both sides
            if rec.is_exchange_transfer:
                rec.exchange_transfer_ok = (
                    rec.disciplinary_status == "none" and rec.exchange_partner_disciplinary_status == "none"
                )
                if not rec.exchange_transfer_ok:
                    reasons.append(_("Exchange Transfer requires both employees to have zero active "
                                      "disciplinary records."))
            else:
                rec.exchange_transfer_ok = True

            rec.ineligibility_reason = "\n".join(reasons) if reasons else False
            rec.eligibility_status = "ineligible" if reasons else "eligible"

    @api.depends("disciplinary_status")
    def _compute_discipline_deduction(self):
        for rec in self:
            rec.discipline_deduction_percent = DISCIPLINE_DEDUCTION.get(rec.disciplinary_status, 0.0)

    # ---------------------------------------------------------------------------
    # Workflow
    # ---------------------------------------------------------------------------
    def action_submit(self):
        for rec in self:
            if not rec.target_vacancy_id:
                raise ValidationError(_("Please select a Target Vacancy before submitting."))
            rec.state = "submitted"
            rec.message_post(body=_("Transfer request submitted."))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Request Submitted'),
                'message': _('Transfer request submitted.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_start_review(self):
        records = self.filtered(lambda r: r.state == "submitted")
        records.write({"state": "under_review"})
        for rec in records:
            rec.message_post(body=_("Transfer request is now under review."))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Under Review'),
                'message': _('Transfer request is now under review.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_approve(self):
        for rec in self:
            if rec.eligibility_status != "eligible":
                raise ValidationError(_(
                    "This transfer request is not eligible and cannot be approved:\n%s"
                ) % (rec.ineligibility_reason or _("Unknown reason.")))
            rec.state = "approved"
            rec.message_post(body=_("Transfer request approved."))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Transfer Approved'),
                'message': _('Transfer request approved.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_reject(self):
        self.write({"state": "rejected"})
        for rec in self:
            rec.message_post(body=_("Transfer request rejected."))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Transfer Rejected'),
                'message': _('Transfer request rejected.'),
                'type': 'warning',
                'sticky': False,
            },
        }

    def action_withdraw(self):
        """FR-REC-067: employees may cancel a pending request via Self-Service."""
        for rec in self:
            if rec.state not in ("draft", "submitted", "under_review"):
                raise UserError(_("Only pending requests (Draft, Submitted, or Under Review) can be withdrawn."))
            rec.state = "withdrawn"
            rec.message_post(body=_("Transfer request withdrawn by employee."))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Request Withdrawn'),
                'message': _('Transfer request withdrawn.'),
                'type': 'warning',
                'sticky': False,
            },
        }

    def action_refuse_transfer(self):
        """FR-REC-068: if the employee refuses an Approved Transfer, flag the
        record and notify HR."""
        for rec in self:
            if rec.state != "approved":
                raise UserError(_("Only an Approved transfer can be refused."))
            rec.write({
                "state": "refused",
                "is_flagged_for_hr": True,
                "hr_notified_on_refusal": fields.Datetime.now(),
            })
            rec._notify_hr_of_refusal()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Transfer Refused'),
                'message': _('Transfer refused and HR notified.'),
                'type': 'warning',
                'sticky': False,
            },
        }

    def _notify_hr_of_refusal(self):
        self.ensure_one()
        hr_group = self.env.ref("hr.group_hr_manager", raise_if_not_found=False)
        hr_users = self.env["res.users"].search([("group_ids", "in", [hr_group.id])]) if hr_group else self.env["res.users"]
        body = _(
            "Employee <b>%(employee)s</b> has refused the approved transfer to "
            "<b>%(position)s</b> (Vacancy: %(vacancy)s). Reason: %(reason)s"
        ) % {
            "employee": self.employee_id.name,
            "position": self.target_job_position_id.name or "",
            "vacancy": self.target_vacancy_id.reference or "",
            "reason": self.refusal_reason or _("Not specified"),
        }
        self.message_post(body=body)
        partners = hr_users.mapped("partner_id")
        if partners:
            channel = self.env["discuss.channel"]._get_or_create_chat(partners_to=partners.ids)
            channel.message_post(body=body, message_type="comment", subtype_xmlid="mail.mt_comment")
