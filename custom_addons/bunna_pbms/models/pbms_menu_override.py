# -*- coding: utf-8 -*-
"""
pbms_menu_override.py
=====================
Override ir.ui.menu._load_menus_blacklist() to dynamically hide
Review & Consolidation sub-menus based on PBMS privilege assignments
configured in pbms.review.menu.config.

Odoo 19 calls _load_menus_blacklist() inside load_menus() and excludes
those IDs from the session menu tree.
"""
import logging
from odoo import api, models

_logger = logging.getLogger(__name__)

# xmlid → menu_key mapping (mirrors pbms_review_menu_config.py)
XMLID_TO_MENU_KEY = {
    "bunna_pbms.menu_pbms_review_retail":                "deposit",
    "bunna_pbms.menu_pbms_review_retail_customer":       "customer_base",
    "bunna_pbms.menu_pbms_review_workforce":             "workforce",
    "bunna_pbms.menu_pbms_review_exceptional_workforce": "exceptional_workforce",
    "bunna_pbms.menu_pbms_review_fx":                    "fx",
    "bunna_pbms.menu_pbms_review_digital":               "digital",
    "bunna_pbms.menu_pbms_review_loan_disbursement":     "loan_disbursement",
    "bunna_pbms.menu_pbms_review_loan_outstanding":      "loan_outstanding",
    "bunna_pbms.menu_pbms_review_expense":               "expense",
    "bunna_pbms.menu_pbms_review_fixed_asset":           "fixed_asset",
    "bunna_pbms.menu_pbms_review_credit_portfolio":      "income_plan",
    "bunna_pbms.menu_pbms_review_initiative_budget":     "initiative_budget",
    "bunna_pbms.menu_pbms_consolidation":                "consolidation",
}


class IrUiMenuPbmsOverride(models.Model):
    _inherit = "ir.ui.menu"

    @api.model
    def _load_menus_blacklist(self):
        """
        Extend Odoo's blacklist with Review & Consolidation menu IDs that
        the current user lacks the configured PBMS privilege for.
        """
        blacklist = super()._load_menus_blacklist()

        try:
            MenuConfig = self.env.get("pbms.review.menu.config")
            if MenuConfig is None:
                return blacklist

            user = self.env.user
            visible_keys = user._pbms_visible_review_menus()

            # Any review menu not in visible_keys must be hidden / blacklisted
            all_review_keys = set(XMLID_TO_MENU_KEY.values())
            hide_keys = all_review_keys - visible_keys

            if hide_keys:
                extra_blacklist = self._pbms_menu_ids_for_keys(hide_keys)
                return list(set(blacklist) | extra_blacklist)

        except Exception as e:
            _logger.warning("PBMS review menu privilege filter error: %s", e, exc_info=True)

        return blacklist

    @api.model
    def _pbms_menu_ids_for_keys(self, menu_keys):
        """
        Given a set of menu_key strings, return the set of ir.ui.menu IDs
        (integers) for those menu items via ir.model.data lookup.
        """
        result = set()
        IrModelData = self.env["ir.model.data"].sudo()
        for xmlid, key in XMLID_TO_MENU_KEY.items():
            if key not in menu_keys:
                continue
            module, name = xmlid.split(".", 1)
            rec = IrModelData.search([
                ("module", "=", module),
                ("name", "=", name),
                ("model", "=", "ir.ui.menu"),
            ], limit=1)
            if rec:
                result.add(rec.res_id)
        return result
