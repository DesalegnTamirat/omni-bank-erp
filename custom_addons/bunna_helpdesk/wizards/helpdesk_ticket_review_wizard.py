# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.translate import _


class HelpdeskTicketReviewWizard(models.TransientModel):
    _name = "helpdesk.ticket.review.wizard"
    _description = "Helpdesk Ticket Back-Line Audit & Review Wizard"

    ticket_id = fields.Many2one(
        "helpdesk.ticket",
        string="Ticket",
        required=True,
        ondelete="cascade",
    )
    ticket_number = fields.Char(related="ticket_id.number", readonly=True, string="Ticket Number")
    ticket_name = fields.Char(related="ticket_id.name", readonly=True, string="Ticket Subject")
    partner_name = fields.Char(related="ticket_id.partner_name", readonly=True, string="Customer Name")
    partner_phone = fields.Char(related="ticket_id.partner_phone", readonly=True, string="Phone Number")
    account_number = fields.Char(related="ticket_id.account_number", readonly=True, string="Account Number")
    operating_unit_id = fields.Many2one(related="ticket_id.operating_unit_id", readonly=True, string="Operating Unit")
    service_name = fields.Char(compute="_compute_case_summary", readonly=True, string="Service Category")
    customer_request_details = fields.Text(related="ticket_id.customer_request_details", readonly=True, string="Customer Inquiry / Request")

    review_submitted_by_id = fields.Many2one(related="ticket_id.review_submitted_by_id", readonly=True, string="Resolved By (Front-Line Agent)")
    review_submitted_at = fields.Datetime(related="ticket_id.review_submitted_at", readonly=True, string="Front-Line Resolution Date")

    frontline_root_cause = fields.Text(compute="_compute_case_summary", readonly=True, string="Front-Line Identified Root Cause")
    frontline_resolution = fields.Text(compute="_compute_case_summary", readonly=True, string="Front-Line Resolution / Action Taken")

    decision = fields.Selection(
        selection=[
            ("approved", "Approve & Mark as Resolved"),
            ("returned", "Return to Front-Line for Correction"),
        ],
        string="Audit Decision",
        required=True,
        default="approved",
    )

    registration_feedback = fields.Text(
        string="Feedback on Case Registration",
        required=True,
        default="Case registration verified: Customer identity, account/card details, service classification, and inquiry details are properly and accurately documented.",
        help="Evaluation and feedback on whether the case was properly registered by the front-line agent.",
    )
    root_cause_feedback = fields.Text(
        string="Feedback on Root Cause",
        required=True,
        default="Root cause analysis confirmed: The root cause identified by the front-line agent is accurate and corresponds to the reported customer issue.",
        help="Evaluation and feedback on the accuracy of the root cause identified by front-line.",
    )
    resolution_feedback = fields.Text(
        string="Feedback on Resolution",
        required=True,
        default="Resolution verified: The action taken and explanation provided to the customer are appropriate, complete, and adhere to operational standards.",
        help="Evaluation and feedback on the resolution steps and advice given to the customer.",
    )
    general_comments = fields.Text(
        string="General Review Comments / Notes",
        help="Additional guidance, audit notes, or recommendations from the Back-line support team.",
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

    @api.depends("ticket_id")
    def _compute_case_summary(self):
        for rec in self:
            ticket = rec.ticket_id
            if not ticket:
                rec.service_name = ""
                rec.frontline_root_cause = ""
                rec.frontline_resolution = ""
                continue

            # Service name
            svc_parts = []
            if ticket.service_family_id:
                svc_parts.append(ticket.service_family_id.name)
            if ticket.service_id:
                svc_parts.append(ticket.service_id.name)
            if ticket.service_sub_category_id:
                svc_parts.append(ticket.service_sub_category_id.name)
            rec.service_name = " > ".join(svc_parts) if svc_parts else (ticket.team_id.name or "N/A")

            # Root cause
            rec.frontline_root_cause = ticket.inquiry_summary or ticket.root_case or "N/A"

            # Resolution
            rec.frontline_resolution = ticket.agent_action_taken or ticket.resolution or ticket.escalated_agent_response or "N/A"

    def action_confirm_review(self):
        self.ensure_one()
        ticket = self.ticket_id
        if not ticket:
            raise UserError(_("No ticket found to review."))

        user = self.env.user
        now = fields.Datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")

        vals = {
            "reviewed_by_id": user.id,
            "reviewed_at": now,
            "review_decision": self.decision,
            "review_registration_feedback": self.registration_feedback,
            "review_root_cause_feedback": self.root_cause_feedback,
            "review_resolution_feedback": self.resolution_feedback,
            "review_comments": self.general_comments or "",
        }

        if self.decision == "approved":
            resolved_stage = self.env["helpdesk.ticket.stage"].search(
                ["|", ("name", "=ilike", "Resolved"), ("name", "=ilike", "Resolve")], limit=1
            )
            if not resolved_stage:
                resolved_stage = self.env["helpdesk.ticket.stage"].search(
                    [("name", "=ilike", "Done")], limit=1
                )
            if resolved_stage:
                vals["stage_id"] = resolved_stage.id

            ticket.sudo().with_context(bypass_stage_guard=True).write(vals)

            comments_block = f"<br/>• <strong>General Review Notes:</strong> {self.general_comments}" if self.general_comments else ""
            body = _(
                "<div><strong>✅ Back-Line Audit Completed &amp; Resolution Approved</strong><br/>"
                "• <strong>Audited By:</strong> %s (Back-Line)<br/>"
                "• <strong>Audit Date &amp; Time:</strong> %s<br/>"
                "• <strong>Case Registration Feedback:</strong> %s<br/>"
                "• <strong>Root Cause Feedback:</strong> %s<br/>"
                "• <strong>Resolution Feedback:</strong> %s"
                "%s<br/>"
                "• <strong>Status:</strong> Case successfully verified and transitioned to <strong>Resolved</strong>.</div>"
            ) % (
                user.name,
                now_str,
                self.registration_feedback,
                self.root_cause_feedback,
                self.resolution_feedback,
                comments_block,
            )
            ticket.sudo().message_post(
                body=body,
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

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Audit Approved"),
                    "message": _("Ticket %s has been reviewed and approved as Resolved.") % (ticket.number or ticket.name),
                    "type": "success",
                    "sticky": False,
                    "next": {"type": "ir.actions.act_window_close"},
                },
            }

        else:
            # Returned to Front-Line for Correction
            in_prog_stage = self.env["helpdesk.ticket.stage"].search(
                ["|", ("name", "=ilike", "In Progress"), ("name", "=ilike", "Progress")], limit=1
            )
            if not in_prog_stage:
                in_prog_stage = self.env["helpdesk.ticket.stage"].search(
                    [("sequence", "<", 4), ("closed", "=", False)], order="sequence desc", limit=1
                )
            if in_prog_stage:
                vals["stage_id"] = in_prog_stage.id

            ticket.sudo().with_context(bypass_stage_guard=True).write(vals)

            comments_block = f"<br/>• <strong>General Review Notes:</strong> {self.general_comments}" if self.general_comments else ""
            body = _(
                "<div style='color: #856404; background-color: #fff3cd; border: 1px solid #ffeeba; padding: 10px; border-radius: 4px;'>"
                "<strong>⚠️ Back-Line Audit: Ticket Returned to Front-Line for Correction</strong><br/>"
                "• <strong>Audited By:</strong> %s (Back-Line)<br/>"
                "• <strong>Audit Date &amp; Time:</strong> %s<br/>"
                "• <strong>Feedback on Case Registration:</strong> %s<br/>"
                "• <strong>Feedback on Root Cause:</strong> %s<br/>"
                "• <strong>Feedback on Resolution:</strong> %s"
                "%s<br/>"
                "• <strong>Required Action:</strong> Front-Line Agent please review the feedback above, make necessary corrections to registration / root cause / resolution, and re-submit.</div>"
            ) % (
                user.name,
                now_str,
                self.registration_feedback,
                self.root_cause_feedback,
                self.resolution_feedback,
                comments_block,
            )
            ticket.sudo().message_post(
                body=body,
                author_id=user.partner_id.id,
                subtype_xmlid="mail.mt_comment",
                body_is_html=True,
            )
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Ticket Returned for Correction"),
                    "message": _("Ticket %s has been returned to Front-Line with your feedback.") % (ticket.number or ticket.name),
                    "type": "warning",
                    "sticky": False,
                    "next": {"type": "ir.actions.act_window_close"},
                },
            }
