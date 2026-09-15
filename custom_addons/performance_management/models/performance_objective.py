# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PerformanceObjective(models.Model):
    _name = 'performance.objective'
    _description = 'Strategic Objective (Cascaded)'
    _order = 'perspective_id, name'

    name = fields.Char(required=True, string='Strategic Objective')
    employee_id = fields.Many2one('hr.employee', string='Belongs To', required=True)
    perspective_id = fields.Many2one('performance.perspective', string='Perspective')

    coach_id = fields.Many2one(
        'hr.employee',
        related='employee_id.coach_id',
        store=True,
        readonly=True,
        string='Coach (for filtering)',
    )

    employee_operating_unit_id = fields.Many2one(
        'operating.unit',
        compute='_compute_operating_units',
        store=True,
        string='Operating Unit (managed by Employee)',
        help='The Work Unit this Employee is the manager of, if any.',
    )
    coach_operating_unit_id = fields.Many2one(
        'operating.unit',
        compute='_compute_operating_units',
        store=True,
        string='Operating Unit (managed by Coach)',
        help='The Work Unit this Employee\'s Coach is the manager of, if any.',
    )
    measure_count = fields.Integer(
        compute='_compute_measure_count',
    )

    @api.depends('measure_ids')
    def _compute_measure_count(self):
        for rec in self:
            rec.measure_count = len(rec.measure_ids)
    @api.depends('employee_id', 'coach_id')
    def _compute_operating_units(self):
        OperatingUnit = self.env['operating.unit']
        for rec in self:
            rec.employee_operating_unit_id = OperatingUnit.search(
                [('manager_id', '=', rec.employee_id.id)], limit=1,
            ) if rec.employee_id else False
            rec.coach_operating_unit_id = OperatingUnit.search(
                [('manager_id', '=', rec.coach_id.id)], limit=1,
            ) if rec.coach_id else False

    # parent_measure_id = fields.Many2one(
    #     'performance.measure',
    #     string='Cascades From',
    #     ondelete='cascade',
    #     domain="""
    #         [
    #             ('objective_id.employee_id', '=', coach_id),
    #             ('perspective_id', '=', perspective_id)
    #         ]
    #     """,
    #     help='Leave blank only for the CEO (top of the hierarchy).'
    # )
    parent_objective_id = fields.Many2one(
        'performance.objective',
        string='Cascades From',
        domain="""
            [
                ('employee_id', '=', coach_id),
                ('perspective_id', '=', perspective_id)
            ]
        """,
        help="Select your coach's objective in the same perspective."
    )

    measure_ids = fields.One2many(
        'performance.measure',
        'objective_id',
        string='Measures',
    )
    total_weight = fields.Float(
        compute='_compute_total_weight',
        store=True,
        aggregator='sum',
    )
    unit_total_weight = fields.Float(
        compute='_compute_unit_total_weight',
    )
    _unique_employee_name = models.Constraint(
        'unique(employee_id, name)',
        'This employee already has an Objective with this exact name.',
    )

    @api.constrains('measure_ids')
    def _check_has_measures(self):
        for rec in self:
            if not rec.measure_ids:
                raise ValidationError(
                    'This Objective must have at least one Measure before it can be saved.'
                )



    def _compute_unit_total_weight(self):
        for rec in self:
            if not rec.employee_operating_unit_id:
                rec.unit_total_weight = rec.total_weight
                continue
            siblings = self.search([
                ('employee_operating_unit_id', '=', rec.employee_operating_unit_id.id),
            ])
            rec.unit_total_weight = sum(siblings.mapped('total_weight'))

    @api.depends('measure_ids.weight')
    def _compute_total_weight(self):
        for rec in self:
            rec.total_weight = sum(rec.measure_ids.mapped('weight'))

    active = fields.Boolean(default=True)

    # @api.onchange('parent_measure_id')
    # def _onchange_parent_measure_id(self):
    #     if self.parent_measure_id:
    #         self.perspective_id = self.parent_measure_id.perspective_id

    # @api.constrains('employee_id', 'parent_measure_id')
    # def _check_parent_required(self):
    #     for rec in self:
    #         if rec.employee_id.coach_id and not rec.parent_measure_id:
    #             raise ValidationError(
    #                 'This employee has a Coach — you must select which of '
    #                 'the Coach\'s Measures this Objective cascades from.'
    #             )
    @api.onchange('parent_objective_id')
    def _onchange_parent_objective_id(self):
        if self.parent_objective_id:
            self.perspective_id = self.parent_objective_id.perspective_id

    @api.constrains('employee_id', 'parent_objective_id')
    def _check_parent_required(self):
        for rec in self:
            if rec.employee_id.coach_id and not rec.parent_objective_id:
                raise ValidationError(
                    'This employee has a Coach, so you must select which of the '
                    "Coach's Objectives this Objective cascades from."
                )