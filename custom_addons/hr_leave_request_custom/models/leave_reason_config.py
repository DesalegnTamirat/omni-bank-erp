# -*- coding: utf-8 -*-
from odoo import models, fields


class HrLeaveReasonConfig(models.Model):
    _name = 'hr.leave.reason.config'
    _description = 'Leave Reason Configuration'
    _rec_name = 'leave_reason'

    leave_reason = fields.Selection([
        ('annual_leave', 'Annual Leave'),
        ('sick_leave', 'Sick Leave'),
        ('wedding_leave', 'Wedding Leave'),
        ('prenatal_leave', 'Prenatal Leave'),
        ('postnatal_leave', 'Postnatal Leave'),
        ('paternity_leave', 'Paternity Leave'),
        ('mourning_leave', 'Mourning Leave'),
        ('special_leave', 'Special Leave'),
        ('on_duty', 'On Duty'),
        ('leave_without_pay', 'Leave Without Pay'),
        ('schedule_leave', 'Schedule Leave'),
    ], required=True, string='Leave Reason')

    holiday_status_id = fields.Many2one(
        'hr.leave.type', string='Time Off Type', required=True,
        help='Which native Time Off Type this reason maps to.'
    )
    max_days = fields.Integer(string='Max Days Allowed', help='0 = no cap')
    exact_days = fields.Integer(string='Exact Days Required', help='e.g. Leave Without Pay = 30. 0 = not enforced')
    requires_balance_check = fields.Boolean(
        string='Requires Accrued Balance Check', default=True,
        help='If checked, requester must have enough accrued balance to cover the requested days.'
    )

    _leave_reason_uniq = models.Constraint(
        'unique(leave_reason)',
        'Each leave reason can only be configured once.',
    )