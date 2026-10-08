# -*- coding: utf-8 -*-
from odoo import api, fields, models, _

class PmStrategicSource(models.Model):
    _name = 'pm.strategic.source'
    _description = 'Strategic Source'
    _order = 'name asc'

    name = fields.Char(string='Strategic Source', required=True)
    code = fields.Char(string='ID / Code', readonly=True, copy=False, default=lambda self: _('New'))
    description = fields.Text(string='Description & Context')
    active = fields.Boolean(string='Active', default=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code') or vals.get('code') == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('pm.strategic.source') or _('New')
        return super().create(vals_list)
