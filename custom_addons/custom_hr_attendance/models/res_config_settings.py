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
    saturday_halfday_district = fields.Boolean(
        string='Apply Saturday Half-Day to District Offices',
        default=True,
        config_parameter="hr_attendance.saturday_halfday_district",
        help="Apply Saturday half-day exit time to District Office staff in addition to Head Office."
    )
    enable_lunch_break = fields.Boolean(
        string='Enable Lunch Break',
        default=False,
        config_parameter="hr_attendance.enable_lunch_break",
        help="Enable the lunch break flow: Check-In → Lunch-Out → Back from Lunch → Check-Out."
    )
    enable_overtime_payroll = fields.Boolean(
        string='Enable Overtime Payout for Payroll',
        default=False,
        config_parameter="custom_hr_attendance.enable_overtime_payroll",
        help="When OFF (Default), extra shift work is compensated via Duty OFF (Half-Day/Full-Day). When ON, managers can record and approve overtime for payroll payout."
    )

    # ----------------------------------------------------------
    # CONFIGURABLE REGULATION PARAMETERS (Requirement 3)
    # ----------------------------------------------------------
    attendance_unexcused_consecutive_threshold = fields.Integer(
        string='Discipline Trigger: Consecutive Unexcused Absences (Days)',
        default=3,
        config_parameter='custom_hr_attendance.unexcused_consecutive_threshold',
        help='Auto-generates draft discipline case when consecutive unexcused absences reach this number.'
    )
    attendance_unexcused_monthly_threshold = fields.Integer(
        string='Discipline Trigger: Monthly Cumulative Unexcused Absences (Days)',
        default=5,
        config_parameter='custom_hr_attendance.unexcused_monthly_threshold',
        help='Auto-generates draft discipline case when cumulative monthly unexcused absences reach this number.'
    )
    discipline_managerial_warning1_days = fields.Integer(
        string='Managerial 1st Warning Penalty (Days)',
        default=1,
        config_parameter='discipline_management.managerial_warning1_days'
    )
    discipline_managerial_warning2_days = fields.Integer(
        string='Managerial 2nd Warning Penalty (Days)',
        default=2,
        config_parameter='discipline_management.managerial_warning2_days'
    )
    discipline_managerial_warning3_days = fields.Integer(
        string='Managerial 3rd Warning Penalty (Days)',
        default=3,
        config_parameter='discipline_management.managerial_warning3_days'
    )
    discipline_non_managerial_warning1_pct = fields.Float(
        string='Non-Managerial 1st Warning Penalty (%)',
        default=5.0,
        config_parameter='discipline_management.non_managerial_warning1_pct'
    )
    discipline_non_managerial_warning2_pct = fields.Float(
        string='Non-Managerial 2nd Warning Penalty (%)',
        default=10.0,
        config_parameter='discipline_management.non_managerial_warning2_pct'
    )
    discipline_non_managerial_warning3_pct = fields.Float(
        string='Non-Managerial 3rd Warning Penalty (%)',
        default=20.0,
        config_parameter='discipline_management.non_managerial_warning3_pct'
    )
    discipline_appeal_window_days = fields.Integer(
        string='Appeal Deadline Window (Working Days)',
        default=10,
        config_parameter='discipline_management.appeal_window_days'
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
    enable_checkin_gate = fields.Boolean(
        string='Enable ERP Access Gate (Requires Check-In)',
        default=False,
        config_parameter="hr_attendance.enable_checkin_gate",
        help="When enabled, employees must be checked in to access ERP modules. "
             "Exempt routes (Settings, Attendance, Discuss) are always accessible. "
             "Roll out branch-by-branch after load testing."
    )

    # Target HR User for Escalation 
    escalation_hr_user_id = fields.Many2one(
        'res.users',
        string='HR Escalation Target User',
        config_parameter="hr_attendance.escalation_hr_user_id",
        help="User account to receive HR escalation activities when attendance violation thresholds are breached."
    )

    #  Pluggable Authentication Method Framework
    checkin_auth_method = fields.Selection([
        ('session', 'Odoo Web Session (Standard)'),
        ('pin', 'Employee Security PIN'),
        ('qr', 'Branch Kiosk QR Code'),
    ], string='Check-in Authentication Method', default='session',
        config_parameter="hr_attendance.checkin_auth_method",
        help="Configurable authentication method required before check-in is recorded.")


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
    enable_checkin_grace = fields.Boolean(
        string='Enable Check-in Grace Period',
        default=True,
        config_parameter="hr_attendance.enable_checkin_grace",
        help="When enabled, arrivals within the grace period are recorded as Normal check-in with no penalties."
    )
    checkin_grace_period = fields.Float(
        string='Check-in Grace Period (Hours)',
        default=0.25,
        config_parameter="hr_attendance.checkin_grace_period",
        help="Grace period in hours after shift start where check-in is considered Normal (e.g., 0.25 for 15 minutes)"
    )
    dead_time = fields.Float(
        string='Late Tolerance Window (Dead Time)',
        default=0.33,
        config_parameter="hr_attendance.dead_time",
        help="Tolerance in hours after the grace period where late check-in is allowed before being blocked (e.g., 0.33 for 20 min)"
    )
    checkin_buffer = fields.Float(
        string='Check-in Buffer (Hours)',
        default=0.50,
        config_parameter="hr_attendance.checkin_buffer",
        help="Allowed early check-in buffer before shift start (e.g., 0.50 = 30 minutes)"
    )
    force_checkout_hours = fields.Float(
        string='Post-Shift Force Checkout Grace (Hours)',
        default=3.00,
        config_parameter="hr_attendance.post_shift_grace_hours",
        help="Grace period in hours after official shift end time before force checkout is executed (e.g., 3.0)"
    )
    saturday_exit_time = fields.Float(
        string='Saturday Head Office Exit Time',
        default=12.00,
        config_parameter="hr_attendance.saturday_exit_time",
        help="Default exit time on Saturdays for Head Office staff (e.g., 12.00 for 12:00 PM Noon)"
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

    # ----------------------------------------------------------
    # DISCIPLINE INTEGRATION THRESHOLDS
    # ----------------------------------------------------------
    lateness_hours_violation_threshold = fields.Float(
        string='Cumulative Late Hours Threshold for Discipline (Hours)',
        default=4.0,
        config_parameter="hr_attendance.lateness_hours_violation_threshold",
        help="Total cumulative late hours within the rolling evaluation window that triggers an automatic discipline case."
    )
    lateness_eval_window_months = fields.Integer(
        string='Lateness Evaluation Window (Months)',
        default=3,
        config_parameter="hr_attendance.lateness_eval_window_months",
        help="Rolling evaluation window in months over which cumulative late hours are aggregated (e.g., 3 months)."
    )
    force_checkout_violation_threshold = fields.Integer(
        string='Force Checkout Violation Threshold (Occurrences)',
        default=2,
        config_parameter="hr_attendance.force_checkout_violation_threshold",
        help="Number of force checkouts that triggers an automatic discipline case (Repeated Force Checkout)."
    )

    # ----------------------------------------------------------
    # EMPLOYEE REGULATION WARNING VALIDITY PERIODS (ART. 10.3)
    # ----------------------------------------------------------
    warning_1_validity_months = fields.Integer(
        string='First Written Warning Validity (Months)',
        default=3,
        config_parameter="hr_attendance.warning_1_validity_months",
        help="Validity duration of 1st written warning per Bank Regulation 10.3.1 (Default: 3 months)."
    )
    warning_2_validity_months = fields.Integer(
        string='Second Written Warning Validity (Months)',
        default=6,
        config_parameter="hr_attendance.warning_2_validity_months",
        help="Validity duration of 2nd written warning per Bank Regulation 10.3.2 (Default: 6 months)."
    )
    warning_3_validity_months = fields.Integer(
        string='Final Written Warning Validity (Months)',
        default=12,
        config_parameter="hr_attendance.warning_3_validity_months",
        help="Validity duration of final written warning per Bank Regulation 10.3.3 (Default: 12 months)."
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
            enable_checkin_gate=_get_bool('hr_attendance.enable_checkin_gate', False),
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
        params.set_param('hr_attendance.enable_checkin_gate', str(self.enable_checkin_gate))


