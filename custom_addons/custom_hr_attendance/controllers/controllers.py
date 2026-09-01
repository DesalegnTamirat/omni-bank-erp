# -*- coding: utf-8 -*-
import datetime
import pytz
from odoo import http, fields
from odoo.http import request

from odoo.addons.hr_attendance.controllers.main import HrAttendance


class BunnaMyAttendance(http.Controller):

    def _float_to_time_str(self, float_time):
        if float_time is None or float_time is False:
            return ""
        hours = int(float_time)
        minutes = int(round((float_time - hours) * 60))
        if minutes >= 60:
            hours += 1
            minutes = 0
        hours_12 = hours % 12
        if hours_12 == 0:
            hours_12 = 12
        period = "AM" if hours < 12 else "PM"
        return f"{hours_12:02d}:{minutes:02d} {period}"

    def _get_employee_shift_info(self, employee, target_date=None):
        if not employee:
            return None

        env = employee.env
        if not target_date:
            target_date = fields.Date.context_today(request.env.user)

        today_date = fields.Date.context_today(request.env.user)

        # Tier 0: Approved Time Off / Leave (hr.leave)
        leave = env['hr.leave'].sudo().search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'validate'),
            ('date_from', '<=', datetime.datetime.combine(target_date, datetime.time.max)),
            ('date_to', '>=', datetime.datetime.combine(target_date, datetime.time.min)),
        ], limit=1)

        if leave:
            l_name = leave.holiday_status_id.name or 'Time Off'
            if isinstance(l_name, dict):
                l_name = l_name.get('en_US', list(l_name.values())[0]) if l_name else 'Time Off'
            is_half = bool(getattr(leave, 'request_unit_half', False) or getattr(leave, 'half_day', False) or (getattr(leave, 'number_of_days', 1.0) == 0.5))
            half_period = getattr(leave, 'request_date_from_period', False) or getattr(leave, 'single_half_day_period', 'am')
            s_d = getattr(leave, 'request_date_from', False) or getattr(leave, 'leave_start_date', False) or (leave.date_from.date() if leave.date_from else target_date)
            e_d = getattr(leave, 'request_date_to', False) or getattr(leave, 'leave_end_date', False) or (leave.date_to.date() if leave.date_to else target_date)
            date_range_str = f"{s_d.strftime('%b %d')} - {e_d.strftime('%b %d')}" if s_d != e_d else s_d.strftime('%b %d')
            dur = getattr(leave, 'number_of_days', 1.0)

            if is_half:
                if half_period == 'am':
                    return {
                        'name': f"Approved Time Off - {l_name} (Morning)",
                        'code': 'LEAVE_HALF_AM',
                        'time_range': 'Afternoon Shift (13:00 - 17:00)',
                        'start_time': 13.0,
                        'end_time': 17.0,
                        'start_time_str': '01:00 PM',
                        'end_time_str': '05:00 PM',
                        'is_night_shift': False,
                        'has_lunch_break': False,
                        'lunch_time_str': 'No Lunch Break',
                        'is_custom_exception': True,
                        'is_day_off': False,
                        'is_on_leave': True,
                        'is_half_day_leave': True,
                        'leave_name': l_name,
                        'leave_date_range': date_range_str,
                        'leave_duration': f"{dur:.1f} Day(s)",
                        'source_label': f"Approved Leave ({l_name})"
                    }
                else:
                    return {
                        'name': f"Approved Time Off - {l_name} (Afternoon)",
                        'code': 'LEAVE_HALF_PM',
                        'time_range': 'Morning Shift (08:00 - 12:00)',
                        'start_time': 8.0,
                        'end_time': 12.0,
                        'start_time_str': '08:00 AM',
                        'end_time_str': '12:00 PM',
                        'is_night_shift': False,
                        'has_lunch_break': False,
                        'lunch_time_str': 'No Lunch Break',
                        'is_custom_exception': True,
                        'is_day_off': False,
                        'is_on_leave': True,
                        'is_half_day_leave': True,
                        'leave_name': l_name,
                        'leave_date_range': date_range_str,
                        'leave_duration': f"{dur:.1f} Day(s)",
                        'source_label': f"Approved Leave ({l_name})"
                    }
            else:
                return {
                    'name': f"Approved Time Off - {l_name}",
                    'code': 'LEAVE',
                    'time_range': f"Excused All Day ({date_range_str})",
                    'start_time': 0.0,
                    'end_time': 0.0,
                    'start_time_str': '--:--',
                    'end_time_str': '--:--',
                    'is_night_shift': False,
                    'has_lunch_break': False,
                    'lunch_time_str': 'No Lunch Break',
                    'is_custom_exception': True,
                    'is_day_off': True,
                    'is_on_leave': True,
                    'leave_name': l_name,
                    'leave_date_range': date_range_str,
                    'leave_duration': f"{dur:.1f} Day(s)",
                    'source_label': 'Approved Time Off'
                }

        # Tier 1: Check active Roster Exception (job.position.roster.exception)
        roster = env['job.position.roster.exception'].sudo().search([
            ('employee_id', '=', employee.id),
            ('status', '=', 'active'),
            ('active', '=', True),
            ('start_date', '<=', target_date),
            ('end_date', '>=', target_date)
        ], order='start_date desc, id desc', limit=1)

        if roster:
            line = roster.line_ids.filtered(lambda l: l.date == target_date)
            if line:
                line = line[0]
                if line.schedule_type == 'day_off':
                    return {
                        'name': 'Scheduled Day Off',
                        'code': 'DAY_OFF',
                        'time_range': 'No mandatory shift today',
                        'start_time_str': 'Day Off',
                        'end_time_str': 'Day Off',
                        'is_night_shift': False,
                        'has_lunch_break': False,
                        'lunch_time_str': 'No Lunch Break',
                        'is_custom_exception': True,
                        'is_day_off': True,
                        'source_label': 'Roster Exception (Day Off)'
                    }
                shift = line.shift_id
                if shift:
                    start_str = self._float_to_time_str(shift.start_time)
                    end_str = self._float_to_time_str(shift.end_time)
                    lunch_str = "No Lunch Break"
                    if shift.has_lunch_break:
                        l_start = self._float_to_time_str(shift.lunch_start_time)
                        l_end_float = shift.lunch_start_time + shift.lunch_duration
                        l_end = self._float_to_time_str(l_end_float)
                        lunch_str = f"{l_start} - {l_end} ({shift.lunch_duration:.1f}h)"

                    return {
                        'name': shift.name,
                        'code': shift.code or '',
                        'time_range': shift.time_range or f"{start_str} - {end_str}",
                        'start_time_str': start_str,
                        'end_time_str': end_str,
                        'is_night_shift': shift.is_night_shift,
                        'has_lunch_break': shift.has_lunch_break,
                        'lunch_time_str': lunch_str,
                        'is_custom_exception': True,
                        'is_day_off': False,
                        'source_label': 'Roster Exception'
                    }

        # Tier 2: Search for active Static Job Position Exception (job.position.exception)
        active_exception = env['job.position.exception'].sudo().search([
            ('employee_id', '=', employee.id),
            ('status', '=', 'active'),
            ('active', '=', True),
            ('start_date', '<=', target_date),
            '|', ('end_date', '=', False), ('end_date', '>=', target_date)
        ], order='start_date desc, id desc', limit=1)

        if active_exception and active_exception.shift_id:
            is_sunday = (target_date.weekday() == 6)
            is_explicit_day_off = (active_exception.day_off == target_date)
            if is_sunday or is_explicit_day_off:
                return {
                    'name': 'Scheduled Day Off',
                    'code': 'DAY_OFF',
                    'time_range': 'No mandatory shift today',
                    'start_time_str': 'Day Off',
                    'end_time_str': 'Day Off',
                    'is_night_shift': False,
                    'has_lunch_break': False,
                    'lunch_time_str': 'No Lunch Break',
                    'is_custom_exception': True,
                    'is_day_off': True,
                    'source_label': 'Assigned Shift Exception (Day Off)'
                }

            shift = active_exception.shift_id
            start_str = self._float_to_time_str(shift.start_time)
            end_str = self._float_to_time_str(shift.end_time)
            
            lunch_str = "No Lunch Break"
            if shift.has_lunch_break:
                l_start = self._float_to_time_str(shift.lunch_start_time)
                l_end_float = shift.lunch_start_time + shift.lunch_duration
                l_end = self._float_to_time_str(l_end_float)
                lunch_str = f"{l_start} - {l_end} ({shift.lunch_duration:.1f}h)"

            return {
                'name': shift.name,
                'code': shift.code or '',
                'time_range': shift.time_range or f"{start_str} - {end_str}",
                'start_time_str': start_str,
                'end_time_str': end_str,
                'is_night_shift': shift.is_night_shift,
                'has_lunch_break': shift.has_lunch_break,
                'lunch_time_str': lunch_str,
                'is_custom_exception': True,
                'is_day_off': False,
                'source_label': 'Assigned Shift Exception'
            }

        # Tier 3: Search for active Location Based Exception (location.based.exception)
        if employee.default_operating_unit_id:
            ou_ids = [employee.default_operating_unit_id.id]
            if hasattr(employee.default_operating_unit_id, 'parent_unit') and employee.default_operating_unit_id.parent_unit:
                ou_ids.append(employee.default_operating_unit_id.parent_unit.id)

            loc_ex = env['location.based.exception'].sudo().search([
                '|', ('operating_unit_ids', 'in', ou_ids),
                     ('operating_unit', 'in', ou_ids),
                ('active', '=', True),
                ('start_date', '<=', target_date),
                '|', ('end_date', '=', False), ('end_date', '>=', target_date)
            ], order='start_date desc, id desc', limit=1)

            if loc_ex:
                shift = loc_ex.shift_id
                if shift:
                    start_str = self._float_to_time_str(shift.start_time)
                    end_str = self._float_to_time_str(shift.end_time)
                    lunch_str = "No Lunch Break"
                    if shift.has_lunch_break:
                        l_start = self._float_to_time_str(shift.lunch_start_time)
                        l_end_float = shift.lunch_start_time + shift.lunch_duration
                        l_end = self._float_to_time_str(l_end_float)
                        lunch_str = f"{l_start} - {l_end} ({shift.lunch_duration:.1f}h)"

                    return {
                        'name': loc_ex.schedule_name or shift.name,
                        'code': shift.code or 'LOC_EX',
                        'time_range': shift.time_range or f"{start_str} - {end_str}",
                        'start_time_str': start_str,
                        'end_time_str': end_str,
                        'is_night_shift': shift.is_night_shift,
                        'has_lunch_break': shift.has_lunch_break,
                        'lunch_time_str': lunch_str,
                        'is_custom_exception': True,
                        'is_day_off': False,
                        'source_label': 'Location Based Exception'
                    }
                elif loc_ex.start_time and loc_ex.end_time:
                    start_str = self._float_to_time_str(loc_ex.start_time)
                    end_str = self._float_to_time_str(loc_ex.end_time)
                    return {
                        'name': loc_ex.schedule_name or 'Location Based Exception',
                        'code': 'LOC_EX',
                        'time_range': f"{start_str} - {end_str}",
                        'start_time_str': start_str,
                        'end_time_str': end_str,
                        'is_night_shift': False,
                        'has_lunch_break': False,
                        'lunch_time_str': 'No Lunch Break',
                        'is_custom_exception': True,
                        'is_day_off': False,
                        'source_label': 'Location Based Exception'
                    }

        # Tier 4: Fallback to Default Global Shift (Sunday is default Day Off)
        if target_date.weekday() == 6:
            return {
                'name': 'Default Global Shift (Day Off)',
                'code': 'GLOBAL_OFF',
                'time_range': 'No mandatory shift today',
                'start_time_str': 'Day Off',
                'end_time_str': 'Day Off',
                'is_night_shift': False,
                'has_lunch_break': False,
                'lunch_time_str': 'No Lunch Break',
                'is_custom_exception': False,
                'is_day_off': True,
                'source_label': 'Default Global Shift (Sunday Off)'
            }

        params = env['ir.config_parameter'].sudo()
        try:
            std_start = float(params.get_param('custom_hr_attendance.standard_shift_start', '8.0'))
        except Exception:
            std_start = 8.0

        try:
            std_end = float(params.get_param('custom_hr_attendance.standard_shift_end', '17.0'))
        except Exception:
            std_end = 17.0

        try:
            std_lunch_start = float(params.get_param('custom_hr_attendance.standard_lunch_start', '12.0'))
        except Exception:
            std_lunch_start = 12.0

        try:
            std_lunch_duration = float(params.get_param('custom_hr_attendance.standard_lunch_duration', '1.0'))
        except Exception:
            std_lunch_duration = 1.0

        start_str = self._float_to_time_str(std_start)
        end_str = self._float_to_time_str(std_end)
        l_start = self._float_to_time_str(std_lunch_start)
        l_end = self._float_to_time_str(std_lunch_start + std_lunch_duration)
        lunch_str = f"{l_start} - {l_end} ({std_lunch_duration:.1f}h)"

        return {
            'name': 'Default Global Shift',
            'code': 'GLOBAL',
            'time_range': f"{start_str} - {end_str}",
            'start_time_str': start_str,
            'end_time_str': end_str,
            'is_night_shift': False,
            'has_lunch_break': True,
            'lunch_time_str': lunch_str,
            'is_custom_exception': False,
            'is_day_off': False,
            'source_label': 'Default Global Shift'
        }

    def _enrich_attendance_data(self, employee, data):
        if not employee or not data:
            return data

        data['job_title'] = employee.job_title or (employee.job_id.name if employee.job_id else "") or ""
        data['department_name'] = employee.department_id.name if employee.department_id else ""
        data['shift_info'] = self._get_employee_shift_info(employee)

        today = fields.Date.context_today(request.env.user)
        # Week starts on Monday
        start_of_week = today - datetime.timedelta(days=today.weekday())
        end_of_week = start_of_week + datetime.timedelta(days=6)

        # Month calculation
        start_of_month = today.replace(day=1)
        if today.month == 12:
            next_month = today.replace(year=today.year + 1, month=1, day=1)
        else:
            next_month = today.replace(month=today.month + 1, day=1)
        end_of_month = next_month - datetime.timedelta(days=1)

        search_start_date = min(start_of_week, start_of_month) - datetime.timedelta(days=1)
        search_end_date = max(end_of_week, end_of_month) + datetime.timedelta(days=1)

        tz_name = request.env.user.tz or 'UTC'
        try:
            local_tz = pytz.timezone(tz_name)
        except Exception:
            local_tz = pytz.utc

        search_start_utc = local_tz.localize(
            datetime.datetime.combine(search_start_date, datetime.time.min)
        ).astimezone(pytz.utc).replace(tzinfo=None)
        search_end_utc = local_tz.localize(
            datetime.datetime.combine(search_end_date, datetime.time.max)
        ).astimezone(pytz.utc).replace(tzinfo=None)

        attendances = request.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', search_start_utc),
            ('check_in', '<=', search_end_utc)
        ], order='check_in asc')

        day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        daily_hours = {d: 0.0 for d in range(7)}
        daily_checked_in = {d: False for d in range(7)}

        total_weekly_hours = 0.0
        total_monthly_hours = 0.0
        today_completed_hours = 0.0
        weekly_completed_hours = 0.0
        monthly_completed_hours = 0.0

        for att in attendances:
            check_in_local_dt = fields.Datetime.context_timestamp(employee, att.check_in)
            check_in_local_date = check_in_local_dt.date()

            in_week = (start_of_week <= check_in_local_date <= end_of_week)
            in_month = (start_of_month <= check_in_local_date <= end_of_month)

            if not (in_week or in_month):
                continue

            day_idx = check_in_local_dt.weekday()
            is_today_att = (check_in_local_date == today)

            if att.check_out:
                duration = att.worked_hours or 0.0
                if is_today_att:
                    today_completed_hours += duration
                if in_week:
                    weekly_completed_hours += duration
                if in_month:
                    monthly_completed_hours += duration
            else:
                now_dt = fields.Datetime.context_timestamp(employee, fields.Datetime.now())
                # For Normal check-in (snapped to shift start), payable live timer starts from official check_in
                live_ref_dt = att.check_in if (att.check_in_status == 'Normal' and att.check_in) else (att.actual_check_in or att.check_in)
                live_start_dt = fields.Datetime.context_timestamp(employee, live_ref_dt)
                if now_dt >= live_start_dt:
                    duration = max(0.0, (now_dt - live_start_dt).total_seconds() / 3600.0)
                else:
                    duration = 0.0
                if in_week:
                    daily_checked_in[day_idx] = True

            if in_week:
                daily_hours[day_idx] += duration
            if in_month:
                total_monthly_hours += duration

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

            day_shift = self._get_employee_shift_info(employee, target_date=cur_date)
            is_day_off = day_shift.get('is_day_off', False) if day_shift else False
            is_on_leave = day_shift.get('is_on_leave', False) if day_shift else False
            leave_name = day_shift.get('leave_name', 'Time Off') if day_shift else 'Time Off'

            pct = min(100, int((hrs / 9.0) * 100))

            if is_on_leave and hrs == 0:
                hours_formatted = f"🌴 {leave_name}"
            elif is_day_off and hrs == 0:
                hours_formatted = 'Day Off'
            else:
                hours_formatted = f"{hours_int:02d}h {mins_int:02d}m"

            daily_breakdown.append({
                'day_name': day_names[d],
                'date_str': cur_date.strftime('%b %d'),
                'hours': hrs,
                'hours_formatted': hours_formatted,
                'percentage': pct,
                'is_today': cur_date == today,
                'checked_in': daily_checked_in[d],
                'is_day_off': is_day_off,
                'is_on_leave': is_on_leave,
                'leave_name': leave_name,
            })

        # Format weekly & monthly hours
        wk_hours_int = int(total_weekly_hours)
        wk_mins_int = int(round((total_weekly_hours - wk_hours_int) * 60))
        data['weekly_hours_formatted'] = f"{wk_hours_int:02d}h {wk_mins_int:02d}m"
        data['weekly_hours_float'] = round(total_weekly_hours, 2)

        mo_hours_int = int(total_monthly_hours)
        mo_mins_int = int(round((total_monthly_hours - mo_hours_int) * 60))
        data['monthly_hours_formatted'] = f"{mo_hours_int:02d}h {mo_mins_int:02d}m"
        data['monthly_hours_float'] = round(total_monthly_hours, 2)

        data['daily_breakdown'] = daily_breakdown
        # Send completed hours as float hours so JS can format live timer accurately
        data['hours_today_completed'] = round(today_completed_hours, 6)
        data['hours_weekly_completed'] = round(weekly_completed_hours, 6)
        data['hours_monthly_completed'] = round(monthly_completed_hours, 6)
        data['hours_today'] = round(today_completed_hours, 6)

        # Determine real-time check-in state directly from active open attendance record
        open_att = request.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_out', '=', False)
        ], order='check_in desc', limit=1)

        if open_att and open_att.check_in:
            data['attendance_state'] = 'checked_in'
            # For Normal check-in snapped to official shift start, timer starts from official check_in
            live_check_in = open_att.check_in if (open_att.check_in_status == 'Normal' and open_att.check_in) else (open_att.actual_check_in or open_att.check_in)
            data['check_in_raw'] = fields.Datetime.to_string(live_check_in).replace(' ', 'T') + 'Z'
            check_in_local = fields.Datetime.context_timestamp(employee, open_att.check_in)
            data['check_in_time_str'] = check_in_local.strftime('%I:%M %p')

            # Dynamic Shift Punctuality Check (Shift-Specific)
            check_in_date = check_in_local.date()
            shift_info = self._get_employee_shift_info(employee, check_in_date)
            shift_start = shift_info.get('start_time', 8.0) if shift_info else 8.0

            check_in_float = check_in_local.hour + (check_in_local.minute / 60.0)
            data['check_in_status'] = open_att.check_in_status or ('Late' if check_in_float > (shift_start + dead_time) else 'Normal')
        else:
            data['attendance_state'] = 'checked_out'
            data['check_in_raw'] = False
            data['check_in_time_str'] = False
            data['check_in_status'] = False

        # Dual-Session Status Breakdown for Today
        now_dt = fields.Datetime.context_timestamp(employee, fields.Datetime.now())
        current_float = now_dt.hour + (now_dt.minute / 60.0) + (now_dt.second / 3600.0)
        today_shift = self._get_employee_shift_info(employee, target_date=today)
        has_lunch = today_shift.get('has_lunch_break', False) if today_shift else False

        today_start_utc = local_tz.localize(datetime.datetime.combine(today, datetime.time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        today_end_utc = local_tz.localize(datetime.datetime.combine(today, datetime.time.max)).astimezone(pytz.utc).replace(tzinfo=None)

        today_atts = request.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', today_start_utc),
            ('check_in', '<=', today_end_utc)
        ], order='check_in asc')

        sessions_info = []
        if today_shift and today_shift.get('is_on_leave') and not today_shift.get('is_half_day_leave'):
            l_name = today_shift.get('leave_name', 'Time Off')
            sessions_info = [
                {
                    'session_name': 'Morning Session',
                    'icon': 'fa-sun-o',
                    'time_range': '08:00 - 12:00',
                    'status': 'leave',
                    'badge': f"Approved Time Off ({l_name})"
                },
                {
                    'session_name': 'Afternoon Session',
                    'icon': 'fa-cloud-sun-o',
                    'time_range': '13:00 - 17:00',
                    'status': 'leave',
                    'badge': f"Approved Time Off ({l_name})"
                }
            ]
        elif has_lunch and not today_shift.get('is_day_off'):
            m_start = today_shift.get('start_time', 8.0)
            m_end = today_shift.get('lunch_out_time', 12.0)
            a_start = m_end + today_shift.get('lunch_duration', 1.0)
            a_end = today_shift.get('end_time', 17.0)

            enable_checkin_restriction = request.env['ir.config_parameter'].sudo().get_param(
                'hr_attendance.enable_checkin_restriction', 'True').lower() in ('true', '1')
            dead_time = float(request.env['ir.config_parameter'].sudo().get_param('hr_attendance.dead_time', 0.50))
            checkin_grace = float(request.env['ir.config_parameter'].sudo().get_param('hr_attendance.checkin_grace_period', 0.25))

            m_cutoff = m_start + checkin_grace + dead_time
            a_cutoff = a_start + dead_time

            # Morning Session Check
            m_att = today_atts.filtered(lambda a: (a.shift_end_float and a.shift_end_float <= (m_end + 0.1)) or (a.check_in and fields.Datetime.context_timestamp(employee, a.check_in).hour < int(m_end)))
            if m_att:
                m_att = m_att[0]
                if m_att.check_out:
                    m_status = 'completed'
                    m_badge = f"Completed ({m_att.worked_hours:.2f}h)"
                else:
                    m_status = 'active'
                    m_badge = "Active (Live)"
            else:
                if enable_checkin_restriction and current_float > m_cutoff:
                    m_status = 'absent'
                    m_badge = "Window Closed (Missed)"
                elif current_float >= m_end:
                    m_status = 'absent'
                    m_badge = "Absent (Missed)"
                elif current_float >= (m_start - 0.50):
                    m_status = 'ready'
                    m_badge = "Ready to Check In"
                else:
                    m_status = 'upcoming'
                    m_badge = "Upcoming"

            # Afternoon Session Check
            a_att = today_atts.filtered(lambda a: (a.shift_start_float and a.shift_start_float >= (m_end - 0.1)) or (a.check_in and fields.Datetime.context_timestamp(employee, a.check_in).hour >= int(m_end)))
            if a_att:
                a_att = a_att[0]
                if a_att.check_out:
                    a_status = 'completed'
                    a_badge = f"Completed ({a_att.worked_hours:.2f}h)"
                else:
                    a_status = 'active'
                    a_badge = "Active (Live)"
            else:
                if enable_checkin_restriction and current_float > a_cutoff:
                    a_status = 'absent'
                    a_badge = "Window Closed (Missed)"
                elif current_float >= a_end:
                    a_status = 'absent'
                    a_badge = "Absent (Missed)"
                elif current_float >= (a_start - 0.25):
                    a_status = 'ready'
                    a_badge = "Ready to Check In"
                else:
                    a_status = 'upcoming'
                    a_badge = "Upcoming"

            m_start_fmt = f"{int(m_start):02d}:{int(round((m_start % 1) * 60)):02d}"
            m_end_fmt = f"{int(m_end):02d}:{int(round((m_end % 1) * 60)):02d}"
            a_start_fmt = f"{int(a_start):02d}:{int(round((a_start % 1) * 60)):02d}"
            a_end_fmt = f"{int(a_end):02d}:{int(round((a_end % 1) * 60)):02d}"

            sessions_info = [
                {
                    'session_name': 'Morning Session',
                    'icon': 'fa-sun-o',
                    'time_range': f"{m_start_fmt} - {m_end_fmt}",
                    'status': m_status,
                    'badge': m_badge
                },
                {
                    'session_name': 'Afternoon Session',
                    'icon': 'fa-cloud-sun-o',
                    'time_range': f"{a_start_fmt} - {a_end_fmt}",
                    'status': a_status,
                    'badge': a_badge
                }
            ]
        data['today_sessions'] = sessions_info

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
                'enable_checkin_grace': _bool('hr_attendance.enable_checkin_grace', True),
                'checkin_grace_period': _float('hr_attendance.checkin_grace_period', 0.25),
                'enable_checkout_restriction': _bool('hr_attendance.enable_checkout_restriction', True),
                'enable_saturday_halfday': _bool('hr_attendance.enable_saturday_halfday', True),
                'saturday_halfday_district': _bool('hr_attendance.saturday_halfday_district', True),
                'enable_lunch_break': _bool('hr_attendance.enable_lunch_break', False),
                'enable_auto_absence': _bool('hr_attendance.enable_auto_absence', True),
                'enable_checkin_gate': _bool('hr_attendance.enable_checkin_gate', False),
                'morning_time': _float('hr_attendance.morning_time', 8.0),
                'exit_time': _float('hr_attendance.exit_time', 17.0),
                'dead_time': _float('hr_attendance.dead_time', 0.33),
                'checkin_buffer': _float('hr_attendance.checkin_buffer', 0.5),
                'post_shift_grace_hours': _float('hr_attendance.post_shift_grace_hours', 3.0),
                'saturday_exit_time': _float('hr_attendance.saturday_exit_time', 12.0),
                'lunch_out_time': _float('hr_attendance.lunch_out_time', 12.0),
                'lunch_duration': _float('hr_attendance.lunch_duration', 1.0),
                'lunch_grace_time': _float('hr_attendance.lunch_grace_time', 0.25),
                'lateness_hours_violation_threshold': _float('hr_attendance.lateness_hours_violation_threshold', 4.0),
                'lateness_eval_window_months': _int('hr_attendance.lateness_eval_window_months', 3),
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
            'enable_checkin_restriction', 'enable_checkin_grace', 'enable_checkout_restriction',
            'enable_saturday_halfday', 'saturday_halfday_district',
            'enable_lunch_break', 'enable_auto_absence', 'enable_checkin_gate',
        ]
        float_keys = [
            'morning_time', 'exit_time', 'checkin_grace_period', 'dead_time', 'checkin_buffer',
            'post_shift_grace_hours', 'saturday_exit_time',
            'lunch_out_time', 'lunch_duration', 'lunch_grace_time',
            'lateness_hours_violation_threshold'
        ]
        int_keys = [
            'lateness_eval_window_months', 'force_checkout_violation_threshold'
        ]
        for key in bool_keys:
            if key in settings:
                params.set_param(f'hr_attendance.{key}', str(bool(settings[key])))
        for key in float_keys:
            if key in settings:
                params.set_param(f'hr_attendance.{key}', str(round(float(settings[key]), 2)))
        for key in int_keys:
            if key in settings:
                params.set_param(f'hr_attendance.{key}', str(int(settings[key])))
        return {'status': 'success'}
