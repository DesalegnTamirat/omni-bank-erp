# -*- coding: utf-8 -*-

import time
import logging
import requests
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CbsCashIndemnityWizard(models.TransientModel):
    _name = 'cbs.cash.indemnity.wizard'
    _description = 'Fetch Cash Indemnity from CBS Wizard'

    @api.model
    def _default_open_period(self):
        open_periods = self.env['hr.payroll.period'].search([('state', '=', 'open')], limit=2)
        if len(open_periods) == 1:
            return open_periods
        return self.env['hr.payroll.period']

    @api.model
    def _default_from_date(self):
        period = self._default_open_period()
        if period:
            return period.date_from
        today = fields.Date.today()
        return today.replace(day=1)

    @api.model
    def _default_to_date(self):
        period = self._default_open_period()
        if period:
            return period.date_to
        today = fields.Date.today()
        return today + relativedelta(day=31)

    from_date = fields.Date(
        string='From Date',
        required=True,
        default=_default_from_date,
        help='Start date for cash indemnity allowance calculation (can be earlier than period start date)'
    )
    to_date = fields.Date(
        string='To Date',
        required=True,
        default=_default_to_date,
        help='End date for cash indemnity allowance calculation (must fall between the open period start and end date)'
    )
    working_days = fields.Integer(
        string='Working Days',
        required=True,
        default=22,
        help='Number of working days in the month/period'
    )
    period_id = fields.Many2one(
        'hr.payroll.period',
        string='Payroll Period',
        compute='_compute_period_id',
        store=True,
        readonly=True,
        help='Open Payroll Period determined by the date range'
    )

    @api.depends('from_date', 'to_date')
    def _compute_period_id(self):
        for wizard in self:
            if not wizard.to_date:
                wizard.period_id = False
                continue

            open_periods = self.env['hr.payroll.period'].search([
                ('state', '=', 'open'),
                ('date_from', '<=', wizard.to_date),
                ('date_to', '>=', wizard.to_date),
            ])

            if len(open_periods) == 1:
                wizard.period_id = open_periods.id
            else:
                wizard.period_id = False

    def _get_cbs_session(self):
        self.env.cr.execute("""
            SELECT endpoint, username, cbs_decode(password) as plain_pwd
            FROM cbs_integration
            WHERE environment = 'CBS' AND status = 'true'
            LIMIT 1;
        """)
        row = self.env.cr.fetchone()
        if not row or not row[0]:
            raise UserError(_("No active CBS configuration found in 'cbs_integration' with environment='CBS' and status='true'."))

        endpoint = (row[0] or '').strip().rstrip('/')
        username = (row[1] or '').strip()
        password = row[2] or ''

        login_url = f"{endpoint}/api/auth/login"
        try:
            login_res = requests.post(
                login_url,
                params={'username': username, 'password': password},
                headers={'Content-Type': 'application/json'},
                timeout=20
            )
        except Exception as e:
            raise UserError(_("Failed to connect to CBS Login API at %s:\n%s") % (login_url, str(e)))

        if login_res.status_code != 200:
            err_msg = login_res.text
            try:
                err_json = login_res.json()
                err_msg = err_json.get('message') or err_msg
            except Exception:
                pass
            raise UserError(_("CBS Login failed (HTTP %s):\n%s") % (login_res.status_code, err_msg))

        login_data = login_res.json()
        token = login_data.get('accessToken') or login_data.get('access_token') or login_data.get('token')
        if not token:
            raise UserError(_("CBS Login succeeded but did not return an access token."))

        return endpoint, token

    def action_fetch_cash_indemnity(self):
        self.ensure_one()

        if self.from_date > self.to_date:
            raise UserError(_("From Date cannot be later than To Date."))

        if self.working_days <= 0:
            raise UserError(_("Working Days must be greater than 0."))

        # ─────────────────────────────────────────────────────────────
        # Validation: Exactly ONE open Payroll Period must match To Date
        # ─────────────────────────────────────────────────────────────
        if not self.to_date:
            raise UserError(_("Please specify 'To Date' to determine the Payroll Period."))

        open_periods = self.env['hr.payroll.period'].search([
            ('state', '=', 'open'),
            ('date_from', '<=', self.to_date),
            ('date_to', '>=', self.to_date),
        ])

        if not open_periods:
            raise UserError(_(
                "No OPEN Payroll Period found where 'To Date' (%s) falls between period duration.\n\n"
                "The end date must fall within the start and end dates of an open Payroll Period. "
                "Please configure and open a Payroll Period before fetching Cash Indemnity."
            ) % self.to_date)

        if len(open_periods) > 1:
            names = ", ".join(open_periods.mapped('name'))
            raise UserError(_(
                "Multiple OPEN Payroll Periods (%s) match 'To Date' (%s).\n\n"
                "There must be exactly ONE active open Payroll Period to fetch Cash Indemnity. "
                "Please ensure only one matching period is open."
            ) % (names, self.to_date))

        period = open_periods[0]
        self.period_id = period.id
        period_id_int = int(period.id)
        if period_id_int <= 0:
            raise UserError(_("Invalid Payroll Period ID: %s. It must be a positive number.") % period_id_int)

        endpoint, token = self._get_cbs_session()

        # Call load-cash-indemnity API
        load_url = f"{endpoint}/api/v2/payroll/load-cash-indemnity"
        status_url = f"{endpoint}/api/v2/payroll/load-cash-indemnity/status"
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        params = {
            'fromDate': str(self.from_date),
            'toDate': str(self.to_date),
            'workingDays': int(self.working_days),
            'payrollPeriodId': period_id_int,
            'payroll_period_id': period_id_int,
        }
        payload = {
            'fromDate': str(self.from_date),
            'toDate': str(self.to_date),
            'workingDays': int(self.working_days),
            'payrollPeriodId': period_id_int,
            'payroll_period_id': period_id_int,
        }

        try:
            load_res = requests.post(load_url, headers=headers, params=params, json=payload, timeout=120)
        except Exception as e:
            raise UserError(_("Failed to call CBS Cash Indemnity API at %s:\n%s") % (load_url, str(e)))

        res_data = {}
        try:
            res_data = load_res.json() if load_res.text else {}
        except Exception:
            pass

        # HTTP 200 (OK) or 202 (Accepted - Processing started) are successful responses
        if load_res.status_code not in (200, 202):
            if load_res.status_code in (400, 409) and ('running' in load_res.text.lower() or 'started' in load_res.text.lower()):
                pass  # A job is already active on CBS, we will query its status below
            else:
                err_msg = res_data.get('message') or res_data.get('error') or load_res.text
                raise UserError(_("CBS Cash Indemnity API failed (HTTP %s):\n%s") % (load_res.status_code, err_msg))

        # Query status endpoint
        status_params = {
            'payrollPeriodId': period_id_int,
            'payroll_period_id': period_id_int,
        }
        status_data = {}
        try:
            s_res = requests.get(status_url, headers=headers, params=status_params, timeout=15)
            if s_res.status_code != 200:
                s_res = requests.get(status_url, headers=headers, timeout=15)
            if s_res.status_code == 200 and s_res.text:
                status_data = s_res.json()
        except Exception:
            pass

        job_state = status_data.get('state') or ('COMPLETED' if load_res.status_code == 200 else 'RUNNING')
        started_at = status_data.get('startedAt', '')
        rows = res_data.get('rowsInserted') or status_data.get('rowsInserted', 0)

        if job_state in ('COMPLETED', 'SUCCESS', 'DONE'):
            msg = _("Cash Indemnity calculation completed for period '%s': %s records loaded successfully.") % (period.name, rows)
            title = _('Cash Indemnity Completed')
            msg_type = 'success'
            sticky = False
        elif job_state in ('FAILED', 'ERROR'):
            raise UserError(_("CBS Cash Indemnity calculation failed:\n%s") % (status_data.get('message') or status_data))
        else:
            msg = _("CBS Cash Indemnity calculation is RUNNING in the background.\n"
                    "Period: %s (%s to %s) | Working Days: %s\n"
                    "Started: %s\n\n"
                    "The calculation is processing in CBS. You can check status anytime using 'Check Status'.") % (
                        period.name, self.from_date, self.to_date, self.working_days, started_at or 'just now'
                    )
            title = _('Cash Indemnity Processing')
            msg_type = 'info'
            sticky = True

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': msg,
                'sticky': sticky,
                'type': msg_type,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_check_status(self):
        """Query live status of Cash Indemnity processing from CBS."""
        self.ensure_one()
        endpoint, token = self._get_cbs_session()
        status_url = f"{endpoint}/api/v2/payroll/load-cash-indemnity/status"
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }

        status_params = {}
        if self.period_id:
            status_params = {
                'payrollPeriodId': int(self.period_id.id),
                'payroll_period_id': int(self.period_id.id),
            }

        try:
            s_res = requests.get(status_url, headers=headers, params=status_params, timeout=15)
            if s_res.status_code != 200 and status_params:
                # Fallback without params if endpoint does not accept params
                s_res = requests.get(status_url, headers=headers, timeout=15)
        except Exception as e:
            raise UserError(_("Failed to query CBS Status at %s:\n%s") % (status_url, str(e)))

        if s_res.status_code != 200:
            raise UserError(_("CBS Status query failed (HTTP %s):\n%s") % (s_res.status_code, s_res.text))

        status_data = s_res.json() if s_res.text else {}
        state = status_data.get('state', 'UNKNOWN')
        started = status_data.get('startedAt', 'N/A')
        from_d = status_data.get('fromDate', 'N/A')
        to_d = status_data.get('toDate', 'N/A')
        requested_by = status_data.get('requestedBy', 'N/A')
        rows = status_data.get('rowsInserted', 0)

        period_str = f" ({self.period_id.name})" if self.period_id else ""

        if state in ('COMPLETED', 'SUCCESS', 'DONE'):
            msg = _("Cash Indemnity status: COMPLETED%s\nRecords loaded: %s\nRequested by: %s\nPeriod dates: %s to %s") % (period_str, rows, requested_by, from_d, to_d)
            msg_type = 'success'
        elif state == 'RUNNING':
            msg = _("Cash Indemnity status: RUNNING in background on CBS%s\nStarted at: %s\nRequested by: %s\nPeriod dates: %s to %s") % (period_str, started, requested_by, from_d, to_d)
            msg_type = 'info'
        else:
            msg = _("Cash Indemnity status: %s\n%s") % (state, status_data)
            msg_type = 'warning'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Cash Indemnity Status (Allowance)'),
                'message': msg,
                'sticky': True if state == 'RUNNING' else False,
                'type': msg_type,
            }
        }
