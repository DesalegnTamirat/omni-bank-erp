from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import pytz
import logging

_logger = logging.getLogger(__name__)


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

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
        for vals in vals_list:
            if can_ack and vals.get('attendance_reason_ids'):
                vals.update({
                    'is_acknowledged': True,
                    'acknowledged_by': user.id,
                    'acknowledged_date': fields.Datetime.now()
                })

            # ---- track ip: stamp check-in IP on creation ----
            if not vals.get('check_in_ip'):
                ip = self._resolve_check_in_ip(vals)
                if ip:
                    vals['check_in_ip'] = ip

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

        # ---- track ip: stamp check-out IP when check_out is being set ----
        if vals.get('check_out') and not vals.get('check_out_ip'):
            ip = self._resolve_check_out_ip(vals)
            if ip:
                vals['check_out_ip'] = ip

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
        on scheduled work days, ensuring high performance without daytime overhead.
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
        _logger.info("Executed off-peak automatic absence detection cron. Found %d absent employees for date %s.", len(absent_employees), yesterday)


