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

    # Defensive can_review computation
    can_review = fields.Boolean(
        string="Can Review",
        compute="_compute_can_review",
    )

    def _compute_can_review(self):
        is_reviewer = (
            self.env.user.has_group("hr.group_hr_user")
            or self.env.user.has_group("hr.group_hr_manager")
            or self.env.user.has_group("custom_recruitment.group_recruitment_officer")
            or self.env.user.has_group("custom_recruitment.group_recruitment_manager")
            or self.env.user.has_group("custom_recruitment.group_recruitment_administrator")
            or self.env.user.has_group("assessment_system.group_assessment_officer")
            or self.env.user.has_group("assessment_system.group_assessment_manager")
            or self.env.user.has_group("assessment_system.group_assessment_administrator")
            or self.env.is_admin()
        )
        for rec in self:
            rec.can_review = is_reviewer

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
        readonly=False,
        index=True,
        domain="[(\'is_reversed\', \'=\', False)]"
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

    can_review = fields.Boolean(
        string="Can Review Appeal",
        compute="_compute_can_review",
        help="Technical field: True if current user has HR Officer, HR Manager, or Assessment Officer/Manager permissions."
    )

    def _compute_can_review(self):
        is_reviewer = (
            self.env.user.has_group("hr.group_hr_user")
            or self.env.user.has_group("hr.group_hr_manager")
            or self.env.user.has_group("custom_recruitment.group_recruitment_officer")
            or self.env.user.has_group("custom_recruitment.group_recruitment_manager")
            or self.env.user.has_group("custom_recruitment.group_recruitment_administrator")
            or self.env.user.has_group("assessment_system.group_assessment_officer")
            or self.env.user.has_group("assessment_system.group_assessment_manager")
            or self.env.user.has_group("assessment_system.group_assessment_administrator")
            or self.env.is_admin()
        )
        for rec in self:
            rec.can_review = is_reviewer


    @api.constrains("disqualification_log_id")
    def _check_disqualification_log(self):
        for rec in self:
            if rec.disqualification_log_id.is_reversed:
                raise ValidationError(_(
                    "The disqualification record '%s' has already been reversed. "
                    "A new appeal cannot be created for an already reversed disqualification record."
                ) % rec.disqualification_log_id.name)
            duplicate_appeals = self.search([
                ("disqualification_log_id", "=", rec.disqualification_log_id.id),
                ("id", "!=", rec.id),
                ("state", "in", ["submitted", "approved"])
            ])
            if duplicate_appeals:
                raise ValidationError(_(
                    "An active appeal (%s) already exists for disqualification record '%s'."
                ) % (duplicate_appeals[0].name, rec.disqualification_log_id.name))

    @api.model_create_multi
    def create(self, vals_list):
        is_reviewer = (
            self.env.user.has_group("hr.group_hr_user")
            or self.env.user.has_group("hr.group_hr_manager")
            or self.env.user.has_group("custom_recruitment.group_recruitment_officer")
            or self.env.user.has_group("custom_recruitment.group_recruitment_manager")
            or self.env.user.has_group("custom_recruitment.group_recruitment_administrator")
            or self.env.user.has_group("assessment_system.group_assessment_officer")
            or self.env.user.has_group("assessment_system.group_assessment_manager")
            or self.env.user.has_group("assessment_system.group_assessment_administrator")
            or self.env.is_admin()
        )
        for vals in vals_list:
            if not is_reviewer and "review_comments" in vals:
                del vals["review_comments"]
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("exam.disqualification.appeal") or _("APL/%05d") % self.search_count([])
        records = super().create(vals_list)
        for rec in records:
            if rec.disqualification_log_id and not rec.disqualification_log_id.appeal_id:
                rec.disqualification_log_id.appeal_id = rec.id
        return records

    def write(self, vals):
        if "review_comments" in vals:
            is_reviewer = (
                self.env.user.has_group("hr.group_hr_user")
                or self.env.user.has_group("hr.group_hr_manager")
                or self.env.user.has_group("custom_recruitment.group_recruitment_officer")
                or self.env.user.has_group("custom_recruitment.group_recruitment_manager")
                or self.env.user.has_group("custom_recruitment.group_recruitment_administrator")
                or self.env.user.has_group("assessment_system.group_assessment_officer")
                or self.env.user.has_group("assessment_system.group_assessment_manager")
                or self.env.user.has_group("assessment_system.group_assessment_administrator")
                or self.env.is_admin()
            )
            if not is_reviewer:
                raise UserError(_("Only HR Officers and HR Managers can write or update the Review Decision Justification."))
        return super().write(vals)

    def _get_candidate_partners(self):
        self.ensure_one()
        candidate_partners = self.env["res.partner"]
        if self.create_uid and self.create_uid.partner_id:
            candidate_partners |= self.create_uid.partner_id
        emp = self.disqualification_log_id.employee_id
        if emp:
            if emp.user_id and emp.user_id.partner_id:
                candidate_partners |= emp.user_id.partner_id
            elif emp.address_home_id:
                candidate_partners |= emp.address_home_id
            elif emp.work_email:
                p = self.env["res.partner"].search([("email", "=ilike", emp.work_email.strip())], limit=1)
                if p:
                    candidate_partners |= p
        applicant = self.disqualification_log_id.applicant_id
        if applicant:
            if applicant.partner_id:
                candidate_partners |= applicant.partner_id
            elif applicant.email_from:
                p = self.env["res.partner"].search([("email", "=ilike", applicant.email_from.strip())], limit=1)
                if p:
                    candidate_partners |= p
        return candidate_partners

    def action_approve_appeal(self):
        """Reverses disqualification with full audit logging and candidate notification"""
        if not (
            self.env.user.has_group("custom_recruitment.group_recruitment_manager")
            or self.env.user.has_group("custom_recruitment.group_recruitment_administrator")
            or self.env.user.has_group("assessment_system.group_assessment_manager")
            or self.env.user.has_group("assessment_system.group_assessment_administrator")
            or self.env.user.has_group("hr.group_hr_manager")
            or self.env.is_admin()
        ):
            raise UserError(_("Only HR / Assessment Managers and Administrators can uphold appeals."))
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

            # Automated Candidate Notification (Email & Chatter)
            partners = rec._get_candidate_partners()
            subject = _("Candidate Appeal Upheld: Disqualification Reversed (%s)") % rec.name
            body = _(
                "<p>Dear <strong>%s</strong>,</p>"
                "<p>Your appeal <strong>%s</strong> regarding the assessment disqualification has been reviewed and <strong>UPHELD</strong> by HR Management.</p>"
                "<p><strong>Review Decision Justification:</strong></p>"
                "<blockquote style='border-left: 4px solid #28a745; margin: 10px 0; padding: 10px 14px; background: #eafaf1; color: #155724; border-radius: 4px;'>%s</blockquote>"
                "<p>Your examination record has been restored. If applicable, please follow up with HR or review your assessment portal for updated status.</p>"
            ) % (rec.candidate_name, rec.name, rec.review_comments)

            rec.message_post(
                body=body,
                subject=subject,
                partner_ids=partners.ids if partners else False,
                message_type="notification",
                subtype_xmlid="mail.mt_comment",
            )
            log.message_post(
                body=_("Disqualification reversed on Appeal %s by %s: %s") % (rec.name, self.env.user.name, rec.review_comments),
                subtype_xmlid="mail.mt_comment",
            )

    def action_reject_appeal(self):
        """Rejects appeal with candidate notification and audit logging"""
        if not (
            self.env.user.has_group("custom_recruitment.group_recruitment_manager")
            or self.env.user.has_group("custom_recruitment.group_recruitment_administrator")
            or self.env.user.has_group("assessment_system.group_assessment_manager")
            or self.env.user.has_group("assessment_system.group_assessment_administrator")
            or self.env.user.has_group("hr.group_hr_manager")
            or self.env.is_admin()
        ):
            raise UserError(_("Only HR / Assessment Managers and Administrators can reject appeals."))
        for rec in self:
            if not rec.review_comments:
                raise UserError(_("Please provide a review decision justification before rejecting the appeal."))

            rec.write({
                "state": "rejected",
                "reviewer_user_id": self.env.user.id,
                "review_date": fields.Datetime.now(),
            })

            # Automated Candidate Notification (Email & Chatter)
            partners = rec._get_candidate_partners()
            subject = _("Candidate Appeal Decision: Rejected (%s)") % rec.name
            body = _(
                "<p>Dear <strong>%s</strong>,</p>"
                "<p>Your appeal <strong>%s</strong> regarding the assessment disqualification has been <strong>REJECTED</strong> after review by HR Management.</p>"
                "<p><strong>Review Decision Justification:</strong></p>"
                "<blockquote style='border-left: 4px solid #dc3545; margin: 10px 0; padding: 10px 14px; background: #fdf2f2; color: #721c24; border-radius: 4px;'>%s</blockquote>"
                "<p>The original disqualification status remains in effect.</p>"
            ) % (rec.candidate_name, rec.name, rec.review_comments)

            rec.message_post(
                body=body,
                subject=subject,
                partner_ids=partners.ids if partners else False,
                message_type="notification",
                subtype_xmlid="mail.mt_comment",
            )

            # Log audit event
            self.env["assessment.audit.log"].log_event(
                event_type="appeal_rejected",
                model_name="exam.disqualification.appeal",
                res_id=rec.id,
                description=_("Appeal %s for candidate %s was rejected by %s. Justification: %s") % (
                    rec.name, rec.candidate_name, self.env.user.name, rec.review_comments
                )
            )
