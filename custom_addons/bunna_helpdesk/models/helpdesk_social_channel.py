# -*- coding: utf-8 -*-
import json
import logging
import re
import urllib.request
import urllib.parse
import urllib.error

from odoo import api, fields, models, _
from odoo.tools import html_escape, plaintext2html

_logger = logging.getLogger(__name__)


class HelpdeskSocialChannel(models.AbstractModel):
    _name = "helpdesk.social.channel"
    _description = "Helpdesk Social Media & Omnichannel Service"

    # ── Telegram Bot Processor ────────────────────────────────────────────────

    @api.model
    def process_telegram_update(self, update_data):
        """Process incoming Telegram Bot update and auto-create helpdesk ticket."""
        if not update_data or not isinstance(update_data, dict):
            _logger.warning("Empty or invalid Telegram update received: %s", update_data)
            return False

        message = update_data.get("message") or update_data.get("edited_message")
        if not message:
            return False

        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        from_user = message.get("from", {})
        first_name = from_user.get("first_name") or ""
        last_name = from_user.get("last_name") or ""
        username = from_user.get("username")
        full_name = f"{first_name} {last_name}".strip()
        if not full_name:
            full_name = f"@{username}" if username else f"Telegram User {chat_id}"

        # Extract text or caption
        text = message.get("text") or message.get("caption") or ""
        message_id = str(message.get("message_id", ""))

        if text.strip() == "/start":
            welcome_msg = (
                f"Hello {full_name}! 👋\n\n"
                f"Welcome to Bunna Bank Customer Support.\n"
                f"Please describe your issue, request, or inquiry right here in this chat.\n\n"
                f"💡 <i>Tip: You can include your account number, transaction reference, or phone number to help us assist you faster.</i>"
            )
            self.send_telegram_message(chat_id=chat_id, text=welcome_msg)
            return False

        # Check contact sharing
        contact = message.get("contact", {})
        phone = contact.get("phone_number") or ""
        if phone and not phone.startswith("+"):
            phone = f"+{phone}"

        # If phone not shared directly, check if text has phone pattern (+251... or 09... or 07...)
        if not phone and text:
            phone_match = re.search(r"(\+?251\s?[79]\d{8}|0[79]\d{8})", text)
            if phone_match:
                raw_phone = phone_match.group(1).replace(" ", "")
                if raw_phone.startswith("0"):
                    phone = f"+251{raw_phone[1:]}"
                elif not raw_phone.startswith("+"):
                    phone = f"+{raw_phone}"
                else:
                    phone = raw_phone

        # Extract account number (11-16 digits, excluding phone number)
        account_number = False
        if text:
            for num_candidate in re.findall(r"\b\d{11,16}\b", text):
                if not phone or num_candidate not in phone:
                    account_number = num_candidate
                    break

        # Partner Resolution & CBS Finacle Lookup
        partner = self._resolve_partner(full_name=full_name, phone=phone, telegram_handle=username)

        # Team & Case Type configuration
        team_id = self._get_config_param("bunna_helpdesk.telegram_team_id")
        case_type_id = self._get_config_param("bunna_helpdesk.telegram_default_case_type_id")

        ticket_vals = {
            "name": f"Telegram: {(text or 'Customer Support Request')[:60]}",
            "description": (
                f"<p><strong>Sender:</strong> {full_name} (@{username or 'N/A'})</p>"
                f"<p><strong>Telegram Chat ID:</strong> {chat_id}</p>"
                f"<p><strong>Message:</strong></p><p>{text or '[Attachment / Image]'}</p>"
            ),
            "channel_type": "telegram",
            "social_chat_id": chat_id,
            "social_message_id": message_id,
            "partner_id": partner.id if partner else False,
            "partner_name": partner.name if partner else full_name,
            "partner_phone": phone or (partner.phone if partner else False),
        }
        if account_number:
            ticket_vals["account_number"] = account_number
        if team_id:
            ticket_vals["team_id"] = int(team_id)
        if case_type_id:
            ticket_vals["case_type_id"] = int(case_type_id)

        ticket = self.env["helpdesk.ticket"].create(ticket_vals)

        # Apply customer CBS banking profile if partner exists
        if partner:
            ticket._apply_customer_profile(partner)

        _logger.info("Successfully created Helpdesk Ticket %s from Telegram chat %s", ticket.number, chat_id)

        # Send automated Telegram acknowledgment reply
        reply_msg = (
            f"Hello {full_name},\n\n"
            f"Thank you for contacting Bunna Bank Contact Center!\n"
            f"Your request has been registered under Ticket Reference: {ticket.number}.\n\n"
            f"An agent will investigate and respond to you shortly."
        )
        self.send_telegram_message(chat_id=chat_id, text=reply_msg)

        return ticket

    @api.model
    def send_telegram_message(self, chat_id, text):
        """Dispatch message to customer on Telegram Bot API."""
        bot_token = self.env["ir.config_parameter"].sudo().get_param("bunna_helpdesk.telegram_bot_token")
        if not bot_token or not chat_id:
            _logger.info("Telegram reply skipped: bot_token or chat_id missing (chat_id: %s)", chat_id)
            return False

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status == 200
        except Exception as e:
            _logger.warning("Failed to send Telegram message to %s: %s", chat_id, str(e))
            return False

    @api.model
    def fetch_telegram_updates(self):
        """Poll Telegram getUpdates API for local or scheduled ticket creation."""
        bot_active = self.env["ir.config_parameter"].sudo().get_param("bunna_helpdesk.telegram_bot_active")
        if bot_active not in (True, "True", "true", "1", 1):
            return {"status": "warning", "message": _("Telegram Bot is disabled in Helpdesk settings.")}

        bot_token = self.env["ir.config_parameter"].sudo().get_param("bunna_helpdesk.telegram_bot_token")
        if not bot_token:
            return {"status": "error", "message": _("Telegram Bot Token is missing in Helpdesk settings.")}

        last_update_id = int(self.env["ir.config_parameter"].sudo().get_param("bunna_helpdesk.telegram_last_update_id", "0"))
        url = f"https://api.telegram.org/bot{bot_token}/getUpdates?offset={last_update_id + 1}&timeout=3"

        def _do_get():
            req = urllib.request.Request(url, headers={"User-Agent": "OdooHelpdesk/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))

        try:
            data = _do_get()
        except urllib.error.HTTPError as he:
            # If 409 Conflict because webhook is set, delete webhook and retry
            if he.code == 409:
                try:
                    del_url = f"https://api.telegram.org/bot{bot_token}/deleteWebhook"
                    with urllib.request.urlopen(del_url, timeout=10):
                        pass
                    data = _do_get()
                except Exception as inner_e:
                    _logger.warning("Telegram polling error after deleteWebhook: %s", str(inner_e))
                    return {"status": "error", "message": _("Telegram webhook conflict: %s") % str(inner_e)}
            else:
                _logger.warning("Telegram polling HTTP error: %s", str(he))
                return {"status": "error", "message": str(he)}
        except Exception as e:
            _logger.warning("Telegram polling network error: %s", str(e))
            return {"status": "error", "message": str(e)}

        if not data.get("ok"):
            desc = data.get("description", "Unknown error")
            return {"status": "error", "message": desc}

        updates = data.get("result", [])
        created_tickets = 0
        new_max_id = last_update_id

        for update in updates:
            up_id = update.get("update_id", 0)
            if up_id > new_max_id:
                new_max_id = up_id
            try:
                ticket = self.process_telegram_update(update)
                if ticket:
                    created_tickets += 1
            except Exception as e:
                _logger.error("Failed to process Telegram update %s: %s", up_id, str(e))

        if new_max_id > last_update_id:
            self.env["ir.config_parameter"].sudo().set_param("bunna_helpdesk.telegram_last_update_id", str(new_max_id))

        msg = _("Fetched %d update(s) from Telegram. %d ticket(s) created.") % (len(updates), created_tickets)
        _logger.info(msg)
        return {
            "status": "success",
            "count": len(updates),
            "tickets_created": created_tickets,
            "message": msg,
        }

    @api.model
    def register_telegram_webhook(self, base_url=None):
        """Set Telegram webhook to point to this instance's webhook endpoint."""
        bot_token = self.env["ir.config_parameter"].sudo().get_param("bunna_helpdesk.telegram_bot_token")
        if not bot_token:
            return {"status": "error", "message": _("Telegram Bot Token is not configured.")}

        if not base_url:
            base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")

        if not base_url or "localhost" in base_url or "127.0.0.1" in base_url:
            return {
                "status": "warning",
                "message": _(
                    "Current Web Base URL is '%s'. Telegram requires a public HTTPS domain.\n"
                    "For local development, use 'Fetch Telegram Messages Now' or leave background polling active."
                ) % base_url,
            }

        webhook_url = f"{base_url.rstrip('/')}/helpdesk/telegram/webhook"
        api_url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
        payload = {"url": webhook_url}

        try:
            req = urllib.request.Request(
                api_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read().decode("utf-8"))
                if result.get("ok"):
                    return {"status": "success", "message": _("Telegram Webhook successfully set to %s") % webhook_url}
                else:
                    return {"status": "error", "message": result.get("description", "Failed to set webhook")}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ── WhatsApp Business Cloud API Processor ─────────────────────────────────

    @api.model
    def process_whatsapp_update(self, payload):
        """Process incoming Meta WhatsApp Cloud API webhook update."""
        if not payload or not isinstance(payload, dict):
            return False

        entries = payload.get("entry", [])
        created_tickets = self.env["helpdesk.ticket"]

        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])
                contacts = {c.get("wa_id"): c.get("profile", {}).get("name") for c in value.get("contacts", [])}

                for msg in messages:
                    sender_wa_id = str(msg.get("from", ""))
                    msg_id = str(msg.get("id", ""))
                    msg_type = msg.get("type", "text")
                    sender_name = contacts.get(sender_wa_id) or f"+{sender_wa_id}"

                    text = ""
                    if msg_type == "text":
                        text = msg.get("text", {}).get("body", "")
                    elif msg_type == "image":
                        text = msg.get("image", {}).get("caption") or "[WhatsApp Photo Attachment]"
                    elif msg_type == "document":
                        text = msg.get("document", {}).get("caption") or "[WhatsApp Document Attachment]"
                    else:
                        text = f"[WhatsApp {msg_type.capitalize()} Message]"

                    # Format international phone number
                    phone = f"+{sender_wa_id.lstrip('+')}"

                    # Extract account number (11-16 digits)
                    account_number = False
                    if text:
                        for num_candidate in re.findall(r"\b\d{11,16}\b", text):
                            if num_candidate not in phone:
                                account_number = num_candidate
                                break

                    # Partner & Core Banking Profile Resolution
                    partner = self._resolve_partner(full_name=sender_name, phone=phone)

                    team_id = self._get_config_param("bunna_helpdesk.whatsapp_team_id")
                    case_type_id = self._get_config_param("bunna_helpdesk.whatsapp_default_case_type_id")

                    ticket_vals = {
                        "name": f"WhatsApp: {(text or 'WhatsApp Inbound Support')[:60]}",
                        "description": (
                            f"<p><strong>From:</strong> {sender_name} ({phone})</p>"
                            f"<p><strong>WhatsApp Message ID:</strong> {msg_id}</p>"
                            f"<p><strong>Message:</strong></p><p>{text}</p>"
                        ),
                        "channel_type": "whatsapp",
                        "social_chat_id": sender_wa_id,
                        "social_message_id": msg_id,
                        "partner_id": partner.id if partner else False,
                        "partner_name": partner.name if partner else sender_name,
                        "partner_phone": phone,
                    }
                    if account_number:
                        ticket_vals["account_number"] = account_number
                    if team_id:
                        ticket_vals["team_id"] = int(team_id)
                    if case_type_id:
                        ticket_vals["case_type_id"] = int(case_type_id)

                    ticket = self.env["helpdesk.ticket"].create(ticket_vals)

                    if partner:
                        ticket._apply_customer_profile(partner)

                    created_tickets |= ticket
                    _logger.info("Created Helpdesk Ticket %s from WhatsApp number %s", ticket.number, sender_wa_id)

                    # Automated WhatsApp Confirmation Reply
                    reply_text = (
                        f"Dear Customer,\n\n"
                        f"Thank you for reaching Bunna Bank Helpdesk. Your inquiry has been registered as Ticket #{ticket.number}.\n"
                        f"Our support team is reviewing it and will get back to you shortly."
                    )
                    self.send_whatsapp_message(recipient_phone=sender_wa_id, text=reply_text)

        return created_tickets

    @api.model
    def send_whatsapp_message(self, recipient_phone, text):
        """Dispatch text reply to recipient via Meta WhatsApp Cloud API."""
        config_obj = self.env["ir.config_parameter"].sudo()
        phone_number_id = config_obj.get_param("bunna_helpdesk.whatsapp_phone_number_id")
        access_token = config_obj.get_param("bunna_helpdesk.whatsapp_access_token")

        if not phone_number_id or not access_token or not recipient_phone:
            _logger.info("WhatsApp reply skipped: phone_number_id or access_token missing")
            return False

        url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": str(recipient_phone).lstrip("+"),
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {access_token}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status in (200, 201)
        except Exception as e:
            _logger.warning("Failed to send WhatsApp message to %s: %s", recipient_phone, str(e))
    # ── Facebook Messenger Processor ──────────────────────────────────────────

    @api.model
    def process_facebook_update(self, payload):
        """Process incoming Facebook Messenger webhook update and create tickets."""
        if not payload or not isinstance(payload, dict):
            return False

        entries = payload.get("entry", [])
        created_tickets = self.env["helpdesk.ticket"]

        for entry in entries:
            messaging_events = entry.get("messaging", [])
            for event in messaging_events:
                message = event.get("message")
                if not message or message.get("is_echo"):
                    continue

                sender_psid = str(event.get("sender", {}).get("id", ""))
                msg_id = str(message.get("mid", ""))
                text = message.get("text") or ""
                if not text:
                    attachments = message.get("attachments", [])
                    if attachments:
                        att_type = attachments[0].get("type", "attachment")
                        text = f"[Facebook {att_type.capitalize()} Attachment]"

                # Check if customer shared or mentioned phone number in the message
                phone = ""
                phone_match = re.search(r"(\+?251\s?[79]\d{8}|0[79]\d{8})", text)
                if phone_match:
                    raw_phone = phone_match.group(1).replace(" ", "")
                    if raw_phone.startswith("0"):
                        phone = f"+251{raw_phone[1:]}"
                    elif not raw_phone.startswith("+"):
                        phone = f"+{raw_phone}"
                    else:
                        phone = raw_phone

                # Extract account number (11-16 digits)
                account_number = False
                if text:
                    for num_candidate in re.findall(r"\b\d{11,16}\b", text):
                        if not phone or num_candidate not in phone:
                            account_number = num_candidate
                            break

                # Partner & Core Banking Profile Resolution
                sender_name = f"Facebook User {sender_psid[-6:]}"
                partner = self._resolve_partner(full_name=sender_name, phone=phone)

                team_id = self._get_config_param("bunna_helpdesk.facebook_team_id")
                case_type_id = self._get_config_param("bunna_helpdesk.facebook_default_case_type_id")

                ticket_vals = {
                    "name": f"Facebook: {(text or 'Facebook Support Inquiry')[:60]}",
                    "description": (
                        f"<p><strong>From:</strong> {sender_name} (PSID: {sender_psid})</p>"
                        f"<p><strong>Facebook Message ID:</strong> {msg_id}</p>"
                        f"<p><strong>Message:</strong></p><p>{text}</p>"
                    ),
                    "channel_type": "facebook",
                    "social_chat_id": sender_psid,
                    "social_message_id": msg_id,
                    "partner_id": partner.id if partner else False,
                    "partner_name": partner.name if partner else sender_name,
                    "partner_phone": phone or (partner.phone if partner else False),
                }
                if account_number:
                    ticket_vals["account_number"] = account_number
                if team_id:
                    ticket_vals["team_id"] = int(team_id)
                if case_type_id:
                    ticket_vals["case_type_id"] = int(case_type_id)

                ticket = self.env["helpdesk.ticket"].create(ticket_vals)

                if partner:
                    ticket._apply_customer_profile(partner)

                created_tickets |= ticket
                _logger.info("Created Helpdesk Ticket %s from Facebook PSID %s", ticket.number, sender_psid)

                # Automated Facebook Messenger Confirmation Reply
                reply_text = (
                    f"Hello,\n\n"
                    f"Thank you for contacting Bunna Bank via Facebook Messenger!\n"
                    f"Your inquiry has been registered as Ticket #{ticket.number}.\n"
                    f"Our support team will respond to you directly here."
                )
                self.send_facebook_message(recipient_psid=sender_psid, text=reply_text)

        return created_tickets

    @api.model
    def send_facebook_message(self, recipient_psid, text):
        """Dispatch text reply to recipient via Meta Facebook Send API."""
        config_obj = self.env["ir.config_parameter"].sudo()
        page_access_token = config_obj.get_param("bunna_helpdesk.facebook_page_access_token")

        if not page_access_token or not recipient_psid:
            _logger.info("Facebook reply skipped: page_access_token or recipient_psid missing")
            return False

        url = f"https://graph.facebook.com/v19.0/me/messages?access_token={page_access_token}"
        payload = {
            "recipient": {"id": recipient_psid},
            "message": {"text": text},
            "messaging_type": "RESPONSE",
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status in (200, 201)
        except Exception as e:
            _logger.warning("Failed to send Facebook message to %s: %s", recipient_psid, str(e))
            return False

    # ── Website Chatbot ───────────────────────────────────────────────────────

    @api.model
    def process_chatbot_request(self, data):
        """Create a helpdesk ticket (channel_type = 'chatbot') from a website chatbot.

        Used by the Odoo Live Chat chatbot step (bunna_helpdesk_livechat) and by
        the public /helpdesk/chatbot/ticket endpoint for external chatbots.

        :param dict data: keys (all optional except description or subject)
            subject, description, transcript (plain text), full_name, email,
            phone, account_number, session_id (dedupe key), message_id,
            partner_id (already identified customer)
        :return: helpdesk.ticket record (sudo) or empty recordset
        """
        data = data or {}
        # Support Tidio native webhook structure:
        visitor = data.get("visitor") if isinstance(data.get("visitor"), dict) else {}
        msg_obj = data.get("message") if isinstance(data.get("message"), dict) else {}

        full_name = (data.get("full_name") or data.get("name") or visitor.get("name") or "").strip()
        email = (data.get("email") or visitor.get("email") or "").strip()
        phone = (data.get("phone") or data.get("mobile") or visitor.get("phone") or "").strip()

        msg_val = data.get("message")
        if isinstance(msg_val, dict):
            raw_msg = msg_val.get("text") or ""
        elif isinstance(msg_val, str):
            raw_msg = msg_val
        else:
            raw_msg = ""

        raw_desc = data.get("description") if isinstance(data.get("description"), str) else ""
        msg_text = msg_obj.get("text") or ""
        description = (raw_desc or raw_msg or msg_text or "").strip()
        subject = (data.get("subject") or "").strip() if isinstance(data.get("subject"), str) else ""
        transcript = (data.get("transcript") or "").strip() if isinstance(data.get("transcript"), str) else ""

        combined_text = f"{subject} {description} {transcript}"
        if not phone and combined_text:
            phone_match = re.search(r"(\+?251\s?[79]\d{8}|0[79]\d{8})", combined_text)
            if phone_match:
                raw_phone = phone_match.group(1).replace(" ", "")
                if raw_phone.startswith("0"):
                    phone = f"+251{raw_phone[1:]}"
                elif not raw_phone.startswith("+"):
                    phone = f"+{raw_phone}"
                else:
                    phone = raw_phone

        account_number = (data.get("account_number") or "").strip()
        if not account_number and combined_text:
            for num_candidate in re.findall(r"\b\d{11,16}\b", combined_text):
                if not phone or num_candidate not in phone:
                    account_number = num_candidate
                    break

        if not (subject or description or transcript):
            _logger.warning("Chatbot ticket request ignored: no subject/description/transcript.")
            return self.env["helpdesk.ticket"]

        env_sudo = self.sudo()
        Ticket = env_sudo.env["helpdesk.ticket"]
        session_id = (str(data.get("session_id") or data.get("thread_id") or visitor.get("id") or "")).strip()[:120] or False

        # Idempotency: the same chatbot session cannot create a flood of tickets
        # (double click, retry of a failed HTTP call, bot re-processing a step).
        if session_id:
            since = fields.Datetime.subtract(fields.Datetime.now(), minutes=10)
            existing = Ticket.search(
                [
                    ("channel_type", "=", "chatbot"),
                    ("social_chat_id", "=", session_id),
                    ("create_date", ">=", since),
                ],
                limit=1,
            )
            if existing:
                return existing

        partner = self._resolve_chatbot_partner(
            partner_id=data.get("partner_id"), full_name=full_name, email=email, phone=phone
        )

        title_src = subject or description or transcript
        title_src = " ".join(title_src.split())
        body = ["<p><strong>Channel:</strong> Website Chatbot / Tidio Live Chat</p>"]
        if full_name or partner:
            body.append(f"<p><strong>Customer:</strong> {html_escape(full_name or partner.name)}</p>")
        if email:
            body.append(f"<p><strong>Email:</strong> {html_escape(email)}</p>")
        if phone:
            body.append(f"<p><strong>Phone:</strong> {html_escape(phone)}</p>")
        if session_id:
            body.append(f"<p><strong>Chat session / Thread ID:</strong> {html_escape(session_id)}</p>")
        body.append("<p><strong>Request:</strong></p>")
        body.append(str(plaintext2html(description or subject or transcript)))
        if transcript and transcript != description:
            body.append("<p><strong>Chatbot conversation:</strong></p>")
            body.append(str(plaintext2html(transcript)))

        ticket_vals = {
            "name": f"Chatbot: {title_src[:60]}",
            "description": "".join(body),
            "channel_type": "chatbot",
            "social_chat_id": session_id,
            "social_message_id": str(data.get("message_id") or "") or False,
            "partner_id": partner.id if partner else False,
            "partner_name": (partner.name if partner else full_name) or False,
            "partner_email": email or (partner.email if partner else False) or False,
            "partner_phone": phone or (partner.phone if partner else False) or False,
        }
        if account_number:
            ticket_vals["account_number"] = account_number
        team_id = self._get_config_param("bunna_helpdesk.chatbot_team_id")
        case_type_id = self._get_config_param("bunna_helpdesk.chatbot_default_case_type_id")
        if team_id:
            ticket_vals["team_id"] = team_id
        if case_type_id:
            ticket_vals["case_type_id"] = case_type_id

        ticket = Ticket.create(ticket_vals)

        if partner:
            try:
                with self.env.cr.savepoint():
                    ticket._apply_customer_profile(partner)
            except Exception:  # CBS profile is a nice-to-have, never block the ticket
                _logger.exception("Could not apply customer profile on chatbot ticket %s", ticket.number)

        _logger.info("Created Helpdesk Ticket %s from website chatbot session %s", ticket.number, session_id)
        return ticket

    @api.model
    def _resolve_chatbot_partner(self, partner_id=None, full_name=None, email=None, phone=None):
        """Known partner (logged-in user) > match by email > match by phone > create."""
        Partner = self.env["res.partner"].sudo()
        if partner_id:
            partner = Partner.browse(int(partner_id)).exists()
            if partner:
                return partner
        if email:
            partner = Partner.search([("email", "=ilike", email)], limit=1)
            if partner:
                return partner
        if phone:
            digits_suffix = phone[-9:] if len(phone) >= 9 else phone
            partner = Partner.search(
                ["|", ("phone", "=ilike", phone), ("phone", "=ilike", f"%{digits_suffix}")], limit=1
            )
            if partner:
                return partner
        if full_name or email or phone:
            return Partner.create(
                {
                    "name": full_name or email or phone,
                    "email": email or False,
                    "phone": phone or False,
                    "comment": "Auto-created from Website Chatbot",
                }
            )
        return Partner.browse()

    # ── Helper Methods ────────────────────────────────────────────────────────

    @api.model
    def _resolve_partner(self, full_name, phone=None, telegram_handle=None):
        """Match existing partner by phone / national ID or create a new one."""
        partner_obj = self.env["res.partner"].sudo()
        partner = False

        if phone:
            clean_phone = phone.strip()
            # Match exact or last 9 digits (handles 09... vs +2519...)
            digits_suffix = clean_phone[-9:] if len(clean_phone) >= 9 else clean_phone
            domain = ["|", ("phone", "=ilike", clean_phone), ("phone", "=ilike", f"%{digits_suffix}")]
            partner = partner_obj.search(domain, limit=1)

        if not partner and full_name:
            partner = partner_obj.search([("name", "=ilike", full_name.strip())], limit=1)

        if not partner:
            vals = {
                "name": full_name or "Social Customer",
                "phone": phone or False,
                "comment": f"Auto-created from Social Channel (Telegram: @{telegram_handle})" if telegram_handle else "Auto-created from WhatsApp",
            }
            partner = partner_obj.create(vals)

        return partner

    @api.model
    def _get_config_param(self, key):
        val = self.env["ir.config_parameter"].sudo().get_param(key)
        if val and str(val).isdigit():
            return int(val)
        return False
