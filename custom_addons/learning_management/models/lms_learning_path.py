# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class LmsLearningPath(models.Model):
    """
    Structured Learning Paths (FR-LMS-002).
    Groups related courses into progressive curriculum journeys (e.g. 'New Branch Manager Onboarding Path').
    Supports both linear progression and optional / branched prerequisites.
    """
    _name = 'lms.learning.path'
    _description = 'Structured Learning Path'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Learning Path Title', required=True, tracking=True)
    code = fields.Char(string='Pathway Code', required=True)
    description = fields.Html(string='Pathway Description & Target Audience', required=True)
    category_id = fields.Many2one('lms.category', string='Domain Category')
    cover_image = fields.Binary(string='Pathway Banner', attachment=True)

    target_job_ids = fields.Many2many('hr.job', string='Target Job Positions')
    target_department_ids = fields.Many2many('hr.department', string='Target Departments')

    path_course_ids = fields.One2many('lms.learning.path.course', 'path_id', string='Curriculum Stages')
    total_courses = fields.Integer(string='Total Courses', compute='_compute_path_stats', store=True)
    estimated_duration_hours = fields.Float(string='Total Hours', compute='_compute_path_stats', store=True)

    active = fields.Boolean(default=True)

    _code_unique = models.Constraint(
        'UNIQUE(code)',
        'Learning path code must be unique!'
    )

    @api.depends('path_course_ids', 'path_course_ids.course_id.estimated_duration_hours')
    def _compute_path_stats(self):
        for rec in self:
            rec.total_courses = len(rec.path_course_ids)
            rec.estimated_duration_hours = sum(pc.course_id.estimated_duration_hours for pc in rec.path_course_ids)


class LmsLearningPathCourse(models.Model):
    """
    Course stage in a learning path with optional / branched prerequisite logic (FR-LMS-002).
    """
    _name = 'lms.learning.path.course'
    _description = 'Learning Path Course Stage'
    _order = 'path_id, sequence, id'

    path_id = fields.Many2one('lms.learning.path', string='Learning Path', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(string='Stage Order', default=10)
    course_id = fields.Many2one('lms.course', string='Course', required=True, ondelete='cascade')

    # Optional / Branched Prerequisites Support
    is_optional_branch = fields.Boolean(
        string='Optional / Elective Branch',
        default=False,
        help='If checked, this course is an elective branch rather than a strictly mandatory progression step.'
    )
    branch_group_code = fields.Char(
        string='Elective Group Identifier',
        help='Group identifier if the learner must pick 1 of N elective courses in this branch, e.g. ELECTIVE_BRANCH_A.'
    )
    prerequisite_course_ids = fields.Many2many(
        'lms.course',
        'lms_path_course_prereq_rel',
        'path_course_id',
        'prereq_course_id',
        string='Branched Prerequisites',
        help='Specific prerequisite course(s) that must be passed before this stage unlocks.'
    )
    stage_notes = fields.Char(string='Stage Instructions / Prerequisites Guidance')

    _path_course_unique = models.Constraint(
        'UNIQUE(path_id, course_id)',
        'This course is already added to this learning path!'
    )
