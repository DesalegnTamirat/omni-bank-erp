# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
import odoo.tools as tools


class HelpdeskTicketDoneWizard(models.TransientModel):
    _name = "helpdesk.ticket.done.wizard"
    _description = "Helpdesk Ticket Completion & Agent Response Wizard"

    ticket_id = fields.Many2one(
        "helpdesk.ticket",
        string="Ticket",
        required=True,
        readonly=True,
    )
    ticket_number = fields.Char(related="ticket_id.number", string="Ticket Number", readonly=True)
    ticket_name = fields.Char(related="ticket_id.name", string="Subject", readonly=True)
    current_stage_id = fields.Many2one(related="ticket_id.stage_id", string="Current Stage", readonly=True)
    customer_request_details = fields.Text(related="ticket_id.customer_request_details", string="Customer Inquiry", readonly=True)
    target_stage_id = fields.Many2one("helpdesk.ticket.stage", string="Target Stage")

    is_escalated = fields.Boolean(
        string="Is Escalated Ticket",
        compute="_compute_is_escalated",
        store=True,
        readonly=False,
    )
    agent_response = fields.Text(
        string="Agent Response",
        help="Initial response / notes provided by the agent.",
    )
    escalated_agent_response = fields.Text(
        string="Escalated Agent Response",
        help="Detail the resolution steps and guidance provided by the escalated specialist/operating unit.",
    )
    save_to_kb = fields.Boolean(
        string="Save to Knowledge Base",
        default=True,
        help="If checked, this resolution will be published to the Helpdesk Knowledge Base for future agent guidance.",
    )
    kb_title = fields.Char(
        string="Knowledge Base Article Title",
        help="Optional title for the KB article. Defaults to inquiry summary or ticket title.",
    )

    @api.depends("ticket_id", "ticket_id.is_escalated", "ticket_id.is_reopened", "ticket_id.stage_id", "ticket_id.escalation_level", "ticket_id.agent_action_taken")
    def _compute_is_escalated(self):
        for wiz in self:
            ticket = wiz.ticket_id
            if ticket:
                stage_name = (ticket.stage_id.name or "").lower() if ticket.stage_id else ""
                has_initial = bool(ticket.agent_action_taken and ticket.agent_action_taken.strip())
                wiz.is_escalated = bool(
                    ticket.is_escalated
                    or ticket.is_reopened
                    or has_initial
                    or "escalat" in stage_name
                    or (ticket.escalation_level and ticket.escalation_level > 1)
                    or self.env.context.get("default_is_escalated")
                )
            else:
                wiz.is_escalated = bool(self.env.context.get("default_is_escalated", False))

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ticket_id = self.env.context.get("default_ticket_id") or self.env.context.get("active_id")
        if ticket_id:
            ticket = self.env["helpdesk.ticket"].browse(ticket_id)
            if ticket.exists():
                res["ticket_id"] = ticket.id
                stage_name = (ticket.stage_id.name or "").lower() if ticket.stage_id else ""
                has_initial = bool(ticket.agent_action_taken and ticket.agent_action_taken.strip())
                is_esc = bool(
                    ticket.is_escalated
                    or ticket.is_reopened
                    or has_initial
                    or "escalat" in stage_name
                    or (ticket.escalation_level and ticket.escalation_level > 1)
                    or self.env.context.get("default_is_escalated")
                )
                res["is_escalated"] = is_esc
                res["agent_response"] = ticket.agent_action_taken or ""
                # Escalated Agent Response must always be empty when opening the Done wizard
                # so the resolving agent writes their fresh resolution response
                res["escalated_agent_response"] = ""
                if not res.get("kb_title"):
                    res["kb_title"] = ticket.inquiry_summary or ticket.name or ticket.number
        return res

    def action_confirm_done(self):
        self.ensure_one()
        ticket = self.ticket_id
        stage_name = (ticket.stage_id.name or "").lower() if ticket and ticket.stage_id else ""
        has_initial = bool(ticket and ticket.agent_action_taken and ticket.agent_action_taken.strip())
        is_esc = bool(
            self.is_escalated
            or (ticket and ticket.is_escalated)
            or (ticket and ticket.is_reopened)
            or has_initial
            or "escalat" in stage_name
            or (ticket and ticket.escalation_level and ticket.escalation_level > 1)
        )

        if is_esc:
            if not self.escalated_agent_response or not self.escalated_agent_response.strip():
                raise ValidationError(_("Please enter an Escalated Agent Response before completing the ticket."))
            response_text = self.escalated_agent_response.strip()
            vals = {
                "escalated_agent_response": response_text,
            }
        else:
            if not self.agent_response or not self.agent_response.strip():
                raise ValidationError(_("Please enter an Agent Response before completing the ticket."))
            response_text = self.agent_response.strip()
            vals = {
                "agent_action_taken": response_text,
            }

        done_stage = self.target_stage_id
        if not done_stage:
            done_stage = self.env["helpdesk.ticket.stage"].search(
                [("name", "ilike", "done")], limit=1
            )
        if not done_stage:
            done_stage = self.env["helpdesk.ticket.stage"].search(
                [("closed", "=", True)], limit=1
            )

        if done_stage:
            vals["stage_id"] = done_stage.id

        ticket.with_context(from_done_wizard=True).write(vals)

        # Save to Knowledge Base if checked
        kb_article = False
        if self.save_to_kb:
            kb_title = (self.kb_title or ticket.inquiry_summary or ticket.name or ticket.number).strip()
            content_parts = []
            if ticket.customer_request_details:
                details_html = tools.html_escape(ticket.customer_request_details).replace("\n", "<br/>")
                content_parts.append(f"<h3>Customer Inquiry / Issue Context</h3><p>{details_html}</p>")

            if is_esc and ticket.agent_action_taken:
                escalater_html = tools.html_escape(ticket.agent_action_taken.strip()).replace("\n", "<br/>")
                content_parts.append(f"<h3>Initial Agent Response (Escalater)</h3><p>{escalater_html}</p>")
                action_html = tools.html_escape(response_text).replace("\n", "<br/>")
                content_parts.append(f"<h3>Escalated Specialist Resolution</h3><p>{action_html}</p>")
            else:
                action_html = tools.html_escape(response_text).replace("\n", "<br/>")
                content_parts.append(f"<h3>Standard Resolution Steps / Guidance</h3><p>{action_html}</p>")

            meta_info = f"<hr/><p><small><em>Authored from Ticket {ticket.display_name} on {fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</em></small></p>"
            full_content = "".join(content_parts) + meta_info

            author_user = ticket.user_id or self.env.user
            emp = self.env["hr.employee"].sudo().search([("user_id", "=", author_user.id)], limit=1)
            authoring_ou = ticket.operating_unit_id or (emp.default_operating_unit_id if emp else False)

            kb_article = self.env["helpdesk.knowledge.article"].create({
                "name": kb_title,
                "agent_response": response_text,
                "service_family_id": ticket.service_family_id.id if ticket.service_family_id else False,
                "service_id": ticket.service_id.id if ticket.service_id else False,
                "sub_category_id": ticket.service_sub_category_id.id if ticket.service_sub_category_id else False,
                "operating_unit_id": authoring_ou.id if authoring_ou else False,
                "tag_ids": [(6, 0, ticket.tag_ids.ids)] if ticket.tag_ids else False,
                "author_id": author_user.id,
                "content": full_content,
                "state": "published",
            })
            ticket.kb_article_id = kb_article.id

        # Post chatter note
        kb_note = f"<br/>• <strong>Knowledge Base Article:</strong> {kb_article.name} (Published)" if kb_article else ""
        if is_esc:
            escalater_note = f"<br/>• <strong>Initial Escalater Response:</strong> {ticket.agent_action_taken}" if ticket.agent_action_taken else ""
            ticket.message_post(
                body=f"<div><strong>✅ Ticket Resolved &amp; Completed (Done)</strong><br/>"
                     f"• <strong>Resolved By (Escalated Specialist):</strong> {self.env.user.name}"
                     f"{escalater_note}<br/>"
                     f"• <strong>Escalated Agent Response:</strong> {response_text}"
                     f"{kb_note}</div>",
                subtype_xmlid="mail.mt_note",
                body_is_html=True,
            )
        else:
            ticket.message_post(
                body=f"<div><strong>✅ Ticket Completed (Done)</strong><br/>"
                     f"• <strong>Completed By:</strong> {self.env.user.name}<br/>"
                     f"• <strong>Agent Response:</strong> {response_text}"
                     f"{kb_note}</div>",
                subtype_xmlid="mail.mt_note",
                body_is_html=True,
            )

        return {"type": "ir.actions.act_window_close"}
