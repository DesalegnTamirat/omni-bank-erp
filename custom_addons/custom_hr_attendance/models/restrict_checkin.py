# -*- coding: utf-8 -*-
import datetime
import pytz
import logging
from odoo import models, fields, api, tools, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _fmt(f):
    """Helper: format float 8.5 -> '08:30', 17.0 -> '17:00'"""
    if f is None or f is False:
        return "--:--"
    h = int(f)
    m = int(round((f - h) * 60))
    if m >= 60:
        h += 1
        m = 0
    return f"{h:02d}:{m:02d}"


class HrEmployeePrivate(models.Model):
    _inherit = 'hr.employee'

    _last_action_cache = {}

    @property
    def _last_attendance_action(self):
        return HrEmployeePrivate._last_action_cache.get(self.id, False)

    @_last_attendance_action.setter
    def _last_attendance_action(self, value):
        HrEmployeePrivate._last_action_cache[self.id] = value

    # ============================================================
    # CONFIG PARAMETER CACHING (O(1) in RAM via @tools.ormcache)
    # ============================================================
    @api.model
    @tools.ormcache()
    def _get_attendance_config_params(self):
        """ Cached dictionary of attendance regulation parameters to avoid DB reads on hot paths. """
        params = self.env['ir.config_parameter'].sudo()
        return {
            'morning_time': float(params.get_param('hr_attendance.morning_time', 8.0)),
            'exit_time': float(params.get_param('hr_attendance.exit_time', 17.0)),
            'enable_saturday_halfday': params.get_param('hr_attendance.enable_saturday_halfday', 'True').lower() in ('true', '1'),
            'saturday_halfday_district': params.get_param('hr_attendance.saturday_halfday_district', 'True').lower() in ('true', '1'),
            'saturday_exit_time': float(params.get_param('hr_attendance.saturday_exit_time', 12.0)),
            'enable_lunch_break': params.get_param('hr_attendance.enable_lunch_break', 'False').lower() in ('true', '1'),
            'lunch_out_time': float(params.get_param('hr_attendance.lunch_out_time', 12.0)),
            'lunch_duration': float(params.get_param('hr_attendance.lunch_duration', 1.0)),
            'grace_time': float(params.get_param('hr_attendance.grace_time', 0.25)),
            'dead_time': float(params.get_param('hr_attendance.dead_time', 0.333333)),
            'min_work_hour': float(params.get_param('hr_attendance.min_work_hour', 4.0)),
            'enable_checkin_gate': params.get_param('hr_attendance.enable_checkin_gate', 'False').lower() in ('true', '1'),
            'enable_checkin_restriction': params.get_param('hr_attendance.enable_checkin_restriction', 'True').lower() in ('true', '1'),
            'enable_checkout_restriction': params.get_param('hr_attendance.enable_checkout_restriction', 'True').lower() in ('true', '1'),
        }

    # ============================================================
    # UNIVERSAL SCHEDULE RESOLVER
    # ============================================================
    def _resolve_employee_full_schedule(self, current_float=None, target_date=None):
        """
        Universally resolves an employee's full schedule for target_date.
        Returns a dict:
        {
            'shift_start': float,
            'shift_end': float,
            'has_lunch': bool,
            'lunch_start': float,
            'lunch_end': float,
            'lunch_duration': float,
            'lunch_midpoint': float,
            'is_night_shift': bool,
            'is_day_off': bool,
            'shift_name': str
        }
        """
        if not target_date:
            target_date = fields.Date.context_today(self)

        cfg = self._get_attendance_config_params()
        default_morning_time = cfg['morning_time']
        default_exit_time = cfg['exit_time']
        enable_saturday = cfg['enable_saturday_halfday']
        enable_district_saturday = cfg['saturday_halfday_district']
        saturday_exit_time = cfg['saturday_exit_time']
        enable_lunch = cfg['enable_lunch_break']
        default_lunch_out = cfg['lunch_out_time']
        default_lunch_dur = cfg['lunch_duration']

        is_saturday = (target_date.weekday() == 5) if target_date else False

        # 0. Approved Time Off / Leave (hr.leave)
        leave = self.env['hr.leave'].sudo().search([
            ('employee_id', '=', self.id),
            ('state', '=', 'validate'),
            ('date_from', '<=', datetime.datetime.combine(target_date, datetime.time.max)),
            ('date_to', '>=', datetime.datetime.combine(target_date, datetime.time.min)),
        ], limit=1)

        if leave:
            l_name = leave.holiday_status_id.name or _('Time Off')
            if isinstance(l_name, dict):
                l_name = l_name.get('en_US', list(l_name.values())[0]) if l_name else _('Time Off')
            is_half = bool(getattr(leave, 'request_unit_half', False) or getattr(leave, 'half_day', False) or (getattr(leave, 'number_of_days', 1.0) == 0.5))
            half_period = getattr(leave, 'request_date_from_period', False) or getattr(leave, 'single_half_day_period', 'am')
            if is_half:
                if half_period == 'am':
                    return {
                        'shift_start': 13.0, 'shift_end': default_exit_time,
                        'has_lunch': False, 'lunch_start': 0.0, 'lunch_end': 0.0, 'lunch_duration': 0.0,
                        'lunch_midpoint': 0.0, 'is_night_shift': False, 'is_day_off': False,
                        'is_on_leave': False, 'is_half_day_leave': True,
                        'leave_name': l_name, 'shift_name': f"Afternoon Shift (Morning on {l_name})"
                    }
                else:
                    return {
                        'shift_start': default_morning_time, 'shift_end': 12.0,
                        'has_lunch': False, 'lunch_start': 0.0, 'lunch_end': 0.0, 'lunch_duration': 0.0,
                        'lunch_midpoint': 0.0, 'is_night_shift': False, 'is_day_off': False,
                        'is_on_leave': False, 'is_half_day_leave': True,
                        'leave_name': l_name, 'shift_name': f"Morning Shift (Afternoon on {l_name})"
                    }
            else:
                return {
                    'shift_start': 0.0, 'shift_end': 0.0,
                    'has_lunch': False, 'lunch_start': 0.0, 'lunch_end': 0.0, 'lunch_duration': 0.0,
                    'lunch_midpoint': 0.0, 'is_night_shift': False, 'is_day_off': True,
                    'is_on_leave': True, 'leave_name': l_name,
                    'shift_name': f"Approved Time Off ({l_name})"
                }

        # 1. Roster Exception (Date-Based)
        roster_exceptions = self.env['job.position.roster.exception'].sudo().search([
            ('employee_id', '=', self.id),
            ('status', '=', 'active'),
            ('active', '=', True),
            ('start_date', '<=', target_date),
            ('end_date', '>=', target_date)
        ], order='start_date desc, id desc', limit=1)

        if roster_exceptions:
            line = roster_exceptions.line_ids.filtered(lambda l: l.date == target_date)
            if line:
                line = line[0]
                if line.schedule_type == 'day_off':
                    return {
                        'shift_start': 0.0, 'shift_end': 0.0, 'has_lunch': False,
                        'lunch_start': 0.0, 'lunch_end': 0.0, 'lunch_duration': 0.0,
                        'lunch_midpoint': 0.0, 'is_night_shift': False, 'is_day_off': True,
                        'shift_name': 'Scheduled Day Off',
                        'is_custom_exception': True,
                        'source_label': 'Job Position Roster Exception'
                    }
                shift = line.shift_id
                if shift:
                    has_l = bool(enable_lunch and shift.has_lunch_break and not shift.is_night_shift and not is_saturday)
                    l_start = (shift.lunch_start_time or 12.0) if has_l else 0.0
                    l_dur = (shift.lunch_duration or 1.0) if has_l else 0.0
                    l_end = l_start + l_dur
                    return {
                        'shift_start': shift.start_time, 'shift_end': shift.end_time,
                        'has_lunch': has_l, 'lunch_start': l_start, 'lunch_end': l_end,
                        'lunch_duration': l_dur, 'lunch_midpoint': (l_start + l_end) / 2.0 if has_l else 0.0,
                        'is_night_shift': bool(shift.is_night_shift), 'is_day_off': False,
                        'shift_name': shift.name,
                        'is_custom_exception': True,
                        'source_label': 'Job Position Roster Exception'
                    }

        # 2. Job Position Exception (Static)
        job_exceptions = self.env['job.position.exception'].sudo().search([
            ('employee_id', '=', self.id), ('status', '=', 'active'),
            ('active', '=', True),
            ('start_date', '<=', target_date),
            '|', ('end_date', '=', False), ('end_date', '>=', target_date)
        ], order='start_date desc, id desc', limit=1)

        if job_exceptions and job_exceptions.shift_id:
            shift = job_exceptions.shift_id
            has_l = bool(enable_lunch and shift.has_lunch_break and not shift.is_night_shift and not is_saturday)
            l_start = (shift.lunch_start_time or 12.0) if has_l else 0.0
            l_dur = (shift.lunch_duration or 1.0) if has_l else 0.0
            l_end = l_start + l_dur
            return {
                'shift_start': shift.start_time, 'shift_end': shift.end_time,
                'has_lunch': has_l, 'lunch_start': l_start, 'lunch_end': l_end,
                'lunch_duration': l_dur, 'lunch_midpoint': (l_start + l_end) / 2.0 if has_l else 0.0,
                'is_night_shift': bool(shift.is_night_shift), 'is_day_off': False,
                'shift_name': shift.name,
                'is_custom_exception': True,
                'source_label': 'Job Position Exception'
            }

        # 3. Location-based shifts
        location_exceptions = self.env['location.based.exception'].browse()
        if self.default_operating_unit_id:
            ou_ids = [self.default_operating_unit_id.id]
            if hasattr(self.default_operating_unit_id, 'parent_unit') and self.default_operating_unit_id.parent_unit:
                ou_ids.append(self.default_operating_unit_id.parent_unit.id)
            location_exceptions = self.env['location.based.exception'].sudo().search([
                '|', ('operating_unit_ids', 'in', ou_ids),
                     ('operating_unit', 'in', ou_ids),
                ('active', '=', True),
                ('state', '=', 'active'),
                ('start_date', '<=', target_date),
                '|', ('end_date', '=', False), ('end_date', '>=', target_date)
            ], limit=1)

        if location_exceptions:
            loc = location_exceptions
            shift = loc.shift_id if hasattr(loc, 'shift_id') and loc.shift_id else False
            is_night = shift.is_night_shift if shift else False
            has_l = bool(enable_lunch and (shift.has_lunch_break if shift else loc.has_lunch_break) and not is_night and not is_saturday)
            l_start = (shift.lunch_start_time or 12.0) if (shift and has_l) else (default_lunch_out if has_l else 0.0)
            l_dur = (shift.lunch_duration or default_lunch_dur) if (shift and has_l) else (default_lunch_dur if has_l else 0.0)
            l_end = l_start + l_dur
            s_start = shift.start_time if shift else loc.start_time
            s_end = shift.end_time if shift else loc.end_time
            return {
                'shift_start': s_start, 'shift_end': s_end,
                'has_lunch': has_l, 'lunch_start': l_start, 'lunch_end': l_end,
                'lunch_duration': l_dur, 'lunch_midpoint': (l_start + l_end) / 2.0 if has_l else 0.0,
                'is_night_shift': bool(is_night), 'is_day_off': False,
                'shift_name': (shift.name if shift else loc.name) or 'Location Shift',
                'is_custom_exception': True,
                'source_label': 'Location-Based Exception'
            }

        # 4. Default global schedule
        if target_date and target_date.weekday() == 6:
            return {
                'shift_start': 0.0, 'shift_end': 0.0,
                'has_lunch': False, 'lunch_start': 0.0, 'lunch_end': 0.0, 'lunch_duration': 0.0,
                'lunch_midpoint': 0.0, 'is_night_shift': False, 'is_day_off': True,
                'shift_name': 'Scheduled Day Off (Sunday)',
                'is_custom_exception': False,
                'source_label': 'Default Calendar'
            }

        s_end = default_exit_time
        is_sat_half = False
        if enable_saturday and is_saturday:
            ou = self.default_operating_unit_id
            unit_type = ou.work_unit_type if ou else False
            if unit_type in ('head_office', 'head_offices', 'ho') or (unit_type in ('district', 'district_office', 'regional_office') and enable_district_saturday) or not ou:
                s_end = saturday_exit_time
                is_sat_half = True

        has_l = bool(enable_lunch and not is_saturday)
        l_start = default_lunch_out if has_l else 0.0
        l_dur = default_lunch_dur if has_l else 0.0
        l_end = l_start + l_dur

        shift_title = 'Default Global Shift (Saturday Half Day)' if is_sat_half else 'Default Global Shift'

        return {
            'shift_start': default_morning_time, 'shift_end': s_end,
            'has_lunch': has_l, 'lunch_start': l_start, 'lunch_end': l_end,
            'lunch_duration': l_dur, 'lunch_midpoint': (l_start + l_end) / 2.0 if has_l else 0.0,
            'is_night_shift': False, 'is_day_off': False,
            'shift_name': shift_title
        }

    def _resolve_schedules_batch(self, date_from, date_to):
        """
        Batch resolves schedules for self (an hr.employee record) across date_from to date_to.
        Returns a dict mapping date -> resolved schedule dict.
        Fires only 3-4 bulk queries total for the entire date range instead of per-day queries.
        """
        self.ensure_one()
        cfg = self._get_attendance_config_params()
        default_morning_time = cfg['morning_time']
        default_exit_time = cfg['exit_time']
        enable_saturday = cfg['enable_saturday_halfday']
        enable_district_saturday = cfg['saturday_halfday_district']
        saturday_exit_time = cfg['saturday_exit_time']
        enable_lunch = cfg['enable_lunch_break']
        default_lunch_out = cfg['lunch_out_time']
        default_lunch_dur = cfg['lunch_duration']

        # 1. Batch fetch validated leaves
        leaves = self.env['hr.leave'].sudo().search([
            ('employee_id', '=', self.id),
            ('state', '=', 'validate'),
            ('date_from', '<=', datetime.datetime.combine(date_to, datetime.time.max)),
            ('date_to', '>=', datetime.datetime.combine(date_from, datetime.time.min)),
        ])

        # 2. Batch fetch active roster lines
        roster_lines = self.env['job.position.roster.exception.line'].sudo().search([
            ('employee_id', '=', self.id),
            ('roster_id.status', '=', 'active'),
            ('roster_id.active', '=', True),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
        ], order='date asc')
        roster_lines_by_date = {line.date: line for line in roster_lines}

        # 3. Batch fetch static job position exception
        job_exceptions = self.env['job.position.exception'].sudo().search([
            ('employee_id', '=', self.id),
            ('status', '=', 'active'),
            ('active', '=', True),
            ('start_date', '<=', date_to),
            '|', ('end_date', '=', False), ('end_date', '>=', date_from)
        ], order='start_date desc, id desc', limit=1)

        # 4. Batch fetch location-based exception
        location_exceptions = self.env['location.based.exception'].browse()
        if self.default_operating_unit_id:
            ou_ids = [self.default_operating_unit_id.id]
            if hasattr(self.default_operating_unit_id, 'parent_unit') and self.default_operating_unit_id.parent_unit:
                ou_ids.append(self.default_operating_unit_id.parent_unit.id)
            location_exceptions = self.env['location.based.exception'].sudo().search([
                '|', ('operating_unit_ids', 'in', ou_ids),
                     ('operating_unit', 'in', ou_ids),
                ('active', '=', True),
                ('state', '=', 'active'),
                ('start_date', '<=', date_to),
                '|', ('end_date', '=', False), ('end_date', '>=', date_from)
            ], limit=1)

        result = {}
        cur_date = date_from
        while cur_date <= date_to:
            is_saturday = (cur_date.weekday() == 5)
            is_sunday = (cur_date.weekday() == 6)

            # Check leave for cur_date
            matching_leave = leaves.filtered(lambda l: l.date_from.date() <= cur_date <= l.date_to.date())
            if matching_leave:
                leave = matching_leave[0]
                l_name = leave.holiday_status_id.name or _('Time Off')
                if isinstance(l_name, dict):
                    l_name = l_name.get('en_US', list(l_name.values())[0]) if l_name else _('Time Off')
                is_half = bool(getattr(leave, 'request_unit_half', False) or getattr(leave, 'half_day', False) or (getattr(leave, 'number_of_days', 1.0) == 0.5))
                half_period = getattr(leave, 'request_date_from_period', False) or getattr(leave, 'single_half_day_period', 'am')
                if is_half:
                    if half_period == 'am':
                        result[cur_date] = {
                            'shift_start': 13.0, 'shift_end': default_exit_time,
                            'has_lunch': False, 'lunch_start': 0.0, 'lunch_end': 0.0, 'lunch_duration': 0.0,
                            'lunch_midpoint': 0.0, 'is_night_shift': False, 'is_day_off': False,
                            'is_on_leave': False, 'is_half_day_leave': True,
                            'leave_name': l_name, 'shift_name': f"Afternoon Shift (Morning on {l_name})"
                        }
                    else:
                        result[cur_date] = {
                            'shift_start': default_morning_time, 'shift_end': 12.0,
                            'has_lunch': False, 'lunch_start': 0.0, 'lunch_end': 0.0, 'lunch_duration': 0.0,
                            'lunch_midpoint': 0.0, 'is_night_shift': False, 'is_day_off': False,
                            'is_on_leave': False, 'is_half_day_leave': True,
                            'leave_name': l_name, 'shift_name': f"Morning Shift (Afternoon on {l_name})"
                        }
                else:
                    result[cur_date] = {
                        'shift_start': 0.0, 'shift_end': 0.0,
                        'has_lunch': False, 'lunch_start': 0.0, 'lunch_end': 0.0, 'lunch_duration': 0.0,
                        'lunch_midpoint': 0.0, 'is_night_shift': False, 'is_day_off': True,
                        'is_on_leave': True, 'leave_name': l_name,
                        'shift_name': f"Approved Time Off ({l_name})"
                    }
                cur_date += datetime.timedelta(days=1)
                continue

            # Check roster line
            line = roster_lines_by_date.get(cur_date)
            if line:
                if line.schedule_type == 'day_off':
                    result[cur_date] = {
                        'shift_start': 0.0, 'shift_end': 0.0, 'has_lunch': False,
                        'lunch_start': 0.0, 'lunch_end': 0.0, 'lunch_duration': 0.0,
                        'lunch_midpoint': 0.0, 'is_night_shift': False, 'is_day_off': True,
                        'shift_name': 'Scheduled Day Off', 'is_custom_exception': True,
                        'source_label': 'Job Position Roster Exception'
                    }
                else:
                    shift = line.shift_id
                    if shift:
                        has_l = bool(enable_lunch and shift.has_lunch_break and not shift.is_night_shift and not is_saturday)
                        l_start = (shift.lunch_start_time or 12.0) if has_l else 0.0
                        l_dur = (shift.lunch_duration or 1.0) if has_l else 0.0
                        l_end = l_start + l_dur
                        result[cur_date] = {
                            'shift_start': shift.start_time, 'shift_end': shift.end_time,
                            'has_lunch': has_l, 'lunch_start': l_start, 'lunch_end': l_end,
                            'lunch_duration': l_dur, 'lunch_midpoint': (l_start + l_end) / 2.0 if has_l else 0.0,
                            'is_night_shift': bool(shift.is_night_shift), 'is_day_off': False,
                            'shift_name': shift.name, 'is_custom_exception': True,
                            'source_label': 'Job Position Roster Exception'
                        }
                    else:
                        result[cur_date] = self._resolve_employee_full_schedule(target_date=cur_date)
                cur_date += datetime.timedelta(days=1)
                continue

            # Check static job exception
            if job_exceptions and job_exceptions.shift_id and (job_exceptions.start_date <= cur_date and (not job_exceptions.end_date or job_exceptions.end_date >= cur_date)):
                shift = job_exceptions.shift_id
                has_l = bool(enable_lunch and shift.has_lunch_break and not shift.is_night_shift and not is_saturday)
                l_start = (shift.lunch_start_time or 12.0) if has_l else 0.0
                l_dur = (shift.lunch_duration or 1.0) if has_l else 0.0
                l_end = l_start + l_dur
                result[cur_date] = {
                    'shift_start': shift.start_time, 'shift_end': shift.end_time,
                    'has_lunch': has_l, 'lunch_start': l_start, 'lunch_end': l_end,
                    'lunch_duration': l_dur, 'lunch_midpoint': (l_start + l_end) / 2.0 if has_l else 0.0,
                    'is_night_shift': bool(shift.is_night_shift), 'is_day_off': False,
                    'shift_name': shift.name, 'is_custom_exception': True,
                    'source_label': 'Job Position Exception'
                }
                cur_date += datetime.timedelta(days=1)
                continue

            # Check location exception
            if location_exceptions and (location_exceptions.start_date <= cur_date and (not location_exceptions.end_date or location_exceptions.end_date >= cur_date)):
                loc = location_exceptions
                shift = loc.shift_id if hasattr(loc, 'shift_id') and loc.shift_id else False
                is_night = shift.is_night_shift if shift else False
                has_l = bool(enable_lunch and (shift.has_lunch_break if shift else loc.has_lunch_break) and not is_night and not is_saturday)
                l_start = (shift.lunch_start_time or 12.0) if (shift and has_l) else (default_lunch_out if has_l else 0.0)
                l_dur = (shift.lunch_duration or default_lunch_dur) if (shift and has_l) else (default_lunch_dur if has_l else 0.0)
                l_end = l_start + l_dur
                s_start = shift.start_time if shift else loc.start_time
                s_end = shift.end_time if shift else loc.end_time
                result[cur_date] = {
                    'shift_start': s_start, 'shift_end': s_end,
                    'has_lunch': has_l, 'lunch_start': l_start, 'lunch_end': l_end,
                    'lunch_duration': l_dur, 'lunch_midpoint': (l_start + l_end) / 2.0 if has_l else 0.0,
                    'is_night_shift': bool(is_night), 'is_day_off': False,
                    'shift_name': (shift.name if shift else loc.name) or 'Location Shift',
                    'is_custom_exception': True,
                    'source_label': 'Location-Based Exception'
                }
                cur_date += datetime.timedelta(days=1)
                continue

            # Default global schedule
            if is_sunday:
                result[cur_date] = {
                    'shift_start': 0.0, 'shift_end': 0.0,
                    'has_lunch': False, 'lunch_start': 0.0, 'lunch_end': 0.0, 'lunch_duration': 0.0,
                    'lunch_midpoint': 0.0, 'is_night_shift': False, 'is_day_off': True,
                    'shift_name': 'Scheduled Day Off (Sunday)',
                    'is_custom_exception': False,
                    'source_label': 'Default Calendar'
                }
            else:
                s_end = default_exit_time
                is_sat_half = False
                if enable_saturday and is_saturday:
                    ou = self.default_operating_unit_id
                    unit_type = ou.work_unit_type if ou else False
                    if unit_type in ('head_office', 'head_offices', 'ho') or (unit_type in ('district', 'district_office', 'regional_office') and enable_district_saturday) or not ou:
                        s_end = saturday_exit_time
                        is_sat_half = True
                has_l = bool(enable_lunch and not is_saturday)
                l_start = default_lunch_out if has_l else 0.0
                l_dur = default_lunch_dur if has_l else 0.0
                l_end = l_start + l_dur
                result[cur_date] = {
                    'shift_start': default_morning_time, 'shift_end': s_end,
                    'has_lunch': has_l, 'lunch_start': l_start, 'lunch_end': l_end,
                    'lunch_duration': l_dur, 'lunch_midpoint': (l_start + l_end) / 2.0 if has_l else 0.0,
                    'is_night_shift': False, 'is_day_off': False,
                    'shift_name': 'Default Global Shift (Saturday Half Day)' if is_sat_half else 'Default Global Shift',
                    'is_custom_exception': False,
                    'source_label': 'Default Global Shift'
                }

            cur_date += datetime.timedelta(days=1)

        # Uniformly enrich all schedule dictionaries
        for dt_key, sched in result.items():
            s_start = sched.get('shift_start', 8.0)
            s_end = sched.get('shift_end', 17.0)
            l_start = sched.get('lunch_start', 12.0)
            l_dur = sched.get('lunch_duration', 1.0)
            has_l = sched.get('has_lunch', False)
            is_off = sched.get('is_day_off', False)

            start_str = _fmt(s_start)
            end_str = _fmt(s_end)
            l_start_str = _fmt(l_start)
            l_end_str = _fmt(l_start + l_dur)
            lunch_str = f"{l_start_str} - {l_end_str} ({l_dur:.1f}h)" if has_l else "No Lunch Break"

            sched['name'] = sched.get('shift_name') or 'Default Global Shift'
            sched['start_time'] = s_start
            sched['end_time'] = s_end
            sched['start_time_str'] = start_str
            sched['end_time_str'] = end_str
            sched['time_range'] = f"{start_str} - {end_str}" if not is_off else "No mandatory shift today"
            sched['lunch_out_time'] = l_start if has_l else 0.0
            sched['lunch_duration'] = l_dur if has_l else 0.0
            sched['has_lunch_break'] = has_l
            sched['lunch_time_str'] = lunch_str
            sched['is_custom_exception'] = sched.get('is_custom_exception', False)
            sched['source_label'] = sched.get('source_label') or sched['name']

        return result

    def _get_employee_shift_info(self, target_date=None):
        """ Alias mapping to _resolve_employee_full_schedule for unified shift data across models and controllers """
        res = self._resolve_employee_full_schedule(target_date=target_date)
        s_start = res.get('shift_start', 8.0)
        s_end = res.get('shift_end', 17.0)
        l_start = res.get('lunch_start', 12.0)
        l_dur = res.get('lunch_duration', 1.0)
        has_l = res.get('has_lunch', False)

        start_str = _fmt(s_start)
        end_str = _fmt(s_end)
        l_start_str = _fmt(l_start)
        l_end_str = _fmt(l_start + l_dur)
        lunch_str = f"{l_start_str} - {l_end_str} ({l_dur:.1f}h)" if has_l else "No Lunch Break"

        res['name'] = res.get('shift_name', 'Default Global Shift')
        res['start_time'] = s_start
        res['end_time'] = s_end
        res['start_time_str'] = start_str
        res['end_time_str'] = end_str
        res['time_range'] = f"{start_str} - {end_str}" if not res.get('is_day_off') else "No mandatory shift today"
        res['lunch_out_time'] = l_start if has_l else 0.0
        res['lunch_duration'] = l_dur if has_l else 0.0
        res['has_lunch_break'] = has_l
        res['lunch_time_str'] = lunch_str
        res['is_custom_exception'] = res.get('is_custom_exception', False)
        return res

    # ============================================================
    # SHIFT SELECTION HELPER
    # ============================================================
    def _select_applicable_shift(self, current_float, morning_start, exit_time, location_exceptions=None, job_position_exceptions=None, target_date=None, is_manager=False, **kwargs):
        if not target_date:
            target_date = fields.Date.context_today(self)

        checkin_buffer = self._get_param_float('hr_attendance.checkin_buffer', 0.50)
        enable_checkin_restriction = self.env['ir.config_parameter'].sudo().get_param(
            'hr_attendance.enable_checkin_restriction', 'True').lower() in ('true', '1')

        sched = self._resolve_employee_full_schedule(current_float=current_float, target_date=target_date)
        if sched.get('is_on_leave'):
            if not is_manager:
                raise UserError(_("Attendance cannot be recorded.\n\nYou have an approved Time Off today: %s.") % sched.get('leave_name', 'Time Off'))
        elif sched.get('is_day_off'):
            if not is_manager:
                raise UserError(_("Attendance cannot be recorded.\n\nYou have a scheduled Day Off today."))

        if sched['has_lunch']:
            morning_s = sched['shift_start']
            morning_e = sched['lunch_start']
            afternoon_s = sched['lunch_end']
            afternoon_e = sched['shift_end']
            lunch_gap = max(0.0, afternoon_s - morning_e)
            afternoon_buffer_start = max(morning_e, afternoon_s - min(0.25, lunch_gap / 2.0))

            if current_float >= afternoon_e:
                if enable_checkin_restriction and not is_manager:
                    raise UserError(_(
                        "Check-in is not allowed.\n\n"
                        "Your scheduled shift ended at %s."
                    ) % _fmt(afternoon_e))
                return afternoon_s, afternoon_e

            if current_float < morning_e:
                # Morning Session
                earliest_checkin = morning_s - checkin_buffer
                if current_float >= earliest_checkin or not enable_checkin_restriction or is_manager:
                    _logger.info("Using Morning Shift Session: %.2f - %.2f", morning_s, morning_e)
                    return morning_s, morning_e
                raise UserError(_(
                    "Check-in is not allowed yet.\n\n"
                    "You are too early for the Morning shift (%s - %s).\n"
                    "Check-in window opens at %s (Buffer: %d min)."
                ) % (_fmt(morning_s), _fmt(morning_e), _fmt(earliest_checkin), int(round(checkin_buffer * 60))))
            elif current_float < afternoon_buffer_start:
                # Lunch Break Window (e.g. 12:00 - 12:45)
                if enable_checkin_restriction and not is_manager:
                    raise UserError(_(
                        "Check-in is not allowed during lunch break (%s - %s).\n\n"
                        "Morning shift ended at %s. Afternoon check-in opens at %s."
                    ) % (_fmt(morning_e), _fmt(afternoon_s), _fmt(morning_e), _fmt(afternoon_buffer_start)))
                return afternoon_s, afternoon_e
            else:
                # Afternoon Session (e.g. 12:45 - 17:00)
                _logger.info("Using Afternoon Shift Session: %.2f - %.2f", afternoon_s, afternoon_e)
                return afternoon_s, afternoon_e
        else:
            # Single Continuous Shift (e.g. Saturday Half Day, regular continuous shift, location shift)
            if sched['is_night_shift']:
                earliest_checkin = sched['shift_start'] - checkin_buffer
                if current_float >= sched['shift_end'] and current_float < earliest_checkin:
                    if enable_checkin_restriction and not is_manager:
                        raise UserError(_(
                            "Check-in is not allowed.\n\n"
                            "Your scheduled shift ended at %s."
                        ) % _fmt(sched['shift_end']))
                if current_float >= earliest_checkin or current_float <= sched['shift_end'] or not enable_checkin_restriction or is_manager:
                    return sched['shift_start'], sched['shift_end']
            else:
                if current_float >= sched['shift_end']:
                    if enable_checkin_restriction and not is_manager:
                        raise UserError(_(
                            "Check-in is not allowed.\n\n"
                            "Your scheduled shift ended at %s."
                        ) % _fmt(sched['shift_end']))

                earliest_checkin = sched['shift_start'] - checkin_buffer
                if current_float >= earliest_checkin or not enable_checkin_restriction or is_manager:
                    return sched['shift_start'], sched['shift_end']

            raise UserError(_(
                "Check-in is not allowed yet.\n\n"
                "You are too early for your scheduled shift (%s - %s).\n"
                "Check-in window opens at %s (Buffer: %d min)."
            ) % (_fmt(sched['shift_start']), _fmt(sched['shift_end']), _fmt(earliest_checkin), int(round(checkin_buffer * 60))))

    # ============================================================
    # Check-in Evaluation Logic
    # ============================================================
    def _evaluate_checkin_status(self, current_float, shift_start, dead_time, predefined_late, is_manager=False, allow_late=False, is_afternoon=False):
        status = 'Normal'
        late_time = 0.0
        pre_defined_lateness_hours = 0.0
        
        enable_checkin_grace = self.env['ir.config_parameter'].sudo().get_param('hr_attendance.enable_checkin_grace', 'True').lower() in ('true', '1')
        checkin_grace_period = self._get_param_float('hr_attendance.checkin_grace_period', 0.25)
        
        # Rule: Afternoon check-in has ZERO grace time (any arrival past shift start is late)
        if is_afternoon or not enable_checkin_grace:
            grace = 0.0
        else:
            grace = checkin_grace_period

        normal_cutoff = shift_start + grace
        late_cutoff = shift_start + grace + dead_time

        _logger.debug(
            "EVALUATING CHECKIN | Employee: %s | Current: %.4f | ShiftStart: %.4f | Grace: %.4f | DeadTime: %.4f | NormalCutoff: %.4f | LateCutoff: %.4f",
            self.name, current_float, shift_start, grace, dead_time, normal_cutoff, late_cutoff
        )

        if predefined_late and current_float <= predefined_late.end_time:
            status = 'Pre-Defined Lateness'
            pre_defined_lateness_hours = round(current_float - shift_start, 4)
        elif current_float <= normal_cutoff:
            status = 'Normal'
            late_time = 0.0
        elif current_float <= late_cutoff:
            status = 'Late'
            late_time = max(0.0, round(current_float - shift_start, 4))
        else:
            # Past dead-time cutoff
            enable_checkin_restriction = self.env['ir.config_parameter'].sudo().get_param(
                'hr_attendance.enable_checkin_restriction', 'True').lower() in ('true', '1')
            if enable_checkin_restriction and not is_manager and not allow_late:
                raise UserError(_(
                    "Check-in is not allowed.\n\n"
                    "Late arrival cutoff was %s (Dead time: %d min).\n"
                    "Please contact your manager for manual attendance registration."
                ) % (_fmt(late_cutoff), int(round(dead_time * 60))))
            status = 'Very Late'
            late_time = max(0.0, round(current_float - shift_start, 4))
            _logger.info("Check-in marked Very Late for %s: Current (%.4f) > Cutoff (%.4f)", self.name, current_float, late_cutoff)

        return status, late_time, 0.0, pre_defined_lateness_hours

    # ============================================================
    # Helpers
    # ============================================================
    def _get_local_time_and_float(self):
        tz_name = self.user_id.tz or self.env.user.tz or 'Africa/Addis_Ababa'
        try:
            local_tz = pytz.timezone(tz_name)
        except Exception:
            local_tz = pytz.timezone('Africa/Addis_Ababa')
        utc_dt = self.env.context.get('mock_now_utc') or fields.Datetime.now()
        local_dt = pytz.utc.localize(utc_dt).astimezone(local_tz)
        current_float = local_dt.hour + (local_dt.minute / 60.0) + (local_dt.second / 3600.0)
        return local_dt, current_float, local_dt.date()

    def _load_time_parameters(self):
        cfg = self._get_attendance_config_params()
        return cfg['morning_time'], cfg['exit_time'], cfg['dead_time']

    def _get_predefined_attendance(self, today_date, current_float):
        predefined_late = self.env['attendance.preapproval'].search([
            ('employee_id', '=', self.id),
            ('date', '=', today_date),
            ('exception_type', '=', 'predefined_late'),
            ('state', '=', 'approved'),
        ], limit=1)

        predefined_early_exit = self.env['attendance.preapproval'].search([
            ('employee_id', '=', self.id),
            ('date', '=', today_date),
            ('exception_type', '=', 'predefined_early_exit'),
            ('state', '=', 'approved'),
        ], limit=1)

        return predefined_late, predefined_early_exit

    def _get_param_float(self, key, default):
        val = self.env['ir.config_parameter'].sudo().get_param(key)
        try:
            return float(val) if val is not None else default
        except (ValueError, TypeError):
            return default

    def _is_lunch_break_enabled(self):
        val = self.env['ir.config_parameter'].sudo().get_param('hr_attendance.enable_lunch_break', 'False')
        return val.lower() in ('true', '1')

    def _get_min_work_hour(self):
        val = self.env['ir.config_parameter'].sudo().get_param('hr_attendance.min_work_hour', '4.0')
        try:
            return float(val)
        except (ValueError, TypeError):
            return 4.0

    def _float_to_utc_datetime(self, float_hour, local_dt, is_next_day=False):
        tz_name = self.user_id.tz or self.env.user.tz or 'Africa/Addis_Ababa'
        try:
            local_tz = pytz.timezone(tz_name)
        except Exception:
            local_tz = pytz.timezone('Africa/Addis_Ababa')
        total_seconds = int(round(float(float_hour) * 3600.0))
        days = total_seconds // 86400
        rem_seconds = total_seconds % 86400
        h = rem_seconds // 3600
        m = (rem_seconds % 3600) // 60
        s = rem_seconds % 60
        local_target = local_dt.replace(hour=h, minute=m, second=s, microsecond=0)
        extra_days = (1 if is_next_day else 0) + days
        if extra_days:
            local_target += datetime.timedelta(days=extra_days)
        utc_target = local_tz.localize(local_target.replace(tzinfo=None)).astimezone(pytz.utc)
        return utc_target.replace(tzinfo=None)

    # ============================================================
    # MAIN ATTENDANCE ACTION (CHECK IN / CHECK OUT / 1-CLICK LUNCH)
    # ============================================================
    def _attendance_action_change(self, geo_information=None):
        """ Universal Check in / Check out action wrapper for Bunna Bank rules. """
        self.ensure_one()
        _logger.info("=== ATTENDANCE ACTION TRIGGERED FOR %s ===", self.name)
        # Acquire transaction-scoped PostgreSQL advisory lock on employee ID to prevent double check-in race conditions
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s, %s);", (abs(hash('hr_attendance')) % 2147483647, self.id))

        # ----------------------------------------------------
        # ELIGIBILITY & ACTIVE EMPLOYMENT VALIDATIONS
        # ----------------------------------------------------
        if not self.active or (hasattr(self, 'active_employee') and not self.active_employee):
            raise UserError(_("Attendance cannot be recorded.\n\nEmployee %s is inactive or archived.") % self.name)

        if hasattr(self, 'is_suspended') and self.is_suspended:
            raise UserError(_("Attendance cannot be recorded.\n\nEmployee %s is currently under active disciplinary suspension.") % self.name)

        if hasattr(self, 'state') and self.state in ('terminated', 'resigned', 'cancel', 'draft', 'refuse'):
            raise UserError(_("Attendance cannot be recorded.\n\nEmployee %s does not have an active employment status (Current status: %s).") % (self.name, self.state))

        local_dt, current_float, today_date = self._get_local_time_and_float()
        morning_start, exit_time, dead_time = self._load_time_parameters()
        predefined_late, predefined_early_exit = self._get_predefined_attendance(today_date, current_float)
        min_work_hour = self._get_min_work_hour()

        utc_naive_dt = self.env.context.get('mock_now_utc') or fields.Datetime.now()
        sched = self._resolve_employee_full_schedule(current_float=current_float, target_date=today_date)

        open_attendance = self.env['hr.attendance'].search([
            ('employee_id', '=', self.id), ('check_out', '=', False)
        ], limit=1)

        enable_checkin_restriction = self.env['ir.config_parameter'].sudo().get_param(
            'hr_attendance.enable_checkin_restriction', 'True').lower() in ('true', '1')
        enable_checkout_restriction = self.env['ir.config_parameter'].sudo().get_param(
            'hr_attendance.enable_checkout_restriction', 'True').lower() in ('true', '1')

        acting_user = self.env.user
        # Strict equality: all self-service attendance actions enforce standard shift regulations for all users (including Admins and Managers).
        # Administrative override is strictly limited to backend manual management tools via explicit context flag.
        is_manager = bool(self.env.context.get('bypass_attendance_restrictions', False))
        _logger.info("ATTENDANCE_ACTION_CHANGE: employee=%s, user=%s (uid=%s), is_manager=%s", self.name, acting_user.login, acting_user.id, is_manager)

        self._last_attendance_action = False

        # ----------------------------------------------------
        # SCENARIO 1: EMPLOYEE HAS AN OPEN ATTENDANCE RECORD
        # ----------------------------------------------------
        if open_attendance:
            attendance = open_attendance
            open_att_local = fields.Datetime.context_timestamp(self, attendance.check_in) if attendance.check_in else local_dt
            open_att_date = open_att_local.date()

            # Determine if this open attendance belongs to an already-ended previous shift (JIT Auto-Heal)
            is_prev_day_session = (open_att_date < today_date)
            if is_prev_day_session:
                old_s_end = attendance.shift_end_float or 17.0
                old_s_start = attendance.shift_start_float or 8.0
                is_old_night = (old_s_end <= old_s_start)
                old_shift_end_utc = self._float_to_utc_datetime(old_s_end, open_att_local, is_next_day=is_old_night)

                actual_out_utc = old_shift_end_utc if (attendance.check_in and attendance.check_in < old_shift_end_utc) else (attendance.check_in + datetime.timedelta(hours=8))
                gross_dur = max(0.0, (actual_out_utc - attendance.check_in).total_seconds() / 3600.0) if attendance.check_in else 8.0

                attendance.with_context(tracking_disable=True, mail_notrack=True).write({
                    'check_out': actual_out_utc,
                    'check_out_status': 'Force Checkout',
                    'is_force_checkout': True,
                    'worked_hours': round(gross_dur, 2),
                })
                attendance.flush_recordset()
                _logger.info("JIT Auto-Heal: Force-closed expired session %s for %s", attendance.id, self.name)
                try:
                    profile = self.env['hr.employee.discipline.profile'].sudo().search([('employee_id', '=', self.id)], limit=1)
                    if profile:
                        profile.sudo().write({'force_checkout_count_rolling': profile.force_checkout_count_rolling + 1})
                except Exception as e:
                    _logger.warning("Could not increment discipline profile on JIT auto-heal: %s", e)

                open_attendance = False
                self._last_attendance_action = 'jit_auto_heal_checkin'

        if open_attendance:
            attendance = open_attendance

            def _att_in_hour(a):
                if not a.check_in:
                    return 0.0
                ts = fields.Datetime.context_timestamp(self, a.check_in)
                return ts.hour + ts.minute / 60.0 + ts.second / 3600.0

            # Check if this open attendance is a Morning Session of a lunch-split shift
            is_morning_session = sched['has_lunch'] and (
                (attendance.shift_end_float and attendance.shift_end_float <= (sched['lunch_start'] + 0.1)) or
                (attendance.check_in and _att_in_hour(attendance) < (sched['lunch_start'] - 0.01))
            )
            if is_morning_session:
                lunch_start = sched['lunch_start']
                afternoon_start = sched['lunch_end']
                lunch_gap = max(0.0, afternoon_start - lunch_start)
                afternoon_buffer_start = max(lunch_start, afternoon_start - min(0.25, lunch_gap / 2.0))
                afternoon_late_cutoff = afternoon_start + dead_time

                if current_float < (lunch_start - 0.05):
                    # Trying to check out BEFORE lunch starts (e.g. 11:30 AM before 12:00 PM)
                    if enable_checkout_restriction and not is_manager and not predefined_early_exit:
                        raise UserError(_(
                            "Check-out is not allowed yet.\n\n"
                            "You cannot check out before your scheduled lunch time (%s)."
                        ) % _fmt(lunch_start))
                    else:
                        # Checkout allowed early at exact system time
                        attendance.write({
                            'check_out': utc_naive_dt,
                            'check_out_status': 'Early Check-out',
                        })
                        self._last_attendance_action = 'check_out'
                        _logger.info("Early Morning Lunch Checkout for %s at %.2f", self.name, current_float)
                        return attendance

                elif current_float < afternoon_buffer_start:
                    # NORMAL LUNCH CHECKOUT (e.g. 12:00 PM - 12:44 PM)
                    lunch_checkout_utc = self._float_to_utc_datetime(lunch_start, local_dt)
                    if attendance.check_in and lunch_checkout_utc < attendance.check_in:
                        lunch_checkout_utc = attendance.check_in
                    attendance.write({
                        'check_out': lunch_checkout_utc,
                        'check_out_status': 'Normal',
                    })
                    self._last_attendance_action = 'check_out'
                    _logger.info("Normal Morning Lunch Checkout for %s at %.2f (Check-out stamped: %s)", self.name, current_float, lunch_start)
                    return attendance

                else:
                    # 1-CLICK AFTERNOON TRANSITION (e.g. 12:45 PM onwards)
                    # Employee forgot morning lunch checkout and clicks for the first time during afternoon entry!
                    lunch_checkout_utc = self._float_to_utc_datetime(lunch_start, local_dt)
                    if attendance.check_in and lunch_checkout_utc < attendance.check_in:
                        lunch_checkout_utc = attendance.check_in
                    attendance.write({
                        'check_out': lunch_checkout_utc,
                        'check_out_status': 'Force Checkout',
                        'is_force_checkout': True,
                    })
                    attendance.flush_recordset()
                    # Check if afternoon check-in window is still open or allowed
                    # If it is past dead-time cutoff and not allowed to check in, treat this click as a day-end checkout!
                    has_predefined = bool(predefined_late and current_float <= predefined_late.end_time)
                    is_past_deadtime = (current_float > afternoon_late_cutoff)

                    if is_past_deadtime and enable_checkin_restriction and not is_manager and not has_predefined:
                        self._last_attendance_action = 'check_out'
                        _logger.info("Morning Session Force-Closed at end of day for %s at %.2f (Afternoon check-in skipped as window is closed)", self.name, current_float)
                        return attendance

                    self._last_attendance_action = 'dual_transition'
                    _logger.info("1-Click Force Checkout Morning Session for %s at %.2f + Afternoon Check-In", self.name, current_float)

                    fast_att_env = self.env['hr.attendance'].with_context(
                        tracking_disable=True,
                        mail_create_nosubscribe=True,
                        mail_create_nolog=True,
                        mail_notrack=True,
                        skip_duplicate_check=True,
                    )

                    # Evaluate afternoon check-in status using standard unified engine (enforces dead-time, preapprovals, and grace)
                    status, late_hrs, ot, pre_late = self._evaluate_checkin_status(
                        current_float, afternoon_start, dead_time, predefined_late,
                        is_manager=is_manager, allow_late=not enable_checkin_restriction, is_afternoon=True
                    )

                    checkin_dt = utc_naive_dt if status in ('Late', 'Very Late', 'Pre-Defined Lateness') else self._float_to_utc_datetime(afternoon_start, local_dt)
                    in_mode_val = 'predefined' if pre_late > 0 else self.env.context.get('attendance_mode', 'kiosk')

                    vals = {
                        'employee_id': self.id,
                        'check_in': checkin_dt,
                        'actual_check_in': utc_naive_dt,
                        'in_mode': in_mode_val,
                        'check_in_status': status,
                        'late_time_hour': late_hrs,
                        'pre_defined_lateness': pre_late,
                        'shift_start_float': afternoon_start,
                        'shift_end_float': sched['shift_end'],
                    }
                    if predefined_late and pre_late > 0:
                        vals['pre_defined_attendance_id'] = predefined_late.id
                    if geo_information:
                        vals.update({'in_%s' % key: geo_information[key] for key in geo_information})
                    new_att = fast_att_env.create(vals)
                    new_att._enqueue_attendance_side_effects()
                    return new_att

            # Regular Shift-End Check-Out (Afternoon or Full-Day / Saturday)
            # Use dynamic schedule shift_end to immediately reflect updated settings or Saturday half-day
            target_shift_end = sched['shift_end'] if (not sched.get('has_lunch') or not attendance.shift_end_float) else attendance.shift_end_float
            target_shift_end_utc = self._float_to_utc_datetime(target_shift_end, local_dt)

            if enable_checkout_restriction and not is_manager and not predefined_early_exit and current_float < (target_shift_end - 0.05):
                raise UserError(_(
                    "Check-out is not allowed yet.\n\n"
                    "Your scheduled shift ends at %s.\n"
                    "You cannot check out before shift end."
                ) % _fmt(target_shift_end))

            out_status = 'Normal'
            if current_float < (target_shift_end - 0.05):
                out_status = 'Early Check-out'

            attendance.with_context(tracking_disable=True, mail_notrack=True).write({
                'check_out': utc_naive_dt,
                'check_out_status': out_status,
            })
            self._last_attendance_action = 'check_out'
            _logger.info("Check-Out recorded for %s at %.2f (Status: %s)", self.name, current_float, out_status)
            return attendance

        # ----------------------------------------------------
        # SCENARIO 2: EMPLOYEE IS CHECKED OUT (CHECKING IN)
        # ----------------------------------------------------
        else:
            shift_start, shift_end = self._select_applicable_shift(
                current_float, morning_start, exit_time, target_date=today_date, is_manager=is_manager
            )
            is_night = (shift_end <= shift_start)
            shift_start_utc = self._float_to_utc_datetime(shift_start, local_dt)
            lunch_start_val = sched.get('lunch_start', 12.0)
            lunch_end_val = sched.get('lunch_end', 13.0)
            lunch_gap = max(0.0, lunch_end_val - lunch_start_val)
            afternoon_buf_start = max(lunch_start_val, lunch_end_val - min(0.25, lunch_gap / 2.0))
            is_afternoon_checkin = bool(sched['has_lunch'] and current_float >= afternoon_buf_start)

            status, late_time, ot, pre_late = self._evaluate_checkin_status(
                current_float, shift_start, dead_time, predefined_late,
                is_manager=is_manager, allow_late=not enable_checkin_restriction, is_afternoon=is_afternoon_checkin
            )
            checkin_dt = utc_naive_dt if status in ('Late', 'Very Late', 'Pre-Defined Lateness') else shift_start_utc

            in_mode_val = 'predefined' if pre_late > 0 else self.env.context.get('attendance_mode', 'kiosk')
            vals = {
                'employee_id': self.id,
                'check_in': checkin_dt,
                'actual_check_in': utc_naive_dt,
                'in_mode': in_mode_val,
                'out_mode': False,
                'check_in_status': status,
                'late_time_hour': late_time,
                'pre_defined_lateness': pre_late,
                'shift_start_float': shift_start,
                'shift_end_float': shift_end,
            }

            if geo_information:
                vals.update({'in_%s' % key: geo_information[key] for key in geo_information})
            _logger.info("Creating Check-in for %s: %s", self.name, vals)
            fast_att_env = self.env['hr.attendance'].with_context(
                tracking_disable=True,
                mail_create_nosubscribe=True,
                mail_create_nolog=True,
                mail_notrack=True,
                skip_duplicate_check=True,
            )
            attendance = fast_att_env.create(vals)
            attendance._enqueue_attendance_side_effects()
            if not getattr(self, '_last_attendance_action', None):
                self._last_attendance_action = 'check_in'
            return attendance
