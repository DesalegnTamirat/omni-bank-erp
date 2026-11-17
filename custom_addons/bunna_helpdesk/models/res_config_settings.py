from odoo import api, fields, models, _


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # ── Portal ────────────────────────────────────────────────────────────────
    helpdesk_mgmt_portal_select_team = fields.Boolean(
        related="company_id.helpdesk_mgmt_portal_select_team",
        readonly=False,
    )
    helpdesk_mgmt_portal_team_id_required = fields.Boolean(
        related="company_id.helpdesk_mgmt_portal_team_id_required",
        readonly=False,
    )
    helpdesk_mgmt_portal_select_category = fields.Boolean(
        related="company_id.helpdesk_mgmt_portal_select_category",
        readonly=False,
    )
    helpdesk_mgmt_portal_category_id_required = fields.Boolean(
        related="company_id.helpdesk_mgmt_portal_category_id_required",
        readonly=False,
    )

    # ── Duplicate tracking ────────────────────────────────────────────────────
    helpdesk_mgmt_duplicate_tracking = fields.Boolean(
        related="company_id.helpdesk_mgmt_duplicate_tracking", readonly=False
    )
    helpdesk_mgmt_duplicate_ticket_stage_id = fields.Many2one(
        related="company_id.helpdesk_mgmt_duplicate_ticket_stage_id", readonly=False
    )

    # ── Auto-assign & Team Notifications ─────────────────────────────────────
    helpdesk_default_team_id = fields.Many2one(
        comodel_name="helpdesk.ticket.team",
        string="Default Responsible Operating Unit",
        config_parameter="bunna_helpdesk.default_team_id",
        help="Fallback Responsible Operating Unit automatically assigned to incoming tickets.",
    )
    helpdesk_default_operating_unit_id = fields.Many2one(
        comodel_name="operating.unit",
        string="Default Operating Unit",
        config_parameter="bunna_helpdesk.default_operating_unit_id",
        help="Fallback Responsible Operating Unit from employee work units with its parent.",
    )
    helpdesk_default_operating_unit_parent_id = fields.Many2one(
        comodel_name="operating.unit",
        string="Parent Operating Unit",
        related="helpdesk_default_operating_unit_id.parent_unit",
        readonly=True,
    )

    @api.onchange("helpdesk_default_operating_unit_id")
    def _onchange_helpdesk_default_operating_unit_id(self):
        if self.helpdesk_default_operating_unit_id:
            team = self.env["helpdesk.ticket.team"].search(
                [("operating_unit_id", "=", self.helpdesk_default_operating_unit_id.id)],
                limit=1,
            )
            if team:
                self.helpdesk_default_team_id = team

    @api.onchange("helpdesk_default_team_id")
    def _onchange_helpdesk_default_team_id(self):
        if self.helpdesk_default_team_id and self.helpdesk_default_team_id.operating_unit_id:
            self.helpdesk_default_operating_unit_id = self.helpdesk_default_team_id.operating_unit_id
    helpdesk_notify_team_members = fields.Boolean(
        string="Notify Team & Members on Ticket Arrival",
        config_parameter="bunna_helpdesk.notify_team_members",
        default=True,
    )

    # ── Auto-Close Policy ────────────────────────────────────────────────────
    helpdesk_auto_close_tickets = fields.Boolean(
        string="Auto-Close Done Tickets",
        config_parameter="bunna_helpdesk.auto_close_tickets",
        default=True,
        help="Automatically move tickets from Done to Closed stage after configured grace period.",
    )
    helpdesk_auto_close_delay = fields.Integer(
        string="Auto-Close Delay Duration",
        config_parameter="bunna_helpdesk.auto_close_delay",
        default=3,
        help="Number of days or hours to wait after Done notification before closing.",
    )
    helpdesk_auto_close_unit = fields.Selection(
        selection=[
            ("hours", "Hours"),
            ("days", "Days"),
        ],
        string="Delay Unit",
        config_parameter="bunna_helpdesk.auto_close_unit",
        default="days",
        help="Unit of time for the auto-close delay.",
    )
    helpdesk_closed_stage_id = fields.Many2one(
        comodel_name="helpdesk.ticket.stage",
        string="Target Closed Stage",
        config_parameter="bunna_helpdesk.closed_stage_id",
        help="Stage to which tickets will be moved upon auto-close.",
    )
    # ── Bunna SMS Notifications ──────────────────────────────────────────────
    bunna_sms_acceptance_template = fields.Char(
        string="Acceptance SMS Template",
        config_parameter="bunna_helpdesk.bunna_sms_acceptance_template",
        default=(
            "Dear {first_name}\n"
            "Your Bunna Bank request {number} has been registered and accepted by {team_name}. We are currently processing it. For inquiries, call 8501.\n"
            "Bunna Bank S.C."
        ),
        help="Placeholders: {first_name}, {partner_name}, {number}, {reference}, {name}, {team_name}, {operating_unit_name}, {bank_hotline}",
    )
    bunna_sms_done_template = fields.Char(
        string="Done SMS Template",
        config_parameter="bunna_helpdesk.bunna_sms_done_template",
        default=(
            "Dear {first_name}\n"
            "Your Bunna Bank ticket {number} has been successfully resolved. Thank you for banking with Bunna Bank! Inquiries: 8501.\n"
            "Bunna Bank S.C."
        ),
        help="Placeholders: {first_name}, {partner_name}, {number}, {reference}, {name}, {team_name}, {operating_unit_name}, {bank_hotline}",
    )
    # ── Bunna SMS Gateway ────────────────────────────────────────────────────
    bunna_sms_endpoint = fields.Char(
        string="SMS Gateway URL",
        config_parameter="bunna_helpdesk.sms_endpoint",
        help="HTTP(S) endpoint that receives the SMS. Username and password are read from the cbs_integration table.",
    )
    bunna_sms_country_code = fields.Char(
        string="Default Country Code",
        config_parameter="bunna_helpdesk.sms_country_code",
        default="251",
        help="Used to convert local numbers (09XXXXXXXX -> 2519XXXXXXXX).",
    )
    bunna_sms_test_mobile = fields.Char(string="Test Mobile Number")

    def action_test_bunna_sms(self):
        """Send a test SMS with the gateway settings currently saved."""
        self.ensure_one()
        mobile = (self.bunna_sms_test_mobile or "").strip()
        if not mobile:
            notif_type, message = "warning", _("Enter a test mobile number first.")
        else:
            result = self.env["bunna.sms.service"].send_sms(
                mobile, _("Bunna Helpdesk test SMS. The SMS gateway is working.")
            )
            notif_type = "success" if result["success"] else "danger"
            message = result["detail"]
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("SMS Gateway Test"),
                "message": message,
                "type": notif_type,
                "sticky": notif_type != "success",
            },
        }

    # ── Bunna Notification Email Gateway (REST API) ──────────────────────────
    bunna_email_endpoint = fields.Char(
        string="Email Gateway URL",
        config_parameter="bunna_helpdesk.email_endpoint",
        help="HTTP(S) endpoint URL for sending formatted customer emails (e.g. http://sms-gateway-host:8080/api/email/send). If left empty, uses the SMS gateway endpoint base.",
    )
    bunna_email_test_recipient = fields.Char(string="Test Recipient Email")

    def action_test_bunna_email(self):
        """Send a test email with the In-House Notification API Gateway."""
        self.ensure_one()
        recipient = (self.bunna_email_test_recipient or "").strip()
        if not recipient:
            notif_type, message = "warning", _("Enter a test recipient email address first.")
        else:
            result = self.env["bunna.sms.service"].send_email(
                to_email=recipient,
                subject=_("Bunna Helpdesk Test Email"),
                body=_("<p>Dear Customer,<br/><br/>This is a test email sent via the <b>Bunna Bank In-House Notification API Gateway</b>.</p>"),
                recipient_name=_("Valued Customer"),
            )
            notif_type = "success" if result["success"] else "danger"
            message = result["detail"]
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Email Gateway Test"),
                "message": message,
                "type": notif_type,
                "sticky": notif_type != "success",
            },
        }

    helpdesk_mgmt_ticket_auto_assign = fields.Boolean(
        related="company_id.helpdesk_mgmt_ticket_auto_assign",
        readonly=False,
    )

    # ── SLA & Hierarchical Escalation ─────────────────────────────────────────
    helpdesk_mgmt_sla_active = fields.Boolean(
        related="company_id.helpdesk_mgmt_sla_active",
        readonly=False,
    )
    helpdesk_ceo_user_id = fields.Many2one(
        comodel_name="res.users",
        string="CEO / Executive Authority",
        help="Top-level authority for final SLA escalation. If not set, automatically determined from the top of the employee reporting hierarchy.",
        config_parameter="bunna_helpdesk.ceo_user_id",
    )
    cbs_endpoint = fields.Char(
        string="CBS Customer Endpoint URL",
        help="HTTP API endpoint URL for querying Finacle Core Banking customer profiles.",
        config_parameter="bunna_helpdesk.cbs_endpoint",
    )

    # ── Auto-close ────────────────────────────────────────────────────────────
    helpdesk_mgmt_auto_close_active = fields.Boolean(
        related="company_id.helpdesk_mgmt_auto_close_active",
        readonly=False,
    )
    helpdesk_mgmt_auto_close_days = fields.Integer(
        related="company_id.helpdesk_mgmt_auto_close_days",
        readonly=False,
    )
    helpdesk_mgmt_auto_close_stage_id = fields.Many2one(
        related="company_id.helpdesk_mgmt_auto_close_stage_id",
        readonly=False,
    )

    # ── Social Media & Omnichannel Integration ────────────────────────────────
    # Telegram Bot
    telegram_bot_active = fields.Boolean(
        string="Enable Telegram Bot",
        config_parameter="bunna_helpdesk.telegram_bot_active",
    )
    telegram_bot_token = fields.Char(
        string="Telegram Bot API Token",
        config_parameter="bunna_helpdesk.telegram_bot_token",
    )
    telegram_team_id = fields.Many2one(
        comodel_name="helpdesk.ticket.team",
        string="Telegram Default Team",
        config_parameter="bunna_helpdesk.telegram_team_id",
    )
    telegram_default_case_type_id = fields.Many2one(
        comodel_name="helpdesk.ticket.case.type",
        string="Telegram Default Case Type",
        config_parameter="bunna_helpdesk.telegram_default_case_type_id",
    )
    telegram_cron_interval_number = fields.Integer(
        string="Telegram Cron Polling Interval",
        help="Interval frequency for the Telegram message poller scheduled action.",
    )
    telegram_cron_interval_type = fields.Selection(
        selection=[
            ("minutes", "Minutes"),
            ("hours", "Hours"),
            ("days", "Days"),
            ("weeks", "Weeks"),
        ],
        string="Telegram Cron Interval Unit",
        default="hours",
        help="Unit of time for the Telegram message poller scheduled action.",
    )

    # ── Helpdesk REST API ─────────────────────────────────────────────────────
    helpdesk_api_active = fields.Boolean(
        string="Enable Helpdesk REST API",
        config_parameter="bunna_helpdesk.api_active",
        default=True,
        help="Enable external ticket creation and status REST API (/api/v1/helpdesk/ticket/create).",
    )
    helpdesk_api_master_key = fields.Char(
        string="Master API Key (Optional)",
        config_parameter="bunna_helpdesk.api_key",
        help="Optional shared master API key for direct server-to-server integration.",
    )

    def action_open_api_key_wizard(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Generate Helpdesk REST API Key",
            "res_model": "helpdesk.api.key.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_user_id": self.env.user.id},
        }

    # Website Chatbot (Odoo Live Chat chatbot / external chatbots such as Tidio)
    chatbot_ticket_active = fields.Boolean(
        string="Enable Public Chatbot Ticket Endpoint",
        config_parameter="bunna_helpdesk.chatbot_ticket_active",
        default=True,
        help="Allow external chatbots to create tickets through /helpdesk/chatbot/ticket. "
        "The Odoo Live Chat chatbot step does not need this switch.",
    )
    chatbot_api_key = fields.Char(
        string="Chatbot Endpoint API Key",
        config_parameter="bunna_helpdesk.chatbot_api_key",
        help="If set, external callers must send it in the X-Chatbot-Key header.",
    )
    chatbot_team_id = fields.Many2one(
        comodel_name="helpdesk.ticket.team",
        string="Chatbot Default Team",
        config_parameter="bunna_helpdesk.chatbot_team_id",
    )
    chatbot_default_case_type_id = fields.Many2one(
        comodel_name="helpdesk.ticket.case.type",
        string="Chatbot Default Case Type",
        config_parameter="bunna_helpdesk.chatbot_default_case_type_id",
    )

    # WhatsApp Business Cloud API (Meta)
    whatsapp_active = fields.Boolean(
        string="Enable WhatsApp Business API",
        config_parameter="bunna_helpdesk.whatsapp_active",
    )
    whatsapp_phone_number_id = fields.Char(
        string="WhatsApp Phone Number ID",
        config_parameter="bunna_helpdesk.whatsapp_phone_number_id",
    )
    whatsapp_access_token = fields.Char(
        string="Meta API Access Token",
        config_parameter="bunna_helpdesk.whatsapp_access_token",
    )
    whatsapp_verify_token = fields.Char(
        string="Webhook Verify Token",
        config_parameter="bunna_helpdesk.whatsapp_verify_token",
        default="bunna_bank_helpdesk_secret",
    )
    whatsapp_team_id = fields.Many2one(
        comodel_name="helpdesk.ticket.team",
        string="WhatsApp Default Team",
        config_parameter="bunna_helpdesk.whatsapp_team_id",
    )
    whatsapp_default_case_type_id = fields.Many2one(
        comodel_name="helpdesk.ticket.case.type",
        string="WhatsApp Default Case Type",
        config_parameter="bunna_helpdesk.whatsapp_default_case_type_id",
    )

    # Facebook Messenger / Page (Meta)
    facebook_active = fields.Boolean(
        string="Enable Facebook Messenger",
        config_parameter="bunna_helpdesk.facebook_active",
    )
    facebook_page_id = fields.Char(
        string="Facebook Page ID",
        config_parameter="bunna_helpdesk.facebook_page_id",
    )
    facebook_page_access_token = fields.Char(
        string="Page Access Token",
        config_parameter="bunna_helpdesk.facebook_page_access_token",
    )
    facebook_verify_token = fields.Char(
        string="Facebook Webhook Verify Token",
        config_parameter="bunna_helpdesk.facebook_verify_token",
        default="bunna_bank_helpdesk_secret",
    )
    facebook_team_id = fields.Many2one(
        comodel_name="helpdesk.ticket.team",
        string="Facebook Default Team",
        config_parameter="bunna_helpdesk.facebook_team_id",
    )
    facebook_default_case_type_id = fields.Many2one(
        comodel_name="helpdesk.ticket.case.type",
        string="Facebook Default Case Type",
        config_parameter="bunna_helpdesk.facebook_default_case_type_id",
    )

    def action_fetch_telegram_messages(self):
        """Manually trigger fetching messages from Telegram Bot."""
        res = self.env["helpdesk.social.channel"].fetch_telegram_updates()
        status = res.get("status")
        message = res.get("message", "")
        title = _("Telegram Sync")
        msg_type = "info" if status == "success" else "warning"
        if status == "error":
            msg_type = "danger"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": msg_type,
                "sticky": False,
            },
        }

    def action_register_telegram_webhook(self):
        """Register Telegram Webhook using current base URL."""
        res = self.env["helpdesk.social.channel"].register_telegram_webhook()
        status = res.get("status")
        message = res.get("message", "")
        title = _("Telegram Webhook")
        msg_type = "info" if status == "success" else "warning"
        if status == "error":
            msg_type = "danger"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": msg_type,
                "sticky": False,
            },
        }

    def action_simulate_whatsapp_ticket(self):
        """Simulate an incoming WhatsApp customer message for local testing."""
        social_channel = self.env["helpdesk.social.channel"].sudo()
        now_str = fields.Datetime.now().strftime("%Y%m%d%H%M%S")
        fake_payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "WABA_SIM_101",
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {"display_phone_number": "251911000000", "phone_number_id": "109876543210987"},
                                "contacts": [{"profile": {"name": "Dawit Tesfaye"}, "wa_id": "251922334455"}],
                                "messages": [
                                    {
                                        "from": "251922334455",
                                        "id": f"wamid.SIM_{now_str}",
                                        "timestamp": "1710000000",
                                        "text": {"body": "Hello Bunna Bank, my mobile banking transfer failed. Account: 1000987654321"},
                                        "type": "text",
                                    }
                                ],
                            },
                            "field": "messages",
                        }
                    ],
                }
            ],
        }
        tickets = social_channel.process_whatsapp_update(fake_payload)
        ticket = tickets[0] if tickets else False
        t_ref = ticket.number if ticket else "N/A"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("WhatsApp Simulation"),
                "message": _("Simulated incoming WhatsApp message created Ticket %s. Team notified!") % t_ref,
                "type": "success",
                "sticky": False,
            },
        }

    def action_simulate_facebook_ticket(self):
        """Simulate an incoming Facebook Messenger inquiry for local testing."""
        social_channel = self.env["helpdesk.social.channel"].sudo()
        now_str = fields.Datetime.now().strftime("%Y%m%d%H%M%S")
        fake_payload = {
            "object": "page",
            "entry": [
                {
                    "id": "FB_PAGE_101",
                    "time": 1710000000,
                    "messaging": [
                        {
                            "sender": {"id": "998877665544"},
                            "recipient": {"id": "FB_PAGE_101"},
                            "timestamp": 1710000000,
                            "message": {
                                "mid": f"mid.SIM_FB_{now_str}",
                                "text": "Good afternoon, I would like to inquire about Bunna Bank loan interest rates for SME. Phone: +251933445566, Account: 1000987654321",
                            },
                        }
                    ],
                }
            ],
        }
        tickets = social_channel.process_facebook_update(fake_payload)
        ticket = tickets[0] if tickets else False
        t_ref = ticket.number if ticket else "N/A"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Facebook Simulation"),
                "message": _("Simulated incoming Facebook Messenger message created Ticket %s. Team notified!") % t_ref,
                "type": "success",
                "sticky": False,
            },
        }

    def action_simulate_chatbot_ticket(self):
        """Simulate an incoming Website Chatbot / Tidio live chat inquiry for testing."""
        social_channel = self.env["helpdesk.social.channel"].sudo()
        now_str = fields.Datetime.now().strftime("%Y%m%d%H%M%S")
        fake_payload = {
            "visitor": {
                "name": "Almaz Ayana",
                "email": "almaz.ayana@example.com",
                "phone": "+251911445566",
                "id": f"tidio_vis_{now_str}",
            },
            "message": {
                "text": "Hello Bunna Bank support, my ATM card was captured at Mexico Branch ATM yesterday evening. Account number 100087654321.",
            },
            "thread_id": f"tidio_thr_{now_str}",
        }
        ticket = social_channel.process_chatbot_request(fake_payload)
        t_ref = ticket.number if ticket else "N/A"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Website Chatbot / Tidio Simulation"),
                "message": _("Simulated incoming Tidio Chatbot message created Ticket %s. Team notified!") % t_ref,
                "type": "success",
                "sticky": False,
            },
        }

    def get_values(self):
        res = super().get_values()
        icp = self.env["ir.config_parameter"].sudo()

        ou_param = icp.get_param("bunna_helpdesk.default_operating_unit_id")
        if ou_param and str(ou_param).isdigit():
            res["helpdesk_default_operating_unit_id"] = int(ou_param)
        elif res.get("helpdesk_default_team_id"):
            team = self.env["helpdesk.ticket.team"].browse(res["helpdesk_default_team_id"])
            if team.exists() and team.operating_unit_id:
                res["helpdesk_default_operating_unit_id"] = team.operating_unit_id.id
        cron = self.env.ref("bunna_helpdesk.ir_cron_fetch_telegram_messages", raise_if_not_found=False)

        # Telegram Cron Interval Number: if not set in settings, fallback to helpdesk_data.xml (cron default: 4)
        cron_num_param = icp.get_param("bunna_helpdesk.telegram_cron_interval_number")
        if cron_num_param:
            try:
                res["telegram_cron_interval_number"] = int(cron_num_param)
            except (ValueError, TypeError):
                res["telegram_cron_interval_number"] = cron.interval_number if cron else 4
        elif cron:
            res["telegram_cron_interval_number"] = cron.interval_number
        else:
            res["telegram_cron_interval_number"] = 4

        # Telegram Cron Interval Type: if not set in settings, fallback to helpdesk_data.xml (cron default: hours)
        cron_type_param = icp.get_param("bunna_helpdesk.telegram_cron_interval_type")
        if cron_type_param:
            res["telegram_cron_interval_type"] = cron_type_param
        elif cron:
            res["telegram_cron_interval_type"] = cron.interval_type
        else:
            res["telegram_cron_interval_type"] = "hours"

        return res

    def set_values(self):
        super().set_values()
        icp = self.env["ir.config_parameter"].sudo()

        if self.helpdesk_default_operating_unit_id:
            icp.set_param("bunna_helpdesk.default_operating_unit_id", str(self.helpdesk_default_operating_unit_id.id))
            if not self.helpdesk_default_team_id:
                team = self.env["helpdesk.ticket.team"].search(
                    [("operating_unit_id", "=", self.helpdesk_default_operating_unit_id.id)],
                    limit=1,
                )
                if team:
                    icp.set_param("bunna_helpdesk.default_team_id", str(team.id))
        elif self.helpdesk_default_team_id and self.helpdesk_default_team_id.operating_unit_id:
            icp.set_param("bunna_helpdesk.default_operating_unit_id", str(self.helpdesk_default_team_id.operating_unit_id.id))
        cron = self.env.ref("bunna_helpdesk.ir_cron_fetch_telegram_messages", raise_if_not_found=False)

        interval_num = self.telegram_cron_interval_number
        interval_type = self.telegram_cron_interval_type

        # If not configured or <= 0, fallback to default from helpdesk_data.xml (4 hours)
        if not interval_num or interval_num <= 0:
            interval_num = 4
            icp.set_param("bunna_helpdesk.telegram_cron_interval_number", "")
        else:
            icp.set_param("bunna_helpdesk.telegram_cron_interval_number", str(interval_num))

        if not interval_type:
            interval_type = "hours"
            icp.set_param("bunna_helpdesk.telegram_cron_interval_type", "")
        else:
            icp.set_param("bunna_helpdesk.telegram_cron_interval_type", str(interval_type))

        # Directly synchronize the scheduled action (ir.cron)
        if cron:
            cron_vals = {
                "interval_number": interval_num,
                "interval_type": interval_type,
            }
            if hasattr(self, "telegram_bot_active"):
                cron_vals["active"] = bool(self.telegram_bot_active)
            cron.sudo().write(cron_vals)




