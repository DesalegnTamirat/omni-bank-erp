# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PerformanceMeasure(models.Model):
    _name = 'performance.measure'
    _description = 'Performance Measure'
    _order = 'objective_id, name'

    name = fields.Char(
        required=True,
        string='Performance Measure'
    )

    perspective_id = fields.Many2one(
        'performance.perspective',
        related='objective_id.perspective_id',
        store=True,
        readonly=True,
        string='Perspective',
    )
    kpi = fields.Text(string='KPI')

    objective_id = fields.Many2one(
        'performance.objective',
        string='Strategic Objective',
        required=True,
        ondelete='cascade',
    )

    weight = fields.Float(
        string='Weight (%)',
        required=True,
        digits=(5, 2),
    )

    target_type = fields.Selection([
        ('number', 'Number'),
        ('percent', 'Percent'),
        ('text', 'Text'),
    ], string='Target Type', default='number', required=True)

    active = fields.Boolean(default=True)

    @api.constrains('weight')
    def _check_weight(self):
        for rec in self:
            if rec.weight <= 0 or rec.weight > 100:
                raise ValidationError('Weight must be greater than 0 and no more than 100.')