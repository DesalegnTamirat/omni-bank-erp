# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class HelpdeskTeamOperation(models.Model):
    """Operation / Case List assigned to a specific Helpdesk Team.
    When a ticket is created under an operation, it is strictly routed to that team.
    """
    _name = "helpdesk.team.operation"
    _description = "Helpdesk Team Operation / Case List"
    _order = "sequence, name, id"

    name = fields.Char(
        string="Operation / Case Name",
        required=True,
        translate=True,
        help="Name of the case or operation (e.g. A2A Transaction/Incoming, A2A Transaction/Outgoing).",
    )
    code = fields.Char(string="Code", help="Short code for internal reference or integration.")
    sequence = fields.Integer(string="Sequence", default=10)
    team_id = fields.Many2one(
        comodel_name="helpdesk.ticket.team",
        string="Assigned Team",
        required=True,
        ondelete="cascade",
        index=True,
        help="All tickets created under this operation will strictly route to this team.",
    )
    case_type_id = fields.Many2one(
        comodel_name="helpdesk.ticket.case.type",
        string="Default Case Type",
        help="Default case classification (e.g. Complaint, Inquiry, Service Request).",
    )
    # ── Service Catalogue (3-tier) ────────────────────────────────────────────
    service_family_id = fields.Many2one(
        comodel_name="helpdesk.service.family",
        string="Service Family",
        help="Top-level service family grouping (Tier 1 of service catalogue).",
        index=True,
    )
    service_id = fields.Many2one(
        comodel_name="helpdesk.service",
        string="Service",
        domain="[('family_id', '=', service_family_id)] if service_family_id else []",
        help="Service in the 3-tier banking service catalogue.",
    )
    service_sub_category_id = fields.Many2one(
        comodel_name="helpdesk.service.sub.category",
        string="Sub-Category / Issue",
        domain="[('service_id', '=', service_id)] if service_id else []",
    )
    default_priority = fields.Selection(
        selection=[
            ("0", "Low"),
            ("1", "Medium"),
            ("2", "High"),
            ("3", "Critical"),
        ],
        string="Default Priority",
        default="1",
        help="Default priority assigned to tickets of this operation.",
    )
    target_hours = fields.Float(
        string="SLA Target (Hours)",
        default=24.0,
        help="Target resolution / service delivery time in hours.",
    )
    ticket_count = fields.Integer(
        string="Tickets Count",
        compute="_compute_ticket_count",
    )
    description = fields.Text(string="Description / Notes")
    active = fields.Boolean(default=True)

    def _compute_ticket_count(self):
        ticket_data = self.env["helpdesk.ticket"]._read_group(
            [("operation_id", "in", self.ids)],
            groupby=["operation_id"],
            aggregates=["__count"],
        )
        mapped_data = {op.id: count for op, count in ticket_data}
        for op in self:
            op.ticket_count = mapped_data.get(op.id, 0)

    # ── Cascading Onchange Handlers ───────────────────────────────────────────

    @api.onchange("team_id")
    def _onchange_team_id(self):
        """When team changes, clear service family/service/sub-category if they
        belong to a different team's responsible chain."""
        if self.team_id and self.service_id:
            # If the service has a responsible_team_id that differs from the selected team,
            # clear the service selection to prompt re-selection.
            if (
                self.service_id.responsible_team_id
                and self.service_id.responsible_team_id != self.team_id
            ):
                self.service_family_id = False
                self.service_id = False
                self.service_sub_category_id = False

    @api.onchange("service_family_id")
    def _onchange_service_family_id(self):
        """When Service Family changes, clear Service and Sub-Category if they
        no longer belong to the selected family."""
        if self.service_id and self.service_id.family_id != self.service_family_id:
            self.service_id = False
            self.service_sub_category_id = False
        elif not self.service_family_id:
            self.service_id = False
            self.service_sub_category_id = False

    @api.onchange("service_id")
    def _onchange_service_id(self):
        """When Service changes, auto-populate Service Family and clear orphaned Sub-Category."""
        if self.service_id:
            # Auto-fill family from the chosen service
            if self.service_id.family_id:
                self.service_family_id = self.service_id.family_id
        else:
            self.service_sub_category_id = False
        # Clear sub-category when service changes
        if self.service_sub_category_id and self.service_sub_category_id.service_id != self.service_id:
            self.service_sub_category_id = False

    @api.depends("name", "team_id.name")
    def _compute_display_name(self):
        show_prefix = self.env.context.get("show_team_prefix")
        for op in self:
            if show_prefix and op.team_id:
                op.display_name = f"[{op.team_id.name}] {op.name}"
            else:
                op.display_name = op.name or ""

    @api.model
    def _init_default_operations(self):
        """Seed initial operations for Digital Banking Directorate and other teams."""
        digital_team = self.env["helpdesk.ticket.team"].search([
            "|",
            ("name", "ilike", "Digital Banking Directorate"),
            ("name", "ilike", "Digital Banking")
        ], limit=1)
        if digital_team:
            complaint_type = self.env["helpdesk.ticket.case.type"].search([("code", "=", "complaint")], limit=1) or \
                             self.env["helpdesk.ticket.case.type"].search([("name", "ilike", "complaint")], limit=1)
            request_type = self.env["helpdesk.ticket.case.type"].search([("code", "=", "request")], limit=1) or \
                           self.env["helpdesk.ticket.case.type"].search([("name", "ilike", "request")], limit=1)
            
            default_ops = [
                {
                    "name": "A2A Transaction/Incoming",
                    "code": "A2A_IN",
                    "sequence": 10,
                    "team_id": digital_team.id,
                    "case_type_id": complaint_type.id if complaint_type else False,
                    "default_priority": "2",
                    "target_hours": 24.0,
                    "description": "Account-to-Account Incoming transfer issues, failures, delays.",
                },
                {
                    "name": "A2A Transaction/Outgoing",
                    "code": "A2A_OUT",
                    "sequence": 20,
                    "team_id": digital_team.id,
                    "case_type_id": complaint_type.id if complaint_type else False,
                    "default_priority": "2",
                    "target_hours": 24.0,
                    "description": "Account-to-Account Outgoing transfer issues, debit without credit.",
                },
                {
                    "name": "A2A Dispute (Debited Not Credited)",
                    "code": "A2A_DISP",
                    "sequence": 30,
                    "team_id": digital_team.id,
                    "case_type_id": complaint_type.id if complaint_type else False,
                    "default_priority": "3",
                    "target_hours": 12.0,
                    "description": "Customer account debited but beneficiary not credited on A2A transaction.",
                },
                {
                    "name": "Mobile Banking Login / Activation",
                    "code": "MB_LOGIN",
                    "sequence": 40,
                    "team_id": digital_team.id,
                    "case_type_id": request_type.id if request_type else False,
                    "default_priority": "1",
                    "target_hours": 8.0,
                    "description": "Mobile banking credential reset, device activation, PIN issues.",
                },
                {
                    "name": "ATM Cash Retraction / Failure",
                    "code": "ATM_FAIL",
                    "sequence": 50,
                    "team_id": digital_team.id,
                    "case_type_id": complaint_type.id if complaint_type else False,
                    "default_priority": "2",
                    "target_hours": 24.0,
                    "description": "ATM cash failed to dispense or cash retracted with debit.",
                },
            ]
            for val in default_ops:
                existing = self.search([("team_id", "=", digital_team.id), ("name", "=", val["name"])], limit=1)
                if not existing:
                    self.create(val)


