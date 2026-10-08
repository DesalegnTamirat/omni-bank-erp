from odoo import fields, models, _


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
        string="Default Helpdesk Team",
        config_parameter="bunna_helpdesk.default_team_id",
    )
    helpdesk_notify_team_members = fields.Boolean(
        string="Notify Team & Members on Ticket Arrival",
        config_parameter="bunna_helpdesk.notify_team_members",
        default=True,
    )
    # ── Bunna SMS Notifications ──────────────────────────────────────────────
    bunna_sms_acceptance_template = fields.Char(
        string="Acceptance SMS Template",
        config_parameter="bunna_helpdesk.bunna_sms_acceptance_template",
        default="Dear {partner_name}, your Bunna Bank request {number} ('{name}') has been registered and accepted by {team_name}. We are currently processing it. For inquiries, call 8501. Bunna Bank S.C.",
        help="Placeholders: {partner_name}, {number}, {name}, {team_name}, {bank_hotline}",
    )
    bunna_sms_done_template = fields.Char(
        string="Done SMS Template",
        config_parameter="bunna_helpdesk.bunna_sms_done_template",
        default="Dear {partner_name}, your Bunna Bank ticket {number} ('{name}') has been successfully resolved. Thank you for banking with Bunna Bank! Inquiries: 8501.",
        help="Placeholders: {partner_name}, {number}, {name}, {team_name}, {bank_hotline}",
    )
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



