# -*- coding: utf-8 -*-
from odoo import fields, models, api, _
from markupsafe import Markup, escape

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

        emp = self.request_id.requestor or self.request_id.employee_id
        if (
            emp
            and emp.user_id
            and emp.user_id.partner_id
        ):
            pid = emp.user_id.partner_id.id
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
            sr_url = f"{base_url.rstrip('/')}/web#id={self.request_id.id}&model=employee.service.request&view_type=form" if base_url else f"/web#id={self.request_id.id}&model=employee.service.request&view_type=form"
            body = Markup(
                f"<p>Dear Colleague,</p>"
                f"<p>Your Service Request <b>{escape(self.request_id.reference or '')}</b> has been <b>Rejected</b>.</p>"
                f"<p><b>Reason:</b> {escape(self.reason or '')}</p>"
                f"<div style='margin-top: 10px; margin-bottom: 12px;'>"
                f"<a href='{sr_url}' target='_blank' style='display: inline-block; padding: 8px 16px; background-color: #541718; color: #ffffff !important; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 13px;'>"
                f"👉 View Service Request"
                f"</a>"
                f"</div>"
            )
            try:
                # Odoo 19 discuss.channel way
                channel = self.env["discuss.channel"].sudo()._get_or_create_chat(partners_to=[pid])
                channel.message_post(
                    body=body, 
                    message_type="comment",
                    subtype_xmlid="mail.mt_comment",
                )
            except Exception:
                pass
            try:
                emp_partner = emp.user_id.partner_id
                self.env['bus.bus']._sendone(emp_partner, 'simple_notification', {
                    'title': _('Service Request Rejected'),
                    'message': _('Your Service Request %s was rejected: %s') % (self.request_id.reference, self.reason),
                    'type': 'danger',
                    'sticky': True,
                })
            except Exception:
                pass

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Request Rejected'),
                'message': _('Service Request %s has been rejected.') % self.request_id.reference,
                'type': 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
