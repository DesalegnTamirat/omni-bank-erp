# -*- coding: utf-8 -*-
import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class HelpdeskSocialWebhookController(http.Controller):

    # ── Telegram Bot Webhook ──────────────────────────────────────────────────

    @http.route(
        "/helpdesk/telegram/webhook",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def telegram_webhook(self, **kwargs):
        """Receive incoming message updates from Telegram Bot API."""
        try:
            raw_data = request.httprequest.data
            if not raw_data:
                return request.make_response(
                    json.dumps({"error": "Empty payload"}),
                    headers=[("Content-Type", "application/json")],
                    status=400,
                )
            payload = json.loads(raw_data.decode("utf-8"))
        except Exception as e:
            _logger.error("Failed to parse Telegram JSON payload: %s", str(e))
            return request.make_response(
                json.dumps({"error": "Invalid JSON"}),
                headers=[("Content-Type", "application/json")],
                status=400,
            )

        try:
            social_channel = request.env["helpdesk.social.channel"].sudo()
            social_channel.process_telegram_update(payload)
            return request.make_response(
                json.dumps({"ok": True}),
                headers=[("Content-Type", "application/json")],
            )
        except Exception as e:
            _logger.exception("Error processing Telegram update: %s", str(e))
            return request.make_response(
                json.dumps({"ok": False, "error": str(e)}),
                headers=[("Content-Type", "application/json")],
                status=500,
            )

    # ── WhatsApp Business Cloud API Webhook ───────────────────────────────────

    @http.route(
        "/helpdesk/whatsapp/webhook",
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
    )
    def whatsapp_webhook(self, **kwargs):
        """Handle Meta WhatsApp Cloud API verification handshake and incoming messages."""
        # Verification Handshake (GET)
        if request.httprequest.method == "GET":
            mode = kwargs.get("hub.mode")
            token = kwargs.get("hub.verify_token")
            challenge = kwargs.get("hub.challenge")

            expected_token = (
                request.env["ir.config_parameter"]
                .sudo()
                .get_param("bunna_helpdesk.whatsapp_verify_token", "bunna_bank_helpdesk_secret")
            )

            if mode == "subscribe" and token == expected_token:
                _logger.info("WhatsApp webhook verified successfully.")
                return request.make_response(
                    str(challenge),
                    headers=[("Content-Type", "text/plain")],
                )
            else:
                _logger.warning("WhatsApp webhook verification failed. Token mismatch: %s != %s", token, expected_token)
                return request.make_response("Forbidden", status=403)

        # Incoming Messages Notification (POST)
        try:
            raw_data = request.httprequest.data
            payload = json.loads(raw_data.decode("utf-8")) if raw_data else {}
        except Exception as e:
            _logger.error("Invalid WhatsApp JSON payload: %s", str(e))
            return request.make_response(
                json.dumps({"error": "Invalid JSON"}),
                headers=[("Content-Type", "application/json")],
                status=400,
            )

        try:
            social_channel = request.env["helpdesk.social.channel"].sudo()
            social_channel.process_whatsapp_update(payload)
            return request.make_response(
                json.dumps({"status": "EVENT_RECEIVED"}),
                headers=[("Content-Type", "application/json")],
            )
        except Exception as e:
            _logger.exception("Error processing WhatsApp update: %s", str(e))
            return request.make_response(
                json.dumps({"status": "ERROR", "error": str(e)}),
                headers=[("Content-Type", "application/json")],
                status=500,
            )

    # ── Facebook Messenger / Page Webhook ─────────────────────────────────────

    @http.route(
        "/helpdesk/facebook/webhook",
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
    )
    def facebook_webhook(self, **kwargs):
        """Handle Meta Facebook Messenger webhook verification handshake and incoming messages."""
        # Verification Handshake (GET)
        if request.httprequest.method == "GET":
            mode = kwargs.get("hub.mode")
            token = kwargs.get("hub.verify_token")
            challenge = kwargs.get("hub.challenge")

            expected_token = (
                request.env["ir.config_parameter"]
                .sudo()
                .get_param("bunna_helpdesk.facebook_verify_token", "bunna_bank_helpdesk_secret")
            )

            if mode == "subscribe" and token == expected_token:
                _logger.info("Facebook webhook verified successfully.")
                return request.make_response(
                    str(challenge),
                    headers=[("Content-Type", "text/plain")],
                )
            else:
                _logger.warning("Facebook webhook verification failed. Token mismatch: %s != %s", token, expected_token)
                return request.make_response("Forbidden", status=403)

        # Incoming Messages Notification (POST)
        try:
            raw_data = request.httprequest.data
            payload = json.loads(raw_data.decode("utf-8")) if raw_data else {}
        except Exception as e:
            _logger.error("Invalid Facebook JSON payload: %s", str(e))
            return request.make_response(
                json.dumps({"error": "Invalid JSON"}),
                headers=[("Content-Type", "application/json")],
                status=400,
            )

        try:
            social_channel = request.env["helpdesk.social.channel"].sudo()
            social_channel.process_facebook_update(payload)
            return request.make_response(
                json.dumps({"status": "EVENT_RECEIVED"}),
                headers=[("Content-Type", "application/json")],
            )
        except Exception as e:
            _logger.exception("Error processing Facebook update: %s", str(e))
            return request.make_response(
                json.dumps({"status": "ERROR", "error": str(e)}),
                headers=[("Content-Type", "application/json")],
                status=500,
            )

    # ── Simulation Endpoint (Local / Developer Testing) ───────────────────────

    @http.route(
        "/helpdesk/social/simulate",
        type="json",
        auth="user",
        methods=["POST"],
    )
    def simulate_social_ticket(self, channel, sender_name, sender_id, message_text, phone=None):
        """Simulate an incoming Telegram, WhatsApp, or Facebook ticket for testing."""
        social_channel = request.env["helpdesk.social.channel"].sudo()
        ticket = False

        if channel == "telegram":
            fake_update = {
                "update_id": 999999,
                "message": {
                    "message_id": 1001,
                    "from": {
                        "id": int(sender_id) if str(sender_id).isdigit() else 12345678,
                        "first_name": sender_name,
                        "username": sender_name.lower().replace(" ", "_"),
                    },
                    "chat": {"id": int(sender_id) if str(sender_id).isdigit() else 12345678, "type": "private"},
                    "text": message_text,
                    "contact": {"phone_number": phone} if phone else {},
                },
            }
            ticket = social_channel.process_telegram_update(fake_update)

        elif channel == "whatsapp":
            fake_payload = {
                "object": "whatsapp_business_account",
                "entry": [
                    {
                        "id": "WABA_SIM_123",
                        "changes": [
                            {
                                "value": {
                                    "messaging_product": "whatsapp",
                                    "metadata": {"display_phone_number": "251911000000", "phone_number_id": "PN_123"},
                                    "contacts": [{"profile": {"name": sender_name}, "wa_id": sender_id}],
                                    "messages": [
                                        {
                                            "from": sender_id,
                                            "id": "wamid.SIM12345678",
                                            "timestamp": "1710000000",
                                            "text": {"body": message_text},
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

        elif channel == "facebook":
            fake_payload = {
                "object": "page",
                "entry": [
                    {
                        "id": "PAGE_SIM_123",
                        "time": 1710000000,
                        "messaging": [
                            {
                                "sender": {"id": str(sender_id)},
                                "recipient": {"id": "PAGE_SIM_123"},
                                "timestamp": 1710000000,
                                "message": {
                                    "mid": "mid.SIM_FB_12345678",
                                    "text": message_text,
                                },
                            }
                        ],
                    }
                ],
            }
            tickets = social_channel.process_facebook_update(fake_payload)
            ticket = tickets[0] if tickets else False

        if ticket:
            return {
                "success": True,
                "ticket_id": ticket.id,
                "ticket_number": ticket.number,
                "ticket_name": ticket.name,
                "channel_type": ticket.channel_type,
                "partner_name": ticket.partner_name,
                "account_number": ticket.account_number,
                "cbs_status": ticket.cbs_lookup_status,
            }
        return {"success": False, "error": "Could not create ticket from simulation"}
