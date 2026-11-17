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
        string="Service",
        index=True,
    )
    sub_category_id = fields.Many2one(
        comodel_name="helpdesk.service.sub.category",
        string="Sub Service",
        domain="[('service_id', '=', service_id)] if service_id else []",
    )
    def _default_requesting_team_id(self):
        ou = self.env["operating.unit"].search([
            ("name", "ilike", "Contact Center"),
        ], limit=1)
        if not ou:
            ou = self.env["operating.unit"].search([
                ("name", "ilike", "Main Operating Unit"),
            ], limit=1)
        return ou

    requesting_team_id = fields.Many2one(
        comodel_name="operating.unit",
        string="First Level Team (e.g. Contact Center)",
        default=_default_requesting_team_id,
        help="The operating unit initiating or escalating the customer request (e.g. Contact Center).",
    )
    providing_team_id = fields.Many2one(
        comodel_name="operating.unit",
        string="Service Provider",
        help="The 2nd level work unit or directorate responsible for resolving the escalated case.",
    )
    operating_unit_id = fields.Many2one(
        comodel_name="operating.unit",
        string="Sub Service Provider",
        help="Internal sub-work unit or branch responsible for this OLA commitment.",
    )

    @api.onchange("service_id")
    def _onchange_service_id(self):
        if self.service_id:
            if self.service_id.operating_unit_id:
                self.providing_team_id = self.service_id.operating_unit_id
                self.operating_unit_id = self.service_id.operating_unit_id
            if self.service_id.default_sdt_hours:
                self.delivery_time_value = self.service_id.default_sdt_hours
                self.delivery_time_unit = "hours"

    @api.onchange("providing_team_id")
    def _onchange_providing_team_id(self):
        if self.providing_team_id:
            self.operating_unit_id = self.providing_team_id

    @api.onchange("operating_unit_id")
    def _onchange_operating_unit_id(self):
        if self.operating_unit_id and not self.providing_team_id:
            self.providing_team_id = self.operating_unit_id

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
        inverse="_inverse_target_hours",
        store=True,
        readonly=False,
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

    def _inverse_target_hours(self):
        for rec in self:
            if rec.target_hours is not False and rec.target_hours is not None:
                rec.delivery_time_unit = "hours"
                rec.delivery_time_value = rec.target_hours
