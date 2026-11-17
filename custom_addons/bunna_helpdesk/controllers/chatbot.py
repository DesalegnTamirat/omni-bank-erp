# -*- coding: utf-8 -*-
import hmac
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class HelpdeskChatbotController(http.Controller):
    """Public endpoint for external website chatbots (e.g. Tidio, custom bots).

    The Odoo Live Chat chatbot does not use HTTP: it calls the same service
    method directly through the bunna_helpdesk_livechat bridge module.
    """

    def _json(self, payload, status=200):
        return request.make_response(
            json.dumps(payload),
            headers=[("Content-Type", "application/json")],
            status=status,
        )

    @http.route(
        "/helpdesk/chatbot/ticket",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def chatbot_ticket(self, **kwargs):
        params = request.env["ir.config_parameter"].sudo()
        if params.get_param("bunna_helpdesk.chatbot_ticket_active") not in (True, "True", "true", "1", 1):
            return self._json({"success": False, "error": "Chatbot endpoint is disabled"}, status=403)

        expected_key = params.get_param("bunna_helpdesk.chatbot_api_key")
        if expected_key:
            received = request.httprequest.headers.get("X-Chatbot-Key", "")
            if not hmac.compare_digest(str(received), str(expected_key)):
                _logger.warning("Chatbot ticket request rejected: bad API key")
                return self._json({"success": False, "error": "Unauthorized"}, status=401)

        try:
            raw = request.httprequest.data
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            if not isinstance(payload, dict):
                raise ValueError("JSON object expected")
        except Exception:
            return self._json({"success": False, "error": "Invalid JSON"}, status=400)

        data = {
            "subject": payload.get("subject"),
            "description": payload.get("description") or payload.get("message"),
            "transcript": payload.get("transcript"),
            "full_name": payload.get("name") or payload.get("full_name"),
            "email": payload.get("email"),
            "phone": payload.get("phone"),
            "account_number": payload.get("account_number"),
            "session_id": payload.get("session_id"),
            "message_id": payload.get("message_id"),
        }
        try:
            ticket = request.env["helpdesk.social.channel"].sudo().process_chatbot_request(data)
        except Exception:
            _logger.exception("Error creating ticket from chatbot request")
            return self._json({"success": False, "error": "Could not create ticket"}, status=500)

        if not ticket:
            return self._json({"success": False, "error": "subject or description is required"}, status=400)
        return self._json(
            {
                "success": True,
                "ticket_id": ticket.id,
                "ticket_number": ticket.number,
                "channel_type": ticket.channel_type,
            }
        )
