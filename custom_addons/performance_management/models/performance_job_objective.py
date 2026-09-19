# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PerformanceJobObjective(models.Model):
    _name = 'performance.job.objective'
    _description = 'Key Performance Indicator (Tier3 - Job Position)'
    _order = 'perspective_id, name'

    name = fields.Char(required=True, string='Key Performance Indicator')

    operating_unit_id = fields.Many2one('operating.unit', string='Work Unit', required=True)
    job_id = fields.Many2one('hr.job', string='Job Position', required=True)

    parent_measure_id = fields.Many2one(
        'performance.measure',
        string='KPI (from Work Unit)',
        domain="[('objective_id.employee_operating_unit_id', '=', operating_unit_id)]",
        required=True,
        ondelete='cascade',
        help="Select the specific KPI/Measure from this Work Unit's own "
             "Strategic Objective. The Objective and Perspective below are "
             "derived automatically from this choice.",
    )
    parent_objective_id = fields.Many2one(
        related='parent_measure_id.objective_id',
        store=True, readonly=True,
        string='Directorate Objective',
    )
    perspective_id = fields.Many2one(
        related='parent_measure_id.objective_id.perspective_id',
        store=True, readonly=True,
    )

    measure_ids = fields.One2many(
        'performance.job.measure', 'job_objective_id', string='Measurements',
    )
    measure_count = fields.Integer(compute='_compute_measure_count')
    total_weight = fields.Float(compute='_compute_total_weight', store=True)

    active = fields.Boolean(default=True)

    @api.depends('measure_ids')
    def _compute_measure_count(self):
        for rec in self:
            rec.measure_count = len(rec.measure_ids)

    @api.depends('measure_ids.weight')
    def _compute_total_weight(self):
        for rec in self:
            rec.total_weight = sum(rec.measure_ids.mapped('weight'))

    @api.constrains('measure_ids')
    def _check_has_measures(self):
        for rec in self:
            if not rec.measure_ids:
                raise ValidationError(
                    'This KPI must have at least one Measurement before it can be saved.'
                )

    _unique_kpi_per_job = models.Constraint(
        'unique(operating_unit_id, job_id, name)',
        'This Job Position already has a KPI with this exact name in this Work Unit.',
    )


class PerformanceJobMeasure(models.Model):
    _name = 'performance.job.measure'
    _description = 'Measurement (Tier3 - Job Position)'
    _order = 'job_objective_id, name'

    name = fields.Char(required=True, string='Measurement')
    job_objective_id = fields.Many2one(
        'performance.job.objective', string='Key Performance Indicator',
        required=True, ondelete='cascade',
    )
    operating_unit_id = fields.Many2one(
        related='job_objective_id.operating_unit_id', store=True, readonly=True,
    )
    job_id = fields.Many2one(
        related='job_objective_id.job_id', store=True, readonly=True,
    )
    perspective_id = fields.Many2one(
        related='job_objective_id.perspective_id', store=True, readonly=True,
    )
    parent_objective_id = fields.Many2one(
        related='job_objective_id.parent_objective_id', store=True, readonly=True,
    )
    weight = fields.Float(string='Weight (%)', required=True, digits=(5, 2))
    target_type = fields.Selection([
        ('number', 'Number'),
        ('percent', 'Percent'),
        ('expense', 'Expense'),
        ('hours', 'Hours'),
        ('days', 'Days'),
        ('text', 'Text'),
    ], string='Target Type', default='number', required=True)
    active = fields.Boolean(default=True)



    @api.onchange('job_objective_id')
    def _onchange_job_objective_id(self):
        if self.job_objective_id and self.job_objective_id.parent_measure_id:
            self.target_type = self.job_objective_id.parent_measure_id.target_type

    @api.constrains('weight')
    def _check_weight(self):
        for rec in self:
            if rec.weight <= 0 or rec.weight > 100:
                raise ValidationError('Weight must be greater than 0 and no more than 100.')