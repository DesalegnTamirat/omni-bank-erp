# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class CompetencyCluster(models.Model):
    """Bundling related competencies with minimum proficiency requirement (FR-CFD-0176)."""
    _name = 'competency.cluster'
    _description = 'Competency Cluster'
    _order = 'code, name'

    name = fields.Char(string='Cluster Name', required=True)
    code = fields.Char(string='Cluster Code', required=True)
    description = fields.Text(string='Description')
    competency_ids = fields.Many2many(
        'competency.competency', 'competency_cluster_rel', 'cluster_id', 'competency_id',
        string='Competencies in Cluster', required=True,
        domain="[('state', '=', 'approved'), ('status', '=', 'active')]")
    min_proficiency = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Minimum Required Proficiency', required=True, default='2')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'The Competency Cluster code must be unique!'),
    ]
