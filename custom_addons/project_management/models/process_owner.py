# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class PmProcessOwner(models.Model):
    _name = 'pm.process.owner'
    _description = 'Process Owner Work Unit'
    _order = 'name asc'

    code = fields.Char(string='Code / Acronym', required=True)
    name = fields.Char(string='Office / Work Unit Name', required=True)
    head_id = fields.Many2one('res.users', string='Leader / Process Owner Head', required=True)
    user_id = fields.Many2one('res.users', string='Executive User', compute='_compute_user_id', store=True)
    color = fields.Integer(default=0)
    active = fields.Boolean(string='Active', default=True)

    project_ids = fields.Many2many(
        'pm.project',
        'pm_project_process_owner_rel',
        'process_owner_id',
        'project_id',
        string='Projects'
    )
    project_count = fields.Integer(string='Projects Count', compute='_compute_project_count')

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'The Process Owner Code must be unique!')
    ]

    @api.depends('head_id')
    def _compute_user_id(self):
        for rec in self:
            rec.user_id = rec.head_id

    @api.depends('project_ids')
    def _compute_project_count(self):
        for rec in self:
            rec.project_count = len(rec.project_ids)

    def name_get(self):
        result = []
        for rec in self:
            name = f"[{rec.code}] {rec.name}" if rec.code else rec.name
            result.append((rec.id, name))
        return result

    def action_view_projects(self):
        self.ensure_one()
        return {
            'name': _('Projects for %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'pm.project',
            'view_mode': 'kanban,list,form',
            'domain': [('process_owner_ids', 'in', self.id)],
            'context': {'default_process_owner_ids': [(4, self.id)]},
        }

    def unlink(self):
        """Soft delete: archive process owner instead of permanent deletion."""
        return self.write({'active': False})

