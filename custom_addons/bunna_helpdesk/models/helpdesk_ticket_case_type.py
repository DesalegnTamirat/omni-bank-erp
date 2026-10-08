# -*- coding: utf-8 -*-
from odoo import fields, models


class HelpdeskTicketCaseType(models.Model):
    _name = "helpdesk.ticket.case.type"
    _description = "Helpdesk Ticket Case Type"
    _order = "sequence, name"

    name = fields.Char(string="Case Type Name", required=True, translate=True)
    code = fields.Char(string="Code / Identifier", required=True, index=True)
    sequence = fields.Integer(string="Sequence", default=10)
    is_nbe_complaint = fields.Boolean(
        string="NBE Regulated Complaint",
        default=False,
        help="Check if tickets under this case type require mandatory NBE regulatory compliance tracking and CAPA.",
    )
    default_priority = fields.Selection(
        selection=[
            ("0", "Low"),
            ("1", "Medium"),
            ("2", "High"),
            ("3", "Very High"),
        ],
        string="Default Priority",
        default="1",
    )
    active = fields.Boolean(default=True)
    description = fields.Text(string="Description / Scope")
