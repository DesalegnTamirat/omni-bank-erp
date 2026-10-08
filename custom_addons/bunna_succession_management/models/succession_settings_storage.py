# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    # ─────────────────────────────────────────────────────────────────────────
    # 9-BOX GRID THRESHOLDS
    # ─────────────────────────────────────────────────────────────────────────
    succ_high_perf_threshold = fields.Float(
        string='High Performance Threshold (≥ PMS Score)',
        default=85.0,
        help="Employees scoring at or above this PMS score are classified as "
             "High Performers on the 9-Box Grid (top row). Recommended: 80–90."
    )
    succ_med_perf_threshold = fields.Float(
        string='Medium Performance Threshold (≥ PMS Score)',
        default=70.0,
        help="Employees scoring at or above this PMS score (but below the High "
             "threshold) are classified as Medium Performers (middle row). "
             "Recommended: 65–79. Must be less than the High threshold."
    )
    succ_high_pot_threshold = fields.Float(
        string='High Potential Threshold (≥ Match %)',
        default=80.0,
        help="Candidates with a competency match of at or above this percentage "
             "are classified as High Potential on the 9-Box Grid (right column). "
             "Recommended: 75–85%."
    )
    succ_med_pot_threshold = fields.Float(
        string='Medium Potential Threshold (≥ Match %)',
        default=60.0,
        help="Candidates with a competency match at or above this percentage "
             "(but below the High threshold) are Medium Potential (middle column). "
             "Recommended: 50–74%. Must be less than the High threshold."
    )

    # ─────────────────────────────────────────────────────────────────────────
    # SUCCESSION GOVERNANCE RULES
    # ─────────────────────────────────────────────────────────────────────────
    succ_min_successors_global = fields.Integer(
        string='Minimum Successors Required (Global Default)',
        default=2,
        help="The minimum number of approved successor candidates required for "
             "any Critical Position before its succession risk can drop below "
             "'High'. This is the bank-wide default; each position can override "
             "it individually. Best practice: 2–3 successors."
    )
    succ_risk_review_months = fields.Integer(
        string='Succession Risk Review Cycle (Months)',
        default=6,
        help="How often (in months) the system should automatically trigger a "
             "risk recalculation and alert PPDD to review critical positions. "
             "Recommended: every 6 months (twice a year)."
    )
    succ_require_spmc_approval = fields.Boolean(
        string='Require SPMC Approval for Critical Positions',
        default=True,
        help="When enabled, all Critical Positions must pass through the full "
             "PPDD → SPMC governance workflow before candidates can be formally "
             "nominated. Disable only during initial system setup or data migration."
    )
    succ_auto_deactivate_on_fill = fields.Boolean(
        string='Auto-Deactivate Position When Vacancy is Filled',
        default=False,
        help="When enabled, a Critical Position will be automatically moved to "
             "'Deactivated' state once a candidate is marked as 'Placed' in the "
             "role, removing it from the active succession pipeline."
    )

    # ─────────────────────────────────────────────────────────────────────────
    # READINESS & PIPELINE RULES
    # ─────────────────────────────────────────────────────────────────────────
    succ_readiness_review_months = fields.Integer(
        string='Readiness Review Reminder (Months)',
        default=6,
        help="Number of months between mandatory readiness review dates for each "
             "approved candidate. After this period, the candidate's readiness "
             "level will be flagged for update by PPDD. Recommended: 6 months."
    )
    succ_idp_mandatory = fields.Boolean(
        string='Require Development Plan (IDP) Before Candidate Approval',
        default=True,
        help="When enabled, a Succession Development Plan (IDP) must be created "
             "for a candidate before SPMC can mark them as 'Approved'. Enforces "
             "best-practice development governance."
    )
    succ_career_discussion_mandatory = fields.Boolean(
        string='Require Career Discussion Before IDP Creation',
        default=True,
        help="When enabled, at least one confirmed Career Discussion must exist "
             "for an employee before a Succession Development Plan (IDP) can be "
             "created for them. Ensures employee buy-in before development begins."
    )
    succ_auto_match_min_score = fields.Float(
        string='Auto-Match Minimum Eligibility Score (%)',
        default=30.0,
        help="Minimum competency match percentage for a candidate to appear."
    )
    succ_ready_now_min_match = fields.Float(
        string='Ready Now Minimum Match (%)',
        default=90.0,
        help="Minimum competency match percentage to be automatically suggested as Ready Now."
    )
    succ_ready_soon_min_match = fields.Float(
        string='Ready Soon Minimum Match (%)',
        default=70.0,
        help="Minimum competency match percentage to be automatically suggested as Ready Soon."
    )

    # ─────────────────────────────────────────────────────────────────────────
    # BENCH STRENGTH SCORING WEIGHTS
    # ─────────────────────────────────────────────────────────────────────────
    succ_score_weight_competency = fields.Float(
        string='Competency Match Weight (%)',
        default=60.0,
        help="The percentage weight given to Competency Match when calculating "
             "a candidate's overall succession readiness score. Must sum to 100% "
             "together with the PMS weight. Recommended: 60% (competency-led "
             "succession is more forward-looking)."
    )
    succ_score_weight_pms = fields.Float(
        string='PMS Score Weight (%)',
        default=40.0,
        help="The percentage weight given to PMS (Performance) Score when "
             "calculating a candidate's overall succession readiness score. "
             "Must sum to 100% with the Competency weight. Recommended: 40%."
    )

    # ─────────────────────────────────────────────────────────────────────────
    # ALERTS & NOTIFICATIONS
    # ─────────────────────────────────────────────────────────────────────────
    succ_alert_critical_no_successors = fields.Boolean(
        string='Alert PPDD When Critical Position Has No Successors',
        default=True,
        help="When enabled, the system will send an email/internal notification "
             "to the PPDD team whenever an Approved Critical Position has zero "
             "nominated candidates. Triggered weekly by the scheduled cron job."
    )
    succ_alert_idp_overdue = fields.Boolean(
        string='Alert When IDP Activities Are Overdue',
        default=True,
        help="When enabled, email notifications are sent to the responsible "
             "manager and PPDD when a Succession Development Plan activity "
             "passes its target completion date without being marked done."
    )
    succ_alert_readiness_expiry = fields.Boolean(
        string='Alert When Readiness Review Is Overdue',
        default=True,
        help="Triggers an alert when a candidate's last readiness assessment "
             "exceeds the configured Readiness Review Cycle without update. "
             "Ensures the pipeline data remains current and reliable."
    )
