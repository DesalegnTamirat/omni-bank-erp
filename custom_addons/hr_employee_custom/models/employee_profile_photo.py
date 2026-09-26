# -*- coding: utf-8 -*-
from odoo import models, fields

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

    def init(self):
        super().init()
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS employee_profile_photo_employee_id_uniq 
            ON employee_profile_photo (employee_id);
        """)
