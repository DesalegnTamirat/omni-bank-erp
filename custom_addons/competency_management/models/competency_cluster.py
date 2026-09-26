# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class CompetencyCluster(models.Model):
    """Groups related competencies with a minimum proficiency requirement.
    
    Shared globally across all companies to maintain a unified bank-wide
    competency framework.
    """
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
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'The Competency Cluster code must be unique!'),
    ]
