# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class HrEmployeeSignatureWizard(models.TransientModel):
    _name = "hr.employee.signature.wizard"
    _description = "Employee Master Digital Signature Wizard"

    employee_id = fields.Many2one("hr.employee", string="Employee", required=True, readonly=True)
    employee_name = fields.Char(related="employee_id.name", readonly=True)
    employee_badge_id = fields.Char(related="employee_id.barcode", string="Employee ID", readonly=True)
    user_id = fields.Many2one(related="employee_id.user_id", readonly=True)

    digital_signature = fields.Binary(
        string="Draw or Upload Digital Signature",
        required=False,
        attachment=False,
        help="Draw your signature or upload a signature image."
    )

    def action_save_signature(self):
        self.ensure_one()
        current_user = self.env.user
        is_owner = bool(self.employee_id.user_id and self.employee_id.user_id == current_user)
        is_admin = current_user.has_group('hr.group_hr_manager') or self.env.is_superuser()

        if not is_owner and not is_admin:
            raise UserError(_(
                "Security Restriction: You can only create or update your own digital signature."
            ))

        if not self.digital_signature:
            raise UserError(_("Please draw or upload your signature before clicking Save."))

        # Update all employee records linked to this user account via sudo()
        user = self.employee_id.user_id
        target_emps = self.env['hr.employee'].sudo().search([('user_id', '=', user.id)]) if user else self.employee_id
        if not target_emps:
            target_emps = self.employee_id

        target_emps.sudo().write({
            'digital_signature': self.digital_signature,
            'digital_signature_updated_on': fields.Datetime.now(),
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }
