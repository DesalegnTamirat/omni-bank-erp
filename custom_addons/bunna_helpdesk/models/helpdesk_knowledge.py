from odoo import api, fields, models


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
        index=True,
    )
    sub_category_id = fields.Many2one(
        comodel_name="helpdesk.service.sub.category",
        string="Sub Service",
        domain="[('service_id', '=', service_id)] if service_id else []",
    )
    operating_unit_id = fields.Many2one(
        comodel_name="operating.unit",
        string="Authoring Work Unit",
        default=lambda self: self._default_operating_unit_id(),
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
    agent_response = fields.Text(
        string="Agent Response",
        tracking=True,
        help="Standard verified agent response provided to customer inquiries.",
    )
    content = fields.Html(
        string="Article Content / SOP Details",
        required=False,
    )
    attachment_ids = fields.Many2many(
        comodel_name="ir.attachment",
        relation="helpdesk_knowledge_attachment_rel",
        column1="article_id",
        column2="attachment_id",
        string="Supporting Documents",
    )
    active = fields.Boolean(default=True)

    @api.model_create_multi
    def create(self, vals_list):
        from odoo import tools
        for vals in vals_list:
            if vals.get("agent_response") and not vals.get("content"):
                vals["content"] = f"<p>{tools.html_escape(vals['agent_response']).replace(chr(10), '<br/>')}</p>"
            elif vals.get("content") and not vals.get("agent_response"):
                vals["agent_response"] = tools.html2plaintext(vals["content"]).strip()
        return super().create(vals_list)

    def write(self, vals):
        from odoo import tools
        if vals.get("agent_response") and "content" not in vals:
            for art in self:
                if not art.content:
                    vals["content"] = f"<p>{tools.html_escape(vals['agent_response']).replace(chr(10), '<br/>')}</p>"
        elif vals.get("content") and "agent_response" not in vals:
            vals["agent_response"] = tools.html2plaintext(vals["content"]).strip()
        return super().write(vals)

    @api.model
    def _default_operating_unit_id(self):
        emp = self.env["hr.employee"].sudo().search([("user_id", "=", self.env.uid)], limit=1)
        if emp and emp.default_operating_unit_id:
            return emp.default_operating_unit_id.id
        if hasattr(self.env.user, "default_operating_unit_id") and self.env.user.default_operating_unit_id:
            return self.env.user.default_operating_unit_id.id
        return False

    @api.onchange("author_id")
    def _onchange_author_id(self):
        if self.author_id:
            emp = self.env["hr.employee"].sudo().search([("user_id", "=", self.author_id.id)], limit=1)
            if emp and emp.default_operating_unit_id:
                self.operating_unit_id = emp.default_operating_unit_id
            elif hasattr(self.author_id, "default_operating_unit_id") and self.author_id.default_operating_unit_id:
                self.operating_unit_id = self.author_id.default_operating_unit_id

    @api.onchange("service_id", "service_family_id")
    def _onchange_service_mapping_ou(self):
        if not self.operating_unit_id:
            if self.service_id and self.service_id.operating_unit_id:
                self.operating_unit_id = self.service_id.operating_unit_id
            elif self.service_family_id and self.service_family_id.operating_unit_id:
                self.operating_unit_id = self.service_family_id.operating_unit_id
