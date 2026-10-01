# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PbmsFxPlan(models.Model):
    """FX Mobilization Plan: foreign-currency inflow targets by source
    (BRD 8.1 FX Mobilization Plan). Remittance-SWIFT is bank-level only;
    Cash Purchase-Export and Purchase from NBE/Other Bank are planned at
    branch/district level too."""
    _name = "pbms.fx.plan"
    _description = "FX Mobilization Plan"
    _inherit = ["pbms.cumulative.plan.mixin", "mail.thread", "mail.activity.mixin"]
    _rec_name = "display_name"

    fx_source_type = fields.Selection(
        [
            ("remittance_swift", "Remittance - SWIFT"),
            ("cash_export", "Cash Purchase - Export"),
            ("purchase_nbe_other", "Purchase from NBE / Other Bank"),
        ],
        required=True, default="cash_export", index=True, tracking=True,
    )

    display_name = fields.Char(compute="_compute_display_name", store=True)

    @api.depends("org_unit_id", "fx_source_type", "cycle_id")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = " / ".join(filter(None, [
                rec.org_unit_id.display_name,
                dict(rec._fields["fx_source_type"].selection).get(rec.fx_source_type),
                rec.cycle_id.name,
            ]))

    @api.constrains("fx_source_type", "org_unit_id")
    def _check_swift_bank_level_only(self):
        for rec in self:
            if rec.fx_source_type == "remittance_swift" and rec.org_unit_id.work_unit_type != "head_office":
                raise ValidationError(
                    "Remittance-SWIFT targets are planned at Head Office / "
                    "corporate level only, not per branch or district."
                )

    def _get_duplicate_domain(self):
        self.ensure_one()
        domain = super()._get_duplicate_domain()
        return domain + [("fx_source_type", "=", self.fx_source_type)]

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
            key = p.fx_source_type
            if key not in grouped:
                grouped[key] = {
                    "opening_balance": 0.0,
                    **{f: 0.0 for f in MONTH_FIELDS}
                }
            grouped[key]["opening_balance"] += (p.opening_balance or 0.0)
            for f in MONTH_FIELDS:
                grouped[key][f] += (getattr(p, f) or 0.0)

        for fx_type, vals in grouped.items():
            dist_plan = self.search([
                ("cycle_id", "=", cycle_id.id),
                ("org_unit_id", "=", district.id),
                ("fx_source_type", "=", fx_type),
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
                    "fx_source_type": fx_type,
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
            key = p.fx_source_type
            if key not in grouped:
                grouped[key] = {
                    "opening_balance": 0.0,
                    **{f: 0.0 for f in MONTH_FIELDS}
                }
            grouped[key]["opening_balance"] += (p.opening_balance or 0.0)
            for f in MONTH_FIELDS:
                grouped[key][f] += (getattr(p, f) or 0.0)

        for fx_type, vals in grouped.items():
            ho_plan = self.search([
                ("cycle_id", "=", cycle_id.id),
                ("org_unit_id", "=", ho_unit.id),
                ("fx_source_type", "=", fx_type),
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
                    "fx_source_type": fx_type,
                    "state": "draft",
                    **vals_to_write,
                }
                self.create(vals_to_create)
