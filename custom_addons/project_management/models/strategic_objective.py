# -*- coding: utf-8 -*-
from odoo import api, fields, models

class PmStrategicObjective(models.Model):
    _name = 'pm.strategic.objective'
    _description = 'Strategic Objective'
    _order = 'name asc'

    name = fields.Char(string='Strategic Objective', required=True)
    code = fields.Char(string='Code')
    description = fields.Text(string='Description & Scope')
    active = fields.Boolean(string='Active', default=True)
