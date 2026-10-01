# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

class PmTaskTag(models.Model):
    _name = 'pm.task.tag'
    _description = 'Task Tag'

    name = fields.Char(string='Tag Name', required=True, translate=True)
    color = fields.Integer(string='Color Index', default=0)

    @api.constrains('name')
    def _check_name_uniq(self):
        for rec in self:
            if self.search_count([('name', '=ilike', rec.name), ('id', '!=', rec.id)]) > 0:
                raise ValidationError(_("A tag with the name '%s' already exists!") % rec.name)