# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import AccessError


class TestLmsPhase1Security(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.LmsCategory = cls.env['lms.category']
        cls.LmsCourse = cls.env['lms.course']
        cls.LmsLesson = cls.env['lms.lesson']
        cls.LmsAssessment = cls.env['lms.assessment']
        cls.LmsQuestion = cls.env['lms.question']
        cls.LmsQuestionAnswer = cls.env['lms.question.answer']
        cls.LmsEnrollment = cls.env['lms.enrollment']
        cls.LmsLessonProgress = cls.env['lms.lesson.progress']
        cls.LmsExamSession = cls.env['lms.exam.session']

        cls.instructor_user = cls.env['res.users'].create({
            'name': 'Test Instructor User',
            'login': 'test_instructor_sec@bunna.et',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('learning_management.group_lms_instructor').id])],
        })
        cls.instructor_employee = cls.env['hr.employee'].create({
            'name': 'Test Instructor Employee',
            'user_id': cls.instructor_user.id,
        })

        cls.category = cls.LmsCategory.create({
            'name': 'Security Test Category',
            'code': 'SEC-TEST',
        })

        cls.course = cls.LmsCourse.create({
            'name': 'Security Test Course',
            'code': 'SEC-101',
            'category_id': cls.category.id,
            'instructor_id': cls.instructor_employee.id,
            'description': '<p>Security Course</p>',
            'state': 'published',
        })

        cls.lesson = cls.LmsLesson.create({
            'name': 'Lesson 1 Video',
            'course_id': cls.course.id,
            'lesson_type': 'video',
            'video_source_type': 'file',
            'video_duration_seconds': 100,
            'min_watch_percentage': 90.0,
            'prevent_fast_forward': True,
        })

        cls.assessment = cls.LmsAssessment.create({
            'name': 'Security Test Assessment',
            'course_id': cls.course.id,
            'assessment_type': 'post_course',
            'pass_score_percentage': 70.0,
            'max_attempts': 3,
            'duration_minutes': 30,
            'instructions': '<p>Please read instructions carefully.</p>',
        })

        cls.question = cls.LmsQuestion.create({
            'name': 'Q1',
            'question_text': '<p>What is 2+2?</p>',
            'points': 1.0,
            'question_type': 'single_choice',
        })

        cls.ans_correct = cls.LmsQuestionAnswer.create({
            'question_id': cls.question.id,
            'answer_text': '4',
            'is_correct': True,
        })
        cls.ans_wrong = cls.LmsQuestionAnswer.create({
            'question_id': cls.question.id,
            'answer_text': '5',
            'is_correct': False,
        })

        cls.assessment.write({'fixed_question_ids': [(4, cls.question.id)]})

        # Create Learner User and Employee
        cls.learner_user = cls.env['res.users'].create({
            'name': 'Test Learner User',
            'login': 'test_learner_sec@bunna.et',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('learning_management.group_lms_learner').id])],
        })
        cls.learner_employee = cls.env['hr.employee'].create({
            'name': 'Test Learner Employee',
            'user_id': cls.learner_user.id,
        })

    def test_01_learner_cannot_read_answer_key_or_unassigned_questions(self):
        """Fix 1: Learner cannot read is_correct field or questions outside active exam session."""
        ans_as_learner = self.ans_correct.with_user(self.learner_user)
        # Attempting to read 'is_correct' as a learner must raise AccessError due to field-level groups
        with self.assertRaises(AccessError):
            ans_as_learner.read(['is_correct'])

        # Outside any active session, learner question search returns 0 questions due to record rule
        q_count = self.LmsQuestion.with_user(self.learner_user).search_count([('id', '=', self.question.id)])
        self.assertEqual(q_count, 0, "Learner must not see questions outside an assigned exam session")

    def test_02_video_streaming_unauthorized_denied(self):
        """Fix 2: Unenrolled user cannot stream lesson video."""
        from odoo.addons.learning_management.controllers.main import LmsController
        from unittest.mock import MagicMock
        import odoo.http

        controller = LmsController()
        env_learner = self.env(user=self.learner_user)

        authorized, resp, enrollment = controller._check_video_access(self.lesson.id, env=env_learner)
        self.assertFalse(authorized, "Unenrolled learner must be denied video access")
        self.assertEqual(resp.status_code, 403, "Response status must be 403 Forbidden")

        # Now enroll the learner
        enrollment_rec = self.LmsEnrollment.create({
            'employee_id': self.learner_employee.id,
            'course_id': self.course.id,
        })
        authorized, res, enr = controller._check_video_access(self.lesson.id, env=env_learner)
        self.assertTrue(authorized, "Enrolled learner must be granted video access")
        self.assertEqual(enr.id, enrollment_rec.id)

    def test_03_heartbeat_ignores_spoofed_duration_and_clamps_time(self):
        """Fix 3: Anti-skip heartbeat uses authoritative video duration and clamps spoofed time."""
        enrollment = self.LmsEnrollment.create({
            'employee_id': self.learner_employee.id,
            'course_id': self.course.id,
        })
        progress = self.LmsLessonProgress.search([
            ('enrollment_id', '=', enrollment.id),
            ('lesson_id', '=', self.lesson.id),
        ], limit=1)

        # Authoritative duration is 100s. Attacker sends duration=1, current_time=10
        res = progress.update_progress(current_time=10, duration=1)
        self.assertFalse(res['is_completed'], "Lesson must NOT be completed when client spoofs short duration")
        self.assertEqual(progress.max_watched_seconds, 10)
        self.assertNotEqual(progress.state, 'completed')

        # Attacker attempts to send current_time far beyond video_duration_seconds (e.g. 99999)
        res_spoof = progress.update_progress(current_time=99999, duration=100)
        # Max valid time clamped to video_duration_seconds (100) + tolerance (5) = 105
        self.assertLessEqual(progress.last_position_seconds, 105, "Current time must be clamped to authoritative duration + tolerance")
