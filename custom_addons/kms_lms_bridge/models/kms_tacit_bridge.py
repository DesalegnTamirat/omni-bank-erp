# -*- coding: utf-8 -*-
from odoo import api, fields, models


class KmsLessonLearned(models.Model):
    _inherit = 'kms.lesson.learned'

    related_course_ids = fields.Many2many(
        'lms.course',
        'kms_lms_course_lesson_rel',
        'lesson_id',
        'course_id',
        string='Associated Training Courses',
        help='Courses in LMS that incorporate or reference this institutional lesson.'
    )
