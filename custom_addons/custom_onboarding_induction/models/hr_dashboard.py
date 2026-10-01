# -*- coding: utf-8 -*-
from odoo import models, fields, api


class HrOnboardingDashboard(models.TransientModel):
    _name = "hr.onboarding.dashboard"
    _description = "Onboarding & Induction Dashboard"

    # ── Onboarding Plan KPIs ─────────────────────────────────────────────────
    ob_total          = fields.Integer(string="Total Onboarding Plans",        compute="_compute_ob_stats")
    ob_draft          = fields.Integer(string="Onboarding Draft",              compute="_compute_ob_stats")
    ob_pre_boarding   = fields.Integer(string="Pre-Boarding",                  compute="_compute_ob_stats")
    ob_induction_gate = fields.Integer(string="Induction Gate",                compute="_compute_ob_stats")
    ob_work_unit      = fields.Integer(string="Work Unit Onboarding",          compute="_compute_ob_stats")
    ob_midterm        = fields.Integer(string="Mid-Term Review",               compute="_compute_ob_stats")
    ob_completed      = fields.Integer(string="Onboarding Completed",          compute="_compute_ob_stats")
    ob_escalated      = fields.Integer(string="Escalated",                     compute="_compute_ob_stats")
    ob_completion_rate= fields.Float( string="Onboarding Completion Rate (%)", compute="_compute_ob_stats")

    # ── Induction Plan KPIs ──────────────────────────────────────────────────
    ind_total         = fields.Integer(string="Total Induction Plans",         compute="_compute_ind_stats")
    ind_draft         = fields.Integer(string="Induction Draft",               compute="_compute_ind_stats")
    ind_in_progress   = fields.Integer(string="In Progress",                   compute="_compute_ind_stats")
    ind_completed     = fields.Integer(string="Induction Completed",           compute="_compute_ind_stats")
    ind_completion_rate = fields.Float(string="Induction Completion Rate (%)", compute="_compute_ind_stats")

    # Onboarding Task KPIs
    task_total        = fields.Integer(string="Total Onboarding Tasks",        compute="_compute_task_stats")
    task_done         = fields.Integer(string="Tasks Completed",               compute="_compute_task_stats")
    task_todo         = fields.Integer(string="Tasks Pending",                 compute="_compute_task_stats")
    task_overdue      = fields.Integer(string="Overdue Tasks",             compute="_compute_task_stats")
    task_completion_rate = fields.Float(string="Task Completion (%)",     compute="_compute_task_stats")

    # LMS Task KPIs
    lms_total         = fields.Integer(string="Total LMS Tasks",           compute="_compute_lms_stats")
    lms_done          = fields.Integer(string="Completed LMS Tasks",       compute="_compute_lms_stats")
    lms_overdue       = fields.Integer(string="Overdue LMS Tasks",         compute="_compute_lms_stats")
    lms_completion_rate = fields.Float(string="LMS Completion (%)",       compute="_compute_lms_stats")

    recent_onboarding_ids = fields.Many2many(
        "hr.onboarding.plan", string="Recent Onboarding Plans",
        compute="_compute_recent"
    )
    recent_induction_ids = fields.Many2many(
        "hr.induction.plan", string="Recent Induction Plans",
        compute="_compute_recent",
        relation="hr_dash_recent_induction_rel"
    )

    def _compute_ob_stats(self):
        OB = self.env["hr.onboarding.plan"]
        for rec in self:
            all_plans = OB.search([])
            total = len(all_plans)
            rec.ob_total          = total
            rec.ob_draft          = len(all_plans.filtered(lambda p: p.state == "draft"))
            rec.ob_pre_boarding   = len(all_plans.filtered(lambda p: p.state == "pre_boarding"))
            rec.ob_induction_gate = len(all_plans.filtered(lambda p: p.state == "induction_gate"))
            rec.ob_work_unit      = len(all_plans.filtered(lambda p: p.state == "work_unit_onboarding"))
            rec.ob_midterm        = len(all_plans.filtered(lambda p: p.state == "midterm_review"))
            rec.ob_completed      = len(all_plans.filtered(lambda p: p.state == "completed"))
            rec.ob_escalated      = len(all_plans.filtered(lambda p: p.state == "escalated"))
            rec.ob_completion_rate= round((rec.ob_completed / total * 100) if total else 0.0, 1)

    def _compute_ind_stats(self):
        IND = self.env["hr.induction.plan"]
        for rec in self:
            all_plans = IND.search([])
            total = len(all_plans)
            rec.ind_total       = total
            rec.ind_draft       = len(all_plans.filtered(lambda p: p.state == "draft"))
            rec.ind_in_progress = len(all_plans.filtered(lambda p: p.state == "in_progress"))
            rec.ind_completed   = len(all_plans.filtered(lambda p: p.state == "completed"))
            rec.ind_completion_rate = round((rec.ind_completed / total * 100) if total else 0.0, 1)

    def _compute_task_stats(self):
        TASK = self.env["hr.onboarding.task"]
        for rec in self:
            all_tasks = TASK.search([])
            total = len(all_tasks)
            done  = len(all_tasks.filtered(lambda t: t.state == "done"))
            rec.task_total   = total
            rec.task_done    = done
            rec.task_todo    = total - done
            rec.task_overdue = len(all_tasks.filtered(lambda t: t.is_overdue))
            rec.task_completion_rate = round((done / total * 100) if total else 0.0, 1)

    def _compute_lms_stats(self):
        LMS = self.env["hr.induction.lms.task"]
        for rec in self:
            all_tasks = LMS.search([])
            total = len(all_tasks)
            done  = len(all_tasks.filtered(lambda t: t.state == "completed"))
            rec.lms_total   = total
            rec.lms_done    = done
            rec.lms_overdue = len(all_tasks.filtered(lambda t: t.is_overdue))
            rec.lms_completion_rate = round((done / total * 100) if total else 0.0, 1)

    def _compute_recent(self):
        for rec in self:
            rec.recent_onboarding_ids = self.env["hr.onboarding.plan"].search(
                [], order="create_date desc", limit=8
            )
            rec.recent_induction_ids = self.env["hr.induction.plan"].search(
                [], order="create_date desc", limit=5
            )

    @api.model
    def get_or_create_dashboard(self):
        rec = self.create({})
        return rec.id
