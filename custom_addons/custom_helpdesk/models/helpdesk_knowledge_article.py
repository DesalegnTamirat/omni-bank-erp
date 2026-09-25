# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HelpdeskKnowledgeArticle(models.Model):
    _name = "helpdesk.knowledge.article"
    _description = "Helpdesk Knowledge Base Article"
    _order = "create_date desc, id desc"

    name = fields.Char(string="Title", required=True)
    service_family_id = fields.Many2one(
        "helpdesk.service.family", string="Service Family"
    )
    category_id = fields.Many2one(
        "helpdesk.ticket.category", string="Category / Sub-Service"
    )
    work_unit_id = fields.Many2one(
        "hr.department", string="Responsible Work Unit"
    )
    author_id = fields.Many2one(
        "res.users", string="Author", default=lambda self: self.env.user
    )
    content = fields.Html(string="Article Content / SOP", required=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("approved", "Approved"),
            ("published", "Published"),
            ("obsolete", "Obsolete"),
        ],
        string="Status",
        default="draft",
        required=True,
    )
    active = fields.Boolean(string="Active", default=True)
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "helpdesk_knowledge_article_rel",
        "article_id",
        "attachment_id",
        string="Attachments",
    )

    def action_approve(self):
        self.write({"state": "approved"})

    def action_publish(self):
        self.write({"state": "published"})

    def action_set_obsolete(self):
        self.write({"state": "obsolete", "active": False})

    def action_reset_draft(self):
        self.write({"state": "draft", "active": True})
