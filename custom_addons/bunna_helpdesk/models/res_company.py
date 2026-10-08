from odoo import fields, models


class Company(models.Model):
    _inherit = "res.company"

    # ── Portal / team selection settings ─────────────────────────────────────
    helpdesk_mgmt_portal_select_team = fields.Boolean(
        string="Select team in Helpdesk portal"
    )
    helpdesk_mgmt_portal_team_id_required = fields.Boolean(
        string="Required Team field in Helpdesk portal",
        default=True,
    )
    helpdesk_mgmt_portal_select_category = fields.Boolean(
        string="Select category in Helpdesk portal"
    )
    helpdesk_mgmt_portal_category_id_required = fields.Boolean(
        string="Required Category field in Helpdesk portal",
        default=True,
    )

    # ── Duplicate tracking ────────────────────────────────────────────────────
    helpdesk_mgmt_duplicate_tracking = fields.Boolean(
        string="Enable duplicate ticket tracking.", default=False
    )
    helpdesk_mgmt_duplicate_ticket_stage_id = fields.Many2one(
        comodel_name="helpdesk.ticket.stage",
        string="Move duplicate tickets to this stage",
        default=False,
    )

    # ── Auto-assign ───────────────────────────────────────────────────────────
    helpdesk_mgmt_ticket_auto_assign = fields.Boolean(
        string="Auto assign tickets (manual-mode fallback)",
        default=True,
    )

    # ── SLA ───────────────────────────────────────────────────────────────────
    helpdesk_mgmt_sla_active = fields.Boolean(
        string="Enable SLA Policies",
        default=False,
    )

    # ── Auto-close inactive tickets ───────────────────────────────────────────
    helpdesk_mgmt_auto_close_active = fields.Boolean(
        string="Auto-close Inactive Tickets",
        default=False,
    )
    helpdesk_mgmt_auto_close_days = fields.Integer(
        string="Close After (days)",
        default=30,
        help="Tickets with no stage update for this many days will be automatically closed.",
    )
    helpdesk_mgmt_auto_close_stage_id = fields.Many2one(
        comodel_name="helpdesk.ticket.stage",
        string="Move to Stage",
        help="Stage to move stale tickets to when auto-close runs.",
    )
