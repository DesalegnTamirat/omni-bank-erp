import logging







import re







from datetime import datetime, timedelta







from odoo import _, api, fields, models, tools



from odoo.osv import expression







from odoo.exceptions import AccessError, UserError, ValidationError















_logger = logging.getLogger(__name__)























class HelpdeskTicket(models.Model):







    _name = "helpdesk.ticket"







    _description = "Helpdesk Ticket"







    _rec_name = "number"







    _rec_names_search = ["number", "name"]







    _order = "create_date desc, id desc"







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















    @api.depends("user_id", "user_id.is_on_leave", "user_id.leave_status_text")







    def _compute_user_is_on_leave(self):







        for ticket in self:







            if ticket.user_id and getattr(ticket.user_id, "is_on_leave", False):







                ticket.user_is_on_leave = True







                ticket.user_leave_status = ticket.user_id.leave_status_text or _("On Leave")







            else:







                ticket.user_is_on_leave = False







                ticket.user_leave_status = False















    def _search_user_is_on_leave(self, operator, value):







        users_on_leave = self.env["res.users"].search([("is_on_leave", "=", True)])







        is_true = (operator in ("=", "==") and value) or (operator in ("!=", "<>") and not value)







        if is_true:







            return [("user_id", "in", users_on_leave.ids)]







        else:







            return ["|", ("user_id", "=", False), ("user_id", "not in", users_on_leave.ids)]















    @api.depends("user_id", "escalated_to_user_id", "escalated_to_level_3_user_id")







    def _compute_is_assigned_to_me(self):







        uid = self.env.uid







        for ticket in self:







            ticket.is_assigned_to_me = bool(







                (ticket.user_id and ticket.user_id.id == uid)







                or (ticket.escalated_to_user_id and ticket.escalated_to_user_id.id == uid)







                or (ticket.escalated_to_level_3_user_id and ticket.escalated_to_level_3_user_id.id == uid)







            )















    def _search_is_assigned_to_me(self, operator, value):







        uid = self.env.uid







        is_true = (operator in ("=", "==") and value) or (operator in ("!=", "<>") and not value)







        my_domain = ["|", "|", ("user_id", "=", uid), ("escalated_to_user_id", "=", uid), ("escalated_to_level_3_user_id", "=", uid)]







        if is_true:







            return my_domain







        else:







            return ["!", "&", "&", ("user_id", "=", uid), ("escalated_to_user_id", "=", uid), ("escalated_to_level_3_user_id", "=", uid)]















    @api.model







    def _read_group_stage_ids(self, stages, domain):







        """Show always the stages without team, or stages of the default/context team."""







        team_id = self.env.context.get("default_team_id")







        if not team_id:







            default_vals = self.default_get(["team_id"])







            team_id = default_vals.get("team_id") if isinstance(default_vals, dict) else False















        search_domain = ["|", ("id", "in", stages.ids), ("team_ids", "=", False)]







        if team_id:







            search_domain = ["|", ("team_ids", "=", team_id)] + search_domain















        stage_ids = stages.sudo()._search(search_domain, order=stages._order)







        return stages.browse(stage_ids)















    @api.depends("duplicate_ids")







    def _compute_duplicate_count(self):







        for record in self:







            record.duplicate_count = len(record.duplicate_ids)















    @api.depends("sla_status_ids.deadline", "sla_status_ids.status", "sla_status_ids.reached_datetime", "stage_id.closed", "stage_id.name", "closed", "ola_deadline", "ola_status")



    def _compute_sla_fields(self):



        now = fields.Datetime.now()



        for ticket in self:



            statuses = ticket.sla_status_ids



            deadlines = statuses.filtered("deadline").mapped("deadline")



            ticket.sla_deadline = min(deadlines) if deadlines else False



            stage_name = (ticket.stage_id.name or "").lower() if ticket.stage_id else ""



            is_done_or_closed = ticket.closed or (ticket.stage_id and (ticket.stage_id.closed or any(w in stage_name for w in ("done", "resolved", "resolve", "closed", "close", "rejected", "reject", "cancelled", "cancel"))))







            sla_failed = False



            for s in statuses:



                if s.reached_datetime:



                    continue



                if s.status == "failed" or (s.deadline and now > s.deadline):



                    sla_failed = True



                    break







            # Also check if OLA deadline has passed on an open ticket



            ola_failed = False



            if ticket.ola_deadline and now > ticket.ola_deadline and not is_done_or_closed:



                ola_failed = True







            if sla_failed or ola_failed:



                ticket.sla_status = "failed"



                if ola_failed and ticket.ola_status not in ("failed", "reached"):



                    ticket.ola_status = "failed"



            elif any(s.status == "in_progress" for s in statuses) or (ticket.ola_status == "in_progress" and not is_done_or_closed):



                ticket.sla_status = "reached" if is_done_or_closed else "in_progress"



            elif statuses or ticket.ola_status in ("reached", "failed"):



                ticket.sla_status = "reached"



            else:



                ticket.sla_status = "reached" if is_done_or_closed else "in_progress"















    # ── Core fields ───────────────────────────────────────────────────────────















    number = fields.Char(string="Ticket number", default="/", readonly=True, index=True)







    name = fields.Char(string="Title", default="/", required=False)







    description = fields.Html(required=True, sanitize_style=True)







    user_id = fields.Many2one(







        comodel_name="res.users",







        string="Assigned user",







        readonly=True,







        tracking=True,







        index=True,







        domain="[('share', '=', False)]",







    )







    user_is_on_leave = fields.Boolean(







        string="Assigned Agent on Leave",







        compute="_compute_user_is_on_leave",







        search="_search_user_is_on_leave",







        help="Indicates whether the assigned agent is currently on approved leave.",







    )







    user_leave_status = fields.Char(







        string="Agent Leave Status",







        compute="_compute_user_is_on_leave",







        help="Leave details and return date of the assigned agent.",







    )







    is_assigned_to_me = fields.Boolean(







        string="Assigned to Me",







        compute="_compute_is_assigned_to_me",







        search="_search_is_assigned_to_me",







        help="Indicates whether the ticket is assigned or escalated to the current user.",







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







    partner_id = fields.Many2one(comodel_name="res.partner", string="Contact", index=True)







    commercial_partner_id = fields.Many2one(







        string="Commercial Partner",







        store=True,







        related="partner_id.commercial_partner_id",







    )







    partner_name = fields.Char()







    customer_name = fields.Char(



        string="Customer Name",



        required=True,



        store=True,



        index=True,



        tracking=True,



        help="Full name of the customer (mandatory and empty by default).",



    )







    phone_number = fields.Char(



        string="Phone Number",



        compute="_compute_phone_number",



        inverse="_inverse_phone_number",



        search="_search_phone_number",



        help="Customer primary phone number (synced with partner_phone).",



    )







    customer_email = fields.Char(



        string="Customer Email",



        compute="_compute_customer_email",



        inverse="_inverse_customer_email",



        search="_search_customer_email",



        help="Customer email address (synced with partner_email).",



    )







    customer_inquires = fields.Text(



        string="Customer Inquiries",



        compute="_compute_customer_inquires",



        inverse="_inverse_customer_inquires",



        search="_search_customer_inquires",



        help="Customer inquiry details (synced with customer_request_details).",



    )







    @api.depends("partner_phone")



    def _compute_phone_number(self):



        for ticket in self:



            ticket.phone_number = ticket.partner_phone







    def _inverse_phone_number(self):



        for ticket in self:



            ticket.partner_phone = ticket.phone_number







    def _search_phone_number(self, operator, value):



        return [("partner_phone", operator, value)]







    @api.depends("partner_email")



    def _compute_customer_email(self):



        for ticket in self:



            ticket.customer_email = ticket.partner_email







    def _inverse_customer_email(self):



        for ticket in self:



            ticket.partner_email = ticket.customer_email







    def _search_customer_email(self, operator, value):



        return [("partner_email", operator, value)]







    @api.depends("customer_request_details", "description")



    def _compute_customer_inquires(self):



        for ticket in self:



            ticket.customer_inquires = ticket.customer_request_details or (tools.html2plaintext(ticket.description).strip() if ticket.description else False)







    def _inverse_customer_inquires(self):



        for ticket in self:



            ticket.customer_request_details = ticket.customer_inquires



            if not ticket.description and ticket.customer_inquires:



                ticket.description = f"<p>{ticket.customer_inquires}</p>"







    def _search_customer_inquires(self, operator, value):



        return [("customer_request_details", operator, value)]







    @api.onchange("customer_name")



    def _onchange_customer_name_sync(self):



        if self.customer_name:



            self.partner_name = self.customer_name







    partner_email = fields.Char(string="Email", index=True)







    last_stage_update = fields.Datetime(default=fields.Datetime.now, index=True)







    assigned_date = fields.Datetime(copy=False)







    closed_date = fields.Datetime(copy=False)







    closed = fields.Boolean(related="stage_id.closed")







    unattended = fields.Boolean(related="stage_id.unattended", store=True)







    is_reopened = fields.Boolean(







        string="Is Reopened",







        default=False,







        copy=False,







        tracking=True,







        help="Flag indicating if this ticket was reopened after closure.",







    )







    reopen_reason = fields.Text(







        string="Reopen Reason",







        copy=False,







        tracking=True,







        help="Reason provided when this ticket was reopened.",







    )







    is_under_review = fields.Boolean(



        string="Under Review",



        compute="_compute_is_under_review",



        store=True,



        tracking=True,



        help="Flag indicating ticket was resolved by Front-line and is awaiting Back-line audit.",



    )



    review_submitted_by_id = fields.Many2one("res.users", string="Review Submitted By", copy=False)



    review_submitted_at = fields.Datetime(string="Review Submitted At", copy=False)



    reviewed_by_id = fields.Many2one("res.users", string="Audited By (Back-line)", copy=False, tracking=True)



    reviewed_at = fields.Datetime(string="Audit Date", copy=False)



    review_decision = fields.Selection(



        selection=[



            ("approved", "Approved & Marked as Resolved"),



            ("returned", "Returned to Front-Line for Correction"),



        ],



        string="Audit Decision",



        copy=False,



        tracking=True,



    )



    review_registration_feedback = fields.Text(



        string="Feedback on Case Registration",



        copy=False,



        tracking=True,



        help="Back-line feedback on customer info, service classification, and inquiry documentation.",



    )



    review_root_cause_feedback = fields.Text(



        string="Feedback on Root Cause",



        copy=False,



        tracking=True,



        help="Back-line feedback on the root cause identified by the front-line agent.",



    )



    review_resolution_feedback = fields.Text(



        string="Feedback on Resolution",



        copy=False,



        tracking=True,



        help="Back-line feedback on the resolution and explanation provided to the customer.",



    )



    review_comments = fields.Text(



        string="Back-Line Review Comments",



        copy=False,



        tracking=True,



        help="General audit comments and recommendations from the Back-line support team.",



    )







    @api.depends("stage_id", "stage_id.name")



    def _compute_is_under_review(self):



        for ticket in self:



            stage_name = (ticket.stage_id.name or "").lower() if ticket.stage_id else ""



            ticket.is_under_review = ("review" in stage_name)







    cancel_reason = fields.Text(







        string="Cancellation Reason",







        copy=False,







        tracking=True,







        help="Reason provided when this ticket was cancelled.",







    )







    is_closed_or_resolved = fields.Boolean(







        string="Is Closed, Done, Cancelled, or Rejected",







        compute="_compute_is_closed_or_resolved",







    )







    is_resolved = fields.Boolean(







        string="Is Resolved",







        compute="_compute_is_resolved",







        help="True specifically when the ticket is in the Resolved stage (not yet Closed).",







    )







    can_escalate = fields.Boolean(







        string="Can Escalate",







        compute="_compute_can_escalate",







        help="Controls visibility and eligibility to escalate this ticket without duplicates.",







    )







    is_rejected = fields.Boolean(







        string="Is Rejected",







        default=False,







        copy=False,







        index=True,







        tracking=True,







        help="Flag indicating if this ticket was rejected by Back Office or Manager.",







    )







    is_creator_viewing = fields.Boolean(







        string="Is Ticket Creator",







        compute="_compute_is_creator_viewing",







        help="True if the current user is the creator of this ticket.",







    )







    can_act_on_rejected = fields.Boolean(







        string="Can Act on Rejected Ticket",







        compute="_compute_can_act_on_rejected",







        help="True if the current user is the creator and ticket is rejected, allowing reassignment or escalation.",







    )







    rejection_reason = fields.Text(







        string="Rejection Reason",







        tracking=True,







        copy=False,







        help="Reason why this ticket was rejected by Back Office or Manager.",







    )







    closure_reason = fields.Char(



        string="Rejection / Cancellation Reason",



        compute="_compute_closure_reason",



        store=True,



        help="Unified reason for ticket cancellation or rejection.",



    )







    @api.depends("rejection_reason", "cancel_reason", "is_rejected", "stage_id")



    def _compute_closure_reason(self):



        for ticket in self:



            ticket.closure_reason = ticket.rejection_reason or ticket.cancel_reason or False







    tag_ids = fields.Many2many(comodel_name="helpdesk.ticket.tag", string="Tags")







    company_id = fields.Many2one(







        comodel_name="res.company",







        string="Company",







        required=True,







        index=True,







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







        string="Responsible Operating Unit",







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







        default="1",







        index=True,







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







    active = fields.Boolean(default=True, index=True)















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







    customer_status = fields.Selection(







        selection=[







            ("existing", "Existing Customer"),







            ("new", "New Customer / Prospect"),







        ],







        string="Customer Status",







        default=False,







        tracking=True,







    )







    customer_type = fields.Selection(







        selection=[







            ("internal", "Internal Staff"),







            ("external", "External Customer"),







        ],







        string="Customer Type",







        default=False,







        tracking=True,







    )







    customer_type_id = fields.Many2one(







        comodel_name="helpdesk.ticket.customer.type",







        string="Customer Classification",







        index=True,







        tracking=True,







    )







    internal_unit_id = fields.Many2one(







        comodel_name="operating.unit",







        string="Originating Branch / Work Unit",







        help="Branch or Head Office work unit that submitted or reported this request.",







    )







    account_number = fields.Char(string="Account Number", tracking=True, index=True)







    cif_number = fields.Char(string="CIF Number", tracking=True, index=True)







    fayda_number = fields.Char(string="Fayda / National ID", tracking=True, index=True)







    partner_phone = fields.Char(string="Phone / Mobile", tracking=True, index=True)







    partner_phone_secondary = fields.Char(







        string="Caller Phone",







        tracking=True,







        help="Secondary or alternative telephone number for customer contact.",







    )







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







        string="Communication Language",







        default="amharic",







        tracking=True,







    )







    customer_age = fields.Integer(string="Age", tracking=True)







    customer_district = fields.Char(string="District Name", tracking=True)







    account_branch_name = fields.Char(string="Branch Name", tracking=True)







    customer_type_name = fields.Char(string="Customer Type", tracking=True)







    sol_id = fields.Char(string="SOL ID", tracking=True)







    acct_opn_date = fields.Date(string="Account Opening Date", tracking=True)







    mode_of_oper_code = fields.Char(string="Mode of Operation", tracking=True)







    account_ownership = fields.Char(string="Account Ownership", tracking=True)















    # ── 3-Tier Product & Service Catalogue ────────────────────────────────────







    service_family_id = fields.Many2one(







        comodel_name="helpdesk.service.family",







        string="Service Family",







        tracking=True,







        index=True,







    )







    service_id = fields.Many2one(







        comodel_name="helpdesk.service",







        string="Service",







        tracking=True,







        index=True,







    )







    service_sub_category_id = fields.Many2one(







        comodel_name="helpdesk.service.sub.category",







        string="Sub Service",







        domain="[('service_id', '=', service_id)] if service_id else []",







        tracking=True,







        index=True,







    )







    parent_operating_unit_id = fields.Many2one(







        comodel_name="operating.unit",







        string="Service Provider",







        store=True,







        readonly=False,







        tracking=True,







        index=True,







        help="Service Provider / Parent Operating Unit (e.g. District, Directorate).",







    )







    operating_unit_id = fields.Many2one(







        comodel_name="operating.unit",







        string="Sub Service Provider",







        tracking=True,







        index=True,







        help="Division / Child Operating Unit (e.g. Branch, Work Unit) resolving this ticket.",







    )







    branch_operating_unit_id = fields.Many2one(







        comodel_name="operating.unit",







        string="Branch / Base Work Unit",







        compute="_compute_parent_operating_units",







        store=True,







        readonly=False,







        help="Branch or base work unit level.",







    )







    district_operating_unit_id = fields.Many2one(







        comodel_name="operating.unit",







        string="District Office / Division",







        compute="_compute_parent_operating_units",







        store=True,







        readonly=False,







        help="District office or operational division level.",







    )







    directorate_operating_unit_id = fields.Many2one(







        comodel_name="operating.unit",







        string="Directorate / Head Office Unit",







        compute="_compute_parent_operating_units",







        store=True,







        readonly=False,







        help="Directorate or Head Office department level.",







    )







    executive_operating_unit_id = fields.Many2one(







        comodel_name="operating.unit",







        string="Executive Management / CEO Office",







        compute="_compute_parent_operating_units",







        store=True,







        readonly=False,







        help="Top-level executive office / CEO Office level.",







    )







    grandparent_operating_unit_id = fields.Many2one(







        comodel_name="operating.unit",







        string="Top / Executive Unit (CEO Office)",







        compute="_compute_parent_operating_units",







        store=True,







        readonly=False,







        help="Top-level parent operating unit up to CEO Office.",







    )







    parent_operating_unit_ids = fields.Many2many(







        comodel_name="operating.unit",







        relation="helpdesk_ticket_parent_operating_unit_rel",







        column1="ticket_id",







        column2="operating_unit_id",







        string="All Parent Operating Units",







        compute="_compute_parent_operating_units",







        store=True,







        help="All ancestral parent operating units up to CEO.",







    )







    operating_unit_hierarchy = fields.Char(







        string="Operating Unit Chain (to CEO)",







        compute="_compute_parent_operating_units",







        store=True,







        help="Complete hierarchical organizational path up to CEO.",







    )







    operating_unit_user_ids = fields.Many2many(







        comodel_name="res.users",







        string="Operating Unit Members",







        compute="_compute_operating_unit_user_ids",







        help="All eligible users belonging to the selected Operating Unit / Directorate.",







    )







    user_helpdesk_role = fields.Selection(







        related="user_id.helpdesk_role",







        string="Assignee Role / Specialization",







        readonly=True,







    )







    service_sop = fields.Html(







        string="Resolution SOP",







        compute="_compute_service_sop",







        readonly=True,







    )















    @api.depends("service_sub_category_id.resolution_sop", "kb_article_id.content")







    def _compute_service_sop(self):







        for ticket in self:







            ticket.service_sop = (







                (ticket.service_sub_category_id and ticket.service_sub_category_id.resolution_sop)







                or (ticket.kb_article_id and ticket.kb_article_id.content)







                or False







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







            ("api", "REST API / External Integration"),







            ("phone", "Phone Call / IVR (Contact Center)"),







            ("email", "Email (CC Helpdesk)"),







            ("tidio_chat", "Tidio Website Chat"),







            ("web_portal", "Customer Web Portal"),







            ("telegram", "Telegram Bot"),







            ("whatsapp", "WhatsApp"),







            ("instagram", "Instagram Direct / Comments"),







            ("facebook", "Facebook Messenger / Page"),







            ("chatbot", "AI Chatbot / Live Chat"),







            ("mobile_banking", "Mobile Banking App"),







            ("branch_walkin", "Branch Walk-in"),







            ("sms", "SMS / USSD"),







            ("other", "Other Channels"),







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







    contact_center_agent_ids = fields.Many2many(







        comodel_name="hr.employee",







        string="Eligible Contact Center Agents",







        compute="_compute_contact_center_agent_ids",







        compute_sudo=True,







        help="All employees belonging to Contact Center Operating Unit.",







    )







    contact_center_agent_id = fields.Many2one(







        comodel_name="hr.employee",







        string="Contact Center Agent",







        index=True,







        domain="[('id', 'in', contact_center_agent_ids)]",







        default=lambda self: self._default_contact_center_agent_id(),







        tracking=True,







        help="Contact Center agent / employee who received or registered this customer inquiry.",







    )















    @api.depends_context("uid")







    @api.depends("create_uid", "company_id")







    def _compute_contact_center_agent_ids(self):







        """







        Filter Contact Center Agents strictly to employees belonging to the SAME







        operating unit(s) as the ticket creator, and ALWAYS including the creator's employee.







        """







        def _get_creator_ous(user):







            ous = self.env["operating.unit"]







            if not user:







                return ous







            if user.default_operating_unit_id:







                ous |= user.default_operating_unit_id







            if user.assigned_operating_unit_ids:







                ous |= user.assigned_operating_unit_ids







            emp = self.env["hr.employee"].sudo().search([("user_id", "=", user.id)], limit=1)







            if emp:







                if emp.default_operating_unit_id:







                    ous |= emp.default_operating_unit_id







                if emp.operating_unit_ids:







                    ous |= emp.operating_unit_ids







            return ous.filtered(lambda o: o.active)















        for ticket in self:







            creator = ticket.create_uid or self.env.user







            creator_emp = self.env["hr.employee"].sudo().search([("user_id", "=", creator.id)], limit=1)







            if not creator_emp:







                creator_emp = getattr(creator, "employee_id", self.env["hr.employee"])







            if not creator_emp and creator.email:







                creator_emp = self.env["hr.employee"].sudo().search([("work_email", "=", creator.email)], limit=1)







            if not creator_emp:







                creator_emp = self.env["hr.employee"].sudo().search([("name", "=", creator.name)], limit=1)















            creator_ous = _get_creator_ous(creator)







            ou_ids = creator_ous.ids







            if not ou_ids:







                cc_ous = self.env["operating.unit"].sudo().search([("name", "ilike", "contact center")])







                if cc_ous:







                    candidates = self.env["hr.employee"].sudo().search([







                        ("active", "=", True),







                        "|",







                        ("default_operating_unit_id", "in", cc_ous.ids),







                        ("operating_unit_ids", "in", cc_ous.ids),







                    ])







                else:







                    candidates = self.env["hr.employee"].sudo().search([("active", "=", True)], limit=50)







                ticket.contact_center_agent_ids = (candidates | creator_emp) if creator_emp else candidates







                continue















            # Employees directly assigned to creator's operating unit(s)







            emps_direct = self.env["hr.employee"].sudo().search([







                ("active", "=", True),







                "|",







                ("default_operating_unit_id", "in", ou_ids),







                ("operating_unit_ids", "in", ou_ids),







            ])







            # Employees whose linked user is assigned to creator's operating unit(s)







            users_in_ou = self.env["res.users"].sudo().search([







                ("active", "=", True),







                ("share", "=", False),







                "|",







                ("default_operating_unit_id", "in", ou_ids),







                ("assigned_operating_unit_ids", "in", ou_ids),







            ])







            emps_via_user = self.env["hr.employee"].sudo().search([







                ("active", "=", True),







                ("user_id", "in", users_in_ou.ids),







            ])







            candidate_emps = (emps_direct | emps_via_user).filtered(lambda e: e.active)







            if creator_emp:







                candidate_emps |= creator_emp







            ticket.contact_center_agent_ids = candidate_emps















    @api.onchange("contact_center_agent_id")







    def _onchange_contact_center_agent_id(self):







        """Only auto-assign user if user_id is unset and CC agent belongs to ticket's division."""







        cc_agent = self.sudo().contact_center_agent_id







        if cc_agent and cc_agent.user_id:







            if not self.user_id and self.operating_unit_id and cc_agent.user_id in self.operating_unit_user_ids:







                self.user_id = cc_agent.user_id















    @api.model







    def _default_contact_center_agent_id(self):







        """







        Default to the ticket creator's employee record.







        """







        uid = self.env.uid







        emp = self.env["hr.employee"].sudo().search([("user_id", "=", uid)], limit=1)







        if not emp:







            emp = getattr(self.env.user, "employee_id", False)







        if not emp and self.env.user.email:







            emp = self.env["hr.employee"].sudo().search([("work_email", "=", self.env.user.email)], limit=1)







        if not emp:







            emp = self.env["hr.employee"].sudo().search([("name", "=", self.env.user.name)], limit=1)







        return emp.id if emp else False















    @api.constrains("partner_phone", "partner_phone_secondary")







    def _check_phone_numbers(self):







        """The phone number field must accept only 10- or 13-digit numbers and prevent submission otherwise."""







        for ticket in self:







            for field_name, label in [







                ("partner_phone", _("Phone / Mobile")),







                ("partner_phone_secondary", _("Caller Phone")),







            ]:







                val = getattr(ticket, field_name, False)







                if val:







                    cleaned = re.sub(r"[\s\-\.\(\)]", "", str(val).strip())







                    is_10 = bool(re.fullmatch(r"\d{10}", cleaned))







                    is_13 = bool(re.fullmatch(r"(\+\d{12}|\d{13})", cleaned))







                    if not (is_10 or is_13):







                        raise ValidationError(_(







                            "Invalid %s '%s'. The phone number field must accept only 10- or 13-digit numbers "







                            "(e.g., 10 digits: 0919166920 or 13 characters: +251919166920) "







                            "and prevent submission if the entered number does not meet either requirement."







                        ) % (label, val))















    @api.onchange("partner_phone", "partner_phone_secondary")







    def _onchange_phone_numbers(self):







        for field_name, label in [







            ("partner_phone", _("Phone / Mobile")),







            ("partner_phone_secondary", _("Caller Phone")),







        ]:







            val = getattr(self, field_name, False)







            if val:







                cleaned = re.sub(r"[\s\-\.\(\)]", "", str(val).strip())







                is_10 = bool(re.fullmatch(r"\d{10}", cleaned))







                is_13 = bool(re.fullmatch(r"(\+\d{12}|\d{13})", cleaned))







                # Only warn if the phone number is 10 or more characters and doesn't match standard patterns



                if len(cleaned) >= 10 and not (is_10 or is_13):







                    return {







                        "warning": {







                            "title": _("Invalid Phone Number"),







                            "message": _(







                                "The %s must be either 10 digits (e.g. 0919166920) or 13 digits (e.g. +251919166920). "







                                "Entered value: '%s'"







                            ) % (label, val),







                        }







                    }















    @api.constrains("stage_id", "is_rejected", "rejection_reason")







    def _check_rejection_reason(self):







        for ticket in self:







            is_rejected_stage = bool(ticket.stage_id and "reject" in (ticket.stage_id.name or "").lower())







            if ticket.is_rejected or is_rejected_stage:







                if not ticket.rejection_reason or not ticket.rejection_reason.strip():







                    raise ValidationError(_(







                        "A Rejection Reason is required when rejecting a ticket. "







                        "Please use the 'Reject' button or provide a detailed rejection reason."







                    ))















    @api.constrains("contact_center_agent_id", "operating_unit_id")







    def _check_contact_center_agent_valid(self):







        """Prevent assigning a contact center agent outside the creator's operating unit."""







        if self.env.context.get("skip_ou_user_constraint"):







            return







        for ticket in self:







            if not ticket.contact_center_agent_id:







                continue







            creator = ticket.create_uid or self.env.user







            if ticket.contact_center_agent_id.user_id and ticket.contact_center_agent_id.user_id == creator:







                continue







            eligible = ticket.with_context(uid=creator.id).contact_center_agent_ids







            if eligible and (ticket.contact_center_agent_id._origin not in eligible._origin and ticket.contact_center_agent_id.id not in eligible.ids):







                raise ValidationError(_(







                    "Contact Center Agent '%s' does not belong to the operating unit "







                    "of the ticket creator. Please select an eligible agent."







                ) % ticket.contact_center_agent_id.name)















    @api.constrains("user_id", "operating_unit_id")







    def _check_assigned_user_in_division(self):







        """Prevent assigning a user who is not in the ticket's responsible division."""







        for ticket in self:







            if not ticket.user_id or not ticket.operating_unit_id:







                continue







            if ticket.user_id.id in (1, 2) or getattr(ticket.user_id, "is_admin", lambda: False)():







                continue







            if ticket.user_id in ticket.operating_unit_user_ids:







                continue







            # Allow if user is an authorized contact center agent for this ticket







            if ticket.contact_center_agent_ids and ticket.user_id in ticket.contact_center_agent_ids.mapped("user_id"):







                continue







            # Allow when the write is performed within the escalation engine context







            if self.env.context.get("skip_ou_user_constraint"):







                continue







            # Allow manager-hierarchy escalations (directorate level and above).







            # At these levels the assignee is determined by the org reporting chain







            # and may belong to a different operating unit (e.g. a corporate/executive OU).







            if ticket.is_escalated and (ticket.escalation_level or 0) >= 4:







                continue







            # Allow when the assigned user is an organizational manager of







            # someone who belongs to the ticket's operating unit.







            mgr_emp = self.env["hr.employee"].sudo().search(







                [("user_id", "=", ticket.user_id.id)], limit=1







            )







            if mgr_emp:







                ou_emps = self.env["hr.employee"].sudo().search([







                    ("active", "=", True),







                    ("user_id", "!=", False),







                    "|",







                    ("default_operating_unit_id", "=", ticket.operating_unit_id.id),







                    ("operating_unit_ids", "in", ticket.operating_unit_id.id),







                ])







                is_manager = False







                for emp in ou_emps:







                    curr = emp.parent_id







                    depth = 0







                    while curr and depth < 10:







                        if curr.id == mgr_emp.id:







                            is_manager = True







                            break







                        curr = curr.parent_id







                        depth += 1







                    if is_manager:







                        break







                if is_manager:







                    continue







            raise ValidationError(_(







                "Assigned user '%s' does not belong to the division '%s'. "







                "Please select a user from the responsible division."







            ) % (ticket.user_id.name, ticket.operating_unit_id.name))















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







        index=True,







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







        copy=False,







    )







    original_operating_unit_id = fields.Many2one(







        comodel_name="operating.unit",







        string="Original Operating Unit",







        readonly=True,







        copy=False,







        help="Operating unit where the ticket originally entered the system.",







    )







    escalation_journey = fields.Selection(







        selection=[







            ("primary_journey", "1. Primary Operating Unit Journey Track"),







            ("other_work_journey", "2. Other Operating Unit Journey Track (Cross-Unit Transfer)"),







        ],







        string="Escalation Journey Track",







        default="primary_journey",







        tracking=True,







        copy=False,







        help="Current active escalation journey track (Primary vs Cross-Operating Unit).",







    )







    is_escalated = fields.Boolean(







        string="Escalated to 2nd Level",







        default=False,







        tracking=True,







        index=True,







        copy=False,







    )







    escalated_to_team_id = fields.Many2one(







        comodel_name="helpdesk.ticket.team",







        string="Escalated Operating Unit (2nd Level)",







        tracking=True,







        index=True,







        copy=False,







    )







    escalated_to_user_id = fields.Many2one(







        comodel_name="res.users",







        string="Escalated Specialist",







        tracking=True,







        index=True,







        copy=False,







    )







    escalation_date = fields.Datetime(string="Escalated On", copy=False)







    escalation_reason = fields.Text(string="Escalation Reason", copy=False)







    escalation_level = fields.Integer(string="Escalation Level", default=0, tracking=True, index=True)















    # ── 3rd Level Escalation Fields ──────────────────────────────────────────







    is_level_3_escalated = fields.Boolean(







        string="Escalated to 3rd Level",







        default=False,







        tracking=True,







        index=True,







        copy=False,







    )







    escalated_to_level_3_team_id = fields.Many2one(







        comodel_name="helpdesk.ticket.team",







        string="Escalated Operating Unit (3rd Level)",







        tracking=True,







        index=True,







        copy=False,







    )







    escalated_to_level_3_user_id = fields.Many2one(







        comodel_name="res.users",







        string="3rd Level Specialist / Executive",







        tracking=True,







        index=True,







        copy=False,







    )







    level_3_escalation_date = fields.Datetime(string="3rd Level Escalated On", copy=False)







    level_3_escalation_reason = fields.Text(string="3rd Level Escalation Reason", copy=False)















    is_ceo_escalated = fields.Boolean(string="CEO Level Escalated", default=False, tracking=True, index=True)



    is_sla_expired = fields.Boolean(string="SLA Escalation Time Expired", default=False, tracking=True, copy=False)



    sla_expired_at = fields.Datetime(string="SLA Expired At", copy=False)







    last_escalation_date = fields.Datetime(string="Last Escalated Date", tracking=True)







    escalation_history_ids = fields.One2many(







        comodel_name="helpdesk.ticket.escalation.history",







        inverse_name="ticket_id",







        string="Escalation Audit Trail",







    )















    # ── Pending Stage Tracking ────────────────────────────────────────────────







    pending_reason = fields.Char(







        string="In-Progress Reason",







        tracking=True,







        copy=False,







        help="Reason why this ticket is currently in progress and cannot yet be fully resolved.",







    )







    pending_reason_details = fields.Text(







        string="In-Progress Details",







        tracking=True,







        copy=False,







        help="Detailed explanation, context, and findings for why the ticket is pending.",







    )







    pending_date = fields.Datetime(







        string="Pending Since",







        tracking=True,







        copy=False,







    )







    is_pending = fields.Boolean(







        string="Is Pending",







        compute="_compute_is_pending",







        store=True,







        index=True,







        tracking=True,







    )















    @api.depends("stage_id", "stage_id.name")







    def _compute_is_pending(self):







        for ticket in self:







            ticket.is_pending = bool(ticket.stage_id and "pending" in (ticket.stage_id.name or "").lower())















    # ── Customer Inquiry Formulation & KB Integration ────────────────────────











    # ── Ticket Module Enhancement Fields (Customer Rating & Case Resolution) ──



    customer_rating = fields.Selection(



        [



            ("very_dissatisfied", "Very Dissatisfied"),



            ("dissatisfied", "Dissatisfied"),



            ("neutral", "Neutral"),



            ("satisfied", "Satisfied"),



            ("very_satisfied", "Very Satisfied"),



        ],



        string="Customer Rating",



        tracking=True,



        help="Customer satisfaction rating collected during ticket handling at any stage.",



    )



    customer_feedback = fields.Text(



        string="Customer Feedback",



        tracking=True,



        help="Direct customer feedback and suggestions collected across stages.",



    )



    resolution = fields.Text(



        string="Case Resolution",



        tracking=True,



        copy=False,



        help="Resolution details including the reason for resolving the issue and actions taken.",



    )







    inquiry_summary = fields.Char(string="Root Case")







    customer_request_details = fields.Text(







        string="Customer Inquired Details",







        compute="_compute_customer_request_details",







        store=True,







        readonly=False,







        tracking=True,







    )















    @api.depends("description")







    def _compute_customer_request_details(self):







        for ticket in self:







            if not ticket.customer_request_details and ticket.description:







                ticket.customer_request_details = tools.html2plaintext(ticket.description).strip()







    agent_action_taken = fields.Text(string="Agent Response", tracking=True)







    escalated_agent_response = fields.Text(







        string="Escalated Agent Response",







        tracking=True,







        copy=False,







        help="Resolution steps and response provided by the escalated specialist/operating unit.",







    )







    kb_article_id = fields.Many2one(







        comodel_name="helpdesk.knowledge.article",







        string="Knowledge Base SOP / Article",







        compute="_compute_kb_article_id",







        store=True,







        readonly=False,







        help="Automatically populated from the selected Service, Sub Service, or Sub-Category.",







    )















    @api.onchange("kb_article_id")







    def _onchange_kb_article_id(self):







        if self.kb_article_id:







            if self.kb_article_id.agent_response:







                self.agent_action_taken = self.kb_article_id.agent_response







            elif self.kb_article_id.content:







                plain_text = tools.html2plaintext(self.kb_article_id.content).strip()







                if plain_text:







                    self.agent_action_taken = plain_text















    @api.onchange("agent_action_taken")







    def _onchange_agent_action_taken_match_kb(self):







        """When agent writes in Agent Response, check Knowledge Base for a match and load the response."""







        if not self.agent_action_taken:







            return







        text = self.agent_action_taken.strip()







        if len(text) < 3:







            return







        if self.kb_article_id and self.kb_article_id.agent_response and self.kb_article_id.agent_response.strip() == text:







            return















        domain_base = [("state", "=", "published")]







        article = False















        # 1. Search in matching service / sub-category first if selected







        service_domain = []







        if self.service_sub_category_id:







            service_domain = [("sub_category_id", "=", self.service_sub_category_id.id)]







        elif self.service_id:







            service_domain = [("service_id", "=", self.service_id.id)]







        elif self.service_family_id:







            service_domain = [("service_family_id", "=", self.service_family_id.id)]















        if service_domain:







            article = self.env["helpdesk.knowledge.article"].search(







                domain_base + service_domain + [("agent_response", "=ilike", text)], limit=1







            )







            if not article:







                article = self.env["helpdesk.knowledge.article"].search(







                    domain_base + service_domain + [("agent_response", "ilike", text)], limit=1







                )















        # 2. Search all published articles for agent_response match







        if not article:







            article = self.env["helpdesk.knowledge.article"].search(







                domain_base + [("agent_response", "=ilike", text)], limit=1







            )







        if not article:







            article = self.env["helpdesk.knowledge.article"].search(







                domain_base + [("agent_response", "ilike", text)], limit=1







            )















        # 3. Check if text contains any KB agent_response phrase or keyword







        if not article and len(text) >= 6:







            candidates = self.env["helpdesk.knowledge.article"].search(







                domain_base + [("agent_response", "!=", False)], limit=50







            )







            text_lower = text.lower()







            for cand in candidates:







                c_resp = cand.agent_response.strip().lower() if cand.agent_response else ""







                if c_resp and (c_resp in text_lower or text_lower in c_resp):







                    article = cand







                    break







                if c_resp and any(w in c_resp for w in text_lower.split() if len(w) >= 4):







                    article = cand







                    break















        # 4. Search by article name / content if no agent_response matched







        if not article:







            article = self.env["helpdesk.knowledge.article"].search(







                domain_base + ["|", ("name", "ilike", text), ("content", "ilike", text)], limit=1







            )















        if article:







            self.kb_article_id = article.id







            resp = article.agent_response or (tools.html2plaintext(article.content).strip() if article.content else False)







            if resp and resp.strip() != text:







                self.agent_action_taken = resp







                return {







                    "warning": {







                        "title": _("Knowledge Base Match Found!"),







                        "message": _("Matched Knowledge Base Article '%s'. Verified standard response has been loaded into Agent Response.") % article.name,







                    }







                }















    @api.onchange("inquiry_summary")







    def _onchange_inquiry_summary_load_kb(self):







        if self.inquiry_summary and not self.kb_article_id:







            article = self.env["helpdesk.knowledge.article"].search([







                ("state", "=", "published"),







                "|",







                ("name", "ilike", self.inquiry_summary.strip()),







                ("content", "ilike", self.inquiry_summary.strip()),







            ], limit=1)







            if article:







                self.kb_article_id = article







                if not self.agent_action_taken and article.content:







                    self.agent_action_taken = tools.html2plaintext(article.content).strip()















    @api.depends("service_sub_category_id", "service_id", "service_family_id", "inquiry_summary", "name")







    def _compute_kb_article_id(self):







        for ticket in self:







            article = False







            if ticket.service_sub_category_id:







                article = self.env["helpdesk.knowledge.article"].search([







                    ("sub_category_id", "=", ticket.service_sub_category_id.id),







                    ("state", "=", "published"),







                ], limit=1)







                if not article and ticket.service_sub_category_id.resolution_sop:







                    art_name = f"SOP: {ticket.service_sub_category_id.name}"







                    article = self.env["helpdesk.knowledge.article"].search([







                        ("name", "=", art_name),







                    ], limit=1)







                    if not article:







                        article = self.env["helpdesk.knowledge.article"].sudo().create({







                            "name": art_name,







                            "service_family_id": ticket.service_family_id.id if ticket.service_family_id else False,







                            "service_id": ticket.service_id.id if ticket.service_id else False,







                            "sub_category_id": ticket.service_sub_category_id.id,







                            "content": ticket.service_sub_category_id.resolution_sop,







                            "state": "published",







                        })







            if not article and ticket.service_id:







                article = self.env["helpdesk.knowledge.article"].search([







                    ("service_id", "=", ticket.service_id.id),







                    ("state", "=", "published"),







                ], limit=1)







            if not article and ticket.service_family_id:







                article = self.env["helpdesk.knowledge.article"].search([







                    ("service_family_id", "=", ticket.service_family_id.id),







                    ("state", "=", "published"),







                ], limit=1)







            ticket.kb_article_id = article















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







        index=True,







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















    def action_send_rating(self):







        """Send or re-send CSAT satisfaction rating survey to customer."""







        self.ensure_one()







        if not self.partner_id:







            raise ValidationError(_("Cannot send rating survey: Please specify a customer (partner) on this ticket."))







        template = (







            self.team_id.rating_template_id







            if self.team_id and self.team_id.rating_template_id







            else self.env.ref("bunna_helpdesk.helpdesk_rating_request_template", raise_if_not_found=False)







        )







        if not template:







            raise ValidationError(_("Rating email template could not be found."))







        try:







            self.rating_send_request(template, force_send=True)







        except Exception:







            template.send_mail(self.id, force_send=True)















        access_url = self.rating_get_access_url()







        self.message_post(







            body=_(







                "<div>⭐ <strong>Customer Satisfaction Survey Sent</strong><br/>"







                "• Recipient: %s (%s)<br/>"







                "• Direct Survey Link: <a href='%s' target='_blank'>Open Survey</a></div>"







            ) % (self.partner_id.name, self.partner_id.email or _("no email"), access_url),







            message_type="notification",







        )







        return {







            "type": "ir.actions.client",







            "tag": "display_notification",







            "params": {







                "title": _("Rating Survey Sent"),







                "message": _("Customer rating request was sent to %s.") % self.partner_id.name,







                "type": "success",







                "sticky": False,







            },







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















    @api.depends("account_number", "partner_id.account_number")







    def _compute_customer_status(self):







        for ticket in self:







            has_acct = bool(







                (ticket.account_number and str(ticket.account_number).strip())







                or (ticket.partner_id and ticket.partner_id.account_number and str(ticket.partner_id.account_number).strip())







            )







            if has_acct:







                ticket.customer_status = "existing"







            elif not ticket.account_number and not (ticket.partner_id and ticket.partner_id.account_number):







                ticket.customer_status = False







            else:







                ticket.customer_status = "new"















    @api.onchange("customer_status")







    def _onchange_customer_status(self):







        self._sync_customer_type_id()















    @api.onchange("customer_type")







    def _onchange_customer_type(self):







        self._sync_customer_type_id()















    @api.onchange("account_ownership")







    def _onchange_account_ownership(self):







        for ticket in self:







            if not ticket.account_ownership:







                continue







            ownership = str(ticket.account_ownership or "").strip().lower()







            segment = str(ticket.customer_segment or "").strip().lower()







            has_acct = bool(







                (ticket.account_number and str(ticket.account_number).strip())







                or (ticket.partner_id and ticket.partner_id.account_number and str(ticket.partner_id.account_number).strip())







            )







            if "employee" in ownership or "staff" in ownership or segment == "staff":







                ticket.customer_type = "internal"







                if has_acct:







                    ticket.customer_status = "existing"







            elif has_acct:







                ticket.customer_type = "external"







                ticket.customer_status = "existing"







            ticket._sync_customer_type_id()















    def _sync_customer_type_id(self):







        """Synchronize customer_type_id record with customer_status and customer_type."""







        for ticket in self:







            if not ticket.customer_status or not ticket.customer_type:







                ticket.customer_type_id = False







                continue







            type_model = self.env["helpdesk.ticket.customer.type"]







            if ticket.customer_status == "new":







                if ticket.customer_type == "internal":







                    int_type = type_model.search([("code", "=", "internal")], limit=1)







                    ticket.customer_type_id = int_type or type_model.search([("code", "=", "external_prospective")], limit=1)







                else:







                    new_type = type_model.search([("code", "=", "external_prospective")], limit=1)







                    ticket.customer_type_id = new_type







            elif ticket.customer_status == "existing":







                if ticket.customer_type == "internal":







                    int_type = type_model.search([("code", "=", "internal")], limit=1)







                    if int_type:







                        ticket.customer_type_id = int_type







                elif ticket.customer_type == "external":







                    ext_type = type_model.search([("code", "=", "external_existing")], limit=1)







                    if ext_type:







                        ticket.customer_type_id = ext_type















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







        acct_no = partner.account_number or self.account_number or False







        cif_no = partner.cif_number or self.cif_number or False







        fayda_no = partner.fayda_number or self.fayda_number or False















        has_account = bool(acct_no and str(acct_no).strip())







        cust_status = "existing" if has_account else (self.customer_status or "existing")















        ownership_str = str(getattr(partner, "account_ownership", "") or getattr(self, "account_ownership", "") or "").strip().lower()







        segment_str = str(partner.customer_segment or self.customer_segment or "").strip().lower()















        if "employee" in ownership_str or "staff" in ownership_str or segment_str == "staff":







            cust_type = "internal"







        elif getattr(partner, "customer_type", False) in ("internal", "external"):







            cust_type = partner.customer_type







        else:







            cust_type = self.customer_type or "external"















        vals = {







            "partner_id": partner.id,







            "partner_name": partner.name,







            "partner_email": (self.partner_email or "").strip() or partner.email or False,







            "partner_phone": (self.partner_phone or "").strip() or partner.phone or (getattr(partner, "mobile", False) if "mobile" in partner._fields else False) or False,







            "customer_status": cust_status,







            "customer_type": cust_type,







            "account_number": acct_no,







            "cif_number": cif_no,







            "fayda_number": fayda_no,







            "account_type": partner.account_type or self.account_type or "Savings Account",







            "account_status": partner.account_status or self.account_status or "active",







            "account_branch_id": partner.branch_id.id if partner.branch_id else (self.account_branch_id.id if self.account_branch_id else False),







            "account_branch_name": partner.branch_name or (partner.branch_id.name if partner.branch_id else False) or getattr(self, "account_branch_name", False),







            "sol_id": getattr(partner, "sol_id", False) or getattr(self, "sol_id", False),







            "customer_district": partner.district_name or getattr(self, "customer_district", False),







            "customer_age": partner.age or getattr(self, "customer_age", 0),







            "customer_type_name": partner.customer_type or getattr(self, "customer_type_name", False),







            "customer_segment": partner.customer_segment or self.customer_segment or "retail",







            "preferred_language": partner.preferred_language or self.preferred_language or "amharic",







            "acct_opn_date": getattr(partner, "acct_opn_date", False) or getattr(self, "acct_opn_date", False),







            "mode_of_oper_code": getattr(partner, "mode_of_oper_code", False) or getattr(self, "mode_of_oper_code", False),







            "account_ownership": getattr(partner, "account_ownership", False) or getattr(self, "account_ownership", False),







            "cbs_lookup_status": "verified",







        }







        p_name = (partner.name or "").strip()



        is_phone_name = bool(re.search(r"^\+?\d{8,}$", re.sub(r"[\s\-\.\(\)]", "", p_name)))



        is_generic = "bunna customer (" in p_name.lower() or p_name.lower() in ("customer", "guest customer")



        if p_name and not is_phone_name and not is_generic and not self.customer_name:



            vals["customer_name"] = p_name







        for k, v in vals.items():







            setattr(self, k, v)







        self._sync_customer_type_id()







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







            domain.append(("account_number", "=ilike", str(matched_cust["account_number"]).strip()))







        if matched_cust.get("cif_number"):







            domain.append(("cif_number", "=ilike", str(matched_cust["cif_number"]).strip()))







        if matched_cust.get("fayda_number"):







            domain.append(("fayda_number", "=ilike", str(matched_cust["fayda_number"]).strip()))







        if matched_cust.get("phone"):







            domain.append(("phone", "=ilike", str(matched_cust["phone"]).strip()))















        partner = False







        if domain:







            or_domain = ["|"] * (len(domain) - 1) + domain if len(domain) > 1 else domain







            partner = partner_obj.search(or_domain, limit=1)















        # Match operating.unit branch







        branch = False







        if matched_cust.get("sol_id"):







            try:







                sol_int = int(str(matched_cust["sol_id"]).strip())







                branch = self.env["operating.unit"].sudo().search([







                    ("sol_id", "=", sol_int)







                ], limit=1)







            except (ValueError, TypeError):







                pass







        if not branch and matched_cust.get("branch_name"):







            branch = self.env["operating.unit"].sudo().search([







                ("name", "=ilike", str(matched_cust["branch_name"]).strip())







            ], limit=1)







        if not branch:







            branch = self.env["operating.unit"].sudo().search([], limit=1)















        partner_vals = {}







        for k in ("name", "account_number", "cif_number", "fayda_number", "phone", "email",







                  "account_type", "account_status", "customer_segment", "preferred_language",







                  "age", "district_name", "branch_name", "customer_type",







                  "sol_id", "acct_opn_date", "mode_of_oper_code", "account_ownership"):







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







            if len(digits) < 9:







                return False, _("Phone number too short for lookup.")







            digits_suffix = digits[-9:]







            has_mobile = "mobile" in partner_obj._fields







            domain = [







                "|", "|",







                ("phone", "=ilike", q),







                ("phone", "=ilike", f"%{digits_suffix}"),







                ("mobile", "=ilike", f"%{digits_suffix}"),







            ] if has_mobile else [







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







        if val:







            self.customer_status = "existing"







            if len(val) >= 3:







                if self.partner_id and (self.partner_id.account_number or "").strip().lower() == val.lower():







                    return







                self._lookup_and_apply_cbs(val, "account")







        self._sync_customer_type_id()















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















    @api.onchange("partner_phone_secondary")



    def _onchange_partner_phone_secondary_sync(self):



        if self.partner_phone_secondary and not self.partner_phone:



            self.partner_phone = self.partner_phone_secondary







    @api.onchange("partner_phone")



    def _onchange_partner_phone_sync(self):



        if self.partner_phone and not self.partner_phone_secondary:



            self.partner_phone_secondary = self.partner_phone







    @api.onchange("partner_phone", "partner_phone_secondary")







    def _onchange_partner_phone(self):







        val = (self.partner_phone or self.partner_phone_secondary or "").strip()







        if not val:







            return







        digits = re.sub(r"\D", "", val)







        # Ethiopian phone numbers require at least 9 digits (e.g. 911234567 or 0911234567)







        if len(digits) < 9:







            return







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







        self._sync_customer_type_id()















    @api.depends("operating_unit_id", "service_sub_category_id", "service_id", "service_family_id")







    def _compute_parent_operating_units(self):







        for ticket in self:







            ou = ticket.operating_unit_id or ticket.parent_operating_unit_id







            if not ou:







                ou = (







                    (ticket.service_sub_category_id and ticket.service_sub_category_id.operating_unit_id)







                    or (ticket.service_id and ticket.service_id.operating_unit_id)







                    or (ticket.service_family_id and ticket.service_family_id.operating_unit_id)







                )







            if ou:







                chain = []







                parents = []







                curr = ou







                visited = set()







                while curr and curr.id not in visited:







                    visited.add(curr.id)







                    chain.append(curr)







                    if curr != ou:







                        parents.append(curr)







                    curr = curr.parent_unit if curr.parent_unit and curr.parent_unit != curr else False















                if not ticket.operating_unit_id and (ticket.service_sub_category_id or ticket.service_id or ticket.service_family_id):







                    ticket.operating_unit_id = ou







                # Only auto-fill parent_operating_unit_id if not already chosen by user



                if not ticket.parent_operating_unit_id:







                    if ticket.operating_unit_id and ticket.operating_unit_id.parent_unit:







                        ticket.parent_operating_unit_id = ticket.operating_unit_id.parent_unit







                    elif ou:







                        ticket.parent_operating_unit_id = ou.parent_unit if ou.parent_unit else ou







                ticket.grandparent_operating_unit_id = parents[-1] if parents else False







                ticket.parent_operating_unit_ids = self.env["operating.unit"].browse([p.id for p in parents]) if parents else self.env["operating.unit"]







                ticket.operating_unit_hierarchy = " ➔ ".join([c.name for c in chain])















                # Assign distinct hierarchical levels







                if len(chain) >= 4:







                    ticket.branch_operating_unit_id = chain[0]







                    ticket.district_operating_unit_id = chain[1]







                    ticket.directorate_operating_unit_id = chain[2]







                    ticket.executive_operating_unit_id = chain[-1]







                elif len(chain) == 3:







                    ticket.branch_operating_unit_id = False







                    ticket.district_operating_unit_id = chain[0]







                    ticket.directorate_operating_unit_id = chain[1]







                    ticket.executive_operating_unit_id = chain[-1]







                elif len(chain) == 2:







                    ticket.branch_operating_unit_id = False







                    ticket.district_operating_unit_id = False







                    ticket.directorate_operating_unit_id = chain[0]







                    ticket.executive_operating_unit_id = chain[1]







                elif len(chain) == 1:







                    ticket.branch_operating_unit_id = False







                    ticket.district_operating_unit_id = False







                    ticket.directorate_operating_unit_id = False







                    ticket.executive_operating_unit_id = chain[0]







            else:







                # Do NOT clear parent_operating_unit_id when operating_unit_id is empty



                ticket.grandparent_operating_unit_id = False







                ticket.parent_operating_unit_ids = self.env["operating.unit"]







                ticket.operating_unit_hierarchy = False







                ticket.branch_operating_unit_id = False







                ticket.district_operating_unit_id = False







                ticket.directorate_operating_unit_id = False







                ticket.executive_operating_unit_id = False















    @api.depends("operating_unit_id")







    def _compute_operating_unit_user_ids(self):







        """







        Compute users belonging to the ticket's responsible division (operating_unit_id).







        No fallback to all users ? if the division is unset or has no members, returns empty.







        """







        for ticket in self:







            ou = ticket.operating_unit_id







            if not ou:







                ticket.operating_unit_user_ids = self.env["res.users"]







                continue







            # 1. Users directly on the OU record (many2many, stored)







            direct_users = ou.user_ids.filtered(lambda u: not u.share and u.active)







            # 2. Users linked via hr.employee stored OU fields







            emp_users = self.env["hr.employee"].sudo().search([







                ("active", "=", True),







                ("user_id", "!=", False),







                ("user_id.active", "=", True),







                ("user_id.share", "=", False),







                "|",







                ("default_operating_unit_id", "=", ou.id),







                ("operating_unit_ids", "in", ou.id),







            ]).mapped("user_id")







            # 3. Users directly assigned to this OU in res.users (stored fields)







            users_in_ou = self.env["res.users"].sudo().search([







                ("active", "=", True),







                ("share", "=", False),







                "|",







                ("default_operating_unit_id", "=", ou.id),







                ("assigned_operating_unit_ids", "in", ou.id),







            ])







            all_users = (direct_users | emp_users | users_in_ou).filtered(







                lambda u: not u.share and u.active







            )







            ticket.operating_unit_user_ids = all_users















    @api.onchange("parent_operating_unit_id")







    def _onchange_parent_operating_unit_id(self):



        if self.parent_operating_unit_id:



            children = self.env["operating.unit"].search([



                "|", ("parent_unit", "=", self.parent_operating_unit_id.id),



                ("id", "=", self.parent_operating_unit_id.id)



            ])



            # Keep operating_unit_id if it's already part of the chosen hierarchy



            if self.operating_unit_id:



                curr = self.operating_unit_id



                is_valid = False



                visited = set()



                while curr and curr.id not in visited:



                    visited.add(curr.id)



                    if curr.id == self.parent_operating_unit_id.id:



                        is_valid = True



                        break



                    curr = curr.parent_unit



                if not is_valid and self.operating_unit_id not in children:



                    self.operating_unit_id = False



            return {"domain": {"operating_unit_id": ["|", ("parent_unit", "=", self.parent_operating_unit_id.id), ("id", "=", self.parent_operating_unit_id.id)]}}



        else:



            return {"domain": {"operating_unit_id": []}}







    @api.onchange("operating_unit_id")



    def _onchange_operating_unit_id(self):







        if self.operating_unit_id:







            if self.operating_unit_id.parent_unit and not self.parent_operating_unit_id:







                self.parent_operating_unit_id = self.operating_unit_id.parent_unit







            elif not self.parent_operating_unit_id:







                self.parent_operating_unit_id = self.operating_unit_id







            self._compute_parent_operating_units()







            self._compute_operating_unit_user_ids()







            if self.user_id and self.user_id not in self.operating_unit_user_ids:







                self.user_id = False







            creator_emp_id = self._default_contact_center_agent_id()







            if self.contact_center_agent_id and self.contact_center_agent_id._origin not in self.contact_center_agent_ids._origin and self.contact_center_agent_id.id not in self.contact_center_agent_ids.ids:







                if not (creator_emp_id and (self.contact_center_agent_id.id == creator_emp_id or self.contact_center_agent_id._origin.id == creator_emp_id)):







                    self.contact_center_agent_id = False







            if not self.contact_center_agent_id and creator_emp_id:







                self.contact_center_agent_id = creator_emp_id







            if not self.team_id or self.team_id.operating_unit_id != self.operating_unit_id:







                matching_team = self.env["helpdesk.ticket.team"].search([







                    ("operating_unit_id", "=", self.operating_unit_id.id)







                ], limit=1)







                if matching_team:







                    self.team_id = matching_team.id







            # Only reset service / sub-service if they truly do not belong to the OU hierarchy



            if self.service_id and self.service_id.operating_unit_id:



                allowed_ous = {self.operating_unit_id.id}



                if self.parent_operating_unit_id:



                    allowed_ous.add(self.parent_operating_unit_id.id)



                if self.parent_operating_unit_ids:



                    allowed_ous.update(self.parent_operating_unit_ids.ids)



                # Also allow child units under operating_unit_id or parent_operating_unit_id



                child_ous = self.env["operating.unit"].search([



                    "|", ("parent_unit", "=", self.operating_unit_id.id),



                    ("parent_unit", "=", self.parent_operating_unit_id.id if self.parent_operating_unit_id else 0)



                ])



                allowed_ous.update(child_ous.ids)



                if self.service_id.operating_unit_id.id not in allowed_ous:



                    self.service_id = False



                    self.service_sub_category_id = False







            if self.service_family_id:







                has_matching_service = self.env["helpdesk.service"].search_count([







                    ("family_id", "=", self.service_family_id.id),







                    ("operating_unit_id", "=", self.operating_unit_id.id),







                ])







                if self.service_family_id.operating_unit_id and self.service_family_id.operating_unit_id != self.operating_unit_id:







                    self.service_family_id = False







                    self.service_id = False







                    self.service_sub_category_id = False







                elif not self.service_family_id.operating_unit_id and not has_matching_service:







                    self.service_family_id = False







                    self.service_id = False







                    self.service_sub_category_id = False







            self._compute_kb_article_id()







            return {"domain": {"user_id": [("share", "=", False), ("id", "in", self.operating_unit_user_ids.ids)]}}







        else:







            self.operating_unit_user_ids = self.env["res.users"]







            self.user_id = False







            # NEVER clear parent_operating_unit_id here; the user may have chosen Service Provider first!



            self.grandparent_operating_unit_id = False







            self.parent_operating_unit_ids = False







            self.operating_unit_hierarchy = False







            return {"domain": {"user_id": [("id", "=", 0)]}}















    @api.onchange("user_id")







    def _onchange_user_id(self):







        if self.user_id:







            emp = self.env["hr.employee"].sudo().search([("user_id", "=", self.user_id.id)], limit=1)







            ou = (emp.default_operating_unit_id if emp else False) or getattr(self.user_id, "default_operating_unit_id", False)







            if ou and (not self.operating_unit_id or self.operating_unit_id != ou):







                self.operating_unit_id = ou







                self._onchange_operating_unit_id()















            if getattr(self.user_id, "is_on_leave", False):







                status_desc = self.user_id.leave_status_text or _("on leave")







                return {







                    "warning": {







                        "title": _("⚠️ Assigned Agent is Currently on Leave!"),







                        "message": _(







                            "Notice: %s is currently %s.\n\n"







                            "Assigning this ticket to an absent agent may delay customer resolution and lead to SLA/OLA breaches.\n"







                            "Please verify or consider assigning an active team member."







                        ) % (self.user_id.name, status_desc),







                    }







                }















    @api.onchange("branch_operating_unit_id")







    def _onchange_branch_operating_unit_id(self):







        if self.branch_operating_unit_id:







            self.operating_unit_id = self.branch_operating_unit_id







            self._onchange_operating_unit_id()















    @api.onchange("district_operating_unit_id")







    def _onchange_district_operating_unit_id(self):







        if self.district_operating_unit_id and not self.branch_operating_unit_id:







            self.operating_unit_id = self.district_operating_unit_id







            self._onchange_operating_unit_id()















    @api.onchange("directorate_operating_unit_id")







    def _onchange_directorate_operating_unit_id(self):







        if self.directorate_operating_unit_id and not self.branch_operating_unit_id and not self.district_operating_unit_id:







            self.operating_unit_id = self.directorate_operating_unit_id







            self._onchange_operating_unit_id()















    @api.onchange("executive_operating_unit_id")







    def _onchange_executive_operating_unit_id(self):







        if self.executive_operating_unit_id and not self.operating_unit_id:







            self.operating_unit_id = self.executive_operating_unit_id







            self._onchange_operating_unit_id()















    @api.onchange("service_family_id")







    def _onchange_service_family_id(self):







        if self.service_family_id:







            if self.service_id and self.service_id.family_id != self.service_family_id:







                self.service_id = False







                self.service_sub_category_id = False







            if self.service_family_id.operating_unit_id:







                self.operating_unit_id = self.service_family_id.operating_unit_id







                self._onchange_operating_unit_id()







        else:







            self.service_id = False







            self.service_sub_category_id = False







            self._onchange_operating_unit_id()







        self._compute_kb_article_id()







        self._update_ticket_title_if_auto()















    @api.onchange("service_id")







    def _onchange_service_id(self):



        if self.service_id:



            srv = self.service_id



            if srv.family_id and self.service_family_id != srv.family_id:



                self.service_family_id = srv.family_id



            if self.service_sub_category_id and self.service_sub_category_id.service_id != srv:



                self.service_sub_category_id = False



            ou = srv.operating_unit_id or (srv.family_id and srv.family_id.operating_unit_id)



            if ou and (not self.operating_unit_id or self.operating_unit_id != ou):



                self.operating_unit_id = ou



            parent_ou = getattr(srv, "parent_operating_unit_id", False) or (self.operating_unit_id and self.operating_unit_id.parent_unit) or self.operating_unit_id



            if parent_ou and not self.parent_operating_unit_id:



                self.parent_operating_unit_id = parent_ou



            if self.operating_unit_id:



                self._compute_parent_operating_units()



                self._compute_operating_unit_user_ids()



            if srv.responsible_team_id:



                self.team_id = srv.responsible_team_id



            elif self.operating_unit_id:



                matching_team = self.env["helpdesk.ticket.team"].search([



                    ("operating_unit_id", "=", self.operating_unit_id.id)



                ], limit=1)



                if matching_team:



                    self.team_id = matching_team



        else:



            self.service_sub_category_id = False



        self._compute_kb_article_id()



        self._update_ticket_title_if_auto()







    @api.onchange("service_sub_category_id")



    def _onchange_service_sub_category_id(self):







        if self.service_sub_category_id:



            sub = self.service_sub_category_id



            # 1. ALWAYS populate service_id automatically from selected subservice



            if sub.service_id:



                self.service_id = sub.service_id



                if sub.service_id.family_id:



                    self.service_family_id = sub.service_id.family_id







            # 2. Populate Sub Service Provider (operating_unit_id)



            sub_ou = sub.operating_unit_id or (sub.service_id and sub.service_id.operating_unit_id)



            if sub_ou and (not self.operating_unit_id or self.operating_unit_id != sub_ou):



                self.operating_unit_id = sub_ou







            # 3. Populate Service Provider (parent_operating_unit_id)



            parent_ou = (



                sub.parent_operating_unit_id



                or (sub.service_id and getattr(sub.service_id, "parent_operating_unit_id", False))



                or (self.operating_unit_id and self.operating_unit_id.parent_unit)



                or self.operating_unit_id



            )



            if parent_ou and (not self.parent_operating_unit_id or self.parent_operating_unit_id != parent_ou):



                self.parent_operating_unit_id = parent_ou







            if self.operating_unit_id:



                self._compute_parent_operating_units()



                self._compute_operating_unit_user_ids()







            if sub.default_priority:



                self.priority = sub.default_priority







            team = sub.responsible_team_id or (sub.service_id and sub.service_id.responsible_team_id)



            if not team and self.operating_unit_id:



                team = self.env["helpdesk.ticket.team"].search([



                    ("operating_unit_id", "=", self.operating_unit_id.id)



                ], limit=1)



            if team:



                self.team_id = team







        self._compute_kb_article_id()



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







        if self.team_id:







            if self.operation_id and self.operation_id.team_id != self.team_id:







                self.operation_id = False







            if self.operating_unit_id:







                self._compute_operating_unit_user_ids()







                if self.user_id and self.user_id not in self.operating_unit_user_ids:







                    self.user_id = False















    def action_lookup_cbs_account(self):







        """Lookup customer profile from Core Banking (CBS / Finacle) or CRM."""







        self.ensure_one()







        phone_val = (self.partner_phone or "").strip() or (self.partner_phone_secondary or "").strip()







        account_val = (self.account_number or "").strip()







        phone_filled_no_account = bool(phone_val and not account_val)















        query_val = (







            self.account_number







            or self.cif_number







            or self.fayda_number







            or self.partner_phone







            or self.partner_phone_secondary







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







        elif (self.partner_phone and self.partner_phone.strip() == q) or (self.partner_phone_secondary and self.partner_phone_secondary.strip() == q):







            id_type = "phone"















        partner, msg = self._lookup_and_apply_cbs(q, id_type)















        if partner:







            vals = self._apply_customer_profile(partner)







            if phone_filled_no_account and not partner.account_number:







                vals["customer_status"] = "new"







                vals["customer_type"] = "external"







                self.customer_status = "new"







                self.customer_type = "external"







            self.sudo().write(vals)







            self._sync_customer_type_id()







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







                    "next": {"type": "ir.actions.client", "tag": "reload"},







                },







            }







        else:







            self.cbs_lookup_status = "not_found"







            if phone_filled_no_account:







                vals = {







                    "customer_status": "new",







                    "customer_type": "external",







                    "cbs_lookup_status": "not_found",







                }







                self.customer_status = "new"







                self.customer_type = "external"







                self.sudo().write(vals)







                self._sync_customer_type_id()







                return {







                    "type": "ir.actions.client",







                    "tag": "display_notification",







                    "params": {







                        "title": _("Finacle CBS Lookup"),







                        "message": _("No Core Banking account found for phone %s. Customer status set to New Customer / Prospect (External Customer).") % phone_val,







                        "type": "info",







                        "sticky": False,







                        "next": {"type": "ir.actions.client", "tag": "reload"},







                    },







                }







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







        """Synthesize agent caller notes into clean, readable plain text ticket description."""







        self.ensure_one()







        sections = []







        if self.inquiry_summary:







            sections.append(f"Customer Issue Summary: {self.inquiry_summary.strip()}")







        if self.customer_request_details:







            sections.append(f"Inquiry / Request Details:\n{self.customer_request_details.strip()}")







        if self.agent_action_taken:







            sections.append(f"Initial Agent Response / Guidance:\n{self.agent_action_taken.strip()}")







        if self.escalated_agent_response:







            sections.append(f"Escalated Agent Response:\n{self.escalated_agent_response.strip()}")







        if sections:







            formatted_text = "\n\n".join(sections)







            current = (self.description or "").strip()







            # Clean any legacy raw html tags from current description







            clean_current = re.sub(r'<[^>]+>', '\n', current).strip()







            clean_current = re.sub(r'\n{3,}', '\n\n', clean_current)















            if clean_current:







                self.description = f"{clean_current}\n\n{formatted_text}"







            else:







                self.description = formatted_text















            return {







                "type": "ir.actions.client",







                "tag": "display_notification",







                "params": {







                    "title": _("Inquiry Structured"),







                    "message": _("Formatted inquiry details appended as plain text."),







                    "type": "success",







                    "sticky": False,







                },







            }















    def action_assign_contact_center_agent_to_me(self):







        """Assign current user's employee as the Contact Center / Frontline Agent."""







        self.ensure_one()







        emp = self.env["hr.employee"].sudo().search([("user_id", "=", self.env.uid)], limit=1)







        if emp:







            self.contact_center_agent_id = emp







        return True















    def action_load_kb_sop_to_notes(self):







        """Pull Knowledge Base Article response / guidelines directly into Agent Response."""







        self.ensure_one()







        sop_text = ""







        article_title = ""















        if self.kb_article_id:







            sop_text = self.kb_article_id.agent_response or self.kb_article_id.content or ""







            article_title = self.kb_article_id.name







        elif self.service_sub_category_id and self.service_sub_category_id.resolution_sop:







            sop_text = self.service_sub_category_id.resolution_sop







            article_title = self.service_sub_category_id.name







        else:







            # Auto-search matching Knowledge Base article







            domain = [("state", "=", "published")]







            if self.service_sub_category_id:







                domain.append(("sub_category_id", "=", self.service_sub_category_id.id))







            elif self.service_id:







                domain.append(("service_id", "=", self.service_id.id))







            elif self.service_family_id:







                domain.append(("service_family_id", "=", self.service_family_id.id))















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







                    "message": _("No matching Knowledge Base response found. Please select an article or enter guidance."),







                    "type": "warning",







                    "sticky": False,







                },







            }















        # Convert HTML content to clean plain text for agent response







        clean_text = tools.html2plaintext(sop_text).strip()







        existing_text = self.escalated_agent_response if self.is_escalated else self.agent_action_taken







        formatted_notes = f"--- [KB: {article_title}] ---\n{clean_text}" if existing_text else clean_text















        if self.is_escalated:







            if self.escalated_agent_response:







                self.escalated_agent_response = self.escalated_agent_response + "\n\n" + formatted_notes







            else:







                self.escalated_agent_response = formatted_notes







        else:







            if self.agent_action_taken:







                self.agent_action_taken = self.agent_action_taken + "\n\n" + formatted_notes







            else:







                self.agent_action_taken = formatted_notes















        return {







            "type": "ir.actions.client",







            "tag": "display_notification",







            "params": {







                "title": _("Response Loaded from Knowledge Base"),







                "message": _("Knowledge Base response loaded into %s.") % (_("Escalated Agent Response") if self.is_escalated else _("Agent Response")),







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















        if self.is_escalated and self.escalated_agent_response:







            action_html = tools.html_escape(self.escalated_agent_response.strip()).replace("\n", "<br/>")







            content_parts.append(f"<h3>Escalated Specialist Resolution</h3><p>{action_html}</p>")







            if self.agent_action_taken:







                escalater_html = tools.html_escape(self.agent_action_taken.strip()).replace("\n", "<br/>")







                content_parts.append(f"<h3>Initial Agent Response (Escalater)</h3><p>{escalater_html}</p>")







        elif self.agent_action_taken:







            action_html = tools.html_escape(self.agent_action_taken).replace("\n", "<br/>")







            content_parts.append(f"<h3>Standard Resolution Steps / Guidance</h3><p>{action_html}</p>")







        elif self.description:







            content_parts.append(f"<h3>Resolution Description</h3>{self.description}")















        if not content_parts:







            raise UserError(_("Please enter Action Taken / Resolution Notes before publishing to Knowledge Base."))















        meta_info = f"<hr/><p><small><em>Authored from Ticket {self.display_name} on {fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</em></small></p>"







        full_content = "".join(content_parts) + meta_info















        author_user = self.user_id or self.env.user







        emp = self.env["hr.employee"].sudo().search([("user_id", "=", author_user.id)], limit=1)







        authoring_ou = self.operating_unit_id or (emp.default_operating_unit_id if emp else False)















        res_agent_response = (self.escalated_agent_response if self.is_escalated and self.escalated_agent_response else self.agent_action_taken) or ""















        article = self.env["helpdesk.knowledge.article"].create({







            "name": title,







            "agent_response": res_agent_response.strip(),







            "service_family_id": self.service_family_id.id if self.service_family_id else False,







            "service_id": self.service_id.id if self.service_id else False,







            "sub_category_id": self.service_sub_category_id.id if self.service_sub_category_id else False,







            "operating_unit_id": authoring_ou.id if authoring_ou else False,







            "tag_ids": [(6, 0, self.tag_ids.ids)] if self.tag_ids else False,







            "author_id": author_user.id,







            "content": full_content,







            "state": "published",







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







                (_("Document"), f'"{self.display_name}" ({_("Helpdesk Ticket")})'),







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







                (_("Document"), f'"{self.display_name}" ({_("Helpdesk Ticket")})'),







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















    @api.depends_context("uid")







    @api.depends("create_uid")







    def _compute_is_creator_viewing(self):







        uid = self.env.uid







        for ticket in self:







            ticket.is_creator_viewing = ticket.create_uid.id == uid















    @api.depends_context("uid")







    @api.depends("create_uid", "contact_center_agent_id", "is_rejected", "stage_id.name")







    def _compute_can_act_on_rejected(self):







        uid = self.env.uid







        for ticket in self:







            cc_user = ticket.sudo().contact_center_agent_id.user_id if ticket.contact_center_agent_id else False







            is_creator = (







                ticket.create_uid.id == uid







                or (cc_user and cc_user.id == uid)







                or self.env.user.has_group("bunna_helpdesk.group_helpdesk_manager")







                or self.env.is_admin()







            )







            is_rejected_stage = bool(ticket.stage_id and "reject" in (ticket.stage_id.name or "").lower())







            ticket.can_act_on_rejected = is_creator and (ticket.is_rejected or is_rejected_stage)















    @api.depends("stage_id.name", "closed", "is_rejected")







    def _compute_is_closed_or_resolved(self):







        for ticket in self:







            stage_name = (ticket.stage_id.name or "").lower() if ticket.stage_id else ""







            ticket.is_closed_or_resolved = (







                ticket.closed







                or ticket.is_rejected







                or any(term in stage_name for term in ("cancel", "reject", "done", "resolved", "close"))







            )















    @api.depends("stage_id.name", "stage_id.closed")



    def _compute_is_resolved(self):



        for ticket in self:



            stage_name = (ticket.stage_id.name or "").lower() if ticket.stage_id else ""



            ticket.is_resolved = (



                not ticket.stage_id.closed



                and any(w in stage_name for w in ("resolve", "resolved"))



            )















    @api.depends_context("uid")



    @api.depends("is_escalated", "user_id", "is_ceo_escalated", "closed", "is_rejected", "stage_id.name")



    def _compute_can_escalate(self):



        user = self.env.user



        current_uid = user.id



        is_admin_or_mgr = (



            user.has_group("bunna_helpdesk.group_helpdesk_manager")



            or user.has_group("base.group_erp_manager")



            or user.has_group("base.group_system")



            or getattr(user, "helpdesk_role", "") in ("admin", "manager")



            or self.env.is_admin()



        )



        for ticket in self:



            stage_name = (ticket.stage_id.name or "").lower() if ticket.stage_id else ""



            is_creator = ticket.create_uid.id == current_uid



            # Rejected tickets: only creator can escalate to re-route the ticket



            if ticket.is_rejected or any(term in stage_name for term in ("reject",)):



                ticket.can_escalate = is_creator or is_admin_or_mgr



                continue



            if (



                ticket.is_ceo_escalated



                or any(term in stage_name for term in ("cancel",))



            ):



                ticket.can_escalate = False



                continue



            if not ticket.is_escalated:



                ticket.can_escalate = True



            else:



                # Already escalated: current assignee or admin/manager can



                # escalate further — allowing unlimited chain (2nd, 3rd, Nth level).



                ticket.can_escalate = is_admin_or_mgr or bool(ticket.user_id and ticket.user_id.id == current_uid)















    def action_already_escalated(self):







        """No-op action for the disabled 'Escalated' state button."""







        self.ensure_one()







        return False















    def action_open_cancel_wizard(self):







        """Open wizard to enter cancellation reason."""







        self.ensure_one()







        return {







            "name": _("Cancel Ticket"),







            "type": "ir.actions.act_window",







            "res_model": "helpdesk.ticket.cancel.wizard",







            "view_mode": "form",







            "target": "new",







            "context": {







                "default_ticket_id": self.id,







            },







        }















    def action_set_pending(self, reason, notes=""):







        """Move ticket to Pending stage with a captured reason and audit note."""







        self.ensure_one()







        pending_stage = self.env["helpdesk.ticket.stage"].search(







            ["|", ("name", "ilike", "pending"), ("name", "ilike", "in progress"), ("closed", "=", False)], limit=1







        )







        if not pending_stage:







            pending_stage = self.env["helpdesk.ticket.stage"].create({







                "name": "In Progress",







                "sequence": 4,







                "closed": False,







                "fold": False,







            })







        vals = {







            "stage_id": pending_stage.id,







            "pending_reason": str(reason).strip() if reason else "Pending Resolution",







            "pending_reason_details": str(notes).strip() if notes else "",







            "pending_date": fields.Datetime.now(),







        }







        self.write(vals)







        reason_msg = f"<br/>• <strong>Pending Reason:</strong> {reason.strip()}" if reason else ""







        notes_msg = f"<br/>• <strong>Details &amp; Findings:</strong> {notes.strip()}" if notes else ""







        self.message_post(







            body=f"<div><strong>⏸️ Ticket Placed on Pending</strong><br/>"







                 f"• <strong>Updated By:</strong> {self.env.user.name}"







                 f"{reason_msg}{notes_msg}</div>",







            subtype_xmlid="mail.mt_note",







        )







        return True















    def action_open_pending_wizard(self):







        """Open wizard to enter pending reason."""







        self.ensure_one()







        return {







            "name": _("Ticket Pending - Escalated Pending Resolution"),







            "type": "ir.actions.act_window",







            "res_model": "helpdesk.ticket.pending.wizard",







            "views": [[False, "form"]],







            "target": "new",







            "context": {







                "default_ticket_id": self.id,







                "default_target_stage_id": self.stage_id.id,







            },







        }















    def action_cancel_ticket(self, reason=None):







        """Allow users to cancel a ticket with a required reason."""







        cancel_stage = self.env["helpdesk.ticket.stage"].search(







            [("name", "ilike", "cancel")], limit=1







        )







        if not cancel_stage:







            cancel_stage = self.env["helpdesk.ticket.stage"].search(







                [("closed", "=", True)], limit=1







            )







        for ticket in self:







            vals = {}







            if reason:







                vals["cancel_reason"] = str(reason).strip()







            if cancel_stage:







                vals["stage_id"] = cancel_stage.id







            ticket.with_context(bypass_stage_guard=True).write(vals)







            reason_msg = f"<br/>• <strong>Reason:</strong> {reason.strip()}" if reason else ""







            ticket.message_post(







                body=f"<div><strong>🚫 Ticket Cancelled</strong><br/>"







                     f"• <strong>Cancelled By:</strong> {self.env.user.name}"







                     f"{reason_msg}</div>",







                subtype_xmlid="mail.mt_note",







                body_is_html=True,







            )







        return True















    def action_open_reopen_wizard(self):







        """Open wizard to enter reopen reason."""







        self.ensure_one()







        return {







            "name": _("Reopen Ticket"),







            "type": "ir.actions.act_window",







            "res_model": "helpdesk.ticket.reopen.wizard",







            "view_mode": "form",







            "target": "new",







            "context": {







                "default_ticket_id": self.id,







            },







        }















    def action_open_escalate_wizard(self):







        """Open the Hierarchical Escalation Wizard."""







        self.ensure_one()







        stage_name = (self.stage_id.name or "").lower() if self.stage_id else ""







        is_rejected_ticket = self.is_rejected or any(term in stage_name for term in ("reject",))







        is_resolved_ticket = any(term in stage_name for term in ("resolve", "resolved", "done"))







        is_closed_ticket = self.closed or (self.stage_id and self.stage_id.closed) or any(term in stage_name for term in ("close", "closed"))







        if is_resolved_ticket:







            raise UserError(_("Ticket '%s' is marked as Resolved. You must first Reopen the ticket before it can be escalated.") % (self.number or self.name))







        if is_closed_ticket:







            raise UserError(_("Ticket '%s' is Closed. You must first Reopen the ticket before it can be escalated.") % (self.number or self.name))







        if is_rejected_ticket:







            raise UserError(_("Ticket '%s' is Rejected. You must first Reopen the ticket before it can be escalated.") % (self.number or self.name))







        if any(term in stage_name for term in ("cancel", "cancelled")):







            raise UserError(_("Ticket '%s' is Cancelled. You must first Reopen the ticket before it can be escalated.") % (self.number or self.name))







        user = self.env.user



        is_admin_or_mgr = (



            user.has_group("bunna_helpdesk.group_helpdesk_manager")



            or user.has_group("base.group_erp_manager")



            or user.has_group("base.group_system")



            or getattr(user, "helpdesk_role", "") in ("admin", "manager")



            or self.env.is_admin()



        )







        if not self.can_escalate and not self.can_act_on_rejected and not is_admin_or_mgr:







            if self.is_escalated and self.user_id and self.user_id.id == self.env.uid:



                # Current assignee on an escalated ticket is always allowed to escalate further



                pass







            else:







                raise UserError(_("You are not eligible to escalate this ticket."))







        current_role = (self.user_id.helpdesk_role if self.user_id else False) or getattr(self.env.user, "helpdesk_role", False) or ""







        default_type = "back_line"







        if current_role in ("contact_center", "support"):







            default_type = "front_line"







        elif not self.user_id or current_role in ("front_line", "frontend", "officer"):







            default_type = "back_line"







        elif current_role in ("back_line", "backend", "senior_principal", "fullstack", "database", "qa"):







            default_type = "team_leader"







        elif current_role in ("team_leader", "supervisor", "manager"):







            default_type = "directorate"







        elif current_role in ("directorate", "director"):







            default_type = "deputy_chief"







        elif current_role in ("deputy_chief", "deputy_cto"):







            default_type = "chief"







        elif current_role in ("chief", "cido"):







            default_type = "ceo"















        return {







            "name": _("Escalate Ticket"),







            "type": "ir.actions.act_window",







            "res_model": "helpdesk.ticket.escalate.wizard",







            "view_mode": "form",







            "views": [(False, "form")],







            "target": "new",







            "context": {







                "active_id": self.id,







                "default_ticket_id": self.id,







                "default_escalation_type": default_type,







            },







        }















    def action_open_escalate_level_3_wizard(self):







        """Open the Executive / Directorate Escalation Wizard."""







        self.ensure_one()







        return {







            "name": _("Escalate Ticket to Directorate / Deputy Chief"),







            "type": "ir.actions.act_window",







            "res_model": "helpdesk.ticket.escalate.wizard",







            "view_mode": "form",







            "views": [(False, "form")],







            "target": "new",







            "context": {







                "default_ticket_id": self.id,







                "default_escalation_type": "directorate",







            },







        }















    def action_open_escalate_chief_wizard(self):







        """Open the Chief Escalation Wizard."""







        self.ensure_one()







        return {







            "name": _("Escalate Ticket to Chief Officer (C-Level / CIDO)"),







            "type": "ir.actions.act_window",







            "res_model": "helpdesk.ticket.escalate.wizard",







            "view_mode": "form",







            "views": [(False, "form")],







            "target": "new",







            "context": {







                "default_ticket_id": self.id,







                "default_escalation_type": "chief",







            },







        }















    def action_open_escalate_ceo_wizard(self):







        """Open the CEO Escalation Wizard."""







        self.ensure_one()







        return {







            "name": _("Escalate Ticket to Chief Executive Officer (CEO)"),







            "type": "ir.actions.act_window",







            "res_model": "helpdesk.ticket.escalate.wizard",







            "view_mode": "form",







            "views": [(False, "form")],







            "target": "new",







            "context": {







                "default_ticket_id": self.id,







                "default_escalation_type": "ceo",







            },







        }















    def _get_current_escalation_employee(self):







        """







        Identify the hr.employee record of the current escalation recipient / assignee







        responsible for escalating the ticket to the next level.







        """







        self.ensure_one()







        emp_obj = self.env["hr.employee"].sudo()







        if self.user_id:







            emp = emp_obj.search([("user_id", "=", self.user_id.id)], limit=1)







            if emp:







                return emp







        if self.escalated_to_user_id:







            emp = emp_obj.search([("user_id", "=", self.escalated_to_user_id.id)], limit=1)







            if emp:







                return emp







        cc_agent = self.sudo().contact_center_agent_id







        if cc_agent:







            return cc_agent







        if self.create_uid and not self.create_uid.share:







            emp = emp_obj.search([("user_id", "=", self.create_uid.id)], limit=1)







            if emp:







                return emp







        return emp_obj.search([("user_id", "=", self.env.user.id)], limit=1)















    def _get_manager_escalation_target(self, current_emp, escalation_type):







        """







        Determine the eligible next manager through the organizational reporting hierarchy (parent_id)







        from Team Leader upwards:







        - Team Leader -> Director: Director must be the team leader's direct manager.







        - Director -> Chief: Chief must be the director's direct manager.







        - Chief -> Higher Manager (CEO): Higher manager must be the chief's direct manager (or top of hierarchy).







        - Direct Bypass (team_leader_to_deputy_chief): 2nd-level manager of the team leader.















        Returns: (manager_emp, manager_user, manager_rel_string, error_message)







        """







        MANAGER_STAGES = {







            "directorate": "Director",







            "director": "Director",







            "other_directorate": "Director",







            "deputy_chief": "Deputy Chief / Chief",







            "chief": "Chief",







            "other_deputy_chief_chief": "Chief",







            "ceo": "Higher-Level Manager (CEO)",







            "other_ceo": "Higher-Level Manager (CEO)",







            "team_leader_to_deputy_chief": "Deputy Chief (Direct Bypass)",







        }







        if escalation_type not in MANAGER_STAGES:







            return None, None, "", None















        stage_title = MANAGER_STAGES[escalation_type]















        if not current_emp:







            return None, None, "", _("Cannot identify the current assignee's employee record in the HR organizational hierarchy.")















        target_emp = False







        rel = ""















        if escalation_type in ("directorate", "director", "other_directorate"):







            is_tl = getattr(current_emp.user_id, "helpdesk_role", "") in ("team_leader", "manager", "supervisor", "admin") or (self.escalation_level or 0) >= 3







            if is_tl or not current_emp.parent_id or not current_emp.parent_id.parent_id:







                target_emp = current_emp.parent_id







                rel = f"Director: Direct organizational manager of Team Leader '{current_emp.name}'"







            else:







                target_emp = current_emp.parent_id.parent_id







                rel = f"Director: Manager of Team Leader '{current_emp.parent_id.name}' (reporting manager of '{current_emp.name}')"















            if not target_emp:







                return None, None, "", _("Cannot escalate to Director: Employee '%s' does not have a reporting manager assigned in the organizational hierarchy.") % current_emp.name















        elif escalation_type in ("deputy_chief", "chief", "other_deputy_chief_chief", "team_leader_to_deputy_chief"):







            is_dir = getattr(current_emp.user_id, "helpdesk_role", "") in ("directorate", "director") or (self.escalation_level or 0) >= 4







            is_tl = getattr(current_emp.user_id, "helpdesk_role", "") in ("team_leader", "manager", "supervisor", "admin")







            if is_dir:







                target_emp = current_emp.parent_id







                rel = f"Chief: Direct organizational manager of Director '{current_emp.name}'"







            elif is_tl and current_emp.parent_id:







                target_emp = current_emp.parent_id.parent_id or current_emp.parent_id







                dir_name = current_emp.parent_id.name







                rel = f"Chief: Manager of Director '{dir_name}' (reporting manager of Team Leader '{current_emp.name}')"







            else:







                curr = current_emp







                for _i in range(3):







                    if curr and curr.parent_id:







                        curr = curr.parent_id







                target_emp = curr or current_emp.parent_id







                rel = f"Chief: Higher-level manager in organizational reporting hierarchy from '{current_emp.name}'"















            if not target_emp:







                return None, None, "", _("Cannot escalate to Chief: Employee '%s' does not have a reporting manager assigned in the organizational hierarchy.") % current_emp.name















        elif escalation_type in ("ceo", "other_ceo"):







            curr = current_emp







            chain = [curr]







            while curr and curr.parent_id:







                curr = curr.parent_id







                chain.append(curr)







            if len(chain) > 1:







                target_emp = chain[-1]







                via_name = chain[-2].name if len(chain) > 2 else current_emp.name







                rel = f"Higher-Level Manager (CEO): Top executive in reporting chain from '{current_emp.name}' via '{via_name}'"







            else:







                target_emp = False







                rel = ""















            if not target_emp:







                return None, None, "", _("Cannot escalate to Higher-Level Manager: Employee '%s' has no higher-level manager in the organizational hierarchy.") % current_emp.name















        elif escalation_type == "team_leader_to_deputy_chief":







            p1 = current_emp.parent_id







            p2 = p1.parent_id if p1 else False







            target_emp = p2







            if not target_emp:







                return None, None, "", _("Cannot escalate via direct bypass: Team Leader '%s' does not have a 2nd-level manager (Deputy Chief) in the organizational hierarchy.") % current_emp.name







            rel = f"Deputy Chief (Direct Bypass): Manager of Director '{p1.name}' from Team Leader '{current_emp.name}'"















        if not target_emp.user_id:







            return None, None, "", _("Cannot escalate to %s: Manager '%s' has no linked Odoo user account.") % (stage_title, target_emp.name)







        if not target_emp.user_id.active:







            return None, None, "", _("Cannot escalate to %s: Manager '%s' user account is inactive.") % (stage_title, target_emp.name)















        return target_emp, target_emp.user_id, rel, None















    def action_perform_hierarchical_escalation(







        self,







        escalation_type="manager",







        target_user_id=None,







        target_team_id=None,







        target_operating_unit_id=None,







        reason=None,







        escalation_journey=None,







    ):







        """







        Unified multi-level hierarchical escalation engine (Bunna Journey Map):







        - Left Track: Contact Center ➔ Front line ➔ Back line ➔ Team Leader ➔ Directorate ➔ Deputy Chief ➔ Chief ➔ CEO







          (plus Team Leader ➔ Deputy Chief direct bypass option)







        - Bridge & Right Track: Other Workunit ➔ Officer ➔ Senior/Principal ➔ Manager/Team Leader ➔ Directorate ➔ Deputy Chief/Chief ➔ CEO







        """







        self.ensure_one()







        from datetime import timedelta







        now = fields.Datetime.now()















        level_map = {







            # Left Track: Primary Helpdesk Escalation Journey







            "contact_center_front_line": (1, _("Contact Center Front Line"), False, False),







            "contact_center_back_line": (2, _("Contact Center Backline"), False, False),







            "contact_center_team_leader": (3, _("Contact Center Team Leader"), False, False),







            "contact_center_director": (4, _("Contact Center Director"), True, False),







            "contact_center": (1, _("Contact Center (Tier 1)"), False, False),







            "front_line": (1, _("Front line (Team) Escalation"), False, False),







            "back_line": (2, _("Back line (Team) Escalation"), False, False),







            "team_leader": (3, _("Team Leader Escalation (Level 3)"), False, False),







            "directorate": (4, _("Directorate Director Escalation (Level 4)"), True, False),







            "team_leader_to_deputy_chief": (5, _("Deputy Chief Escalation (Direct from Team Leader)"), True, False),







            "deputy_chief": (5, _("Deputy Chief Escalation (Level 5)"), True, False),







            "chief": (6, _("Chief Officer Escalation (Level 6)"), True, False),







            "ceo": (7, _("Chief Executive Officer (CEO) Escalation (Level 7)"), True, True),















            # Bridge & Right Track: Other Workunit Escalation Journey







            "other_work": (2, _("Other Workunit Transfer Escalation"), False, False),







            "other_officer": (2, _("Other Workunit Officer Escalation"), False, False),







            "other_senior_principal": (3, _("Other Workunit Senior/Principal Escalation"), False, False),







            "other_manager_team_leader": (3, _("Other Workunit Manager/Team Leader Escalation"), False, False),







            "other_directorate": (4, _("Other Workunit Directorate Escalation"), True, False),







            "other_deputy_chief_chief": (5, _("Other Workunit Deputy Chief/Chief Escalation"), True, False),







            "other_ceo": (7, _("Other Workunit CEO Escalation"), True, True),















            # Legacy / Alias compatibility







            "peer_backend": (2, _("Peer Escalation (Frontend → Backend Specialist)"), False, False),







            "line_manager": (3, _("Division Manager Escalation (Level 3)"), False, False),







            "manager": (3, _("Manager / Team Leader Escalation"), False, False),







            "director": (4, _("Directorate Director Escalation (Level 4)"), True, False),







            "deputy_cto": (5, _("Deputy CTO Escalation (Level 5)"), True, False),







            "cido": (6, _("Chief Information & Digital Officer (CIDO) Escalation (Level 6)"), True, False),







            "team_transfer": (2, _("Work Unit Transfer Escalation"), False, False),







        }







        level_int, level_title, is_lvl3, is_ceo = level_map.get(







            escalation_type,







            ((self.escalation_level or 1) + 1, _("Hierarchical Escalation"), False, False)







        )















        user_rec = self.env["res.users"].browse(target_user_id.id if hasattr(target_user_id, "id") else target_user_id) if target_user_id else False







        team_rec = self.env["helpdesk.ticket.team"].browse(target_team_id.id if hasattr(target_team_id, "id") else target_team_id) if target_team_id else False







        ou_rec = self.env["operating.unit"].browse(target_operating_unit_id.id if hasattr(target_operating_unit_id, "id") else target_operating_unit_id) if target_operating_unit_id else False















        user = self.env.user



        is_admin_or_mgr = (



            user.has_group("bunna_helpdesk.group_helpdesk_manager")



            or user.has_group("base.group_erp_manager")



            or user.has_group("base.group_system")



            or getattr(user, "helpdesk_role", "") in ("admin", "manager")



            or self.env.is_admin()



        )







        # 0. Prevent escalation of cancelled, rejected, done, or closed tickets and duplicate escalations



        stage_name = (self.stage_id.name or "").lower() if self.stage_id else ""



        is_rejected_ticket = self.is_rejected or any(term in stage_name for term in ("reject",))







        # Rejected tickets: only the original creator can re-escalate to re-route



        if is_rejected_ticket:



            if not self.can_act_on_rejected and not is_admin_or_mgr:



                raise UserError(_("Only the ticket creator can escalate a rejected ticket to re-route it."))



        elif any(term in stage_name for term in ("cancel",)):



            raise UserError(_("Cancelled tickets cannot be escalated."))







        if not self.can_escalate and not self.can_act_on_rejected and not is_admin_or_mgr:



            if self.is_escalated and self.user_id and self.user_id.id == self.env.uid:



                # Current assignee on an already-escalated ticket can escalate further (2nd, 3rd, Nth level)



                pass



            else:



                raise UserError(_("You are not eligible to escalate this ticket."))















        # 1. Prevent self-escalation







        cc_agent = self.sudo().contact_center_agent_id







        current_assignee = self.user_id or (cc_agent.user_id if cc_agent else False)







        if user_rec and (user_rec == self.env.user or (current_assignee and user_rec == current_assignee)):







            raise ValidationError(_("Self-escalation is not allowed. A ticket cannot be escalated to yourself or the current assignee."))















        # 1b. Directorate Privilege check: Only users with Directorate privilege can escalate to Deputy Chief / Chief / CEO







        director_only_types = ("deputy_chief", "chief", "ceo", "team_leader_to_deputy_chief", "other_deputy_chief_chief", "other_ceo")







        if escalation_type in director_only_types:







            user = self.env.user







            user_role = getattr(user, "helpdesk_role", "") or ""







            emp_obj = self.env["hr.employee"].sudo()







            user_emp = emp_obj.search([("user_id", "=", user.id)], limit=1)







            emp_role = getattr(user_emp, "helpdesk_role", "") if user_emp and hasattr(user_emp, "helpdesk_role") else ""







            is_dir = (







                user_role in ("directorate", "director")







                or emp_role in ("directorate", "director")







                or (self.user_id and getattr(self.user_id, "helpdesk_role", "") in ("directorate", "director"))







            )







            if not is_dir:







                raise ValidationError(_("Only users with Directorate privilege can escalate to Deputy Chief, Chief Officer, or CEO."))















        # 2. Prevent duplicate escalation







        if self.is_escalated and self.escalated_to_user_id == user_rec and self.escalation_level == level_int:







            raise ValidationError(_("This ticket has already been escalated to '%s' at level %s.") % (user_rec.name, level_int))















        # 3. Manager-Based Hierarchy Validation (Primary Journey Track)







        # In Other Operating Unit track (Cross-Unit Transfer), the ticket is transferred to another







        # unit, so the recipient belongs to the target OU and is NOT required to be the direct HR manager of the transferring agent.







        is_cross_unit = (







            escalation_journey == "other_work_journey"







            or escalation_type.startswith("other_")







            or escalation_type == "team_transfer"







        )







        mgr_rel = ""







        if is_cross_unit:



            if not ou_rec:



                raise ValidationError(_("Please select the Target Responsible Work Unit for cross-unit escalation."))



            if not user_rec:



                raise ValidationError(_("Please select an Assigned User (team member) in the target Work Unit before escalating."))



            if ou_rec and ou_rec != self.operating_unit_id:



                mgr_rel = f"Cross-Unit Transfer: Handover to {ou_rec.name}" 







        if not is_cross_unit or (ou_rec and ou_rec == self.operating_unit_id):







            subordinate_emp = self._get_current_escalation_employee()







            mgr_emp, mgr_user, mgr_rel, mgr_err = self._get_manager_escalation_target(subordinate_emp, escalation_type)







            if mgr_err:







                raise ValidationError(mgr_err)







            if mgr_user:







                if user_rec and user_rec != mgr_user:







                    raise ValidationError(_(







                        "Invalid escalation: '%s' is not the designated manager of '%s' in the organizational hierarchy. "







                        "Escalation to %s must follow the reporting hierarchy and be assigned to '%s'."







                    ) % (user_rec.name, subordinate_emp.name, level_title, mgr_user.name))







                user_rec = mgr_user















        prev_user = self.user_id







        prev_display_name = prev_user.name if prev_user else (







            f"{self.sudo().contact_center_agent_id.name} (Contact Center Agent)"







            if self.sudo().contact_center_agent_id







            else _("Unassigned")







        )







        # Compute OLA deadline







        sdt = self.ola_sdt_hours or (self.service_id.default_sdt_hours if self.service_id else 24.0)







        if is_lvl3:







            sdt = sdt * 1.5







        new_deadline = now + timedelta(hours=sdt)















        vals = {







            "is_escalated": True,







            "is_level_3_escalated": is_lvl3 or self.is_level_3_escalated,







            "is_ceo_escalated": is_ceo or self.is_ceo_escalated,







            "escalation_level": max(self.escalation_level or 0, level_int),







            "escalation_date": now,







            "last_escalation_date": now,







            "escalation_reason": reason or "",







            "ola_status": "in_progress",







            "ola_deadline": new_deadline,







            "escalated_agent_response": False,







        }







        if not self.original_operating_unit_id and self.operating_unit_id:







            vals["original_operating_unit_id"] = self.operating_unit_id.id







        vals["escalation_journey"] = escalation_journey or self.escalation_journey or "primary_journey"















        if ou_rec:







            vals["operating_unit_id"] = ou_rec.id







        elif self.operating_unit_id:







            vals["operating_unit_id"] = self.operating_unit_id.id







        is_primary_track = (vals["escalation_journey"] == "primary_journey")















        if user_rec:







            vals["escalated_to_user_id"] = user_rec.id







            if is_lvl3:







                vals["escalated_to_level_3_user_id"] = user_rec.id















            # Contact Center Agent escalation: update contact_center_agent_id for contact_center stages







            if escalation_type in ("contact_center", "contact_center_front_line", "contact_center_back_line", "contact_center_team_leader", "contact_center_director"):







                emp = self.env["hr.employee"].sudo().search([("user_id", "=", user_rec.id)], limit=1)







                if emp:







                    vals["contact_center_agent_id"] = emp.id















            # Set assigned user to the escalated specialist/manager







            vals["user_id"] = user_rec.id







        if team_rec:







            vals["team_id"] = team_rec.id







            vals["escalated_to_team_id"] = team_rec.id







            if is_lvl3:







                vals["escalated_to_level_3_team_id"] = team_rec.id















        if is_ceo:







            vals["priority"] = "3"  # Critical















        # Set ticket stage to 'Escalated' upon escalation







        escalated_stage = self.env["helpdesk.ticket.stage"].search(







            [("name", "ilike", "escalat"), ("closed", "=", False)], limit=1







        )







        if not escalated_stage:







            escalated_stage = self.env["helpdesk.ticket.stage"].search(







                [("name", "ilike", "progress"), ("closed", "=", False)], limit=1







            )







        if escalated_stage:







            vals["stage_id"] = escalated_stage.id















        # If the ticket was rejected and the creator is now re-routing/escalating it,







        # clear the rejection flags so it returns to active workflow







        if self.is_rejected or (self.stage_id and "reject" in (self.stage_id.name or "").lower()):







            vals["is_rejected"] = False







            vals["rejection_reason"] = False















        cc_agent = self.sudo().contact_center_agent_id







        prev_uid = prev_user.id if prev_user else (cc_agent.user_id.id if (cc_agent and cc_agent.user_id) else False)







        self.with_context(



            skip_ou_user_constraint=True,



            skip_assign_notification=True,



            skip_team_notification=True,



            mail_auto_subscribe_no_notify=True,



        ).write(vals)















        # Log Escalation History Audit Trail







        self.env["helpdesk.ticket.escalation.history"].sudo().create({







            "ticket_id": self.id,







            "escalation_journey": vals["escalation_journey"],







            "original_operating_unit_id": self.original_operating_unit_id.id if self.original_operating_unit_id else (self.operating_unit_id.id if self.operating_unit_id else False),







            "current_operating_unit_id": ou_rec.id if ou_rec else (self.operating_unit_id.id if self.operating_unit_id else False),







            "previous_escalation_level": self.escalation_level or 0,







            "escalation_level": vals["escalation_level"],







            "escalation_type": escalation_type,







            "level_name": level_title,







            "escalated_by_user_id": self.env.user.id,







            "previous_user_id": prev_uid,







            "new_user_id": user_rec.id if user_rec else (team_rec.user_id.id if team_rec and team_rec.user_id else self.env.user.id),







            "escalation_datetime": now,







            "sla_deadline": self.sla_deadline,







            "new_sla_deadline": new_deadline,







            "is_ceo_level": is_ceo,







            "manager_relationship": mgr_rel or "",







            "escalation_status": "escalated",







            "reason": reason or _("%s: Escalated by %s") % (level_title, self.env.user.name),







        })















        # Post Chatter Note







        author_name = self.env.user.name or _("System")







        target_str = user_rec.name if user_rec else (team_rec.name if team_rec else _("Specialist Unit"))







        chatter_msg = (







            f"<div><strong>🚨 Escalated: {level_title}</strong><br/>"







            f"• <strong>Initiated By:</strong> {author_name}<br/>"







            f"• <strong>Previous Assignee:</strong> {prev_display_name}<br/>"







            f"• <strong>New Assignee:</strong> {target_str}<br/>"







            f"• <strong>Reason &amp; Findings:</strong> {reason or _('Requires higher-level intervention')}<br/>"







            f"• <strong>Target OLA Deadline:</strong> {new_deadline.strftime('%Y-%m-%d %H:%M:%S')}</div>"







        )







        self.message_post(body=chatter_msg, subtype_xmlid="mail.mt_note", body_is_html=True)







        # Notify BOTH Front Office and Back Office parties







        recipient = user_rec or (team_rec.user_id if team_rec else False)







        recipients = self.env["res.partner"]







        if recipient and recipient.partner_id:







            recipients |= recipient.partner_id







        if team_rec and team_rec.user_id and team_rec.user_id.partner_id:







            recipients |= team_rec.user_id.partner_id







        if self.create_uid and self.create_uid.partner_id:







            recipients |= self.create_uid.partner_id







        if cc_agent and cc_agent.user_id and cc_agent.user_id.partner_id:







            recipients |= cc_agent.user_id.partner_id







        if self.env.user.partner_id:







            recipients |= self.env.user.partner_id















        items = [







            (_("Document"), f'"{self.display_name}" ({_("Helpdesk Ticket")})'),







            (_("Escalation Stage"), level_title),







            (_("Initiated By"), author_name),







            (_("Previous Assignee"), prev_display_name),







            (_("New Assignee"), target_str),







            (_("Reason"), reason or _("Requires resolution")),







            (_("Service"), self.service_id.name if self.service_id else _("General")),







            (_("OLA Deadline"), str(new_deadline)),







        ]







        target_partner = recipient.partner_id if (recipient and recipient.partner_id) else False







        if target_partner and target_partner in recipients:







            subject_target = _("🚨 [%s] Ticket %s Escalated to You") % (level_title, self.display_name)







            body_target = self._format_ticket_notification_body(







                recipient_name=target_partner.name,







                action_statement=_("%s has escalated this ticket to you for %s") % (author_name, level_title),







                items=items,







            )







            self.message_notify(







                partner_ids=[target_partner.id],







                subject=subject_target,







                body=body_target,







                email_layout_xmlid="mail.mail_notification_light",







            )







            # Direct Chat & Discuss Notification to escalated recipient







            self._send_discuss_chat_notification(







                target_user=recipient,







                title=subject_target,







                items=items,







                author_user=self.env.user,







            )







        other_recipients = recipients - (target_partner if target_partner else self.env["res.partner"])







        if other_recipients:







            subject_others = _("🚨 [%s] Ticket %s Escalated: %s") % (level_title, self.display_name, target_str)







            body_others = self._format_ticket_notification_body(







                recipient_name=_("Team Member"),







                action_statement=_("Ticket %s has been escalated to %s (%s) by %s") % (self.display_name, target_str, level_title, author_name),







                items=items,







            )







            self.message_notify(







                partner_ids=other_recipients.ids,







                subject=subject_others,







                body=body_others,







                email_layout_xmlid="mail.mail_notification_light",







            )







        # ── Trigger Pop-Up Notification for Concerned Person / Work Unit ──



        concerned_user = recipient or self.user_id



        if concerned_user:



            try:



                # 1. Create persistent popup record for desktop / PC webclient startup



                self.env["helpdesk.ticket.escalation.popup"].sudo().create({



                    "ticket_id": self.id,



                    "user_id": concerned_user.id,



                    "escalation_level_name": level_title,



                    "escalated_by_id": self.env.user.id,



                    "escalation_date": now,



                })



            except Exception as e:



                _logger.warning("Could not create escalation popup record: %s", e)







            # 2. Real-time Desktop / Browser bus notification



            if concerned_user.partner_id:



                try:



                    popup_msg = _(



                        "📌 Ticket #: %s\n"



                        "👤 Customer: %s (%s)\n"



                        "🏢 Unit: %s\n"



                        "🚨 Stage: %s\n"



                        "👤 Escalated By: %s\n"



                        "🕒 Date: %s\n"



                        "📝 Issue: %s"



                    ) % (



                        self.number or self.name,



                        self.customer_name or self.partner_name or _("N/A"),



                        self.partner_phone or _("N/A"),



                        self.operating_unit_id.name if self.operating_unit_id else _("Responsible Unit"),



                        level_title,



                        self.env.user.name,



                        now.strftime("%Y-%m-%d %H:%M:%S"),



                        (self.customer_request_details or self.name or "")[:140],



                    )



                    self.env["bus.bus"].sudo()._sendone(



                        concerned_user.partner_id,



                        "simple_notification",



                        {



                            "type": "warning",



                            "title": _("🚨 Action Required: New Ticket Escalated to You!"),



                            "message": popup_msg,



                            "sticky": True,



                        },



                    )



                except Exception as e:



                    _logger.warning("Could not dispatch bus escalation pop-up: %s", e)







            # 3. Schedule Activity for concerned person (top systray red badge)



            try:



                act_type = self.env.ref("mail.mail_activity_data_warning", raise_if_not_found=False) or self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)



                if act_type:



                    self.sudo().activity_schedule(



                        activity_type_id=act_type.id,



                        summary=_("🚨 Escalated Ticket: %s - Requires Attention") % (self.number or self.name),



                        note=_(



                            "<b>New Ticket Escalated to You</b><br/>"



                            "• <b>Ticket:</b> %s<br/>"



                            "• <b>Customer:</b> %s (%s)<br/>"



                            "• <b>Stage:</b> %s<br/>"



                            "• <b>Escalated By:</b> %s<br/>"



                            "• <b>Date:</b> %s<br/>"



                            "• <b>Issue:</b> %s"



                        ) % (



                            self.number or self.name,



                            self.customer_name or self.partner_name or "N/A",



                            self.partner_phone or "N/A",



                            level_title,



                            self.env.user.name,



                            now.strftime("%Y-%m-%d %H:%M:%S"),



                            self.customer_request_details or self.name or "",



                        ),



                        user_id=concerned_user.id,



                        date_deadline=new_deadline.date() if new_deadline else fields.Date.today(),



                    )



            except Exception as e:



                _logger.warning("Could not schedule escalation activity: %s", e)







        return True















    # ── Automatic Hierarchical SLA-Based Escalation ───────────────────────────







    def _get_next_escalation_manager(self):







        """







        Traverse the organizational reporting hierarchy to identify the next manager







        eligible for SLA escalation, progressing up to the CEO level along the Journey Map:







        Contact Center ➔ Front line ➔ Back line ➔ Team Leader ➔ Directorate ➔ Deputy Chief ➔ Chief ➔ CEO







        Returns:







            tuple: (manager_user: res.users, is_ceo: bool, level_title: str, escalation_type: str, level_int: int)







        """







        self.ensure_one()







        if self.is_ceo_escalated:







            return False, True, _("CEO Level"), "ceo", 7















        params = self.env["ir.config_parameter"].sudo()







        ceo_param = params.get_param("bunna_helpdesk.ceo_user_id")







        ceo_user = False







        if ceo_param and str(ceo_param).isdigit():







            ceo_user = self.env["res.users"].sudo().browse(int(ceo_param))







            if not ceo_user.exists() or not ceo_user.active:







                ceo_user = False















        current_user = self.user_id



        if not current_user and self.team_id and self.team_id.user_id:



            current_user = self.team_id.user_id







        # If ticket has no assigned user (unassigned ticket breached SLA):



        # Automatically escalate to the Responsible Unit Manager, Team Leader, or Unit Officer



        if not current_user:



            ou_mgr_user = False



            if self.operating_unit_id:



                if hasattr(self.operating_unit_id, "manager_id") and self.operating_unit_id.manager_id:



                    mgr_emp = self.operating_unit_id.manager_id



                    if hasattr(mgr_emp, "user_id") and mgr_emp.user_id and mgr_emp.user_id.active:



                        ou_mgr_user = mgr_emp.user_id



                if not ou_mgr_user and hasattr(self.operating_unit_id, "user_id") and self.operating_unit_id.user_id and self.operating_unit_id.user_id.active:



                    ou_mgr_user = self.operating_unit_id.user_id







            if not ou_mgr_user and self.team_id and self.team_id.user_id and self.team_id.user_id.active:



                ou_mgr_user = self.team_id.user_id







            if not ou_mgr_user and self.operating_unit_user_ids:



                leaders = self.operating_unit_user_ids.filtered(



                    lambda u: getattr(u, "helpdesk_role", "") in ("team_leader", "manager", "supervisor", "directorate", "director")



                )



                if leaders:



                    ou_mgr_user = leaders[0]



                else:



                    ou_mgr_user = self.operating_unit_user_ids[0]







            if not ou_mgr_user and self.team_id and self.team_id.user_ids:



                ou_mgr_user = self.team_id.user_ids[0]







            if ou_mgr_user:



                role = getattr(ou_mgr_user, "helpdesk_role", "team_leader")



                title = _("Responsible Unit Manager / Team Leader Escalation")



                return ou_mgr_user, False, title, role or "team_leader", 3















        curr_role = getattr(current_user, "helpdesk_role", "") if current_user else ""















        # 1. Direct Journey step lookup for Contact Center / Front line







        if current_user and curr_role == "contact_center":







            # Escalate to Front line or Back line in operating unit / team







            target = False







            if self.operating_unit_id:







                target = self.operating_unit_user_ids.filtered(







                    lambda u: u.id != current_user.id and getattr(u, "helpdesk_role", "") in ("front_line", "frontend", "support", "officer", "back_line", "backend")







                )







            if not target and self.team_id:







                target = self.team_id.user_ids.filtered(







                    lambda u: u.id != current_user.id and getattr(u, "helpdesk_role", "") in ("front_line", "frontend", "support", "officer", "back_line", "backend")







                )







            if target:







                t_user = target[0]







                t_role = getattr(t_user, "helpdesk_role", "front_line")







                return t_user, False, _("Front line / Specialist Escalation"), t_role, 2















        if current_user and curr_role in ("front_line", "frontend", "support", "officer"):







            backend_user = False







            if self.operating_unit_id:







                backend_user = self.operating_unit_user_ids.filtered(







                    lambda u: u.id != current_user.id and getattr(u, "helpdesk_role", "") in ("back_line", "backend", "fullstack", "database", "senior_principal", "qa")







                )







            if not backend_user and self.team_id:







                backend_user = self.team_id.user_ids.filtered(







                    lambda u: u.id != current_user.id and getattr(u, "helpdesk_role", "") in ("back_line", "backend", "fullstack", "database", "senior_principal", "qa")







                )







            if backend_user:







                return backend_user[0], False, _("Back line (Team) Escalation"), "back_line", 2















        # 2. Traverse employee hierarchy (parent_id)







        emp_obj = self.env["hr.employee"].sudo()







        current_emp = False







        if current_user:







            current_emp = emp_obj.search([("user_id", "=", current_user.id)], limit=1)















        visited_emps = set()







        if current_emp:







            visited_emps.add(current_emp.id)















        curr = current_emp







        while curr and curr.parent_id:







            parent = curr.parent_id







            if parent.id in visited_emps:







                _logger.warning("Circular reporting detected in employee hierarchy for %s (id: %s)", curr.name, curr.id)







                break







            visited_emps.add(parent.id)















            if parent.active and parent.user_id and parent.user_id.active and parent.user_id != current_user:







                next_user = parent.user_id







                job_title = parent.job_title or (parent.job_id.name if parent.job_id else "") or ""







                job_lower = job_title.lower()







                words = set(job_lower.replace("-", " ").replace("/", " ").split())







                role = getattr(next_user, "helpdesk_role", "")







                is_ceo = bool((ceo_user and next_user == ceo_user) or not parent.parent_id or role == "ceo" or "ceo" in words or "chief executive" in job_lower)















                if is_ceo or role == "ceo":







                    return next_user, True, _("Chief Executive Officer (CEO) Escalation"), "ceo", 7







                elif role in ("chief", "cido") or "cido" in words or "digital officer" in job_lower:







                    return next_user, False, _("Chief Officer Escalation"), "chief", 6







                elif role in ("deputy_chief", "deputy_cto") or "deputy" in words or "cto" in words or "technology officer" in job_lower:







                    return next_user, False, _("Deputy Chief Escalation"), "deputy_chief", 5







                elif role in ("directorate", "director") or "director" in words or "directorate" in words:







                    return next_user, False, _("Directorate Director Escalation"), "directorate", 4







                elif role in ("team_leader", "manager", "supervisor") or "leader" in words or "manager" in words or "division" in words:







                    return next_user, False, _("Team Leader / Supervisor Escalation"), "team_leader", 3







                else:







                    return next_user, False, _("Manager / Supervisor Escalation"), "team_leader", 3















            curr = parent















        # 3. Role-based fallback across organizational levels







        if curr_role in ("back_line", "backend", "fullstack", "database", "senior_principal", "qa"):







            mgr = self.env["res.users"].sudo().search([("helpdesk_role", "in", ("team_leader", "manager", "supervisor", "admin")), ("active", "=", True)], limit=1)







            if mgr and mgr != current_user:







                return mgr, False, _("Team Leader / Supervisor Escalation"), "team_leader", 3















        if curr_role in ("team_leader", "manager", "supervisor"):







            dir_user = self.env["res.users"].sudo().search([("helpdesk_role", "in", ("directorate", "director")), ("active", "=", True)], limit=1)







            if dir_user and dir_user != current_user:







                return dir_user, False, _("Directorate Director Escalation"), "directorate", 4















        if curr_role in ("directorate", "director"):







            dep_chief = self.env["res.users"].sudo().search([("helpdesk_role", "in", ("deputy_chief", "deputy_cto")), ("active", "=", True)], limit=1)







            if dep_chief and dep_chief != current_user:







                return dep_chief, False, _("Deputy Chief Escalation"), "deputy_chief", 5















        if curr_role in ("deputy_chief", "deputy_cto"):







            chief_user = self.env["res.users"].sudo().search([("helpdesk_role", "in", ("chief", "cido")), ("active", "=", True)], limit=1)







            if chief_user and chief_user != current_user:







                return chief_user, False, _("Chief Officer Escalation"), "chief", 6















        if curr_role in ("chief", "cido"):







            if ceo_user and current_user != ceo_user:







                return ceo_user, True, _("Chief Executive Officer (CEO) Escalation"), "ceo", 7







            ceo_role_user = self.env["res.users"].sudo().search([("helpdesk_role", "=", "ceo"), ("active", "=", True)], limit=1)







            if ceo_role_user and ceo_role_user != current_user:







                return ceo_role_user, True, _("Chief Executive Officer (CEO) Escalation"), "ceo", 7















        # 4. Fallback to CEO or Administrator if top reached or unassigned



        if ceo_user and current_user != ceo_user:



            return ceo_user, True, _("Chief Executive Officer (CEO) Escalation"), "ceo", 7







        admin_user = self.env.ref("base.user_admin", raise_if_not_found=False)



        if admin_user and admin_user != current_user:



            return admin_user, False, _("Administrator Escalation"), "admin", 3







        return False, False, "", "", 0















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















        res = self._get_next_escalation_manager()







        if not res or not res[0]:







            _logger.warning("No escalation manager found for ticket %s (current user: %s).", self.number, self.user_id.name if self.user_id else "None")







            return False















        next_manager, is_ceo, level_title, escalation_type, level_int = res







        prev_user = self.user_id







        prev_display_name = prev_user.name if prev_user else _("Unassigned")







        new_level = level_int or ((self.escalation_level or 0) + 1)







        now = fields.Datetime.now()







        breached_deadline = self.sla_deadline or now















        # Determine next SLA target duration from applicable SLA policy







        applicable_slas = self.team_id.sudo().sla_ids.filtered(lambda s: s._is_applicable(self)) if self.team_id else False







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







            "is_sla_expired": True,







            "sla_expired_at": now,







        }







        if is_ceo:



            vals["priority"] = "3"



        self.with_context(bypass_stage_guard=True, skip_ou_user_constraint=True).write(vals)















        # Record audit history







        self.env["helpdesk.ticket.escalation.history"].sudo().create({







            "ticket_id": self.id,







            "escalation_level": new_level,







            "escalation_type": escalation_type or "sla_breach",







            "level_name": level_title or (_("Level %d") % new_level),







            "escalated_by_user_id": self.env.user.id,







            "previous_user_id": prev_user.id if prev_user else False,







            "new_user_id": next_manager.id,







            "escalation_datetime": now,







            "sla_deadline": breached_deadline,







            "new_sla_deadline": next_deadline,







            "is_ceo_level": is_ceo,







            "reason": reason or _("Automatic hierarchical escalation due to SLA deadline breach: %s") % (level_title or ""),







        })















        # Post rich message in Chatter







        level_label = level_title or (_("CEO / Executive Authority Level") if is_ceo else _("Level %d") % new_level)







        chatter_msg = (







            f"<div><strong>🚨 SLA Breached &amp; Automatically Escalated ({level_label})</strong><br/>"







            f"• <strong>Previous Assignee:</strong> {prev_display_name}<br/>"







            f"• <strong>New Assignee:</strong> {next_manager.name}<br/>"







            f"• <strong>Escalation Time:</strong> {now.strftime('%Y-%m-%d %H:%M:%S')}<br/>"







            f"• <strong>Breached SLA Deadline:</strong> {breached_deadline.strftime('%Y-%m-%d %H:%M:%S') if breached_deadline else 'N/A'}<br/>"







            f"• <strong>New Target Deadline:</strong> {next_deadline.strftime('%Y-%m-%d %H:%M:%S') if next_deadline else 'N/A'}</div>"







        )







        self.message_post(body=chatter_msg, subtype_xmlid="mail.mt_note", body_is_html=True)







        # Notify the previous user that SLA escalation time has expired



        if prev_user and prev_user.partner_id:



            try:



                self.env["bus.bus"]._sendone(



                    prev_user.partner_id,



                    "simple_notification",



                    {



                        "type": "danger",



                        "title": _("⚠️ SLA Escalation Time Expired"),



                        "message": _("SLA time has expired for Ticket %s (%s). The case has been automatically escalated to %s (%s).") % (



                            self.number or self.name,



                            self.service_id.name if self.service_id else _("General"),



                            next_manager.name,



                            level_label,



                        ),



                        "sticky": True,



                    },



                )



            except Exception as e:



                _logger.warning("Could not send SLA expiration notification to previous assignee: %s", e)







            try:



                act_type = self.env.ref("mail.mail_activity_data_warning", raise_if_not_found=False) or self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)



                if act_type:



                    self.activity_schedule(



                        activity_type_id=act_type.id,



                        summary=_("SLA Escalation Time Expired"),



                        note=_("SLA escalation time has ended for Ticket %s. Automatically escalated to %s (%s).") % (



                            self.number,



                            next_manager.name,



                            level_label,



                        ),



                        user_id=prev_user.id,



                    )



            except Exception as e:



                _logger.warning("Could not schedule SLA expiration activity: %s", e)















        # Notify the newly assigned manager







        if next_manager.partner_id:







            subject = _("⚠️ Escalation (%s): Ticket %s Assigned to You") % (level_label, self.display_name)







            items = [







                (_("Ticket"), f'"{self.display_name}"'),







                (_("Escalation Level"), level_label),







                (_("Previous Assignee"), prev_display_name),







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







            # Direct Chat & Discuss Notification to SLA escalated manager







            self._send_discuss_chat_notification(







                target_user=next_manager,







                title=subject,







                items=items,







                author_user=False,







            )







        return True















    @api.model







    def _cron_evaluate_sla_escalation(self):







        """







        Scheduled action: scan open tickets that have breached SLA/OLA deadline,







        mark breach statuses, and automatically escalate them up the organizational reporting hierarchy.







        """







        now = fields.Datetime.now()







        # 1. Update expired helpdesk.sla.status records



        expired_statuses = self.env["helpdesk.sla.status"].search([



            ("reached_datetime", "=", False),



            ("deadline", "<", now),



            ("status", "!=", "failed"),



        ])



        if expired_statuses:



            expired_statuses.write({"status": "failed"})







        # 2. Mark breached open tickets



        breached_open = self.search([



            ("stage_id.closed", "=", False),



            "|",



            "&", ("sla_deadline", "!=", False), ("sla_deadline", "<", now),



            "&", ("ola_deadline", "!=", False), ("ola_deadline", "<", now),



        ])



        for t in breached_open:



            vals = {}



            if t.sla_status != "failed":



                vals["sla_status"] = "failed"



            if t.ola_deadline and t.ola_deadline < now and t.ola_status not in ("failed", "reached"):



                vals["ola_status"] = "failed"



            if vals:



                t.with_context(bypass_stage_guard=True).write(vals)







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







        company_id = defaults.get("company_id") or self.env.company.id or self.env.user.company_id.id or 1







        defaults["company_id"] = company_id







        defaults["user_id"] = False







        defaults["team_id"] = False







        defaults["operating_unit_id"] = False







        defaults["parent_operating_unit_id"] = False















        if "case_type_id" in flds and not defaults.get("case_type_id"):







            default_case_code = self.env.context.get("default_case_type") or "inquiry"







            case_type = self.env["helpdesk.ticket.case.type"].search([("code", "=", default_case_code)], limit=1)







            if not case_type:







                case_type = self.env["helpdesk.ticket.case.type"].search([], limit=1)







            if case_type:







                defaults["case_type_id"] = case_type.id







                if "priority" in flds and not defaults.get("priority") and case_type.default_priority:







                    defaults["priority"] = case_type.default_priority















        if "customer_status" in flds and not defaults.get("customer_status"):







            defaults["customer_status"] = False















        if "customer_type" in flds and not defaults.get("customer_type"):







            defaults["customer_type"] = False















        if "customer_type_id" in flds and not defaults.get("customer_type_id"):







            defaults["customer_type_id"] = False







        if "customer_name" in flds:



            defaults["customer_name"] = False







        if "partner_name" in flds:



            defaults["partner_name"] = False







        if "partner_id" in flds and not defaults.get("partner_id"):



            defaults["partner_id"] = False















        return defaults















    @api.depends("name")







    def _compute_display_name(self):







        for ticket in self:







            ticket.display_name = f"{ticket.number} - {ticket.name}"















    def assign_to_me(self):







        for ticket in self:







            vals = {"user_id": self.env.user.id}







            if ticket.is_escalated or ticket.escalated_to_team_id:







                vals["escalated_to_user_id"] = self.env.user.id







            if ticket.escalated_to_level_3_team_id:







                vals["escalated_to_level_3_user_id"] = self.env.user.id







            ticket.with_context(bypass_stage_guard=True).write(vals)















    @api.onchange("channel_id")







    def _onchange_channel_id_sync_type(self):







        if self.channel_id and self.channel_id.name:







            ch_map = {







                "api": "api",







                "phone": "phone",







                "email": "email",







                "web": "web_portal",







                "telegram": "telegram",







                "whatsapp": "whatsapp",







                "chatbot": "chatbot",







            }







            mapped = ch_map.get(self.channel_id.name.lower().strip())







            if mapped:







                self.channel_type = mapped















    @api.onchange("partner_id")







    def _onchange_partner_id(self):







        if self.partner_id:







            self.partner_name = self.partner_id.name



            p_name = (self.partner_id.name or "").strip()



            is_phone_name = bool(re.search(r"^\+?\d{8,}$", re.sub(r"[\s\-\.\(\)]", "", p_name)))



            is_generic = "bunna customer (" in p_name.lower() or p_name.lower() in ("customer", "guest customer")



            if p_name and not is_phone_name and not is_generic and not self.customer_name:



                self.customer_name = p_name







            self.partner_email = self.partner_id.email















    # ── SLA helpers ───────────────────────────────────────────────────────────















    def _sla_apply(self):







        """Compute and attach/update SLA statuses for each ticket."""







        for ticket in self:







            team = ticket.team_id







            if not team:







                continue







            applicable_slas = team.sudo().sla_ids.filtered(







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







            # Remove statuses for SLAs no longer applicable







            for sla, status in existing.items():







                if sla not in applicable_slas:







                    status.sudo().unlink()







            if vals_list:







                self.env["helpdesk.sla.status"].create(vals_list)















    def _sla_mark_reached(self, stage_id):







        """Mark SLA statuses as reached when their target stage is met or when the ticket is completed."""







        now = fields.Datetime.now()







        stage = self.env["helpdesk.ticket.stage"].browse(stage_id) if stage_id else False







        is_done_stage = stage and (stage.closed or (stage.name and stage.name.lower() in ("done", "resolved", "resolve", "closed", "close", "rejected", "reject", "cancelled", "cancel")))







        for ticket in self:







            for status in ticket.sla_status_ids:







                if not status.reached_datetime:







                    if status.sla_id.stage_id.id == stage_id or is_done_stage:







                        status.reached_datetime = now







            if is_done_stage and ticket.ola_status == "in_progress":







                ticket.ola_status = "reached"















    # ── CRUD ─────────────────────────────────────────────────────────────────















    def _creation_subtype(self):







        return self.env.ref("bunna_helpdesk.hlp_tck_created")















    @api.model_create_multi







    def create(self, vals_list):







        default_team_param = self.env["ir.config_parameter"].sudo().get_param("bunna_helpdesk.default_team_id")







        for vals in vals_list:



            # Map frontend aliases gracefully



            if "subject" in vals and not vals.get("name"):



                vals["name"] = vals.pop("subject")



            elif "subject" in vals:



                vals.pop("subject")







            # Map phone aliases



            if vals.get("phone_number"):



                if not vals.get("partner_phone"):



                    vals["partner_phone"] = vals["phone_number"]



            if "phone" in vals and not vals.get("partner_phone"):



                vals["partner_phone"] = vals.pop("phone")



            elif "phone" in vals:



                vals.pop("phone")



            if vals.get("partner_phone") and not vals.get("phone_number"):



                vals["phone_number"] = vals["partner_phone"]







            if "secondary_phone" in vals and not vals.get("partner_phone_secondary"):



                vals["partner_phone_secondary"] = vals.pop("secondary_phone")



            elif "secondary_phone" in vals:



                vals.pop("secondary_phone")







            if "communication_channel" in vals and not vals.get("channel_type"):



                vals["channel_type"] = vals.pop("communication_channel")



            elif "communication_channel" in vals:



                vals.pop("communication_channel")







            # Map email aliases



            if vals.get("customer_email"):



                if not vals.get("partner_email"):



                    vals["partner_email"] = vals["customer_email"]



            if "email" in vals and not vals.get("partner_email"):



                vals["partner_email"] = vals.pop("email")



            elif "email" in vals:



                vals.pop("email")



            if vals.get("partner_email") and not vals.get("customer_email"):



                vals["customer_email"] = vals["partner_email"]







            # Map customer inquires aliases



            inq_val = vals.get("customer_inquires") or vals.get("customer_inquiries") or vals.get("customer_inquiry")



            if inq_val:



                vals["customer_inquires"] = inq_val



                if not vals.get("customer_request_details"):



                    vals["customer_request_details"] = inq_val



                if not vals.get("description"):



                    vals["description"] = f"<p>{inq_val}</p>"







            # Map customer name / partner name



            if vals.get("customer_name") and not vals.get("partner_name"):



                vals["partner_name"] = vals["customer_name"]



            elif vals.get("partner_name") and not vals.get("customer_name"):



                vals["customer_name"] = vals["partner_name"]







            if not vals.get("company_id"):







                company_id = False







                if vals.get("team_id"):







                    team = self.env["helpdesk.ticket.team"].browse(vals["team_id"])







                    if team.company_id:







                        company_id = team.company_id.id







                if not company_id and vals.get("operating_unit_id"):







                    ou = self.env["operating.unit"].sudo().browse(vals["operating_unit_id"])







                    if ou.company_id:







                        company_id = ou.company_id.id







                if not company_id:







                    company = self.env.company or self.env.user.company_id or self.env.ref("base.main_company", raise_if_not_found=False)







                    company_id = company.id if company else 1







                vals["company_id"] = company_id







            if vals.get("operating_unit_id") and not vals.get("original_operating_unit_id"):







                vals["original_operating_unit_id"] = vals["operating_unit_id"]







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







            # Auto-sync Communication Channel (channel_type) from channel_id







            if vals.get("channel_id") and (not vals.get("channel_type") or vals.get("channel_type") == "phone"):







                ch = self.env["helpdesk.ticket.channel"].browse(vals["channel_id"])







                if ch.exists() and ch.name:







                    ch_map = {







                        "api": "api",







                        "phone": "phone",







                        "email": "email",







                        "web": "web_portal",







                        "telegram": "telegram",







                        "whatsapp": "whatsapp",







                        "chatbot": "chatbot",







                    }







                    if ch.name.lower().strip() in ch_map:







                        vals["channel_type"] = ch_map[ch.name.lower().strip()]







            if not vals.get("customer_request_details") and vals.get("description"):







                vals["customer_request_details"] = tools.html2plaintext(vals["description"]).strip()







            if vals.get("number", "/") == "/":







                vals["number"] = self._prepare_ticket_number(vals)







            # Automatic ticket title generation if name is omitted or default







            if not vals.get("name") or vals.get("name") in ("/", "New", "New Ticket", False):







                vals["name"] = vals.get("number") or "/"







            is_frontline = (







                not self.env.user.has_group("bunna_helpdesk.group_helpdesk_back_line")







                or getattr(self.env.user, "helpdesk_role", "") in ("contact_center", "front_line", "support")







            )







            if is_frontline:







                vals["user_id"] = False







            if not vals.get("contact_center_agent_id"):







                cc_agent = self._default_contact_center_agent_id()







                if cc_agent:







                    vals["contact_center_agent_id"] = cc_agent







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







        ch_map = {



            "mobile app": "mobile_banking",



            "mobile_app": "mobile_banking",



            "mobile": "mobile_banking",



            "mobile banking": "mobile_banking",



            "mobile_banking": "mobile_banking",



            "app": "mobile_banking",



            "web": "web_portal",



            "web portal": "web_portal",



            "web_portal": "web_portal",



            "website": "web_portal",



            "portal": "web_portal",



            "tidio": "tidio_chat",



            "tidio chat": "tidio_chat",



            "tidio_chat": "tidio_chat",



            "call": "phone",



            "phone": "phone",



            "ivr": "phone",



            "phone call": "phone",



            "contact center": "phone",



            "email": "email",



            "mail": "email",



            "telegram": "telegram",



            "tg": "telegram",



            "whatsapp": "whatsapp",



            "wa": "whatsapp",



            "instagram": "instagram",



            "ig": "instagram",



            "facebook": "facebook",



            "fb": "facebook",



            "messenger": "facebook",



            "chatbot": "chatbot",



            "bot": "chatbot",



            "chat": "chatbot",



            "branch": "branch_walkin",



            "branch walkin": "branch_walkin",



            "branch walk-in": "branch_walkin",



            "walkin": "branch_walkin",



            "walk-in": "branch_walkin",



            "branch_walkin": "branch_walkin",



            "sms": "sms",



            "ussd": "sms",



            "sms / ussd": "sms",



            "api": "api",



            "rest": "api",



            "rest api": "api",



            "rest_api": "api",



            "integration": "api",



            "other": "other",



        }



        for v in vals_list:



            if not v.get("customer_name"):



                v["customer_name"] = v.get("partner_name") or (v.get("name") if v.get("name") and v.get("name") != "/" else "Customer")



            if not v.get("channel_type"):



                v["channel_type"] = "phone"



            else:



                raw_ch = str(v["channel_type"]).strip().lower()



                v["channel_type"] = ch_map.get(raw_ch, raw_ch)







            valid_channel_keys = dict(self._fields["channel_type"].selection).keys()



            if v["channel_type"] not in valid_channel_keys:



                v["channel_type"] = "phone"







            if not v.get("description"):



                v["description"] = v.get("customer_request_details") or v.get("inquiry_summary") or "<p>Customer inquiry</p>"



            if v.get("partner_phone_secondary") and not v.get("partner_phone"):



                v["partner_phone"] = v["partner_phone_secondary"]



            if v.get("partner_phone") and not v.get("partner_phone_secondary"):



                v["partner_phone_secondary"] = v["partner_phone"]



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



        if "phone_number" in vals and not vals.get("partner_phone"):



            vals["partner_phone"] = vals["phone_number"]



        if "customer_email" in vals and not vals.get("partner_email"):



            vals["partner_email"] = vals["customer_email"]



        inq_val = vals.get("customer_inquires") or vals.get("customer_inquiries") or vals.get("customer_inquiry")



        if inq_val:



            if not vals.get("customer_request_details"):



                vals["customer_request_details"] = inq_val



            if not vals.get("description"):



                vals["description"] = f"<p>{inq_val}</p>"



        if "customer_name" in vals and not vals.get("partner_name"):



            vals["partner_name"] = vals["customer_name"]



        elif "partner_name" in vals and not vals.get("customer_name"):



            vals["customer_name"] = vals["partner_name"]







        if "description" in vals and not vals.get("customer_request_details"):



            vals["customer_request_details"] = tools.html2plaintext(vals["description"]).strip()







        if "company_id" in vals and not vals["company_id"]:







            vals.pop("company_id")







        now = fields.Datetime.now()







        if "name" in vals and (not vals["name"] or vals["name"] in ("/", "New")):







            vals.pop("name")







        # Route team if operation is changed







        if "operation_id" in vals and vals.get("operation_id"):







            op = self.env["helpdesk.team.operation"].browse(vals["operation_id"])







            if op.team_id:







                vals["team_id"] = op.team_id.id







        # Front-line resolving ticket redirection: Front-line users cannot directly resolve;



        # resolving a ticket moves it to Review stage for Back-Line audit.



        if vals.get("stage_id") and not self.env.context.get("bypass_stage_guard"):



            target_stage = self.env["helpdesk.ticket.stage"].browse(vals["stage_id"])



            target_name = (target_stage.name or "").lower()



            if target_stage.closed or any(kw in target_name for kw in ("resolve", "resolved", "done")):



                curr_user = self.env.user



                is_fl = (



                    curr_user.has_group("bunna_helpdesk.group_helpdesk_front_line")



                    or curr_user.has_group("bunna_helpdesk.group_helpdesk_contact_center_front_line")



                    or curr_user.has_group("bunna_helpdesk.group_helpdesk_contact_center")



                    or getattr(curr_user, "helpdesk_role", "") in ("contact_center", "contact_center_front_line", "front_line", "support")



                )



                is_bl = (



                    curr_user.has_group("bunna_helpdesk.group_helpdesk_back_line")



                    or curr_user.has_group("bunna_helpdesk.group_helpdesk_contact_center_back_line")



                    or curr_user.has_group("bunna_helpdesk.group_helpdesk_team_leader")



                    or curr_user.has_group("bunna_helpdesk.group_helpdesk_contact_center_team_leader")



                    or curr_user.has_group("bunna_helpdesk.group_helpdesk_manager")



                    or curr_user.has_group("bunna_helpdesk.group_helpdesk_contact_center_director")



                    or curr_user.has_group("base.group_erp_manager")



                    or getattr(curr_user, "helpdesk_role", "") in ("back_line", "contact_center_back_line", "team_leader", "contact_center_team_leader", "contact_center_director", "manager", "admin")



                )



                if is_fl and not is_bl:



                    review_stage = self.env["helpdesk.ticket.stage"].search(



                        ["|", ("name", "=ilike", "Review"), ("name", "=ilike", "Under Review")], limit=1



                    )



                    if not review_stage:



                        review_stage = self.env["helpdesk.ticket.stage"].create({



                            "name": "Review",



                            "sequence": 4,



                            "closed": False,



                            "company_id": self.env.company.id or 1,



                        })



                    vals["stage_id"] = review_stage.id



                    vals["review_submitted_by_id"] = curr_user.id



                    vals["review_submitted_at"] = fields.Datetime.now()







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







                current_stage = _ticket.stage_id







                # Enforce rule: Resolved, Closed, and Rejected tickets can only be Reopened (or Closed if Resolved)







                if current_stage and stage and stage.id != current_stage.id and not self.env.context.get("bypass_stage_guard"):







                    curr_name = (current_stage.name or "").lower()







                    target_name = (stage.name or "").lower()







                    # 1. Resolved tickets: can only transition to Reopen or Closed







                    if "done" in curr_name or "resolved" in curr_name or "resolve" in curr_name:







                        is_allowed = (







                            "reopen" in target_name







                            or "close" in target_name







                            or stage.closed







                        )







                        if not is_allowed:







                            raise ValidationError(_(







                                "Ticket '%s' is already marked as Resolved. Once a ticket is Resolved, it can only be Closed or Reopened. "







                                "To change its stage to '%s', you must first Reopen the ticket."







                            ) % (_ticket.number or _ticket.name, stage.name))







                    # 2. Closed tickets: can only transition to Reopen







                    elif "close" in curr_name or current_stage.closed or _ticket.closed:







                        is_allowed = "reopen" in target_name







                        if not is_allowed:







                            raise ValidationError(_(







                                "Ticket '%s' is Closed. Once a ticket is Closed, it can only be Reopened. "







                                "To change its stage to '%s', you must first Reopen the ticket."







                            ) % (_ticket.number or _ticket.name, stage.name))







                    # 3. Rejected tickets: can only transition to Reopen







                    elif "reject" in curr_name or getattr(_ticket, "is_rejected", False):







                        is_allowed = "reopen" in target_name







                        if not is_allowed:







                            raise ValidationError(_(







                                "Ticket '%s' is Rejected. Once a ticket is Rejected, it can only be Reopened. "







                                "To change its stage to '%s', you must first Reopen the ticket."







                            ) % (_ticket.number or _ticket.name, stage.name))







                vals["last_stage_update"] = now







                if stage.closed:







                    vals["closed_date"] = now







                if stage and "reject" in (stage.name or "").lower():







                    reason = vals.get("rejection_reason") or _ticket.rejection_reason







                    if not reason or not str(reason).strip():







                        raise ValidationError(_(







                            "A Rejection Reason is required to reject a ticket. "







                            "Please use the 'Reject' button to provide the rejection reason."







                        ))







                    vals["is_rejected"] = True







                if stage and "escalat" in (stage.name or "").lower():







                    vals["is_escalated"] = True







                if stage and not stage.closed and "done" not in (stage.name or "").lower() and "resolved" not in (stage.name or "").lower() and "resolve" not in (stage.name or "").lower():







                    if "escalated_agent_response" not in vals:







                        vals["escalated_agent_response"] = False







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







                    if not ticket.partner_id:







                        continue







                    if ticket.team_id and not ticket.team_id.use_rating:







                        continue







                    template = (







                        ticket.team_id.rating_template_id







                        if ticket.team_id and ticket.team_id.rating_template_id







                        else self.env.ref("bunna_helpdesk.helpdesk_rating_request_template", raise_if_not_found=False)







                    )







                    if template:







                        try:







                            ticket.rating_send_request(template, force_send=True)







                        except Exception:







                            try:







                                template.send_mail(ticket.id, force_send=True)







                            except Exception as err:







                                _logger.warning("Failed to auto-send rating request for ticket %s: %s", ticket.id, err)















        # ── Notifications for Discuss / Chatter ──────────────────────────────







        for ticket in self:







            old = old_data.get(ticket.id, {})















            # 1. Assignment notification



            if user_changed and not self.env.context.get("skip_assign_notification"):



                old_user = old.get("user_id")



                if ticket.user_id and ticket.user_id != old_user:



                    ticket._notify_ticket_assigned(previous_user=old_user)



                    if getattr(ticket.user_id, "is_on_leave", False):



                        status_str = ticket.user_id.leave_status_text or _("on leave")



                        ticket.message_post(



                            body=(



                                f"<div><strong>⚠️ Agent on Leave Notice:</strong> "



                                f"This ticket has been assigned to <strong>{ticket.user_id.name}</strong> "



                                f"who is currently <em>{status_str}</em>. "



                                f"Please consider reassigning to an active agent to avoid resolution delays.</div>"



                            ),



                            subtype_xmlid="mail.mt_note",



                            body_is_html=True,



                        )







            # 2. Team reassignment notification



            if team_changed and not self.env.context.get("skip_team_notification"):



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















    @api.model



    def name_search(self, name="", domain=None, operator="ilike", limit=100):



        if name:



            search_domain = [



                "|", "|", "|", "|", "|", "|",



                ("number", operator, name),



                ("name", operator, name),



                ("account_number", operator, name),



                ("partner_phone", operator, name),



                ("phone_number", operator, name),



                ("partner_phone_secondary", operator, name),



                ("customer_name", operator, name),



            ]



            if domain:



                search_domain = expression.AND([search_domain, domain])



            records = self.search(search_domain, limit=limit)



            return [(r.id, r.display_name) for r in records.sudo()]



        return super().name_search(name=name, domain=domain, operator=operator, limit=limit)







    def _prepare_ticket_number(self, values):







        seq = self.env["ir.sequence"]







        if values.get("company_id"):







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







        """Format ticket notification cleanly as normal plain text without raw HTML tags."""







        self.ensure_one()







        lines = [







            f"{_('Dear')} {recipient_name},",







            "",







            f"{action_statement}:",







        ]







        if items:







            for label, val in items:







                if not val:







                    continue







                clean_val = (







                    str(val)







                    .replace("&quot;", '"')







                    .replace("&amp;", "&")







                    .replace("&lt;", "<")







                    .replace("&gt;", ">")







                )







                lines.append(f"• {label}: {clean_val}")







        return tools.plaintext2html("\n".join(lines))















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







                (_("Document"), f'"{ticket.display_name}" ({_("Helpdesk Ticket")})'),







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







            bus_items = [







                (partner, "simple_notification", {







                    "type": "info",







                    "title": toast_title,







                    "message": toast_msg,







                    "sticky": False,







                })







                for partner in recipient_partners







            ]







            if bus_items:







                try:







                    self.env["bus.bus"]._sendmany(bus_items)







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















            # 5. Direct Chat notification to team leader if no specific assignee is set







            if target_user and not ticket.user_id:







                ticket._send_discuss_chat_notification(







                    target_user=target_user,







                    title=subject,







                    items=items,







                    author_user=self.env.user,







                )















    def _send_discuss_chat_notification(self, target_user, title, items, author_user=None):







        """







        Send a direct 1-on-1 Chat message in Discuss to target_user,







        along with real-time web bus toast notification and activity scheduling.







        Appears in Discuss sidebar under Direct messages and the top-right Chat systray.







        """







        self.ensure_one()







        if not target_user or not target_user.partner_id:







            return















        recipient_partner = target_user.partner_id







        author = author_user or self.env.user







        sender_user = author if author != target_user else self.env.ref("base.user_root", raise_if_not_found=False)







        if not sender_user:







            sender_user = self.env.user















        # 1. Format rich HTML message with clickable ticket link







        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "http://localhost:8069")







        ticket_url = f"{base_url}/odoo/action-bunna_helpdesk.action_helpdesk_ticket/{self.id}"















        lines = [title, ""]



        lines.append(f"Ticket: {self.display_name}")



        for k, v in items:



            if not v:



                continue



            clean_v = re.sub(r"<[^>]+>", "", str(v)).strip()



            clean_v = (



                clean_v.replace("&quot;", '"')



                .replace("&amp;", "&")



                .replace("&lt;", "<")



                .replace("&gt;", ">")



                .replace("&nbsp;", " ")



            )



            if str(k).strip() == "Document" and self.display_name in clean_v:



                continue



            lines.append(f"{k}: {clean_v}")



        lines.append("")



        lines.append(f"Open Ticket: {ticket_url}")



        chat_body = tools.plaintext2html("\n".join(lines))















        # 2. Direct Chat (discuss.channel of type 'chat')







        try:







            # Get or create 1-on-1 private chat channel with target user







            chat = self.env["discuss.channel"].with_user(sender_user).sudo()._get_or_create_chat(







                partners_to=[recipient_partner.id]







            )







            if chat:







                chat.with_user(sender_user).sudo().message_post(







                    body=chat_body,







                    message_type="comment",







                    subtype_xmlid="mail.mt_comment",







                )







        except Exception as e:







            _logger.warning("Failed to post direct chat message for ticket %s: %s", self.number, str(e))















        # 3. Real-time web bus toast alert







        try:







            toast_item = [







                (recipient_partner, "simple_notification", {







                    "type": "info",







                    "title": title,







                    "message": f"[{self.number}] {self.name or ''}",







                    "sticky": False,







                })







            ]







            self.env["bus.bus"].sudo()._sendmany(toast_item)







        except Exception as e:







            _logger.debug("Bus notification failed: %s", str(e))















        # 4. Schedule Activity for assigned user







        try:







            existing = self.env["mail.activity"].sudo().search([







                ("res_model", "=", "helpdesk.ticket"),







                ("res_id", "=", self.id),







                ("user_id", "=", target_user.id),







                ("activity_type_id", "=", self.env.ref("mail.mail_activity_data_todo").id),







            ], limit=1)







            if not existing:







                deadline = fields.Date.today()







                if self.sla_deadline:







                    deadline = fields.Date.to_date(self.sla_deadline)







                self.sudo().activity_schedule(







                    "mail.mail_activity_data_todo",







                    user_id=target_user.id,







                    summary=title,







                    note=f"Assigned Ticket: {self.display_name}. Customer: {self.partner_name or self.partner_id.name or 'N/A'}",







                    date_deadline=deadline,







                )







        except Exception as e:







            _logger.debug("Activity schedule failed: %s", str(e))















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







                (_("Document"), f'"{ticket.display_name}" ({_("Helpdesk Ticket")})'),







                (_("Team"), ticket.team_id.name if ticket.team_id else _("General")),







            ]







            if ticket.partner_id or ticket.partner_name:







                cust = ticket.partner_name or ticket.partner_id.name







                items.append((_("Customer"), cust))







            if ticket.account_number:







                items.append((_("Account No"), ticket.account_number))







            if ticket.service_id:







                items.append((_("Service"), ticket.service_id.name))







            if ticket.parent_operating_unit_id:







                items.append((_("Operating Unit"), ticket.parent_operating_unit_id.name))







            items.append((_("Priority"), prio_label))







            if ticket.stage_id:







                items.append((_("Stage"), ticket.stage_id.name))







            if ticket.sla_deadline:







                items.append((_("SLA Deadline"), str(ticket.sla_deadline)))















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















            # Direct Chat & Discuss Notification (yellow circled: top Chat systray & Discuss Direct Messages)







            chat_title = _("🎫 New Ticket Assigned to You: %s") % ticket.number







            ticket._send_discuss_chat_notification(







                target_user=ticket.user_id,







                title=chat_title,







                items=items,







                author_user=self.env.user,







            )















            if previous_user and previous_user != ticket.user_id and previous_user.partner_id:







                prev_partner = previous_user.partner_id







                prev_subject = _('"%s" reassigned') % ticket.display_name







                prev_items = [







                    (_("Document"), f'"{ticket.display_name}" ({_("Helpdesk Ticket")})'),







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







                ticket._send_discuss_chat_notification(







                    target_user=previous_user,







                    title=_("ℹ️ Ticket Reassigned: %s") % ticket.number,







                    items=prev_items,







                    author_user=self.env.user,







                )















    def _notify_ticket_resolved(self, stage):







        """Send Discuss notification when ticket issue is resolved/closed."""







        for ticket in self:







            # Internal users only: the customer already receives the dedicated







            # completion SMS/email (see helpdesk_ticket_notification.py).







            partners = set()







            if ticket.create_uid and ticket.create_uid.partner_id:







                partners.add(ticket.create_uid.partner_id)







            if ticket.user_id and ticket.user_id.partner_id:







                partners.add(ticket.user_id.partner_id)







            partners -= {ticket.partner_id}















            author_name = self.env.user.name or _("System")







            subject = _('"%s: Resolved"') % ticket.display_name







            items = [







                (_("Document"), f'"{ticket.display_name}" ({_("Helpdesk Ticket")})'),







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







                (_("Document"), f'"{ticket.display_name}" ({_("Helpdesk Ticket")})'),







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







                (_("Document"), f'"{ticket.display_name}" ({_("Helpdesk Ticket")})'),







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







                (_("Document"), f'"{ticket.display_name}" ({_("Helpdesk Ticket")})'),







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







        """Automatically close tickets in 'Done' stage after the configured grace period following notification."""







        icp = self.env["ir.config_parameter"].sudo()







        enabled = icp.get_param("bunna_helpdesk.auto_close_tickets", "True") == "True"







        if not enabled:







            return















        try:







            delay = int(icp.get_param("bunna_helpdesk.auto_close_delay", "3"))







        except (ValueError, TypeError):







            delay = 3















        unit = icp.get_param("bunna_helpdesk.auto_close_unit", "days")







        now = fields.Datetime.now()







        if unit == "hours":







            cutoff = now - timedelta(hours=delay)







        else:







            cutoff = now - timedelta(days=delay)















        # 1. Resolve Target Closed Stage







        closed_stage_id = icp.get_param("bunna_helpdesk.closed_stage_id")







        closed_stage = False







        if closed_stage_id:







            closed_stage = self.env["helpdesk.ticket.stage"].browse(int(closed_stage_id)).exists()







        if not closed_stage:







            closed_stage = self.env.ref("bunna_helpdesk.helpdesk_ticket_stage_closed", raise_if_not_found=False)







        if not closed_stage:







            closed_stage = self.env["helpdesk.ticket.stage"].search([







                ("name", "ilike", "Closed"),







                ("closed", "=", True),







            ], limit=1)















        if not closed_stage:







            _logger.warning("Auto-close cron: No Closed stage found in database.")







            return















        # 2. Done Stage(s)







        done_stages = self.env["helpdesk.ticket.stage"].search([







            ("name", "in", ["Done", "Resolved", "Resolve"]),







            ("id", "!=", closed_stage.id),







        ])







        if not done_stages:







            return















        # 3. Candidate tickets: Resolved/Done stage tickets where completion notification (or last stage update) has exceeded grace period







        domain = [







            ("stage_id", "in", done_stages.ids),







            "|",







            ("done_notification_date", "<=", cutoff),







            "&",







            ("done_notification_date", "=", False),







            ("last_stage_update", "<=", cutoff),







        ]







        tickets_to_close = self.search(domain)







        _logger.info("Auto-close cron: Found %s tickets to auto-close.", len(tickets_to_close))







        for ticket in tickets_to_close:







            ticket.with_context(bypass_stage_guard=True).write({"stage_id": closed_stage.id})







            ticket.message_post(







                body=_(







                    "<strong>Ticket Auto-Closed:</strong> Automatically moved from Resolved to Closed stage "







                    "after %s %s following resolution and notification."







                ) % (delay, unit),







                subtype_xmlid="mail.mt_note",







            )















    # ── Bunna customer notifications: see helpdesk_ticket_notification.py ─────















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







            "Account / CIF", "Case Type", "Service", "Sub Service", "Assigned Team",







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







































    def action_reopen_ticket(self, reason=None):







        """Allow Frontline, Backline, and Managers to reopen a closed/resolved/rejected ticket with a reason."""







        reopen_stage = self.env["helpdesk.ticket.stage"].search(







            [("name", "ilike", "reopen")], limit=1







        )







        if not reopen_stage:







            reopen_stage = self.env["helpdesk.ticket.stage"].search(







                [("closed", "=", False), ("name", "ilike", "progress")], limit=1







            )







        if not reopen_stage:







            reopen_stage = self.env["helpdesk.ticket.stage"].search(







                [("closed", "=", False)], limit=1







            )







        for ticket in self:







            vals = {







                "is_reopened": True,







                "is_rejected": False,







                "is_escalated": False,







                "escalation_level": 0,







                "user_id": False,  # Clear assignee so creator can pick a new one







                "escalated_agent_response": False,







            }







            if reason:







                vals["reopen_reason"] = str(reason).strip()







            if reopen_stage:







                vals["stage_id"] = reopen_stage.id







            ticket.with_context(bypass_stage_guard=True).write(vals)







            reason_msg = f"<br/>• <strong>Reason:</strong> {reason.strip()}" if reason else ""







            ticket.message_post(







                body=f"<div><strong>🔄 Ticket Reopened</strong><br/>"







                     f"• <strong>Reopened By:</strong> {self.env.user.name}"







                     f"{reason_msg}</div>",







                subtype_xmlid="mail.mt_note",







                body_is_html=True,







            )







        return True















    def action_open_reject_wizard(self):







        """Open wizard to enter rejection reason."""







        self.ensure_one()







        stage_name = (self.stage_id.name or "").lower() if self.stage_id else ""







        if self.closed or (self.stage_id and self.stage_id.closed) or any(term in stage_name for term in ("resolve", "resolved", "done", "close", "reject")):







            raise UserError(_("Ticket '%s' is %s. A resolved, closed, or rejected ticket cannot be rejected. You must first Reopen the ticket.") % (self.number or self.name, self.stage_id.name or "terminal"))







        user = self.env.user







        is_authorized = (







            user._is_admin()







            or user.has_group("bunna_helpdesk.group_helpdesk_back_line")







            or user.has_group("bunna_helpdesk.group_helpdesk_team_leader")







            or user.has_group("bunna_helpdesk.group_helpdesk_director")







            or user.has_group("bunna_helpdesk.group_helpdesk_manager")







            or user.has_group("bunna_helpdesk.group_helpdesk_front_line")







        )







        if not is_authorized:







            raise UserError(_("You are not authorized to reject this ticket."))







        return {







            "name": _("Reject Ticket"),







            "type": "ir.actions.act_window",







            "res_model": "helpdesk.ticket.reject.wizard",







            "view_mode": "form",







            "target": "new",







            "context": {







                "default_ticket_id": self.id,







            },







        }















    def action_reject_ticket(self, reason=None):







        """Allow Back Office, Front Office, and Managers to reject a ticket with a required reason."""







        for ticket in self:







            stage_name = (ticket.stage_id.name or "").lower() if ticket.stage_id else ""







            if ticket.closed or (ticket.stage_id and ticket.stage_id.closed) or any(term in stage_name for term in ("resolve", "resolved", "done", "close", "reject")):







                raise ValidationError(_("Ticket '%s' is %s. A resolved, closed, or rejected ticket cannot be rejected. You must first Reopen the ticket.") % (ticket.number or ticket.name, ticket.stage_id.name or "terminal"))







            if not reason or not str(reason).strip():







                raise ValidationError(_("A Rejection Reason is required to reject a ticket."))







            reject_stage = self.env["helpdesk.ticket.stage"].search(







                [("name", "ilike", "reject")], limit=1







            )







            if not reject_stage:







                reject_stage = self.env["helpdesk.ticket.stage"].search(







                    [("name", "ilike", "cancel")], limit=1







                )







            vals = {







                "is_rejected": True,







                "rejection_reason": reason.strip(),







                "user_id": ticket.create_uid.id if ticket.create_uid else False,  # Return ticket back to frontline creator







                "is_escalated": False,







                "escalation_level": 0,







            }







            if reject_stage:







                vals["stage_id"] = reject_stage.id







            ticket.with_context(skip_ou_user_constraint=True).write(vals)







            ticket.message_post(







                body=f"<div><strong>❌ Ticket Rejected</strong><br/>"







                     f"• <strong>Rejected By:</strong> {self.env.user.name}<br/>"







                     f"• <strong>Rejection Reason:</strong> {reason.strip()}</div>",







                subtype_xmlid="mail.mt_note",







                body_is_html=True,







            )







            ticket._notify_ticket_rejected(reason.strip())







        return True















    def _notify_ticket_rejected(self, rejection_reason):







        """Notify both Front Office and Back Office parties when a ticket is rejected."""







        for ticket in self:







            recipients = ticket.env["res.partner"]







            # Front Office: ticket creator, contact center agent, assigned user







            if ticket.create_uid and ticket.create_uid.partner_id:







                recipients |= ticket.create_uid.partner_id







            cc_agent = ticket.sudo().contact_center_agent_id







            if cc_agent and cc_agent.user_id and cc_agent.user_id.partner_id:







                recipients |= cc_agent.user_id.partner_id







            if ticket.user_id and ticket.user_id.partner_id:







                recipients |= ticket.user_id.partner_id







            # Back Office: rejecting user and team leader







            if ticket.env.user.partner_id:







                recipients |= ticket.env.user.partner_id







            if ticket.team_id and ticket.team_id.user_id and ticket.team_id.user_id.partner_id:







                recipients |= ticket.team_id.user_id.partner_id















            author_name = ticket.env.user.name or _("System")







            for p in recipients:







                subject = _("❌ Ticket %s Rejected") % ticket.display_name







                items = [







                    (_("Document"), f'"{ticket.display_name}" ({_("Helpdesk Ticket")})'),







                    (_("Status"), _("Rejected")),







                    (_("Rejected By"), author_name),







                    (_("Rejection Reason"), rejection_reason or _("No reason provided")),







                    (_("Service"), ticket.service_id.name if ticket.service_id else _("General")),







                    (_("Operating Unit"), ticket.operating_unit_id.name if ticket.operating_unit_id else _("N/A")),







                ]







                body = ticket._format_ticket_notification_body(







                    recipient_name=p.name,







                    action_statement=_("Ticket %s has been rejected by %s") % (ticket.display_name, author_name),







                    items=items,







                )







                ticket.message_notify(







                    partner_ids=[p.id],







                    subject=subject,







                    body=body,







                    email_layout_xmlid="mail.mail_notification_light",







                )







    def action_open_review_wizard(self):



        """Open Back-Line Review Wizard for tickets in Review stage."""



        self.ensure_one()



        return {



            "name": _("Back-Line Audit & Review"),



            "type": "ir.actions.act_window",



            "res_model": "helpdesk.ticket.review.wizard",



            "view_mode": "form",



            "target": "new",



            "context": {



                "default_ticket_id": self.id,



            },



        }







    def action_approve_review(self):



        """Action for Back-line Team to audit and review a ticket resolved by Front-line."""



        self.ensure_one()



        return self.action_open_review_wizard()







