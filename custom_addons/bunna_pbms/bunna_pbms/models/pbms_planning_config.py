# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class PbmsPlanningConfig(models.Model):
    """Planning Configuration per Operating Unit.

    Allows configuring which planning categories (Deposit, Customer Base, FX,
    Digital Banking, General Expense, Manpower, Fixed Asset) are eligible /
    active for a given Operating Unit.
    """
    _name = "pbms.planning.config"
    _description = "Planning Category Configuration by Operating Unit"
    _rec_name = "org_unit_id"
    _order = "org_unit_id"

    org_unit_id = fields.Many2one(
        "operating.unit",
        string="Operating Unit",
        required=True,
        ondelete="cascade",
        index=True,
        help="Select the Operating Unit to configure eligible planning categories for.",
    )
    company_id = fields.Many2one(
        "res.company",
        related="org_unit_id.company_id",
        store=True,
        readonly=True,
    )

    enable_deposit = fields.Boolean(
        string="Deposit Mobilization",
        default=True,
        help="Enable Deposit Mobilization planning for this Operating Unit.",
    )
    enable_customer_base = fields.Boolean(
        string="Customer Base",
        default=True,
        help="Enable Customer Base planning for this Operating Unit.",
    )
    enable_fx = fields.Boolean(
        string="FX Mobilization",
        default=True,
        help="Enable Foreign Exchange (FX) Mobilization planning for this Operating Unit.",
    )
    enable_digital_banking = fields.Boolean(
        string="Digital Banking Channels",
        default=True,
        help="Enable Digital Banking channels planning for this Operating Unit.",
    )
    enable_expense = fields.Boolean(
        string="General Expense",
        default=True,
        help="Enable General Expense budget planning for this Operating Unit.",
    )
    enable_manpower = fields.Boolean(
        string="Manpower Requirement",
        default=True,
        help="Enable Manpower Requirement planning for this Operating Unit.",
    )
    enable_fixed_asset = fields.Boolean(
        string="Fixed Asset Requirement",
        default=True,
        help="Enable Fixed Asset Requirement planning for this Operating Unit.",
    )

    _sql_constraints = [
        ("org_unit_uniq", "unique(org_unit_id)", "A planning configuration already exists for this Operating Unit."),
    ]

    @api.model
    def get_config_for_unit(self, org_unit_id):
        """Retrieve or create default planning configuration for an operating unit."""
        if not org_unit_id:
            return False
        unit_id = org_unit_id.id if isinstance(org_unit_id, models.BaseModel) else org_unit_id
        config = self.search([("org_unit_id", "=", unit_id)], limit=1)
        if not config:
            config = self.create({"org_unit_id": unit_id})
        return config

    @api.model
    def get_user_planning_categories(self):
        """Return enabled planning categories for the current user operating unit.

        Each item contains the tab id, display title, icon and the action XMLID to
        open the full planning screen when selected.
        """
        user = self.env.user
        org_unit = False
        if hasattr(user, "assigned_operating_unit_ids") and user.assigned_operating_unit_ids:
            org_unit = user.assigned_operating_unit_ids[0]
        else:
            org_unit = self.env["operating.unit"].search([], limit=1)

        config = self.get_config_for_unit(org_unit) if org_unit else False
        categories = []
        category_map = [
            ("deposit", "Deposit Mobilization", "fa-university", "action_pbms_deposit_plan", config.enable_deposit if config else True),
            ("customer_base", "Customer Base", "fa-users", "action_pbms_customer_base_plan", config.enable_customer_base if config else True),
            ("fx", "FX Mobilization", "fa-exchange-alt", "action_pbms_fx_plan", config.enable_fx if config else True),
            ("digital_banking", "Digital Banking", "fa-mobile-alt", "action_pbms_digital_banking_plan", config.enable_digital_banking if config else True),
            ("expense", "General Expense", "fa-chart-line", "action_pbms_expense_plan", config.enable_expense if config else True),
            ("manpower", "Manpower Requirement", "fa-user-tie", "action_pbms_manpower_plan", config.enable_manpower if config else True),
            ("fixed_asset", "Fixed Asset Requirement", "fa-building", "action_pbms_fixed_asset_plan", config.enable_fixed_asset if config else True),
        ]

        for category_id, name, icon, action, enabled in category_map:
            if enabled:
                categories.append({
                    "id": category_id,
                    "name": name,
                    "icon": icon,
                    "action": action,
                })

        return {
            "unit_name": org_unit.name if org_unit else "",
            "categories": categories,
        }


class PbmsPlanningWorkspace(models.TransientModel):
    """Tabbed Planning Workspace.

    Provides a unified tabbed interface for users to access eligible planning formats
    (Deposit, Customer Base, FX, Digital Banking, General Expense, Manpower, Fixed Assets)
    in notebook tabs based on their Operating Unit's configuration.
    """
    _name = "pbms.planning.workspace"
    _description = "Tabbed Planning Workspace"

    cycle_id = fields.Many2one(
        "pbms.planning.cycle",
        string="Planning Cycle",
        required=True,
        default=lambda self: self._default_cycle(),
    )
    org_unit_id = fields.Many2one(
        "operating.unit",
        string="Operating Unit",
        required=True,
        default=lambda self: self._default_org_unit(),
    )

    enable_deposit = fields.Boolean(compute="_compute_eligibility", store=False)
    enable_customer_base = fields.Boolean(compute="_compute_eligibility", store=False)
    enable_fx = fields.Boolean(compute="_compute_eligibility", store=False)
    enable_digital_banking = fields.Boolean(compute="_compute_eligibility", store=False)
    enable_expense = fields.Boolean(compute="_compute_eligibility", store=False)
    enable_manpower = fields.Boolean(compute="_compute_eligibility", store=False)
    enable_fixed_asset = fields.Boolean(compute="_compute_eligibility", store=False)

    @api.model
    def _default_cycle(self):
        cycle = self.env["pbms.planning.cycle"].search([("state", "=", "open")], limit=1)
        if not cycle:
            cycle = self.env["pbms.planning.cycle"].search([], order="date_start desc", limit=1)
        return cycle.id if cycle else False

    @api.model
    def _default_org_unit(self):
        user = self.env.user
        if hasattr(user, "assigned_operating_unit_ids") and user.assigned_operating_unit_ids:
            return user.assigned_operating_unit_ids[0].id
        unit = self.env["operating.unit"].search([], limit=1)
        return unit.id if unit else False

    @api.depends("org_unit_id")
    def _compute_eligibility(self):
        Config = self.env["pbms.planning.config"]
        for rec in self:
            if not rec.org_unit_id:
                rec.enable_deposit = True
                rec.enable_customer_base = True
                rec.enable_fx = True
                rec.enable_digital_banking = True
                rec.enable_expense = True
                rec.enable_manpower = True
                rec.enable_fixed_asset = True
            else:
                config = Config.get_config_for_unit(rec.org_unit_id)
                rec.enable_deposit = config.enable_deposit if config else True
                rec.enable_customer_base = config.enable_customer_base if config else True
                rec.enable_fx = config.enable_fx if config else True
                rec.enable_digital_banking = config.enable_digital_banking if config else True
                rec.enable_expense = config.enable_expense if config else True
                rec.enable_manpower = config.enable_manpower if config else True
                rec.enable_fixed_asset = config.enable_fixed_asset if config else True

    @api.model
    def action_get_user_workspace(self):
        """Action launched from Planning menu to open or create the user's tabbed workspace."""
        workspace = self.create({
            "cycle_id": self._default_cycle(),
            "org_unit_id": self._default_org_unit(),
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Planning Workspace"),
            "res_model": "pbms.planning.workspace",
            "res_id": workspace.id,
            "view_mode": "form",
            "target": "main",
        }