# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class AssessmentResultPublication(models.Model):

    _name = "assessment.result.publication"
    _description = "Assessment Result Publication Batch"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "publication_date desc, id desc"

    name = fields.Char(string="Publication Title", required=True, tracking=True)
    code = fields.Char(string="Publication Code", readonly=True, default=lambda self: _("New"))
    
    publication_category = fields.Selection([
        ("recruitment_exam", "Written Exam Shortlist / Results"),
        ("interview_result", "Interview Evaluation Results"),
        ("final_selection", "Final Composite Selection List"),
        ("transfer_result", "Transfer Assessment Results"),
        ("promotion_result", "Promotion Assessment Results"),
    ], string="Publication Category", default="final_selection", required=True, tracking=True)

    job_id = fields.Many2one("hr.job", string="Job Position", required=True, index=True)
    vacancy_id = fields.Many2one("job.vacancy", string="Job Vacancy", index=True)
    
    publication_date = fields.Datetime(string="Publish Date & Time", default=fields.Datetime.now, required=True, tracking=True)
    expiry_date = fields.Datetime(string="Auto-Expiry Date", help="FR-EXM-076: Automatically removes from portal on this date", tracking=True)
    
    # Line items (anonymized result rows)
    line_ids = fields.One2many("assessment.result.publication.line", "publication_id", string="Published Candidate Results", copy=True)
    total_candidates = fields.Integer(string="Published Candidates", compute="_compute_total_candidates", store=True)

    # View Tracking & Access Logs (FR-EXM-085)
    view_log_ids = fields.One2many("assessment.publication.view.log", "publication_id", string="Candidate View Logs")
    view_count = fields.Integer(string="Total Views", compute="_compute_view_count")

    # Withdrawal Management (FR-EXM-070)
    is_withdrawn = fields.Boolean(string="Withdrawn", default=False, readonly=True, tracking=True)
    withdrawal_reason = fields.Text(string="Withdrawal Reason", readonly=True, tracking=True)
    withdrawn_by_user_id = fields.Many2one("res.users", string="Withdrawn By", readonly=True)
    withdrawn_date = fields.Datetime(string="Withdrawn Date", readonly=True)

    state = fields.Selection([
        ("draft", "Draft / Scheduled"),
        ("published", "Published Live on Portal"),
        ("expired", "Expired / Public Access Closed"),
        ("withdrawn", "Withdrawn with Audit"),
    ], string="Status", default="draft", tracking=True, required=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("code", _("New")) == _("New"):
                vals["code"] = self.env["ir.sequence"].next_by_code("assessment.result.publication") or _("PUB/%05d") % self.search_count([])
        return super().create(vals_list)

    @api.depends("line_ids")
    def _compute_total_candidates(self):
        for rec in self:
            rec.total_candidates = len(rec.line_ids)

    def _compute_view_count(self):
        for rec in self:
            rec.view_count = len(rec.view_log_ids)

    def action_publish(self):
        """Single action publication to HR Portal (FR-EXM-068)"""
        for rec in self:
            if not rec.line_ids:
                raise UserError(_("Cannot publish: Please populate candidate results before publishing."))
            rec.write({
                "state": "published",
                "publication_date": fields.Datetime.now()
            })
            rec._notify_candidates_published()

    def action_withdraw(self, reason):
        """Withdraws publication with mandatory audit trail (FR-EXM-070)"""
        self.ensure_one()
        if not reason:
            raise UserError(_("A valid withdrawal justification reason is required."))
        self.write({
            "state": "withdrawn",
            "is_withdrawn": True,
            "withdrawal_reason": reason,
            "withdrawn_by_user_id": self.env.user.id,
            "withdrawn_date": fields.Datetime.now(),
        })
        self.env["assessment.audit.log"].log_event(
            event_type="publication_withdrawal",
            model_name="assessment.result.publication",
            res_id=self.id,
            description=_("Publication %s withdrawn by %s. Reason: %s") % (self.name, self.env.user.name, reason)
        )

    def _notify_candidates_published(self):
        for line in self.line_ids:
            if line.candidate_email:
                subject = _("Assessment Results Published: %s - Bunna Bank") % (self.job_id.name or "Position")
                body = _("""
                    <p>Dear Candidate,</p>
                    <p>Assessment results for <b>%s</b> have been published to the HR Portal.</p>
                    <p>You can check your status and scores using your Candidate ID: <b>%s</b>.</p>
                    <p>Best regards,<br/>Bunna Bank Assessment Team</p>
                """) % (self.job_id.name, line.candidate_code)
                self.env['mail.mail'].sudo().create({
                    'subject': subject,
                    'body_html': body,
                    'email_to': line.candidate_email,
                }).send()

    @api.model
    def check_expired_publications_cron(self):
        """Auto-expires publications past their configured expiry date (FR-EXM-076)"""
        now = fields.Datetime.now()
        expired = self.search([
            ("state", "=", "published"),
            ("expiry_date", "!=", False),
            ("expiry_date", "<", now)
        ])
        for pub in expired:
            pub.state = "expired"


class AssessmentResultPublicationLine(models.Model):

    _name = "assessment.result.publication.line"
    _description = "Published Candidate Result Line"
    _order = "rank asc, total_score desc"

    publication_id = fields.Many2one("assessment.result.publication", string="Publication", required=True, ondelete="cascade", index=True)
    
    # Anonymized Identifier (Candidate Code / Employee ID ONLY)
    candidate_code = fields.Char(string="Candidate ID / Employee ID", required=True, index=True)
    candidate_name_private = fields.Char(string="Full Name (Internal Admin Only)", help="Never rendered on portal views")
    candidate_email = fields.Char(string="Candidate Email")
    
    # Component Scores
    exam_score = fields.Float(string="Written Exam (%)")
    interview_score = fields.Float(string="Interview Score (%)")
    pms_score = fields.Float(string="PMS Rating (%)")
    transfer_additional_score = fields.Float(string="Transfer Criteria Score (%)")
    
    total_score = fields.Float(string="Composite Final Score (%)", required=True)
    rank = fields.Integer(string="Rank / Position", default=1)
    
    employee_id = fields.Many2one("hr.employee", string="Related Employee", index=True)
    user_id = fields.Many2one("res.users", string="Related User", index=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._resolve_user_and_employee(vals)
        return super().create(vals_list)

    def write(self, vals):
        if "candidate_code" in vals or "candidate_email" in vals or "employee_id" in vals:
            self._resolve_user_and_employee(vals)
        return super().write(vals)

    def _resolve_user_and_employee(self, vals):
        code = (vals.get("candidate_code") or (self.candidate_code if self else False) or "").strip()
        email = (vals.get("candidate_email") or (self.candidate_email if self else False) or "").strip()
        
        emp = False
        if not vals.get("employee_id"):
            if code:
                emp = self.env["hr.employee"].sudo().search([
                    "|", ("identification_id", "=ilike", code), ("barcode", "=ilike", code)
                ], limit=1)
            if not emp and email:
                emp = self.env["hr.employee"].sudo().search([
                    "|", ("work_email", "=ilike", email), ("user_id.login", "=ilike", email)
                ], limit=1)
            if emp:
                vals["employee_id"] = emp.id

        if not vals.get("user_id"):
            if emp and emp.user_id:
                vals["user_id"] = emp.user_id.id
            elif email:
                user = self.env["res.users"].sudo().search([("login", "=ilike", email)], limit=1)
                if user:
                    vals["user_id"] = user.id
            elif code:
                user = self.env["res.users"].sudo().search([("login", "=ilike", code)], limit=1)
                if user:
                    vals["user_id"] = user.id

    status = fields.Selection([
        ("passed", "Passed / Shortlisted"),
        ("selected", "Selected / Offered"),
        ("failed", "Did Not Pass Component Floor (<50%)"),
        ("disqualified", "Disqualified"),
        ("under_review", "Under Review"),
    ], string="Result Status", default="passed", required=True)


class AssessmentPublicationViewLog(models.Model):
    """
    """
    _name = "assessment.publication.view.log"
    _description = "Candidate Result Portal View Log"
    _order = "view_datetime desc"

    publication_id = fields.Many2one("assessment.result.publication", string="Publication", required=True, ondelete="cascade", index=True)
    candidate_code = fields.Char(string="Candidate ID Looked Up", required=True, index=True)
    ip_address = fields.Char(string="IP Address")
    view_datetime = fields.Datetime(string="Viewed At", default=fields.Datetime.now, required=True)
    verification_success = fields.Boolean(string="Secondary Verification Passed", default=True)
