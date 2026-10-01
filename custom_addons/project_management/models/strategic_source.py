# -*- coding: utf-8 -*-
from odoo import api, fields, models

class PmStrategicSource(models.Model):
    _name = 'pm.strategic.source'
    _description = 'Strategic Source'
    _order = 'name asc'

    name = fields.Char(string='Strategic Source', required=True)
    code = fields.Char(string='Code')
    description = fields.Text(string='Description & Context')
    active = fields.Boolean(string='Active', default=True)
