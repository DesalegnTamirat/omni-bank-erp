# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class PmProjectRole(models.Model):
    _name = 'pm.project.role'
    _description = 'Project Team Role'
    _order = 'sequence asc, name asc'

    name = fields.Char(string='Role Title', required=True)
    code = fields.Char(string='Code')
    sequence = fields.Integer(string='Sequence', default=10)
    description = fields.Text(string='Description / Responsibilities')
    active = fields.Boolean(string='Active', default=True)
    member_count = fields.Integer(string='Assigned Members', compute='_compute_member_count')

    def _compute_member_count(self):
        for role in self:
            role.member_count = self.env['pm.project.team'].search_count([('role_id', '=', role.id)])


class PmProjectTeam(models.Model):
    _name = 'pm.project.team'
    _description = 'Project Team Member & Role'
    _order = 'id desc'

    project_id = fields.Many2one('pm.project', string='Project', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', string='Member Name', required=True)
    role_id = fields.Many2one('pm.project.role', string='Role', required=True, ondelete='restrict')
    role = fields.Char(string='Legacy Role')
    status = fields.Selection([
        ('active', 'Active'),
        ('inactive', 'Inactive')
    ], string='Status', default='active', required=False)
    notes = fields.Char(string='Responsibilities / Notes')

    _sql_constraints = [
        ('project_user_role_unique', 'unique(project_id, user_id, role_id)', 'A user cannot have duplicate identical roles in the same project!')
    ]
