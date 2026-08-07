# -*- coding: utf-8 -*-
# Transfer Ranking Engine – , , , , 

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class TransferCommitteeMinutes(models.Model):
    _name = "transfer.committee.minutes"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Transfer Committee Minutes"
    _rec_name = "name"
    active = fields.Boolean(default=True)

    def unlink(self):
        """ Soft delete: Archive records instead of removing from DB """
        for rec in self:
            rec.write({'active': False})
        return True
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
        """ /  / : compute the weighted Transfer Suitability
        Score for every eligible transfer request considered by this committee,
        apply the discipline deduction, and populate the ranked list.

        Weighting (BRD Section 8.3 / :
            Configured weights are loaded dynamically, defaulting to:
            Application Date   20%
            Total Experience   20%
            Service in Location 20%
            PMS Score          30%
            Recommendation     10%

        Tie-breaking :
            1. Final Transfer Suitability Score (descending)
            2. Female gender priority (female ranked higher)
            3. Earlier Application Date/Timestamp
            4. Total Work Experience at Bunna Bank
            5. PMS Score
        """
        # Fetch config weights
        ICPSudo = self.env["ir.config_parameter"].sudo()
        try:
            w_pms = float(ICPSudo.get_param("custom_recruitment.transfer_weight_pms", "30.0")) / 100.0
        except ValueError:
            w_pms = 0.30
        try:
            w_app = float(ICPSudo.get_param("custom_recruitment.transfer_weight_application_date", "20.0")) / 100.0
        except ValueError:
            w_app = 0.20
        try:
            w_exp = float(ICPSudo.get_param("custom_recruitment.transfer_weight_experience", "20.0")) / 100.0
        except ValueError:
            w_exp = 0.20
        try:
            w_loc = float(ICPSudo.get_param("custom_recruitment.transfer_weight_service_location", "20.0")) / 100.0
        except ValueError:
            w_loc = 0.20
        try:
            w_rec = float(ICPSudo.get_param("custom_recruitment.transfer_weight_recommendation", "10.0")) / 100.0
        except ValueError:
            w_rec = 0.10

        for rec in self:
            eligible_requests = rec.transfer_request_ids.filtered(
                lambda r: r.eligibility_status == "eligible"
            )
            if not eligible_requests:
                raise UserError(_("There are no eligible transfer requests to rank."))

            rec.ranking_line_ids.unlink

            # --- Normalize each factor across the pool (0-100 scale) ---------
            dates = eligible_requests.mapped("request_date")
            min_date = min(dates)
            max_date = max(dates)
            date_span = (max_date - min_date).days or 1

            max_experience = max(eligible_requests.mapped("total_experience_years")) or 1.0
            max_location_years = max(eligible_requests.mapped("service_years_current_location")) or 1.0

            scored = []
            for req in eligible_requests:
                # Earlier application → higher score
                days_from_earliest = (req.request_date - min_date).days
                application_score = 100.0 * (1 - (days_from_earliest / date_span))

                experience_score = (
                    100.0 * (req.total_experience_years / max_experience)
                    if max_experience else 0.0
                )
                location_score = (
                    100.0 * (req.service_years_current_location / max_location_years)
                    if max_location_years else 0.0
                )
                pms_score = req.pms_score or 0.0
                recommendation_score = req.supervisor_recommendation_score or 0.0
                deduction = req.discipline_deduction_percent or 0.0

                weighted_total = (
                    application_score * w_app
                    + experience_score * w_exp
                    + location_score * w_loc
                    + pms_score * w_pms
                    + recommendation_score * w_rec
                )
                final_score = max(0.0, weighted_total - deduction)

                # FIX: Append tuple to scored list (was missing in original code)
                scored.append((
                    req,            # [0] request record
                    application_score,  # [1]
                    experience_score,   # [2]
                    location_score,     # [3]
                    pms_score,          # [4]
                    recommendation_score,  # [5]
                    deduction,          # [6]
                    final_score,        # [7]
                ))

            # --- Sort descending by composite score with tie-breaking  ---
            # Tie-break order:
            #   1. Final score (higher = better)
            #   2. Female priority (female = 1, else = 0, higher = better)
            #   3. Earlier application date (lower days_from_earliest = better)
            #   4. More experience (higher = better)
            #   5. Higher PMS score (higher = better)
            scored.sort(
                key=lambda t: (
                    round(t[7], 4),                                        # final score
                    1 if getattr(t[0].employee_id, "gender", "") == "female" else 0,  # gender priority
                    -((t[0].request_date - min_date).days),               # earlier date (negative for desc)
                    t[0].total_experience_years or 0.0,                   # total experience
                    t[4] or 0.0,                                           # PMS score
                ),
                reverse=True,
            )

            for idx, (req, app_s, exp_s, loc_s, pms_s, rec_s, deduction, final_s) in enumerate(scored, start=1):
                self.env["transfer.committee.minutes.line"].create({
                    "minutes_id": rec.id,
                    "rank": idx,
                    "transfer_request_id": req.id,
                    "application_date_score": round(app_s, 2),
                    "experience_score": round(exp_s, 2),
                    "service_location_score": round(loc_s, 2),
                    "pms_score": round(pms_s, 2),
                    "recommendation_score": round(rec_s, 2),
                    "discipline_deduction_percent": round(deduction, 2),
                    "final_score": round(final_s, 2),
                })
                req.transfer_suitability_score = round(final_s, 2)

            rec.state = "ranked"
            rec.message_post(body=_("Transfer ranking computed. %d candidates ranked.") % len(scored))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Ranking Computed'),
                'message': _('Transfer candidates have been ranked successfully.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_approve_minutes(self):
        """: Approve the minutes and auto-approve all transfer requests
        for candidates marked as 'selected' in the ranked list.
        Triggers Employee Master Data updates for selected candidates."""
        for rec in self:
            if rec.state != "ranked":
                raise UserError(_("Please compute the ranking before approving the minutes."))
            rec.state = "approved"
            rec.message_post(body=_("Transfer Committee Minutes approved."))

            # : Auto-approve transfer requests for selected candidates
            selected_lines = rec.ranking_line_ids.filtered(
                lambda l: l.selection_decision == "selected"
            )
            for line in selected_lines:
                transfer_req = line.transfer_request_id
                if transfer_req and transfer_req.state in ("submitted", "under_review"):
                    try:
                        transfer_req.action_approve
                    except Exception as e:
                        rec.message_post(
                            body=_("Could not auto-approve transfer request %s: %s") % (
                                transfer_req.name, str(e)
                            )
                        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Minutes Approved'),
                'message': _('Transfer Committee Minutes approved and selected candidates notified.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }


class TransferCommitteeMinutesLine(models.Model):
    _name = "transfer.committee.minutes.line"
    active = fields.Boolean(default=True)

    def unlink(self):
        self.write({"active": False})
        return True

    _description = "Transfer Committee Minutes - Ranked Candidate"
    _order = "rank"

    minutes_id = fields.Many2one("transfer.committee.minutes", string="Minutes", required=True, ondelete="cascade")
    rank = fields.Integer(string="Rank")
    transfer_request_id = fields.Many2one("employee.transfer.request", string="Transfer Request", required=True)
    employee_id = fields.Many2one(related="transfer_request_id.employee_id", string="Employee", store=True)
    employee_gender = fields.Selection(
        related="transfer_request_id.employee_id.gender",
        string="Gender", store=True,
    )

    application_date_score = fields.Float(string="Application Date Score (20%)")
    experience_score = fields.Float(string="Total Experience Score (20%)")
    service_location_score = fields.Float(string="Service in Location Score (20%)")
    pms_score = fields.Float(string="PMS Score (30%)")
    recommendation_score = fields.Float(string="Recommendation Score (10%)")
    discipline_deduction_percent = fields.Float(string="Discipline Deduction (%)")
    final_score = fields.Float(string="Final Transfer Suitability Score")

    selection_decision = fields.Selection(
        [("selected", "Selected"), ("not_selected", "Not Selected")],
        string="Decision", default="not_selected",
    )
