# -*- coding: utf-8 -*-
from datetime import date, timedelta
from odoo.tests.common import TransactionCase

class TestLmsAssignmentsAndAnalytics(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.LmsCategory = cls.env['lms.category']
        cls.LmsCourse = cls.env['lms.course']
        cls.LmsLesson = cls.env['lms.lesson']
        cls.LmsEnrollment = cls.env['lms.enrollment']
        cls.LmsLessonProgress = cls.env['lms.lesson.progress']

        cls.dept = cls.env['hr.department'].create({'name': 'Test Training Dept'})
        cls.ou = cls.env['operating.unit'].search([], limit=1)
        if not cls.ou:
            cls.ou = cls.env['operating.unit'].create({'name': 'Main Branch HQ', 'code': 'MBHQ'})

        cls.mgr_user = cls.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create({
            'name': 'LMS Manager Test User',
            'login': 'lms_mgr_test@bunnabank.et',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('learning_management.group_lms_manager').id])],
        })
        cls.mgr_emp = cls.env['hr.employee'].create({
            'name': 'LMS Manager Test Emp',
            'user_id': cls.mgr_user.id,
            'department_id': cls.dept.id,
            'default_operating_unit_id': cls.ou.id,
        })

        cls.learner_user = cls.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create({
            'name': 'LMS Learner Test User',
            'login': 'lms_learner_test@bunnabank.et',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('learning_management.group_lms_learner').id])],
        })
        cls.learner_emp = cls.env['hr.employee'].create({
            'name': 'LMS Learner Test Emp',
            'user_id': cls.learner_user.id,
            'parent_id': cls.mgr_emp.id,
            'department_id': cls.dept.id,
            'default_operating_unit_id': cls.ou.id,
        })

        cls.category = cls.LmsCategory.create({'name': 'Analytics & Reminders Test Category', 'code': 'ARTC-01'})
        cls.course = cls.LmsCourse.create({
            'name': 'Analytics Compliance Course',
            'code': 'ACC-101',
            'category_id': cls.category.id,
            'instructor_id': cls.mgr_emp.id,
            'description': '<p>Analytics Course Description</p>',
            'state': 'published',
            'is_mandatory_default': True,
        })
        cls.lesson1 = cls.LmsLesson.create({
            'name': 'Lesson 1: Intro',
            'course_id': cls.course.id,
            'sequence': 10,
            'video_duration_seconds': 120,
            'min_watch_percentage': 80.0,
        })
        cls.lesson2 = cls.LmsLesson.create({
            'name': 'Lesson 2: Advanced',
            'course_id': cls.course.id,
            'sequence': 20,
            'video_duration_seconds': 180,
            'min_watch_percentage': 80.0,
        })

    def test_01_enrollment_creation_activity_and_chatter(self):
        due = date.today() + timedelta(days=14)
        enrollment = self.LmsEnrollment.create({
            'employee_id': self.learner_emp.id,
            'course_id': self.course.id,
            'is_mandatory': True,
            'due_date': due,
        })
        self.assertTrue(enrollment.id)
        messages = enrollment.message_ids
        self.assertTrue(any('enrolled in the course' in (m.body or '') for m in messages))
        activities = self.env['mail.activity'].search([
            ('res_model', '=', 'lms.enrollment'),
            ('res_id', '=', enrollment.id),
            ('user_id', '=', self.learner_user.id),
        ])
        self.assertTrue(activities, 'A To-Do mail activity should be scheduled for the enrolled user.')
        self.assertEqual(activities[0].date_deadline, due)

    def test_02_progress_threshold_notifications(self):
        enrollment = self.LmsEnrollment.create({
            'employee_id': self.learner_emp.id,
            'course_id': self.course.id,
        })
        self.assertFalse(enrollment.threshold_50_notified)
        self.assertFalse(enrollment.threshold_100_notified)
        lp1 = enrollment.lesson_progress_ids.filtered(lambda lp: lp.lesson_id == self.lesson1)
        self.assertTrue(lp1)
        lp1.mark_completed()
        self.assertEqual(enrollment.progress_percentage, 50.0)
        self.assertTrue(enrollment.threshold_50_notified)
        messages_50 = enrollment.message_ids.filtered(lambda m: '50' in (m.body or '') or 'Milestone' in (m.body or ''))
        self.assertTrue(messages_50)
        lp2 = enrollment.lesson_progress_ids.filtered(lambda lp: lp.lesson_id == self.lesson2)
        self.assertTrue(lp2)
        lp2.mark_completed()
        self.assertEqual(enrollment.progress_percentage, 100.0)
        self.assertTrue(enrollment.threshold_100_notified)

    def test_03_configurable_due_date_reminders_cron(self):
        self.env['ir.config_parameter'].sudo().set_param('learning_management.reminder_days_before_due', '7')
        today = date.today()
        enrollment_upcoming = self.LmsEnrollment.create({
            'employee_id': self.learner_emp.id,
            'course_id': self.course.id,
            'is_mandatory': True,
            'due_date': today + timedelta(days=5),
        })
        self.LmsEnrollment.cron_send_overdue_reminders()
        upcoming_msgs = enrollment_upcoming.message_ids.filtered(lambda m: 'UPCOMING DEADLINE' in (m.body or ''))
        self.assertTrue(upcoming_msgs)

    def test_04_engagement_report_view(self):
        enrollment = self.LmsEnrollment.create({
            'employee_id': self.learner_emp.id,
            'course_id': self.course.id,
        })
        lp1 = enrollment.lesson_progress_ids.filtered(lambda lp: lp.lesson_id == self.lesson1)
        lp1.write({'total_seconds_watched': 120})
        lp1.mark_completed()
        lp2 = enrollment.lesson_progress_ids.filtered(lambda lp: lp.lesson_id == self.lesson2)
        lp2.write({'total_seconds_watched': 180})
        lp2.mark_completed()
        enrollment.action_mark_completed_and_certify(score_pct=95.0)
        report_records = self.env['lms.engagement.report'].search([('course_id', '=', self.course.id)])
        self.assertTrue(report_records)
        rec = report_records[0]
        self.assertGreaterEqual(rec.total_enrolled, 1)
        self.assertGreaterEqual(rec.total_completed, 1)
        self.assertGreaterEqual(rec.completion_rate, 50.0)
        self.assertGreaterEqual(rec.avg_score, 90.0)
        self.assertGreaterEqual(rec.avg_time_spent_minutes, 1.0)

    def test_05_res_config_settings_integration(self):
        settings = self.env['res.config.settings'].create({'lms_reminder_days_before_due': 5})
        settings.execute()
        param = self.env['ir.config_parameter'].sudo().get_param('learning_management.reminder_days_before_due')
        self.assertEqual(param, '5')
        new_settings = self.env['res.config.settings'].create({})
        self.assertEqual(new_settings.lms_reminder_days_before_due, 5)
