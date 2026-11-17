# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    digital_signature = fields.Binary(
        string="Master Digital Signature",
        attachment=False,
        copy=False,
        help="Permanent base64 digital signature stored in employee master for committee minutes."
    )
    digital_signature_updated_on = fields.Datetime(
        string="Signature Last Updated",
        copy=False,
        readonly=True,
        help="Date and time when the digital signature was last updated."
    )
    is_current_user = fields.Boolean(
        string="Is Current User",
        compute="_compute_is_current_user",
        search=False,
        help="True if the logged-in user corresponds to this employee record."
    )
    can_edit_signature = fields.Boolean(
        string="Can Edit Signature",
        compute="_compute_can_edit_signature",
        search=False,
        help="True if current user can edit this employee's signature (self or HR Manager)."
    )

    @api.depends_context('uid')
    def _compute_is_current_user(self):
        current_uid = self.env.uid
        for rec in self:
            rec.is_current_user = bool(rec.user_id and rec.user_id.id == current_uid)

    @api.depends_context('uid')
    def _compute_can_edit_signature(self):
        current_user = self.env.user
        is_admin = current_user.has_group('hr.group_hr_manager') or self.env.is_superuser()
        for rec in self:
            is_owner = bool(rec.user_id and rec.user_id == current_user)
            rec.can_edit_signature = is_owner or is_admin

    def action_open_signature_dialog(self):
        """Open the signature drawing/upload dialog wizard."""
        self.ensure_one()
        current_user = self.env.user
        is_owner = bool(self.user_id and self.user_id == current_user)
        is_admin = current_user.has_group('hr.group_hr_manager') or self.env.is_superuser()

        if not is_owner and not is_admin:
            raise UserError(_(
                "Security Restriction: You can only edit or update your own digital signature."
            ))

        vals = {'employee_id': self.id}
        if self.digital_signature:
            vals['digital_signature'] = self.digital_signature
        wizard = self.env['hr.employee.signature.wizard'].create(vals)
        return {
            'name': _("Master Digital Signature"),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee.signature.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_clear_signature(self):
        """Clear the stored signature."""
        self.ensure_one()
        current_user = self.env.user
        is_owner = bool(self.user_id and self.user_id == current_user)
        is_admin = current_user.has_group('hr.group_hr_manager') or self.env.is_superuser()

        if not is_owner and not is_admin:
            raise UserError(_(
                "Security Restriction: You can only clear your own digital signature."
            ))
        self.sudo().write({
            'digital_signature': False,
            'digital_signature_updated_on': False,
        })
        return True

    def write(self, vals):
        if 'digital_signature' in vals and not self.env.su:
            current_user = self.env.user
            is_admin = current_user.has_group('hr.group_hr_manager') or self.env.is_superuser()
            for rec in self:
                is_owner = bool(rec.user_id and rec.user_id == current_user)
                if not is_owner and not is_admin:
                    raise UserError(_(
                        "Security Restriction: You cannot edit another employee's digital signature. "
                        "Digital signatures can only be drawn or updated by the employee themselves (or HR Administrator)."
                    ))
        if 'digital_signature' in vals and vals.get('digital_signature'):
            vals['digital_signature_updated_on'] = fields.Datetime.now()
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        current_user = self.env.user
        is_admin = current_user.has_group('hr.group_hr_manager') or self.env.is_superuser()
        for vals in vals_list:
            if vals.get('digital_signature') and not self.env.su:
                user_id = vals.get('user_id')
                if user_id and user_id != current_user.id and not is_admin:
                    raise UserError(_(
                        "Security Restriction: You cannot set another employee's digital signature."
                    ))
                vals['digital_signature_updated_on'] = fields.Datetime.now()
        return super().create(vals_list)


class ResUsers(models.Model):
    _inherit = 'res.users'

    digital_signature = fields.Binary(
        string="Master Digital Signature",
        related='employee_id.digital_signature',
        readonly=False,
        help="Digital signature linked directly to the employee profile."
    )

    def get_master_digital_signature(self):
        """Retrieve master digital signature for current or given user."""
        self.ensure_one()
        current_user = self.env.user
        is_admin = current_user.has_group('hr.group_hr_manager') or self.env.is_superuser()
        if not is_admin and self != current_user:
            return False
        emp = self.employee_id or (self.employee_ids and self.employee_ids[0])
        if emp and emp.digital_signature:
            return emp.digital_signature
        return False

    def update_master_digital_signature(self, signature_b64):
        """Update master digital signature for current or given user."""
        self.ensure_one()
        current_user = self.env.user
        is_admin = current_user.has_group('hr.group_hr_manager') or self.env.is_superuser()
        if not is_admin and self != current_user:
            raise UserError(_("Security Restriction: You can only update your own digital signature."))
        emp = self.employee_id or (self.employee_ids and self.employee_ids[0])
        if emp and signature_b64:
            emp.sudo().write({
                'digital_signature': signature_b64,
                'digital_signature_updated_on': fields.Datetime.now(),
            })
            return True
        return False
