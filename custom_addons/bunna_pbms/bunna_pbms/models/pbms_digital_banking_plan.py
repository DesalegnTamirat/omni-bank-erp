# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PbmsDigitalChannel(models.Model):
    """Configurable digital-banking channel/product list (Mobile Banking
    Activation, ATM Card Activation, Active Merchant, Quality Merchant,
    Merchant Residual Deposits, ...)."""
    _name = "pbms.digital.channel"
    _description = "Digital Banking Channel"
    _order = "sequence, name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    unit_of_measure = fields.Selection(
        [("count", "Count"), ("amount", "Amount")], required=True, default="count",
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("code_uniq", "unique(code)", "Digital channel code must be unique."),
    ]


class PbmsDigitalBankingPlan(models.Model):
    """Digital Banking Plan: monthly + cumulative + outstanding targets
    per digital channel (BRD 8.1 Digital Banking Plan)."""
    _name = "pbms.digital.banking.plan"
    _description = "Digital Banking Plan"
    _inherit = ["pbms.cumulative.plan.mixin", "mail.thread", "mail.activity.mixin"]
    _rec_name = "display_name"

    channel_id = fields.Many2one(
        "pbms.digital.channel", required=True, index=True, tracking=True,
    )
    display_name = fields.Char(compute="_compute_display_name", store=True)

    @api.depends("org_unit_id", "channel_id", "cycle_id")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = " / ".join(filter(None, [
                rec.org_unit_id.display_name, rec.channel_id.name, rec.cycle_id.name,
            ]))

    def _get_duplicate_domain(self):
        self.ensure_one()
        domain = super()._get_duplicate_domain()
        return domain + [("channel_id", "=", self.channel_id.id)]

    @api.model
    def _consolidate_district_plan_data(self, cycle_id, district):
        from .pbms_plan_line_mixin import MONTH_FIELDS
        branch_plans = self.search([
            ("cycle_id", "=", cycle_id.id),
            ("district_id", "=", district.id),
            ("state", "=", "district_approved"),
            ("org_unit_id", "!=", district.id),
        ])
        grouped = {}
        for p in branch_plans:
            key = p.channel_id.id
            if key not in grouped:
                grouped[key] = {
                    "opening_balance": 0.0,
                    **{f: 0.0 for f in MONTH_FIELDS}
                }
            grouped[key]["opening_balance"] += (p.opening_balance or 0.0)
            for f in MONTH_FIELDS:
                grouped[key][f] += (getattr(p, f) or 0.0)

        for channel_id, vals in grouped.items():
            dist_plan = self.search([
                ("cycle_id", "=", cycle_id.id),
                ("org_unit_id", "=", district.id),
                ("channel_id", "=", channel_id),
            ], limit=1)
            vals_to_write = {
                "opening_balance": vals["opening_balance"],
                **{f: vals[f] for f in MONTH_FIELDS}
            }
            if dist_plan:
                dist_plan.write(vals_to_write)
            else:
                vals_to_create = {
                    "cycle_id": cycle_id.id,
                    "org_unit_id": district.id,
                    "channel_id": channel_id,
                    "state": "draft",
                    **vals_to_write,
                }
                self.create(vals_to_create)

    @api.model
    def _consolidate_ho_plan_data(self, cycle_id, ho_unit):
        from .pbms_plan_line_mixin import MONTH_FIELDS
        dist_plans = self.search([
            ("cycle_id", "=", cycle_id.id),
            ("org_unit_type", "=", "district_office"),
            ("state", "in", ("submitted", "ho_reviewed", "approved")),
        ])
        grouped = {}
        for p in dist_plans:
            key = p.channel_id.id
            if key not in grouped:
                grouped[key] = {
                    "opening_balance": 0.0,
                    **{f: 0.0 for f in MONTH_FIELDS}
                }
            grouped[key]["opening_balance"] += (p.opening_balance or 0.0)
            for f in MONTH_FIELDS:
                grouped[key][f] += (getattr(p, f) or 0.0)

        for channel_id, vals in grouped.items():
            ho_plan = self.search([
                ("cycle_id", "=", cycle_id.id),
                ("org_unit_id", "=", ho_unit.id),
                ("channel_id", "=", channel_id),
            ], limit=1)
            vals_to_write = {
                "opening_balance": vals["opening_balance"],
                **{f: vals[f] for f in MONTH_FIELDS}
            }
            if ho_plan:
                ho_plan.write(vals_to_write)
            else:
                vals_to_create = {
                    "cycle_id": cycle_id.id,
                    "org_unit_id": ho_unit.id,
                    "channel_id": channel_id,
                    "state": "draft",
                    **vals_to_write,
                }
                self.create(vals_to_create)
