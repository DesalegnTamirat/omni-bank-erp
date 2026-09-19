# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class T2Scorecard(models.Model):
    _name = "t2.scorecard"
    _description = "Tier 2 Scorecard"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = "employee_id"
    _order = "employee_id"

    employee_id = fields.Many2one("hr.employee", string="Employee",)
    manager_id = fields.Many2one("hr.employee", string="Manager", readonly=True)

    planning_name = fields.Char(readonly=True)
    appraisal_period_id = fields.Many2one(
        'appraisal.period', string='Appraisal Period', readonly=True,
    )
    appraisal_period_name = fields.Char(
        related='appraisal_period_id.name', store=True, readonly=True,
    )
    appraisal_period_code = fields.Selection(
        related='appraisal_period_id.code', store=True, readonly=True,
    )

    company_id = fields.Many2one("res.company", readonly=True)



    job_id = fields.Many2one("hr.job", string="Job Position", readonly=True)



    start_date = fields.Date(readonly=True)
    end_date = fields.Date(readonly=True)

    accepted_by = fields.Many2one("hr.employee", string="Accepted By")

    employee_image_128 = fields.Image(
        string='Employee Photo',
        related='employee_id.image_128',
        max_width=128,
        max_height=128,
        store=True,
    )

    line_ids = fields.One2many(
        "t2.scorecard.line",
        "scorecard_id",
        string="Score Card Plan Details",
    )

    total_weight = fields.Float(
        compute="_compute_total_weight",
        store=True,
    )

    state = fields.Selection([
        ("draft", "Draft"),
        ("notified", "Notified"),
        ("accepted", "Accepted"),
        ("rejected", "Rejected"),
        ("confirmed", "Confirmed"),
    ], default="draft", tracking=True)
    department_id = fields.Many2one(
        "hr.department",
        compute='_compute_department_id',
        string="Department",
    )

    operating_unit_id = fields.Many2one(
        "operating.unit",
        string="Operating Unit",
        readonly=True,
        help="Set when the scorecard was generated. Does not change if the "
             "Employee is later reassigned.",
    )

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            self.job_id = self.employee_id.job_id
            self.company_id = self.employee_id.company_id


    def _compute_department_id(self):
        for rec in self:
            rec.department_id = rec.employee_id.department_id if rec.employee_id else False

    @api.depends("line_ids.weight")
    def _compute_total_weight(self):
        for rec in self:
            rec.total_weight = sum(rec.line_ids.mapped("weight"))

    def action_notify(self):

        self.write({'state': 'notified'})

    def action_accept(self):
        self.write({'state': 'accepted'})

    def action_reject(self):
        self.write({'state': 'rejected'})

    def action_confirm(self):
        self.write({'state': 'confirmed'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def write(self, vals):
        for rec in self:
            if rec.state in ('accepted', 'confirmed'):
                if not set(vals.keys()).issubset({'state', 'accepted_by'}):
                    raise UserError(
                        'This Tier 2 Scorecard is %s and can no longer be edited.'
                        % dict(rec._fields['state'].selection).get(rec.state, rec.state)
                    )
        res = super().write(vals)
        if 'employee_id' in vals:
            for rec in self:
                rec.employee_image_128 = rec.employee_id.image_128
        return res

    def unlink(self):
        for rec in self:
            if rec.state in ('accepted', 'confirmed'):
                raise UserError(
                    'This Tier 2 Scorecard is %s and cannot be deleted.'
                    % dict(rec._fields['state'].selection).get(rec.state, rec.state)
                )
        return super().unlink()

    def action_populate_lines(self):
        Measure = self.env['performance.measure']
        Line = self.env['t2.scorecard.line']

        vals_list = []
        for scorecard in self:
            measures = Measure.search([
                ('objective_id.employee_id', '=', scorecard.employee_id.id),
            ])
            existing_measure_ids = set(scorecard.line_ids.mapped('measure_id').ids)

            for measure in measures:
                if measure.id in existing_measure_ids:
                    continue
                vals_list.append({
                    'scorecard_id': scorecard.id,
                    'measure_id': measure.id,
                })

        if not vals_list:
            return Line.browse()

        new_lines = Line.create(vals_list)
        self._compute_total_weight()
        return new_lines


class T2ScorecardLine(models.Model):
    _name = "t2.scorecard.line"
    _description = "Tier 2 Scorecard Line"

    scorecard_id = fields.Many2one(
        "t2.scorecard",
        required=True,
        ondelete="cascade",
    )
    scorecard_employee_id = fields.Many2one(
        related='scorecard_id.employee_id',
        store=True, readonly=True,
    )
    period_name = fields.Char(
        related='scorecard_id.planning_name',
        store=True,
        readonly=True,
    )

    measure_id = fields.Many2one(
        'performance.measure',
        string='Performance Measure',
        required=True,
        domain="[('objective_id.employee_id', '=', scorecard_employee_id)]",
    )
    objective_id = fields.Many2one(
        related='measure_id.objective_id', store=True, readonly=True,
        string='Strategic Objective',
    )
    perspective_id = fields.Many2one(
        related='measure_id.objective_id.perspective_id', store=True, readonly=True,
    )
    weight = fields.Float(
        related='measure_id.weight', store=True, readonly=True, string='Weight (%)',
    )
    target_type = fields.Selection(
        related='measure_id.target_type', store=True, readonly=True,
    )

    baseline = fields.Float(string='Baseline')
    q1_target = fields.Float(string='Q1 Target')
    h1_target = fields.Float(string='H1 Target')
    q3_target = fields.Float(string='Q3 Target')
    h2_target = fields.Float(string='H2 Target')
    annual_target = fields.Float(
        string='Annual Target', compute='_compute_annual_target', store=True, readonly=False,
    )
    target_description = fields.Text(string='Target Description')

    @api.depends('q1_target', 'h1_target', 'q3_target', 'h2_target')
    def _compute_annual_target(self):
        for line in self:
            line.annual_target = (
                (line.q1_target or 0.0) + (line.h1_target or 0.0)
                + (line.q3_target or 0.0) + (line.h2_target or 0.0)
            )

    def write(self, vals):
        for rec in self:
            if rec.scorecard_id.state in ('accepted', 'confirmed'):
                raise UserError(
                    'The parent Tier 2 Scorecard is %s and its lines can '
                    'no longer be edited.'
                    % dict(rec.scorecard_id._fields['state'].selection).get(
                        rec.scorecard_id.state, rec.scorecard_id.state
                    )
                )
        return super().write(vals)
