# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HelpdeskTicketInProgressWizard(models.TransientModel):
    _name = "helpdesk.ticket.inprogress.wizard"
    _description = "Helpdesk Ticket Accept / In-Progress Wizard"

    ticket_id = fields.Many2one(
        "helpdesk.ticket",
        string="Ticket",
        required=True,
        readonly=True,
    )
    ticket_number = fields.Char(related="ticket_id.number", string="Ticket Number", readonly=True)
    ticket_name = fields.Char(related="ticket_id.name", string="Sub Service", readonly=True)
    current_stage_id = fields.Many2one(related="ticket_id.stage_id", string="Current Stage", readonly=True)
    customer_request_details = fields.Text(
        related="ticket_id.customer_request_details",
        string="Customer Inquiry",
        readonly=True,
    )
    target_stage_id = fields.Many2one("helpdesk.ticket.stage", string="Target Stage")

    action_notes = fields.Text(
        string="Initial Action / Notes",
        required=True,
        help="Describe the initial steps being taken to investigate or resolve this ticket.",
    )

    send_acceptance_notification = fields.Boolean(
        string="Send Acceptance Notification to Customer",
        default=True,
        help="If checked, the customer will be notified via SMS that their ticket has been accepted and is being processed.",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ticket_id = self.env.context.get("default_ticket_id") or self.env.context.get("active_id")
        if ticket_id:
            ticket = self.env["helpdesk.ticket"].browse(ticket_id)
            if ticket.exists():
                res["ticket_id"] = ticket.id
        return res

    def action_confirm_inprogress(self):
        self.ensure_one()
        if not self.action_notes or not self.action_notes.strip():
            raise ValidationError(_("Please provide initial action notes before accepting the ticket."))

        ticket = self.ticket_id
        stage_name = (ticket.stage_id.name or "").lower() if ticket.stage_id else ""
        if ticket.closed or (ticket.stage_id and ticket.stage_id.closed) or any(w in stage_name for w in ("resolve", "resolved", "done", "close", "reject")):
            raise ValidationError(_("Ticket '%s' is %s. You must first Reopen the ticket before moving it to In Progress.") % (ticket.number or ticket.name, ticket.stage_id.name or "terminal"))

        # Find target In Progress stage
        target_stage = self.target_stage_id
        if not target_stage:
            target_stage = self.env.ref(
                "bunna_helpdesk.helpdesk_ticket_stage_in_progress", raise_if_not_found=False
            )
        if not target_stage:
            target_stage = self.env["helpdesk.ticket.stage"].search(
                [("name", "ilike", "in progress"), ("closed", "=", False)], limit=1
            )

        vals = {}
        if target_stage:
            vals["stage_id"] = target_stage.id

        ticket.with_context(from_inprogress_wizard=True).write(vals)

        # Post acceptance note to chatter
        ticket.message_post(
            body=(
                f"<div><strong>✅ Ticket Accepted — In Progress</strong><br/>"
                f"• <strong>Accepted By:</strong> {self.env.user.name}<br/>"
                f"• <strong>Initial Action / Notes:</strong> {self.action_notes.strip()}</div>"
            ),
            subtype_xmlid="mail.mt_note",
            body_is_html=True,
        )

        # Optionally send acceptance notification
        if self.send_acceptance_notification:
            try:
                ticket._bunna_manual_notify("acceptance", channels=("sms",))
            except Exception:
                pass

        return {"type": "ir.actions.act_window_close"}
