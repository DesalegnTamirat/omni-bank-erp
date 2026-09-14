# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class ExamDisqualificationLog(models.Model):
    """
    =============================================================================
    Maintains an immutable, append-only record of all disqualification events
    (Late arrival, Tab-switch limit, Screenshot attempts, Copy/Paste, etc.).
    """
    _name = "exam.disqualification.log"
    _description = "Assessment Disqualification Log"
    _inherit = ["mail.thread"]
    _order = "timestamp desc, id desc"

    name = fields.Char(string="Log Reference", readonly=True, default=lambda self: _("New"))
    attempt_id = fields.Many2one("exam.candidate.attempt", string="Exam Attempt", readonly=True, index=True)
    session_id = fields.Many2one("exam.session", string="Exam Session", readonly=True, index=True)
    applicant_id = fields.Many2one("hr.applicant", string="Recruitment Applicant", readonly=True)
    employee_id = fields.Many2one("hr.employee", string="Internal Employee", readonly=True)
    
    candidate_name = fields.Char(string="Candidate Name", required=True, readonly=True)
    candidate_code = fields.Char(string="Candidate / Employee ID", required=True, readonly=True)
    
    timestamp = fields.Datetime(string="Disqualification Timestamp", required=True, readonly=True, default=fields.Datetime.now)
    
    violation_type = fields.Selection([
        ("late_arrival", "Late Arrival Window Exceeded "),
        ("tab_switch", "Tab-Switch Violation Limit Exceeded"),
        ("screenshot", "Screenshot / Screen Capture Attempt"),
        ("copy_paste", "Copy / Paste Anti-Cheat Violation"),
        ("manual_admin", "Administrative / Invigilator Disqualification"),
        ("score_floor", "Score Below 50% Component Floor"),
    ], string="Violation Type", required=True, readonly=True)

    reason = fields.Text(string="Violation Details / Evidence Log", required=True, readonly=True)
    
    # Appeals Workflow (FR-EXM-041)
    appeal_id = fields.Many2one("exam.disqualification.appeal", string="Linked Candidate Appeal", readonly=True)
    is_reversed = fields.Boolean(string="Disqualification Reversed on Appeal", default=False, readonly=True)
    reversal_reason = fields.Text(string="Reversal Justification", readonly=True)
    reversed_by_user_id = fields.Many2one("res.users", string="Reversed By", readonly=True)
    reversal_date = fields.Datetime(string="Reversal Date", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("exam.disqualification.log") or _("DISQ/%05d") % self.search_count([])
        return super().create(vals_list)


class ExamDisqualificationAppeal(models.Model):
    """
    ======================================================
    Allows disqualified candidates to submit an appeal through ESS / HR portal.
    Reviewed by HR Manager / Administrator with full audit logging upon reversal.
    """
    _name = "exam.disqualification.appeal"
    _description = "Disqualification Appeal Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(string="Appeal Reference", readonly=True, default=lambda self: _("New"))
    disqualification_log_id = fields.Many2one(
        "exam.disqualification.log",
        string="Disqualification Record",
        required=True,
        readonly=True,
        index=True
    )
    attempt_id = fields.Many2one(related="disqualification_log_id.attempt_id", string="Exam Attempt", readonly=True)
    candidate_name = fields.Char(related="disqualification_log_id.candidate_name", string="Candidate Name", readonly=True)
    candidate_code = fields.Char(related="disqualification_log_id.candidate_code", string="Candidate ID", readonly=True)

    appeal_reason = fields.Text(string="Candidate Appeal Statement / Justification", required=True, tracking=True)
    evidence_attachment_ids = fields.Many2many("ir.attachment", string="Supporting Evidence / Documentation")

    reviewer_user_id = fields.Many2one("res.users", string="Reviewing Manager", readonly=True, tracking=True)
    review_date = fields.Datetime(string="Review Date", readonly=True)
    review_comments = fields.Text(string="Review Decision Justification", tracking=True)

    state = fields.Selection([
        ("submitted", "Submitted / Under Review"),
        ("approved", "Appeal Upheld / Disqualification Reversed"),
        ("rejected", "Appeal Rejected"),
    ], string="Appeal Status", default="submitted", tracking=True, required=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("exam.disqualification.appeal") or _("APL/%05d") % self.search_count([])
        return super().create(vals_list)

    def action_approve_appeal(self):
        """Reverses disqualification with full audit logging"""
        for rec in self:
            if not rec.review_comments:
                raise UserError(_("Please provide a review decision justification before upholding the appeal."))
            
            rec.write({
                "state": "approved",
                "reviewer_user_id": self.env.user.id,
                "review_date": fields.Datetime.now(),
            })
            
            # Update log
            log = rec.disqualification_log_id
            log.write({
                "is_reversed": True,
                "reversal_reason": rec.review_comments,
                "reversed_by_user_id": self.env.user.id,
                "reversal_date": fields.Datetime.now(),
                "appeal_id": rec.id,
            })
            
            # Reopen candidate attempt to allow sitting or re-grading
            attempt = log.attempt_id
            if attempt:
                attempt.write({
                    "state": "completed",
                    "disqualification_reason": _("Reversed on Appeal #%s: %s") % (rec.name, rec.review_comments)
                })
                attempt._auto_grade_objective_answers()
            
            # Log in immutable audit log
            self.env["assessment.audit.log"].log_event(
                event_type="appeal_reversal",
                model_name="exam.disqualification.log",
                res_id=log.id,
                description=_("Disqualification for candidate %s reversed via Appeal %s by %s. Reason: %s") % (
                    rec.candidate_name, rec.name, self.env.user.name, rec.review_comments
                )
            )

    def action_reject_appeal(self):
        for rec in self:
            rec.write({
                "state": "rejected",
                "reviewer_user_id": self.env.user.id,
                "review_date": fields.Datetime.now(),
            })
