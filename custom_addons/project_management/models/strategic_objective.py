# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class PmStrategicObjective(models.Model):
    _name = 'pm.strategic.objective'
    _description = 'Strategic Objective'
    _order = 'name asc'

    name = fields.Char(string='Strategic Objective', required=True)
    code = fields.Char(string='ID / Code', readonly=True, copy=False, default=lambda self: _('New'))
    description = fields.Text(string='Description & Scope')
    active = fields.Boolean(string='Active', default=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code') or vals.get('code') == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('pm.strategic.objective') or _('New')
        return super().create(vals_list)
