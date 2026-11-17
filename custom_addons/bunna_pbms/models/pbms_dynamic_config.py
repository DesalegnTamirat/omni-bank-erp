# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models, tools, _
from odoo.exceptions import ValidationError, UserError, AccessError

_logger = logging.getLogger(__name__)


class PbmsPlanningCategoryDefinition(models.Model):
    def init(self):
        super().init()
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS pbms_cat_def_code_active_idx
                ON pbms_planning_category_definition (code, active);
        """)
    """Centralized, dynamic configuration of PBMS Planning Categories.
    Allows administrators to configure, activate, deactivate, and extend planning categories
    without source code changes."""
    _name = "pbms.planning.category.definition"
    _description = "Planning Category Definition"
    _order = "sequence, id"

    name = fields.Char(string="Category Name", required=True, translate=True)
    code = fields.Char(string="Code / Identifier", required=True, index=True)
    sequence = fields.Integer(string="Sequence", default=10)
    description = fields.Text(string="Description / Guidance")
    active = fields.Boolean(string="Active", default=True, index=True)

    measurement_type = fields.Selection(
        [
            ("monetary", "Monetary Target (ETB / FX)"),
            ("integer", "Integer Target (Count / Accounts / Quantity)"),
            ("itemized", "Itemized Resource Requirement"),
        ],
        string="Measurement Type",
        default="monetary",
        required=True,
    )
    icon = fields.Char(string="UI Icon Class", default="fa-folder", help="FontAwesome icon class (e.g. fa-university, fa-users, fa-mobile-alt).")
    is_consolidable = fields.Boolean(
        string="Consolidable Category",
        default=False,
        help="Whether branch plans in this category roll up into a District Overview and Bank-Wide Head Office overview.",
    )
    requires_dropdown_planning = fields.Boolean(
        string="Requires Dropdown Planning",
        default=False,
        help="If enabled, all configured dropdown types (deposit types, channels, etc.) must be planned before submission.",
    )
    workflow_id = fields.Many2one(
        "pbms.workflow.definition",
        string="Approval Workflow",
        help="Custom approval workflow assigned to this planning category. If unset, uses the default workflow.",
    )
    allowed_work_unit_type_ids = fields.Many2many(
        "pbms.work.unit.type",
        "pbms_category_unit_type_rel",
        "category_id",
        "unit_type_id",
        string="Eligible Work Unit Types",
        help="Work unit types (Branch, District, Head Office) for which this planning category is eligible by default.",
    )

    # ----------------------------------------------------
    # Configurable Submission Routing & Reviewer Destination
    # ----------------------------------------------------
    branch_submission_destination = fields.Selection(
        [
            ("default", "Standard Default (District Reviewer)"),
            ("district_reviewer", "District Reviewer (State: submitted)"),
            ("ho_reviewer", "Head Office Functional Reviewer (State: district_endorsed)"),
            ("respective_chief", "Respective Chief Review (State: chief_review)"),
            ("sppmd_approver", "SPPMD Final Approver (State: ho_reviewed)"),
        ],
        string="Branch Submission Destination",
        default="default",
        help="Where plans submitted by Branch operating units route to. Standard default routes to District Reviewer.",
    )
    ho_submission_destination = fields.Selection(
        [
            ("default", "Standard Default (Respective Chief)"),
            ("respective_chief", "Respective Chief Review (State: chief_review)"),
            ("ho_reviewer", "Head Office Functional Reviewer (State: district_endorsed)"),
            ("sppmd_approver", "SPPMD Final Approver (State: approved)"),
        ],
        string="Head Office Submission Destination",
        default="default",
        help="Where plans submitted by Head Office operating units route to. Standard default routes to Respective Chief.",
    )
    district_submission_destination = fields.Selection(
        [
            ("default", "Standard Default (By Category)"),
            ("ho_reviewer", "Head Office Functional Reviewer (State: district_endorsed)"),
            ("respective_chief", "Respective Chief Review (State: chief_review)"),
            ("sppmd_approver", "SPPMD Final Approver (State: approved)"),
        ],
        string="District Office Submission Destination",
        default="default",
        help="Where plans submitted by District Offices for their own units route to.",
    )
    submission_required_privilege_id = fields.Many2one(
        "pbms.privilege",
        string="Required Privilege to Submit",
        help="The privilege a user must possess to submit a plan in this category. Defaults to 'Submit Plan' (priv_submit).",
    )
    destination_required_privilege_id = fields.Many2one(
        "pbms.privilege",
        string="Required Privilege for Next Reviewer",
        help="If set, overrides the required privilege that the destination reviewer must have to review/action the submitted plan.",
    )

    # ----------------------------------------------------
    # Configurable District Action Routing & Privileges
    # ----------------------------------------------------
    district_endorse_destination = fields.Selection(
        [
            ("default", "Standard Default (Head Office Functional Reviewer)"),
            ("ho_reviewer", "Head Office Functional Reviewer (State: district_endorsed)"),
            ("respective_chief", "Respective Chief Review (State: chief_review)"),
            ("sppmd_approver", "SPPMD Final Approver (State: ho_reviewed)"),
            ("final_approved", "Direct Final Approval (State: approved)"),
        ],
        string="District Endorse Destination",
        default="default",
        help="Where plans endorsed by District Reviewers route to. Standard default routes to Head Office Functional Reviewer (district_endorsed).",
    )
    district_endorse_required_privilege_id = fields.Many2one(
        "pbms.privilege",
        string="Required Privilege to Endorse",
        help="Privilege required by District Reviewer to endorse a plan. Defaults to 'District Endorse Plan' (priv_district_endorse).",
    )
    district_endorse_next_privilege_id = fields.Many2one(
        "pbms.privilege",
        string="Privilege Required for Endorsement Recipient",
        help="Privilege required by the recipient who receives the district-endorsed plan (e.g. HO Reviewer or Chief).",
    )

    district_approve_destination = fields.Selection(
        [
            ("default", "Standard Default (By Category)"),
            ("ho_reviewer", "Head Office Functional Reviewer (State: district_approved)"),
            ("respective_chief", "Respective Chief Review (State: chief_review)"),
            ("sppmd_approver", "SPPMD Final Approver (State: ho_reviewed)"),
            ("final_approved", "Direct Final Approval (State: approved)"),
        ],
        string="District Approve Destination",
        default="default",
        help="Where plans approved by District Reviewers route to. Standard default routes to HO Reviewer for resources, and Chief for workforce.",
    )
    district_approve_required_privilege_id = fields.Many2one(
        "pbms.privilege",
        string="Required Privilege to District Approve",
        help="Privilege required by District Reviewer to approve a plan. Defaults to 'District Approve Plan' (priv_district_approve).",
    )
    district_approve_next_privilege_id = fields.Many2one(
        "pbms.privilege",
        string="Privilege Required for District Approval Recipient",
        help="Privilege required by the recipient who receives the district-approved plan.",
    )

    # ----------------------------------------------------
    # Configurable Head Office Action Routing & Privileges
    # ----------------------------------------------------
    ho_approve_destination = fields.Selection(
        [
            ("default", "Standard Default (Final Approved)"),
            ("final_approved", "Final Approved (State: approved)"),
            ("sppmd_approver", "SPPMD Final Approver / Consolidation (State: ho_reviewed)"),
            ("respective_chief", "Respective Chief Review (State: chief_review)"),
        ],
        string="Head Office Approve Destination",
        default="default",
        help="Where plans approved by Head Office Functional Reviewers route to. Standard default routes to Final Approved.",
    )
    ho_approve_required_privilege_id = fields.Many2one(
        "pbms.privilege",
        string="Required Privilege to Head Office Approve",
        help="Privilege required to approve at Head Office level. Defaults to 'Head Office Approve Plan' (priv_ho_approve).",
    )
    ho_approve_next_privilege_id = fields.Many2one(
        "pbms.privilege",
        string="Privilege Required for Next Action (Cascade/Lock)",
        help="Privilege required to cascade or finalize the plan after HO approval. Defaults to 'Cascade Approved Targets' (priv_cascade).",
    )

    # ----------------------------------------------------
    # Configurable Respective Chief Action Routing & Privileges
    # ----------------------------------------------------
    chief_endorse_destination = fields.Selection(
        [
            ("default", "Standard Default (By Category)"),
            ("ho_reviewer", "Head Office Functional Reviewer (State: district_endorsed)"),
            ("people_solutions", "People Solutions Directorate (State: people_solutions_review)"),
            ("cpco", "CPCO Review (State: cpco_review)"),
            ("committee", "Review Committee (State: committee_review)"),
            ("sppmd_approver", "SPPMD Final Approver / Consolidation (State: ho_reviewed)"),
            ("final_approved", "Direct Final Approval (State: approved)"),
        ],
        string="Chief Endorse Destination",
        default="default",
        help="Where plans endorsed by the Respective Chief route to. Standard default routes to People Solutions for Workforce, and Head Office Functional Reviewer for other categories.",
    )
    chief_endorse_required_privilege_id = fields.Many2one(
        "pbms.privilege",
        string="Required Privilege to Chief Endorse",
        help="Privilege required by Respective Chief to endorse/approve plan. Defaults to 'Chief Approve Plan' (priv_chief_approve).",
    )
    chief_endorse_next_privilege_id = fields.Many2one(
        "pbms.privilege",
        string="Privilege Required for Chief Endorsement Recipient",
        help="Privilege required by the recipient who receives the chief-endorsed plan.",
    )

    _code_uniq = models.Constraint("unique(code)", "Planning category code must be unique.")

    @api.model
    def get_category_by_code(self, code):
        """Retrieve category record by code with caching."""
        if not code:
            return self.browse()
        return self.sudo().search([("code", "=", code)], limit=1)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.env.registry.clear_cache()
        return records

    def write(self, vals):
        res = super().write(vals)
        self.env.registry.clear_cache()
        return res

    def unlink(self):
        res = super().unlink()
        self.env.registry.clear_cache()
        return res


class PbmsWorkUnitType(models.Model):
    """Dynamic representation of Work Unit Types for category and workflow eligibility."""
    _name = "pbms.work.unit.type"
    _description = "PBMS Work Unit Type"
    _order = "sequence, id"

    name = fields.Char(string="Work Unit Type Name", required=True)
    code = fields.Char(string="Code", required=True, index=True)
    sequence = fields.Integer(string="Sequence", default=10)
    org_level = fields.Selection(
        [
            ("branch", "Branch Level"),
            ("district", "District Level"),
            ("head_office", "Head Office Level"),
            ("other", "Other / Specialized"),
        ],
        string="Organizational Level",
        default="branch",
        required=True,
    )
    active = fields.Boolean(string="Active", default=True)

    _code_uniq = models.Constraint("unique(code)", "Work unit type code must be unique.")


class PbmsPrivilege(models.Model):
    def init(self):
        super().init()
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS pbms_privilege_action_active_idx
                ON pbms_privilege (action_type, active);
            CREATE INDEX IF NOT EXISTS pbms_privilege_code_active_idx
                ON pbms_privilege (code, active);
        """)
    """Granular PBMS Privileges controlling planning actions and permissions."""
    _name = "pbms.privilege"
    _description = "PBMS Privilege"
    _order = "sequence, id"

    name = fields.Char(string="Privilege Name", required=True, translate=True)
    code = fields.Char(string="Privilege Code", required=True, index=True)
    sequence = fields.Integer(string="Sequence", default=10)
    action_type = fields.Selection(
        [
            ("view", "View / Read Plan"),
            ("create", "Create Plan"),
            ("edit", "Edit Content / Financial Data"),
            ("delete", "Delete Plan"),
            ("submit", "Submit Plan"),
            ("district_edit", "District Edit Annual Total"),
            ("district_review", "District Review & Edit"),
            ("district_approve", "District Approve"),
            ("district_endorse", "District Endorse"),
            ("district_return", "District Return"),
            ("ho_edit", "Head Office Edit Annual Total"),
            ("ho_review", "Head Office Functional Review"),
            ("ho_approve", "Head Office Approve"),
            ("ho_endorse", "Head Office Endorse"),
            ("ho_return", "Head Office Return"),
            ("chief_review", "Respective Chief Review"),
            ("chief_approve", "Respective Chief Approve"),
            ("people_solutions_review", "People Solutions Review"),
            ("ps_approve", "People Solutions Approve"),
            ("cpco_review", "CPCO Review"),
            ("cpco_approve", "CPCO Approve"),
            ("committee_review", "Budget Hiring Committee Review"),
            ("committee_approve", "Budget Hiring Committee Approve"),
            ("ceo_approval", "CEO / Executive Approval"),
            ("ceo_approve", "CEO Approve"),
            ("final_approve", "SPPMD Final Approval"),
            ("return_plan", "Return for Revision"),
            ("request_info", "Request Information"),
            ("recommend_rejection", "Recommend Rejection"),
            ("reject_plan", "Reject Plan"),
            ("cascade", "Cascade Targets"),
            ("cascade_target", "Cascade Targets"),
            ("export_excel", "Export to Excel"),
            ("import_excel", "Import from Excel"),
            ("other", "Other / Custom Action"),
        ],
        string="Action Type",
        required=True,
        index=True,
    )
    description = fields.Text(string="Description & Scope")
    color = fields.Integer(string="Color Index", default=0)
    active = fields.Boolean(string="Active", default=True, index=True)

    _code_uniq = models.Constraint("unique(code)", "Privilege code must be unique.")


class PbmsRoleDefinition(models.Model):
    def init(self):
        super().init()
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS pbms_role_def_code_active_idx
                ON pbms_role_definition (code, active);
            CREATE INDEX IF NOT EXISTS pbms_role_def_active_level_idx
                ON pbms_role_definition (active, org_level);
        """)
    """Configurable Organizational Planning Roles consolidating privileges."""
    _name = "pbms.role.definition"
    _description = "Planning Role & Responsibilities"
    _order = "sequence, id"

    name = fields.Char(string="Role Name", required=True, translate=True)
    code = fields.Char(string="Role Code", required=True, index=True)
    sequence = fields.Integer(string="Sequence", default=10)
    org_level = fields.Selection(
        [
            ("branch", "Branch Level"),
            ("district", "District Level"),
            ("head_office", "Head Office Level"),
            ("ho", "Head Office Level"),
            ("functional_dept", "Functional Directorate"),
            ("executive", "Executive / CEO / Board"),
            ("all", "All Organizational Levels"),
        ],
        string="Organizational Level",
        default="branch",
        required=True,
    )
    description = fields.Text(string="Responsibilities Description")
    privilege_ids = fields.Many2many(
        "pbms.privilege",
        "pbms_role_privilege_rel",
        "role_id",
        "privilege_id",
        string="Granted Privileges",
    )
    group_ids = fields.Many2many(
        "res.groups",
        "pbms_role_group_rel",
        "role_id",
        "group_id",
        string="Associated Security Groups",
        help="Users in these Odoo security groups automatically inherit this role's privileges.",
    )
    category_ids = fields.Many2many(
        "pbms.planning.category.definition",
        "pbms_role_category_rel",
        "role_id",
        "category_id",
        string="Authorized Categories",
        help="If specified, this role's privileges are restricted to these planning categories. If empty, applies to all categories.",
    )
    active = fields.Boolean(string="Active", default=True, index=True)

    _code_uniq = models.Constraint("unique(code)", "Role code must be unique.")

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.env.registry.clear_cache()
        return records

    def write(self, vals):
        res = super().write(vals)
        self.env.registry.clear_cache()
        return res

    def unlink(self):
        res = super().unlink()
        self.env.registry.clear_cache()
        return res


class PbmsPrivilegeAssignment(models.Model):
    def init(self):
        super().init()
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS pbms_priv_assign_active_grant_priv_idx
                ON pbms_privilege_assignment (active, grant_type, privilege_id);
            CREATE INDEX IF NOT EXISTS pbms_priv_assign_active_user_idx
                ON pbms_privilege_assignment (active, user_id);
            CREATE INDEX IF NOT EXISTS pbms_priv_assign_active_group_idx
                ON pbms_privilege_assignment (active, group_id);
            CREATE INDEX IF NOT EXISTS pbms_priv_assign_active_job_idx
                ON pbms_privilege_assignment (active, job_id);
            CREATE INDEX IF NOT EXISTS pbms_priv_assign_active_role_idx
                ON pbms_privilege_assignment (active, role_id);
            CREATE INDEX IF NOT EXISTS pbms_priv_assign_active_ou_idx
                ON pbms_privilege_assignment (active, org_unit_id);
        """)
    """Direct Privilege Assignment to Users, Security Groups, HR Job Positions, or Units."""
    _name = "pbms.privilege.assignment"
    _description = "Privilege Assignment"
    _order = "id desc"

    name = fields.Char(string="Assignment Name", compute="_compute_name", store=True)
    privilege_id = fields.Many2one("pbms.privilege", string="Privilege", required=False, index=True, ondelete="cascade")
    privilege_ids = fields.Many2many(
        "pbms.privilege",
        "pbms_priv_assign_multi_priv_rel",
        "assignment_id",
        "privilege_id",
        string="Additional Privileges",
        help="Optional: grant or deny multiple specific privileges at once.",
    )
    role_id = fields.Many2one("pbms.role.definition", string="Role Reference", index=True, ondelete="set null")
    
    # Target actors
    user_id = fields.Many2one("res.users", string="Specific User", index=True, ondelete="cascade")
    group_id = fields.Many2one("res.groups", string="Security Group", index=True, ondelete="cascade")
    job_id = fields.Many2one("hr.job", string="HR Job Position", index=True, ondelete="cascade")
    org_unit_id = fields.Many2one("operating.unit", string="Specific Operating Unit", index=True, ondelete="cascade")

    # Scope filters
    org_level = fields.Selection(
        [
            ("all", "All Levels"),
            ("branch", "Branch Level Only"),
            ("district", "District Level Only"),
            ("head_office", "Head Office Only"),
            ("ho", "Head Office Only"),
        ],
        string="Org Level Restriction",
        default="all",
        required=True,
    )
    category_ids = fields.Many2many(
        "pbms.planning.category.definition",
        "pbms_priv_assign_category_rel",
        "assignment_id",
        "category_id",
        string="Planning Categories",
        help="Leave empty for all planning categories.",
    )
    grant_type = fields.Selection(
        [
            ("allow", "Grant Privilege (Allow)"),
            ("deny", "Revoke / Restrict (Deny)"),
        ],
        string="Grant Type",
        default="allow",
        required=True,
    )
    active = fields.Boolean(string="Active", default=True, index=True)

    @api.constrains("privilege_id", "privilege_ids", "role_id")
    def _check_privilege_or_role(self):
        for rec in self:
            if not rec.privilege_id and not rec.privilege_ids and not rec.role_id:
                raise ValidationError(_("Please specify at least a Privilege, Additional Privileges, or a Role Reference."))

    @api.depends("privilege_id", "privilege_ids", "user_id", "group_id", "job_id", "role_id", "grant_type")
    def _compute_name(self):
        for rec in self:
            priv_names = []
            if rec.privilege_id:
                priv_names.append(rec.privilege_id.name)
            if hasattr(rec, "privilege_ids") and rec.privilege_ids:
                for p in rec.privilege_ids:
                    if p.name not in priv_names:
                        priv_names.append(p.name)
            if priv_names:
                priv_name = ", ".join(priv_names[:3])
                if len(priv_names) > 3:
                    priv_name += f" (+{len(priv_names) - 3})"
            elif rec.role_id:
                priv_name = rec.role_id.name
            else:
                priv_name = _("Unknown Privilege")
            target = ""
            if rec.user_id:
                target = f"User: {rec.user_id.name}"
            elif rec.group_id:
                target = f"Group: {rec.group_id.name}"
            elif rec.job_id:
                target = f"Job: {rec.job_id.name}"
            elif rec.role_id:
                target = f"Role: {rec.role_id.name}"
            elif rec.org_unit_id:
                target = f"Unit: {rec.org_unit_id.name}"
            else:
                target = _("Global")
            mode = "[ALLOW]" if rec.grant_type == "allow" else "[DENY]"
            rec.name = f"{mode} {priv_name} -> {target}"

    def _sync_user_security_groups(self):
        """Automatically synchronize Odoo security groups and operating units when a privilege or role is assigned to a user."""
        action_group_map = {
            "view": "bunna_pbms.group_pbms_branch_user",
            "create": "bunna_pbms.group_pbms_branch_user",
            "edit": "bunna_pbms.group_pbms_branch_user",
            "delete": "bunna_pbms.group_pbms_branch_user",
            "submit": "bunna_pbms.group_pbms_branch_user",
            "export_excel": "bunna_pbms.group_pbms_branch_user",
            "import_excel": "bunna_pbms.group_pbms_branch_user",
            "district_edit": "bunna_pbms.group_pbms_district_reviewer",
            "district_review": "bunna_pbms.group_pbms_district_reviewer",
            "district_approve": "bunna_pbms.group_pbms_district_reviewer",
            "district_endorse": "bunna_pbms.group_pbms_district_reviewer",
            "district_return": "bunna_pbms.group_pbms_district_reviewer",
            "ho_edit": "bunna_pbms.group_pbms_ho_reviewer",
            "ho_review": "bunna_pbms.group_pbms_ho_reviewer",
            "ho_approve": "bunna_pbms.group_pbms_ho_reviewer",
            "ho_endorse": "bunna_pbms.group_pbms_ho_reviewer",
            "ho_return": "bunna_pbms.group_pbms_ho_reviewer",
            "chief_review": "bunna_pbms.group_pbms_respective_chief",
            "chief_approve": "bunna_pbms.group_pbms_respective_chief",
            "people_solutions_review": "bunna_pbms.group_pbms_people_solutions",
            "ps_approve": "bunna_pbms.group_pbms_people_solutions",
            "cpco_review": "bunna_pbms.group_pbms_cpco",
            "cpco_approve": "bunna_pbms.group_pbms_cpco",
            "committee_review": "bunna_pbms.group_pbms_budget_hiring_committee",
            "committee_approve": "bunna_pbms.group_pbms_budget_hiring_committee",
            "ceo_approval": "bunna_pbms.group_pbms_ceo",
            "ceo_approve": "bunna_pbms.group_pbms_ceo",
            "final_approve": "bunna_pbms.group_pbms_approver",
            "cascade": "bunna_pbms.group_pbms_approver",
            "cascade_target": "bunna_pbms.group_pbms_approver",
        }
        branch_group = self.env.ref("bunna_pbms.group_pbms_branch_user", raise_if_not_found=False)
        for rec in self:
            if not rec.user_id:
                continue
            groups_to_add = self.env["res.groups"]
            if rec.grant_type == "allow" and rec.active and branch_group:
                groups_to_add |= branch_group

            if rec.role_id:
                if rec.role_id.group_ids:
                    groups_to_add |= rec.role_id.group_ids
                for p in rec.role_id.privilege_ids:
                    if p.action_type:
                        xml_id = action_group_map.get(p.action_type)
                        if xml_id:
                            grp = self.env.ref(xml_id, raise_if_not_found=False)
                            if grp:
                                groups_to_add |= grp

            if rec.privilege_id and rec.privilege_id.action_type:
                xml_id = action_group_map.get(rec.privilege_id.action_type)
                if xml_id:
                    grp = self.env.ref(xml_id, raise_if_not_found=False)
                    if grp:
                        groups_to_add |= grp

            if hasattr(rec, "privilege_ids") and rec.privilege_ids:
                for p in rec.privilege_ids:
                    if p.action_type:
                        xml_id = action_group_map.get(p.action_type)
                        if xml_id:
                            grp = self.env.ref(xml_id, raise_if_not_found=False)
                            if grp:
                                groups_to_add |= grp

            if groups_to_add and rec.grant_type == "allow" and rec.active:
                rec.user_id.sudo().write({"group_ids": [(4, g.id) for g in groups_to_add]})
            if rec.org_unit_id and rec.grant_type == "allow" and rec.active:
                if rec.org_unit_id not in rec.user_id.operating_unit_ids:
                    rec.user_id.sudo().write({"operating_unit_ids": [(4, rec.org_unit_id.id)]})

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_user_security_groups()
        self.env.registry.clear_cache()
        return records

    def write(self, vals):
        res = super().write(vals)
        self._sync_user_security_groups()
        self.env.registry.clear_cache()
        return res

    def unlink(self):
        res = super().unlink()
        self.env.registry.clear_cache()
        return res


class PbmsWorkflowDefinition(models.Model):
    """Dynamic Planning Approval Workflow Definition."""
    _name = "pbms.workflow.definition"
    _description = "Planning Approval Workflow"
    _order = "sequence, id"

    name = fields.Char(string="Workflow Name", required=True, translate=True)
    code = fields.Char(string="Workflow Code", required=True, index=True)
    sequence = fields.Integer(string="Sequence", default=10)
    description = fields.Text(string="Description & Workflow Purpose")
    active = fields.Boolean(string="Active", default=True, index=True)
    category_ids = fields.One2many(
        "pbms.planning.category.definition",
        "workflow_id",
        string="Assigned Planning Categories",
    )
    step_ids = fields.One2many(
        "pbms.workflow.step",
        "workflow_id",
        string="Workflow Steps",
        copy=True,
    )

    _code_uniq = models.Constraint("unique(code)", "Workflow code must be unique.")


class PbmsWorkflowStep(models.Model):
    def init(self):
        super().init()
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS pbms_wf_step_wf_state_idx
                ON pbms_workflow_step (workflow_id, state);
            CREATE INDEX IF NOT EXISTS pbms_wf_step_wf_seq_idx
                ON pbms_workflow_step (workflow_id, sequence);
        """)
    """Single Stage / Step within an Approval Workflow."""
    _name = "pbms.workflow.step"
    _description = "Approval Workflow Step"
    _order = "sequence, id"

    workflow_id = fields.Many2one("pbms.workflow.definition", string="Workflow", required=True, index=True, ondelete="cascade")
    sequence = fields.Integer(string="Step Sequence", default=10)
    name = fields.Char(string="Step Name", required=True, translate=True)
    state = fields.Char(
        string="Plan State Code",
        required=True,
        index=True,
        help="The technical state string of the plan at this step (e.g. draft, submitted, chief_review, district_approved, district_endorsed, people_solutions_review, cpco_review, committee_review, ceo_approval, ho_reviewed, approved, rejected, returned, info_requested).",
    )
    org_level = fields.Selection(
        [
            ("branch", "Branch"),
            ("district", "District"),
            ("head_office", "Head Office"),
            ("ho", "Head Office"),
            ("functional_dept", "Functional Directorate"),
            ("committee", "Review Committee"),
            ("executive", "Executive / CEO / Board"),
            ("all", "All Levels"),
        ],
        string="Responsible Organizational Level",
        default="branch",
        required=True,
    )
    role_id = fields.Many2one("pbms.role.definition", string="Responsible Role")
    responsible_group_id = fields.Many2one("res.groups", string="Responsible Security Group")
    required_privilege_id = fields.Many2one("pbms.privilege", string="Required Privilege to Act")
    can_edit_content = fields.Boolean(
        string="Content Editable at this Step",
        default=False,
        help="Whether financial/target figures and requirement lines can be modified by authorized actors at this step.",
    )
    is_start_step = fields.Boolean(string="Is Initial / Start Step", default=False)
    is_final_step = fields.Boolean(string="Is Approved / Final Step", default=False)
    transition_ids = fields.One2many(
        "pbms.workflow.transition",
        "step_id",
        string="Outgoing Actions & Transitions",
        copy=True,
    )


class PbmsWorkflowTransition(models.Model):
    def init(self):
        super().init()
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS pbms_wf_trans_step_action_idx
                ON pbms_workflow_transition (step_id, action_type, active);
            CREATE INDEX IF NOT EXISTS pbms_wf_trans_step_method_idx
                ON pbms_workflow_transition (step_id, action_method, active);
        """)
    """Outgoing Action and State Transition from a Workflow Step."""
    _name = "pbms.workflow.transition"
    _description = "Workflow Action Transition"
    _order = "sequence, id"

    step_id = fields.Many2one("pbms.workflow.step", string="Origin Step", required=True, index=True, ondelete="cascade")
    sequence = fields.Integer(string="Sequence", default=10)
    name = fields.Char(string="Action Label / Button Text", required=True, translate=True)
    action_type = fields.Selection(
        [
            ("submit", "Submit Plan"),
            ("approve", "Approve Plan"),
            ("endorse", "Endorse Plan"),
            ("district_approve", "District Approve"),
            ("district_endorse", "District Endorse"),
            ("chief_approve", "Respective Chief Approve & Escalate"),
            ("people_solutions_escalate", "People Solutions Escalate to CPCO"),
            ("ps_approve", "People Solutions Approve"),
            ("cpco_submit_committee", "CPCO Submit to Committee"),
            ("cpco_submit_ceo", "CPCO Submit to CEO / Board"),
            ("cpco_approve", "CPCO Approve"),
            ("committee_approve", "Committee Approve"),
            ("ceo_approve", "CEO Approve"),
            ("ho_review", "Head Office Review"),
            ("ho_approve", "Head Office Final Approve"),
            ("final_approve", "SPPMD Final Approve"),
            ("return", "Return for Revision"),
            ("request_info", "Request Information"),
            ("recommend_rejection", "Recommend Rejection"),
            ("reject", "Reject Plan"),
        ],
        string="Action Type",
        required=True,
    )
    action_method = fields.Char(
        string="Python Method Name",
        default="action_submit",
        help="The Python method triggered on the plan model (e.g. action_submit, action_district_approve, action_ho_approve, action_return, action_reject).",
    )
    target_step_id = fields.Many2one("pbms.workflow.step", string="Destination Step", required=True)
    target_state = fields.Char(related="target_step_id.state", string="Destination State", readonly=True)
    required_privilege_id = fields.Many2one("pbms.privilege", string="Required Privilege to Execute")
    condition_category_ids = fields.Many2many(
        "pbms.planning.category.definition",
        "pbms_transition_category_rel",
        "transition_id",
        "category_id",
        string="Condition: Categories",
        help="If set, this transition is only available for these planning categories.",
    )
    condition_org_level = fields.Selection(
        [
            ("all", "All Organizational Levels"),
            ("branch", "Branch Units Only"),
            ("district", "District Units Only"),
            ("head_office", "Head Office Units Only"),
            ("ho", "Head Office Units Only"),
        ],
        string="Condition: Unit Level",
        default="all",
        required=True,
    )
    button_style = fields.Selection(
        [
            ("primary", "Primary (Highlight)"),
            ("secondary", "Secondary (Default)"),
            ("success", "Success (Green)"),
            ("danger", "Danger (Red)"),
            ("btn-primary", "Primary (Button)"),
            ("btn-secondary", "Secondary (Button)"),
            ("btn-success", "Success (Button)"),
            ("btn-danger", "Danger (Button)"),
        ],
        string="Button UI Style",
        default="secondary",
    )
    active = fields.Boolean(string="Active", default=True, index=True)
