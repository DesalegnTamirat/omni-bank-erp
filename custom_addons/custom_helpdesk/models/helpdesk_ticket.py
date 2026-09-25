# -*- coding: utf-8 -*-
from odoo import Command, api, fields, models
from odoo import api, fields, models
from odoo import api, fields, models, tools
from odoo import fields, models
from odoo import models
from odoo.exceptions import AccessError
from odoo.exceptions import UserError
from odoo.fields import Domain
from odoo.tools.safe_eval import safe_eval
import ast



class HelpdeskTicket(models.Model):
    _name = "helpdesk.ticket"
    _description = "Helpdesk Ticket"
    _rec_name = "number"
    _rec_names_search = ["number", "name"]
    _order = "priority desc, sequence, number desc, id desc"
    _mail_post_access = "read"
    _inherit = [
        "mail.thread.cc",
        "mail.activity.mixin",
        "portal.mixin",
        "mail.tracking.duration.mixin",
    ]
    _track_duration_field = "stage_id"

    @api.depends("team_id")
    def _compute_stage_id(self):
        # This compute is executed on user change, even if not changing team, so let's
        # apply a preventive check for not changing stage if the current one is still
        # applicable to the current team
        for ticket in self:
            applicable_stages = ticket.team_id._get_applicable_stages()
            if ticket.stage_id not in applicable_stages:
                ticket.stage_id = applicable_stages[:1]

    @api.depends("team_id")
    def _compute_user_id(self):
        for ticket in self:
            if ticket.team_id and ticket.user_id not in ticket.team_id.user_ids:
                # If the user is not part of the team, we remove the user
                ticket.user_id = False

    @api.depends("user_id")
    def _compute_team_id(self):
        for ticket in self:
            if not ticket.team_id and ticket.user_id.helpdesk_team_ids:
                # If no team is set, we default to the user's first team
                ticket.team_id = ticket.user_id.helpdesk_team_ids[0]

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        """Show always the stages without team, or stages of the default team."""
        search_domain = [
            "|",
            ("id", "in", stages.ids),
            ("team_ids", "=", False),
        ]
        default_team_id = self.default_get(["team_id"])
        if default_team_id:
            search_domain = [
                "|",
                ("team_ids", "=", default_team_id["team_id"]),
            ] + search_domain
        return stages.search(search_domain)

    @api.depends("duplicate_ids")
    def _compute_duplicate_count(self):
        for record in self:
            record.duplicate_count = len(record.duplicate_ids)

    number = fields.Char(string="Ticket number", default="/", readonly=True)
    name = fields.Char(string="Title", required=True)
    description = fields.Html(required=True, sanitize_style=True)
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Assigned user",
        tracking=True,
        index=True,
        compute="_compute_user_id",
        store=True,
        readonly=False,
        domain="team_id and [('share', '=', False),('id', 'in', user_ids)] or [('share', '=', False)]",  # noqa E501,
    )
    user_ids = fields.Many2many(
        comodel_name="res.users", related="team_id.user_ids", string="Users"
    )
    stage_id = fields.Many2one(
        comodel_name="helpdesk.ticket.stage",
        string="Stage",
        compute="_compute_stage_id",
        store=True,
        readonly=False,
        ondelete="restrict",
        tracking=True,
        group_expand="_read_group_stage_ids",
        copy=False,
        index=True,
        domain="['|',('team_ids', '=', team_id),('team_ids','=',False)]",
    )
    partner_id = fields.Many2one(comodel_name="res.partner", string="Contact")
    commercial_partner_id = fields.Many2one(
        string="Commercial Partner",
        store=True,
        related="partner_id.commercial_partner_id",
    )
    partner_name = fields.Char()
    partner_email = fields.Char(string="Email")

    # --- Banking & Customer Enhancements (Enhancement 03) ---
    cif_number = fields.Char(string="CIF Number", tracking=True, index=True)
    account_number = fields.Char(string="Account Number", tracking=True, index=True)
    customer_type = fields.Selection(
        [
            ("internal", "Internal (Branch / HO / District)"),
            ("external_new", "External - New / Prospect"),
            ("external_existing", "External - Existing Customer"),
        ],
        string="Customer Type",
        default="external_existing",
        tracking=True,
    )
    customer_segment = fields.Selection(
        [
            ("retail", "Retail"),
            ("sme", "SME"),
            ("corporate", "Corporate"),
            ("vip", "VIP"),
            ("youth", "Youth"),
        ],
        string="Customer Segmentation",
        default="retail",
        tracking=True,
    )
    language_tag = fields.Selection(
        [
            ("amharic", "Amharic"),
            ("english", "English"),
            ("afan_oromo", "Afan Oromo"),
            ("tigrigna", "Tigrigna"),
            ("other", "Other"),
        ],
        string="Language Preference",
        default="amharic",
    )
    case_type = fields.Selection(
        [
            ("complaint", "Complaint"),
            ("inquiry", "Inquiry"),
            ("service_request", "Service Request"),
            ("incident", "Incident"),
            ("technical", "Technical / System Issue"),
            ("fraud_alert", "Fraud Alert"),
            ("suggestion", "Suggestion"),
            ("feedback", "Feedback"),
        ],
        string="Case Type",
        default="inquiry",
        tracking=True,
    )
    service_family_id = fields.Many2one(
        "helpdesk.service.family",
        string="Service Family",
        index=True,
    )
    sub_category_id = fields.Many2one(
        "helpdesk.ticket.category",
        string="Sub Category",
        domain="[('parent_id', '=', category_id)]",
    )
    
    # NBE Complaint Management
    is_complaint = fields.Boolean(string="Is NBE Complaint", default=False, tracking=True)
    regulatory_tracking_number = fields.Char(string="Regulatory Tracking No.", copy=False)
    ethics_investigation = fields.Text(string="Ethics Investigation & Follow-up")
    ethics_officer_id = fields.Many2one("res.users", string="Ethics Officer / Investigator")

    last_stage_update = fields.Datetime(default=fields.Datetime.now)
    assigned_date = fields.Datetime(copy=False)
    closed_date = fields.Datetime(copy=False)
    closed = fields.Boolean(related="stage_id.closed")
    unattended = fields.Boolean(related="stage_id.unattended", store=True)
    tag_ids = fields.Many2many(comodel_name="helpdesk.ticket.tag", string="Tags")
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    channel_id = fields.Many2one(
        comodel_name="helpdesk.ticket.channel",
        string="Channel",
        help="Channel indicates where the source of a ticket"
        "comes from (it could be a phone call, an email...)",
    )
    category_id = fields.Many2one(
        comodel_name="helpdesk.ticket.category",
        string="Category",
    )
    team_id = fields.Many2one(
        comodel_name="helpdesk.ticket.team",
        string="Team",
        index=True,
        compute="_compute_team_id",
        store=True,
        readonly=False,
    )
    priority = fields.Selection(
        selection=[
            ("0", "Low"),
            ("1", "Medium"),
            ("2", "High"),
            ("3", "Critical"),
        ],
        string="Priority",
        default="1",
        tracking=True,
    )
    attachment_ids = fields.One2many(
        comodel_name="ir.attachment",
        inverse_name="res_id",
        domain=[("res_model", "=", "helpdesk.ticket")],
        string="Media Attachments",
    )
    attachment_number = fields.Integer(
        compute="_compute_attachment_number", string="Number of Attachments"
    )

    def _compute_attachment_number(self):
        for ticket in self:
            ticket.attachment_number = self.env["ir.attachment"].search_count(
                [("res_model", "=", "helpdesk.ticket"), ("res_id", "=", ticket.id)]
            )

    def action_get_attachment_tree_view(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("base.action_attachment")
        action["domain"] = [
            ("res_model", "=", "helpdesk.ticket"),
            ("res_id", "=", self.id),
        ]
        action["context"] = {
            "default_res_model": "helpdesk.ticket",
            "default_res_id": self.id,
        }
        return action
    color = fields.Integer(string="Color Index")
    kanban_state = fields.Selection(
        selection=[
            ("normal", "Default"),
            ("done", "Ready for next stage"),
            ("blocked", "Blocked"),
        ],
    )
    sequence = fields.Integer(
        index=True,
        default=10,
        help="Gives the sequence order when displaying a list of tickets.",
    )
    active = fields.Boolean(default=True)
    properties = fields.Properties(
        definition="team_id.ticket_properties", copy=True, precompute=False
    )

    duplicate_id = fields.Many2one(
        "helpdesk.ticket", string="Duplicate of", tracking=True, copy=False
    )
    duplicate_ids = fields.One2many(
        "helpdesk.ticket", "duplicate_id", string="Duplicate tickets"
    )
    duplicate_count = fields.Integer(compute="_compute_duplicate_count")
    duplicate_tracking_enabled = fields.Boolean(
        related="company_id.helpdesk_mgmt_duplicate_tracking"
    )

    def action_open_duplicate_wizard(self):
        self.ensure_one()
        target_stage = self.env.company.helpdesk_mgmt_duplicate_ticket_stage_id
        return {
            "name": "Mark as Duplicate",
            "type": "ir.actions.act_window",
            "res_model": "helpdesk.ticket.duplicate.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_ticket_id": self.id,
                "default_target_stage_id": target_stage.id,
            },
        }

    def action_view_duplicates(self):
        self.ensure_one()
        return {
            "name": "Duplicates",
            "type": "ir.actions.act_window",
            "res_model": "helpdesk.ticket",
            "view_mode": "list",
            "target": "new",
            "domain": [("duplicate_id", "=", self.id)],
        }

    @api.model
    def default_get(self, fields):
        # The appropriate user is defined only if the "Auto assign User" option is
        # checked in the company.
        # If the team is set, the user must belong to that team.
        defaults = super().default_get(fields)
        company_id = defaults.get("company_id") or self.env.company.id
        if "user_id" in fields and not defaults.get("user_id"):
            company = self.env["res.company"].browse(company_id)
            if company.helpdesk_mgmt_ticket_auto_assign:
                if defaults.get("team_id"):
                    team = self.env["helpdesk.ticket.team"].browse(
                        defaults.get("team_id")
                    )
                    if self.env.user in team.user_ids:
                        defaults["user_id"] = self.env.user.id
                else:
                    defaults["user_id"] = self.env.user.id
        return defaults

    @api.depends("name")
    def _compute_display_name(self):
        for ticket in self:
            ticket.display_name = f"{ticket.number} - {ticket.name}"

    def assign_to_me(self):
        self.ensure_one()
        if self.team_id and self.env.user not in self.team_id.user_ids:
            raise AccessError(
                self.env._(
                    "You cannot assign this ticket to yourself because you are not "
                    "a member of the assigned team."
                )
            )
        self.write({"user_id": self.env.user.id})

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        if self.partner_id:
            self.partner_name = self.partner_id.name
            self.partner_email = self.partner_id.email

    # ---------------------------------------------------
    # CRUD
    # ---------------------------------------------------

    def _creation_subtype(self):
        return self.env.ref("custom_helpdesk.hlp_tck_created", raise_if_not_found=False) or self.env.ref("mail.mt_note")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("number") or vals.get("number") == "/":
                vals["number"] = self._prepare_ticket_number(vals)
            if vals.get("user_id") and not vals.get("assigned_date"):
                vals["assigned_date"] = fields.Datetime.now()
            if vals.get("team_id"):
                team = self.env["helpdesk.ticket.team"].browse([vals["team_id"]])
                if team.company_id:
                    vals["company_id"] = team.company_id.id
                if "stage_id" not in vals or not vals.get("stage_id"):
                    stages = team._get_applicable_stages()
                    if stages:
                        vals["stage_id"] = stages[:1].id
            if vals.get("team_id") and not vals.get("user_id"):
                team = self.env["helpdesk.ticket.team"].browse(vals["team_id"])
                auto_user = team._get_auto_assign_user()
                if auto_user:
                    vals["user_id"] = auto_user.id
                    vals["assigned_date"] = fields.Datetime.now()
            if not vals.get("stage_id"):
                first_stage = self.env["helpdesk.ticket.stage"].search([], order="sequence asc", limit=1)
                if first_stage:
                    vals["stage_id"] = first_stage.id
            if self.env.context.get("fetchmail_cron_running") and not vals.get(
                "channel_id"
            ):
                channel_email_id = self.env.ref(
                    "custom_helpdesk.helpdesk_ticket_channel_email",
                    raise_if_not_found=False,
                )
                if channel_email_id:
                    vals["channel_id"] = channel_email_id.id
        return super().create(vals_list)

    def copy(self, default=None):
        self.ensure_one()
        if default is None:
            default = {}
        if "number" not in default:
            default["number"] = self._prepare_ticket_number(default)
        res = super().copy(default)
        return res

    def write(self, vals):
        for ticket in self:
            now = fields.Datetime.now()
            if vals.get("stage_id"):
                stage = self.env["helpdesk.ticket.stage"].browse([vals["stage_id"]])
                vals["last_stage_update"] = now
                if stage.closed:
                    vals["closed_date"] = now
            if vals.get("user_id"):
                vals["assigned_date"] = now
            elif vals.get("team_id") and "user_id" not in vals and not ticket.user_id:
                team = self.env["helpdesk.ticket.team"].browse(vals["team_id"])
                auto_user = team._get_auto_assign_user()
                if auto_user:
                    vals["user_id"] = auto_user.id
                    vals["assigned_date"] = now
        return super().write(vals)

    def action_assign_to_me(self):
        self.ensure_one()
        self.write({
            "user_id": self.env.user.id,
            "assigned_date": fields.Datetime.now(),
        })
        self.message_post(body=f"Ticket manually assigned to <b>{self.env.user.name}</b>.")
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_duplicate_tickets(self):
        for ticket in self.browse(self.env.context["active_ids"]):
            ticket.copy()

    def _prepare_ticket_number(self, values=None):
        values = values or {}
        seq = self.env["ir.sequence"]
        if "company_id" in values and values["company_id"]:
            seq = seq.with_company(values["company_id"])
        number = seq.next_by_code("helpdesk.ticket.sequence")
        if not number or number == "/":
            today_str = fields.Date.today().strftime("%Y")
            last_ticket = self.sudo().search([("number", "like", f"TICK/{today_str}/%")], order="id desc", limit=1)
            next_id = 1
            if last_ticket and last_ticket.number and "/" in last_ticket.number:
                try:
                    next_id = int(last_ticket.number.split("/")[-1]) + 1
                except ValueError:
                    next_id = self.sudo().search_count([]) + 1
            number = f"TICK/{today_str}/{next_id:05d}"
        return number

    def _compute_access_url(self):
        res = super()._compute_access_url()
        for item in self:
            item.access_url = f"/my/ticket/{item.id}"
        return res

    # ---------------------------------------------------
    # Mail gateway
    # ---------------------------------------------------

    def _track_template(self, tracking):
        res = super()._track_template(tracking)
        ticket = self[0]
        if "stage_id" in tracking and ticket.stage_id.mail_template_id:
            res["stage_id"] = (
                ticket.stage_id.mail_template_id,
                {
                    # Need to set mass_mail so that the email will always be sent
                    "composition_mode": "mass_mail",
                    "auto_delete_keep_log": False,
                    "subtype_id": self.env["ir.model.data"]._xmlid_to_res_id(
                        "mail.mt_note"
                    ),
                    "email_layout_xmlid": "mail.mail_notification_light",
                },
            )
        return res

    @api.model
    def message_new(self, msg, custom_values=None):
        """Override message_new from mail gateway so we can set correct
        default values.
        """
        if custom_values is None:
            custom_values = {}
        defaults = {
            "name": msg.get("subject") or self.env._("No Subject"),
            "number": "/",
            "description": msg.get("body"),
            "partner_email": msg.get("from"),
            "partner_id": msg.get("author_id"),
        }
        defaults.update(custom_values)

        # Write default values coming from msg
        ticket = super().message_new(msg, custom_values=defaults)

        # Use mail gateway tools to search for partners to subscribe
        email_list = tools.email_split(
            (msg.get("to") or "") + "," + (msg.get("cc") or "")
        )
        partner_ids = [
            p.id
            for p in self.env["mail.thread"]._mail_find_partner_from_emails(
                email_list, records=ticket, force_create=False
            )
            if p
        ]
        ticket.message_subscribe(partner_ids)

        return ticket

    def message_update(self, msg, update_vals=None):
        """Override message_update to subscribe partners"""
        email_list = tools.email_split(
            (msg.get("to") or "") + "," + (msg.get("cc") or "")
        )
        partner_ids = [
            p.id
            for p in self.env["mail.thread"]._mail_find_partner_from_emails(
                email_list, records=self, force_create=False
            )
            if p
        ]
        self.message_subscribe(partner_ids)
        return super().message_update(msg, update_vals=update_vals)

    def _message_add_suggested_recipients(self, force_primary_email=False):
        suggested = super()._message_add_suggested_recipients(
            force_primary_email=force_primary_email
        )
        try:
            for ticket in self:
                if ticket.partner_id:
                    suggested[ticket.id]["partners"] |= ticket.partner_id
                elif ticket.partner_email:
                    suggested[ticket.id]["email_to_lst"] += (
                        tools.mail.email_split_and_format_normalize(
                            ticket.partner_email
                        )
                    )
        except AccessError:
            # no read access rights -> just ignore suggested recipients because this
            # imply modifying followers
            return suggested
        return suggested

    def _notify_get_reply_to(self, default=None, author_id=False):
        """Override to set alias of tasks to their team if any."""
        aliases = (
            self.sudo()
            .mapped("team_id")
            ._notify_get_reply_to(
                default=default,
                author_id=author_id,
            )
        )
        res = {ticket.id: aliases.get(ticket.team_id.id) for ticket in self}
        leftover = self.filtered(lambda rec: not rec.team_id)
        if leftover:
            res.update(
                super(HelpdeskTicket, leftover)._notify_get_reply_to(
                    default=default,
                    author_id=author_id,
                )
            )
        return res

# --- From helpdesk_mgmt_activity ---
# Copyright (C) 2024 Cetmix OÜ
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).




class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    can_create_activity = fields.Boolean(related="team_id.allow_set_activity")
    res_model = fields.Char(string="Source Document Model", index=True)
    res_id = fields.Integer(string="Source Document", index=True)

    record_ref = fields.Reference(
        selection="_selection_record_ref",
        compute="_compute_record_ref",
        inverse="_inverse_record_ref",
        string="Source Record",
    )
    source_activity_type_id = fields.Many2one(comodel_name="mail.activity.type")
    date_deadline = fields.Date(string="Due Date", default=fields.Date.today)
    next_stage_id = fields.Many2one(
        comodel_name="helpdesk.ticket.stage",
        compute="_compute_next_stage_id",
        store=True,
        index=True,
    )
    assigned_user_id = fields.Many2one(
        comodel_name="res.users",
    )
    is_new_stage = fields.Boolean(compute="_compute_is_new_stage")

    @api.model
    def _selection_record_ref(self):
        """Select target model for source document"""
        model_ids_str = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("helpdesk_mgmt_activity.helpdesk_available_model_ids", "[]")
        )
        model_ids = ast.literal_eval(model_ids_str)
        if not model_ids:
            return []
        IrModelAccess = self.env["ir.model.access"].with_user(self.env.user.id)
        available_models = self.env["ir.model"].search_read(
            [("id", "in", model_ids)], fields=["model", "name"]
        )
        return [
            (model.get("model"), model.get("name"))
            for model in available_models
            if IrModelAccess.check(model.get("model"), "read", False)
        ]

    @api.model
    def _get_team_stages(self, teams):
        """
        Get grouping stages by team id

        :param teams: helpdesk.ticket.team record set
        :return: dict {team_id: team stages recordset}
        """
        return {team.id: team._get_applicable_stages() for team in teams}

    def _compute_is_new_stage(self):
        for ticket in self:
            new_stage = ticket.team_id._get_applicable_stages()[:1]
            ticket.is_new_stage = ticket.stage_id == new_stage

    @api.depends("stage_id")
    def _compute_next_stage_id(self):
        """Compute next stage for ticket"""
        team_stages = self._get_team_stages(self.team_id)
        helpdesk_ticket_stage_obj = self.env["helpdesk.ticket.stage"]
        for record in self:
            current_stage = record.stage_id
            stages = team_stages.get(record.team_id.id, helpdesk_ticket_stage_obj)
            next_stage = (
                stages.filtered(
                    lambda stage, _cur_stage=current_stage: stage.sequence
                    > _cur_stage.sequence
                )[:1]
                or current_stage
            )
            record.next_stage_id = next_stage

    @api.depends("res_model", "res_id")
    def _compute_record_ref(self):
        """Compute Source Document Reference"""
        for rec in self:
            if not rec.res_model or not rec.res_id:
                rec.record_ref = None
                continue
            try:
                record = self.env[rec.res_model].browse(rec.res_id)
                record.check_access("read")
                rec.record_ref = f"{rec.res_model},{rec.res_id}"
            except Exception:
                rec.record_ref = None

    def _inverse_record_ref(self):
        """Set Source Document Reference"""
        for record in self:
            record_ref = record.record_ref
            record.write(
                {
                    "res_id": record_ref and record_ref.id or False,
                    "res_model": record_ref and record_ref._name or False,
                }
            )

    def set_next_stage(self):
        """Set next ticket stage"""
        for record in self:
            record.stage_id = record.next_stage_id

    def _check_activity_values(self):
        """Check activity values for helpdesk ticket"""
        if not self.can_create_activity:
            raise UserError(self.env._("You cannot create activity!"))
        if not (self.res_id and self.res_model):
            raise UserError(self.env._("Source Record is not set!"))
        if not self.source_activity_type_id:
            raise UserError(self.env._("Activity Type is not set!"))
        if not self.date_deadline:
            raise UserError(self.env._("Date Deadline is not set!"))
        if not self.assigned_user_id:
            raise UserError(self.env._("Assigned User is not set!"))

    def perform_action(self):
        """Perform action for ticket"""
        self.ensure_one()
        # Check values for create activity
        self._check_activity_values()
        try:
            # Create activity for source record
            self.record_ref.activity_schedule(
                summary=self.name,
                note=self.description,
                date_deadline=self.date_deadline,
                activity_type_id=self.source_activity_type_id.id,
                user_id=self.assigned_user_id.id,
                ticket_id=self.id,
            )
            self.set_next_stage()
        except Exception as e:
            raise UserError from e
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": self.env._("Activity has been created!"),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

# --- From helpdesk_mgmt_rating ---


class HelpdeskTicket(models.Model):
    _name = "helpdesk.ticket"
    _inherit = ["helpdesk.ticket", "rating.mixin"]

    positive_rate_percentage = fields.Integer(
        string="Positive Rates Percentage",
        compute="_compute_percentage",
        store=True,
        default=-1,
    )
    rating_status = fields.Selection(
        selection=[
            ("stage_change", "Rating when changing stage"),
            ("no_rate", "No rating"),
        ],
        string="Customer Rating",
        default="stage_change",
        required=True,
    )

    @api.depends("rating_ids.rating")
    def _compute_percentage(self):
        for ticket in self:
            activity = ticket.rating_get_grades()
            ticket.positive_rate_percentage = (
                activity["great"] * 100 / sum(activity.values())
                if sum(activity.values())
                else -1
            )

    def write(self, vals):
        res = super().write(vals)
        if "stage_id" in vals and vals.get("stage_id"):
            stage = self.env["helpdesk.ticket.stage"].browse(vals.get("stage_id"))
            if stage.rating_mail_template_id:
                self._send_ticket_rating_mail(force_send=True)
        return res

    def _send_ticket_rating_mail(self, force_send=False):
        for ticket in self:
            if ticket.rating_status == "stage_change":
                survey_template = ticket.stage_id.rating_mail_template_id
                if survey_template:
                    ticket.rating_send_request(
                        survey_template,
                        lang=ticket.partner_id.lang,
                        force_send=force_send,
                    )

    def _rating_apply_get_default_subtype_id(self):
        return self.env["ir.model.data"]._xmlid_to_res_id(
            "helpdesk_mgmt_rating.mt_ticket_rating"
        )

    def action_view_ticket_rating(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "helpdesk_mgmt_rating.helpdesk_ticket_rating_action"
        )
        action["name"] = self.env._("Ticket Rating")
        action_context = safe_eval(action["context"]) if action["context"] else {}
        action_context.update(self.env.context)
        action_context.pop("group_by", None)
        if not action_context.get("id"):
            action_context["id"] = self.id
        action["context"] = action_context
        return action

# --- From helpdesk_mgmt_sla ---
#    Copyright (C) 2020 GARCO Consulting <www.garcoconsulting.es>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).



class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    team_sla = fields.Boolean(string="Team SLA", related="team_id.use_sla")
    ticket_sla_ids = fields.One2many(
        "helpdesk.ticket.sla", inverse_name="ticket_id", readonly=True
    )
    sla_ids = fields.Many2many(
        comodel_name="helpdesk.sla",
        string="Applicable SLAs",
        compute="_compute_sla_ids",
    )
    sla_expired = fields.Boolean(
        string="SLA expired", compute="_compute_sla_data", search="_search_sla_expired"
    )
    sla_deadline = fields.Datetime(string="SLA deadline", compute="_compute_sla_data")
    sla_fits = fields.Boolean(compute="_compute_sla_fits")

    def _compute_sla_fits(self):
        for ticket in self:
            ticket.sla_fits = ticket.sla_ids == ticket._get_sla()

    @api.depends("ticket_sla_ids", "ticket_sla_ids.state", "ticket_sla_ids.deadline")
    def _compute_sla_data(self):
        now = fields.Datetime.now()
        for ticket in self:
            ticket.sla_expired = any(
                ticket.ticket_sla_ids.filtered(
                    lambda sla: sla.state == "expired"
                    or (
                        sla.state == "in_progress"
                        and sla.deadline
                        and sla.deadline < now
                    )
                )
            )
            ticket.sla_deadline = min(
                ticket.ticket_sla_ids.filtered(
                    lambda r: r.state == "in_progress"
                ).mapped("deadline"),
                default=False,
            )

    @api.depends("ticket_sla_ids")
    def _compute_sla_ids(self):
        for ticket in self:
            ticket.sla_ids = ticket.ticket_sla_ids.sla_id

    def _get_sla_ticket_domain(self):
        domain = Domain.OR(
            (Domain("team_ids", "=", False), Domain("team_ids", "=", self.team_id.id))
        )
        if self.tag_ids:
            domain += Domain.OR(
                (
                    Domain("tag_ids", "=", False),
                    Domain("tag_ids", "in", self.tag_ids.ids),
                )
            )
        else:
            domain += Domain("tag_ids", "=", False)
        if self.category_id:
            domain += Domain.OR(
                (
                    Domain("category_ids", "=", False),
                    Domain("category_ids", "=", self.category_id.id),
                )
            )
        else:
            domain += Domain("category_ids", "=", False)
        return domain

    def _get_sla(self):
        slas = self.env["helpdesk.sla"]
        for sla in self.env["helpdesk.sla"].search(self._get_sla_ticket_domain()):
            if not sla.domain or self.filtered_domain(safe_eval(sla.domain)):
                slas |= sla
        return slas

    def set_sla(self):
        for ticket in self:
            ticket.ticket_sla_ids.unlink()
            if ticket.team_id.use_sla:
                for sla in ticket._get_sla():
                    self.env["helpdesk.ticket.sla"].create(
                        {"ticket_id": ticket.id, "sla_id": sla.id}
                    )

    @api.model_create_multi
    def create(self, vals_list):
        tickets = super().create(vals_list)
        tickets.set_sla()
        return tickets

    def write(self, vals):
        result = super().write(vals)
        if "stage_id" in vals:
            for ticket_sla in self.ticket_sla_ids:
                ticket_sla._stage_recompute()
        return result

    def refresh_sla(self):
        self.ensure_one()
        slas = self._get_sla()
        self.ticket_sla_ids.filtered(lambda r: r.sla_id not in slas).unlink()
        for sla in slas - self.sla_ids:
            self.env["helpdesk.ticket.sla"].create(
                {"ticket_id": self.id, "sla_id": sla.id}
            )

    def _search_sla_expired(self, operator, value):
        return Domain("ticket_sla_ids.expired", operator, value)

# --- From helpdesk_product ---


# --- From helpdesk_ticket_partner_response ---
# Copyright 2025 Onestein - Anjeel Haria
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).



class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    def _message_post_after_hook(self, message, msg_vals):
        """Change status of ticket if the required conditions are satisfied"""
        if (
            self
            and self.env.user.partner_id.id == self.partner_id.id
            and self.team_id.autoupdate_ticket_stage
            and self.stage_id in self.team_id.autopupdate_src_stage_ids
        ):
            self.sudo().stage_id = self.team_id.autopupdate_dest_stage_id.id
        return super()._message_post_after_hook(message, msg_vals)

# --- From helpdesk_ticket_related ---
# Copyright 2024 Antoni Marroig(APSL-Nagarro)<amarroig@apsl.net>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).



class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    related_ticket_ids = fields.Many2many(
        "helpdesk.ticket",
        "ticket_relationship_table",
        "ticket_id1",
        "ticket_id2",
        string="Related tickets",
    )

    def write(self, vals):
        if "related_ticket_ids" in vals:
            for ticket in self.related_ticket_ids:
                if (
                    6 == vals.get("related_ticket_ids")[0][0]
                    and ticket.id not in vals.get("related_ticket_ids")[0][2]
                ):
                    ticket.write({"related_ticket_ids": [(3, self.id)]})
        res = super().write(vals)
        if "related_ticket_ids" in vals:
            for rel_ticket in self.related_ticket_ids:
                if self._origin.id not in rel_ticket.related_ticket_ids.ids:
                    rel_ticket.write({"related_ticket_ids": [(4, self.id)]})
        return res

    def open_ticket(self):
        return {
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "helpdesk.ticket",
            "res_id": self.id,
        }

# --- From helpdesk_type ---
# Copyright (c) 2019 Open Source Integrators
# Copyright (C) 2019 Konos
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    type_id = fields.Many2one("helpdesk.ticket.type", string="Type")

    @api.onchange("type_id")
    def _onchange_type_id(self):
        if self.type_id and self.team_id and self.type_id not in self.team_id.type_ids:
            self.team_id = False
            self.user_id = False


    # ── BRD 40 Core Functionalities & Custom Requirements ────────────────
    national_id = fields.Char(string="National ID (Fayda)", copy=False, help="Customer National ID / Fayda Number")
    digital_banking_id = fields.Char(string="Digital Banking ID", copy=False, help="Phone / Digital Banking Identifier")
    
    branch_id = fields.Many2one("hr.department", string="Customer Branch", help="Reporting Branch")
    district_id = fields.Many2one("hr.department", string="District", help="Bank District Office")
    work_unit_id = fields.Many2one("hr.department", string="Responsible Work Unit", help="2nd Level Work Unit / Directorate")
    
    incident_class = fields.Selection([
        ("operational_risk", "Operational Risk"),
        ("fraud", "Fraud"),
        ("compliance", "Compliance"),
        ("system_issue", "System Issue"),
        ("service_request", "Service Request"),
        ("customer_complaint", "Customer Complaint"),
    ], string="Incident Classification", default="service_request", tracking=True)
    
    root_cause = fields.Text(string="Root Cause Details", help="Root cause identified during investigation")
    corrective_action = fields.Text(string="Corrective Action Taken", help="Immediate fix or resolution step")
    preventive_action = fields.Text(string="Preventive Action Implemented", help="Long-term prevention step")
    fcr = fields.Boolean(string="First Contact Resolution (FCR)", default=False, tracking=True, help="Resolved on first contact without escalation")
    
    parent_id = fields.Many2one("helpdesk.ticket", string="Parent / Master Problem Ticket", index=True, ondelete="cascade")
    child_ids = fields.One2many("helpdesk.ticket", "parent_id", string="Child Tickets / Sub-Tasks")
    child_count = fields.Integer(string="Child Ticket Count", compute="_compute_child_count")
    is_problem = fields.Boolean(string="Is Master Problem Record", default=False)
    
    approval_state = fields.Selection([
        ("not_required", "Not Required"),
        ("pending", "Pending Approval"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ], string="Approval Status", default="not_required", tracking=True)
    
    reopen_count = fields.Integer(string="Reopen Count", default=0, readonly=True)
    reopen_date = fields.Datetime(string="Last Reopened On", readonly=True)
    
    @api.depends("child_ids")
    def _compute_child_count(self):
        for ticket in self:
            ticket.child_count = len(ticket.child_ids)

    is_escalated = fields.Boolean(
        string="Is Escalated",
        compute="_compute_is_escalated",
        search="_search_is_escalated",
    )

    @api.depends("stage_id", "stage_id.name")
    def _compute_is_escalated(self):
        for ticket in self:
            stage_name = (ticket.stage_id.name or "").lower()
            ticket.is_escalated = bool(
                ticket.stage_id and ("escalat" in stage_name or "2nd" in stage_name)
            )

    def _search_is_escalated(self, operator, value):
        escalated_stages = self.env["helpdesk.ticket.stage"].search(
            ["|", ("name", "ilike", "escalat"), ("name", "ilike", "2nd")]
        )
        if (operator in ("=", "==") and value) or (operator in ("!=", "<>") and not value):
            return [("stage_id", "in", escalated_stages.ids)]
        return [("stage_id", "not in", escalated_stages.ids)]

    def action_escalate(self):
        self.ensure_one()
        escalated_stage = self.env["helpdesk.ticket.stage"].search(
            ["|", ("name", "ilike", "escalat"), ("name", "ilike", "2nd")], limit=1
        )
        if not escalated_stage and self.stage_id:
            escalated_stage = self.env["helpdesk.ticket.stage"].search(
                [("sequence", ">", self.stage_id.sequence), ("closed", "=", False)],
                order="sequence asc",
                limit=1,
            )
        if not escalated_stage:
            escalated_stage = self.env["helpdesk.ticket.stage"].search([("closed", "=", False)], order="sequence desc", limit=1)

        if escalated_stage:
            self.write({"stage_id": escalated_stage.id})

        unit_name = self.work_unit_id.name if self.work_unit_id else "Unassigned 2nd Level Work Unit"
        self.message_post(body=f"Ticket escalated to 2nd Level Work Unit queue: <b>{unit_name}</b>.")
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_reset_to_draft(self):
        self.ensure_one()
        draft_stage = self.env["helpdesk.ticket.stage"].search(
            [("unattended", "=", True)], order="sequence asc", limit=1
        )
        if not draft_stage:
            draft_stage = self.env["helpdesk.ticket.stage"].search(
                [("closed", "=", False)], order="sequence asc", limit=1
            )
        if draft_stage:
            self.write({"stage_id": draft_stage.id})
        self.message_post(body="Ticket status has been reset to Draft / New stage.")
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_reopen(self):
        self.ensure_one()
        reopen_stage = self.env["helpdesk.ticket.stage"].search(
            [("closed", "=", False)], order="sequence asc", limit=1
        )
        if reopen_stage:
            self.write({
                "stage_id": reopen_stage.id,
                "reopen_count": self.reopen_count + 1,
                "reopen_date": fields.Datetime.now(),
            })
        self.message_post(body="Ticket has been reopened due to persistent issue.")
        return {"type": "ir.actions.client", "tag": "reload"}

# --- From helpdesk_product ---


# --- From helpdesk_ticket_partner_response ---
# Copyright 2025 Onestein - Anjeel Haria
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).



class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    def _message_post_after_hook(self, message, msg_vals):
        """Change status of ticket if the required conditions are satisfied"""
        if (
            self
            and self.env.user.partner_id.id == self.partner_id.id
            and self.team_id.autoupdate_ticket_stage
            and self.stage_id in self.team_id.autopupdate_src_stage_ids
        ):
            self.sudo().stage_id = self.team_id.autopupdate_dest_stage_id.id
        return super()._message_post_after_hook(message, msg_vals)

# --- From helpdesk_ticket_related ---
# Copyright 2024 Antoni Marroig(APSL-Nagarro)<amarroig@apsl.net>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).



class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    related_ticket_ids = fields.Many2many(
        "helpdesk.ticket",
        "ticket_relationship_table",
        "ticket_id1",
        "ticket_id2",
        string="Related tickets",
    )

    def write(self, vals):
        if "related_ticket_ids" in vals:
            for ticket in self.related_ticket_ids:
                if (
                    6 == vals.get("related_ticket_ids")[0][0]
                    and ticket.id not in vals.get("related_ticket_ids")[0][2]
                ):
                    ticket.write({"related_ticket_ids": [(3, self.id)]})
        res = super().write(vals)
        if "related_ticket_ids" in vals:
            for rel_ticket in self.related_ticket_ids:
                if self._origin.id not in rel_ticket.related_ticket_ids.ids:
                    rel_ticket.write({"related_ticket_ids": [(4, self.id)]})
        return res

    def open_ticket(self):
        return {
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "helpdesk.ticket",
            "res_id": self.id,
        }

# --- From helpdesk_type ---
# Copyright (c) 2019 Open Source Integrators
# Copyright (C) 2019 Konos
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    type_id = fields.Many2one("helpdesk.ticket.type", string="Type")

    @api.onchange("type_id")
    def _onchange_type_id(self):
        if self.type_id and self.team_id and self.type_id not in self.team_id.type_ids:
            self.team_id = False
            self.user_id = False


    # ── BRD 40 Core Functionalities & Custom Requirements ────────────────
    national_id = fields.Char(string="National ID (Fayda)", copy=False, help="Customer National ID / Fayda Number")
    digital_banking_id = fields.Char(string="Digital Banking ID", copy=False, help="Phone / Digital Banking Identifier")
    
    branch_id = fields.Many2one("hr.department", string="Customer Branch", help="Reporting Branch")
    district_id = fields.Many2one("hr.department", string="District", help="Bank District Office")
    work_unit_id = fields.Many2one("hr.department", string="Responsible Work Unit", help="2nd Level Work Unit / Directorate")
    
    incident_class = fields.Selection([
        ("operational_risk", "Operational Risk"),
        ("fraud", "Fraud"),
        ("compliance", "Compliance"),
        ("system_issue", "System Issue"),
        ("service_request", "Service Request"),
        ("customer_complaint", "Customer Complaint"),
    ], string="Incident Classification", default="service_request", tracking=True)
    
    root_cause = fields.Text(string="Root Cause Details", help="Root cause identified during investigation")
    corrective_action = fields.Text(string="Corrective Action Taken", help="Immediate fix or resolution step")
    preventive_action = fields.Text(string="Preventive Action Implemented", help="Long-term prevention step")
    fcr = fields.Boolean(string="First Contact Resolution (FCR)", default=False, tracking=True, help="Resolved on first contact without escalation")
    
    parent_id = fields.Many2one("helpdesk.ticket", string="Parent / Master Problem Ticket", index=True, ondelete="cascade")
    child_ids = fields.One2many("helpdesk.ticket", "parent_id", string="Child Tickets / Sub-Tasks")
    child_count = fields.Integer(string="Child Ticket Count", compute="_compute_child_count")
    is_problem = fields.Boolean(string="Is Master Problem Record", default=False)
    
    approval_state = fields.Selection([
        ("not_required", "Not Required"),
        ("pending", "Pending Approval"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ], string="Approval Status", default="not_required", tracking=True)
    
    reopen_count = fields.Integer(string="Reopen Count", default=0, readonly=True)
    reopen_date = fields.Datetime(string="Last Reopened On", readonly=True)
    
    @api.depends("child_ids")
    def _compute_child_count(self):
        for ticket in self:
            ticket.child_count = len(ticket.child_ids)
            
    is_escalated = fields.Boolean(
        string="Is Escalated",
        compute="_compute_is_escalated",
        search="_search_is_escalated",
    )

    @api.depends("stage_id", "stage_id.name")
    def _compute_is_escalated(self):
        for ticket in self:
            stage_name = (ticket.stage_id.name or "").lower()
            ticket.is_escalated = bool(
                ticket.stage_id and ("escalat" in stage_name or "2nd" in stage_name)
            )

    def _search_is_escalated(self, operator, value):
        escalated_stages = self.env["helpdesk.ticket.stage"].search(
            ["|", ("name", "ilike", "escalat"), ("name", "ilike", "2nd")]
        )
        if (operator in ("=", "==") and value) or (operator in ("!=", "<>") and not value):
            return [("stage_id", "in", escalated_stages.ids)]
        return [("stage_id", "not in", escalated_stages.ids)]

    def action_escalate(self):
        self.ensure_one()
        escalated_stage = self.env["helpdesk.ticket.stage"].search(
            ["|", ("name", "ilike", "escalat"), ("name", "ilike", "2nd")], limit=1
        )
        if not escalated_stage and self.stage_id:
            domain += Domain("category_ids", "=", False)
        return domain

    def _get_sla(self):
        slas = self.env["helpdesk.sla"]
        for sla in self.env["helpdesk.sla"].search(self._get_sla_ticket_domain()):
            if not sla.domain or self.filtered_domain(safe_eval(sla.domain)):
                slas |= sla
        return slas

    def set_sla(self):
        for ticket in self:
            ticket.ticket_sla_ids.unlink()
            if ticket.team_id.use_sla:
                for sla in ticket._get_sla():
                    self.env["helpdesk.ticket.sla"].create(
                        {"ticket_id": ticket.id, "sla_id": sla.id}
                    )

    @api.model_create_multi
    def create(self, vals_list):
        tickets = super().create(vals_list)
        tickets.set_sla()
        return tickets

    def write(self, vals):
        result = super().write(vals)
        if "stage_id" in vals:
            for ticket_sla in self.ticket_sla_ids:
                ticket_sla._stage_recompute()
        return result

    def refresh_sla(self):
        self.ensure_one()
        slas = self._get_sla()
        self.ticket_sla_ids.filtered(lambda r: r.sla_id not in slas).unlink()
        for sla in slas - self.sla_ids:
            self.env["helpdesk.ticket.sla"].create(
                {"ticket_id": self.id, "sla_id": sla.id}
            )

    def _search_sla_expired(self, operator, value):
        return Domain("ticket_sla_ids.expired", operator, value)

# --- From helpdesk_product ---


# --- From helpdesk_ticket_partner_response ---
# Copyright 2025 Onestein - Anjeel Haria
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).



class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    def _message_post_after_hook(self, message, msg_vals):
        """Change status of ticket if the required conditions are satisfied"""
        if (
            self
            and self.env.user.partner_id.id == self.partner_id.id
            and self.team_id.autoupdate_ticket_stage
            and self.stage_id in self.team_id.autopupdate_src_stage_ids
        ):
            self.sudo().stage_id = self.team_id.autopupdate_dest_stage_id.id
        return super()._message_post_after_hook(message, msg_vals)

# --- From helpdesk_ticket_related ---
# Copyright 2024 Antoni Marroig(APSL-Nagarro)<amarroig@apsl.net>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).



class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    related_ticket_ids = fields.Many2many(
        "helpdesk.ticket",
        "ticket_relationship_table",
        "ticket_id1",
        "ticket_id2",
        string="Related tickets",
    )

    def write(self, vals):
        if "related_ticket_ids" in vals:
            for ticket in self.related_ticket_ids:
                if (
                    6 == vals.get("related_ticket_ids")[0][0]
                    and ticket.id not in vals.get("related_ticket_ids")[0][2]
                ):
                    ticket.write({"related_ticket_ids": [(3, self.id)]})
        res = super().write(vals)
        if "related_ticket_ids" in vals:
            for rel_ticket in self.related_ticket_ids:
                if self._origin.id not in rel_ticket.related_ticket_ids.ids:
                    rel_ticket.write({"related_ticket_ids": [(4, self.id)]})
        return res

    def open_ticket(self):
        return {
            "type": "ir.actions.act_window",
            "view_mode": "form",
            "res_model": "helpdesk.ticket",
            "res_id": self.id,
        }

# --- From helpdesk_type ---
# Copyright (c) 2019 Open Source Integrators
# Copyright (C) 2019 Konos
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    type_id = fields.Many2one("helpdesk.ticket.type", string="Type")

    @api.onchange("type_id")
    def _onchange_type_id(self):
        if self.type_id and self.team_id and self.type_id not in self.team_id.type_ids:
            self.team_id = False
            self.user_id = False


    # ── BRD 40 Core Functionalities & Custom Requirements ────────────────
    national_id = fields.Char(string="National ID (Fayda)", copy=False, help="Customer National ID / Fayda Number")
    digital_banking_id = fields.Char(string="Digital Banking ID", copy=False, help="Phone / Digital Banking Identifier")
    
    branch_id = fields.Many2one("hr.department", string="Customer Branch", help="Reporting Branch")
    district_id = fields.Many2one("hr.department", string="District", help="Bank District Office")
    work_unit_id = fields.Many2one("hr.department", string="Responsible Work Unit", help="2nd Level Work Unit / Directorate")
    
    incident_class = fields.Selection([
        ("operational_risk", "Operational Risk"),
        ("fraud", "Fraud"),
        ("compliance", "Compliance"),
        ("system_issue", "System Issue"),
        ("service_request", "Service Request"),
        ("customer_complaint", "Customer Complaint"),
    ], string="Incident Classification", default="service_request", tracking=True)
    
    root_cause = fields.Text(string="Root Cause Details", help="Root cause identified during investigation")
    corrective_action = fields.Text(string="Corrective Action Taken", help="Immediate fix or resolution step")
    preventive_action = fields.Text(string="Preventive Action Implemented", help="Long-term prevention step")
    fcr = fields.Boolean(string="First Contact Resolution (FCR)", default=False, tracking=True, help="Resolved on first contact without escalation")
    
    parent_id = fields.Many2one("helpdesk.ticket", string="Parent / Master Problem Ticket", index=True, ondelete="cascade")
    child_ids = fields.One2many("helpdesk.ticket", "parent_id", string="Child Tickets / Sub-Tasks")
    child_count = fields.Integer(string="Child Ticket Count", compute="_compute_child_count")
    is_problem = fields.Boolean(string="Is Master Problem Record", default=False)
    
    approval_state = fields.Selection([
        ("not_required", "Not Required"),
        ("pending", "Pending Approval"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ], string="Approval Status", default="not_required", tracking=True)
    
    reopen_count = fields.Integer(string="Reopen Count", default=0, readonly=True)
    reopen_date = fields.Datetime(string="Last Reopened On", readonly=True)
    
    @api.depends("child_ids")
    def _compute_child_count(self):
        for ticket in self:
            ticket.child_count = len(ticket.child_ids)
            
    is_escalated = fields.Boolean(
        string="Is Escalated",
        compute="_compute_is_escalated",
        search="_search_is_escalated",
    )

    @api.depends("stage_id", "stage_id.name")
    def _compute_is_escalated(self):
        for ticket in self:
            stage_name = (ticket.stage_id.name or "").lower()
            ticket.is_escalated = bool(
                ticket.stage_id and ("escalat" in stage_name or "2nd" in stage_name)
            )

    def _search_is_escalated(self, operator, value):
        escalated_stages = self.env["helpdesk.ticket.stage"].search(
            ["|", ("name", "ilike", "escalat"), ("name", "ilike", "2nd")]
        )
        if (operator in ("=", "==") and value) or (operator in ("!=", "<>") and not value):
            return [("stage_id", "in", escalated_stages.ids)]
        return [("stage_id", "not in", escalated_stages.ids)]

    def action_escalate(self):
        self.ensure_one()
        escalated_stage = self.env["helpdesk.ticket.stage"].search(
            ["|", ("name", "ilike", "escalat"), ("name", "ilike", "2nd")], limit=1
        )
        if not escalated_stage and self.stage_id:
            escalated_stage = self.env["helpdesk.ticket.stage"].search(
                [("sequence", ">", self.stage_id.sequence), ("closed", "=", False)],
                order="sequence asc",
                limit=1,
            )
        if not escalated_stage:
            escalated_stage = self.env["helpdesk.ticket.stage"].search([("closed", "=", False)], order="sequence desc", limit=1)

        if escalated_stage:
            self.write({"stage_id": escalated_stage.id})

        unit_name = self.work_unit_id.name if self.work_unit_id else "Unassigned 2nd Level Work Unit"
        self.message_post(body=f"Ticket escalated to 2nd Level Work Unit queue: <b>{unit_name}</b>.")
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_reset_to_draft(self):
        self.ensure_one()
        draft_stage = self.env["helpdesk.ticket.stage"].search(
            [("unattended", "=", True)], order="sequence asc", limit=1
        )
        if not draft_stage:
            draft_stage = self.env["helpdesk.ticket.stage"].search(
                [("closed", "=", False)], order="sequence asc", limit=1
            )
        if draft_stage:
            self.write({"stage_id": draft_stage.id})
        self.message_post(body="Ticket status has been reset to Draft / New stage.")
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_reopen(self):
        self.ensure_one()
        new_stage = self.env["helpdesk.ticket.stage"].search([("closed", "=", False)], order="sequence asc", limit=1)
        if new_stage:
            self.write({
                "stage_id": new_stage.id,
                "reopen_count": self.reopen_count + 1,
                "reopen_date": fields.Datetime.now(),
            })
        self.message_post(body=f"Ticket reopened by user/agent (Reopen Count: {self.reopen_count}).")
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_approve_ticket(self):
        self.ensure_one()
        self.approval_state = "approved"
        self.message_post(body="Ticket exception/request has been APPROVED.")
        return True

    def action_reject_ticket(self):
        self.ensure_one()
        self.approval_state = "rejected"
        self.message_post(body="Ticket exception/request has been REJECTED.")
        return True

    def action_lookup_knowledge_base(self):
        self.ensure_one()
        domain = [("state", "=", "published")]
        if self.service_family_id:
            domain.append(("service_family_id", "=", self.service_family_id.id))
        return {
            "type": "ir.actions.act_window",
            "name": f"Knowledge Base SOPs - {self.service_family_id.name if self.service_family_id else 'All'}",
            "res_model": "helpdesk.knowledge.article",
            "view_mode": "list,form",
            "domain": domain,
            "target": "current",
        }

    internal_notes = fields.Text(
        string="Internal Agent Notes",
        help="Private notes for internal agent collaboration not visible to portal customers.",
    )
    customer_ticket_count = fields.Integer(
        string="Customer History Count",
        compute="_compute_customer_ticket_count",
    )

    @api.depends("partner_id", "cif_number", "account_number")
    def _compute_customer_ticket_count(self):
        for ticket in self:
            domain = []
            if ticket.partner_id:
                domain = [("partner_id", "=", ticket.partner_id.id)]
            elif ticket.cif_number:
                domain = [("cif_number", "=", ticket.cif_number)]
            elif ticket.account_number:
                domain = [("account_number", "=", ticket.account_number)]
            
            if domain:
                domain.append(("id", "!=", ticket.id))
                ticket.customer_ticket_count = self.search_count(domain)
            else:
                ticket.customer_ticket_count = 0

    def action_view_customer_tickets(self):
        self.ensure_one()
        domain = [("id", "!=", self.id)]
        if self.partner_id:
            domain.append(("partner_id", "=", self.partner_id.id))
        elif self.cif_number:
            domain.append(("cif_number", "=", self.cif_number))
        elif self.account_number:
            domain.append(("account_number", "=", self.account_number))
        else:
            domain.append(("id", "=", False))

        return {
            "type": "ir.actions.act_window",
            "name": f"Customer History - {self.partner_name or self.cif_number or 'Customer'}",
            "res_model": "helpdesk.ticket",
            "view_mode": "list,kanban,form",
            "domain": domain,
            "target": "current",
        }

    def action_detect_duplicates(self):
        """Detect duplicate complaints based on matching CIF, Account, or Partner."""
        self.ensure_one()
        conds = []
        if self.cif_number:
            conds.append(("cif_number", "=", self.cif_number))
        if self.account_number:
            conds.append(("account_number", "=", self.account_number))
        if self.partner_id:
            conds.append(("partner_id", "=", self.partner_id.id))

        if not conds:
            self.message_post(body="No CIF, Account Number, or Customer linked to scan for duplicates.")
            return True

        duplicates = self.search([("id", "!=", self.id), ("closed", "=", False)] + ["|"] * (len(conds) - 1) + conds)
        if duplicates:
            for dup in duplicates:
                existing = self.env["helpdesk.ticket.duplicate"].search([
                    ("ticket_id", "=", self.id),
                    ("duplicate_id", "=", dup.id)
                ], limit=1)
                if not existing:
                    self.env["helpdesk.ticket.duplicate"].create({
                        "ticket_id": self.id,
                        "duplicate_id": dup.id,
                    })
            self.message_post(body=f"<b>[DUPLICATE DETECTION]</b> Detected and linked {len(duplicates)} matching ticket(s): {', '.join(duplicates.mapped('number'))}.")
        else:
            self.message_post(body="No open duplicate tickets detected for this customer.")
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_split_ticket(self):
        """Split a complex ticket into a child sub-task ticket linked under master ticket."""
        self.ensure_one()
        self.write({"is_problem": True})
        child_vals = {
            "name": f"[SUB-TASK] {self.name}",
            "parent_id": self.id,
            "partner_id": self.partner_id.id if self.partner_id else False,
            "partner_name": self.partner_name,
            "partner_email": self.partner_email,
            "cif_number": self.cif_number,
            "account_number": self.account_number,
            "service_family_id": self.service_family_id.id if self.service_family_id else False,
            "category_id": self.category_id.id if self.category_id else False,
            "team_id": self.team_id.id if self.team_id else False,
            "work_unit_id": self.work_unit_id.id if self.work_unit_id else False,
            "description": f"Sub-task split from Master Ticket {self.number}:\n\n{self.description or ''}",
        }
        child_ticket = self.create(child_vals)
        self.message_post(body=f"Split sub-task created: {child_ticket.number} - {child_ticket.name}.")
        return {
            "type": "ir.actions.act_window",
            "name": "Sub-Task Created",
            "res_model": "helpdesk.ticket",
            "res_id": child_ticket.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_merge_tickets(self):
        """Merge selected active duplicate tickets into the master ticket."""
        self.ensure_one()
        active_ids = self.env.context.get("active_ids", [self.id])
        other_tickets = self.browse(active_ids).filtered(lambda t: t.id != self.id)
        if not other_tickets:
            self.message_post(body="Select additional duplicate tickets in list view to execute Merge.")
            return True

        merged_numbers = []
        for ot in other_tickets:
            merged_numbers.append(ot.number)
            if ot.description:
                self.description = (self.description or "") + f"\n\n--- Merged from {ot.number} ---\n" + ot.description
            ot.child_ids.write({"parent_id": self.id})
            closed_stage = self.env["helpdesk.ticket.stage"].search([("closed", "=", True)], limit=1)
            if closed_stage:
                ot.write({"stage_id": closed_stage.id})
            ot.message_post(body=f"Merged into master ticket {self.number}.")

        self.message_post(body=f"<b>[MERGE EXECUTED]</b> Merged contents from ticket(s): {', '.join(merged_numbers)}.")
        return {"type": "ir.actions.client", "tag": "reload"}

    @api.model
    def _cron_auto_close_tickets(self):
        """Auto-close solved tickets after 3 days of waiting for customer feedback"""
        solved_stages = self.env["helpdesk.ticket.stage"].search([("name", "ilike", "solved")])
        closed_stage = self.env["helpdesk.ticket.stage"].search([("closed", "=", True)], limit=1)
        if not solved_stages or not closed_stage:
            return
        limit_date = fields.Datetime.now() - timedelta(days=3)
        tickets = self.search([
            ("stage_id", "in", solved_stages.ids),
            ("write_date", "<=", limit_date)
        ])
        tickets.write({"stage_id": closed_stage.id})

    @api.model
    def _cron_check_sla_escalations(self):
        """Automatically escalate overdue SLA or high-priority unhandled tickets to 2nd Level Work Unit queue."""
        open_tickets = self.search([("closed", "=", False)])
        escalated_count = 0
        for ticket in open_tickets:
            if ticket.sla_expired or (ticket.priority == "3" and not ticket.is_escalated):
                ticket.action_escalate()
                ticket.message_post(
                    body="<b>[AUTOMATIC ESCALATION]</b> Ticket SLA expired or high-priority overdue. Automatically escalated to 2nd Level Work Unit queue."
                )
                escalated_count += 1
        return escalated_count
