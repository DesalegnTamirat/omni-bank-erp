# -*- coding: utf-8 -*-
from odoo import fields, models


class KmsDigitalLibrary(models.Model):
    _inherit = 'kms.digital.library'

    related_course_ids = fields.Many2many(
        'lms.course', 'lms_kms_library_course_rel', 'library_id', 'course_id',
        string='Related LMS Courses',
        domain="[('state', '=', 'published'), ('is_latest_version', '=', True)]",
        help='Approved LMS courses that use this library item as supporting material.',
    )
