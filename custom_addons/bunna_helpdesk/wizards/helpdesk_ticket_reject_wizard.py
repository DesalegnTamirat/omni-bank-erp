# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HelpdeskTicketRejectWizard(models.TransientModel):
    _name = "helpdesk.ticket.reject.wizard"
    _description = "Helpdesk Ticket Rejection Wizard"

    ticket_id = fields.Many2one(
        "helpdesk.ticket",
        string="Ticket",
        required=True,
        readonly=True,
    )
    ticket_number = fields.Char(related="ticket_id.number", string="Ticket Number", readonly=True)
    ticket_name = fields.Char(related="ticket_id.name", string="Sub Service", readonly=True)
    current_stage_id = fields.Many2one(related="ticket_id.stage_id", string="Current Stage", readonly=True)
    rejection_reason = fields.Text(
        string="Rejection Reason",
        required=True,
        help="Please provide a clear reason for rejecting this ticket. This will be shared with the ticket creator and team.",
    )

    def action_confirm_reject(self):
        self.ensure_one()
        if not self.rejection_reason or not self.rejection_reason.strip():
            raise ValidationError(_("Please provide a rejection reason."))
        self.ticket_id.action_reject_ticket(reason=self.rejection_reason.strip())
        return {"type": "ir.actions.act_window_close"}
