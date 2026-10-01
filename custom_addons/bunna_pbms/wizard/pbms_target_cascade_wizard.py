# -*- coding: utf-8 -*-
"""Top-down Target Cascading & Allocation Wizard for Bunna Bank PBMS.

Enables Retail Banking Operations / SPPMD to divide approved corporate targets
across District Offices (Tier 1), and District Offices to divide and cascade
their allocated quota to Child Branches (Tier 2).
"""

import logging
from markupsafe import Markup
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from ..models.pbms_plan_line_mixin import MONTH_FIELDS

_logger = logging.getLogger(__name__)


class PbmsTargetCascadeWizard(models.TransientModel):
    _name = "pbms.target.cascade.wizard"
    _description = "Target Cascading & Allocation Wizard"

    plan_id = fields.Many2one(
        "pbms.planning.category", string="Source Plan", required=True, readonly=True,
    )
    cycle_id = fields.Many2one(
        "pbms.planning.cycle", related="plan_id.cycle_id", readonly=True, string="Planning Cycle",
    )
    source_org_unit_id = fields.Many2one(
        "operating.unit", related="plan_id.org_unit_id", readonly=True, string="Source Work Unit",
    )
    cascade_level = fields.Selection(
        [
            ("ho_to_district", "Head Office to Districts (Tier 1)"),
            ("district_to_branch", "District to Child Branches (Tier 2)"),
        ],
        string="Cascade Level", required=True, default="ho_to_district",
    )

    category = fields.Selection(
        [
            ("deposit", "Deposit Mobilization"),
            ("customer_base", "Customer Base"),
            ("fx", "FX Mobilization"),
            ("digital_banking", "Digital Banking"),
            ("general_expense", "General Expense"),
        ],
        string="Planning Category", required=True, default="deposit",
    )

    cascade_scope = fields.Selection(
        [
            ("all_products", "All Products in Category (Proportional Breakdown)"),
            ("single_product", "Specific Single Product / Item"),
        ],
        string="Cascading Scope",
        default="all_products",
        required=True,
        help="Choose whether to cascade the entire category total across all products proportionally, or cascade a specific product."
    )

    # Product selectors per category
    deposit_type_id = fields.Many2one("pbms.deposit.type", string="Deposit Product")
    channel_id = fields.Many2one("pbms.digital.channel", string="Digital Channel")
    fx_source_type = fields.Many2one("pbms.fx.source.type", string="FX Source")
    expense_account_id = fields.Many2one("pbms.expense.account", string="Expense Account")
    base_type = fields.Selection(
        [
            ("new_acquisition", "New Customer Acquisition"),
            ("dormant_reduction", "Dormant Account Reduction"),
        ],
        string="Customer Base Type", default="new_acquisition",
    )

    distribution_method = fields.Selection(
        [
            ("proportional", "Proportional to Submitted Baseline"),
            ("equal", "Equal Division"),
            ("percentage", "Custom Percentage Share (%)"),
            ("amount", "Direct Target Amounts"),
        ],
        string="Distribution Method", default="proportional", required=True,
    )

    source_annual_target = fields.Float(
        string="Source Annual Target", compute="_compute_source_target", store=True, readonly=False,
    )
    total_target_amount = fields.Float(
        string="Total Target to Allocate", required=True,
    )
    currency_id = fields.Many2one(
        "res.currency", related="plan_id.currency_id", readonly=True,
    )

    line_ids = fields.One2many(
        "pbms.target.cascade.wizard.line", "wizard_id", string="Allocation Lines",
    )

    total_allocated_amount = fields.Float(
        string="Total Allocated", compute="_compute_allocation_totals",
    )
    total_allocated_percentage = fields.Float(
        string="Total Percentage (%)", compute="_compute_allocation_totals",
    )
    allocation_difference = fields.Float(
        string="Unallocated Difference", compute="_compute_allocation_totals",
    )

    @api.model
    def _get_source_category_total(
        self, plan, category, cascade_scope="all_products",
        deposit_type=False, channel=False, fx_source=False, exp_acc=False, base_type="new_acquisition"
    ):
        """Fetch the approved or planned annual total for the selected planning category."""
        if not plan:
            return 0.0

        lines = plan.line_ids.filtered(lambda l: l.line_type == category)
        if cascade_scope == "single_product":
            if category == "deposit" and deposit_type:
                lines = lines.filtered(lambda l: l.deposit_type_id == deposit_type)
            elif category == "customer_base":
                if deposit_type:
                    lines = lines.filtered(lambda l: l.deposit_type_id == deposit_type)
                if base_type:
                    lines = lines.filtered(lambda l: l.base_type == base_type)
            elif category == "fx" and fx_source:
                lines = lines.filtered(lambda l: l.fx_source_type == fx_source)
            elif category == "digital_banking" and channel:
                lines = lines.filtered(lambda l: l.channel_id == channel)
            elif category == "general_expense" and exp_acc:
                lines = lines.filtered(lambda l: l.expense_account_id == exp_acc)

            tot = sum(lines.mapped("approved_annual_total")) or sum(lines.mapped("annual_total")) or sum(lines.mapped("proposed_annual_total"))
            return float(tot or 0.0)

        # For all_products in category: Check approved category summary first, else annual total
        cat_summary_map = {
            "deposit": plan.deposit_approved_total or plan.deposit_annual_total,
            "customer_base": plan.customer_base_approved_total or plan.customer_base_annual_total,
            "fx": plan.fx_approved_total or plan.fx_annual_total,
            "digital_banking": plan.digital_banking_approved_total or plan.digital_banking_annual_total,
            "general_expense": plan.expense_approved_total or plan.expense_annual_total,
        }
        if category in cat_summary_map and cat_summary_map[category] > 0:
            return float(cat_summary_map[category])

        # Fallback to lines sum
        tot_appr = sum(lines.mapped("approved_annual_total"))
        if tot_appr > 0:
            return float(tot_appr)
        tot_ann = sum(lines.mapped("annual_total"))
        if tot_ann > 0:
            return float(tot_ann)
        tot_prop = sum(lines.mapped("proposed_annual_total"))
        if tot_prop > 0:
            return float(tot_prop)
        return 0.0

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        plan_id = res.get("plan_id") or self.env.context.get("default_plan_id")
        cascade_level = res.get("cascade_level") or self.env.context.get("default_cascade_level", "ho_to_district")
        cascade_scope = res.get("cascade_scope", "all_products")

        if plan_id:
            plan = self.env["pbms.planning.category"].browse(plan_id)
            if plan.is_targets_cascaded:
                raise UserError(_(
                    "Targets for '%s' have already been cascaded to subordinate units. "
                    "Re-cascading is prevented to eliminate duplicate target allocations."
                ) % plan.display_name)
            category = plan.category or res.get("category", "deposit")
            if plan.org_unit_type == "district_office" and not self.env.context.get("default_cascade_level"):
                cascade_level = "district_to_branch"
            res["plan_id"] = plan.id
            res["cascade_level"] = cascade_level
            res["category"] = category
            res["cascade_scope"] = cascade_scope

            lines = plan.line_ids.filtered(lambda l: l.line_type == category)
            deposit_type = lines.mapped("deposit_type_id")[:1]
            if deposit_type:
                res["deposit_type_id"] = deposit_type.id

            channel = lines.mapped("channel_id")[:1]
            if channel:
                res["channel_id"] = channel.id

            fx_source = lines.mapped("fx_source_type")[:1]
            if fx_source:
                res["fx_source_type"] = fx_source.id

            exp_acc = lines.mapped("expense_account_id")[:1]
            if exp_acc:
                res["expense_account_id"] = exp_acc.id

            tot = self._get_source_category_total(
                plan, category,
                cascade_scope=cascade_scope,
                deposit_type=deposit_type,
                channel=channel,
                fx_source=fx_source,
                exp_acc=exp_acc,
                base_type=res.get("base_type", "new_acquisition"),
            )

            res["source_annual_target"] = tot
            res["total_target_amount"] = tot

            lines_data = self._get_initial_recipient_lines(
                plan, cascade_level, category,
                cascade_scope=cascade_scope,
                deposit_type=deposit_type,
                channel=channel,
                fx_source=fx_source,
                exp_acc=exp_acc,
                total_target=tot,
                method=res.get("distribution_method", "proportional"),
                base_type=res.get("base_type", "new_acquisition"),
            )
            if lines_data:
                res["line_ids"] = lines_data

        return res

    @api.depends("plan_id", "category", "cascade_scope", "deposit_type_id", "channel_id", "fx_source_type", "expense_account_id", "base_type")
    def _compute_source_target(self):
        for wizard in self:
            if not wizard.plan_id:
                wizard.source_annual_target = 0.0
                continue

            total = wizard._get_source_category_total(
                wizard.plan_id, wizard.category,
                cascade_scope=wizard.cascade_scope,
                deposit_type=wizard.deposit_type_id,
                channel=wizard.channel_id,
                fx_source=wizard.fx_source_type,
                exp_acc=wizard.expense_account_id,
                base_type=wizard.base_type,
            )
            wizard.source_annual_target = total
            if not wizard.total_target_amount or wizard.total_target_amount == 0.0:
                wizard.total_target_amount = total

    @api.depends("line_ids.allocated_amount", "line_ids.allocation_percentage", "total_target_amount")
    def _compute_allocation_totals(self):
        for wizard in self:
            tot_amt = sum(wizard.line_ids.mapped("allocated_amount"))
            tot_pct = sum(wizard.line_ids.mapped("allocation_percentage"))
            wizard.total_allocated_amount = tot_amt
            wizard.total_allocated_percentage = round(tot_pct, 2)
            wizard.allocation_difference = round(wizard.total_target_amount - tot_amt, 2)

    @api.onchange("category", "cascade_scope", "deposit_type_id", "channel_id", "fx_source_type", "expense_account_id", "base_type", "distribution_method")
    def _onchange_distribution_parameters(self):
        if not self.plan_id:
            return

        lines = self.plan_id.line_ids.filtered(lambda l: l.line_type == self.category)
        if self.category == "deposit":
            if not self.deposit_type_id or self.deposit_type_id not in lines.mapped("deposit_type_id"):
                dep_type = lines.mapped("deposit_type_id")[:1]
                self.deposit_type_id = dep_type.id if dep_type else False
        elif self.category == "customer_base":
            if not self.deposit_type_id or self.deposit_type_id not in lines.mapped("deposit_type_id"):
                dep_type = lines.mapped("deposit_type_id")[:1]
                self.deposit_type_id = dep_type.id if dep_type else False
        elif self.category == "fx":
            if not self.fx_source_type or self.fx_source_type not in lines.mapped("fx_source_type"):
                fx_source = lines.mapped("fx_source_type")[:1]
                self.fx_source_type = fx_source.id if fx_source else False
        elif self.category == "digital_banking":
            if not self.channel_id or self.channel_id not in lines.mapped("channel_id"):
                ch = lines.mapped("channel_id")[:1]
                self.channel_id = ch.id if ch else False
        elif self.category == "general_expense":
            if not self.expense_account_id or self.expense_account_id not in lines.mapped("expense_account_id"):
                exp = lines.mapped("expense_account_id")[:1]
                self.expense_account_id = exp.id if exp else False

        tot = self._get_source_category_total(
            self.plan_id, self.category,
            cascade_scope=self.cascade_scope,
            deposit_type=self.deposit_type_id,
            channel=self.channel_id,
            fx_source=self.fx_source_type,
            exp_acc=self.expense_account_id,
            base_type=self.base_type,
        )
        self.source_annual_target = tot
        self.total_target_amount = tot
        self._populate_recipient_lines()

    @api.onchange("total_target_amount")
    def _onchange_total_target_amount(self):
        if self.total_target_amount and self.plan_id:
            self._populate_recipient_lines()

    @api.model
    def _get_initial_recipient_lines(
        self, plan, cascade_level, category, cascade_scope="all_products",
        deposit_type=False, channel=False, fx_source=False, exp_acc=False,
        total_target=0.0, method="proportional", base_type="new_acquisition"
    ):
        Plan = self.env["pbms.planning.category"]
        Line = self.env["pbms.plan.category.line"]

        if cascade_level == "ho_to_district":
            ho_unit = plan.org_unit_id if plan else False
            domain = [
                ("work_unit_type", "=", "district_office"),
                ("active", "=", True),
            ]
            if ho_unit:
                child_districts = self.env["operating.unit"].search(domain + [("parent_unit", "=", ho_unit.id)])
                recipient_units = child_districts if child_districts else self.env["operating.unit"].search(domain)
            else:
                recipient_units = self.env["operating.unit"].search(domain)
        else:
            district_unit = plan.org_unit_id
            recipient_units = self.env["operating.unit"].search([
                ("parent_unit", "=", district_unit.id),
                ("work_unit_type", "in", ("branch", "sub_branch", "service_center")),
                ("active", "=", True),
            ])
            if not recipient_units:
                recipient_units = self.env["operating.unit"].search([
                    ("work_unit_type", "in", ("branch", "sub_branch", "service_center")),
                    ("active", "=", True),
                ])

        if not recipient_units:
            return []

        baselines = {}
        for unit in recipient_units:
            if cascade_level == "ho_to_district":
                # Check for direct district overview plan first
                plans = Plan.search([
                    ("cycle_id", "=", plan.cycle_id.id),
                    ("org_unit_id", "=", unit.id),
                    ("active", "=", True),
                ])
                unit_lines = Line.search([
                    ("plan_id", "in", plans.ids),
                    ("line_type", "=", category),
                ])
                if not unit_lines:
                    # Fallback to branch lines under this district
                    unit_lines = Line.search([
                        ("cycle_id", "=", plan.cycle_id.id),
                        ("district_id", "=", unit.id),
                        ("org_unit_id", "!=", unit.id),
                        ("line_type", "=", category),
                    ])
            else:
                plans = Plan.search([
                    ("cycle_id", "=", plan.cycle_id.id),
                    ("org_unit_id", "=", unit.id),
                    ("active", "=", True),
                ])
                unit_lines = Line.search([
                    ("plan_id", "in", plans.ids),
                    ("line_type", "=", category),
                ])

            if cascade_scope == "single_product":
                if category == "deposit" and deposit_type:
                    unit_lines = unit_lines.filtered(lambda l: l.deposit_type_id == deposit_type)
                elif category == "customer_base":
                    if deposit_type:
                        unit_lines = unit_lines.filtered(lambda l: l.deposit_type_id == deposit_type)
                    if base_type:
                        unit_lines = unit_lines.filtered(lambda l: l.base_type == base_type)
                elif category == "fx" and fx_source:
                    unit_lines = unit_lines.filtered(lambda l: l.fx_source_type == fx_source)
                elif category == "digital_banking" and channel:
                    unit_lines = unit_lines.filtered(lambda l: l.channel_id == channel)
                elif category == "general_expense" and exp_acc:
                    unit_lines = unit_lines.filtered(lambda l: l.expense_account_id == exp_acc)

            total_val = 0.0
            if unit_lines:
                for l in unit_lines:
                    val = (
                        l.annual_total
                        or l.proposed_annual_total
                        or ((l.quarter1_total or 0.0) + (l.quarter2_total or 0.0) + (l.quarter3_total or 0.0) + (l.quarter4_total or 0.0))
                        or sum(getattr(l, m) or 0.0 for m in ("m01", "m02", "m03", "m04", "m05", "m06", "m07", "m08", "m09", "m10", "m11", "m12"))
                        or 0.0
                    )
                    total_val += val

            if total_val <= 0.0 and plans:
                cat_summary_field = f"{category}_annual_total"
                cat_prop_field = f"{category}_proposed_total"
                total_val = sum(getattr(p, cat_summary_field, 0.0) or getattr(p, cat_prop_field, 0.0) or 0.0 for p in plans)

            baselines[unit.id] = total_val

        total_baseline = sum(baselines.values())

        # Only cascade to units that have planned their plan (baseline > 0.0)
        planned_units = [u for u in recipient_units if baselines.get(u.id, 0.0) > 0.0]
        if planned_units:
            effective_units = planned_units
        else:
            # Fallback only if no units have planned targets at all (e.g. fresh top-down scenario)
            effective_units = recipient_units

        unit_count = len(effective_units)
        lines_data = []

        for unit in effective_units:
            base_amt = baselines.get(unit.id, 0.0)
            if method == "proportional" and total_baseline > 0:
                pct = (base_amt / total_baseline) * 100.0
                alloc_amt = (total_target * (pct / 100.0))
            elif method == "equal" and unit_count > 0:
                pct = 100.0 / unit_count
                alloc_amt = total_target / unit_count
            else:
                pct = (100.0 / unit_count) if unit_count > 0 else 0.0
                alloc_amt = (total_target * (pct / 100.0)) if total_target else 0.0

            lines_data.append((0, 0, {
                "org_unit_id": unit.id,
                "baseline_amount": base_amt,
                "allocation_percentage": round(pct, 2),
                "allocated_amount": round(alloc_amt, 2),
            }))

        return lines_data

    def _populate_recipient_lines(self):
        self.ensure_one()
        lines_data = self._get_initial_recipient_lines(
            self.plan_id, self.cascade_level, self.category,
            cascade_scope=self.cascade_scope,
            deposit_type=self.deposit_type_id,
            channel=self.channel_id,
            fx_source=self.fx_source_type,
            exp_acc=self.expense_account_id,
            total_target=self.total_target_amount,
            method=self.distribution_method,
            base_type=self.base_type,
        )
        self.line_ids = [(5, 0, 0)] + lines_data

    def action_recalculate_proportions(self):
        """Action button in wizard to re-calculate allocation according to selected method."""
        self._populate_recipient_lines()
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_apply_cascade(self):
        """Apply the cascaded targets to each recipient operating unit's plan."""
        self.ensure_one()
        if self.plan_id.is_targets_cascaded:
            raise UserError(_(
                "Targets for '%s' have already been cascaded to subordinate units. "
                "Re-cascading is prevented to eliminate duplicate target allocations."
            ) % self.plan_id.display_name)
        if not self.line_ids:
            raise UserError(_("No recipient work units found to cascade targets to."))

        user = self.env.user
        if self.cascade_level == "ho_to_district":
            if not (user._pbms_is_ho_reviewer() or user._pbms_is_sppmd_approver() or user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
                raise AccessError(_("Only Head Office Reviewers or SPPMD Administrators can cascade targets to Districts."))
        elif self.cascade_level == "district_to_branch":
            if not (user._pbms_is_district_reviewer() or user._pbms_is_ho_reviewer() or user._pbms_is_sppmd_approver() or user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
                raise AccessError(_("Only District Reviewers or Administrators can cascade targets to Branches."))

        if abs(self.total_allocated_percentage - 100.0) > 0.5 and self.distribution_method == "percentage":
            raise ValidationError(_(
                "Total allocated percentage must equal 100.0%% (Current total: %.2f%%)."
            ) % self.total_allocated_percentage)

        Plan = self.env["pbms.planning.category"].sudo().with_context(pbms_target_cascade=True)
        Line = self.env["pbms.plan.category.line"].sudo().with_context(pbms_target_cascade=True)

        source_lines = self.plan_id.line_ids.filtered(lambda l: l.line_type == self.category)
        if self.cascade_scope == "single_product":
            if self.category == "deposit" and self.deposit_type_id:
                source_lines = source_lines.filtered(lambda l: l.deposit_type_id == self.deposit_type_id)
            elif self.category == "customer_base":
                if self.deposit_type_id:
                    source_lines = source_lines.filtered(lambda l: l.deposit_type_id == self.deposit_type_id)
                if self.base_type:
                    source_lines = source_lines.filtered(lambda l: l.base_type == self.base_type)
            elif self.category == "fx" and self.fx_source_type:
                source_lines = source_lines.filtered(lambda l: l.fx_source_type == self.fx_source_type)
            elif self.category == "digital_banking" and self.channel_id:
                source_lines = source_lines.filtered(lambda l: l.channel_id == self.channel_id)
            elif self.category == "general_expense" and self.expense_account_id:
                source_lines = source_lines.filtered(lambda l: l.expense_account_id == self.expense_account_id)

        # Ensure distinct source lines per product/segment so each item is only processed once
        distinct_source_lines = []
        seen_keys = set()
        for s_line in source_lines:
            key = (
                s_line.line_type,
                s_line.deposit_type_id.id if s_line.deposit_type_id else False,
                s_line.channel_id.id if s_line.channel_id else False,
                s_line.fx_source_type.id if s_line.fx_source_type else False,
                s_line.expense_account_id.id if s_line.expense_account_id else False,
                s_line.base_type if self.category == "customer_base" else False,
            )
            if key not in seen_keys:
                seen_keys.add(key)
                distinct_source_lines.append(s_line)

        source_category_total = sum(s.approved_annual_total or s.annual_total for s in distinct_source_lines) or 1.0
        scaling_factor = (self.total_target_amount / source_category_total) if source_category_total > 0 else 1.0

        updated_plans = self.env["pbms.planning.category"]
        product_label = self._get_product_display_name()

        for wizard_line in self.line_ids:
            unit = wizard_line.org_unit_id
            unit_pct = wizard_line.allocation_percentage / 100.0

            # Find or create recipient plan for this category
            rec_plan = Plan.search([
                ("cycle_id", "=", self.cycle_id.id),
                ("org_unit_id", "=", unit.id),
                ("category", "=", self.category),
                ("active", "=", True),
            ], limit=1)
            if not rec_plan:
                rec_plan = Plan.create({
                    "cycle_id": self.cycle_id.id,
                    "org_unit_id": unit.id,
                    "category": self.category,
                    "state": "draft" if self.cascade_level == "district_to_branch" else "district_approved",
                    "active": True,
                })

            for s_line in distinct_source_lines:
                s_base_target = s_line.approved_annual_total or s_line.annual_total or 0.0
                prod_annual_target = s_base_target * scaling_factor
                monthly_curve = {}
                s_tot = s_base_target
                if s_tot > 0:
                    for m in MONTH_FIELDS:
                        s_m_val = getattr(s_line, f"approved_{m}", 0.0) or getattr(s_line, m, 0.0) or 0.0
                        monthly_curve[m] = s_m_val / s_tot
                else:
                    for m in MONTH_FIELDS:
                        monthly_curve[m] = 1.0 / 12.0

                if self.cascade_scope == "single_product":
                    prod_alloc_total = wizard_line.allocated_amount
                else:
                    prod_alloc_total = round(prod_annual_target * unit_pct, 2)

                m_vals = {}
                approved_m_vals = {}
                for m in MONTH_FIELDS:
                    val = round(prod_alloc_total * monthly_curve.get(m, 1.0 / 12.0), 2)
                    m_vals[m] = val
                    approved_m_vals[f"approved_{m}"] = val

                # Direct database search for existing line(s) on recipient plan matching this EXACT product
                line_domain = [
                    ("plan_id", "=", rec_plan.id),
                    ("line_type", "=", self.category),
                ]
                if self.category == "deposit":
                    if s_line.deposit_type_id:
                        line_domain.append(("deposit_type_id", "=", s_line.deposit_type_id.id))
                elif self.category == "customer_base":
                    if s_line.deposit_type_id:
                        line_domain.append(("deposit_type_id", "=", s_line.deposit_type_id.id))
                    if s_line.base_type:
                        line_domain.append(("base_type", "=", s_line.base_type))
                elif self.category == "fx":
                    if s_line.fx_source_type:
                        line_domain.append(("fx_source_type", "=", s_line.fx_source_type.id))
                elif self.category == "digital_banking":
                    if s_line.channel_id:
                        line_domain.append(("channel_id", "=", s_line.channel_id.id))
                elif self.category == "general_expense":
                    if s_line.expense_account_id:
                        line_domain.append(("expense_account_id", "=", s_line.expense_account_id.id))

                existing_lines = Line.search(line_domain, order="id asc")

                if existing_lines:
                    target_line = existing_lines[0]
                    # Snapshot proposed targets if not already snapshotted
                    if hasattr(target_line, "_snapshot_proposed_targets"):
                        target_line._snapshot_proposed_targets()

                    # Preserve the original proposed target as the baseline
                    orig_proposed = target_line.proposed_annual_total or target_line.annual_total or 0.0

                    # Update both active monthly targets and approved target fields on the existing row
                    update_vals = {
                        "is_cascaded": True,
                        "annual_total": prod_alloc_total,
                        "approved_annual_total": prod_alloc_total,
                        "proposed_annual_total": orig_proposed,
                        **m_vals,
                        **approved_m_vals,
                    }
                    if self.category == "deposit" and getattr(s_line, "opening_balance", False):
                        update_vals["approved_opening_balance"] = round((getattr(s_line, "approved_opening_balance", 0.0) or s_line.opening_balance or 0.0) * unit_pct, 2)

                    for m in MONTH_FIELDS:
                        if not getattr(target_line, f"proposed_{m}", False):
                            update_vals[f"proposed_{m}"] = getattr(target_line, m, 0.0) or 0.0

                    target_line.write(update_vals)

                    # Clean up any leftover duplicate rows for this exact same product
                    duplicate_lines = existing_lines[1:]
                    if duplicate_lines:
                        duplicate_lines.unlink()
                else:
                    # Create new row only if this product does not exist on recipient plan
                    line_payload = {
                        "plan_id": rec_plan.id,
                        "line_type": self.category,
                        "deposit_type_id": s_line.deposit_type_id.id if s_line.deposit_type_id else False,
                        "channel_id": s_line.channel_id.id if s_line.channel_id else False,
                        "fx_source_type": s_line.fx_source_type.id if s_line.fx_source_type else False,
                        "expense_account_id": s_line.expense_account_id.id if s_line.expense_account_id else False,
                        "base_type": s_line.base_type if self.category == "customer_base" else False,
                        "is_cascaded": True,
                        "proposed_annual_total": prod_alloc_total,
                        "annual_total": prod_alloc_total,
                        "approved_annual_total": prod_alloc_total,
                        **m_vals,
                        **approved_m_vals,
                    }
                    if self.category == "deposit" and getattr(s_line, "opening_balance", False):
                        line_payload["opening_balance"] = round((s_line.opening_balance or 0.0) * unit_pct, 2)
                        line_payload["approved_opening_balance"] = round((s_line.opening_balance or 0.0) * unit_pct, 2)

                    Line.create(line_payload)

            # Purge any residual duplicate rows on rec_plan for this category so each product appears exactly once
            all_cat_lines = Line.search([("plan_id", "=", rec_plan.id), ("line_type", "=", self.category)], order="id asc")
            seen_prod_keys = set()
            for cl in all_cat_lines:
                pkey = (
                    cl.deposit_type_id.id if cl.deposit_type_id else False,
                    cl.channel_id.id if cl.channel_id else False,
                    cl.fx_source_type.id if cl.fx_source_type else False,
                    cl.expense_account_id.id if cl.expense_account_id else False,
                    cl.base_type if self.category == "customer_base" else False,
                )
                if pkey in seen_prod_keys:
                    cl.unlink()
                else:
                    seen_prod_keys.add(pkey)

            rec_plan._compute_totals()
            rec_plan._compute_category_summaries()
            rec_plan._compute_has_cascaded_targets()
            updated_plans |= rec_plan

            # Find recipient users to notify via Systray (Discuss, Activities, and Popups)
            rec_users = self.env["res.users"]
            if self.cascade_level == "ho_to_district":
                dist_reviewers = self.plan_id._get_users_with_group("bunna_pbms.group_pbms_district_reviewer").filtered(
                    lambda u: u.active and (unit.id in u._pbms_operating_unit_ids() or not u.assigned_operating_unit_ids)
                )
                rec_users |= dist_reviewers
            else:
                branch_planners = self.plan_id._get_users_with_group("bunna_pbms.group_pbms_branch_user").filtered(
                    lambda u: u.active and (unit.id in u._pbms_operating_unit_ids() or not u.assigned_operating_unit_ids)
                )
                rec_users |= branch_planners

            if rec_plan.submitted_by:
                rec_users |= rec_plan.submitted_by
            if rec_plan.create_uid:
                rec_users |= rec_plan.create_uid
            if unit:
                mgr = self.plan_id._get_unit_manager_user(unit)
                if mgr:
                    rec_users |= mgr
                if hasattr(unit, "user_ids") and unit.user_ids:
                    rec_users |= unit.user_ids
                unit_assigned_users = self.env["res.users"].search([
                    ("active", "=", True),
                    "|",
                    ("assigned_operating_unit_ids", "in", [unit.id]),
                    ("default_operating_unit_id", "=", unit.id),
                ])
                rec_users |= unit_assigned_users

            rec_partners = rec_users.mapped("partner_id")

            currency_sym = rec_plan.currency_id.symbol or "ETB"
            formatted_amt = "{:,.2f}".format(wizard_line.allocated_amount)
            cat_name = dict(self._fields["category"].selection).get(self.category, self.category)
            source_name = self.source_org_unit_id.display_name if self.source_org_unit_id else _("Head Office")

            # Build branded Bunna Bank email template and chatter card (Image 1)
            base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
            action_url = f"{base_url}/web#id={rec_plan.id}&model=pbms.planning.category&view_type=form"
            card_table_html = f"""
                <table style="width: 100%; border-collapse: collapse; margin: 16px 0; background-color: #FAFAFA; border-radius: 6px;">
                    <tr style="border-bottom: 1px solid #EEEEEE;">
                        <td style="padding: 10px; font-weight: bold; width: 35%; color: #555555;">Work Unit:</td>
                        <td style="padding: 10px; font-weight: bold; color: #541718;">{unit.display_name}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #EEEEEE;">
                        <td style="padding: 10px; font-weight: bold; color: #555555;">Category:</td>
                        <td style="padding: 10px;">{cat_name}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #EEEEEE;">
                        <td style="padding: 10px; font-weight: bold; color: #555555;">Product / Metric:</td>
                        <td style="padding: 10px; font-weight: bold; color: #425727;">{product_label}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #EEEEEE;">
                        <td style="padding: 10px; font-weight: bold; color: #555555;">Allocated Target:</td>
                        <td style="padding: 10px; font-weight: bold; color: #198754; font-size: 15px;">{formatted_amt} {currency_sym}</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #EEEEEE;">
                        <td style="padding: 10px; font-weight: bold; color: #555555;">Allocation Share:</td>
                        <td style="padding: 10px; font-weight: bold; color: #C17540;">{wizard_line.allocation_percentage:.2f}%</td>
                    </tr>
                    <tr style="border-bottom: 1px solid #EEEEEE;">
                        <td style="padding: 10px; font-weight: bold; color: #555555;">Source Unit:</td>
                        <td style="padding: 10px;">{source_name}</td>
                    </tr>
                </table>
            """

            full_email_body = f"""
                <div style="margin: 0px; padding: 0px; font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 14px; color: #333333;">
                    <table border="0" cellpadding="0" cellspacing="0" style="padding-top: 16px; background-color: #F1F1F1; width: 100%;">
                        <tr><td align="center">
                            <table border="0" cellpadding="0" cellspacing="0" style="padding: 24px; background-color: #FFFFFF; width: 600px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">
                                <tr><td style="padding-bottom: 20px; border-bottom: 2.5px solid #541718;">
                                    <h2 style="color: #541718; margin: 0; font-weight: 700;">Bunna Bank - Plan &amp; Budget Management System</h2>
                                    <p style="color: #C17540; margin: 4px 0 0 0; font-size: 13px; font-weight: bold;">🎯 Official Business Target Cascaded Notification</p>
                                </td></tr>
                                <tr><td style="padding: 20px 0;">
                                    <p>Dear Colleague / Unit Manager,</p>
                                    <p>Official business targets have been allocated and cascaded to <b>{unit.display_name}</b> for the <b>{self.cycle_id.name}</b> planning cycle.</p>
                                    {card_table_html}
                                    <p style="margin-top: 16px;">The approved annual and monthly targets have been populated and updated in your planning matrix.</p>
                                    <div style="text-align: center; margin: 30px 0;">
                                        <a href="{action_url}" style="background-color: #541718; color: #FFFFFF; padding: 12px 24px; text-decoration: none; border-radius: 4px; font-weight: bold; display: inline-block;">
                                            View Planning Matrix
                                        </a>
                                    </div>
                                </td></tr>
                                <tr><td style="border-top: 1px solid #EEEEEE; padding-top: 15px; font-size: 12px; color: #888888; text-align: center;">
                                    Bunna Bank S.C. | Strategic Planning &amp; Performance Management Directorate (SPPMD)<br/>
                                    This is an automated system notification from Bunna PBMS.
                                </td></tr>
                            </table>
                        </td></tr>
                    </table>
                </div>
            """

            subject = _("🎯 Official Target Cascaded: %s - %s (%s)") % (
                cat_name, unit.display_name, self.cycle_id.name
            )

            # Post Bunna Bank branded template card to chatter (Image 1, single note)
            rec_plan.message_post(
                subject=subject,
                body=Markup(full_email_body),
                message_type="notification",
                subtype_xmlid="mail.mt_note",
            )

            # Send single branded email directly to recipient partners
            if rec_partners:
                try:
                    mail_vals = {
                        "subject": subject,
                        "body_html": full_email_body,
                        "recipient_ids": [(6, 0, rec_partners.ids)],
                        "auto_delete": False,
                    }
                    self.env["mail.mail"].sudo().create(mail_vals).send()
                except Exception as e:
                    _logger.warning("Failed sending cascaded target email for %s: %s", unit.display_name, e)

            # Schedule Activity in the Clock Systray icon for recipient work unit users
            if rec_users and hasattr(rec_plan, "_schedule_pbms_activity"):
                cascade_action_label = _("Review & Cascade Target to Branches") if self.cascade_level == "ho_to_district" else _("Review Cascaded Annual Target")
                rec_plan._schedule_pbms_activity(
                    users=rec_users,
                    summary=_("%s: %s (%s)") % (cascade_action_label, product_label, unit.display_name),
                    note=_("Official target of %s %s (%.2f%% share) has been allocated to %s by %s. Please review and cascade as applicable.") % (
                        formatted_amt,
                        currency_sym,
                        wizard_line.allocation_percentage,
                        unit.display_name,
                        source_name,
                    ),
                )

            # Real-time popup notifications via bus.bus
            if hasattr(self.env["bus.bus"], "_sendone"):
                for partner in rec_partners:
                    try:
                        self.env["bus.bus"]._sendone(partner, "simple_notification", {
                            "type": "info",
                            "title": _("🎯 Target Cascaded: %s") % product_label,
                            "message": _("%s has been allocated %s %s (%.2f%%) for %s.") % (
                                unit.display_name,
                                formatted_amt,
                                currency_sym,
                                wizard_line.allocation_percentage,
                                cat_name,
                            ),
                            "sticky": False,
                        })
                    except Exception:
                        pass

        # Mark source plan as cascaded to prevent double cascading and update UI button
        self.plan_id.write({"is_targets_cascaded": True})

        cascade_level_label = _("Districts") if self.cascade_level == "ho_to_district" else _("Branches")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Target Cascade Complete"),
                "message": _("Successfully cascaded %s target (%s) across %d %s.") % (
                    product_label,
                    "{:,.2f}".format(self.total_target_amount),
                    len(self.line_ids),
                    cascade_level_label,
                ),
                "type": "success",
                "sticky": False,
            },
        }

    def _get_product_display_name(self):
        if self.cascade_scope == "all_products":
            return _("All %s Products") % dict(self._fields["category"].selection).get(self.category, self.category)
        if self.category == "deposit" and self.deposit_type_id:
            return self.deposit_type_id.name
        elif self.category == "customer_base":
            p_name = self.deposit_type_id.name if self.deposit_type_id else _("Customer Accounts")
            b_label = _("New Acquisition") if self.base_type == "new_acquisition" else _("Dormant Reduction")
            return f"{p_name} ({b_label})"
        elif self.category == "fx" and self.fx_source_type:
            return self.fx_source_type.name
        elif self.category == "digital_banking" and self.channel_id:
            return self.channel_id.name
        elif self.category == "general_expense" and self.expense_account_id:
            return self.expense_account_id.name
        return dict(self._fields["category"].selection).get(self.category, self.category)


class PbmsTargetCascadeWizardLine(models.TransientModel):
    _name = "pbms.target.cascade.wizard.line"
    _description = "Target Cascade Allocation Line"
    _order = "org_unit_id"

    wizard_id = fields.Many2one(
        "pbms.target.cascade.wizard", required=True, ondelete="cascade",
    )
    org_unit_id = fields.Many2one(
        "operating.unit", string="Recipient Work Unit", required=True,
    )
    baseline_amount = fields.Float(
        string="Submitted Baseline",
    )
    allocation_percentage = fields.Float(
        string="Share (%)", digits=(16, 2),
    )
    allocated_amount = fields.Float(
        string="Allocated Target", digits=(16, 2),
    )

    @api.onchange("allocation_percentage")
    def _onchange_allocation_percentage(self):
        if self.wizard_id and self.wizard_id.total_target_amount:
            self.allocated_amount = round(self.wizard_id.total_target_amount * (self.allocation_percentage / 100.0), 2)

    @api.onchange("allocated_amount")
    def _onchange_allocated_amount(self):
        if self.wizard_id and self.wizard_id.total_target_amount and self.wizard_id.total_target_amount > 0:
            self.allocation_percentage = round((self.allocated_amount / self.wizard_id.total_target_amount) * 100.0, 2)
