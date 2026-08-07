# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class HrAttendanceNotificationLog(models.Model):
    """
    Lightweight deduplication and audit table for attendance notifications.
    Ensures employees, supervisors, and HR are not repeatedly spammed with duplicate
    notifications on the same day for the same event.
    """
    _name = 'hr.attendance.notification.log'
    _description = 'Attendance Notification Deduplication Log'
    _order = 'sent_date desc, id desc'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        index=True,
        ondelete='cascade',
    )
    notif_type = fields.Selection([
        ('missing_checkin', 'Missing Check-In'),
        ('missing_checkout', 'Missing Check-Out'),
        ('violation_supervisor', 'Violation — Supervisor Notified'),
        ('violation_hr_escalation', 'Violation — HR Escalated'),
    ], string='Notification Type', required=True, index=True)

    reference_date = fields.Date(
        string='Reference Date',
        required=True,
        index=True,
        default=fields.Date.context_today,
    )
    sent_date = fields.Datetime(
        string='Sent Date',
        default=fields.Datetime.now,
        readonly=True,
    )

    _sql_constraints = [
        ('uniq_notif_per_day', 'unique(employee_id, notif_type, reference_date)',
         'Only one notification of this type per employee per day.'),
    ]

    @api.model
    def log_and_check(self, employee_id, notif_type, reference_date=None):
        """
        Attempts to insert a deduplication record.
        Returns True if insert succeeded (meaning notification should be sent),
        Returns False if unique constraint failed (already notified today).
        """
        if not reference_date:
            reference_date = fields.Date.context_today(self)
        try:
            with self.env.cr.savepoint():
                self.create({
                    'employee_id': employee_id,
                    'notif_type': notif_type,
                    'reference_date': reference_date,
                })
            return True
        except Exception:
            return False
