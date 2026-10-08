# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HelpdeskServiceFamily(models.Model):
    """Tier 1 of Service Catalogue: Service Family (e.g. CBS Services, Digital Products, Digital Dispute)"""
    _name = "helpdesk.service.family"
    _description = "Service Family"
    _order = "sequence, name"

    name = fields.Char(string="Service Family", required=True, translate=True)
    code = fields.Char(string="Code")
    sequence = fields.Integer(string="Sequence", default=10)
    description = fields.Text(string="Description")
    active = fields.Boolean(default=True)
    service_ids = fields.One2many(
        comodel_name="helpdesk.service",
        inverse_name="family_id",
        string="Services",
    )
    service_count = fields.Integer(
        string="Service Count",
        compute="_compute_service_count",
    )

    @api.depends("service_ids")
    def _compute_service_count(self):
        for rec in self:
            rec.service_count = len(rec.service_ids)


class HelpdeskService(models.Model):
    """Tier 2 of Service Catalogue: Specific Service (e.g. Digital Financial Services, On-Us ATM Service)"""
    _name = "helpdesk.service"
    _description = "Service"
    _order = "sequence, name"

    name = fields.Char(string="Service Name", required=True, translate=True)
    code = fields.Char(string="Code")
    sequence = fields.Integer(string="Sequence", default=10)
    family_id = fields.Many2one(
        comodel_name="helpdesk.service.family",
        string="Service Family",
        required=True,
        ondelete="cascade",
        index=True,
    )
    responsible_team_id = fields.Many2one(
        comodel_name="helpdesk.ticket.team",
        string="Responsible 2nd-Level Team",
        help="Default 2nd level team / unit responsible for handling escalated cases of this service.",
    )
    operating_unit_id = fields.Many2one(
        comodel_name="operating.unit",
        string="Work Unit / Directorate",
        help="Bank work unit or directorate owning this service.",
    )
    default_sdt_hours = fields.Float(
        string="Default SDT (Hours)",
        default=24.0,
        help="Standard Service Delivery Time in hours under the OLA agreement.",
    )
    sub_category_ids = fields.One2many(
        comodel_name="helpdesk.service.sub.category",
        inverse_name="service_id",
        string="Sub-Categories",
    )
    sub_category_count = fields.Integer(
        string="Sub-Category Count",
        compute="_compute_sub_category_count",
    )
    active = fields.Boolean(default=True)

    @api.depends("sub_category_ids")
    def _compute_sub_category_count(self):
        for rec in self:
            rec.sub_category_count = len(rec.sub_category_ids)

    def name_get(self):
        return [(rec.id, f"{rec.family_id.name} / {rec.name}" if rec.family_id else rec.name) for rec in self]


class HelpdeskServiceSubCategory(models.Model):
    """Tier 3 of Service Catalogue: Service Sub-Category (e.g. ATM Dispute, Telebirr Case, A2A Dispute)"""
    _name = "helpdesk.service.sub.category"
    _description = "Service Sub-Category"
    _order = "sequence, name"

    name = fields.Char(string="Sub-Category / Issue Type", required=True, translate=True)
    code = fields.Char(string="Code")
    sequence = fields.Integer(string="Sequence", default=10)
    service_id = fields.Many2one(
        comodel_name="helpdesk.service",
        string="Service",
        required=True,
        ondelete="cascade",
        index=True,
    )
    family_id = fields.Many2one(
        comodel_name="helpdesk.service.family",
        string="Service Family",
        related="service_id.family_id",
        store=True,
        readonly=True,
    )
    default_priority = fields.Selection(
        selection=[
            ("0", "Low"),
            ("1", "Medium"),
            ("2", "High"),
            ("3", "Critical"),
        ],
        string="Default Priority",
        default="1",
    )
    resolution_sop = fields.Html(
        string="Resolution SOP / Standard Guide",
        help="Step-by-step guidance for CC agents and support staff to troubleshoot and resolve this issue.",
    )
    active = fields.Boolean(default=True)

    def name_get(self):
        return [(rec.id, f"{rec.service_id.name} → {rec.name}" if rec.service_id else rec.name) for rec in self]
