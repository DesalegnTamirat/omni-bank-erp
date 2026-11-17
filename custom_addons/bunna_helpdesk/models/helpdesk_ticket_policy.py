# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class HelpdeskTicketPolicy(models.Model):
    _name = "helpdesk.ticket.policy"
    _description = "Helpdesk Ticket Policy"

    name = fields.Char(string="Policy Name", default="Bunna Helpdesk Policy", required=True)
    company_id = fields.Many2one("res.company", string="Company", default=lambda self: self.env.company)

    # ── Auto-Close Policy ─────────────────────────────────────────────────────
    auto_close_tickets = fields.Boolean(
        string="Automatic Ticket Closure",
        default=True,
        help="Automatically move tickets from Done to Closed stage after customer notification and elapsed time.",
    )
    auto_close_delay = fields.Integer(
        string="Closure Grace Period",
        default=3,
        help="Wait duration after completion message is dispatched before closing.",
    )
    auto_close_unit = fields.Selection(
        selection=[
            ("hours", "Hours"),
            ("days", "Days"),
        ],
        string="Grace Period Unit",
        default="days",
        help="Unit of time for the auto-close delay.",
    )
    closed_stage_id = fields.Many2one(
        comodel_name="helpdesk.ticket.stage",
        string="Target Closed Stage",
        ondelete="set null",
        help="Stage to which tickets will be moved upon auto-close.",
    )
    auto_close_inactive_active = fields.Boolean(
        string="Auto-close Inactive Tickets",
        default=False,
        help="A scheduled job will automatically close tickets that have had no stage update for the configured number of days.",
    )
    auto_close_inactive_days = fields.Integer(
        string="Days of Inactivity",
        default=14,
        help="Number of days of inactivity before closing.",
    )
    auto_close_inactive_stage_id = fields.Many2one(
        comodel_name="helpdesk.ticket.stage",
        string="Move Inactive Tickets to Stage",
        ondelete="set null",
        help="Target stage for inactive tickets.",
    )

    # ── Ticket Assignment Policy ──────────────────────────────────────────────
    default_team_id = fields.Many2one(
        comodel_name="helpdesk.ticket.team",
        string="Default Responsible Operating Unit",
        ondelete="set null",
        help="Fallback Responsible Operating Unit automatically assigned to incoming tickets.",
    )
    default_operating_unit_id = fields.Many2one(
        comodel_name="operating.unit",
        string="Default Operating Unit",
        ondelete="set null",
        help="Fallback Responsible Operating Unit from employee work units with its parent.",
    )
    default_operating_unit_parent_id = fields.Many2one(
        comodel_name="operating.unit",
        related="default_operating_unit_id.parent_unit",
        readonly=True,
        string="Parent Operating Unit",
    )
    notify_team_members = fields.Boolean(
        string="Notify Team & Members on Ticket Arrival",
        default=True,
        help="Automatically dispatch Discuss inbox notifications, real-time alerts, and activities to the team leader and members when a new ticket is received.",
    )
    auto_assign_creator = fields.Boolean(
        string="Auto assign to creator (Manual mode fallback)",
        default=False,
        help="Automatically assign newly created tickets to the creator when they belong to the team (used only when the team's assignment method is Manual).",
    )
    ceo_user_id = fields.Many2one(
        comodel_name="res.users",
        string="CEO / Executive Authority",
        ondelete="set null",
        help="Top executive authority for final SLA escalation. If not set, automatically determined from the top of the employee reporting hierarchy.",
    )

    # ── Duplicate Tracking Policy ─────────────────────────────────────────────
    duplicate_tracking = fields.Boolean(
        string="Enable Duplicate Tracking",
        default=False,
        help="Enable duplicate ticket detection and linking.",
    )
    duplicate_ticket_stage_id = fields.Many2one(
        comodel_name="helpdesk.ticket.stage",
        string="Duplicate Ticket Stage",
        ondelete="set null",
        help="When marked as duplicate, tickets will be moved to this stage.",
    )

    # ── Portal Form Policy ────────────────────────────────────────────────────
    portal_select_category = fields.Boolean(string="Display Category on Portal Form")
    portal_select_team = fields.Boolean(string="Display Team on Portal Form")
    portal_category_required = fields.Boolean(string="Category Required on Portal")
    portal_team_required = fields.Boolean(string="Team Required on Portal")

    @api.onchange("default_operating_unit_id")
    def _onchange_default_operating_unit_id(self):
        if self.default_operating_unit_id:
            team = self.env["helpdesk.ticket.team"].search(
                [("operating_unit_id", "=", self.default_operating_unit_id.id)],
                limit=1,
            )
            if team:
                self.default_team_id = team

    @api.onchange("default_team_id")
    def _onchange_default_team_id(self):
        if self.default_team_id and self.default_team_id.operating_unit_id:
            self.default_operating_unit_id = self.default_team_id.operating_unit_id

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        icp = self.env["ir.config_parameter"].sudo()
        company = self.env.company

        # Load from ICP
        res["auto_close_tickets"] = icp.get_param("bunna_helpdesk.auto_close_tickets", "True").lower() in ("true", "1")
        try:
            res["auto_close_delay"] = int(icp.get_param("bunna_helpdesk.auto_close_delay", "3"))
        except (ValueError, TypeError):
            res["auto_close_delay"] = 3
        res["auto_close_unit"] = icp.get_param("bunna_helpdesk.auto_close_unit", "days")

        closed_stage_param = icp.get_param("bunna_helpdesk.closed_stage_id")
        if closed_stage_param and str(closed_stage_param).isdigit():
            res["closed_stage_id"] = int(closed_stage_param)

        team_param = icp.get_param("bunna_helpdesk.default_team_id")
        if team_param and str(team_param).isdigit():
            res["default_team_id"] = int(team_param)

        ou_param = icp.get_param("bunna_helpdesk.default_operating_unit_id")
        if ou_param and str(ou_param).isdigit():
            res["default_operating_unit_id"] = int(ou_param)

        res["notify_team_members"] = icp.get_param("bunna_helpdesk.notify_team_members", "True").lower() in ("true", "1")

        ceo_param = icp.get_param("bunna_helpdesk.ceo_user_id")
        if ceo_param and str(ceo_param).isdigit():
            res["ceo_user_id"] = int(ceo_param)

        # Load from Company
        res["duplicate_tracking"] = company.helpdesk_mgmt_duplicate_tracking
        if company.helpdesk_mgmt_duplicate_ticket_stage_id:
            res["duplicate_ticket_stage_id"] = company.helpdesk_mgmt_duplicate_ticket_stage_id.id
        res["auto_assign_creator"] = company.helpdesk_mgmt_ticket_auto_assign
        res["portal_select_category"] = company.helpdesk_mgmt_portal_select_category
        res["portal_select_team"] = company.helpdesk_mgmt_portal_select_team
        res["portal_category_required"] = company.helpdesk_mgmt_portal_category_id_required
        res["portal_team_required"] = company.helpdesk_mgmt_portal_team_id_required
        res["auto_close_inactive_active"] = company.helpdesk_mgmt_auto_close_active
        res["auto_close_inactive_days"] = company.helpdesk_mgmt_auto_close_days
        if company.helpdesk_mgmt_auto_close_stage_id:
            res["auto_close_inactive_stage_id"] = company.helpdesk_mgmt_auto_close_stage_id.id

        return res

    def _sync_to_system_config(self):
        icp = self.env["ir.config_parameter"].sudo()
        company = self.company_id or self.env.company
        for rec in self:
            icp.set_param("bunna_helpdesk.auto_close_tickets", str(rec.auto_close_tickets))
            icp.set_param("bunna_helpdesk.auto_close_delay", str(rec.auto_close_delay))
            icp.set_param("bunna_helpdesk.auto_close_unit", rec.auto_close_unit or "days")
            if rec.closed_stage_id:
                icp.set_param("bunna_helpdesk.closed_stage_id", str(rec.closed_stage_id.id))
            if rec.default_team_id:
                icp.set_param("bunna_helpdesk.default_team_id", str(rec.default_team_id.id))
            if rec.default_operating_unit_id:
                icp.set_param("bunna_helpdesk.default_operating_unit_id", str(rec.default_operating_unit_id.id))
            icp.set_param("bunna_helpdesk.notify_team_members", str(rec.notify_team_members))
            if rec.ceo_user_id:
                icp.set_param("bunna_helpdesk.ceo_user_id", str(rec.ceo_user_id.id))

            company.sudo().write({
                "helpdesk_mgmt_duplicate_tracking": rec.duplicate_tracking,
                "helpdesk_mgmt_duplicate_ticket_stage_id": rec.duplicate_ticket_stage_id.id if rec.duplicate_ticket_stage_id else False,
                "helpdesk_mgmt_ticket_auto_assign": rec.auto_assign_creator,
                "helpdesk_mgmt_portal_select_category": rec.portal_select_category,
                "helpdesk_mgmt_portal_select_team": rec.portal_select_team,
                "helpdesk_mgmt_portal_category_id_required": rec.portal_category_required,
                "helpdesk_mgmt_portal_team_id_required": rec.portal_team_required,
                "helpdesk_mgmt_auto_close_active": rec.auto_close_inactive_active,
                "helpdesk_mgmt_auto_close_days": rec.auto_close_inactive_days,
                "helpdesk_mgmt_auto_close_stage_id": rec.auto_close_inactive_stage_id.id if rec.auto_close_inactive_stage_id else False,
            })

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_to_system_config()
        return records

    def write(self, vals):
        res = super().write(vals)
        self._sync_to_system_config()
        return res

    @api.model
    def _get_singleton_policy(self):
        policy = self.search([], limit=1)
        if not policy:
            policy = self.create({"name": "Bunna Helpdesk Policy"})
        return policy

    @api.model
    def action_open_auto_close_policy(self):
        policy = self._get_singleton_policy()
        return {
            "type": "ir.actions.act_window",
            "name": _("Auto-Close Policy"),
            "res_model": "helpdesk.ticket.policy",
            "res_id": policy.id,
            "view_mode": "form",
            "view_id": self.env.ref("bunna_helpdesk.view_helpdesk_policy_auto_close_form").id,
            "target": "current",
        }

    @api.model
    def action_open_assignment_policy(self):
        policy = self._get_singleton_policy()
        return {
            "type": "ir.actions.act_window",
            "name": _("Ticket Assignment Policy"),
            "res_model": "helpdesk.ticket.policy",
            "res_id": policy.id,
            "view_mode": "form",
            "view_id": self.env.ref("bunna_helpdesk.view_helpdesk_policy_assignment_form").id,
            "target": "current",
        }

    @api.model
    def action_open_duplicate_policy(self):
        policy = self._get_singleton_policy()
        return {
            "type": "ir.actions.act_window",
            "name": _("Duplicate Tracking"),
            "res_model": "helpdesk.ticket.policy",
            "res_id": policy.id,
            "view_mode": "form",
            "view_id": self.env.ref("bunna_helpdesk.view_helpdesk_policy_duplicate_form").id,
            "target": "current",
        }
