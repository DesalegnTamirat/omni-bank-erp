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
                                 location_exceptions, job_position_exceptions, target_date=None, is_manager=False):
        """
        Shift selection priority:
        1) Date-based Roster Exception (job.position.roster.exception)
        2) Job-position exception shift (job.position.exception)
        3) Location-based shift (location.based.exception)
        4) Default system shift (Full Day)
        """
        if not target_date:
            target_date = fields.Date.context_today(self)

        checkin_buffer = self._get_param_float('hr_attendance.checkin_buffer', 0.50)

        # Helper to format float hours to clean AM/PM string
        def _fmt(val):
            hrs = int(val) % 24
            mins = int(round((val - int(val)) * 60))
            ampm = "AM" if hrs < 12 else "PM"
            dh = hrs if hrs in (1, 12) else (hrs % 12)
            if dh == 0:
                dh = 12
            return f"{dh:02d}:{mins:02d} {ampm}"

        # ----------------------------
        # 1. Roster Exceptions (Date-Based)
        # ----------------------------
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
                    raise UserError(_("Attendance cannot be recorded.\n\nYou have a scheduled Day Off today."))
                shift = line.shift_id
                if shift:
                    _logger.info(
                        "Roster Exception Shift | Shift: %s | Start: %.2f | End: %.2f | Night: %s",
                        shift.name, shift.start_time, shift.end_time, shift.is_night_shift
                    )
                    earliest_checkin = shift.start_time - checkin_buffer
                    if shift.is_night_shift:
                        if current_float >= earliest_checkin or current_float <= shift.end_time:
                            return shift.start_time, shift.end_time
                    else:
                        if earliest_checkin <= current_float <= shift.end_time:
                            _logger.info("Using Roster shift: %.2f - %.2f", shift.start_time, shift.end_time)
                            return shift.start_time, shift.end_time
                        elif current_float < earliest_checkin:
                            raise UserError(_(
                                "Check-in is not allowed yet.\n\n"
                                "You are too early for your scheduled shift (%s - %s).\n"
                                "Check-in window opens at %s (Buffer: %d min)."
                            ) % (_fmt(shift.start_time), _fmt(shift.end_time), _fmt(earliest_checkin), int(round(checkin_buffer * 60))))

        # ----------------------------
        # 2. Job-position-based shifts (Static)
        # ----------------------------
        if job_position_exceptions:
            for job in job_position_exceptions:
                shift = job.shift_id
                if not shift:
                    continue

                _logger.info(
                    "Job Position Exception | Shift: %s | Start: %.2f | End: %.2f | Night: %s",
                    job.job_position_exception_name, shift.start_time, shift.end_time, shift.is_night_shift,
                )

                earliest_checkin = shift.start_time - checkin_buffer

                if shift.is_night_shift:
                    if current_float >= earliest_checkin or current_float <= shift.end_time:
                        return shift.start_time, shift.end_time
                else:
                    if earliest_checkin <= current_float <= shift.end_time:
                        _logger.info("Using Job-Position shift: %.2f - %.2f", shift.start_time, shift.end_time)
                        return shift.start_time, shift.end_time
                    elif current_float < earliest_checkin:
                        # Employee has an active exception shift today, but is trying to check in before the buffer window opens
                        raise UserError(_(
                            "Check-in is not allowed yet.\n\n"
                            "You are too early for your scheduled shift (%s - %s).\n"
                            "Check-in window opens at %s (Buffer: %d min)."
                        ) % (_fmt(shift.start_time), _fmt(shift.end_time), _fmt(earliest_checkin), int(round(checkin_buffer * 60))))

        # ----------------------------
        # 2. Location-based shifts
        # ----------------------------
        for loc in location_exceptions:
            _logger.info("Checking Location Exception: %.2f - %.2f", loc.start_time, loc.end_time)
            earliest_checkin = loc.start_time - checkin_buffer
            if earliest_checkin <= current_float <= loc.end_time:
                return loc.start_time, loc.end_time
            elif current_float < earliest_checkin:
                raise UserError(_(
                    "Check-in is not allowed yet.\n\n"
                    "You are too early for your scheduled shift (%s - %s).\n"
                    "Check-in window opens at %s (Buffer: %d min)."
                ) % (_fmt(loc.start_time), _fmt(loc.end_time), _fmt(earliest_checkin), int(round(checkin_buffer * 60))))

        # If check-in restriction feature toggle is OFF, bypass shift boundary check
        enable_checkin_restriction = self.env['ir.config_parameter'].sudo().get_param(
            'hr_attendance.enable_checkin_restriction', 'True')
        if enable_checkin_restriction.lower() not in ('true', '1'):
            _logger.info("Check-in Restriction Disabled: Returning default shift bounds.")
            return morning_start, exit_time

        # ----------------------------
        # 3. Default system shifts (Full Day)
        # ----------------------------
        earliest_checkin = morning_start - checkin_buffer
        if current_float >= earliest_checkin:
            _logger.info("Using Default Full Day shift: %.2f - %.2f", morning_start, exit_time)
            return morning_start, exit_time

        # MANAGER OVERRIDE
        if is_manager:
            _logger.info("Manager Override: Forcing default shift bounds.")
            return morning_start, exit_time

        raise UserError(_(
            "Check-in is not allowed yet.\n\n"
            "You are too early for your scheduled shift (%s - %s).\n"
            "Check-in window opens at %s (Buffer: %d min)."
        ) % (_fmt(morning_start), _fmt(exit_time), _fmt(earliest_checkin), int(round(checkin_buffer * 60))))

    # ============================================================
    # Check-in Evaluation Logic
    # ============================================================
    def _evaluate_checkin_status(self, current_float, shift_start, dead_time, predefined_late, is_manager=False, allow_late=False):
        status = 'Normal'
        late_time = 0.0
        pre_defined_lateness_hours = 0.0
        checkin_buffer = self._get_param_float('hr_attendance.checkin_buffer', 0.50)

        if predefined_late and current_float <= predefined_late.end_time:
            status = 'Pre-Defined Lateness'
            pre_defined_lateness_hours = round(current_float - shift_start, 4)
        elif current_float <= shift_start:
            status = 'Normal'
        elif current_float <= shift_start + dead_time:
            status = 'Late'
            late_time = max(0.0, round(current_float - shift_start, 4))
        elif is_manager or allow_late:
            status = 'Late'
            late_time = max(0.0, round(current_float - shift_start, 4))
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
            pre_approved_early = round(shift_end - current_float, 4)
        elif current_float >= shift_end:
            status = 'Normal'
        elif current_float < shift_end:
            status = 'Unauthorized Early Exit'
            early_exit = round(shift_end - current_float, 4)
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

    def _get_lunch_window(self, applicable_shift=None):
        """Return (lunch_start, lunch_end) as floats based on shift-specific config or global config."""
        lunch_grace = self._get_param_float('hr_attendance.lunch_grace_time', 0.25)
        if applicable_shift and getattr(applicable_shift, 'has_lunch_break', False):
            lunch_out_time = applicable_shift.lunch_start_time
            lunch_duration = applicable_shift.lunch_duration
        else:
            lunch_out_time = self._get_param_float('hr_attendance.lunch_out_time', 12.0)
            lunch_duration = self._get_param_float('hr_attendance.lunch_duration', 1.0)

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
        saturday_exit = self._get_param_float('hr_attendance.saturday_exit_time', 12.00)

        # ----------------------------------------------------
        # Saturday Half Day Logic (Head Office & District Offices)
        # ----------------------------------------------------
        is_saturday = local_dt.weekday() == 5
        operating_unit = self.default_operating_unit_id
        enable_saturday_halfday = self.env['ir.config_parameter'].sudo().get_param(
            'hr_attendance.enable_saturday_halfday', 'True').lower() in ('true', '1')
        enable_district_saturday = self.env['ir.config_parameter'].sudo().get_param(
            'hr_attendance.saturday_halfday_district', 'True').lower() in ('true', '1')

        unit_type = operating_unit.work_unit_type if operating_unit else False
        is_halfday_unit = (unit_type == 'head_office') or (unit_type == 'district' and enable_district_saturday)

        if enable_saturday_halfday and is_halfday_unit and is_saturday:
            _logger.info("Saturday Half-Day Applied | Employee: %s | Unit: %s", self.name, unit_type)
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

        # ORM-level dismissal block. Even if the employee is still
        # technically 'active', a finalised Level-1 / dismissal discipline case
        # MUST prevent attendance. This stops API callers from bypassing the UI guard.
        if self.env.get('discipline.case'):
            active_dismissal = self.env['discipline.case'].sudo().search([
                ('employee_id', '=', self.id),
                ('punishment_type', '=', 'dismissal'),
                ('state', '=', 'enforced'),
            ], limit=1)
            if active_dismissal:
                raise UserError(_(
                    "Attendance cannot be recorded.\n\n"
                    "Employee %s has an enforced dismissal decision (Case: %s). "
                    "Contact HR to resolve."
                ) % (self.name, active_dismissal.name))

        # ----------------------------------------------------
        # Disciplinary Suspension Validation
        # Checks is_suspended and suspension_type from discipline_management.
        # Employees under any active suspension are blocked from attendance.
        # ----------------------------------------------------
        if hasattr(self, 'is_suspended') and self.is_suspended:
            suspension_label = dict(
                self._fields.get('suspension_type', fields.Selection([])).selection
            ).get(self.suspension_type, self.suspension_type or _('Unknown'))
            raise UserError(_(
                "Attendance cannot be recorded.\n\n"
                "Employee is currently under disciplinary suspension (%s).\n"
                "Please contact HR to resolve the active disciplinary case."
            ) % suspension_label)

        # Leave Validation — delegates to reusable method for testability and future Leave module reuse
        if self._is_covered_by_approved_leave(self.id, today_date):
            leave = self.env['hr.leave'].search([
                ('employee_id', '=', self.id), ('state', '=', 'validate'), ('holiday_status_id', '!=', 80),
                ('date_from', '<=', today_date), ('date_to', '>=', today_date),
            ], limit=1)
            raise UserError(_(
                "Attendance cannot be recorded.\n\n"
                "You are currently on approved leave:\n%s"
            ) % (leave.holiday_status_id.name if leave else _('Unknown Leave')))

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
            ('active', '=', True),
            ('start_date', '<=', today_date),
            '|', ('end_date', '=', False), ('end_date', '>=', today_date)
        ], order='start_date desc, id desc')

        # ----------------------------------------------------
        # Determine Shift
        # ----------------------------------------------------
        shift_start, shift_end = self._select_applicable_shift(
            current_float, morning_start, exit_time, location_exceptions, job_position_exceptions
        )
        # Convert float shift times to Odoo-ready UTC datetimes
        shift_start_utc = self._float_to_utc_datetime(shift_start, local_dt)
        shift_end_utc = self._float_to_utc_datetime(shift_end, local_dt)
        open_attendance = self.env['hr.attendance'].search([
            ('employee_id', '=', self.id), ('check_out', '=', False)
        ], limit=1)

        # ----------------------------------------------------
        # CHECK-IN (when no open attendance exists)
        # ----------------------------------------------------
        if not open_attendance and self.attendance_state != 'lunch_out':
            enable_checkin_restriction = self.env['ir.config_parameter'].sudo().get_param(
                'hr_attendance.enable_checkin_restriction', 'True')
            checkin_restriction_enabled = enable_checkin_restriction.lower() in ('true', '1')

            if checkin_restriction_enabled:
                status, late_time, ot, pre_late = self._evaluate_checkin_status(
                    current_float, shift_start, dead_time, predefined_late
                )
                checkin_dt = utc_naive_dt if status == 'Late' else shift_start_utc
            else:
                # Restriction disabled: do not block check-in, but still evaluate shift lateness
                status, late_time, ot, pre_late = self._evaluate_checkin_status(
                    current_float, shift_start, dead_time, predefined_late, allow_late=True
                )
                checkin_dt = utc_naive_dt
            vals = {
                'employee_id': self.id,
                # 'check_in': utc_naive_dt,
                'check_in': checkin_dt,
                # Real wall-clock check-in moment, kept separately so the
                # live dashboard timer starts counting from 00:00:00 at the
                # actual tap time instead of jumping to elapsed-since-shift-start.
                'actual_check_in': utc_naive_dt,
                'check_in_status': status,
                'late_time_hour': late_time,
                'pre_defined_lateness': pre_late
            }
            if geo_information:
                vals.update({'in_%s' % key: geo_information[key] for key in geo_information})
            _logger.info("Creating Check-in: %s", vals)
            attendance = self.env['hr.attendance'].create(vals)
            self.write({'attendance_state': 'checked_in', 'last_attendance_id': attendance.id})
            # Offload discipline counter increments and violation threshold checks
            # asynchronously so the check-in response is never delayed by side effects.
            attendance._enqueue_attendance_side_effects()
            return attendance

        # ----------------------------------------------------
        # LUNCH-OUT (employee going for lunch)
        # ----------------------------------------------------
        elif self.attendance_state == 'checked_in' and self._is_lunch_break_enabled():
            # Check if employee has a shift-specific lunch break
            active_shift = False
            for job in job_position_exceptions:
                if job.shift_id:
                    active_shift = job.shift_id
                    break

            lunch_start, lunch_end = self._get_lunch_window(applicable_shift=active_shift)
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
        if open_attendance and self.attendance_state != 'lunch_out':
            attendance = open_attendance

            enable_checkout_restriction = self.env['ir.config_parameter'].sudo().get_param(
                'hr_attendance.enable_checkout_restriction', 'True')
            checkout_restriction_enabled = enable_checkout_restriction.lower() in ('true', '1')

            if not checkout_restriction_enabled:
                # Restriction disabled: no shift boundary to snap to, so
                # credit the real wall-clock checkout time instead of
                # always pinning to the official shift end.
                checkout_dt = utc_naive_dt
                status, early_exit, ot, pre_early = 'Normal', 0.0, 0.0, 0.0
            elif shift_end_utc <= attendance.check_in:
                # Guard: the resolved shift end is normally a safe anchor for
                # check_out, but if this attendance's actual check_in already
                # falls at or after that shift end (e.g. employee checked in
                # very late, past the official exit time), snapping check_out
                # to shift_end_utc would land BEFORE check_in and produce a
                # negative/invalid worked_hours. Fall back to the real
                # checkout time in that case instead.
                _logger.warning(
                    "Resolved shift end (%s) is not after check_in (%s) for %s; "
                    "using actual checkout time instead of shift end.",
                    shift_end_utc, attendance.check_in, self.name,
                )
                checkout_dt = utc_naive_dt
                status, early_exit, ot, pre_early = 'Normal', 0.0, 0.0, 0.0
            else:
                checkout_dt = shift_end_utc
                status, early_exit, ot, pre_early = self._evaluate_checkout_status(
                    current_float, shift_end, attendance, utc_naive_dt, min_work_hour, predefined_early_exit
                )

            vals = {
                # 'check_out': utc_naive_dt,
                'check_out': checkout_dt,
                'check_out_status': status,
                'early_exit_hour': early_exit,
                'pre_approved_early_checkout': pre_early
            }
            if geo_information:
                vals.update({'out_%s' % key: geo_information[key] for key in geo_information})
            attendance.write(vals)
            self.write({'attendance_state': 'checked_out', 'last_attendance_id': attendance.id})
            # Offload force-checkout counter increment and violation threshold check asynchronously.
            attendance._enqueue_attendance_side_effects()
            _logger.info("Check-out completed for %s", self.name)
            return attendance

        raise UserError(_("Unexpected attendance state: %s") % self.attendance_state)

    # ============================================================
    # Leave Coverage Check (reusable by Leave module and wizards)
    # ============================================================
    def _is_covered_by_approved_leave(self, employee_id, date):
        """
        Returns True if the given employee has an approved leave record covering the given date.
        Excludes leave type ID 80 (internal Bunna Bank exclusion — verify periodically).
        Extracted here so Leave module wizards can call identical logic without duplication.
        """
        return bool(self.env['hr.leave'].search([
            ('employee_id', '=', employee_id),
            ('state', '=', 'validate'),
            ('holiday_status_id', '!=', 80),
            ('date_from', '<=', date),
            ('date_to', '>=', date),
        ], limit=1))

    def _get_employee_shift_info(self, target_date=None):
        self.ensure_one()
        if not target_date:
            target_date = fields.Date.context_today(self)

        morning_start = self._get_param_float('hr_attendance.morning_time', 8.0)
        exit_time = self._get_param_float('hr_attendance.exit_time', 17.0)

        # 1. Roster Exception
        roster = self.env['job.position.roster.exception'].sudo().search([
            ('employee_id', '=', self.id),
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
                        'is_day_off': True,
                        'has_lunch_break': False,
                        'start_time': 8.0,
                        'end_time': 17.0,
                    }
                shift = line.shift_id
                if shift:
                    return {
                        'name': shift.name,
                        'is_day_off': False,
                        'has_lunch_break': shift.has_lunch_break,
                        'start_time': shift.start_time,
                        'end_time': shift.end_time,
                        'lunch_start_time': shift.lunch_start_time,
                        'lunch_duration': shift.lunch_duration,
                    }

        # 2. Position Exception
        active_exception = self.env['job.position.exception'].sudo().search([
            ('employee_id', '=', self.id),
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
                    'is_day_off': True,
                    'has_lunch_break': False,
                    'start_time': 8.0,
                    'end_time': 17.0,
                }
            shift = active_exception.shift_id
            return {
                'name': shift.name,
                'is_day_off': False,
                'has_lunch_break': shift.has_lunch_break,
                'start_time': shift.start_time,
                'end_time': shift.end_time,
                'lunch_start_time': shift.lunch_start_time,
                'lunch_duration': shift.lunch_duration,
            }

        # 3. Default Global Shift (Sunday is Day Off)
        if target_date.weekday() == 6:
            return {
                'name': 'Default Global Shift (Day Off)',
                'is_day_off': True,
                'has_lunch_break': False,
                'start_time': morning_start,
                'end_time': exit_time,
            }

        enable_lunch = self._is_lunch_break_enabled() if hasattr(self, '_is_lunch_break_enabled') else False
        lunch_start = self._get_param_float('hr_attendance.lunch_out_time', 12.0)
        lunch_duration = self._get_param_float('hr_attendance.lunch_duration', 1.0)

        return {
            'name': 'Default Global Shift',
            'is_day_off': False,
            'has_lunch_break': enable_lunch,
            'start_time': morning_start,
            'end_time': exit_time,
            'lunch_start_time': lunch_start,
            'lunch_duration': lunch_duration,
        }

