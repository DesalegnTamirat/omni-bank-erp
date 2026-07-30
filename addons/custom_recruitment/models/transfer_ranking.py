# -*- coding: utf-8 -*-
"""
Transfer Ranking Algorithm
=============================
Implements BRD Module 1 (Recruitment and Selection Management System),
section 7.4 "Transfer Ranking Algorithm":

    FR-REC-069  Weighted Scoring   : Transfer Suitability Score = Application Date (20%)
                                      + Total Experience (20%) + Service in Current
                                      Location (20%) + PMS Score (40%).
    FR-REC-070  Discipline Deduction: apply the discipline deduction (FR-REC-065) to
                                       the final score if applicable.
    FR-REC-071  Minutes Generation  : generate Transfer Committee Minutes with ranked
                                       list, scores, and selection decision.

Normalization note: the BRD specifies percentage weights but not the exact
normalization method for each factor. This implementation normalizes each
factor to a 0-100 scale within the pool of eligible candidates for the same
vacancy (earliest application / highest experience / highest tenure in
location score 100, decreasing proportionally), and uses the PMS Score
directly (already 0-100). The discipline deduction is then subtracted, as
percentage points, from the weighted total.
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class TransferCommitteeMinutes(models.Model):
    _name = "transfer.committee.minutes"
    _inherit = ["mail.thread"]
    _description = "Transfer Committee Minutes"
    _rec_name = "name"
    _order = "meeting_date desc"

    name = fields.Char(string="Reference", copy=False, readonly=True, default=lambda self: _("New"))
    target_vacancy_id = fields.Many2one("job.vacancy", string="Target Vacancy", required=True, tracking=True)
    meeting_date = fields.Date(string="Meeting Date", default=fields.Date.context_today, required=True)
    state = fields.Selection(
        [("draft", "Draft"), ("ranked", "Ranked"), ("approved", "Approved")],
        string="Status", default="draft", tracking=True, copy=False,
    )

    transfer_request_ids = fields.Many2many(
        "employee.transfer.request", string="Transfer Requests Considered",
        domain="[('target_vacancy_id', '=', target_vacancy_id), "
               "('state', 'in', ['submitted', 'under_review', 'approved'])]",
    )
    ranking_line_ids = fields.One2many(
        "transfer.committee.minutes.line", "minutes_id", string="Ranked Candidates"
    )
    selection_decision = fields.Text(string="Selection Decision / Committee Notes")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("transfer.committee.minutes") or _("New")
        return super().create(vals_list)

    def action_compute_ranking(self):
        """FR-REC-069 / FR-REC-070: compute the weighted Transfer Suitability
        Score for every eligible transfer request considered by this
        committee, apply the discipline deduction, and populate the ranked
        list."""
        for rec in self:
            eligible_requests = rec.transfer_request_ids.filtered(lambda r: r.eligibility_status == "eligible")
            if not eligible_requests:
                raise UserError(_("There are no eligible transfer requests to rank."))

            rec.ranking_line_ids.unlink()

            # --- Normalize each factor across the pool (0-100 scale) ---------------
            dates = eligible_requests.mapped("request_date")
            min_date, max_date = min(dates), max(dates)
            date_span = (max_date - min_date).days or 1

            experiences = eligible_requests.mapped("total_experience_years")
            max_experience = max(experiences) or 1.0

            location_years = eligible_requests.mapped("service_years_current_location")
            max_location_years = max(location_years) or 1.0

            scored = []
            for req in eligible_requests:
                # Earlier application -> higher score.
                days_from_earliest = (req.request_date - min_date).days
                application_score = 100.0 * (1 - (days_from_earliest / date_span))

                experience_score = 100.0 * (req.total_experience_years / max_experience) if max_experience else 0.0
                location_score = 100.0 * (req.service_years_current_location / max_location_years) if max_location_years else 0.0
                pms_score = req.pms_score or 0.0

                weighted_total = (
                    application_score * 0.20
                    + experience_score * 0.20
                    + location_score * 0.20
                    + pms_score * 0.40
                )
                final_score = max(0.0, weighted_total - req.discipline_deduction_percent)

                scored.append((req, application_score, experience_score, location_score, pms_score,
                                req.discipline_deduction_percent, final_score))

            # Rank descending by final score.
            scored.sort(key=lambda t: t[6], reverse=True)

            for idx, (req, app_s, exp_s, loc_s, pms_s, deduction, final_s) in enumerate(scored, start=1):
                self.env["transfer.committee.minutes.line"].create({
                    "minutes_id": rec.id,
                    "rank": idx,
                    "transfer_request_id": req.id,
                    "application_date_score": app_s,
                    "experience_score": exp_s,
                    "service_location_score": loc_s,
                    "pms_score": pms_s,
                    "discipline_deduction_percent": deduction,
                    "final_score": final_s,
                })
                req.transfer_suitability_score = final_s

            rec.state = "ranked"

    def action_approve_minutes(self):
        for rec in self:
            if rec.state != "ranked":
                raise UserError(_("Please compute the ranking before approving the minutes."))
            rec.state = "approved"
            rec.message_post(body=_("Transfer Committee Minutes approved."))


class TransferCommitteeMinutesLine(models.Model):
    _name = "transfer.committee.minutes.line"
    _description = "Transfer Committee Minutes - Ranked Candidate"
    _order = "rank"

    minutes_id = fields.Many2one("transfer.committee.minutes", string="Minutes", required=True, ondelete="cascade")
    rank = fields.Integer(string="Rank")
    transfer_request_id = fields.Many2one("employee.transfer.request", string="Transfer Request", required=True)
    employee_id = fields.Many2one(related="transfer_request_id.employee_id", string="Employee", store=True)

    application_date_score = fields.Float(string="Application Date Score (20%)")
    experience_score = fields.Float(string="Total Experience Score (20%)")
    service_location_score = fields.Float(string="Service in Location Score (20%)")
    pms_score = fields.Float(string="PMS Score (40%)")
    discipline_deduction_percent = fields.Float(string="Discipline Deduction (%)")
    final_score = fields.Float(string="Final Transfer Suitability Score")

    selection_decision = fields.Selection(
        [("selected", "Selected"), ("not_selected", "Not Selected")],
        string="Decision", default="not_selected",
    )
