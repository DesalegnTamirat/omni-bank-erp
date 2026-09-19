# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

from .planing_categories import WORK_UNIT_TYPES

# Map config toggle -> unified category value
CATEGORY_TOGGLE_MAP = [
    ("deposit", "enable_deposit", "Deposit Mobilization"),
    ("customer_base", "enable_customer_base", "Customer Base"),
    ("fx", "enable_fx", "FX Mobilization"),
    ("digital_banking", "enable_digital_banking", "Digital Banking"),
    ("general_expense", "enable_expense", "General Expense"),
    ("manpower", "enable_manpower", "Work Force"),
    ("fixed_asset", "enable_fixed_asset", "Fixed Asset Requirement"),
]


class PbmsPlanningConfig(models.Model):
    """Planning Configuration per Work Unit Type.

    Allows configuring which planning categories (Deposit, Customer Base, FX,
    Digital Banking, General Expense, Manpower, Fixed Asset) are eligible /
    active for a given Work Unit Type (Branch, District Office, Head Office,
    ...). The tabbed planning workspace then shows exactly the enabled tabs.
    """
    _name = "pbms.planning.config"
    _description = "Planning Category Configuration by Work Unit Type"
    _rec_name = "work_unit_type"
    _order = "work_unit_type"

    work_unit_type = fields.Selection(
        WORK_UNIT_TYPES,
        string="Work Unit Type",
        required=True,
        index=True,
        help="Select the Work Unit Type (Branch, District Office, Head Office, ...) "
             "to configure eligible planning categories for.",
    )

    enable_deposit = fields.Boolean(
        string="Deposit Mobilization",
        default=True,
        help="Enable Deposit Mobilization planning for this Work Unit Type.",
    )
    enable_customer_base = fields.Boolean(
        string="Customer Base",
        default=True,
        help="Enable Customer Base planning for this Work Unit Type.",
    )
    enable_fx = fields.Boolean(
        string="FX Mobilization",
        default=True,
        help="Enable Foreign Exchange (FX) Mobilization planning for this Work Unit Type.",
    )
    enable_digital_banking = fields.Boolean(
        string="Digital Banking Channels",
        default=True,
        help="Enable Digital Banking channels planning for this Work Unit Type.",
    )
    enable_expense = fields.Boolean(
        string="General Expense",
        default=True,
        help="Enable General Expense budget planning for this Work Unit Type.",
    )
    enable_manpower = fields.Boolean(
        string="Work Force",
        default=True,
        help="Enable Manpower Requirement planning for this Work Unit Type.",
    )
    enable_fixed_asset = fields.Boolean(
        string="Fixed Asset Requirement",
        default=True,
        help="Enable Fixed Asset Requirement planning for this Work Unit Type.",
    )

    _work_unit_type_uniq = models.Constraint(
        "unique(work_unit_type)",
        "A planning configuration already exists for this Work Unit Type.",
    )

    @api.model
    def get_config_for_type(self, work_unit_type):
        """Retrieve or create default planning configuration for a work unit type."""
        if not work_unit_type:
            return False
        config = self.search([("work_unit_type", "=", work_unit_type)], limit=1)
        if not config:
            config = self.create({"work_unit_type": work_unit_type})
        return config

    @api.model
    def _get_user_work_unit_type(self):
        user = self.env.user
        org_unit = False
        if hasattr(user, "default_operating_unit_id") and user.default_operating_unit_id:
            org_unit = user.default_operating_unit_id
        elif hasattr(user, "assigned_operating_unit_ids") and user.assigned_operating_unit_ids:
            org_unit = user.assigned_operating_unit_ids[0]
        else:
            org_unit = self.env["operating.unit"].search([], limit=1)
        return org_unit.work_unit_type if org_unit else False

    @api.model
    def get_user_planning_categories(self):
        """Return enabled planning categories for the current user's work unit type.

        Each item contains the category id, display title, icon and the action
        XMLID to open the unified planning screen when selected.
        """
        work_unit_type = self._get_user_work_unit_type()
        config = self.get_config_for_type(work_unit_type) if work_unit_type else False
        categories = []
        icons = {
            "deposit": "fa-university",
            "customer_base": "fa-users",
            "fx": "fa-exchange-alt",
            "digital_banking": "fa-mobile-alt",
            "general_expense": "fa-chart-line",
            "manpower": "fa-user-tie",
            "fixed_asset": "fa-building",
        }
        for category_id, toggle, name in CATEGORY_TOGGLE_MAP:
            enabled = getattr(config, toggle) if config else True
            if enabled:
                categories.append({
                    "id": category_id,
                    "name": name,
                    "icon": icons.get(category_id, "fa-file"),
                    "action": "action_pbms_planning_category",
                })
        unit = self.env.user.default_operating_unit_id
        return {
            "work_unit_type": work_unit_type,
            "unit_name": unit.display_name if unit else "",
            "categories": categories,
        }


class PbmsPlanningWorkspace(models.Model):
    """Tabbed Planning Workspace.

    Provides a unified notebook screen for the user's operating unit / cycle.
    Each tab corresponds to one planning category and embeds the editable plan
    lines of the single ``pbms.planning.category`` model. Tabs are shown /
    hidden based on the Planning Configuration for the work unit type of the
    selected operating unit.
    """
    _name = "pbms.planning.workspace"
    _description = "Tabbed Planning Workspace"
    _rec_name = "org_unit_id"

    cycle_id = fields.Many2one(
        "pbms.planning.cycle",
        string="Planning Cycle",
        required=True,
        ondelete="cascade",
        default=lambda self: self._default_cycle(),
    )
    org_unit_id = fields.Many2one(
        "operating.unit",
        string="Work Unit",
        required=True,
        default=lambda self: self._default_org_unit(),
    )
    work_unit_type = fields.Selection(
        WORK_UNIT_TYPES, related="org_unit_id.work_unit_type", store=True, readonly=True,
    )

    enable_deposit = fields.Boolean(compute="_compute_eligibility")
    enable_customer_base = fields.Boolean(compute="_compute_eligibility")
    enable_fx = fields.Boolean(compute="_compute_eligibility")
    enable_digital_banking = fields.Boolean(compute="_compute_eligibility")
    enable_expense = fields.Boolean(compute="_compute_eligibility")
    enable_manpower = fields.Boolean(compute="_compute_eligibility")
    enable_fixed_asset = fields.Boolean(compute="_compute_eligibility")

    # Editable plan lines per category, all backed by pbms.planning.category
    deposit_line_ids = fields.One2many("pbms.planning.category", "workspace_deposit_id", string="Deposit Plans")
    customer_base_line_ids = fields.One2many("pbms.planning.category", "workspace_customer_base_id", string="Customer Base Plans")
    fx_line_ids = fields.One2many("pbms.planning.category", "workspace_fx_id", string="FX Plans")
    digital_banking_line_ids = fields.One2many("pbms.planning.category", "workspace_digital_banking_id", string="Digital Banking Plans")
    expense_line_ids = fields.One2many("pbms.planning.category", "workspace_expense_id", string="General Expense Plans")
    manpower_line_ids = fields.One2many("pbms.planning.category", "workspace_manpower_id", string="Manpower Plans")
    fixed_asset_line_ids = fields.One2many("pbms.planning.category", "workspace_fixed_asset_id", string="Fixed Asset Plans")

    @api.model
    def _default_cycle(self):
        cycle = self.env["pbms.planning.cycle"].search([("state", "=", "open")], limit=1)
        return cycle.id if cycle else False

    @api.model
    def _default_org_unit(self):
        user = self.env.user
        if hasattr(user, "default_operating_unit_id") and user.default_operating_unit_id:
            return user.default_operating_unit_id.id
        if hasattr(user, "assigned_operating_unit_ids") and user.assigned_operating_unit_ids:
            return user.assigned_operating_unit_ids[0].id
        unit = self.env["operating.unit"].search([], limit=1)
        return unit.id if unit else False

    @api.depends("org_unit_id", "org_unit_id.work_unit_type")
    def _compute_eligibility(self):
        Config = self.env["pbms.planning.config"]
        for rec in self:
            defaults = {toggle: True for _cat, toggle, _name in CATEGORY_TOGGLE_MAP}
            if rec.org_unit_id:
                config = Config.get_config_for_type(rec.org_unit_id.work_unit_type)
                if config:
                    defaults = {
                        toggle: getattr(config, toggle)
                        for _cat, toggle, _name in CATEGORY_TOGGLE_MAP
                    }
            for _cat, toggle, _name in CATEGORY_TOGGLE_MAP:
                rec[toggle] = defaults[toggle]

    @api.model
    def _find_workspace(self):
        """Reuse the workspace of the current cycle + work unit if present."""
        cycle_id = self._default_cycle()
        if not cycle_id:
            return False
        domain = [("cycle_id", "=", cycle_id)]
        org_unit_id = self._default_org_unit()
        if org_unit_id:
            domain.append(("org_unit_id", "=", org_unit_id))
        workspace = self.search(domain, limit=1)
        if not workspace:
            vals = {"cycle_id": cycle_id}
            if org_unit_id:
                vals["org_unit_id"] = org_unit_id
            workspace = self.create(vals)
        return workspace

    @api.model
    def action_get_user_workspace(self):
        """Action launched from the Planning menu to open the user's tabbed workspace."""
        workspace = self._find_workspace()
        if not workspace:
            pending_cycle = self.env["pbms.planning.cycle"].search([], order="date_start desc", limit=1)
            state_label = dict(pending_cycle._fields['state'].selection).get(pending_cycle.state, pending_cycle.state) if pending_cycle else ""
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Planning Cycle Not Open'),
                    'message': _("Planning cycle '%s' is currently '%s' and is not open for unit input.") % (pending_cycle.name if pending_cycle else "", state_label),
                    'type': 'warning',
                    'sticky': True,
                }
            }
        return {
            "type": "ir.actions.act_window",
            "name": _("Planning Workspace"),
            "res_model": "pbms.planning.workspace",
            "res_id": workspace.id,
            "view_mode": "form",
            "target": "main",
        }