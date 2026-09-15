# -*- coding: utf-8 -*-
from odoo import fields, models


class PerformancePerspective(models.Model):
    _name = 'performance.perspective'
    _description = 'Performance Perspective'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)


    _name_uniq = models.Constraint(
        'unique(name)',
        'A Perspective with this name already exists.',
    )
