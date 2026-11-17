# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import datetime
import pytz


class HrAttendanceManualWizard(models.TransientModel):
    """
    Enhanced Manual Attendance Creation Wizard.
    Supports 3 modes:
    1. Individual Entry (Single employee, single date, check-in, check-out, or both)
    2. Batch Entry (Operating Unit employees, date range, lunch break splitting, Coach approval for >3 days)
    3. Finacle EOD Rest Entry (Morning OFF, Afternoon OFF, Full Day OFF for bank ops staff & drivers)
    """
    _name = 'hr.attendance.manual.wizard'
    _description = 'Manual Attendance Entry Wizard'
    entry_type = fields.Selection([
        ('individual', 'Individual Employee (Single Day)'),
        ('batch', 'Batch Operating Unit (Multi-Day / Outage)'),
    ], string='Entry Mode', default='individual', required=True)

    is_hr_admin = fields.Boolean(
        string='Is HR Admin',
        compute='_compute_is_hr_admin',
    )

    def _compute_is_hr_admin(self):
        is_admin = self.env.user.has_group('hr_attendance.group_hr_attendance_manager') or self.env.user.has_group('base.group_system')
        for rec in self:
            rec.is_hr_admin = is_admin

    # --- Individual Mode Fields ---
    attendance_mode = fields.Selection([
        ('check_in', 'Check-In Only'),
        ('check_out', 'Check-Out Only'),
        ('both', 'Both (Check-In & Check-Out)'),
    ], string='Attendance Action')

    @api.model
    def _get_default_employee(self):
        return False

    @api.model
    def _get_employee_domain(self):
        user = self.env.user
        emp = user.employee_id
        if not emp:
            emp = self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        self_emp_id = emp.id if emp else False

        if user.has_group('hr_attendance.group_hr_attendance_manager') or user.has_group('base.group_system'):
            # Administrator can see all active employees EXCEPT themselves
            if self_emp_id:
                return ['&', ('active', '=', True), ('id', '!=', self_emp_id)]
            return [('active', '=', True)]

        if emp:
            return ['&', '&', ('active', '=', True), ('id', '!=', self_emp_id), '|', '|',
                ('coach_id', '=', emp.id),
                ('parent_id', '=', emp.id),
                ('attendance_manager_id', '=', user.id)
            ]
        return [('id', '=', False)]

    @api.model
    def _get_batch_employee_domain(self):
        user = self.env.user
        emp = user.employee_id
        if not emp:
            emp = self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        self_emp_id = emp.id if emp else False

        if user.has_group('hr_attendance.group_hr_attendance_manager') or user.has_group('base.group_system'):
            if self_emp_id:
                return ['&', ('active', '=', True), ('id', '!=', self_emp_id)]
            return [('active', '=', True)]

        if emp:
            return ['&', '&', ('active', '=', True), ('id', '!=', self_emp_id), '|', '|',
                ('coach_id', '=', emp.id),
                ('parent_id', '=', emp.id),
                ('attendance_manager_id', '=', user.id)
            ]
        return [('id', '=', False)]

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

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        default=_get_default_employee,
        domain=lambda self: self._get_employee_domain(),
    )
    work_date = fields.Date(
        string='Attendance Date',
        default=fields.Date.context_today,
    )
    detected_shift_name = fields.Char(
        string='Detected Shift Name',
        readonly=True
    )
    detected_shift_info = fields.Char(
        string='Detected Shift',
        readonly=True
    )
    target_session = fields.Selection([
        ('morning', 'Morning Session'),
        ('afternoon', 'Afternoon Session'),
        ('full_day', 'Full Day'),
    ], string='Target Session', default='morning')
    check_in_time = fields.Float(
        string='Check-In Time',
        help='Check-in time (e.g. 8.0 = 08:00 AM)',
    )
    check_out_time = fields.Float(
        string='Check-Out Time',
        help='Check-out time (e.g. 17.0 = 05:00 PM)',
    )

    # --- Batch & Finacle Rest Fields ---
    @api.model
    def _get_default_operating_unit(self):
        emp = self.env.user.employee_id
        if emp and emp.default_operating_unit_id:
            return emp.default_operating_unit_id.id
        return False

    operating_unit_id = fields.Many2one(
        'operating.unit',
        string='Operating Unit',
        default=_get_default_operating_unit,
    )
    
    employee_ids = fields.Many2many(
        'hr.employee',
        'manual_wiz_emp_rel',
        'wiz_id',
        'emp_id',
        string='Employees',
        domain=lambda self: self._get_batch_employee_domain(),
    )

    start_date = fields.Date(
        string='Start Date',
        default=fields.Date.context_today,
    )
    end_date = fields.Date(
        string='End Date',
        default=fields.Date.context_today,
    )
    duration_days = fields.Integer(
        string='Duration (Days)',
        compute='_compute_duration_days',
        store=True,
    )


    use_employee_shifts = fields.Boolean(
        string='Use Individual Assigned Shifts & Lunch Splits',
        default=True,
    )
    overwrite_existing = fields.Boolean(
        string='Overwrite Existing Attendances',
        default=False,
        help='If checked, existing attendances for selected employees on target dates will be replaced.',
    )
    check_in_time_only = fields.Float(string='Default Check-In Time', default=8.0)
    check_out_time_only = fields.Float(string='Default Check-Out Time', default=17.0)

    # --- Common Fields ---
    justification = fields.Text(
        string='Reason / Justification',
        required=True,
        help='Mandatory explanation for manual attendance entry.',
    )
    attendance_reason_ids = fields.Many2many(
        'hr.attendance.reason',
        string='Attendance Reasons',
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        emp_id = res.get('employee_id') or self._get_default_employee()
        target_date = res.get('work_date') or fields.Date.context_today(self)
        if emp_id:
            emp = self.env['hr.employee'].browse(emp_id)
            if emp.exists():
                shift_info = emp._get_employee_shift_info(target_date=target_date)
                if shift_info and not shift_info.get('is_day_off'):
                    s_start = shift_info.get('start_time', 8.0)
                    s_end = shift_info.get('end_time', 17.0)
                    s_name = shift_info.get('name', 'Standard Shift')
                    res['detected_shift_name'] = s_name
                    res['detected_shift_info'] = f"{s_name} ({self._float_to_time_str(s_start)} - {self._float_to_time_str(s_end)})"
                else:
                    res['detected_shift_name'] = 'Default Global Shift'
                    res['detected_shift_info'] = 'Default Global Shift (08:00 AM - 05:00 PM)'
        return res

    @api.depends('start_date', 'end_date')
    def _compute_duration_days(self):
        for rec in self:
            if rec.start_date and rec.end_date:
                rec.duration_days = (rec.end_date - rec.start_date).days + 1
            else:
                rec.duration_days = 0

    @api.onchange('operating_unit_id')
    def _onchange_operating_unit_id(self):
        if self.operating_unit_id:
            emp = self.env.user.employee_id or self.env['hr.employee'].sudo().search([('user_id', '=', self.env.uid)], limit=1)
            domain = [
                ('default_operating_unit_id', '=', self.operating_unit_id.id),
                ('active', '=', True)
            ]
            if emp:
                domain = ['&'] + domain + [('id', '!=', emp.id)]
            emps = self.env['hr.employee'].search(domain)
            self.employee_ids = [(6, 0, emps.ids)]

    def _analyze_existing_sessions(self, employee, target_date):
        """
        Analyzes existing closed attendance records for the given employee on target_date.
        Returns a dict:
        {
            'has_morning': bool,
            'has_afternoon': bool,
            'has_full_day': bool,
            'is_day_complete': bool,
            'records': recordset,
        }
        """
        if not employee or not target_date:
            return {
                'has_morning': False,
                'has_afternoon': False,
                'has_full_day': False,
                'is_day_complete': False,
                'records': self.env['hr.attendance'],
            }

        import pytz
        eat_tz = pytz.timezone('Africa/Addis_Ababa')

        records = self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee.id),
            ('work_date', '=', target_date),
            ('check_out', '!=', False),
        ])

        has_morning = False
        has_afternoon = False
        has_full_day = False

        for rec in records:
            if not rec.check_in or not rec.check_out:
                continue
            dt_in = rec.check_in.astimezone(eat_tz) if rec.check_in.tzinfo else pytz.utc.localize(rec.check_in).astimezone(eat_tz)
            in_hour = dt_in.hour + (dt_in.minute / 60.0)

            dt_out = rec.check_out.astimezone(eat_tz) if rec.check_out.tzinfo else pytz.utc.localize(rec.check_out).astimezone(eat_tz)
            out_hour = dt_out.hour + (dt_out.minute / 60.0)

            s_start = rec.shift_start_float or in_hour
            s_end = rec.shift_end_float or out_hour

            if in_hour < 12.5 and out_hour > 13.5:
                has_full_day = True
                has_morning = True
                has_afternoon = True
            elif s_start >= 12.5 or in_hour >= 12.5:
                has_afternoon = True
            else:
                has_morning = True

        return {
            'has_morning': has_morning,
            'has_afternoon': has_afternoon,
            'has_full_day': has_full_day,
            'is_day_complete': bool(has_full_day or (has_morning and has_afternoon)),
            'records': records,
        }

    @api.onchange('employee_id', 'work_date', 'entry_type', 'attendance_mode', 'target_session')
    def _onchange_employee_work_date(self):
        if self.entry_type == 'individual' and self.employee_id:
            target_date = self.work_date or fields.Date.context_today(self)
            shift_info = self.employee_id._get_employee_shift_info(target_date=target_date)

            if shift_info and shift_info.get('is_day_off'):
                s_name = shift_info.get('name', 'Scheduled Day Off')
                s_start = 8.0
                s_end = 17.0
                has_lunch = False
                lunch_start = 12.0
                lunch_dur = 1.0
                afternoon_start = 13.0
                self.detected_shift_name = s_name
                self.detected_shift_info = f"{s_name} - DAY OFF / REST DAY"
            elif shift_info:
                s_start = shift_info.get('start_time', 8.0)
                s_end = shift_info.get('end_time', 17.0)
                has_lunch = shift_info.get('has_lunch_break', False)
                lunch_start = shift_info.get('lunch_out_time', 12.0)
                lunch_dur = shift_info.get('lunch_duration', 1.0)
                afternoon_start = lunch_start + lunch_dur
                s_name = shift_info.get('name', 'Standard Shift')
                self.detected_shift_name = s_name
                self.detected_shift_info = f"{s_name} ({self._float_to_time_str(s_start)} - {self._float_to_time_str(s_end)})"
            else:
                s_start = 8.0
                s_end = 17.0
                has_lunch = False
                lunch_start = 12.0
                lunch_dur = 1.0
                afternoon_start = 13.0
                s_name = 'Default Global Shift'
                self.detected_shift_name = s_name
                self.detected_shift_info = f"{s_name} ({self._float_to_time_str(s_start)} - {self._float_to_time_str(s_end)})"

            # Smart Bi-directional Session Detection
            session_status = self._analyze_existing_sessions(self.employee_id, target_date)
            if session_status['is_day_complete']:
                self.detected_shift_info += " [Full Attendance Already Recorded]"
            elif session_status['has_morning'] and not session_status['has_afternoon']:
                self.target_session = 'afternoon'
            elif session_status['has_afternoon'] and not session_status['has_morning']:
                self.target_session = 'morning'

            # Resolve session timings based on target_session
            if self.target_session == 'afternoon':
                session_start = afternoon_start if (has_lunch and afternoon_start) else 13.0
                session_end = s_end if s_end > 13.0 else 17.0
            elif self.target_session == 'morning':
                session_start = s_start
                session_end = lunch_start if has_lunch else (s_end if s_end <= 13.0 else 12.0)
            else:
                session_start = s_start
                session_end = s_end

            # Find active open check-in on that date or open check-in in general
            open_att = self.env['hr.attendance'].sudo().search([
                ('employee_id', '=', self.employee_id.id),
                ('work_date', '=', target_date),
                ('check_out', '=', False),
            ], order='check_in desc', limit=1)
            if not open_att:
                open_att = self.env['hr.attendance'].sudo().search([
                    ('employee_id', '=', self.employee_id.id),
                    ('check_out', '=', False),
                ], order='check_in desc', limit=1)

            if not self.attendance_mode:
                self.check_in_time = False
                self.check_out_time = False
                return

            if self.attendance_mode == 'both':
                self.check_in_time = session_start
                self.check_out_time = session_end
            elif self.attendance_mode == 'check_in':
                self.check_in_time = session_start
                self.check_out_time = False
            elif self.attendance_mode == 'check_out':
                if open_att and open_att.check_in:
                    local_dt = fields.Datetime.context_timestamp(self.employee_id, open_att.check_in)
                    self.check_in_time = local_dt.hour + (local_dt.minute / 60.0)
                else:
                    self.check_in_time = session_start
                self.check_out_time = session_end

    @api.constrains('work_date', 'start_date', 'end_date', 'entry_type')
    def _check_back_date(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.entry_type == 'individual' and rec.work_date:
                if rec.work_date > today:
                    raise ValidationError(_('Manual attendance entry can only be created for past dates or today.'))
            elif rec.entry_type == 'batch' and rec.end_date:
                if rec.end_date > today:
                    raise ValidationError(_('Manual attendance batch entry can only be created for past dates or today.'))
                if rec.start_date and rec.end_date < rec.start_date:
                    raise ValidationError(_('End Date cannot be before Start Date.'))

    def _float_time_to_utc_dt(self, target_date, float_time):
        """Converts local EAT date and float time into a UTC Datetime object."""
        if float_time is None or float_time is False:
            return False
        import datetime
        import pytz
        eat_tz = pytz.timezone('Africa/Addis_Ababa')
        
        hours = int(float_time)
        minutes = int(round((float_time - hours) * 60))
        if minutes >= 60:
            hours = (hours + 1) % 24
            minutes = 0
            
        local_dt = eat_tz.localize(datetime.datetime.combine(target_date, datetime.time(hours, minutes)))
        return local_dt.astimezone(pytz.UTC).replace(tzinfo=None)

    def action_create_manual_attendance(self):
        """Main execution action for Individual, Batch, or Finacle Rest entries."""
        self.ensure_one()
        today = fields.Date.context_today(self)

        # ----------------------------------------------------
        # SCENARIO 1: INDIVIDUAL ENTRY
        # ----------------------------------------------------
        if self.entry_type == 'individual':
            if not self.employee_id or not self.work_date:
                raise ValidationError(_('Employee and Attendance Date are required for individual entry.'))

            # Anti-Self Acknowledgement: Users (including Administrators) cannot create/acknowledge manual attendance for themselves
            emp_user = self.employee_id.user_id
            user_emp = self.env.user.employee_id or self.env['hr.employee'].sudo().search([('user_id', '=', self.env.uid)], limit=1)
            if (emp_user and emp_user.id == self.env.uid) or (user_emp and self.employee_id.id == user_emp.id):
                raise ValidationError(_("You cannot create or acknowledge manual attendance for yourself. Even Administrators must have their attendance recorded and acknowledged by another authorized supervisor or administrator."))

            # Direct Coach / Immediate Manager Hierarchy Guard
            user = self.env.user
            is_admin = user.has_group('hr_attendance.group_hr_attendance_manager') or user.has_group('base.group_system')
            user_emp = user.employee_id or self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
            is_direct_coach = bool(user_emp and self.employee_id.coach_id and self.employee_id.coach_id.id == user_emp.id)
            is_immediate_mgr = bool(user_emp and self.employee_id.parent_id and self.employee_id.parent_id.id == user_emp.id)
            is_att_mgr = bool(self.employee_id.attendance_manager_id and self.employee_id.attendance_manager_id.id == user.id)

            if not (is_admin or is_direct_coach or is_immediate_mgr or is_att_mgr):
                direct_sup = self.employee_id.coach_id.name or self.employee_id.parent_id.name or _('their direct coach / immediate supervisor')
                raise ValidationError(_(
                    "You cannot acknowledge attendance for '%(employee)s'. Every manager can only acknowledge their direct employees. "
                    "Only %(employee)s's direct coach or immediate supervisor (%(supervisor)s) is authorized to acknowledge."
                ) % {
                    'employee': self.employee_id.name,
                    'supervisor': direct_sup,
                })

            if not self.attendance_mode:
                raise ValidationError(_('Please select an Attendance Action (Check-In Only, Check-Out Only, or Both).'))

            # Scheduled Day-Off Guard
            shift_info = self.employee_id._get_employee_shift_info(target_date=self.work_date)
            if shift_info and shift_info.get('is_day_off'):
                shift_name = shift_info.get('name', _('Standard Shift'))
                raise ValidationError(_(
                    "The selected date (%(date)s) is a scheduled Day-Off for '%(employee)s' (Shift: %(shift)s). "
                    "Manual attendance cannot be recorded or acknowledged for scheduled rest days."
                ) % {
                    'date': self.work_date,
                    'employee': self.employee_id.name,
                    'shift': shift_name,
                })

            # Prohibit Backdated 'Check-In Only' Mode
            if self.attendance_mode == 'check_in' and self.work_date < today:
                raise ValidationError(_(
                    "Cannot record 'Check-In Only' for a past date (%(date)s). "
                    "Past attendance entries must include both Check-In and Check-Out ('Both' mode) "
                    "to prevent leaving open, unclosed attendance sessions."
                ) % {
                    'date': self.work_date,
                })

            session_status = self._analyze_existing_sessions(self.employee_id, self.work_date)
            if session_status['is_day_complete']:
                raise ValidationError(_(
                    "Employee '%(employee)s' already has complete attendance records for %(date)s (both morning and afternoon sessions)."
                ) % {
                    'employee': self.employee_id.name,
                    'date': self.work_date,
                })

            if session_status['has_morning'] and not session_status['has_afternoon']:
                if self.target_session in ('morning', 'full_day'):
                    raise ValidationError(_(
                        "Employee '%(employee)s' already has a recorded morning attendance for %(date)s. "
                        "Please select 'Afternoon Session' to record afternoon attendance."
                    ) % {
                        'employee': self.employee_id.name,
                        'date': self.work_date,
                    })
                if self.attendance_mode in ('both', 'check_in') and self.check_in_time is not False and self.check_in_time < 12.5:
                    raise ValidationError(_(
                        "Employee '%(employee)s' already has a recorded morning attendance for %(date)s. "
                        "Check-In time must be in the afternoon (after 12:30 PM)."
                    ) % {
                        'employee': self.employee_id.name,
                        'date': self.work_date,
                    })

            if session_status['has_afternoon'] and not session_status['has_morning']:
                if self.target_session in ('afternoon', 'full_day'):
                    raise ValidationError(_(
                        "Employee '%(employee)s' already has a recorded afternoon attendance for %(date)s. "
                        "Please select 'Morning Session' to record morning attendance."
                    ) % {
                        'employee': self.employee_id.name,
                        'date': self.work_date,
                    })
                if self.attendance_mode in ('both', 'check_out') and self.check_out_time is not False and self.check_out_time > 12.5:
                    raise ValidationError(_(
                        "Employee '%(employee)s' already has a recorded afternoon attendance for %(date)s. "
                        "Check-Out time must be before or at lunch (12:30 PM)."
                    ) % {
                        'employee': self.employee_id.name,
                        'date': self.work_date,
                    })

            shift_info = self.employee_id._get_employee_shift_info(target_date=self.work_date)
            shift_start = shift_info.get('start_time', 8.0) if shift_info else 8.0
            shift_end = shift_info.get('end_time', 17.0) if shift_info else 17.0
            has_lunch = shift_info.get('has_lunch_break', False) if shift_info else False
            lunch_start = shift_info.get('lunch_out_time', 12.0) if shift_info else 12.0
            lunch_dur = shift_info.get('lunch_duration', 1.0) if shift_info else 1.0
            afternoon_start = lunch_start + lunch_dur
            lunch_midpoint = (lunch_start + afternoon_start) / 2.0 if has_lunch else 0.0

            # ------------------------------------------------
            # 1.1 CHECK-OUT ONLY (Complete Active Session)
            # ------------------------------------------------
            if self.attendance_mode == 'check_out':
                if self.check_out_time is False or self.check_out_time is None:
                    raise ValidationError(_('Check-Out Time is required for Check-Out Only mode.'))

                open_att = self.env['hr.attendance'].sudo().search([
                    ('employee_id', '=', self.employee_id.id),
                    ('work_date', '=', self.work_date),
                    ('check_out', '=', False),
                ], order='check_in desc', limit=1)

                if not open_att:
                    open_att = self.env['hr.attendance'].sudo().search([
                        ('employee_id', '=', self.employee_id.id),
                        ('check_out', '=', False),
                    ], order='check_in desc', limit=1)

                if not open_att:
                    raise ValidationError(_(
                        "Cannot complete Check-Out: Employee '%s' does not have an active open check-in record for %s."
                    ) % (self.employee_id.name, self.work_date))

                effective_out = self.check_out_time
                if has_lunch and (lunch_start < effective_out < afternoon_start):
                    effective_out = lunch_start

                dt_check_out = self._float_time_to_utc_dt(self.work_date, effective_out)
                if self.work_date > today:
                    raise ValidationError(_('Cannot record Check-Out time for future dates.'))
                if dt_check_out <= open_att.check_in:
                    raise ValidationError(_('Check-Out time must be strictly after the recorded Check-In time (%s).') % fields.Datetime.to_string(open_att.check_in))

                s_end = open_att.shift_end_float or (lunch_start if (has_lunch and effective_out <= lunch_start) else shift_end)
                early_exit_hour = 0.0
                acknowledged_exit = 0.0
                over_time_hour = 0.0
                if effective_out < s_end:
                    early_exit_hour = round(s_end - effective_out, 4)
                    acknowledged_exit = early_exit_hour
                    check_out_status = 'Acknowledged Early Exit'
                else:
                    if effective_out > s_end:
                        over_time_hour = round(effective_out - s_end, 2)
                    check_out_status = 'Acknowledged Check-Out' if self.attendance_reason_ids else 'Manager Manual Check-Out'

                out_mode_val = 'acknowledged' if self.attendance_reason_ids else 'manual'
                open_att.sudo().write({
                    'check_out': dt_check_out,
                    'out_mode': out_mode_val,
                    'check_out_status': check_out_status,
                    'early_exit_hour': early_exit_hour,
                    'acknowledged_exit': acknowledged_exit,
                    'over_time_hour': over_time_hour,
                    'is_acknowledged': True,
                    'acknowledged_by': self.env.user.id,
                    'acknowledged_date': fields.Datetime.now(),
                })
                if self.attendance_reason_ids:
                    open_att.sudo().write({'attendance_reason_ids': [(4, rid) for rid in self.attendance_reason_ids.ids]})

                if over_time_hour > 0 and self.env.get('over.time'):
                    self.env['over.time'].sudo().with_context(skip_past_date_check=True).create({
                        'employee_id': self.employee_id.id,
                        'date': self.work_date,
                        'start_time': s_end,
                        'end_time': self.check_out_time,
                        'over_time_reason': self.justification or _('Manual Attendance Overtime'),
                    })

                if hasattr(open_att, 'message_post'):
                    open_att.message_post(body=_('Manual check-out recorded by %s. Justification: %s') % (self.env.user.name, self.justification))

                return {
                    'type': 'ir.actions.client',
                    'tag': 'attendance_action_pill',
                    'params': {
                        'message': _('Manual Check-Out Recorded'),
                        'subtitle': _('Check-Out recorded for %s') % self.employee_id.name,
                        'type': 'success',
                        'icon': 'fa-check',
                        'next_action': {
                            'name': _('Manual Attendance Updated'),
                            'type': 'ir.actions.act_window',
                            'res_model': 'hr.attendance',
                            'res_id': open_att.id,
                            'view_mode': 'form',
                            'views': [[False, 'form']],
                            'target': 'current',
                        }
                    }
                }

            # ------------------------------------------------
            # 1.2 CHECK-IN ONLY (Start Open Session)
            # ------------------------------------------------
            elif self.attendance_mode == 'check_in':
                if self.check_in_time is False or self.check_in_time is None:
                    raise ValidationError(_('Check-In Time is required for Check-In Only mode.'))

                existing_open = self.env['hr.attendance'].sudo().search([
                    ('employee_id', '=', self.employee_id.id),
                    ('work_date', '=', self.work_date),
                    ('check_out', '=', False),
                ], limit=1)
                if not existing_open:
                    existing_open = self.env['hr.attendance'].sudo().search([
                        ('employee_id', '=', self.employee_id.id),
                        ('check_out', '=', False),
                    ], limit=1)
                if existing_open:
                    raise ValidationError(_(
                        "Employee '%s' already has an active open check-in record for %s. "
                        "Please select 'Check-Out Only' to close the open session."
                    ) % (self.employee_id.name, self.work_date))

                # Lunch break snapping for Check-In
                effective_checkin = self.check_in_time
                if has_lunch and (lunch_start < effective_checkin <= afternoon_start):
                    effective_checkin = afternoon_start

                dt_check_in = self._float_time_to_utc_dt(self.work_date, effective_checkin)
                if self.work_date > today:
                    raise ValidationError(_('Cannot record Check-In time for future dates.'))

                is_afternoon = bool(self.target_session == 'afternoon' or (has_lunch and effective_checkin >= afternoon_start))
                if is_afternoon:
                    session_start = afternoon_start if (has_lunch and afternoon_start) else 13.0
                    session_end = shift_end if shift_end > 13.0 else 17.0
                else:
                    session_start = shift_start
                    session_end = lunch_start if has_lunch else shift_end

                params = self.env['ir.config_parameter'].sudo()
                enable_checkin_grace = params.get_param('hr_attendance.enable_checkin_grace', 'True').lower() in ('true', '1')
                checkin_grace_period = float(params.get_param('hr_attendance.checkin_grace_period', params.get_param('hr_attendance.grace_time', 0.25)))
                grace = 0.0 if (is_afternoon or not enable_checkin_grace) else checkin_grace_period
                grace_mins = int(round(grace * 60.0))
                normal_cutoff = session_start + (grace_mins / 60.0) + (59.999 / 3600.0)

                if effective_checkin > normal_cutoff:
                    late_hours = round(effective_checkin - session_start, 4)
                    status = 'Acknowledged Lateness'
                    late_time_hour = late_hours
                    acknowledged_late = late_hours
                    is_late = True
                else:
                    status = 'Acknowledged Check-In' if self.attendance_reason_ids else 'Manager Manual Check-In'
                    late_time_hour = 0.0
                    acknowledged_late = 0.0
                    is_late = False

                in_mode_val = 'acknowledged' if self.attendance_reason_ids else 'manual'
                vals = {
                    'employee_id': self.employee_id.id,
                    'work_date': self.work_date,
                    'check_in': dt_check_in,
                    'check_out': False,
                    'actual_check_in': dt_check_in,
                    'in_mode': in_mode_val,
                    'out_mode': False,
                    'shift_start_float': session_start,
                    'shift_end_float': session_end,
                    'check_in_status': status,
                    'late_time_hour': late_time_hour,
                    'acknowledged_late': acknowledged_late,
                    'is_late': is_late,
                    'is_acknowledged': True,
                    'acknowledged_by': self.env.user.id,
                    'acknowledged_date': fields.Datetime.now(),
                    'attendance_reason_ids': [(6, 0, self.attendance_reason_ids.ids)],
                }

                att = self.env['hr.attendance'].sudo().with_context(skip_duplicate_check=True).create(vals)

                if hasattr(att, 'message_post'):
                    att.message_post(body=_('Manual check-in created by %s. Justification: %s') % (self.env.user.name, self.justification))

                return {
                    'type': 'ir.actions.client',
                    'tag': 'attendance_action_pill',
                    'params': {
                        'message': _('Manual Check-In Recorded'),
                        'subtitle': _('Check-In recorded for %s') % self.employee_id.name,
                        'type': 'success',
                        'icon': 'fa-check',
                        'next_action': {
                            'name': _('Manual Attendance Created'),
                            'type': 'ir.actions.act_window',
                            'res_model': 'hr.attendance',
                            'res_id': att.id,
                            'view_mode': 'form',
                            'views': [[False, 'form']],
                            'target': 'current',
                        }
                    }
                }

            # ------------------------------------------------
            # 1.3 BOTH (Check-In & Check-Out)
            # ------------------------------------------------
            elif self.attendance_mode == 'both':
                # Block creating 'both' if an active check-in exists
                existing_open = self.env['hr.attendance'].sudo().search([
                    ('employee_id', '=', self.employee_id.id),
                    ('work_date', '=', self.work_date),
                    ('check_out', '=', False),
                ], limit=1)
                if not existing_open:
                    existing_open = self.env['hr.attendance'].sudo().search([
                        ('employee_id', '=', self.employee_id.id),
                        ('check_out', '=', False),
                    ], limit=1)
                if existing_open:
                    raise ValidationError(_(
                        "Employee '%s' already has an active open check-in record for %s. "
                        "Please select 'Check-Out Only' to close the open session."
                    ) % (self.employee_id.name, self.work_date))

                if self.check_in_time is False or not self.check_out_time:
                    raise ValidationError(_('Both Check-In Time and Check-Out Time are required when mode is Both.'))

                effective_in = self.check_in_time
                effective_out = self.check_out_time

                # Check if this is a Full-Day spanning across lunch
                is_full_day_span = (has_lunch and (
                    self.target_session == 'full_day' or 
                    (effective_in <= lunch_start and effective_out >= afternoon_start)
                ))

                mode_val = 'acknowledged' if self.attendance_reason_ids else 'manual'

                if is_full_day_span:
                    # Create 2 clean sessions: Morning (shift_start -> lunch_start) and Afternoon (afternoon_start -> shift_end)
                    dt_m_in = self._float_time_to_utc_dt(self.work_date, effective_in)
                    dt_m_out = self._float_time_to_utc_dt(self.work_date, lunch_start)
                    dt_a_in = self._float_time_to_utc_dt(self.work_date, afternoon_start)
                    dt_a_out = self._float_time_to_utc_dt(self.work_date, effective_out)

                    if self.work_date > today:
                        raise ValidationError(_('Cannot record attendance for future dates.'))

                    params = self.env['ir.config_parameter'].sudo()
                    enable_checkin_grace = params.get_param('hr_attendance.enable_checkin_grace', 'True').lower() in ('true', '1')
                    checkin_grace_period = float(params.get_param('hr_attendance.checkin_grace_period', params.get_param('hr_attendance.grace_time', 0.25)))
                    grace = checkin_grace_period if enable_checkin_grace else 0.0
                    grace_mins = int(round(grace * 60.0))
                    normal_cutoff = shift_start + (grace_mins / 60.0) + (59.999 / 3600.0)

                    if effective_in > normal_cutoff:
                        m_late = round(effective_in - shift_start, 4)
                        m_status = 'Acknowledged Lateness'
                        m_is_late = True
                    else:
                        m_late = 0.0
                        m_status = 'Acknowledged Check-In' if self.attendance_reason_ids else 'Normal'
                        m_is_late = False

                    vals_morning = {
                        'employee_id': self.employee_id.id,
                        'work_date': self.work_date,
                        'check_in': dt_m_in,
                        'check_out': dt_m_out,
                        'actual_check_in': dt_m_in,
                        'in_mode': mode_val,
                        'out_mode': mode_val,
                        'shift_start_float': shift_start,
                        'shift_end_float': lunch_start,
                        'check_in_status': m_status,
                        'late_time_hour': m_late,
                        'acknowledged_late': m_late,
                        'is_late': m_is_late,
                        'check_out_status': 'Normal',
                        'early_exit_hour': 0.0,
                        'acknowledged_exit': 0.0,
                        'over_time_hour': 0.0,
                        'is_acknowledged': True,
                        'acknowledged_by': self.env.user.id,
                        'acknowledged_date': fields.Datetime.now(),
                        'attendance_reason_ids': [(6, 0, self.attendance_reason_ids.ids)],
                    }
                    att_morning = self.env['hr.attendance'].sudo().with_context(skip_duplicate_check=True).create(vals_morning)

                    a_ot = round(effective_out - shift_end, 2) if effective_out > shift_end else 0.0
                    a_early = round(shift_end - effective_out, 4) if effective_out < shift_end else 0.0

                    vals_afternoon = {
                        'employee_id': self.employee_id.id,
                        'work_date': self.work_date,
                        'check_in': dt_a_in,
                        'check_out': dt_a_out,
                        'actual_check_in': dt_a_in,
                        'in_mode': mode_val,
                        'out_mode': mode_val,
                        'shift_start_float': afternoon_start,
                        'shift_end_float': shift_end,
                        'check_in_status': 'Acknowledged Check-In' if self.attendance_reason_ids else 'Normal',
                        'late_time_hour': 0.0,
                        'acknowledged_late': 0.0,
                        'check_out_status': 'Acknowledged Early Exit' if a_early > 0 else ('Acknowledged Check-Out' if self.attendance_reason_ids else 'Normal'),
                        'early_exit_hour': a_early,
                        'acknowledged_exit': a_early,
                        'over_time_hour': a_ot,
                        'is_acknowledged': True,
                        'acknowledged_by': self.env.user.id,
                        'acknowledged_date': fields.Datetime.now(),
                        'attendance_reason_ids': [(6, 0, self.attendance_reason_ids.ids)],
                    }
                    att_afternoon = self.env['hr.attendance'].sudo().with_context(skip_duplicate_check=True).create(vals_afternoon)

                    if a_ot > 0 and self.env.get('over.time'):
                        self.env['over.time'].sudo().with_context(skip_past_date_check=True).create({
                            'employee_id': self.employee_id.id,
                            'date': self.work_date,
                            'start_time': shift_end,
                            'end_time': effective_out,
                            'over_time_reason': self.justification or _('Manual Attendance Overtime'),
                        })

                    if hasattr(att_afternoon, 'message_post'):
                        att_afternoon.message_post(body=_('Full day manual attendance created by %s. Justification: %s') % (self.env.user.name, self.justification))

                    return {
                        'type': 'ir.actions.client',
                        'tag': 'attendance_action_pill',
                        'params': {
                            'message': _('Manual Attendance Created'),
                            'subtitle': _('Full day attendance recorded for %s') % self.employee_id.name,
                            'type': 'success',
                            'icon': 'fa-check',
                            'next_action': {
                                'name': _('Acknowledged Attendances'),
                                'type': 'ir.actions.act_window',
                                'res_model': 'hr.attendance',
                                'domain': [('id', 'in', [att_morning.id, att_afternoon.id])],
                                'view_mode': 'list,form',
                                'views': [[False, 'list'], [False, 'form']],
                                'target': 'current',
                            }
                        }
                    }

                # Single session both mode
                # Lunch break snapping
                if has_lunch:
                    if lunch_start < effective_in <= afternoon_start:
                        effective_in = afternoon_start
                    if lunch_start < effective_out < afternoon_start:
                        effective_out = lunch_start

                dt_check_in = self._float_time_to_utc_dt(self.work_date, effective_in)
                dt_check_out = self._float_time_to_utc_dt(self.work_date, effective_out)

                if self.work_date > today:
                    raise ValidationError(_('Cannot record attendance for future dates.'))

                if dt_check_out <= dt_check_in:
                    raise ValidationError(_('Check-Out time must be strictly after Check-In time.'))

                is_afternoon = bool(self.target_session == 'afternoon' or (has_lunch and effective_in >= afternoon_start))
                if is_afternoon:
                    session_start = afternoon_start if (has_lunch and afternoon_start) else 13.0
                    session_end = shift_end if shift_end > 13.0 else 17.0
                else:
                    session_start = shift_start
                    session_end = lunch_start if has_lunch else (shift_end if shift_end <= 13.0 else 12.0)

                params = self.env['ir.config_parameter'].sudo()
                enable_checkin_grace = params.get_param('hr_attendance.enable_checkin_grace', 'True').lower() in ('true', '1')
                checkin_grace_period = float(params.get_param('hr_attendance.checkin_grace_period', params.get_param('hr_attendance.grace_time', 0.25)))
                grace = 0.0 if (is_afternoon or not enable_checkin_grace) else checkin_grace_period
                grace_mins = int(round(grace * 60.0))
                normal_cutoff = session_start + (grace_mins / 60.0) + (59.999 / 3600.0)

                if effective_in > normal_cutoff:
                    late_hours = round(effective_in - session_start, 4)
                    status = 'Acknowledged Lateness'
                    late_time_hour = late_hours
                    acknowledged_late = late_hours
                    is_late = True
                else:
                    status = 'Acknowledged Check-In' if self.attendance_reason_ids else 'Manager Manual Check-In'
                    late_time_hour = 0.0
                    acknowledged_late = 0.0
                    is_late = False

                early_exit_hour = 0.0
                acknowledged_exit = 0.0
                over_time_hour = 0.0
                if effective_out < session_end:
                    early_exit_hour = round(session_end - effective_out, 4)
                    acknowledged_exit = early_exit_hour
                    check_out_status = 'Acknowledged Early Exit'
                else:
                    if effective_out > session_end:
                        over_time_hour = round(effective_out - session_end, 2)
                    check_out_status = 'Acknowledged Check-Out' if self.attendance_reason_ids else 'Manager Manual Check-Out'

                vals = {
                    'employee_id': self.employee_id.id,
                    'work_date': self.work_date,
                    'check_in': dt_check_in,
                    'check_out': dt_check_out,
                    'actual_check_in': dt_check_in,
                    'in_mode': mode_val,
                    'out_mode': mode_val,
                    'shift_start_float': session_start,
                    'shift_end_float': session_end,
                    'check_in_status': status,
                    'late_time_hour': late_time_hour,
                    'acknowledged_late': acknowledged_late,
                    'is_late': is_late,
                    'check_out_status': check_out_status,
                    'early_exit_hour': early_exit_hour,
                    'acknowledged_exit': acknowledged_exit,
                    'over_time_hour': over_time_hour,
                    'is_acknowledged': True,
                    'acknowledged_by': self.env.user.id,
                    'acknowledged_date': fields.Datetime.now(),
                    'attendance_reason_ids': [(6, 0, self.attendance_reason_ids.ids)],
                }

                att = self.env['hr.attendance'].sudo().with_context(skip_duplicate_check=True).create(vals)

                if over_time_hour > 0 and self.env.get('over.time'):
                    self.env['over.time'].sudo().with_context(skip_past_date_check=True).create({
                        'employee_id': self.employee_id.id,
                        'date': self.work_date,
                        'start_time': session_end,
                        'end_time': effective_out,
                        'over_time_reason': self.justification or _('Manual Attendance Overtime'),
                    })

                if hasattr(att, 'message_post'):
                    att.message_post(body=_('Manual attendance created by %s. Justification: %s') % (self.env.user.name, self.justification))

                return {
                    'type': 'ir.actions.client',
                    'tag': 'attendance_action_pill',
                    'params': {
                        'message': _('Manual Attendance Created'),
                        'subtitle': _('Attendance recorded for %s') % self.employee_id.name,
                        'type': 'success',
                        'icon': 'fa-check',
                        'next_action': {
                            'name': _('Manual Attendance Created'),
                            'type': 'ir.actions.act_window',
                            'res_model': 'hr.attendance',
                            'res_id': att.id,
                            'view_mode': 'form',
                            'views': [[False, 'form']],
                            'target': 'current',
                        }
                    }
                }

        # ----------------------------------------------------
        # SCENARIO 2: BATCH OPERATING UNIT ENTRY (HR ADMIN DIRECT GENERATION)
        # ----------------------------------------------------
        elif self.entry_type == 'batch':
            if not self.env.user.has_group('hr_attendance.group_hr_attendance_manager'):
                raise ValidationError(_('Batch Operating Unit attendance entry is strictly restricted to HR Administrators.'))

            if not self.employee_ids or not self.start_date or not self.end_date:
                raise ValidationError(_('Operating Unit, Employees, Start Date, and End Date are required for Batch entry.'))

            if self.start_date > self.end_date:
                raise ValidationError(_('Start Date cannot be greater than End Date.'))

            # Direct generation with zero approval hierarchy
            return self._generate_batch_attendances()

    def _generate_batch_attendances(self):
        """Helper to create attendance records across date range."""
        current_date = self.start_date
        created_attendances = []

        while current_date <= self.end_date:
            is_sunday = (current_date.weekday() == 6)

            user_emp = self.env.user.employee_id or self.env['hr.employee'].sudo().search([('user_id', '=', self.env.uid)], limit=1)
            for emp in self.employee_ids:
                if is_sunday:
                    continue

                # Anti-Self Protection: Even Administrators cannot acknowledge their own attendance in batch
                if (emp.user_id and emp.user_id.id == self.env.uid) or (user_emp and emp.id == user_emp.id):
                    continue

                existing = self.env['hr.attendance'].sudo().search([
                    ('employee_id', '=', emp.id),
                    ('work_date', '=', current_date)
                ])
                if existing:
                    if self.overwrite_existing:
                        existing.with_context(force_unlink_attendance=True).unlink()
                    else:
                        continue

                if self.use_employee_shifts:
                    shift_info = emp._get_employee_shift_info(target_date=current_date)
                    if shift_info and shift_info.get('is_day_off'):
                        continue
                    s_start = shift_info.get('start_time', 8.0) if shift_info else 8.0
                    s_end = shift_info.get('end_time', 17.0) if shift_info else 17.0
                    has_lunch = shift_info.get('has_lunch_break', False) if shift_info else False
                    lunch_start = shift_info.get('lunch_start_time', 12.0) if shift_info else 12.0
                    lunch_dur = shift_info.get('lunch_duration', 1.0) if shift_info else 1.0
                else:
                    s_start = self.check_in_time_only or 8.0
                    s_end = self.check_out_time_only or 17.0
                    has_lunch = False
                    lunch_start = 12.0
                    lunch_dur = 1.0

                lunch_end = lunch_start + lunch_dur if (has_lunch and lunch_dur > 0) else lunch_start
                can_split_lunch = bool(
                    has_lunch and 
                    lunch_dur > 0 and 
                    s_start < lunch_start and 
                    lunch_end < s_end
                )

                if can_split_lunch:
                    dt_in1 = self._float_time_to_utc_dt(current_date, s_start)
                    dt_out1 = self._float_time_to_utc_dt(current_date, lunch_start)
                    vals1 = {
                        'employee_id': emp.id,
                        'work_date': current_date,
                        'check_in': dt_in1,
                        'check_out': dt_out1,
                        'actual_check_in': dt_in1,
                        'in_mode': 'batch',
                        'out_mode': 'batch',
                        'shift_start_float': s_start,
                        'shift_end_float': lunch_start,
                        'check_in_status': 'Normal',
                        'is_acknowledged': True,
                        'acknowledged_by': self.env.user.id,
                        'acknowledged_date': fields.Datetime.now(),
                        'attendance_reason_ids': [(6, 0, self.attendance_reason_ids.ids)],
                    }
                    att1 = self.env['hr.attendance'].sudo().with_context(skip_duplicate_check=True).create(vals1)
                    created_attendances.append(att1.id)

                    dt_in2 = self._float_time_to_utc_dt(current_date, lunch_end)
                    dt_out2 = self._float_time_to_utc_dt(current_date, s_end)
                    vals2 = {
                        'employee_id': emp.id,
                        'work_date': current_date,
                        'check_in': dt_in2,
                        'check_out': dt_out2,
                        'actual_check_in': dt_in2,
                        'in_mode': 'batch',
                        'out_mode': 'batch',
                        'shift_start_float': lunch_end,
                        'shift_end_float': s_end,
                        'check_in_status': 'Normal',
                        'is_acknowledged': True,
                        'acknowledged_by': self.env.user.id,
                        'acknowledged_date': fields.Datetime.now(),
                        'attendance_reason_ids': [(6, 0, self.attendance_reason_ids.ids)],
                    }
                    att2 = self.env['hr.attendance'].sudo().with_context(skip_duplicate_check=True).create(vals2)
                    created_attendances.append(att2.id)
                elif s_end > s_start:
                    dt_in = self._float_time_to_utc_dt(current_date, s_start)
                    dt_out = self._float_time_to_utc_dt(current_date, s_end)
                    vals = {
                        'employee_id': emp.id,
                        'work_date': current_date,
                        'check_in': dt_in,
                        'check_out': dt_out,
                        'actual_check_in': dt_in,
                        'in_mode': 'batch',
                        'out_mode': 'batch',
                        'shift_start_float': s_start,
                        'shift_end_float': s_end,
                        'check_in_status': 'Normal',
                        'is_acknowledged': True,
                        'acknowledged_by': self.env.user.id,
                        'acknowledged_date': fields.Datetime.now(),
                        'attendance_reason_ids': [(6, 0, self.attendance_reason_ids.ids)],
                    }
                    att = self.env['hr.attendance'].sudo().with_context(skip_duplicate_check=True).create(vals)
                    created_attendances.append(att.id)


            current_date += datetime.timedelta(days=1)

        if not created_attendances:
            if self.start_date == self.end_date:
                date_str = self.start_date.strftime('%B %d, %Y')
                day_name = self.start_date.strftime('%A')
                raise ValidationError(_(
                    "No attendance records were created: %(date)s (%(day)s) is a scheduled Day-Off (Rest Day) for the selected employees, or attendance records already exist."
                ) % {
                    'date': date_str,
                    'day': day_name,
                })
            else:
                raise ValidationError(_(
                    "No attendance records were created: All dates in the selected range (%(start)s to %(end)s) are scheduled Day-Offs for the selected employees, or attendance records already exist."
                ) % {
                    'start': self.start_date.strftime('%B %d, %Y'),
                    'end': self.end_date.strftime('%B %d, %Y'),
                })

        # Record the Batch Request in hr.attendance.batch.request for audit and reporting
        coach = (self.env.user.employee_id.coach_id or self.env.user.employee_id.parent_id or self.env.user.employee_id) if self.env.user.employee_id else False
        ou_id = self.operating_unit_id.id if self.operating_unit_id else (self.employee_ids[0].default_operating_unit_id.id if self.employee_ids and self.employee_ids[0].default_operating_unit_id else False)
        self.env['hr.attendance.batch.request'].sudo().create({
            'manager_id': self.env.user.id,
            'coach_id': coach.id if coach else False,
            'operating_unit_id': ou_id,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'employee_ids': [(6, 0, self.employee_ids.ids)],
            'rest_type': 'none',
            'use_employee_shifts': self.use_employee_shifts,
            'overwrite_existing': self.overwrite_existing,
            'check_in_time_only': self.check_in_time_only or 8.0,
            'check_out_time_only': self.check_out_time_only or 17.0,
            'justification': self.justification or _('Manual Batch Attendance Entry'),
            'attendance_reason_ids': [(6, 0, self.attendance_reason_ids.ids)],
            'state': 'approved',
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'attendance_action_pill',
            'params': {
                'message': _('Batch Attendance Created'),
                'subtitle': _('Batch attendance created successfully for %d employee(s)!') % len(self.employee_ids),
                'type': 'success',
                'icon': 'fa-check',
                'next_action': {
                    'name': _('Batch Attendances Created'),
                    'type': 'ir.actions.act_window',
                    'res_model': 'hr.attendance',
                    'view_mode': 'list,form',
                    'views': [[False, 'list'], [False, 'form']],
                    'domain': [('id', 'in', created_attendances)],
                    'target': 'current',
                }
            }
        }
