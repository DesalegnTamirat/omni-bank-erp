# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PbmsFixedAssetCategory(models.Model):
    """Standardized fixed-asset categories with a reference unit price,
    directly addressing the BRD action item: 'standardize fixed asset
    accounts and determine unit price of fixed assets' (Facility Mgmt D.)."""
    _name = "pbms.fixed.asset.category"
    _description = "Fixed Asset Category"
    _order = "sequence, name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    reference_unit_price = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id,
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("code_uniq", "unique(code)", "Fixed asset category code must be unique."),
    ]


class PbmsFixedAssetPlan(models.Model):
    """Property & Equipment Plan (BB-APF7)."""
    _name = "pbms.fixed.asset.plan"
    _description = "Fixed Asset Requirement Plan (BB-APF7)"
    _inherit = ["pbms.workflow.mixin", "mail.thread", "mail.activity.mixin"]
    _rec_name = "display_name"

    line_ids = fields.One2many("pbms.fixed.asset.plan.line", "plan_id", string="Requested Items")
    total_estimated_amount = fields.Monetary(
        compute="_compute_total_estimated_amount", store=True, index=True,
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id,
    )
    display_name = fields.Char(compute="_compute_display_name", store=True)

    @api.depends("line_ids.estimated_total_price")
    def _compute_total_estimated_amount(self):
        for rec in self:
            rec.total_estimated_amount = sum(rec.line_ids.mapped("estimated_total_price"))

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.org_unit_id.display_name} - Fixed Assets - {rec.cycle_id.name}"

    def _protected_write_fields(self):
        return ["line_ids"]

    @api.constrains("line_ids", "state")
    def _check_has_lines(self):
        for rec in self:
            if rec.state != "draft" and not rec.line_ids:
                raise UserError(_("Cannot submit a fixed asset plan with no requested items."))

    @api.model
    def _consolidate_district_plan_data(self, cycle_id, district):
        branch_plans = self.search([
            ("cycle_id", "=", cycle_id.id),
            ("district_id", "=", district.id),
            ("state", "=", "district_approved"),
            ("org_unit_id", "!=", district.id),
        ])
        dist_plan = self.search([
            ("cycle_id", "=", cycle_id.id),
            ("org_unit_id", "=", district.id),
        ], limit=1)
        if not dist_plan:
            dist_plan = self.create({
                "cycle_id": cycle_id.id,
                "org_unit_id": district.id,
                "state": "draft",
            })
        
        # Clear existing consolidated lines on District plan if in draft
        if dist_plan.state == "draft":
            dist_plan.line_ids.unlink()
            lines_to_create = []
            for bp in branch_plans:
                for line in bp.line_ids:
                    lines_to_create.append((0, 0, {
                        "nature": line.nature,
                        "category_id": line.category_id.id,
                        "item_description": f"[{bp.org_unit_id.display_name}] {line.item_description}",
                        "purpose": line.purpose,
                        "quantity": line.quantity,
                        "estimated_unit_price": line.estimated_unit_price,
                    }))
            if lines_to_create:
                dist_plan.write({"line_ids": lines_to_create})

    @api.model
    def _consolidate_ho_plan_data(self, cycle_id, ho_unit):
        dist_plans = self.search([
            ("cycle_id", "=", cycle_id.id),
            ("org_unit_type", "=", "district_office"),
            ("state", "in", ("submitted", "ho_reviewed", "approved")),
        ])
        ho_plan = self.search([
            ("cycle_id", "=", cycle_id.id),
            ("org_unit_id", "=", ho_unit.id),
        ], limit=1)
        if not ho_plan:
            ho_plan = self.create({
                "cycle_id": cycle_id.id,
                "org_unit_id": ho_unit.id,
                "state": "draft",
            })

        if ho_plan.state == "draft":
            ho_plan.line_ids.unlink()
            lines_to_create = []
            for dp in dist_plans:
                for line in dp.line_ids:
                    lines_to_create.append((0, 0, {
                        "nature": line.nature,
                        "category_id": line.category_id.id,
                        "item_description": f"[{dp.org_unit_id.display_name}] {line.item_description}",
                        "purpose": line.purpose,
                        "quantity": line.quantity,
                        "estimated_unit_price": line.estimated_unit_price,
                    }))
            if lines_to_create:
                ho_plan.write({"line_ids": lines_to_create})


class PbmsFixedAssetPlanLine(models.Model):
    _name = "pbms.fixed.asset.plan.line"
    _description = "Fixed Asset Requirement Line"
    _order = "id"

    plan_id = fields.Many2one(
        "pbms.fixed.asset.plan", required=True, ondelete="cascade", index=True,
    )
    nature = fields.Selection(
        [("new", "New"), ("replacement", "Replacement")], required=True, default="new",
    )
    category_id = fields.Many2one("pbms.fixed.asset.category", required=True, index=True)
    item_description = fields.Char(required=True)
    purpose = fields.Char(string="User's Position / Purpose of the Item")
    quantity = fields.Integer(required=True, default=1)
    estimated_unit_price = fields.Monetary(currency_field="currency_id")
    estimated_total_price = fields.Monetary(
        compute="_compute_estimated_total_price", store=True, currency_field="currency_id",
    )
    currency_id = fields.Many2one(related="plan_id.currency_id", store=True)

    _sql_constraints = [
        ("quantity_positive", "check(quantity > 0)", "Quantity must be greater than zero."),
        ("unit_price_non_negative", "check(estimated_unit_price >= 0)",
         "Unit price cannot be negative."),
    ]

    @api.depends("quantity", "estimated_unit_price")
    def _compute_estimated_total_price(self):
        for line in self:
            line.estimated_total_price = (line.quantity or 0) * (line.estimated_unit_price or 0.0)

    @api.onchange("category_id")
    def _onchange_category_id(self):
        if self.category_id and not self.estimated_unit_price:
            self.estimated_unit_price = self.category_id.reference_unit_price
