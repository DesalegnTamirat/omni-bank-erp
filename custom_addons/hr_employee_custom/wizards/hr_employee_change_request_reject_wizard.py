# -*- coding: utf-8 -*-
from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class HrEmployeeChangeRequestRejectWizard(models.TransientModel):
    _name = "hr.employee.change.request.reject.wizard"
    _description = "Reject Master Data Change Request Wizard"

    request_id = fields.Many2one(
        "hr.employee.change.request",
        string="Change Request",
        required=True,
        readonly=True,
    )
    rejection_reason = fields.Text(
        string="Rejection Reason",
        required=True,
    )

    def action_confirm_rejection(self):
        self.ensure_one()
        if not self.rejection_reason or not self.rejection_reason.strip():
            raise ValidationError(_("Please specify a valid rejection reason."))
        self.request_id._do_reject(self.rejection_reason.strip())
        return {'type': 'ir.actions.act_window_close'}
