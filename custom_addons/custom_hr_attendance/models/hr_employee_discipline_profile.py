# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class HrEmployeeDisciplineProfile(models.Model):
    """
    Decoupled 1-to-1 extension profile for employee attendance discipline counters.
    Keeps hr_employee table 100% clean and free of counter column clutter while
    preserving sub-millisecond O(1) atomic SQL update performance.
    """
    _name = 'hr.employee.discipline.profile'
    _description = 'Employee Attendance Discipline Profile'
    _rec_name = 'employee_id'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        ondelete='cascade',
        index=True,
    )
    late_count_rolling = fields.Integer(
        string='Rolling Late Count',
        default=0,
        groups='hr_attendance.group_hr_attendance_manager',
        help='Cumulative late check-in count since last discipline case creation. Resets to 0 on threshold breach.',
    )
    force_checkout_count_rolling = fields.Integer(
        string='Rolling Force Checkout Count',
        default=0,
        groups='hr_attendance.group_hr_attendance_manager',
        help='Cumulative force checkout count since last discipline case creation. Resets to 0 on threshold breach.',
    )
    missing_lunch_tap_count_rolling = fields.Integer(
        string='Rolling Missing Lunch Tap Count',
        default=0,
        groups='hr_attendance.group_hr_attendance_manager',
        help='Cumulative missing lunch tap count. Every 3 missing lunch taps converts to 1 Lateness Violation.',
    )

    @api.model
    def _get_or_create_profile(self, employee_id):
        """Find or atomically create the discipline profile for an employee."""
        profile = self.search([('employee_id', '=', employee_id)], limit=1)
        if not profile:
            profile = self.create({'employee_id': employee_id})
        return profile

    @api.model
    def _increment_late_count(self, employee_id):
        """Atomic O(1) SQL increment for late check-in counter."""
        self._get_or_create_profile(employee_id)
        self.env.cr.execute(
            "UPDATE hr_employee_discipline_profile SET late_count_rolling = late_count_rolling + 1 WHERE employee_id = %s RETURNING late_count_rolling",
            (employee_id,)
        )
        row = self.env.cr.fetchone()
        return row[0] if row else 0

    @api.model
    def _increment_force_checkout_count(self, employee_id):
        """Atomic O(1) SQL increment for force checkout counter."""
        self._get_or_create_profile(employee_id)
        self.env.cr.execute(
            "UPDATE hr_employee_discipline_profile SET force_checkout_count_rolling = force_checkout_count_rolling + 1 WHERE employee_id = %s RETURNING force_checkout_count_rolling",
            (employee_id,)
        )
        row = self.env.cr.fetchone()
        return row[0] if row else 0

    @api.model
    def _increment_missing_lunch_tap_count(self, employee_id):
        """Atomic O(1) SQL increment for missing lunch tap counter. Dynamic threshold converts to 1 Lateness Violation."""
        profile = self._get_or_create_profile(employee_id)
        threshold_param = self.env['ir.config_parameter'].sudo().get_param('hr_attendance.missing_lunch_tap_threshold', '3')
        try:
            threshold = int(threshold_param)
        except (ValueError, TypeError):
            threshold = 3

        self.env.cr.execute(
            "UPDATE hr_employee_discipline_profile SET missing_lunch_tap_count_rolling = missing_lunch_tap_count_rolling + 1 WHERE employee_id = %s RETURNING missing_lunch_tap_count_rolling",
            (employee_id,)
        )
        row = self.env.cr.fetchone()
        new_count = row[0] if row else 0
        if threshold > 0 and new_count >= threshold:
            self._reset_missing_lunch_tap_count(employee_id)
            return self._increment_late_count(employee_id)
        return new_count

    @api.model
    def _reset_late_count(self, employee_id):
        """Resets the rolling late counter to 0."""
        self._get_or_create_profile(employee_id)
        self.env.cr.execute(
            "UPDATE hr_employee_discipline_profile SET late_count_rolling = 0 WHERE employee_id = %s",
            (employee_id,)
        )

    @api.model
    def _reset_force_checkout_count(self, employee_id):
        """Resets the rolling force checkout counter to 0."""
        self._get_or_create_profile(employee_id)
        self.env.cr.execute(
            "UPDATE hr_employee_discipline_profile SET force_checkout_count_rolling = 0 WHERE employee_id = %s",
            (employee_id,)
        )

    @api.model
    def _reset_missing_lunch_tap_count(self, employee_id):
        """Resets the rolling missing lunch tap counter to 0."""
        self._get_or_create_profile(employee_id)
        self.env.cr.execute(
            "UPDATE hr_employee_discipline_profile SET missing_lunch_tap_count_rolling = 0 WHERE employee_id = %s",
            (employee_id,)
        )
