# -*- coding: utf-8 -*-
from odoo import api, fields, models, tools, _
from odoo.exceptions import UserError


class HelpdeskTicketNotifyWizard(models.TransientModel):
    _name = "helpdesk.ticket.notify.wizard"
    _description = "Customer Notification Wizard (SMS or Email)"

    ticket_id = fields.Many2one(
        comodel_name="helpdesk.ticket",
        string="Ticket",
        required=True,
    )
    notification_type = fields.Selection(
        selection=[
            ("acceptance", "Acceptance Notification (-> In Progress)"),
            ("completion", "Resolution & Completion (-> Done)"),
        ],
        string="Notification Event",
        required=True,
        default="acceptance",
    )
    channel = fields.Selection(
        selection=[
            ("sms", "SMS Notification"),
            ("email", "Email Notification"),
            ("none", "No Notification (Internal Update Only)"),
        ],
        string="Send Via",
        required=True,
        default="sms",
        help="Select whether to send notification exclusively via SMS or Email (only one channel is sent).",
    )
    partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Customer",
        related="ticket_id.partner_id",
        readonly=True,
    )
    customer_phone = fields.Char(
        string="Customer Phone",
        compute="_compute_customer_contacts",
        readonly=True,
    )
    customer_email = fields.Char(
        string="Customer Email",
        compute="_compute_customer_contacts",
        readonly=True,
    )
    resolution_notes = fields.Text(
        string="Resolution Notes / Action Taken",
        help="Summarize the action taken to resolve this ticket.",
    )
    message_preview = fields.Text(
        string="Message Preview",
        compute="_compute_message_preview",
        readonly=True,
    )

    @api.depends("ticket_id")
    def _compute_customer_contacts(self):
        for wiz in self:
            if wiz.ticket_id:
                raw_phone, normalized = wiz.ticket_id._bunna_sms_phone()
                wiz.customer_phone = normalized or raw_phone or _("No mobile phone on record")
                wiz.customer_email = (
                    wiz.ticket_id.partner_email
                    or (wiz.ticket_id.partner_id.email if wiz.ticket_id.partner_id else False)
                    or _("No email address on record")
                )
            else:
                wiz.customer_phone = ""
                wiz.customer_email = ""

    @api.depends("channel", "notification_type", "ticket_id", "resolution_notes")
    def _compute_message_preview(self):
        for wiz in self:
            if not wiz.ticket_id:
                wiz.message_preview = ""
                continue
            if wiz.channel == "none":
                wiz.message_preview = _("No customer notification will be sent. Ticket status will be updated directly.")
            elif wiz.channel == "sms":
                body = wiz.ticket_id._bunna_sms_body(wiz.notification_type)
                wiz.message_preview = body
            elif wiz.channel == "email":
                partner_name = wiz.ticket_id.partner_id.name or wiz.ticket_id.partner_name or _("Valued Customer")
                event_title = _("Accepted and In Progress") if wiz.notification_type == "acceptance" else _("Successfully Resolved")
                wiz.message_preview = _(
                    "Dear %s,\n\nYour service request '%s' (%s) has been %s.\n\nThank you for banking with Bunna Bank!\nHotline: 8501"
                ) % (partner_name, wiz.ticket_id.name or "", wiz.ticket_id.number or "", event_title)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get("active_id")
        if active_id and not res.get("ticket_id"):
            ticket = self.env["helpdesk.ticket"].browse(active_id)
            res["ticket_id"] = ticket.id
            if ticket.agent_action_taken and not res.get("resolution_notes"):
                res["resolution_notes"] = ticket.agent_action_taken

            # Default channel: SMS if phone is present, otherwise Email
            raw_phone, _norm = ticket._bunna_sms_phone()
            if raw_phone:
                res["channel"] = "sms"
            elif ticket.partner_email or (ticket.partner_id and ticket.partner_id.email):
                res["channel"] = "email"
            else:
                res["channel"] = "sms"

        return res

    def action_confirm_notification(self):
        self.ensure_one()
        ticket = self.ticket_id

        if self.notification_type == "completion":
            if self.resolution_notes:
                ticket.agent_action_taken = self.resolution_notes
            elif not ticket.agent_action_taken:
                raise UserError(_("Please provide Resolution Notes / Action Taken before completing this ticket."))

        if self.channel == "none":
            # Direct status transition without sending SMS/Email
            stage = ticket._bunna_get_stage(self.notification_type)
            if stage:
                ticket.with_context(bunna_skip_notifications=True).write({"stage_id": stage.id})
            # Flag both as fulfilled to prevent re-prompting
            if self.notification_type == "acceptance":
                ticket.write({"acceptance_sms_sent": True, "acceptance_email_sent": True})
            else:
                ticket.write({"completion_sms_sent": True, "completion_email_sent": True})
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Ticket Updated"),
                    "message": _("Ticket status updated to %s (No customer message sent).") % (stage.name if stage else "Done"),
                    "type": "info",
                    "sticky": False,
                },
            }

        # Send exclusively via chosen channel (SMS or Email only, never both)
        res_notify = ticket._bunna_manual_notify(self.notification_type, channels=(self.channel,))

        # Flag the other channel as well so that the user cannot send both
        if self.notification_type == "acceptance":
            ticket.write({"acceptance_sms_sent": True, "acceptance_email_sent": True})
        elif self.notification_type == "completion":
            ticket.write({"completion_sms_sent": True, "completion_email_sent": True})

        return res_notify
