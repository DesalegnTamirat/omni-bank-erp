import time
import json
import logging
from odoo import models, _
from odoo.exceptions import ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)

# Routes that must always be accessible regardless of check-in state.
# Prevents employees from being fully locked out of the system or crashing web client metadata loads.
# Prefix-matched: any route starting with these paths is exempt.
_GATE_EXEMPT_PREFIXES = (
    # Core web client infrastructure & static assets
    '/web/login',
    '/web/logout',
    '/web/assets',
    '/web/bundle',
    '/web/static',
    '/web/webclient',
    '/web/session',
    '/web/image',
    '/web/action',
    '/web/manifest',
    '/web/service-worker',
    '/websocket',
    '/web/dataset/call_kw/ir.attachment',
    '/web/dataset/call_kw/ir.http',
    '/web/dataset/call_kw/res.users',
    '/web/dataset/call_kw/res.company',
    '/web/dataset/call_kw/ir.actions',
    '/web/dataset/call_kw/ir.ui.menu',
    '/web/dataset/call_kw/ir.model.data',
    '/web/dataset/call_kw/bus.bus',
    '/bus/',
    '/discuss',
    '/mail',

    # Attendance module UI and API controllers
    '/odoo/attendances',
    '/custom_hr_attendance',

    # Attendance module models & administration (accessible to manage attendance & turn off gate)
    '/web/dataset/call_kw/hr.attendance',
    '/web/dataset/call_kw/hr.employee',
    '/web/dataset/call_kw/job.shift',
    '/web/dataset/call_kw/job.position',
    '/web/dataset/call_kw/location.based',
    '/web/dataset/call_kw/attendance.',
    '/web/dataset/call_kw/over.time',
    '/web/dataset/call_kw/overtime.',
    '/web/dataset/call_kw/my.shift',
    '/web/dataset/call_kw/res.config',
    '/web/dataset/call_kw/ir.config_parameter',
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
    def _is_user_gate_exempt(cls, user):
        """
        Determines whether the user is exempt from ERP check-in gate enforcement:
        1. Superuser, System Administrator (base.group_system), or Attendance Manager (hr_attendance.group_hr_attendance_manager)
        2. Technical/portal accounts with no linked employee profile
        3. Active exemption record in attendance.gate.exception
        """
        if not user or user._is_public() or user._is_superuser() or not user.employee_id:
            return True

        # System Administrator & Attendance Administrator: full access to all modules for support/maintenance
        if user.has_group('base.group_system') or user.has_group('hr_attendance.group_hr_attendance_manager'):
            return True

        # Exceptional user check from dedicated attendance.gate.exception table
        env = (request.env if request and getattr(request, 'env', None) else None) or user.env
        if env and 'attendance.gate.exception' in env:
            try:
                if env['attendance.gate.exception'].sudo().search_count([
                    ('employee_id', '=', user.employee_id.id),
                    ('active', '=', True),
                ]):
                    return True
            except Exception:
                pass

        # 4. Non-working day exemption: employees are not forced to check in on Public Holidays or scheduled Days Off
        try:
            emp = user.employee_id
            if emp:
                today = fields.Date.context_today(emp)
                sched = emp._resolve_employee_full_schedule(target_date=today)
                if sched.get('is_day_off') or sched.get('is_on_leave'):
                    return True
        except Exception:
            pass

        return False

    @classmethod
    def _dispatch(cls, endpoint):
        if cls._attendance_gate_enabled() and cls._route_requires_gate():
            user = request.env.user if (request and request.env and request.env.user) else None
            if not user or user._is_public():
                return super()._dispatch(endpoint)

            # Administrators & registered exceptional users bypass gate checks completely
            if cls._is_user_gate_exempt(user):
                return super()._dispatch(endpoint)

            # 1. Fast path: check session cache first with a 120s TTL
            session = getattr(request, 'session', None)
            now_ts = time.time()
            if session:
                cached_checked_in = session.get('attendance_checked_in')
                last_check_ts = session.get('attendance_gate_checked_at', 0)
                # If cached within 120s and checked in, bypass DB lookup completely (0 SQL queries)
                if cached_checked_in is True and (now_ts - last_check_ts < 120):
                    return super()._dispatch(endpoint)

            # 2. Slow path: check live database state
            employee = user.employee_id
            if employee and employee.attendance_state == 'checked_in':
                if session:
                    session['attendance_checked_in'] = True
                    session['attendance_gate_checked_at'] = now_ts
            else:
                if session:
                    session['attendance_checked_in'] = False
                    session['attendance_gate_checked_at'] = now_ts
                # Employee is not checked in — block access to restricted routes
                return cls._attendance_gate_blocked_response()
        return super()._dispatch(endpoint)

    @classmethod
    def _attendance_gate_enabled(cls):
        """Returns True if the attendance access gate feature is active (read from RAM cache)."""
        if not request or not request.env:
            return False
        cfg = request.env['hr.employee']._get_attendance_config_params()
        return bool(cfg.get('enable_checkin_gate', False))

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
        Directs un-checked-in employees to check in.
        Raises a standard Odoo ValidationError for RPC calls so the frontend displays a
        clean, user-friendly Validation Error modal instead of crashing the OWL lifecycle.
        For browser page navigation, redirects to the attendance screen.
        """
        content_type = request.httprequest.content_type or ''
        path = request.httprequest.path or ''
        is_json = 'json' in content_type or path.startswith('/web/dataset/')
        if is_json:
            raise ValidationError(_(
                'You must check in before accessing the system. '
                'Please use the Check-In button to record your attendance.'
            ))

        # For regular full-page browser navigation, redirect to attendance screen
        from werkzeug.utils import redirect
        return redirect('/odoo/attendances', code=302)

    def session_info(self):
        res = super().session_info()
        user = request.env.user if request and request.env else None
        if user and not user._is_public():
            gate_enabled = self._attendance_gate_enabled()
            is_admin = user.has_group('base.group_system')
            is_attendance_admin = is_admin or user.has_group('hr_attendance.group_hr_attendance_manager')
            is_gate_exempt = self._is_user_gate_exempt(user)
            employee = user.employee_id
            checked_in = bool(employee and employee.attendance_state == 'checked_in')
            res['enable_checkin_gate'] = gate_enabled
            res['is_system_admin'] = is_admin
            res['is_attendance_admin'] = is_attendance_admin
            res['is_gate_exempt'] = is_gate_exempt
            res['attendance_checked_in'] = checked_in
        return res

