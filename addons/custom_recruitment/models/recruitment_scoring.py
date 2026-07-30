# -*- coding: utf-8 -*-

from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

DISQUALIFICATION_THRESHOLD = 50.0  # Section 9.2
OFFER_RESPONSE_DAYS = 3  # Section 11.2.2
INTERNAL_APPLICATION_DAYS = 3  # Section 5.2.1

# ── FR-REC-034: Default weight matrix ────────────────────────────────────
# Keyed by (recruitment_type, vacancy employee_category, job_level)
# job_level is only meaningful when employee_category == 'Non Managerial'.
# For 'Managerial' vacancies job_level is always False.
WEIGHT_MATRIX = {
    # Internal
    ("internal", "Managerial", False): (60.0, 0.0, 40.0),
    ("internal", "Non Managerial", "senior"): (40.0, 30.0, 30.0),
    ("internal", "Non Managerial", "junior"): (50.0, 25.0, 25.0),

    # External (no PMS component)
    ("external", "Managerial", False): (0.0, 50.0, 50.0),
    ("external", "Non Managerial", "junior"): (0.0, 50.0, 50.0),
    ("external", "Non Managerial", "senior"): (0.0, 60.0, 40.0),
}
DEFAULT_BOTH_WEIGHTS = (0.0, 50.0, 50.0)


# ── Section 9: Candidate Score Record ─────────────────────────────────────

class RecruitmentCandidateScore(models.Model):
    """
    Central scoring record for one candidate against one vacancy.
    Enforces the FRS formulas, disqualification gate, weight matrix,
    vacancy-slot cap, and Selected/Reserve tick-box workflow.
    """
    _name = "recruitment.candidate.score"
    _inherit = ["mail.thread"]
    _description = "Candidate Score & Ranking"
    _rec_name = "candidate_name"
    _order = "rank asc, final_score desc"

    vacancy_id = fields.Many2one("job.vacancy", string="Vacancy", required=True, ondelete="cascade", tracking=True)
    recruitment_type = fields.Selection(
        [("internal", "Internal"), ("external", "External")],
        string="Recruitment Type", required=True, default="internal"
    )

    # ── Driven by job.vacancy.employee_category — NOT independently set ───
    vacancy_employee_category = fields.Selection(
        related="vacancy_id.employee_category", string="Job Category", store=True, readonly=True
    )

    # Only relevant / visible when vacancy_employee_category == 'Non Managerial'
    job_level = fields.Selection(
        [("junior", "Junior"), ("senior", "Senior / Regular")],
        string="Job Level", tracking=True,
        help="Only applicable for Non-Managerial posts. Managerial posts have "
             "no sub-level, so this is hidden and cleared automatically."
    )

    # ── Vacancy slot info (read-only reference for the Selected cap) ──────
    vacancy_no_of_vacancies = fields.Integer(
        related="vacancy_id.no_of_vacancies", string="Vacancy Slots", store=False, readonly=True
    )

    # ── Applicant (external) or Employee (internal) ──────────────────────
    applicant_id = fields.Many2one("hr.applicant", string="Applicant (External)")
    employee_id = fields.Many2one("hr.employee", string="Employee (Internal)")
    candidate_name = fields.Char(string="Candidate Name", compute="_compute_name", store=True)
    gender = fields.Selection([("male", "Male"), ("female", "Female"), ("other", "Other")], string="Gender")

    # ── Assessment Scores ────────────────────────────────────────────────
    pms_score = fields.Float(string="PMS Score", digits=(5, 2), readonly=True)
    written_score = fields.Float(string="Written Exam Score", digits=(5, 2))
    interview_score = fields.Float(string="Interview Score", digits=(5, 2))

    # ── Weights (auto-defaulted from matrix, but fully user-editable) ─────
    weights_manually_set = fields.Boolean(string="Weights Manually Overridden", default=False, copy=False)
    pms_weight = fields.Float(string="PMS Weight (%)", default=0.0, digits=(5, 2))
    written_weight = fields.Float(string="Exam Weight (%)", default=50.0, digits=(5, 2))
    interview_weight = fields.Float(string="Interview Weight (%)", default=50.0, digits=(5, 2))

    # ── Disqualification flags ────────────────────────────────────────────
    disqualified = fields.Boolean(string="Disqualified", default=False, readonly=True, tracking=True)
    disqualification_reason = fields.Char(string="Disqualification Reason", readonly=True)
    disqualification_checked = fields.Boolean(
        string="Disqualification Checked", default=False, readonly=True, copy=False,
        help="Set automatically when 'Check Disqualification' has been run on this "
             "candidate. Ranking requires this to be True for every eligible "
             "candidate in the vacancy, to guarantee the 50% gate always runs "
             "before ranking — never after or skipped."
    )

    # ── Computed scores ───────────────────────────────────────────────────
    final_score = fields.Float(string="Final Score", digits=(5, 2), compute="_compute_final_score", store=True)
    rank = fields.Integer(string="Rank", default=0)

    # ── Selection outcome ─────────────────────────────────────────────────
    selection_status = fields.Selection(
        [("pending", "Pending"), ("selected", "Selected"),
         ("reserve", "Reserve Pool"), ("rejected", "Rejected"), ("disqualified", "Disqualified")],
        string="Selection Status", default="pending", tracking=True
    )
    reserve_expiry = fields.Date(string="Reserve Pool Expiry", readonly=True, copy=False)

    # ── Tick-box UX for Selected / Reserve, mutually exclusive ────────────
    mark_selected = fields.Boolean(
        string="Selected", compute="_compute_marks", inverse="_inverse_mark_selected", store=False
    )
    mark_reserve = fields.Boolean(
        string="Reserve", compute="_compute_marks", inverse="_inverse_mark_reserve", store=False
    )

    @api.depends("selection_status")
    def _compute_marks(self):
        for rec in self:
            rec.mark_selected = rec.selection_status == "selected"
            rec.mark_reserve = rec.selection_status == "reserve"

    def _inverse_mark_selected(self):
        for rec in self:
            if rec.mark_selected:
                rec._select_candidate()
                rec.message_post(body=_("Candidate marked as Selected."))
            elif rec.selection_status == "selected":
                rec.write({"selection_status": "pending"})

    def _inverse_mark_reserve(self):
        for rec in self:
            if rec.mark_reserve:
                if rec.disqualified:
                    raise ValidationError(_("Cannot reserve a disqualified candidate."))
                rec.action_set_reserve()
            elif rec.selection_status == "reserve":
                rec.write({"selection_status": "pending", "reserve_expiry": False})

    def _select_candidate(self):
        self.ensure_one()
        if self.disqualified:
            raise ValidationError(_("Cannot select a disqualified candidate."))

        slots = self.vacancy_id.no_of_vacancies or 0
        if slots <= 0:
            raise ValidationError(_(
                "Vacancy %s has no 'Number of Vacancies' set — cannot select candidates."
            ) % self.vacancy_id.reference)

        already_selected = self.env["recruitment.candidate.score"].search_count([
            ("vacancy_id", "=", self.vacancy_id.id),
            ("selection_status", "=", "selected"),
            ("id", "!=", self.id),
        ])
        if already_selected >= slots:
            raise ValidationError(_(
                "Vacancy %s allows only %d selected candidate(s), and that limit "
                "has already been reached. Deselect another candidate first, or "
                "add them to the Reserve Pool instead."
            ) % (self.vacancy_id.reference, slots))

        self.write({"selection_status": "selected", "reserve_expiry": False})

    # ── Hard backstop: catches bulk writes / multi_edit / imports / API ───
    @api.constrains("selection_status", "vacancy_id")
    def _check_selected_count_within_vacancy_slots(self):
        for vacancy in self.mapped("vacancy_id"):
            slots = vacancy.no_of_vacancies or 0
            selected_count = self.env["recruitment.candidate.score"].search_count([
                ("vacancy_id", "=", vacancy.id),
                ("selection_status", "=", "selected"),
            ])
            if slots and selected_count > slots:
                raise ValidationError(_(
                    "Vacancy %s has %d selected candidate(s), which exceeds the allowed "
                    "Number of Vacancies (%d). Please reduce the number of Selected candidates."
                ) % (vacancy.reference, selected_count, slots))

    _SCORE_FIELDS_INVALIDATING_CHECK = {
        "pms_score", "written_score", "interview_score",
        "pms_weight", "written_weight", "interview_weight",
    }

    def write(self, vals):
        """
        If any score or weight is edited after a disqualification check has
        already been run, the check is stale — clear disqualification_checked
        (unless this very write is the check itself setting it) so ranking
        is forced to require a fresh check again before it will run.
        """
        if self._SCORE_FIELDS_INVALIDATING_CHECK.intersection(vals.keys()) \
                and "disqualification_checked" not in vals:
            vals = dict(vals, disqualification_checked=False)
        return super().write(vals)

    @api.depends("applicant_id", "employee_id")
    def _compute_name(self):
        for rec in self:
            if rec.employee_id:
                rec.candidate_name = rec.employee_id.name
            elif rec.applicant_id:
                rec.candidate_name = rec.applicant_id.partner_name or rec.applicant_id.display_name
            else:
                rec.candidate_name = _("Unknown")

    # ── Job level visibility: clear it when vacancy is Managerial ─────────
    @api.onchange("vacancy_id", "vacancy_employee_category")
    def _onchange_vacancy_clear_job_level(self):
        for rec in self:
            if rec.vacancy_employee_category == "Managerial":
                rec.job_level = False

    @api.constrains("vacancy_employee_category", "job_level")
    def _check_job_level_required(self):
        for rec in self:
            if rec.vacancy_employee_category == "Non Managerial" and not rec.job_level:
                raise ValidationError(_(
                    "Job Level (Junior / Senior) is required for Non-Managerial vacancies."
                ))
            if rec.vacancy_employee_category == "Managerial" and rec.job_level:
                raise ValidationError(_(
                    "Job Level does not apply to Managerial vacancies — clear it before saving."
                ))

    # ── FR-REC-034: auto-populate weights from the matrix ─────────────────
    @api.onchange("recruitment_type", "vacancy_employee_category", "job_level")
    def _onchange_weight_defaults(self):
        for rec in self:
            if rec.weights_manually_set:
                continue
            level_key = False if rec.vacancy_employee_category == "Managerial" else rec.job_level
            key = (rec.recruitment_type, rec.vacancy_employee_category, level_key)
            weights = WEIGHT_MATRIX.get(key, DEFAULT_BOTH_WEIGHTS)
            rec.pms_weight, rec.written_weight, rec.interview_weight = weights

    @api.onchange("pms_weight", "written_weight", "interview_weight")
    def _onchange_weight_manual_edit(self):
        for rec in self:
            rec.weights_manually_set = True

    @api.constrains("pms_weight", "written_weight", "interview_weight", "recruitment_type")
    def _check_weights_sum(self):
        for rec in self:
            total = rec.pms_weight + rec.written_weight + rec.interview_weight
            if rec.recruitment_type == "external" and rec.pms_weight:
                raise ValidationError(_("External candidates cannot have a PMS weight."))
            if abs(total - 100.0) > 0.01:
                raise ValidationError(_(
                    "PMS + Exam + Interview weights must total 100%% (currently %.2f%%)."
                ) % total)

    @api.depends("pms_score", "written_score", "interview_score",
                 "pms_weight", "written_weight", "interview_weight",
                 "recruitment_type", "disqualified")
    def _compute_final_score(self):
        for rec in self:
            if rec.disqualified:
                rec.final_score = 0.0
                continue
            if rec.recruitment_type == "internal":
                rec.final_score = (
                        (rec.pms_score * rec.pms_weight / 100.0) +
                        (rec.written_score * rec.written_weight / 100.0) +
                        (rec.interview_score * rec.interview_weight / 100.0)
                )
            else:
                rec.final_score = (
                        (rec.written_score * rec.written_weight / 100.0) +
                        (rec.interview_score * rec.interview_weight / 100.0)
                )

    def action_apply_disqualification_check(self):
        """
        Section 9.2: disqualify a candidate if EITHER:
          - an individual component (Written Exam or Interview) is < 50%, OR
          - the overall WEIGHTED Final Score is < 50% (catches cases where
            each individual component looks fine but a low-scoring,
            heavily-weighted component — e.g. PMS — drags the weighted
            average below the gate).

        The weighted score is computed here directly from raw
        scores/weights rather than read from the stored `final_score`
        field, because `final_score` is forced to 0 once `disqualified`
        is True — reading it directly would make a second run on an
        already-disqualified record always see 0 and never re-clear them
        even if scores were corrected afterward.
        """
        for rec in self:
            reasons = []
            if rec.written_score < DISQUALIFICATION_THRESHOLD and rec.written_weight > 0:
                reasons.append(_("Written Exam score %.1f%% < 50%%") % rec.written_score)
            if rec.interview_score < DISQUALIFICATION_THRESHOLD and rec.interview_weight > 0:
                reasons.append(_("Interview score %.1f%% < 50%%") % rec.interview_score)

            if rec.recruitment_type == "internal":
                raw_final_score = (
                        (rec.pms_score * rec.pms_weight / 100.0) +
                        (rec.written_score * rec.written_weight / 100.0) +
                        (rec.interview_score * rec.interview_weight / 100.0)
                )
            else:
                raw_final_score = (
                        (rec.written_score * rec.written_weight / 100.0) +
                        (rec.interview_score * rec.interview_weight / 100.0)
                )
            if raw_final_score < DISQUALIFICATION_THRESHOLD:
                reasons.append(_("Overall weighted Final Score %.1f%% < 50%%") % raw_final_score)

            if reasons:
                rec.write({
                    "disqualified": True,
                    "disqualification_reason": "; ".join(reasons),
                    "selection_status": "disqualified",
                    "rank": 0,
                    "disqualification_checked": True,
                })
                rec.message_post(body=_("Candidate disqualified: %s") % "; ".join(reasons))
            else:
                rec.write({
                    "disqualified": False,
                    "disqualification_reason": False,
                    "disqualification_checked": True,
                })

    def action_apply_disqualification_check_menu(self):
        """
        Same disqualification check (Section 9.2), exposed separately in
        the list view's ⚙ Actions menu so it can run WITHOUT ticking any
        row checkboxes first — same no-selection scope resolution as the
        Rank / Rank & Auto-Select menu actions: uses the current list
        filter (active_domain) if nothing is selected, or every candidate
        score if no filter is active.
        """
        if self:
            candidates = self
        else:
            domain = self.env.context.get("active_domain") or []
            candidates = self.env["recruitment.candidate.score"].search(domain)
            if not candidates:
                raise UserError(_(
                    "No candidate scores found for the current list/filter — "
                    "nothing to check."
                ))

        candidates.action_apply_disqualification_check()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Disqualification Check Complete"),
                "message": _("%d candidate(s) checked against the 50%% gate.") % len(candidates),
                "type": "success",
                "sticky": False,
            },
        }

    def action_rank_candidates(self):
        """
        Section 9.3: mass-action from the LIST VIEW. Select any subset of
        candidate rows (typically all rows for one vacancy) and click
        'Rank Selected Candidates' — ranks all of them in a single pass
        instead of ranking record-by-record from the form. If the selection
        spans multiple vacancies, each vacancy's candidates rank independently.

        Required order: Check Disqualification → Rank → Auto-Select. To
        enforce this, every eligible (non-disqualified) candidate in the
        vacancy must have disqualification_checked = True — set by running
        'Check Disqualification (50% Gate)' — or this raises, telling the
        user to run that first. Editing any score/weight after a check
        clears disqualification_checked again (see write()), so a stale
        check can't be used to sneak past this gate.
        """
        if not self:
            raise UserError(_("Select at least one candidate to rank."))

        vacancies = self.mapped("vacancy_id")
        total_ranked = 0
        for vacancy in vacancies:
            eligible = self.env["recruitment.candidate.score"].search([
                ("vacancy_id", "=", vacancy.id),
                ("disqualified", "=", False),
            ])

            unchecked = eligible.filtered(lambda r: not r.disqualification_checked)
            if unchecked:
                raise UserError(_(
                    "Vacancy %s has %d candidate(s) that haven't been checked for "
                    "disqualification yet. Please run 'Check Disqualification (50%% "
                    "Gate)' first."
                ) % (vacancy.reference, len(unchecked)))

            def sort_key(r):
                gender_priority = 0 if (r.gender or "male") == "female" else 1
                return (-r.final_score, gender_priority, -r.pms_score)

            sorted_records = sorted(eligible, key=sort_key)
            for idx, rec in enumerate(sorted_records, start=1):
                rec.rank = idx
            total_ranked += len(sorted_records)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Candidates Ranked"),
                "message": _("%d candidates ranked across %d vacancy(ies).") % (total_ranked, len(vacancies)),
                "type": "success",
                "sticky": False,
            },
        }

    def action_auto_select_candidates(self):
        """
        Section 9.3.x: the ONE-CLICK action from the LIST VIEW header (and
        also callable from the form / gear menu). This is the ONLY path a
        user has to reach 'selected' or 'reserve' status — the manual
        mark_selected/mark_reserve tick-boxes are no longer exposed in
        the UI.

        Per vacancy, this does ALL of the following in one call — nothing
        needs to be run beforehand:
          1. Re-applies the disqualification check (Section 9.2, including
             the weighted Final Score gate) to every non-locked candidate,
             so a bad candidate is always caught even if this is the only
             button ever clicked.
          2. Ranks the remaining eligible (non-disqualified) candidates.
          3. Candidates already locked in by an ACCEPTED offer letter are
             left untouched throughout (retracting an accepted offer is a
             separate, deliberate action).
          4. Selects the top (slots - locked) candidates by rank.
          5. Every remaining eligible candidate beyond the slot count is
             put in the Reserve Pool (6-month expiry) instead of being
             left as 'Pending' — so after this runs, every candidate for
             the vacancy is Selected, Reserved, or Disqualified.

        Idempotent: re-running it (e.g. after scores change) recomputes
        everything from scratch for non-locked candidates.
        """
        if not self:
            raise UserError(_(
                "Select at least one candidate row (e.g. all rows for a vacancy) "
                "before clicking Auto-Select."
            ))

        Offer = self.env["recruitment.offer.letter"]
        Score = self.env["recruitment.candidate.score"]

        vacancies = self.mapped("vacancy_id")
        total_selected = 0
        total_reserved = 0

        for vacancy in vacancies:
            slots = vacancy.no_of_vacancies or 0
            if slots <= 0:
                raise UserError(_(
                    "Vacancy %s has no 'Number of Vacancies' set — cannot auto-select."
                ) % vacancy.reference)

            all_for_vacancy = Score.search([("vacancy_id", "=", vacancy.id)])

            # Candidates already locked in by an ACCEPTED offer — never re-evaluated.
            locked = Offer.search([
                ("vacancy_id", "=", vacancy.id),
                ("state", "=", "accepted"),
            ]).mapped("candidate_score_id")

            # 1. Disqualification check (component scores + weighted Final Score).
            (all_for_vacancy - locked).action_apply_disqualification_check()

            # 2. Rank the eligible (non-disqualified) candidates.
            eligible = Score.search([
                ("vacancy_id", "=", vacancy.id),
                ("disqualified", "=", False),
            ])

            def sort_key(r):
                gender_priority = 0 if (r.gender or "male") == "female" else 1
                return (-r.final_score, gender_priority, -r.pms_score)

            ranked_all = sorted(eligible, key=sort_key)
            for idx, rec in enumerate(ranked_all, start=1):
                rec.rank = idx

            # Free up everyone non-locked currently selected/reserved, for a clean recompute.
            (all_for_vacancy.filtered(lambda r: r.selection_status in ("selected", "reserve")) - locked).write(
                {"selection_status": "pending", "reserve_expiry": False}
            )

            # 4. Select top N (excluding locked, which already occupy slots).
            remaining_slots = slots - len(locked)
            ranked_unlocked = (eligible - locked).sorted(key=lambda r: r.rank)
            top_n = ranked_unlocked[:max(remaining_slots, 0)]
            overflow = ranked_unlocked[max(remaining_slots, 0):]

            for rec in top_n:
                rec._select_candidate()

            # 5. Reserve everyone else eligible, instead of leaving them Pending.
            if overflow:
                overflow.action_set_reserve()

            total_selected += len(top_n) + len(locked)
            total_reserved += len(overflow)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Candidates Auto-Selected"),
                "message": _("%d selected, %d reserved, across %d vacancy(ies).") % (
                    total_selected, total_reserved, len(vacancies)
                ),
                "type": "success",
                "sticky": False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_rank_and_auto_select(self):
        """
        Combined one-click action: rank, then auto-select — bound to the
        list view's ⚙ Actions menu, so it's usable WITHOUT ticking any row
        checkboxes first (unlike the <header> buttons, which only appear
        once at least one row is selected).

        Scope of "which candidates":
          - If called with a non-empty recordset (e.g. triggered from a
            manual row selection), rank/select only those candidates'
            vacancies — same as running the two separate buttons.
          - If called with an EMPTY recordset (e.g. clicked from the ⚙
            menu with nothing ticked), Odoo still passes along the current
            list view's search filters as `active_domain` in the context.
            We use that domain to find the in-scope candidates; if no
            filter is active, that means "every candidate score record."
        """
        if self:
            vacancies = self.mapped("vacancy_id")
        else:
            domain = self.env.context.get("active_domain") or []
            in_scope = self.env["recruitment.candidate.score"].search(domain)
            vacancies = in_scope.mapped("vacancy_id")
            if not vacancies:
                raise UserError(_(
                    "No candidate scores found for the current list/filter — "
                    "nothing to rank or select."
                ))

        Score = self.env["recruitment.candidate.score"]
        all_candidates = Score.search([("vacancy_id", "in", vacancies.ids)])

        # action_auto_select_candidates now runs disqualification + ranking
        # internally, so it doesn't need a separate rank pass beforehand.
        return all_candidates.action_auto_select_candidates()

    def action_rank_candidates_menu(self):
        """
        Same ranking as action_rank_candidates (Section 9.3), but exposed
        separately in the list view's ⚙ Actions menu so ranking alone can
        be run WITHOUT ticking any row checkboxes first — same
        no-selection scope resolution as action_rank_and_auto_select:
        uses the current list filter (active_domain) if nothing is
        selected, or falls back to every candidate score if no filter is
        active. Selection is intentionally NOT run here — this only
        updates the Rank column.
        """
        if self:
            vacancies = self.mapped("vacancy_id")
        else:
            domain = self.env.context.get("active_domain") or []
            in_scope = self.env["recruitment.candidate.score"].search(domain)
            vacancies = in_scope.mapped("vacancy_id")
            if not vacancies:
                raise UserError(_(
                    "No candidate scores found for the current list/filter — "
                    "nothing to rank."
                ))

        Score = self.env["recruitment.candidate.score"]
        all_candidates = Score.search([("vacancy_id", "in", vacancies.ids)])
        return all_candidates.action_rank_candidates()

    def action_set_reserve(self):
        """Section 9.4: mark as reserve with 6-month expiry."""
        expiry = fields.Date.today() + timedelta(days=180)
        for rec in self:
            rec.write({"selection_status": "reserve", "reserve_expiry": expiry})
            rec.message_post(body=_("Candidate added to Reserve Pool. Expires: %s") % expiry)

    @api.model
    def _cron_expire_reserve_pool(self):
        """Section 9.4.2: automatically expire reserve status after 6 months."""
        today = fields.Date.today()
        expired = self.search([
            ("selection_status", "=", "reserve"),
            ("reserve_expiry", "<", today),
        ])
        expired.write({"selection_status": "rejected"})
        for rec in expired:
            rec.message_post(body=_("Reserve pool status expired automatically."))


# ── Section 11: Offer Management ────────────────────────────────────────────

class RecruitmentOfferLetter(models.Model):
    """
    Section 11.2: Job Offer Letter with 3-day response window and cascade logic.
    """
    _name = "recruitment.offer.letter"
    _inherit = ["mail.thread"]
    _description = "Job Offer Letter"
    _rec_name = "reference"
    _order = "offer_date desc"

    reference = fields.Char(string="Offer Reference", copy=False, readonly=True,
                            default=lambda self: _("New"))
    vacancy_id = fields.Many2one("job.vacancy", string="Vacancy", required=True, tracking=True)
    candidate_score_id = fields.Many2one("recruitment.candidate.score", string="Candidate", required=True,
                                         domain="[('vacancy_id','=',vacancy_id),('selection_status','in',['pending','reserve','selected'])]")
    candidate_name = fields.Char(related="candidate_score_id.candidate_name", store=True)

    offer_date = fields.Date(string="Offer Issue Date", default=fields.Date.context_today, required=True)
    response_deadline = fields.Date(string="Response Deadline", compute="_compute_deadline", store=True)

    response = fields.Selection(
        [("pending", "Awaiting Response"), ("accepted", "Accepted"), ("declined", "Declined"), ("expired", "Expired")],
        string="Candidate Response", default="pending", tracking=True
    )
    response_date = fields.Date(string="Response Date", readonly=True, copy=False)

    employment_letter_generated = fields.Boolean(string="Employment Letter Generated", default=False, readonly=True)

    state = fields.Selection(
        [("draft", "Draft"), ("sent", "Offer Sent"), ("accepted", "Accepted"),
         ("declined", "Declined"), ("expired", "Expired"), ("cascaded", "Cascaded")],
        string="Status", default="draft", tracking=True, copy=False
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("reference") or vals["reference"] == _("New"):
                vals["reference"] = (
                        self.env["ir.sequence"].next_by_code("recruitment.offer.letter") or _("New")
                )
        return super().create(vals_list)

    @api.depends("offer_date")
    def _compute_deadline(self):
        for rec in self:
            if rec.offer_date:
                rec.response_deadline = rec.offer_date + timedelta(days=OFFER_RESPONSE_DAYS)
            else:
                rec.response_deadline = False

    def action_send_offer(self):
        """11.2.1: Send the offer letter. Selection now routes through the
        validated _select_candidate() so the vacancy slot cap is respected
        even when this fires automatically from a cascade."""
        for rec in self:
            rec.write({"state": "sent"})
            rec.candidate_score_id._select_candidate()
            rec.message_post(body=_(
                "Offer letter sent to <b>%s</b>. Response deadline: <b>%s</b>."
            ) % (rec.candidate_name, rec.response_deadline))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Offer Sent"),
                "message": _("Offer letter sent. Candidate has %d days to respond.") % OFFER_RESPONSE_DAYS,
                "type": "success",
                "sticky": False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_accept(self):
        """Candidate accepts — generate employment letter."""
        for rec in self:
            rec.write({
                "state": "accepted",
                "response": "accepted",
                "response_date": fields.Date.today(),
            })
            rec.message_post(body=_("Offer accepted by %s.") % rec.candidate_name)
            rec._generate_employment_letter()

    def _generate_employment_letter(self):
        """11.3: Generate employment letter on acceptance."""
        self.ensure_one()
        self.write({"employment_letter_generated": True})
        self.message_post(body=_(
            "Employment letter generated for <b>%s</b>. Distributed to Payroll and HR."
        ) % self.candidate_name)

    def action_decline(self):
        """11.2.3: Candidate declines — frees the slot, then cascades to the
        next ranked candidate."""
        for rec in self:
            rec.write({
                "state": "declined",
                "response": "declined",
                "response_date": fields.Date.today(),
            })
            rec.candidate_score_id.write({"selection_status": "rejected"})
            rec.message_post(body=_("Offer declined by %s. Cascading to next candidate.") % rec.candidate_name)
            rec._cascade_to_next_candidate()

    def _cascade_to_next_candidate(self):
        """
        Find the next-ranked eligible candidate — not disqualified, and
        currently 'pending' or 'reserve' — and automatically create + send
        them an offer. Sending the offer is what flips their status to
        'selected' (via _select_candidate()), so the vacancy slot cap is
        always respected on every hop of the cascade.
        """
        self.ensure_one()
        current_rank = self.candidate_score_id.rank

        Score = self.env["recruitment.candidate.score"]
        next_candidate = Score.search([
            ("vacancy_id", "=", self.vacancy_id.id),
            ("disqualified", "=", False),
            ("selection_status", "in", ("pending", "reserve")),
            ("rank", ">", current_rank),
        ], order="rank asc", limit=1)

        if next_candidate:
            new_offer = self.create({
                "vacancy_id": self.vacancy_id.id,
                "candidate_score_id": next_candidate.id,
            })
            new_offer.message_post(body=_(
                "Offer cascaded from %s (rank %d) after decline/expiry."
            ) % (self.candidate_name, current_rank))
            self.write({"state": "cascaded"})
            new_offer.action_send_offer()
        else:
            self.message_post(body=_(
                "No more eligible candidates (pending or reserve) to cascade the offer to."
            ))

    @api.model
    def _cron_expire_pending_offers(self):
        """11.2.2: Auto-expire offers that exceeded the 3-day response window."""
        today = fields.Date.today()
        expired = self.search([
            ("state", "=", "sent"),
            ("response_deadline", "<", today),
        ])
        for rec in expired:
            rec.write({"state": "expired", "response": "expired"})
            rec.candidate_score_id.write({"selection_status": "rejected"})
            rec.message_post(body=_("Offer expired. Response deadline %s passed.") % rec.response_deadline)
            rec._cascade_to_next_candidate()


# ── Section 5: Application Window Enforcement ────────────────────────────────

class RecruitmentApplicationWindow(models.Model):
    _name = "recruitment.application.window"
    _description = "Internal Application Window"
    _rec_name = "vacancy_id"

    vacancy_id = fields.Many2one("job.vacancy", string="Vacancy", required=True, ondelete="cascade")
    notification_date = fields.Date(string="Notification Sent Date", required=True,
                                    default=fields.Date.context_today)
    deadline = fields.Date(string="Application Deadline", compute="_compute_deadline", store=True)
    is_closed = fields.Boolean(string="Window Closed", default=False)
    late_inclusion_allowed = fields.Boolean(string="Late Inclusion Allowed", default=False)
    late_inclusion_justification = fields.Text(string="Justification for Late Inclusion")

    @api.depends("notification_date")
    def _compute_deadline(self):
        for rec in self:
            if rec.notification_date:
                rec.deadline = rec.notification_date + timedelta(days=INTERNAL_APPLICATION_DAYS)
            else:
                rec.deadline = False

    def check_application_allowed(self, application_date=None):
        self.ensure_one()
        today = application_date or fields.Date.today()
        if self.is_closed and not self.late_inclusion_allowed:
            return False
        if today > self.deadline and not self.late_inclusion_allowed:
            return False
        return True

    @api.model
    def _cron_close_expired_windows(self):
        today = fields.Date.today()
        windows = self.search([
            ("is_closed", "=", False),
            ("deadline", "<", today),
        ])
        windows.write({"is_closed": True})
        for w in windows:
            w.vacancy_id.message_post(
                body=_("Internal application window closed. Deadline %s has passed.") % w.deadline
            )


# ── Section 6: Blacklist Check ───────────────────────────────────────────────

class BlacklistPool(models.Model):
    _inherit = "blacklist.pool"

    national_id = fields.Char(string="National ID")
    reason = fields.Text(string="Reason for Blacklisting")
    blacklisted_on = fields.Date(string="Blacklisted On", default=fields.Date.context_today)
    active = fields.Boolean(default=True)

    @api.model
    def is_blacklisted(self, name=None, national_id=None):
        domain = []
        if national_id:
            domain = [("national_id", "=", national_id), ("active", "=", True)]
        elif name:
            domain = [("candidate", "ilike", name), ("active", "=", True)]
        else:
            return self.browse()
        return self.search(domain, limit=1)


class ApplicantAssessmentBlacklistCheck(models.Model):
    _inherit = "hr.applicant"

    blacklist_checked = fields.Boolean(string="Blacklist Checked", default=False, readonly=True)
    blacklist_status = fields.Selection(
        [("clear", "Clear"), ("flagged", "Flagged - On Blacklist"), ("not_checked", "Not Checked")],
        string="Blacklist Status", default="not_checked", readonly=True
    )

    def action_check_blacklist(self):
        for rec in self:
            blacklist = self.env["blacklist.pool"]
            partner_name = rec.partner_name or ""
            result = blacklist.is_blacklisted(name=partner_name)
            if result:
                rec.write({"blacklist_checked": True, "blacklist_status": "flagged"})
                rec.message_post(body=_(
                    "⚠️ BLACKLIST ALERT: Applicant <b>%s</b> is on the blacklist. "
                    "Reason: %s. This application requires HR review before proceeding."
                ) % (partner_name, result.reason or _("Not specified")))
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": _("Blacklist Alert"),
                        "message": _("%s is flagged on the blacklist!") % partner_name,
                        "type": "danger",
                        "sticky": True,
                        'next': {'type': 'ir.actions.client', 'tag': 'reload'},
                    },
                }
            else:
                rec.write({"blacklist_checked": True, "blacklist_status": "clear"})
                rec.message_post(body=_("Blacklist check complete: %s is clear.") % partner_name)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Blacklist Check Complete"),
                "message": _("All selected applicants passed the blacklist check."),
                "type": "success",
                "sticky": False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }
