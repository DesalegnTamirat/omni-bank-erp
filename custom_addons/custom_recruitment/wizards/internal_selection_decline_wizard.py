# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class InternalSelectionDeclineWizard(models.TransientModel):
    """
    Wizard for capturing candidate rejection / decline reasons for
    Internal Promotions and Transfers.
    """
    _name = 'internal.selection.decline.wizard'
    _description = 'Decline Promotion or Transfer Wizard'

    candidate_id = fields.Many2one(
        'new.internal.recruitment.selected.candidates',
        string='Selected Candidate'
    )
    transfer_request_id = fields.Many2one(
        'employee.transfer.request',
        string='Transfer Request'
    )
    transfer_letter_id = fields.Many2one(
        'transfer.letter',
        string='Transfer Letter'
    )

    rejection_reason = fields.Text(
        string='Reason for Declining / Rejection',
        required=True,
        help='State the specific reason why the employee or HR is declining the offer.'
    )

    def action_confirm_decline(self):
        self.ensure_one()
        if not self.rejection_reason or not self.rejection_reason.strip():
            raise UserError(_("Please provide a reason for declining the offer."))

        reason = self.rejection_reason.strip()

        if self.candidate_id:
            self.candidate_id.confirm_decline_promotion(reason)
        elif self.transfer_request_id:
            self.transfer_request_id.confirm_decline_transfer(reason)
        elif self.transfer_letter_id:
            self.transfer_letter_id.confirm_decline_transfer(reason)
        else:
            raise UserError(_("No candidate or transfer record associated with this wizard."))

        return {'type': 'ir.actions.act_window_close'}
