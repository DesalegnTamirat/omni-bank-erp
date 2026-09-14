# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class TransferAssessmentRecord(models.Model):
    """
    Transfer Assessment Management (FR-EXM-055 - FR-EXM-066)
    ========================================================
    Automatically triggered upon ESS transfer request submission. Calculates
    composite transfer score based on Bank policy:
    PMS (30%) + Application Date (20%) + Total Experience (20%) + Location Service (20%) + Recommendation (10%).
    Feeds directly into the Recruitment Transfer Ranking Algorithm.
    """
    _name = "transfer.assessment.record"
    _description = "Employee Transfer Assessment Evaluation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(string="Assessment Reference", readonly=True, default=lambda self: _("New"))
    
    # Linked Transfer Request & Employee
    transfer_request_id = fields.Many2one("employee.transfer.request", string="Transfer Request", tracking=True, index=True)
    employee_id = fields.Many2one("hr.employee", string="Applicant Employee", required=True, tracking=True, index=True)
    employee_code = fields.Char(related="employee_id.barcode", string="Employee ID", readonly=True)
    
    target_job_id = fields.Many2one("hr.job", string="Target Position", required=True, tracking=True)
    target_branch_id = fields.Char(string="Requested Branch / Location")

    # Assessment Mode
    assessment_mode = fields.Selection([
        ("criteria_only", "Transfer Criteria Matrix Only"),
        ("exam_and_criteria", "Written Exam + Transfer Criteria"),
        ("interview_and_criteria", "Interview + Transfer Criteria"),
        ("all", "Full Evaluation (Exam + Interview + Criteria)"),
    ], string="Assessment Scope", default="criteria_only", required=True, tracking=True)

    # 1. Performance Management Score (PMS) - 30% Weight
    pms_score = fields.Float(string="PMS Score (out of 100)", default=85.0, tracking=True)
    pms_weight = fields.Float(string="PMS Weight (%)", default=30.0)
    pms_weighted_score = fields.Float(string="PMS Weighted", compute="_compute_final_transfer_score", store=True)

    # 2. Application Date Seniority - 20% Weight
    application_date = fields.Date(string="Transfer Request Date", default=fields.Date.context_today)
    application_date_score = fields.Float(string="App Date Score (out of 100)", default=100.0, tracking=True)
    application_date_weight = fields.Float(string="App Date Weight (%)", default=20.0)
    application_date_weighted_score = fields.Float(string="App Date Weighted", compute="_compute_final_transfer_score", store=True)

    # 3. Total Experience Score - 20% Weight
    total_experience_years = fields.Float(string="Total Experience (Years)", default=5.0)
    total_experience_score = fields.Float(string="Experience Score (out of 100)", default=80.0, tracking=True)
    total_experience_weight = fields.Float(string="Experience Weight (%)", default=20.0)
    total_experience_weighted_score = fields.Float(string="Experience Weighted", compute="_compute_final_transfer_score", store=True)

    # 4. Service in Current Location - 20% Weight
    service_years_in_location = fields.Float(string="Service in Location (Years)", default=3.0)
    service_location_score = fields.Float(string="Location Service Score (out of 100)", default=75.0, tracking=True)
    service_location_weight = fields.Float(string="Location Service Weight (%)", default=20.0)
    service_location_weighted_score = fields.Float(string="Location Service Weighted", compute="_compute_final_transfer_score", store=True)

    # 5. Managerial Recommendation - 10% Weight
    recommendation_score = fields.Float(string="Recommendation Score (out of 100)", default=90.0, tracking=True)
    recommendation_weight = fields.Float(string="Recommendation Weight (%)", default=10.0)
    recommendation_weighted_score = fields.Float(string="Recommendation Weighted", compute="_compute_final_transfer_score", store=True)
    recommendation_notes = fields.Text(string="Supervisor Recommendation Notes")

    # Optional Exam / Interview Links
    exam_attempt_id = fields.Many2one("exam.candidate.attempt", string="Transfer Written Exam", readonly=True)
    interview_candidate_id = fields.Many2one("cbis.interview.candidate", string="Transfer Interview Record", readonly=True)

    # Final Transfer Composite Score
    total_transfer_score = fields.Float(
        string="Total Transfer Score (%)",
        compute="_compute_final_transfer_score",
        store=True,
        tracking=True
    )
    transfer_rank = fields.Integer(string="Transfer Rank", default=1, tracking=True)

    state = fields.Selection([
        ("draft", "Draft Assessment"),
        ("evaluated", "Evaluated / Scores Computed"),
        ("approved", "HR Approved & Ranked"),
        ("rejected", "Not Approved"),
    ], string="Status", default="draft", tracking=True, required=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("transfer.assessment.record") or _("TRA/%05d") % self.search_count([])
        return super().create(vals_list)

    @api.depends("pms_score", "application_date_score", "total_experience_score", "service_location_score", "recommendation_score")
    def _compute_final_transfer_score(self):
        for rec in self:
            rec.pms_weighted_score = round((rec.pms_score * rec.pms_weight) / 100.0, 2)
            rec.application_date_weighted_score = round((rec.application_date_score * rec.application_date_weight) / 100.0, 2)
            rec.total_experience_weighted_score = round((rec.total_experience_score * rec.total_experience_weight) / 100.0, 2)
            rec.service_location_weighted_score = round((rec.service_location_score * rec.service_location_weight) / 100.0, 2)
            rec.recommendation_weighted_score = round((rec.recommendation_score * rec.recommendation_weight) / 100.0, 2)

            rec.total_transfer_score = round(
                rec.pms_weighted_score +
                rec.application_date_weighted_score +
                rec.total_experience_weighted_score +
                rec.service_location_weighted_score +
                rec.recommendation_weighted_score,
                2
            )

    def action_evaluate(self):
        for rec in self:
            rec.state = "evaluated"

    def action_approve_transfer_assessment(self):
        for rec in self:
            rec.state = "approved"
            # Push score to Recruitment Module transfer ranking
            if rec.transfer_request_id and hasattr(rec.transfer_request_id, "score"):
                rec.transfer_request_id.score = rec.total_transfer_score
