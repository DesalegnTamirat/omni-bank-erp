# -*- coding: utf-8 -*-
"""CBS SMS gateway integration.

Credentials (username, password) are read at runtime from the existing
``cbs_integration`` table of the current database (row selected by
``bunna_helpdesk.sms_environment``, default "SMS").

The gateway URL is entered in Helpdesk > Configuration > Settings > "Bunna SMS
Gateway" (system parameter ``bunna_helpdesk.sms_endpoint``). When it is empty,
the ``endpoint`` column of the same ``cbs_integration`` row is used.

Nothing is stored in source code, XML, JS, .env or Docker files.

Two abstract (table-less) models live here:

* ``cbs.integration.config`` - safe, read-only reader of ``cbs_integration``.
  The table has no Odoo model in this project (``cbs_service.get_cbs_credentials``
  already reads it with SQL), so we do not map it with ``_auto = False``: that
  would make the ORM assume a primary key / extra columns and expose the
  password through ORM reads, exports and the UI.
* ``bunna.sms.service`` - reusable SMS sender used by the ticket workflow.
"""
import json
import logging
import re
import time
from urllib.parse import urlparse

import requests

from odoo import _, api, models

_logger = logging.getLogger(__name__)

# Selector used to pick the row of cbs_integration that holds the SMS gateway
# settings. It is NOT a credential. It can be overridden without code change
# through the system parameter ``bunna_helpdesk.sms_environment``.
DEFAULT_SMS_ENVIRONMENT = "SMS"
SMS_ENVIRONMENT_PARAM = "bunna_helpdesk.sms_environment"
SMS_ENDPOINT_PARAM = "bunna_helpdesk.sms_endpoint"

# Default country calling code used to normalise local mobile numbers
# (09XXXXXXXX -> 2519XXXXXXXX). Overridable with ``bunna_helpdesk.sms_country_code``.
DEFAULT_COUNTRY_CODE = "251"
COUNTRY_CODE_PARAM = "bunna_helpdesk.sms_country_code"

SMS_TIMEOUT = (5.0, 15.0)  # (connect, read) seconds
_ACTIVE_VALUES = ("true", "t", "1", "yes", "y", "active")
_FAILURE_WORDS = ("fail", "error", "reject", "invalid", "denied", "unauthor")

# In-memory token cache: {"token": str, "expires_at": float}
_SMS_TOKEN_CACHE = {
    "token": None,
    "expires_at": 0,
}


def _safe_host(endpoint):
    """host[:port] only - never log userinfo, path or query string."""
    try:
        parsed = urlparse(endpoint)
        return parsed.netloc.rsplit("@", 1)[-1] or "?"
    except Exception:  # pragma: no cover - defensive
        return "?"


def get_sms_access_token(username, password, base_url, force_refresh=False):
    """Authenticate against Bunna Bank SMS Gateway (JWT) and cache token."""
    global _SMS_TOKEN_CACHE
    now = time.time()
    if not force_refresh and _SMS_TOKEN_CACHE.get("token") and _SMS_TOKEN_CACHE.get("expires_at", 0) > (now + 60):
        return _SMS_TOKEN_CACHE["token"]

    if not username or not password or not base_url:
        return None

    clean_base = str(base_url).strip().rstrip("/")
    if clean_base.endswith("/sms"):
        login_url = f"{clean_base}/auth/login"
    else:
        login_url = f"{clean_base}/sms/auth/login"

    try:
        resp = requests.post(
            login_url,
            json={"username": username, "password": password},
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "BunnaHelpdesk-SMSConnector/1.0",
            },
            timeout=(4.0, 8.0),
        )
        if resp.status_code == 200:
            data = resp.json()
            token = data.get("accessToken") or data.get("token") or data.get("jwt")
            if token:
                _SMS_TOKEN_CACHE["token"] = token
                _SMS_TOKEN_CACHE["expires_at"] = now + 900  # cache for 15 minutes
                _logger.info("Successfully authenticated with Bunna SMS Gateway.")
                return token
        _logger.warning("SMS Gateway login failed at %s with status %s", login_url, resp.status_code)
    except Exception as exc:
        _logger.warning("SMS Gateway login error: %s", exc.__class__.__name__)
    return None


_SMS_CONFIG_CACHE = {}

class CbsIntegrationConfig(models.AbstractModel):
    _name = "cbs.integration.config"
    _description = "CBS Integration Configuration Reader (cbs_integration table)"

    @api.model
    def _table_columns(self):
        try:
            with self.env.registry.cursor() as fresh_cr:
                fresh_cr.execute(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = 'cbs_integration'
                    """
                )
                return {row[0] for row in fresh_cr.fetchall()}
        except Exception as e:
            _logger.warning("Could not check cbs_integration columns: %s", e)
            return set()

    @api.model
    def get_config(self, environment=None):
        """Return the gateway configuration.

        Username / password always come from the ``cbs_integration`` row,
        transparently decrypted via PostgreSQL pgcrypto cbs_decode(). The
        URL from the Settings screen overrides the row's ``endpoint`` when set.

        :return: dict(username, password, endpoint, environment) or ``None``.
        The password is returned to the caller in memory only; it is never
        logged nor stored anywhere else.
        """
        global _SMS_CONFIG_CACHE
        if not environment:
            environment = (
                self.env["ir.config_parameter"].sudo().get_param(SMS_ENVIRONMENT_PARAM)
                or DEFAULT_SMS_ENVIRONMENT
            )
        environment = str(environment).strip()
        now = time.time()
        cached = _SMS_CONFIG_CACHE.get(environment)
        if cached and cached.get("expires_at", 0) > now:
            return dict(cached["config"])

        row = None
        try:
            with self.env.registry.cursor() as fresh_cr:
                columns = self._table_columns()
                required = {"username", "password", "endpoint", "environment"}
                if not columns:
                    _logger.warning("cbs_integration table does not exist in this database.")
                    return None
                if not required <= columns:
                    _logger.warning(
                        "cbs_integration is missing column(s): %s",
                        ", ".join(sorted(required - columns)),
                    )
                    return None
                query = (
                    "SELECT username, cbs_decode(password), endpoint, environment "
                    "FROM cbs_integration WHERE UPPER(TRIM(environment)) = UPPER(%s)"
                )
                params = [environment]
                if "status" in columns:
                    # status is stored as text ('true'/'false') or NULL (default active) in this project
                    query += " AND (status IS NULL OR LOWER(TRIM(status::text)) IN %s)"
                    params.append(_ACTIVE_VALUES)
                query += " LIMIT 1"
                try:
                    fresh_cr.execute(query, params)
                    row = fresh_cr.fetchone()
                except Exception:
                    fresh_cr.rollback()
                    # Fallback query if cbs_decode is missing
                    try:
                        fallback_query = (
                            "SELECT username, password, endpoint, environment "
                            "FROM cbs_integration WHERE UPPER(TRIM(environment)) = UPPER(%s)"
                        )
                        if "status" in columns:
                            fallback_query += " AND (status IS NULL OR LOWER(TRIM(status::text)) IN %s)"
                        fallback_query += " LIMIT 1"
                        fresh_cr.execute(fallback_query, params)
                        row = fresh_cr.fetchone()
                    except Exception:
                        fresh_cr.rollback()
        except Exception as exc:
            _logger.error("Could not read cbs_integration: %s", exc.__class__.__name__)
            return None
        if not row:
            return None
        endpoint_setting = (
            self.env["ir.config_parameter"].sudo().get_param(SMS_ENDPOINT_PARAM) or ""
        ).strip()
        cfg = {
            "username": str(row[0] or "").strip(),
            "password": str(row[1] or "").strip(),
            "endpoint": endpoint_setting or str(row[2] or "").strip(),
            "environment": str(row[3] or environment).strip(),
        }
        _SMS_CONFIG_CACHE[environment] = {
            "config": dict(cfg),
            "expires_at": now + 300,
        }
        return cfg
        return {
            "username": str(row[0] or "").strip(),
            "password": str(row[1] or "").strip(),
            "endpoint": endpoint_setting or str(row[2] or "").strip(),
            "environment": str(row[3] or "").strip(),
        }


class BunnaSmsService(models.AbstractModel):
    _name = "bunna.sms.service"
    _description = "Bunna CBS SMS Service"

    # ── helpers ──────────────────────────────────────────────────────────────

    @api.model
    def normalize_mobile(self, number):
        """Return the number in international digits-only form (2519XXXXXXXX)
        or ``False`` when it is not a plausible mobile number."""
        if not number:
            return False
        raw = str(number).strip()
        # keep the first number if several were typed in one field
        raw = re.split(r"[/,;]", raw)[0]
        digits = re.sub(r"\D", "", raw)
        if digits.startswith("00"):
            digits = digits[2:]
        cc = (
            self.env["ir.config_parameter"].sudo().get_param(COUNTRY_CODE_PARAM)
            or DEFAULT_COUNTRY_CODE
        )
        cc = re.sub(r"\D", "", cc)
        if digits.startswith(cc):
            national = digits[len(cc):]
        elif digits.startswith("0"):
            national = digits[1:]
        else:
            national = digits
        # Ethiopian mobile numbers: 9 digits starting with 9 (Ethio Telecom) or 7 (Safaricom)
        if cc == "251" and not re.fullmatch(r"[97]\d{8}", national):
            return False
        if not re.fullmatch(r"\d{7,12}", national):
            return False
        return cc + national

    @api.model
    def _validate_config(self, config):
        if not config:
            return _("SMS credentials not found in cbs_integration (environment row missing or inactive).")
        missing = [k for k in ("username", "password", "endpoint", "environment") if not config.get(k)]
        if missing:
            return _("SMS integration configuration is incomplete (missing: %s).") % ", ".join(missing)
        if not re.match(r"^https?://", config["endpoint"], re.I):
            return _("SMS integration endpoint is not a valid http(s) URL.")
        return False

    @api.model
    def _build_request(self, config, mobile, message, token=None):
        """Build the SMS gateway HTTP request matching OpenAPI specification.

        If a JWT Bearer token is provided:
        POST <base>/api/v1/core/sms/sendsms
        Authorization: Bearer <token>
        {"recipientPhoneNumber": "<mobile>", "messageBody": "<message>"}

        Fallback (Basic Auth legacy):
        POST <base> (Basic auth)
        {"mobile": "<mobile>", "message": "<message>"}
        """
        clean_endpoint = config["endpoint"].rstrip("/")
        if token:
            if clean_endpoint.endswith("/sms"):
                send_url = f"{clean_endpoint}/api/v1/core/sms/sendsms"
            elif "/api/v1/core/sms/sendsms" in clean_endpoint:
                send_url = clean_endpoint
            else:
                send_url = f"{clean_endpoint}/sms/api/v1/core/sms/sendsms"
            return {
                "url": send_url,
                "headers": {
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": "BunnaHelpdesk-SMSConnector/1.0",
                },
                "data": json.dumps({"recipientPhoneNumber": mobile, "messageBody": message}),
            }

        # Fallback to direct URL with Basic Auth and both schemas
        return {
            "url": clean_endpoint,
            "auth": (config["username"], config["password"]),
            "headers": {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "BunnaHelpdesk-SMSConnector/1.0",
            },
            "data": json.dumps({
                "recipientPhoneNumber": mobile,
                "messageBody": message,
                "mobile": mobile,
                "message": message,
            }),
        }

    @api.model
    def _parse_response(self, resp):
        """Return (ok, detail) for an HTTP response. Never includes secrets."""
        if resp.status_code in (401, 403):
            return False, _("SMS gateway rejected the credentials (HTTP %s).") % resp.status_code
        if not 200 <= resp.status_code < 300:
            return False, _("SMS gateway returned HTTP %s.") % resp.status_code
        text = (resp.text or "").strip()
        try:
            payload = resp.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            lowered = {str(k).lower(): v for k, v in payload.items()}
            for key in ("success", "ok"):
                if key in lowered and lowered[key] in (False, "false", "False", 0, "0"):
                    return False, _("SMS gateway reported failure: %s") % str(
                        lowered.get("message") or lowered.get("error") or "")[:200]
            status = lowered.get("status")
            if isinstance(status, str) and any(w in status.lower() for w in _FAILURE_WORDS):
                return False, _("SMS gateway reported failure: %s") % status[:200]
            if "error" in lowered and lowered["error"]:
                return False, _("SMS gateway reported failure: %s") % str(lowered["error"])[:200]
            return True, _("SMS accepted by gateway.")
        if payload is None and text:
            if any(w in text.lower()[:200] for w in _FAILURE_WORDS):
                return False, _("SMS gateway returned an error response.")
            return True, _("SMS accepted by gateway.")
        if payload is None and not text:
            return False, _("SMS gateway returned an empty response.")
        return True, _("SMS accepted by gateway.")

    # ── public API ───────────────────────────────────────────────────────────

    @api.model
    def send_sms(self, mobile, message, environment=None):
        """Send one SMS through the CBS SMS gateway.

        Never raises. :return: dict(success: bool, detail: str, mobile: str|False)
        """
        normalized = self.normalize_mobile(mobile)
        if not normalized:
            _logger.warning("SMS skipped: missing or invalid customer mobile number.")
            return {"success": False, "detail": _("Missing or invalid mobile number."), "mobile": False}
        if not message:
            return {"success": False, "detail": _("Empty SMS message."), "mobile": normalized}

        config = self.env["cbs.integration.config"].sudo().get_config(environment)
        error = self._validate_config(config)
        if error:
            _logger.warning("SMS configuration problem: %s", error)
            return {"success": False, "detail": error, "mobile": normalized}
        _logger.info(
            "SMS configuration found (environment=%s, host=%s).",
            config["environment"], _safe_host(config["endpoint"]),
        )

        masked = "*" * (len(normalized) - 4) + normalized[-4:]
        _logger.info("SMS request initiated to %s via %s.", masked, _safe_host(config["endpoint"]))

        # Step 1: Obtain JWT access token from SMS Gateway
        token = get_sms_access_token(config["username"], config["password"], config["endpoint"])

        try:
            request_kwargs = self._build_request(config, normalized, message, token=token)
            resp = requests.post(timeout=SMS_TIMEOUT, **request_kwargs)

            # If token expired on gateway (401), force-refresh and retry once
            if resp.status_code in (401, 403) and token:
                token = get_sms_access_token(config["username"], config["password"], config["endpoint"], force_refresh=True)
                if token:
                    request_kwargs = self._build_request(config, normalized, message, token=token)
                    resp = requests.post(timeout=SMS_TIMEOUT, **request_kwargs)

        except requests.exceptions.Timeout:
            detail = _("SMS gateway timed out.")
            _logger.error("SMS failed: %s", detail)
            return {"success": False, "detail": detail, "mobile": normalized}
        except requests.exceptions.ConnectionError:
            detail = _("Cannot connect to the SMS gateway.")
            _logger.error("SMS failed: %s", detail)
            return {"success": False, "detail": detail, "mobile": normalized}
        except Exception as exc:  # never leak exception text: it may embed the URL/auth
            detail = _("Unexpected error while calling the SMS gateway (%s).") % exc.__class__.__name__
            _logger.error("SMS failed: %s", detail)
            return {"success": False, "detail": detail, "mobile": normalized}

        ok, detail = self._parse_response(resp)
        if ok:
            _logger.info("SMS successfully sent to %s.", masked)
        else:
            _logger.error("SMS failed for %s: %s", masked, detail)
        return {"success": ok, "detail": detail, "mobile": normalized}

    @api.model
    def send_email(self, to_email, subject, body, recipient_name=None, environment=None):
        """Send one Email through the Bunna Bank In-House Notification API Gateway.

        POST <endpoint>/api/email/send
        Authorization: Bearer <token>
        Content-Type: application/json
        {"to": "<email>", "recipientName": "<name>", "subject": "<subject>", "body": "<body>"}
        """
        if not to_email:
            return {"success": False, "detail": _("Missing or invalid recipient email address.")}
        if not subject or not body:
            return {"success": False, "detail": _("Email subject or body cannot be empty.")}

        config = self.env["cbs.integration.config"].sudo().get_config(environment)
        error = self._validate_config(config)
        if error:
            _logger.warning("Email configuration problem: %s", error)
            return {"success": False, "detail": error}

        email_endpoint = (
            self.env["ir.config_parameter"].sudo().get_param("bunna_helpdesk.email_endpoint") or ""
        ).strip()

        clean_base = (email_endpoint or config["endpoint"]).rstrip("/")
        if clean_base.endswith("/sms"):
            send_url = f"{clean_base}/api/email/send"
        elif "/api/email/send" in clean_base:
            send_url = clean_base
        else:
            send_url = f"{clean_base}/sms/api/email/send"

        token = get_sms_access_token(config["username"], config["password"], config["endpoint"])
        if not token:
            return {"success": False, "detail": _("Failed to authenticate with Notification Email Gateway.")}

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "BunnaHelpdesk-EmailConnector/1.0",
        }
        payload = {
            "to": str(to_email).strip(),
            "recipientName": str(recipient_name or "Customer").strip(),
            "subject": str(subject).strip(),
            "body": str(body).strip(),
        }

        try:
            resp = requests.post(send_url, json=payload, headers=headers, timeout=(5.0, 30.0))
            if resp.status_code in (401, 403):
                token = get_sms_access_token(config["username"], config["password"], config["endpoint"], force_refresh=True)
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                    resp = requests.post(send_url, json=payload, headers=headers, timeout=(5.0, 30.0))
        except requests.exceptions.Timeout:
            detail = _("Notification Email Gateway timed out.")
            _logger.error("Email API failed: %s", detail)
            return {"success": False, "detail": detail}
        except requests.exceptions.ConnectionError:
            detail = _("Cannot connect to the Notification Email Gateway.")
            _logger.error("Email API failed: %s", detail)
            return {"success": False, "detail": detail}
        except Exception as exc:
            detail = _("Unexpected error while calling Email Gateway (%s).") % exc.__class__.__name__
            _logger.error("Email API failed: %s", detail)
            return {"success": False, "detail": detail}

        if 200 <= resp.status_code < 300:
            _logger.info("Email successfully dispatched via Notification Gateway to %s.", to_email)
            return {"success": True, "detail": _("Email sent to %s.") % to_email}

        return {"success": False, "detail": _("Email Gateway returned HTTP %s.") % resp.status_code}

