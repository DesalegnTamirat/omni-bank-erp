# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .pbms_plan_line_mixin import MONTH_FIELDS


class PbmsCumulativePlanMixin(models.AbstractModel):
    """Adds an opening balance + running cumulative/outstanding total on
    top of the monthly grid (pbms.plan.line.mixin). Used by every format
    where the BRD calls for 'outstanding' figures, not just net monthly
    ones: Deposit Mobilization, Customer Base, FX Mobilization, Digital
    Banking.

    Split out from pbms.plan.line.mixin (rather than folded into it)
    because General Expense and other pure-budget formats don't have a
    meaningful "outstanding balance" concept - they'd carry 12 unused
    Monetary fields for nothing.
    """
    _name = "pbms.cumulative.plan.mixin"
    _description = "PBMS Cumulative/Outstanding Planning Line (abstract)"
    _inherit = "pbms.plan.line.mixin"

    opening_balance = fields.Monetary(
        string="Outstanding Balance for End Period (Actual)",
        help="Actual closing balance of the prior period, used as the "
             "base for cumulative outstanding projections.",
    )

    cumulative_m01 = fields.Monetary(string="Jul (Cum.)", compute="_compute_cumulative", store=True)
    cumulative_m02 = fields.Monetary(string="Aug (Cum.)", compute="_compute_cumulative", store=True)
    cumulative_m03 = fields.Monetary(string="Sep (Cum.)", compute="_compute_cumulative", store=True)
    cumulative_m04 = fields.Monetary(string="Oct (Cum.)", compute="_compute_cumulative", store=True)
    cumulative_m05 = fields.Monetary(string="Nov (Cum.)", compute="_compute_cumulative", store=True)
    cumulative_m06 = fields.Monetary(string="Dec (Cum.)", compute="_compute_cumulative", store=True)
    cumulative_m07 = fields.Monetary(string="Jan (Cum.)", compute="_compute_cumulative", store=True)
    cumulative_m08 = fields.Monetary(string="Feb (Cum.)", compute="_compute_cumulative", store=True)
    cumulative_m09 = fields.Monetary(string="Mar (Cum.)", compute="_compute_cumulative", store=True)
    cumulative_m10 = fields.Monetary(string="Apr (Cum.)", compute="_compute_cumulative", store=True)
    cumulative_m11 = fields.Monetary(string="May (Cum.)", compute="_compute_cumulative", store=True)
    outstanding_year_end = fields.Monetary(
        string="Projected Year-End Outstanding",
        compute="_compute_cumulative", store=True, index=True,
    )

    _CUMULATIVE_FIELDS = [
        "cumulative_m01", "cumulative_m02", "cumulative_m03", "cumulative_m04",
        "cumulative_m05", "cumulative_m06", "cumulative_m07", "cumulative_m08",
        "cumulative_m09", "cumulative_m10", "cumulative_m11",
    ]

    @api.depends("opening_balance", *MONTH_FIELDS)
    def _compute_cumulative(self):
        # One pass per record (O(12)) rather than 11 separate compute
        # methods, so a single monthly-figure edit doesn't trigger 11x
        # recomputation overhead.
        for rec in self:
            running = rec.opening_balance or 0.0
            for month_field, cum_field in zip(MONTH_FIELDS[:11], self._CUMULATIVE_FIELDS):
                running += getattr(rec, month_field) or 0.0
                rec[cum_field] = running
            rec.outstanding_year_end = running + (rec.m12 or 0.0)
