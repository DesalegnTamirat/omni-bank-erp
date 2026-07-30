# -*- coding: utf-8 -*-
from odoo import fields, models, api, _

class ServiceRequestCompletionWizard(models.TransientModel):
    _name = "service.request.completion.wizard"
    _description = "Service Request Completion Wizard"

    request_id = fields.Many2one(
        "employee.service.request", string="Request", required=True
    )
    ref_num = fields.Char(string="Reference Number (External Letter)", required=True)
    type_guarantee = fields.Selection(
        [('in', 'In'), ('out', 'Out')],
        string="Type of Guarantee",
        required=True
    )
    effective_date = fields.Date(string="Effective Date", required=True, default=fields.Date.context_today)
    guarantee_amount = fields.Float(string="Guarantee Amount", required=True)

    def action_confirm_completion(self):
        self.ensure_one()
        request = self.request_id

        # Write completion status and wizard fields back to request model in python
        request.write({
            'status': 'completed',
            'ref_num': self.ref_num,
            'type_guarantee': self.type_guarantee,
            'effective_date': self.effective_date,
            'guarantee_amount': self.guarantee_amount,
        })

        # Insert guarantees details record
        self.env['guarentees.details'].create({
            'employee_id': request.employee_id.id,
            'ref_num': self.ref_num,
            'type_guarantee': self.type_guarantee,
            'effective_date': self.effective_date,
            'name_of_staff': request.employee_id.id,
            'external_person_name': request.name_of_the_external_person,
            'guarantee_amount': request.guarantee_amount,
            'name_of_institution': request.name_of_the_organization,
            'type': 'internal' if self.type_guarantee == 'in' else 'external',
            'state': 'active',
        })

        # Send completion message via mail channel (same logic as in main action_complete)
        if (
            request.requestor
            and request.requestor.user_id
            and request.requestor.user_id.partner_id
        ):
            requestor_partner_id = request.requestor.user_id.partner_id.id
            sr_type_label = ""
            if request.sr_type:
                sr_type_label = (
                    getattr(request.sr_type, "sr_type", None)
                    or getattr(request.sr_type, "name", None)
                    or request.sr_type.display_name
                    or ""
                )
            body = (
                "Dear {name},<br/><br/>"
                "Your Service Request <b>{ref}</b> ({sr_type}) has been successfully "
                "<b>Completed</b> by the HR Team.<br/><br/>Regards,"
            ).format(
                name=request.requestor.name,
                ref=request.reference,
                sr_type=sr_type_label,
            )
            try:
                # Odoo 19 discuss.channel way
                channel = self.env["discuss.channel"]._get_or_create_chat(partners_to=[requestor_partner_id])
                channel.message_post(
                    body=body,
                    message_type="comment",
                    subtype_xmlid="mail.mt_comment",
                )
            except Exception:
                pass

        return {"type": "ir.actions.act_window_close"}
