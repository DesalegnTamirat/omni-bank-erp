from datetime import timedelta

from odoo import api, fields, models


class HelpdeskSla(models.Model):
    _name = "helpdesk.sla"
    _description = "Helpdesk SLA Policy"
    _order = "name"

    name = fields.Char(string="SLA Policy Name", required=True)
    active = fields.Boolean(default=True)
    team_id = fields.Many2one(
        comodel_name="helpdesk.ticket.team",
        string="Team",
        required=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        related="team_id.company_id",
        store=True,
    )
    stage_id = fields.Many2one(
        comodel_name="helpdesk.ticket.stage",
        string="Reach Stage",
        required=True,
        help="The SLA is satisfied when the ticket reaches this stage.",
    )
    priority = fields.Selection(
        selection=[
            ("0", "Low"),
            ("1", "Medium"),
            ("2", "High"),
            ("3", "Very High"),
        ],
        string="Minimum Priority",
        default="0",
        help="SLA applies only to tickets with this priority or higher.",
    )
    tag_ids = fields.Many2many(
        comodel_name="helpdesk.ticket.tag",
        string="Tags",
        help="SLA applies only to tickets that have ALL of these tags. Leave empty to match any ticket.",
    )
    time_days = fields.Integer(string="Days", default=0)
    time_hours = fields.Integer(string="Hours", default=8)
    time_minutes = fields.Integer(string="Minutes", default=0)

    def _get_deadline(self, start_dt):
        """Compute the SLA deadline from a start datetime."""
        self.ensure_one()
        return start_dt + timedelta(
            days=self.time_days,
            hours=self.time_hours,
            minutes=self.time_minutes,
        )

    def _is_applicable(self, ticket):
        """Return True if this SLA applies to the given ticket."""
        self.ensure_one()
        if self.team_id != ticket.team_id:
            return False
        if int(ticket.priority) < int(self.priority):
            return False
        if self.tag_ids and not (self.tag_ids & ticket.tag_ids):
            return False
        return True


class HelpdeskSlaStatus(models.Model):
    _name = "helpdesk.sla.status"
    _description = "Helpdesk SLA Status"
    _order = "deadline ASC, sla_id"

    ticket_id = fields.Many2one(
        comodel_name="helpdesk.ticket",
        string="Ticket",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sla_id = fields.Many2one(
        comodel_name="helpdesk.sla",
        string="SLA Policy",
        required=True,
        ondelete="cascade",
    )
    deadline = fields.Datetime(string="Deadline", readonly=True)
    reached_datetime = fields.Datetime(string="Reached On", readonly=True)
    status = fields.Selection(
        selection=[
            ("in_progress", "In Progress"),
            ("reached", "Reached"),
            ("failed", "Failed"),
        ],
        string="Status",
        compute="_compute_status",
        store=True,
    )

    @api.depends("deadline", "reached_datetime")
    def _compute_status(self):
        now = fields.Datetime.now()
        for rec in self:
            if rec.reached_datetime:
                rec.status = "reached"
            elif rec.deadline and now > rec.deadline:
                rec.status = "failed"
            else:
                rec.status = "in_progress"
