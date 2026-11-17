# -*- coding: utf-8 -*-
import datetime
import logging
import re
import time
import requests
from odoo import _

_logger = logging.getLogger(__name__)

# In-memory JWT token cache: {"token": str, "expires_at": float}
_TOKEN_CACHE = {
    "token": None,
    "expires_at": 0,
}


def get_cbs_credentials(env):
    """Retrieve CBS API credentials from cbs_integration table or system parameters."""
    config = {
        "username": "",
        "password": "",
        "endpoint": "http://10.1.11.242:7001",
        "environment": "CBS",
        "status": "true",
    }
    try:
        env.cr.execute(
            """
            SELECT username, cbs_decode(password), endpoint, environment, status
            FROM cbs_integration
            WHERE (status IS NULL OR status = 'true' OR status = 'active')
              AND UPPER(TRIM(environment)) IN ('CBS', 'UAT')
            LIMIT 1
            """
        )
        row = env.cr.fetchone()
        if row:
            config["username"] = str(row[0] or "").strip()
            config["password"] = str(row[1] or "").strip()
            raw_endpoint = str(row[2] or "").strip()
            if raw_endpoint:
                config["endpoint"] = raw_endpoint.rstrip("/")
            config["environment"] = str(row[3] or "CBS").strip()
            config["status"] = str(row[4] or "true").strip()
    except Exception as e:
        _logger.warning("Querying cbs_integration with cbs_decode failed, falling back: %s", e)
        try:
            env.cr.execute(
                """
                SELECT username, password, endpoint, environment, status
                FROM cbs_integration
                WHERE (status IS NULL OR status = 'true' OR status = 'active')
                  AND UPPER(TRIM(environment)) IN ('CBS', 'UAT')
                LIMIT 1
                """
            )
            row = env.cr.fetchone()
            if row:
                config["username"] = str(row[0] or "").strip()
                config["password"] = str(row[1] or "").strip()
                raw_endpoint = str(row[2] or "").strip()
                if raw_endpoint:
                    config["endpoint"] = raw_endpoint.rstrip("/")
                config["environment"] = str(row[3] or "CBS").strip()
                config["status"] = str(row[4] or "true").strip()
        except Exception as exc:
            _logger.warning("Could not query cbs_integration table: %s", exc)

    # Fallback to system parameters (configured in Settings)
    params = env["ir.config_parameter"].sudo()
    if not config["username"]:
        config["username"] = params.get_param("bunna_helpdesk.cbs_username", "erp1.bunna").strip()
    if not config["password"]:
        config["password"] = params.get_param("bunna_helpdesk.cbs_password", "Bib@ERp@admi").strip()
    if not config["endpoint"]:
        config["endpoint"] = params.get_param("bunna_helpdesk.cbs_endpoint", "http://10.1.11.242:7001").strip().rstrip("/")

    return config


def get_cbs_access_token(env, username, password, base_url, force_refresh=False):
    """Authenticate against Bunna Bank CBS Gateway and obtain JWT Bearer token."""
    global _TOKEN_CACHE
    now = time.time()

    if not force_refresh and _TOKEN_CACHE.get("token") and _TOKEN_CACHE.get("expires_at", 0) > (now + 60):
        return _TOKEN_CACHE["token"]

    if not username or not password:
        _logger.warning("CBS username or password missing for authentication.")
        return None

    login_url = f"{base_url}/api/auth/login"
    try:
        resp = requests.post(
            login_url,
            params={"username": username, "password": password},
            headers={"Accept": "application/json", "User-Agent": "BunnaWeb-FinacleConnector/1.0"},
            timeout=(3.0, 5.0),
        )
        if resp.status_code == 200:
            data = resp.json()
            token = data.get("accessToken") or data.get("token") or data.get("jwt")
            if token:
                _TOKEN_CACHE["token"] = token
                _TOKEN_CACHE["expires_at"] = now + 3000
                _logger.info("Successfully authenticated with Bunna Bank CBS Gateway.")
                return token
        _logger.error("CBS Authentication failed at %s with status %s: %s", login_url, resp.status_code, resp.text[:200])
    except Exception as exc:
        _logger.error("Error during CBS authentication login: %s", str(exc))

    return None


def parse_cbs_response_customer(raw_data, query_identifier=None):
    """Map raw Finacle CBS customer details response into standardized dictionary."""
    if not raw_data:
        return None

    if isinstance(raw_data, list):
        data = raw_data[0] if raw_data else {}
    elif isinstance(raw_data, dict):
        data = (
            raw_data.get("data")
            or raw_data.get("DATA")
            or raw_data.get("customer")
            or raw_data.get("CUSTOMER")
            or raw_data
        )
        if isinstance(data, list):
            data = data[0] if data else {}
    else:
        return None

    if not isinstance(data, dict):
        return None

    def get_val(keys, default=None):
        for k in keys:
            if k in data and data[k] is not None:
                return data[k]
            k_lower = k.lower()
            if k_lower in data and data[k_lower] is not None:
                return data[k_lower]
        return default

    account_no = get_val(["ACCOUNT_NUMBER", "account_number", "accountNumber", "accountNo", "foracid", "acctNo"])
    if not account_no and query_identifier:
        account_no = query_identifier

    name = get_val(["NAME", "name", "customer_name", "customerName", "custName", "account_name"])
    cif = get_val(["CIF_NUMBER", "cif_number", "cif", "cifNumber", "cifId"])
    fayda = get_val(["FAYDA_NUMBER", "fayda_number", "faydaNumber", "nationalId", "national_id"])
    phone = get_val(["PHONE", "phone", "phoneNumber", "mobile", "mobileNumber"])
    branch_name = get_val(["BRANCH_NAME", "branch_name", "branchName", "branch", "solDesc"], "BIB Main Branch")
    sol_id = get_val(["SOL_ID", "sol_id", "solId"], "")
    account_type = get_val(["ACCOUNT_TYPE", "account_type", "accountType", "schmType", "schmCode"], "Saving Account")

    raw_status = str(get_val(["ACCOUNT_STATUS", "account_status", "status"], "A")).strip().upper()
    if raw_status in ("A", "ACTIVE", "OPEN", "O"):
        account_status = "Active"
    elif raw_status in ("D", "DORMANT"):
        account_status = "Dormant"
    elif raw_status in ("I", "INACTIVE", "F", "FROZEN", "BLOCKED", "T", "TOTAL_FREEZE"):
        account_status = "Frozen"
    elif raw_status in ("C", "CLOSED"):
        account_status = "Closed"
    else:
        account_status = "Active"

    return {
        "account_number": str(account_no).strip() if account_no else "",
        "name": str(name).strip() if name else "",
        "cif_number": str(cif).strip() if cif else "",
        "fayda_number": str(fayda).strip() if fayda else "",
        "phone": str(phone).strip() if phone else "",
        "branch_name": str(branch_name).strip() if branch_name else "BIB Main Branch",
        "sol_id": str(sol_id).strip() if sol_id else "",
        "account_type": str(account_type).strip() if account_type else "Saving Account",
        "account_status": account_status,
        "district_name": str(get_val(["DISTRICT_NAME", "district_name"], "")).strip(),
        "customer_segment": str(get_val(["CUSTOMER_SEGMENT", "customer_segment"], "Retail")).strip(),
        "account_ownership": str(get_val(["ACCOUNT_OWNERSHIP", "account_ownership"], "")).strip(),
    }


def query_cbs_api(env, account_number):
    """
    Query real Core Banking System (Finacle) HTTP API for customer details by account number.
    Endpoint: http://10.1.11.242:7001/api/cbs/customer-details/{foracid}
    Returns:
        tuple: (success: bool, customer_dict: dict or None, user_message: str)
    """
    if not account_number:
        return False, None, _("Please provide a valid Bunna Bank account number.")

    q = str(account_number).strip()

    cbs_config = get_cbs_credentials(env)
    endpoint = cbs_config.get("endpoint") or "http://10.1.11.242:7001"
    username = cbs_config.get("username") or "erp1.bunna"
    password = cbs_config.get("password") or "Bib@ERp@admi"

    base_url = endpoint
    for suffix in ("/api/cbs/customer-details", "/customer", "/api"):
        if base_url.endswith(suffix):
            base_url = base_url[:-len(suffix)]
            break
    base_url = base_url.rstrip("/")

    token = get_cbs_access_token(env, username, password, base_url)
    if not token:
        _logger.warning("CBS authentication login failed for user '%s' at '%s'", username, base_url)
        return False, None, _("Authentication failed while connecting to Core Banking System. Please verify credentials or network connection.")

    def do_request(jwt_token=None):
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "BunnaWeb-FinacleConnector/1.0",
        }
        if jwt_token:
            headers["Authorization"] = f"Bearer {jwt_token}"

        # Endpoint: http://10.1.11.242:7001/api/cbs/customer-details/{foracid}
        req_url = f"{base_url}/api/cbs/customer-details/{q}"
        resp = requests.get(req_url, headers=headers, timeout=(3.0, 5.0))
        return resp

    raw_response = None
    try:
        resp = do_request(token)
        if resp.status_code == 401 and token:
            _logger.info("CBS returned 401; refreshing token...")
            new_token = get_cbs_access_token(env, username, password, base_url, force_refresh=True)
            if new_token:
                resp = do_request(new_token)

        if resp.status_code == 200:
            raw_response = resp.json()
        elif resp.status_code == 404:
            return False, None, _("Account number %s was not found in Bunna Core Banking System.") % q
        elif resp.status_code in (401, 403):
            return False, None, _("Authentication failed while connecting to Core Banking System.")
        else:
            return False, None, _("Core Banking System returned HTTP status %s") % resp.status_code

    except requests.exceptions.Timeout:
        _logger.warning("CBS API connection timed out to endpoint %s", base_url)
        return False, None, _("Core Banking System (CBS) service timed out. Please ensure you are connected to the Bunna Bank network/VPN.")
    except requests.exceptions.ConnectionError:
        _logger.warning("CBS API connection failed to endpoint %s", base_url)
        return False, None, _("Cannot connect to Core Banking System. Please ensure you are connected to the Bunna Bank network/VPN.")
    except Exception as exc:
        _logger.error("Unexpected error querying CBS API: %s", str(exc))
        return False, None, _("Error communicating with Core Banking System: %s") % str(exc)

    if raw_response:
        parsed = parse_cbs_response_customer(raw_response, q)
        if parsed and (parsed.get("name") or parsed.get("account_number")):
            return True, parsed, _("Customer account details successfully retrieved from Finacle CBS.")
        return False, None, _("Account %s not found in Finacle Core Banking.") % q

    return False, None, _("Account %s could not be found.") % q
