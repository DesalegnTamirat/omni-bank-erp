# -*- coding: utf-8 -*-
# Committee Approval Role Configuration
# Configurable committee roles across Transfer Vacancies, Promotion Vacancies, and External Vacancies

from odoo import api, fields, models, _

class CommitteeRoleConfig(models.Model):
    _name = "committee.role.config"
    _description = "Committee Approval Role Configuration"
    _order = "sequence, id"

    name = fields.Char(string="Configuration Name", required=True)
    sequence = fields.Integer(string="Sequence", default=10)
    active = fields.Boolean(default=True)

    approval_hierarchy_type = fields.Selection(
        [
            ("ho_district_grade2_plus", "Head Office & District Grade II and above"),
            ("non_managerial_ho", "For all non-managerial head office"),
            ("non_managerial_district", "For all non-managerial district"),
        ],
        string="Approval Hierarchy Category",
        required=True,
        index=True,
    )

    scope = fields.Selection(
        [
            ("all", "All Vacancies & Transfers (Default)"),
            ("transfer", "Transfer Vacancy & Lateral Transfer Only"),
            ("internal", "Promotion / Internal Vacancy Only"),
            ("external", "External Vacancy Only"),
        ],
        string="Application Scope",
        default="all",
        required=True,
        help="Defines whether this role configuration applies across all committee minute types or specifically to one type.",
    )

    # 1. Chairperson Role Config
    chairperson_title = fields.Char(
        string="Chairperson Title / Designation",
        required=True,
        default="Chairperson",
    )
    chairperson_job_ids = fields.Many2many(
        "hr.job",
        "committee_cfg_chairperson_job_rel",
        "config_id",
        "job_id",
        string="Allowed Chairperson Job Positions",
        help="Employees holding any of these job positions will be eligible to be selected as Chairperson.",
    )
    chairperson_employee_ids = fields.Many2many(
        "hr.employee",
        "committee_cfg_chairperson_emp_rel",
        "config_id",
        "employee_id",
        string="Allowed Chairperson Employees",
        help="Explicitly authorized employees for the Chairperson role.",
    )

    # 2. Panel Member Role Config
    panel_member_title = fields.Char(
        string="Panel Member Title / Designation",
        required=True,
        default="Panel Member",
    )
    panel_member_job_ids = fields.Many2many(
        "hr.job",
        "committee_cfg_panel_job_rel",
        "config_id",
        "job_id",
        string="Allowed Panel Member Job Positions",
        help="Employees holding any of these job positions will be eligible to be selected as Panel Member.",
    )
    panel_member_employee_ids = fields.Many2many(
        "hr.employee",
        "committee_cfg_panel_emp_rel",
        "config_id",
        "employee_id",
        string="Allowed Panel Member Employees",
        help="Explicitly authorized employees for the Panel Member role.",
    )
    panel_member_is_unit_head = fields.Boolean(
        string="Include Work Unit / District Head",
        default=False,
        help="If enabled, the Director or Manager of the target Operating Unit / Department will also be allowed.",
    )

    # 3. Panel Member & Secretary Role Config
    secretary_title = fields.Char(
        string="Secretary Title / Designation",
        required=True,
        default="Panel Member & Secretary",
    )
    secretary_job_ids = fields.Many2many(
        "hr.job",
        "committee_cfg_secretary_job_rel",
        "config_id",
        "job_id",
        string="Allowed Secretary Job Positions",
        help="Employees holding any of these job positions will be eligible to be selected as Secretary.",
    )
    secretary_employee_ids = fields.Many2many(
        "hr.employee",
        "committee_cfg_secretary_emp_rel",
        "config_id",
        "employee_id",
        string="Allowed Secretary Employees",
        help="Explicitly authorized employees for the Secretary role.",
    )

    # 4. Labor Representative (Observer) Role Config
    observer_title = fields.Char(
        string="Observer Title / Designation",
        default="Labor Representative (Observer)",
    )
    observer_job_ids = fields.Many2many(
        "hr.job",
        "committee_cfg_observer_job_rel",
        "config_id",
        "job_id",
        string="Allowed Observer Job Positions",
        help="Employees holding any of these job positions will be eligible as Observer.",
    )
    observer_employee_ids = fields.Many2many(
        "hr.employee",
        "committee_cfg_observer_emp_rel",
        "config_id",
        "employee_id",
        string="Allowed Observer Employees",
        help="Explicitly authorized employees for the Observer role.",
    )

    # Dynamic Domain Fields (Computed)
    chairperson_job_domain = fields.Binary(compute="_compute_chairperson_domains")
    chairperson_employee_domain = fields.Binary(compute="_compute_chairperson_domains")

    panel_member_job_domain = fields.Binary(compute="_compute_panel_member_domains")
    panel_member_employee_domain = fields.Binary(compute="_compute_panel_member_domains")

    secretary_job_domain = fields.Binary(compute="_compute_secretary_domains")
    secretary_employee_domain = fields.Binary(compute="_compute_secretary_domains")

    observer_job_domain = fields.Binary(compute="_compute_observer_domains")
    observer_employee_domain = fields.Binary(compute="_compute_observer_domains")

    # --- Domain Computations ---
    @api.depends("chairperson_job_ids", "chairperson_employee_ids")
    def _compute_chairperson_domains(self):
        for rec in self:
            if rec.chairperson_job_ids:
                rec.chairperson_employee_domain = [
                    ("job_id", "in", rec.chairperson_job_ids.ids),
                    ("active", "=", True),
                ]
            else:
                rec.chairperson_employee_domain = [("active", "=", True)]

            if rec.chairperson_employee_ids:
                emp_jobs = rec.chairperson_employee_ids.mapped("job_id")
                rec.chairperson_job_domain = [("id", "in", emp_jobs.ids)]
            else:
                rec.chairperson_job_domain = []

    @api.depends("panel_member_job_ids", "panel_member_employee_ids")
    def _compute_panel_member_domains(self):
        for rec in self:
            if rec.panel_member_job_ids:
                rec.panel_member_employee_domain = [
                    ("job_id", "in", rec.panel_member_job_ids.ids),
                    ("active", "=", True),
                ]
            else:
                rec.panel_member_employee_domain = [("active", "=", True)]

            if rec.panel_member_employee_ids:
                emp_jobs = rec.panel_member_employee_ids.mapped("job_id")
                rec.panel_member_job_domain = [("id", "in", emp_jobs.ids)]
            else:
                rec.panel_member_job_domain = []

    @api.depends("secretary_job_ids", "secretary_employee_ids")
    def _compute_secretary_domains(self):
        for rec in self:
            if rec.secretary_job_ids:
                rec.secretary_employee_domain = [
                    ("job_id", "in", rec.secretary_job_ids.ids),
                    ("active", "=", True),
                ]
            else:
                rec.secretary_employee_domain = [("active", "=", True)]

            if rec.secretary_employee_ids:
                emp_jobs = rec.secretary_employee_ids.mapped("job_id")
                rec.secretary_job_domain = [("id", "in", emp_jobs.ids)]
            else:
                rec.secretary_job_domain = []

    @api.depends("observer_job_ids", "observer_employee_ids")
    def _compute_observer_domains(self):
        for rec in self:
            if rec.observer_job_ids:
                rec.observer_employee_domain = [
                    ("job_id", "in", rec.observer_job_ids.ids),
                    ("active", "=", True),
                ]
            else:
                rec.observer_employee_domain = [("active", "=", True)]

            if rec.observer_employee_ids:
                emp_jobs = rec.observer_employee_ids.mapped("job_id")
                rec.observer_job_domain = [("id", "in", emp_jobs.ids)]
            else:
                rec.observer_job_domain = []

    # --- Bidirectional Dynamic Filtering & Sync ---
    @api.onchange("chairperson_job_ids")
    def _onchange_chairperson_job_ids(self):
        if self.chairperson_job_ids:
            matching_emps = self.env["hr.employee"].search([
                ("job_id", "in", self.chairperson_job_ids.ids),
                ("active", "=", True),
            ])
            self.chairperson_employee_ids = matching_emps
        else:
            self.chairperson_employee_ids = False

    @api.onchange("chairperson_employee_ids")
    def _onchange_chairperson_employee_ids(self):
        if self.chairperson_employee_ids:
            emp_jobs = self.chairperson_employee_ids.mapped("job_id")
            if emp_jobs:
                self.chairperson_job_ids = emp_jobs

    @api.onchange("panel_member_job_ids")
    def _onchange_panel_member_job_ids(self):
        if self.panel_member_job_ids:
            matching_emps = self.env["hr.employee"].search([
                ("job_id", "in", self.panel_member_job_ids.ids),
                ("active", "=", True),
            ])
            self.panel_member_employee_ids = matching_emps
        else:
            self.panel_member_employee_ids = False

    @api.onchange("panel_member_employee_ids")
    def _onchange_panel_member_employee_ids(self):
        if self.panel_member_employee_ids:
            emp_jobs = self.panel_member_employee_ids.mapped("job_id")
            if emp_jobs:
                self.panel_member_job_ids = emp_jobs

    @api.onchange("secretary_job_ids")
    def _onchange_secretary_job_ids(self):
        if self.secretary_job_ids:
            matching_emps = self.env["hr.employee"].search([
                ("job_id", "in", self.secretary_job_ids.ids),
                ("active", "=", True),
            ])
            self.secretary_employee_ids = matching_emps
        else:
            self.secretary_employee_ids = False

    @api.onchange("secretary_employee_ids")
    def _onchange_secretary_employee_ids(self):
        if self.secretary_employee_ids:
            emp_jobs = self.secretary_employee_ids.mapped("job_id")
            if emp_jobs:
                self.secretary_job_ids = emp_jobs

    @api.onchange("observer_job_ids")
    def _onchange_observer_job_ids(self):
        if self.observer_job_ids:
            matching_emps = self.env["hr.employee"].search([
                ("job_id", "in", self.observer_job_ids.ids),
                ("active", "=", True),
            ])
            self.observer_employee_ids = matching_emps
        else:
            self.observer_employee_ids = False

    @api.onchange("observer_employee_ids")
    def _onchange_observer_employee_ids(self):
        if self.observer_employee_ids:
            emp_jobs = self.observer_employee_ids.mapped("job_id")
            if emp_jobs:
                self.observer_job_ids = emp_jobs

    def _auto_init(self):
        res = super()._auto_init()
        try:
            self._seed_default_configs()
        except Exception:
            pass
        return res

    def _seed_default_configs(self):
        Job = self.env["hr.job"]
        Employee = self.env["hr.employee"]

        cpco_jobs = Job.search([("name", "ilike", "Chief People")])
        dir_people_jobs = Job.search([("name", "ilike", "Director-People")])
        all_dir_jobs = Job.search([("name", "ilike", "Director")])
        principal_hr_jobs = Job.search([("name", "ilike", "Principal"), ("name", "ilike", "People")])
        if not principal_hr_jobs:
            principal_hr_jobs = Job.search([("name", "ilike", "Principal")])
        district_dir_jobs = Job.search([("name", "ilike", "Director"), ("name", "ilike", "District")])

        cpco_emps = Employee.search([("job_id", "in", cpco_jobs.ids), ("active", "=", True)])
        dir_people_emps = Employee.search([("job_id", "in", dir_people_jobs.ids), ("active", "=", True)])
        principal_emps = Employee.search([("job_id", "in", principal_hr_jobs.ids), ("active", "=", True)])
        district_dir_emps = Employee.search([("job_id", "in", district_dir_jobs.ids), ("active", "=", True)])

        # 1. Head Office & District Grade II and above
        cfg1 = self.search([("name", "ilike", "Grade II")], limit=1)
        vals1 = {
            "name": "Head office and District Grade II and above",
            "sequence": 10,
            "approval_hierarchy_type": "ho_district_grade2_plus",
            "scope": "all",
            "chairperson_title": "Chief People and Culture Officer (Chairperson)",
            "chairperson_job_ids": [(6, 0, cpco_jobs.ids)],
            "chairperson_employee_ids": [(6, 0, cpco_emps.ids)],
            "panel_member_title": "Respective senior management (Panel Member)",
            "panel_member_job_ids": [(6, 0, all_dir_jobs.ids)],
            "panel_member_is_unit_head": True,
            "secretary_title": "Director people operation management Directorate (Panel Member & Secretary)",
            "secretary_job_ids": [(6, 0, dir_people_jobs.ids)],
            "secretary_employee_ids": [(6, 0, dir_people_emps.ids)],
            "observer_title": "Labor Representative (Observer)",
        }
        if not cfg1:
            self.create(vals1)

        # 2. For all non-managerial head office
        cfg2 = self.search([("name", "ilike", "non-managerial head office")], limit=1)
        vals2 = {
            "name": "For all non-managerial head office",
            "sequence": 20,
            "approval_hierarchy_type": "non_managerial_ho",
            "scope": "all",
            "chairperson_title": "Director people operation management Directorate (Chairperson)",
            "chairperson_job_ids": [(6, 0, dir_people_jobs.ids)],
            "chairperson_employee_ids": [(6, 0, dir_people_emps.ids)],
            "panel_member_title": "Head office /District director (Panel Member)",
            "panel_member_job_ids": [(6, 0, all_dir_jobs.ids)],
            "panel_member_is_unit_head": True,
            "secretary_title": "Principal HR (Panel Member & Secretary)",
            "secretary_job_ids": [(6, 0, principal_hr_jobs.ids)],
            "secretary_employee_ids": [(6, 0, principal_emps.ids[:10])],
            "observer_title": "Labor Representative (Observer)",
        }
        if not cfg2:
            self.create(vals2)

        # 3. For all non-managerial district
        cfg3 = self.search([("name", "ilike", "non-managerial district")], limit=1)
        vals3 = {
            "name": "For all non-managerial district",
            "sequence": 30,
            "approval_hierarchy_type": "non_managerial_district",
            "scope": "all",
            "chairperson_title": "District Director (Chairperson)",
            "chairperson_job_ids": [(6, 0, district_dir_jobs.ids or all_dir_jobs.ids)],
            "chairperson_employee_ids": [(6, 0, district_dir_emps.ids)],
            "panel_member_title": "District Division Member (Panel Member)",
            "panel_member_job_ids": [(6, 0, Job.search([("name", "ilike", "Division")]).ids[:20])],
            "panel_member_is_unit_head": True,
            "secretary_title": "Principal HR (Panel Member & Secretary)",
            "secretary_job_ids": [(6, 0, principal_hr_jobs.ids)],
            "secretary_employee_ids": [(6, 0, principal_emps.ids[:10])],
            "observer_title": "Labor Representative (Observer)",
        }
        if not cfg3:
            self.create(vals3)

    @api.model
    def get_config_for_hierarchy(self, hierarchy_type, scope=None):
        """Find the matching active configuration record for the given hierarchy category and scope."""
        domain = [
            ("approval_hierarchy_type", "=", hierarchy_type),
            ("active", "=", True),
        ]
        if scope and scope != "all":
            cfg = self.search(domain + [("scope", "=", scope)], limit=1)
            if cfg:
                return cfg
        cfg = self.search(domain + [("scope", "=", "all")], limit=1)
        if cfg:
            return cfg
        return self.search(domain, limit=1)

    def get_allowed_users_for_role(self, role_type, operating_unit=None, department=None):
        """Returns recordset of allowed res.users for a given role:
        chairperson, panel_member, secretary, observer."""
        self.ensure_one()
        user_model = self.env["res.users"]
        employee_model = self.env["hr.employee"]

        allowed_users = user_model.browse()

        if role_type == "chairperson":
            employees = self.chairperson_employee_ids
            jobs = self.chairperson_job_ids
        elif role_type == "panel_member":
            employees = self.panel_member_employee_ids
            jobs = self.panel_member_job_ids
        elif role_type == "secretary":
            employees = self.secretary_employee_ids
            jobs = self.secretary_job_ids
        elif role_type == "observer":
            employees = self.observer_employee_ids
            jobs = self.observer_job_ids
        else:
            return allowed_users

        # 1. Add users from explicitly configured employees
        if employees:
            for emp in employees:
                if emp.user_id and emp.user_id.active:
                    allowed_users |= emp.user_id
                else:
                    u = user_model.sudo().search([
                        "|", "|",
                        ("employee_id", "=", emp.id),
                        ("partner_id", "=", emp.work_contact_id.id if emp.work_contact_id else False),
                        ("login", "=ilike", emp.work_email or emp.private_email or "")
                    ], limit=1)
                    if u and u.active:
                        allowed_users |= u
        # 2. Else if jobs are configured (and no specific employees configured)
        elif jobs:
            job_emps = employee_model.search([
                ("job_id", "in", jobs.ids),
                ("active", "=", True),
            ])
            for emp in job_emps:
                if emp.user_id and emp.user_id.active:
                    allowed_users |= emp.user_id
                else:
                    u = user_model.sudo().search([
                        "|", "|",
                        ("employee_id", "=", emp.id),
                        ("partner_id", "=", emp.work_contact_id.id if emp.work_contact_id else False),
                        ("login", "=ilike", emp.work_email or emp.private_email or "")
                    ], limit=1)
                    if u and u.active:
                        allowed_users |= u

        # 3. If panel member has unit head enabled
        if role_type == "panel_member" and self.panel_member_is_unit_head:
            if department and department.manager_id and department.manager_id.user_id:
                allowed_users |= department.manager_id.user_id
            if operating_unit:
                ou_emps = employee_model.search([
                    ("operating_unit_id", "=", operating_unit.id),
                    ("user_id", "!=", False),
                    ("active", "=", True),
                ])
                mgr_emps = ou_emps.filtered(lambda e: any(k in (e.job_id.name or "").lower() for k in ["director", "manager", "head"]))
                if mgr_emps:
                    allowed_users |= mgr_emps.mapped("user_id")

        return allowed_users
