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

    _sql_constraints = [
        ('employee_id_uniq', 'unique(employee_id)', 'An employee can only have one profile photo record.')
    ]
