# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

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

# Measurement types per planning category
CATEGORY_MEASUREMENT_TYPES = {
    "deposit": "monetary",
    "customer_base": "integer",
    "fx": "monetary",
    "digital_banking": "integer",
    "general_expense": "monetary",
    "manpower": "integer",
    "fixed_asset": "integer",
}

# Default currency per category (company currency)
DEFAULT_CURRENCY = "ETB"


class PbmsPlanningConfig(models.Model):
    """Planning Configuration per Work Unit Type or specific Operating Unit.

    Allows configuring which planning categories (Deposit, Customer Base, FX,
    Digital Banking, General Expense, Manpower, Fixed Asset) are eligible /
    active for a given Work Unit Type (Branch, District Office, Head Office,
    ...) or overridden for a specific Operating Unit (e.g. Branch X).
    Also supports category-specific operating unit exclusions under a work unit type.
    """
    _name = "pbms.planning.config"
    _description = "Planning Category Configuration by Work Unit Type & Operating Unit"
    _order = "config_type, work_unit_type, id"

    config_type = fields.Selection(
        [
            ("work_unit_type", "Work Unit Type"),
            ("operating_unit", "Specific Operating Unit"),
        ],
        string="Configuration Scope",
        default="work_unit_type",
        required=True,
        index=True,
        help="Select whether this configuration applies to all operating units of a Work Unit Type or specifically overrides settings for a single Operating Unit.",
    )
    work_unit_type = fields.Selection(
        WORK_UNIT_TYPES,
        string="Work Unit Type",
        index=True,
        help="Select the Work Unit Type (Branch, District Office, Head Office, ...) to configure eligible planning categories for.",
    )
    org_unit_id = fields.Many2one(
        "operating.unit",
        string="Specific Operating Unit",
        index=True,
        help="Select the specific Operating Unit to override planning settings for (e.g. disable FX or General Expense for this branch).",
    )
    display_name = fields.Char(compute="_compute_display_name", store=True)

    # Currency for monetary planning categories
    currency_id = fields.Many2one(
        "res.currency",
        string="Default Base Currency",
        default=lambda self: self.env.company.currency_id,
        required=True,
        help="Default base currency used for general planning categories.",
    )
    fx_currency_id = fields.Many2one(
        "res.currency",
        string="FX Planning Currency",
        default=lambda self: self.env["res.currency"].search([("name", "=", "USD")], limit=1) or self.env.company.currency_id,
        help="Default foreign currency for FX Mobilization planning (e.g. USD, EUR, GBP).",
    )
    fx_allowed_currency_ids = fields.Many2many(
        "res.currency",
        "pbms_planning_config_fx_currency_rel",
        "config_id",
        "currency_id",
        string="Allowed FX Currencies",
        help="Select allowable foreign currencies (USD, EUR, GBP, AED, etc.) for FX planning.",
    )
    deposit_currency_id = fields.Many2one(
        "res.currency",
        string="Deposit Planning Currency",
        default=lambda self: self.env.company.currency_id,
        help="Currency for Deposit Mobilization planning (defaults to ETB).",
    )
    expense_currency_id = fields.Many2one(
        "res.currency",
        string="Expense Planning Currency",
        default=lambda self: self.env.company.currency_id,
        help="Currency for General Expense planning (defaults to ETB).",
    )

    enable_deposit = fields.Boolean(
        string="Deposit Mobilization",
        default=True,
        help="Enable Deposit Mobilization planning for this Work Unit Type / Operating Unit.",
    )
    enable_customer_base = fields.Boolean(
        string="Customer Base",
        default=True,
        help="Enable Customer Base planning for this Work Unit Type / Operating Unit.",
    )
    enable_fx = fields.Boolean(
        string="FX Mobilization",
        default=True,
        help="Enable Foreign Exchange (FX) Mobilization planning for this Work Unit Type / Operating Unit.",
    )
    enable_digital_banking = fields.Boolean(
        string="Digital Banking Channels",
        default=True,
        help="Enable Digital Banking channels planning for this Work Unit Type / Operating Unit.",
    )
    enable_expense = fields.Boolean(
        string="General Expense",
        default=True,
        help="Enable General Expense budget planning for this Work Unit Type / Operating Unit.",
    )
    enable_manpower = fields.Boolean(
        string="Work force",
        default=True,
        help="Enable Manpower Requirement planning for this Work Unit Type / Operating Unit.",
    )
    enable_fixed_asset = fields.Boolean(
        string="Fixed Asset Requirement",
        default=True,
        help="Enable Fixed Asset Requirement planning for this Work Unit Type / Operating Unit.",
    )

    # Measurement type per category (monetary, integer, count)
    deposit_measurement_type = fields.Selection(
        [("monetary", "Monetary"), ("integer", "Integer"), ("count", "Count")],
        string="Deposit Measurement",
        default="monetary",
        help="Measurement type for Deposit Mobilization targets.",
    )
    customer_base_measurement_type = fields.Selection(
        [("monetary", "Monetary"), ("integer", "Integer"), ("count", "Count")],
        string="Customer Base Measurement",
        default="integer",
        help="Measurement type for Customer Base targets.",
    )
    fx_measurement_type = fields.Selection(
        [("monetary", "Monetary"), ("integer", "Integer"), ("count", "Count")],
        string="FX Measurement",
        default="monetary",
        help="Measurement type for FX Mobilization targets.",
    )
    digital_banking_measurement_type = fields.Selection(
        [("monetary", "Monetary"), ("integer", "Integer"), ("count", "Count")],
        string="Digital Banking Measurement",
        default="integer",
        help="Measurement type for Digital Banking targets.",
    )
    expense_measurement_type = fields.Selection(
        [("monetary", "Monetary"), ("integer", "Integer"), ("count", "Count")],
        string="Expense Measurement",
        default="monetary",
        help="Measurement type for General Expense targets.",
    )
    manpower_measurement_type = fields.Selection(
        [("monetary", "Monetary"), ("integer", "Integer"), ("count", "Count")],
        string="Manpower Measurement",
        default="integer",
        help="Measurement type for Manpower Requirement targets.",
    )
    fixed_asset_measurement_type = fields.Selection(
        [("monetary", "Monetary"), ("integer", "Integer"), ("count", "Count")],
        string="Fixed Asset Measurement",
        default="integer",
        help="Measurement type for Fixed Asset Requirement targets.",
    )

    # Category-specific excluded operating units under this work unit type
    deposit_excluded_org_unit_ids = fields.Many2many(
        "operating.unit",
        "pbms_config_deposit_excluded_ou_rel",
        "config_id",
        "org_unit_id",
        string="Excluded Units for Deposit",
        help="Specific operating units under this work unit type where Deposit Mobilization is not eligible.",
    )
    customer_base_excluded_org_unit_ids = fields.Many2many(
        "operating.unit",
        "pbms_config_cust_base_excluded_ou_rel",
        "config_id",
        "org_unit_id",
        string="Excluded Units for Customer Base",
        help="Specific operating units under this work unit type where Customer Base is not eligible.",
    )
    fx_excluded_org_unit_ids = fields.Many2many(
        "operating.unit",
        "pbms_config_fx_excluded_ou_rel",
        "config_id",
        "org_unit_id",
        string="Excluded Units for FX Mobilization",
        help="Specific operating units under this work unit type where FX Mobilization is not eligible.",
    )
    digital_banking_excluded_org_unit_ids = fields.Many2many(
        "operating.unit",
        "pbms_config_dig_bank_excluded_ou_rel",
        "config_id",
        "org_unit_id",
        string="Excluded Units for Digital Banking",
        help="Specific operating units under this work unit type where Digital Banking is not eligible.",
    )
    expense_excluded_org_unit_ids = fields.Many2many(
        "operating.unit",
        "pbms_config_expense_excluded_ou_rel",
        "config_id",
        "org_unit_id",
        string="Excluded Units for General Expense",
        help="Specific operating units under this work unit type where General Expense is not eligible.",
    )
    manpower_excluded_org_unit_ids = fields.Many2many(
        "operating.unit",
        "pbms_config_manpower_excluded_ou_rel",
        "config_id",
        "org_unit_id",
        string="Excluded Units for Manpower",
        help="Specific operating units under this work unit type where Manpower is not eligible.",
    )
    fixed_asset_excluded_org_unit_ids = fields.Many2many(
        "operating.unit",
        "pbms_config_fa_excluded_ou_rel",
        "config_id",
        "org_unit_id",
        string="Excluded Units for Fixed Asset",
        help="Specific operating units under this work unit type where Fixed Asset is not eligible.",
    )

    # Configurable dropdown selections per category
    deposit_type_ids = fields.Many2many(
        "pbms.deposit.type",
        "pbms_planning_config_deposit_type_rel",
        "config_id",
        "deposit_type_id",
        string="Available Deposit Types",
        help="Select which deposit types are available for Deposit Mobilization planning.",
    )
    digital_channel_ids = fields.Many2many(
        "pbms.digital.channel",
        "pbms_planning_config_digital_channel_rel",
        "config_id",
        "channel_id",
        string="Available Digital Channels",
        help="Select which digital channels are available for Digital Banking planning.",
    )
    expense_account_ids = fields.Many2many(
        "pbms.expense.account",
        "pbms_planning_config_expense_account_rel",
        "config_id",
        "expense_account_id",
        string="Available Expense Accounts",
        help="Select which expense accounts are available for General Expense planning.",
    )
    fixed_asset_category_ids = fields.Many2many(
        "pbms.fixed.asset.category",
        "pbms_planning_config_fa_category_rel",
        "config_id",
        "fa_category_id",
        string="Available Fixed Asset Categories",
        help="Select which fixed asset categories are available for Fixed Asset planning.",
    )
    justification_category_ids = fields.Many2many(
        "pbms.justification.category",
        "pbms_planning_config_justification_rel",
        "config_id",
        "justification_category_id",
        string="Available Justification Categories",
        help="Select which justification categories are available for Manpower planning.",
    )
    position_type_ids = fields.Many2many(
        "pbms.position.type",
        "pbms_planning_config_pos_type_rel",
        "config_id",
        "position_type_id",
        string="Available Position / Request Types",
        help="Select which request types (New Position, Additional Position, Replacement, Position Transfer, Position Upgrade) are available for Manpower planning.",
    )
    fx_source_type_ids = fields.Many2many(
        "pbms.fx.source.type",
        "pbms_planning_config_fx_source_rel",
        "config_id",
        "fx_source_type_id",
        string="Available FX Sources",
        help="Select which FX sources are available for FX Mobilization planning.",
    )

    # -------------------------------------------------------------
    # Functional Reviewers & Department Routing per Category
    # -------------------------------------------------------------
    deposit_reviewer_ou_id = fields.Many2one(
        "operating.unit",
        string="Responsible Head Office Unit (Deposit)",
        help="Head Office Operating Unit responsible for reviewing Deposit Mobilization plans (e.g. Retail Operation).",
    )
    deposit_reviewer_dept_id = fields.Many2one(
        "hr.department",
        string="Responsible Department (Deposit)",
        help="Department responsible for reviewing Deposit Mobilization plans (e.g. Retail Banking Operations).",
    )
    deposit_reviewer_user_ids = fields.Many2many(
        "res.users",
        "pbms_cfg_deposit_reviewer_rel",
        "config_id",
        "user_id",
        string="Designated Reviewers (Deposit)",
        help="Specific user accounts assigned to review Deposit Mobilization plans.",
    )

    customer_base_reviewer_ou_id = fields.Many2one(
        "operating.unit",
        string="Responsible Head Office Unit (Customer Base)",
        help="Head Office Operating Unit responsible for reviewing Customer Base plans.",
    )
    customer_base_reviewer_dept_id = fields.Many2one(
        "hr.department",
        string="Responsible Department (Customer Base)",
        help="Department responsible for reviewing Customer Base plans.",
    )
    customer_base_reviewer_user_ids = fields.Many2many(
        "res.users",
        "pbms_cfg_customer_base_reviewer_rel",
        "config_id",
        "user_id",
        string="Designated Reviewers (Customer Base)",
        help="Specific user accounts assigned to review Customer Base plans.",
    )

    fx_reviewer_ou_id = fields.Many2one(
        "operating.unit",
        string="Responsible Head Office Unit (FX)",
        help="Head Office Operating Unit responsible for reviewing FX Mobilization plans (e.g. International Banking).",
    )
    fx_reviewer_dept_id = fields.Many2one(
        "hr.department",
        string="Responsible Department (FX)",
        help="Department responsible for reviewing FX Mobilization plans (e.g. International Banking / Trade).",
    )
    fx_reviewer_user_ids = fields.Many2many(
        "res.users",
        "pbms_cfg_fx_reviewer_rel",
        "config_id",
        "user_id",
        string="Designated Reviewers (FX)",
        help="Specific user accounts assigned to review FX Mobilization plans.",
    )

    digital_reviewer_ou_id = fields.Many2one(
        "operating.unit",
        string="Responsible Head Office Unit (Digital)",
        help="Head Office Operating Unit responsible for reviewing Digital Banking plans.",
    )
    digital_reviewer_dept_id = fields.Many2one(
        "hr.department",
        string="Responsible Department (Digital)",
        help="Department responsible for reviewing Digital Banking plans.",
    )
    digital_reviewer_user_ids = fields.Many2many(
        "res.users",
        "pbms_cfg_digital_reviewer_rel",
        "config_id",
        "user_id",
        string="Designated Reviewers (Digital)",
        help="Specific user accounts assigned to review Digital Banking plans.",
    )

    expense_reviewer_ou_id = fields.Many2one(
        "operating.unit",
        string="Responsible Head Office Unit (Expense)",
        help="Head Office Operating Unit responsible for reviewing General Expense plans (e.g. Finance & Accounts).",
    )
    expense_reviewer_dept_id = fields.Many2one(
        "hr.department",
        string="Responsible Department (Expense)",
        help="Department responsible for reviewing General Expense plans (e.g. Finance & Accounts).",
    )
    expense_reviewer_user_ids = fields.Many2many(
        "res.users",
        "pbms_cfg_expense_reviewer_rel",
        "config_id",
        "user_id",
        string="Designated Reviewers (Expense)",
        help="Specific user accounts assigned to review General Expense plans.",
    )

    manpower_reviewer_ou_id = fields.Many2one(
        "operating.unit",
        string="Responsible Head Office Unit (Manpower)",
        help="Head Office Operating Unit responsible for reviewing Manpower Requirement plans (e.g. Human Resources).",
    )
    manpower_reviewer_dept_id = fields.Many2one(
        "hr.department",
        string="Responsible Department (Manpower)",
        help="Department responsible for reviewing Manpower Requirement plans (e.g. Human Resources).",
    )
    manpower_reviewer_user_ids = fields.Many2many(
        "res.users",
        "pbms_cfg_manpower_reviewer_rel",
        "config_id",
        "user_id",
        string="Designated Reviewers (Work force)",
        help="Specific user accounts assigned to review Manpower Requirement plans.",
    )

    budget_hiring_committee_user_ids = fields.Many2many(
        "res.users",
        "pbms_cfg_committee_user_rel",
        "config_id",
        "user_id",
        string="Budget Hiring Committee Members",
        help="Designated members of the Budget Hiring Committee responsible for reviewing and approving manpower targets.",
    )
    ceo_user_id = fields.Many2one(
        "res.users",
        string="Chief Executive Officer (CEO)",
        help="Designated CEO user account for executive approval of external vacancies.",
    )

    fixed_asset_reviewer_ou_id = fields.Many2one(
        "operating.unit",
        string="Responsible Head Office Unit (Fixed Asset)",
        help="Head Office Operating Unit responsible for reviewing Fixed Asset Requirement plans.",
    )
    fixed_asset_reviewer_dept_id = fields.Many2one(
        "hr.department",
        string="Responsible Department (Fixed Asset)",
        help="Department responsible for reviewing Fixed Asset Requirement plans.",
    )
    fixed_asset_reviewer_user_ids = fields.Many2many(
        "res.users",
        "pbms_cfg_fixed_asset_reviewer_rel",
        "config_id",
        "user_id",
        string="Designated Reviewers (Fixed Asset)",
        help="Specific user accounts assigned to review Fixed Asset Requirement plans.",
    )

    @api.model
    def get_category_review_info(cls, category, org_unit=None):
        """Lookup responsible Operating Unit, Department, and Reviewer users for a category.
        Follows a strict hierarchy to locate the configuration where this category is defined:
        1. Specific Operating Unit override
        2. Parent / Ancestor Operating Unit (e.g. parent District Office)
        3. Work Unit Type default (e.g. branch)
        4. Parent Work Unit Type default (e.g. district_office)
        5. Global fallback to any config that defined this category
        """
        Config = cls.env["pbms.planning.config"]
        prefix_map = {
            "deposit": "deposit",
            "customer_base": "customer_base",
            "fx": "fx",
            "digital_banking": "digital",
            "general_expense": "expense",
            "manpower": "manpower",
            "fixed_asset": "fixed_asset",
        }
        prefix = prefix_map.get(category, category)

        def _is_configured(cfg_rec):
            if not cfg_rec:
                return False
            users = getattr(cfg_rec, f"{prefix}_reviewer_user_ids", False)
            ou = getattr(cfg_rec, f"{prefix}_reviewer_ou_id", False)
            dept = getattr(cfg_rec, f"{prefix}_reviewer_dept_id", False)
            return bool(users or ou or dept)

        cfg = False
        if org_unit:
            # 1. Direct operating unit config
            c1 = Config.search([("config_type", "=", "operating_unit"), ("org_unit_id", "=", org_unit.id)], limit=1)
            if _is_configured(c1):
                cfg = c1

            # 2. Check parent/ancestor operating units (e.g. parent district)
            if not cfg:
                curr_ou = org_unit
                for _ in range(5):
                    parent = getattr(curr_ou, "parent_unit", False) or getattr(curr_ou, "parent_id", False)
                    if not parent:
                        break
                    c_parent = Config.search([("config_type", "=", "operating_unit"), ("org_unit_id", "=", parent.id)], limit=1)
                    if _is_configured(c_parent):
                        cfg = c_parent
                        break
                    curr_ou = parent

            # 3. Work unit type config for this unit
            if not cfg and org_unit.work_unit_type:
                c_type = Config.search([("config_type", "=", "work_unit_type"), ("work_unit_type", "=", org_unit.work_unit_type)], limit=1)
                if _is_configured(c_type):
                    cfg = c_type

            # 4. Parent work unit type config (e.g. district_office)
            if not cfg:
                parent = getattr(org_unit, "parent_unit", False) or getattr(org_unit, "parent_id", False)
                if parent and parent.work_unit_type:
                    c_ptype = Config.search([("config_type", "=", "work_unit_type"), ("work_unit_type", "=", parent.work_unit_type)], limit=1)
                    if _is_configured(c_ptype):
                        cfg = c_ptype

        # 5. Global fallback to any config that defined this category
        if not cfg:
            all_cfgs = Config.search([], order="config_type desc, id asc")
            for c_cand in all_cfgs:
                if _is_configured(c_cand):
                    cfg = c_cand
                    break

        if cfg:
            users = getattr(cfg, f"{prefix}_reviewer_user_ids", cls.env["res.users"])
            ou = getattr(cfg, f"{prefix}_reviewer_ou_id", False)
            dept = getattr(cfg, f"{prefix}_reviewer_dept_id", False)
            return {"users": users, "ou": ou, "dept": dept}
        return {"users": cls.env["res.users"], "ou": False, "dept": False}

    @api.model
    def get_user_authorized_categories(cls, user):
        """Check all Planning Configurations to determine which categories the user is designated to review."""
        Config = cls.env["pbms.planning.config"]
        configs = Config.search([])
        cats = set()
        user_unit_ids = set(user._pbms_operating_unit_ids())
        user_dept_id = user.employee_id.department_id.id if (user.employee_id and user.employee_id.department_id) else False

        prefix_map = [
            ("deposit", "deposit"),
            ("customer_base", "customer_base"),
            ("fx", "fx"),
            ("digital_banking", "digital"),
            ("general_expense", "expense"),
            ("manpower", "manpower"),
            ("fixed_asset", "fixed_asset"),
        ]

        for cfg in configs:
            for cat, prefix in prefix_map:
                user_ids = getattr(cfg, f"{prefix}_reviewer_user_ids", cls.env["res.users"]).ids
                ou_id = getattr(cfg, f"{prefix}_reviewer_ou_id", False)
                dept_id = getattr(cfg, f"{prefix}_reviewer_dept_id", False)
                if user.id in user_ids:
                    cats.add(cat)
                elif ou_id and ou_id.id in user_unit_ids:
                    cats.add(cat)
                elif dept_id and user_dept_id and dept_id.id == user_dept_id:
                    cats.add(cat)

        return list(cats)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_committee_and_ceo_roles()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "budget_hiring_committee_user_ids" in vals or "ceo_user_id" in vals:
            self._sync_committee_and_ceo_roles()
        return res

    def action_save(self):
        """Explicit save action for Planning Configuration."""
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Configuration Saved"),
                "message": _("Planning configuration has been saved successfully."),
                "type": "success",
                "sticky": False,
            },
        }

    def _sync_committee_and_ceo_roles(self):
        grp_comm = self.env.ref("bunna_pbms.group_pbms_budget_hiring_committee", raise_if_not_found=False)
        grp_ceo = self.env.ref("bunna_pbms.group_pbms_ceo", raise_if_not_found=False)
        for rec in self:
            if grp_comm and rec.budget_hiring_committee_user_ids:
                grp_comm.sudo().write({"user_ids": [(4, u.id) for u in rec.budget_hiring_committee_user_ids]})
            if grp_ceo and rec.ceo_user_id:
                grp_ceo.sudo().write({"user_ids": [(4, rec.ceo_user_id.id)]})

    @api.depends("config_type", "work_unit_type", "org_unit_id", "org_unit_id.display_name")
    def _compute_display_name(self):
        type_labels = dict(WORK_UNIT_TYPES)
        for rec in self:
            if rec.config_type == "operating_unit" and rec.org_unit_id:
                rec.display_name = f"[Override] {rec.org_unit_id.display_name}"
            elif rec.work_unit_type:
                rec.display_name = f"{type_labels.get(rec.work_unit_type, rec.work_unit_type)} (Default)"
            else:
                rec.display_name = _("Planning Configuration")

    @api.onchange("org_unit_id")
    def _onchange_org_unit_id(self):
        if self.org_unit_id and self.org_unit_id.work_unit_type:
            self.work_unit_type = self.org_unit_id.work_unit_type

    @api.constrains("config_type", "work_unit_type", "org_unit_id")
    def _check_unique_config(self):
        for rec in self:
            if rec.config_type == "work_unit_type":
                if not rec.work_unit_type:
                    raise ValidationError(_("Please select a Work Unit Type for default configuration."))
                existing = self.search([
                    ("id", "!=", rec.id),
                    ("config_type", "=", "work_unit_type"),
                    ("work_unit_type", "=", rec.work_unit_type),
                ])
                if existing:
                    raise ValidationError(_(
                        "A default configuration for Work Unit Type '%s' already exists."
                    ) % dict(WORK_UNIT_TYPES).get(rec.work_unit_type, rec.work_unit_type))
            elif rec.config_type == "operating_unit":
                if not rec.org_unit_id:
                    raise ValidationError(_("Please select a Specific Operating Unit."))
                existing = self.search([
                    ("id", "!=", rec.id),
                    ("config_type", "=", "operating_unit"),
                    ("org_unit_id", "=", rec.org_unit_id.id),
                ])
                if existing:
                    raise ValidationError(_(
                        "A configuration override for Operating Unit '%s' already exists."
                    ) % rec.org_unit_id.display_name)

    @api.model
    def _default_deposit_types(self):
        """Default all active deposit types."""
        return self.env["pbms.deposit.type"].search([("active", "=", True)]).ids

    @api.model
    def _default_digital_channels(self):
        """Default all active digital channels."""
        return self.env["pbms.digital.channel"].search([("active", "=", True)]).ids

    @api.model
    def _default_expense_accounts(self):
        """Default all active expense accounts."""
        return self.env["pbms.expense.account"].search([("active", "=", True)]).ids

    @api.model
    def _default_fa_categories(self):
        """Default all active fixed asset categories."""
        return self.env["pbms.fixed.asset.category"].search([("active", "=", True)]).ids

    @api.model
    def _default_justification_categories(self):
        """Default all active justification categories."""
        return self.env["pbms.justification.category"].search([("active", "=", True)]).ids

    @api.model
    def _default_fx_source_types(self):
        """Default all active FX source types."""
        return self.env["pbms.fx.source.type"].search([("active", "=", True)]).ids

    def init(self):
        super().init()
        # 1. Backfill config_type to 'work_unit_type' where NULL
        self.env.cr.execute("""
            UPDATE pbms_planning_config
            SET config_type = 'work_unit_type'
            WHERE config_type IS NULL;
        """)
        # 2. Clean up any duplicate records for the same work_unit_type
        self.env.cr.execute("""
            DELETE FROM pbms_planning_config
            WHERE id IN (
                SELECT p1.id
                FROM pbms_planning_config p1
                JOIN pbms_planning_config p2
                  ON p1.config_type = 'work_unit_type'
                 AND p2.config_type = 'work_unit_type'
                 AND p1.work_unit_type = p2.work_unit_type
                 AND p1.id < p2.id
            );
        """)
        # 3. Clean up any duplicate records for the same org_unit_id
        self.env.cr.execute("""
            DELETE FROM pbms_planning_config
            WHERE id IN (
                SELECT p1.id
                FROM pbms_planning_config p1
                JOIN pbms_planning_config p2
                  ON p1.config_type = 'operating_unit'
                 AND p2.config_type = 'operating_unit'
                 AND p1.org_unit_id = p2.org_unit_id
                 AND p1.id < p2.id
            );
        """)
        # 4. Ensure customer base measurement type defaults to integer
        self.env.cr.execute("""
            UPDATE pbms_planning_config
            SET customer_base_measurement_type = 'integer'
            WHERE customer_base_measurement_type IS NULL OR customer_base_measurement_type = 'monetary';
        """)

    @api.model_create_multi
    def create(self, vals_list):
        """Auto-populate default dropdown selections and reuse existing config if already present."""
        created_records = self.browse()
        for vals in vals_list:
            config_type = vals.get("config_type", "work_unit_type")
            work_unit_type = vals.get("work_unit_type")
            org_unit_id = vals.get("org_unit_id")

            existing = False
            if config_type == "work_unit_type" and work_unit_type:
                existing = self.search([
                    ("config_type", "=", "work_unit_type"),
                    ("work_unit_type", "=", work_unit_type),
                ], limit=1)
                if not existing:
                    existing = self.search([
                        ("work_unit_type", "=", work_unit_type),
                        ("org_unit_id", "=", False),
                    ], limit=1)
            elif config_type == "operating_unit" and org_unit_id:
                existing = self.search([
                    ("config_type", "=", "operating_unit"),
                    ("org_unit_id", "=", org_unit_id),
                ], limit=1)

            if existing:
                clean_vals = {k: v for k, v in vals.items() if k != "id"}
                existing.write(clean_vals)
                created_records |= existing
            else:
                if not vals.get("deposit_type_ids"):
                    vals["deposit_type_ids"] = [(6, 0, self._default_deposit_types())]
                if not vals.get("digital_channel_ids"):
                    vals["digital_channel_ids"] = [(6, 0, self._default_digital_channels())]
                if not vals.get("expense_account_ids"):
                    vals["expense_account_ids"] = [(6, 0, self._default_expense_accounts())]
                if not vals.get("fixed_asset_category_ids"):
                    vals["fixed_asset_category_ids"] = [(6, 0, self._default_fa_categories())]
                if not vals.get("justification_category_ids"):
                    vals["justification_category_ids"] = [(6, 0, self._default_justification_categories())]
                if not vals.get("fx_source_type_ids"):
                    vals["fx_source_type_ids"] = [(6, 0, self._default_fx_source_types())]
                new_rec = super(PbmsPlanningConfig, self).create([vals])
                created_records |= new_rec
        return created_records

    @api.model
    def get_config_for_unit(self, org_unit):
        """Retrieve planning configuration for a specific operating unit or fallback to its work unit type."""
        if not org_unit:
            return False
        ou_id = org_unit.id if isinstance(org_unit, models.Model) else org_unit
        ou_rec = self.env["operating.unit"].browse(ou_id) if isinstance(ou_id, int) else org_unit
        if not ou_rec or not ou_rec.exists():
            return False

        # 1. Specific operating unit override
        config = self.search([
            ("config_type", "=", "operating_unit"),
            ("org_unit_id", "=", ou_rec.id),
        ], limit=1)
        if config:
            return config

        # 2. Work unit type default
        if ou_rec.work_unit_type:
            return self.get_config_for_type(ou_rec.work_unit_type)
        return False

    @api.model
    def get_config_for_type(self, work_unit_type):
        """Retrieve or create default planning configuration for a work unit type."""
        if not work_unit_type:
            return False
        config = self.search([
            ("config_type", "=", "work_unit_type"),
            ("work_unit_type", "=", work_unit_type),
        ], limit=1)
        if not config:
            # Check without config_type filter for backward compatibility
            config = self.search([
                ("work_unit_type", "=", work_unit_type),
                ("org_unit_id", "=", False),
            ], limit=1)
        if not config:
            config = self.create({
                "config_type": "work_unit_type",
                "work_unit_type": work_unit_type,
            })
        return config

    @api.model
    def is_category_enabled(self, category, org_unit):
        """Determine if a planning category is eligible for a specific operating unit."""
        if not category:
            return False
        if not org_unit:
            return True
        ou_id = org_unit.id if isinstance(org_unit, models.Model) else org_unit
        ou_rec = self.env["operating.unit"].browse(ou_id) if isinstance(ou_id, int) else org_unit
        if not ou_rec or not ou_rec.exists():
            return True

        # Toggle field name map
        toggle_map = {
            "deposit": "enable_deposit",
            "customer_base": "enable_customer_base",
            "fx": "enable_fx",
            "digital_banking": "enable_digital_banking",
            "general_expense": "enable_expense",
            "expense": "enable_expense",
            "manpower": "enable_manpower",
            "fixed_asset": "enable_fixed_asset",
        }
        toggle_field = toggle_map.get(category, f"enable_{category}")

        # Check if there is an OU specific config
        specific_config = self.search([
            ("config_type", "=", "operating_unit"),
            ("org_unit_id", "=", ou_rec.id),
        ], limit=1)
        if specific_config:
            return bool(getattr(specific_config, toggle_field, True))

        # Check work unit type default config
        if not ou_rec.work_unit_type:
            return True
        type_config = self.get_config_for_type(ou_rec.work_unit_type)
        if not type_config:
            return True

        if not getattr(type_config, toggle_field, True):
            return False

        # Check if this operating unit is explicitly excluded for this category
        cat_key = "expense" if category == "general_expense" else category
        excluded_field = f"{cat_key}_excluded_org_unit_ids"
        if hasattr(type_config, excluded_field):
            excluded_units = getattr(type_config, excluded_field)
            if ou_rec.id in excluded_units.ids:
                return False

        return True

    @api.model
    def get_default_category_for_unit(self, org_unit):
        """Return the first active/enabled category for a given operating unit."""
        if not org_unit:
            return "deposit"
        ou_id = org_unit.id if isinstance(org_unit, models.Model) else org_unit
        ou_rec = self.env["operating.unit"].browse(ou_id) if isinstance(ou_id, int) else org_unit
        for cat, _toggle, _name in CATEGORY_TOGGLE_MAP:
            if self.is_category_enabled(cat, ou_rec):
                return cat
        return "manpower"

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
    def get_user_planning_categories(self, org_unit=False):
        """Return enabled planning categories for the user / operating unit."""
        unit = org_unit
        if not unit:
            user = self.env.user
            if hasattr(user, "default_operating_unit_id") and user.default_operating_unit_id:
                unit = user.default_operating_unit_id
            elif hasattr(user, "assigned_operating_unit_ids") and user.assigned_operating_unit_ids:
                unit = user.assigned_operating_unit_ids[0]
            else:
                unit = self.env["operating.unit"].search([], limit=1)

        work_unit_type = unit.work_unit_type if unit else self._get_user_work_unit_type()
        config = self.get_config_for_unit(unit) if unit else (self.get_config_for_type(work_unit_type) if work_unit_type else False)

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
            enabled = self.is_category_enabled(category_id, unit) if unit else (getattr(config, toggle) if config else True)
            if enabled:
                measurement_type = getattr(config, f"{category_id}_measurement_type", "monetary") if config else CATEGORY_MEASUREMENT_TYPES.get(category_id, "monetary")
                categories.append({
                    "id": category_id,
                    "name": name,
                    "icon": icons.get(category_id, "fa-file"),
                    "action": "action_pbms_planning_category",
                    "measurement_type": measurement_type,
                })
        return {
            "work_unit_type": work_unit_type,
            "unit_name": unit.display_name if unit else "",
            "categories": categories,
        }

    @api.model
    def get_category_dropdown_options(self, category, work_unit_type=False, org_unit=False):
        """Return the available dropdown options for a given planning category."""
        config = False
        if org_unit:
            config = self.get_config_for_unit(org_unit)
        elif work_unit_type:
            config = self.get_config_for_type(work_unit_type)
        else:
            wut = self._get_user_work_unit_type()
            config = self.get_config_for_type(wut) if wut else False

        options = {}
        if category in ("deposit", "customer_base"):
            options["deposit_types"] = config.deposit_type_ids if config and config.deposit_type_ids else self.env["pbms.deposit.type"].search([("active", "=", True)])
        elif category == "digital_banking":
            options["channels"] = config.digital_channel_ids if config and config.digital_channel_ids else self.env["pbms.digital.channel"].search([("active", "=", True)])
        elif category in ("general_expense", "expense"):
            options["expense_accounts"] = config.expense_account_ids if config and config.expense_account_ids else self.env["pbms.expense.account"].search([("active", "=", True)])
        elif category == "fixed_asset":
            options["fa_categories"] = config.fixed_asset_category_ids if config and config.fixed_asset_category_ids else self.env["pbms.fixed.asset.category"].search([("active", "=", True)])
        elif category == "manpower":
            options["justification_categories"] = config.justification_category_ids if config and config.justification_category_ids else self.env["pbms.justification.category"].search([("active", "=", True)])
            options["position_types"] = config.position_type_ids if config and config.position_type_ids else self.env["pbms.position.type"].search([("active", "=", True)])
        elif category == "fx":
            options["fx_sources"] = config.fx_source_type_ids if config and config.fx_source_type_ids else self.env["pbms.fx.source.type"].search([("active", "=", True)])
        return options

    @api.model
    def get_measurement_type(self, category, work_unit_type=False, org_unit=False):
        """Return the measurement type for a given planning category."""
        config = False
        if org_unit:
            config = self.get_config_for_unit(org_unit)
        elif work_unit_type:
            config = self.get_config_for_type(work_unit_type)
        else:
            wut = self._get_user_work_unit_type()
            config = self.get_config_for_type(wut) if wut else False
        cat_key = "expense" if category == "general_expense" else category
        if config and hasattr(config, f"{cat_key}_measurement_type"):
            return getattr(config, f"{cat_key}_measurement_type") or CATEGORY_MEASUREMENT_TYPES.get(category, "monetary")
        return CATEGORY_MEASUREMENT_TYPES.get(category, "monetary")

    @api.model
    def get_category_currency(self, category, work_unit_type=False, org_unit=False):
        """Return the configured planning currency for a given category (e.g. USD/EUR for FX, ETB for others)."""
        config = False
        if org_unit:
            config = self.get_config_for_unit(org_unit)
        elif work_unit_type:
            config = self.get_config_for_type(work_unit_type)
        else:
            wut = self._get_user_work_unit_type()
            config = self.get_config_for_type(wut) if wut else False

        if category == "fx":
            if config and config.fx_currency_id:
                return config.fx_currency_id
            usd = self.env["res.currency"].search([("name", "=", "USD")], limit=1)
            if usd:
                return usd
        elif category == "deposit":
            if config and config.deposit_currency_id:
                return config.deposit_currency_id
        elif category in ("general_expense", "expense"):
            if config and config.expense_currency_id:
                return config.expense_currency_id
        return (config.currency_id if config and config.currency_id else self.env.company.currency_id)

    @api.model
    def get_allowed_fx_currencies(self, work_unit_type=False, org_unit=False):
        """Return allowed foreign currencies for FX mobilization planning."""
        config = False
        if org_unit:
            config = self.get_config_for_unit(org_unit)
        elif work_unit_type:
            config = self.get_config_for_type(work_unit_type)
        else:
            wut = self._get_user_work_unit_type()
            config = self.get_config_for_type(wut) if wut else False

        if config and config.fx_allowed_currency_ids:
            return config.fx_allowed_currency_ids
        fx_currs = self.env["res.currency"].search([
            ("name", "in", ["USD", "EUR", "GBP", "AED", "SAR", "CHF", "CAD", "JPY", "CNY"]),
        ])
        return fx_currs if fx_currs else self.env["res.currency"].search([("active", "=", True)])


class PbmsPlanningWorkspace(models.Model):
    """Tabbed Planning Workspace.

    Provides a unified notebook screen for the user's operating unit / cycle.
    Each tab corresponds to one planning category and embeds the editable plan
    lines of the single ``pbms.planning.category`` model. Tabs are shown /
    hidden based on the Planning Configuration for the selected operating unit.
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
            if rec.org_unit_id:
                for cat, toggle, _name in CATEGORY_TOGGLE_MAP:
                    rec[toggle] = Config.is_category_enabled(cat, rec.org_unit_id)
            else:
                for _cat, toggle, _name in CATEGORY_TOGGLE_MAP:
                    rec[toggle] = True

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