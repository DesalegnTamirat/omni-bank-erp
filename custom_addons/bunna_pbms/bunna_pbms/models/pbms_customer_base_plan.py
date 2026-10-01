# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PbmsCustomerBasePlan(models.Model):
    """Customer Base Plan: new customer/account acquisition and dormant
    account reduction targets, expressed as monthly counts with running
    cumulative totals (BRD 8.1 Customer Base Plan)."""
    _name = "pbms.customer.base.plan"
    _description = "Customer Base Plan"
    _inherit = ["pbms.cumulative.plan.mixin", "mail.thread", "mail.activity.mixin"]
    _rec_name = "display_name"

    deposit_type_id = fields.Many2one(
        "pbms.deposit.type", required=True, index=True, tracking=True,
        help="Account/product type this customer-base target applies to.",
    )
    base_type = fields.Selection(
        [
            ("new_acquisition", "New Customer Acquisition"),
            ("dormant_reduction", "Dormant Account Reduction"),
        ],
        required=True, default="new_acquisition", index=True,
    )

    display_name = fields.Char(compute="_compute_display_name", store=True)

    @api.depends("org_unit_id", "deposit_type_id", "base_type", "cycle_id")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = " / ".join(filter(None, [
                rec.org_unit_id.display_name,
                rec.deposit_type_id.name,
                dict(rec._fields["base_type"].selection).get(rec.base_type),
                rec.cycle_id.name,
            ]))

    def _get_duplicate_domain(self):
        self.ensure_one()
        domain = super()._get_duplicate_domain()
        return domain + [
            ("deposit_type_id", "=", self.deposit_type_id.id),
            ("base_type", "=", self.base_type),
        ]

    def _allow_negative_targets(self):
        # A planned reduction is naturally expressed as a negative
        # monthly figure (e.g. -50 dormant accounts in a month).
        return self.base_type == "dormant_reduction"

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
            key = (p.deposit_type_id.id, p.base_type)
            if key not in grouped:
                grouped[key] = {
                    "opening_balance": 0.0,
                    **{f: 0.0 for f in MONTH_FIELDS}
                }
            grouped[key]["opening_balance"] += (p.opening_balance or 0.0)
            for f in MONTH_FIELDS:
                grouped[key][f] += (getattr(p, f) or 0.0)

        for (dep_type_id, base_type), vals in grouped.items():
            dist_plan = self.search([
                ("cycle_id", "=", cycle_id.id),
                ("org_unit_id", "=", district.id),
                ("deposit_type_id", "=", dep_type_id),
                ("base_type", "=", base_type),
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
                    "deposit_type_id": dep_type_id,
                    "base_type": base_type,
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
            key = (p.deposit_type_id.id, p.base_type)
            if key not in grouped:
                grouped[key] = {
                    "opening_balance": 0.0,
                    **{f: 0.0 for f in MONTH_FIELDS}
                }
            grouped[key]["opening_balance"] += (p.opening_balance or 0.0)
            for f in MONTH_FIELDS:
                grouped[key][f] += (getattr(p, f) or 0.0)

        for (dep_type_id, base_type), vals in grouped.items():
            ho_plan = self.search([
                ("cycle_id", "=", cycle_id.id),
                ("org_unit_id", "=", ho_unit.id),
                ("deposit_type_id", "=", dep_type_id),
                ("base_type", "=", base_type),
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
                    "deposit_type_id": dep_type_id,
                    "base_type": base_type,
                    "state": "draft",
                    **vals_to_write,
                }
                self.create(vals_to_create)
