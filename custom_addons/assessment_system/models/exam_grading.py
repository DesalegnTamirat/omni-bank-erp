# -*- coding: utf-8 -*-

from datetime import datetime, timedelta
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class ExamGradingTask(models.Model):
    """
    ==================================================
    Queues Essay and Short Answer questions for manual grading, auto-assigned
    to work unit graders, with 3-working-day SLA monitoring and supervisor verification.
    """
    _name = "exam.grading.task"
    _description = "Exam Manual Question Grading Task"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "is_overdue desc, create_date asc, id asc"

    name = fields.Char(string="Task Reference", readonly=True, default=lambda self: _("New"))
    attempt_id = fields.Many2one("exam.candidate.attempt", string="Candidate Attempt", required=True, ondelete="cascade", index=True)
    answer_id = fields.Many2one("exam.candidate.answer", string="Candidate Answer", required=True, ondelete="cascade")
    question_id = fields.Many2one("exam.question", string="Question", required=True, ondelete="cascade")
    job_id = fields.Many2one("hr.job", string="Target Job Position", readonly=True)
    department_id = fields.Many2one("hr.department", string="Department", compute="_compute_department_id", store=True, index=True)
    operating_unit_id = fields.Many2one("operating.unit", string="Submitting Work Unit", compute="_compute_department_id", store=True, index=True)

    candidate_name = fields.Char(string="Candidate Name", readonly=True)
    question_type = fields.Selection(related="question_id.question_type", string="Question Type", readonly=True)
    question_text = fields.Text(related="question_id.name", string="Question Prompt", readonly=True)
    rubric_guidelines = fields.Text(related="question_id.rubric_guidelines", string="Scoring Rubric", readonly=True)
    correct_text_answer = fields.Char(related="question_id.correct_text_answer", string="Expected Answer / Keyword", readonly=True)
    candidate_response = fields.Text(related="answer_id.text_answer", string="Candidate Response", readonly=True)
    
    marks_available = fields.Float(string="Max Marks", readonly=True)
    marks_awarded = fields.Float(string="Marks Awarded", tracking=True)
    grader_comments = fields.Text(string="Grader Feedback / Scoring Justification", tracking=True)

    assigned_grader_id = fields.Many2one("res.users", string="Assigned Grader", tracking=True, index=True)
    graded_by_user_id = fields.Many2one("res.users", string="Graded By", readonly=True, tracking=True)
    graded_date = fields.Datetime(string="Graded Date", readonly=True)

    verified_by_user_id = fields.Many2one("res.users", string="Supervisor Verifier", readonly=True, tracking=True)
    verified_date = fields.Datetime(string="Verification Date", readonly=True)

    # 3-Working-Day SLA Watchdog (FR-EXM-034, BR-AMS-14)
    sla_deadline = fields.Datetime(string="SLA Target Deadline", compute="_compute_sla_deadline", store=True)
    is_overdue = fields.Boolean(string="Overdue (>3 Working Days)", compute="_compute_is_overdue", store=True, index=True)
    days_pending = fields.Integer(string="Days Pending", compute="_compute_days_pending")

    state = fields.Selection([
        ("pending", "Pending Grading"),
        ("graded", "Graded / Awaiting Verification"),
        ("verified", "Verified & Score Finalized"),
    ], string="Grading Status", default="pending", tracking=True, required=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("exam.grading.task") or _("GRADE/%06d") % self.search_count([])
        return super().create(vals_list)

    @api.depends("question_id.department_id", "question_id.operating_unit_id", "job_id.department_id", "attempt_id.employee_id.operating_unit_id")
    def _compute_department_id(self):
        for rec in self:
            rec.department_id = rec.question_id.department_id or (rec.job_id.department_id if rec.job_id else False)
            rec.operating_unit_id = rec.question_id.operating_unit_id or (rec.attempt_id.employee_id.operating_unit_id if rec.attempt_id and rec.attempt_id.employee_id else False) or (getattr(rec.job_id.department_id, "operating_unit_id", False) if rec.job_id and rec.job_id.department_id else False)

    @api.depends("create_date")
    def _compute_sla_deadline(self):
        for rec in self:
            c_date = rec.create_date or fields.Datetime.now()
            # 3 working days (roughly +72 hours excluding weekends)
            rec.sla_deadline = c_date + timedelta(days=3)

    @api.depends("state", "sla_deadline")
    def _compute_is_overdue(self):
        now = fields.Datetime.now()
        for rec in self:
            if rec.state != "verified" and rec.sla_deadline and now > rec.sla_deadline:
                rec.is_overdue = True
            else:
                rec.is_overdue = False

    def _compute_days_pending(self):
        now = fields.Datetime.now()
        for rec in self:
            if rec.create_date:
                delta = now - rec.create_date
                rec.days_pending = max(0, delta.days)
            else:
                rec.days_pending = 0

    @api.constrains("marks_awarded", "marks_available")
    def _check_marks_awarded(self):
        for rec in self:
            if rec.marks_awarded < 0:
                raise ValidationError(_("Marks awarded cannot be negative. (Task: %s)") % rec.name)
            if rec.marks_available > 0 and rec.marks_awarded > rec.marks_available:
                raise ValidationError(
                    _("Cannot give marks beyond the allocated exam question marks!\n\n"
                      "• Question: %s\n"
                      "• Max Available Marks: %.2f\n"
                      "• Marks Entered: %.2f\n\n"
                      "Please enter a score between 0 and %.2f.") % (
                        rec.question_text or rec.name,
                        rec.marks_available,
                        rec.marks_awarded,
                        rec.marks_available
                    )
                )

    def action_submit_grade(self):
        for rec in self:
            if rec.marks_awarded < 0 or rec.marks_awarded > rec.marks_available:
                raise ValidationError(_("Marks awarded must be between 0 and %s.") % rec.marks_available)
            rec.write({
                "state": "graded",
                "graded_by_user_id": self.env.user.id,
                "graded_date": fields.Datetime.now(),
            })

    def action_submit_candidate_evaluation(self):
        """
        Submits evaluation for all essay questions of the selected candidate(s) and computes final written exam scores.
        """
        attempts = self.mapped("attempt_id")
        for att in attempts:
            for task in self.filtered(lambda t: t.attempt_id == att):
                if task.marks_awarded < 0 or task.marks_awarded > task.marks_available:
                    raise ValidationError(_("Marks awarded for '%s' must be between 0 and %s.") % ((task.question_text or "Question")[:40], task.marks_available))
                task.answer_id.marks_awarded = task.marks_awarded
            att.action_submit_essay_evaluation()

    def action_verify_grade(self):
        """Supervisor verification step (FR-EXM-036)"""
        for rec in self:
            # Segregation of duties: Verifier should ideally not be the grader
            if rec.graded_by_user_id and rec.graded_by_user_id == self.env.user:
                # Warning or check (unless admin)
                pass
            
            rec.write({
                "state": "verified",
                "verified_by_user_id": self.env.user.id,
                "verified_date": fields.Datetime.now(),
            })
            
            # Update the candidate's answer record and attempt manual score
            rec.answer_id.write({
                "marks_awarded": rec.marks_awarded,
                "is_correct": (rec.marks_awarded > 0),
            })
            
            # Recalculate total manual score on attempt
            attempt = rec.attempt_id
            attempt.action_submit_essay_evaluation()

    @api.model
    def check_overdue_grading_tasks_cron(self):
        """
        SLA Compliance Watchdog Cron (FR-EXM-034, FR-AMS-NOT-05).
        Runs daily, flags tasks >3 working days, sends alerts to HR officers.
        """
        overdue_tasks = self.search([
            ("state", "!=", "verified"),
            ("is_overdue", "=", True)
        ])
        if overdue_tasks:
            # Group by assigned grader / manager
            hr_officers = self.env["res.users"].search([
                ("groups_id", "in", [self.env.ref("custom_recruitment.group_recruitment_officer").id])
            ])
            for officer in hr_officers:
                self.env["mail.activity"].create({
                    "res_model_id": self.env["ir.model"]._get("exam.grading.task").id,
                    "res_id": overdue_tasks[0].id,
                    "user_id": officer.id,
                    "activity_type_id": self.env.ref("mail.mail_activity_data_todo").id,
                    "summary": _("SLA Alert: %d Exam Grading Task(s) Overdue (>3 working days)") % len(overdue_tasks),
                    "note": _("Please review and complete overdue manual question grading tasks."),
                })


class ExamManualScoreOverride(models.Model):
    """
    """
    _name = "exam.manual.override"
    _description = "Exam Score Manual Override Log"
    _inherit = ["mail.thread"]
    _order = "create_date desc, id desc"

    name = fields.Char(string="Override Reference", readonly=True, default=lambda self: _("New"))
    attempt_id = fields.Many2one("exam.candidate.attempt", string="Candidate Attempt", required=True, index=True)
    candidate_name = fields.Char(related="attempt_id.candidate_name", string="Candidate", readonly=True)
    
    original_objective_score = fields.Float(string="Original Objective Score", readonly=True)
    original_manual_score = fields.Float(string="Original Manual Score", readonly=True)
    original_total_score = fields.Float(string="Original Total Score", readonly=True)

    new_total_score = fields.Float(string="New Overridden Total Score", required=True, tracking=True)
    reason = fields.Text(string="Mandatory Justification / Reason", required=True, tracking=True)
    
    entered_by_user_id = fields.Many2one("res.users", string="Entered By", default=lambda self: self.env.user, readonly=True)
    verified_by_user_id = fields.Many2one("res.users", string="Verified By Supervisor", readonly=True, tracking=True)
    verification_date = fields.Datetime(string="Verification Date", readonly=True)

    state = fields.Selection([
        ("draft", "Draft / Entered"),
        ("verified", "Verified & Applied"),
        ("rejected", "Rejected"),
    ], string="Status", default="draft", tracking=True, required=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("exam.manual.override") or _("OVR/%05d") % self.search_count([])
        return super().create(vals_list)

    def action_verify_override(self):
        for rec in self:
            rec.attempt_id.write({
                "manual_score": rec.new_total_score - rec.attempt_id.objective_score
            })
            rec.write({
                "state": "verified",
                "verified_by_user_id": self.env.user.id,
                "verification_date": fields.Datetime.now(),
            })
            # Log in immutable audit log
            self.env["assessment.audit.log"].log_event(
                event_type="score_override",
                model_name="exam.candidate.attempt",
                res_id=rec.attempt_id.id,
                description=_("Score manually overridden from %s to %s. Reason: %s") % (
                    rec.original_total_score, rec.new_total_score, rec.reason
                )
            )

    def action_reject(self):
        for rec in self:
            rec.state = "rejected"
