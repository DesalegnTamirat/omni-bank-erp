# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class PmTaskTag(models.Model):
    _name = 'pm.task.tag'
    _description = 'Project Type / Tag'

    name = fields.Char(string='Project Type / Tag Name', required=True, translate=True)
    color = fields.Integer(string='Color Index', default=0)

    @api.constrains('name')
    def _check_name_uniq(self):
        for rec in self:
            if self.search_count([('name', '=ilike', rec.name), ('id', '!=', rec.id)]) > 0:
                raise ValidationError(_("A Project Type with the name '%s' already exists!") % rec.name)
