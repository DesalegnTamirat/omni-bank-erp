# -*- coding: utf-8 -*-
"""Role- and state-based access helpers for PBMS workflow."""

from odoo import fields, models

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

    def _pbms_operating_unit_ids(self):
        self.ensure_one()
        unit_ids = set()
        if hasattr(self, "operating_unit_ids") and self.operating_unit_ids:
            unit_ids.update(self.operating_unit_ids.ids)
        if hasattr(self, "assigned_operating_unit_ids") and self.assigned_operating_unit_ids:
            unit_ids.update(self.assigned_operating_unit_ids.ids)
        if hasattr(self, "default_operating_unit_id") and self.default_operating_unit_id:
            unit_ids.add(self.default_operating_unit_id.id)
        if hasattr(self, "employee_id") and self.employee_id:
            emp = self.employee_id
            if hasattr(emp, "operating_unit_id") and emp.operating_unit_id:
                unit_ids.add(emp.operating_unit_id.id)
            if hasattr(emp, "default_operating_unit_id") and emp.default_operating_unit_id:
                unit_ids.add(emp.default_operating_unit_id.id)
            if hasattr(emp, "operating_unit_ids") and emp.operating_unit_ids:
                unit_ids.update(emp.operating_unit_ids.ids)
            if hasattr(emp, "department_id") and emp.department_id and hasattr(emp.department_id, "operating_unit_id") and emp.department_id.operating_unit_id:
                unit_ids.add(emp.department_id.operating_unit_id.id)
        return list(unit_ids)

    def _pbms_is_manager(self):
        return (
            self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        )

    def _pbms_is_sppmd_admin(self):
        return (
            self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        )

    def _pbms_is_sppmd_approver(self):
        return (
            self.has_group("bunna_pbms.group_pbms_approver")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        )

    def _pbms_is_ho_reviewer(self):
        return (
            self.has_group("bunna_pbms.group_pbms_ho_reviewer")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        )

    def _pbms_is_district_reviewer(self):
        return (
            self.has_group("bunna_pbms.group_pbms_district_reviewer")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        )

    def _pbms_is_branch_user(self):
        return (
            self.has_group("bunna_pbms.group_pbms_branch_user")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        )

    def _pbms_is_budget_hiring_committee(self):
        return (
            self.has_group("bunna_pbms.group_pbms_budget_hiring_committee")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        )

    def _pbms_is_ceo(self):
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
        return (
            self.has_group("bunna_pbms.group_pbms_respective_chief")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        )

    def _pbms_is_people_solutions(self):
        return (
            self.has_group("bunna_pbms.group_pbms_people_solutions")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        )

    def _pbms_is_cpco(self):
        return (
            self.has_group("bunna_pbms.group_pbms_cpco")
            or self.has_group("bunna_pbms.group_pbms_manager")
            or self.has_group("base.group_system")
        )

    def _pbms_is_people_operations(self):
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
