# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    leave_accrual_policy_opening_date = fields.Date(
        string='Policy Opening Date',
        default=fields.Date.from_string('2023-08-31'),
        help='Cutoff date for opening balance load and leaves taken tracking.',
    )
    leave_accrual_base_entitlement = fields.Integer(
        string='Base Annual Leave Entitlement',
        config_parameter='hr_leave_request_custom.base_entitlement',
        default=16,
        help='Base annual leave days for year 0 of service (e.g. 16 days).',
    )
    leave_accrual_managerial_cap_years = fields.Integer(
        string='Managerial Carryover Cap (Years)',
        config_parameter='hr_leave_request_custom.managerial_cap_years',
        default=3,
        help='Number of years entitlement allowed for carryover cap for Managerial employees (e.g. 3 years).',
    )
    leave_accrual_non_managerial_cap_years = fields.Integer(
        string='Non-Managerial Carryover Cap (Years)',
        config_parameter='hr_leave_request_custom.non_managerial_cap_years',
        default=2,
        help='Number of years entitlement allowed for carryover cap for Non-Managerial employees (e.g. 2 years).',
    )
    leave_accrual_opening_balance_name = fields.Char(
        string='Opening Balance Record Name',
        config_parameter='hr_leave_request_custom.opening_balance_name',
        default='Opening Balance Load',
        help='Allocation record description used to identify the initial opening balance load.',
    )

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        get_param = self.env['ir.config_parameter'].sudo().get_param
        policy_date_str = get_param('hr_leave_request_custom.policy_opening_date', '2023-08-31')
        try:
            res['leave_accrual_policy_opening_date'] = fields.Date.from_string(policy_date_str) if policy_date_str else fields.Date.from_string('2023-08-31')
        except Exception:
            res['leave_accrual_policy_opening_date'] = fields.Date.from_string('2023-08-31')
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        set_param = self.env['ir.config_parameter'].sudo().set_param
        for record in self:
            set_param(
                'hr_leave_request_custom.policy_opening_date',
                fields.Date.to_string(record.leave_accrual_policy_opening_date) if record.leave_accrual_policy_opening_date else '2023-08-31'
            )