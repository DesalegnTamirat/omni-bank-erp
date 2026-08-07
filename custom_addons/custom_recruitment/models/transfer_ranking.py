# -*- coding: utf-8 -*-
# Transfer Ranking Engine – Fixed for Direct & Vacancy Transfers

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

    target_vacancy_id = fields.Many2one(
        "job.vacancy",
        string="Target Vacancy",
        tracking=True,
        required=False,
        help="Optional. Leave empty for committees reviewing direct transfer "
             "requests that are not linked to a specific vacancy.",
    )

    meeting_date = fields.Date(string="Meeting Date", default=fields.Date.context_today, required=True)
    state = fields.Selection(
        [("draft", "Draft"), ("ranked", "Ranked"), ("approved", "Approved")],
        string="Status", default="draft", tracking=True, copy=False,
    )

    transfer_request_ids = fields.Many2many(
        "employee.transfer.request", string="Transfer Requests Considered",
    )
    ranking_line_ids = fields.One2many(
        "transfer.committee.minutes.line", "minutes_id", string="Ranked Candidates"
    )
    selection_decision = fields.Text(string="Selection Decision / Committee Notes")

    @api.onchange('target_vacancy_id')
    def _onchange_target_vacancy_id(self):
        """Auto-populate transfer_request_ids with all eligible requests matching
        the current vacancy setting (or direct transfers if left empty), and keep
        the picker domain in sync for any manual adjustments afterward."""
        if self.target_vacancy_id:
            domain = [
                ('target_vacancy_id', '=', self.target_vacancy_id.id),
                ('state', 'in', ['submitted', 'under_review', 'approved']),
                ('eligibility_status', '=', 'eligible'),
            ]
        else:
            domain = [
                ('target_vacancy_id', '=', False),
                ('state', 'in', ['submitted', 'under_review', 'approved']),
                ('eligibility_status', '=', 'eligible'),
            ]

        matching_requests = self.env['employee.transfer.request'].search(domain)
        self.transfer_request_ids = matching_requests

        return {'domain': {'transfer_request_ids': domain}}

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("transfer.committee.minutes") or _("New")
            if 'target_vacancy_id' not in vals:
                vals['target_vacancy_id'] = False
        return super().create(vals_list)

    @api.constrains('target_vacancy_id', 'transfer_request_ids')
    def _check_vacancy_consistency(self):
        """Validate that transfer requests match the vacancy setting"""
        for rec in self:
            if rec.transfer_request_ids:
                vacancy_requests = rec.transfer_request_ids.filtered(
                    lambda r: r.target_vacancy_id
                )
                direct_requests = rec.transfer_request_ids.filtered(
                    lambda r: not r.target_vacancy_id
                )
                if vacancy_requests and direct_requests:
                    pass  # Allow mixing both types

    def action_refresh_eligible_requests(self):
        """Manually re-sync transfer_request_ids with all eligible requests matching
        the current Target Vacancy (or direct transfers if empty)."""
        for rec in self:
            domain = [
                ('state', 'in', ['submitted', 'under_review', 'approved']),
                ('eligibility_status', '=', 'eligible'),
            ]
            if rec.target_vacancy_id:
                domain.append(('target_vacancy_id', '=', rec.target_vacancy_id.id))
            else:
                domain.append(('target_vacancy_id', '=', False))

            matching_requests = self.env['employee.transfer.request'].search(domain)
            rec.transfer_request_ids = matching_requests

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Requests Refreshed'),
                'message': _('Eligible transfer requests have been reloaded.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_compute_ranking(self):
        """ Compute the weighted Transfer Suitability Score for every eligible transfer request,
        apply discipline deduction, and populate the ranked list.

        Weighting (BRD Section 8.3):
            Application Date   20%
            Total Experience   20%
            Service in Location 20%
            PMS Score          30%
            Recommendation     10%

        Tie-breaking:
            1. Final Transfer Suitability Score (descending)
            2. Female gender priority (female ranked higher)
            3. Earlier Application Date/Timestamp
            4. Total Work Experience at Bunna Bank
            5. PMS Score

        Auto-selection:
            The top N ranked candidates are automatically marked "Selected" on the
            ranking line, where N = target_vacancy_id.no_of_vacancies (or 1 if this
            committee has no target vacancy, i.e. a direct transfer). The committee
            can still manually override any line's Decision afterward before
            approving the minutes.
        """
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
            if not rec.transfer_request_ids:
                raise UserError(_(
                    "No transfer requests have been added to this committee yet. "
                    "Select at least one request under 'Transfer Requests Considered' "
                    "before computing the ranking. If none appear as selectable, check "
                    "that this committee's Target Vacancy matches the vacancy on the "
                    "requests you're trying to rank (or leave it empty for direct "
                    "transfers)."
                ))

            eligible_requests = rec.transfer_request_ids.filtered(
                lambda r: r.eligibility_status == "eligible"
            )
            if not eligible_requests:
                status_summary = ", ".join(
                    "%s (%s)" % (r.name, r.eligibility_status or _("unknown"))
                    for r in rec.transfer_request_ids
                )
                raise UserError(_(
                    "None of the %d transfer request(s) added to this committee are "
                    "marked eligible. Current status: %s"
                ) % (len(rec.transfer_request_ids), status_summary))

            rec.ranking_line_ids.unlink()

            # --- Determine number of open slots for auto-selection ---------
            if rec.target_vacancy_id:
                slots = rec.target_vacancy_id.no_of_vacancies or 1
            else:
                slots = 1

            # --- Normalize each factor across the pool (0-100 scale) ---------
            dates = eligible_requests.mapped("request_date")
            min_date = min(dates)
            max_date = max(dates)
            date_span = (max_date - min_date).days or 1

            max_experience = max(eligible_requests.mapped("total_experience_years")) or 1.0
            max_location_years = max(eligible_requests.mapped("service_years_current_location")) or 1.0

            scored = []
            for req in eligible_requests:
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

                scored.append((
                    req,                    # [0]
                    application_score,      # [1]
                    experience_score,       # [2]
                    location_score,         # [3]
                    pms_score,              # [4]
                    recommendation_score,   # [5]
                    deduction,              # [6]
                    final_score,            # [7]
                ))

            scored.sort(
                key=lambda t: (
                    round(t[7], 4),
                    1 if getattr(t[0].employee_id, "gender", "") == "female" else 0,
                    -((t[0].request_date - min_date).days),
                    t[0].total_experience_years or 0.0,
                    t[4] or 0.0,
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
                    "selection_decision": "selected" if idx <= slots else "not_selected",
                })
                req.transfer_suitability_score = round(final_s, 2)

            rec.state = "ranked"
            rec.message_post(
                body=_("Transfer ranking computed. %d candidates ranked. "
                       "Top %d auto-marked as Selected based on %d open slot(s).")
                     % (len(scored), min(slots, len(scored)), slots)
            )

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
        """Approve the minutes and auto-approve all transfer requests
        for candidates marked as 'selected' in the ranked list."""
        for rec in self:
            if rec.state != "ranked":
                raise UserError(_("Please compute the ranking before approving the minutes."))
            rec.state = "approved"
            rec.message_post(body=_("Transfer Committee Minutes approved."))

            selected_lines = rec.ranking_line_ids.filtered(
                lambda l: l.selection_decision == "selected"
            )
            for line in selected_lines:
                transfer_req = line.transfer_request_id
                if not transfer_req:
                    continue
                try:
                    if transfer_req.state in ("submitted", "under_review"):
                        transfer_req.action_approve()
                    if transfer_req.state == "approved":
                        transfer_req.action_complete_transfer()
                except Exception as e:
                    rec.message_post(
                        body=_("Could not complete transfer for request %s: %s") % (
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