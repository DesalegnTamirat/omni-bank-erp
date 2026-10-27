# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError, AccessError


class TestLmsPhase2Gates(TransactionCase):

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
        cls.LmsExamSession = cls.env['lms.exam.session']
        cls.LmsLearningPath = cls.env['lms.learning.path']
        cls.LmsPathCourse = cls.env['lms.learning.path.course']

        cls.instructor_user = cls.env['res.users'].create({
            'name': 'Instructor Gates',
            'login': 'instructor_gates@bunna.et',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('learning_management.group_lms_instructor').id])],
        })
        cls.instructor_employee = cls.env['hr.employee'].create({
            'name': 'Instructor Gates Employee',
            'user_id': cls.instructor_user.id,
        })

        cls.learner_user = cls.env['res.users'].create({
            'name': 'Learner Gates',
            'login': 'learner_gates@bunna.et',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('learning_management.group_lms_learner').id])],
        })
        cls.learner_employee = cls.env['hr.employee'].create({
            'name': 'Learner Gates Employee',
            'user_id': cls.learner_user.id,
        })

        cls.manager_user = cls.env['res.users'].create({
            'name': 'Manager LMS User',
            'login': 'manager_lms_gates@bunna.et',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('learning_management.group_lms_manager').id])],
        })

        cls.category = cls.LmsCategory.create({
            'name': 'Gate Test Category',
            'code': 'GATE-CAT',
        })

    def test_04_assessment_gating_uncompleted_lessons_blocked(self):
        """Fix 4: Learner cannot take post-course assessment without completing all lessons."""
        course = self.LmsCourse.create({
            'name': 'Post-Assessment Gating Course',
            'category_id': self.category.id,
            'instructor_id': self.instructor_employee.id,
            'state': 'published',
            'description': '<p>Course description</p>',
        })
        lesson1 = self.LmsLesson.create({
            'name': 'Lesson 1',
            'course_id': course.id,
            'lesson_type': 'video',
            'video_duration_seconds': 120,
        })
        lesson2 = self.LmsLesson.create({
            'name': 'Lesson 2',
            'course_id': course.id,
            'lesson_type': 'document',
        })
        post_exam = self.LmsAssessment.create({
            'name': 'Final Exam',
            'course_id': course.id,
            'assessment_type': 'post_course',
            'pass_score_percentage': 75.0,
            'instructions': '<p>Final exam instructions</p>',
        })
        q = self.LmsQuestion.create({
            'name': 'Q1',
            'question_text': '<p>Question</p>',
            'points': 10.0,
            'question_type': 'single_choice',
        })
        self.LmsQuestionAnswer.create({
            'question_id': q.id,
            'answer_text': 'Correct Answer',
            'is_correct': True,
        })
        post_exam.write({'fixed_question_ids': [(4, q.id)]})

        # Learner not enrolled -> must raise UserError
        with self.assertRaises(UserError):
            post_exam.with_user(self.learner_user).action_start_exam()

        # Enroll learner
        enrollment = self.LmsEnrollment.create({
            'employee_id': self.learner_employee.id,
            'course_id': course.id,
        })

        # Lessons are incomplete -> must raise UserError with incomplete lesson names
        with self.assertRaises(UserError) as cm:
            post_exam.with_user(self.learner_user).action_start_exam()
        self.assertIn("You must complete all lessons", str(cm.exception))

        # Complete lesson 1 only -> still incomplete
        prog1 = enrollment.lesson_progress_ids.filtered(lambda lp: lp.lesson_id == lesson1)
        prog1.write({'state': 'completed'})
        with self.assertRaises(UserError):
            post_exam.with_user(self.learner_user).action_start_exam()

        # Complete lesson 2 -> now all lessons are completed
        prog2 = enrollment.lesson_progress_ids.filtered(lambda lp: lp.lesson_id == lesson2)
        prog2.write({'state': 'completed'})

        action = post_exam.with_user(self.learner_user).action_start_exam()
        self.assertEqual(action.get('res_model'), 'lms.exam.session')
        session = self.LmsExamSession.browse(action['res_id'])
        self.assertEqual(session.state, 'in_progress')
        self.assertEqual(session.employee_id.id, self.learner_employee.id)
        line = session.line_ids[:1]
        with self.assertRaises(AccessError):
            line.with_user(self.learner_user).write({'points_earned': 10.0})
        other_question = self.LmsQuestion.create({
            'name': 'Other question', 'question_text': '<p>Other</p>',
        })
        other_answer = self.LmsQuestionAnswer.create({
            'question_id': other_question.id, 'answer_text': 'Unrelated answer',
            'is_correct': True,
        })
        with self.assertRaises(UserError):
            line.with_user(self.learner_user).write({
                'selected_answer_ids': [(6, 0, [other_answer.id])],
            })

    def test_05_pre_assessment_gating(self):
        """Fix 5: Course content access blocked until pre-assessment passed."""
        from odoo.addons.learning_management.controllers.main import LmsController

        course = self.LmsCourse.create({
            'name': 'Pre-Assessment Gating Course',
            'category_id': self.category.id,
            'instructor_id': self.instructor_employee.id,
            'state': 'published',
            'description': '<p>Course description</p>',
            'has_pre_assessment': True,
        })
        lesson = self.LmsLesson.create({
            'name': 'Core Video Lesson',
            'course_id': course.id,
            'lesson_type': 'video',
            'video_duration_seconds': 100,
        })
        pre_exam = self.LmsAssessment.create({
            'name': 'Diagnostic Pre-Test',
            'course_id': course.id,
            'assessment_type': 'pre_course',
            'pass_score_percentage': 60.0,
            'cooldown_hours': 0,
            'instructions': '<p>Pre-test instructions</p>',
        })
        course.write({'pre_assessment_id': pre_exam.id})

        q = self.LmsQuestion.create({
            'name': 'Pre-Q1',
            'question_text': '<p>Diagnostic Q</p>',
            'points': 10.0,
            'question_type': 'single_choice',
        })
        ans_yes = self.LmsQuestionAnswer.create({
            'question_id': q.id,
            'answer_text': 'Correct',
            'is_correct': True,
        })
        ans_no = self.LmsQuestionAnswer.create({
            'question_id': q.id,
            'answer_text': 'Wrong',
            'is_correct': False,
        })
        pre_exam.write({'fixed_question_ids': [(4, q.id)]})

        enrollment = self.LmsEnrollment.create({
            'employee_id': self.learner_employee.id,
            'course_id': course.id,
        })

        controller = LmsController()
        env_learner = self.env(user=self.learner_user)

        # 1. Attempting to start course before pre-assessment is passed -> UserError
        self.assertFalse(enrollment.pre_assessment_passed)
        with self.assertRaises(UserError):
            enrollment.with_user(self.learner_user).action_start_course()

        # 2. Attempting to stream video before pre-assessment is passed -> 403 Forbidden
        auth, resp, _ = controller._check_video_access(lesson.id, env=env_learner)
        self.assertFalse(auth)
        self.assertEqual(resp.status_code, 403)

        # 3. Learner fails pre-assessment
        fail_session = pre_exam.with_user(self.learner_user).action_start_exam()
        sess_fail = self.LmsExamSession.browse(fail_session['res_id'])
        line = sess_fail.line_ids[0]
        line.write({'selected_answer_ids': [(4, ans_no.id)]})
        sess_fail.action_submit_and_grade()
        self.assertEqual(sess_fail.state, 'failed')
        self.assertFalse(enrollment.pre_assessment_passed)

        # 4. Learner retries and passes pre-assessment
        pass_session = pre_exam.with_user(self.learner_user).action_start_exam()
        sess_pass = self.LmsExamSession.browse(pass_session['res_id'])
        line = sess_pass.line_ids[0]
        line.write({'selected_answer_ids': [(4, ans_yes.id)]})
        sess_pass.action_submit_and_grade()
        self.assertEqual(sess_pass.state, 'passed')
        enrollment.invalidate_recordset(['pre_assessment_passed'])
        self.assertTrue(enrollment.pre_assessment_passed, "pre_assessment_passed must be set to True on enrollment")

        # 5. Now action_start_course and video streaming succeed
        start_action = enrollment.with_user(self.learner_user).action_start_course()
        self.assertEqual(enrollment.state, 'in_progress')
        self.assertEqual(start_action['type'], 'ir.actions.act_url')
        self.assertIn('/lms/video/%s/player' % lesson.id, start_action['url'])
        auth_ok, _, _ = controller._check_video_access(lesson.id, env=env_learner)
        self.assertTrue(auth_ok)

    def test_module_quiz_pass_credits_lesson_and_opens_final_exam(self):
        """A failed quiz stays gated; a passing attempt credits only its enrollment."""
        course = self.LmsCourse.create({
            'name': 'Module quiz completion course',
            'category_id': self.category.id,
            'instructor_id': self.instructor_employee.id,
            'state': 'published',
            'description': '<p>Course description</p>',
            'issue_certificate': False,
        })
        reading = self.LmsLesson.create({
            'name': 'Read first', 'course_id': course.id,
            'lesson_type': 'text', 'html_content': '<p>Read.</p>',
            'is_mandatory': True,
        })
        question = self.LmsQuestion.create({
            'name': 'Quiz question', 'question_text': '<p>Choose yes.</p>',
            'question_type': 'single_choice', 'points': 1,
        })
        correct = self.LmsQuestionAnswer.create({
            'question_id': question.id, 'answer_text': 'Yes', 'is_correct': True,
        })
        wrong = self.LmsQuestionAnswer.create({
            'question_id': question.id, 'answer_text': 'No', 'is_correct': False,
        })
        quiz = self.LmsAssessment.create({
            'name': 'Module check', 'course_id': course.id,
            'assessment_type': 'module_quiz', 'cooldown_hours': 0,
            'use_random_pool': False, 'fixed_question_ids': [(4, question.id)],
            'instructions': '<p>Answer the quiz.</p>',
        })
        quiz_lesson = self.LmsLesson.create({
            'name': 'Quiz lesson', 'course_id': course.id,
            'lesson_type': 'quiz', 'assessment_id': quiz.id,
            'is_mandatory': True,
        })
        final = self.LmsAssessment.create({
            'name': 'Final check', 'course_id': course.id,
            'assessment_type': 'post_course', 'use_random_pool': False,
            'fixed_question_ids': [(4, question.id)],
            'instructions': '<p>Answer the final.</p>',
        })
        course.write({'post_assessment_id': final.id})
        enrollment = self.LmsEnrollment.create({
            'employee_id': self.learner_employee.id, 'course_id': course.id,
        })
        other_enrollment = self.LmsEnrollment.create({
            'employee_id': self.instructor_employee.id, 'course_id': course.id,
        })

        reading_progress = enrollment.lesson_progress_ids.filtered(lambda p: p.lesson_id == reading)
        quiz_progress = enrollment.lesson_progress_ids.filtered(lambda p: p.lesson_id == quiz_lesson)
        other_quiz_progress = other_enrollment.lesson_progress_ids.filtered(
            lambda p: p.lesson_id == quiz_lesson)
        reading_progress.with_user(self.learner_user).action_open_lesson()
        reading_progress.with_user(self.learner_user).mark_completed()
        with self.assertRaises(UserError):
            final.with_user(self.learner_user).action_start_exam(enrollment)

        failed_action = quiz_progress.with_user(self.learner_user).action_open_lesson()
        failed = self.LmsExamSession.browse(failed_action['res_id'])
        failed.line_ids.with_user(self.learner_user).write({
            'selected_answer_ids': [(6, 0, [wrong.id])],
        })
        failed.with_user(self.learner_user).action_submit_and_grade()
        self.assertEqual(failed.state, 'failed')
        self.assertNotEqual(quiz_progress.state, 'completed')
        with self.assertRaises(UserError):
            final.with_user(self.learner_user).action_start_exam(enrollment)

        passed_action = quiz_progress.with_user(self.learner_user).action_open_lesson()
        passed = self.LmsExamSession.browse(passed_action['res_id'])
        passed.line_ids.with_user(self.learner_user).write({
            'selected_answer_ids': [(6, 0, [correct.id])],
        })
        passed.with_user(self.learner_user).action_submit_and_grade()
        self.assertEqual(passed.state, 'passed')
        self.assertEqual(quiz_progress.state, 'completed')
        self.assertEqual(quiz_progress.completion_method, 'quiz_pass')
        self.assertTrue(quiz_progress.date_completed)
        self.assertNotEqual(other_quiz_progress.state, 'completed')
        self.assertEqual(enrollment.state, 'in_progress')

        final_action = final.with_user(self.learner_user).action_start_exam(enrollment)
        final_session = self.LmsExamSession.browse(final_action['res_id'])
        final_session.line_ids.with_user(self.learner_user).write({
            'selected_answer_ids': [(6, 0, [correct.id])],
        })
        final_session.with_user(self.learner_user).action_submit_and_grade()
        self.assertEqual(enrollment.state, 'completed')
        self.assertEqual(other_enrollment.state, 'enrolled')

    def test_shared_quiz_assessment_credits_only_unlocked_lesson(self):
        """A pass cannot credit a later quiz behind a required reading lesson."""
        course = self.LmsCourse.create({
            'name': 'Repeated module check course',
            'category_id': self.category.id,
            'instructor_id': self.instructor_employee.id,
            'state': 'published',
            'description': '<p>Course description</p>',
            'has_post_assessment': False,
            'issue_certificate': False,
        })
        question = self.LmsQuestion.create({
            'name': 'Shared question', 'question_text': '<p>Choose yes.</p>',
            'question_type': 'single_choice', 'points': 1,
        })
        correct = self.LmsQuestionAnswer.create({
            'question_id': question.id, 'answer_text': 'Yes', 'is_correct': True,
        })
        assessment = self.LmsAssessment.create({
            'name': 'Shared module check', 'course_id': course.id,
            'assessment_type': 'module_quiz', 'cooldown_hours': 0,
            'use_random_pool': False, 'fixed_question_ids': [(4, question.id)],
            'instructions': '<p>Answer the quiz.</p>',
        })
        first_quiz = self.LmsLesson.create({
            'name': 'First quiz', 'course_id': course.id,
            'lesson_type': 'quiz', 'assessment_id': assessment.id,
            'is_mandatory': True,
        })
        reading = self.LmsLesson.create({
            'name': 'Required reading', 'course_id': course.id,
            'lesson_type': 'text', 'html_content': '<p>Read.</p>',
            'is_mandatory': True,
        })
        later_quiz = self.LmsLesson.create({
            'name': 'Later quiz', 'course_id': course.id,
            'lesson_type': 'quiz', 'assessment_id': assessment.id,
            'is_mandatory': True,
        })
        enrollment = self.LmsEnrollment.create({
            'employee_id': self.learner_employee.id, 'course_id': course.id,
        })
        first_progress = enrollment.lesson_progress_ids.filtered(lambda p: p.lesson_id == first_quiz)
        reading_progress = enrollment.lesson_progress_ids.filtered(lambda p: p.lesson_id == reading)
        later_progress = enrollment.lesson_progress_ids.filtered(lambda p: p.lesson_id == later_quiz)

        first_action = first_progress.with_user(self.learner_user).action_open_lesson()
        first_session = self.LmsExamSession.browse(first_action['res_id'])
        first_session.line_ids.with_user(self.learner_user).write({
            'selected_answer_ids': [(6, 0, [correct.id])],
        })
        first_session.with_user(self.learner_user).action_submit_and_grade()
        self.assertEqual(first_session.state, 'passed')
        self.assertEqual(first_progress.state, 'completed')
        self.assertNotEqual(reading_progress.state, 'completed')
        self.assertNotEqual(later_progress.state, 'completed')

        reading_progress.with_user(self.learner_user).action_open_lesson()
        reading_progress.with_user(self.learner_user).mark_completed()
        later_action = later_progress.with_user(self.learner_user).action_open_lesson()
        later_session = self.LmsExamSession.browse(later_action['res_id'])
        later_session.line_ids.with_user(self.learner_user).write({
            'selected_answer_ids': [(6, 0, [correct.id])],
        })
        later_session.with_user(self.learner_user).action_submit_and_grade()
        self.assertEqual(later_progress.state, 'completed')
        self.assertEqual(enrollment.state, 'completed')

    def test_06_learning_path_sequencing(self):
        """Fix 6: Learning path sequence locks subsequent courses until prerequisites are completed."""
        from odoo.addons.learning_management.controllers.main import LmsController

        course_a = self.LmsCourse.create({
            'name': 'Level 1 Course A',
            'category_id': self.category.id,
            'instructor_id': self.instructor_employee.id,
            'state': 'published',
            'description': '<p>Course description</p>',
            'has_post_assessment': False,
        })
        self.LmsLesson.create({
            'name': 'Level 1 reading', 'course_id': course_a.id,
            'lesson_type': 'text', 'html_content': '<p>Read this lesson.</p>',
        })
        course_b = self.LmsCourse.create({
            'name': 'Level 2 Course B',
            'category_id': self.category.id,
            'instructor_id': self.instructor_employee.id,
            'state': 'published',
            'description': '<p>Course description</p>',
        })
        lesson_b = self.LmsLesson.create({
            'name': 'Lesson B1',
            'course_id': course_b.id,
            'lesson_type': 'video',
            'video_duration_seconds': 60,
        })

        # Create Learning Path
        path = self.LmsLearningPath.create({
            'name': 'Credit Analysis Path',
            'code': 'CAP-01',
            'description': '<p>Progressive credit curriculum</p>',
        })
        self.LmsPathCourse.create({
            'path_id': path.id,
            'sequence': 10,
            'course_id': course_a.id,
        })
        self.LmsPathCourse.create({
            'path_id': path.id,
            'sequence': 20,
            'course_id': course_b.id,
            'prerequisite_course_ids': [(4, course_a.id)],
        })

        enrollment_a = self.LmsEnrollment.create({
            'employee_id': self.learner_employee.id,
            'course_id': course_a.id,
        })
        enrollment_b = self.LmsEnrollment.create({
            'employee_id': self.learner_employee.id,
            'course_id': course_b.id,
        })

        controller = LmsController()
        env_learner = self.env(user=self.learner_user)

        # Course A is not completed -> Course B must be locked
        self.assertTrue(enrollment_b.is_locked, "Enrollment B must be locked until Course A is completed")
        with self.assertRaises(UserError):
            enrollment_b.with_user(self.learner_user).action_start_course()

        auth, resp, _ = controller._check_video_access(lesson_b.id, env=env_learner)
        self.assertFalse(auth)
        self.assertEqual(resp.status_code, 403)

        # Now complete Course A
        enrollment_a.lesson_progress_ids.mark_completed()
        self.assertEqual(enrollment_a.state, 'completed')

        # Course B must now be unlocked
        enrollment_b.invalidate_recordset(['is_locked'])
        self.assertFalse(enrollment_b.is_locked, "Enrollment B must be unlocked after Course A completion")
        enrollment_b.with_user(self.learner_user).action_start_course()
        self.assertEqual(enrollment_b.state, 'in_progress')

        auth_ok, _, _ = controller._check_video_access(lesson_b.id, env=env_learner)
        self.assertTrue(auth_ok)

    def test_07_attempt_cooldown(self):
        """Fix 7: Cooldown period is strictly enforced between exam attempts."""
        course = self.LmsCourse.create({
            'name': 'Cooldown Test Course',
            'category_id': self.category.id,
            'instructor_id': self.instructor_employee.id,
            'state': 'published',
            'description': '<p>Course description</p>',
        })
        assessment = self.LmsAssessment.create({
            'name': 'Cooldown Exam',
            'course_id': course.id,
            'assessment_type': 'post_course',
            'pass_score_percentage': 80.0,
            'cooldown_hours': 2.0,
            'instructions': '<p>Cooldown test</p>',
        })
        q = self.LmsQuestion.create({
            'name': 'Q-Cool',
            'question_text': '<p>Cool question</p>',
            'points': 5.0,
            'question_type': 'single_choice',
        })
        self.LmsQuestionAnswer.create({
            'question_id': q.id,
            'answer_text': 'Ans',
            'is_correct': True,
        })
        assessment.write({'fixed_question_ids': [(4, q.id)]})

        enrollment = self.LmsEnrollment.create({
            'employee_id': self.learner_employee.id,
            'course_id': course.id,
        })

        # Start attempt 1
        action1 = assessment.with_user(self.learner_user).action_start_exam()
        sess1 = self.LmsExamSession.browse(action1['res_id'])
        sess1.action_submit_and_grade()

        # Immediate attempt 2 -> must raise UserError due to cooldown period
        with self.assertRaises(UserError) as cm:
            assessment.with_user(self.learner_user).action_start_exam()
        self.assertIn("Cooldown period active", str(cm.exception))

        # Simulate time passing beyond 2 hours cooldown
        sess1.write({'end_time': fields.Datetime.now() - timedelta(hours=3)})

        # Now attempt 2 must succeed
        action2 = assessment.with_user(self.learner_user).action_start_exam()
        sess2 = self.LmsExamSession.browse(action2['res_id'])
        self.assertEqual(sess2.state, 'in_progress')
        self.assertEqual(sess2.attempt_number, 2)

    def test_09_lms_course_state_guard(self):
        """Fix 9: Only LMS Managers can publish or archive courses directly."""
        course = self.LmsCourse.create({
            'name': 'State Guard Test Course',
            'category_id': self.category.id,
            'instructor_id': self.instructor_employee.id,
            'description': '<p>Course description</p>',
            'state': 'draft',
            'has_post_assessment': False,
        })
        self.LmsLesson.create({
            'name': 'State Guard Reading', 'course_id': course.id,
            'lesson_type': 'text', 'html_content': '<p>Read this lesson.</p>',
        })
        # Learner / non-manager cannot set state to published or archived
        with self.assertRaises(AccessError):
            course.with_user(self.learner_user).write({'state': 'published'})
        with self.assertRaises(AccessError):
            course.with_user(self.learner_user).write({'state': 'archived'})

        # LMS Manager can publish after review and archive the course.
        course.with_user(self.manager_user).action_submit_for_review()
        course.with_user(self.manager_user).action_publish()
        self.assertEqual(course.state, 'published')
        course.with_user(self.manager_user).write({'state': 'archived'})
        self.assertEqual(course.state, 'archived')

    def test_10_assessment_max_attempts_enforcement(self):
        """FR-LMS-016: Server-side enforcement of assessment max attempts limit."""
        course = self.LmsCourse.create({
            'name': 'Max Attempts Test Course',
            'category_id': self.category.id,
            'instructor_id': self.instructor_employee.id,
            'state': 'published',
            'description': '<p>Description</p>',
        })
        assessment = self.LmsAssessment.create({
            'name': 'Strict 1-Attempt Exam',
            'course_id': course.id,
            'assessment_type': 'post_course',
            'max_attempts': 1,
            'cooldown_hours': 0.0,
            'pass_score_percentage': 80.0,
            'instructions': '<p>1 attempt only</p>',
        })
        q = self.LmsQuestion.create({
            'name': 'Q-Strict',
            'question_text': '<p>Question text</p>',
            'points': 10.0,
            'question_type': 'single_choice',
        })
        self.LmsQuestionAnswer.create({
            'question_id': q.id,
            'answer_text': 'Right Answer',
            'is_correct': True,
        })
        assessment.write({'fixed_question_ids': [(4, q.id)]})

        enrollment = self.LmsEnrollment.create({
            'employee_id': self.learner_employee.id,
            'course_id': course.id,
        })

        # Attempt 1 succeeds
        action1 = assessment.with_user(self.learner_user).action_start_exam()
        sess1 = self.LmsExamSession.browse(action1['res_id'])
        sess1.action_submit_and_grade()
        self.assertIn(sess1.state, ['passed', 'failed'])

        # Attempt 2 via action_start_exam -> must raise UserError
        with self.assertRaises(UserError) as cm:
            assessment.with_user(self.learner_user).action_start_exam()
        self.assertIn("exhausted the maximum allowed attempts", str(cm.exception))

        # Attempt 2 via create_session_for_learner -> must raise UserError
        with self.assertRaises(UserError):
            self.LmsExamSession.create_session_for_learner(assessment, self.learner_employee, enrollment)

        # Attempt 2 via direct ORM create -> must raise UserError
        with self.assertRaises(UserError):
            self.LmsExamSession.create({
                'assessment_id': assessment.id,
                'employee_id': self.learner_employee.id,
                'enrollment_id': enrollment.id,
            })

    def test_11_course_version_archiving_and_visibility(self):
        """FR-LMS-011: Publishing a new course version auto-archives predecessor and hides from learner catalog."""
        course_v1 = self.LmsCourse.create({
            'name': 'Risk Management Course',
            'category_id': self.category.id,
            'instructor_id': self.instructor_employee.id,
            'state': 'draft',
            'version': '1.0',
            'description': '<p>V1 syllabus</p>',
        })
        self.LmsLesson.create({
            'name': 'Intro to Risk',
            'course_id': course_v1.id,
            'lesson_type': 'text',
            'html_content': '<p>Content</p>',
        })
        # Publish v1
        course_v1.write({'has_post_assessment': False})
        course_v1.with_user(self.manager_user).action_submit_for_review()
        course_v1.with_user(self.manager_user).action_publish()
        self.assertEqual(course_v1.state, 'published')
        self.assertTrue(course_v1.is_latest_version)

        # Learner can see v1
        published_for_learner = self.LmsCourse.with_user(self.learner_user).search([('id', '=', course_v1.id)])
        self.assertTrue(published_for_learner)

        # Create v2
        rev_action = course_v1.with_user(self.manager_user).action_create_new_version()
        course_v2 = self.LmsCourse.browse(rev_action['res_id'])
        self.assertEqual(course_v2.version, '1.1')
        self.assertEqual(course_v2.previous_version_id.id, course_v1.id)

        # Publish v2
        course_v2.with_user(self.manager_user).action_submit_for_review()
        course_v2.with_user(self.manager_user).action_publish()
        self.assertEqual(course_v2.state, 'published')
        self.assertTrue(course_v2.is_latest_version)

        # v1 must be automatically archived and is_latest_version=False
        course_v1.invalidate_recordset(['state', 'is_latest_version'])
        self.assertEqual(course_v1.state, 'archived')
        self.assertFalse(course_v1.is_latest_version)

        # Learner search catalog must find v2, but NOT v1
        catalog = self.LmsCourse.with_user(self.learner_user).search([('id', 'in', [course_v1.id, course_v2.id])])
        self.assertIn(course_v2, catalog)
        self.assertNotIn(course_v1, catalog)

    def test_12_cron_send_overdue_reminders(self):
        """FR-LMS-028: Daily automated notifications for overdue and approaching-deadline mandatory courses."""
        today = fields.Date.context_today(self)
        course = self.LmsCourse.create({
            'name': 'Mandatory AML Compliance',
            'category_id': self.category.id,
            'instructor_id': self.instructor_employee.id,
            'state': 'published',
            'is_mandatory': True,
            'description': '<p>AML compliance syllabus</p>',
        })
        enrollment_overdue = self.LmsEnrollment.create({
            'employee_id': self.learner_employee.id,
            'course_id': course.id,
            'is_mandatory': True,
            'due_date': today - timedelta(days=5),
            'state': 'in_progress',
        })

        # Run cron
        self.env['lms.enrollment'].cron_send_overdue_reminders()

        # Check chatter on overdue enrollment
        messages = enrollment_overdue.message_ids
        overdue_notif = messages.filtered(lambda m: "MANDATORY TRAINING OVERDUE" in (m.body or ''))
        self.assertTrue(overdue_notif, "Overdue warning message should be posted to chatter")

    def test_13_direct_completion_and_video_field_access_are_blocked(self):
        course = self.LmsCourse.create({
            'name': 'Protected Completion Course',
            'category_id': self.category.id,
            'instructor_id': self.instructor_employee.id,
            'description': '<p>Required reading</p>',
            'state': 'published',
            'has_post_assessment': False,
            'issue_certificate': False,
        })
        lesson = self.LmsLesson.create({
            'name': 'Required Reading', 'course_id': course.id,
            'lesson_type': 'text', 'html_content': '<p>Read this.</p>',
        })
        enrollment = self.LmsEnrollment.create({
            'employee_id': self.learner_employee.id, 'course_id': course.id,
        })
        with self.assertRaises(AccessError):
            enrollment.with_user(self.learner_user).write({'state': 'completed'})
        with self.assertRaises(UserError):
            enrollment.with_user(self.learner_user).action_mark_completed_and_certify()
        with self.assertRaises(AccessError):
            enrollment.lesson_progress_ids.with_user(self.learner_user).write({'state': 'completed'})
        video = self.LmsLesson.create({
            'name': 'Protected Video', 'course_id': course.id,
            'lesson_type': 'video', 'video_file': b'AA==',
            'is_mandatory': False,
        })
        with self.assertRaises(AccessError):
            video.with_user(self.learner_user).read(['video_file'])
        reading_progress = enrollment.lesson_progress_ids.filtered(
            lambda progress: progress.lesson_id == lesson
        ).with_user(self.learner_user)
        reading_progress.action_open_lesson()
        reading_progress.mark_completed()
        self.assertEqual(enrollment.state, 'completed')
