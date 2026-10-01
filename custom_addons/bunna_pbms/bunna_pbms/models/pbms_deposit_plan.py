# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .pbms_plan_line_mixin import MONTH_FIELDS


class PbmsDepositType(models.Model):
    """Configurable deposit product list (Savings, Demand, Time, IFB, ...)
    so new products can be added by SPPMD without a code change."""
    _name = "pbms.deposit.type"
    _description = "Deposit Product Type"
    _order = "sequence, name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    is_ifb = fields.Boolean(string="Interest-Free Banking", default=False)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("code_uniq", "unique(code)", "Deposit type code must be unique."),
    ]


class PbmsDepositPlan(models.Model):
    """Net Monthly Deposit (Amount & Customer Base) Plan - format BB-APF1.

    This is the reference implementation of the planning-line pattern:
    every other monthly-grid format (Customer Base, FX, Digital Banking,
    General Expense) follows the same shape - inherit the mixin, add the
    2-3 identifying fields, done.
    """
    _name = "pbms.deposit.plan"
    _description = "Deposit Mobilization Plan (BB-APF1)"
    _inherit = ["pbms.cumulative.plan.mixin", "mail.thread", "mail.activity.mixin"]
    _rec_name = "display_name"

    deposit_type_id = fields.Many2one(
        "pbms.deposit.type", required=True, index=True, tracking=True,
    )
    plan_category = fields.Selection(
        [("amount", "Amount"), ("account", "Account / Customer Base")],
        required=True, default="amount", index=True,
        help="Whether this line plans the deposit amount or the number "
             "of accounts/customers for the deposit type.",
    )

    display_name = fields.Char(compute="_compute_display_name", store=True)

    @api.depends("org_unit_id", "deposit_type_id", "plan_category", "cycle_id")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = " / ".join(filter(None, [
                rec.org_unit_id.display_name,
                rec.deposit_type_id.name,
                dict(rec._fields["plan_category"].selection).get(rec.plan_category),
                rec.cycle_id.name,
            ]))

    def _get_duplicate_domain(self):
        self.ensure_one()
        domain = super()._get_duplicate_domain()
        return domain + [
            ("deposit_type_id", "=", self.deposit_type_id.id),
            ("plan_category", "=", self.plan_category),
        ]

    @api.constrains("plan_category", "m01", "m02", "m03", "m04", "m05", "m06",
                     "m07", "m08", "m09", "m10", "m11", "m12")
    def _check_account_category_is_whole_number(self):
        for rec in self:
            if rec.plan_category == "account":
                for fname in MONTH_FIELDS:
                    val = getattr(rec, fname) or 0.0
                    if val != int(val):
                        raise ValidationError(_(
                            "Account/customer-base targets must be whole numbers "
                            "(got %(val)s for %(month)s).",
                            val=val, month=fname))

    @api.model
    def _consolidate_district_plan_data(self, cycle_id, district):
        branch_plans = self.search([
            ("cycle_id", "=", cycle_id.id),
            ("district_id", "=", district.id),
            ("state", "=", "district_approved"),
            ("org_unit_id", "!=", district.id),
        ])
        grouped = {}
        for p in branch_plans:
            key = (p.deposit_type_id.id, p.plan_category)
            if key not in grouped:
                grouped[key] = {
                    "opening_balance": 0.0,
                    **{f: 0.0 for f in MONTH_FIELDS}
                }
            grouped[key]["opening_balance"] += (p.opening_balance or 0.0)
            for f in MONTH_FIELDS:
                grouped[key][f] += (getattr(p, f) or 0.0)

        for (dep_type_id, category), vals in grouped.items():
            dist_plan = self.search([
                ("cycle_id", "=", cycle_id.id),
                ("org_unit_id", "=", district.id),
                ("deposit_type_id", "=", dep_type_id),
                ("plan_category", "=", category),
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
                    "plan_category": category,
                    "state": "draft",
                    **vals_to_write,
                }
                self.create(vals_to_create)

    @api.model
    def _consolidate_ho_plan_data(self, cycle_id, ho_unit):
        dist_plans = self.search([
            ("cycle_id", "=", cycle_id.id),
            ("org_unit_type", "=", "district_office"),
            ("state", "in", ("submitted", "ho_reviewed", "approved")),
        ])
        grouped = {}
        for p in dist_plans:
            key = (p.deposit_type_id.id, p.plan_category)
            if key not in grouped:
                grouped[key] = {
                    "opening_balance": 0.0,
                    **{f: 0.0 for f in MONTH_FIELDS}
                }
            grouped[key]["opening_balance"] += (p.opening_balance or 0.0)
            for f in MONTH_FIELDS:
                grouped[key][f] += (getattr(p, f) or 0.0)

        for (dep_type_id, category), vals in grouped.items():
            ho_plan = self.search([
                ("cycle_id", "=", cycle_id.id),
                ("org_unit_id", "=", ho_unit.id),
                ("deposit_type_id", "=", dep_type_id),
                ("plan_category", "=", category),
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
                    "plan_category": category,
                    "state": "draft",
                    **vals_to_write,
                }
                self.create(vals_to_create)
