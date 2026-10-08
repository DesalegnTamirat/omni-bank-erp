import logging
import re
from odoo import _, api, fields, models, tools
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


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
        "rating.mixin",
    ]
    _track_duration_field = "stage_id"

    # ── Compute helpers ───────────────────────────────────────────────────────

    @api.depends("team_id")
    def _compute_stage_id(self):
        for ticket in self:
            ticket.stage_id = ticket.team_id._get_applicable_stages()[:1]


    @api.depends("user_id")
    def _compute_team_id(self):
        for ticket in self:
            if not ticket.team_id and ticket.user_id.helpdesk_team_ids:
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

    @api.depends("sla_status_ids.deadline", "sla_status_ids.status")
    def _compute_sla_fields(self):
        for ticket in self:
            statuses = ticket.sla_status_ids
            deadlines = statuses.filtered("deadline").mapped("deadline")
            ticket.sla_deadline = min(deadlines) if deadlines else False
            if any(s.status == "failed" for s in statuses):
                ticket.sla_status = "failed"
            elif any(s.status == "in_progress" for s in statuses):
                ticket.sla_status = "in_progress"
            elif statuses:
                ticket.sla_status = "reached"
            else:
                ticket.sla_status = "in_progress"

    # ── Core fields ───────────────────────────────────────────────────────────

    number = fields.Char(string="Ticket number", default="/", readonly=True)
    name = fields.Char(string="Title", default="/", required=False)
    description = fields.Html(required=True, sanitize_style=True)
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Assigned user",
        tracking=True,
        index=True,
        domain="[('share', '=', False)]",
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
            ("3", "Very High"),
        ],
        default="1",
    )
    attachment_ids = fields.One2many(
        comodel_name="ir.attachment",
        inverse_name="res_id",
        domain=[("res_model", "=", "helpdesk.ticket")],
        string="Media Attachments",
    )
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

    # ── Duplicate tracking ────────────────────────────────────────────────────

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

    # ── Bunna Bank Customer Profile & Core Banking (CBS) Fields ──────────────
    customer_type_id = fields.Many2one(
        comodel_name="helpdesk.ticket.customer.type",
        string="Customer Type",
        index=True,
        tracking=True,
    )
    customer_type = fields.Char(
        string="Customer Type Code",
        compute="_compute_customer_type",
        inverse="_inverse_customer_type",
        store=True,
    )
    internal_unit_id = fields.Many2one(
        comodel_name="operating.unit",
        string="Originating Branch / Work Unit",
        help="Branch or Head Office work unit that submitted or reported this request.",
    )
    account_number = fields.Char(string="Account Number", tracking=True, index=True)
    cif_number = fields.Char(string="CIF Number", tracking=True, index=True)
    fayda_number = fields.Char(string="Fayda / National ID", tracking=True, index=True)
    partner_phone = fields.Char(string="Phone / Mobile", tracking=True)
    account_type = fields.Char(string="Account Type / Product", default="Savings Account")
    account_status = fields.Selection(
        selection=[
            ("active", "Active"),
            ("dormant", "Dormant"),
            ("frozen", "Frozen / Inactive"),
            ("closed", "Closed"),
        ],
        string="Account Status",
        default="active",
        tracking=True,
    )
    account_branch_id = fields.Many2one(
        comodel_name="operating.unit",
        string="Managing Branch / SOL",
        help="Core Banking home branch (SOL) where the customer's account is maintained.",
    )
    cbs_lookup_status = fields.Selection(
        selection=[
            ("verified", "Verified CBS Customer"),
            ("not_found", "Unverified / New Prospect"),
            ("pending", "Not Queried"),
        ],
        string="CBS Verification Status",
        default="pending",
    )
    customer_segment = fields.Selection(
        selection=[
            ("retail", "Retail Banking"),
            ("sme", "SME / Commercial"),
            ("corporate", "Corporate"),
            ("vip", "VIP / High Net Worth"),
            ("youth", "Youth / Student"),
            ("staff", "Bunna Bank Staff"),
        ],
        string="Customer Segment",
        default="retail",
        tracking=True,
    )
    preferred_language = fields.Selection(
        selection=[
            ("amharic", "Amharic"),
            ("english", "English"),
            ("afan_oromo", "Afan Oromo"),
            ("tigrigna", "Tigrigna"),
            ("somali", "Somali"),
        ],
        string="Preferred Language",
        default="amharic",
        tracking=True,
    )
    customer_age = fields.Integer(string="Age", tracking=True)
    customer_district = fields.Char(string="District Name", tracking=True)
    account_branch_name = fields.Char(string="Branch Name", tracking=True)
    customer_type_name = fields.Char(string="Customer Type", tracking=True)

    # ── 3-Tier Product & Service Catalogue ────────────────────────────────────
    service_family_id = fields.Many2one(
        comodel_name="helpdesk.service.family",
        string="Service Family",
        tracking=True,
        index=True,
    )
    service_id = fields.Many2one(
        comodel_name="helpdesk.service",
        string="Services",
        domain="[('family_id', '=', service_family_id)] if service_family_id else []",
        tracking=True,
        index=True,
    )
    service_sub_category_id = fields.Many2one(
        comodel_name="helpdesk.service.sub.category",
        string="Subservice Category / Issues",
        domain="[('service_id', '=', service_id)] if service_id else []",
        tracking=True,
        index=True,
    )
    service_sop = fields.Html(
        string="Resolution SOP",
        related="service_sub_category_id.resolution_sop",
        readonly=True,
    )

    # ── Team Operation / Dedicated Case List ──────────────────────────────────
    operation_id = fields.Many2one(
        comodel_name="helpdesk.team.operation",
        string="Operation / Case",
        domain="[('team_id', '=', team_id)] if team_id else []",
        tracking=True,
        index=True,
        help="Select the specific operation or case. The ticket will automatically be routed to the team owning this operation.",
    )

    # ── Case Type & Multi-Channel ─────────────────────────────────────────────
    case_type_id = fields.Many2one(
        comodel_name="helpdesk.ticket.case.type",
        string="Case Type",
        index=True,
        tracking=True,
    )
    case_type = fields.Char(
        string="Case Type Code",
        compute="_compute_case_type",
        inverse="_inverse_case_type",
        store=True,
    )
    channel_type = fields.Selection(
        selection=[
            ("phone", "Phone Call / IVR (Contact Center)"),
            ("email", "Email (CC Helpdesk)"),
            ("tidio_chat", "Tidio Website Chat"),
            ("web_portal", "Customer Web Portal"),
            ("telegram", "Telegram Bot"),
            ("whatsapp", "WhatsApp"),
            ("facebook", "Facebook Messenger / Page"),
            ("mobile_banking", "Mobile Banking App"),
            ("branch_walkin", "Branch Walk-in"),
        ],
        string="Communication Channel",
        default="phone",
        required=True,
        tracking=True,
    )
    social_chat_id = fields.Char(
        string="Social Chat / Phone ID",
        index=True,
        help="Telegram Chat ID or WhatsApp Phone Number from which this ticket originated.",
    )
    social_message_id = fields.Char(
        string="Originating Social Message ID",
        help="Telegram or WhatsApp incoming message identifier.",
    )
    is_nbe_complaint = fields.Boolean(
        string="NBE Regulated Complaint",
        compute="_compute_is_nbe_complaint",
        store=True,
        tracking=True,
    )
    nbe_reference_number = fields.Char(string="NBE Complaint Ref #", tracking=True)
    complaint_root_cause = fields.Text(string="Root Cause Analysis")
    corrective_action_plan = fields.Text(string="Corrective Action")
    preventive_action_plan = fields.Text(string="Preventive Action")
    ethics_officer_id = fields.Many2one(
        comodel_name="res.users",
        string="Ethics / Compliance Officer",
        tracking=True,
    )

    # ── Operational Level Agreement (OLA) & Multi-Tier Escalation ─────────────
    ola_id = fields.Many2one(
        comodel_name="helpdesk.ola",
        string="Applicable OLA Policy",
        compute="_compute_ola_policy",
        store=True,
    )
    ola_sdt_hours = fields.Float(
        string="OLA Target (Hours)",
        compute="_compute_ola_policy",
        store=True,
    )
    ola_deadline = fields.Datetime(
        string="OLA Deadline",
        tracking=True,
        copy=False,
    )
    ola_status = fields.Selection(
        selection=[
            ("none", "Not Escalated"),
            ("in_progress", "OLA In Progress"),
            ("reached", "OLA Met"),
            ("failed", "OLA Breached"),
        ],
        string="OLA Status",
        default="none",
        tracking=True,
        copy=False,
    )
    is_escalated = fields.Boolean(
        string="Escalated to 2nd Level",
        default=False,
        tracking=True,
        copy=False,
    )
    escalated_to_team_id = fields.Many2one(
        comodel_name="helpdesk.ticket.team",
        string="Escalated Team (2nd Level)",
        tracking=True,
        copy=False,
    )
    escalated_to_user_id = fields.Many2one(
        comodel_name="res.users",
        string="Escalated Specialist",
        tracking=True,
        copy=False,
    )
    escalation_date = fields.Datetime(string="Escalated On", copy=False)
    escalation_reason = fields.Text(string="Escalation Reason", copy=False)
    escalation_level = fields.Integer(string="Escalation Level", default=0, tracking=True)

    # ── 3rd Level Escalation Fields ──────────────────────────────────────────
    is_level_3_escalated = fields.Boolean(
        string="Escalated to 3rd Level",
        default=False,
        tracking=True,
        copy=False,
    )
    escalated_to_level_3_team_id = fields.Many2one(
        comodel_name="helpdesk.ticket.team",
        string="Escalated Team (3rd Level)",
        tracking=True,
        copy=False,
    )
    escalated_to_level_3_user_id = fields.Many2one(
        comodel_name="res.users",
        string="3rd Level Specialist / Executive",
        tracking=True,
        copy=False,
    )
    level_3_escalation_date = fields.Datetime(string="3rd Level Escalated On", copy=False)
    level_3_escalation_reason = fields.Text(string="3rd Level Escalation Reason", copy=False)

    is_ceo_escalated = fields.Boolean(string="CEO Level Escalated", default=False, tracking=True)
    last_escalation_date = fields.Datetime(string="Last Escalated Date", tracking=True)
    escalation_history_ids = fields.One2many(
        comodel_name="helpdesk.ticket.escalation.history",
        inverse_name="ticket_id",
        string="Escalation Audit Trail",
    )

    # ── Customer Inquiry Formulation & KB Integration ────────────────────────
    inquiry_summary = fields.Char(string="Customer Issue Summary")
    customer_request_details = fields.Text(string="Customer Inquired Details")
    agent_action_taken = fields.Text(string="Action Taken / Resolution Notes")
    kb_article_id = fields.Many2one(
        comodel_name="helpdesk.knowledge.article",
        string="Knowledge Base SOP / Article",
        domain="['|', ('service_id', '=', service_id), ('service_family_id', '=', service_family_id)] if service_id or service_family_id else []",
        help="Select a Knowledge Base article or SOP to pull resolution guidelines.",
    )

    # ── SLA ───────────────────────────────────────────────────────────────────

    sla_status_ids = fields.One2many(
        comodel_name="helpdesk.sla.status",
        inverse_name="ticket_id",
        string="SLA Status",
    )
    sla_deadline = fields.Datetime(
        string="SLA Deadline",
        compute="_compute_sla_fields",
        store=True,
        help="Earliest SLA deadline on this ticket.",
    )
    sla_status = fields.Selection(
        selection=[
            ("in_progress", "In Progress"),
            ("reached", "Reached"),
            ("failed", "Failed"),
        ],
        string="SLA Status",
        compute="_compute_sla_fields",
        store=True,
    )

    # ── Wizard flags (invisible fields) ──────────────────────────────────────

    # used by views to know whether crm / repair / loyalty are installed
    has_crm = fields.Boolean(compute="_compute_installed_modules")
    has_repair = fields.Boolean(compute="_compute_installed_modules")
    has_loyalty = fields.Boolean(compute="_compute_installed_modules")

    @api.depends_context("uid")
    def _compute_installed_modules(self):
        installed = self.env["ir.module.module"].sudo().search(
            [("name", "in", ["crm", "repair", "loyalty"]), ("state", "=", "installed")]
        ).mapped("name")
        for ticket in self:
            ticket.has_crm = "crm" in installed
            ticket.has_repair = "repair" in installed
            ticket.has_loyalty = "loyalty" in installed

    # ── Actions ───────────────────────────────────────────────────────────────

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

    def action_open_merge_wizard(self):
        self.ensure_one()
        return {
            "name": "Merge Tickets",
            "type": "ir.actions.act_window",
            "res_model": "helpdesk.ticket.merge.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_target_ticket_id": self.id,
                "active_ids": self.env.context.get("active_ids", [self.id]),
            },
        }

    def action_open_convert_wizard(self):
        self.ensure_one()
        return {
            "name": "Convert Ticket",
            "type": "ir.actions.act_window",
            "res_model": "helpdesk.ticket.convert.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_ticket_id": self.id},
        }

    def action_view_rating(self):
        self.ensure_one()
        return {
            "name": "Ratings",
            "type": "ir.actions.act_window",
            "res_model": "rating.rating",
            "view_mode": "list,form",
            "domain": [("res_model", "=", "helpdesk.ticket"), ("res_id", "=", self.id)],
        }

    # ── Bunna Bank Contact Center Actions & Computes ──────────────────────────

    @api.depends("case_type_id", "case_type_id.code")
    def _compute_case_type(self):
        for ticket in self:
            ticket.case_type = ticket.case_type_id.code if ticket.case_type_id else False

    def _inverse_case_type(self):
        for ticket in self:
            if ticket.case_type and (not ticket.case_type_id or ticket.case_type_id.code != ticket.case_type):
                ct = self.env["helpdesk.ticket.case.type"].search([("code", "=", ticket.case_type)], limit=1)
                if ct:
                    ticket.case_type_id = ct

    @api.depends("customer_type_id", "customer_type_id.code")
    def _compute_customer_type(self):
        for ticket in self:
            ticket.customer_type = ticket.customer_type_id.code if ticket.customer_type_id else False

    def _inverse_customer_type(self):
        for ticket in self:
            if ticket.customer_type and (not ticket.customer_type_id or ticket.customer_type_id.code != ticket.customer_type):
                ct = self.env["helpdesk.ticket.customer.type"].search([("code", "=", ticket.customer_type)], limit=1)
                if ct:
                    ticket.customer_type_id = ct

    @api.depends("case_type_id", "case_type_id.is_nbe_complaint", "case_type")
    def _compute_is_nbe_complaint(self):
        for ticket in self:
            ticket.is_nbe_complaint = bool(
                (ticket.case_type_id and ticket.case_type_id.is_nbe_complaint)
                or ticket.case_type == "complaint"
            )

    @api.onchange("case_type_id")
    def _onchange_case_type_id(self):
        if self.case_type_id and self.case_type_id.default_priority:
            self.priority = self.case_type_id.default_priority

    @api.depends("service_id", "service_sub_category_id")
    def _compute_ola_policy(self):
        ola_obj = self.env["helpdesk.ola"]
        for ticket in self:
            ola = False
            if ticket.service_sub_category_id:
                ola = ola_obj.search(
                    [("sub_category_id", "=", ticket.service_sub_category_id.id), ("active", "=", True)],
                    limit=1,
                )
            if not ola and ticket.service_id:
                ola = ola_obj.search(
                    [("service_id", "=", ticket.service_id.id), ("active", "=", True)],
                    limit=1,
                )
            ticket.ola_id = ola
            ticket.ola_sdt_hours = (
                ola.target_hours if ola else (ticket.service_id.default_sdt_hours if ticket.service_id else 24.0)
            )

    # ── Automatic Ticket Title Generation ─────────────────────────────────────
    def _generate_ticket_title(self):
        """Generate ticket title automatically using customer profile and selected service."""
        self.ensure_one()
        service_part = ""
        if self.service_sub_category_id:
            service_part = self.service_sub_category_id.name
        elif self.service_id:
            service_part = self.service_id.name
        elif self.service_family_id:
            service_part = self.service_family_id.name

        customer_part = ""
        if self.partner_id and self.partner_id.name:
            customer_part = self.partner_id.name
        elif self.partner_name:
            customer_part = self.partner_name
        elif self.account_number:
            customer_part = f"A/C: {self.account_number}"
        elif self.cif_number:
            customer_part = f"CIF: {self.cif_number}"
        elif self.partner_phone:
            customer_part = f"Tel: {self.partner_phone}"

        if service_part and customer_part:
            return f"[{service_part}] {customer_part}"
        elif service_part:
            ref = self.number if self.number and self.number != "/" else _("New")
            return f"{service_part} ({ref})"
        elif customer_part:
            return f"Ticket for {customer_part}"
        elif self.number and self.number != "/":
            return f"Ticket {self.number}"
        return _("New Service Ticket")

    def _update_ticket_title_if_auto(self):
        """Update ticket title if current title is default, empty, or previously generated."""
        for ticket in self:
            cur = (ticket.name or "").strip()
            if not cur or cur in ("/", "New", _("New"), _("New Ticket"), _("New Service Ticket")) or cur.startswith("[") or cur.startswith("Ticket"):
                ticket.name = ticket._generate_ticket_title()

    # ── Finacle Core Banking (CBS) Integration ────────────────────────────────
    def _apply_customer_profile(self, partner):
        """Populate ticket customer profile with verified Core Banking details."""
        vals = {
            "partner_id": partner.id,
            "partner_name": partner.name,
            "partner_email": partner.email or self.partner_email or False,
            "partner_phone": partner.phone or (getattr(partner, "mobile", False) if "mobile" in partner._fields else False) or self.partner_phone or False,
            "account_number": partner.account_number or self.account_number or False,
            "cif_number": partner.cif_number or self.cif_number or False,
            "fayda_number": partner.fayda_number or self.fayda_number or False,
            "account_type": partner.account_type or self.account_type or "Savings Account",
            "account_status": partner.account_status or self.account_status or "active",
            "account_branch_id": partner.branch_id.id if partner.branch_id else (self.account_branch_id.id if self.account_branch_id else False),
            "account_branch_name": partner.branch_name or (partner.branch_id.name if partner.branch_id else False) or getattr(self, "account_branch_name", False),
            "customer_district": partner.district_name or getattr(self, "customer_district", False),
            "customer_age": partner.age or getattr(self, "customer_age", 0),
            "customer_type_name": partner.customer_type or getattr(self, "customer_type_name", False),
            "customer_segment": partner.customer_segment or self.customer_segment or "retail",
            "preferred_language": partner.preferred_language or self.preferred_language or "amharic",
            "cbs_lookup_status": "verified",
        }
        for k, v in vals.items():
            setattr(self, k, v)
        self._update_ticket_title_if_auto()
        return vals

    @api.model
    def _fetch_or_create_finacle_cbs_partner(self, query_str, id_type="account"):
        """Query real Finacle Core Banking API (or mock fallback) and sync customer into res.partner."""
        from .cbs_service import query_cbs_api
        success, matched_cust, msg = query_cbs_api(self.env, query_str, id_type)
        if not success or not matched_cust:
            return False, msg

        partner_obj = self.env["res.partner"].sudo()
        domain = []
        if matched_cust.get("account_number"):
            domain.append(("account_number", "=ilike", matched_cust["account_number"].strip()))
        if matched_cust.get("cif_number"):
            domain.append(("cif_number", "=ilike", matched_cust["cif_number"].strip()))
        if matched_cust.get("fayda_number"):
            domain.append(("fayda_number", "=ilike", matched_cust["fayda_number"].strip()))
        if matched_cust.get("phone"):
            domain.append(("phone", "=ilike", matched_cust["phone"].strip()))

        partner = False
        if domain:
            or_domain = ["|"] * (len(domain) - 1) + domain if len(domain) > 1 else domain
            partner = partner_obj.search(or_domain, limit=1)

        # Match operating.unit branch
        branch = False
        if matched_cust.get("branch_name"):
            branch = self.env["operating.unit"].sudo().search([
                ("name", "=ilike", matched_cust["branch_name"].strip())
            ], limit=1)
        if not branch:
            branch = self.env["operating.unit"].sudo().search([], limit=1)

        partner_vals = {}
        for k in ("name", "account_number", "cif_number", "fayda_number", "phone", "email",
                  "account_type", "account_status", "customer_segment", "preferred_language",
                  "age", "district_name", "branch_name", "customer_type"):
            val = matched_cust.get(k)
            if val is not None and val is not False and val != "":
                partner_vals[k] = val
        if branch and not partner_vals.get("branch_id"):
            partner_vals["branch_id"] = branch.id
        partner_vals["comment"] = "Verified Core Banking System (Finacle) customer profile."

        if partner:
            # Avoid overwriting valid customer data with empty responses
            partner.write(partner_vals)
        else:
            partner = partner_obj.create(partner_vals)

        return partner, msg

    def _lookup_and_apply_cbs(self, identifier, id_type="account"):
        """Search local CBS cache or query Finacle CBS service, then populate ticket fields."""
        if not identifier:
            return False, _("No identifier provided.")
        q = str(identifier).strip()
        partner_obj = self.env["res.partner"].sudo()

        partner = False
        if id_type == "account":
            partner = partner_obj.search([("account_number", "=ilike", q)], limit=1)
        elif id_type == "cif":
            partner = partner_obj.search([("cif_number", "=ilike", q)], limit=1)
        elif id_type == "fayda":
            partner = partner_obj.search([("fayda_number", "=ilike", q)], limit=1)
        elif id_type == "phone":
            digits = re.sub(r"\D", "", q)
            digits_suffix = digits[-9:] if len(digits) >= 9 else digits
            has_mobile = "mobile" in partner_obj._fields
            domain = ["|", ("phone", "=ilike", q), ("mobile", "=ilike", q)] if has_mobile else [("phone", "=ilike", q)]
            if digits_suffix:
                if has_mobile:
                    domain = [
                        "|", "|",
                        ("phone", "=ilike", q),
                        ("phone", "=ilike", f"%{digits_suffix}"),
                        ("mobile", "=ilike", f"%{digits_suffix}"),
                    ]
                else:
                    domain = [
                        "|",
                        ("phone", "=ilike", q),
                        ("phone", "=ilike", f"%{digits_suffix}"),
                    ]
            partner = partner_obj.search(domain, limit=1)

        msg = _("Found in local database.")
        # If not found in local DB, or partner lacks core banking account details or age, query the Finacle CBS
        if not partner or not partner.account_number or not partner.age:
            cbs_partner, cbs_msg = self._fetch_or_create_finacle_cbs_partner(q, id_type)
            if cbs_partner:
                partner = cbs_partner
                msg = cbs_msg
            elif not partner:
                msg = cbs_msg

        if partner:
            self._apply_customer_profile(partner)
            return partner, msg
        else:
            self.cbs_lookup_status = "not_found"
            return False, msg

    # ── Onchange Triggers for Customer Identifiers & Service Catalogue ────────
    @api.onchange("account_number")
    def _onchange_account_number(self):
        val = (self.account_number or "").strip()
        if val and len(val) >= 3:
            if self.partner_id and (self.partner_id.account_number or "").strip().lower() == val.lower():
                return
            self._lookup_and_apply_cbs(val, "account")

    @api.onchange("cif_number")
    def _onchange_cif_number(self):
        val = (self.cif_number or "").strip()
        if val and len(val) >= 3:
            if self.partner_id and (self.partner_id.cif_number or "").strip().lower() == val.lower():
                return
            self._lookup_and_apply_cbs(val, "cif")

    @api.onchange("fayda_number")
    def _onchange_fayda_number(self):
        val = (self.fayda_number or "").strip()
        if val and len(val) >= 3:
            if self.partner_id and (self.partner_id.fayda_number or "").strip().lower() == val.lower():
                return
            self._lookup_and_apply_cbs(val, "fayda")

    @api.onchange("partner_phone")
    def _onchange_partner_phone(self):
        val = (self.partner_phone or "").strip()
        if val and len(val) >= 4:
            if self.partner_id:
                partner_phone = (self.partner_id.phone or "").strip()
                partner_mob = (getattr(self.partner_id, "mobile", "") or "").strip() if "mobile" in self.partner_id._fields else ""
                if partner_phone == val or partner_mob == val:
                    return
            self._lookup_and_apply_cbs(val, "phone")

    @api.onchange("partner_id")
    def _onchange_partner_id_banking(self):
        if self.partner_id:
            self._apply_customer_profile(self.partner_id)

    @api.onchange("service_family_id")
    def _onchange_service_family_id(self):
        if self.service_family_id:
            if self.service_id and self.service_id.family_id != self.service_family_id:
                self.service_id = False
                self.service_sub_category_id = False
        else:
            self.service_id = False
            self.service_sub_category_id = False
        self._update_ticket_title_if_auto()

    @api.onchange("service_id")
    def _onchange_service_id(self):
        if self.service_id:
            if self.service_id.family_id and self.service_family_id != self.service_id.family_id:
                self.service_family_id = self.service_id.family_id
            if self.service_sub_category_id and self.service_sub_category_id.service_id != self.service_id:
                self.service_sub_category_id = False
            if self.service_id.responsible_team_id and not self.team_id:
                self.team_id = self.service_id.responsible_team_id
        else:
            self.service_sub_category_id = False
        self._update_ticket_title_if_auto()

    @api.onchange("service_sub_category_id")
    def _onchange_service_sub_category_id(self):
        if self.service_sub_category_id:
            if self.service_sub_category_id.service_id and self.service_id != self.service_sub_category_id.service_id:
                self.service_id = self.service_sub_category_id.service_id
                if self.service_id.family_id:
                    self.service_family_id = self.service_id.family_id
            if self.service_sub_category_id.default_priority:
                self.priority = self.service_sub_category_id.default_priority
            if self.service_id and self.service_id.responsible_team_id and not self.team_id:
                self.team_id = self.service_id.responsible_team_id
        self._update_ticket_title_if_auto()

    @api.onchange("operation_id")
    def _onchange_operation_id(self):
        if self.operation_id:
            if self.operation_id.team_id:
                self.team_id = self.operation_id.team_id
            if self.operation_id.default_priority:
                self.priority = self.operation_id.default_priority
            if self.operation_id.case_type_id and not self.case_type_id:
                self.case_type_id = self.operation_id.case_type_id
            if self.operation_id.service_id and not self.service_id:
                self.service_id = self.operation_id.service_id
                if self.operation_id.service_id.family_id:
                    self.service_family_id = self.operation_id.service_id.family_id
            if self.operation_id.service_sub_category_id and not self.service_sub_category_id:
                self.service_sub_category_id = self.operation_id.service_sub_category_id

    @api.onchange("team_id")
    def _onchange_team_id(self):
        if self.team_id and self.operation_id and self.operation_id.team_id != self.team_id:
            self.operation_id = False

    def action_lookup_cbs_account(self):
        """Lookup customer profile from Core Banking (CBS / Finacle) or CRM."""
        self.ensure_one()
        query_val = (
            self.account_number
            or self.cif_number
            or self.fayda_number
            or self.partner_phone
            or (self.partner_id and (self.partner_id.account_number or self.partner_id.cif_number or self.partner_id.phone))
        )
        if not query_val:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Core Banking (Finacle) Lookup"),
                    "message": _("Please enter an Account Number, CIF, Fayda ID, or Phone to query Finacle CBS."),
                    "type": "warning",
                    "sticky": False,
                },
            }

        q = str(query_val).strip()
        id_type = "account"
        if self.account_number and self.account_number.strip() == q:
            id_type = "account"
        elif self.cif_number and self.cif_number.strip() == q:
            id_type = "cif"
        elif self.fayda_number and self.fayda_number.strip() == q:
            id_type = "fayda"
        elif self.partner_phone and self.partner_phone.strip() == q:
            id_type = "phone"

        partner, msg = self._lookup_and_apply_cbs(q, id_type)

        if partner:
            vals = self._apply_customer_profile(partner)
            self.write(vals)
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Finacle CBS Verified"),
                    "message": _("Customer profile for %s (A/C: %s, CIF: %s, Age: %s, District: %s) verified: %s") % (
                        partner.name, partner.account_number or "N/A", partner.cif_number or "N/A",
                        partner.age or "N/A", partner.district_name or "N/A", msg
                    ),
                    "type": "success",
                    "sticky": False,
                },
            }
        else:
            self.cbs_lookup_status = "not_found"
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Finacle CBS Lookup"),
                    "message": msg or (_("No customer found in Core Banking matching identifier: %s.") % q),
                    "type": "warning",
                    "sticky": False,
                },
            }

    def action_format_inquiry_description(self):
        """Synthesize agent caller notes into structured, professional ticket description."""
        self.ensure_one()
        sections = []
        if self.inquiry_summary:
            sections.append(f"<p><strong>Customer Issue Summary:</strong> {tools.html_escape(self.inquiry_summary)}</p>")
        if self.customer_request_details:
            details = tools.html_escape(self.customer_request_details).replace("\n", "<br/>")
            sections.append(f"<p><strong>Inquiry / Request Details:</strong><br/>{details}</p>")
        if self.agent_action_taken:
            action = tools.html_escape(self.agent_action_taken).replace("\n", "<br/>")
            sections.append(f"<p><strong>Action Taken / Guidance:</strong><br/>{action}</p>")
        if sections:
            formatted_html = (
                "<div style='background:#fdfbf7; padding:14px; border-left:4px solid #541718; "
                "border-radius:6px; margin-top:8px;'>" + "".join(sections) + "</div>"
            )
            self.description = (self.description or "") + ("<br/>" if self.description else "") + formatted_html
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Inquiry Structured"),
                    "message": _("Formatted inquiry details appended to description."),
                    "type": "success",
                    "sticky": False,
                },
            }

    def action_load_kb_sop_to_notes(self):
        """Pull Knowledge Base Article SOP / guidelines directly into Action Taken Notes."""
        self.ensure_one()
        sop_text = ""
        article_title = ""

        if self.kb_article_id:
            sop_text = self.kb_article_id.content or ""
            article_title = self.kb_article_id.name
        elif self.service_sub_category_id and self.service_sub_category_id.resolution_sop:
            sop_text = self.service_sub_category_id.resolution_sop
            article_title = self.service_sub_category_id.name
        else:
            # Auto-search matching Knowledge Base article
            domain = []
            if self.service_id:
                domain.append(("service_id", "=", self.service_id.id))
            elif self.service_family_id:
                domain.append(("service_family_id", "=", self.service_family_id.id))

            if domain:
                match = self.env["helpdesk.knowledge.article"].search(domain, limit=1)
                if match:
                    self.kb_article_id = match.id
                    sop_text = match.content or ""
                    article_title = match.name

        if not sop_text:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Knowledge Base Lookup"),
                    "message": _("No matching Knowledge Base SOP or article found for this service. Select an article manually or create one."),
                    "type": "warning",
                    "sticky": False,
                },
            }

        # Convert HTML content to clean plain text for agent notes
        clean_text = tools.html2plaintext(sop_text).strip()
        formatted_notes = f"--- [KB SOP: {article_title}] ---\n{clean_text}"

        if self.agent_action_taken:
            self.agent_action_taken = self.agent_action_taken + "\n\n" + formatted_notes
        else:
            self.agent_action_taken = formatted_notes

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("KB SOP Loaded"),
                "message": _("Knowledge Base SOP guidance loaded into Action Taken / Resolution Notes."),
                "type": "success",
                "sticky": False,
            },
        }

    def action_publish_notes_to_kb(self):
        """Publish Contact Center Assistant Notes into a new Knowledge Base Article."""
        self.ensure_one()
        title = self.inquiry_summary or self.display_name
        if not title:
            raise UserError(_("Please provide a Customer Issue Summary or Ticket Title before publishing to Knowledge Base."))

        content_parts = []
        if self.customer_request_details:
            details_html = tools.html_escape(self.customer_request_details).replace("\n", "<br/>")
            content_parts.append(f"<h3>Customer Inquiry / Issue Context</h3><p>{details_html}</p>")

        if self.agent_action_taken:
            action_html = tools.html_escape(self.agent_action_taken).replace("\n", "<br/>")
            content_parts.append(f"<h3>Standard Resolution Steps / Guidance</h3><p>{action_html}</p>")
        elif self.description:
            content_parts.append(f"<h3>Resolution Description</h3>{self.description}")

        if not content_parts:
            raise UserError(_("Please enter Action Taken / Resolution Notes before publishing to Knowledge Base."))

        meta_info = f"<hr/><p><small><em>Authored from Ticket {self.display_name} on {fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</em></small></p>"
        full_content = "".join(content_parts) + meta_info

        article = self.env["helpdesk.knowledge.article"].create({
            "name": title,
            "service_family_id": self.service_family_id.id if self.service_family_id else False,
            "service_id": self.service_id.id if self.service_id else False,
            "sub_category_id": self.service_sub_category_id.id if self.service_sub_category_id else False,
            "content": full_content,
            "state": "published",
            "author_id": self.env.user.id,
        })

        self.kb_article_id = article.id

        # Post chatter note
        self.message_post(
            body=_("<strong>Bookmarked Knowledge Base Article Created:</strong> <a href='#id=%s&amp;model=helpdesk.knowledge.article'>%s</a>") % (article.id, article.name),
            subtype_xmlid="mail.mt_note",
        )

        return {
            "name": _("Knowledge Base Article"),
            "type": "ir.actions.act_window",
            "res_model": "helpdesk.knowledge.article",
            "res_id": article.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_escalate_to_level_2(self, target_team_id=None, target_user_id=None, reason=None):
        """Escalate ticket to 2nd Level Work Unit and activate OLA tracking."""
        self.ensure_one()
        from datetime import timedelta
        now = fields.Datetime.now()
        vals = {
            "is_escalated": True,
            "escalation_level": 2 if self.escalation_level < 2 else self.escalation_level,
            "escalation_date": now,
            "last_escalation_date": now,
            "ola_status": "in_progress",
        }
        if target_team_id:
            vals["escalated_to_team_id"] = target_team_id.id if hasattr(target_team_id, "id") else target_team_id
            vals["team_id"] = target_team_id.id if hasattr(target_team_id, "id") else target_team_id
        if target_user_id:
            vals["escalated_to_user_id"] = target_user_id.id if hasattr(target_user_id, "id") else target_user_id
            vals["user_id"] = target_user_id.id if hasattr(target_user_id, "id") else target_user_id
        if reason:
            vals["escalation_reason"] = reason

        # Compute OLA deadline
        sdt = self.ola_sdt_hours or (self.service_id.default_sdt_hours if self.service_id else 24.0)
        vals["ola_deadline"] = now + timedelta(hours=sdt)

        self.write(vals)

        # Log Escalation History
        target_team_rec = self.env["helpdesk.ticket.team"].browse(vals.get("escalated_to_team_id")) if vals.get("escalated_to_team_id") else False
        target_user_rec = self.env["res.users"].browse(vals.get("escalated_to_user_id")) if vals.get("escalated_to_user_id") else False

        self.env["helpdesk.ticket.escalation.history"].sudo().create({
            "ticket_id": self.id,
            "escalation_level": 2,
            "previous_user_id": self.user_id.id if self.user_id else False,
            "new_user_id": target_user_rec.id if target_user_rec else (target_team_rec.user_id.id if target_team_rec and target_team_rec.user_id else False),
            "escalation_datetime": now,
            "sla_deadline": self.sla_deadline,
            "new_sla_deadline": vals["ola_deadline"],
            "is_ceo_level": False,
            "reason": _("2nd Level Work Unit Escalation: %s") % (reason or _("Transferred to specialized 2nd level unit")),
        })

        # Notify 2nd level team / user
        recipient = self.escalated_to_user_id or (self.escalated_to_team_id.user_id if self.escalated_to_team_id else False)
        if recipient and recipient.partner_id:
            author_name = self.env.user.name or _("System")
            team_or_user = self.escalated_to_team_id.name if self.escalated_to_team_id else recipient.name
            subject = _('"%s: 2nd Level Escalation" assigned to you') % self.display_name
            items = [
                (_("Document"), f'&quot;{self.display_name}&quot; ({_("Helpdesk Ticket")})'),
                (_("Escalated To"), team_or_user),
                (_("Reason"), reason or _("Requires 2nd-level specialized resolution")),
                (_("Service"), self.service_id.name if self.service_id else _("General")),
                (_("OLA Deadline"), str(vals.get("ola_deadline", ""))),
            ]
            body = self._format_ticket_notification_body(
                recipient_name=recipient.name,
                action_statement=_("%s has just escalated the following ticket to you") % author_name,
                items=items,
            )
            self.message_notify(
                partner_ids=[recipient.partner_id.id],
                subject=subject,
                body=body,
                email_layout_xmlid="mail.mail_notification_light",
            )
        return True

    def action_escalate_to_level_3(self, target_team_id=None, target_user_id=None, reason=None):
        """Escalate ticket to 3rd Level Executive Committee / Vendor Support / Specialist Taskforce."""
        self.ensure_one()
        from datetime import timedelta
        now = fields.Datetime.now()
        team_id_val = target_team_id.id if hasattr(target_team_id, "id") else target_team_id
        user_id_val = target_user_id.id if hasattr(target_user_id, "id") else target_user_id

        vals = {
            "is_escalated": True,
            "is_level_3_escalated": True,
            "escalation_level": 3,
            "level_3_escalation_date": now,
            "level_3_escalation_reason": reason or "",
            "last_escalation_date": now,
            "priority": "3",  # Critical Priority for 3rd level escalation
        }
        if team_id_val:
            vals["escalated_to_level_3_team_id"] = team_id_val
            vals["team_id"] = team_id_val
        if user_id_val:
            vals["escalated_to_level_3_user_id"] = user_id_val
            vals["user_id"] = user_id_val
        if reason:
            vals["escalation_reason"] = reason

        # Extend OLA deadline for 3rd level resolution
        sdt = (self.ola_sdt_hours or 24.0) * 1.5
        vals["ola_deadline"] = now + timedelta(hours=sdt)

        self.write(vals)

        # Log Escalation History
        target_team_rec = self.env["helpdesk.ticket.team"].browse(team_id_val) if team_id_val else False
        target_user_rec = self.env["res.users"].browse(user_id_val) if user_id_val else False

        self.env["helpdesk.ticket.escalation.history"].sudo().create({
            "ticket_id": self.id,
            "escalation_level": 3,
            "previous_user_id": self.user_id.id if self.user_id else False,
            "new_user_id": target_user_rec.id if target_user_rec else (target_team_rec.user_id.id if target_team_rec and target_team_rec.user_id else False),
            "escalation_datetime": now,
            "sla_deadline": self.sla_deadline,
            "new_sla_deadline": vals["ola_deadline"],
            "is_ceo_level": bool(target_team_rec and target_team_rec.team_tier in ("level_3_executive", "ethics_compliance")),
            "reason": _("3rd Level Escalation: %s") % (reason or _("Escalated to Executive / External Vendor Taskforce")),
        })

        # Post Chatter Note
        author_name = self.env.user.name or _("System")
        target_str = target_team_rec.name if target_team_rec else (target_user_rec.name if target_user_rec else _("3rd Level Unit"))
        msg = _(
            "<strong>🚨 Escalated to 3rd Level Executive / Vendor Unit</strong><br/>"
            "<b>Escalated By:</b> %s<br/>"
            "<b>Target 3rd Level Unit:</b> %s<br/>"
            "<b>Reason &amp; Findings:</b> %s<br/>"
            "<b>OLA Extension:</b> Extended to %s"
        ) % (author_name, target_str, reason or _("Executive intervention required"), vals["ola_deadline"])
        self.message_post(body=msg, subtype_xmlid="mail.mt_comment")

        # Send Discuss Notification to 3rd level recipient
        recipient = target_user_rec or (target_team_rec.user_id if target_team_rec else False)
        if recipient and recipient.partner_id:
            subject = _('"[3rd Level Escalation] %s" assigned for Executive Resolution') % self.display_name
            items = [
                (_("Document"), f'&quot;{self.display_name}&quot; ({_("Helpdesk Ticket")})'),
                (_("Escalated To (3rd Level)"), target_str),
                (_("Reason"), reason or _("Requires executive / vendor resolution")),
                (_("Service"), self.service_id.name if self.service_id else _("General")),
                (_("OLA Deadline"), str(vals["ola_deadline"])),
            ]
            body = self._format_ticket_notification_body(
                recipient_name=recipient.name,
                action_statement=_("%s has escalated this ticket to 3rd Level Executive Resolution") % author_name,
                items=items,
            )
            self.message_notify(
                partner_ids=[recipient.partner_id.id],
                subject=subject,
                body=body,
                email_layout_xmlid="mail.mail_notification_light",
            )
        return True

    def action_open_escalate_wizard(self):
        """Open the 2nd Level Escalation Wizard."""
        self.ensure_one()
        return {
            "name": _("Escalate to 2nd Level Work Unit"),
            "type": "ir.actions.act_window",
            "res_model": "helpdesk.ticket.escalate.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_ticket_id": self.id,
                "default_escalation_target_level": "level_2",
            },
        }

    def action_open_escalate_level_3_wizard(self):
        """Open the 3rd Level Escalation Wizard."""
        self.ensure_one()
        return {
            "name": _("Escalate to 3rd Level Executive / Vendor Unit"),
            "type": "ir.actions.act_window",
            "res_model": "helpdesk.ticket.escalate.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_ticket_id": self.id,
                "default_escalation_target_level": "level_3",
            },
        }

    # ── Automatic Hierarchical SLA-Based Escalation ───────────────────────────
    def _get_next_escalation_manager(self):
        """
        Traverse the organizational reporting hierarchy to identify the next manager
        eligible for SLA escalation, progressing up to the CEO level.
        Returns:
            tuple: (manager_user: res.users or False, is_ceo: bool)
        """
        self.ensure_one()
        if self.is_ceo_escalated:
            return False, True

        params = self.env["ir.config_parameter"].sudo()
        ceo_param = params.get_param("bunna_helpdesk.ceo_user_id")
        ceo_user = False
        if ceo_param and str(ceo_param).isdigit():
            ceo_user = self.env["res.users"].sudo().browse(int(ceo_param))
            if not ceo_user.exists() or not ceo_user.active:
                ceo_user = False

        # Current assignee or team lead
        current_user = self.user_id
        if not current_user and self.team_id and self.team_id.user_id:
            current_user = self.team_id.user_id

        emp_obj = self.env["hr.employee"].sudo()
        current_emp = False
        if current_user:
            current_emp = emp_obj.search([("user_id", "=", current_user.id)], limit=1)

        visited_emps = set()
        if current_emp:
            visited_emps.add(current_emp.id)

        next_user = False
        is_ceo = False

        curr = current_emp
        while curr and curr.parent_id:
            parent = curr.parent_id
            if parent.id in visited_emps:
                _logger.warning("Circular reporting detected in employee hierarchy for %s (id: %s)", curr.name, curr.id)
                break
            visited_emps.add(parent.id)

            if parent.active and parent.user_id and parent.user_id.active and parent.user_id != current_user:
                next_user = parent.user_id
                # Check if this parent is CEO
                if ceo_user and parent.user_id == ceo_user:
                    is_ceo = True
                elif not parent.parent_id:
                    # Top of employee organizational hierarchy
                    is_ceo = True
                break
            curr = parent

        # Fallback to CEO if no intermediate manager found
        if not next_user and ceo_user and current_user != ceo_user:
            next_user = ceo_user
            is_ceo = True

        return next_user, is_ceo

    def _escalate_ticket_sla(self, reason=None):
        """
        Execute automatic hierarchical SLA escalation:
        Reassigns ticket to next manager up to CEO, updates target SLA deadline,
        resets SLA status to in_progress, records audit trail, and notifies assignee.
        """
        self.ensure_one()
        if self.closed or (self.stage_id and self.stage_id.closed):
            return False

        if self.is_ceo_escalated:
            _logger.info("Ticket %s is already escalated to CEO level. Skipping further escalation.", self.number)
            return False

        next_manager, is_ceo = self._get_next_escalation_manager()
        if not next_manager:
            _logger.warning("No escalation manager found for ticket %s (current user: %s).", self.number, self.user_id.name if self.user_id else "None")
            return False

        prev_user = self.user_id
        new_level = (self.escalation_level or 0) + 1
        now = fields.Datetime.now()
        breached_deadline = self.sla_deadline or now

        # Determine next SLA target duration from applicable SLA policy
        applicable_slas = self.team_id.sla_ids.filtered(lambda s: s._is_applicable(self)) if self.team_id else False
        next_deadline = False
        if applicable_slas:
            sla_policy = applicable_slas[0]
            next_deadline = sla_policy._get_deadline(now)
        else:
            from datetime import timedelta
            # Default to service SDT hours or 24 hours
            hours = self.service_id.default_sdt_hours if self.service_id and self.service_id.default_sdt_hours else 24.0
            next_deadline = now + timedelta(hours=hours)

        vals = {
            "user_id": next_manager.id,
            "escalation_level": new_level,
            "last_escalation_date": now,
            "sla_deadline": next_deadline,
            "sla_status": "in_progress",
            "is_escalated": True,
            "is_ceo_escalated": is_ceo,
        }
        self.write(vals)

        # Record audit history
        self.env["helpdesk.ticket.escalation.history"].sudo().create({
            "ticket_id": self.id,
            "escalation_level": new_level,
            "previous_user_id": prev_user.id if prev_user else False,
            "new_user_id": next_manager.id,
            "escalation_datetime": now,
            "sla_deadline": breached_deadline,
            "new_sla_deadline": next_deadline,
            "is_ceo_level": is_ceo,
            "reason": reason or _("Automatic hierarchical escalation due to SLA deadline breach."),
        })

        # Post rich message in Chatter
        level_label = _("CEO / Executive Authority Level") if is_ceo else _("Level %d") % new_level
        chatter_msg = (
            f"<div><strong>🚨 SLA Breached &amp; Automatically Escalated ({level_label})</strong><br/>"
            f"• <strong>Previous Assignee:</strong> {prev_user.name if prev_user else _('Unassigned')}<br/>"
            f"• <strong>New Assignee (Manager):</strong> {next_manager.name}<br/>"
            f"• <strong>Escalation Time:</strong> {now.strftime('%Y-%m-%d %H:%M:%S')}<br/>"
            f"• <strong>Breached SLA Deadline:</strong> {breached_deadline.strftime('%Y-%m-%d %H:%M:%S') if breached_deadline else 'N/A'}<br/>"
            f"• <strong>New Target Deadline:</strong> {next_deadline.strftime('%Y-%m-%d %H:%M:%S') if next_deadline else 'N/A'}</div>"
        )
        self.message_post(body=chatter_msg, subtype_xmlid="mail.mt_note")

        # Notify the newly assigned manager
        if next_manager.partner_id:
            subject = _("⚠️ Escalation (%s): Ticket %s Assigned to You") % (level_label, self.display_name)
            items = [
                (_("Ticket"), f'&quot;{self.display_name}&quot;'),
                (_("Escalation Level"), level_label),
                (_("Previous Assignee"), prev_user.name if prev_user else _("Unassigned")),
                (_("New SLA Deadline"), str(next_deadline)),
                (_("Service"), self.service_id.name if self.service_id else _("General")),
            ]
            body = self._format_ticket_notification_body(
                recipient_name=next_manager.name,
                action_statement=_("Ticket %s has breached SLA and has been escalated to you for management resolution") % self.number,
                items=items,
            )
            self.message_notify(
                partner_ids=[next_manager.partner_id.id],
                subject=subject,
                body=body,
                email_layout_xmlid="mail.mail_notification_light",
            )
        return True

    @api.model
    def _cron_evaluate_sla_escalation(self):
        """
        Scheduled action: scan open tickets that have breached SLA deadline
        and automatically escalate them up the organizational reporting hierarchy.
        """
        now = fields.Datetime.now()
        domain = [
            ("closed", "=", False),
            ("sla_deadline", "<", now),
            ("is_ceo_escalated", "=", False),
        ]
        breached_tickets = self.search(domain)
        _logger.info("Evaluating SLA escalations: found %d candidate tickets.", len(breached_tickets))
        count = 0
        for ticket in breached_tickets:
            # Re-check closed status on stage
            if ticket.stage_id and ticket.stage_id.closed:
                continue
            try:
                ticket._escalate_ticket_sla()
                count += 1
            except Exception as e:
                _logger.error("Failed to escalate ticket %s (id %s): %s", ticket.number, ticket.id, e)
        return count


    # ── Auto-assignment ───────────────────────────────────────────────────────

    @api.model
    def default_get(self, flds):
        defaults = super().default_get(flds)
        company_id = defaults.get("company_id") or self.env.company.id
        if "user_id" in flds and not defaults.get("user_id"):
            company = self.env["res.company"].browse(company_id)
            team_id = defaults.get("team_id")
            if team_id:
                team = self.env["helpdesk.ticket.team"].browse(team_id)
                if team.assignment_method == "manual":
                    # Legacy: auto-assign to creator if company toggle is on
                    if company.helpdesk_mgmt_ticket_auto_assign and self.env.user in team.user_ids:
                        defaults["user_id"] = self.env.user.id
                else:
                    next_user = team._get_next_user()
                    if next_user:
                        defaults["user_id"] = next_user.id
            else:
                if company.helpdesk_mgmt_ticket_auto_assign:
                    defaults["user_id"] = self.env.user.id

        if "case_type_id" in flds and not defaults.get("case_type_id"):
            default_case_code = self.env.context.get("default_case_type") or "inquiry"
            case_type = self.env["helpdesk.ticket.case.type"].search([("code", "=", default_case_code)], limit=1)
            if not case_type:
                case_type = self.env["helpdesk.ticket.case.type"].search([], limit=1)
            if case_type:
                defaults["case_type_id"] = case_type.id
                if "priority" in flds and not defaults.get("priority") and case_type.default_priority:
                    defaults["priority"] = case_type.default_priority

        if "customer_type_id" in flds and not defaults.get("customer_type_id"):
            default_cust_code = self.env.context.get("default_customer_type") or "external_existing"
            cust_type = self.env["helpdesk.ticket.customer.type"].search([("code", "=", default_cust_code)], limit=1)
            if not cust_type:
                cust_type = self.env["helpdesk.ticket.customer.type"].search([], limit=1)
            if cust_type:
                defaults["customer_type_id"] = cust_type.id

        return defaults

    @api.depends("name")
    def _compute_display_name(self):
        for ticket in self:
            ticket.display_name = f"{ticket.number} - {ticket.name}"

    def assign_to_me(self):
        self.write({"user_id": self.env.user.id})

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        if self.partner_id:
            self.partner_name = self.partner_id.name
            self.partner_email = self.partner_id.email

    # ── SLA helpers ───────────────────────────────────────────────────────────

    def _sla_apply(self):
        """Compute and attach/update SLA statuses for each ticket."""
        for ticket in self:
            team = ticket.team_id
            if not team:
                continue
            applicable_slas = team.sla_ids.filtered(
                lambda s: s._is_applicable(ticket)
            )
            existing = {s.sla_id: s for s in ticket.sla_status_ids}
            vals_list = []
            for sla in applicable_slas:
                deadline = sla._get_deadline(
                    ticket.assigned_date or ticket.create_date or fields.Datetime.now()
                )
                if sla in existing:
                    status = existing[sla]
                    if not status.reached_datetime:
                        status.deadline = deadline
                else:
                    vals_list.append({
                        "ticket_id": ticket.id,
                        "sla_id": sla.id,
                        "deadline": deadline,
                    })
            # Archive statuses for SLAs no longer applicable
            for sla, status in existing.items():
                if sla not in applicable_slas:
                    status.unlink()
            if vals_list:
                self.env["helpdesk.sla.status"].create(vals_list)

    def _sla_mark_reached(self, stage_id):
        """Mark SLA statuses as reached when their target stage is met."""
        now = fields.Datetime.now()
        for ticket in self:
            for status in ticket.sla_status_ids.filtered(
                lambda s: s.sla_id.stage_id.id == stage_id and not s.reached_datetime
            ):
                status.reached_datetime = now

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def _creation_subtype(self):
        return self.env.ref("bunna_helpdesk.hlp_tck_created")

    @api.model_create_multi
    def create(self, vals_list):
        default_team_param = self.env["ir.config_parameter"].sudo().get_param("bunna_helpdesk.default_team_id")
        for vals in vals_list:
            # Operation routing: All cases/operations strictly route to their assigned team
            if vals.get("operation_id"):
                op = self.env["helpdesk.team.operation"].browse(vals["operation_id"])
                if op.team_id:
                    vals["team_id"] = op.team_id.id
                if op.default_priority and not vals.get("priority"):
                    vals["priority"] = op.default_priority
                if op.case_type_id and not vals.get("case_type_id"):
                    vals["case_type_id"] = op.case_type_id.id
                if op.service_id and not vals.get("service_id"):
                    vals["service_id"] = op.service_id.id
                    if op.service_id.family_id and not vals.get("service_family_id"):
                        vals["service_family_id"] = op.service_id.family_id.id
                if op.service_sub_category_id and not vals.get("service_sub_category_id"):
                    vals["service_sub_category_id"] = op.service_sub_category_id.id

            if not vals.get("team_id") and default_team_param and str(default_team_param).isdigit():
                vals["team_id"] = int(default_team_param)
            if vals.get("number", "/") == "/":
                vals["number"] = self._prepare_ticket_number(vals)
            # Automatic ticket title generation if name is omitted or default
            if not vals.get("name") or vals.get("name") in ("/", "New", "New Ticket", False):
                vals["name"] = vals.get("number") or "/"
            if vals.get("user_id") and not vals.get("assigned_date"):
                vals["assigned_date"] = fields.Datetime.now()
            if vals.get("team_id"):
                team = self.env["helpdesk.ticket.team"].browse([vals["team_id"]])
                if team.company_id:
                    vals["company_id"] = team.company_id.id
                if "stage_id" not in vals:
                    vals["stage_id"] = team._get_applicable_stages()[:1].id
                # Round-robin / load-balanced on create (if not already set)
                if not vals.get("user_id") and team.assignment_method != "manual":
                    next_user = team._get_next_user()
                    if next_user:
                        vals["user_id"] = next_user.id
                        if not vals.get("assigned_date"):
                            vals["assigned_date"] = fields.Datetime.now()
            if self.env.context.get("fetchmail_cron_running") and not vals.get("channel_id"):
                channel_email_id = self.env.ref(
                    "bunna_helpdesk.helpdesk_ticket_channel_email",
                    raise_if_not_found=False,
                )
                if channel_email_id:
                    vals["channel_id"] = channel_email_id.id
        tickets = super().create(vals_list)
        tickets._sla_apply()
        for ticket in tickets:
            if not ticket.name or ticket.name in ("/", "New", ticket.number):
                ticket.name = ticket._generate_ticket_title()
            if ticket.team_id:
                ticket._notify_ticket_created_team(reassigned=False)
            if ticket.user_id:
                ticket._notify_ticket_assigned()
            if ticket.priority in ("2", "3"):
                ticket._notify_ticket_urgent()
        return tickets

    def copy(self, default=None):
        self.ensure_one()
        if default is None:
            default = {}
        if "number" not in default:
            default["number"] = self._prepare_ticket_number(default)
        res = super().copy(default)
        return res

    def write(self, vals):
        now = fields.Datetime.now()
        if "name" in vals and (not vals["name"] or vals["name"] in ("/", "New")):
            vals.pop("name")
        # Route team if operation is changed
        if "operation_id" in vals and vals.get("operation_id"):
            op = self.env["helpdesk.team.operation"].browse(vals["operation_id"])
            if op.team_id:
                vals["team_id"] = op.team_id.id

        stage_changed = "stage_id" in vals
        user_changed = "user_id" in vals
        prio_changed = "priority" in vals
        team_changed = "team_id" in vals
        old_data = {}
        if stage_changed or user_changed or prio_changed or team_changed:
            old_data = {
                t.id: {
                    "stage_id": t.stage_id,
                    "user_id": t.user_id,
                    "priority": t.priority,
                    "team_id": t.team_id,
                }
                for t in self
            }

        for _ticket in self:
            if vals.get("stage_id"):
                stage = self.env["helpdesk.ticket.stage"].browse([vals["stage_id"]])
                vals["last_stage_update"] = now
                if stage.closed:
                    vals["closed_date"] = now
            if vals.get("user_id"):
                vals["assigned_date"] = now

        res = super().write(vals)

        if any(k in vals for k in ("service_id", "service_sub_category_id", "service_family_id", "partner_id", "account_number")):
            self._update_ticket_title_if_auto()

        # SLA: re-apply when team/priority/tags change
        if any(k in vals for k in ("team_id", "priority", "tag_ids")):
            self._sla_apply()

        # SLA: mark reached when stage changes
        if stage_changed and vals.get("stage_id"):
            self._sla_mark_reached(vals["stage_id"])

        # Rating: send survey when ticket is closed and team uses ratings
        if stage_changed and vals.get("stage_id"):
            stage = self.env["helpdesk.ticket.stage"].browse(vals["stage_id"])
            if stage.closed:
                for ticket in self:
                    if (
                        ticket.team_id.use_rating
                        and ticket.team_id.rating_template_id
                        and ticket.partner_id
                    ):
                        ticket.team_id.rating_template_id.send_mail(
                            ticket.id, force_send=True
                        )

        # ── Notifications for Discuss / Chatter ──────────────────────────────
        for ticket in self:
            old = old_data.get(ticket.id, {})

            # 1. Assignment notification
            if user_changed:
                old_user = old.get("user_id")
                if ticket.user_id and ticket.user_id != old_user:
                    ticket._notify_ticket_assigned(previous_user=old_user)

            # 2. Team reassignment notification
            if team_changed:
                old_team = old.get("team_id")
                if ticket.team_id and ticket.team_id != old_team:
                    ticket._notify_ticket_created_team(reassigned=True, previous_team=old_team)

            # 3. Stage change / resolution notification
            if stage_changed:
                old_stage = old.get("stage_id")
                new_stage = ticket.stage_id
                if new_stage and old_stage != new_stage:
                    if new_stage.closed and (not old_stage or not old_stage.closed):
                        ticket._notify_ticket_resolved(new_stage)
                    elif old_stage and old_stage.closed and not new_stage.closed:
                        ticket._notify_ticket_reopened(new_stage)

            # 4. Priority escalation
            if prio_changed and vals.get("priority") in ("2", "3"):
                old_prio = old.get("priority")
                if old_prio != ticket.priority:
                    ticket._notify_ticket_urgent()

        return res

    def action_duplicate_tickets(self):
        for ticket in self.browse(self.env.context["active_ids"]):
            ticket.copy()

    def _prepare_ticket_number(self, values):
        seq = self.env["ir.sequence"]
        if "company_id" in values:
            seq = seq.with_company(values["company_id"])
        return seq.next_by_code("helpdesk.ticket.sequence") or "/"

    def _compute_access_url(self):
        res = super()._compute_access_url()
        for item in self:
            item.access_url = f"/my/ticket/{item.id}"
        return res

    # ── Mail gateway ──────────────────────────────────────────────────────────

    def _track_template(self, tracking):
        res = super()._track_template(tracking)
        ticket = self[0]
        if "stage_id" in tracking and ticket.stage_id.mail_template_id:
            res["stage_id"] = (
                ticket.stage_id.mail_template_id,
                {
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
        ticket = super().message_new(msg, custom_values=defaults)
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

    def _message_get_suggested_recipients(self, **kwargs):
        recipients = super()._message_get_suggested_recipients(**kwargs)
        try:
            for ticket in self:
                if ticket.partner_id:
                    if not any(r.get("partner_id") == ticket.partner_id.id for r in recipients):
                        recipients.append({
                            "name": ticket.partner_id.name,
                            "email": ticket.partner_id.email_normalized or ticket.partner_id.email,
                            "partner_id": ticket.partner_id.id,
                            "reason": self.env._("Customer"),
                            "create_values": {},
                        })
                elif ticket.partner_email:
                    if not any(r.get("email") == ticket.partner_email for r in recipients):
                        recipients.append({
                            "name": ticket.partner_name or ticket.partner_email,
                            "email": ticket.partner_email,
                            "partner_id": False,
                            "reason": self.env._("Customer Email"),
                            "create_values": {},
                        })
        except AccessError:
            return recipients
        return recipients

    def _notify_get_reply_to(self, default=None, author_id=False):
        """Override to set alias of tasks to their team if any."""
        aliases = self.sudo().mapped("team_id")._notify_get_reply_to(default=default, author_id=author_id)
        res = {ticket.id: aliases.get(ticket.team_id.id) for ticket in self}
        leftover = self.filtered(lambda rec: not rec.team_id)
        if leftover:
            res.update(
                super(HelpdeskTicket, leftover)._notify_get_reply_to(default=default, author_id=author_id)
            )
        return res

    # ── Rating mixin override ─────────────────────────────────────────────────

    def rating_get_partner_id(self):
        """Return the partner to whom the rating request is sent."""
        return self.partner_id or super().rating_get_partner_id()

    def rating_get_access_url(self, rating=None):
        self.ensure_one()
        try:
            token = self._rating_get_access_token(self.partner_id)
            return f"{self.get_base_url()}/rate/{token}/5"
        except Exception:
            return f"{self.get_base_url()}/my/ticket/{self.id}"

    # ── Discuss & Chatter Notifications ───────────────────────────────────────

    def _format_ticket_notification_body(
        self,
        recipient_name,
        action_statement,
        items=None,
    ):
        """Format ticket notification cleanly matching native Odoo notification/activity style."""
        self.ensure_one()
        bullets = []
        if items:
            for label, val in items:
                if not val:
                    continue
                bullets.append(f"<li><strong>{label}:</strong> {val}</li>")
        bullets_html = f"<ul>{''.join(bullets)}</ul>" if bullets else ""
        return (
            f"<p>{_('Dear')} {recipient_name},</p>"
            f"<p>{action_statement}:</p>"
            f"{bullets_html}"
        )

    def _notify_ticket_created_team(self, reassigned=False, previous_team=None):
        """Notify team leader and members when a ticket arrives or is assigned to a team."""
        notify_enabled = self.env["ir.config_parameter"].sudo().get_param(
            "bunna_helpdesk.notify_team_members", "True"
        )
        if notify_enabled not in (True, "True", "true", "1", 1):
            return

        for ticket in self:
            team = ticket.team_id
            if not team:
                continue

            recipient_users = self.env["res.users"]
            if team.user_ids:
                recipient_users |= team.user_ids
            if team.user_id:
                recipient_users |= team.user_id

            if not recipient_users:
                continue

            recipient_partners = recipient_users.mapped("partner_id")
            if not recipient_partners:
                continue

            # 1. Subscribe team members as followers of the ticket
            ticket.message_subscribe(partner_ids=recipient_partners.ids)

            channel_label = dict(ticket._fields["channel_type"].selection).get(
                ticket.channel_type, ticket.channel_type or "General"
            )
            customer_str = ticket.partner_name or (ticket.partner_id.name if ticket.partner_id else _("Customer"))
            phone_str = ticket.partner_phone or (ticket.partner_id.phone if ticket.partner_id else "")
            account_str = ticket.account_number or ""
            prio_label = dict(ticket._fields["priority"].selection).get(ticket.priority, ticket.priority)
            author_name = self.env.user.name or _("System")

            cust_display = f"{customer_str} ({phone_str})" if phone_str else customer_str
            account_display = f"{account_str}" if account_str else ""
            if ticket.cif_number:
                account_display = f"{account_str} (CIF: {ticket.cif_number})" if account_str else f"CIF: {ticket.cif_number}"

            items = [
                (_("Document"), f'&quot;{ticket.display_name}&quot; ({_("Helpdesk Ticket")})'),
                (_("Team"), team.name),
                (_("Customer"), cust_display),
            ]
            if account_display:
                items.append((_("Account No"), account_display))
            items.append((_("Channel"), channel_label))
            items.append((_("Priority"), prio_label))
            if ticket.stage_id:
                items.append((_("Stage"), ticket.stage_id.name))

            if reassigned:
                subject = _('"%s: Ticket Reassigned" assigned to your team') % ticket.display_name
                action_stmt = _("%s has just reassigned the following ticket to your team") % author_name
            else:
                subject = _('"%s: New Ticket" assigned to your team') % ticket.display_name
                action_stmt = _("%s has just assigned a new ticket to your team") % author_name

            body = ticket._format_ticket_notification_body(
                recipient_name=_("Team Member"),
                action_statement=action_stmt,
                items=items,
            )

            # 2. Send Discuss inbox notification & email
            ticket.message_notify(
                partner_ids=recipient_partners.ids,
                subject=subject,
                body=body,
                email_layout_xmlid="mail.mail_notification_light",
            )

            # 3. Real-time toast alert to active web client sessions
            toast_title = _("New Ticket: %s") % ticket.number
            toast_msg = _("[%s] %s for team %s") % (channel_label, customer_str, team.name)
            for partner in recipient_partners:
                try:
                    self.env["bus.bus"]._sendone(
                        partner,
                        "simple_notification",
                        {
                            "type": "info",
                            "title": toast_title,
                            "message": toast_msg,
                            "sticky": False,
                        },
                    )
                except Exception as e:
                    _logger.debug("Bus notification failed: %s", str(e))

            # 4. Schedule Activity for the assigned user, team leader, or first member
            target_user = ticket.user_id or team.user_id or (team.user_ids[:1] if team.user_ids else False)
            if target_user:
                try:
                    ticket.activity_schedule(
                        "mail.mail_activity_data_todo",
                        user_id=target_user.id,
                        summary=_("New Ticket: %s") % ticket.number,
                        note=_("Incoming %s ticket from %s (%s).") % (
                            channel_label, customer_str, phone_str
                        ),
                    )
                except Exception as act_err:
                    _logger.debug("Activity scheduling error: %s", str(act_err))

    def _notify_ticket_assigned(self, previous_user=None):
        """Send Discuss inbox notification when ticket is assigned to a user."""
        for ticket in self:
            if not ticket.user_id or not ticket.user_id.partner_id:
                continue
            recipient = ticket.user_id.partner_id
            ticket.message_subscribe(partner_ids=[recipient.id])

            author_name = self.env.user.name or _("System")
            subject = _('"%s: Ticket Assignment" assigned to you') % ticket.display_name
            prio_label = dict(ticket._fields["priority"].selection).get(ticket.priority, ticket.priority)

            items = [
                (_("Document"), f'&quot;{ticket.display_name}&quot; ({_("Helpdesk Ticket")})'),
                (_("Team"), ticket.team_id.name if ticket.team_id else _("General")),
            ]
            if ticket.partner_id or ticket.partner_name:
                cust = ticket.partner_name or ticket.partner_id.name
                items.append((_("Customer"), cust))
            if ticket.account_number:
                items.append((_("Account No"), ticket.account_number))
            items.append((_("Priority"), prio_label))
            if ticket.stage_id:
                items.append((_("Stage"), ticket.stage_id.name))

            body = ticket._format_ticket_notification_body(
                recipient_name=ticket.user_id.name,
                action_statement=_("%s has just assigned you the following ticket") % author_name,
                items=items,
            )
            ticket.message_notify(
                partner_ids=[recipient.id],
                subject=subject,
                body=body,
                email_layout_xmlid="mail.mail_notification_light",
            )
            if previous_user and previous_user != ticket.user_id and previous_user.partner_id:
                prev_partner = previous_user.partner_id
                prev_subject = _('"%s" reassigned') % ticket.display_name
                prev_items = [
                    (_("Document"), f'&quot;{ticket.display_name}&quot; ({_("Helpdesk Ticket")})'),
                    (_("Reassigned To"), ticket.user_id.name),
                    (_("Team"), ticket.team_id.name if ticket.team_id else _("General")),
                ]
                prev_body = ticket._format_ticket_notification_body(
                    recipient_name=previous_user.name,
                    action_statement=_("%s has reassigned the following ticket to %s") % (author_name, ticket.user_id.name),
                    items=prev_items,
                )
                ticket.message_notify(
                    partner_ids=[prev_partner.id],
                    subject=prev_subject,
                    body=prev_body,
                    email_layout_xmlid="mail.mail_notification_light",
                )

    def _notify_ticket_resolved(self, stage):
        """Send Discuss notification when ticket issue is resolved/closed."""
        for ticket in self:
            partners = set()
            if ticket.create_uid and ticket.create_uid.partner_id:
                partners.add(ticket.create_uid.partner_id)
            if ticket.partner_id:
                partners.add(ticket.partner_id)
            if ticket.user_id and ticket.user_id.partner_id:
                partners.add(ticket.user_id.partner_id)

            author_name = self.env.user.name or _("System")
            subject = _('"%s: Resolved"') % ticket.display_name
            items = [
                (_("Document"), f'&quot;{ticket.display_name}&quot; ({_("Helpdesk Ticket")})'),
                (_("Resolution Stage"), stage.name),
                (_("Resolved By"), ticket.user_id.name if ticket.user_id else _("Support Team")),
                (_("Team"), ticket.team_id.name if ticket.team_id else ""),
            ]
            for partner in partners:
                body = ticket._format_ticket_notification_body(
                    recipient_name=partner.name,
                    action_statement=_("%s has marked the following ticket as resolved") % author_name,
                    items=items,
                )
                ticket.message_notify(
                    partner_ids=[partner.id],
                    subject=subject,
                    body=body,
                    email_layout_xmlid="mail.mail_notification_light",
                )

    def _notify_ticket_reopened(self, stage):
        """Send Discuss notification when a resolved ticket is reopened."""
        for ticket in self:
            partners = set()
            if ticket.user_id and ticket.user_id.partner_id:
                partners.add(ticket.user_id.partner_id)
            if ticket.create_uid and ticket.create_uid.partner_id:
                partners.add(ticket.create_uid.partner_id)

            author_name = self.env.user.name or _("System")
            subject = _('"%s: Reopened"') % ticket.display_name
            items = [
                (_("Document"), f'&quot;{ticket.display_name}&quot; ({_("Helpdesk Ticket")})'),
                (_("Stage"), stage.name),
                (_("Responsible Agent"), ticket.user_id.name if ticket.user_id else _("Unassigned")),
                (_("Team"), ticket.team_id.name if ticket.team_id else ""),
            ]
            for partner in partners:
                body = ticket._format_ticket_notification_body(
                    recipient_name=partner.name,
                    action_statement=_("%s has reopened the following ticket") % author_name,
                    items=items,
                )
                ticket.message_notify(
                    partner_ids=[partner.id],
                    subject=subject,
                    body=body,
                    email_layout_xmlid="mail.mail_notification_light",
                )

    def _notify_ticket_urgent(self):
        """Send Discuss notification when ticket is escalated to High or Very High priority."""
        for ticket in self:
            partners = set()
            if ticket.user_id and ticket.user_id.partner_id:
                partners.add(ticket.user_id.partner_id)
            elif ticket.team_id and ticket.team_id.user_id and ticket.team_id.user_id.partner_id:
                partners.add(ticket.team_id.user_id.partner_id)
            elif ticket.team_id:
                for u in ticket.team_id.user_ids[:3]:
                    if u.partner_id:
                        partners.add(u.partner_id)

            prio_label = dict(ticket._fields["priority"].selection).get(ticket.priority, ticket.priority)
            subject = _('"%s: Urgent Priority Alert"') % ticket.display_name
            items = [
                (_("Document"), f'&quot;{ticket.display_name}&quot; ({_("Helpdesk Ticket")})'),
                (_("Priority"), prio_label),
                (_("Team"), ticket.team_id.name if ticket.team_id else ""),
                (_("Customer"), ticket.partner_name or (ticket.partner_id.name if ticket.partner_id else "")),
            ]
            for partner in partners:
                body = ticket._format_ticket_notification_body(
                    recipient_name=partner.name,
                    action_statement=_("Urgent Priority Alert: The following ticket requires immediate attention"),
                    items=items,
                )
                ticket.message_notify(
                    partner_ids=[partner.id],
                    subject=subject,
                    body=body,
                    email_layout_xmlid="mail.mail_notification_light",
                )

    def _notify_sla_failed(self, sla_name=None):
        """Send Discuss notification when ticket has breached its SLA policy."""
        for ticket in self:
            partners = set()
            if ticket.user_id and ticket.user_id.partner_id:
                partners.add(ticket.user_id.partner_id)
            if ticket.team_id and ticket.team_id.user_id and ticket.team_id.user_id.partner_id:
                partners.add(ticket.team_id.user_id.partner_id)

            subject = _('"%s: SLA Target Exceeded"') % ticket.display_name
            items = [
                (_("Document"), f'&quot;{ticket.display_name}&quot; ({_("Helpdesk Ticket")})'),
                (_("Breached Policy"), sla_name or _("Service Level Agreement")),
                (_("Stage"), ticket.stage_id.name if ticket.stage_id else ""),
                (_("Responsible Agent"), ticket.user_id.name if ticket.user_id else _("Unassigned")),
            ]
            for partner in partners:
                body = ticket._format_ticket_notification_body(
                    recipient_name=partner.name,
                    action_statement=_("SLA Target Exceeded: The following ticket has breached its resolution deadline"),
                    items=items,
                )
                ticket.message_notify(
                    partner_ids=[partner.id],
                    subject=subject,
                    body=body,
                    email_layout_xmlid="mail.mail_notification_light",
                )

    # ── Cron actions ──────────────────────────────────────────────────────────

    @api.model
    def _cron_auto_close_tickets(self):
        """Close tickets that have been inactive longer than the configured threshold."""
        companies = self.env["res.company"].search(
            [("helpdesk_mgmt_auto_close_active", "=", True)]
        )
        for company in companies:
            days = company.helpdesk_mgmt_auto_close_days or 30
            close_stage = company.helpdesk_mgmt_auto_close_stage_id
            if not close_stage:
                continue
            cutoff = fields.Datetime.now() - __import__("datetime").timedelta(days=days)
            stale_tickets = self.search(
                [
                    ("company_id", "=", company.id),
                    ("closed", "=", False),
                    ("last_stage_update", "<", cutoff),
                ]
            )
            if stale_tickets:
                stale_tickets.write({"stage_id": close_stage.id})
                stale_tickets._message_log_batch(
                    bodies={
                        t.id: (
                            self.env._("Ticket automatically closed due to inactivity.")
                        )
                        for t in stale_tickets
                    }
                )

    # ── Bunna SMS Notifications (Acceptance & Done) ───────────────────────────

    def _get_customer_sms_phone(self):
        """Extract recipient phone number from ticket or partner profile."""
        self.ensure_one()
        phone = (
            self.partner_phone
            or (self.partner_id and getattr(self.partner_id, "phone", False))
            or (self.partner_id and getattr(self.partner_id, "mobile", False))
        )
        if phone:
            phone_str = str(phone).strip()
            if "/" in phone_str:
                phone_str = phone_str.split("/")[0].strip()
            if "," in phone_str:
                phone_str = phone_str.split(",")[0].strip()
            return phone_str
        return False

    def _dispatch_bunna_sms(self, phone, body, sms_type="acceptance"):
        """Dispatches SMS, records chatter entry, and creates sms.sms history."""
        self.ensure_one()
        # Create SMS record in sms.sms
        sms_record = self.env["sms.sms"].create({
            "number": phone,
            "body": body,
            "partner_id": self.partner_id.id if self.partner_id else False,
        })
        try:
            sms_record.send()
        except Exception as e:
            _logger.warning("Bunna SMS gateway dispatch notification: %s", e)

        # Style Chatter post with Bunna Bank branding
        is_acc = sms_type == "acceptance"
        theme_color = "#541718" if is_acc else "#198754"
        badge_bg = "#c17540" if is_acc else "#198754"
        title_text = "Acceptance SMS Dispatched" if is_acc else "Done / Resolution SMS Dispatched"
        badge_text = "ACCEPTED" if is_acc else "DONE / RESOLVED"
        icon = "fa-mobile" if is_acc else "fa-check-circle"

        chatter_body = f"""
        <div style="border-left: 4px solid {theme_color}; background-color: #fafaf9; border: 1px solid #e7e5e4; border-radius: 6px; padding: 12px 16px; margin: 6px 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                <span style="color: {theme_color}; font-weight: bold; font-size: 13px;">
                    <i class="fa {icon}"></i> 📱 {title_text}
                </span>
                <span style="background-color: {badge_bg}; color: #ffffff; padding: 2px 8px; border-radius: 3px; font-size: 10px; font-weight: bold; letter-spacing: 0.5px;">
                    {badge_text}
                </span>
            </div>
            <div style="font-size: 13px; color: #1D2B32; line-height: 1.5; margin-bottom: 8px; background: #ffffff; padding: 8px 12px; border-radius: 4px; border: 1px solid #e2e8f0;">
                "{body}"
            </div>
            <div style="font-size: 11px; color: #78716c; border-top: 1px solid #e7e5e4; padding-top: 4px; display: flex; justify-content: space-between;">
                <span><strong>Recipient:</strong> {phone}</span>
                <span><strong>Sender:</strong> Bunna Bank Contact Center (8501)</span>
            </div>
        </div>
        """
        self.message_post(body=chatter_body, message_type="comment", subtype_xmlid="mail.mt_comment")

    def action_send_acceptance_sms(self):
        """Send ticket acceptance / registration SMS notification to the customer."""
        last_phone = None
        for ticket in self:
            phone = ticket._get_customer_sms_phone()
            if not phone:
                raise UserError(
                    _("No customer phone number found for Ticket %s!\n\nPlease enter a phone number in the customer profile or 'Partner Phone' field before sending SMS.")
                    % ticket.number
                )
            last_phone = phone

            team_name = ticket.team_id.name if ticket.team_id else "Bunna Bank Support"
            cust_name = ticket.partner_id.name if ticket.partner_id else "Valued Customer"
            ticket_ref = ticket.number or "HT00000"
            ticket_subject = ticket.name or "Support Request"

            template_param = self.env["ir.config_parameter"].sudo().get_param(
                "bunna_helpdesk.bunna_sms_acceptance_template"
            )
            if not template_param:
                template_param = (
                    "Dear {partner_name}, your Bunna Bank request {number} ('{name}') has been accepted "
                    "by {team_name}. We are working to resolve it. Inquiries: 8501. Bunna Bank S.C."
                )

            body = template_param.format(
                partner_name=cust_name,
                number=ticket_ref,
                name=ticket_subject,
                team_name=team_name,
                bank_hotline="8501",
            )

            # Auto-advance stage to In Progress if currently New
            in_progress_stage = self.env["helpdesk.ticket.stage"].search(
                [("name", "ilike", "In Progress")], limit=1
            )
            new_stage = self.env["helpdesk.ticket.stage"].search(
                [("name", "ilike", "New")], limit=1
            )
            if in_progress_stage and (ticket.stage_id == new_stage or not ticket.stage_id):
                ticket.write({"stage_id": in_progress_stage.id})

            ticket._dispatch_bunna_sms(phone, body, sms_type="acceptance")

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Acceptance SMS Sent"),
                "message": _("Acceptance notification SMS successfully sent to %(phone)s. Ticket updated to In Progress.", phone=last_phone),
                "type": "success",
                "sticky": False,
            },
        }

    def action_send_done_sms(self):
        """Send ticket completion / resolution SMS notification to the customer."""
        last_phone = None
        for ticket in self:
            phone = ticket._get_customer_sms_phone()
            if not phone:
                raise UserError(
                    _("No customer phone number found for Ticket %s!\n\nPlease enter a phone number in the customer profile or 'Partner Phone' field before sending SMS.")
                    % ticket.number
                )
            last_phone = phone

            cust_name = ticket.partner_id.name if ticket.partner_id else "Valued Customer"
            ticket_ref = ticket.number or "HT00000"
            ticket_subject = ticket.name or "Support Request"
            team_name = ticket.team_id.name if ticket.team_id else "Bunna Bank Support"

            template_param = self.env["ir.config_parameter"].sudo().get_param(
                "bunna_helpdesk.bunna_sms_done_template"
            )
            if not template_param:
                template_param = (
                    "Dear {partner_name}, your Bunna Bank ticket {number} ('{name}') has been successfully "
                    "resolved. Thank you for banking with Bunna Bank! Inquiries: 8501."
                )

            body = template_param.format(
                partner_name=cust_name,
                number=ticket_ref,
                name=ticket_subject,
                team_name=team_name,
                bank_hotline="8501",
            )

            # Auto-advance stage to Done if not closed
            done_stage = self.env["helpdesk.ticket.stage"].search(
                [("name", "ilike", "Done")], limit=1
            )
            if done_stage and ticket.stage_id != done_stage:
                ticket.write({
                    "stage_id": done_stage.id,
                    "closed": True,
                    "closed_date": fields.Datetime.now(),
                })

            ticket._dispatch_bunna_sms(phone, body, sms_type="done")

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Done SMS Sent"),
                "message": _("Done / Resolution notification SMS successfully sent to %(phone)s. Ticket marked as Done.", phone=last_phone),
                "type": "success",
                "sticky": False,
            },
        }

    def action_export_bunna_excel(self):
        """Export selected or active tickets to a high-definition Excel (.xlsx) file with official Bunna Bank branding."""
        import base64
        import io
        try:
            import xlsxwriter
        except ImportError:
            raise UserError(_("The 'xlsxwriter' Python library is required. Please install it on the server."))

        tickets = self
        if not tickets:
            active_ids = self.env.context.get("active_ids")
            if active_ids:
                tickets = self.browse(active_ids)
            else:
                active_id = self.env.context.get("active_id")
                if active_id:
                    tickets = self.browse([active_id])
                else:
                    tickets = self.search([], order="id desc", limit=1000)

        if not tickets:
            raise UserError(_("No helpdesk tickets selected for export."))

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {"in_memory": True})
        ws = wb.add_worksheet("Tickets Register")
        ws.set_tab_color("#541718")

        # Bunna Bank official branding styles (#541718 maroon, #c17540 gold)
        fmt_bank_title = wb.add_format({
            "bold": True, "font_size": 15, "font_color": "#FFFFFF", "bg_color": "#541718",
            "font_name": "Segoe UI", "align": "center", "valign": "vcenter"
        })
        fmt_hub_title = wb.add_format({
            "bold": True, "font_size": 11, "font_color": "#f3d7c5", "bg_color": "#3a0d0e",
            "font_name": "Segoe UI", "align": "center", "valign": "vcenter"
        })
        fmt_doc_title = wb.add_format({
            "bold": True, "font_size": 10, "font_color": "#FFFFFF", "bg_color": "#c17540",
            "font_name": "Segoe UI", "align": "center", "valign": "vcenter"
        })
        fmt_meta = wb.add_format({
            "font_size": 9, "font_name": "Segoe UI", "font_color": "#55626a",
            "valign": "vcenter", "italic": True
        })
        fmt_th = wb.add_format({
            "bold": True, "bg_color": "#541718", "font_color": "#FFFFFF",
            "font_size": 10, "font_name": "Segoe UI", "align": "center", "valign": "vcenter",
            "text_wrap": True, "border": 1, "border_color": "#3D1011"
        })
        fmt_cell = wb.add_format({
            "font_size": 9, "font_name": "Segoe UI", "valign": "vcenter",
            "border": 1, "border_color": "#E2E8F0"
        })
        fmt_cell_center = wb.add_format({
            "font_size": 9, "font_name": "Segoe UI", "valign": "vcenter", "align": "center",
            "border": 1, "border_color": "#E2E8F0"
        })
        fmt_cell_bold = wb.add_format({
            "bold": True, "font_size": 9, "font_name": "Segoe UI", "valign": "vcenter",
            "font_color": "#541718", "border": 1, "border_color": "#E2E8F0"
        })
        fmt_tot = wb.add_format({
            "bold": True, "bg_color": "#541718", "font_color": "#FFFFFF",
            "font_size": 10, "font_name": "Segoe UI", "align": "left", "valign": "vcenter",
            "border": 1, "border_color": "#3D1011"
        })

        # Corporate Header Banner (Merged 16 columns)
        last_col = 14
        ws.set_row(0, 30)
        ws.set_row(1, 20)
        ws.set_row(2, 20)
        ws.set_row(4, 24)

        ws.merge_range(0, 0, 0, last_col, "BUNNA BANK S.C.", fmt_bank_title)
        ws.merge_range(1, 0, 1, last_col, "Customer Care & Contact Center Service Hub", fmt_hub_title)
        ws.merge_range(2, 0, 2, last_col, "Helpdesk Tickets Performance & Register Export", fmt_doc_title)

        now_str = fields.Datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        user_name = self.env.user.name or "Administrator"
        ws.write(3, 0, f"Generated: {now_str}  |  Exported By: {user_name}  |  Total Tickets: {len(tickets)}", fmt_meta)

        headers = [
            "Ticket #", "Subject", "Customer / Branch", "Customer Type",
            "Account / CIF", "Case Type", "Service Family", "Service", "Assigned Team",
            "Assigned Agent", "Priority", "Channel", "Stage", "SLA Status", "Created Date"
        ]
        for ci, h in enumerate(headers):
            ws.write(4, ci, h, fmt_th)

        prio_map = {"0": "Low", "1": "Medium", "2": "High", "3": "Urgent"}

        row_idx = 5
        for t in tickets:
            prio_label = prio_map.get(t.priority, t.priority or "")
            cif_acc = t.account_number or t.cif_number or ""
            sla_map = {"failed": "Breached", "reached": "Met / On-time", "in_progress": "Ongoing"}
            sla_text = sla_map.get(t.sla_status, "Ongoing")
            if t.sla_deadline and t.sla_deadline < fields.Datetime.now() and not t.closed:
                sla_text = "Breached"

            ws.write(row_idx, 0, t.number or "", fmt_cell_bold)
            ws.write(row_idx, 1, t.name or "", fmt_cell)
            ws.write(row_idx, 2, t.partner_id.name or "", fmt_cell)
            ws.write(row_idx, 3, t.customer_type_id.name or "", fmt_cell_center)
            ws.write(row_idx, 4, cif_acc, fmt_cell_center)
            ws.write(row_idx, 5, t.case_type_id.name or "", fmt_cell)
            ws.write(row_idx, 6, t.service_family_id.name or t.category_id.name or "", fmt_cell)
            ws.write(row_idx, 7, t.service_id.name or "", fmt_cell)
            ws.write(row_idx, 8, t.team_id.name or "", fmt_cell)
            ws.write(row_idx, 9, t.user_id.name or "Unassigned", fmt_cell)
            ws.write(row_idx, 10, prio_label, fmt_cell_center)
            ws.write(row_idx, 11, t.channel_id.name or "", fmt_cell_center)
            ws.write(row_idx, 12, t.stage_id.name or "", fmt_cell_center)
            ws.write(row_idx, 13, sla_text, fmt_cell_center)
            ws.write(row_idx, 14, str(t.create_date or "")[:19], fmt_cell_center)
            row_idx += 1

        # Summary total row
        ws.set_row(row_idx, 22)
        ws.merge_range(row_idx, 0, row_idx, 2, f"Total Tickets Exported: {len(tickets)}", fmt_tot)
        for ci in range(3, last_col + 1):
            ws.write(row_idx, ci, "", fmt_tot)

        # Set clean column widths
        col_widths = [14, 32, 24, 18, 18, 18, 20, 20, 22, 18, 12, 16, 16, 16, 20]
        for ci, w in enumerate(col_widths):
            ws.set_column(ci, ci, w)
            ws.set_column(ci, ci, w)

        ws.freeze_panes(5, 3)

        wb.close()
        output.seek(0)
        file_data = output.getvalue()

        file_name = f"Bunna_Bank_Helpdesk_Tickets_{fields.Date.today()}.xlsx"
        attachment = self.env["ir.attachment"].create({
            "name": file_name,
            "type": "binary",
            "datas": base64.b64encode(file_data),
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        })
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

