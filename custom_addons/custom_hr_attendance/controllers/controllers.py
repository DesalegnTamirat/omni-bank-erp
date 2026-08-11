# -*- coding: utf-8 -*-
import datetime
import pytz
from odoo import http, fields
from odoo.http import request

from odoo.addons.hr_attendance.controllers.main import HrAttendance


class BunnaMyAttendance(http.Controller):


    def _enrich_attendance_data(self, employee, data):
        if not employee or not data:
            return data

        data['job_title'] = employee.job_title or (employee.job_id.name if employee.job_id else "") or ""
        data['department_name'] = employee.department_id.name if employee.department_id else ""

        today = fields.Date.context_today(request.env.user)
        # Week starts on Monday
        start_of_week = today - datetime.timedelta(days=today.weekday())
        end_of_week = start_of_week + datetime.timedelta(days=6)

        # `check_in` is stored in UTC, but start_of_week/end_of_week are local
        # calendar dates. Combining them naively and comparing directly against
        # check_in silently drops/misattributes records near local midnight
        # whenever the user's timezone has a non-zero UTC offset (e.g. a
        # 1:29 AM local check-in in UTC+3 is stored as ~22:29 the previous day
        # in UTC, so a naive "Monday 00:00" boundary would exclude it).
        # Localize the boundaries in the user's timezone, then convert to UTC.
        tz_name = request.env.user.tz or 'UTC'
        try:
            local_tz = pytz.timezone(tz_name)
        except Exception:
            local_tz = pytz.utc
        week_start_utc = local_tz.localize(
            datetime.datetime.combine(start_of_week, datetime.time.min)
        ).astimezone(pytz.utc).replace(tzinfo=None)
        week_end_utc = local_tz.localize(
            datetime.datetime.combine(end_of_week, datetime.time.max)
        ).astimezone(pytz.utc).replace(tzinfo=None)

        # Search attendances spanning the week window in employee local time.
        # Fetch records starting from 1 day prior to start_of_week to account
        # for local timezone offsets (e.g. UTC+3 check-ins late Sunday UTC).
        search_start_utc = local_tz.localize(
            datetime.datetime.combine(start_of_week - datetime.timedelta(days=1), datetime.time.min)
        ).astimezone(pytz.utc).replace(tzinfo=None)
        search_end_utc = local_tz.localize(
            datetime.datetime.combine(end_of_week + datetime.timedelta(days=1), datetime.time.max)
        ).astimezone(pytz.utc).replace(tzinfo=None)

        attendances = request.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', search_start_utc),
            ('check_in', '<=', search_end_utc)
        ], order='check_in asc')

        # Calculate weekly total and daily breakdown
        day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        daily_hours = {d: 0.0 for d in range(7)}
        daily_checked_in = {d: False for d in range(7)}

        total_weekly_hours = 0.0
        today_completed_hours = 0.0   # closed sessions today only

        for att in attendances:
            # Convert UTC check_in to employee's local datetime
            check_in_local_dt = fields.Datetime.context_timestamp(employee, att.check_in)
            check_in_local_date = check_in_local_dt.date()

            # Include only if the local check_in date falls inside this calendar week [start_of_week .. end_of_week]
            if not (start_of_week <= check_in_local_date <= end_of_week):
                continue

            day_idx = check_in_local_dt.weekday()
            is_today_att = (check_in_local_date == today)

            if att.check_out:
                duration = att.worked_hours or 0.0
                if is_today_att:
                    today_completed_hours += duration
            else:
                now_dt = fields.Datetime.context_timestamp(employee, fields.Datetime.now())
                # Use actual_check_in if available for live session elapsed calculation
                live_start_dt = fields.Datetime.context_timestamp(employee, att.actual_check_in or att.check_in)
                duration = max(0.0, (now_dt - live_start_dt).total_seconds() / 3600.0)
                daily_checked_in[day_idx] = True

            daily_hours[day_idx] += duration

        total_weekly_hours = sum(daily_hours.values())

        daily_breakdown = []
        max_daily = max(daily_hours.values()) if any(daily_hours.values()) else 8.0
        if max_daily <= 0:
            max_daily = 8.0

        for d in range(7):
            cur_date = start_of_week + datetime.timedelta(days=d)
            hrs = round(daily_hours[d], 2)
            hours_int = int(hrs)
            mins_int = int(round((hrs - hours_int) * 60))

            # Progress bar percentage (capped relative to 9 hours standard max day)
            pct = min(100, int((hrs / 9.0) * 100))

            daily_breakdown.append({
                'day_name': day_names[d],
                'date_str': cur_date.strftime('%b %d'),
                'hours': hrs,
                'hours_formatted': f"{hours_int:02d}h {mins_int:02d}m",
                'percentage': pct,
                'is_today': cur_date == today,
                'checked_in': daily_checked_in[d]
            })

        # Format weekly hours
        wk_hours_int = int(total_weekly_hours)
        wk_mins_int = int(round((total_weekly_hours - wk_hours_int) * 60))
        data['weekly_hours_formatted'] = f"{wk_hours_int:02d}h {wk_mins_int:02d}m"
        data['weekly_hours_float'] = round(total_weekly_hours, 2)
        data['daily_breakdown'] = daily_breakdown
        # Send completed-today hours as float hours so JS can format them
        data['hours_today_completed'] = round(today_completed_hours, 6)
        data['hours_today'] = round(today_completed_hours, 6)

        # Determine real-time check-in state directly from active open attendance record
        open_att = request.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_out', '=', False)
        ], order='check_in desc', limit=1)

        if open_att and open_att.check_in:
            data['attendance_state'] = 'checked_in'
            # Drive the live dashboard timer off the *actual* wall-clock
            # check-in moment (actual_check_in) so it starts at 00:00:00
            # when the employee taps Check In, rather than off the
            # shift-aligned `check_in` field used for worked_hours/payroll.
            # Fall back to check_in for older records created before this
            # field existed.
            live_check_in = open_att.actual_check_in or open_att.check_in
            # Append 'Z' so JS Luxon knows this is UTC and converts to local properly
            data['check_in_raw'] = fields.Datetime.to_string(live_check_in).replace(' ', 'T') + 'Z'
            check_in_local = fields.Datetime.context_timestamp(employee, open_att.check_in)
            data['check_in_time_str'] = check_in_local.strftime('%I:%M %p')

            # Punctuality check (8:30 AM standard start)
            if check_in_local.hour > 8 or (check_in_local.hour == 8 and check_in_local.minute > 30):
                data['check_in_status'] = 'Late'
            else:
                data['check_in_status'] = 'On Time'
        else:
            data['attendance_state'] = 'checked_out'
            data['check_in_raw'] = False
            data['check_in_time_str'] = False
            data['check_in_status'] = False

        return data

    @http.route('/custom_hr_attendance/my_attendance_data', type='jsonrpc', auth='user', readonly=True)
    def my_attendance_data(self):
        """Read-only snapshot for the current user's employee."""
        employee = request.env.user.employee_id
        res = HrAttendance._get_employee_info_response(employee)
        return self._enrich_attendance_data(employee, res)

    @http.route('/custom_hr_attendance/my_attendance_toggle', type='jsonrpc', auth='user')
    def my_attendance_toggle(self, latitude=False, longitude=False):
        """Check the current user's employee in or out instantly."""
        employee = request.env.user.employee_id
        employee._attendance_action_change()
        res = HrAttendance._get_employee_info_response(employee)
        return self._enrich_attendance_data(employee, res)

    @http.route('/custom_hr_attendance/get_settings', type='jsonrpc', auth='user', readonly=True)
    def get_settings(self):
        """Return current attendance config parameters and whether the user is an attendance admin."""
        params = request.env['ir.config_parameter'].sudo()
        is_admin = request.env.user.has_group('hr_attendance.group_hr_attendance_manager') or request.env.user.has_group('base.group_system')


        def _bool(key, default=True):
            val = params.get_param(key)
            if val is False or val is None:
                return default
            return val.lower() in ('true', '1', 'yes')

        def _float(key, default=0.0):
            val = params.get_param(key)
            try:
                return float(val) if val is not None else default
            except (ValueError, TypeError):
                return default

        def _int(key, default=0):
            val = params.get_param(key)
            try:
                return int(val) if val is not None else default
            except (ValueError, TypeError):
                return default

        return {
            'is_admin': is_admin,
            'settings': {
                'enable_checkin_restriction': _bool('hr_attendance.enable_checkin_restriction', True),
                'enable_checkout_restriction': _bool('hr_attendance.enable_checkout_restriction', True),
                'enable_saturday_halfday': _bool('hr_attendance.enable_saturday_halfday', True),
                'enable_lunch_break': _bool('hr_attendance.enable_lunch_break', False),
                'enable_auto_absence': _bool('hr_attendance.enable_auto_absence', True),
                'enable_checkin_gate': _bool('hr_attendance.enable_checkin_gate', False),
                'morning_time': _float('hr_attendance.morning_time', 8.0),
                'exit_time': _float('hr_attendance.exit_time', 17.0),
                'checkin_buffer': _float('hr_attendance.checkin_buffer', 0.5),
                'force_checkout_hours': _float('hr_attendance.force_checkout_hours', 14.0),
                'saturday_exit_time': _float('hr_attendance.saturday_exit_time', 14.75),
                'lateness_violation_threshold': _int('hr_attendance.lateness_violation_threshold', 3),
                'force_checkout_violation_threshold': _int('hr_attendance.force_checkout_violation_threshold', 2),
            }
        }

    @http.route('/custom_hr_attendance/save_settings', type='jsonrpc', auth='user')
    def save_settings(self, settings=None):
        """Persist attendance config parameters. Attendance Manager or Admin."""
        if not (request.env.user.has_group('hr_attendance.group_hr_attendance_manager') or request.env.user.has_group('base.group_system')):
            return {'error': 'Permission denied'}

        if not settings:
            return {'error': 'No settings provided'}
        params = request.env['ir.config_parameter'].sudo()
        bool_keys = [
            'enable_checkin_restriction', 'enable_checkout_restriction',
            'enable_saturday_halfday', 'enable_lunch_break',
            'enable_auto_absence', 'enable_checkin_gate',
        ]
        float_keys = ['morning_time', 'exit_time', 'checkin_buffer', 'force_checkout_hours', 'saturday_exit_time']
        int_keys = ['lateness_violation_threshold', 'force_checkout_violation_threshold']
        for key in bool_keys:
            if key in settings:
                params.set_param(f'hr_attendance.{key}', str(bool(settings[key])))
        for key in float_keys:
            if key in settings:
                params.set_param(f'hr_attendance.{key}', str(round(float(settings[key]), 2)))
        for key in int_keys:
            if key in settings:
                params.set_param(f'hr_attendance.{key}', str(int(settings[key])))
        return {'success': True}
