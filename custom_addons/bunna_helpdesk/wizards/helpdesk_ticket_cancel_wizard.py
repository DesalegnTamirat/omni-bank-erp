# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HelpdeskTicketCancelWizard(models.TransientModel):
    _name = "helpdesk.ticket.cancel.wizard"
    _description = "Helpdesk Ticket Cancellation Wizard"

    ticket_id = fields.Many2one(
        "helpdesk.ticket",
        string="Ticket",
        required=True,
        readonly=True,
    )
    ticket_number = fields.Char(related="ticket_id.number", string="Ticket Number", readonly=True)
    ticket_name = fields.Char(related="ticket_id.name", string="Subject", readonly=True)
    current_stage_id = fields.Many2one(related="ticket_id.stage_id", string="Current Stage", readonly=True)
    target_stage_id = fields.Many2one("helpdesk.ticket.stage", string="Target Stage")

    cancel_reason = fields.Text(
        string="Cancellation Reason",
        required=True,
        help="Please state the reason why this ticket is being cancelled.",
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

    def action_confirm_cancel(self):
        self.ensure_one()
        if not self.cancel_reason or not self.cancel_reason.strip():
            raise ValidationError(_("Please provide a cancellation reason."))

        self.ticket_id.action_cancel_ticket(reason=self.cancel_reason.strip())
        return {"type": "ir.actions.act_window_close"}
