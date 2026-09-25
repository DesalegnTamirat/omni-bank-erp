# -*- coding: utf-8 -*-
from odoo import fields, models


class HelpdeskServiceFamily(models.Model):
    _name = "helpdesk.service.family"
    _description = "Helpdesk Service Family"
    _order = "name"

    name = fields.Char(string="Service Family", required=True, translate=True)
    code = fields.Char(string="Code")
    description = fields.Text(string="Description")
    active = fields.Boolean(string="Active", default=True)
    category_ids = fields.One2many(
        "helpdesk.ticket.category",
        "service_family_id",
        string="Categories",
    )
