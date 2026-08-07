# -*- coding: utf-8 -*-
# Transfer Assessment Scheduling and Management – Module 3 (Assessment
# Management Module) BRD Requirements:
#     Auto-trigger transfer assessment on Transfer Request submission
#     Configurable transfer assessment parameters
#     Assignment of transfer assessment to eligible transfer applicants
#     Transfer-specific written exam creation
#     Transfer interview scheduling with configurable panel composition
#     Bulk scheduling/management of assessments for multiple applicants
#     Automatic calculation of transfer assessment scores
#     Transfer Ranking integration (Recruitment Module)
#     Final transfer result calculation (assessment + ranking criteria)
#     Transfer result approval routing
#     Transfer result notification to applicants
#     Transfer result archiving (historical record)
#
# This module was previously missing: `employee.transfer.request` 
# to  only carried the ranking inputs (PMS, experience, service,
# recommendation) but had no Written Exam Score / Interview Score / Weighted
# Assessment Score, even though  (Mandatory Data Fields – Internal
# Applicants, Transfer Purpose) explicitly lists "Written Exam Score,
# Interview Score, Weighted Score, Final Result" as required data, and
# Module 3 dedicates  entirely to Transfer Assessment.

from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

# : default configurable transfer assessment parameters.
# Kept as module-level defaults; each transfer.assessment.config record can
# override them per policy update, consistent with the BRD note that
# "assessment rules must be flexible when procedure changes."
DEFAULT_EXAM_WEIGHT = 50.0
DEFAULT_INTERVIEW_WEIGHT = 50.0
DEFAULT_PASSING_SCORE = 50.0  # BRD 8.3: "Minimum score of 50% required in any individual assessment component."


class TransferAssessmentConfig(models.Model):
    """: Transfer Assessment Configuration.

    Single active configuration record (similar to a settings singleton)
    that HR Administrators can adjust when assessment procedures change,
    without touching code.
    """
    _name = "transfer.assessment.config"
    _description = "Transfer Assessment Configuration "
    _rec_name = "name"

    name = fields.Char(string="Configuration Name", default="Default Transfer Assessment Policy", required=True)
    active = fields.Boolean(default=True)
    exam_weight = fields.Float(string="Written Exam Weight (%)", default=DEFAULT_EXAM_WEIGHT)
    interview_weight = fields.Float(string="Interview Weight (%)", default=DEFAULT_INTERVIEW_WEIGHT)
    passing_score = fields.Float(
        string="Minimum Passing Score (%)", default=DEFAULT_PASSING_SCORE,
        help="Minimum score required in each individual assessment component (BRD 8.3).",
    )
    default_panel_size = fields.Integer(string="Default Interview Panel Size", default=3)

    @api.constrains("exam_weight", "interview_weight")
    def _check_weights(self):
        for rec in self:
            if round(rec.exam_weight + rec.interview_weight, 2) != 100.0:
                raise ValidationError(_("Exam Weight and Interview Weight must add up to 100%%."))

    @api.model
    def get_active_config(self):
        """Return the active configuration, creating a default one if none exists."""
        config = self.search([("active", "=", True)], limit=1)
        if not config:
            config = self.create({})
        return config


class TransferAssessment(models.Model):
    """: Transfer Assessment record.

    One record per Employee Transfer Request (employee.transfer.request),
    covering written exam and interview scheduling, scoring, approval,
    notification, and archiving for the transfer selection process.
    """
    _name = "transfer.assessment"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Transfer Assessment "
    _rec_name = "name"
    _order = "create_date desc"

    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({"active": False})
        return True

    name = fields.Char(string="Reference", copy=False, readonly=True, default=lambda self: _("New"))

    #  / : link back to the originating Transfer Request
    transfer_request_id = fields.Many2one(
        "employee.transfer.request", string="Transfer Request", required=True,
        ondelete="cascade", tracking=True,
    )
    employee_id = fields.Many2one(
        related="transfer_request_id.employee_id", string="Employee", store=True, readonly=True,
    )
    target_vacancy_id = fields.Many2one(
        related="transfer_request_id.target_vacancy_id", string="Target Vacancy", store=True, readonly=True,
    )
    config_id = fields.Many2one(
        "transfer.assessment.config", string="Assessment Configuration",
        default=lambda self: self.env["transfer.assessment.config"].get_active_config.id,
        help="Configurable weighting/passing-score parameters .",
    )

    # : Transfer-specific written exam ----------------
    exam_scheduled_date = fields.Datetime(string="Written Exam Date")
    exam_score = fields.Float(string="Written Exam Score (%)", tracking=True)
    exam_completed = fields.Boolean(string="Exam Completed", default=False)

    # : Transfer interview scheduling with configurable panel -----
    interview_scheduled_date = fields.Datetime(string="Interview Date")
    interview_panel_ids = fields.Many2many(
        "hr.employee", "transfer_assessment_panel_rel", "assessment_id", "employee_id",
        string="Interview Panel",
        help="Configurable interview panel composition based on the transfer position .",
    )
    interview_score = fields.Float(string="Interview Score (%)", tracking=True)
    interview_completed = fields.Boolean(string="Interview Completed", default=False)

    # : Automatic score calculation ------------------
    weighted_assessment_score = fields.Float(
        string="Weighted Assessment Score (%)", compute="_compute_weighted_score", store=True,
        help="(Exam Score x Exam Weight) + (Interview Score x Interview Weight), per .",
    )
    passed_minimum_component_score = fields.Boolean(
        string="Passed Minimum Component Score", compute="_compute_weighted_score", store=True,
        help="True only if both Exam Score and Interview Score individually meet the configured "
             "minimum passing score (BRD 8.3 / .",
    )

    #  / : integration with Transfer Ranking Algorithm --
    transfer_suitability_score = fields.Float(
        related="transfer_request_id.transfer_suitability_score", string="Transfer Suitability Score (Ranking)",
        store=True, readonly=True,
        help="Populated by the Transfer Committee Minutes ranking engine , "
             "combined here with assessment results per .",
    )
    final_transfer_result = fields.Float(
        string="Final Transfer Result (%)", compute="_compute_final_result", store=True,
        help="Combines Weighted Assessment Score with the Transfer Suitability Score "
             "from the ranking engine .",
    )

    #  / : Approval & Notification -------------
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("scheduled", "Scheduled"),
            ("assessed", "Assessed"),
            ("pending_approval", "Pending Approval"),
            ("approved", "Approved"),
            ("published", "Published to Applicant"),
        ],
        string="Status", default="draft", tracking=True, copy=False,
    )
    approved_by = fields.Many2one("res.users", string="Approved By", readonly=True, copy=False)
    approved_date = fields.Datetime(string="Approval Date", readonly=True, copy=False)
    result_published_date = fields.Datetime(string="Result Published Date", readonly=True, copy=False)

    # ---------------------------------------
    # Sequence
    # ---------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("transfer.assessment") or _("New")
        return super().create(vals_list)

    # ---------------------------------------
    # Computations , 
    # ---------------------------------------
    @api.depends("exam_score", "interview_score", "config_id.exam_weight", "config_id.interview_weight",
                 "config_id.passing_score")
    def _compute_weighted_score(self):
        for rec in self:
            config = rec.config_id or rec.env["transfer.assessment.config"].get_active_config
            exam_weight = config.exam_weight or DEFAULT_EXAM_WEIGHT
            interview_weight = config.interview_weight or DEFAULT_INTERVIEW_WEIGHT
            passing = config.passing_score or DEFAULT_PASSING_SCORE

            rec.weighted_assessment_score = round(
                (rec.exam_score or 0.0) * (exam_weight / 100.0)
                + (rec.interview_score or 0.0) * (interview_weight / 100.0),
                2,
            )
            rec.passed_minimum_component_score = (
                rec.exam_score >= passing and rec.interview_score >= passing
            )

    @api.depends("weighted_assessment_score", "transfer_suitability_score")
    def _compute_final_result(self):
        for rec in self:
            # : combine assessment results with the ranking-engine
            # Transfer Suitability Score. Weighted evenly by default; the
            # ranking engine  already embeds PMS/experience/
            # service/recommendation/date, so this final figure represents
            # "assessment fitness" blended with "ranking suitability".
            if rec.transfer_suitability_score:
                rec.final_transfer_result = round(
                    (rec.weighted_assessment_score * 0.5) + (rec.transfer_suitability_score * 0.5), 2
                )
            else:
                rec.final_transfer_result = rec.weighted_assessment_score

    # ---------------------------------------
    # Workflow Actions
    # ---------------------------------------
    def action_schedule(self):
        """: schedule interview/exam. Requires both dates set."""
        for rec in self:
            if not rec.exam_scheduled_date and not rec.interview_scheduled_date:
                raise ValidationError(_("Please set a Written Exam Date and/or an Interview Date before scheduling."))
            rec.state = "scheduled"
            rec.message_post(body=_("Transfer assessment scheduled."))

    def action_mark_assessed(self):
        """: lock in scores once both exam and interview are completed."""
        for rec in self:
            if not rec.exam_completed or not rec.interview_completed:
                raise ValidationError(
                    _("Both the Written Exam and Interview must be marked completed before the "
                      "assessment can be finalized.")
                )
            rec.state = "assessed"
            rec.message_post(
                body=_("Transfer assessment completed. Weighted Score: %.2f%%") % rec.weighted_assessment_score
            )

    def action_submit_for_approval(self):
        """: route transfer assessment results for approval."""
        for rec in self:
            if rec.state != "assessed":
                raise UserError(_("Only completed (Assessed) records can be submitted for approval."))
            rec.state = "pending_approval"
            rec.message_post(body=_("Transfer assessment result submitted for approval."))

    def action_approve(self):
        """: approve the transfer assessment result."""
        for rec in self:
            if rec.state != "pending_approval":
                raise UserError(_("Only results Pending Approval can be approved."))
            rec.write({
                "state": "approved",
                "approved_by": self.env.user.id,
                "approved_date": fields.Datetime.now(),
            })
            rec.message_post(body=_("Transfer assessment result approved by %s.") % self.env.user.name)

    def action_publish_result(self):
        """: notify the transfer applicant of their assessment results."""
        for rec in self:
            if rec.state != "approved":
                raise UserError(_("Only Approved results can be published to the applicant."))
            rec.write({
                "state": "published",
                "result_published_date": fields.Datetime.now(),
            })
            body = _(
                "Your transfer assessment result has been published.<br/>"
                "Written Exam Score: %(exam)s%%<br/>Interview Score: %(interview)s%%<br/>"
                "Weighted Assessment Score: %(weighted)s%%<br/>Final Transfer Result: %(final)s%%"
            ) % {
                "exam": rec.exam_score,
                "interview": rec.interview_score,
                "weighted": rec.weighted_assessment_score,
                "final": rec.final_transfer_result,
            }
            rec.message_post(body=body)
            partner = rec.employee_id.user_id.partner_id if rec.employee_id.user_id else False
            if partner:
                try:
                    channel = self.env["discuss.channel"]._get_or_create_chat(partners_to=[partner.id])
                    channel.message_post(body=body, message_type="comment", subtype_xmlid="mail.mt_comment")
                except Exception:
                    pass  # : publication/archiving must not fail on notification errors

    # ---------------------------------------
    # Bulk actions  / 
    # ---------------------------------------
    @api.model
    def action_bulk_schedule(self, assessment_ids, exam_date=None, interview_date=None):
        """: Bulk scheduling of assessments for multiple transfer applicants."""
        records = self.browse(assessment_ids)
        vals = {}
        if exam_date:
            vals["exam_scheduled_date"] = exam_date
        if interview_date:
            vals["interview_scheduled_date"] = interview_date
        if vals:
            records.write(vals)
        records.filtered(lambda r: r.state == "draft").action_schedule
        return True

    # ---------------------------------------
    # Auto-trigger hook  / 
    # ---------------------------------------
    @api.model
    def create_for_transfer_request(self, transfer_request):
        """ / : automatically create (and assign) a Transfer
        Assessment when a Transfer Request is submitted and the employee is
        eligible. Called from employee.transfer.request.action_submit.
        Idempotent: reuses an existing draft/scheduled record if present.
        """
        existing = self.search([
            ("transfer_request_id", "=", transfer_request.id),
            ("state", "!=", "published"),
        ], limit=1)
        if existing:
            return existing
        return self.create({
            "transfer_request_id": transfer_request.id,
        })
