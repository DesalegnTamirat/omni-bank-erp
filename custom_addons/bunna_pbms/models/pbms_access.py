import logging
from odoo import api, fields, models, tools
from odoo.tools import sql
try:
    from odoo.addons.mail.tools.discuss import Store
except ImportError:
    Store = None

_logger = logging.getLogger(__name__)

_TABLE_EXISTS_CACHE = {}


def _safe_table_exists(env, model_name):
    """Safely check if the underlying table for a model exists in PostgreSQL with in-memory caching."""
    db_name = env.cr.dbname if hasattr(env, "cr") and hasattr(env.cr, "dbname") else ""
    cache_key = (db_name, model_name)
    if cache_key in _TABLE_EXISTS_CACHE:
        return _TABLE_EXISTS_CACHE[cache_key]
    try:
        model = env.get(model_name)
        if model is None or not getattr(model, "_table", None):
            return False
        exists = bool(sql.table_exists(env.cr, model._table))
        if exists:
            _TABLE_EXISTS_CACHE[cache_key] = True
        return exists
    except Exception:
        return False


# Branch / Head Office submitter may edit their own plan only in these states.
PBMS_BRANCH_EDITABLE_STATES = frozenset({"draft", "returned", "info_requested"})

# District reviewer may act on child-unit plans only when submitted/pending district review:
PBMS_DISTRICT_REVIEW_STATES = frozenset({
    "submitted", "info_requested",
})

# Head Office functional reviewer may act on district-endorsed, direct HO unit plans, or returned HO plans:
PBMS_HO_REVIEW_STATES = frozenset({
    "draft", "returned", "info_requested", "submitted", "district_approved", "district_endorsed", "ho_endorse", "committee_review",
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

        # 1. Check dynamic privilege assignments for this user first
        if _safe_table_exists(self.env, "pbms.privilege.assignment"):
            try:
                Assignment = self.env["pbms.privilege.assignment"].sudo()
                user_group_ids = user.all_group_ids.ids if hasattr(user, "all_group_ids") else getattr(user, "group_ids", getattr(user, "groups_id", self.env["res.groups"])).ids
                u_domain = ["|", ("user_id", "=", user.id), ("group_id", "in", user_group_ids)]
                if hasattr(user, "employee_id") and user.employee_id and user.employee_id.job_id:
                    u_domain = ["|", ("job_id", "=", user.employee_id.job_id.id)] + u_domain

                # Check for bank-wide 'all' level allow assignment
                all_level_count = Assignment.search_count([
                    ("active", "=", True),
                    ("grant_type", "=", "allow"),
                    ("org_level", "=", "all"),
                ] + u_domain)
                if all_level_count:
                    denied_units = Assignment.search([
                        ("active", "=", True),
                        ("grant_type", "=", "deny"),
                        ("org_unit_id", "!=", False),
                    ] + u_domain).mapped("org_unit_id")
                    all_ous = self.env["operating.unit"].sudo().search([])
                    if denied_units:
                        all_ous -= denied_units
                    return all_ous.ids

                # Specific assignments (HO, District, Branch, or Specific Unit)
                dyn_assigns = Assignment.search([
                    ("active", "=", True),
                    ("grant_type", "=", "allow"),
                ] + u_domain)
                dyn_unit_ids = set()
                for da in dyn_assigns:
                    if da.org_unit_id:
                        dyn_unit_ids.add(da.org_unit_id.id)
                    elif da.org_level in ("head_office", "ho"):
                        ho_ous = self.env["operating.unit"].sudo().search([("work_unit_type", "=", "head_office")])
                        dyn_unit_ids.update(ho_ous.ids)
                    elif da.org_level == "district":
                        dist_ous = self.env["operating.unit"].sudo().search([("work_unit_type", "in", ("district_office", "regional_office"))])
                        dyn_unit_ids.update(dist_ous.ids)
                    elif da.org_level == "branch":
                        br_ous = self.env["operating.unit"].sudo().search([("work_unit_type", "in", ("branch", "sub_branch"))])
                        dyn_unit_ids.update(br_ous.ids)

                deny_assigns = Assignment.search([
                    ("active", "=", True),
                    ("grant_type", "=", "deny"),
                    ("org_unit_id", "!=", False),
                ] + u_domain)
                for da in deny_assigns:
                    dyn_unit_ids.discard(da.org_unit_id.id)

                if dyn_unit_ids:
                    static_units = set()
                    if hasattr(user, "operating_unit_ids") and user.operating_unit_ids:
                        static_units.update(user.operating_unit_ids.ids)
                    if hasattr(user, "default_operating_unit_id") and user.default_operating_unit_id:
                        static_units.add(user.default_operating_unit_id.id)
                    return list(dyn_unit_ids | static_units)
            except Exception as e:
                _logger.warning("Error computing dynamic operating units: %s", e)

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
            if hasattr(user, "operating_unit_ids") and user.operating_unit_ids:
                for ou_id in user.operating_unit_ids.ids:
                    if ou_id not in unit_ids:
                        unit_ids.append(ou_id)
            if hasattr(user, "default_operating_unit_id") and user.default_operating_unit_id and user.default_operating_unit_id.id not in unit_ids:
                unit_ids.insert(0, user.default_operating_unit_id.id)
            if hasattr(user, "employee_id") and user.employee_id:
                emp = user.employee_id.sudo()
                if hasattr(emp, "operating_unit_id") and emp.operating_unit_id and emp.operating_unit_id.id not in unit_ids:
                    unit_ids.append(emp.operating_unit_id.id)
                if hasattr(emp, "default_operating_unit_id") and emp.default_operating_unit_id and emp.default_operating_unit_id.id not in unit_ids:
                    unit_ids.append(emp.default_operating_unit_id.id)
                if hasattr(emp, "operating_unit_ids") and emp.operating_unit_ids:
                    for ou_id in emp.operating_unit_ids.ids:
                        if ou_id not in unit_ids:
                            unit_ids.append(ou_id)
            # Operating unit managers: always include units managed by this user
            managed_ous = self.env["operating.unit"].sudo().search([("manager_id.user_id", "=", user.id)])
            for ou_id in managed_ous.ids:
                if ou_id not in unit_ids:
                    unit_ids.append(ou_id)
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
        managed_ous = self.env["operating.unit"].sudo().search([("manager_id.user_id", "=", user.id)])
        unit_ids.update(managed_ous.ids)
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

        is_pure_chief = (
            user.has_group("bunna_pbms.group_pbms_respective_chief") or user._pbms_is_respective_chief()
        ) and not user.has_group("bunna_pbms.group_pbms_district_reviewer")

        if is_pure_chief:
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

            # 5. Operating units where parent_unit manager is the chief (for district child branches)
            ou_by_parent = self.env["operating.unit"].sudo().search([
                ("parent_unit.manager_id", "=", emp.id),
                ("parent_unit.work_unit_type", "in", ("district_office", "regional_office")),
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

            # For pure Respective Chief (not District Reviewer), return manager-scoped units strictly
            if (user.has_group("bunna_pbms.group_pbms_respective_chief") or user._pbms_is_respective_chief()) and not user.has_group("bunna_pbms.group_pbms_district_reviewer"):
                return list(child_units)
        else:
            child_units = set()

        # For District Reviewers and other roles: traverse parent_unit hierarchy downward
        user_units = set(self._pbms_operating_unit_ids())
        if not user_units:
            return list(child_units)

        all_descendants = set(child_units)
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

        # Head office units can never be child/subordinate units of a district reviewer or non-HO user
        is_ho_user = any(ou.work_unit_type == "head_office" for ou in (user.assigned_operating_unit_ids or user.operating_unit_ids))
        if not is_ho_user and not user._pbms_is_sppmd_admin():
            ho_units = self.env["operating.unit"].sudo().search([("work_unit_type", "=", "head_office")])
            all_descendants -= set(ho_units.ids)

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
        - all operating units directly managed by subordinate managers in employee hierarchy
        - child branch units under subordinate district directors
        """
        self.ensure_one()
        accessible = set(self._pbms_chief_accessible_unit_ids())

        # Check dynamic role or privilege assignments
        if _safe_table_exists(self.env, "pbms.privilege.assignment"):
            try:
                Assignment = self.env["pbms.privilege.assignment"]
                user_group_ids = self.all_group_ids.ids if hasattr(self, "all_group_ids") else getattr(self, "group_ids", getattr(self, "groups_id", self.env["res.groups"])).ids
                u_domain = ["|", ("user_id", "=", self.id), ("group_id", "in", user_group_ids)]
                chief_assigns = Assignment.sudo().search([
                    ("active", "=", True),
                    ("grant_type", "=", "allow"),
                    "|", ("role_id.code", "=", "role_respective_chief"),
                         ("privilege_id.action_type", "=", "chief_approve"),
                ] + u_domain)
                for ca in chief_assigns:
                    if ca.org_level == "all":
                        return self.env["operating.unit"].sudo().search([]).ids
                    elif ca.org_unit_id:
                        accessible.add(ca.org_unit_id.id)
            except Exception:
                pass

        emp = self.employee_id or (self.employee_ids and self.employee_ids[0])
        if not emp:
            emp = self.env["hr.employee"].sudo().search([("user_id", "=", self.id)], limit=1)
        if emp:
            self.env.cr.execute("""
                WITH RECURSIVE subordinates AS (
                    SELECT id, parent_id, ARRAY[id] AS path
                    FROM hr_employee
                    WHERE parent_id = %s
                    UNION ALL
                    SELECT e.id, e.parent_id, s.path || e.id
                    FROM hr_employee e
                    INNER JOIN subordinates s ON s.id = e.parent_id
                    WHERE NOT (e.id = ANY(s.path))
                      AND array_length(s.path, 1) < 50
                )
                SELECT DISTINCT id FROM subordinates;
            """, (emp.id,))
            sub_emp_ids = [row[0] for row in self.env.cr.fetchall()]
            if sub_emp_ids:
                ou_direct = self.env["operating.unit"].sudo().search([("manager_id", "in", sub_emp_ids)])
                ou_parent = self.env["operating.unit"].sudo().search([
                    ("parent_unit.manager_id", "in", sub_emp_ids),
                    ("parent_unit.work_unit_type", "in", ("district_office", "regional_office")),
                    "|", ("manager_id", "=", False), ("manager_id", "in", sub_emp_ids),
                ])
                accessible.update((ou_direct | ou_parent).ids)
        return list(accessible)

    @tools.ormcache("self.id")
    def _pbms_chief_subordinate_user_ids(self):
        """Return res.users IDs of employees managed by this user in management hierarchy.
        Fast recursive CTE across organizational tree with cycle prevention."""
        self.ensure_one()
        emp = self.employee_id or (self.employee_ids and self.employee_ids[0])
        if not emp:
            emp = self.env["hr.employee"].sudo().search([("user_id", "=", self.id)], limit=1)
        if emp:
            self.env.cr.execute("""
                WITH RECURSIVE subordinates AS (
                    SELECT id, parent_id, user_id, ARRAY[id] AS path
                    FROM hr_employee
                    WHERE parent_id = %s
                    UNION ALL
                    SELECT e.id, e.parent_id, e.user_id, s.path || e.id
                    FROM hr_employee e
                    INNER JOIN subordinates s ON s.id = e.parent_id
                    WHERE NOT (e.id = ANY(s.path))
                      AND array_length(s.path, 1) < 50
                )
                SELECT DISTINCT user_id FROM subordinates WHERE user_id IS NOT NULL;
            """, (emp.id,))
            user_ids = {row[0] for row in self.env.cr.fetchall()}
            return list(user_ids | {self.id})
        return [self.id]

    @tools.ormcache("self.id")
    def _pbms_is_config_ceo_cached(self):
        ConfigModel = self.env.get("pbms.planning.config")
        if ConfigModel is None:
            return False
        return bool(ConfigModel.sudo().search([("ceo_user_id", "=", self.id)], limit=1))

    def _pbms_is_config_ceo(self):
        """True when this user is configured as CEO in a planning config.
        Cached: this used to hit the DB on every permission check."""
        self.ensure_one()
        return self._pbms_is_config_ceo_cached()

    def _pbms_clear_access_caches(self):
        """Drop cached access data (called when users / groups / config change)."""
        self.env.registry.clear_cache()

    def write(self, vals):
        res = super().write(vals)
        watched = {
            "group_ids", "groups_id", "all_group_ids", "active", "employee_id", "employee_ids",
            "operating_unit_ids", "assigned_operating_unit_ids", "default_operating_unit_id",
        }
        if watched & set(vals):
            self._pbms_clear_access_caches()
        return res

    @tools.ormcache("self.id", "role_code")
    def _pbms_has_dynamic_role(self, role_code):
        if not self:
            return False
        user_group_ids = self.all_group_ids.ids if hasattr(self, "all_group_ids") else getattr(self, "group_ids", getattr(self, "groups_id", self.env["res.groups"])).ids
        user_emp = self.employee_id.sudo() if self.employee_id else False
        user_job_id = user_emp.job_id.id if user_emp and user_emp.job_id else False

        if _safe_table_exists(self.env, "pbms.privilege.assignment"):
            try:
                Assignment = self.env["pbms.privilege.assignment"]
                domain = [
                    ("active", "=", True),
                    ("role_id.code", "=", role_code),
                    ("grant_type", "=", "allow"),
                ]
                user_domain = ["|", ("user_id", "=", self.id), ("group_id", "in", user_group_ids)]
                if user_job_id:
                    user_domain = ["|", ("job_id", "=", user_job_id)] + user_domain
                if Assignment.sudo().search_count(domain + user_domain):
                    return True
            except Exception:
                pass

        if _safe_table_exists(self.env, "pbms.role.definition"):
            try:
                Role = self.env["pbms.role.definition"]
                if Role.sudo().search_count([
                    ("code", "=", role_code),
                    ("active", "=", True),
                    ("group_ids", "in", user_group_ids),
                ]):
                    return True
            except Exception:
                pass
        return False

    def _pbms_has_dynamic_privilege(self, action_or_privilege, category=False):
        if not self:
            return False
        if self.has_group("base.group_system") or self.id == 1:
            return True

        priv_key = action_or_privilege
        if hasattr(action_or_privilege, "_name") and action_or_privilege._name == "pbms.privilege":
            priv_key = action_or_privilege.code or action_or_privilege.action_type or str(action_or_privilege.id)
        elif isinstance(action_or_privilege, int):
            priv_key = str(action_or_privilege)
        return self._pbms_has_dynamic_privilege_cached(priv_key, category)

    @tools.ormcache("self.id", "priv_key", "category")
    def _pbms_has_dynamic_privilege_cached(self, priv_key, category=False):
        user_group_ids = self.all_group_ids.ids if hasattr(self, "all_group_ids") else getattr(self, "group_ids", getattr(self, "groups_id", self.env["res.groups"])).ids
        user_emp = self.employee_id.sudo() if self.employee_id else False
        user_job_id = user_emp.job_id.id if user_emp and user_emp.job_id else False

        priv_id = False
        action_type = False
        priv_code = False
        if isinstance(priv_key, int) or (isinstance(priv_key, str) and priv_key.isdigit()):
            priv_id = int(priv_key)
        elif isinstance(priv_key, str):
            action_type = priv_key
            priv_code = priv_key

        match_domain = []
        if priv_id:
            match_domain = [
                "|", ("privilege_id", "=", priv_id),
                "|", ("privilege_ids", "in", [priv_id]),
                     ("role_id.privilege_ids", "in", [priv_id]),
            ]
        elif action_type:
            match_domain = [
                "|", ("privilege_id.action_type", "=", action_type),
                "|", ("privilege_id.code", "=", priv_code),
                "|", ("privilege_ids.action_type", "=", action_type),
                "|", ("privilege_ids.code", "=", priv_code),
                "|", ("role_id.privilege_ids.action_type", "=", action_type),
                     ("role_id.privilege_ids.code", "=", priv_code),
            ]

        if match_domain and _safe_table_exists(self.env, "pbms.privilege.assignment"):
            try:
                Assignment = self.env["pbms.privilege.assignment"]
                u_domain = ["|", ("user_id", "=", self.id), ("group_id", "in", user_group_ids)]
                if user_job_id:
                    u_domain = ["|", ("job_id", "=", user_job_id)] + u_domain

                # Explicit deny takes precedence
                deny_domain = [
                    ("active", "=", True),
                    ("grant_type", "=", "deny"),
                ] + match_domain + u_domain
                if Assignment.sudo().search_count(deny_domain):
                    return False

                # Direct allow check
                allow_assigns = Assignment.sudo().search([
                    ("active", "=", True),
                    ("grant_type", "=", "allow"),
                ] + match_domain + u_domain)
                for aa in allow_assigns:
                    if aa.category_ids and category and not any(c.code == category for c in aa.category_ids):
                        continue
                    return True
            except Exception:
                pass

        # Role-based privilege check (roles linked to user's security groups)
        if user_group_ids and _safe_table_exists(self.env, "pbms.role.definition"):
            try:
                Role = self.env["pbms.role.definition"]
                role_priv_domain = [
                    ("active", "=", True),
                    ("group_ids", "in", user_group_ids),
                ]
                if priv_id:
                    role_priv_domain.append(("privilege_ids", "in", [priv_id]))
                elif action_type:
                    role_priv_domain.extend(["|", ("privilege_ids.action_type", "=", action_type), ("privilege_ids.code", "=", priv_code)])

                roles = Role.sudo().search(role_priv_domain)
                for r in roles:
                    if r.category_ids and category and not any(c.code == category for c in r.category_ids):
                        continue
                    return True
            except Exception:
                pass

        return False

    @tools.ormcache("self.id")
    def _pbms_has_access(self):
        """Return True if the user has active access rights in the PBMS system."""
        if not self or not self.active:
            return False
        if self._is_superuser() or self._is_system() or self.has_group("base.group_system"):
            return True
        pbms_group_xmlids = (
            "bunna_pbms.group_pbms_branch_user",
            "bunna_pbms.group_pbms_district_reviewer",
            "bunna_pbms.group_pbms_ho_reviewer",
            "bunna_pbms.group_pbms_approver",
            "bunna_pbms.group_pbms_budget_hiring_committee",
            "bunna_pbms.group_pbms_respective_chief",
            "bunna_pbms.group_pbms_ceo",
            "bunna_pbms.group_pbms_people_solutions",
            "bunna_pbms.group_pbms_cpco",
            "bunna_pbms.group_pbms_people_operations",
            "bunna_pbms.group_pbms_manager",
        )
        for g_xmlid in pbms_group_xmlids:
            if self.has_group(g_xmlid):
                return True
        if _safe_table_exists(self.env, "pbms.privilege.assignment"):
            try:
                user_group_ids = self.all_group_ids.ids if hasattr(self, "all_group_ids") else getattr(self, "group_ids", getattr(self, "groups_id", self.env["res.groups"])).ids
                u_domain = ["|", ("user_id", "=", self.id), ("group_id", "in", user_group_ids)]
                if self.env["pbms.privilege.assignment"].sudo().search_count([
                    ("active", "=", True),
                    ("grant_type", "=", "allow"),
                ] + u_domain):
                    return True
            except Exception:
                pass
        return False

    @tools.ormcache("self.id")
    def _pbms_is_manager(self):
        if not self:
            return False
        return (
            self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
            or self._pbms_has_dynamic_role("role_pbms_manager")
        )

    @tools.ormcache("self.id")
    def _pbms_is_sppmd_admin(self):
        if not self:
            return False
        return (
            self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
            or self._pbms_has_dynamic_role("role_pbms_manager")
        )

    @tools.ormcache("self.id")
    def _pbms_is_sppmd_approver(self):
        if not self:
            return False
        return (
            self.has_group("bunna_pbms.group_pbms_approver")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
            or self._pbms_has_dynamic_role("role_sppmd_approver")
        )

    @tools.ormcache("self.id")
    def _pbms_is_ho_reviewer(self):
        if not self:
            return False
        return (
            self.has_group("bunna_pbms.group_pbms_ho_reviewer")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
            or self._pbms_has_dynamic_role("role_ho_reviewer")
            or self._pbms_has_dynamic_privilege("ho_review")
            or self._pbms_has_dynamic_privilege("ho_approve")
            or self._pbms_has_dynamic_privilege("ho_endorse")
        )

    @tools.ormcache("self.id")
    def _pbms_is_district_reviewer(self):
        if not self:
            return False
        return (
            self.has_group("bunna_pbms.group_pbms_district_reviewer")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
            or self._pbms_has_dynamic_role("role_district_reviewer")
            or self._pbms_has_dynamic_privilege("district_review")
            or self._pbms_has_dynamic_privilege("district_approve")
            or self._pbms_has_dynamic_privilege("district_endorse")
        )

    def _pbms_is_operating_unit_manager(self):
        """Check if user is assigned as manager_id on any operating.unit or has manager group."""
        if not self:
            return False
        user = self.sudo()
        emp_ids = []
        if user.employee_id:
            emp_ids.append(user.employee_id.id)
        if hasattr(user, "employee_ids") and user.employee_ids:
            emp_ids.extend(user.employee_ids.ids)
        if not emp_ids:
            emps = self.env["hr.employee"].sudo().search([("user_id", "=", user.id)])
            emp_ids.extend(emps.ids)
        if emp_ids and self.env["operating.unit"].sudo().search_count([("manager_id", "in", emp_ids)]):
            return True
        if user.has_group("hr_employee_custom.group_manager_operating_unit"):
            return True
        return False

    @tools.ormcache("self.id")
    def _pbms_is_branch_user(self):
        if not self:
            return False
        return (
            self.has_group("bunna_pbms.group_pbms_branch_user")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
            or self._pbms_is_operating_unit_manager()
            or self._pbms_has_dynamic_role("role_branch_planner")
            or self._pbms_has_dynamic_privilege("create")
            or self._pbms_has_dynamic_privilege("submit")
            or self._pbms_has_dynamic_privilege("view")
            or self._pbms_has_dynamic_privilege("edit")
        )

    @api.model
    def _sync_all_ou_managers_branch_group(self):
        """Automatically ensure all operating unit managers have the Branch / Head Office User privilege."""
        branch_group = self.env.ref("bunna_pbms.group_pbms_branch_user", raise_if_not_found=False)
        if not branch_group:
            return
        ous = self.env["operating.unit"].sudo().search([("manager_id.user_id", "!=", False)])
        mgr_users = ous.mapped("manager_id.user_id")
        mgr_group = self.env.ref("hr_employee_custom.group_manager_operating_unit", raise_if_not_found=False)
        if mgr_group:
            mgr_users |= self.sudo().search([("group_ids", "in", [mgr_group.id])])
        for u in mgr_users:
            if branch_group not in u.group_ids:
                u.write({"group_ids": [(4, branch_group.id)]})

    @tools.ormcache("self.id")
    def _pbms_is_budget_hiring_committee(self):
        if not self:
            return False
        return (
            self.has_group("bunna_pbms.group_pbms_budget_hiring_committee")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
            or self._pbms_has_dynamic_role("role_committee")
            or self._pbms_has_dynamic_privilege("committee_approve")
        )

    @tools.ormcache("self.id")
    def _pbms_is_ceo(self):
        if not self:
            return False
        if (
            self.has_group("bunna_pbms.group_pbms_ceo")
            or self.has_group("bunna_pbms.group_pbms_approver")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
            or self._pbms_has_dynamic_role("role_ceo")
            or self._pbms_has_dynamic_privilege("ceo_approve")
        ):
            return True
        return self._pbms_is_config_ceo()

    @tools.ormcache("self.id")
    def _pbms_is_respective_chief(self):
        if not self:
            return False
        return (
            self.has_group("bunna_pbms.group_pbms_respective_chief")
            or self.has_group("bunna_pbms.group_pbms_ceo")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
            or self._pbms_has_dynamic_role("role_respective_chief")
            or self._pbms_has_dynamic_privilege("chief_approve")
        )

    @tools.ormcache("self.id")
    def _pbms_is_people_solutions(self):
        if not self:
            return False
        return (
            self.has_group("bunna_pbms.group_pbms_people_solutions")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
            or self._pbms_has_dynamic_role("role_people_solutions")
            or self._pbms_has_dynamic_privilege("ps_approve")
        )

    @tools.ormcache("self.id")
    def _pbms_is_cpco(self):
        if not self:
            return False
        return (
            self.has_group("bunna_pbms.group_pbms_cpco")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
            or self._pbms_has_dynamic_role("role_cpco")
            or self._pbms_has_dynamic_privilege("cpco_approve")
        )

    @tools.ormcache("self.id")
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
        return self._pbms_is_config_ceo()

    @tools.ormcache("self.id")
    def _pbms_is_people_operations(self):
        if not self:
            return False
        return (
            self.has_group("bunna_pbms.group_pbms_people_operations")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        )

    def _pbms_ho_review_categories(self):
        """Return the list of functional categories this user reviews as Head Office Functional Reviewer."""
        self.ensure_one()
        return list(self._pbms_ho_review_categories_cached())

    @tools.ormcache("self.id")
    def _pbms_ho_review_categories_cached(self):
        return tuple(self._pbms_ho_review_categories_uncached())

    def _pbms_ho_review_categories_uncached(self):
        self.ensure_one()
        all_cats = [
            "deposit", "customer_base", "fx", "digital_banking", "general_expense", "manpower", "fixed_asset",
            "loan_disbursement_collection", "loan_outstanding",
            "credit_portfolio", "initiative_budget",
        ]
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
                "credit_portfolio": "credit_reviewer_user_ids",
                "loan_disbursement_collection": "loan_reviewer_user_ids",
                "loan_outstanding": "loan_reviewer_user_ids",
                "initiative_budget": "initiative_reviewer_user_ids",
            }
            cfg = Config.sudo().search([], limit=1)
            if cfg:
                for cat, fname in field_map.items():
                    if hasattr(cfg, fname) and cfg[fname]:
                        if self.id in cfg[fname].ids:
                            ho_cats.add(cat)

        dept_name = ((self.employee_id and self.employee_id.department_id and self.employee_id.department_id.name) or "").lower()
        ou_names = " ".join((ou.name or "").lower() for ou in (self.operating_unit_ids | self.assigned_operating_unit_ids))
        all_text = f"{dept_name} {ou_names}"
        if any(w in all_text for w in ("retail",)):
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
        if any(w in all_text for w in ("credit", "loan", "financing", "portfolio")):
            ho_cats.update(["credit_portfolio", "loan_disbursement_collection", "loan_outstanding"])
        if any(w in all_text for w in ("initiative", "strategy", "project")):
            ho_cats.add("initiative_budget")

        # If categories like credit, loans, initiative budget have no dedicated HO reviewer
        # assigned in other departments, allow any authorized HO functional reviewer to review them
        ho_group = self.env.ref("bunna_pbms.group_pbms_ho_reviewer", raise_if_not_found=False)
        if ho_group:
            all_ho_users = self.env["res.users"].sudo().search([
                ("group_ids" if hasattr(self, "group_ids") else "groups_id", "in", [ho_group.id])
            ])
            for cat in all_cats:
                if cat in ho_cats:
                    continue
                has_dedicated = False
                for other in (all_ho_users - self):
                    other_text = f"{((other.employee_id and other.employee_id.department_id and other.employee_id.department_id.name) or '').lower()} {' '.join((ou.name or '').lower() for ou in other.operating_unit_ids)}"
                    if cat in ("credit_portfolio", "loan_disbursement_collection", "loan_outstanding") and any(w in other_text for w in ("credit", "loan", "financing", "portfolio")):
                        has_dedicated = True
                        break
                    elif cat == "initiative_budget" and any(w in other_text for w in ("initiative", "strategy", "project")):
                        has_dedicated = True
                        break
                    elif cat == "general_expense" and any(w in other_text for w in ("finance", "account", "budget", "cost")):
                        has_dedicated = True
                        break
                    elif cat == "fixed_asset" and any(w in other_text for w in ("property", "procurement", "facility", "asset")):
                        has_dedicated = True
                        break
                    elif cat == "fx" and any(w in other_text for w in ("international", "trade", "treasury", "forex")):
                        has_dedicated = True
                        break
                    elif cat == "digital_banking" and any(w in other_text for w in ("digital", "e-banking", "card", "electronic")):
                        has_dedicated = True
                        break
                    elif cat in ("deposit", "customer_base") and "retail" in other_text:
                        has_dedicated = True
                        break
                if not has_dedicated:
                    ho_cats.add(cat)

        if ho_cats:
            return [c for c in all_cats if c in ho_cats]
        return all_cats

    def _pbms_allowed_categories(self):
        """Return the list of planning categories the user is authorized to view / action.

        Result is cached per user (it used to run several searches on every call, and it
        is called per record from the permission computes, the dashboard and the menus)."""
        self.ensure_one()
        return list(self._pbms_allowed_categories_cached())

    @tools.ormcache("self.id")
    def _pbms_allowed_categories_cached(self):
        return tuple(self._pbms_allowed_categories_uncached())

    def _pbms_allowed_categories_uncached(self):
        self.ensure_one()
        all_cats = [
            "deposit", "customer_base", "fx", "digital_banking", "general_expense", "manpower", "fixed_asset",
            "loan_disbursement_collection", "loan_outstanding",
            "credit_portfolio", "initiative_budget",
        ]
        if _safe_table_exists(self.env, "pbms.planning.category.definition"):
            try:
                CatDef = self.env["pbms.planning.category.definition"]
                active_defs = CatDef.sudo().search([("active", "=", True)])
                if active_defs:
                    all_cats = list(dict.fromkeys(active_defs.mapped("code") + all_cats))
            except Exception:
                pass
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

        # Pure workforce review roles: manpower for review, plus resource categories for planning their own unit's plans
        if (is_solutions or is_cpco or is_operations) and not (is_chief or is_ho or is_bhc or is_district):
            return ["manpower", "general_expense", "fixed_asset", "credit_portfolio", "initiative_budget"]

        # Budget Hiring Committee (Manpower, Fixed Asset, Initiative Budget)
        if is_bhc and not (is_chief or is_ho or is_district):
            return ["manpower", "fixed_asset", "initiative_budget"]

        # Respective Chiefs (who are not HO reviewers or admins)
        if is_chief and not (is_ho or is_district):
            return [
                "deposit", "customer_base", "fx", "digital_banking",
                "manpower", "general_expense", "fixed_asset",
                "credit_portfolio", "initiative_budget",
                "loan_disbursement_collection", "loan_outstanding",
            ]

        # Head Office Functional Reviewer
        if is_ho:
            ho_cats = set(self._pbms_ho_review_categories())
            # Also include categories where their own unit(s) have active plans
            user_ou_ids = self._pbms_operating_unit_ids()
            if user_ou_ids:
                self.env.cr.execute(
                    "SELECT DISTINCT category FROM pbms_planning_category WHERE org_unit_id IN %s AND active = true",
                    (tuple(user_ou_ids),),
                )
                for (cat,) in self.env.cr.fetchall():
                    if cat:
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
        Cached in memory for maximum performance across ir.rule evaluations.
        """
        self.ensure_one()
        return list(self._pbms_enabled_category_domain_cached(category))

    @tools.ormcache("self.id", "category")
    def _pbms_enabled_category_domain_cached(self, category):
        return tuple(self._pbms_enabled_category_domain_uncached(category))

    def _pbms_enabled_category_domain_uncached(self, category):
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

    # Normalize to unique (partner, user) pairs - ONLY users with active PBMS access rights
    seen_partner_ids = set()
    pairs = []
    for item in recipients:
        if not item:
            continue
        if item._name == "res.users":
            for u in item:
                if u.active and u._pbms_has_access() and u.partner_id and u.partner_id.id not in seen_partner_ids:
                    seen_partner_ids.add(u.partner_id.id)
                    pairs.append((u.partner_id, u))
        elif item._name == "res.partner":
            for p in item:
                # Find active user with PBMS access rights for this partner
                u = p.user_ids.filtered(lambda usr: usr.active and usr._pbms_has_access())[:1] if p.user_ids else False
                if u and p.id not in seen_partner_ids:
                    seen_partner_ids.add(p.id)
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

    # Live web bus notifications to online users for Discuss inbox & systray chat bubble
    for partner, user in pairs:
        if user and Store:
            try:
                store = Store(bus_channel=user).add(
                    msg.with_user(user).with_context(allowed_company_ids=[]),
                    add_followers=False,
                )
                payload = {
                    "message_id": msg.id,
                    "store_data": store.get_result(),
                }
                if hasattr(user, "_bus_send"):
                    user._bus_send("mail.message/inbox", payload)
                elif hasattr(partner, "_bus_send"):
                    partner._bus_send("mail.message/inbox", payload)
                elif "bus.bus" in env and hasattr(env["bus.bus"], "_sendone"):
                    env["bus.bus"]._sendone(user, "mail.message/inbox", payload)
            except Exception as e:
                _logger.debug("Bus notification failed for user %s: %s", user.id, e)


class HrEmployeePbmsCache(models.Model):
    _inherit = "hr.employee"

    def write(self, vals):
        res = super().write(vals)
        if "user_id" in vals:
            self._ensure_ou_manager_branch_group()
        if {"parent_id", "user_id", "department_id", "operating_unit_id",
            "default_operating_unit_id", "operating_unit_ids", "active"} & set(vals):
            self.env.registry.clear_cache()
        return res

    def _ensure_ou_manager_branch_group(self):
        branch_group = self.env.ref("bunna_pbms.group_pbms_branch_user", raise_if_not_found=False)
        if not branch_group:
            return
        for emp in self:
            if emp.user_id and branch_group not in emp.user_id.group_ids:
                is_mgr = bool(self.env["operating.unit"].sudo().search_count([("manager_id", "=", emp.id)]))
                if is_mgr:
                    emp.user_id.sudo().write({"group_ids": [(4, branch_group.id)]})


class OperatingUnitPbmsCache(models.Model):
    _inherit = "operating.unit"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._ensure_managers_branch_user_group()
        return records

    def _compute_display_name(self):
        super()._compute_display_name()
        for ou in self:
            if ou.display_name and "hr.report.code(" in ou.display_name:
                code_obj = getattr(ou, "code", False)
                raw_code = (getattr(code_obj, "code", False) or getattr(code_obj, "name", False)) if code_obj else ""
                code_str = str(raw_code).strip() if raw_code else ""
                ou.display_name = f"[{code_str}] {ou.name}" if code_str else (ou.name or "")

    def write(self, vals):
        res = super().write(vals)
        if "manager_id" in vals:
            self._ensure_managers_branch_user_group()
        if {"parent_unit", "manager_id", "work_unit_type", "name", "user_ids", "active"} & set(vals):
            self.env.registry.clear_cache()
        return res

    def _ensure_managers_branch_user_group(self):
        branch_group = self.env.ref("bunna_pbms.group_pbms_branch_user", raise_if_not_found=False)
        if not branch_group:
            return
        users_to_add = self.env["res.users"].sudo()
        for ou in self:
            if ou.manager_id and ou.manager_id.user_id:
                users_to_add |= ou.manager_id.user_id
        for u in users_to_add:
            if branch_group not in u.group_ids:
                u.write({"group_ids": [(4, branch_group.id)]})


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

        menu_xmlid_to_key = {
            "bunna_pbms.menu_pbms_review_retail": "deposit",
            "bunna_pbms.menu_pbms_review_retail_customer": "customer_base",
            "bunna_pbms.menu_pbms_review_workforce": "workforce",
            "bunna_pbms.menu_pbms_review_exceptional_workforce": "exceptional_workforce",
            "bunna_pbms.menu_pbms_review_fx": "fx",
            "bunna_pbms.menu_pbms_review_digital": "digital",
            "bunna_pbms.menu_pbms_review_loan_disbursement": "loan_disbursement",
            "bunna_pbms.menu_pbms_review_loan_outstanding": "loan_outstanding",
            "bunna_pbms.menu_pbms_review_expense": "expense",
            "bunna_pbms.menu_pbms_review_fixed_asset": "fixed_asset",
            "bunna_pbms.menu_pbms_review_credit_portfolio": "income_plan",
            "bunna_pbms.menu_pbms_review_initiative_budget": "initiative_budget",
            "bunna_pbms.menu_pbms_consolidation": "consolidation",
        }

        # Check configured dynamic permissions
        dynamic_configs = {}
        if _safe_table_exists(self.env, "pbms.review.menu.config"):
            try:
                MenuConfig = self.env["pbms.review.menu.config"]
                for cfg in MenuConfig.sudo().search([]):
                    dynamic_configs[cfg.menu_key] = cfg
            except Exception:
                pass

        menu_category_map = {
            "bunna_pbms.menu_pbms_review_retail": {"deposit"},
            "bunna_pbms.menu_pbms_review_retail_customer": {"customer_base"},
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
        for xmlid, key in menu_xmlid_to_key.items():
            menu = self.env.ref(xmlid, raise_if_not_found=False)
            if not menu or menu not in visible:
                continue

            cfg = dynamic_configs.get(key)
            if cfg:
                if not cfg.active:
                    menus_to_hide |= menu
                    continue
                if cfg.privilege_ids:
                    # Dynamic privilege configuration in UI takes full precedence!
                    if user._pbms_can_see_review_menu(key):
                        continue
                    else:
                        menus_to_hide |= menu
                        continue

            # Fallback to default legacy role checks if no dynamic privileges configured:
            cats = menu_category_map.get(xmlid, set())
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

        ctx = result.get("context")
        if isinstance(ctx, str) and ("group_by_branch" in ctx or "group_by_line_type" in ctx or "group_district" in ctx):
            try:
                eval_ctx = tools.safe_eval.safe_eval(ctx)
                if isinstance(eval_ctx, dict):
                    eval_ctx["search_default_group_by_line_type"] = 1
                    eval_ctx["search_default_group_district"] = 2
                    eval_ctx["search_default_group_by_branch"] = 3
                    result["context"] = repr(eval_ctx)
            except Exception as e:
                _logger.warning("Failed adjusting action context for pbms line view: %s", e)
        elif isinstance(ctx, dict) and ("group_by_branch" in ctx or "group_by_line_type" in ctx or "group_district" in ctx):
            new_ctx = dict(ctx)
            new_ctx["search_default_group_by_line_type"] = 1
            new_ctx["search_default_group_district"] = 2
            new_ctx["search_default_group_by_branch"] = 3
            result["context"] = new_ctx

        return result



