# -*- coding: utf-8 -*-
from odoo import api, fields, models
from .pbms_plan_line_mixin import MONTH_FIELDS


class PbmsExpenseAccount(models.Model):
    """Standard chart-of-account list for general expense items. Keeping
    this as master data (instead of free-text) directly addresses the
    BRD limitation: 'Use of unstandardized accounts which is not
    available in the standard chart of account'."""
    _name = "pbms.expense.account"
    _description = "General Expense Account"
    _order = "sequence, name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("code_uniq", "unique(code)", "Expense account code must be unique."),
    ]


class PbmsGeneralExpensePlan(models.Model):
    """General Expense Budget (BB-APF4) - annual budget distributed
    across months, for both branches/districts and Head Office units."""
    _name = "pbms.general.expense.plan"
    _description = "General Expense Budget (BB-APF4)"
    _inherit = ["pbms.plan.line.mixin", "mail.thread", "mail.activity.mixin"]
    _rec_name = "display_name"

    expense_account_id = fields.Many2one(
        "pbms.expense.account", required=True, index=True, tracking=True,
    )
    prior_year_actual = fields.Monetary(
        string="End Period Actual Performance",
        help="Prior period actual expense, shown for reviewers to "
             "sanity-check the requested budget against.",
    )
    is_office_rent = fields.Boolean(
        help="Flags office-rent lines so the district-level contractual "
             "agreement attachment can be required (BRD 6.4).",
    )

    display_name = fields.Char(compute="_compute_display_name", store=True)

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = " / ".join(filter(None, [
                rec.org_unit_id.display_name, rec.expense_account_id.name, rec.cycle_id.name,
            ]))

    def _get_duplicate_domain(self):
        self.ensure_one()
        domain = super()._get_duplicate_domain()
        return domain + [("expense_account_id", "=", self.expense_account_id.id)]

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
            key = p.expense_account_id.id
            if key not in grouped:
                grouped[key] = {
                    "prior_year_actual": 0.0,
                    **{f: 0.0 for f in MONTH_FIELDS}
                }
            grouped[key]["prior_year_actual"] += (p.prior_year_actual or 0.0)
            for f in MONTH_FIELDS:
                grouped[key][f] += (getattr(p, f) or 0.0)

        for exp_acc_id, vals in grouped.items():
            dist_plan = self.search([
                ("cycle_id", "=", cycle_id.id),
                ("org_unit_id", "=", district.id),
                ("expense_account_id", "=", exp_acc_id),
            ], limit=1)
            vals_to_write = {
                "prior_year_actual": vals["prior_year_actual"],
                **{f: vals[f] for f in MONTH_FIELDS}
            }
            if dist_plan:
                dist_plan.write(vals_to_write)
            else:
                vals_to_create = {
                    "cycle_id": cycle_id.id,
                    "org_unit_id": district.id,
                    "expense_account_id": exp_acc_id,
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
            key = p.expense_account_id.id
            if key not in grouped:
                grouped[key] = {
                    "prior_year_actual": 0.0,
                    **{f: 0.0 for f in MONTH_FIELDS}
                }
            grouped[key]["prior_year_actual"] += (p.prior_year_actual or 0.0)
            for f in MONTH_FIELDS:
                grouped[key][f] += (getattr(p, f) or 0.0)

        for exp_acc_id, vals in grouped.items():
            ho_plan = self.search([
                ("cycle_id", "=", cycle_id.id),
                ("org_unit_id", "=", ho_unit.id),
                ("expense_account_id", "=", exp_acc_id),
            ], limit=1)
            vals_to_write = {
                "prior_year_actual": vals["prior_year_actual"],
                **{f: vals[f] for f in MONTH_FIELDS}
            }
            if ho_plan:
                ho_plan.write(vals_to_write)
            else:
                vals_to_create = {
                    "cycle_id": cycle_id.id,
                    "org_unit_id": ho_unit.id,
                    "expense_account_id": exp_acc_id,
                    "state": "draft",
                    **vals_to_write,
                }
                self.create(vals_to_create)
