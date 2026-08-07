from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import pytz
import logging

_logger = logging.getLogger(__name__)


class HrAttendance(models.Model):
    _name = 'hr.attendance'
    _inherit = ['hr.attendance', 'mail.thread', 'mail.activity.mixin']

    active = fields.Boolean(string="Active", default=True, index=True)
    is_force_checkout = fields.Boolean(string="Force Checkout", default=False, index=True)
    attendance_reason_ids = fields.Many2many("hr.attendance.reason", string="Acknowledgement Reason")
    is_acknowledged = fields.Boolean(string="Manager Acknowledged", default=False, index=True)
    late_by = fields.Char(string="Late By")
    regularization = fields.Boolean(string="Regularization")
    reason_type = fields.Selection(
        [('check_in', 'Acknowledged Check In'),
         ('check_out', 'Acknowledged Check Out')], compute="_compute_reason_type", store=True, index=True)
    acknowledged_by = fields.Many2one('res.users', string="Acknowledged By", readonly=True)
    acknowledged_date = fields.Datetime(string="Acknowledged Date", readonly=True)
    acknowledged_late = fields.Float(string="Acknowledged Late", readonly=True)
    acknowledged_exit = fields.Float(string="Acknowledged Exit", readonly=True)

    check_in_status = fields.Char(string='Check-in Status', index=True)
    late_time_hour = fields.Float(string='Late Time Hour')
    over_time_hour = fields.Float(string='Over Time Hour')
    check_out_status = fields.Char("Check-Out Status", index=True)
    early_exit_hour = fields.Float("Early Exit Hour")
    pre_defined_lateness = fields.Float(string="Pre-Defined")
    pre_approved_early_checkout = fields.Float(string="Pre-Approved Early Checkout")

    # Manual discipline flag by supervisor/HR
    flagged_for_discipline = fields.Boolean(
        string='Flagged for Discipline Review',
        default=False,
        index=True,
        tracking=True,
        help='/ FR-HR or supervisor can flag this attendance record for discipline review.'
    )
    flagged_reason = fields.Char(string='Flag Reason', tracking=True)
    flagged_by_id = fields.Many2one('res.users', string='Flagged By', readonly=True, tracking=True)
    flagged_date = fields.Datetime(string='Flagged Date', readonly=True)

    # Smart button counter (discipline cases referencing this attendance)
    discipline_case_count = fields.Integer(
        string='Discipline Cases',
        compute='_compute_discipline_case_count',
        help='Number of discipline cases where reference = ATT-{this id}.'
    )

    # Overtime payroll approval tracking
    overtime_approved_for_payroll = fields.Boolean(
        string='Overtime Approved for Payroll',
        default=False,
        index=True,
        tracking=True,
        help='Once supervisor approves overtime, this triggers payroll payload creation.'
    )
    overtime_approved_by_id = fields.Many2one('res.users', string='Overtime Approved By', readonly=True)
    overtime_approved_date = fields.Datetime(string='Overtime Approved Date', readonly=True)

    # ----------------------------------------------------------
    # LUNCH BREAK FIELDS
    # ----------------------------------------------------------
    lunch_out = fields.Datetime(
        string='Lunch Out',
        readonly=True,
        copy=False,
        help='Time the employee left for lunch break.',
        index=True,
    )
    lunch_in = fields.Datetime(
        string='Lunch In',
        readonly=True,
        copy=False,
        help='Time the employee returned from lunch break.',
        index=True,
    )
    lunch_break_hours = fields.Float(
        string='Lunch Break (hrs)',
        compute='_compute_lunch_break_hours',
        store=True,
        readonly=True,
        help='Actual lunch break duration in hours (lunch_in - lunch_out).',
    )

    @api.depends('lunch_out', 'lunch_in')
    def _compute_lunch_break_hours(self):
        for rec in self:
            if rec.lunch_out and rec.lunch_in and rec.lunch_in > rec.lunch_out:
                delta = rec.lunch_in - rec.lunch_out
                rec.lunch_break_hours = delta.total_seconds() / 3600.0
            else:
                rec.lunch_break_hours = 0.0

    @api.depends('check_in', 'check_out', 'lunch_break_hours')
    def _compute_worked_hours(self):
        """Override to subtract actual lunch break duration from worked hours."""
        super()._compute_worked_hours()
        for rec in self:
            if rec.lunch_break_hours > 0:
                rec.worked_hours = max(0.0, rec.worked_hours - rec.lunch_break_hours)

    def unlink(self):
        """ Soft delete: Archive records instead of removing them from database """
        for rec in self:
            rec.write({'active': False})
        return True

    def _compute_discipline_case_count(self):
        """Count discipline cases referencing this attendance record."""
        for rec in self:
            if self.env.get('discipline.case'):
                rec.discipline_case_count = self.env['discipline.case'].sudo().search_count([
                    ('reference', '=', 'ATT-%s' % rec.id)
                ])
            else:
                rec.discipline_case_count = 0

    def action_flag_for_discipline(self):
        """
        / FR-Flag this attendance record for discipline review.
        Opens a popup so the supervisor can enter a reason.
        """
        self.ensure_one()
        return {
            'name': _('Flag for Discipline Review'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.attendance.flag.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_attendance_id': self.id,
                'default_employee_id': self.employee_id.id,
            }
        }

    def action_approve_overtime_for_payroll(self):
        """
        Approve overtime and create a payroll payload record.
        Restricted to managers and HR.
        """
        self.ensure_one()
        if not self.over_time_hour or self.over_time_hour <= 0:
            from odoo.exceptions import UserError
            raise UserError(_('No overtime hours recorded for this attendance record.'))
        if self.overtime_approved_for_payroll:
            from odoo.exceptions import UserError
            raise UserError(_('Overtime has already been approved for this record.'))

        self.write({
            'overtime_approved_for_payroll': True,
            'overtime_approved_by_id': self.env.user.id,
            'overtime_approved_date': fields.Datetime.now(),
        })

        # Create attendance.payroll.payload via factory method
        if self.env.get('attendance.payroll.payload'):
            self.env['attendance.payroll.payload'].sudo().create({
                'employee_id': self.employee_id.id,
                'payload_type': 'overtime',
                'source_attendance_id': self.id,
                'hours': self.over_time_hour,
                'effective_date': fields.Date.context_today(self),
                'notes': _('Overtime approved by %s on %s for attendance on %s.') % (
                    self.env.user.name,
                    fields.Datetime.now().date(),
                    self.check_in.date() if self.check_in else 'N/A'
                )
            })

        _logger.info(
            'Overtime approved for employee %s, attendance ID %s, hours: %.2f',
            self.employee_id.name, self.id, self.over_time_hour
        )
        return True

    # ----------------------------------------------------------
    # ACTUAL (WALL-CLOCK) CHECK-IN TIME
    # ----------------------------------------------------------
    # `check_in` itself is intentionally snapped to the official shift
    # start time by _attendance_action_change() (see restrict_checkin.py)
    # since it drives worked_hours / weekly totals / payroll payloads.
    # `actual_check_in` instead stores the real moment the employee
    # tapped "Check In", so the live dashboard timer can start ticking
    # from 00:00:00 at that exact moment instead of jumping to the
    # elapsed time since the official shift start.
    actual_check_in = fields.Datetime(
        string='Actual Check-in Time',
        readonly=True,
        copy=False,
        help='Real wall-clock time the employee tapped Check In. Used only '
             'by the live attendance dashboard timer, never for worked-hours '
             'or payroll calculations.',
    )

    #track ip
    check_in_ip = fields.Char(
        string='Check-in IP Address',
        readonly=True,
        copy=False,
        help='IP address of the device used when the employee checked in.',
    )

    check_out_ip = fields.Char(
        string='Check-out IP Address',
        readonly=True,
        copy=False,
        help='IP address of the device used when the employee checked out.',
    )

    # / Device information capture
    check_in_device_info = fields.Char(
        string='Check-in Device Info',
        readonly=True,
        copy=False,
        help='User-Agent and device information captured during check-in.',
    )
    check_out_device_info = fields.Char(
        string='Check-out Device Info',
        readonly=True,
        copy=False,
        help='User-Agent and device information captured during check-out.',
    )

    def _resolve_request_device_info(self):
        """/ Captures client User-Agent device info."""
        try:
            from odoo.http import request
            if request and request.httprequest:
                user_agent = request.httprequest.headers.get('User-Agent')
                if user_agent:
                    return user_agent[:250]  # truncate to fit Char field limit
        except RuntimeError:
            pass
        return False

    def _resolve_request_ip(self, vals=None, context_key='attendance_check_in_ip'):
        """
        Generic IP resolver used for both check-in and check-out.

        Priority:
          1. Explicit value already present in vals (e.g. passed by an
             external/API caller)
          2. Value passed via context under `context_key`
          3. X-Forwarded-For header (first IP = original client)
          4. REMOTE_ADDR / remote_addr from the WSGI environ
        """
        field_name = 'check_in_ip' if 'check_in' in context_key else 'check_out_ip'
        if vals and vals.get(field_name):
            return vals[field_name]

        ip = self.env.context.get(context_key)
        if ip:
            return ip

        try:
            from odoo.http import request
            if request and request.httprequest:
                forwarded = request.httprequest.headers.get('X-Forwarded-For')
                if forwarded:
                    return forwarded.split(',')[0].strip()
                return (
                    request.httprequest.environ.get('REMOTE_ADDR')
                    or request.httprequest.remote_addr
                )
        except RuntimeError:
            pass

        return False

    def _is_ip_tracking_enabled(self):
        """Check if IP address tracking is enabled in configuration."""
        param = self.env['ir.config_parameter'].sudo().get_param('hr_attendance.enable_ip_tracking', 'True')
        return param.lower() in ('true', '1')

    def _resolve_check_in_ip(self, vals=None):
        """Resolve the IP for a check-in event."""
        if not self._is_ip_tracking_enabled():
            return False
        return self._resolve_request_ip(vals, context_key='attendance_check_in_ip')

    def _resolve_check_out_ip(self, vals=None):
        """Resolve the IP for a check-out event."""
        if not self._is_ip_tracking_enabled():
            return False
        return self._resolve_request_ip(vals, context_key='attendance_check_out_ip')

    # ----------------------------------------------------------
    # PERMISSION HELPER

    # ----------------------------------------------------------
    def _can_acknowledge(self, user):
        """Centralized permission check"""
        return any([
            user.has_group('custom_hr_attendance.group_hr_attendance_job_position_user'),
            user.has_group('custom_hr_attendance.group_hr_attendance_it_driver_user'),
            user.has_group('hr_attendance.group_hr_attendance_manager'),
            user.has_group('hr_attendance.group_hr_attendance_user'),
        ])

    @api.depends('is_acknowledged', 'check_in', 'check_out', 'attendance_reason_ids')
    def _compute_reason_type(self):
        for rec in self:
            if not rec.is_acknowledged and not rec.attendance_reason_ids:
                rec.reason_type = False
                continue
            elif rec.check_in and not rec.check_out:
                rec.reason_type = 'check_in'
            else:
                rec.reason_type = 'check_out'

    def _apply_manager_logic(self):
        self.ensure_one()
        local_tz = pytz.timezone('Africa/Addis_Ababa')
        emp = self.employee_id

        _logger.info("Applying Manager Logic for Employee: %s", emp.name)

        def _get_param_float(key, default):
            return float(self.env['ir.config_parameter'].sudo().get_param(key, default))

        m_start = _get_param_float('hr_attendance.morning_time', 8.0)
        e_time = _get_param_float('hr_attendance.exit_time', 17.0)

        loc_ex = self.env['location.based.exception'].search(
            [('operating_unit', '=', emp.default_operating_unit_id.id)])
        job_ex = self.env['job.position.exception'].search([('employee_id', '=', emp.id), ('status', '=', 'active')])

        # Phase 2: Check for Technical Failure or Operational Disruption reasons
        reason_codes = self.attendance_reason_ids.mapped('code')
        if 'TECHNICAL_FAILURE' in reason_codes or 'Technical' in reason_codes:
            if self.reason_type == 'check_in':
                self.check_in_status = 'Technical Failure'
            else:
                self.check_out_status = 'Technical Failure'
            return
        elif 'OPERATIONAL_DISRUPTION' in reason_codes:
            if self.reason_type == 'check_in':
                self.check_in_status = 'Operational Disruption'
            else:
                self.check_out_status = 'Operational Disruption'
            return

        # ----------------------------------------------------------
        # MANUAL CHECK-IN CALCULATION
        # ----------------------------------------------------------
        if self.reason_type == 'check_in' and self.check_in:
            dt_local = pytz.utc.localize(self.check_in).astimezone(local_tz)
            f_time = dt_local.hour + dt_local.minute / 60 + dt_local.second / 3600

            s_start, s_end = emp._select_applicable_shift(f_time, m_start,  e_time, loc_ex, job_ex, is_manager=True)

            _logger.info("Manual Check-in | Selected Time: %.2f | Shift Start: %.2f", f_time, s_start)

            if f_time > s_start:
                self.check_in_status = 'Acknowledged Lateness'
                self.acknowledged_late = round((f_time - s_start) * 60, 2)
            else:
                self.check_in_status = 'Normal'
                self.acknowledged_late = 0.0

        # ----------------------------------------------------------
        # MANUAL CHECK-OUT CALCULATION
        # ----------------------------------------------------------
        elif self.reason_type == 'check_out' and self.is_acknowledged and self.check_out:
            dt_local = pytz.utc.localize(self.check_out).astimezone(local_tz)
            f_time = dt_local.hour + dt_local.minute / 60 + dt_local.second / 3600

            s_start, s_end = emp._select_applicable_shift(f_time, m_start, e_time, loc_ex, job_ex, is_manager=True)

            _logger.info("Manual Check-out | Selected Time: %.2f | Shift End: %.2f", f_time, s_end)

            if f_time < s_end:
                self.check_out_status = 'Acknowledged Early check out'
                self.acknowledged_exit = round((s_end - f_time) * 60, 2)
            else:
                self.check_out_status = 'Normal'
                self.acknowledged_exit = 0.0

    @api.model_create_multi
    def create(self, vals_list):
        user = self.env.user
        can_ack = self._can_acknowledge(user)
        params = self.env['ir.config_parameter'].sudo()
        window_sec = float(params.get_param('hr_attendance.duplicate_checkin_window_seconds', 30.0))

        for vals in vals_list:
            emp_id = vals.get('employee_id')
            if emp_id and window_sec > 0:
                import datetime
                recent = self.sudo().search([
                    ('employee_id', '=', emp_id),
                    ('create_date', '>=', fields.Datetime.now() - datetime.timedelta(seconds=window_sec)),
                ], limit=1)
                if recent:
                    raise ValidationError(_('Duplicate submission detected. Please wait %d seconds between check-in requests.') % int(window_sec))

            if can_ack and vals.get('attendance_reason_ids'):
                vals.update({
                    'is_acknowledged': True,
                    'acknowledged_by': user.id,
                    'acknowledged_date': fields.Datetime.now()
                })

            # ---- track ip & device: stamp check-in IP & device info on creation ----
            if not vals.get('check_in_ip'):
                ip = self._resolve_check_in_ip(vals)
                if ip:
                    vals['check_in_ip'] = ip
            if not vals.get('check_in_device_info'):
                device_info = self._resolve_request_device_info()
                if device_info:
                    vals['check_in_device_info'] = device_info

        res = super(HrAttendance, self).create(vals_list)
        for record in res:
            if record.is_acknowledged:
                record._apply_manager_logic()
        return res

    def write(self, vals):
        user = self.env.user
        if self._can_acknowledge(user) and vals.get('attendance_reason_ids'):
            vals.update({
                'is_acknowledged': True,
                'acknowledged_by': user.id,
                'acknowledged_date': fields.Datetime.now()
            })

        # ---- track ip & device: stamp check-out IP & device info when check_out is set ----
        if vals.get('check_out'):
            if not vals.get('check_out_ip'):
                ip = self._resolve_check_out_ip(vals)
                if ip:
                    vals['check_out_ip'] = ip
            if not vals.get('check_out_device_info'):
                device_info = self._resolve_request_device_info()
                if device_info:
                    vals['check_out_device_info'] = device_info

        # Phase 8: Audit log immutability hardening guard
        # Block core attendance edits if linked to a payroll payload already transferred or processed.
        core_fields = {'check_in', 'check_out', 'employee_id', 'check_in_status', 'check_out_status'}
        if any(f in vals for f in core_fields):
            for rec in self:
                if self.env.get('attendance.payroll.payload'):
                    processed_payload = self.env['attendance.payroll.payload'].sudo().search([
                        ('source_attendance_id', '=', rec.id),
                        ('state', 'in', ['transferred', 'processed'])
                    ], limit=1)
                    if processed_payload:
                        from odoo.exceptions import UserError
                        raise UserError(_(
                            'Audit Immutability Violation: Attendance record for %s on %s has already '
                            'been consumed by Payroll (Payload %s, State: %s). Direct edits are locked.'
                        ) % (rec.employee_id.name, rec.check_in.date() if rec.check_in else '', processed_payload.display_name, processed_payload.state))

        res = super(HrAttendance, self).write(vals)

        # Trigger logic if reason or times change
        if any(f in vals for f in ['attendance_reason_ids', 'check_in', 'check_out']):
            for rec in self:
                if rec.attendance_reason_ids:
                    rec._compute_reason_type()
                    rec._apply_manager_logic()
        return res

    # ----------------------------------------------------------
    # VALIDATIONS
    # ----------------------------------------------------------
    @api.constrains('attendance_reason_ids', 'is_acknowledged')
    def _check_acknowledgement_rules(self):
        for rec in self:
            if not rec.attendance_reason_ids:
                continue
            writer = rec.write_uid or self.env.user
            if not rec._can_acknowledge(writer):
                raise ValidationError(_("Only authorized users can acknowledge attendance."))
            if rec.employee_id.user_id == writer:
                raise ValidationError(_("You cannot acknowledge your own attendance."))
            if not rec.is_acknowledged:
                raise ValidationError(_("Acknowledgement requires at least one reason."))

    @api.constrains('attendance_reason_ids', 'reason_type')
    def _check_reason_usage(self):
        for rec in self:
            if not rec.reason_type:
                continue
            for reason in rec.attendance_reason_ids:
                if reason.action_type not in ('both', rec.reason_type):
                    raise ValidationError(_("Reason '%s' cannot be used for this acknowledgement.") % reason.name)

    # ----------------------------------------------------------
    # OFF-PEAK AUTOMATED CRON METHODS
    # ----------------------------------------------------------
    @api.model
    def cron_automatic_force_checkout(self):
        """
        Executes a set-based SQL update off-peak to automatically force check-out 
        any employees who remained checked-in past the configured threshold (default 14h).
        Runs cleanly without locking worker processes.
        """
        threshold_hours = float(self.env['ir.config_parameter'].sudo().get_param('hr_attendance.force_checkout_hours', 14.0))
        sql = """
            UPDATE hr_attendance
            SET check_out = check_in + (interval '1 hour' * %s),
                check_out_status = 'Force Checkout',
                is_force_checkout = TRUE,
                write_date = NOW()
            WHERE check_out IS NULL 
              AND check_in <= NOW() - (interval '1 hour' * %s)
              AND (active = TRUE OR active IS NULL);
        """
        self.env.cr.execute(sql, (threshold_hours, threshold_hours))
        _logger.info("Executed off-peak automatic force checkout cron.")

    @api.model
    def cron_automatic_absence_detection(self):
        """
        Off-peak cron to detect employees who had no attendance and no approved leave
        on scheduled work days. For each absent employee:
          1. Logs the absence
          2. Creates an attendance.payroll.payload (type: absence) so payroll can deduct
          3. Sends a discipline signal to the discipline module if the employee has
             accumulated >= configured absence threshold
        """
        enabled = self.env['ir.config_parameter'].sudo().get_param('hr_attendance.enable_auto_absence', 'True')
        if enabled.lower() not in ('true', '1'):
            return

        today = fields.Date.context_today(self)
        yesterday = fields.Date.subtract(today, days=1)

        sql = """
            SELECT emp.id, emp.name
            FROM hr_employee emp
            WHERE emp.active = TRUE
              AND NOT EXISTS (
                  SELECT 1 FROM hr_attendance att
                  WHERE att.employee_id = emp.id
                    AND att.check_in >= %s::timestamp
                    AND att.check_in < %s::timestamp
                    AND (att.active = TRUE OR att.active IS NULL)
              )
              AND NOT EXISTS (
                  SELECT 1 FROM hr_leave l
                  WHERE l.employee_id = emp.id
                    AND l.state = 'validate'
                    AND l.date_from <= %s
                    AND l.date_to >= %s
              );
        """
        self.env.cr.execute(sql, (yesterday, today, yesterday, yesterday))
        absent_employees = self.env.cr.fetchall()
        _logger.info(
            "Absence cron found %d absent employees for date %s.",
            len(absent_employees), yesterday
        )

        params = self.env['ir.config_parameter'].sudo()
        absence_discipline_threshold = int(params.get_param(
            'hr_attendance.absence_discipline_threshold', 3
        ))

        for emp_id, emp_name in absent_employees:
            employee = self.env['hr.employee'].browse(emp_id)

            # a: Create payroll payload for absence deduction
            if self.env.get('attendance.payroll.payload'):
                self.env['attendance.payroll.payload'].sudo().create_absence_payload(
                    employee_id=emp_id,
                    absence_date=yesterday,
                    hours=8.0,
                )

            # b: Check absence counter and signal discipline if threshold reached
            if hasattr(employee, 'consecutive_absence_count'):
                employee.consecutive_absence_count = (employee.consecutive_absence_count or 0) + 1
                if employee.consecutive_absence_count >= absence_discipline_threshold:
                    # Signal the discipline module to create a case
                    if self.env.get('discipline.case'):
                        self.env['discipline.case'].sudo()._create_from_attendance(
                            emp_id, 'absence', 0
                        )
                        employee.consecutive_absence_count = 0
                        _logger.info(
                            "Discipline signal sent for employee %s after %d consecutive absences.",
                            emp_name, absence_discipline_threshold
                        )
            else:
                _logger.info(
                    "Employee %s absent on %s. No consecutive_absence_count field — discipline threshold not checked.",
                    emp_name, yesterday
                )

    @api.model
    def cron_job_abandonment_detection(self):
        """
        Detect job abandonment — employees absent for 3+ consecutive working days
        with no approved leave or explanation. Creates a discipline case automatically.
        BRD definition: 3 consecutive working days = job abandonment trigger.
        """
        enabled = self.env['ir.config_parameter'].sudo().get_param(
            'hr_attendance.enable_job_abandonment_cron', 'True'
        )
        if enabled.lower() not in ('true', '1'):
            return

        today = fields.Date.context_today(self)
        abandonment_days = int(self.env['ir.config_parameter'].sudo().get_param(
            'hr_attendance.job_abandonment_days', 3
        ))
        # Look back abandonment_days working days (simple calendar days; refine with resource.calendar if needed)
        from datetime import timedelta
        check_from = today - timedelta(days=abandonment_days + 1)  # +1 for safety buffer

        sql = """
            SELECT emp.id, emp.name
            FROM hr_employee emp
            WHERE emp.active = TRUE
              AND NOT EXISTS (
                  SELECT 1 FROM discipline_case dc
                  WHERE dc.employee_id = emp.id
                    AND dc.reference LIKE 'JOB-ABANDON-%%'
                    AND dc.state NOT IN ('revoked', 'closed')
              )
              AND (
                  SELECT COUNT(DISTINCT att.check_in::date)
                  FROM hr_attendance att
                  WHERE att.employee_id = emp.id
                    AND att.check_in >= %s
                    AND (att.active = TRUE OR att.active IS NULL)
              ) = 0
              AND NOT EXISTS (
                  SELECT 1 FROM hr_leave l
                  WHERE l.employee_id = emp.id
                    AND l.state = 'validate'
                    AND l.date_from <= %s
                    AND l.date_to >= %s
              );
        """
        self.env.cr.execute(sql, (check_from, today, check_from))
        abandoned_employees = self.env.cr.fetchall()

        for emp_id, emp_name in abandoned_employees:
            _logger.warning(
                "Job abandonment detected for employee %s (%d). Creating discipline case.",
                emp_name, emp_id
            )
            if self.env.get('discipline.case'):
                offense_xmlid = 'custom_hr_attendance.offense_job_abandonment'
                offense = self.env.ref(offense_xmlid, raise_if_not_found=False)
                if not offense:
                    # Fall back to creating a case without a specific offense
                    _logger.warning("offense_job_abandonment not found. Skipping case creation for %s.", emp_name)
                    continue
                case = self.env['discipline.case'].sudo().create({
                    'employee_id': emp_id,
                    'offense_id': offense.id,
                    'description': _(
                        '/ Job Abandonment: Employee %s has been absent for %d+ consecutive working days '
                        '(from %s to %s) with no approved leave on record. '
                        'This case was auto-created by the attendance absence monitoring cron.'
                    ) % (emp_name, abandonment_days, check_from, today),
                    'reference': 'JOB-ABANDON-%s-%s' % (emp_id, today),
                })
                if hasattr(case, 'action_initiate'):
                    case.action_initiate()
                _logger.info(
                    "Job abandonment discipline case %s created for employee %s.",
                    case.name, emp_name
                )

    @api.model
    def cron_notify_missing_attendance(self):
        """
        FR-Missing check-in / check-out notification to employees.
        Runs periodically during business hours (08:15–18:00).
        Notifies employees who are missing check-in or check-out.
        Deduplicates via hr.attendance.notification.log.
        """
        today = fields.Date.context_today(self)
        notif_log = self.env['hr.attendance.notification.log']

        # 1. MISSING CHECK-IN: active employees with no attendance and no approved leave today
        sql_missing_in = """
            SELECT emp.id, emp.name, emp.user_id
            FROM hr_employee emp
            WHERE emp.active = TRUE
              AND NOT EXISTS (
                  SELECT 1 FROM hr_attendance att
                  WHERE att.employee_id = emp.id
                    AND att.check_in >= %s::timestamp
                    AND (att.active = TRUE OR att.active IS NULL)
              )
              AND NOT EXISTS (
                  SELECT 1 FROM hr_leave l
                  WHERE l.employee_id = emp.id
                    AND l.state = 'validate'
                    AND l.date_from <= %s
                    AND l.date_to >= %s
              );
        """
        self.env.cr.execute(sql_missing_in, (today, today, today))
        missing_in_records = self.env.cr.fetchall()

        for emp_id, emp_name, user_id in missing_in_records:
            if notif_log.log_and_check(emp_id, 'missing_checkin', today):
                if user_id:
                    self.env['mail.activity'].sudo().create({
                        'res_model_id': self.env.ref('hr.model_hr_employee').id,
                        'res_id': emp_id,
                        'user_id': user_id,
                        'summary': _('Reminder: Missing Check-In for Today'),
                        'note': _('Dear %s, you have not recorded a check-in for today (%s). Please check in or submit an attendance request.') % (emp_name, today),
                        'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                    })

        # 2. MISSING CHECK-OUT: employees with an open attendance record from today
        open_attendances = self.sudo().search([
            ('check_out', '=', False),
            ('check_in', '>=', today),
        ])
        for att in open_attendances:
            emp = att.employee_id
            if emp and emp.user_id:
                if notif_log.log_and_check(emp.id, 'missing_checkout', today):
                    self.env['mail.activity'].sudo().create({
                        'res_model_id': self.env.ref('hr_attendance.model_hr_attendance').id,
                        'res_id': att.id,
                        'user_id': emp.user_id.id,
                        'summary': _('Reminder: Open Attendance / Missing Check-Out'),
                        'note': _('Dear %s, your attendance session is still open. Please check out before leaving.') % emp.name,
                        'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                    })


    # ============================================================
    # DATABASE INDEXES — called once on module install / upgrade
    # Partial and composite indexes for O(1) hot-path queries at
    # 6,000+ concurrent check-ins without row-lock contention.
    # ============================================================
    def _auto_init(self):
        res = super()._auto_init()
        # Partial index: open attendance records (WHERE check_out IS NULL).
        # Used by every check-out lookup — avoid full-table scans.
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS hr_attendance_employee_open_idx
            ON hr_attendance (employee_id)
            WHERE check_out IS NULL;
        """)
        # Composite index for date-range queries on attendance per employee.
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS hr_attendance_employee_checkin_idx
            ON hr_attendance (employee_id, check_in);
        """)
        # Index on check_in_status for discipline counter queries.
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS hr_attendance_checkin_status_idx
            ON hr_attendance (check_in_status);
        """)
        # Partial index on is_force_checkout for discipline and reporting queries.
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS hr_attendance_force_checkout_idx
            ON hr_attendance (employee_id)
            WHERE is_force_checkout = TRUE;
        """)
        return res

    # ============================================================
    # ATTENDANCE SIDE EFFECTS — HOT-PATH BRIDGE
    # Called once per check-in/check-out by restrict_checkin.py.
    # Synchronous work here is strictly O(1): only reads already-set
    # fields on self (no queries). All cross-module work (discipline
    # case creation) is delegated to the discipline integration layer.
    # ============================================================
    def _enqueue_attendance_side_effects(self):
        """
        Single bridge between the check-in transaction and all side-effect logic.
        Delegates to discipline_case_attendance.py (Phase 5) where the
        actual rolling counter increments and threshold checks live.
        Keeping this method minimal ensures the check-in response time
        is never affected by discipline or payroll logic.
        """
        self.ensure_one()
        # Delegate to the discipline integration mixin if it's loaded.
        # The method is defined in discipline_case_attendance.py (Phase 5).
        if hasattr(self, '_process_attendance_violation_counters'):
            self._process_attendance_violation_counters()
