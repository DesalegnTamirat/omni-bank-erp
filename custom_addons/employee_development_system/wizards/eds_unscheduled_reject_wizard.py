# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import UserError


class EdsUnscheduledRejectWizard(models.TransientModel):
    """Wizard for capturing a rejection reason when rejecting an unscheduled training request."""
    _name = 'eds.unscheduled.reject.wizard'
    _description = 'Reject Unscheduled Training Request'

    request_id = fields.Many2one(
        'eds.unscheduled.request',
        string='Unscheduled Request',
        required=True,
        ondelete='cascade',
    )
    rejected_reason = fields.Text(
        string='Rejection Reason',
        required=True,
        help='Provide the business justification or reason for rejecting this request.',
    )

    def action_confirm_reject(self):
        self.ensure_one()
        reason = (self.rejected_reason or '').strip()
        if not reason:
            raise UserError(_('Please provide a rejection reason.'))
        return self.request_id.action_confirm_rejection(reason)
