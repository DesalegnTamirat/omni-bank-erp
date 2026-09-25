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
PBMS_CHIEF_REVIEW_STATES = frozenset({"chief_review", "district_approved", "district_endorsed"})
PBMS_PEOPLE_SOLUTIONS_STATES = frozenset({"people_solutions_review"})
PBMS_CPCO_REVIEW_STATES = frozenset({"cpco_review"})

# Workflow-only fields reviewers and system may update without full content edit rights.
PBMS_WORKFLOW_ONLY_FIELDS = frozenset({
    "state", "submitted_by", "submitted_date",
    "district_reviewer_id", "district_review_date", "district_comment",
    "chief_approver_id", "chief_approval_date", "chief_comment",
    "people_solutions_reviewer_id", "people_solutions_review_date", "people_solutions_comment",
    "cpco_reviewer_id", "cpco_submission_date", "cpco_comment",
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
    *PBMS_MONTH_FIELDS,
    "deposit_type_id", "base_type", "fx_source_type", "channel_id", "expense_account_id",
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

        if user.has_group("bunna_pbms.group_pbms_respective_chief"):
            # 1. Resolve employee(s) for the chief user
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

            if not emp:
                return []

            # 2. Find all subordinate employees in the management hierarchy (direct & indirect)
            subordinates = self.env["hr.employee"].sudo().search([
                ("id", "child_of", emp.id),
                ("id", "!=", emp.id),
            ])
            if not subordinates:
                return []

            child_units = set()
            # 3. Operating units where manager_id is one of the subordinates
            ou_by_mgr = self.env["operating.unit"].sudo().search([
                ("manager_id", "in", subordinates.ids)
            ])
            child_units.update(ou_by_mgr.ids)

            # 4. Operating units assigned to subordinate employees
            for sub in subordinates:
                if sub.operating_unit_id:
                    child_units.add(sub.operating_unit_id.id)
                if sub.default_operating_unit_id:
                    child_units.add(sub.default_operating_unit_id.id)
                if sub.operating_unit_ids:
                    child_units.update(sub.operating_unit_ids.ids)

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
        all_cats = ["deposit", "customer_base", "fx", "digital_banking", "general_expense", "manpower", "fixed_asset"]
        if self._pbms_is_sppmd_admin() or self._pbms_is_sppmd_approver() or self.has_group("base.group_system") or self.id == 1:
            return all_cats

        # If Head Office Reviewer: evaluate strictly from Planning Configuration or department mapping
        if self.has_group("bunna_pbms.group_pbms_ho_reviewer"):
            # 1. Check Planning Configuration
            ConfigModel = self.env.get("pbms.planning.config")
            if ConfigModel is not None:
                cats = ConfigModel.get_user_authorized_categories(self)
                if cats:
                    return cats

            # 2. Fallback Heuristic matching
            cats = set()
            dept_name = (self.employee_id.department_id.name or "").lower() if (self.employee_id and self.employee_id.department_id) else ""
            emp_ous = self.employee_id.operating_unit_ids.mapped("name") if (self.employee_id and self.employee_id.operating_unit_ids) else []
            emp_def_ou = [self.employee_id.default_operating_unit_id.name] if (self.employee_id and self.employee_id.default_operating_unit_id and self.employee_id.default_operating_unit_id.name) else []
            user_ous = [ou.name for ou in self.operating_unit_ids if ou.name]
            combined = f"{dept_name} {' '.join(emp_ous + emp_def_ou + user_ous)}".lower()

            if self.has_group("hr.group_hr_user") or self.has_group("hr.group_hr_manager") or any(w in combined for w in ("hr", "human", "manpower", "recruitment", "people")):
                cats.add("manpower")
            if any(w in combined for w in ("retail", "operation", "deposit", "branch", "customer")):
                cats.update(["deposit", "customer_base"])
            if any(w in combined for w in ("fx", "foreign", "trade", "international", "treasury")):
                cats.add("fx")
            if any(w in combined for w in ("digital", "e-banking", "electronic", "card", "channel")):
                cats.add("digital_banking")
            if any(w in combined for w in ("finance", "account", "budget", "cost")):
                cats.add("general_expense")
            if any(w in combined for w in ("property", "procurement", "facility", "admin", "asset")):
                cats.add("fixed_asset")

            if cats:
                return list(cats)
            return all_cats

        # Branch Users & District Reviewers see all categories for their assigned operating units
        return all_cats


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

    doc_model = doc._name if doc and hasattr(doc, "_name") else False
    doc_res_id = doc.id if doc and hasattr(doc, "id") and len(doc) == 1 else False

    for partner, user in pairs:
        if not partner or not partner.active:
            continue
        author = env.user.partner_id if env.user and env.user.partner_id else partner
        msg = MailMessage.create({
            "subject": subject,
            "body": body,
            "model": doc_model,
            "res_id": doc_res_id,
            "message_type": "user_notification",
            "subtype_id": subtype_id,
            "author_id": author.id,
            "partner_ids": [(4, partner.id)],
            "is_internal": True,
        })
        MailNotification.create({
            "author_id": msg.author_id.id,
            "mail_message_id": msg.id,
            "notification_status": "sent",
            "notification_type": "inbox",
            "res_partner_id": partner.id,
            "is_read": False,
        })
        if user and Store:
            try:
                store = Store(bus_channel=user).add(
                    msg.with_user(user).with_context(allowed_company_ids=[]),
                    add_followers=False,
                )
                user._bus_send(
                    "mail.message/inbox",
                    {
                        "message_id": msg.id,
                        "store_data": store.get_result(),
                    },
                )
            except Exception as e:
                _logger.debug("Bus send failed for user %s: %s", user.id, e)


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
            or user.has_group("bunna_pbms.group_pbms_respective_chief")
            or user.has_group("bunna_pbms.group_pbms_ceo")
        )
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
            elif has_bhc_role and xmlid in (
                "bunna_pbms.menu_pbms_review_workforce",
                "bunna_pbms.menu_pbms_review_expense",
                "bunna_pbms.menu_pbms_review_fixed_asset",
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


