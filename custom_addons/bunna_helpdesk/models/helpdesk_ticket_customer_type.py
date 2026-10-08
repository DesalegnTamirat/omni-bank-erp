# -*- coding: utf-8 -*-
from odoo import fields, models


class HelpdeskTicketCustomerType(models.Model):
    _name = "helpdesk.ticket.customer.type"
    _description = "Helpdesk Ticket Customer Type"
    _order = "sequence, name"

    name = fields.Char(string="Customer Type Name", required=True, translate=True)
    code = fields.Char(string="Code / Identifier", required=True, index=True)
    sequence = fields.Integer(string="Sequence", default=10)
    is_internal = fields.Boolean(
        string="Internal Work Unit / Staff",
        default=False,
        help="Check if this type represents internal bank staff, branches, or Head Office work units.",
    )
    active = fields.Boolean(default=True)
    description = fields.Text(string="Description / Scope")
