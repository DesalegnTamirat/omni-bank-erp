import logging
from odoo import models, fields, _
from odoo.exceptions import UserError
import pytz
from datetime import datetime, time

_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    attendance_state = fields.Selection([
        ('checked_in', 'Checked In'),
        ('checked_out', 'Checked Out'),
        ('lunch_out', 'On Lunch Break'),
    ], default='checked_out', string="Attendance State")

    # ============================================================
    # Determine Applicable Shift (Continuous Full Day)
    # ============================================================
    def _select_applicable_shift(self, current_float, morning_start, exit_time,
                                 location_exceptions, job_position_exceptions, is_manager=False):
        """
        Shift selection priority:
        1) Job-position exception shift
        2) Location-based shift
        3) Default system shift (Full Day)
        """
        #checkin_buffer = 0.50  # 30-minute buffer
        checkin_buffer = self._get_param_float('hr_attendance.checkin_buffer', 0.50)

        # ----------------------------
        # 1. Job-position-based shifts
        # ----------------------------
        for job in job_position_exceptions:
            shift = job.shift_id
            if not shift:
                continue

            _logger.info(
                "Job Position Exception | Shift: %s | Start: %.2f | End: %.2f | Night: %s",
                job.job_position_exception_name, shift.start_time, shift.end_time, shift.is_night_shift,
            )

            if shift.is_night_shift:
                if current_float >= (shift.start_time - checkin_buffer) or current_float <= shift.end_time:
                    return shift.start_time, shift.end_time
            else:
                if (shift.start_time - checkin_buffer) <= current_float <= shift.end_time:
                    _logger.info("Using Job-Position shift: %.2f - %.2f", shift.start_time, shift.end_time)
                    return shift.start_time, shift.end_time

        # ----------------------------
        # 2. Location-based shifts
        # ----------------------------
        for loc in location_exceptions:
            _logger.info("Checking Location Exception: %.2f - %.2f", loc.start_time, loc.end_time)
            if (loc.start_time - checkin_buffer) <= current_float <= loc.end_time:
                return loc.start_time, loc.end_time

        # ----------------------------
        # 3. Default system shifts (Full Day)
        # ----------------------------
        # if (morning_start - checkin_buffer) <= current_float <= exit_time or current_float >= exit_time:
        if current_float >= (morning_start - checkin_buffer):
            _logger.info("Using Default Full Day shift: %.2f - %.2f", morning_start, exit_time)
            return morning_start, exit_time

        # MANAGER OVERRIDE
        if is_manager:
            _logger.info("Manager Override: Forcing default shift bounds.")
            return morning_start, exit_time

        raise UserError(
            _("Check-in/out is not allowed at this time. Expected shift: %.2f to %.2f") % (morning_start, exit_time))

    # ============================================================
    # Check-in Evaluation Logic
    # ============================================================
    def _evaluate_checkin_status(self, current_float, shift_start, dead_time, predefined_late, is_manager=False):
        status = 'Normal'
        late_time = 0.0
        pre_defined_lateness_hours = 0.0
        #checkin_buffer = 0.50
        checkin_buffer = self._get_param_float('hr_attendance.checkin_buffer', 0.50)

        if predefined_late and current_float <= predefined_late.end_time:
            status = 'Pre-Defined Lateness'
            pre_defined_lateness_hours = round((current_float - shift_start) * 60, 2)
        elif (shift_start - checkin_buffer) <= current_float <= shift_start:
            status = 'Normal'
        elif current_float <= shift_start + dead_time:
            status = 'Late'
            late_time = max(0, round((current_float - shift_start) * 60, 2))
        elif is_manager:
            # status = 'Late'
            late_time = max(0, round((current_float - shift_start) * 60, 2))
        else:
            _logger.warning("Check-in rejected: Outside allowed grace period (%.2f)", current_float)
            raise UserError(_("Check-in is not allowed. You are past the allowed late threshold."))

        return status, late_time, 0.0, pre_defined_lateness_hours

    # ============================================================
    # Check-out Evaluation Logic
    # ============================================================
    def _evaluate_checkout_status(self, current_float, shift_end, attendance, utc_naive_dt, min_work_hour,
                                  predefined_early_exit, is_manager=False):

        # EXIT TIME VALIDATION
        if current_float < shift_end and not is_manager:
           # Check if they have a pre-approved early exit for this exact time
            if not (predefined_early_exit and current_float >= predefined_early_exit.start_time):
                raise UserError(_(
                    "You cannot check out yet. Your shift ends at %.2f.\n"
                    "Current time is %.2f.") % (shift_end, current_float))

        status = 'Normal'
        early_exit = 0.0
        pre_approved_early = 0.0

        if predefined_early_exit and current_float >= predefined_early_exit.start_time:
            status = 'Pre-Defined Early Exit'
            pre_approved_early = round((shift_end - current_float) * 60, 2)
        elif current_float >= shift_end:
            status = 'Normal'
        elif current_float < shift_end:
            status = 'Unauthorized Early Exit'
            early_exit = round((shift_end - current_float) * 60, 2)
        else:
            raise UserError(_("Early check-out is not allowed.\n\n"
                              "If you need to leave early, please submit an Early Exit request to your manager."))

        return status, early_exit, 0.0, pre_approved_early

    def _float_to_utc_datetime(self, float_time, reference_dt):
        """Converts a float hour (e.g., 8.5) to a UTC datetime object for the current day."""
        hours = int(float_time)
        minutes = int((float_time - hours) * 60)

        # Create local time object
        local_tz = pytz.timezone('Africa/Addis_Ababa')
        local_dt = local_tz.localize(datetime.combine(reference_dt.date(), time(hours, minutes)))

        # Return as naive UTC for Odoo fields
        return local_dt.astimezone(pytz.utc).replace(tzinfo=None)
        
    # ============================================================
    # Lunch Break Logic
    # ============================================================
    def _is_lunch_break_enabled(self):
        """Check if lunch break feature is enabled."""
        param = self.env['ir.config_parameter'].sudo().get_param('hr_attendance.enable_lunch_break', 'False')
        return param.lower() in ('true', '1')

    def _get_lunch_window(self):
        """Return (lunch_start, lunch_end) as floats based on config."""
        lunch_out_time = self._get_param_float('hr_attendance.lunch_out_time', 12.0)
        lunch_duration = self._get_param_float('hr_attendance.lunch_duration', 1.0)
        lunch_grace = self._get_param_float('hr_attendance.lunch_grace_time', 0.25)
        return lunch_out_time - lunch_grace, lunch_out_time + lunch_duration + lunch_grace

    # Load Parameters
    def _get_param_float(self, key, default):
        return float(self.env['ir.config_parameter'].sudo().get_param(key, default))

    
    def _attendance_action_change(self, geo_information=None):
        self.ensure_one()

        # Time Handling
        now_utc = fields.Datetime.now()
        if now_utc.tzinfo is None:
            now_utc = pytz.utc.localize(now_utc)
        local_dt = now_utc.astimezone(pytz.timezone('Africa/Addis_Ababa'))
        utc_naive_dt = local_dt.astimezone(pytz.utc).replace(tzinfo=None)
        today_date = local_dt.date()
        current_float = (local_dt.hour + local_dt.minute / 60 + local_dt.second / 3600)

        _logger.info("Action Triggered | Employee: %s | Time: %.2f", self.name, current_float)

        # Load Parameters
        #def _get_param_float(key, default):
        #    return float(self.env['ir.config_parameter'].sudo().get_param(key, default))

        morning_start = self._get_param_float('hr_attendance.morning_time', 8.0)
        exit_time = self._get_param_float('hr_attendance.exit_time', 17.0)
        dead_time = self._get_param_float('hr_attendance.dead_time', 0.25)
        min_work_hour = self._get_param_float('hr_attendance.min_working_hour', 7.0)
        checkin_buffer = self._get_param_float('hr_attendance.checkin_buffer', 0.50)
        saturday_exit = self._get_param_float('hr_attendance.saturday_exit_time', 14.75)

        # ----------------------------------------------------
        # Saturday Half Day Logic (Head Office Only)
        # ----------------------------------------------------
        is_saturday = local_dt.weekday() == 4
        operating_unit = self.default_operating_unit_id
        enable_saturday_halfday = self.env['ir.config_parameter'].sudo().get_param(
            'hr_attendance.enable_saturday_halfday', 'True')

        if enable_saturday_halfday.lower() in ('true', '1') and \
                operating_unit and operating_unit.work_unit_type != 'branch' and is_saturday:
            _logger.info("Saturday Half-Day Applied | Employee: %s", self.name)
            exit_time = saturday_exit

        # ----------------------------------------------------
        # Separation / Offboarding Validation
        # ----------------------------------------------------
        if hasattr(self, 'exit_date') and self.exit_date and self.exit_date <= today_date:
            raise UserError(_(
                "Attendance cannot be recorded.\n\n"
                "Employee separated on %s."
            ) % self.exit_date)

        if not self.active:
            raise UserError(_(
                "Attendance cannot be recorded.\n\n"
                "Employee account is archived or inactive."
            ))

        # ----------------------------------------------------
        # Disciplinary Suspension Validation (Dynamic)
        # ----------------------------------------------------
        if 'hr.discipline' in self.env:
            discipline = self.env['hr.discipline'].search([
                ('employee_id', '=', self.id),
                ('state', 'in', ['active', 'confirmed', 'validated']),
                ('penalty_type', '=', 'suspension'),
                ('date_from', '<=', today_date),
                ('date_to', '>=', today_date),
            ], limit=1)
            if discipline:
                raise UserError(_(
                    "Attendance cannot be recorded.\n\n"
                    "Employee is currently under disciplinary suspension until %s."
                ) % discipline.date_to)

        # Leave Validation
        leave = self.env['hr.leave'].search([
            ('employee_id', '=', self.id), ('state', '=', 'validate'), ('holiday_status_id', '!=', 80),
            ('date_from', '<=', today_date), ('date_to', '>=', today_date),
        ], limit=1)

        if leave:
            raise UserError(_(
                "Attendance cannot be recorded.\n\n"
                "You are currently on approved leave:\n%s"
            ) % leave.holiday_status_id.name)

        # ----------------------------------------------------
        # Pre-approval Exceptions
        # ----------------------------------------------------
        predefined_late = self.env['attendance.preapproval'].search([
            ('employee_id', '=', self.id), ('date', '=', today_date),
            ('state', '=', 'approved'), ('exception_type', '=', 'predefined_late'),
            ('active', '=', True)
        ], limit=1)
        predefined_early_exit = self.env['attendance.preapproval'].search([
            ('employee_id', '=', self.id), ('date', '=', today_date),
            ('state', '=', 'approved'), ('exception_type', '=', 'predefined_early_exit'),
            ('active', '=', True)
        ], limit=1)
        # ----------------------------------------------------
        # Location Exceptions
        # ----------------------------------------------------
        location_exceptions = self.env['location.based.exception'].search([
            ('operating_unit', '=', self.default_operating_unit_id.id),
            ('active', '=', True)
        ])
        # ----------------------------------------------------
        # Job Position Exceptions
        # ----------------------------------------------------
        job_position_exceptions = self.env['job.position.exception'].search([
            ('employee_id', '=', self.id), ('status', '=', 'active'),
            ('active', '=', True)
        ])

        # ----------------------------------------------------
        # Determine Shift
        # ----------------------------------------------------
        shift_start, shift_end = self._select_applicable_shift(
            current_float, morning_start, exit_time, location_exceptions, job_position_exceptions
        )
        # Convert float shift times to Odoo-ready UTC datetimes
        shift_start_utc = self._float_to_utc_datetime(shift_start, local_dt)
        shift_end_utc = self._float_to_utc_datetime(shift_end, local_dt)
        # ----------------------------------------------------
        # CHECK-IN
        # ----------------------------------------------------
        if self.attendance_state == 'checked_out':
            enable_checkin_restriction = self.env['ir.config_parameter'].sudo().get_param(
                'hr_attendance.enable_checkin_restriction', 'True')
            if enable_checkin_restriction.lower() in ('true', '1'):
                status, late_time, ot, pre_late = self._evaluate_checkin_status(
                    current_float, shift_start, dead_time, predefined_late
                )
                if status == 'Late':
                    shift_start_utc = utc_naive_dt
            else:
                status, late_time, ot, pre_late = 'Normal', 0.0, 0.0, 0.0
            vals = {
                'employee_id': self.id,
                # 'check_in': utc_naive_dt,
                'check_in': shift_start_utc,
                'check_in_status': status,
                'late_time_hour': late_time,
                'pre_defined_lateness': pre_late
            }
            if geo_information:
                vals.update({'in_%s' % key: geo_information[key] for key in geo_information})
            _logger.info("Creating Check-in: %s", vals)
            attendance = self.env['hr.attendance'].create(vals)
            self.attendance_state = 'checked_in'
            return attendance

        # ----------------------------------------------------
        # LUNCH-OUT (employee going for lunch)
        # ----------------------------------------------------
        elif self.attendance_state == 'checked_in' and self._is_lunch_break_enabled():
            # Check if we're inside the lunch window
            lunch_start, lunch_end = self._get_lunch_window()
            if lunch_start <= current_float <= lunch_end:
                # Record lunch-out on the current open attendance record
                attendance = self.env['hr.attendance'].search([
                    ('employee_id', '=', self.id), ('check_out', '=', False)
                ], limit=1)
                if not attendance:
                    raise UserError(_("No active check-in found."))
                attendance.write({'lunch_out': utc_naive_dt})
                self.attendance_state = 'lunch_out'
                _logger.info("Lunch-Out recorded for %s at %.2f", self.name, current_float)
                return attendance
            else:
                # Outside lunch window → proceed to check-out flow below
                pass

        # ----------------------------------------------------
        # BACK FROM LUNCH
        # ----------------------------------------------------
        if self.attendance_state == 'lunch_out':
            attendance = self.env['hr.attendance'].search([
                ('employee_id', '=', self.id), ('check_out', '=', False),
                ('lunch_out', '!=', False), ('lunch_in', '=', False)
            ], limit=1)
            if not attendance:
                raise UserError(_("No active lunch break record found."))
            attendance.write({'lunch_in': utc_naive_dt})
            self.attendance_state = 'checked_in'
            _logger.info("Back-from-Lunch recorded for %s at %.2f", self.name, current_float)
            return attendance

        # ----------------------------------------------------
        # CHECK-OUT
        # ----------------------------------------------------
        if self.attendance_state == 'checked_in':
            attendance = self.env['hr.attendance'].search([
                ('employee_id', '=', self.id), ('check_out', '=', False)
            ], limit=1)
            if not attendance:
                raise UserError(_("No active check-in found."))

            # Validate checkout restriction toggle
            enable_checkout_restriction = self.env['ir.config_parameter'].sudo().get_param(
                'hr_attendance.enable_checkout_restriction', 'True')
            if enable_checkout_restriction.lower() in ('true', '1'):
                status, early_exit, ot, pre_early = self._evaluate_checkout_status(
                    current_float, shift_end, attendance, utc_naive_dt, min_work_hour, predefined_early_exit
                )
            else:
                status, early_exit, ot, pre_early = 'Normal', 0.0, 0.0, 0.0

            vals = {
                # 'check_out': utc_naive_dt,
                'check_out': shift_end_utc,
                'check_out_status': status,
                'early_exit_hour': early_exit,
                'pre_approved_early_checkout': pre_early
            }
            if geo_information:
                vals.update({'out_%s' % key: geo_information[key] for key in geo_information})
            attendance.write(vals)
            self.attendance_state = 'checked_out'
            _logger.info("Check-out completed for %s", self.name)
            return attendance

        raise UserError(_("Unexpected attendance state: %s") % self.attendance_state)

