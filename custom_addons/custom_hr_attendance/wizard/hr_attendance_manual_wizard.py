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
    entry_type = fields.Selection([
        ('individual', 'Individual Employee (Single Day)'),
        ('batch', 'Batch Operating Unit (Multi-Day / Outage)'),
    ], string='Entry Mode', default='individual', required=True)

    is_hr_admin = fields.Boolean(
        string='Is HR Admin',
        compute='_compute_is_hr_admin',
    )

    def _compute_is_hr_admin(self):
        is_admin = self.env.user.has_group('hr_attendance.group_hr_attendance_manager')
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
        emp = self.env.user.employee_id
        if not emp:
            emp = self.env['hr.employee'].sudo().search([('user_id', '=', self.env.uid)], limit=1)
        return emp.id if emp else False

    @api.model
    def _get_employee_domain(self):
        if self.env.user.has_group('hr_attendance.group_hr_attendance_manager'):
            return [('active', '=', True)]
        emp = self.env.user.employee_id
        if not emp:
            emp = self.env['hr.employee'].sudo().search([('user_id', '=', self.env.uid)], limit=1)
        if emp:
            return ['&', ('active', '=', True), '|', '|',
                ('parent_id', '=', emp.id),
                ('attendance_manager_id', '=', self.env.uid),
                ('default_operating_unit_id', '=', emp.default_operating_unit_id.id if emp.default_operating_unit_id else False)
            ]
        return [('active', '=', True)]

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
        domain=lambda self: self._get_employee_domain(),
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
            emps = self.env['hr.employee'].search([
                ('default_operating_unit_id', '=', self.operating_unit_id.id),
                ('active', '=', True)
            ])
            self.employee_ids = [(6, 0, emps.ids)]

    @api.onchange('employee_id', 'work_date', 'entry_type', 'attendance_mode')
    def _onchange_employee_work_date(self):
        if self.entry_type == 'individual' and self.employee_id:
            target_date = self.work_date or fields.Date.context_today(self)
            shift_info = self.employee_id._get_employee_shift_info(target_date=target_date)
            if shift_info and not shift_info.get('is_day_off'):
                s_start = shift_info.get('start_time', 8.0)
                s_end = shift_info.get('end_time', 17.0)
                s_name = shift_info.get('name', 'Standard Shift')
                self.detected_shift_name = s_name
                self.detected_shift_info = f"{s_name} ({self._float_to_time_str(s_start)} - {self._float_to_time_str(s_end)})"
            else:
                s_start = 8.0
                s_end = 17.0
                self.detected_shift_name = 'Default Global Shift'
                self.detected_shift_info = 'Default Global Shift (08:00 AM - 05:00 PM)'

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
                if open_att:
                    self.attendance_mode = False
                    self.check_in_time = False
                    self.check_out_time = False
                    return {
                        'warning': {
                            'title': _('Active Check-In Exists'),
                            'message': _(
                                "Employee '%s' already has an active open check-in session for %s. "
                                "You cannot create a 'Both (Check-In & Check-Out)' record while a session is open. "
                                "Please select 'Check-Out Only' to complete the active session."
                            ) % (self.employee_id.name, target_date)
                        }
                    }
                self.check_in_time = s_start
                self.check_out_time = s_end

            elif self.attendance_mode == 'check_in':
                if open_att:
                    self.attendance_mode = False
                    self.check_in_time = False
                    self.check_out_time = False
                    return {
                        'warning': {
                            'title': _('Active Check-In Exists'),
                            'message': _(
                                "Employee '%s' already has an active open check-in session for %s. "
                                "Please select 'Check-Out Only' to complete the active session."
                            ) % (self.employee_id.name, target_date)
                        }
                    }
                self.check_in_time = s_start
                self.check_out_time = False

            elif self.attendance_mode == 'check_out':
                if not open_att:
                    self.attendance_mode = False
                    self.check_in_time = False
                    self.check_out_time = False
                    return {
                        'warning': {
                            'title': _('No Active Check-In Found'),
                            'message': _(
                                "Employee '%s' does not have an active check-in record for %s to check out from. "
                                "Please select 'Check-In Only' or 'Both'."
                            ) % (self.employee_id.name, target_date)
                        }
                    }
                if open_att.check_in:
                    local_dt = fields.Datetime.context_timestamp(self.employee_id, open_att.check_in)
                    self.check_in_time = local_dt.hour + (local_dt.minute / 60.0)
                else:
                    self.check_in_time = s_start
                self.check_out_time = s_end

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

            if not self.attendance_mode:
                raise ValidationError(_('Please select an Attendance Action (Check-In Only, Check-Out Only, or Both).'))

            shift_info = self.employee_id._get_employee_shift_info(target_date=self.work_date)
            shift_start = shift_info.get('start_time', 8.0) if shift_info else 8.0
            shift_end = shift_info.get('end_time', 17.0) if shift_info else 17.0

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

                dt_check_out = self._float_time_to_utc_dt(self.work_date, self.check_out_time)
                if dt_check_out <= open_att.check_in:
                    raise ValidationError(_('Check-Out time must be strictly after the recorded Check-In time (%s).') % fields.Datetime.to_string(open_att.check_in))

                s_end = open_att.shift_end_float or shift_end
                early_exit_hour = 0.0
                acknowledged_exit = 0.0
                if self.check_out_time < s_end:
                    early_exit_hour = s_end - self.check_out_time
                    acknowledged_exit = early_exit_hour
                    check_out_status = 'Acknowledged Early Exit'
                else:
                    check_out_status = 'Acknowledged Check-Out' if self.attendance_reason_ids else 'Manager Manual Check-Out'

                out_mode_val = 'acknowledged' if self.attendance_reason_ids else 'manual'
                open_att.sudo().write({
                    'check_out': dt_check_out,
                    'out_mode': out_mode_val,
                    'check_out_status': check_out_status,
                    'early_exit_hour': early_exit_hour,
                    'acknowledged_exit': acknowledged_exit,
                    'is_acknowledged': True,
                    'acknowledged_by': self.env.user.id,
                    'acknowledged_date': fields.Datetime.now(),
                })
                if self.attendance_reason_ids:
                    open_att.sudo().write({'attendance_reason_ids': [(4, rid) for rid in self.attendance_reason_ids.ids]})

                if self.work_date == today:
                    self.employee_id.sudo().write({
                        'attendance_state': 'checked_out',
                        'last_attendance_id': open_att.id
                    })

                if hasattr(open_att, 'message_post'):
                    open_att.message_post(body=_('Manual check-out recorded by %s. Justification: %s') % (self.env.user.name, self.justification))

                return {
                    'name': _('Manual Attendance Updated'),
                    'type': 'ir.actions.act_window',
                    'res_model': 'hr.attendance',
                    'res_id': open_att.id,
                    'view_mode': 'form',
                    'target': 'current',
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
                        "Employee '%s' already has an active open check-in session for %s. "
                        "Please select 'Check-Out Only' to complete the active session."
                    ) % (self.employee_id.name, self.work_date))

                dt_check_in = self._float_time_to_utc_dt(self.work_date, self.check_in_time)

                if self.check_in_time > shift_start:
                    late_hours = self.check_in_time - shift_start
                    status = 'Acknowledged Lateness'
                    late_time_hour = late_hours
                    acknowledged_late = late_hours
                else:
                    status = 'Acknowledged Check-In' if self.attendance_reason_ids else 'Manager Manual Check-In'
                    late_time_hour = 0.0
                    acknowledged_late = 0.0

                in_mode_val = 'acknowledged' if self.attendance_reason_ids else 'manual'
                vals = {
                    'employee_id': self.employee_id.id,
                    'work_date': self.work_date,
                    'check_in': dt_check_in,
                    'check_out': False,
                    'actual_check_in': dt_check_in,
                    'in_mode': in_mode_val,
                    'out_mode': False,
                    'shift_start_float': shift_start,
                    'shift_end_float': shift_end,
                    'check_in_status': status,
                    'late_time_hour': late_time_hour,
                    'acknowledged_late': acknowledged_late,
                    'is_acknowledged': True,
                    'acknowledged_by': self.env.user.id,
                    'acknowledged_date': fields.Datetime.now(),
                    'attendance_reason_ids': [(6, 0, self.attendance_reason_ids.ids)],
                }


                att = self.env['hr.attendance'].sudo().with_context(skip_duplicate_check=True).create(vals)

                if self.work_date == today:
                    self.employee_id.sudo().write({
                        'attendance_state': 'checked_in',
                        'last_attendance_id': att.id
                    })

                if hasattr(att, 'message_post'):
                    att.message_post(body=_('Manual check-in created by %s. Justification: %s') % (self.env.user.name, self.justification))

                return {
                    'name': _('Manual Attendance Created'),
                    'type': 'ir.actions.act_window',
                    'res_model': 'hr.attendance',
                    'res_id': att.id,
                    'view_mode': 'form',
                    'target': 'current',
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
                        "Employee '%s' already has an active open check-in session for %s. "
                        "You cannot create a 'Both (Check-In & Check-Out)' record while a session is active. "
                        "Please select 'Check-Out Only' to complete the active session."
                    ) % (self.employee_id.name, self.work_date))

                if self.check_in_time is False or not self.check_out_time:
                    raise ValidationError(_('Both Check-In Time and Check-Out Time are required when mode is Both.'))

                dt_check_in = self._float_time_to_utc_dt(self.work_date, self.check_in_time)
                dt_check_out = self._float_time_to_utc_dt(self.work_date, self.check_out_time)

                if dt_check_out <= dt_check_in:
                    raise ValidationError(_('Check-Out time must be strictly after Check-In time.'))

                if self.check_in_time > shift_start:
                    late_hours = self.check_in_time - shift_start
                    status = 'Acknowledged Lateness'
                    late_time_hour = late_hours
                    acknowledged_late = late_hours
                else:
                    status = 'Acknowledged Check-In' if self.attendance_reason_ids else 'Manager Manual Check-In'
                    late_time_hour = 0.0
                    acknowledged_late = 0.0

                early_exit_hour = 0.0
                acknowledged_exit = 0.0
                if self.check_out_time < shift_end:
                    early_exit_hour = shift_end - self.check_out_time
                    acknowledged_exit = early_exit_hour
                    check_out_status = 'Acknowledged Early Exit'
                else:
                    check_out_status = 'Acknowledged Check-Out' if self.attendance_reason_ids else 'Manager Manual Check-Out'


                mode_val = 'acknowledged' if self.attendance_reason_ids else 'manual'
                vals = {
                    'employee_id': self.employee_id.id,
                    'work_date': self.work_date,
                    'check_in': dt_check_in,
                    'check_out': dt_check_out,
                    'actual_check_in': dt_check_in,
                    'in_mode': mode_val,
                    'out_mode': mode_val,
                    'shift_start_float': shift_start,
                    'shift_end_float': shift_end,
                    'check_in_status': status,
                    'late_time_hour': late_time_hour,
                    'acknowledged_late': acknowledged_late,
                    'check_out_status': check_out_status,
                    'early_exit_hour': early_exit_hour,
                    'acknowledged_exit': acknowledged_exit,
                    'is_acknowledged': True,
                    'acknowledged_by': self.env.user.id,
                    'acknowledged_date': fields.Datetime.now(),
                    'attendance_reason_ids': [(6, 0, self.attendance_reason_ids.ids)],
                }


                att = self.env['hr.attendance'].sudo().with_context(skip_duplicate_check=True).create(vals)

                if self.work_date == today:
                    self.employee_id.sudo().write({
                        'attendance_state': 'checked_out',
                        'last_attendance_id': att.id
                    })

                if hasattr(att, 'message_post'):
                    att.message_post(body=_('Manual attendance created by %s. Justification: %s') % (self.env.user.name, self.justification))

                return {
                    'name': _('Manual Attendance Created'),
                    'type': 'ir.actions.act_window',
                    'res_model': 'hr.attendance',
                    'res_id': att.id,
                    'view_mode': 'form',
                    'target': 'current',
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

            for emp in self.employee_ids:
                if is_sunday:
                    continue

                if self.overwrite_existing:
                    existing = self.env['hr.attendance'].sudo().search([
                        ('employee_id', '=', emp.id),
                        ('work_date', '=', current_date)
                    ])
                    existing.unlink()

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

                if has_lunch and lunch_dur > 0:
                    lunch_end = lunch_start + lunch_dur
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
                else:
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

        return {
            'name': _('Batch Attendances Created'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.attendance',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created_attendances)],
            'target': 'current',
        }
