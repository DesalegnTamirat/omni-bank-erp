# -*- coding: utf-8 -*-
from odoo import models, fields


class CompetencyCompetency(models.Model):
    """Base competency definition in hr_employee_custom.
    Extended with full dictionary, clusters, proficiency levels, and role mappings
    by the competency_management module.
    """
    _name = 'competency.competency'
    _description = 'Competency'
    _order = 'name'

    name = fields.Char(string='Competency Name', required=True)
    code = fields.Char(string='Competency Code')
    description = fields.Text(string='Description')
    active = fields.Boolean(default=True)
