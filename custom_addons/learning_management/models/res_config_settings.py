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
