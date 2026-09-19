# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class CorporateScorecard(models.Model):
    _name = 'corporate.scorecard'
    _description = 'Corporate Score Card'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, name'

    name = fields.Char(
        string='Planning Name',
        required=True,
        readonly=True,
    )
    fiscal_year_id = fields.Many2one(
        'performance.fiscal.year',
        string='Fiscal Year',
        readonly=True,
    )
    appraisal_period_id = fields.Many2one(
        'appraisal.period',
        string='Appraisal Period', required=True,
        readonly=True,
    )
    employee_image_128 = fields.Image(
        string='Employee Photo',
        related='employee_id.image_128',
        max_width=128,
        max_height=128,
        store=True,
    )
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)

    date_start = fields.Date(
        string='Planning Period Start Date',
        required=True,
        readonly=True,
    )
    date_end = fields.Date(
        string='Planning Period End Date',
        required=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company Name',
        default=lambda self: self.env.company,
        readonly=True,
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('notified', 'Notified'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('appraisal_started', 'Appraisal Started'),
        ('completed', 'Completed'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False)

    line_ids = fields.One2many(
        'corporate.scorecard.line',
        'scorecard_id',
        string='Corporate Score Card Plan Details',
        copy=True,
    )
    total_weight = fields.Float(
        string='Total Weight (%)',
        compute='_compute_total_weight',
    )

    @api.depends('line_ids.weight')
    def _compute_total_weight(self):
        for rec in self:
            rec.total_weight = sum(rec.line_ids.mapped('weight'))

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_start > rec.date_end:
                raise ValidationError(
                    'Planning Period Start Date must be before the Planning Period End Date.'
                )

    @api.onchange('fiscal_year_id')
    def _onchange_fiscal_year_id(self):
        self.appraisal_period_id = False
        self.date_start = False
        self.date_end = False

        if self.fiscal_year_id:
            lines = self.fiscal_year_id.line_ids.sorted('date_start')

            if lines:
                self.appraisal_period_id = lines[0].appraisal_period
                self.date_start = lines[0].date_start
                self.date_end = lines[0].date_end

            return {
                'domain': {
                    'appraisal_period_id': [
                        ('id', 'in', lines.mapped('appraisal_period').ids)
                    ]
                }
            }

    @api.onchange('appraisal_period_id')
    def _onchange_appraisal_period_id(self):
        self.date_start = False
        self.date_end = False

        if self.fiscal_year_id and self.appraisal_period_id:
            line = self.fiscal_year_id.line_ids.filtered(
                lambda l: l.appraisal_period == self.appraisal_period_id
            )[:1]

            if line:
                self.date_start = line.date_start
                self.date_end = line.date_end

    def action_notify(self):
        self.write({'state': 'notified'})

    def action_accept(self):
        self.write({'state': 'accepted'})

    def action_reject(self):
        self.write({'state': 'rejected'})

    def action_complete(self):
        self.write({'state': 'completed'})

    def action_start_appraisal(self):
        self.write({'state': 'appraisal_started'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def write(self, vals):
        for rec in self:
            if rec.state in ('accepted', 'appraisal_started', 'completed'):
                if not set(vals.keys()).issubset({'state'}):
                    raise UserError(
                        'This Corporate Scorecard is %s and can no longer be edited.'
                        % dict(rec._fields['state'].selection).get(rec.state, rec.state)
                    )
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.state in ('appraisal_started', 'completed'):
                raise UserError(
                    'This Corporate Scorecard is %s and cannot be deleted.'
                    % dict(rec._fields['state'].selection).get(rec.state, rec.state)
                )
        return super().unlink()

    def action_populate_lines(self):
        self.ensure_one()
        Measure = self.env['performance.measure']
        Line = self.env['corporate.scorecard.line']

        root_measures = Measure.search([('objective_id.parent_objective_id', '=', False)])

        vals_list = [
            {'scorecard_id': self.id, 'measure_id': measure.id}
            for measure in root_measures
        ]

        if not vals_list:
            return Line.browse()

        new_lines = Line.create(vals_list)
        self._compute_total_weight()
        return new_lines


class CorporateScorecardLine(models.Model):
    _name = 'corporate.scorecard.line'
    _description = 'Corporate Score Card Plan Detail'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    scorecard_id = fields.Many2one(
        'corporate.scorecard',
        string='Corporate Score Card',
        required=True,
        ondelete='cascade',
    )
    period_name = fields.Char(
        related='scorecard_id.appraisal_period_id.name',
        store=True,
        readonly=True,
    )
    period_code = fields.Selection(
        related='scorecard_id.appraisal_period_id.code',
        store=True,
        readonly=True,
    )

    measure_id = fields.Many2one(
        'performance.measure',
        string='Performance Measure',
        required=True,
        domain="[('objective_id.parent_objective_id', '=', False)]",
    )
    objective_id = fields.Many2one(
        related='measure_id.objective_id',
        store=True, readonly=True,
        string='Strategic Objective',
    )
    perspective_id = fields.Many2one(
        related='measure_id.objective_id.perspective_id',
        store=True, readonly=True,
        string='Perspective',
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
        string='Annual Target', compute='_compute_annual_target', store=True, readonly=True,
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
            if rec.scorecard_id.state in ('accepted', 'appraisal_started', 'completed'):
                raise UserError(
                    'The parent Corporate Scorecard is %s and its lines can '
                    'no longer be edited.'
                    % dict(rec.scorecard_id._fields['state'].selection).get(
                        rec.scorecard_id.state, rec.scorecard_id.state
                    )
                )
        return super().write(vals)