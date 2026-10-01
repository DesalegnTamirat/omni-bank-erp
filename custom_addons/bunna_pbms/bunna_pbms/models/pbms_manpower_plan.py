# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PbmsManpowerPlan(models.Model):
    """New Staff Plan by Type of Job Position (BB-APF6).

    Unlike the monthly-grid formats, manpower requests are itemized
    (one row per requested position), so this is a header/line model:
    one header per org unit + cycle carrying the workflow, with N
    request lines - matching how the Bank's own Excel format (one
    sheet per unit, many rows) works, and letting district/head-office
    reviewers endorse or return the whole unit's manpower request in
    one action instead of row by row.
    """
    _name = "pbms.manpower.plan"
    _description = "Manpower Requirement Plan (BB-APF6)"
    _inherit = ["pbms.workflow.mixin", "mail.thread", "mail.activity.mixin"]
    _rec_name = "display_name"

    line_ids = fields.One2many("pbms.manpower.plan.line", "plan_id", string="Requested Positions")
    line_count = fields.Integer(compute="_compute_line_count", store=True)
    display_name = fields.Char(compute="_compute_display_name", store=True)

    @api.depends("line_ids")
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.org_unit_id.display_name} - Manpower - {rec.cycle_id.name}"

    def _protected_write_fields(self):
        return ["line_ids"]

    @api.constrains("line_ids", "state")
    def _check_has_lines(self):
        for rec in self:
            if rec.state != "draft" and not rec.line_ids:
                raise UserError(_("Cannot submit a manpower plan with no requested positions."))

    @api.model
    def _consolidate_district_plan_data(self, cycle_id, district):
        branch_plans = self.search([
            ("cycle_id", "=", cycle_id.id),
            ("district_id", "=", district.id),
            ("state", "=", "district_approved"),
            ("org_unit_id", "!=", district.id),
        ])
        dist_plan = self.search([
            ("cycle_id", "=", cycle_id.id),
            ("org_unit_id", "=", district.id),
        ], limit=1)
        if not dist_plan:
            dist_plan = self.create({
                "cycle_id": cycle_id.id,
                "org_unit_id": district.id,
                "state": "draft",
            })
        
        # Clear existing consolidated lines on District plan if in draft
        if dist_plan.state == "draft":
            dist_plan.line_ids.unlink()
            lines_to_create = []
            for bp in branch_plans:
                for line in bp.line_ids:
                    lines_to_create.append((0, 0, {
                        "position_type": line.position_type,
                        "employment_type": line.employment_type,
                        "job_id": line.job_id.id,
                        "job_grade_id": line.job_grade_id.id if line.job_grade_id else False,
                        "job_title": line.job_title,
                        "job_grade": line.job_grade,
                        "quantity": line.quantity,
                        "date_needed": line.date_needed,
                        "reason": f"[{bp.org_unit_id.display_name}] {line.reason or ''}",
                    }))
            if lines_to_create:
                dist_plan.write({"line_ids": lines_to_create})

    @api.model
    def _consolidate_ho_plan_data(self, cycle_id, ho_unit):
        dist_plans = self.search([
            ("cycle_id", "=", cycle_id.id),
            ("org_unit_type", "=", "district_office"),
            ("state", "in", ("submitted", "ho_reviewed", "approved")),
        ])
        ho_plan = self.search([
            ("cycle_id", "=", cycle_id.id),
            ("org_unit_id", "=", ho_unit.id),
        ], limit=1)
        if not ho_plan:
            ho_plan = self.create({
                "cycle_id": cycle_id.id,
                "org_unit_id": ho_unit.id,
                "state": "draft",
            })

        if ho_plan.state == "draft":
            ho_plan.line_ids.unlink()
            lines_to_create = []
            for dp in dist_plans:
                for line in dp.line_ids:
                    lines_to_create.append((0, 0, {
                        "position_type": line.position_type,
                        "employment_type": line.employment_type,
                        "job_id": line.job_id.id,
                        "job_grade_id": line.job_grade_id.id if line.job_grade_id else False,
                        "job_title": line.job_title,
                        "job_grade": line.job_grade,
                        "quantity": line.quantity,
                        "date_needed": line.date_needed,
                        "reason": f"[{dp.org_unit_id.display_name}] {line.reason or ''}",
                    }))
            if lines_to_create:
                ho_plan.write({"line_ids": lines_to_create})


class PbmsManpowerPlanLine(models.Model):
    _name = "pbms.manpower.plan.line"
    _description = "Manpower Requirement Line"
    _order = "id"

    plan_id = fields.Many2one(
        "pbms.manpower.plan", required=True, ondelete="cascade", index=True,
    )
    position_type = fields.Selection(
        [("new", "New Position"), ("replacement", "Replacement")],
        required=True, default="new",
    )
    employment_type = fields.Selection(
        [("permanent", "Permanent"), ("contract", "Contract"), ("temporary", "Temporary")],
        required=True, default="permanent",
    )
    job_id = fields.Many2one(
        "hr.job", string="Job Position", required=True, index=True,
    )
    job_grade_id = fields.Many2one(
        "employee.grade", string="Job Grade", index=True,
    )
    job_title = fields.Char(
        string="Job Title", compute="_compute_job_info", store=True, readonly=False,
    )
    job_grade = fields.Char(
        string="Job Grade Text", compute="_compute_job_info", store=True, readonly=False,
    )
    quantity = fields.Integer(required=True, default=1)
    date_needed = fields.Date(required=True)
    reason = fields.Text(string="Reason for the Proposed Position", required=True)

    @api.depends("job_id", "job_grade_id")
    def _compute_job_info(self):
        for line in self:
            if line.job_id:
                line.job_title = line.job_id.name
            elif not line.job_title:
                line.job_title = ""

            if line.job_grade_id:
                line.job_grade = line.job_grade_id.grade_name or line.job_grade_id.display_name
            elif not line.job_grade:
                line.job_grade = ""

    _sql_constraints = [
        ("quantity_positive", "check(quantity > 0)", "Quantity must be greater than zero."),
    ]
