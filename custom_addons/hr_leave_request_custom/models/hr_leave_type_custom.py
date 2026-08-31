# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class HrLeaveTypeCustom(models.Model):
    _inherit = 'hr.leave.type'

    check_accrual_balance = fields.Boolean(
        string='Requires Accrual Check',
        default=False,
        help="If enabled, verifies that accrued balance is sufficient and scheduled balance is positive."
    )
    is_exact_days = fields.Boolean(
        string='Exact Days Required',
        default=False,
        help="If enabled, leave requests of this type will enforce and display this exact number of days as read-only."
    )
    exact_days = fields.Float(
        string='Exact Days',
        default=0.0,
        help="If set greater than 0, the requested leave duration must be exactly this number of days."
    )
    max_allowed_days = fields.Float(
        string='Max Allowed Days',
        default=0.0,
        help="If set greater than 0, the requested leave duration cannot exceed this number of days."
    )

    @api.onchange('is_exact_days')
    def _onchange_is_exact_days(self):
        if not self.is_exact_days:
            self.exact_days = 0.0

    @api.onchange('exact_days')
    def _onchange_exact_days(self):
        if self.exact_days > 0:
            self.is_exact_days = True

    @api.constrains('is_exact_days', 'exact_days')
    def _check_exact_days(self):
        for record in self:
            if record.is_exact_days and record.exact_days <= 0:
                raise ValidationError(_("Please specify an Exact Days value greater than 0 when 'Exact Days Required' is enabled."))
