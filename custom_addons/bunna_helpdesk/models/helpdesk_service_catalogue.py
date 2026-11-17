# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HelpdeskServiceFamily(models.Model):
    """Tier 1 of Service Catalogue: Service (e.g. CBS Services, Digital Products, Digital Dispute)"""
    _name = "helpdesk.service.family"
    _description = "Service"
    _order = "sequence, name"

    name = fields.Char(string="Service", required=True, translate=True)
    code = fields.Char(string="Code")
    sequence = fields.Integer(string="Sequence", default=10)
    operating_unit_id = fields.Many2one(
        comodel_name="operating.unit",
        string="Operating Unit / Directorate",
        help="Bank work unit or directorate owning this service.",
        index=True,
    )
    parent_operating_unit_id = fields.Many2one(
        comodel_name="operating.unit",
        string="Parent Operating Unit / Directorate",
        compute="_compute_parent_operating_unit",
        store=True,
    )
    operating_unit_hierarchy = fields.Char(
        string="Operating Unit Hierarchy (to CEO)",
        compute="_compute_parent_operating_unit",
        store=True,
    )
    description = fields.Text(string="Description")
    active = fields.Boolean(default=True)
    service_ids = fields.One2many(
        comodel_name="helpdesk.service",
        inverse_name="family_id",
        string="Sub Services",
    )
    service_count = fields.Integer(
        string="Sub Service Count",
        compute="_compute_service_count",
    )

    @api.depends("service_ids")
    def _compute_service_count(self):
        for rec in self:
            rec.service_count = len(rec.service_ids)

    @api.depends("operating_unit_id", "operating_unit_id.parent_unit")
    def _compute_parent_operating_unit(self):
        for rec in self:
            if rec.operating_unit_id:
                chain = []
                curr = rec.operating_unit_id
                visited = set()
                while curr and curr.id not in visited:
                    visited.add(curr.id)
                    chain.append(curr.name)
                    curr = curr.parent_unit if curr.parent_unit and curr.parent_unit != curr else False
                rec.parent_operating_unit_id = rec.operating_unit_id.parent_unit
                rec.operating_unit_hierarchy = " ➔ ".join(chain)
            else:
                rec.parent_operating_unit_id = False
                rec.operating_unit_hierarchy = False


class HelpdeskService(models.Model):
    """Service Catalogue: Service (e.g. Digital Financial Services, On-Us ATM Service)"""
    _name = "helpdesk.service"
    _description = "Service"
    _order = "sequence, name"

    name = fields.Char(string="Service Name", required=True, translate=True)
    code = fields.Char(string="Code")
    sequence = fields.Integer(string="Sequence", default=10)
    family_id = fields.Many2one(
        comodel_name="helpdesk.service.family",
        string="Service Family",
        required=False,
        ondelete="set null",
        index=True,
    )
    responsible_team_id = fields.Many2one(
        comodel_name="helpdesk.ticket.team",
        string="Service Provider",
        help="Default operating unit responsible for handling escalated cases of this service.",
    )
    operating_unit_id = fields.Many2one(
        comodel_name="operating.unit",
        string="Service Provider",
        compute="_compute_operating_unit_id",
        store=True,
        readonly=False,
        help="Bank work unit or directorate owning this service.",
    )
    parent_operating_unit_id = fields.Many2one(
        comodel_name="operating.unit",
        string="Parent Service Provider",
        compute="_compute_parent_operating_unit",
        store=True,
    )
    operating_unit_hierarchy = fields.Char(
        string="Operating Unit Hierarchy (to CEO)",
        compute="_compute_parent_operating_unit",
        store=True,
    )
    default_sdt_hours = fields.Float(
        string="Default SDT (Hours)",
        default=24.0,
        help="Standard Service Delivery Time in hours under the OLA agreement.",
    )
    sub_category_ids = fields.One2many(
        comodel_name="helpdesk.service.sub.category",
        inverse_name="service_id",
        string="Sub Services",
    )
    sub_category_count = fields.Integer(
        string="Sub Service Count",
        compute="_compute_sub_category_count",
    )
    active = fields.Boolean(default=True)

    @api.depends("family_id.operating_unit_id")
    def _compute_operating_unit_id(self):
        for rec in self:
            if not rec.operating_unit_id and rec.family_id and rec.family_id.operating_unit_id:
                rec.operating_unit_id = rec.family_id.operating_unit_id

    @api.depends("operating_unit_id", "operating_unit_id.parent_unit", "family_id.operating_unit_id")
    def _compute_parent_operating_unit(self):
        for rec in self:
            ou = rec.operating_unit_id or (rec.family_id and rec.family_id.operating_unit_id)
            if ou:
                chain = []
                curr = ou
                visited = set()
                while curr and curr.id not in visited:
                    visited.add(curr.id)
                    chain.append(curr.name)
                    curr = curr.parent_unit if curr.parent_unit and curr.parent_unit != curr else False
                rec.parent_operating_unit_id = ou.parent_unit
                rec.operating_unit_hierarchy = " ➔ ".join(chain)
            else:
                rec.parent_operating_unit_id = False
                rec.operating_unit_hierarchy = False

    @api.depends("sub_category_ids")
    def _compute_sub_category_count(self):
        for rec in self:
            rec.sub_category_count = len(rec.sub_category_ids)

    def name_get(self):
        return [(rec.id, rec.name) for rec in self]


class HelpdeskServiceSubCategory(models.Model):
    """Service Catalogue: Sub Service (e.g. ATM Dispute, Telebirr Case, A2A Dispute)"""
    _name = "helpdesk.service.sub.category"
    _description = "Sub Service"
    _order = "sequence, name"

    name = fields.Char(string="Sub Service Name", required=True, translate=True)
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
        string="Service",
        related="service_id.family_id",
        store=True,
        readonly=True,
    )
    operating_unit_id = fields.Many2one(
        comodel_name="operating.unit",
        string="Service Provider",
        related="service_id.operating_unit_id",
        store=True,
        readonly=True,
    )
    parent_operating_unit_id = fields.Many2one(
        comodel_name="operating.unit",
        string="Parent Service Provider",
        related="service_id.parent_operating_unit_id",
        store=True,
        readonly=True,
    )
    operating_unit_hierarchy = fields.Char(
        string="Operating Unit Hierarchy (to CEO)",
        related="service_id.operating_unit_hierarchy",
        store=True,
        readonly=True,
    )
    responsible_team_id = fields.Many2one(
        comodel_name="helpdesk.ticket.team",
        string="Service Provider",
        related="service_id.responsible_team_id",
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
