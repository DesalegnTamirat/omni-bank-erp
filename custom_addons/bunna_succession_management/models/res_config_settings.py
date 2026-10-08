# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ── 9-Box Grid Thresholds ─────────────────────────────────────────────────
    succ_high_perf_threshold = fields.Float(
        related='company_id.succ_high_perf_threshold', readonly=False)
    succ_med_perf_threshold = fields.Float(
        related='company_id.succ_med_perf_threshold', readonly=False)
    succ_high_pot_threshold = fields.Float(
        related='company_id.succ_high_pot_threshold', readonly=False)
    succ_med_pot_threshold = fields.Float(
        related='company_id.succ_med_pot_threshold', readonly=False)

    # ── Governance Rules ──────────────────────────────────────────────────────
    succ_min_successors_global = fields.Integer(
        related='company_id.succ_min_successors_global', readonly=False)
    succ_risk_review_months = fields.Integer(
        related='company_id.succ_risk_review_months', readonly=False)
    succ_require_spmc_approval = fields.Boolean(
        related='company_id.succ_require_spmc_approval', readonly=False)
    succ_auto_deactivate_on_fill = fields.Boolean(
        related='company_id.succ_auto_deactivate_on_fill', readonly=False)

    # ── Readiness & Pipeline Rules ────────────────────────────────────────────
    succ_readiness_review_months = fields.Integer(
        related='company_id.succ_readiness_review_months', readonly=False)
    succ_idp_mandatory = fields.Boolean(
        related='company_id.succ_idp_mandatory', readonly=False)
    succ_career_discussion_mandatory = fields.Boolean(
        related='company_id.succ_career_discussion_mandatory', readonly=False)
    succ_auto_match_min_score = fields.Float(
        related='company_id.succ_auto_match_min_score', readonly=False)
    succ_ready_now_min_match = fields.Float(
        related='company_id.succ_ready_now_min_match', readonly=False)
    succ_ready_soon_min_match = fields.Float(
        related='company_id.succ_ready_soon_min_match', readonly=False)

    # ── Scoring Weights ───────────────────────────────────────────────────────
    succ_score_weight_competency = fields.Float(
        related='company_id.succ_score_weight_competency', readonly=False)
    succ_score_weight_pms = fields.Float(
        related='company_id.succ_score_weight_pms', readonly=False)

    # ── Alerts & Notifications ────────────────────────────────────────────────
    succ_alert_critical_no_successors = fields.Boolean(
        related='company_id.succ_alert_critical_no_successors', readonly=False)
    succ_alert_idp_overdue = fields.Boolean(
        related='company_id.succ_alert_idp_overdue', readonly=False)
    succ_alert_readiness_expiry = fields.Boolean(
        related='company_id.succ_alert_readiness_expiry', readonly=False)

    # ── 9-Box Cell Definitions (read-only display helper) ─────────────────────
    ninebox_cell_ids = fields.Many2many(
        'succession.ninebox.cell',
        string='9-Box Cell Definitions',
        compute='_compute_ninebox_cell_ids',
        readonly=False,
    )

    def _compute_ninebox_cell_ids(self):
        cells = self.env['succession.ninebox.cell'].search([])
        for rec in self:
            rec.ninebox_cell_ids = cells
