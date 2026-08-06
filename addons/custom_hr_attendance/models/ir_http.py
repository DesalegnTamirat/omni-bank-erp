# -*- coding: utf-8 -*-
import json
import logging
from odoo import models
from odoo.http import request

_logger = logging.getLogger(__name__)

# Routes that must always be accessible regardless of check-in state.
# Prevents employees from being fully locked out of the system.
# Prefix-matched: any route starting with these paths is exempt.
_GATE_EXEMPT_PREFIXES = (
    '/web/login',
    '/web/logout',
    '/web/assets',
    '/web/static',
    '/web/webclient',
    '/web/session',
    '/web/action',
    '/web#action=',
    '/odoo',
    '/odoo/settings',
    '/odoo/attendances',
    '/odoo/action',
    '/discuss',
    '/mail',
    '/custom_hr_attendance',
    '/web/dataset/call_kw/res.config',
)


class IrHttp(models.AbstractModel):
    """
    Session-cached ERP access gate for attendance check-in enforcement.

    When enable_checkin_gate is True, employees who are not checked in cannot
    access ERP application routes. The gate state is cached in the HTTP session
    so the database is queried at most once per session, not once per request.

    Performance contract:
    - Requests within an active session where the employee is checked in: zero DB queries.
    - First request of a session or after check-out: one DB query (employee.attendance_state).
    - All exempt routes: zero DB queries, always pass through.

    This is the highest blast-radius change in the plan — enable only after
    Phase 1 load testing passes at target scale (p95 < 300ms for 6,000 check-ins/15min).
    """
    _inherit = 'ir.http'

    @classmethod
    def _dispatch(cls, endpoint):
        if cls._attendance_gate_enabled() and cls._route_requires_gate():
            if not cls._session_is_checked_in():
                # Session not flagged: check live DB state and update session
                employee = request.env.user.employee_id if request.env.user else None
                if employee and employee.attendance_state == 'checked_in':
                    request.session['attendance_checked_in'] = True
                else:
                    # Employee is not checked in — block access to restricted routes
                    return cls._attendance_gate_blocked_response()
        return super()._dispatch(endpoint)

    @classmethod
    def _attendance_gate_enabled(cls):
        """Returns True if the attendance access gate feature is active."""
        param = request.env['ir.config_parameter'].sudo().get_param(
            'hr_attendance.enable_checkin_gate', 'False'
        )
        return param.lower() in ('true', '1')

    @classmethod
    def _route_requires_gate(cls):
        """
        Returns True if the current request path is NOT on the exempt list.
        Exempt routes are always accessible regardless of check-in state.
        """
        if not request or not request.httprequest:
            return False
        path = request.httprequest.path
        return not any(path.startswith(prefix) for prefix in _GATE_EXEMPT_PREFIXES)

    @classmethod
    def _session_is_checked_in(cls):
        """Returns True if this session already confirmed the employee is checked in."""
        return bool(request.session.get('attendance_checked_in'))

    @classmethod
    def _attendance_gate_blocked_response(cls):
        """
        Returns a minimal JSON-RPC error response directing the employee to check in.
        Used for JSONRPC requests. For regular HTTP requests, redirects to attendance page.
        """
        content_type = request.httprequest.content_type or ''
        if 'json' in content_type:
            body = json.dumps({
                'jsonrpc': '2.0',
                'id': None,
                'error': {
                    'code': 403,
                    'message': 'Access Restricted',
                    'data': {
                        'message': (
                            'You must check in before accessing the system. '
                            'Please use the Check-In button to record your attendance.'
                        ),
                    }
                }
            })
            from werkzeug.wrappers import Response
            return Response(body, status=200, content_type='application/json')

        # For regular HTTP routes, redirect to the attendance check-in screen
        from werkzeug.utils import redirect
        return redirect('/odoo/attendances', code=302)

