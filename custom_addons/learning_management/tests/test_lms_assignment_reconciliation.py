# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestLmsAssignmentReconciliation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.department = cls.env['hr.department'].create({'name': 'LMS campaign target'})
        cls.other_department = cls.env['hr.department'].create({'name': 'LMS campaign other'})
        cls.category = cls.env['lms.category'].create({
            'name': 'LMS campaign tests', 'code': 'LMS-CAMPAIGN-TEST',
        })
        cls.instructor = cls.env['hr.employee'].create({'name': 'Campaign instructor'})
        cls.course = cls.env['lms.course'].create({
            'name': 'Campaign renewal course',
            'code': 'LMS-CAMPAIGN-RENEW',
            'category_id': cls.category.id,
            'description': '<p>Campaign training material.</p>',
            'instructor_id': cls.instructor.id,
            'state': 'published',
            'has_post_assessment': False,
            'issue_certificate': False,
        })
        cls.lesson = cls.env['lms.lesson'].create({
            'name': 'Required reading',
            'course_id': cls.course.id,
            'lesson_type': 'text',
            'html_content': '<p>Read and acknowledge this lesson.</p>',
            'is_mandatory': True,
        })

    def _employee(self, name, department=None):
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': name,
            'login': 'lms_campaign_%s@example.invalid' % name.lower().replace(' ', '_'),
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        return self.env['hr.employee'].create({
            'name': name, 'user_id': user.id,
            'department_id': (department or self.department).id,
        })

    def _campaign(self, name):
        return self.env['lms.course.assignment'].create({
            'name': name,
            'course_id': self.course.id,
            'assignment_type': 'department',
            'department_ids': [(6, 0, [self.department.id])],
            'is_mandatory': True,
            'due_date': fields.Date.today() + timedelta(days=30),
        })

    def test_reconciliation_assigns_new_hires_once(self):
        first = self._employee('First Campaign Learner')
        outsider = self._employee('Other Department Learner', self.other_department)
        campaign = self._campaign('Initial campaign')
        campaign.action_execute_assignment()
        Enrollment = self.env['lms.enrollment']
        Delivery = self.env['lms.assignment.delivery']
        self.assertEqual(Enrollment.search_count([('employee_id', '=', first.id)]), 1)
        self.assertEqual(Enrollment.search_count([('employee_id', '=', outsider.id)]), 0)

        newcomer = self._employee('Later Campaign Learner')
        campaign.cron_reconcile_assignments()
        self.assertEqual(Enrollment.search_count([('employee_id', '=', newcomer.id)]), 1)
        self.assertEqual(Delivery.search_count([('assignment_id', '=', campaign.id)]), 2)
        campaign.cron_reconcile_assignments()
        self.assertEqual(Enrollment.search_count([('employee_id', '=', newcomer.id)]), 1)
        self.assertEqual(campaign.enrolled_count, 2)

    def test_new_campaign_keeps_old_completion_and_opens_new_attempt(self):
        learner = self._employee('Renewal Campaign Learner')
        first = self._campaign('First training cycle')
        first.action_execute_assignment()
        old = self.env['lms.enrollment'].search([
            ('employee_id', '=', learner.id), ('course_id', '=', self.course.id),
        ], limit=1)
        old.lesson_progress_ids.action_open_lesson()
        old.lesson_progress_ids.mark_completed()
        self.assertEqual(old.state, 'completed')

        second = self._campaign('Second training cycle')
        second.action_execute_assignment()
        attempts = self.env['lms.enrollment'].search([
            ('employee_id', '=', learner.id), ('course_id', '=', self.course.id),
        ], order='attempt_number')
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts.mapped('attempt_number'), [1, 2])
        self.assertEqual(attempts[0].state, 'completed')
        self.assertEqual(attempts[1].state, 'enrolled')
        self.assertEqual(self.env['lms.assignment.delivery'].search_count([
            ('employee_id', '=', learner.id),
        ]), 2)

    def test_existing_campaign_is_backfilled_without_mass_reassignment(self):
        learner = self._employee('Legacy Campaign Learner')
        campaign = self._campaign('Existing campaign')
        campaign.write({'state': 'executed', 'enrolled_count': 1})
        original = self.env['lms.enrollment'].create({
            'employee_id': learner.id,
            'course_id': self.course.id,
            'assignment_id': campaign.id,
            'is_mandatory': True,
            'due_date': campaign.due_date,
        })
        self.assertFalse(campaign.delivery_backfilled)
        campaign.cron_reconcile_assignments()
        self.assertTrue(campaign.delivery_backfilled)
        self.assertEqual(self.env['lms.enrollment'].search_count([
            ('employee_id', '=', learner.id), ('course_id', '=', self.course.id),
        ]), 1)
        delivery = self.env['lms.assignment.delivery'].search([
            ('assignment_id', '=', campaign.id), ('employee_id', '=', learner.id),
        ], limit=1)
        self.assertEqual(delivery.enrollment_id, original)

    def test_later_campaign_does_not_extend_mandatory_deadline(self):
        learner = self._employee('Deadline Campaign Learner')
        first = self._campaign('Earlier deadline')
        first.due_date = fields.Date.today() + timedelta(days=7)
        first.action_execute_assignment()
        enrollment = self.env['lms.enrollment'].search([
            ('employee_id', '=', learner.id), ('course_id', '=', self.course.id),
        ], limit=1)
        later = self._campaign('Later deadline')
        later.due_date = fields.Date.today() + timedelta(days=30)
        later.action_execute_assignment()
        self.assertEqual(later.enrolled_count, 0)
        self.assertEqual(enrollment.due_date, first.due_date)

    def test_learning_path_can_be_assigned_without_a_separate_course(self):
        learner = self._employee('Path Campaign Learner')
        path = self.env['lms.learning.path'].create({
            'name': 'Onboarding path',
            'code': 'LMS-CAMPAIGN-PATH',
            'description': '<p>Required onboarding.</p>',
            'path_course_ids': [(0, 0, {'course_id': self.course.id})],
        })
        campaign = self.env['lms.course.assignment'].create({
            'name': 'Path campaign',
            'learning_path_id': path.id,
            'assignment_type': 'individual',
            'employee_ids': [(6, 0, [learner.id])],
            'due_date': fields.Date.today() + timedelta(days=30),
        })
        campaign.action_execute_assignment()
        self.assertEqual(campaign.enrolled_count, 1)
        self.assertTrue(self.env['lms.enrollment'].search([
            ('employee_id', '=', learner.id), ('course_id', '=', self.course.id),
            ('assignment_id', '=', campaign.id),
        ], limit=1))
