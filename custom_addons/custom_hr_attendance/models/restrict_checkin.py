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


def _fmt_12h(f):
    """Helper: format float 8.5 -> '08:30 AM', 13.25 -> '01:15 PM'"""
    if f is None or f is False:
        return "--:--"
    h = int(f)
    m = int(round((f - h) * 60))
    if m >= 60:
        h += 1
        m = 0
    h12 = h % 12 or 12
    period = "AM" if h < 12 else "PM"
    return f"{h12:02d}:{m:02d} {period}"


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
        checkin_grace = float(params.get_param('hr_attendance.checkin_grace_period', params.get_param('hr_attendance.grace_time', 0.25)))
        return {
            'morning_time': float(params.get_param('hr_attendance.morning_time', 8.0)),
            'exit_time': float(params.get_param('hr_attendance.exit_time', 17.0)),
            'enable_saturday_halfday': params.get_param('hr_attendance.enable_saturday_halfday', 'True').lower() in ('true', '1'),
            'saturday_halfday_district': params.get_param('hr_attendance.saturday_halfday_district', 'True').lower() in ('true', '1'),
            'saturday_exit_time': float(params.get_param('hr_attendance.saturday_exit_time', 12.0)),
            'enable_lunch_break': params.get_param('hr_attendance.enable_lunch_break', 'False').lower() in ('true', '1'),
            'lunch_out_time': float(params.get_param('hr_attendance.lunch_out_time', 12.0)),
            'lunch_duration': float(params.get_param('hr_attendance.lunch_duration', 1.0)),
            'grace_time': checkin_grace,
            'checkin_grace_period': checkin_grace,
            'dead_time': float(params.get_param('hr_attendance.dead_time', 0.333333)),
            'min_work_hour': float(params.get_param('hr_attendance.min_work_hour', 4.0)),
            'enable_checkin_gate': params.get_param('hr_attendance.enable_checkin_gate', 'False').lower() in ('true', '1'),
            'enable_checkin_restriction': params.get_param('hr_attendance.enable_checkin_restriction', 'True').lower() in ('true', '1'),
            'enable_checkout_restriction': params.get_param('hr_attendance.enable_checkout_restriction', 'True').lower() in ('true', '1'),
        }

    # ============================================================
    # PUBLIC HOLIDAY & UNIVERSAL SCHEDULE RESOLVER
    # ============================================================
    def _to_local_date(self, dt):
        """Converts UTC datetime or date to local calendar date based on user/calendar/company timezone."""
        if not dt:
            return False
        if isinstance(dt, datetime.date) and not isinstance(dt, datetime.datetime):
            return dt
        tz_name = (
            self.env.context.get('tz') or
            self.env.user.tz or
            (self.resource_calendar_id and self.resource_calendar_id.tz) or
            (self.company_id and self.company_id.resource_calendar_id and self.company_id.resource_calendar_id.tz) or
            'Africa/Addis_Ababa'
        )
        try:
            user_tz = pytz.timezone(tz_name)
            raw_dt = fields.Datetime.to_datetime(dt)
            if not raw_dt.tzinfo:
                raw_dt = pytz.utc.localize(raw_dt)
            return raw_dt.astimezone(user_tz).date()
        except Exception:
            return fields.Datetime.to_datetime(dt).date()

    def _get_employee_public_holiday(self, target_date=None):
        """
        Returns the matching resource.calendar.leaves record for this employee on target_date,
        or False if target_date is not a public holiday.
        Checks both dated public holidays and recurring day_of_week holidays, honoring calendar and work unit type.
        """
        self.ensure_one()
        if not target_date:
            target_date = fields.Date.context_today(self)

        target_dt = fields.Date.to_date(target_date)
        weekday_str = str(target_dt.weekday())

        cal_ids = [False]
        if self.resource_calendar_id:
            cal_ids.append(self.resource_calendar_id.id)
        if self.company_id and self.company_id.resource_calendar_id:
            cal_ids.append(self.company_id.resource_calendar_id.id)

        emp_ou = self.default_operating_unit_id
        emp_wut = emp_ou.work_unit_type if emp_ou else False
        wut_filter = [False]
        if emp_wut:
            normalized_wut = 'head_office' if emp_wut in ('head_office', 'head_offices', 'ho') else ('branch' if emp_wut in ('branch', 'area_office', 'district_office') else emp_wut)
            wut_filter.extend([emp_wut, normalized_wut])

        res_ids = [False]
        if self.resource_id:
            res_ids.append(self.resource_id.id)

        if 'resource.calendar.leaves' not in self.env:
            return False

        domain = [
            ('resource_id', 'in', res_ids),
            ('calendar_id', 'in', list(set(cal_ids))),
        ]
        if 'work_unit_type' in self.env['resource.calendar.leaves']._fields:
            domain.append(('work_unit_type', 'in', list(set(wut_filter))))

        pub_holidays = self.env['resource.calendar.leaves'].sudo().search(domain)
        for h in pub_holidays:
            dow = getattr(h, 'day_of_week', False)
            if dow and str(dow) == weekday_str:
                return h
            if h.date_from and h.date_to:
                p_start = self._to_local_date(h.date_from)
                p_end = self._to_local_date(h.date_to)
                if p_start and p_end and p_start <= target_dt <= p_end:
                    return h

        return False

    def _is_leave_matching_date(self, l, target_date):
        """
        Determines if an hr.leave record applies to target_date.
        Prioritizes pure Date fields (immune to UTC boundary shifts).
        Defensively prevents unlocalized 23:59:59 UTC dates from rolling into the next local day.
        """
        # 1. Prioritize clean Date fields (leave_start_date / leave_end_date, or request_date_from / request_date_to)
        d_from = getattr(l, 'leave_start_date', False) or getattr(l, 'request_date_from', False)
        d_to = getattr(l, 'leave_end_date', False) or getattr(l, 'request_date_to', False) or d_from
        if d_from and d_to:
            return d_from <= target_date <= d_to

        # 2. Datetime fields fallback
        if l.date_from and l.date_to:
            start_local = self._to_local_date(l.date_from)
            end_local = l.date_to.date() if (l.date_to.hour >= 20) else self._to_local_date(l.date_to)
            return start_local <= target_date <= end_local
        return False

    def _split_shift_for_half_day_leave(self, base_shift, half_period, l_name, default_lunch_out=12.0, default_lunch_dur=1.0, enable_lunch=False):
        """
        Dynamically calculates the working slot of a shift when a half-day leave (AM or PM) is applied.
        Works identically whether enable_lunch is True or False, and respects roster, location, or Saturday shifts.
        """
        b_start = base_shift.get('shift_start', 8.0)
        b_end = base_shift.get('shift_end', 17.0)
        is_night = base_shift.get('is_night_shift', False)
        raw_span = (b_end + 24.0 - b_start) if is_night or b_end <= b_start else (b_end - b_start)

        if base_shift.get('has_lunch') and base_shift.get('lunch_start'):
            split_out = base_shift['lunch_start']
            split_in = base_shift['lunch_end']
        elif raw_span <= 5.0:
            mid = round(b_start + (raw_span / 2.0), 2)
            if mid >= 24.0:
                mid -= 24.0
            split_out = mid
            split_in = mid
        else:
            split_out = default_lunch_out or 12.0
            if split_out <= b_start or split_out >= b_end:
                mid = round(b_start + (raw_span / 2.0), 2)
                split_out = mid
                split_in = mid
            else:
                lunch_dur = default_lunch_dur if enable_lunch else 1.0
                split_in = min(b_end, split_out + lunch_dur)

        norm_period = (half_period or 'am').lower()
        if norm_period in ('am', 'morning'):
            # Employee is on leave during Morning; works Afternoon slot
            return {
                'shift_start': split_in,
                'shift_end': b_end,
                'has_lunch': False,
                'lunch_start': 0.0,
                'lunch_end': 0.0,
                'lunch_duration': 0.0,
                'lunch_midpoint': 0.0,
                'is_night_shift': is_night,
                'is_day_off': False,
                'is_on_leave': False,
                'is_half_day_leave': True,
                'half_day_period': 'am',
                'leave_name': l_name,
                'shift_name': f"Afternoon Shift (Morning on {l_name})",
                'is_custom_exception': base_shift.get('is_custom_exception', False),
                'source_label': base_shift.get('source_label', 'Shift Schedule'),
            }
        else:
            # Employee works Morning slot; on leave during Afternoon
            return {
                'shift_start': b_start,
                'shift_end': split_out,
                'has_lunch': False,
                'lunch_start': 0.0,
                'lunch_end': 0.0,
                'lunch_duration': 0.0,
                'lunch_midpoint': 0.0,
                'is_night_shift': False,
                'is_day_off': False,
                'is_on_leave': False,
                'is_half_day_leave': True,
                'half_day_period': 'pm',
                'leave_name': l_name,
                'shift_name': f"Morning Shift (Afternoon on {l_name})",
                'is_custom_exception': base_shift.get('is_custom_exception', False),
                'source_label': base_shift.get('source_label', 'Shift Schedule'),
            }

    def _resolve_employee_base_shift(self, target_date=None, cfg=None):
        """
        Resolves the employee's underlying operational working shift for target_date
        (checking 24/7 Roster Exception -> Job Position Exception -> Location Exception -> Saturday / Default Global Shift).
        Ignores leave and public holiday overrides to establish the baseline working schedule.
        """
        if not target_date:
            target_date = fields.Date.context_today(self)
        target_date = fields.Date.to_date(target_date)

        if not cfg:
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

        # 1. 24/7 Roster Exception
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
                    has_l = bool(enable_lunch and shift.has_lunch_break and not shift.is_night_shift)
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

        # 3. Sunday Day Off (Default Weekly Rest)
        # Location Exceptions, Job Position Exceptions, and Standard Shifts observe Sunday as Scheduled Day Off.
        # ONLY 24/7 Rotational Rosters override Sundays.
        if target_date and target_date.weekday() == 6:
            return {
                'shift_start': 0.0, 'shift_end': 0.0,
                'has_lunch': False, 'lunch_start': 0.0, 'lunch_end': 0.0, 'lunch_duration': 0.0,
                'lunch_midpoint': 0.0, 'is_night_shift': False, 'is_day_off': True,
                'shift_name': 'Scheduled Day Off (Sunday)',
                'is_custom_exception': False,
                'source_label': 'Default Calendar'
            }

        # 4. Job Position Exception (Static)
        job_exceptions = self.env['job.position.exception'].sudo().search([
            ('employee_id', '=', self.id), ('status', '=', 'active'),
            ('active', '=', True),
            ('start_date', '<=', target_date),
            '|', ('end_date', '=', False), ('end_date', '>=', target_date)
        ], order='start_date desc, id desc', limit=1)

        if job_exceptions and job_exceptions.shift_id:
            shift = job_exceptions.shift_id
            has_l = bool(enable_lunch and shift.has_lunch_break and not shift.is_night_shift)
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

        # 5. Location-based shifts
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
            has_l = bool(enable_lunch and (shift.has_lunch_break if shift else loc.has_lunch_break) and not is_night)
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

        # 6. Default global schedule (Monday - Saturday)

        s_end = default_exit_time
        is_sat_half = False
        if enable_saturday and is_saturday:
            ou = self.default_operating_unit_id
            unit_type = ou.work_unit_type if ou else False
            if unit_type in ('head_office', 'head_offices', 'ho') or (unit_type in ('district', 'district_office', 'regional_office') and enable_district_saturday) or not ou:
                s_end = saturday_exit_time
                is_sat_half = True

        has_l = bool(enable_lunch and not is_sat_half)
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
        target_date = fields.Date.to_date(target_date)

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
        leaves = self.env['hr.leave'].sudo().search([
            ('employee_id', '=', self.id),
            ('state', '=', 'validate'),
            '|',
                '&', ('request_date_from', '<=', target_date),
                     ('request_date_to', '>=', target_date),
                '&', ('date_from', '<=', datetime.datetime.combine(target_date + datetime.timedelta(days=1), datetime.time.max)),
                     ('date_to', '>=', datetime.datetime.combine(target_date - datetime.timedelta(days=1), datetime.time.min)),
        ])
        matching_leave = leaves.filtered(lambda l: self._is_leave_matching_date(l, target_date))
        leave = matching_leave[0] if matching_leave else False

        if leave:
            l_name = leave.holiday_status_id.name or _('Time Off')
            if isinstance(l_name, dict):
                l_name = l_name.get('en_US', list(l_name.values())[0]) if l_name else _('Time Off')
            is_start_half = bool(getattr(leave, 'starting_half_day', False) and (getattr(leave, 'leave_start_date', False) or getattr(leave, 'request_date_from', False)) == target_date)
            is_end_half = bool(getattr(leave, 'ending_half_day', False) and (getattr(leave, 'leave_end_date', False) or getattr(leave, 'request_date_to', False)) == target_date)
            is_half = bool(getattr(leave, 'request_unit_half', False) or getattr(leave, 'half_day', False) or (getattr(leave, 'number_of_days', 1.0) == 0.5) or is_start_half or is_end_half)
            if getattr(leave, 'is_continuous_half_day', False):
                half_period = getattr(leave, 'continuous_half_day_period', 'am')
            elif getattr(leave, 'single_half_day_period', False):
                half_period = leave.single_half_day_period
            elif is_start_half:
                half_period = 'pm'
            elif is_end_half:
                half_period = 'am'
            else:
                half_period = getattr(leave, 'request_date_from_period', 'am')
            if is_half:
                base_shift = self._resolve_employee_base_shift(target_date=target_date, cfg=cfg)
                return self._split_shift_for_half_day_leave(
                    base_shift, half_period, l_name,
                    default_lunch_out=default_lunch_out,
                    default_lunch_dur=default_lunch_dur,
                    enable_lunch=enable_lunch
                )
            else:
                return {
                    'shift_start': 0.0, 'shift_end': 0.0,
                    'has_lunch': False, 'lunch_start': 0.0, 'lunch_end': 0.0, 'lunch_duration': 0.0,
                    'lunch_midpoint': 0.0, 'is_night_shift': False, 'is_day_off': True,
                    'is_on_leave': True, 'leave_name': l_name,
                    'shift_name': f"Approved Time Off ({l_name})"
                }

        # 1. 24/7 Roster Exception (Date-Based) - Continuous Operations: Public Holidays do NOT cancel roster shifts
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
                    has_l = bool(enable_lunch and shift.has_lunch_break and not shift.is_night_shift)
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

        # 2. Public Holiday (resource.calendar.leaves)
        # Branches (Location Exceptions), Job Position Exceptions, and Standard Shifts ARE closed / day off on Public Holidays
        pub_holiday = self._get_employee_public_holiday(target_date=target_date)
        if pub_holiday:
            h_name = pub_holiday.name or _('Public Holiday')
            if isinstance(h_name, dict):
                h_name = h_name.get('en_US', list(h_name.values())[0]) if h_name else _('Public Holiday')
            h_weight = getattr(pub_holiday, 'holiday_day_weight', 1.0) or 1.0
            if h_weight == 0.5:
                return {
                    'shift_start': 13.0, 'shift_end': default_exit_time,
                    'has_lunch': False, 'lunch_start': 0.0, 'lunch_end': 0.0, 'lunch_duration': 0.0,
                    'lunch_midpoint': 0.0, 'is_night_shift': False, 'is_day_off': False,
                    'is_on_leave': False, 'is_half_day_leave': True, 'is_public_holiday': True,
                    'leave_name': h_name, 'shift_name': f"Afternoon Shift (Morning Public Holiday: {h_name})",
                    'source_label': 'Public Holiday',
                }
            else:
                return {
                    'shift_start': 0.0, 'shift_end': 0.0,
                    'has_lunch': False, 'lunch_start': 0.0, 'lunch_end': 0.0, 'lunch_duration': 0.0,
                    'lunch_midpoint': 0.0, 'is_night_shift': False, 'is_day_off': True,
                    'is_on_leave': True, 'is_public_holiday': True,
                    'leave_name': h_name, 'shift_name': f"Public Holiday ({h_name})",
                    'source_label': 'Public Holiday',
                }

        # 3. Sunday Day Off (Default Weekly Rest)
        # Location Exceptions, Job Position Exceptions, and Standard Shifts observe Sunday as Scheduled Day Off.
        # ONLY 24/7 Rotational Rosters override Sundays.
        if target_date and target_date.weekday() == 6:
            return {
                'shift_start': 0.0, 'shift_end': 0.0,
                'has_lunch': False, 'lunch_start': 0.0, 'lunch_end': 0.0, 'lunch_duration': 0.0,
                'lunch_midpoint': 0.0, 'is_night_shift': False, 'is_day_off': True,
                'shift_name': 'Scheduled Day Off (Sunday)',
                'is_custom_exception': False,
                'source_label': 'Default Calendar'
            }

        # 4. Job Position Exception (Static)
        job_exceptions = self.env['job.position.exception'].sudo().search([
            ('employee_id', '=', self.id), ('status', '=', 'active'),
            ('active', '=', True),
            ('start_date', '<=', target_date),
            '|', ('end_date', '=', False), ('end_date', '>=', target_date)
        ], order='start_date desc, id desc', limit=1)

        if job_exceptions and job_exceptions.shift_id:
            shift = job_exceptions.shift_id
            has_l = bool(enable_lunch and shift.has_lunch_break and not shift.is_night_shift)
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

        # 5. Location-based shifts
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
            has_l = bool(enable_lunch and (shift.has_lunch_break if shift else loc.has_lunch_break) and not is_night)
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

        # 6. Default global schedule (Monday - Saturday)

        s_end = default_exit_time
        is_sat_half = False
        if enable_saturday and is_saturday:
            ou = self.default_operating_unit_id
            unit_type = ou.work_unit_type if ou else False
            if unit_type in ('head_office', 'head_offices', 'ho') or (unit_type in ('district', 'district_office', 'regional_office') and enable_district_saturday) or not ou:
                s_end = saturday_exit_time
                is_sat_half = True

        has_l = bool(enable_lunch and not is_sat_half)
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

        # 1b. Batch fetch public holidays (resource.calendar.leaves)
        pub_holidays = self.env['resource.calendar.leaves'].browse()
        if 'resource.calendar.leaves' in self.env:
            cal_ids = [False]
            if self.resource_calendar_id:
                cal_ids.append(self.resource_calendar_id.id)
            if self.company_id and self.company_id.resource_calendar_id:
                cal_ids.append(self.company_id.resource_calendar_id.id)

            emp_ou = self.default_operating_unit_id
            emp_wut = emp_ou.work_unit_type if emp_ou else False
            wut_filter = [False]
            if emp_wut:
                normalized_wut = 'head_office' if emp_wut in ('head_office', 'head_offices', 'ho') else ('branch' if emp_wut in ('branch', 'area_office', 'district_office') else emp_wut)
                wut_filter.extend([emp_wut, normalized_wut])

            res_ids = [False]
            if self.resource_id:
                res_ids.append(self.resource_id.id)

            pub_domain = [
                ('resource_id', 'in', res_ids),
                ('calendar_id', 'in', list(set(cal_ids))),
            ]
            if 'work_unit_type' in self.env['resource.calendar.leaves']._fields:
                pub_domain.append(('work_unit_type', 'in', list(set(wut_filter))))

            date_domain = ['|',
                ('day_of_week', '!=', False) if 'day_of_week' in self.env['resource.calendar.leaves']._fields else ('id', '=', False),
                '&', ('date_from', '<=', datetime.datetime.combine(date_to + datetime.timedelta(days=1), datetime.time.max)),
                     ('date_to', '>=', datetime.datetime.combine(date_from - datetime.timedelta(days=1), datetime.time.min)),
            ]
            pub_domain.extend(date_domain)
            pub_holidays = self.env['resource.calendar.leaves'].sudo().search(pub_domain)

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

        def _resolve_base_shift_batch(d):
            is_sat = (d.weekday() == 5)
            # 1. Roster
            r_line = roster_lines_by_date.get(d)
            if r_line and r_line.schedule_type != 'day_off' and r_line.shift_id:
                s = r_line.shift_id
                h_l = bool(enable_lunch and s.has_lunch_break and not s.is_night_shift)
                ls = (s.lunch_start_time or 12.0) if h_l else 0.0
                ld = (s.lunch_duration or 1.0) if h_l else 0.0
                return {
                    'shift_start': s.start_time, 'shift_end': s.end_time,
                    'has_lunch': h_l, 'lunch_start': ls, 'lunch_end': ls + ld,
                    'lunch_duration': ld, 'lunch_midpoint': (ls + (ls + ld)) / 2.0 if h_l else 0.0,
                    'is_night_shift': bool(s.is_night_shift), 'is_day_off': False,
                    'shift_name': s.name, 'is_custom_exception': True,
                    'source_label': 'Job Position Roster Exception'
                }
            # 2. Sunday Day Off (Default Weekly Rest)
            if d.weekday() == 6:
                return {
                    'shift_start': 0.0, 'shift_end': 0.0,
                    'has_lunch': False, 'lunch_start': 0.0, 'lunch_end': 0.0, 'lunch_duration': 0.0,
                    'lunch_midpoint': 0.0, 'is_night_shift': False, 'is_day_off': True,
                    'shift_name': 'Scheduled Day Off (Sunday)',
                    'is_custom_exception': False,
                    'source_label': 'Default Calendar'
                }
            # 3. Job Position Exception
            if job_exceptions and job_exceptions.shift_id:
                s = job_exceptions.shift_id
                h_l = bool(enable_lunch and s.has_lunch_break and not s.is_night_shift)
                ls = (s.lunch_start_time or 12.0) if h_l else 0.0
                ld = (s.lunch_duration or 1.0) if h_l else 0.0
                return {
                    'shift_start': s.start_time, 'shift_end': s.end_time,
                    'has_lunch': h_l, 'lunch_start': ls, 'lunch_end': ls + ld,
                    'lunch_duration': ld, 'lunch_midpoint': (ls + (ls + ld)) / 2.0 if h_l else 0.0,
                    'is_night_shift': bool(s.is_night_shift), 'is_day_off': False,
                    'shift_name': s.name, 'is_custom_exception': True,
                    'source_label': 'Job Position Exception'
                }
            # 3. Location Exception
            if location_exceptions:
                loc = location_exceptions
                s = loc.shift_id if hasattr(loc, 'shift_id') and loc.shift_id else False
                is_n = s.is_night_shift if s else False
                h_l = bool(enable_lunch and (s.has_lunch_break if s else loc.has_lunch_break) and not is_n)
                ls = (s.lunch_start_time or 12.0) if (s and h_l) else (default_lunch_out if h_l else 0.0)
                ld = (s.lunch_duration or default_lunch_dur) if (s and h_l) else (default_lunch_dur if h_l else 0.0)
                return {
                    'shift_start': s.start_time if s else loc.start_time,
                    'shift_end': s.end_time if s else loc.end_time,
                    'has_lunch': h_l, 'lunch_start': ls, 'lunch_end': ls + ld,
                    'lunch_duration': ld, 'lunch_midpoint': (ls + (ls + ld)) / 2.0 if h_l else 0.0,
                    'is_night_shift': bool(is_n), 'is_day_off': False,
                    'shift_name': (s.name if s else loc.name) or 'Location Shift',
                    'is_custom_exception': True, 'source_label': 'Location-Based Exception'
                }
            # 4. Default Global
            s_end_val = default_exit_time
            is_sat_h = False
            if enable_saturday and is_sat:
                ou_rec = self.default_operating_unit_id
                ut = ou_rec.work_unit_type if ou_rec else False
                if ut in ('head_office', 'head_offices', 'ho') or (ut in ('district', 'district_office', 'regional_office') and enable_district_saturday) or not ou_rec:
                    s_end_val = saturday_exit_time
                    is_sat_h = True
            h_l = bool(enable_lunch and not is_sat_h)
            ls = default_lunch_out if h_l else 0.0
            ld = default_lunch_dur if h_l else 0.0
            return {
                'shift_start': default_morning_time, 'shift_end': s_end_val,
                'has_lunch': h_l, 'lunch_start': ls, 'lunch_end': ls + ld,
                'lunch_duration': ld, 'lunch_midpoint': (ls + (ls + ld)) / 2.0 if h_l else 0.0,
                'is_night_shift': False, 'is_day_off': False,
                'shift_name': 'Default Global Shift (Saturday Half Day)' if is_sat_h else 'Default Global Shift'
            }

        result = {}
        cur_date = date_from
        while cur_date <= date_to:
            is_saturday = (cur_date.weekday() == 5)
            is_sunday = (cur_date.weekday() == 6)

            # Check individual leave for cur_date
            matching_leave = leaves.filtered(lambda l: self._is_leave_matching_date(l, cur_date))
            if matching_leave:
                leave = matching_leave[0]
                l_name = leave.holiday_status_id.name or _('Time Off')
                if isinstance(l_name, dict):
                    l_name = l_name.get('en_US', list(l_name.values())[0]) if l_name else _('Time Off')
                is_start_half = bool(getattr(leave, 'starting_half_day', False) and (getattr(leave, 'leave_start_date', False) or getattr(leave, 'request_date_from', False)) == cur_date)
                is_end_half = bool(getattr(leave, 'ending_half_day', False) and (getattr(leave, 'leave_end_date', False) or getattr(leave, 'request_date_to', False)) == cur_date)
                is_half = bool(getattr(leave, 'request_unit_half', False) or getattr(leave, 'half_day', False) or (getattr(leave, 'number_of_days', 1.0) == 0.5) or is_start_half or is_end_half)
                if getattr(leave, 'is_continuous_half_day', False):
                    half_period = getattr(leave, 'continuous_half_day_period', 'am')
                elif getattr(leave, 'single_half_day_period', False):
                    half_period = leave.single_half_day_period
                elif is_start_half:
                    half_period = 'pm'
                elif is_end_half:
                    half_period = 'am'
                else:
                    half_period = getattr(leave, 'request_date_from_period', 'am')
                if is_half:
                    base_shift_for_day = _resolve_base_shift_batch(cur_date)
                    result[cur_date] = self._split_shift_for_half_day_leave(
                        base_shift_for_day, half_period, l_name,
                        default_lunch_out=default_lunch_out,
                        default_lunch_dur=default_lunch_dur,
                        enable_lunch=enable_lunch
                    )
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

            # Check 24/7 roster line (Continuous operations: Public Holidays do NOT cancel roster shifts)
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
                        has_l = bool(enable_lunch and shift.has_lunch_break and not shift.is_night_shift)
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

            # Check public holiday for cur_date (Applies to Location Exceptions, Job Exceptions, and Standard Staff)
            matching_pub = pub_holidays.filtered(lambda h: (
                (getattr(h, 'day_of_week', False) and str(h.day_of_week) == str(cur_date.weekday())) or
                (h.date_from and h.date_to and self._to_local_date(h.date_from) <= cur_date <= self._to_local_date(h.date_to))
            ))
            if matching_pub:
                pub = matching_pub[0]
                p_name = pub.name or _('Public Holiday')
                if isinstance(p_name, dict):
                    p_name = p_name.get('en_US', list(p_name.values())[0]) if p_name else _('Public Holiday')
                p_weight = getattr(pub, 'holiday_day_weight', 1.0) or 1.0
                if p_weight == 0.5:
                    result[cur_date] = {
                        'shift_start': 13.0, 'shift_end': default_exit_time,
                        'has_lunch': False, 'lunch_start': 0.0, 'lunch_end': 0.0, 'lunch_duration': 0.0,
                        'lunch_midpoint': 0.0, 'is_night_shift': False, 'is_day_off': False,
                        'is_on_leave': False, 'is_half_day_leave': True, 'is_public_holiday': True,
                        'leave_name': p_name, 'shift_name': f"Afternoon Shift (Morning Public Holiday: {p_name})",
                        'source_label': 'Public Holiday',
                    }
                else:
                    result[cur_date] = {
                        'shift_start': 0.0, 'shift_end': 0.0,
                        'has_lunch': False, 'lunch_start': 0.0, 'lunch_end': 0.0, 'lunch_duration': 0.0,
                        'lunch_midpoint': 0.0, 'is_night_shift': False, 'is_day_off': True,
                        'is_on_leave': True, 'is_public_holiday': True,
                        'leave_name': p_name, 'shift_name': f"Public Holiday ({p_name})",
                        'source_label': 'Public Holiday',
                    }
                cur_date += datetime.timedelta(days=1)
                continue

            # Check Sunday Day Off (Applies to Location Exceptions, Job Exceptions, and Standard Staff)
            # ONLY 24/7 Rotational Rosters override Sundays.
            if is_sunday:
                result[cur_date] = {
                    'shift_start': 0.0, 'shift_end': 0.0,
                    'has_lunch': False, 'lunch_start': 0.0, 'lunch_end': 0.0, 'lunch_duration': 0.0,
                    'lunch_midpoint': 0.0, 'is_night_shift': False, 'is_day_off': True,
                    'shift_name': 'Scheduled Day Off (Sunday)',
                    'is_custom_exception': False,
                    'source_label': 'Default Calendar'
                }
                cur_date += datetime.timedelta(days=1)
                continue

            # Check static job exception (Monday - Saturday)
            if job_exceptions and job_exceptions.shift_id and (job_exceptions.start_date <= cur_date and (not job_exceptions.end_date or job_exceptions.end_date >= cur_date)):
                shift = job_exceptions.shift_id
                has_l = bool(enable_lunch and shift.has_lunch_break and not shift.is_night_shift)
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

            # Check location exception (Monday - Saturday)
            if location_exceptions and (location_exceptions.start_date <= cur_date and (not location_exceptions.end_date or location_exceptions.end_date >= cur_date)):
                loc = location_exceptions
                shift = loc.shift_id if hasattr(loc, 'shift_id') and loc.shift_id else False
                is_night = shift.is_night_shift if shift else False
                has_l = bool(enable_lunch and (shift.has_lunch_break if shift else loc.has_lunch_break) and not is_night)
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

            # Default global schedule (Monday - Saturday)
            s_end = default_exit_time
            is_sat_half = False
            if enable_saturday and is_saturday:
                ou = self.default_operating_unit_id
                unit_type = ou.work_unit_type if ou else False
                if unit_type in ('head_office', 'head_offices', 'ho') or (unit_type in ('district', 'district_office', 'regional_office') and enable_district_saturday) or not ou:
                    s_end = saturday_exit_time
                    is_sat_half = True
            has_l = bool(enable_lunch and not is_sat_half)
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
        target_date = fields.Date.to_date(target_date)

        checkin_buffer = self._get_param_float('hr_attendance.checkin_buffer', 0.50)
        enable_checkin_restriction = self.env['ir.config_parameter'].sudo().get_param(
            'hr_attendance.enable_checkin_restriction', 'True').lower() in ('true', '1')

        sched = self._resolve_employee_full_schedule(current_float=current_float, target_date=target_date)
        if sched.get('is_public_holiday') and sched.get('is_day_off'):
            if not is_manager:
                raise UserError(_("Attendance cannot be recorded.\n\nToday is a recognized Public Holiday: %s.") % sched.get('leave_name', 'Public Holiday'))
        elif sched.get('is_on_leave'):
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
                        "Check-in is not available.\n\n"
                        "Your scheduled shift concluded at %s.\n"
                        "Please report to your direct coach if you worked during this shift."
                    ) % _fmt_12h(afternoon_e))
                return afternoon_s, afternoon_e

            if current_float < morning_e:
                # Morning Session
                earliest_checkin = morning_s - checkin_buffer
                if current_float >= earliest_checkin or not enable_checkin_restriction or is_manager:
                    _logger.info("Using Morning Shift Session: %.2f - %.2f", morning_s, morning_e)
                    return morning_s, morning_e
                raise UserError(_(
                    "Check-in is not open yet.\n\n"
                    "Your morning shift starts at %s.\n"
                    "Check-in becomes available at %s (30 minutes before shift start)."
                ) % (_fmt_12h(morning_s), _fmt_12h(earliest_checkin)))
            elif current_float < afternoon_buffer_start:
                # Lunch Break Window (e.g. 12:00 - 12:45)
                if enable_checkin_restriction and not is_manager:
                    raise UserError(_(
                        "Lunch break is currently in progress.\n\n"
                        "Morning shift concluded at %s.\n"
                        "Check-in for your afternoon shift opens at %s."
                    ) % (_fmt_12h(morning_e), _fmt_12h(afternoon_buffer_start)))
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
                            "Check-in is not available.\n\n"
                            "Your scheduled shift concluded at %s.\n"
                            "Please report to your direct coach if you worked during this shift."
                        ) % _fmt_12h(sched['shift_end']))
                if current_float >= earliest_checkin or current_float <= sched['shift_end'] or not enable_checkin_restriction or is_manager:
                    return sched['shift_start'], sched['shift_end']
            else:
                if current_float >= sched['shift_end']:
                    if enable_checkin_restriction and not is_manager:
                        raise UserError(_(
                            "Check-in is not available.\n\n"
                            "Your scheduled shift concluded at %s.\n"
                            "Please report to your direct coach if you worked during this shift."
                        ) % _fmt_12h(sched['shift_end']))

                earliest_checkin = sched['shift_start'] - checkin_buffer
                if current_float >= earliest_checkin or not enable_checkin_restriction or is_manager:
                    return sched['shift_start'], sched['shift_end']

            raise UserError(_(
                "Check-in is not open yet.\n\n"
                "Your scheduled shift starts at %s.\n"
                "Check-in becomes available at %s (30 minutes before shift start)."
            ) % (_fmt_12h(sched['shift_start']), _fmt_12h(earliest_checkin)))

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

        grace_mins = int(round(grace * 60.0))
        dead_mins = int(round(dead_time * 60.0))
        # Minute-inclusive cutoff: allows check-in through :59 seconds of the grace minute
        # E.g. shift_start 08:00 with 20 min grace allows check-in up to 08:20:59 as Normal
        normal_cutoff = shift_start + (grace_mins / 60.0) + (59.999 / 3600.0)
        late_cutoff_limit = shift_start + ((grace_mins + dead_mins) / 60.0)
        late_cutoff = late_cutoff_limit + (59.999 / 3600.0)

        _logger.debug(
            "EVALUATING CHECKIN | Employee: %s | Current: %.4f | ShiftStart: %.4f | Grace: %.4f | DeadTime: %.4f | NormalCutoff: %.4f | LateCutoff: %.4f",
            self.name, current_float, shift_start, grace, dead_time, normal_cutoff, late_cutoff
        )

        if predefined_late and current_float <= predefined_late.end_time:
            if current_float <= normal_cutoff:
                status = 'Normal'
                late_time = 0.0
                pre_defined_lateness_hours = 0.0
            else:
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
                    "Self-check-in closed at %s.\n\n"
                    "The check-in window for this shift has passed.\n"
                    "Please report to your direct coach to register your attendance."
                ) % _fmt_12h(late_cutoff_limit))
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

    def _get_predefined_attendance(self, today_date, current_float, session_type=None):
        today_date = fields.Date.to_date(today_date or fields.Date.context_today(self))
        domain_late = [
            ('employee_id', '=', self.id),
            ('date', '=', today_date),
            ('exception_type', '=', 'predefined_late'),
            ('state', '=', 'approved'),
            ('is_utilized', '=', False),
        ]
        domain_early = [
            ('employee_id', '=', self.id),
            ('date', '=', today_date),
            ('exception_type', '=', 'predefined_early_exit'),
            ('state', '=', 'approved'),
            ('is_utilized', '=', False),
        ]
        if session_type:
            domain_late.append(('target_session', 'in', [session_type, 'single_shift']))
            domain_early.append(('target_session', 'in', [session_type, 'single_shift']))

        predefined_late = self.env['attendance.preapproval'].search(domain_late, limit=1)
        predefined_early_exit = self.env['attendance.preapproval'].search(domain_early, limit=1)
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
                user_tz = local_dt.tzinfo or pytz.timezone('Africa/Addis_Ababa')
                ts = pytz.utc.localize(a.check_in).astimezone(user_tz) if a.check_in.tzinfo is None else a.check_in.astimezone(user_tz)
                return ts.hour + ts.minute / 60.0 + ts.second / 3600.0

            # Check if this open attendance is a Morning or Afternoon Session of a lunch-split shift
            att_in_h = _att_in_hour(attendance)
            is_afternoon_session = bool(
                (attendance.shift_start_float and attendance.shift_start_float >= (sched['lunch_start'] - 0.01)) or
                (attendance.check_in and att_in_h >= (sched['lunch_start'] - 0.01))
            )
            is_morning_session = bool(sched['has_lunch'] and not is_afternoon_session)
            # Old morning session check
            _unused_check = (
                (attendance.shift_end_float and attendance.shift_end_float <= (sched['lunch_start'] + 0.1)) or
                (attendance.check_in and _att_in_hour(attendance) < (sched['lunch_start'] - 0.01))
            )
            if is_morning_session:
                lunch_start = sched['lunch_start']
                afternoon_start = sched['lunch_end']
                lunch_gap = max(0.0, afternoon_start - lunch_start)
                afternoon_buffer_start = max(lunch_start, afternoon_start - min(0.25, lunch_gap / 2.0))
                dead_mins = int(round(dead_time * 60.0))
                afternoon_late_cutoff = afternoon_start + (dead_mins / 60.0) + (59.999 / 3600.0)

                if current_float < (lunch_start - 0.05):
                    # Trying to check out BEFORE lunch starts (e.g. 11:30 AM before 12:00 PM)
                    unused_late, predefined_early_exit_m = self._get_predefined_attendance(today_date, current_float, session_type='morning')
                    if predefined_early_exit_m:
                        if current_float < predefined_early_exit_m.start_time:
                            raise UserError(_(
                                "Early departure is not available yet.\n\n"
                                "Your approved early departure begins at %s (Current time is %s)."
                            ) % (_fmt_12h(predefined_early_exit_m.start_time), _fmt_12h(current_float)))
                        else:
                            early_dur = max(0.0, round(lunch_start - current_float, 4))
                            attendance.write({
                                'check_out': utc_naive_dt,
                                'check_out_status': 'Early Check-out',
                                'out_mode': 'predefined',
                                'pre_defined_attendance_id': predefined_early_exit_m.id,
                                'pre_approved_early_checkout': early_dur,
                            })
                            predefined_early_exit_m.sudo().write({
                                'is_utilized': True,
                                'utilization_attendance_id': attendance.id,
                            })
                            self._last_attendance_action = 'check_out'
                            _logger.info("Early Morning Lunch Checkout for %s at %.2f (preapproval %s utilized)", self.name, current_float, predefined_early_exit_m.id)
                            return attendance
                    elif enable_checkout_restriction and not is_manager:
                        raise UserError(_(
                            "Shift still in progress.\n\n"
                            "Your scheduled lunch time begins at %s.\n"
                            "Leaving early requires prior approval from your direct coach."
                        ) % _fmt_12h(lunch_start))
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
                    predefined_late_a, unused_early_a = self._get_predefined_attendance(today_date, current_float, session_type='afternoon')
                    has_predefined = bool(predefined_late_a and current_float <= predefined_late_a.end_time)
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
                        current_float, afternoon_start, dead_time, predefined_late_a,
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
                    if predefined_late_a and pre_late > 0:
                        vals['pre_defined_attendance_id'] = predefined_late_a.id
                    if geo_information:
                        vals.update({'in_%s' % key: geo_information[key] for key in geo_information})
                    new_att = fast_att_env.create(vals)
                    if predefined_late_a and pre_late > 0:
                        predefined_late_a.sudo().write({
                            'is_utilized': True,
                            'utilization_attendance_id': new_att.id,
                        })
                    new_att._enqueue_attendance_side_effects()
                    return new_att

            # Regular Shift-End Check-Out (Afternoon or Full-Day / Saturday)
            # Use dynamic schedule shift_end to immediately reflect updated settings or Saturday half-day
            target_shift_end = sched['shift_end'] if (not sched.get('has_lunch') or not attendance.shift_end_float) else attendance.shift_end_float
            target_shift_end_utc = self._float_to_utc_datetime(target_shift_end, local_dt)

            session_pm = 'afternoon' if sched.get('has_lunch') else 'single_shift'
            unused_late_pm, predefined_early_exit_pm = self._get_predefined_attendance(today_date, current_float, session_type=session_pm)

            if current_float < (target_shift_end - 0.05):
                if predefined_early_exit_pm:
                    if current_float < predefined_early_exit_pm.start_time:
                        raise UserError(_(
                            "Early departure is not available yet.\n\n"
                            "Your approved early departure begins at %s (Current time is %s)."
                        ) % (_fmt_12h(predefined_early_exit_pm.start_time), _fmt_12h(current_float)))
                    else:
                        early_dur = max(0.0, round(target_shift_end - current_float, 4))
                        attendance.with_context(tracking_disable=True, mail_notrack=True).write({
                            'check_out': utc_naive_dt,
                            'check_out_status': 'Early Check-out',
                            'out_mode': 'predefined',
                            'pre_defined_attendance_id': predefined_early_exit_pm.id,
                            'pre_approved_early_checkout': early_dur,
                        })
                        predefined_early_exit_pm.sudo().write({
                            'is_utilized': True,
                            'utilization_attendance_id': attendance.id,
                        })
                        self._last_attendance_action = 'check_out'
                        _logger.info("Pre-Approved Check-Out recorded for %s at %.2f (preapproval %s utilized)", self.name, current_float, predefined_early_exit_pm.id)
                        return attendance
                elif enable_checkout_restriction and not is_manager:
                    raise UserError(_(
                        "Shift still in progress.\n\n"
                        "Your scheduled shift ends at %s.\n"
                        "Leaving early requires prior approval from your direct coach."
                    ) % _fmt_12h(target_shift_end))

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
            # Check if all scheduled sessions for today have already been completed
            today_start_utc = self._float_to_utc_datetime(0.0, local_dt)
            today_end_utc = self._float_to_utc_datetime(24.0, local_dt)
            today_completed_atts = self.env['hr.attendance'].sudo().search([
                ('employee_id', '=', self.id),
                ('check_in', '>=', today_start_utc),
                ('check_in', '<=', today_end_utc),
                ('check_out', '!=', False),
            ], order='check_in asc')

            has_lunch_split = bool(sched.get('has_lunch'))
            is_all_completed = False

            def _att_in_h_val(a):
                if not a.check_in:
                    return 0.0
                user_tz = local_dt.tzinfo or pytz.timezone('Africa/Addis_Ababa')
                ts = pytz.utc.localize(a.check_in).astimezone(user_tz) if a.check_in.tzinfo is None else a.check_in.astimezone(user_tz)
                return ts.hour + ts.minute / 60.0 + ts.second / 3600.0

            if has_lunch_split and not sched.get('is_day_off'):
                lunch_start_val = sched.get('lunch_start', 12.0)
                pm_done = today_completed_atts.filtered(
                    lambda a: (a.shift_start_float and a.shift_start_float >= (lunch_start_val - 0.1)) or
                              (a.check_in and _att_in_h_val(a) >= (lunch_start_val - 0.1))
                )
                if pm_done:
                    is_all_completed = True
            elif today_completed_atts and not sched.get('is_day_off'):
                is_all_completed = True

            if is_all_completed and not is_manager:
                tot_hours = sum(a.worked_hours or 0.0 for a in today_completed_atts)
                h_int = int(tot_hours)
                m_int = int(round((tot_hours - h_int) * 60))
                raise UserError(_(
                    "Daily Attendance Completed.\n\n"
                    "You have completed your scheduled work for today (%02dh %02dm recorded).\n"
                    "No further check-in is required today."
                ) % (h_int, m_int))

            shift_start, shift_end = self._select_applicable_shift(
                current_float, morning_start, exit_time, target_date=today_date, is_manager=is_manager
            )
            is_night = (shift_end <= shift_start)
            shift_start_utc = self._float_to_utc_datetime(shift_start, local_dt)
            lunch_start_val = sched.get('lunch_start', 12.0)
            lunch_end_val = sched.get('lunch_end', 13.0)
            lunch_gap = max(0.0, lunch_end_val - lunch_start_val)
            afternoon_buf_start = max(lunch_start_val, lunch_end_val - min(0.25, lunch_gap / 2.0))
            is_afternoon_checkin = bool((sched.get('has_lunch') and current_float >= afternoon_buf_start) or sched.get('half_day_period') == 'am')

            checkin_session = 'afternoon' if is_afternoon_checkin else ('morning' if sched.get('has_lunch') else 'single_shift')
            predefined_late_in, unused_early_in = self._get_predefined_attendance(today_date, current_float, session_type=checkin_session)

            status, late_time, ot, pre_late = self._evaluate_checkin_status(
                current_float, shift_start, dead_time, predefined_late_in,
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
            if predefined_late_in and pre_late > 0:
                vals['pre_defined_attendance_id'] = predefined_late_in.id

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
            if predefined_late_in and pre_late > 0:
                predefined_late_in.sudo().write({
                    'is_utilized': True,
                    'utilization_attendance_id': attendance.id,
                })
            attendance._enqueue_attendance_side_effects()
            if not getattr(self, '_last_attendance_action', None):
                self._last_attendance_action = 'check_in'
            return attendance
