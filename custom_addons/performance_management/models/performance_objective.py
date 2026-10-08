# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PerformanceObjective(models.Model):
    _name = 'performance.objective'
    _description = 'Strategic Objective (Cascaded)'
    _order = 'perspective_id, name'

    name = fields.Char(required=True, string='Strategic Objective')
    employee_id = fields.Many2one('hr.employee', string='Belongs To', required=True, default=lambda self: self.env.user.employee_id)
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
    @api.model
    def _register_hook(self):
        """Automatically recalculate and commit operating units for all objectives on registry load / upgrade."""
        super()._register_hook()
        try:
            objectives = self.sudo().search([])
            for obj in objectives:
                obj._compute_operating_units()
                self.env.cr.execute("""
                    UPDATE performance_objective
                    SET employee_operating_unit_id = %s,
                        coach_operating_unit_id = %s
                    WHERE id = %s
                """, (
                    obj.employee_operating_unit_id.id or None,
                    obj.coach_operating_unit_id.id or None,
                    obj.id
                ))
            self.env.invalidate_all()
        except Exception:
            pass

    @api.depends('employee_id', 'coach_id', 'employee_id.coach_id')
    def _compute_operating_units(self):
        OperatingUnit = self.env['operating.unit'].sudo()
        for rec in self:
            emp_ou = False
            if rec.employee_id:
                # 1. Operating unit where employee is explicitly manager
                emp_ou = OperatingUnit.search([('manager_id', '=', rec.employee_id.id)], limit=1)
                # 2. Or default_operating_unit_id on employee
                if not emp_ou and hasattr(rec.employee_id, 'default_operating_unit_id') and rec.employee_id.default_operating_unit_id:
                    emp_ou = rec.employee_id.default_operating_unit_id
                # 3. Or operating_unit_ids on employee
                if not emp_ou and hasattr(rec.employee_id, 'operating_unit_ids') and rec.employee_id.operating_unit_ids:
                    emp_ou = rec.employee_id.operating_unit_ids[0]
                # 4. Or department operating_unit_id
                if not emp_ou and rec.employee_id.department_id and hasattr(rec.employee_id.department_id, 'operating_unit_id') and rec.employee_id.department_id.operating_unit_id:
                    emp_ou = rec.employee_id.department_id.operating_unit_id
            rec.employee_operating_unit_id = emp_ou

            coach_ou = False
            if rec.coach_id:
                coach_ou = OperatingUnit.search([('manager_id', '=', rec.coach_id.id)], limit=1)
                if not coach_ou and hasattr(rec.coach_id, 'default_operating_unit_id') and rec.coach_id.default_operating_unit_id:
                    coach_ou = rec.coach_id.default_operating_unit_id
                if not coach_ou and hasattr(rec.coach_id, 'operating_unit_ids') and rec.coach_id.operating_unit_ids:
                    coach_ou = rec.coach_id.operating_unit_ids[0]
                if not coach_ou and rec.coach_id.department_id and hasattr(rec.coach_id.department_id, 'operating_unit_id') and rec.coach_id.department_id.operating_unit_id:
                    coach_ou = rec.coach_id.department_id.operating_unit_id
            rec.coach_operating_unit_id = coach_ou

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

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            OperatingUnit = self.env['operating.unit'].sudo()
            self.employee_operating_unit_id = OperatingUnit.search([('manager_id', '=', self.employee_id.id)], limit=1)
            if self.employee_id.coach_id:
                self.coach_operating_unit_id = OperatingUnit.search([('manager_id', '=', self.employee_id.coach_id.id)], limit=1)
            else:
                self.coach_operating_unit_id = False

    @api.constrains('employee_id')
    def _check_employee_is_operating_unit_manager(self):
        OperatingUnit = self.env['operating.unit'].sudo()
        for rec in self:
            if rec.employee_id:
                # Allow if employee is manager of an Operating Unit or top executive (no coach)
                is_manager = bool(OperatingUnit.search([('manager_id', '=', rec.employee_id.id)], limit=1))
                is_ceo = not bool(rec.employee_id.coach_id)
                if not is_manager and not is_ceo:
                    raise ValidationError(
                        "Strategic Objectives (Tier 2) can only be created for Operating Unit Managers.\n\n"
                        f"Employee '{rec.employee_id.name}' is not currently assigned as a Manager of any Operating Unit. "
                        "Please assign this employee as an Operating Unit Manager in the Operating Unit configuration first, "
                        "or configure Tier 3 Job KPIs for regular non-manager employees."
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
                ('active', '=', True),
            ])
            rec.unit_total_weight = sum(siblings.mapped('total_weight'))

    @api.depends('measure_ids.weight', 'measure_ids.active')
    def _compute_total_weight(self):
        for rec in self:
            active_measures = rec.measure_ids.filtered(lambda m: m.active)
            rec.total_weight = sum(active_measures.mapped('weight'))

    active = fields.Boolean(default=True)

    def unlink(self):
        T2Line = self.env['t2.scorecard.line'].sudo()
        T2AppraisalLine = self.env['t2.appraisal.line'].sudo()
        TemplateLine = self.env['performance.job.template.line'].sudo()

        to_unlink = self.browse()
        for rec in self:
            measure_ids = rec.measure_ids.ids
            is_used = False
            if measure_ids:
                is_used = (
                    T2Line.search_count([('measure_id', 'in', measure_ids)]) > 0
                    or T2AppraisalLine.search_count([('measure_id', 'in', measure_ids)]) > 0
                    or TemplateLine.search_count([('measure_id', 'in', measure_ids)]) > 0
                )
            if is_used:
                rec.write({'active': False})
                rec.measure_ids.write({'active': False})
            else:
                to_unlink |= rec
        if to_unlink:
            return super(PerformanceObjective, to_unlink).unlink()
        return True

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


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ('coach_id', 'department_id', 'default_operating_unit_id', 'operating_unit_ids')):
            for emp in self:
                objectives = self.env['performance.objective'].sudo().search([
                    '|',
                    ('employee_id', '=', emp.id),
                    ('coach_id', '=', emp.id),
                ])
                for obj in objectives:
                    obj._compute_operating_units()
                    self.env.cr.execute("""
                        UPDATE performance_objective
                        SET employee_operating_unit_id = %s,
                            coach_operating_unit_id = %s
                        WHERE id = %s
                    """, (
                        obj.employee_operating_unit_id.id or None,
                        obj.coach_operating_unit_id.id or None,
                        obj.id
                    ))
                self.env.invalidate_all()
        return res