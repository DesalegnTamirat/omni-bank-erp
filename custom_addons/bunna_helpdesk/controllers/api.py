# -*- coding: utf-8 -*-
import base64
import binascii
import datetime
import hmac
import json
import logging
import os

from odoo import fields, http
from odoo.http import request
from odoo.addons.base.models.res_users import (
    API_KEY_SIZE,
    INDEX_SIZE,
    KEY_CRYPT_CONTEXT,
)

_logger = logging.getLogger(__name__)


class HelpdeskApiController(http.Controller):
    """REST API Controller for Bunna Bank Contact Center & Helpdesk.

    Exposes external endpoints for:
      - Authentication & API key generation: /api/v1/helpdesk/auth/token
      - Ticket creation: /api/v1/helpdesk/ticket/create
      - Ticket status & lookup: /api/v1/helpdesk/ticket/<ticket_id_or_number>
      - Reference metadata: /api/v1/helpdesk/metadata
    """

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _json_response(self, data, status=200):
        headers = [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Access-Control-Allow-Origin", "*"),
            ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
            ("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-KEY, X-Requested-With"),
        ]
        return request.make_response(
            json.dumps(data, default=str),
            headers=headers,
            status=status,
        )

    def _json_error(self, message, status=400, details=None):
        payload = {
            "status": "error",
            "error": message,
        }
        if details is not None:
            payload["details"] = details
        return self._json_response(payload, status=status)

    def _extract_token(self):
        """Extract token from Authorization header (Bearer / Token), X-API-KEY header, or query param."""
        auth_header = request.httprequest.headers.get("Authorization", "").strip()
        if auth_header:
            parts = auth_header.split()
            if len(parts) == 2 and parts[0].lower() in ("bearer", "token", "apikey"):
                return parts[1]
            elif len(parts) == 1:
                return parts[0]

        x_api_key = request.httprequest.headers.get("X-API-KEY", "").strip()
        if x_api_key:
            return x_api_key

        query_key = request.params.get("api_key", "").strip()
        if query_key:
            return query_key

        return None

    def _authenticate_request(self):
        """Authenticate caller via Odoo res.users.apikeys or configured master API key.
        Returns (user, None, 200) or (None, error_message, status_code).
        """
        token = self._extract_token()
        if not token:
            return None, "Missing authentication credentials. Provide Bearer token in Authorization header or X-API-KEY header.", 401

        # 1. Check against master API key in system configuration (if configured)
        master_key = request.env["ir.config_parameter"].sudo().get_param("bunna_helpdesk.api_key")
        if master_key and hmac.compare_digest(master_key.strip(), token):
            admin_user = request.env.ref("base.user_admin", raise_if_not_found=False) or request.env["res.users"].sudo().browse(2)
            if admin_user:
                request.update_env(user=admin_user.id, su=True)
                return admin_user.sudo(), None, 200

        # 2. Check against native Odoo res.users.apikeys
        try:
            uid = (
                request.env["res.users.apikeys"].sudo()._check_credentials(scope="rpc", key=token)
                or request.env["res.users.apikeys"].sudo()._check_credentials(scope="helpdesk", key=token)
            )
            if uid:
                user = request.env["res.users"].sudo().browse(uid)
                if user.exists() and user.active:
                    request.update_env(user=user.id, su=True)
                    return user.sudo(), None, 200
                return None, "API Key user is inactive or deleted.", 401
        except Exception as e:
            _logger.warning("Error verifying API key: %s", str(e))

        return None, "Invalid or expired API key.", 401

    def _parse_json_payload(self):
        """Parse incoming JSON payload safely."""
        try:
            raw_data = request.httprequest.data
            if not raw_data:
                # Fallback to form parameters if JSON body is empty
                return dict(request.params)
            return json.loads(raw_data.decode("utf-8"))
        except Exception as e:
            _logger.warning("Failed to parse JSON body: %s", str(e))
            return None

    # ── 1. Authentication & API Key Generation ────────────────────────────────

    @http.route(
        [
            "/api/v1/helpdesk/auth/token",
            "/api/v1/helpdesk/auth/generate-key",
        ],
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        cors="*",
    )
    def api_auth_generate_token(self, **kwargs):
        """Authenticate user credentials (login + password) and generate a permanent
        or time-bound API Key stored in native Odoo res.users.apikeys.
        """
        payload = self._parse_json_payload()
        if payload is None:
            return self._json_error("Malformed JSON payload in request body", status=400)

        login = (payload.get("login") or payload.get("username") or "").strip()
        password = payload.get("password") or ""
        name = (payload.get("name") or payload.get("description") or "").strip()
        expiration_days = payload.get("expiration_days")

        if not login or not password:
            return self._json_error("Both 'login' (or 'username') and 'password' are required.", status=400)

        # Authenticate user with Odoo security
        try:
            uid = request.env["res.users"].sudo().authenticate(
                {"type": "password", "login": login, "password": password},
                user_agent_env={"interactive": False},
            )
        except Exception:
            uid = False

        if not uid:
            return self._json_error("Invalid username or password.", status=401)

        user = request.env["res.users"].sudo().browse(uid)
        key_name = name or f"Helpdesk API Key - {user.name} ({fields.Datetime.now().strftime('%Y-%m-%d %H:%M')})"

        # Calculate expiration
        expiration_date = None
        if expiration_days:
            try:
                days = int(expiration_days)
                if days > 0:
                    expiration_date = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)
            except (ValueError, TypeError):
                pass

        # Generate cryptographic API key and register in res_users_apikeys
        try:
            raw_key = binascii.hexlify(os.urandom(API_KEY_SIZE)).decode()
            hashed_key = KEY_CRYPT_CONTEXT.hash(raw_key)
            index = raw_key[:INDEX_SIZE]

            request.env.cr.execute(
                """
                INSERT INTO res_users_apikeys (name, user_id, scope, expiration_date, key, index)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                [key_name, user.id, None, expiration_date, hashed_key, index],
            )
            request.env.cr.commit()
        except Exception as e:
            _logger.exception("Failed to insert API key into database: %s", str(e))
            return self._json_error(f"Failed to generate API key: {str(e)}", status=500)

        base_url = request.httprequest.host_url.rstrip("/")
        return self._json_response(
            {
                "status": "success",
                "message": "API key generated successfully.",
                "api_key": raw_key,
                "token_type": "Bearer",
                "user": {
                    "id": user.id,
                    "name": user.name,
                    "login": user.login,
                    "email": user.email,
                    "company_id": user.company_id.id,
                    "company_name": user.company_id.name,
                },
                "key_details": {
                    "name": key_name,
                    "expiration_date": expiration_date.strftime("%Y-%m-%d %H:%M:%S") if expiration_date else "Never (Permanent)",
                },
                "usage": {
                    "header": f"Authorization: Bearer {raw_key}",
                    "alternative_header": f"X-API-KEY: {raw_key}",
                    "example_curl": (
                        f'curl -X POST "{base_url}/api/v1/helpdesk/ticket/create" \\\n'
                        f'  -H "Authorization: Bearer {raw_key}" \\\n'
                        f'  -H "Content-Type: application/json" \\\n'
                        f'  -d \'{{"subject": "Card retained by ATM", "description": "Customer ATM card was captured at Bole Branch.", "customer_name": "Abebe Kebede", "phone": "+251911234567"}}\''
                    ),
                },
            },
            status=200,
        )

    # ── 2. Ticket Creation Endpoint ───────────────────────────────────────────

    @http.route(
        [
            "/api/v1/helpdesk/ticket/create",
            "/api/v1/helpdesk/tickets",
        ],
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        cors="*",
    )
    def api_ticket_create(self, **kwargs):
        """Create a new Helpdesk Ticket via JSON API.
        Requires Bearer token or X-API-KEY authentication.
        """
        # Verify API is active
        api_active = request.env["ir.config_parameter"].sudo().get_param("bunna_helpdesk.api_active", default="True")
        if api_active not in (True, "True", "true", "1", 1):
            return self._json_error("Helpdesk REST API is currently disabled in system settings.", status=403)

        # Authenticate request
        user, error_msg, status_code = self._authenticate_request()
        if error_msg:
            return self._json_error(error_msg, status=status_code)

        payload = self._parse_json_payload()
        if payload is None:
            return self._json_error("Malformed JSON payload in request body", status=400)

        # Automatically unwrap if wrapped in vals_list or array
        if isinstance(payload, list) and payload:
            payload = payload[0]
        elif isinstance(payload, dict) and isinstance(payload.get("vals_list"), list) and payload["vals_list"]:
            payload = payload["vals_list"][0]

        # Extract ticket fields
        subject = (
            payload.get("subject")
            or payload.get("name")
            or payload.get("title")
            or ""
        ).strip()
        inquires = (
            payload.get("customer_inquires")
            or payload.get("customer_inquiries")
            or payload.get("customer_inquiry")
            or payload.get("inquires")
            or payload.get("inquiries")
            or ""
        ).strip()
        description = (
            payload.get("description")
            or inquires
            or payload.get("content")
            or payload.get("message")
            or payload.get("inquiry_summary")
            or ""
        ).strip()

        if not description and not subject:
            return self._json_error("Either 'subject' or 'description' is required to create a ticket.", status=400)

        if not description:
            description = subject
        if not subject:
            subject = description[:60]

        # Extract customer profile data
        cust = payload.get("customer") or {}
        customer_name = (cust.get("name") or payload.get("customer_name") or payload.get("partner_name") or "").strip()
        phone = (cust.get("phone") or payload.get("phone_number") or payload.get("phone") or payload.get("partner_phone") or "").strip()
        phone_secondary = (cust.get("secondary_phone") or payload.get("secondary_phone") or payload.get("partner_phone_secondary") or "").strip()
        email = (cust.get("email") or payload.get("customer_email") or payload.get("email") or payload.get("partner_email") or "").strip()
        account_number = (cust.get("account_number") or payload.get("account_number") or "").strip()
        cif_number = (cust.get("cif_number") or payload.get("cif_number") or "").strip()
        fayda_number = (cust.get("fayda_number") or payload.get("fayda_number") or "").strip()
        raw_status = (cust.get("customer_status") or payload.get("customer_status") or "").lower()
        if raw_status in ("new", "prospect"):
            customer_status = "new"
        elif raw_status in ("existing",):
            customer_status = "existing"
        elif account_number:
            customer_status = "existing"
        else:
            customer_status = "new"

        account_type = cust.get("account_type") or payload.get("account_type") or "Savings Account"

        # Partner lookup / creation
        partner_id = cust.get("id") or payload.get("partner_id")
        partner = False
        partner_model = request.env["res.partner"].sudo()

        if partner_id:
            partner = partner_model.browse(int(partner_id))
            if not partner.exists():
                partner = False

        if not partner and (account_number or cif_number or phone or email):
            # Attempt finding existing partner
            domain = []
            if account_number:
                domain.append(("account_number", "=", account_number))
            if cif_number:
                domain.append(("cif_number", "=", cif_number))
            if phone:
                domain.append(("phone", "=", phone))
            if email:
                domain.append(("email", "=", email))

            if domain:
                partner = partner_model.search(["|"] * (len(domain) - 1) + domain, limit=1)

        # Create partner if not found and customer details are provided
        if not partner and (customer_name or phone or email or account_number):
            try:
                partner_vals = {
                    "name": customer_name or phone or account_number or "API Customer",
                    "company_id": user.company_id.id or 1,
                }
                if phone:
                    partner_vals["phone"] = phone
                if email:
                    partner_vals["email"] = email
                if account_number:
                    partner_vals["account_number"] = account_number
                if cif_number:
                    partner_vals["cif_number"] = cif_number
                if fayda_number:
                    partner_vals["fayda_number"] = fayda_number
                partner = partner_model.create(partner_vals)
            except Exception as e:
                _logger.warning("Could not auto-create customer partner: %s", str(e))

        # Communication Channel (channel_type) & Channel resolution from API payload
        raw_channel = (
            payload.get("communication_channel")
            or payload.get("channel_type")
            or payload.get("channel")
            or payload.get("channel_id")
            or "api"
        )
        channel_str = str(raw_channel).strip().lower()

        # Map external channel strings to Odoo channel_type selection keys
        CHANNEL_TYPE_MAP = {
            "api": "api",
            "rest_api": "api",
            "rest": "api",
            "integration": "api",
            "mobile": "mobile_banking",
            "mobile_banking": "mobile_banking",
            "mobile_app": "mobile_banking",
            "app": "mobile_banking",
            "phone": "phone",
            "call": "phone",
            "ivr": "phone",
            "contact_center": "phone",
            "email": "email",
            "mail": "email",
            "tidio": "tidio_chat",
            "tidio_chat": "tidio_chat",
            "web": "web_portal",
            "web_portal": "web_portal",
            "portal": "web_portal",
            "website": "web_portal",
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
            "chat": "chatbot",
            "bot": "chatbot",
            "walkin": "branch_walkin",
            "branch": "branch_walkin",
            "branch_walkin": "branch_walkin",
        }
        resolved_channel_type = CHANNEL_TYPE_MAP.get(channel_str, "api")

        channel_model = request.env["helpdesk.ticket.channel"].sudo()
        channel = False
        if str(raw_channel).isdigit():
            channel = channel_model.browse(int(raw_channel))

        if not channel or not channel.exists():
            # Align channel_id comodel name
            TYPE_TO_CHANNEL_NAME = {
                "api": "API",
                "mobile_banking": "API",
                "phone": "Phone",
                "email": "Email",
                "web_portal": "Web",
                "tidio_chat": "Web",
                "telegram": "telegram",
                "whatsapp": "whatsapp",
                "chatbot": "Web",
                "facebook": "Other",
                "instagram": "Other",
                "branch_walkin": "Other",
            }
            target_ch_name = TYPE_TO_CHANNEL_NAME.get(resolved_channel_type, "API")
            channel = channel_model.search([("name", "=ilike", target_ch_name)], limit=1)

        if not channel or not channel.exists():
            channel = channel_model.search([("name", "=ilike", "api")], limit=1)
            if not channel:
                channel = channel_model.create({
                    "name": "API",
                    "company_id": user.company_id.id or 1,
                })

        # Case Type resolution
        case_type_input = payload.get("case_type") or payload.get("case_type_id") or payload.get("case_type_code")
        case_type = False
        case_model = request.env["helpdesk.ticket.case.type"].sudo()
        if case_type_input:
            if str(case_type_input).isdigit():
                case_type = case_model.browse(int(case_type_input))
            else:
                case_type = case_model.search([
                    "|",
                    ("code", "=", str(case_type_input).lower()),
                    ("name", "=ilike", str(case_type_input)),
                ], limit=1)

        if not case_type or not case_type.exists():
            case_type = case_model.search([("code", "=", "complaint")], limit=1) or case_model.search([], limit=1)

        # Priority resolution
        priority = str(payload.get("priority", "1"))
        priority_map = {"low": "0", "medium": "1", "high": "2", "very_high": "3", "urgent": "3"}
        priority = priority_map.get(priority.lower(), priority)
        if priority not in ("0", "1", "2", "3"):
            priority = "1"

        # Category resolution
        category_id = payload.get("category_id") or payload.get("category")
        category = False
        cat_model = request.env["helpdesk.ticket.category"].sudo()
        if category_id:
            if str(category_id).isdigit():
                category = cat_model.browse(int(category_id))
            else:
                category = cat_model.search([("name", "=ilike", str(category_id))], limit=1)

        # Build ticket create dictionary
        ticket_vals = {
            "name": subject,
            "description": description,
            "priority": priority,
            "channel_type": resolved_channel_type,
            "channel_id": channel.id if channel else False,
            "case_type_id": case_type.id if case_type else False,
            "company_id": user.company_id.id or 1,
            "partner_id": partner.id if partner else False,
            "partner_name": partner.name if partner else (customer_name or False),
            "customer_name": customer_name or (partner.name if partner else "Customer"),
            "partner_phone": phone or (partner.phone if partner else False),
            "phone_number": phone or (partner.phone if partner else False),
            "partner_phone_secondary": phone_secondary,
            "partner_email": email or (partner.email if partner else False),
            "customer_email": email or (partner.email if partner else False),
            "customer_inquires": inquires or (tools.html2plaintext(description).strip() if description else False),
            "customer_request_details": inquires or (tools.html2plaintext(description).strip() if description else False),
            "account_number": account_number or (partner.account_number if partner else False),
            "cif_number": cif_number or (partner.cif_number if partner else False),
            "fayda_number": fayda_number or (partner.fayda_number if partner else False),
            "account_type": account_type,
            "customer_status": customer_status,
        }

        if category and category.exists():
            ticket_vals["category_id"] = category.id

        # Optional organizational and routing fields
        if payload.get("team_id") and str(payload["team_id"]).isdigit():
            ticket_vals["team_id"] = int(payload["team_id"])
        if payload.get("operating_unit_id") and str(payload["operating_unit_id"]).isdigit():
            ticket_vals["operating_unit_id"] = int(payload["operating_unit_id"])
        if payload.get("operation_id") and str(payload["operation_id"]).isdigit():
            ticket_vals["operation_id"] = int(payload["operation_id"])
        if payload.get("service_family_id") and str(payload["service_family_id"]).isdigit():
            ticket_vals["service_family_id"] = int(payload["service_family_id"])
        if payload.get("service_id") and str(payload["service_id"]).isdigit():
            ticket_vals["service_id"] = int(payload["service_id"])
        if payload.get("service_sub_category_id") and str(payload["service_sub_category_id"]).isdigit():
            ticket_vals["service_sub_category_id"] = int(payload["service_sub_category_id"])

        # Tag IDs
        tag_names = payload.get("tags") or payload.get("tag_ids") or []
        if isinstance(tag_names, list) and tag_names:
            tag_ids = []
            tag_model = request.env["helpdesk.ticket.tag"].sudo()
            for t_item in tag_names:
                if str(t_item).isdigit():
                    tag_ids.append(int(t_item))
                else:
                    t_record = tag_model.search([("name", "=ilike", str(t_item))], limit=1)
                    if not t_record:
                        t_record = tag_model.create({"name": str(t_item), "company_id": user.company_id.id or 1})
                    tag_ids.append(t_record.id)
            if tag_ids:
                ticket_vals["tag_ids"] = [(6, 0, tag_ids)]

        # Create ticket record
        try:
            ticket = request.env["helpdesk.ticket"].sudo().create(ticket_vals)
            request.env.cr.commit()
        except Exception as e:
            _logger.exception("Failed to create helpdesk ticket via API: %s", str(e))
            return self._json_error(f"Failed to create ticket: {str(e)}", status=500)

        # Handle base64 attachments if provided
        attachments_input = payload.get("attachments") or []
        created_attachments = []
        if isinstance(attachments_input, list):
            att_model = request.env["ir.attachment"].sudo()
            for att_item in attachments_input:
                if not isinstance(att_item, dict):
                    continue
                file_name = att_item.get("name") or att_item.get("filename") or "attachment"
                file_datas = att_item.get("datas") or att_item.get("content") or ""
                mimetype = att_item.get("mimetype") or "application/octet-stream"

                if not file_datas:
                    continue

                try:
                    # Validate base64 decoding
                    base64.b64decode(file_datas)
                    attachment = att_model.create({
                        "name": file_name,
                        "res_model": "helpdesk.ticket",
                        "res_id": ticket.id,
                        "type": "binary",
                        "db_datas": file_datas,
                        "store_fname": False,
                        "mimetype": mimetype,
                        "company_id": ticket.company_id.id or user.company_id.id or 1,
                    })
                    created_attachments.append({
                        "id": attachment.id,
                        "name": attachment.name,
                        "mimetype": attachment.mimetype,
                    })
                except Exception as att_err:
                    _logger.warning("Failed to attach file '%s' to ticket %s: %s", file_name, ticket.id, str(att_err))

        # Commit attachment creation
        if created_attachments:
            request.env.cr.commit()

        # Format clean response
        priority_label = dict(ticket._fields["priority"].selection).get(ticket.priority, ticket.priority)
        base_url = request.httprequest.host_url.rstrip("/")

        return self._json_response(
            {
                "status": "success",
                "message": f"Ticket {ticket.number} created successfully.",
                "ticket": {
                    "id": ticket.id,
                    "number": ticket.number,
                    "name": ticket.name,
                    "description": ticket.description,
                    "priority": ticket.priority,
                    "priority_label": priority_label,
                    "communication_channel": ticket.channel_type,
                    "communication_channel_label": dict(ticket._fields["channel_type"].selection).get(ticket.channel_type, ticket.channel_type),
                    "stage": ticket.stage_id.name if ticket.stage_id else None,
                    "case_type": ticket.case_type_id.name if ticket.case_type_id else None,
                    "channel": ticket.channel_id.name if ticket.channel_id else None,
                    "team": ticket.team_id.name if ticket.team_id else None,
                    "operating_unit": ticket.operating_unit_id.name if ticket.operating_unit_id else None,
                    "assigned_user": ticket.user_id.name if ticket.user_id else None,
                    "contact_center_agent": ticket.contact_center_agent_id.name if ticket.contact_center_agent_id else None,
                    "customer": {
                        "id": ticket.partner_id.id if ticket.partner_id else None,
                        "name": ticket.partner_name or (ticket.partner_id.name if ticket.partner_id else None),
                        "phone": ticket.partner_phone,
                        "email": ticket.partner_email,
                        "account_number": ticket.account_number,
                        "cif_number": ticket.cif_number,
                        "fayda_number": ticket.fayda_number,
                    },
                    "attachments": created_attachments,
                    "created_at": ticket.create_date.strftime("%Y-%m-%d %H:%M:%S") if ticket.create_date else None,
                    "direct_url": f"{base_url}/odoo/helpdesk.ticket/{ticket.id}",
                },
            },
            status=201,
        )

    # ── 3. Ticket Status & Detail Endpoint ────────────────────────────────────

    @http.route(
        "/api/v1/helpdesk/ticket/<string:ticket_ref>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        cors="*",
    )
    def api_ticket_get(self, ticket_ref, **kwargs):
        """Query ticket status and details by numeric ID or Ticket Number (e.g. HT00262)."""
        user, error_msg, status_code = self._authenticate_request()
        if error_msg:
            return self._json_error(error_msg, status=status_code)

        ticket_model = request.env["helpdesk.ticket"].sudo().with_user(user)
        ticket = False

        if ticket_ref.isdigit():
            ticket = ticket_model.browse(int(ticket_ref))
        if not ticket or not ticket.exists():
            ticket = ticket_model.search([("number", "=", ticket_ref)], limit=1)

        if not ticket or not ticket.exists():
            return self._json_error(f"Ticket '{ticket_ref}' not found.", status=404)

        priority_label = dict(ticket._fields["priority"].selection).get(ticket.priority, ticket.priority)
        base_url = request.httprequest.host_url.rstrip("/")

        return self._json_response(
            {
                "status": "success",
                "ticket": {
                    "id": ticket.id,
                    "number": ticket.number,
                    "name": ticket.name,
                    "description": ticket.description,
                    "priority": ticket.priority,
                    "priority_label": priority_label,
                    "communication_channel": ticket.channel_type,
                    "communication_channel_label": dict(ticket._fields["channel_type"].selection).get(ticket.channel_type, ticket.channel_type),
                    "stage": ticket.stage_id.name if ticket.stage_id else None,
                    "is_closed": bool(ticket.closed),
                    "case_type": ticket.case_type_id.name if ticket.case_type_id else None,
                    "channel": ticket.channel_id.name if ticket.channel_id else None,
                    "team": ticket.team_id.name if ticket.team_id else None,
                    "operating_unit": ticket.operating_unit_id.name if ticket.operating_unit_id else None,
                    "assigned_user": ticket.user_id.name if ticket.user_id else None,
                    "contact_center_agent": ticket.contact_center_agent_id.name if ticket.contact_center_agent_id else None,
                    "customer": {
                        "id": ticket.partner_id.id if ticket.partner_id else None,
                        "name": ticket.partner_name or (ticket.partner_id.name if ticket.partner_id else None),
                        "phone": ticket.partner_phone,
                        "email": ticket.partner_email,
                        "account_number": ticket.account_number,
                        "cif_number": ticket.cif_number,
                        "fayda_number": ticket.fayda_number,
                    },
                    "created_at": ticket.create_date.strftime("%Y-%m-%d %H:%M:%S") if ticket.create_date else None,
                    "closed_date": ticket.closed_date.strftime("%Y-%m-%d %H:%M:%S") if ticket.closed_date else None,
                    "direct_url": f"{base_url}/odoo/helpdesk.ticket/{ticket.id}",
                },
            },
            status=200,
        )

    # ── 4. Metadata Reference Endpoint ────────────────────────────────────────

    @http.route(
        "/api/v1/helpdesk/metadata",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        cors="*",
    )
    def api_metadata(self, **kwargs):
        """Retrieve available case types, channels, priorities, and teams for API clients."""
        user, error_msg, status_code = self._authenticate_request()
        if error_msg:
            return self._json_error(error_msg, status=status_code)

        env = request.env

        case_types = [
            {"id": ct.id, "name": ct.name, "code": getattr(ct, "code", "")}
            for ct in env["helpdesk.ticket.case.type"].sudo().search([])
        ]
        channels = [
            {"id": ch.id, "name": ch.name}
            for ch in env["helpdesk.ticket.channel"].sudo().search([])
        ]
        priorities = [
            {"value": k, "label": v}
            for k, v in env["helpdesk.ticket"]._fields["priority"].selection
        ]
        communication_channels = [
            {"value": k, "label": v}
            for k, v in env["helpdesk.ticket"]._fields["channel_type"].selection
        ]
        teams = [
            {"id": t.id, "name": t.name}
            for t in env["helpdesk.ticket.team"].sudo().search([("active", "=", True)], limit=50)
        ]

        return self._json_response(
            {
                "status": "success",
                "case_types": case_types,
                "channels": channels,
                "communication_channels": communication_channels,
                "priorities": priorities,
                "teams": teams,
            },
            status=200,
        )
