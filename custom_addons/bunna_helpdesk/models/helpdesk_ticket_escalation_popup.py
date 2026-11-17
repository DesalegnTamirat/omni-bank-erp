# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class HelpdeskTicketEscalationPopup(models.Model):
    _name = "helpdesk.ticket.escalation.popup"
    _description = "Escalated Ticket Pop-Up Notification"
    _order = "escalation_date desc, id desc"

    ticket_id = fields.Many2one(
        "helpdesk.ticket",
        string="Ticket",
        required=True,
        ondelete="cascade",
        index=True,
    )
    user_id = fields.Many2one(
        "res.users",
        string="Concerned Person / Assignee",
        required=True,
        ondelete="cascade",
        index=True,
    )
    ticket_number = fields.Char(related="ticket_id.number", readonly=True, store=True, string="Ticket Number")
    ticket_name = fields.Char(related="ticket_id.name", readonly=True, string="Sub Service")
    customer_name = fields.Char(related="ticket_id.customer_name", readonly=True, store=True, string="Customer Name")
    customer_phone = fields.Char(related="ticket_id.partner_phone", readonly=True, store=True, string="Customer Phone")
    customer_account = fields.Char(related="ticket_id.account_number", readonly=True, store=True, string="Account Number")
    issue_description = fields.Text(related="ticket_id.customer_request_details", readonly=True, store=True, string="Issue Description")
    escalation_level_name = fields.Char(string="Escalation Stage")
    escalated_by_id = fields.Many2one("res.users", string="Escalated By")
    escalation_date = fields.Datetime(string="Escalation Date & Time", default=fields.Datetime.now)
    operating_unit_id = fields.Many2one(related="ticket_id.operating_unit_id", readonly=True, store=True, string="Responsible Operating Unit")
    is_acknowledged = fields.Boolean(string="Acknowledged", default=False, index=True)
    acknowledged_at = fields.Datetime(string="Acknowledged At")

    def action_view_ticket(self):
        """Acknowledge notification and open the escalated ticket in form view."""
        self.ensure_one()
        self.write({
            "is_acknowledged": True,
            "acknowledged_at": fields.Datetime.now(),
        })
        return {
            "name": _("Escalated Ticket %s") % (self.ticket_number or self.ticket_name),
            "type": "ir.actions.act_window",
            "res_model": "helpdesk.ticket",
            "res_id": self.ticket_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_acknowledge(self):
        """Mark notification as acknowledged."""
        for rec in self:
            rec.write({
                "is_acknowledged": True,
                "acknowledged_at": fields.Datetime.now(),
            })
        return True
