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
    escalation_journey = fields.Selection(
        selection=[
            ("primary_journey", "1. Primary Operating Unit Journey Track"),
            ("other_work_journey", "2. Other Operating Unit Journey Track (Cross-Unit Transfer)"),
        ],
        string="Escalation Journey Track",
        default="primary_journey",
        index=True,
    )
    original_operating_unit_id = fields.Many2one(
        comodel_name="operating.unit",
        string="Original Operating Unit",
    )
    current_operating_unit_id = fields.Many2one(
        comodel_name="operating.unit",
        string="Current Operating Unit",
    )
    previous_escalation_level = fields.Integer(
        string="Previous Escalation Level",
        default=0,
    )
    escalation_level = fields.Integer(
        string="Escalation Level",
        required=True,
        default=1,
    )
    escalation_type = fields.Selection(
        selection=[
            # Left Journey: Primary Helpdesk Escalation Journey
            ("contact_center_front_line", "Contact Center Front Line"),
            ("contact_center_back_line", "Contact Center Backline"),
            ("contact_center_team_leader", "Contact Center Team Leader"),
            ("contact_center_director", "Contact Center Director"),
            ("contact_center", "Contact Center"),
            ("front_line", "Front line (Team)"),
            ("back_line", "Back line (Team)"),
            ("team_leader", "Team Leader"),
            ("directorate", "Directorate"),
            ("deputy_chief", "Deputy Chief"),
            ("chief", "Chief"),
            ("ceo", "Chief Executive Officer (CEO)"),
            ("team_leader_to_deputy_chief", "Team Leader ➔ Deputy Chief (Direct Bypass)"),

            # Bridge: Cross-Unit Transfer
            ("other_work", "Other Workunit / Transfer"),

            # Right Journey: Other Workunit Escalation Path
            ("other_officer", "Other Workunit ➔ Officer"),
            ("other_senior_principal", "Other Workunit ➔ Senior / Principal Officer"),
            ("other_manager_team_leader", "Other Workunit ➔ Manager / Team Leader"),
            ("other_directorate", "Other Workunit ➔ Directorate"),
            ("other_deputy_chief_chief", "Other Workunit ➔ Deputy Chief / Chief"),
            ("other_ceo", "Other Workunit ➔ CEO"),

            # Aliases & Legacy compatibility
            ("peer_backend", "Back line (Team) / Specialist"),
            ("line_manager", "Team Leader / Division Manager"),
            ("manager", "Manager / Team Leader"),
            ("director", "Directorate Director"),
            ("deputy_cto", "Deputy Chief"),
            ("cido", "Chief Information & Digital Officer (CIDO)"),
            ("team_transfer", "Other Workunit Transfer"),
            ("sla_breach", "Automatic SLA Breach Escalation"),
        ],
        string="Escalation Type",
        default="back_line",
    )
    level_name = fields.Char(
        string="Escalation Stage",
    )
    escalated_by_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Escalated By",
        default=lambda self: self.env.user,
        index=True,
    )
    previous_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Previous Assignee",
    )
    new_user_id = fields.Many2one(
        comodel_name="res.users",
        string="New Assignee",
        required=True,
        index=True,
    )
    manager_relationship = fields.Char(
        string="Manager Relationship",
        help="Reporting hierarchy relationship used to determine the escalation recipient.",
    )
    escalation_status = fields.Selection(
        selection=[
            ("escalated", "Escalated"),
            ("in_progress", "In Progress"),
            ("resolved", "Resolved"),
            ("closed", "Closed"),
        ],
        string="Escalation Status",
        default="escalated",
    )
    escalation_datetime = fields.Datetime(
        string="Escalation Timestamp",
        default=fields.Datetime.now,
        required=True,
        index=True,
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
