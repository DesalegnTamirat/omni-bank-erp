# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HelpdeskOLA(models.Model):
    """Operational Level Agreement (OLA) defining Service Delivery Time (SDT) between CC and 2nd Level Teams"""
    _name = "helpdesk.ola"
    _description = "Operational Level Agreement (OLA)"
    _order = "name"

    name = fields.Char(string="OLA Title / Agreement Name", required=True)
    active = fields.Boolean(default=True)
    service_id = fields.Many2one(
        comodel_name="helpdesk.service",
        string="Target Service",
        index=True,
    )
    sub_category_id = fields.Many2one(
        comodel_name="helpdesk.service.sub.category",
        string="Service Sub-Category",
        domain="[('service_id', '=', service_id)] if service_id else []",
    )
    requesting_team_id = fields.Many2one(
        comodel_name="helpdesk.ticket.team",
        string="First Level Team (e.g. Contact Center)",
        help="The team initiating or escalating the customer request.",
    )
    providing_team_id = fields.Many2one(
        comodel_name="helpdesk.ticket.team",
        string="Service Provider / 2nd Level Team",
        help="The 2nd level work unit or team responsible for resolving the escalated case.",
    )
    operating_unit_id = fields.Many2one(
        comodel_name="operating.unit",
        string="Work Unit / Directorate",
        help="Internal work unit responsible for this OLA commitment.",
    )
    delivery_time_unit = fields.Selection(
        selection=[
            ("minutes", "Minutes"),
            ("hours", "Hours"),
            ("days", "Days"),
        ],
        string="Time Unit",
        default="hours",
        required=True,
    )
    delivery_time_value = fields.Float(
        string="Service Delivery Time (SDT)",
        default=24.0,
        required=True,
        help="Agreed response/resolution duration.",
    )
    target_hours = fields.Float(
        string="Target Hours",
        compute="_compute_target_hours",
        store=True,
    )
    ola_attachment_ids = fields.Many2many(
        comodel_name="ir.attachment",
        relation="helpdesk_ola_attachment_rel",
        column1="ola_id",
        column2="attachment_id",
        string="Signed OLA Document(s)",
        help="Upload the official signed OLA document or SOP.",
    )
    notes = fields.Text(string="Responsibilities & Terms")

    @api.depends("delivery_time_unit", "delivery_time_value")
    def _compute_target_hours(self):
        for rec in self:
            if rec.delivery_time_unit == "minutes":
                rec.target_hours = rec.delivery_time_value / 60.0
            elif rec.delivery_time_unit == "days":
                rec.target_hours = rec.delivery_time_value * 24.0
            else:
                rec.target_hours = rec.delivery_time_value
