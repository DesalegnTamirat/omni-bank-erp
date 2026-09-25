# -*- coding: utf-8 -*-
from datetime import datetime, time, timedelta
from odoo import api, fields, models
from odoo import fields, models
from odoo.tools.safe_eval import safe_eval
import logging

# --- From helpdesk_mgmt ---


class HelpdeskTeam(models.Model):
    _name = "helpdesk.ticket.team"
    _description = "Helpdesk Ticket Team"
    _inherit = ["mail.thread", "mail.alias.mixin"]
    _order = "sequence, id"
    _parent_name = "parent_id"
    _parent_store = True
    _parent_order = "name"
    _rec_name = "complete_name"

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True, translate=True)
    user_ids = fields.Many2many(
        comodel_name="res.users",
        string="Members",
        relation="helpdesk_ticket_team_res_users_rel",
        column1="helpdesk_ticket_team_id",
        column2="res_users_id",
    )
    active = fields.Boolean(default=True)
    category_ids = fields.Many2many(
        comodel_name="helpdesk.ticket.category", string="Category"
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        default=lambda self: self.env.company,
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Team Leader",
        check_company=True,
    )
    support_level = fields.Selection(
        [
            ("1st_level", "1st Level Support (Frontline Contact Center)"),
            ("2nd_level", "2nd Level Support (Back-Office Work Unit)"),
        ],
        string="Support Level / Tier",
        default="1st_level",
        help="Segregation of Duties: 1st Level handles intake/triage; 2nd Level handles back-office work unit resolution.",
    )
    work_unit_id = fields.Many2one(
        comodel_name="hr.department",
        string="Bank Work Unit / Directorate",
        help="Associated Bank Work Unit (e.g. CBS, ATM/E-Banking, Trade Services, Card Operations).",
    )
    assign_method = fields.Selection(
        [
            ("manual", "Manual Assignment Only"),
            ("balanced", "Least-Loaded (Balanced Workload)"),
            ("random", "Round-Robin / Random"),
        ],
        string="Auto-Assignment Method",
        default="manual",
        help="Automatically assign unassigned tickets to active on-duty team members based on selected logic.",
    )

    def _get_auto_assign_user(self):
        self.ensure_one()
        if self.assign_method == "manual" or not self.user_ids:
            return False
        on_duty_members = self.user_ids.filtered(lambda u: getattr(u, "is_on_duty", True))
        if not on_duty_members:
            on_duty_members = self.user_ids
        if not on_duty_members:
            return False

        if self.assign_method == "balanced":
            user_counts = {}
            for member in on_duty_members:
                count = self.env["helpdesk.ticket"].search_count(
                    [("user_id", "=", member.id), ("closed", "=", False)]
                )
                user_counts[member] = count
            return min(user_counts, key=user_counts.get)
        elif self.assign_method == "random":
            import random
            return random.choice(on_duty_members)
        return False
    alias_id = fields.Many2one(
        comodel_name="mail.alias",
        string="Email",
        ondelete="restrict",
        required=True,
        help="The email address associated with \
                               this channel. New emails received will \
                               automatically create new tickets assigned \
                               to the channel.",
    )
    color = fields.Integer(string="Color Index", default=0)
    ticket_ids = fields.One2many(
        comodel_name="helpdesk.ticket",
        inverse_name="team_id",
        string="Tickets",
    )
    todo_ticket_count = fields.Integer(
        string="Number of tickets", compute="_compute_todo_tickets"
    )
    todo_ticket_count_unassigned = fields.Integer(
        string="Number of tickets unassigned", compute="_compute_todo_tickets"
    )
    todo_ticket_count_unattended = fields.Integer(
        string="Number of tickets unattended", compute="_compute_todo_tickets"
    )
    todo_ticket_count_high_priority = fields.Integer(
        string="Number of tickets in high priority", compute="_compute_todo_tickets"
    )
    show_in_portal = fields.Boolean(
        string="Show in portal form",
        default=True,
        help="Allow to select this team when creating a new ticket in the portal.",
    )
    ticket_properties = fields.PropertiesDefinition()
    parent_id = fields.Many2one(
        "helpdesk.ticket.team", string="Parent Team", index=True
    )
    complete_name = fields.Char(
        compute="_compute_complete_name",
        recursive=True,
        search="_search_complete_name",
    )
    parent_path = fields.Char(index=True)

    def _search_complete_name(self, operator, value):
        records = self.search_fetch([], ["complete_name"]).filtered_domain(
            [("complete_name", operator, value)]
        )
        return [("id", "in", records.ids)]

    @api.depends("name", "parent_id.complete_name")
    @api.depends_context("lang")
    def _compute_complete_name(self):
        for record in self:
            if record.parent_id:
                record.complete_name = (
                    f"{record.parent_id.complete_name} / {record.name}"
                )
            else:
                record.complete_name = record.name

    def _get_applicable_stages(self):
        if self:
            domain = [
                ("company_id", "in", [False, self.company_id.id]),
                "|",
                ("team_ids", "=", False),
                ("team_ids", "=", self.id),
            ]
        else:
            domain = [
                ("company_id", "in", [False, self.env.company.id]),
                ("team_ids", "=", False),
            ]
        return self.env["helpdesk.ticket.stage"].search(domain)

    @api.depends("ticket_ids", "ticket_ids.stage_id")
    def _compute_todo_tickets(self):
        ticket_model = self.env["helpdesk.ticket"]
        result = []
        grouped_rows = ticket_model._read_group(
            domain=[("team_id", "in", self.ids), ("closed", "=", False)],
            groupby=["team_id", "user_id", "unattended", "priority"],
            aggregates=["__count"],
        )
        for team, user, unattended, priority, count in grouped_rows:
            result.append(
                [
                    team.id if team else False,
                    user.id if user else False,
                    unattended,
                    priority,
                    count,
                ]
            )
        for team in self:
            team.todo_ticket_count = sum(r[4] for r in result if r[0] == team.id)
            team.todo_ticket_count_unassigned = sum(
                r[4] for r in result if r[0] == team.id and not r[1]
            )
            team.todo_ticket_count_unattended = sum(
                r[4] for r in result if r[0] == team.id and r[2]
            )
            team.todo_ticket_count_high_priority = sum(
                r[4] for r in result if r[0] == team.id and r[3] == "3"
            )

    def _alias_get_creation_values(self):
        values = super()._alias_get_creation_values()
        values["alias_model_id"] = self.env["ir.model"]._get("helpdesk.ticket").id
        values["alias_defaults"] = defaults = safe_eval(self.alias_defaults or "{}")
        defaults["team_id"] = self.id
        return values

    @api.model
    def retrieve_dashboard(self):
        return sorted(self._retrieve_dashboard(), key=lambda d: d.get("sequence", 99))

    def _retrieve_dashboard(self):
        no_team_tickets = self.env["helpdesk.ticket"].search_count(
            [("team_id", "=", False), ("stage_id.closed", "=", False)]
        )
        return [
            {
                "name": self.env._("Open Tickets without team"),
                "value": no_team_tickets,
                "sequence": 1,
                "icon": "fa-exclamation-circle",
                "show": no_team_tickets > 0,
                "action": "custom_helpdesk.action_helpdesk_ticket_unassigned",
            },
            {
                "name": self.env._("Open Tickets"),
                "value": self.env["helpdesk.ticket"].search_count(
                    [("stage_id.closed", "=", False)]
                ),
                "sequence": 2,
                "icon": "fa-life-ring",
                "show": True,
                "action": "custom_helpdesk.action_helpdesk_ticket_all",
            },
        ]


# --- From helpdesk_mgmt_activity ---
# Copyright (C) 2024 Cetmix OÜ
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).



class HelpdeskTicketTeam(models.Model):
    _inherit = "helpdesk.ticket.team"

    allow_set_activity = fields.Boolean(
        string="Set Activities",
        help="Available to set activity on source record from ticket",
    )
    activity_stage_id = fields.Many2one(
        comodel_name="helpdesk.ticket.stage",
        string="Done Activity Stage",
        domain="['|', ('team_ids', 'in, []'), ('team_ids', 'in', [id])]",
        help="Move the ticket when the activity in source record is done",
    )


# --- From helpdesk_mgmt_sla ---
#    Copyright (C) 2020 GARCO Consulting <www.garcoconsulting.es>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).



class HelpdeskTicketTeam(models.Model):
    _inherit = "helpdesk.ticket.team"

    use_sla = fields.Boolean(string="Use SLA")
    resource_calendar_id = fields.Many2one(
        "resource.calendar",
        "Working Hours",
        default=lambda self: self.env.company.resource_calendar_id,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )

# --- From helpdesk_ticket_close_inactive ---
# Copyright 2024 APSL-Nagarro - Miquel Alzanillas


_logger = logging.getLogger(__name__)


class HelpdeskTicketTeam(models.Model):
    _inherit = "helpdesk.ticket.team"

    def _default_warning_email_template(self):
        try:
            return self.env.ref(
                "helpdesk_ticket_close_inactive.warning_inactive_ticket_template"
            ).id
        except Exception:
            _logger.info("Default warning email template not exists.")

    def _default_closing_email_template(self):
        try:
            return self.env.ref("custom_helpdesk.closed_ticket_template", raise_if_not_found=False) and self.env.ref("custom_helpdesk.closed_ticket_template").id or False
        except Exception:
            _logger.info("Default closing email template not exists.")

    close_inactive_tickets = fields.Boolean(
        string="Automatic closure of inactive tickets",
        help="This option enables a cronjob to automatically close inactive tickets.",
        default=False,
    )
    ticket_stage_ids = fields.Many2many(
        comodel_name="helpdesk.ticket.stage",
        string="Ticket Stage",
        help="The cronjob will check for inactivity in \
        tickets that are in these stages.",
    )
    ticket_category_ids = fields.Many2many(
        comodel_name="helpdesk.ticket.category",
        relation="closing_ticket_type_filter",
        string="Ticket Category",
        help="The cronjob will check for inactivity in tickets that belong to "
        "these categories. Leave empty to apply to all categories.",
    )
    inactive_tickets_day_limit_warning = fields.Integer(
        default=7,
        string="Inactive days limit before send a warning",
        required=True,
        help="Number of days of inactivity before a warning email is sent. "
        "Set to 0 to disable the warning phase entirely.",
    )
    warning_inactive_mail_template_id = fields.Many2one(
        "mail.template",
        default=lambda self: self._default_warning_email_template(),
        string="Inactivity warning email template",
        help="Template to be sent as an inactivity warning. "
        "Required when the warning day limit is greater than 0.",
    )
    inactive_tickets_day_limit_closing = fields.Integer(
        default=14,
        required=True,
        help="Number of days of inactivity after which the ticket is "
        "automatically closed. Must be greater than 0.",
    )
    close_inactive_mail_template_id = fields.Many2one(
        "mail.template",
        default=lambda self: self._default_closing_email_template(),
        string="Closing email template",
        help="Template to be sent when a ticket is automatically closed. "
        "Leave empty to close the ticket silently without sending "
        "a notification email.",
    )
    closing_ticket_stage = fields.Many2one(
        "helpdesk.ticket.stage",
        string="Closing Stage",
        help="Set this stage for autoclosing tickets",
    )

    def close_team_inactive_tickets(self):
        if len(self) > 0:
            teams = self
        else:
            teams = self.search([("close_inactive_tickets", "=", True)])

        for team_id in teams:
            ticket_stage_ids = team_id.ticket_stage_ids.ids
            ticket_category_ids = team_id.ticket_category_ids.ids
            closing_limit = datetime.today() - timedelta(
                days=team_id.inactive_tickets_day_limit_closing
            )
            closing_stage = team_id.closing_ticket_stage
            warning_email_ids = []
            closing_email_ids = []

            # Warning phase — only active when warning day limit is greater than 0
            if team_id.inactive_tickets_day_limit_warning > 0:
                warning_limit = datetime.today() - timedelta(
                    days=team_id.inactive_tickets_day_limit_warning
                )

                warning_limit_day_first_hour = datetime.combine(warning_limit, time.min)
                warning_limit_day_last_hour = datetime.combine(warning_limit, time.max)
                closing_remaining_days = (
                    team_id.inactive_tickets_day_limit_closing
                    - team_id.inactive_tickets_day_limit_warning
                )
                warning_domain = [
                    ("team_id", "=", team_id.id),
                    ("stage_id", "in", ticket_stage_ids),
                    ("last_stage_update", ">=", warning_limit_day_first_hour),
                    ("last_stage_update", "<=", warning_limit_day_last_hour),
                ]
                if ticket_category_ids:
                    warning_domain.append(("category_id", "in", ticket_category_ids))
                warning_ticket_ids = self.env["helpdesk.ticket"].search(warning_domain)
                if warning_ticket_ids:
                    for ticket in warning_ticket_ids:
                        # Set template context
                        context = {
                            "stage": ticket.stage_id.name,
                            "close": False,
                            "remaining_days": closing_remaining_days,
                        }
                        # Send warning email
                        warning_email_id = (
                            team_id.warning_inactive_mail_template_id.with_context(
                                **context
                            ).send_mail(ticket.id)
                        )
                        if warning_email_id:
                            _logger.info(
                                "Sending warning ticket email for %s", ticket.number
                            )
                            warning_email_ids.append(warning_email_id)

            closing_domain = [
                ("team_id", "=", team_id.id),
                ("stage_id", "in", ticket_stage_ids),
                ("last_stage_update", "<=", closing_limit),
            ]
            if ticket_category_ids:
                closing_domain.append(("category_id", "in", ticket_category_ids))
            closing_ticket_ids = self.env["helpdesk.ticket"].search(closing_domain)
            if closing_ticket_ids:
                for ticket in closing_ticket_ids:
                    context = {"stage": ticket.stage_id.name, "close": True}
                    ticket.write({"stage_id": closing_stage.id})
                    # Log automated closing ticket action into chatter
                    msg = "Ticket closed automatically because have \
                    reached the inactivity days limit"
                    ticket.message_post(body=msg)
                    # Send closing email (optional — skipped if no template is set)
                    if team_id.close_inactive_mail_template_id:
                        closing_email_id = (
                            team_id.close_inactive_mail_template_id.with_context(
                                **context
                            ).send_mail(ticket.id)
                        )
                        if closing_email_id:
                            _logger.info(
                                "Sending autoclosing ticket email for %s",
                                ticket.number,
                            )
                            closing_email_ids.append(closing_email_id)
            return {
                "warning_email_ids": warning_email_ids,
                "closing_email_ids": closing_email_ids,
            }

# --- From helpdesk_ticket_partner_response ---
# Copyright 2024 Antoni Marroig(APSL-Nagarro)<amarroig@apsl.net>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).



class HelpdeskTicketTeam(models.Model):
    _inherit = "helpdesk.ticket.team"

    autoupdate_ticket_stage = fields.Boolean(
        string="Auto Update Ticket Stage",
        help="Update ticket stage when a new message is registered by the partner.",
        default=False,
    )
    autopupdate_src_stage_ids = fields.Many2many(
        comodel_name="helpdesk.ticket.stage",
        relation="change_stage_partner_response",
        string="Autoupdate Source Stages",
        help=(
            "If a partner posts a message in a ticket on this stages, "
            "the own stage of the ticket will be update by the one set on "
            "Autoupdate Destination Stage "
        ),
    )
    autopupdate_dest_stage_id = fields.Many2one(
        "helpdesk.ticket.stage",
        string="Autoupdate Destination Stage",
        help=("Target stage on partner's message post "),
    )


class HelpdeskTeam(models.Model):
    _inherit = "helpdesk.ticket.team"

    type_ids = fields.Many2many(
        "helpdesk.ticket.type",
        string="Ticket Type",
        help="Ticket Types the team will use. This team's tickets will only "
        "be able to use those types.",
    )
