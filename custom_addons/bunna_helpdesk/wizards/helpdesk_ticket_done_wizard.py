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
    ticket_name = fields.Char(related="ticket_id.name", string="Sub Service", readonly=True)
    current_stage_id = fields.Many2one(related="ticket_id.stage_id", string="Current Stage", readonly=True)
    customer_request_details = fields.Text(related="ticket_id.customer_request_details", string="Customer Inquiry", readonly=True)
    target_stage_id = fields.Many2one("helpdesk.ticket.stage", string="Target Stage")

    root_case = fields.Char(
        string="Root Case",
        required=True,
        help="Identified root cause or core category for this customer issue.",
    )

    is_escalated = fields.Boolean(
        string="Is Escalated Ticket",
        compute="_compute_is_escalated",
        store=True,
        readonly=False,
    )
    resolution = fields.Text(
        string="Case Resolution",
        help="Mandatory: Document the reason for resolving the issue, actions taken, and final solution.",
    )
    agent_response = fields.Text(
        string="Agent Response",
        help="Initial response / notes provided by the agent.",
    )
    escalated_agent_response = fields.Text(
        string="Case Resolution",
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
    notify_customer = fields.Boolean(
        string="Notify Customer",
        default=False,
        help="Button ON/OFF: If enabled, dispatches an SMS or Email notification to the customer informing them that their issue has been resolved.",
    )
    notification_channel = fields.Selection(
        selection=[
            ("sms", "SMS"),
            ("email", "Email"),
        ],
        string="Notification Channel",
        default="sms",
        help="Drop-down SMS and email: Select whether to dispatch notification via SMS or Email.",
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
                res["root_case"] = ticket.inquiry_summary or ""
                res["agent_response"] = ticket.agent_action_taken or ""
                res["escalated_agent_response"] = ""
                res["resolution"] = ticket.resolution or ticket.escalated_agent_response or ticket.agent_action_taken or ""
                if not res.get("kb_title"):
                    sub_title = ticket.service_sub_category_id.name if ticket.service_sub_category_id else (ticket.service_id.name if ticket.service_id else (ticket.inquiry_summary or ticket.name or ticket.number))
                    res["kb_title"] = sub_title
        return res

    def action_confirm_done(self):
        self.ensure_one()
        ticket = self.ticket_id
        stage_name = (ticket.stage_id.name or "").lower() if ticket and ticket.stage_id else ""
        if ticket and (ticket.closed or (ticket.stage_id and ticket.stage_id.closed) or any(w in stage_name for w in ("close", "reject"))):
            raise ValidationError(_("Ticket '%s' is %s. You must first Reopen the ticket before resolving it.") % (ticket.number or ticket.name, ticket.stage_id.name or "terminal"))
        has_initial = bool(ticket and ticket.agent_action_taken and ticket.agent_action_taken.strip())
        is_esc = bool(
            self.is_escalated
            or (ticket and ticket.is_escalated)
            or (ticket and ticket.is_reopened)
            or has_initial
            or "escalat" in stage_name
            or (ticket and ticket.escalation_level and ticket.escalation_level > 1)
        )

        if not self.root_case or not self.root_case.strip():
            raise ValidationError(_("Please enter the Root Case before completing the ticket."))
        root_case_val = self.root_case.strip()

        response_text = (self.resolution or self.escalated_agent_response or self.agent_response or "").strip()
        if not response_text:
            raise ValidationError(_("Please enter the Case Resolution before completing the ticket."))

        if is_esc:
            vals = {
                "inquiry_summary": root_case_val,
                "escalated_agent_response": response_text,
                "resolution": response_text,
            }
        else:
            vals = {
                "inquiry_summary": root_case_val,
                "agent_action_taken": response_text,
                "resolution": response_text,
            }

        user = self.env.user
        is_frontline = (
            user.has_group("bunna_helpdesk.group_helpdesk_front_line")
            or user.has_group("bunna_helpdesk.group_helpdesk_contact_center_front_line")
            or user.has_group("bunna_helpdesk.group_helpdesk_contact_center")
            or getattr(user, "helpdesk_role", "") in ("contact_center", "contact_center_front_line", "front_line", "support")
        )
        is_backline = (
            user.has_group("bunna_helpdesk.group_helpdesk_back_line")
            or user.has_group("bunna_helpdesk.group_helpdesk_contact_center_back_line")
            or user.has_group("bunna_helpdesk.group_helpdesk_team_leader")
            or user.has_group("bunna_helpdesk.group_helpdesk_contact_center_team_leader")
            or user.has_group("bunna_helpdesk.group_helpdesk_manager")
            or user.has_group("bunna_helpdesk.group_helpdesk_contact_center_director")
            or user.has_group("base.group_erp_manager")
            or getattr(user, "helpdesk_role", "") in ("back_line", "contact_center_back_line", "team_leader", "contact_center_team_leader", "contact_center_director", "manager", "admin")
        )

        if is_frontline and not is_backline:
            # Once Front-line Agent resolves a ticket, it moves to the Review Stage
            # where Back-line Team audits the registered case.
            review_stage = self.env["helpdesk.ticket.stage"].search(
                ["|", ("name", "=ilike", "Review"), ("name", "=ilike", "Under Review")], limit=1
            )
            if not review_stage:
                review_stage = self.env["helpdesk.ticket.stage"].create({
                    "name": "Review",
                    "sequence": 4,
                    "closed": False,
                    "company_id": ticket.company_id.id or self.env.company.id or 1,
                })
            vals["stage_id"] = review_stage.id
            vals["review_submitted_by_id"] = user.id
            vals["review_submitted_at"] = fields.Datetime.now()
            ticket.sudo().with_context(from_done_wizard=True).write(vals)
            ticket.sudo().message_post(
                body=_(
                    "<div><strong>📋 Front-line Resolution ➔ Moved to Review Stage</strong><br/>"
                    "• <strong>Front-line Agent:</strong> %s<br/>"
                    "• <strong>Root Case:</strong> %s<br/>"
                    "• <strong>Resolution / Response:</strong> %s<br/>"
                    "• <strong>Status:</strong> Case moved to <strong>Review Stage</strong> for Back-line Team audit "
                    "to ensure that it has been properly documented and that the resolution reason is accurate and appropriate.</div>"
                ) % (user.name, root_case_val, response_text),
                author_id=user.partner_id.id,
                subtype_xmlid="mail.mt_note",
                body_is_html=True,
            )
            return {"type": "ir.actions.act_window_close"}
        else:
            done_stage = self.target_stage_id
            if not done_stage:
                done_stage = self.env["helpdesk.ticket.stage"].search(
                    ["|", ("name", "ilike", "resolve"), ("name", "ilike", "resolved")], limit=1
                )
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
            vals["reviewed_by_id"] = user.id
            vals["reviewed_at"] = fields.Datetime.now()
            ticket.sudo().with_context(from_done_wizard=True).write(vals)

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
            ticket.sudo().message_post(
                body=f"<div><strong>✅ Ticket Resolved</strong><br/>"
                     f"• <strong>Resolved By (Escalated Specialist):</strong> {self.env.user.name}"
                     f"{escalater_note}<br/>"
                     f"• <strong>Case Resolution:</strong> {response_text}"
                     f"{kb_note}</div>",
                author_id=user.partner_id.id,
                subtype_xmlid="mail.mt_note",
                body_is_html=True,
            )
        else:
            ticket.sudo().message_post(
                body=f"<div><strong>✅ Ticket Resolved</strong><br/>"
                     f"• <strong>Resolved By:</strong> {self.env.user.name}<br/>"
                     f"• <strong>Agent Response:</strong> {response_text}"
                     f"{kb_note}</div>",
                author_id=user.partner_id.id,
                subtype_xmlid="mail.mt_note",
                body_is_html=True,
            )

        if self.notify_customer:
            try:
                ticket.with_context(mail_notrack=True, bunna_skip_notifications=True).sudo().write({
                    "completion_sms_sent": False,
                    "completion_email_sent": False,
                })
                ticket._bunna_manual_notify("completion", channels=(self.notification_channel or "sms",))
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning("Could not dispatch resolved customer notification: %s", exc)

        return {"type": "ir.actions.act_window_close"}
