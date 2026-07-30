from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ----------------------------------------------------------
    # PER-FEATURE TOGGLES
    # ----------------------------------------------------------
    enable_checkin_restriction = fields.Boolean(
        string='Enable Check-in Time Restriction',
        default=True,
        config_parameter="hr_attendance.enable_checkin_restriction",
        help="Enforce morning check-in time window. When OFF, employees can check in at any time."
    )
    enable_checkout_restriction = fields.Boolean(
        string='Enable Check-out Time Restriction',
        default=True,
        config_parameter="hr_attendance.enable_checkout_restriction",
        help="Enforce shift-end check-out restriction. When OFF, employees can check out at any time."
    )
    enable_saturday_halfday = fields.Boolean(
        string='Enable Saturday Half-Day (Head Office)',
        default=True,
        config_parameter="hr_attendance.enable_saturday_halfday",
        help="Apply Saturday half-day exit time for Head Office employees."
    )
    enable_lunch_break = fields.Boolean(
        string='Enable Lunch Break',
        default=False,
        config_parameter="hr_attendance.enable_lunch_break",
        help="Enable the lunch break flow: Check-In → Lunch-Out → Back from Lunch → Check-Out."
    )
    enable_auto_absence = fields.Boolean(
        string='Enable Automatic Absence Detection',
        default=True,
        config_parameter="hr_attendance.enable_auto_absence",
        help="Automatically detect and log missing attendance records for employees without approved leave"
    )
    enable_ip_tracking = fields.Boolean(
        string='Enable IP Address Tracking',
        default=True,
        config_parameter="hr_attendance.enable_ip_tracking",
        help="Track IP address of device used when employee checks in and checks out"
    )

    # ----------------------------------------------------------
    # ATTENDANCE TIME SETTINGS
    # ----------------------------------------------------------
    morning_time = fields.Float(
        string='Default Morning Check-in Time',
        default=8.00,
        config_parameter="hr_attendance.morning_time",
        help="Default time for morning check-in (in 24-hour format, e.g., 8.00 for 8:00 AM)"
    )
    exit_time = fields.Float(
        string='Default Exit Time',
        default=17.00,
        config_parameter="hr_attendance.exit_time",
        help="Default Exit time  (in 24-hour format, e.g., 17.00 for 5:00 PM)"
    )
    dead_time = fields.Float(
        string='Default Dead Time',
        default=0.25,
        config_parameter="hr_attendance.dead_time",
        help="Default Dead time  (in 24-hour format, e.g., 0.25 for 15 Minutes,  0.5 for 30 Minutes)"
    )
    checkin_buffer = fields.Float(
        string='Check-in Buffer (Hours)',
        default=0.50,
        config_parameter="hr_attendance.checkin_buffer",
        help="Allowed early check-in buffer before shift start (e.g., 0.5 = 30 minutes)"
    )
    force_checkout_hours = fields.Float(
        string='Force Checkout Threshold (Hours)',
        default=14.00,
        config_parameter="hr_attendance.force_checkout_hours",
        help="Hours after check-in before automatic force checkout is performed (e.g., 14.0)"
    )
    saturday_exit_time = fields.Float(
        string='Saturday Head Office Exit Time',
        default=14.75,
        config_parameter="hr_attendance.saturday_exit_time",
        help="Default exit time on Saturdays for Head Office staff (e.g., 14.75 for 2:45 PM)"
    )

    # ----------------------------------------------------------
    # LUNCH BREAK SETTINGS
    # ----------------------------------------------------------
    lunch_out_time = fields.Float(
        string='Lunch Break Start Time',
        default=12.00,
        config_parameter="hr_attendance.lunch_out_time",
        help="Time when lunch break starts (24-hour format, e.g., 12.00 for noon)"
    )
    lunch_duration = fields.Float(
        string='Lunch Break Duration (Hours)',
        default=1.00,
        config_parameter="hr_attendance.lunch_duration",
        help="Duration of the lunch break in hours (e.g., 1.0 = 1 hour, 0.5 = 30 minutes)"
    )
    lunch_grace_time = fields.Float(
        string='Lunch Grace Time (Hours)',
        default=0.25,
        config_parameter="hr_attendance.lunch_grace_time",
        help="Grace period around the lunch window in hours (e.g., 0.25 = 15 minutes before/after)"
    )

    def get_values(self):
        res = super().get_values()
        params = self.env['ir.config_parameter'].sudo()

        def _get_bool(key, default=True):
            """Read a boolean config parameter stored as a string."""
            val = params.get_param(key)
            if val is False or val is None:
                return default
            return val.lower() in ('true', '1', 'yes')

        res.update(
            # Feature toggles
            enable_checkin_restriction=_get_bool('hr_attendance.enable_checkin_restriction', True),
            enable_checkout_restriction=_get_bool('hr_attendance.enable_checkout_restriction', True),
            enable_saturday_halfday=_get_bool('hr_attendance.enable_saturday_halfday', True),
            enable_lunch_break=_get_bool('hr_attendance.enable_lunch_break', False),
            enable_auto_absence=_get_bool('hr_attendance.enable_auto_absence', True),
            enable_ip_tracking=_get_bool('hr_attendance.enable_ip_tracking', True),
        )
        return res

    def set_values(self):
        """ Override to ensure proper float precision and explicit boolean string storage """
        self.ensure_one()
        if self.morning_time >= self.exit_time:
            raise ValidationError(_("Default Morning Check-in Time must be earlier than Default Exit Time."))
        if self.lunch_duration < 0 or self.lunch_grace_time < 0 or self.checkin_buffer < 0:
            raise ValidationError(_("Duration and buffer values cannot be negative."))

        # Round floats to 2 decimal places
        self.morning_time = round(self.morning_time, 2)
        self.exit_time = round(self.exit_time, 2)
        self.dead_time = round(self.dead_time, 2)
        self.checkin_buffer = round(self.checkin_buffer, 2)
        self.force_checkout_hours = round(self.force_checkout_hours, 2)
        self.saturday_exit_time = round(self.saturday_exit_time, 2)
        self.lunch_out_time = round(self.lunch_out_time, 2)
        self.lunch_duration = round(self.lunch_duration, 2)
        self.lunch_grace_time = round(self.lunch_grace_time, 2)
        super().set_values()
        # Explicitly store booleans as strings to avoid ir.config_parameter ambiguity
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('hr_attendance.enable_checkin_restriction', str(self.enable_checkin_restriction))
        params.set_param('hr_attendance.enable_checkout_restriction', str(self.enable_checkout_restriction))
        params.set_param('hr_attendance.enable_saturday_halfday', str(self.enable_saturday_halfday))
        params.set_param('hr_attendance.enable_lunch_break', str(self.enable_lunch_break))
        params.set_param('hr_attendance.enable_auto_absence', str(self.enable_auto_absence))
        params.set_param('hr_attendance.enable_ip_tracking', str(self.enable_ip_tracking))


