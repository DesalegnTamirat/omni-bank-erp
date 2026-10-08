# -*- coding: utf-8 -*-
from odoo import fields, models


class HelpdeskKnowledgeArticle(models.Model):
    """Support Knowledge Base Articles, SOPs, FAQs & Troubleshooting Guides"""
    _name = "helpdesk.knowledge.article"
    _description = "Knowledge Base Article"
    _order = "sequence, name"

    name = fields.Char(string="Article Title", required=True)
    sequence = fields.Integer(string="Sequence", default=10)
    service_family_id = fields.Many2one(
        comodel_name="helpdesk.service.family",
        string="Service Family",
        index=True,
    )
    service_id = fields.Many2one(
        comodel_name="helpdesk.service",
        string="Service",
        domain="[('family_id', '=', service_family_id)] if service_family_id else []",
        index=True,
    )
    sub_category_id = fields.Many2one(
        comodel_name="helpdesk.service.sub.category",
        string="Sub-Category / Issue",
        domain="[('service_id', '=', service_id)] if service_id else []",
    )
    operating_unit_id = fields.Many2one(
        comodel_name="operating.unit",
        string="Authoring Work Unit",
        help="The Bank work unit responsible for authoring and maintaining this SOP.",
    )
    author_id = fields.Many2one(
        comodel_name="res.users",
        string="Author",
        default=lambda self: self.env.user,
    )
    approver_id = fields.Many2one(
        comodel_name="res.users",
        string="Approved By",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("published", "Published"),
            ("archived", "Archived / Obsolete"),
        ],
        string="Status",
        default="published",
    )
    tag_ids = fields.Many2many(
        comodel_name="helpdesk.ticket.tag",
        string="Tags / Keywords",
    )
    content = fields.Html(
        string="Article Content / SOP Details",
        required=True,
    )
    attachment_ids = fields.Many2many(
        comodel_name="ir.attachment",
        relation="helpdesk_knowledge_attachment_rel",
        column1="article_id",
        column2="attachment_id",
        string="Supporting Documents",
    )
    active = fields.Boolean(default=True)
