# -*- coding: utf-8 -*-
from odoo import fields, models


class HelpdeskTicketEscalationHistory(models.Model):
    """Auditable log of SLA-based hierarchical escalations for Helpdesk Tickets."""
    _name = "helpdesk.ticket.escalation.history"
    _description = "Helpdesk Ticket Escalation Audit History"
    _order = "escalation_datetime desc, id desc"

    ticket_id = fields.Many2one(
        comodel_name="helpdesk.ticket",
        string="Ticket",
        required=True,
        ondelete="cascade",
        index=True,
    )
    escalation_level = fields.Integer(
        string="Escalation Level",
        required=True,
        default=1,
    )
    previous_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Previous Assignee",
    )
    new_user_id = fields.Many2one(
        comodel_name="res.users",
        string="New Assignee (Manager)",
        required=True,
    )
    escalation_datetime = fields.Datetime(
        string="Escalation Timestamp",
        default=fields.Datetime.now,
        required=True,
    )
    sla_deadline = fields.Datetime(
        string="Breached SLA Deadline",
    )
    new_sla_deadline = fields.Datetime(
        string="Next Target Deadline",
    )
    is_ceo_level = fields.Boolean(
        string="CEO Level Escalation",
        default=False,
    )
    reason = fields.Text(
        string="Escalation Reason & SLA Breach Notes",
    )
