# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import datetime
import pytz

class MyShiftSchedule(models.TransientModel):
    _name = 'my.shift.schedule'
    _description = 'My Current Shift Schedule'

    employee_id = fields.Many2one('hr.employee', string="Employee Name", readonly=True)
    job_position = fields.Char(string="Job Position", readonly=True)
    department_id = fields.Many2one('hr.department', string="Department", readonly=True)
    operating_unit_id = fields.Many2one('operating.unit', string="Operating Unit / Branch", readonly=True)
    
    assignment_source = fields.Selection([
        ('leave', 'Approved Time Off'),
        ('roster', 'Job Position Roster Exception'),
        ('job_position', 'Job Position Exception'),
        ('location', 'Location Based Exception'),
        ('default', 'Default System Shift'),
    ], string="Shift Assignment Source", readonly=True)
    
    schedule_name = fields.Char(string="Schedule Name", readonly=True)
    shift_id = fields.Many2one('job.shift', string="Shift Definition", readonly=True)
    
    start_time = fields.Float(string="Start Time", readonly=True)
    end_time = fields.Float(string="End Time", readonly=True)
    duration = fields.Float(string="Net Worked Duration (Hours)", readonly=True)
    time_range = fields.Char(string="Time Range", readonly=True)
    
    has_lunch_break = fields.Boolean(string="Includes Lunch Break", readonly=True)
    lunch_start_time = fields.Float(string="Lunch Start Time", readonly=True)
    lunch_duration = fields.Float(string="Lunch Duration (Hours)", readonly=True)
    lunch_time_range = fields.Char(string="Lunch Time Range", readonly=True)

    start_date = fields.Date(string="Start Date", readonly=True)
    end_date = fields.Date(string="End Date", readonly=True)

    roster_line_ids = fields.One2many(
        'my.shift.schedule.line',
        'schedule_id',
        string="Weekly Roster Schedule",
        readonly=True
    )

    @api.model
    def action_open_my_shift(self):
        """
        Resolves the logged-in user's active shift hierarchy
        and opens a clean My Shift Schedule transient view with full weekly roster details.
        """
        user = self.env.user
        employee = user.employee_id or self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        today = fields.Date.context_today(self)

        def _fmt(f_val):
            val = float(f_val or 0.0) % 24.0
            h = int(val)
            m = int(round((val - h) * 60))
            if m >= 60:
                h = (h + 1) % 24
                m = 0
            return f"{h:02d}:{m:02d}"

        # Clean old transient records created by this user
        self.sudo().search([('create_uid', '=', self.env.uid)]).unlink()

        assignment_source = 'default'
        schedule_name = ""
        shift_obj = False
        start_time = 8.0
        end_time = 17.0
        duration = 8.0
        time_range = "08:00 - 17:00"
        start_date = today
        end_date = False
        roster_lines_vals = []

        if employee:
            # Priority 0: Approved Time Off / Leave (hr.leave)
            leave = self.env['hr.leave'].sudo().search([
                ('employee_id', '=', employee.id),
                ('state', '=', 'validate'),
                ('date_from', '<=', datetime.datetime.combine(today, datetime.time.max)),
                ('date_to', '>=', datetime.datetime.combine(today, datetime.time.min)),
            ], limit=1)

            if leave:
                assignment_source = 'leave'
                l_name = leave.holiday_status_id.name or _('Time Off')
                if isinstance(l_name, dict):
                    l_name = l_name.get('en_US', list(l_name.values())[0]) if l_name else _('Time Off')
                s_d = getattr(leave, 'request_date_from', False) or getattr(leave, 'leave_start_date', False) or (leave.date_from.date() if leave.date_from else today)
                e_d = getattr(leave, 'request_date_to', False) or getattr(leave, 'leave_end_date', False) or (leave.date_to.date() if leave.date_to else today)
                schedule_name = _("Approved Time Off - %s") % l_name
                start_date = s_d
                end_date = e_d
                shift_obj = False
                start_time = 0.0
                end_time = 0.0
                duration = 0.0
                time_range = _("On Approved Time Off")
                lunch_time_range = _("On Approved Time Off")

            else:
                # Priority 1: Job Position Roster Exception (Date-based)
                roster = self.env['job.position.roster.exception'].sudo().search([
                    ('employee_id', '=', employee.id),
                    ('active', '=', True),
                    ('start_date', '<=', today),
                    ('end_date', '>=', today)
                ], order='start_date desc, id desc', limit=1)

                if roster:
                    assignment_source = 'roster'
                    schedule_name = roster.name or _('Job Position Roster Exception')
                    today_line = roster.line_ids.filtered(lambda l: l.date == today)[:1]
                    if today_line:
                        if today_line.schedule_type == 'day_off':
                            schedule_name = _("%s (Day Off Today)") % (roster.name or _('Roster'))
                            shift_obj = False
                        else:
                            shift_obj = today_line.shift_id
                    else:
                        shift_obj = False
                    start_date = roster.start_date
                    end_date = roster.end_date

                    # Build all weekly schedule lines for display
                    for l in roster.line_ids.sorted(key=lambda r: r.date or fields.Date.today()):
                        l_time_range = _("Day Off")
                        l_duration = 0.0
                        l_lunch = _("No Lunch Break")
                        if l.schedule_type == 'shift' and l.shift_id:
                            s_time = l.shift_id.start_time
                            e_time = l.shift_id.end_time
                            gross = e_time - s_time
                            if gross < 0:
                                gross += 24.0
                            l_duration = max(0.0, round(gross - (l.shift_id.lunch_duration if l.shift_id.has_lunch_break else 0.0), 2))
                            l_time_range = l.shift_id.time_range or f"{_fmt(s_time)} - {_fmt(e_time)}"
                            if l.shift_id.has_lunch_break:
                                l_end = l.shift_id.lunch_start_time + l.shift_id.lunch_duration
                                l_lunch = f"{_fmt(l.shift_id.lunch_start_time)} - {_fmt(l_end)} ({l.shift_id.lunch_duration:.1f}h)"
                            else:
                                l_lunch = _("No Lunch Break")

                        roster_lines_vals.append((0, 0, {
                            'date': l.date,
                            'day_name': l.day_name or (l.date.strftime('%A') if l.date else ''),
                            'schedule_type': l.schedule_type,
                            'shift_id': l.shift_id.id if l.shift_id else False,
                            'time_range': l_time_range,
                            'duration': l_duration,
                            'lunch_time_range': l_lunch,
                            'is_today': (l.date == today),
                        }))

                else:
                    # Priority 2: Job Position Exception (Static)
                    job_ex = self.env['job.position.exception'].sudo().search([
                        ('employee_id', '=', employee.id),
                        ('active', '=', True),
                        ('start_date', '<=', today),
                        '|', ('end_date', '=', False), ('end_date', '>=', today)
                    ], order='start_date desc, id desc', limit=1)

                    if job_ex:
                        assignment_source = 'job_position'
                        schedule_name = job_ex.job_position_exception_name or _('Job Position Exception')
                        shift_obj = job_ex.shift_id
                        start_date = job_ex.start_date
                        end_date = job_ex.end_date

                    else:
                        # Priority 3: Location Based Exception (Branch / Operating Unit)
                        if employee.default_operating_unit_id:
                            ou_ids = [employee.default_operating_unit_id.id]
                            if hasattr(employee.default_operating_unit_id, 'parent_unit') and employee.default_operating_unit_id.parent_unit:
                                ou_ids.append(employee.default_operating_unit_id.parent_unit.id)

                            loc_ex = self.env['location.based.exception'].sudo().search([
                                '|', ('operating_unit_ids', 'in', ou_ids),
                                     ('operating_unit', 'in', ou_ids),
                                ('active', '=', True),
                                ('start_date', '<=', today),
                                '|', ('end_date', '=', False), ('end_date', '>=', today)
                            ], order='start_date desc, id desc', limit=1)

                            if loc_ex:
                                assignment_source = 'location'
                                schedule_name = loc_ex.schedule_name or _('Location Based Exception')
                                shift_obj = loc_ex.shift_id
                                start_date = loc_ex.start_date
                                end_date = loc_ex.end_date

        has_lunch_break = False
        lunch_start_time = 12.0
        lunch_duration = 1.0
        lunch_time_range = _("No Lunch Break")

        if shift_obj:
            start_time = shift_obj.start_time
            end_time = shift_obj.end_time
            has_lunch_break = shift_obj.has_lunch_break
            lunch_start_time = shift_obj.lunch_start_time if has_lunch_break else 0.0
            lunch_duration = shift_obj.lunch_duration if has_lunch_break else 0.0
            gross = end_time - start_time
            if gross < 0:
                gross += 24.0
            duration = max(0.0, round(gross - (lunch_duration if has_lunch_break else 0.0), 2))
            time_range = shift_obj.time_range or f"{_fmt(start_time)} - {_fmt(end_time)}"
            if has_lunch_break:
                l_end = lunch_start_time + lunch_duration
                lunch_time_range = f"{_fmt(lunch_start_time)} - {_fmt(l_end)} ({lunch_duration:.1f}h)"
            else:
                lunch_time_range = _("No Lunch Break")
        elif assignment_source == 'leave':
            start_time = 0.0
            end_time = 0.0
            duration = 0.0
            has_lunch_break = False
            lunch_start_time = 0.0
            lunch_duration = 0.0
            time_range = _("On Approved Time Off")
            lunch_time_range = _("On Approved Time Off")
        elif assignment_source == 'roster':
            start_time = 0.0
            end_time = 0.0
            duration = 0.0
            time_range = _("Day Off")
            lunch_time_range = _("Day Off")
        elif assignment_source == 'default':
            ICP = self.env['ir.config_parameter'].sudo()
            start_time = float(ICP.get_param('hr_attendance.morning_time', '8.0'))
            end_time = float(ICP.get_param('hr_attendance.exit_time', '17.0'))
            has_lunch_break = ICP.get_param('hr_attendance.enable_lunch_break', 'False').lower() in ('true', '1')
            lunch_start_time = float(ICP.get_param('hr_attendance.lunch_out_time', '12.0'))
            lunch_duration = float(ICP.get_param('hr_attendance.lunch_duration', '1.0')) if has_lunch_break else 0.0
            gross = end_time - start_time
            if gross < 0:
                gross += 24.0
            duration = max(0.0, round(gross - (lunch_duration if has_lunch_break else 0.0), 2))
            time_range = f"{_fmt(start_time)} - {_fmt(end_time)}"
            schedule_name = _("Default System Shift (%s - %s)") % (_fmt(start_time), _fmt(end_time))
            if has_lunch_break:
                l_end = lunch_start_time + lunch_duration
                lunch_time_range = f"{_fmt(lunch_start_time)} - {_fmt(l_end)} ({lunch_duration:.1f}h)"
            else:
                lunch_time_range = _("No Lunch Break")

        rec = self.sudo().create({
            'employee_id': employee.id if employee else False,
            'job_position': (employee.job_title or (employee.job_id.name if employee.job_id else '')) if employee else 'System Administrator',
            'department_id': (employee.department_id.id if employee.department_id else False) if employee else False,
            'operating_unit_id': (employee.default_operating_unit_id.id if employee.default_operating_unit_id else False) if employee else False,
            'assignment_source': assignment_source,
            'schedule_name': schedule_name,
            'shift_id': shift_obj.id if shift_obj else False,
            'start_time': start_time,
            'end_time': end_time,
            'duration': duration,
            'time_range': time_range,
            'has_lunch_break': has_lunch_break,
            'lunch_start_time': lunch_start_time,
            'lunch_duration': lunch_duration,
            'lunch_time_range': lunch_time_range,
            'start_date': start_date,
            'end_date': end_date,
            'roster_line_ids': roster_lines_vals,
        })

        return {
            'type': 'ir.actions.act_window',
            'name': _('My Shift Schedule'),
            'res_model': 'my.shift.schedule',
            'res_id': rec.id,
            'view_mode': 'form',
            'target': 'current',
        }


class MyShiftScheduleLine(models.TransientModel):
    _name = 'my.shift.schedule.line'
    _description = 'My Shift Schedule Line'
    _order = 'date asc, id asc'

    schedule_id = fields.Many2one('my.shift.schedule', ondelete='cascade')
    date = fields.Date(string="Date", readonly=True)
    day_name = fields.Char(string="Day of Week", readonly=True)
    schedule_type = fields.Selection([
        ('shift', 'Assigned Shift'),
        ('day_off', 'Day Off')
    ], string="Schedule Type", readonly=True)
    shift_id = fields.Many2one('job.shift', string="Assigned Shift", readonly=True)
    time_range = fields.Char(string="Working Hours", readonly=True)
    duration = fields.Float(string="Duration (Hours)", readonly=True)
    lunch_time_range = fields.Char(string="Lunch Break", readonly=True)
    is_today = fields.Boolean(string="Is Today", readonly=True)
