# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PerformanceScoreAllocation(models.Model):
    _name = 'performance.score.allocation'
    _description = 'Performance Score Allocation Configuration'
    _order = 'work_unit_type'

    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True,
    )
    work_unit_type = fields.Selection(
        selection=[
            ('branch', 'Branch'),
            ('sub_branch', 'Sub-Branch'),
            ('head_office', 'Head Office'),
            ('regional_office', 'Regional Office'),
            ('district_office', 'District Office'),
            ('area_office', 'Area Office'),
            ('service_center', 'Service Center'),
            ('other', 'Other'),
        ],
        string='Work Unit Type',
        required=True,
        index=True,
        help='Operating unit classification type (e.g. Branch, Head Office, District).',
    )
    work_unit_weight = fields.Float(
        string='Operating Unit Share (%)',
        required=True,
        default=50.0,
        digits=(5, 2),
        help='Percentage weight of the Operating Unit / Work Unit score in the final Tier 3 average score.',
    )
    employee_weight = fields.Float(
        string='Employee Share (%)',
        compute='_compute_employee_weight',
        store=True,
        readonly=False,
        required=True,
        digits=(5, 2),
        help='Percentage weight of the Employee Individual score in the final Tier 3 average score.',
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )
    description = fields.Text(
        string='Description',
        help='Optional explanatory notes for this allocation rule.',
    )

    @api.depends('work_unit_weight')
    def _compute_employee_weight(self):
        for rec in self:
            if rec.work_unit_weight is not False and rec.work_unit_weight is not None:
                rec.employee_weight = max(0.0, min(100.0, round(100.0 - (rec.work_unit_weight or 0.0), 2)))
            else:
                rec.employee_weight = 50.0

    @api.onchange('work_unit_weight')
    def _onchange_work_unit_weight(self):
        if self.work_unit_weight is not False and self.work_unit_weight is not None:
            self.employee_weight = max(0.0, min(100.0, round(100.0 - (self.work_unit_weight or 0.0), 2)))

    @api.onchange('employee_weight')
    def _onchange_employee_weight(self):
        if self.employee_weight is not False and self.employee_weight is not None:
            self.work_unit_weight = max(0.0, min(100.0, round(100.0 - (self.employee_weight or 0.0), 2)))

    @api.depends('work_unit_type', 'work_unit_weight', 'employee_weight')
    def _compute_name(self):
        type_dict = dict(self._fields['work_unit_type'].selection)
        for rec in self:
            type_label = type_dict.get(rec.work_unit_type, rec.work_unit_type or 'General')
            rec.name = f"{type_label} (OU: {rec.work_unit_weight:.0f}% / Individual: {rec.employee_weight:.0f}%)"

    @api.constrains('work_unit_type')
    def _check_unique_work_unit_type(self):
        for rec in self:
            dup = self.search([
                ('id', '!=', rec.id),
                ('work_unit_type', '=', rec.work_unit_type),
            ], limit=1)
            if dup:
                type_label = dict(self._fields['work_unit_type'].selection).get(rec.work_unit_type, rec.work_unit_type)
                raise ValidationError(f"A score allocation configuration already exists for work unit type '{type_label}'.")

    @api.constrains('work_unit_weight', 'employee_weight')
    def _check_weights(self):
        for rec in self:
            if rec.work_unit_weight < 0.0 or rec.work_unit_weight > 100.0:
                raise ValidationError("Operating Unit Share (%) must be between 0% and 100%.")
            if rec.employee_weight < 0.0 or rec.employee_weight > 100.0:
                raise ValidationError("Employee Share (%) must be between 0% and 100%.")
            if round(rec.work_unit_weight + rec.employee_weight, 2) != 100.0:
                raise ValidationError(
                    f"The sum of Operating Unit Share ({rec.work_unit_weight}%) and Employee Share ({rec.employee_weight}%) must equal 100%."
                )
