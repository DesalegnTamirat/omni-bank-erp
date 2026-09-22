# -*- coding: utf-8 -*-
from odoo import api, fields, models


class KmsDigitalLibrary(models.Model):
    _inherit = 'kms.digital.library'

    related_course_ids = fields.Many2many(
        'lms.course',
        'kms_lms_course_library_rel',
        'library_id',
        'course_id',
        string='Associated Training Courses',
        help='Courses in LMS that recommend or require this reference material.'
    )
