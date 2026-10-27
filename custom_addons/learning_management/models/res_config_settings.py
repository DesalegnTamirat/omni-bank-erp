# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    lms_reminder_days_before_due = fields.Integer(
        string='Course Due Reminder Notice (Days)',
        config_parameter='learning_management.reminder_days_before_due',
        default=3,
        help='Number of days before the course due date to send upcoming deadline notifications to enrolled employees.'
    )
    lms_upcoming_reminder_interval_days = fields.Integer(
        string='Upcoming Reminder Interval (Days)',
        config_parameter='learning_management.upcoming_reminder_interval_days',
        default=3,
        help='Minimum number of days between reminders before the deadline.'
    )
    lms_overdue_reminder_interval_days = fields.Integer(
        string='Overdue Reminder Interval (Days)',
        config_parameter='learning_management.overdue_reminder_interval_days',
        default=7,
        help='Minimum number of days between overdue reminders.'
    )
    lms_notify_manager_on_overdue = fields.Boolean(
        string='Notify Line Manager on Overdue',
        config_parameter='learning_management.notify_manager_on_overdue',
        default=True,
    )
    lms_media_allowed_hosts = fields.Char(
        string='Approved Video Hosts',
        config_parameter='learning_management.media_allowed_hosts',
        help='Comma-separated HTTPS hostnames of approved internal media servers. Required for external video URLs.',
    )
