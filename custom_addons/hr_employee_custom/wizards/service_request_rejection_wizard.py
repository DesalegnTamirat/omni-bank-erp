# -*- coding: utf-8 -*-
from odoo import fields, models, api, _

class ServiceRequestRejectionWizard(models.TransientModel):
    _name = "service.request.rejection.wizard"
    _description = "Service Request Rejection Wizard"

    request_id = fields.Many2one(
        "employee.service.request", string="Request", required=True
    )
    reason = fields.Text(string="Rejection Reason", required=True)

    def action_confirm_rejection(self):
        self.ensure_one()
        self.request_id.write({"status": "rejected", "rejection_reason": self.reason})

        if (
            self.request_id.requestor
            and self.request_id.requestor.user_id
            and self.request_id.requestor.user_id.partner_id
        ):
            pid = self.request_id.requestor.user_id.partner_id.id
            body = _(
                "Dear Colleague,<br/><br/>Your Service Request <b>%s</b> has been rejected.<br/><b>Reason:</b> %s"
            ) % (self.request_id.reference, self.reason)
            try:
                # Odoo 19 discuss.channel way
                channel = self.env["discuss.channel"]._get_or_create_chat(partners_to=[pid])
                channel.message_post(
                    body=body, 
                    message_type="comment",
                    subtype_xmlid="mail.mt_comment",
                )
            except Exception:
                pass

        return {"type": "ir.actions.act_window_close"}
