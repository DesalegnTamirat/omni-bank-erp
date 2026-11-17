# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from .pbms_access import _safe_table_exists

_logger = logging.getLogger(__name__)


class PbmsWorkflowDynamicEngine(models.AbstractModel):
    """Dynamic Workflow & Privilege Engine extension for PBMS planning records.
    Reads workflow definitions, step sequences, transition routing, and privilege
    assignments from the database configuration."""
    _inherit = "pbms.workflow.mixin"

    category_definition_id = fields.Many2one(
        "pbms.planning.category.definition",
        string="Category Definition",
        compute="_compute_category_definition_id",
        store=True,
        readonly=False,
        help="Dynamic planning category configuration linked to this plan.",
    )

    def _get_category_def(self):
        """Safely fetch pbms.planning.category.definition record without crashing if table is not yet created."""
        self.ensure_one()
        cat_code = getattr(self, "category", False)
        if not cat_code:
            return False
        try:
            cat_def = getattr(self, "category_definition_id", False)
            if cat_def:
                return cat_def
        except Exception:
            pass
        if not _safe_table_exists(self.env, "pbms.planning.category.definition"):
            return False
        try:
            return self.env["pbms.planning.category.definition"].sudo().search([
                ("code", "=", cat_code), ("active", "=", True)
            ], limit=1)
        except Exception:
            return False

    @api.depends("category")
    def _compute_category_definition_id(self):
        can_query = _safe_table_exists(self.env, "pbms.planning.category.definition")
        for rec in self:
            cat_code = getattr(rec, "category", False)
            if can_query and cat_code:
                try:
                    rec.category_definition_id = self.env["pbms.planning.category.definition"].sudo().search([("code", "=", cat_code)], limit=1)
                except Exception:
                    rec.category_definition_id = False
            else:
                rec.category_definition_id = False

    def _get_active_workflow(self):
        """Retrieve the configured dynamic workflow for this planning record."""
        self.ensure_one()
        cat_code = getattr(self, "category", False)
        memo_wf = getattr(self.env, "_pbms_active_wf_memo", None)
        if memo_wf is None:
            memo_wf = {}
            self.env._pbms_active_wf_memo = memo_wf
        cache_key = (cat_code, self.is_head_office_unit, bool(self.district_id))
        if cache_key in memo_wf:
            return memo_wf[cache_key]

        if not _safe_table_exists(self.env, "pbms.workflow.definition"):
            return False

        try:
            # 1. Category definition explicit workflow
            cat_rec = self._get_category_def()
            if cat_rec and cat_rec.workflow_id and cat_rec.workflow_id.active:
                return cat_rec.workflow_id

            # 2. Workflow mapped by category_ids
            WfDef = self.env["pbms.workflow.definition"].sudo()
            if cat_code:
                wf = WfDef.search([("category_ids.code", "=", cat_code), ("active", "=", True)], limit=1)
                if wf:
                    return wf

            # 3. Standard fallback workflows
            if cat_code == "manpower":
                wf = WfDef.search([("code", "=", "wf_workforce"), ("active", "=", True)], limit=1)
                if wf:
                    return wf
            elif self.is_head_office_unit and not self.district_id:
                wf = WfDef.search([("code", "=", "wf_direct_ho"), ("active", "=", True)], limit=1)
                if wf:
                    return wf
            elif cat_code in ("deposit", "customer_base", "fx", "digital_banking"):
                wf = WfDef.search([("code", "=", "wf_mobilization"), ("active", "=", True)], limit=1)
                if wf:
                    return wf
            else:
                wf = WfDef.search([("code", "=", "wf_resources"), ("active", "=", True)], limit=1)
                if wf:
                    return wf
        except Exception:
            memo_wf[cache_key] = False
            return False
        memo_wf[cache_key] = wf if 'wf' in locals() and wf else False
        return memo_wf[cache_key]

    def _get_current_workflow_step(self):
        """Find the matching pbms.workflow.step for current state and unit level."""
        self.ensure_one()
        wf = self._get_active_workflow()
        if not wf:
            return False

        matching_steps = wf.step_ids.filtered(lambda s: s.state == self.state)
        if not matching_steps:
            return False
        if len(matching_steps) == 1:
            return matching_steps[0]

        unit_level = "head_office" if self.is_head_office_unit else ("district" if self.is_district_unit else "branch")
        level_map = {
            "branch": ("branch",),
            "district": ("district",),
            "head_office": ("head_office", "functional_dept", "committee", "executive"),
        }
        allowed = level_map.get(unit_level, ("branch",))
        step_for_level = matching_steps.filtered(lambda s: s.org_level in allowed)
        if step_for_level:
            return step_for_level[0]

        return matching_steps[0]

    def _check_dynamic_privilege(self, action_type):
        """Dynamic check of user permissions against pbms.privilege, pbms.privilege.assignment,
        and pbms.role.definition with request-level memoization.
        Returns:
            True: if explicitly granted by dynamic config
            False: if explicitly denied by dynamic config
            None: if unconfigured (triggering transparent fallback to existing static logic)
        """
        self.ensure_one()
        user = self.env.user
        if self.env.is_admin() or user._pbms_is_sppmd_admin() or self.env.su:
            return True

        if not _safe_table_exists(self.env, "pbms.privilege.assignment") or not _safe_table_exists(self.env, "pbms.role.definition"):
            return None

        # Request-level memoization to eliminate hundreds of duplicate queries per action
        memo = getattr(self.env, "_pbms_dyn_priv_memo", None)
        if memo is None:
            memo = {}
            self.env._pbms_dyn_priv_memo = memo

        cat_code = getattr(self, "category", False)
        unit_id = self.org_unit_id.id if self.org_unit_id else False
        cache_key = (user.id, action_type, cat_code, unit_id, self.is_head_office_unit, self.is_district_unit)
        if cache_key in memo:
            return memo[cache_key]

        res = self._check_dynamic_privilege_impl(action_type, user, cat_code, unit_id)
        memo[cache_key] = res
        return res

    def _check_dynamic_privilege_impl(self, action_type, user, cat_code, unit_id):
        try:
            Assignment = self.env["pbms.privilege.assignment"].sudo()
            Role = self.env["pbms.role.definition"].sudo()

            has_assignments = bool(Assignment.search_count([("active", "=", True)]))
            has_roles = bool(Role.search_count([("active", "=", True)]))
        except Exception:
            return None

        if not has_assignments and not has_roles:
            return None

        user_group_ids = user.all_group_ids.ids if hasattr(user, "all_group_ids") else getattr(user, "group_ids", getattr(user, "groups_id", self.env["res.groups"])).ids
        user_emp = user.employee_id.sudo() if user.employee_id else False
        user_job_id = user_emp.job_id.id if user_emp and user_emp.job_id else False

        u_level = "head_office" if self.is_head_office_unit else ("district" if self.is_district_unit else "branch")

        def _matches_privilege(assign):
            if assign.privilege_id and (assign.privilege_id.action_type == action_type or assign.privilege_id.code == action_type):
                return True
            if hasattr(assign, "privilege_ids") and any(p.action_type == action_type or p.code == action_type for p in assign.privilege_ids):
                return True
            if assign.role_id and any(p.action_type == action_type or p.code == action_type for p in assign.role_id.privilege_ids):
                return True
            return False

        def _matches_actor(assign):
            if assign.user_id and assign.user_id.id == user.id:
                return True
            if assign.group_id and assign.group_id.id in user_group_ids:
                return True
            if assign.job_id and user_job_id and assign.job_id.id == user_job_id:
                return True
            if assign.role_id and any(g.id in user_group_ids for g in assign.role_id.group_ids):
                return True
            return False

        def _matches_scope(assign):
            if assign.category_ids and cat_code and not any(c.code == cat_code for c in assign.category_ids):
                return False
            if assign.org_level != "all":
                if assign.org_level in ("head_office", "ho") and u_level != "head_office":
                    return False
                if assign.org_level == "district" and u_level != "district":
                    return False
                if assign.org_level == "branch" and u_level != "branch":
                    return False
            if assign.org_unit_id and assign.org_unit_id.id != unit_id:
                return False
            return True

        # 1. Check explicit DENY assignments first
        if has_assignments:
            deny_assigns = Assignment.search([
                ("active", "=", True),
                ("grant_type", "=", "deny"),
            ])
            for da in deny_assigns:
                if _matches_privilege(da) and _matches_actor(da) and _matches_scope(da):
                    return False

            # 2. Check explicit ALLOW assignments
            allow_assigns = Assignment.search([
                ("active", "=", True),
                ("grant_type", "=", "allow"),
            ])
            for aa in allow_assigns:
                if _matches_privilege(aa) and _matches_actor(aa) and _matches_scope(aa):
                    return True

        # 3. Check active Roles
        if has_roles:
            matching_roles = Role.search([("active", "=", True)])
            for role in matching_roles:
                if not any(g.id in user_group_ids for g in role.group_ids):
                    continue
                if not any(p.action_type == action_type or p.code == action_type for p in role.privilege_ids):
                    continue
                if role.org_level != "all":
                    if role.org_level == "branch" and u_level != "branch":
                        continue
                    if role.org_level == "district" and u_level != "district":
                        continue
                    if role.org_level in ("head_office", "ho") and u_level != "head_office":
                        continue
                if role.category_ids and cat_code and not any(c.code == cat_code for c in role.category_ids):
                    continue
                return True

        return None

    def _get_dynamic_transition(self, action_type):
        """Find matching pbms.workflow.transition for current step and action_type."""
        self.ensure_one()
        step = self._get_current_workflow_step()
        if not step:
            return False

        transitions = step.transition_ids.filtered(
            lambda t: t.active and (t.action_type == action_type or t.action_method == f"action_{action_type}")
        )
        if not transitions:
            return False

        cat_code = getattr(self, "category", False)
        u_level = "head_office" if self.is_head_office_unit else ("district" if self.is_district_unit else "branch")
        for trans in transitions:
            if trans.condition_category_ids and cat_code and not any(c.code == cat_code for c in trans.condition_category_ids):
                continue
            if trans.condition_org_level and trans.condition_org_level != "all" and trans.condition_org_level != u_level:
                continue
            return trans
        return transitions[0] if transitions else False

    def _pbms_can_edit_plan_content(self):
        """Dynamic check combined with backward-compatible static rules."""
        self.ensure_one()
        user = self.env.user
        if self.env.context.get("pbms_target_cascade") or self.env.context.get("bypass_plan_lock"):
            return True

        dyn_edit = self._check_dynamic_privilege("edit")
        if dyn_edit is False:
            return False

        step = self._get_current_workflow_step()
        if step and not step.can_edit_content and not (user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su):
            return False

        if dyn_edit is True:
            if self.state in ("approved", "rejected"):
                return False
            return True

        return super()._pbms_can_edit_plan_content()

    def _pbms_can_delete_plan(self):
        """Dynamic check for delete privilege combined with static rules."""
        self.ensure_one()
        dyn_del = self._check_dynamic_privilege("delete")
        if dyn_del is False:
            return False
        if dyn_del is True:
            if self.state in ("approved", "rejected"):
                return False
            return True
        return super()._pbms_can_delete_plan()

    def _get_submission_destination_and_state(self):
        """Determine destination state and flags for this plan upon submission,
        based on dynamic category configuration and workflow transitions."""
        self.ensure_one()
        cat_def = self._get_category_def()

        is_ho = self._is_head_office_plan() or self.org_unit_type == "head_office" or (self.org_unit_id and getattr(self.org_unit_id, "work_unit_type", False) == "head_office")
        is_dist = self._is_district_plan() or self.org_unit_type == "district_office"
        target_cat = getattr(self, "category", False)

        # 1. Dynamic category destination configuration (when explicitly configured away from default)
        if cat_def:
            if not is_ho and not is_dist and cat_def.branch_submission_destination and cat_def.branch_submission_destination != "default":
                dest = cat_def.branch_submission_destination
                if dest == "district_reviewer":
                    return "submitted", False
                elif dest == "ho_reviewer":
                    return "district_endorsed", False
                elif dest == "respective_chief":
                    return "chief_review", False
                elif dest == "sppmd_approver":
                    return "ho_reviewed", False
            elif is_ho and cat_def.ho_submission_destination and cat_def.ho_submission_destination != "default":
                dest = cat_def.ho_submission_destination
                if dest == "respective_chief":
                    return "chief_review", False
                elif dest == "ho_reviewer":
                    return "district_endorsed", False
                elif dest == "sppmd_approver":
                    return "approved", False
            elif is_dist and cat_def.district_submission_destination and cat_def.district_submission_destination != "default":
                dest = cat_def.district_submission_destination
                if dest == "ho_reviewer":
                    return "district_endorsed", True
                elif dest == "respective_chief":
                    return "chief_review", False
                elif dest == "sppmd_approver":
                    return "approved", False

        # 2. Custom dynamic workflow transition from current step
        dyn_trans = self._get_dynamic_transition("submit")
        if dyn_trans and dyn_trans.target_state:
            return dyn_trans.target_state, False

        # 3. Standard fallback behavior (exact existing PBMS logic)
        is_ho_cascade_cat = target_cat in (
            "manpower", "general_expense", "fixed_asset",
            "credit_portfolio", "initiative_budget",
            "loan_disbursement_collection", "loan_outstanding",
            "deposit", "customer_base", "fx", "digital_banking",
        )
        is_people_ops = self.env.user.has_group("bunna_pbms.group_pbms_people_operations") or (self.org_unit_id and "people" in (self.org_unit_id.name or "").lower() and "operation" in (self.org_unit_id.name or "").lower())

        if (is_ho and is_ho_cascade_cat) or is_people_ops:
            return "chief_review", False
        elif is_dist and target_cat == "manpower":
            return "chief_review", False
        elif is_dist:
            return "district_endorsed", True
        else:
            return "submitted", False

    def _get_district_endorse_destination_and_state(self):
        """Determine destination state and notification label when a district reviewer endorses a district plan."""
        self.ensure_one()
        cat_def = self._get_category_def()
        if cat_def and cat_def.district_endorse_destination and cat_def.district_endorse_destination != "default":
            dest = cat_def.district_endorse_destination
            if dest == "ho_reviewer":
                return "district_endorsed", _("Head Office Functional Review")
            elif dest == "respective_chief":
                return "chief_review", _("Respective Chief Review")
            elif dest == "sppmd_approver":
                return "ho_reviewed", _("SPPMD Final Review / Approval")
            elif dest == "final_approved":
                return "approved", _("Final Approved")

        dyn_trans = self._get_dynamic_transition("district_endorse")
        if dyn_trans and dyn_trans.target_state:
            return dyn_trans.target_state, dyn_trans.name or _("Dynamic Transition")

        return "district_endorsed", _("Head Office Functional Review")

    def _get_district_approve_destination_and_state(self):
        """Determine destination state and notification label when a district reviewer approves a branch plan."""
        self.ensure_one()
        cat_def = self._get_category_def()
        target_cat = getattr(self, "category", False)
        if cat_def and cat_def.district_approve_destination and cat_def.district_approve_destination != "default":
            dest = cat_def.district_approve_destination
            if dest in ("district_approved", "district_reviewer"):
                return "district_approved", _("District Approved (Retained at District)")
            elif dest == "ho_reviewer":
                if target_cat in ("deposit", "customer_base", "fx", "digital_banking"):
                    return "district_approved", _("District Approved (Retained at District)")
                return "district_approved", _("Head Office Functional Review")
            elif dest == "respective_chief":
                return "chief_review", _("Respective Chief Review")
            elif dest == "sppmd_approver":
                return "ho_reviewed", _("SPPMD Final Review / Approval")
            elif dest == "final_approved":
                return "approved", _("Final Approved")

        dyn_trans = self._get_dynamic_transition("district_approve")
        if dyn_trans and dyn_trans.target_state:
            return dyn_trans.target_state, dyn_trans.name or _("Dynamic Transition")

        if target_cat in ("deposit", "customer_base", "fx", "digital_banking"):
            return "district_approved", _("District Approved (Retained at District)")
        elif target_cat == "manpower":
            return "chief_review", _("Respective Chief Review (Workforce)")
        return "district_approved", _("Head Office Functional Review")

    def _get_ho_approve_destination_and_state(self):
        """Determine destination state and notification label when a Head Office Functional Reviewer approves a plan."""
        self.ensure_one()
        cat_def = self._get_category_def()
        if cat_def and cat_def.ho_approve_destination and cat_def.ho_approve_destination != "default":
            dest = cat_def.ho_approve_destination
            if dest == "final_approved":
                return "approved", _("Final Approved")
            elif dest == "sppmd_approver":
                return "ho_reviewed", _("SPPMD Final Review / Consolidation")
            elif dest == "respective_chief":
                return "chief_review", _("Respective Chief Review")

        dyn_trans = self._get_dynamic_transition("ho_approve")
        if dyn_trans and dyn_trans.target_state:
            return dyn_trans.target_state, dyn_trans.name or _("Dynamic Transition")

        return "approved", _("Final Approved")

    def _get_chief_endorse_destination_and_state(self):
        """Determine destination state and notification label when a Respective Chief approves/endorses a plan."""
        self.ensure_one()
        cat_def = self._get_category_def()
        if cat_def and cat_def.chief_endorse_destination and cat_def.chief_endorse_destination != "default":
            dest = cat_def.chief_endorse_destination
            if dest == "ho_reviewer":
                return "district_endorsed", _("Head Office Functional Review")
            elif dest == "people_solutions":
                return "people_solutions_review", _("People Solutions Directorate Review")
            elif dest == "cpco":
                return "cpco_review", _("CPCO Review")
            elif dest == "committee":
                return "committee_review", _("Review Committee")
            elif dest == "sppmd_approver":
                return "ho_reviewed", _("SPPMD Final Review / Approval")
            elif dest == "final_approved":
                return "approved", _("Final Approved")

        dyn_trans = self._get_dynamic_transition("chief_approve") or self._get_dynamic_transition("chief_endorse")
        if dyn_trans and dyn_trans.target_state:
            return dyn_trans.target_state, dyn_trans.name or _("Dynamic Transition")

        target_cat = getattr(self, "category", False)
        if target_cat == "manpower":
            return "people_solutions_review", _("People Solutions Directorate Review")
        return "district_endorsed", _("Head Office Functional Review")

    def _pbms_can_submit_plan(self):
        self.ensure_one()
        cat_def = self._get_category_def()

        req_action = cat_def.submission_required_privilege_id.action_type if (cat_def and cat_def.submission_required_privilege_id) else "submit"
        dyn_submit = self._check_dynamic_privilege(req_action)
        if dyn_submit is False:
            return False
        if dyn_submit is True:
            user = self.env.user
            if self.cycle_id and self.cycle_id.state != "open":
                return False
            if self._is_own_operating_unit_plan() or user._pbms_is_sppmd_admin() or self.env.is_admin() or self.env.su:
                return True
        return super()._pbms_can_submit_plan()

    def _pbms_can_district_review_plan(self):
        self.ensure_one()
        cat_def = self._get_category_def()

        if self.state in ("submitted", "info_requested"):
            req_priv = False
            if cat_def and cat_def.destination_required_privilege_id:
                req_priv = cat_def.destination_required_privilege_id
            if req_priv:
                check_dest = self._check_dynamic_privilege(req_priv.action_type)
                if check_dest is False:
                    return False
                if check_dest is True:
                    return True

        dyn_appr = self._check_dynamic_privilege("district_approve")
        dyn_end = self._check_dynamic_privilege("district_endorse")
        dyn_rev = self._check_dynamic_privilege("district_review")
        if dyn_appr is False and dyn_end is False and dyn_rev is False:
            return False
        if dyn_appr is True or dyn_end is True or dyn_rev is True:
            if self.state not in ("submitted", "info_requested"):
                return False
            return True
        return super()._pbms_can_district_review_plan()

    def _pbms_can_ho_review_plan(self):
        self.ensure_one()
        cat_def = self._get_category_def()

        # Check destination recipient privilege for district-endorsed/approved plans
        if self.state in ("district_endorsed", "district_approved"):
            req_priv = False
            if self.state == "district_endorsed" and cat_def and self.chief_approver_id and cat_def.chief_endorse_next_privilege_id:
                req_priv = cat_def.chief_endorse_next_privilege_id
            elif self.state == "district_endorsed" and cat_def and cat_def.district_endorse_next_privilege_id:
                req_priv = cat_def.district_endorse_next_privilege_id
            elif self.state == "district_approved" and cat_def and cat_def.district_approve_next_privilege_id:
                req_priv = cat_def.district_approve_next_privilege_id
            elif cat_def and cat_def.destination_required_privilege_id:
                req_priv = cat_def.destination_required_privilege_id

            if req_priv:
                check_dest = self._check_dynamic_privilege(req_priv.action_type)
                if check_dest is False:
                    return False
                if check_dest is True:
                    return True

        dyn_appr = self._check_dynamic_privilege("ho_approve")
        dyn_end = self._check_dynamic_privilege("ho_endorse")
        dyn_rev = self._check_dynamic_privilege("ho_review")
        if dyn_appr is False and dyn_end is False and dyn_rev is False:
            return False
        if dyn_appr is True or dyn_end is True or dyn_rev is True:
            return True
        return super()._pbms_can_ho_review_plan()

    def action_submit(self):
        # 1. Validation: Prevent submission of empty planning requests
        plans_to_validate = self.filtered(lambda p: p.state in ("draft", "returned", "info_requested"))
        candidate_all = self.env[self._name]
        for rec in plans_to_validate:
            candidate_all |= rec
            if hasattr(rec, "org_unit_id") and hasattr(rec, "cycle_id") and rec.org_unit_id and rec.cycle_id:
                siblings = self.env[rec._name].search([
                    ("org_unit_id", "=", rec.org_unit_id.id),
                    ("cycle_id", "=", rec.cycle_id.id),
                    ("active", "=", True),
                    ("state", "in", ("draft", "returned", "info_requested")),
                ])
                candidate_all |= siblings

        has_any_data = any(
            p._pbms_has_valid_planning_data() if hasattr(p, "_pbms_has_valid_planning_data") else False
            for p in candidate_all
        )
        if not has_any_data:
            raise ValidationError(_("You cannot submit an empty planning request. Please plan at least one planning category before submitting."))

        for rec in self:
            cat_def = rec.category_definition_id
            if not cat_def and getattr(rec, "category", False):
                cat_def = self._get_category_def()
            req_priv = cat_def.submission_required_privilege_id if cat_def else False
            req_action = req_priv.action_type if req_priv else "submit"
            dyn_submit = rec._check_dynamic_privilege(req_action)
            if dyn_submit is False:
                raise AccessError(_("You do not have the required dynamic privilege '%s' to submit planning records for %s.") % (req_priv.name if req_priv else _("Submit"), rec.display_name or rec.category))

        # Check if any plan has a custom destination configured
        has_custom_destination = False
        for p in self:
            cat_def = p._get_category_def()
            if cat_def:
                if p.is_branch_unit and cat_def.branch_submission_destination not in ("default", False):
                    has_custom_destination = True
                    break
                elif p.is_head_office_unit and cat_def.ho_submission_destination not in ("default", False):
                    has_custom_destination = True
                    break
                elif p.is_district_unit and cat_def.district_submission_destination not in ("default", False):
                    has_custom_destination = True
                    break
            if p._get_dynamic_transition("submit"):
                has_custom_destination = True
                break

        if not has_custom_destination:
            return super().action_submit()

        # If custom routing is configured, execute dynamic destination routing
        plans_to_submit = self.filtered(lambda p: p.state in ("draft", "returned", "info_requested"))
        if not plans_to_submit and all(p.state in ("submitted", "chief_review", "district_approved", "district_endorsed") for p in self):
            return True
        plans_to_submit._check_editable()
        if hasattr(plans_to_submit, "_realign_lines_to_matching_cards"):
            plans_to_submit._realign_lines_to_matching_cards()
        elif hasattr(plans_to_submit, "_sync_category_records"):
            plans_to_submit.with_context(bypass_plan_lock=True)._sync_category_records()

        candidate_plans = self.env[self._name]
        for rec in plans_to_submit:
            candidate_plans |= rec
            if hasattr(rec, "org_unit_id") and hasattr(rec, "cycle_id") and rec.org_unit_id and rec.cycle_id:
                siblings = self.env[rec._name].search([
                    ("org_unit_id", "=", rec.org_unit_id.id),
                    ("cycle_id", "=", rec.cycle_id.id),
                    ("active", "=", True),
                    ("state", "in", ("draft", "returned", "info_requested")),
                ])
                candidate_plans |= siblings

        all_plans = self.env[self._name]
        for p in candidate_plans:
            if hasattr(p, "_pbms_has_valid_planning_data"):
                if p._pbms_has_valid_planning_data():
                    all_plans |= p
            else:
                all_plans |= p

        if not all_plans:
            raise ValidationError(_("You cannot submit an empty planning request. Please plan at least one planning category before submitting."))

        plans_by_action = {}
        old_states = {p.id: p.state for p in all_plans}
        now = fields.Datetime.now()
        for line in all_plans:
            next_state, is_dist_endorsed = line._get_submission_destination_and_state()
            key = (next_state, is_dist_endorsed)
            plans_by_action.setdefault(key, self.env[self._name])
            plans_by_action[key] |= line

        for (next_state, is_dist_endorsed), plan_group in plans_by_action.items():
            write_vals = {
                "state": next_state,
                "submitted_by": self.env.uid,
                "submitted_date": now,
            }
            if is_dist_endorsed:
                write_vals["district_reviewer_id"] = self.env.uid
                write_vals["district_review_date"] = now
            plan_group.sudo().with_context(
                bypass_plan_lock=True,
                skip_sync_category_records=True,
                skip_split_mixed_lines=True,
                skip_dropdown_plan_check=True,
            ).write(write_vals)

            for line in plan_group:
                old_s = old_states.get(line.id, "draft")
                if next_state == "chief_review":
                    line._log_audit_action("submit", old_s, "chief_review", _("%s submitted to Respective Chief for review.") % (line.plan_category_title or _("Plan")))
                    line._notify_pending_approval("chief_review", _("Respective Chief Review"))
                elif next_state == "district_endorsed":
                    line._log_audit_action("submit", old_s, "district_endorsed", _("%s submitted to Head Office Functional Reviewer.") % (line.plan_category_title or _("Plan")))
                    line._notify_pending_approval("district_endorsed", _("Head Office Functional Review"))
                elif next_state == "ho_reviewed":
                    line._log_audit_action("submit", old_s, "ho_reviewed", _("%s submitted to SPPMD Reviewer / Approver.") % (line.plan_category_title or _("Plan")))
                    line._notify_pending_approval("ho_reviewed", _("SPPMD Review"))
                else:
                    line._log_audit_action("submit", old_s, "submitted", _("%s submitted for district review.") % (line.plan_category_title or _("Plan")))
                    line._notify_pending_approval("submitted", _("District Review"))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Submitted Successfully'),
                'message': _('Plan has been submitted successfully for review.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }

    def action_district_approve(self):
        for rec in self:
            cat_def = rec._get_category_def()
            is_dist_plan = rec.is_district_unit or rec._is_district_plan() or rec.org_unit_type in ("district_office", "regional_office", "district")
            if is_dist_plan:
                req_priv = cat_def.district_endorse_required_privilege_id if cat_def else False
                req_action = req_priv.action_type if req_priv else "district_endorse"
            else:
                req_priv = cat_def.district_approve_required_privilege_id if cat_def else False
                req_action = req_priv.action_type if req_priv else "district_approve"
            dyn_check = rec._check_dynamic_privilege(req_action)
            if dyn_check is False:
                raise AccessError(_("You do not have the required dynamic privilege '%s' to approve/endorse planning records for %s.") % (
                    req_priv.name if req_priv else req_action,
                    rec.display_name or rec.category or ""
                ))

        has_custom = False
        all_plans = self._get_workflow_sibling_plans()
        for p in all_plans:
            cat_def = p._get_category_def()
            is_dist_plan = p.is_district_unit or p._is_district_plan() or p.org_unit_type in ("district_office", "regional_office", "district")
            if cat_def:
                if is_dist_plan and cat_def.district_endorse_destination not in ("default", False):
                    has_custom = True
                    break
                elif not is_dist_plan and cat_def.district_approve_destination not in ("default", False):
                    has_custom = True
                    break
            if is_dist_plan and p._get_dynamic_transition("district_endorse"):
                has_custom = True
                break
            elif not is_dist_plan and p._get_dynamic_transition("district_approve"):
                has_custom = True
                break

        if not has_custom:
            return super().action_district_approve()

        # Dynamic approval / endorsement execution
        for line in all_plans:
            if line.state not in ("submitted", "info_requested"):
                if line.state in ("district_approved", "district_endorsed", "chief_review", "people_solutions_review",
                                  "cpco_review", "committee_review", "ceo_approval", "board_ceo_approval",
                                  "ho_endorse", "cpco_endorse", "ho_reviewed", "approved", "rejected"):
                    continue
                raise UserError(_("Plan must be submitted before it can be district approved. Current state: %s") % line.state)
            if not line._pbms_can_district_review_plan():
                raise AccessError(_("Only District Reviewers can approve child work unit plans while they are under district review."))

            old_state = line.state
            is_dist_plan = line.is_district_unit or line._is_district_plan() or line.org_unit_type in ("district_office", "regional_office", "district")

            if is_dist_plan:
                next_state, next_label = line._get_district_endorse_destination_and_state()
                next_msg = line.district_comment or _("Endorsed by District Office (routed to %s).") % next_label
                # Finalize District's proposed figures on District plan lines to reflect the district-edited amount
                for dist_line in line.line_ids:
                    dist_line_vals = {
                        "proposed_annual_total": dist_line.annual_total or 0.0,
                        "proposed_opening_balance": dist_line.opening_balance or 0.0,
                    }
                    for i in range(1, 13):
                        dist_line_vals[f"proposed_m{i:02d}"] = getattr(dist_line, f"m{i:02d}", 0.0) or 0.0
                    dist_line.with_context(bypass_plan_lock=True).write(dist_line_vals)

                if hasattr(line, "_compute_category_summaries"):
                    line._compute_category_summaries()
                if hasattr(line, "_compute_plan_proposed_approved_totals"):
                    line._compute_plan_proposed_approved_totals()
            else:
                next_state, next_label = line._get_district_approve_destination_and_state()
                next_msg = line.district_comment or _("Approved by District (routed to %s).") % next_label

            line.with_context(bypass_plan_lock=True).write({
                "state": next_state,
                "active": True,
                "district_reviewer_id": self.env.uid,
                "district_review_date": fields.Datetime.now(),
            })
            line._log_audit_action("district_approve", old_state, next_state, next_msg)
            line._notify_pending_approval(next_state, next_label)

            # Consolidate into District Overview Plan when approving child branch plans in Mobilization Categories
            if not line.is_district_unit and not line._is_district_plan():
                target_cat = getattr(line, "category", False)
                if target_cat in ("deposit", "customer_base", "fx", "digital_banking"):
                    district = line.district_id or line._find_district_ancestor(line.org_unit_id)
                    if district and hasattr(line, "_consolidate_district_plan_data"):
                        dist_plan = line.sudo().with_context(
                            target_category=target_cat,
                            skip_sync_category_records=True,
                        )._consolidate_district_plan_data(line.cycle_id, district)
                        if dist_plan:
                            if dist_plan.state in ("draft", "returned", "info_requested"):
                                dist_plan.with_context(bypass_plan_lock=True, skip_sync_category_records=True).write({
                                    "state": "district_endorsed",
                                    "active": True,
                                })
                                dist_plan._notify_pending_approval("district_endorsed", _("Head Office Functional Review"))
                            elif not dist_plan.active:
                                dist_plan.with_context(bypass_plan_lock=True, skip_sync_category_records=True).write({"active": True})
            else:
                # District plan endorsed to Head Office:
                # Bank-Wide Head Office Overview is NOT generated here.
                # It is generated strictly after Head Office Functional Reviewer clicks Final Approve (action_ho_approve).
                pass

        if any(p.is_district_unit or p._is_district_plan() or p.org_unit_type in ("district_office", "regional_office", "district") for p in all_plans):
            title = _('Endorsed Successfully')
            msg = _('Plan has been endorsed to Head Office successfully.')
        else:
            title = _('District Approved Successfully')
            msg = _('Plan has been approved by District Reviewer successfully.')

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': msg,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }

    def action_district_endorse(self):
        for rec in self:
            cat_def = rec._get_category_def()
            req_priv = cat_def.district_endorse_required_privilege_id if cat_def else False
            req_action = req_priv.action_type if req_priv else "district_endorse"
            dyn_end = rec._check_dynamic_privilege(req_action)
            if dyn_end is False:
                raise AccessError(_("You do not have the dynamic privilege '%s' to endorse this plan to Head Office.") % (req_priv.name if req_priv else req_action))
        return self.action_district_approve()

    def action_ho_approve(self):
        for rec in self:
            cat_def = rec._get_category_def()
            req_priv = cat_def.ho_approve_required_privilege_id if cat_def else False
            req_action = req_priv.action_type if req_priv else "ho_approve"
            dyn_ho = rec._check_dynamic_privilege(req_action)
            if dyn_ho is False:
                raise AccessError(_("You do not have the dynamic privilege '%s' to approve this plan at Head Office level.") % (req_priv.name if req_priv else req_action))

        has_custom = False
        all_plans = self._get_workflow_sibling_plans()
        for p in all_plans:
            cat_def = p._get_category_def()
            if cat_def and cat_def.ho_approve_destination not in ("default", "final_approved", False):
                has_custom = True
                break
            if p._get_dynamic_transition("ho_approve"):
                has_custom = True
                break

        if not has_custom:
            return super().action_ho_approve()

        # Dynamic HO Approval Routing
        now = fields.Datetime.now()
        for line in all_plans:
            if not line._pbms_can_ho_review_plan():
                raise AccessError(_("Only Head Office Functional Reviewers can approve plans at this stage."))
            old_state = line.state
            next_state, next_label = line._get_ho_approve_destination_and_state()
            target_cat = getattr(line, "category", False)

            line.with_context(bypass_plan_lock=True).write({
                "state": next_state,
                "ho_reviewer_id": self.env.uid,
                "ho_review_date": now,
                "approver_id": self.env.uid if next_state == "approved" else False,
                "approval_date": now if next_state == "approved" else False,
            })
            line._log_audit_action("ho_approve", old_state, next_state, _("Approved at Head Office level (routed to %s).") % next_label)
            line._notify_pending_approval(next_state, next_label)

            # When approving a District Overview Plan, also approve all its attached branch plans
            if next_state == "approved" and (line.is_district_unit or line._is_district_plan() or line.org_unit_type in ("district_office", "regional_office", "district")):
                self.env[line._name].flush_model(["state", "district_id", "cycle_id", "category", "active", "org_unit_id"])
                branch_plans = self.env[line._name].sudo().search([
                    ("cycle_id", "=", line.cycle_id.id),
                    ("category", "=", target_cat),
                    ("active", "=", True),
                    ("org_unit_type", "not in", ("district_office", "regional_office", "district")),
                    ("state", "in", ("submitted", "district_approved", "district_endorsed", "ho_reviewed")),
                    "|",
                    ("district_id", "=", line.org_unit_id.id),
                    ("org_unit_id.parent_unit", "=", line.org_unit_id.id),
                ])
                if branch_plans:
                    branch_plans.with_context(
                        bypass_plan_lock=True,
                        skip_sync_category_records=True,
                        skip_split_mixed_lines=True,
                        skip_cleanup_district_cards=True,
                        skip_dropdown_plan_check=True,
                    ).write({
                        "state": "approved",
                        "ho_reviewer_id": self.env.uid,
                        "ho_review_date": now,
                        "approver_id": self.env.uid,
                        "approval_date": now,
                    })
                    if hasattr(branch_plans, "_compute_category_summaries"):
                        branch_plans._compute_category_summaries()

            # Consolidate all districts into Bank-Wide Head Office record and finally approve it
            if next_state == "approved" and target_cat in ("deposit", "customer_base", "fx", "digital_banking", "loan_disbursement_collection", "loan_outstanding"):
                ho_unit = False
                if line.org_unit_id and line.org_unit_id.parent_unit and line.org_unit_id.parent_unit.work_unit_type == "head_office":
                    ho_unit = line.org_unit_id.parent_unit
                if not ho_unit:
                    ho_unit = self.env["operating.unit"].search([("work_unit_type", "=", "head_office")], limit=1)

                if ho_unit and hasattr(line, "_consolidate_ho_plan_data"):
                    ho_plan = line.sudo()._consolidate_ho_plan_data(line.cycle_id, ho_unit)
                    if ho_plan:
                        ho_old_state = ho_plan.state
                        ho_plan.with_context(bypass_plan_lock=True).write({
                            "state": "approved",
                            "ho_reviewer_id": self.env.uid,
                            "ho_review_date": now,
                            "approver_id": self.env.uid,
                            "approval_date": now,
                            "submitted_by": self.env.uid,
                            "submitted_date": now,
                        })
                        for ho_line in ho_plan.line_ids:
                            ho_line_vals = {
                                "proposed_annual_total": ho_line.annual_total or 0.0,
                                "proposed_opening_balance": ho_line.opening_balance or 0.0,
                            }
                            for i in range(1, 13):
                                ho_line_vals[f"proposed_m{i:02d}"] = getattr(ho_line, f"m{i:02d}", 0.0) or 0.0
                            ho_line.with_context(bypass_plan_lock=True).write(ho_line_vals)

                        if hasattr(ho_plan.line_ids, "_populate_approved_from_annual_total_batch"):
                            ho_plan.line_ids._populate_approved_from_annual_total_batch()
                        else:
                            for ho_line in ho_plan.line_ids:
                                vals = {
                                    "approved_opening_balance": getattr(ho_line, "opening_balance", 0.0) or 0.0,
                                    "approved_annual_total": getattr(ho_line, "annual_total", 0.0) or 0.0,
                                }
                                for i in range(1, 13):
                                    vals[f"approved_m{i:02d}"] = getattr(ho_line, f"m{i:02d}", 0.0) or 0.0
                                ho_line.with_context(bypass_plan_lock=True).write(vals)

                        if hasattr(ho_plan, "_sync_category_records"):
                            ho_plan.with_context(bypass_plan_lock=True)._sync_category_records()
                        if hasattr(ho_plan, "_compute_category_summaries"):
                            ho_plan._compute_category_summaries()

                        ho_plan._log_audit_action("ho_approve", ho_old_state, "approved", _("Bank-Wide Head Office consolidated plan finally approved."))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Approved Successfully'),
                'message': _('Plan has been approved by Head Office Functional Reviewer successfully.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }

    def action_chief_approve_escalate(self):
        for rec in self:
            cat_def = rec._get_category_def()
            req_priv = cat_def.chief_endorse_required_privilege_id if cat_def else False
            req_action = req_priv.action_type if req_priv else "chief_approve"
            dyn_chief = rec._check_dynamic_privilege(req_action)
            if dyn_chief is False:
                raise AccessError(_("You do not have the required dynamic privilege '%s' to approve/endorse this plan at Chief level.") % (
                    req_priv.name if req_priv else req_action
                ))

        has_custom = False
        all_plans = self._get_workflow_sibling_plans()
        for p in all_plans:
            cat_def = p._get_category_def()
            if cat_def and cat_def.chief_endorse_destination not in ("default", False):
                has_custom = True
                break
            if p._get_dynamic_transition("chief_approve") or p._get_dynamic_transition("chief_endorse"):
                has_custom = True
                break

        if not has_custom:
            return super().action_chief_approve_escalate()

        # Dynamic Chief Approval / Endorsement Execution
        now = fields.Datetime.now()
        for line in all_plans:
            can_approve = (
                self.env.user._pbms_is_respective_chief()
                or self.env.user._pbms_is_ceo()
                or line._is_plan_manager_user(self.env.user)
                or self.env.user._pbms_is_sppmd_admin()
                or self.env.is_admin()
                or self.env.su
            )
            if not can_approve:
                raise AccessError(_("Only Respective Chiefs, Managers, or Administrators can approve and escalate plans at this stage."))

            if line.state not in ("chief_review", "district_approved", "district_endorsed"):
                continue

            if hasattr(line, "_compute_category_summaries"):
                line._compute_category_summaries()

            old_state = line.state
            next_state, next_label = line._get_chief_endorse_destination_and_state()
            audit_msg = line.chief_comment or _("Approved and forwarded by Respective Chief (routed to %s).") % next_label

            line.sudo().with_context(bypass_plan_lock=True).write({
                "state": next_state,
                "chief_approver_id": self.env.uid,
                "chief_approval_date": now,
            })
            line.sudo()._log_audit_action("chief_approve_escalate", old_state, next_state, audit_msg)
            line.sudo()._notify_pending_approval(next_state, next_label)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Chief Action Successful'),
                'message': _('Plan has been processed according to configured Chief routing.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            }
        }

    def action_chief_endorse(self):
        return self.action_chief_approve_escalate()
