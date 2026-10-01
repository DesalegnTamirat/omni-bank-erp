# -*- coding: utf-8 -*-
from odoo import models, fields, api

class EmployeeProfilePhoto(models.Model):
    _name = "employee.profile.photo"
    _description = "Employee Profile Photo"

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        ondelete='cascade',
        required=True,
        index=True
    )
    profile_picture = fields.Binary("Profile Image", attachment=False)

    _sql_constraints = [
        ('employee_id_uniq', 'unique(employee_id)', 'An employee can only have one profile photo record.')
    ]

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record, vals in zip(records, vals_list):
            if 'profile_picture' in vals and record.employee_id:
                record.employee_id.sudo().write({'image_1920': vals['profile_picture']})
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'profile_picture' in vals:
            for record in self:
                if record.employee_id:
                    record.employee_id.sudo().write({'image_1920': vals['profile_picture']})
        return res

