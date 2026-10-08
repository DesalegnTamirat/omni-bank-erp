from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class HrInsuranceRejectWizard(models.TransientModel):
    _name = 'hr.insurance.reject.wizard'
    _description = 'Reject Insurance Notification Wizard'

    notification_id = fields.Many2one(
        'hr.insurance.notification',
        string='Insurance Notification',
        required=True
    )
    rejection_reason = fields.Text(
        string='Rejection Reason',
        required=True,
        help="Mandatory comment explaining why this insurance notification is rejected."
    )

    def action_confirm_reject(self):
        self.ensure_one()
        if not self.rejection_reason or not self.rejection_reason.strip():
            raise ValidationError(_("Rejection reason comment is mandatory."))

        notif = self.notification_id
        notif.write({
            'state': 'rejected',
            'rejection_reason': self.rejection_reason,
            'rejected_date': fields.Datetime.now(),
            'reviewed_by_id': self.env.user.id,
            'review_date': fields.Datetime.now()
        })
        notif._notify_employee_state_change(_("REJECTED by POMD.\nReason: %s") % self.rejection_reason)
        return {'type': 'ir.actions.act_window_close'}


class HrInsuranceReturnWizard(models.TransientModel):
    _name = 'hr.insurance.return.wizard'
    _description = 'Return Insurance Notification Wizard'

    notification_id = fields.Many2one(
        'hr.insurance.notification',
        string='Insurance Notification',
        required=True
    )
    return_reason = fields.Text(
        string='Return Reason / Required Corrections',
        required=True,
        help="Mandatory comment detailing the corrections required by the employee."
    )

    def action_confirm_return(self):
        self.ensure_one()
        if not self.return_reason or not self.return_reason.strip():
            raise ValidationError(_("Return reason comment detailing required corrections is mandatory."))

        notif = self.notification_id
        notif.write({
            'state': 'returned',
            'return_reason': self.return_reason,
            'returned_date': fields.Datetime.now(),
            'reviewed_by_id': self.env.user.id,
            'review_date': fields.Datetime.now()
        })
        notif._notify_employee_state_change(_("RETURNED FOR CORRECTION by POMD.\nRequired Corrections: %s") % self.return_reason)
        return {'type': 'ir.actions.act_window_close'}
