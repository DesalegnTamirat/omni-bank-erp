# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HelpdeskTicketPendingWizard(models.TransientModel):
    _name = "helpdesk.ticket.pending.wizard"
    _description = "Helpdesk Ticket Pending Wizard"

    ticket_id = fields.Many2one(
        "helpdesk.ticket",
        string="Ticket",
        required=True,
        readonly=True,
    )
    ticket_number = fields.Char(related="ticket_id.number", string="Ticket Number", readonly=True)
    ticket_name = fields.Char(related="ticket_id.name", string="Sub Service", readonly=True)
    current_stage_id = fields.Many2one(related="ticket_id.stage_id", string="Current Stage", readonly=True)
    target_stage_id = fields.Many2one("helpdesk.ticket.stage", string="Target Stage")

    pending_reason_type = fields.Selection(
        [
            ("customer_info", "Waiting for Customer Information / KYC / Documents"),
            ("branch_sol", "Waiting for Branch / SOL Feedback or Statement"),
            ("cbs_finacle", "Waiting for Core Banking / CBS / Finacle Technical Resolution"),
            ("vendor_third_party", "Waiting for External Third-Party (EthSwitch, Telecom, Vendor)"),
            ("investigation", "In-Depth Investigation / Technical Audit Ongoing"),
            ("customer_confirmation", "Pending Customer Dispute / Cardholder Confirmation"),
            ("other", "Other Operational Reason"),
        ],
        string="In-Progress Reason",
        default="customer_info",
        required=True,
    )
    pending_reason = fields.Char(
        string="Pending Reason Summary",
        required=True,
        help="Brief summary of why this ticket is placed on pending status.",
    )
    pending_notes = fields.Text(
        string="Details / Handover Findings",
        required=True,
        help="Provide detailed context on what is pending, what has been checked, and expected next action.",
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ticket_id = self.env.context.get("default_ticket_id") or self.env.context.get("active_id")
        if ticket_id:
            ticket = self.env["helpdesk.ticket"].browse(ticket_id)
            if ticket.exists():
                res["ticket_id"] = ticket.id
                res["pending_reason"] = "Waiting for Customer Information / KYC / Documents"
                if ticket.pending_reason:
                    res["pending_reason"] = ticket.pending_reason
                if ticket.pending_reason_details:
                    res["pending_notes"] = ticket.pending_reason_details
        return res

    @api.onchange("pending_reason_type")
    def _onchange_pending_reason_type(self):
        selection_dict = dict(self._fields["pending_reason_type"].selection)
        if self.pending_reason_type and self.pending_reason_type in selection_dict:
            self.pending_reason = selection_dict[self.pending_reason_type]

    def action_confirm_pending(self):
        self.ensure_one()
        if not self.pending_reason or not self.pending_reason.strip():
            raise ValidationError(_("Please provide a pending reason summary."))
        if not self.pending_notes or not self.pending_notes.strip():
            raise ValidationError(_("Please provide detailed findings or context for why this ticket is pending."))

        self.ticket_id.action_set_pending(
            reason=self.pending_reason.strip(),
            notes=self.pending_notes.strip(),
        )
        return {"type": "ir.actions.act_window_close"}
