# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class TransferRequestConfig(models.TransientModel):
    """
    Standalone Transfer Request Configuration model.
    Does NOT inherit res.config.settings so it stays completely inside
    the Recruitment application interface without redirecting to global Odoo settings.
    """
    _name = 'transfer.request.config'
    _description = 'Transfer Request Configuration'

    transfer_discipline_blocks_first_warning = fields.Boolean(
        string="Block Transfer for First Warning",
        default=False,
        help="If enabled, employees with a First Warning are completely blocked from transfer requests."
    )
    transfer_discipline_blocks_second_warning = fields.Boolean(
        string="Block Transfer for Second Warning",
        default=False,
        help="If enabled, employees with a Second Warning are completely blocked from transfer requests."
    )
    transfer_min_pms_score = fields.Float(
        string="Minimum PMS Score (%)",
        default=75.0,
        help="Minimum PMS score required to be eligible for transfer."
    )
    transfer_min_service_years = fields.Float(
        string="Minimum Service Years",
        default=1.0,
        help="Minimum tenure (years) required in current position/location."
    )
    transfer_refusal_penalty_months = fields.Integer(
        string="Refusal Penalty (Months)",
        default=12,
        help="Ineligibility duration in months applied if an employee refuses an approved transfer."
    )
    transfer_pending_expiry_days = fields.Integer(
        string="Pending Expiry Notification (Days)",
        default=365,
        help="Days after submission before notifying employee of long-standing pending request."
    )
    transfer_pending_auto_withdraw_days = fields.Integer(
        string="Auto-Withdraw After Notification (Days)",
        default=7,
        help="Days after notification before auto-withdrawing an un-acted pending request."
    )
    transfer_weight_pms = fields.Float(
        string="PMS Score Weight (%)",
        default=30.0
    )
    transfer_weight_application_date = fields.Float(
        string="Application Date Weight (%)",
        default=20.0
    )
    transfer_weight_experience = fields.Float(
        string="Total Experience Weight (%)",
        default=20.0
    )
    transfer_weight_service_location = fields.Float(
        string="Service in Location Weight (%)",
        default=20.0
    )
    transfer_weight_recommendation = fields.Float(
        string="Supervisor Recommendation Weight (%)",
        default=10.0
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ICPSudo = self.env["ir.config_parameter"].sudo()
        res.update({
            'transfer_discipline_blocks_first_warning': ICPSudo.get_param('custom_recruitment.transfer_discipline_blocks_first_warning', 'False') == 'True',
            'transfer_discipline_blocks_second_warning': ICPSudo.get_param('custom_recruitment.transfer_discipline_blocks_second_warning', 'False') == 'True',
            'transfer_min_pms_score': float(ICPSudo.get_param('custom_recruitment.transfer_min_pms_score', '75.0')),
            'transfer_min_service_years': float(ICPSudo.get_param('custom_recruitment.transfer_min_service_years', '1.0')),
            'transfer_refusal_penalty_months': int(ICPSudo.get_param('custom_recruitment.transfer_refusal_penalty_months', '12')),
            'transfer_pending_expiry_days': int(ICPSudo.get_param('custom_recruitment.transfer_pending_expiry_days', '365')),
            'transfer_pending_auto_withdraw_days': int(ICPSudo.get_param('custom_recruitment.transfer_pending_auto_withdraw_days', '7')),
            'transfer_weight_pms': float(ICPSudo.get_param('custom_recruitment.transfer_weight_pms', '30.0')),
            'transfer_weight_application_date': float(ICPSudo.get_param('custom_recruitment.transfer_weight_application_date', '20.0')),
            'transfer_weight_experience': float(ICPSudo.get_param('custom_recruitment.transfer_weight_experience', '20.0')),
            'transfer_weight_service_location': float(ICPSudo.get_param('custom_recruitment.transfer_weight_service_location', '20.0')),
            'transfer_weight_recommendation': float(ICPSudo.get_param('custom_recruitment.transfer_weight_recommendation', '10.0')),
        })
        return res

    def action_save(self):
        self.ensure_one()
        # Validate weights sum to 100%
        total_weight = (
            self.transfer_weight_pms +
            self.transfer_weight_application_date +
            self.transfer_weight_experience +
            self.transfer_weight_service_location +
            self.transfer_weight_recommendation
        )
        if round(total_weight, 2) != 100.0:
            raise ValidationError(_(
                "Ranking weights must sum to exactly 100%%. Current total: %.2f%%"
            ) % total_weight)

        ICPSudo = self.env["ir.config_parameter"].sudo()
        ICPSudo.set_param('custom_recruitment.transfer_discipline_blocks_first_warning', str(self.transfer_discipline_blocks_first_warning))
        ICPSudo.set_param('custom_recruitment.transfer_discipline_blocks_second_warning', str(self.transfer_discipline_blocks_second_warning))
        ICPSudo.set_param('custom_recruitment.transfer_min_pms_score', str(self.transfer_min_pms_score))
        ICPSudo.set_param('custom_recruitment.transfer_min_service_years', str(self.transfer_min_service_years))
        ICPSudo.set_param('custom_recruitment.transfer_refusal_penalty_months', str(self.transfer_refusal_penalty_months))
        ICPSudo.set_param('custom_recruitment.transfer_pending_expiry_days', str(self.transfer_pending_expiry_days))
        ICPSudo.set_param('custom_recruitment.transfer_pending_auto_withdraw_days', str(self.transfer_pending_auto_withdraw_days))
        ICPSudo.set_param('custom_recruitment.transfer_weight_pms', str(self.transfer_weight_pms))
        ICPSudo.set_param('custom_recruitment.transfer_weight_application_date', str(self.transfer_weight_application_date))
        ICPSudo.set_param('custom_recruitment.transfer_weight_experience', str(self.transfer_weight_experience))
        ICPSudo.set_param('custom_recruitment.transfer_weight_service_location', str(self.transfer_weight_service_location))
        ICPSudo.set_param('custom_recruitment.transfer_weight_recommendation', str(self.transfer_weight_recommendation))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Settings Saved'),
                'message': _('Transfer Request Settings have been updated successfully.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }
