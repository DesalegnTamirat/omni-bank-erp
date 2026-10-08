import logging
from odoo import fields, models, tools
try:
    from odoo.addons.mail.tools.discuss import Store
except ImportError:
    Store = None

_logger = logging.getLogger(__name__)

# Branch / Head Office submitter may edit their own plan only in these states.
PBMS_BRANCH_EDITABLE_STATES = frozenset({"draft", "returned", "info_requested"})

# District reviewer may act on child-unit plans only when submitted/pending district review:
PBMS_DISTRICT_REVIEW_STATES = frozenset({
    "submitted", "info_requested",
})

# Head Office functional reviewer may act on district-endorsed, direct HO unit plans, or returned HO plans:
PBMS_HO_REVIEW_STATES = frozenset({
    "draft", "returned", "info_requested", "submitted", "district_approved", "district_endorsed", "ho_endorse",
})

# SPPMD Administrator / Final Approver review stages:
PBMS_SPPMD_REVIEW_STATES = frozenset({
    "ho_reviewed", "district_approved", "district_endorsed", "submitted", "info_requested",
})

# Manpower specific stages
PBMS_COMMITTEE_REVIEW_STATES = frozenset({"committee_review"})
PBMS_HR_FULFILLMENT_STATES = frozenset({"hr_fulfillment"})
PBMS_CEO_REVIEW_STATES = frozenset({"ceo_approval", "board_ceo_approval"})
PBMS_CHIEF_REVIEW_STATES = frozenset({"chief_review"})
PBMS_PEOPLE_SOLUTIONS_STATES = frozenset({"people_solutions_review"})
PBMS_CPCO_REVIEW_STATES = frozenset({"cpco_review"})

# Workflow-only fields reviewers and system may update without full content edit rights.
PBMS_WORKFLOW_ONLY_FIELDS = frozenset({
    "state", "submitted_by", "submitted_date",
    "district_reviewer_id", "district_review_date", "district_comment",
    "chief_approver_id", "chief_approval_date", "chief_comment",
    "people_solutions_reviewer_id", "people_solutions_review_date", "people_solutions_comment",
    "cpco_reviewer_id", "cpco_submission_date", "cpco_comment", "cpco_attachment_ids",
    "ho_reviewer_id", "ho_review_date", "ho_comment",
    "committee_approver_id", "committee_approval_date", "committee_comment",
    "ceo_approver_id", "ceo_approval_date", "ceo_comment",
    "ho_endorser_id", "ho_endorse_date", "cpco_endorser_id", "cpco_endorse_date",
    "return_reason", "message_follower_ids", "message_ids",
    "activity_ids", "activity_state", "activity_user_id",
    "activity_type_id", "activity_date_deadline",
    "has_message", "message_main_attachment_id", "message_needaction",
    "message_has_error", "activity_summary", "website_message_ids",
})

# Content fields that represent budget/plan financial data, targets, or line items
PBMS_MONTH_FIELDS = tuple(f"m{i:02d}" for i in range(1, 13))
PBMS_CONTENT_FIELDS = frozenset({
    "line_ids", "deposit_line_ids", "customer_base_line_ids", "fx_line_ids",
    "digital_banking_line_ids", "expense_line_ids", "manpower_line_ids", "fixed_asset_line_ids",
    "loan_disbursement_line_ids", "loan_outstanding_line_ids",
    *PBMS_MONTH_FIELDS,
    "deposit_type_id", "base_type", "fx_source_type", "channel_id", "expense_account_id",
    "loan_product_id", "loan_flow_type",
    "justification_category_id", "other_justification", "business_justification",
    "fulfillment_promotion", "fulfillment_transfer", "fulfillment_lateral", "fulfillment_external",
    "is_office_rent", "cycle_id", "org_unit_id", "category",
})


class ResUsers(models.Model):
    _inherit = "res.users"

    @tools.ormcache("self.id")
    def _pbms_operating_unit_ids(self):
        self.ensure_one()
        user = self.sudo()
        # Branch & Head Office planner users: bound strictly to their assigned operating unit(s)
        if user._pbms_is_branch_user() and not (
            user._pbms_is_district_reviewer()
            or user._pbms_is_ho_reviewer()
            or user._pbms_is_sppmd_admin()
            or user._pbms_is_sppmd_approver()
            or user.has_group("base.group_system")
        ):
            unit_ids = []
            if hasattr(user, "assigned_operating_unit_ids") and user.assigned_operating_unit_ids:
                unit_ids.extend(user.assigned_operating_unit_ids.ids)
            elif hasattr(user, "operating_unit_ids") and user.operating_unit_ids:
                unit_ids.extend(user.operating_unit_ids.ids)
            if hasattr(user, "default_operating_unit_id") and user.default_operating_unit_id and user.default_operating_unit_id.id not in unit_ids:
                unit_ids.insert(0, user.default_operating_unit_id.id)
            if unit_ids:
                return unit_ids
            return []

        unit_ids = set()
        if hasattr(user, "operating_unit_ids") and user.operating_unit_ids:
            unit_ids.update(user.operating_unit_ids.ids)
        if hasattr(user, "assigned_operating_unit_ids") and user.assigned_operating_unit_ids:
            unit_ids.update(user.assigned_operating_unit_ids.ids)
        if hasattr(user, "default_operating_unit_id") and user.default_operating_unit_id:
            unit_ids.add(user.default_operating_unit_id.id)
        if hasattr(user, "employee_id") and user.employee_id:
            emp = user.employee_id.sudo()
            if hasattr(emp, "operating_unit_id") and emp.operating_unit_id:
                unit_ids.add(emp.operating_unit_id.id)
            if hasattr(emp, "default_operating_unit_id") and emp.default_operating_unit_id:
                unit_ids.add(emp.default_operating_unit_id.id)
            if hasattr(emp, "operating_unit_ids") and emp.operating_unit_ids:
                unit_ids.update(emp.operating_unit_ids.ids)
            if hasattr(emp, "department_id") and emp.department_id and hasattr(emp.department_id, "operating_unit_id") and emp.department_id.operating_unit_id:
                unit_ids.add(emp.department_id.operating_unit_id.id)
        return list(unit_ids)

    @tools.ormcache("self.id")
    def _pbms_child_operating_unit_ids(self):
        """Return all operating unit IDs that are children/subordinates of this user.
        For Respective Chief, child units are determined strictly BY MANAGER (via hr.employee
        reporting hierarchy and operating.unit.manager_id), NOT by operating.unit.parent_unit.
        For other roles, parent_unit hierarchy downward is preserved."""
        self.ensure_one()
        user = self.sudo()

        emp = user.employee_id or (user.employee_ids and user.employee_ids[0])
        if not emp:
            emp = self.env["hr.employee"].sudo().search([("user_id", "=", user.id)], limit=1)
        if not emp and user.default_operating_unit_id and user.default_operating_unit_id.manager_id:
            emp = user.default_operating_unit_id.manager_id
        if not emp:
            for ou in (user.assigned_operating_unit_ids or user.operating_unit_ids):
                if ou.manager_id:
                    emp = ou.manager_id
                    break

        has_subordinates = bool(emp and self.env["hr.employee"].sudo().search([("parent_id", "=", emp.id)], limit=1))

        if user.has_group("bunna_pbms.group_pbms_respective_chief") or user._pbms_is_respective_chief() or has_subordinates:
            if not emp:
                return []

            # 2. Find immediate direct subordinate employees in the management hierarchy
            subordinates = self.env["hr.employee"].sudo().search([
                ("parent_id", "=", emp.id),
            ])
            if not subordinates:
                # Fallback: check operating units with parent_unit managed by this chief
                ou_by_parent = self.env["operating.unit"].sudo().search([
                    ("parent_unit.manager_id", "=", emp.id)
                ])
                if ou_by_parent:
                    chief_emp_ids = (user.employee_id | user.employee_ids).ids
                    if emp.id not in chief_emp_ids:
                        chief_emp_ids.append(emp.id)
                    own_managed_units = self.env["operating.unit"].sudo().search([
                        ("manager_id", "in", chief_emp_ids)
                    ])
                    return list(set(ou_by_parent.ids) - set(own_managed_units.ids))
                return []

            child_units = set()
            # 3. Operating units where manager_id is one of the direct subordinates
            ou_by_mgr = self.env["operating.unit"].sudo().search([
                ("manager_id", "in", subordinates.ids)
            ])
            child_units.update(ou_by_mgr.ids)

            # 4. Operating units assigned to direct subordinate employees or their user accounts
            for sub in subordinates:
                if hasattr(sub, "operating_unit_id") and sub.operating_unit_id:
                    child_units.add(sub.operating_unit_id.id)
                if hasattr(sub, "default_operating_unit_id") and sub.default_operating_unit_id:
                    child_units.add(sub.default_operating_unit_id.id)
                if hasattr(sub, "operating_unit_ids") and sub.operating_unit_ids:
                    child_units.update(sub.operating_unit_ids.ids)
                if sub.user_id:
                    u = sub.user_id
                    if hasattr(u, "default_operating_unit_id") and u.default_operating_unit_id:
                        child_units.add(u.default_operating_unit_id.id)
                    if hasattr(u, "operating_unit_ids") and u.operating_unit_ids:
                        child_units.update(u.operating_unit_ids.ids)
                    if hasattr(u, "assigned_operating_unit_ids") and u.assigned_operating_unit_ids:
                        child_units.update(u.assigned_operating_unit_ids.ids)
                if hasattr(sub, "department_id") and sub.department_id:
                    dept = sub.department_id
                    if hasattr(dept, "operating_unit_id") and dept.operating_unit_id:
                        child_units.add(dept.operating_unit_id.id)
                    if hasattr(dept, "operating_unit_ids") and dept.operating_unit_ids:
                        child_units.update(dept.operating_unit_ids.ids)

            # 5. Operating units where parent_unit manager is the chief
            ou_by_parent = self.env["operating.unit"].sudo().search([
                ("parent_unit.manager_id", "=", emp.id)
            ])
            child_units.update(ou_by_parent.ids)

            # Exclude units where the chief themselves is the manager
            chief_emp_ids = (user.employee_id | user.employee_ids).ids
            if emp.id not in chief_emp_ids:
                chief_emp_ids.append(emp.id)
            own_managed_units = self.env["operating.unit"].sudo().search([
                ("manager_id", "in", chief_emp_ids)
            ])
            child_units -= set(own_managed_units.ids)

            return list(child_units)

        # For other roles: preserve parent_unit hierarchy traversal downward
        user_units = set(self._pbms_operating_unit_ids())
        if not user_units:
            return []

        all_descendants = set()
        current_level = set(user_units)
        while current_level:
            children = self.env["operating.unit"].sudo().search([
                ("parent_unit", "in", list(current_level)),
                ("id", "not in", list(all_descendants | user_units)),
            ])
            if not children:
                break
            child_ids = set(children.ids)
            all_descendants.update(child_ids)
            current_level = child_ids
        return list(all_descendants)

    @tools.ormcache("self.id")
    def _pbms_chief_accessible_unit_ids(self):
        """Return all operating units accessible to this user as a chief:
        their own assigned operating units plus all child/descendant units."""
        self.ensure_one()
        own_units = set(self._pbms_operating_unit_ids())
        child_units = set(self._pbms_child_operating_unit_ids())
        return list(own_units | child_units)

    @tools.ormcache("self.id")
    def _pbms_chief_scope_unit_ids(self):
        """Return all operating unit IDs under this user's scope as a Chief:
        - directly assigned operating units
        - all descendant operating units (branches, sub-branches under districts)
        - units whose manager is managed by this user in employee hierarchy
        - units whose parent unit manager is managed by this user
        """
        self.ensure_one()
        accessible = set(self._pbms_chief_accessible_unit_ids())
        emp = self.employee_id or (self.employee_ids and self.employee_ids[0])
        if not emp:
            emp = self.env["hr.employee"].sudo().search([("user_id", "=", self.id)], limit=1)
        if emp:
            sub_emp_ids = self.env["hr.employee"].sudo().search([("parent_id", "=", emp.id)]).ids
            if sub_emp_ids:
                ou_mgrs = self.env["operating.unit"].sudo().search([
                    "|", ("manager_id", "in", sub_emp_ids),
                    ("parent_unit.manager_id", "in", sub_emp_ids)
                ]).ids
                accessible.update(ou_mgrs)
        return list(accessible)

    @tools.ormcache("self.id")
    def _pbms_chief_subordinate_user_ids(self):
        """Return res.users IDs of employees directly managed by this user."""
        self.ensure_one()
        emp = self.employee_id or (self.employee_ids and self.employee_ids[0])
        if not emp:
            emp = self.env["hr.employee"].sudo().search([("user_id", "=", self.id)], limit=1)
        if emp:
            subs = self.env["hr.employee"].sudo().search([("parent_id", "=", emp.id)])
            return list(set(subs.mapped("user_id").ids) | {self.id})
        return [self.id]

    def _pbms_is_manager(self):
        if not self:
            return False
        return (
            self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        )

    def _pbms_is_sppmd_admin(self):
        if not self:
            return False
        return (
            self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        )

    def _pbms_is_sppmd_approver(self):
        if not self:
            return False
        return (
            self.has_group("bunna_pbms.group_pbms_approver")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        )

    def _pbms_is_ho_reviewer(self):
        if not self:
            return False
        return (
            self.has_group("bunna_pbms.group_pbms_ho_reviewer")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        )

    def _pbms_is_district_reviewer(self):
        if not self:
            return False
        return (
            self.has_group("bunna_pbms.group_pbms_district_reviewer")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        )

    def _pbms_is_branch_user(self):
        if not self:
            return False
        return (
            self.has_group("bunna_pbms.group_pbms_branch_user")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        )

    def _pbms_is_budget_hiring_committee(self):
        if not self:
            return False
        return (
            self.has_group("bunna_pbms.group_pbms_budget_hiring_committee")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        )

    def _pbms_is_ceo(self):
        if not self:
            return False
        if (
            self.has_group("bunna_pbms.group_pbms_ceo")
            or self.has_group("bunna_pbms.group_pbms_approver")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        ):
            return True
        ConfigModel = self.env.get("pbms.planning.config")
        if ConfigModel is not None:
            cfg = ConfigModel.sudo().search([("ceo_user_id", "=", self.id)], limit=1)
            if cfg:
                return True
        return False

    def _pbms_is_respective_chief(self):
        if not self:
            return False
        return (
            self.has_group("bunna_pbms.group_pbms_respective_chief")
            or self.has_group("bunna_pbms.group_pbms_ceo")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        )

    def _pbms_is_people_solutions(self):
        if not self:
            return False
        return (
            self.has_group("bunna_pbms.group_pbms_people_solutions")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        )

    def _pbms_is_cpco(self):
        if not self:
            return False
        return (
            self.has_group("bunna_pbms.group_pbms_cpco")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        )

    def _pbms_can_view_sourcing(self):
        """Sourcing & fulfillment (Promotion / Transfer / Lateral / External ...)
        is visible to People Solutions Directorate, CPCO, Budget Hiring Committee, CEO,
        People Operations/Management Directorate, HO Reviewer (during endorsement into CPCO),
        and SPPMD Admin."""
        if not self:
            return False
        if (
            self.has_group("bunna_pbms.group_pbms_people_solutions")
            or self.has_group("bunna_pbms.group_pbms_cpco")
            or self.has_group("bunna_pbms.group_pbms_budget_hiring_committee")
            or self.has_group("bunna_pbms.group_pbms_ceo")
            or self.has_group("bunna_pbms.group_pbms_people_operations")
            or self.has_group("bunna_pbms.group_pbms_ho_reviewer")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        ):
            return True
        ConfigModel = self.env.get("pbms.planning.config")
        if ConfigModel is not None:
            return bool(ConfigModel.sudo().search([("ceo_user_id", "=", self.id)], limit=1))
        return False

    def _pbms_is_people_operations(self):
        if not self:
            return False
        return (
            self.has_group("bunna_pbms.group_pbms_people_operations")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        )

    def _pbms_allowed_categories(self):
        """Return the list of planning categories the user is authorized to view / action."""
        self.ensure_one()
        all_cats = [
            "deposit", "customer_base", "fx", "digital_banking", "general_expense", "manpower", "fixed_asset",
            "loan_disbursement_collection", "loan_outstanding",
            "credit_portfolio", "initiative_budget",
        ]
        # Administrator, SPPMD Approver, System Admin, or CEO: Bank-wide access to all categories
        if (
            self._pbms_is_sppmd_admin()
            or self._pbms_is_sppmd_approver()
            or self.has_group("base.group_system")
            or self.id == 1
            or self._pbms_is_ceo()
            or self.has_group("bunna_pbms.group_pbms_ceo")
        ):
            return all_cats

        is_solutions = self.has_group("bunna_pbms.group_pbms_people_solutions")
        is_cpco = self.has_group("bunna_pbms.group_pbms_cpco")
        is_operations = self.has_group("bunna_pbms.group_pbms_people_operations")
        is_bhc = self._pbms_is_budget_hiring_committee() or self.has_group("bunna_pbms.group_pbms_budget_hiring_committee")
        is_chief = self._pbms_is_respective_chief() or self.has_group("bunna_pbms.group_pbms_respective_chief")
        is_ho = self._pbms_is_ho_reviewer() or self.has_group("bunna_pbms.group_pbms_ho_reviewer")
        is_district = self._pbms_is_district_reviewer() or self.has_group("bunna_pbms.group_pbms_district_reviewer")

        # Pure workforce review roles
        if (is_solutions or is_cpco or is_operations) and not (is_chief or is_ho or is_bhc or is_district):
            return ["manpower"]

        # Budget Hiring Committee (Manpower, Fixed Asset, Initiative Budget)
        if is_bhc and not (is_chief or is_ho or is_district):
            return ["manpower", "fixed_asset", "initiative_budget"]

        # Respective Chiefs (who are not HO reviewers or admins)
        if is_chief and not (is_ho or is_district):
            return [
                "manpower", "general_expense", "fixed_asset",
                "credit_portfolio", "initiative_budget",
                "loan_disbursement_collection", "loan_outstanding",
            ]

        # Head Office Functional Reviewer
        if is_ho:
            ho_cats = set()
            Config = self.env.get("pbms.planning.config")
            if Config is not None:
                field_map = {
                    "deposit": "deposit_reviewer_user_ids",
                    "customer_base": "customer_base_reviewer_user_ids",
                    "fx": "fx_reviewer_user_ids",
                    "digital_banking": "digital_reviewer_user_ids",
                    "general_expense": "expense_reviewer_user_ids",
                    "manpower": "manpower_reviewer_user_ids",
                    "fixed_asset": "fixed_asset_reviewer_user_ids",
                }
                for cat, fname in field_map.items():
                    if Config.sudo().search([(fname, "in", [self.id])], limit=1):
                        ho_cats.add(cat)

            # Department / Operating Unit keyword matching (matches workflow routing)
            dept_name = ((self.employee_id and self.employee_id.department_id and self.employee_id.department_id.name) or "").lower()
            ou_names = " ".join((ou.name or "").lower() for ou in (self.operating_unit_ids | self.assigned_operating_unit_ids))
            all_text = f"{dept_name} {ou_names}"
            if any(w in all_text for w in ("retail", "operation")):
                ho_cats.update(["deposit", "customer_base"])
            if any(w in all_text for w in ("finance", "account", "budget", "cost")):
                ho_cats.add("general_expense")
            if any(w in all_text for w in ("property", "procurement", "facility", "asset")):
                ho_cats.add("fixed_asset")
            if any(w in all_text for w in ("hr", "human resource", "talent", "people")):
                ho_cats.add("manpower")
            if any(w in all_text for w in ("international", "trade", "treasury", "forex")):
                ho_cats.add("fx")
            if any(w in all_text for w in ("digital", "e-banking", "card", "electronic")):
                ho_cats.add("digital_banking")
            if any(w in all_text for w in ("credit", "loan", "financing")):
                ho_cats.update(["credit_portfolio", "loan_disbursement_collection", "loan_outstanding"])

            # Also include categories enabled for their own unit(s)
            user_ous = self.env["operating.unit"].browse(self._pbms_operating_unit_ids())
            if Config is not None and user_ous:
                for ou in user_ous:
                    for cat in all_cats:
                        if Config.is_category_enabled(cat, ou):
                            ho_cats.add(cat)

            if ho_cats:
                return [c for c in all_cats if c in ho_cats]
            return all_cats

        # District Reviewer: categories enabled in their district office or child branch units
        if is_district:
            ou_ids = set(self._pbms_operating_unit_ids()) | set(self._pbms_child_operating_unit_ids())
            dist_ous = self.env["operating.unit"].browse(ou_ids)
            Config = self.env.get("pbms.planning.config")
            if Config is not None and dist_ous:
                enabled_cats = [cat for cat in all_cats if any(Config.is_category_enabled(cat, ou) for ou in dist_ous)]
                if enabled_cats:
                    return [c for c in all_cats if c in enabled_cats]
            return all_cats

        # Branch Users & Head Office Planner Users: categories enabled for their assigned operating units
        user_ous = self.env["operating.unit"].browse(self._pbms_operating_unit_ids())
        Config = self.env.get("pbms.planning.config")
        if Config is not None and user_ous:
            enabled_cats = [cat for cat in all_cats if any(Config.is_category_enabled(cat, ou) for ou in user_ous)]
            if enabled_cats:
                return [c for c in all_cats if c in enabled_cats]

        return all_cats

    def _pbms_enabled_category_domain(self, category):
        """Return a security domain restricting access to records of `category`
        only for operating units where this category is currently enabled in planning configuration.
        If disabled everywhere or for this user, returns domain preventing access [(0, '=', 1)].
        """
        self.ensure_one()
        Config = self.env.get("pbms.planning.config")
        if Config is None:
            return [(1, "=", 1)]

        # If bank-wide review role (Admin, BHC, CEO, HO Reviewer, SPPMD Approver), check if category is enabled bank-wide
        if (
            self._pbms_is_sppmd_admin()
            or self.has_group("base.group_system")
            or self.id == 1
            or self._pbms_is_budget_hiring_committee()
            or self.has_group("bunna_pbms.group_pbms_budget_hiring_committee")
            or self._pbms_is_ceo()
            or self.has_group("bunna_pbms.group_pbms_ceo")
            or self._pbms_is_ho_reviewer()
            or self.has_group("bunna_pbms.group_pbms_ho_reviewer")
            or self.has_group("bunna_pbms.group_pbms_approver")
        ):
            disabled_ous = Config.sudo().get_disabled_unit_ids_for_category(category)
            all_ous = self.env["operating.unit"].sudo().search([])
            if all_ous and len(disabled_ous) >= len(all_ous):
                return [("id", "=", False)]
            if disabled_ous:
                return [("org_unit_id", "not in", disabled_ous)]
            return [(1, "=", 1)]

        user_ou_ids = set(self._pbms_operating_unit_ids()) | set(self._pbms_child_operating_unit_ids())
        enabled_ou_ids = [
            ou_id for ou_id in user_ou_ids
            if Config.is_category_enabled(category, ou_id)
        ]
        if not enabled_ou_ids:
            return [("id", "=", False)]
        return [("org_unit_id", "in", enabled_ou_ids)]


def send_pbms_inbox_notification(env, doc, recipients, subject, body):
    """Send direct in-app inbox notification to specific users so it appears in the
    Discuss [Notifications] tab (chat bubble) and NOT in scheduled activities (clock).
    Each recipient sees only their own notification.
    """
    if not recipients:
        return
    MailMessage = env["mail.message"].sudo()
    MailNotification = env["mail.notification"].sudo()
    note_subtype = env.ref("mail.mt_note", raise_if_not_found=False)
    subtype_id = note_subtype.id if note_subtype else False

    # Normalize to unique (partner, user) pairs
    seen_partner_ids = set()
    pairs = []
    for item in recipients:
        if not item:
            continue
        if item._name == "res.users":
            for u in item:
                if u.partner_id and u.partner_id.id not in seen_partner_ids:
                    seen_partner_ids.add(u.partner_id.id)
                    pairs.append((u.partner_id, u))
        elif item._name == "res.partner":
            for p in item:
                if p.id not in seen_partner_ids:
                    seen_partner_ids.add(p.id)
                    u = p.user_ids[:1] if p.user_ids else False
                    pairs.append((p, u))

    if not seen_partner_ids:
        return

    doc_model = doc._name if doc and hasattr(doc, "_name") else False
    doc_res_id = doc.id if doc and hasattr(doc, "id") and len(doc) == 1 else False
    author = env.user.partner_id if env.user and env.user.partner_id else env.ref("base.partner_root", raise_if_not_found=False)
    author_id = author.id if author else list(seen_partner_ids)[0]

    # Ultra-fast batch creation: single mail.message for all recipients
    msg = MailMessage.create({
        "subject": subject,
        "body": body,
        "model": doc_model,
        "res_id": doc_res_id,
        "message_type": "user_notification",
        "subtype_id": subtype_id,
        "author_id": author_id,
        "partner_ids": [(6, 0, list(seen_partner_ids))],
        "is_internal": True,
    })

    # Batch insert all mail.notification records in a single database operation
    notif_vals = [
        {
            "author_id": author_id,
            "mail_message_id": msg.id,
            "notification_status": "sent",
            "notification_type": "inbox",
            "res_partner_id": pid,
            "is_read": False,
        }
        for pid in seen_partner_ids
    ]
    MailNotification.create(notif_vals)

    # Batch web bus notifications to online users
    bus_notifications = []
    for partner, user in pairs:
        if user and Store:
            try:
                store = Store(bus_channel=user).add(
                    msg.with_user(user).with_context(allowed_company_ids=[]),
                    add_followers=False,
                )
                bus_notifications.append((
                    user,
                    "mail.message/inbox",
                    {
                        "message_id": msg.id,
                        "store_data": store.get_result(),
                    },
                ))
            except Exception as e:
                _logger.debug("Bus store generation failed for user %s: %s", user.id, e)

    if bus_notifications and "bus.bus" in env:
        try:
            env["bus.bus"]._sendmany(bus_notifications)
        except Exception as e:
            _logger.debug("Bus _sendmany failed: %s", e)


class IrUiMenu(models.Model):
    _inherit = "ir.ui.menu"

    def _filter_visible_menus(self):
        visible = super()._filter_visible_menus()
        user = self.env.user
        # Admins, SPPMD approvers, and SPPMD managers see all review menus
        if user._pbms_is_sppmd_admin() or user._pbms_is_sppmd_approver() or self.env.is_admin() or self.env.su:
            return visible

        # District Reviewers see all branch category review menus
        is_district = bool(user._pbms_is_district_reviewer())

        has_workforce_role = bool(
            user.has_group("bunna_pbms.group_pbms_people_solutions")
            or user.has_group("bunna_pbms.group_pbms_cpco")
            or user.has_group("bunna_pbms.group_pbms_people_operations")
            or user.has_group("bunna_pbms.group_pbms_ceo")
        )
        is_chief = bool(user._pbms_is_respective_chief() or user.has_group("bunna_pbms.group_pbms_respective_chief"))
        has_bhc_role = bool(user.has_group("bunna_pbms.group_pbms_budget_hiring_committee"))

        allowed_cats = set(user._pbms_allowed_categories()) if hasattr(user, "_pbms_allowed_categories") else set()
        is_ho = bool(user.has_group("bunna_pbms.group_pbms_ho_reviewer"))

        menu_category_map = {
            "bunna_pbms.menu_pbms_review_retail": {"deposit", "customer_base"},
            "bunna_pbms.menu_pbms_review_workforce": {"manpower"},
            "bunna_pbms.menu_pbms_review_fx": {"fx"},
            "bunna_pbms.menu_pbms_review_digital": {"digital_banking"},
            "bunna_pbms.menu_pbms_review_expense": {"general_expense"},
            "bunna_pbms.menu_pbms_review_fixed_asset": {"fixed_asset"},
            "bunna_pbms.menu_pbms_review_credit_portfolio": {"credit_portfolio"},
            "bunna_pbms.menu_pbms_review_initiative_budget": {"initiative_budget"},
            "bunna_pbms.menu_pbms_review_loan_disbursement": {"loan_disbursement_collection"},
            "bunna_pbms.menu_pbms_review_loan_outstanding": {"loan_outstanding"},
            "bunna_pbms.menu_pbms_consolidation": set(),
        }

        menus_to_hide = self.env["ir.ui.menu"]
        for xmlid, cats in menu_category_map.items():
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            if not menu or menu not in visible:
                continue

            # Bank-wide consolidation is strictly for SPPMD Approver & Admin
            if xmlid == "bunna_pbms.menu_pbms_consolidation":
                menus_to_hide |= menu
                continue

            allowed = False
            # HO Reviewer: must be authorized for that category
            if is_ho and cats and (cats & allowed_cats):
                allowed = True
            elif is_district:
                allowed = True
            elif is_chief and xmlid in (
                "bunna_pbms.menu_pbms_review_workforce",
                "bunna_pbms.menu_pbms_review_expense",
                "bunna_pbms.menu_pbms_review_fixed_asset",
                "bunna_pbms.menu_pbms_review_credit_portfolio",
                "bunna_pbms.menu_pbms_review_initiative_budget",
                "bunna_pbms.menu_pbms_review_loan_disbursement",
                "bunna_pbms.menu_pbms_review_loan_outstanding",
            ):
                allowed = True
            elif has_bhc_role and xmlid in (
                "bunna_pbms.menu_pbms_review_workforce",
                "bunna_pbms.menu_pbms_review_fixed_asset",
                "bunna_pbms.menu_pbms_review_initiative_budget",
            ):
                allowed = True
            elif has_workforce_role and xmlid == "bunna_pbms.menu_pbms_review_workforce":
                allowed = True

            if not allowed:
                menus_to_hide |= menu

        if menus_to_hide:
            visible -= menus_to_hide

        # If parent Review & Consolidation menu has no visible children, hide parent as well
        parent_review = self.env.ref("bunna_pbms.menu_pbms_review", raise_if_not_found=False)
        if parent_review and parent_review in visible:
            review_children = visible.filtered(lambda m: m.parent_id == parent_review)
            if not review_children:
                visible -= parent_review

        return visible


class IrActionsActWindow(models.Model):
    _inherit = "ir.actions.act_window"

    def _get_action_dict(self):
        result = super()._get_action_dict()
        if not result or result.get("res_model") != "pbms.plan.category.line":
            return result

        # Determine active user (support HTTP request or environment user)
        user = False
        try:
            from odoo.http import request
            if request and hasattr(request, "env") and request.env:
                user = request.env.user
        except Exception:
            pass
        if not user:
            user = self.env.user
        if not user or user.has_group("base.group_system"):
            return result

        # Check if user has review, approval, chief, or manager privileges
        has_reviewer_or_admin = bool(
            user.has_group("bunna_pbms.group_pbms_district_reviewer")
            or user.has_group("bunna_pbms.group_pbms_ho_reviewer")
            or user.has_group("bunna_pbms.group_pbms_approver")
            or user.has_group("bunna_pbms.group_pbms_manager")
            or user.has_group("bunna_pbms.group_pbms_respective_chief")
            or user.has_group("bunna_pbms.group_pbms_people_solutions")
            or user.has_group("bunna_pbms.group_pbms_cpco")
            or user.has_group("bunna_pbms.group_pbms_budget_hiring_committee")
            or user.has_group("bunna_pbms.group_pbms_ceo")
            or user.has_group("base.group_system")
        )

        if not has_reviewer_or_admin:
            # Branch / Head Office User privilege only:
            # Remove district grouping so records group directly under Branch / Operating Unit.
            ctx = result.get("context")
            if isinstance(ctx, str) and "group_district" in ctx:
                try:
                    eval_ctx = tools.safe_eval.safe_eval(ctx)
                    if isinstance(eval_ctx, dict) and "search_default_group_district" in eval_ctx:
                        eval_ctx.pop("search_default_group_district", None)
                        if "search_default_group_by_branch" in eval_ctx:
                            eval_ctx["search_default_group_by_branch"] = (
                                2 if "search_default_group_by_line_type" in eval_ctx else 1
                            )
                        result["context"] = repr(eval_ctx)
                except Exception as e:
                    _logger.warning("Failed adjusting action context for branch/HO user: %s", e)
            elif isinstance(ctx, dict) and "search_default_group_district" in ctx:
                new_ctx = dict(ctx)
                new_ctx.pop("search_default_group_district", None)
                if "search_default_group_by_branch" in new_ctx:
                    new_ctx["search_default_group_by_branch"] = (
                        2 if "search_default_group_by_line_type" in new_ctx else 1
                    )
                result["context"] = new_ctx

        return result



