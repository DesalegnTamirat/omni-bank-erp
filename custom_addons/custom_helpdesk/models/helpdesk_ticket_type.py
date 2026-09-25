# -*- coding: utf-8 -*-
from odoo import fields, models



class HelpdeskType(models.Model):
    """Helpdesk Type"""

    _name = "helpdesk.ticket.type"
    _description = "Helpdesk Ticket Type"
    _order = "name asc"

    name = fields.Char(required=True, translate=True)
    team_ids = fields.Many2many(
        "helpdesk.ticket.team",
        string="Teams",
        help="Helpdesk teams allowed to use this type.",
    )
    active = fields.Boolean(default=True)
    show_in_portal = fields.Boolean(
        string="Show type in portal form",
        default=True,
        help="Allow to select type when creating a new ticket in the portal.",
    )
