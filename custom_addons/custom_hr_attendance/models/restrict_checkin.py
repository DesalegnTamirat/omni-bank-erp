# -*- coding: utf-8 -*-
import datetime
import pytz
import logging
from odoo import models, fields, api, _
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

        params = self.env['ir.config_parameter'].sudo()
        default_morning_time = float(params.get_param('hr_attendance.morning_time', 8.0))
        default_exit_time = float(params.get_param('hr_attendance.exit_time', 17.0))
        enable_saturday = params.get_param('hr_attendance.enable_saturday_halfday', 'True').lower() in ('true', '1')
        enable_district_saturday = params.get_param('hr_attendance.saturday_halfday_district', 'True').lower() in ('true', '1')
        saturday_exit_time = float(params.get_param('hr_attendance.saturday_exit_time', 12.0))
        enable_lunch = params.get_param('hr_attendance.enable_lunch_break', 'False').lower() in ('true', '1')
        default_lunch_out = float(params.get_param('hr_attendance.lunch_out_time', 12.0))
        default_lunch_dur = float(params.get_param('hr_attendance.lunch_duration', 1.0))

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
        roster_exceptions = self.env['job.position.roster.exception'].search([
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
                        'shift_name': 'Scheduled Day Off'
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
                        'shift_name': shift.name
                    }

        # 2. Job Position Exception (Static)
        job_exceptions = self.env['job.position.exception'].search([
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
                'shift_name': shift.name
            }

        # 3. Location-based shifts
        location_exceptions = self.env['location.based.exception'].browse()
        if self.default_operating_unit_id:
            ou_ids = [self.default_operating_unit_id.id]
            if hasattr(self.default_operating_unit_id, 'parent_unit') and self.default_operating_unit_id.parent_unit:
                ou_ids.append(self.default_operating_unit_id.parent_unit.id)
            location_exceptions = self.env['location.based.exception'].search([
                '|', ('operating_unit_ids', 'in', ou_ids),
                     ('operating_unit', 'in', ou_ids),
                ('active', '=', True),
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
                'shift_name': (shift.name if shift else loc.name) or 'Location Shift'
            }

        # 4. Default global schedule
        s_end = default_exit_time
        if enable_saturday and is_saturday:
            ou = self.default_operating_unit_id
            unit_type = ou.work_unit_type if ou else False
            if unit_type == 'head_office' or (unit_type == 'district' and enable_district_saturday):
                s_end = saturday_exit_time

        has_l = bool(enable_lunch and not is_saturday)
        l_start = default_lunch_out if has_l else 0.0
        l_dur = default_lunch_dur if has_l else 0.0
        l_end = l_start + l_dur

        return {
            'shift_start': default_morning_time, 'shift_end': s_end,
            'has_lunch': has_l, 'lunch_start': l_start, 'lunch_end': l_end,
            'lunch_duration': l_dur, 'lunch_midpoint': (l_start + l_end) / 2.0 if has_l else 0.0,
            'is_night_shift': False, 'is_day_off': False,
            'shift_name': 'Default Global Shift'
        }

    def _get_employee_shift_info(self, target_date=None):
        """ Alias mapping to _resolve_employee_full_schedule for backward compatibility across models """
        res = self._resolve_employee_full_schedule(target_date=target_date)
        res['start_time'] = res.get('shift_start', 8.0)
        res['end_time'] = res.get('shift_end', 17.0)
        res['lunch_out_time'] = res.get('lunch_start', 12.0)
        res['has_lunch_break'] = res.get('has_lunch', False)
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
            lunch_midpoint = sched['lunch_midpoint']
            afternoon_buffer_start = afternoon_s - 0.25  # Fixed 15 min buffer before afternoon start

            if current_float < lunch_midpoint:
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
            else:
                # Afternoon Session
                if current_float >= afternoon_buffer_start or not enable_checkin_restriction or is_manager:
                    _logger.info("Using Afternoon Shift Session: %.2f - %.2f", afternoon_s, afternoon_e)
                    return afternoon_s, afternoon_e
                raise UserError(_(
                    "Check-in is not allowed during lunch break.\n\n"
                    "You are too early for the Afternoon shift (%s - %s).\n"
                    "Check-in window opens at %s (15 min buffer)."
                ) % (_fmt(afternoon_s), _fmt(afternoon_e), _fmt(afternoon_buffer_start)))
        else:
            # Single Continuous Shift
            earliest_checkin = sched['shift_start'] - checkin_buffer
            if sched['is_night_shift']:
                if current_float >= earliest_checkin or current_float <= sched['shift_end'] or not enable_checkin_restriction or is_manager:
                    return sched['shift_start'], sched['shift_end']
            else:
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

        _logger.warning(
            "EVALUATING CHECKIN | Employee: %s | Current: %.4f | ShiftStart: %.4f | Grace: %.4f | DeadTime: %.4f | NormalCutoff: %.4f | LateCutoff: %.4f | Pass: %s",
            self.name, current_float, shift_start, grace, dead_time, normal_cutoff, late_cutoff, current_float <= late_cutoff or allow_late
        )

        if predefined_late and current_float <= predefined_late.end_time:
            status = 'Pre-Defined Lateness'
            pre_defined_lateness_hours = round(current_float - shift_start, 4)
        elif current_float <= normal_cutoff:
            status = 'Normal'
            late_time = 0.0
        elif current_float <= late_cutoff or allow_late:
            status = 'Late'
            late_time = max(0.0, round(current_float - shift_start, 4))
        else:
            _logger.warning("Check-in rejected for %s: Current (%.4f) > Cutoff (%.4f)", self.name, current_float, late_cutoff)
            raise UserError(_("Check-in is not allowed. You are past the allowed late threshold."))

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
        utc_dt = fields.Datetime.now()
        local_dt = pytz.utc.localize(utc_dt).astimezone(local_tz)
        current_float = local_dt.hour + (local_dt.minute / 60.0) + (local_dt.second / 3600.0)
        return local_dt, current_float, local_dt.date()

    def _load_time_parameters(self):
        morning_start = self._get_param_float('hr_attendance.morning_time', 8.0)
        exit_time = self._get_param_float('hr_attendance.exit_time', 17.0)
        dead_time = self._get_param_float('hr_attendance.dead_time', 0.33)
        return morning_start, exit_time, dead_time

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

    def _float_to_utc_datetime(self, float_hour, local_dt):
        tz_name = self.user_id.tz or self.env.user.tz or 'Africa/Addis_Ababa'
        try:
            local_tz = pytz.timezone(tz_name)
        except Exception:
            local_tz = pytz.timezone('Africa/Addis_Ababa')
        h = int(float_hour)
        m = int(round((float_hour - h) * 60))
        s = int(round(((float_hour - h) * 60 - m) * 60))
        if s >= 60:
            m += 1
            s = 0
        if m >= 60:
            h += 1
            m = 0
        local_target = local_dt.replace(hour=h, minute=m, second=s, microsecond=0)
        utc_target = local_tz.localize(local_target.replace(tzinfo=None)).astimezone(pytz.utc)
        return utc_target.replace(tzinfo=None)

    # ============================================================
    # MAIN ATTENDANCE ACTION (CHECK IN / CHECK OUT / 1-CLICK LUNCH)
    # ============================================================
    def _attendance_action_change(self, geo_information=None):
        """ Universal Check in / Check out action wrapper for Bunna Bank rules. """
        self.ensure_one()
        _logger.info("=== ATTENDANCE ACTION TRIGGERED FOR %s ===", self.name)

        local_dt, current_float, today_date = self._get_local_time_and_float()
        morning_start, exit_time, dead_time = self._load_time_parameters()
        predefined_late, predefined_early_exit = self._get_predefined_attendance(today_date, current_float)
        min_work_hour = self._get_min_work_hour()

        utc_naive_dt = fields.Datetime.now()
        sched = self._resolve_employee_full_schedule(current_float=current_float, target_date=today_date)

        open_attendance = self.env['hr.attendance'].search([
            ('employee_id', '=', self.id), ('check_out', '=', False)
        ], limit=1)

        enable_checkin_restriction = self.env['ir.config_parameter'].sudo().get_param(
            'hr_attendance.enable_checkin_restriction', 'True').lower() in ('true', '1')
        enable_checkout_restriction = self.env['ir.config_parameter'].sudo().get_param(
            'hr_attendance.enable_checkout_restriction', 'True').lower() in ('true', '1')

        # ----------------------------------------------------
        # SCENARIO 1: EMPLOYEE HAS AN OPEN ATTENDANCE RECORD
        # ----------------------------------------------------
        if open_attendance:
            attendance = open_attendance

            # Check if this open attendance is a Morning Session of a lunch-split shift
            is_morning_session = sched['has_lunch'] and (
                (attendance.shift_end_float and attendance.shift_end_float <= (sched['lunch_start'] + 0.1)) or
                (attendance.check_in and fields.Datetime.context_timestamp(self, attendance.check_in).hour < int(sched['lunch_start'])) or
                (current_float < sched['lunch_end'])
            )
            if is_morning_session:
                lunch_start = sched['lunch_start']
                afternoon_start = sched['lunch_end']
                afternoon_buffer_start = afternoon_start - 0.25  # 15 min buffer before afternoon start
                afternoon_late_cutoff = afternoon_start + dead_time

                if current_float < (lunch_start - 0.05):
                    # Trying to check out BEFORE lunch starts (e.g. 11:30 AM before 12:00 PM)
                    if enable_checkout_restriction:
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
                        self.write({'attendance_state': 'checked_out', 'last_attendance_id': attendance.id})
                        _logger.info("Early Morning Lunch Checkout for %s at %.2f", self.name, current_float)
                        return attendance

                elif current_float < afternoon_buffer_start:
                    # NORMAL LUNCH CHECKOUT (e.g. 12:00 PM - 12:44 PM)
                    lunch_checkout_utc = self._float_to_utc_datetime(lunch_start, local_dt)
                    attendance.write({
                        'check_out': lunch_checkout_utc,
                        'check_out_status': 'Normal',
                    })
                    self.write({'attendance_state': 'checked_out', 'last_attendance_id': attendance.id})
                    _logger.info("Normal Morning Lunch Checkout for %s at %.2f (Check-out stamped: %s)", self.name, current_float, lunch_start)
                    return attendance

                else:
                    # 1-CLICK AFTERNOON TRANSITION (e.g. 12:45 PM onwards)
                    # Employee forgot morning lunch checkout and clicks for the first time during afternoon entry!
                    lunch_checkout_utc = self._float_to_utc_datetime(lunch_start, local_dt)
                    attendance.write({
                        'check_out': lunch_checkout_utc,
                        'check_out_status': 'Force Checkout',
                        'is_force_checkout': True,
                    })
                    _logger.info("1-Click Force Checkout Morning Session for %s at %.2f", self.name, current_float)

                    if current_float <= afternoon_start:
                        # On-Time Afternoon Check-in (snapped to afternoon start)
                        afternoon_start_utc = self._float_to_utc_datetime(afternoon_start, local_dt)
                        vals = {
                            'employee_id': self.id,
                            'check_in': afternoon_start_utc,
                            'actual_check_in': utc_naive_dt,
                            'in_mode': self.env.context.get('attendance_mode', 'kiosk'),
                            'check_in_status': 'Normal',
                            'shift_start_float': afternoon_start,
                            'shift_end_float': sched['shift_end'],
                        }
                        if geo_information:
                            vals.update({'in_%s' % key: geo_information[key] for key in geo_information})
                        new_att = self.env['hr.attendance'].create(vals)
                        self.write({'attendance_state': 'checked_in', 'last_attendance_id': new_att.id})
                        return new_att
                    elif current_float <= afternoon_late_cutoff or not enable_checkin_restriction:
                        # Late Afternoon Check-in (Zero Grace)
                        late_hrs = max(0.0, round(current_float - afternoon_start, 4))
                        vals = {
                            'employee_id': self.id,
                            'check_in': utc_naive_dt,
                            'actual_check_in': utc_naive_dt,
                            'in_mode': self.env.context.get('attendance_mode', 'kiosk'),
                            'check_in_status': 'Late',
                            'late_time_hour': late_hrs,
                            'shift_start_float': afternoon_start,
                            'shift_end_float': sched['shift_end'],
                        }
                        if geo_information:
                            vals.update({'in_%s' % key: geo_information[key] for key in geo_information})
                        new_att = self.env['hr.attendance'].create(vals)
                        self.write({'attendance_state': 'checked_in', 'last_attendance_id': new_att.id})
                        return new_att
                    else:
                        # Past Afternoon Cutoff:
                        # Morning session was force-closed at lunch_start. Commit state cleanly without rollback.
                        self.write({'attendance_state': 'checked_out', 'last_attendance_id': attendance.id})
                        _logger.warning("Morning session Force Checkout committed for %s. Afternoon entry blocked (past cutoff %s).", self.name, _fmt(afternoon_late_cutoff))
                        return attendance

            # Regular Shift-End Check-Out (Afternoon or Full-Day)
            target_shift_end = attendance.shift_end_float or sched['shift_end']
            target_shift_end_utc = self._float_to_utc_datetime(target_shift_end, local_dt)

            if enable_checkout_restriction and current_float < (target_shift_end - 0.05):
                if predefined_early_exit:
                    pass
                else:
                    raise UserError(_(
                        "Check-out is not allowed yet.\n\n"
                        "Your scheduled shift ends at %s.\n"
                        "You cannot check out before shift end."
                    ) % _fmt(target_shift_end))

            out_status = 'Normal'
            if current_float < (target_shift_end - 0.05):
                out_status = 'Early Check-out'

            attendance.write({
                'check_out': utc_naive_dt,
                'check_out_status': out_status,
            })
            self.write({'attendance_state': 'checked_out', 'last_attendance_id': attendance.id})
            _logger.info("Check-Out recorded for %s at %.2f (Status: %s)", self.name, current_float, out_status)
            return attendance

        # ----------------------------------------------------
        # SCENARIO 2: EMPLOYEE IS CHECKED OUT (CHECKING IN)
        # ----------------------------------------------------
        else:
            shift_start, shift_end = self._select_applicable_shift(
                current_float, morning_start, exit_time, target_date=today_date
            )
            shift_start_utc = self._float_to_utc_datetime(shift_start, local_dt)
            shift_end_utc = self._float_to_utc_datetime(shift_end, local_dt)

            is_manager = (
                self.env.user.has_group('hr_attendance.group_hr_attendance_manager') or 
                self.env.user.has_group('hr_attendance.group_hr_attendance_user') or 
                self.env.is_superuser() or
                (self.user_id and self.user_id.id == self.env.uid and (self.user_id.has_group('hr_attendance.group_hr_attendance_manager') or self.user_id.has_group('hr_attendance.group_hr_attendance_user')))
            )

            is_afternoon_checkin = bool(sched['has_lunch'] and current_float >= sched['lunch_midpoint'])

            if enable_checkin_restriction:
                status, late_time, ot, pre_late = self._evaluate_checkin_status(
                    current_float, shift_start, dead_time, predefined_late, is_manager=is_manager, is_afternoon=is_afternoon_checkin
                )
                checkin_dt = utc_naive_dt if status in ('Late', 'Pre-Defined Lateness') else shift_start_utc
            else:
                status, late_time, ot, pre_late = self._evaluate_checkin_status(
                    current_float, shift_start, dead_time, predefined_late, is_manager=is_manager, allow_late=True, is_afternoon=is_afternoon_checkin
                )
                checkin_dt = utc_naive_dt if status in ('Late', 'Pre-Defined Lateness') else shift_start_utc

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
            attendance = self.env['hr.attendance'].create(vals)
            self.write({'attendance_state': 'checked_in', 'last_attendance_id': attendance.id})
            attendance._enqueue_attendance_side_effects()
            return attendance
