# -*- coding: utf-8 -*-
from odoo import fields, models




class HelpdeskSla(models.Model):
    _name = "helpdesk.sla"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Helpdesk SLA"

    name = fields.Char(required=True)
    company_id = fields.Many2one(comodel_name="res.company", string="Company")
    team_ids = fields.Many2many(comodel_name="helpdesk.ticket.team", string="Teams")
    category_ids = fields.Many2many(
        comodel_name="helpdesk.ticket.category", string="Categories"
    )
    tag_ids = fields.Many2many(comodel_name="helpdesk.ticket.tag", string="Tags")
    ignore_stage_ids = fields.Many2many("helpdesk.ticket.stage", string="Ignore Stages")
    stage_id = fields.Many2one("helpdesk.ticket.stage")
    days = fields.Integer(default=0, required=True)
    hours = fields.Integer(default=0, required=True)
    sdt_minutes = fields.Integer(
        string="SDT (Target Minutes)",
        default=0,
        help="Service Delivery Time target in minutes",
    )
    work_unit_id = fields.Many2one(
        "hr.department", string="Responsible Work Unit / Directorate"
    )
    ola_document_ids = fields.Many2many(
        "ir.attachment",
        "helpdesk_sla_ola_attachment_rel",
        "sla_id",
        "attachment_id",
        string="Signed OLA Documents",
    )
    note = fields.Html()
    domain = fields.Char(string="Filter", default="[]")
    active = fields.Boolean(default=True)
