# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class RecruitmentPanelMemberConfig(models.Model):
    _name = "recruitment.panel.member.config"
    _description = "Recruitment Panel Member Configuration"
    _order = "sequence, id"

    name = fields.Char(string="Configuration Title", required=True, default="Authorized Interview Panel Members")
    sequence = fields.Integer(string="Sequence", default=10)
    active = fields.Boolean(default=True)

    scope = fields.Selection(
        [
            ("all", "All Vacancies (Internal & External)"),
            ("internal", "Internal Vacancy Only"),
            ("external", "External Vacancy Only"),
        ],
        string="Application Scope",
        default="all",
        required=True,
        help="Specifies whether this configuration applies to Internal vacancies, External vacancies, or All vacancies."
    )

    employee_ids = fields.Many2many(
        "hr.employee",
        "recruitment_panel_cfg_emp_rel",
        "config_id",
        "employee_id",
        string="Configured Panel Members",
        help="Explicitly authorized employees eligible to serve as interview panel members."
    )

    job_ids = fields.Many2many(
        "hr.job",
        "recruitment_panel_cfg_job_rel",
        "config_id",
        "job_id",
        string="Allowed Job Positions",
        help="All employees currently holding any of these job positions will also be eligible as panel members."
    )

    note = fields.Text(string="Description / Notes")

    employee_count = fields.Integer(string="Employees", compute="_compute_counts")
    job_count = fields.Integer(string="Job Positions", compute="_compute_counts")

    @api.depends("employee_ids", "job_ids")
    def _compute_counts(self):
        for rec in self:
            rec.employee_count = len(rec.employee_ids)
            rec.job_count = len(rec.job_ids)

    @api.onchange("job_ids")
    def _onchange_job_ids(self):
        if self.job_ids:
            matching = self.env["hr.employee"].search([
                ("job_id", "in", self.job_ids.ids),
                ("active", "=", True)
            ])
            self.employee_ids = [(6, 0, (self.employee_ids | matching).ids)]

    @api.model
    def get_eligible_panel_employees(self, sourcing_type=None, vacancy=None):
        """
        Returns hr.employee recordset of all configured panel members strictly from
        active recruitment.panel.member.config records.
        Filters by sourcing_type ('internal', 'external', or 'all').
        If no panel member configuration exists or has employees/jobs, falls back to all active employees.
        """
        domain = [("active", "=", True)]
        if sourcing_type in ("internal", "external"):
            domain.append(("scope", "in", [sourcing_type, "all"]))
        configs = self.search(domain)
        if not configs:
            configs = self.search([("active", "=", True)])

        configured_emps = self.env["hr.employee"].browse()
        has_any_config = False
        for cfg in configs:
            if cfg.employee_ids:
                has_any_config = True
                configured_emps |= cfg.employee_ids.filtered(lambda e: e.active)
            if cfg.job_ids:
                has_any_config = True
                job_emps = self.env["hr.employee"].search([
                    ("job_id", "in", cfg.job_ids.ids),
                    ("active", "=", True)
                ])
                configured_emps |= job_emps

        if has_any_config and configured_emps:
            return configured_emps

        # Fallback to all active employees only if no panel members are configured anywhere
        return self.env["hr.employee"].search([("active", "=", True)])
