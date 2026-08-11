# -*- coding: utf-8 -*-
from odoo import models, fields
from odoo.exceptions import AccessError


class HrEmployeeAttendanceCounters(models.Model):
    """
    Rolling O(1) violation counters on hr.employee for attendance discipline integration.

    Kept separate from discipline_management/models/hr_employee.py to prevent
    merge conflicts and maintain clean module boundary separation.

    Each counter tracks cumulative occurrences since last reset. A reset happens
    automatically when the threshold is reached and a discipline case is created,
    preventing duplicate cases from the same violation run.

    Counter increments are single-row UPDATE operations — cost is identical
    whether 1 or 6,000 employees check in simultaneously.
    """
    _inherit = 'hr.employee'

    def _check_private_fields(self, field_names):
        """ Prevent AccessError for non-HR employees when accessing employee records """
        try:
            super()._check_private_fields(field_names)
        except AccessError:
            if self.env.user.has_group('custom_hr_attendance.group_hr_attendance_manual_user') or self.env.user.has_group('base.group_user'):
                return
            raise

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

    def _increment_late_count(self):
        """
        Atomically increments the rolling late counter for this employee.
        Uses direct SQL to avoid ORM overhead and ensure no concurrent increment
        is lost under high-volume check-in traffic.
        Returns the new counter value after increment.
        """
        self.ensure_one()
        self.env.cr.execute(
            "UPDATE hr_employee SET late_count_rolling = late_count_rolling + 1 WHERE id = %s RETURNING late_count_rolling",
            (self.id,)
        )
        row = self.env.cr.fetchone()
        self.invalidate_recordset(['late_count_rolling'])
        return row[0] if row else 0

    def _increment_force_checkout_count(self):
        """
        Atomically increments the rolling force checkout counter for this employee.
        Same atomic SQL pattern as _increment_late_count.
        Returns the new counter value after increment.
        """
        self.ensure_one()
        self.env.cr.execute(
            "UPDATE hr_employee SET force_checkout_count_rolling = force_checkout_count_rolling + 1 WHERE id = %s RETURNING force_checkout_count_rolling",
            (self.id,)
        )
        row = self.env.cr.fetchone()
        self.invalidate_recordset(['force_checkout_count_rolling'])
        return row[0] if row else 0

    def _reset_late_count(self):
        """Resets the rolling late counter to 0 after threshold is reached and a discipline case is opened."""
        self.ensure_one()
        self.env.cr.execute(
            "UPDATE hr_employee SET late_count_rolling = 0 WHERE id = %s",
            (self.id,)
        )
        self.invalidate_recordset(['late_count_rolling'])

    def _reset_force_checkout_count(self):
        """Resets the rolling force checkout counter to 0 after threshold is reached and a discipline case is opened."""
        self.ensure_one()
        self.env.cr.execute(
            "UPDATE hr_employee SET force_checkout_count_rolling = 0 WHERE id = %s",
            (self.id,)
        )
        self.invalidate_recordset(['force_checkout_count_rolling'])

