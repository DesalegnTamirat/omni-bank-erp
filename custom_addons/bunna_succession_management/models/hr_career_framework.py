# -*- coding: utf-8 -*-
from odoo import fields, models


class HrJobInherit(models.Model):
    _inherit = 'hr.job'

    # --- Primary Job Requirements ---
    required_grade_id = fields.Many2one(
        'employee.grade', string='Required Job Grade',
        index=True,
        help='The minimum job grade expected for this role.'
    )
    required_experience_years = fields.Float(
        string='Required Total Experience (Years)',
        default=0.0,
        help='The total years of experience required.'
    )
    required_certificate = fields.Selection([
        ('diploma', 'Diploma'),
        ('bachelor', 'Bachelor'),
        ('master', 'Master'),
        ('doctor', 'Doctor/PhD'),
        ('other', 'Other'),
    ], string='Required Education Level')
    required_study_field = fields.Char(
        string='Required Field of Study',
        help='e.g., Computer Science, Accounting'
    )
