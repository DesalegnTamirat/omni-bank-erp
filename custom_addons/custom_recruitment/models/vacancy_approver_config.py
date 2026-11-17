# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class VacancyApproverConfig(models.Model):
    _name = "vacancy.approver.config"
    _description = "Vacancy Approver Configuration"
    _order = "sequence, id"

    name = fields.Char(string="Configuration Title", required=True, default="Authorized Vacancy Approvers")
    sequence = fields.Integer(string="Sequence", default=10)
    active = fields.Boolean(default=True)

    scope = fields.Selection(
        [
            ("all", "All Vacancies (Internal & External)"),
            ("internal", "Internal Vacancies Only"),
            ("external", "External Vacancies Only"),
        ],
        string="Application Scope",
        default="all",
        required=True,
        help="Specifies whether this configuration applies to Internal vacancies, External vacancies, or All vacancies."
    )

    operating_unit_ids = fields.Many2many(
        "operating.unit",
        "vac_appr_cfg_ou_rel",
        "config_id",
        "ou_id",
        string="Operating Units / Work Units (Optional)",
        help="If set, this configuration applies only when the vacancy belongs to these operating units. Leave empty to allow across all operating units."
    )

    employee_ids = fields.Many2many(
        "hr.employee",
        "vac_appr_cfg_emp_rel",
        "config_id",
        "employee_id",
        string="Configured Approvers (Employees)",
        help="Explicitly authorized employees eligible to serve as vacancy approvers."
    )

    user_ids = fields.Many2many(
        "res.users",
        "vac_appr_cfg_user_rel",
        "config_id",
        "user_id",
        string="Authorized User Accounts",
        compute="_compute_user_ids",
        store=True,
        readonly=False,
        help="User accounts corresponding to authorized vacancy approver employees."
    )

    job_ids = fields.Many2many(
        "hr.job",
        "vac_appr_cfg_job_rel",
        "config_id",
        "job_id",
        string="Allowed Job Positions",
        help="All employees currently holding any of these job positions will also be eligible as vacancy approvers."
    )

    note = fields.Text(string="Description / Notes")

    employee_count = fields.Integer(string="Employees", compute="_compute_counts")
    job_count = fields.Integer(string="Job Positions", compute="_compute_counts")

    @api.depends("employee_ids", "job_ids")
    def _compute_counts(self):
        for rec in self:
            rec.employee_count = len(rec.employee_ids)
            rec.job_count = len(rec.job_ids)

    @api.depends("employee_ids", "employee_ids.user_id", "job_ids")
    def _compute_user_ids(self):
        for rec in self:
            users = rec.employee_ids.mapped("user_id").filtered(lambda u: bool(u and u.active))
            if rec.job_ids:
                job_emps = self.env["hr.employee"].search([
                    ("job_id", "in", rec.job_ids.ids),
                    ("active", "=", True),
                    ("user_id", "!=", False)
                ])
                users |= job_emps.mapped("user_id").filtered(lambda u: bool(u and u.active))
            rec.user_ids = [(6, 0, users.ids)]

    @api.onchange("job_ids")
    def _onchange_job_ids(self):
        if self.job_ids:
            matching = self.env["hr.employee"].search([
                ("job_id", "in", self.job_ids.ids),
                ("active", "=", True)
            ])
            self.employee_ids = [(6, 0, (self.employee_ids | matching).ids)]

    @api.model
    def get_eligible_approver_users(self, sourcing_type=None, vacancy=None):
        """
        Returns res.users recordset of authorized vacancy approvers from
        active vacancy.approver.config records.
        Strictly limits approvers to explicitly configured employees, users, and job positions.
        """
        domain = [("active", "=", True)]
        if sourcing_type in ("internal", "external"):
            domain.append(("scope", "in", [sourcing_type, "all"]))
        configs = self.search(domain)
        if not configs:
            configs = self.search([("active", "=", True)])

        if not configs:
            return self.env["res.users"].browse()

        vac_ou = getattr(vacancy, "operating_unit_id", False) if vacancy else False

        # 1. First priority: configs matching the specific operating unit of the vacancy
        matching_configs = self.env["vacancy.approver.config"].browse()
        if vac_ou:
            matching_configs = configs.filtered(lambda c: vac_ou.id in c.operating_unit_ids.ids)

        # 2. Second priority: configs applicable across all operating units (empty operating_unit_ids)
        if not matching_configs:
            matching_configs = configs.filtered(lambda c: not c.operating_unit_ids)

        # 3. Fallback: if no unit-level match found, use all active configs so authorized approvers are not dropped
        if not matching_configs:
            matching_configs = configs

        configured_users = self.env["res.users"].browse()
        for cfg in matching_configs:
            if cfg.employee_ids:
                configured_users |= cfg.employee_ids.mapped("user_id").filtered(lambda u: bool(u and u.active))
            if cfg.user_ids:
                configured_users |= cfg.user_ids.filtered(lambda u: bool(u and u.active))
            if cfg.job_ids:
                job_emps = self.env["hr.employee"].search([
                    ("job_id", "in", cfg.job_ids.ids),
                    ("active", "=", True),
                    ("user_id", "!=", False)
                ])
                configured_users |= job_emps.mapped("user_id").filtered(lambda u: bool(u and u.active))

        return configured_users

