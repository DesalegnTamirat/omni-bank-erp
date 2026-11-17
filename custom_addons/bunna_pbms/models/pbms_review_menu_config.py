# -*- coding: utf-8 -*-
"""
pbms_review_menu_config.py
==========================
Review & Consolidation Menu Access Configuration.

Allows PBMS administrators to control which PBMS privileges are required
to see each item in the "Review & Consolidation" top-level menu.

When a menu item has NO configured privileges, it falls back to the default
role groups (backward compatible).
When privileges ARE configured, the user must hold at least ONE of those
privileges (via pbms.privilege.assignment or pbms.role.definition) to see
the menu item.
"""
import logging
from odoo import api, fields, models, tools
from .pbms_access import _safe_table_exists

_logger = logging.getLogger(__name__)


REVIEW_MENU_ITEMS = [
    ("deposit",               "Deposit Mobilization"),
    ("customer_base",         "Customer Base"),
    ("workforce",             "Human Resources (Workforce)"),
    ("exceptional_workforce", "Exceptional Workforce Requests"),
    ("fx",                    "FX Mobilization"),
    ("digital",               "Digital Banking"),
    ("loan_disbursement",     "Credit & Loans (Disbursement & Collection)"),
    ("loan_outstanding",      "Credit & Loans (Outstanding Balance)"),
    ("expense",               "Finance & Accounts (General Expense)"),
    ("fixed_asset",           "Procurement & Property (Fixed Assets)"),
    ("income_plan",           "Income Plan"),
    ("initiative_budget",     "Initiative Budget"),
    ("consolidation",         "Bank-Wide Consolidation"),
]

MENU_KEY_TO_XMLID = {
    "deposit":               "bunna_pbms.menu_pbms_review_retail",
    "customer_base":         "bunna_pbms.menu_pbms_review_retail_customer",
    "workforce":             "bunna_pbms.menu_pbms_review_workforce",
    "exceptional_workforce": "bunna_pbms.menu_pbms_review_exceptional_workforce",
    "fx":                    "bunna_pbms.menu_pbms_review_fx",
    "digital":               "bunna_pbms.menu_pbms_review_digital",
    "loan_disbursement":     "bunna_pbms.menu_pbms_review_loan_disbursement",
    "loan_outstanding":      "bunna_pbms.menu_pbms_review_loan_outstanding",
    "expense":               "bunna_pbms.menu_pbms_review_expense",
    "fixed_asset":           "bunna_pbms.menu_pbms_review_fixed_asset",
    "income_plan":           "bunna_pbms.menu_pbms_review_credit_portfolio",
    "initiative_budget":     "bunna_pbms.menu_pbms_review_initiative_budget",
    "consolidation":         "bunna_pbms.menu_pbms_consolidation",
}

DEFAULT_MENU_GROUPS = {
    "deposit": [
        "bunna_pbms.group_pbms_district_reviewer",
        "bunna_pbms.group_pbms_ho_reviewer",
        "bunna_pbms.group_pbms_approver",
        "bunna_pbms.group_pbms_manager",
        "bunna_pbms.group_pbms_respective_chief",
    ],
    "customer_base": [
        "bunna_pbms.group_pbms_district_reviewer",
        "bunna_pbms.group_pbms_ho_reviewer",
        "bunna_pbms.group_pbms_approver",
        "bunna_pbms.group_pbms_manager",
        "bunna_pbms.group_pbms_respective_chief",
    ],
    "workforce": [
        "bunna_pbms.group_pbms_district_reviewer",
        "bunna_pbms.group_pbms_ho_reviewer",
        "bunna_pbms.group_pbms_approver",
        "bunna_pbms.group_pbms_manager",
        "bunna_pbms.group_pbms_budget_hiring_committee",
        "bunna_pbms.group_pbms_ceo",
        "bunna_pbms.group_pbms_respective_chief",
        "bunna_pbms.group_pbms_people_solutions",
        "bunna_pbms.group_pbms_cpco",
        "bunna_pbms.group_pbms_people_operations",
    ],
    "exceptional_workforce": [
        "bunna_pbms.group_pbms_district_reviewer",
        "bunna_pbms.group_pbms_approver",
        "bunna_pbms.group_pbms_manager",
        "bunna_pbms.group_pbms_respective_chief",
        "bunna_pbms.group_pbms_people_solutions",
        "bunna_pbms.group_pbms_cpco",
        "bunna_pbms.group_pbms_budget_hiring_committee",
        "bunna_pbms.group_pbms_ceo",
        "bunna_pbms.group_pbms_people_operations",
    ],
    "fx": [
        "bunna_pbms.group_pbms_district_reviewer",
        "bunna_pbms.group_pbms_ho_reviewer",
        "bunna_pbms.group_pbms_approver",
        "bunna_pbms.group_pbms_manager",
        "bunna_pbms.group_pbms_respective_chief",
    ],
    "digital": [
        "bunna_pbms.group_pbms_district_reviewer",
        "bunna_pbms.group_pbms_ho_reviewer",
        "bunna_pbms.group_pbms_approver",
        "bunna_pbms.group_pbms_manager",
        "bunna_pbms.group_pbms_respective_chief",
    ],
    "loan_disbursement": [
        "bunna_pbms.group_pbms_respective_chief",
        "bunna_pbms.group_pbms_ho_reviewer",
        "bunna_pbms.group_pbms_approver",
        "bunna_pbms.group_pbms_manager",
    ],
    "loan_outstanding": [
        "bunna_pbms.group_pbms_respective_chief",
        "bunna_pbms.group_pbms_ho_reviewer",
        "bunna_pbms.group_pbms_approver",
        "bunna_pbms.group_pbms_manager",
    ],
    "expense": [
        "bunna_pbms.group_pbms_district_reviewer",
        "bunna_pbms.group_pbms_ho_reviewer",
        "bunna_pbms.group_pbms_approver",
        "bunna_pbms.group_pbms_manager",
        "bunna_pbms.group_pbms_respective_chief",
    ],
    "fixed_asset": [
        "bunna_pbms.group_pbms_district_reviewer",
        "bunna_pbms.group_pbms_ho_reviewer",
        "bunna_pbms.group_pbms_approver",
        "bunna_pbms.group_pbms_manager",
        "bunna_pbms.group_pbms_budget_hiring_committee",
        "bunna_pbms.group_pbms_respective_chief",
    ],
    "income_plan": [
        "bunna_pbms.group_pbms_respective_chief",
        "bunna_pbms.group_pbms_ho_reviewer",
        "bunna_pbms.group_pbms_approver",
        "bunna_pbms.group_pbms_manager",
    ],
    "initiative_budget": [
        "bunna_pbms.group_pbms_respective_chief",
        "bunna_pbms.group_pbms_budget_hiring_committee",
        "bunna_pbms.group_pbms_ho_reviewer",
        "bunna_pbms.group_pbms_approver",
        "bunna_pbms.group_pbms_manager",
    ],
    "consolidation": [
        "bunna_pbms.group_pbms_approver",
        "bunna_pbms.group_pbms_manager",
    ],
}


class PbmsReviewMenuConfig(models.Model):
    """
    One record per Review & Consolidation sub-menu item.
    Defines which PBMS privileges grant visibility of that menu.

    - If privilege_ids is EMPTY  → fallback to DEFAULT_MENU_GROUPS.
    - If privilege_ids is SET    → user must have at least one listed privilege.
    - If 'active' is False       → the menu is hidden for everyone.
    """
    _name = "pbms.review.menu.config"
    _description = "Review & Consolidation Menu Access Configuration"
    _order = "sequence, id"
    _rec_name = "menu_key"

    sequence = fields.Integer(string="Sequence", default=10)
    menu_key = fields.Selection(
        REVIEW_MENU_ITEMS,
        string="Menu Item",
        required=True,
        index=True,
        help="Select the Review & Consolidation sub-menu this rule applies to.",
    )
    menu_label = fields.Char(
        string="Menu Label",
        compute="_compute_menu_label",
        store=True,
    )
    privilege_ids = fields.Many2many(
        "pbms.privilege",
        "pbms_review_menu_privilege_rel",
        "menu_config_id",
        "privilege_id",
        string="Required Privileges",
        help=(
            "Users who hold at least ONE of these privileges (via Privilege Assignment "
            "or Role Definition) will see this menu item.\n"
            "Leave empty to use the standard default role groups."
        ),
    )
    description = fields.Text(string="Notes / Description")
    active = fields.Boolean(
        string="Active / Visible",
        default=True,
        help="Uncheck to completely hide this menu from all users regardless of privileges.",
    )

    _menu_key_uniq = models.Constraint("unique(menu_key)", "Each menu item can only have one configuration row.")

    @api.depends("menu_key")
    def _compute_menu_label(self):
        label_map = dict(REVIEW_MENU_ITEMS)
        for rec in self:
            rec.menu_label = label_map.get(rec.menu_key, rec.menu_key or "")

    def name_get(self):
        label_map = dict(REVIEW_MENU_ITEMS)
        return [(rec.id, label_map.get(rec.menu_key, rec.menu_key or "?")) for rec in self]

    def write(self, vals):
        res = super().write(vals)
        self.env.registry.clear_cache()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        self.env.registry.clear_cache()
        return recs

    def unlink(self):
        res = super().unlink()
        self.env.registry.clear_cache()
        return res


class ResUsersReviewMenuMixin(models.Model):
    """
    Extends res.users with a method to check Review & Consolidation menu visibility
    based on configured privileges.
    """
    _inherit = "res.users"

    def _pbms_visible_review_menus(self):
        """
        Returns a set of menu_key strings that the current user may see
        based on their privilege assignments.

        Logic:
          - If active=False → hidden regardless.
          - If privilege_ids is SET → user needs ≥1 matching privilege.
          - If privilege_ids is EMPTY → fallback to DEFAULT_MENU_GROUPS.
          - Managers and system admins always see everything.
        """
        if not self:
            return set()

        # Managers and system admins see everything
        if self.has_group("bunna_pbms.group_pbms_manager") or self.has_group("base.group_system"):
            return {k for k, _ in REVIEW_MENU_ITEMS}

        hidden_keys = set()
        configs = {}
        if _safe_table_exists(self.env, "pbms.review.menu.config"):
            try:
                MenuConfig = self.env["pbms.review.menu.config"].sudo()
                # Keys that have active=False → always hidden
                hidden_keys = set(
                    MenuConfig.search([("active", "=", False)]).mapped("menu_key")
                )
                configs = {rec.menu_key: rec for rec in MenuConfig.search([])}
            except Exception:
                pass
        visible = set()

        for key, _ in REVIEW_MENU_ITEMS:
            if key in hidden_keys:
                continue

            rec = configs.get(key)
            if rec and rec.privilege_ids:
                # Dynamic privileges explicitly configured by admin
                for priv in rec.privilege_ids:
                    if self._pbms_has_dynamic_privilege(priv):
                        visible.add(key)
                        break
            else:
                # Fallback to default group access
                default_groups = DEFAULT_MENU_GROUPS.get(key, [])
                for grp_xmlid in default_groups:
                    if self.has_group(grp_xmlid):
                        visible.add(key)
                        break

        return visible

    def _pbms_can_see_review_menu(self, menu_key):
        """Convenience single-key check."""
        return menu_key in self._pbms_visible_review_menus()
