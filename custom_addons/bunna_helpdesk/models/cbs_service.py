# -*- coding: utf-8 -*-
import datetime
import logging
import re
import time
import requests
from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# In-memory JWT token cache: {"token": str, "expires_at": float}
_TOKEN_CACHE = {
    "token": None,
    "expires_at": 0,
}


def get_cbs_credentials(env):
    """Retrieve CBS API credentials securely from the cbs_integration table or system parameters.
    No credentials or network endpoints are hardcoded.
    """
    config = {
        "username": "",
        "password": "",
        "endpoint": "",
        "environment": "UAT",
        "status": "true",
    }
    try:
        env.cr.execute(
            """
            SELECT username, password, endpoint, environment, status
            FROM cbs_integration
            WHERE status = 'true'
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
            config["environment"] = str(row[3] or "UAT").strip()
            config["status"] = str(row[4] or "true").strip()
    except Exception as e:
        _logger.warning("Could not query cbs_integration table: %s", e)

    # Fallback to system parameters (configured by Administrator in Settings)
    params = env["ir.config_parameter"].sudo()
    if not config["username"]:
        config["username"] = params.get_param("bunna_helpdesk.cbs_username", "").strip()
    if not config["password"]:
        config["password"] = params.get_param("bunna_helpdesk.cbs_password", "").strip()
    if not config["endpoint"]:
        config["endpoint"] = params.get_param("bunna_helpdesk.cbs_endpoint", "").strip().rstrip("/")

    return config


def get_cbs_access_token(env, username, password, base_url, force_refresh=False):
    """
    Authenticate against Bunna Bank Inhouse API / LDAP gateway and obtain JWT Bearer token.
    Reuses cached token if valid.
    """
    global _TOKEN_CACHE
    now = time.time()

    # Reuse cached token if valid for at least 60 more seconds
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
            headers={"Accept": "application/json", "User-Agent": "BunnaHelpdesk-FinacleConnector/1.0"},
            timeout=(3.0, 5.0),
        )
        if resp.status_code == 200:
            data = resp.json()
            token = data.get("accessToken") or data.get("token") or data.get("jwt")
            if token:
                # Default JWT validity is typically 1-2 hours; cache for 50 minutes (3000 seconds)
                _TOKEN_CACHE["token"] = token
                _TOKEN_CACHE["expires_at"] = now + 3000
                _logger.info("Successfully authenticated with Bunna Bank CBS Gateway and retrieved JWT token.")
                return token
        _logger.error("CBS Authentication failed at %s with status %s: %s", login_url, resp.status_code, resp.text[:200])
    except Exception as exc:
        _logger.error("Error during CBS authentication login: %s", str(exc))

    return None


def parse_cbs_response_customer(raw_data, query_identifier=None, id_type="account"):
    """
    Normalize and map raw CBS / Finacle response data into standardized dictionary.
    Handles exact Finacle production response format:
    {
      "ACCOUNT_NUMBER": "1019501012030",
      "CIF_NUMBER": "100271122",
      "FAYDA_NUMBER": "6/440/3/1",
      "PHONE": "0912211913",
      "NAME": "YONAS GOSA DIBARGACHEW",
      "EMAIL": null,
      "ACCOUNT_TYPE": "Saving Account",
      "ACCOUNT_STATUS": "I",
      "CUSTOMER_SEGMENT": "Retail",
      "PREFERRED_LANGUAGE": "AMH",
      "SOL_ID": "101",
      "BRANCH_NAME": "BIB MAIN BRANCH",
      "DISTRICT_NAME": "South Addis Ababa",
      "ACCT_OPN_DATE": "2017-07-20T00:00:00",
      "MODE_OF_OPER_CODE": "SINGL",
      "AGE": 56
    }
    """
    if not raw_data:
        return None

    # Handle wrapped structures (e.g. {"data": {...}}, {"customer": {...}}, or list of records)
    if isinstance(raw_data, list):
        data = raw_data[0] if raw_data else {}
    elif isinstance(raw_data, dict):
        data = (
            raw_data.get("data")
            or raw_data.get("DATA")
            or raw_data.get("customer")
            or raw_data.get("CUSTOMER")
            or raw_data.get("customerProfile")
            or raw_data.get("CustomerProfile")
            or raw_data
        )
        if isinstance(data, list):
            data = data[0] if data else {}
    else:
        return None

    if not isinstance(data, dict):
        return None

    # Helper for case-insensitive dictionary key access
    def get_val(keys, default=None):
        for k in keys:
            if k in data and data[k] is not None:
                return data[k]
            k_lower = k.lower()
            if k_lower in data and data[k_lower] is not None:
                return data[k_lower]
            k_upper = k.upper()
            if k_upper in data and data[k_upper] is not None:
                return data[k_upper]
        return default

    # 1. Customer Name
    name = get_val(["NAME", "name", "customerName", "customer_name", "fullName", "custName"])
    if not name and query_identifier:
        name = f"Bunna Customer ({query_identifier})"

    # 2. Account Number
    account_no = get_val(["ACCOUNT_NUMBER", "account_number", "accountNumber", "accountNo", "foracid", "acctNo"])
    if not account_no and id_type == "account" and query_identifier:
        account_no = query_identifier

    # 3. CIF Number
    cif = get_val(["CIF_NUMBER", "cif_number", "cif", "cifNumber", "cifId", "cust_id", "custId"])
    if not cif and id_type == "cif" and query_identifier:
        cif = query_identifier

    # 4. Fayda / National ID Number
    fayda = get_val(["FAYDA_NUMBER", "fayda_number", "faydaNumber", "nationalId", "national_id", "fan"])
    if not fayda and id_type == "fayda" and query_identifier:
        fayda = query_identifier

    # 5. Phone / Mobile
    phone = get_val(["PHONE", "phone", "phoneNumber", "mobile", "mobileNumber", "partner_phone"])
    if not phone and id_type == "phone" and query_identifier:
        phone = query_identifier

    # 6. Email
    email = get_val(["EMAIL", "email", "emailAddress", "email_address"])
    email_str = str(email).strip() if email else False

    # 7. Age (Direct integer or computed from DOB)
    raw_age = get_val(["AGE", "age", "customerAge", "customer_age"])
    age = 0
    if raw_age is not None:
        try:
            age = int(raw_age)
        except (ValueError, TypeError):
            age = 0

    if not age:
        dob_str = get_val(["DOB", "dob", "dateOfBirth", "birthDate", "BIRTH_DATE"])
        if dob_str:
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y"):
                try:
                    dob = datetime.datetime.strptime(str(dob_str)[:19], fmt).date()
                    today = datetime.date.today()
                    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                    break
                except ValueError:
                    continue

    # 8. District Name
    district_name = get_val(["DISTRICT_NAME", "district_name", "districtName", "district", "zone"], "")

    # 9. Branch Name & SOL ID
    branch_name = get_val(["BRANCH_NAME", "branch_name", "branchName", "branch", "solDesc"], "")
    sol_id = get_val(["SOL_ID", "sol_id", "solId"], "")

    # 10. Account Type / Product
    account_type = get_val(["ACCOUNT_TYPE", "account_type", "accountType", "schmType", "schmCode"], "Saving Account")

    # 11. Account Status
    # Standard Finacle status codes:
    # A = Active / Open, I = Inactive / Frozen, D = Dormant, F = Frozen, C = Closed, T = Total Freeze
    raw_status = str(get_val(["ACCOUNT_STATUS", "account_status", "accountStatus", "status"], "A")).strip().upper()
    if raw_status in ("A", "ACTIVE", "OPEN", "O"):
        account_status = "active"
    elif raw_status in ("D", "DORMANT"):
        account_status = "dormant"
    elif raw_status in ("I", "INACTIVE", "F", "FROZEN", "BLOCKED", "T", "TOTAL_FREEZE"):
        account_status = "frozen"
    elif raw_status in ("C", "CLOSED"):
        account_status = "closed"
    else:
        account_status = "active"

    # 12. Customer Segment
    raw_segment = str(get_val(["CUSTOMER_SEGMENT", "customer_segment", "customerSegment", "segment"], "Retail")).strip().lower()
    if "sme" in raw_segment or "commercial" in raw_segment:
        customer_segment = "sme"
    elif "corp" in raw_segment:
        customer_segment = "corporate"
    elif "vip" in raw_segment or "hnw" in raw_segment or "diaspora" in raw_segment:
        customer_segment = "vip"
    elif "youth" in raw_segment or "student" in raw_segment:
        customer_segment = "youth"
    elif "staff" in raw_segment or "employee" in raw_segment:
        customer_segment = "staff"
    else:
        customer_segment = "retail"

    # 13. Preferred Language
    # AMH = Amharic, ENG = English, ORO/ORM = Afan Oromo, TIG = Tigrigna, SOM = Somali
    raw_lang = str(get_val(["PREFERRED_LANGUAGE", "preferred_language", "preferredLanguage", "language"], "AMH")).strip().upper()
    if "ENG" in raw_lang:
        preferred_language = "english"
    elif "ORO" in raw_lang or "ORM" in raw_lang or "AFAN" in raw_lang:
        preferred_language = "afan_oromo"
    elif "TIG" in raw_lang:
        preferred_language = "tigrigna"
    elif "SOM" in raw_lang:
        preferred_language = "somali"
    else:
        preferred_language = "amharic"

    # 14. Customer Type Description
    customer_type = str(get_val(["CUSTOMER_SEGMENT", "customer_segment", "customerType", "custType", "CUSTOMER_TYPE"], "Retail")).strip()

    return {
        "name": str(name).strip() if name else False,
        "account_number": str(account_no).strip() if account_no else False,
        "cif_number": str(cif).strip() if cif else False,
        "fayda_number": str(fayda).strip() if fayda else False,
        "phone": str(phone).strip() if phone else False,
        "email": email_str or False,
        "age": age,
        "district_name": str(district_name).strip(),
        "branch_name": str(branch_name).strip(),
        "sol_id": str(sol_id).strip() if sol_id else False,
        "customer_type": customer_type,
        "account_type": str(account_type).strip(),
        "account_status": account_status,
        "customer_segment": customer_segment,
        "preferred_language": preferred_language,
        "acct_opn_date": get_val(["ACCT_OPN_DATE", "acct_opn_date", "acctOpnDate"]),
        "mode_of_oper_code": get_val(["MODE_OF_OPER_CODE", "mode_of_oper_code", "modeOfOperCode"]),
    }


def query_cbs_api(env, identifier, id_type="account"):
    """
    Query the real Core Banking System (Finacle) HTTP API.
    Authenticates dynamically with JWT Bearer token and fetches live customer details.
    Returns:
        tuple: (success: bool, customer_dict: dict or None, user_message: str)
    """
    if not identifier:
        return False, None, _("Please provide a customer identifier (Account, CIF, Fayda, or Phone).")

    q = str(identifier).strip()

    # Retrieve real credentials from cbs_integration table or configuration
    cbs_config = get_cbs_credentials(env)
    endpoint = cbs_config.get("endpoint")
    username = cbs_config.get("username")
    password = cbs_config.get("password")

    if not endpoint:
        return False, None, _("Core Banking System (CBS) endpoint is not configured. Please configure CBS in Settings.")

    # Determine base host URL (e.g. http://10.1.11.242:7001)
    base_url = endpoint
    for suffix in ("/api/cbs/customer-details", "/customer", "/api"):
        if base_url.endswith(suffix):
            base_url = base_url[:-len(suffix)]
            break
    base_url = base_url.rstrip("/")

    # Step 1: Obtain JWT Token (with cached token support)
    token = get_cbs_access_token(env, username, password, base_url)
    if not token:
        # Fallback: try basic auth directly if token login is not supported
        _logger.info("No JWT token obtained, attempting direct request.")

    def do_request(jwt_token=None):
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "BunnaHelpdesk-FinacleConnector/1.0",
        }
        if jwt_token:
            headers["Authorization"] = f"Bearer {jwt_token}"

        auth = (username, password) if (username and password and not jwt_token) else None

        # Build URL for primary customer details endpoint: /api/cbs/customer-details/{foracid}
        req_url = f"{base_url}/api/cbs/customer-details/{q}"

        # If query identifier contains digits (Account or CIF)
        resp = requests.get(req_url, headers=headers, auth=auth, timeout=(3.0, 5.0))
        if resp.status_code == 404 or resp.status_code == 400:
            # Fallback to query parameter endpoint: /api/cbs/customer-details or /customer
            fallback_url = f"{base_url}/customer"
            resp = requests.get(
                fallback_url,
                params={"accountNumber": q, "cif": q, "phone": q, "faydaNumber": q},
                headers=headers,
                auth=auth,
                timeout=(3.0, 5.0),
            )
        return resp

    raw_response = None
    try:
        resp = do_request(token)
        if resp.status_code == 401 and token:
            # Token might have expired on server; force refresh and retry once
            _logger.info("CBS returned 401 with existing token; refreshing token...")
            new_token = get_cbs_access_token(env, username, password, base_url, force_refresh=True)
            if new_token:
                resp = do_request(new_token)

        if resp.status_code == 200:
            raw_response = resp.json()
        elif resp.status_code == 401 or resp.status_code == 403:
            _logger.error("CBS Authentication failed for endpoint %s", base_url)
            return False, None, _("Authentication failed while connecting to Core Banking System. Please verify credentials.")
        elif resp.status_code == 404:
            return False, None, _("Customer %s not found in Finacle Core Banking.") % q
        else:
            return False, None, _("CBS returned HTTP %s") % resp.status_code

    except requests.exceptions.Timeout:
        _logger.warning("CBS API connection timed out to endpoint %s", base_url)
        return False, None, _("Core Banking System (CBS) service timed out (connection exceeded timeout threshold).")
    except requests.exceptions.ConnectionError:
        _logger.warning("CBS API connection failed to endpoint %s", base_url)
        return False, None, _("Cannot connect to Core Banking System. Please verify network or VPN connection.")
    except Exception as exc:
        _logger.error("Unexpected error querying CBS API: %s", str(exc))
        return False, None, _("Error communicating with Core Banking System: %s") % str(exc)

    if raw_response:
        parsed = parse_cbs_response_customer(raw_response, q, id_type)
        if parsed and (parsed.get("name") or parsed.get("account_number") or parsed.get("cif_number")):
            return True, parsed, _("Customer profile successfully retrieved from Finacle CBS.")
        return False, None, _("Customer %s not found in Finacle Core Banking.") % q

    return False, None, _("Customer %s could not be found in Core Banking System.") % q
