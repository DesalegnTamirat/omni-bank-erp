# -*- coding: utf-8 -*-
from odoo import fields, models

class HrJobFamily(models.Model):
    """Job Family configuration (FR-CFW-002)"""
    _name = 'hr.job.family'
    _description = 'Job Family'
    _order = 'name'

    name = fields.Char(string='Job Family Name', required=True, translate=True)
    description = fields.Text(string='Description')
    job_ids = fields.One2many('hr.job', 'job_family_id', string='Roles in Family')
    active = fields.Boolean(default=True)

class HrCareerTrack(models.Model):
    """Career Track configuration (FR-CFW-003)"""
    _inherit = 'hr.career.track'
    _description = 'Career Track'
    _order = 'sequence, name'

    name = fields.Char(string='Track Name', required=True, translate=True)
    sequence = fields.Integer(default=10)
    track_type = fields.Selection([
        ('leadership', 'Managerial / Leadership'),
        ('technical', 'Professional / Technical'),
        ('valuestream', 'Value-Stream / Project')
    ], string='Track Type', required=True)
    description = fields.Text(string='Description')
    active = fields.Boolean(default=True)

class HrJobInherit(models.Model):
    _inherit = 'hr.job'

    job_family_id = fields.Many2one('hr.job.family', string='Job Family')
    career_track_id = fields.Many2one('hr.career.track', string='Career Track')
    career_level = fields.Integer(string='Career Level', help='Numeric level for progression mapping (e.g. 1-10)')
