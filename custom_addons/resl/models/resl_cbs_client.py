import re
import logging

import requests
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Date format sent to the CBS API for expDt / expiryDt.  Change here if the
# Finacle wrapper expects something else (e.g. '%d-%m-%Y').
CBS_DATE_FORMAT = '%Y-%m-%d'
CBS_TIMEOUT = 30
# Zero-pad branchId (operating_unit.sol_id) to this width; 0 = send as stored.
# Set to 3 if Finacle expects e.g. '001' / '952'.
CBS_BRANCH_ID_WIDTH = 0

# Values of cbs_integration.status that mean "usable".  If none of the rows
# match, the first row is used.
_ACTIVE_STATUSES = ('active', 'enabled', 'enable', 'connected', 'live', 'true', '1', 'yes', 'on')


class ReslCbsClient(models.AbstractModel):
    """Thin client for the Core Banking (Finacle) REST wrapper.

    Connection details (endpoint, username, password) are read from the
    ``cbs_integration`` table on every call, so changing them in the DB takes
    effect immediately and nothing is hard-coded.

        1. POST {endpoint}/api/auth/login?username=..&password=..   (AD login)
        2. POST {endpoint}/api/cbs/open-account                     (no OD account yet)
        3. POST {endpoint}/api/cbs/extend-od-limit                  (new AND existing account)
    """
    _name = 'resl.cbs.client'
    _description = 'RESL Core Banking API Client'

    # ── Configuration ─────────────────────────────────────────────────────

    @api.model
    def _get_config(self):
        # Raw SQL on purpose: works whether or not cbs_integration is an Odoo
        # model, and bypasses ACLs (the accountant cannot read it directly).
        self.env.cr.execute(
            "SELECT username, password, endpoint, environment, status FROM cbs_integration"
        )
        rows = self.env.cr.dictfetchall()
        if not rows:
            raise UserError(_("Core Banking integration is not configured (cbs_integration is empty)."))
        row = next(
            (r for r in rows if str(r.get('status') or '').strip().lower() in _ACTIVE_STATUSES),
            rows[0],
        )
        endpoint = (row.get('endpoint') or '').strip().rstrip('/')
        if not endpoint or not row.get('username') or not row.get('password'):
            raise UserError(_("Core Banking integration is incomplete: endpoint, username and password are required."))
        return {
            'endpoint': endpoint,
            'username': row['username'].strip(),
            'password': row['password'],
            'environment': row.get('environment'),
        }

    # ── HTTP helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _redact(text, cfg):
        """Never let the password leak into logs / error popups."""
        text = str(text or '')
        if cfg.get('password'):
            text = text.replace(cfg['password'], '***')
        return text

    def _request(self, http, cfg, path, allow_error=False, **kwargs):
        url = cfg['endpoint'] + path
        try:
            resp = http.post(url, timeout=CBS_TIMEOUT, **kwargs)
        except requests.RequestException as e:
            _logger.error("CBS call %s failed: %s", path, self._redact(e, cfg))
            raise UserError(_("Could not reach the Core Banking service (%s). Please try again or contact IT.") % path)
        if not resp.ok and allow_error:
            return resp          # caller inspects the error body itself
        if not resp.ok:
            body = self._redact(resp.text, cfg)[:500]
            _logger.error("CBS call %s returned HTTP %s: %s", path, resp.status_code, body)
            raise UserError(_("Core Banking rejected the request (%(path)s, HTTP %(code)s): %(body)s") % {
                'path': path, 'code': resp.status_code, 'body': body or _('no details'),
            })
        return resp

    @staticmethod
    def _json_or_none(resp):
        try:
            return resp.json()
        except ValueError:
            return None

    @classmethod
    def _find_key(cls, data, keys):
        """Depth-first search for the first non-empty value under any of `keys`."""
        if isinstance(data, dict):
            for k in keys:
                if data.get(k):
                    return data[k]
            for v in data.values():
                found = cls._find_key(v, keys)
                if found:
                    return found
        elif isinstance(data, list):
            for v in data:
                found = cls._find_key(v, keys)
                if found:
                    return found
        return None

    # ── 1. Authentication ─────────────────────────────────────────────────

    def _login(self, cfg):
        """Authenticate against AD through the API; returns a requests.Session
        already carrying the bearer token (and any session cookie)."""
        http = requests.Session()
        resp = self._request(
            http, cfg, '/api/auth/login',
            params={'username': cfg['username'], 'password': cfg['password']},
        )
        data = self._json_or_none(resp)
        token = None
        if data is not None:
            token = self._find_key(data, ('token', 'access_token', 'accessToken', 'jwt', 'bearer', 'id_token'))
        elif resp.text and re.fullmatch(r'[\w\-\.=]{20,}', resp.text.strip()):
            token = resp.text.strip()      # plain-text JWT
        if token:
            http.headers['Authorization'] = 'Bearer %s' % token
        elif not http.cookies:
            _logger.warning("CBS login returned neither a token nor a cookie; continuing unauthenticated.")
        return http

    # ── 2. Open OD account ────────────────────────────────────────────────

    @api.model
    def _get_source_account(self, loan):
        """hr_version.salary_account of the requester; the API resolves the
        CIF id from it ('foracid').

        Current version first, then the latest version of that employee that
        has a value (same pattern as od_account in the disbursement wizard).
        """
        emp = loan.employee_id.sudo()
        version = loan._get_latest_contract(emp, sudo=True)
        if version and 'salary_account' in version._fields and version.salary_account:
            return str(version.salary_account).strip() or False

        Version = self.env['hr.version'].sudo()
        if 'salary_account' in Version._fields and 'employee_id' in Version._fields:
            order = 'date_version desc, id desc' if 'date_version' in Version._fields else 'id desc'
            found = Version.search(
                [('employee_id', '=', emp.id), ('salary_account', '!=', False)],
                order=order, limit=1,
            )
            if found:
                return str(found.salary_account).strip() or False
        return False

    @api.model
    def _expiry_date(self, loan):
        months = int(loan.loan_term_months or 0) or 12
        return (fields.Date.context_today(self) + relativedelta(months=months)).strftime(CBS_DATE_FORMAT)

    def open_account(self, loan):
        """Open a new ODA account for the loan's borrower.

        The request carries `amount` = the new sanction limit (wage x 3 or 6), so
        a newly created account already has its limit.

        Returns (account_number, created). created is False when Finacle says the
        customer already has an active account, in which case that existing
        account is returned so it can be linked (its limit is NOT set by this
        call, so extend-od-limit is still needed)."""
        cfg = self._get_config()
        source_account = self._get_source_account(loan)
        if not source_account:
            raise UserError(_(
                "%s has no salary account on their HR version, so a new account "
                "cannot be opened (the CIF is resolved from it)."
            ) % loan.employee_id.name)
        ou = self.env['resl.validations'].get_employee_operating_unit(loan.employee_id)
        if not ou:
            raise UserError(_(
                "%s has no operating unit set (neither on the employee nor on any HR version)."
            ) % loan.employee_id.name)
        # Branch ID = the operating unit's SOL id (operating_unit.sol_id).
        # NB: operating_unit.code is an unrelated FK to hr_report_code.
        branch_id = str(ou.sol_id).strip() if 'sol_id' in ou._fields and ou.sol_id else ''
        if not branch_id:
            raise UserError(_(
                "Operating unit '%s' has no SOL ID, so branchId cannot be sent. "
                "Set its SOL ID under Operating Units."
            ) % ou.name)
        if CBS_BRANCH_ID_WIDTH:
            branch_id = branch_id.zfill(CBS_BRANCH_ID_WIDTH)

        # The sanction limit is set by the opening call itself (new field `amount`),
        # so a brand-new account needs no separate extend-od-limit call.
        amount, wage, term = self._new_sanction_limit(loan)

        http = self._login(cfg)
        resp = self._request(http, cfg, '/api/cbs/open-account', allow_error=True, json={
            'accountNumber': source_account,
            'branchId': branch_id,
            'amount': amount,
            'expDt': self._expiry_date(loan),
        })
        data = self._json_or_none(resp)

        if not resp.ok:
            # Finacle: "Customer already has an active RESL1 account (...)".
            # The account already exists for this CIF, so link it instead of failing.
            existing = data.get('activeAccount') if isinstance(data, dict) else None
            message = str(data.get('message') or '') if isinstance(data, dict) else ''
            if existing and re.fullmatch(r'\d{13}', str(existing).strip()) \
                    and 'already has an active' in message.lower():
                _logger.info("CBS open-account: customer already has active account %s; linking it.", existing)
                return str(existing).strip(), False
            body = self._redact(resp.text, cfg)[:500]
            _logger.error("CBS call /api/cbs/open-account returned HTTP %s: %s", resp.status_code, body)
            raise UserError(_("Core Banking rejected the request (/api/cbs/open-account, HTTP %(code)s): %(body)s") % {
                'code': resp.status_code, 'body': body or _('no details'),
            })

        number = None
        if data is not None:
            number = self._find_key(data, ('accountNumber', 'accountNo', 'acctNum', 'foracid', 'account', 'data', 'result'))
        if not number or isinstance(number, (dict, list)):
            number = resp.text
        match = re.search(r'\d{13}', str(number or ''))
        if not match:
            _logger.error("CBS open-account: no 13-digit account in response: %s", self._redact(resp.text, cfg)[:300])
            raise UserError(_("Core Banking did not return a valid account number."))
        return match.group(0), True

    # ── 3. Extend / set OD sanction limit ─────────────────────────────────

    @api.model
    def _new_sanction_limit(self, loan):
        """New Sanction Limit = current basic wage x the RSSA multiplier (3 or 6).

        Always the full multiple, for every request, new or existing account.
        The multiplier is the loan's term, set by the service validation
        (3-5 months of service -> x3, 6+ months -> x6), i.e. the same value as
        the loan's 'Eligible Ceiling' (eligible_amount). Computed server-side
        at call time so a salary increment is picked up automatically.

        The amount already taken (total_loans_taken) is NOT added here; it is
        tracked on the loan and only limits how much can still be requested.
        """
        emp = loan.employee_id.sudo()
        wage = loan._employee_current_wage(emp)
        term = int(loan.loan_term_months or 0) or loan._max_eligible_loan_term(emp)
        if not wage or wage <= 0:
            raise UserError(_("%s has no basic salary on record; cannot compute the new sanction limit.") % emp.name)
        if term not in (3, 6):
            raise UserError(_("%(name)s is not eligible for a sanction limit (service-based multiplier is %(term)s).")
                            % {'name': emp.name, 'term': term})
        return float(wage) * term, wage, term

    def extend_od_limit(self, loan, account_number):
        """Set the OD sanction limit of `account_number` to wage x (3 or 6).
        Returns (amount, wage, multiplier) that was sent to CBS."""
        amount, wage, term = self._new_sanction_limit(loan)
        cfg = self._get_config()
        http = self._login(cfg)
        payload = {
            'accountNumber': account_number,
            'amount': amount,
            'expiryDt': self._expiry_date(loan),
        }
        _logger.info("CBS extend-od-limit payload: %s (wage=%s x %s)", payload, wage, term)
        try:
            self._request(http, cfg, '/api/cbs/extend-od-limit', json=payload)
        except UserError as e:
            raise UserError(_("%(err)s\n\nSent: accountNumber=%(acc)s, amount=%(amt)s, expiryDt=%(exp)s "
                              "(basic salary %(wage)s x %(term)s)") % {
                'err': e.args[0], 'acc': payload['accountNumber'], 'amt': payload['amount'],
                'exp': payload['expiryDt'], 'wage': wage, 'term': term})
        return amount, wage, term