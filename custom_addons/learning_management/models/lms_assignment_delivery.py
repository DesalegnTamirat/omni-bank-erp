# -*- coding: utf-8 -*-
from odoo import fields, models


class LmsAssignmentDelivery(models.Model):
    """Idempotent link between a campaign and a learner's course attempt."""

    _name = 'lms.assignment.delivery'
    _description = 'LMS Assignment Delivery'
    _order = 'delivered_at desc, id desc'

    assignment_id = fields.Many2one(
        'lms.course.assignment', required=True, index=True, ondelete='restrict')
    employee_id = fields.Many2one('hr.employee', required=True, index=True, ondelete='restrict')
    course_id = fields.Many2one('lms.course', required=True, index=True, ondelete='restrict')
    enrollment_id = fields.Many2one('lms.enrollment', required=True, ondelete='restrict')
    delivered_at = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)

    _assignment_employee_course_uniq = models.Constraint(
        'UNIQUE(assignment_id, employee_id, course_id)',
        'This campaign has already delivered the course to this employee.',
    )
