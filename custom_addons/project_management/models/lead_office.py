# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class PmLeadOffice(models.Model):
    _name = 'pm.lead.office'
    _description = 'Project Lead Office / Directorate'
    _order = 'name asc'

    name = fields.Char(string='Office / Directorate Name', required=True)
    code = fields.Char(string='Code / Acronym', required=True, help='Organizational Directorate or Office acronym.')
    description = fields.Text(string='Scope & Mandate')
    head_id = fields.Many2one('res.users', string='Director / Office Head')
    color = fields.Integer(default=0)
    active = fields.Boolean(string='Active', default=True)

    project_ids = fields.Many2many(
        'pm.project',
        'pm_project_lead_office_rel',
        'lead_office_id',
        'project_id',
        string='Projects'
    )
    project_count = fields.Integer(string='Projects Count', compute='_compute_project_count')

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'The Office Code must be unique!')
    ]

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
            'domain': [('lead_office_ids', 'in', self.id)],
            'context': {'default_lead_office_ids': [(4, self.id)]},
        }

    def unlink(self):
        """Soft delete: archive lead office instead of permanent deletion."""
        return self.write({'active': False})

