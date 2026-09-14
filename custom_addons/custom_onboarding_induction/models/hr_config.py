# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrInductionTaskTemplate(models.Model):
    _name = "hr.induction.task.template"
    _description = "Corporate Induction Task / LMS Training Template"
    _order = "sequence, id"

    name = fields.Char(string="Task / Training Title", required=True)
    sequence = fields.Integer(string="Sequence", default=10)
    training_type = fields.Selection(
        [
            ("lms_video", "LMS Video Course"),
            ("document", "Policy Document"),
            ("classroom", "Classroom Orientation"),
            ("system_demo", "System Walkthrough"),
        ],
        string="Training Type",
        required=True,
        default="classroom",
    )
    is_mandatory = fields.Boolean(string="Mandatory?", default=True)
    days_offset = fields.Integer(
        string="Due Date Offset (Days)",
        default=1,
        help="Number of calendar days after the employee's Expected Start Date to set the target due date.",
    )
    active = fields.Boolean(string="Active", default=True)


class HrOnboardingScoreConfig(models.Model):
    _name = "hr.onboarding.score.config"
    _description = "Onboarding Performance Scoring Weight Configuration"
    _rec_name = "name"

    name = fields.Char(string="Configuration Name", default="Bunna Bank Standard Scoring Weights", required=True)
    weight_induction = fields.Float(
        string="Corporate Induction LMS Weight (%)",
        default=20.0,
        required=True,
        help="Percentage weight for Corporate Induction LMS training in overall score (e.g. 20.0).",
    )
    weight_tasks = fields.Float(
        string="Work Unit Tasks Weight (%)",
        default=40.0,
        required=True,
        help="Percentage weight for operational onboarding tasks in overall score (e.g. 40.0).",
    )
    weight_midterm = fields.Float(
        string="Supervisor Mid-Term Rating Weight (%)",
        default=40.0,
        required=True,
        help="Percentage weight for the 4-week supervisor performance rating in overall score (e.g. 40.0).",
    )
    total_weight = fields.Float(
        string="Total Configured Weight (%)",
        compute="_compute_total_weight",
        store=True,
        digits=(5, 2),
    )

    @api.depends("weight_induction", "weight_tasks", "weight_midterm")
    def _compute_total_weight(self):
        for rec in self:
            rec.total_weight = round(rec.weight_induction + rec.weight_tasks + rec.weight_midterm, 2)

    @api.constrains("weight_induction", "weight_tasks", "weight_midterm")
    def _check_total_weight(self):
        for rec in self:
            total = round(rec.weight_induction + rec.weight_tasks + rec.weight_midterm, 2)
            if total != 100.0:
                raise ValidationError(_("The sum of all three scoring weights must equal exactly 100.0%% (Current total: %.2f%%).") % total)

    @api.model
    def get_default_config(self):
        config = self.search([], limit=1)
        if not config:
            config = self.create({
                "name": "Bunna Bank Standard Scoring Weights",
                "weight_induction": 20.0,
                "weight_tasks": 40.0,
                "weight_midterm": 40.0,
            })
        return config


class HrOnboardingTaskTemplate(models.Model):
    _name = "hr.onboarding.task.template"
    _description = "Workplace Onboarding Task Template"
    _order = "sequence, id"

    name = fields.Char(string="Task Description", required=True)
    sequence = fields.Integer(string="Sequence", default=10)
    period = fields.Selection(
        [
            ("day_1", "Day 1 (Immediate Arrival)"),
            ("week_1", "Week 1 (Orientation & SOPs)"),
            ("week_2", "Week 2 (Initial Assignment)"),
            ("week_3", "Week 3 (Process Execution)"),
            ("month_1", "Month 1 (4-Week Mid-Term)"),
            ("month_2", "Month 2 (Final Closure)"),
        ],
        string="Onboarding Period",
        required=True,
        default="day_1",
    )
    assigned_to_role = fields.Selection(
        [
            ("supervisor", "Immediate Supervisor"),
            ("employee", "New Hire Employee"),
            ("buddy", "Assigned Onboarding Buddy"),
            ("hr_officer", "HR Officer / POMD"),
        ],
        string="Assigned Role",
        required=True,
        default="supervisor",
    )
    days_offset = fields.Integer(
        string="Due Date Offset (Days)",
        default=1,
        help="Number of calendar days after the employee's Expected Start Date to set the target due date.",
    )
    active = fields.Boolean(string="Active", default=True)