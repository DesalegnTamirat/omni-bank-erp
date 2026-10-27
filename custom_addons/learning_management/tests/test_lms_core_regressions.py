# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase
from odoo.tools.safe_eval import safe_eval


class TestLmsCoreRegressions(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.learner = cls.env['res.users'].create({
            'name': 'LMS Core Learner',
            'login': 'lms_core_learner@example.test',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('learning_management.group_lms_learner').id,
            ])],
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'LMS Core Learner', 'user_id': cls.learner.id,
        })
        cls.category = cls.env['lms.category'].create({
            'name': 'Core Regression', 'code': 'LMS-CORE-REG',
        })

    def _course(self, name, state='published', post=False):
        course = self.env['lms.course'].create({
            'name': name,
            'category_id': self.category.id,
            'instructor_id': self.employee.id,
            'description': '<p>Core regression course</p>',
            'state': state,
            'has_post_assessment': post,
        })
        lesson = self.env['lms.lesson'].create({
            'name': '%s lesson' % name,
            'course_id': course.id,
            'lesson_type': 'text',
            'html_content': '<p>Bank training material</p>',
        })
        return course, lesson

    def test_app_menu_opens_learner_active_courses(self):
        menu = self.env.ref('learning_management.menu_lms_root')
        action = self.env.ref('learning_management.action_lms_my_enrollments')
        history_action = self.env.ref('learning_management.action_lms_my_history')
        self.assertEqual(menu.action, action)
        self.assertEqual(action.res_model, 'lms.enrollment')
        self.assertEqual(action.view_mode, 'kanban,list,form')

        Enrollment = self.env['lms.enrollment'].with_user(self.learner)
        views = Enrollment.get_views([(False, 'kanban'), (False, 'list')])
        self.assertIn('kanban', views['views'])
        self.assertIn('list', views['views'])

        course, _lesson = self._course('Menu navigation course')
        enrollment = self.env['lms.enrollment'].create({
            'employee_id': self.employee.id,
            'course_id': course.id,
        })
        active_domain = safe_eval(action.domain, {'uid': self.learner.id})
        history_domain = safe_eval(history_action.domain, {'uid': self.learner.id})
        self.assertIn(enrollment, Enrollment.search(active_domain))
        self.assertNotIn(enrollment, Enrollment.search(history_domain))

        enrollment.write({'state': 'completed'})
        self.assertNotIn(enrollment, Enrollment.search(active_domain))
        self.assertIn(enrollment, Enrollment.search(history_domain))

    def test_assignment_requires_draft_campaign_and_published_path_stages(self):
        first, _ = self._course('First path stage')
        second, _ = self._course('Second path stage', state='draft')
        path = self.env['lms.learning.path'].create({
            'name': 'Core path', 'code': 'LMS-CORE-PATH',
            'description': '<p>Ordered learning</p>',
        })
        stages = self.env['lms.learning.path.course']
        stages.create({'path_id': path.id, 'course_id': first.id, 'sequence': 10})
        stages.create({'path_id': path.id, 'course_id': second.id, 'sequence': 20})
        campaign = self.env['lms.course.assignment'].create({
            'name': 'Core path assignment',
            'course_id': first.id,
            'learning_path_id': path.id,
            'assignment_type': 'individual',
            'employee_ids': [(4, self.employee.id)],
            'due_date': fields.Date.today() + timedelta(days=7),
        })
        with self.assertRaises(UserError):
            campaign.action_execute_assignment()
        self.assertFalse(self.env['lms.enrollment'].search([('assignment_id', '=', campaign.id)]))

        second.write({'state': 'review'})
        second.write({'state': 'published'})
        campaign.action_execute_assignment()
        enrollments = self.env['lms.enrollment'].search([('assignment_id', '=', campaign.id)])
        self.assertEqual(set(enrollments.mapped('course_id').ids), {first.id, second.id})
        self.assertEqual(campaign.enrolled_count, 2)
        with self.assertRaises(UserError):
            campaign.action_execute_assignment()
        self.assertTrue(enrollments.filtered(lambda enrollment: enrollment.course_id == second).with_user(self.learner).is_locked)

    def test_learner_cannot_read_draft_material_or_management_reports(self):
        published, lesson = self._course('Published assigned course')
        _, draft_lesson = self._course('Draft hidden course', state='draft')
        other_course, _ = self._course('Other published course')
        other_exam = self.env['lms.assessment'].create({
            'name': 'Other course assessment',
            'course_id': other_course.id,
            'instructions': '<p>Private assessment instructions</p>',
        })
        Lesson = self.env['lms.lesson'].with_user(self.learner)
        self.assertFalse(Lesson.search([('id', '=', lesson.id)]))
        enrollment = self.env['lms.enrollment'].create({
            'employee_id': self.employee.id,
            'course_id': published.id,
        })
        self.assertTrue(Lesson.search([('id', '=', lesson.id)]))
        lesson_action = enrollment.lesson_progress_ids.with_user(self.learner).action_open_lesson()
        self.assertEqual(lesson_action['res_model'], 'lms.lesson')
        self.assertEqual(lesson_action['res_id'], lesson.id)
        self.assertFalse(Lesson.search([('id', '=', draft_lesson.id)]))
        self.assertFalse(self.env['lms.assessment'].with_user(self.learner).search([
            ('id', '=', other_exam.id),
        ]))
        with self.assertRaises(AccessError):
            enrollment.with_user(self.learner).write({'is_mandatory': False})
        with self.assertRaises(AccessError):
            self.env['lms.course.assignment'].with_user(self.learner).search_count([])
        with self.assertRaises(AccessError):
            self.env['lms.branch.compliance.report'].with_user(self.learner).search_count([])

    def test_direct_exam_create_obeys_training_gate_and_timed_deadline(self):
        course, lesson = self._course('Timed course', post=True)
        exam = self.env['lms.assessment'].create({
            'name': 'Timed final', 'course_id': course.id,
            'assessment_type': 'post_course',
            'instructions': '<p>Answer the question</p>',
            'duration_minutes': 1,
            'cooldown_hours': 0,
        })
        course.write({'post_assessment_id': exam.id})
        question = self.env['lms.question'].create({
            'name': 'Training question',
            'question_text': '<p>Choose the answer</p>',
            'question_type': 'single_choice',
        })
        answer = self.env['lms.question.answer'].create({
            'question_id': question.id, 'answer_text': 'Right', 'is_correct': True,
        })
        exam.write({'fixed_question_ids': [(4, question.id)]})
        enrollment = self.env['lms.enrollment'].create({
            'employee_id': self.employee.id, 'course_id': course.id,
        })
        course.write({'has_pre_assessment': True})
        with self.assertRaisesRegex(UserError, 'pre-course assessment'):
            self.env['lms.exam.session'].with_user(self.learner).create({
                'assessment_id': exam.id,
                'employee_id': self.employee.id,
                'enrollment_id': enrollment.id,
            })
        course.write({'has_pre_assessment': False})
        with self.assertRaises(UserError):
            self.env['lms.exam.session'].with_user(self.learner).create({
                'assessment_id': exam.id,
                'employee_id': self.employee.id,
                'enrollment_id': enrollment.id,
            })

        lesson_progress = enrollment.lesson_progress_ids.filtered(
            lambda progress: progress.lesson_id == lesson
        ).with_user(self.learner)
        lesson_progress.action_open_lesson()
        lesson_progress.mark_completed()
        direct_session = self.env['lms.exam.session'].with_user(self.learner).create({
            'assessment_id': exam.id,
            'employee_id': self.employee.id,
            'enrollment_id': enrollment.id,
            'start_time': fields.Datetime.now() - timedelta(days=5),
            'attempt_number': 999,
        })
        self.assertTrue(direct_session.line_ids)
        self.assertEqual(direct_session.attempt_number, 1)
        self.assertGreater(direct_session.start_time, fields.Datetime.now() - timedelta(minutes=1))
        action = enrollment.with_user(self.learner).action_start_post_assessment()
        session = self.env['lms.exam.session'].browse(action['res_id'])
        self.assertEqual(session.id, direct_session.id)
        with self.assertRaises(AccessError):
            session.with_user(self.learner).write({
                'start_time': fields.Datetime.now() + timedelta(days=1),
            })
        with self.assertRaises(AccessError):
            session.with_user(self.learner).write({
                'deadline_time': fields.Datetime.now() + timedelta(days=1),
            })
        session.write({'start_time': fields.Datetime.now() - timedelta(minutes=2)})
        self.env.flush_all()
        with self.assertRaises(UserError):
            session.line_ids.with_user(self.learner).write({
                'selected_answer_ids': [(4, answer.id)],
            })
        self.env['lms.exam.session'].cron_submit_expired_exams()
        self.assertEqual(session.state, 'failed')
