# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HelpdeskTicketReopenWizard(models.TransientModel):
    _name = "helpdesk.ticket.reopen.wizard"
    _description = "Helpdesk Ticket Reopen Wizard"

    ticket_id = fields.Many2one(
        "helpdesk.ticket",
        string="Ticket",
        required=True,
        readonly=True,
    )
    ticket_number = fields.Char(related="ticket_id.number", string="Ticket Number", readonly=True)
    ticket_name = fields.Char(related="ticket_id.name", string="Sub Service", readonly=True)
    current_stage_id = fields.Many2one(related="ticket_id.stage_id", string="Current Stage", readonly=True)
    resolution = fields.Text(
        related="ticket_id.resolution",
        string="Previous Resolution",
        readonly=True,
        help="Previous resolution and actions documented when the case was resolved.",
    )

    target_stage_id = fields.Many2one("helpdesk.ticket.stage", string="Target Stage")

    reopen_reason = fields.Text(
        string="Reopen Reason",
        required=True,
        help="Please state the reason why this ticket is being reopened.",
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

    def action_confirm_reopen(self):
        self.ensure_one()
        if not self.reopen_reason or not self.reopen_reason.strip():
            raise ValidationError(_("Please provide a reason for reopening this ticket."))

        self.ticket_id.action_reopen_ticket(reason=self.reopen_reason.strip())
        return {"type": "ir.actions.act_window_close"}
