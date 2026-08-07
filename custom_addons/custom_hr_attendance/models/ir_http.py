# -*- coding: utf-8 -*-
import json
import logging
from odoo import models
from odoo.http import request

_logger = logging.getLogger(__name__)

# Routes that must always be accessible regardless of check-in state.
# Prevents employees from being fully locked out of the system or crashing web client metadata loads.
# Prefix-matched: any route starting with these paths is exempt.
_GATE_EXEMPT_PREFIXES = (
    '/web/login',
    '/web/logout',
    '/web/assets',
    '/web/static',
    '/web/webclient',
    '/web/session',
    '/web/image',
    '/web/action',
    '/odoo/attendances',
    '/discuss',
    '/mail',
    '/custom_hr_attendance',
    '/web/dataset/call_kw/res.config',
    '/web/dataset/call_kw/res.users',
    '/web/dataset/call_kw/res.company',
    '/web/dataset/call_kw/ir.actions',
    '/web/dataset/call_kw/ir.ui.menu',
    '/web/dataset/call_kw/ir.model.data',
    '/web/dataset/call_kw/hr.attendance',
    '/web/dataset/call_kw/hr.employee',
    '/web/dataset/call_kw/bus.bus',
    '/bus/',
)


class IrHttp(models.AbstractModel):
    """
    Session-cached ERP access gate for attendance check-in enforcement.

    When enable_checkin_gate is True, employees who are not checked in cannot
    access ERP application routes.

    System Administrators (base.group_system) and accounts without linked
    employees are exempt from gate checks to prevent administrative lockouts.
    """
    _inherit = 'ir.http'

    @classmethod
    def _dispatch(cls, endpoint):
        if cls._attendance_gate_enabled() and cls._route_requires_gate():
            user = request.env.user if (request and request.env and request.env.user) else None
            if not user or user._is_public():
                return super()._dispatch(endpoint)

            # System administrators & users without an employee profile are exempt
            if user.has_group('base.group_system') or not user.employee_id:
                return super()._dispatch(endpoint)

            # Check live DB state for the employee
            employee = user.employee_id
            if employee and employee.attendance_state == 'checked_in':
                if request and hasattr(request, 'session'):
                    request.session['attendance_checked_in'] = True
            else:
                if request and hasattr(request, 'session'):
                    request.session['attendance_checked_in'] = False
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

    def session_info(self):
        res = super().session_info()
        user = request.env.user if request and request.env else None
        if user and not user._is_public():
            gate_enabled = self._attendance_gate_enabled()
            is_admin = user.has_group('base.group_system')
            employee = user.employee_id
            checked_in = bool(employee and employee.attendance_state == 'checked_in')
            res['enable_checkin_gate'] = gate_enabled
            res['is_system_admin'] = is_admin
            res['attendance_checked_in'] = checked_in
        return res

