# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

# Fiscal months of the Bank's planning year: July -> June
FISCAL_MONTHS = [
    ("m01", "Jul"), ("m02", "Aug"), ("m03", "Sep"), ("m04", "Oct"),
    ("m05", "Nov"), ("m06", "Dec"), ("m07", "Jan"), ("m08", "Feb"),
    ("m09", "Mar"), ("m10", "Apr"), ("m11", "May"), ("m12", "Jun"),
]
MONTH_FIELDS = [f for f, _label in FISCAL_MONTHS]
QUARTERS = {
    "q1": MONTH_FIELDS[0:3],
    "q2": MONTH_FIELDS[3:6],
    "q3": MONTH_FIELDS[6:9],
    "q4": MONTH_FIELDS[9:12],
}


class PbmsPlanLineMixin(models.AbstractModel):
    """Monthly-target grid (Jul-Jun) layered on top of the generic
    approval workflow (pbms.workflow.mixin). Used by planning formats
    whose targets are expressed as 12 monthly figures: Deposit,
    Customer Base, FX Mobilization, Digital Banking, General Expense.

    Itemized formats (Manpower, Fixed Asset) inherit
    pbms.workflow.mixin directly instead - see pbms_manpower_plan.py.

    Performance notes:
    * quarterly/annual totals are *stored* computed fields so
      dashboards/reports can filter and group on them via read_group
      (SQL-side aggregation) instead of summing in Python per request.
    * The compute method loops over `self` once and reads all 12
      fields per record in one pass, rather than 12 separate compute
      methods - this matters once recordsets reach thousands of lines
      (300+ branches x 7 monthly formats x several deposit/expense
      types each).
    """
    _name = "pbms.plan.line.mixin"
    _description = "PBMS Monthly Planning Line (abstract)"
    _inherit = "pbms.workflow.mixin"

    m01 = fields.Float(string="Jul")
    m02 = fields.Float(string="Aug")
    m03 = fields.Float(string="Sep")
    m04 = fields.Float(string="Oct")
    m05 = fields.Float(string="Nov")
    m06 = fields.Float(string="Dec")
    m07 = fields.Float(string="Jan")
    m08 = fields.Float(string="Feb")
    m09 = fields.Float(string="Mar")
    m10 = fields.Float(string="Apr")
    m11 = fields.Float(string="May")
    m12 = fields.Float(string="Jun")

    quarter1_total = fields.Float(string="QI", compute="_compute_totals", store=True)
    quarter2_total = fields.Float(string="QII", compute="_compute_totals", store=True)
    quarter3_total = fields.Float(string="QIII", compute="_compute_totals", store=True)
    quarter4_total = fields.Float(string="QIV", compute="_compute_totals", store=True)
    annual_total = fields.Float(string="Annual Total", compute="_compute_totals", store=True, index=True)

    display_quarter = fields.Selection(
        [
            ("all", "All Quarters"),
            ("q1", "QI"),
            ("q2", "QII"),
            ("q3", "QIII"),
            ("q4", "QIV"),
        ],
        string="Display Quarter",
        default="all",
        help="Select a quarter to filter the displayed months.",
    )

    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id,
    )

    @api.depends(*MONTH_FIELDS)
    def _compute_totals(self):
        for line in self:
            values = {f: (getattr(line, f) or 0.0) for f in MONTH_FIELDS}
            line.quarter1_total = sum(values[f] for f in QUARTERS["q1"])
            line.quarter2_total = sum(values[f] for f in QUARTERS["q2"])
            line.quarter3_total = sum(values[f] for f in QUARTERS["q3"])
            line.quarter4_total = sum(values[f] for f in QUARTERS["q4"])
            line.annual_total = sum(values.values())

    def _protected_write_fields(self):
        return MONTH_FIELDS

    @api.constrains(*MONTH_FIELDS)
    def _check_target_values(self):
        for line in self:
            for fname in MONTH_FIELDS:
                val = getattr(line, fname)
                if val is not None and val < 0 and not line._allow_negative_targets():
                    raise ValidationError(_(
                        "%(month)s target on %(unit)s cannot be negative.",
                        month=dict(FISCAL_MONTHS)[fname], unit=line.org_unit_id.display_name,
                    ))

    def _allow_negative_targets(self):
        """Override where a negative figure is meaningful, e.g. a
        planned reduction in dormant accounts."""
        return False
