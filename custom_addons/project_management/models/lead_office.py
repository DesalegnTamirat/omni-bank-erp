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
    active = fields.Boolean(string='Active', default=True)

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'The Office Code must be unique!')
    ]

    def name_get(self):
        result = []
        for rec in self:
            name = f"[{rec.code}] {rec.name}" if rec.code else rec.name
            result.append((rec.id, name))
        return result
