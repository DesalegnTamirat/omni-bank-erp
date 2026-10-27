# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestLmsGapClosure(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        manager_group = cls.env.ref('learning_management.group_lms_manager')
        learner_group = cls.env.ref('learning_management.group_lms_learner')
        internal_group = cls.env.ref('base.group_user')
        cls.manager = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'LMS Gap Reviewer',
            'login': 'lms_gap_reviewer@example.test',
            'group_ids': [(6, 0, [internal_group.id, manager_group.id])],
        })
        cls.learner = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'LMS Gap Learner',
            'login': 'lms_gap_learner@example.test',
            'group_ids': [(6, 0, [internal_group.id, learner_group.id])],
        })
        cls.department = cls.env['hr.department'].create({'name': 'LMS Audience A'})
        cls.other_department = cls.env['hr.department'].create({'name': 'LMS Audience B'})
        cls.manager_employee = cls.env['hr.employee'].create({
            'name': 'LMS Gap Reviewer Employee', 'user_id': cls.manager.id,
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'LMS Gap Learner Employee', 'user_id': cls.learner.id,
            'department_id': cls.department.id,
        })
        cls.category = cls.env['lms.category'].create({
            'name': 'LMS Gap Category', 'code': 'LMS-GAP',
        })
        cls.course = cls.env['lms.course'].create({
            'name': 'LMS Gap Course',
            'category_id': cls.category.id,
            'description': '<p>Training</p>',
            'instructor_id': cls.manager_employee.id,
            'reviewer_id': cls.manager.id,
            'has_post_assessment': False,
            'target_department_ids': [(6, 0, [cls.department.id])],
        })
        cls.env['lms.lesson'].create({
            'name': 'LMS Gap Lesson', 'course_id': cls.course.id,
            'lesson_type': 'text', 'html_content': '<p>Learn.</p>',
        })

    def _publish(self):
        self.course.action_submit_for_review()
        self.course.with_user(self.manager).action_publish()

    def test_reviewer_receives_approval_activity(self):
        self.course.action_submit_for_review()
        self.assertEqual(self.course.reviewer_id, self.manager)
        self.assertEqual(self.course.state, 'review')
        self.assertTrue(self.course.activity_ids.filtered(
            lambda activity: activity.user_id == self.manager
        ))

    def test_catalog_audience_and_enrolled_exception(self):
        self._publish()
        learner_courses = self.env['lms.course'].with_user(self.learner)
        self.assertTrue(learner_courses.search([('id', '=', self.course.id)]))
        self.employee.department_id = self.other_department
        self.assertFalse(self.learner.has_group('learning_management.group_lms_instructor'))
        self.assertEqual(self.learner.employee_id.department_id, self.other_department)
        self.assertEqual(self.course.target_department_ids, self.department)
        self.assertFalse(learner_courses.search([('id', '=', self.course.id)]))
        self.env['lms.enrollment'].create({
            'employee_id': self.employee.id, 'course_id': self.course.id,
        })
        self.assertTrue(learner_courses.search([('id', '=', self.course.id)]))

    def test_template_body_escapes_dynamic_values(self):
        self.employee.name = '<A&B>'
        template = self.env['lms.certificate.template'].create({
            'name': 'LMS Gap Template',
            'body_text': '<p>${learner_name} completed ${course_name}</p>',
        })
        certificate = self.env['lms.certificate'].create({
            'name': 'LMS-GAP-CERT', 'employee_id': self.employee.id,
            'course_id': self.course.id, 'template_id': template.id,
        })
        body = str(certificate._certificate_body_html())
        self.assertIn('&lt;A&amp;B&gt;', body)
        self.assertIn(self.course.name, body)

    def test_reminder_is_not_repeated_on_same_day(self):
        self._publish()
        today = fields.Date.context_today(self.env['lms.enrollment'])
        enrollment = self.env['lms.enrollment'].create({
            'employee_id': self.employee.id, 'course_id': self.course.id,
            'is_mandatory': True, 'due_date': today + timedelta(days=2),
        })
        enrollment._send_due_reminder(today, 3, 3, 7, True)
        first_count = len(enrollment.message_ids.filtered(
            lambda message: 'UPCOMING DEADLINE' in (message.body or '')
        ))
        enrollment._send_due_reminder(today, 3, 3, 7, True)
        second_count = len(enrollment.message_ids.filtered(
            lambda message: 'UPCOMING DEADLINE' in (message.body or '')
        ))
        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 1)
        self.assertEqual(enrollment.last_upcoming_reminder_date, today)

    def test_external_media_requires_approved_https_host(self):
        from odoo.addons.learning_management.controllers.main import LmsController

        allowed = LmsController._external_media_url_allowed
        self.assertTrue(allowed('https://media.example.internal/lesson.mp4', 'media.example.internal'))
        self.assertFalse(allowed('http://media.example.internal/lesson.mp4', 'media.example.internal'))
        self.assertFalse(allowed('https://other.example.internal/lesson.mp4', 'media.example.internal'))
        self.assertFalse(allowed('https://media.example.internal@other.example/lesson.mp4',
                                 'media.example.internal'))
        self.assertFalse(allowed('https://media.example.internal/lesson.mp4', ''))
