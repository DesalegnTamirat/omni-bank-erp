# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase
from ..controllers.main import LmsController


class TestLmsPublicationIntegrity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = [cls.env.ref('base.group_user').id,
                  cls.env.ref('learning_management.group_lms_manager').id]
        cls.reviewer = cls.env['res.users'].create({
            'name': 'LMS Content Reviewer',
            'login': 'lms_content_reviewer@example.test',
            'group_ids': [(6, 0, groups)],
        })
        cls.other_manager = cls.env['res.users'].create({
            'name': 'Other LMS Manager',
            'login': 'lms_other_manager@example.test',
            'group_ids': [(6, 0, groups)],
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Content Owner', 'user_id': cls.reviewer.id,
        })
        cls.learner = cls.env['res.users'].create({
            'name': 'Revision Learner',
            'login': 'lms_revision_learner@example.test',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('learning_management.group_lms_learner').id,
            ])],
        })
        cls.learner_employee = cls.env['hr.employee'].create({
            'name': 'Revision Learner', 'user_id': cls.learner.id,
        })
        cls.category = cls.env['lms.category'].create({
            'name': 'Publication Integrity', 'code': 'PUB-INTEGRITY',
        })

    def _course(self, name='Safe publication', lesson_type='text', **lesson_values):
        course = self.env['lms.course'].create({
            'name': name,
            'category_id': self.category.id,
            'description': '<p>Training course description.</p>',
            'instructor_id': self.employee.id,
            'reviewer_id': self.reviewer.id,
            'has_post_assessment': False,
        })
        section = self.env['lms.course.section'].create({
            'name': 'Part one', 'course_id': course.id,
        })
        values = {
            'name': 'The lesson', 'course_id': course.id,
            'section_id': section.id, 'lesson_type': lesson_type,
        }
        values.update(lesson_values)
        lesson = self.env['lms.lesson'].create(values)
        return course, section, lesson

    def _publish(self, course):
        course.with_user(self.reviewer).action_submit_for_review()
        course.with_user(self.reviewer).action_publish()

    def test_review_requires_assigned_reviewer_and_published_content_is_frozen(self):
        course, section, lesson = self._course(html_content='<p>Read this.</p>')
        course.with_user(self.reviewer).action_submit_for_review()
        with self.assertRaises(UserError):
            course.with_user(self.reviewer).write({
                'state': 'published', 'description': '<p>Unreviewed change.</p>',
            })
        with self.assertRaises(AccessError):
            course.with_user(self.other_manager).write({'state': 'published'})
        course.with_user(self.reviewer).action_publish()

        with self.assertRaises(UserError):
            course.with_user(self.reviewer).write({'description': '<p>Changed.</p>'})
        with self.assertRaises(UserError):
            course.with_user(self.reviewer).write({'state': 'review'})
        with self.assertRaises(UserError):
            section.with_user(self.reviewer).write({'name': 'Changed section'})
        with self.assertRaises(UserError):
            lesson.with_user(self.reviewer).write({'html_content': '<p>Changed lesson.</p>'})
        with self.assertRaises(UserError):
            self.env['lms.lesson'].with_user(self.reviewer).create({
                'name': 'Unexpected lesson', 'course_id': course.id,
                'lesson_type': 'text', 'html_content': '<p>New.</p>',
            })
        with self.assertRaises(UserError):
            lesson.with_user(self.reviewer).unlink()

        revision = self.env['lms.course'].browse(
            course.with_user(self.reviewer).action_create_new_version()['res_id'])
        self.assertEqual(revision.state, 'draft')
        self.assertEqual(revision.previous_version_id, course)
        revision.with_user(self.reviewer).write({'description': '<p>Revised material.</p>'})
        self.assertEqual(len(revision.lesson_ids), 1)

    def test_publication_rejects_empty_video_then_accepts_completed_draft(self):
        course, _, lesson = self._course(name='Media review', lesson_type='video')
        course.with_user(self.reviewer).action_submit_for_review()
        with self.assertRaisesRegex(UserError, 'Upload a video'):
            course.with_user(self.reviewer).action_publish()
        course.with_user(self.reviewer).action_return_draft()
        lesson.write({
            'video_file': b'AAAAIGZ0eXBpc29t',
            'video_duration_seconds': 60,
        })
        self._publish(course)
        self.assertEqual(course.state, 'published')

    def test_publication_requires_allowlisted_https_video_url(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'learning_management.media_allowed_hosts', 'media.bank.internal'
        )
        course, _, lesson = self._course(
            name='Internal media review', lesson_type='video',
            video_source_type='url', video_url='https://other.example/video.mp4',
            video_duration_seconds=90,
        )
        course.with_user(self.reviewer).action_submit_for_review()
        with self.assertRaisesRegex(UserError, 'approved HTTPS internal media host'):
            course.with_user(self.reviewer).action_publish()

        course.with_user(self.reviewer).action_return_draft()
        lesson.video_url = 'http://media.bank.internal/video.mp4'
        course.with_user(self.reviewer).action_submit_for_review()
        with self.assertRaisesRegex(UserError, 'approved HTTPS internal media host'):
            course.with_user(self.reviewer).action_publish()

        course.with_user(self.reviewer).action_return_draft()
        lesson.video_url = 'https://media.bank.internal/video.mp4'
        self._publish(course)
        self.assertEqual(course.state, 'published')

    def test_direct_publish_retires_predecessor_and_rejects_competing_revision(self):
        original, _, _ = self._course(name='Revision source', html_content='<p>Read.</p>')
        self._publish(original)
        first = self.env['lms.course'].browse(
            original.with_user(self.reviewer).action_create_new_version()['res_id'])
        second = self.env['lms.course'].browse(
            original.with_user(self.reviewer).action_create_new_version()['res_id'])
        first.with_user(self.reviewer).action_submit_for_review()
        second.with_user(self.reviewer).action_submit_for_review()

        first.with_user(self.reviewer).write({'state': 'published'})
        self.assertEqual(first.state, 'published')
        self.assertTrue(first.is_latest_version)
        self.assertEqual(original.state, 'archived')
        self.assertFalse(original.is_latest_version)
        with self.assertRaisesRegex(UserError, 'Another revision'):
            second.with_user(self.reviewer).write({'state': 'published'})
        self.assertEqual(second.state, 'review')

    def test_assessment_bank_is_frozen_and_revision_clones_questions(self):
        course, _, _ = self._course(name='Assessed course', html_content='<p>Read.</p>')
        question = self.env['lms.question'].create({
            'name': 'Question one', 'question_text': '<p>Original question?</p>',
            'question_type': 'single_choice', 'points': 5,
        })
        correct = self.env['lms.question.answer'].create({
            'question_id': question.id, 'answer_text': 'Correct', 'is_correct': True,
        })
        self.env['lms.question.answer'].create({
            'question_id': question.id, 'answer_text': 'Incorrect', 'is_correct': False,
        })
        assessment = self.env['lms.assessment'].create({
            'name': 'Final exam', 'course_id': course.id,
            'assessment_type': 'post_course', 'use_random_pool': False,
            'fixed_question_ids': [(4, question.id)],
            'instructions': '<p>Choose one answer.</p>',
        })
        course.write({'has_post_assessment': True, 'post_assessment_id': assessment.id})
        self._publish(course)

        with self.assertRaises(UserError):
            assessment.with_user(self.reviewer).write({'pass_score_percentage': 90})
        with self.assertRaises(UserError):
            question.with_user(self.reviewer).write({'points': 10})
        with self.assertRaises(UserError):
            correct.with_user(self.reviewer).write({'is_correct': False})

        revision = self.env['lms.course'].browse(
            course.with_user(self.reviewer).action_create_new_version()['res_id'])
        revised_question = revision.post_assessment_id.fixed_question_ids
        self.assertEqual(len(revised_question), 1)
        self.assertNotEqual(revised_question, question)
        self.assertEqual(len(revised_question.answer_ids), 2)
        revised_question.with_user(self.reviewer).write({'points': 10})

    def test_attempt_grades_from_start_snapshot(self):
        course, _, _ = self._course(name='Snapshot exam', html_content='<p>Read.</p>')
        question = self.env['lms.question'].create({
            'name': 'Stable question', 'question_text': '<p>Original text?</p>',
            'question_type': 'single_choice', 'points': 5,
        })
        original_answer = self.env['lms.question.answer'].create({
            'question_id': question.id, 'answer_text': 'Yes', 'is_correct': True,
        })
        other_answer = self.env['lms.question.answer'].create({
            'question_id': question.id, 'answer_text': 'No', 'is_correct': False,
        })
        assessment = self.env['lms.assessment'].create({
            'name': 'Stable exam', 'course_id': course.id,
            'use_random_pool': False, 'fixed_question_ids': [(4, question.id)],
            'instructions': '<p>Choose.</p>', 'duration_minutes': 30,
            'pass_score_percentage': 70,
        })
        session = self.env['lms.exam.session'].create({
            'assessment_id': assessment.id, 'employee_id': self.employee.id,
        })
        session._generate_question_lines()
        line = session.line_ids
        deadline = session.deadline_time
        self.assertEqual(line.question_text, '<p>Original text?</p>')
        with self.assertRaises(UserError):
            question.with_user(self.reviewer).write({'points': 10})
        line.write({'selected_answer_ids': [(4, original_answer.id)]})

        # A privileged data repair may edit the source, but a started attempt
        # still grades against the recorded policy and answer key.
        assessment.write({'pass_score_percentage': 101, 'duration_minutes': 1})
        question.write({'points': 100, 'question_text': '<p>Changed text?</p>'})
        original_answer.write({'is_correct': False})
        other_answer.write({'is_correct': True})
        self.env.flush_all()
        session.invalidate_recordset(['deadline_time'])
        self.assertEqual(session.deadline_time, deadline)
        self.assertEqual(line.question_text, '<p>Original text?</p>')
        session.action_submit_and_grade()
        self.assertTrue(session.is_passed)
        self.assertEqual(session.max_points, 5)
        self.assertEqual(session.score_percentage, 100)

    def test_existing_enrollment_finishes_superseded_version(self):
        course, _, lesson = self._course(
            name='Versioned training', html_content='<p>Learn this version.</p>')
        question = self.env['lms.question'].create({
            'name': 'Version question', 'question_text': '<p>Choose yes.</p>',
            'question_type': 'single_choice', 'points': 5,
        })
        answer = self.env['lms.question.answer'].create({
            'question_id': question.id, 'answer_text': 'Yes', 'is_correct': True,
        })
        self.env['lms.question.answer'].create({
            'question_id': question.id, 'answer_text': 'No', 'is_correct': False,
        })
        assessment = self.env['lms.assessment'].create({
            'name': 'Version exam', 'course_id': course.id,
            'assessment_type': 'post_course', 'use_random_pool': False,
            'fixed_question_ids': [(4, question.id)],
            'instructions': '<p>Select an answer.</p>',
        })
        course.write({
            'has_post_assessment': True,
            'post_assessment_id': assessment.id,
            'is_mandatory': True,
        })
        self._publish(course)
        enrollment = self.env['lms.enrollment'].create({
            'employee_id': self.learner_employee.id, 'course_id': course.id,
        })

        revision = self.env['lms.course'].browse(
            course.with_user(self.reviewer).action_create_new_version()['res_id'])
        self._publish(revision)
        self.assertEqual(course.state, 'archived')
        self.assertFalse(course.is_latest_version)
        self.assertTrue(self.env['lms.course'].with_user(self.learner).search([('id', '=', course.id)]))
        self.assertTrue(self.env['lms.lesson'].with_user(self.learner).search([('id', '=', lesson.id)]))

        enrollment.with_user(self.learner).action_start_course()
        progress = enrollment.lesson_progress_ids.with_user(self.learner)
        progress.action_open_lesson()
        progress.mark_completed()
        allowed, _, selected = LmsController()._check_video_access(
            lesson.id, env=self.env['lms.lesson'].with_user(self.learner).env)
        self.assertTrue(allowed)
        self.assertEqual(selected, enrollment)

        action = enrollment.with_user(self.learner).action_start_post_assessment()
        session = self.env['lms.exam.session'].browse(action['res_id'])
        session.line_ids.with_user(self.learner).write({
            'selected_answer_ids': [(4, answer.id)],
        })
        session.with_user(self.learner).action_submit_and_grade()
        self.assertEqual(enrollment.state, 'completed')
        self.assertEqual(enrollment.certificate_id.course_id, course)

        with self.assertRaisesRegex(UserError, 'New enrollment requires'):
            self.env['lms.enrollment'].sudo().create({
                'employee_id': self.employee.id, 'course_id': course.id,
            })
        with self.assertRaisesRegex(UserError, 'original learner and course version'):
            enrollment.with_user(self.reviewer).write({'course_id': revision.id})
        campaign = self.env['lms.course.assignment'].create({
            'name': 'Retired version assignment', 'course_id': course.id,
            'assignment_type': 'individual',
            'employee_ids': [(4, self.employee.id)],
            'due_date': fields.Date.add(fields.Date.today(), days=7),
        })
        with self.assertRaisesRegex(UserError, 'Only active, latest published'):
            campaign.with_user(self.reviewer).action_execute_assignment()

        certificate = enrollment.certificate_id
        certificate.write({'expiry_date': fields.Date.add(fields.Date.today(), days=-1)})
        self.env['lms.certificate'].cron_check_certificate_expiry()
        renewal = self.env['lms.enrollment'].search([
            ('employee_id', '=', self.learner_employee.id),
            ('course_id', '=', revision.id),
        ], limit=1)
        self.assertEqual(renewal.state, 'enrolled')
        self.assertEqual(certificate.state, 'expired')

    def test_compliance_rolls_up_versions_until_new_mandatory_obligation(self):
        original, _, _ = self._course(
            name='Versioned compliance', html_content='<p>Read and acknowledge.</p>')
        original.is_mandatory = True
        self._publish(original)
        today = fields.Date.today()
        prior_enrollment = self.env['lms.enrollment'].create({
            'employee_id': self.learner_employee.id,
            'course_id': original.id,
            'is_mandatory': True,
            'state': 'completed',
            'completion_date': today,
        })
        prior_certificate = self.env['lms.certificate'].create({
            'name': 'VERSIONED-COMPLIANCE-1',
            'employee_id': self.learner_employee.id,
            'course_id': original.id,
            'enrollment_id': prior_enrollment.id,
            'issue_date': today,
            'expiry_date': today + timedelta(days=30),
            'state': 'valid',
        })
        prior_enrollment.certificate_id = prior_certificate

        revision = self.env['lms.course'].browse(
            original.with_user(self.reviewer).action_create_new_version()['res_id'])
        self._publish(revision)
        self.assertEqual(original.state, 'archived')
        self.env.flush_all()
        report_model = self.env['lms.branch.compliance.report']
        self.assertFalse(report_model.search([('course_id', '=', original.id)]))
        report = report_model.search([('course_id', '=', revision.id)])
        self.assertEqual(len(report), 1)
        self.assertEqual(report.total_assigned, 1)
        self.assertEqual(report.total_completed, 1)
        self.assertEqual(report.compliance_percentage, 100.0)

        # The earlier certificate remains evidence only while it is valid.
        prior_certificate.expiry_date = today - timedelta(days=1)
        self.env.flush_all()
        report_model.invalidate_model()
        report = report_model.search([('course_id', '=', revision.id)])
        self.assertEqual(report.total_completed, 0)
        prior_certificate.expiry_date = today + timedelta(days=30)

        # A mandatory enrollment on the approved revision is a new obligation.
        renewal = self.env['lms.enrollment'].create({
            'employee_id': self.learner_employee.id,
            'course_id': revision.id,
            'is_mandatory': True,
            'due_date': today - timedelta(days=1),
            'state': 'in_progress',
        })
        self.env.flush_all()
        report_model.invalidate_model()
        report = report_model.search([('course_id', '=', revision.id)])
        self.assertEqual(report.total_assigned, 1)
        self.assertEqual(report.total_completed, 0)
        self.assertEqual(report.total_overdue, 1)
        self.assertFalse(report_model.search([('course_id', '=', original.id)]))

        renewal.write({'state': 'completed', 'completion_date': today})
        current_certificate = self.env['lms.certificate'].create({
            'name': 'VERSIONED-COMPLIANCE-2',
            'employee_id': self.learner_employee.id,
            'course_id': revision.id,
            'enrollment_id': renewal.id,
            'issue_date': today,
            'expiry_date': today + timedelta(days=365),
            'state': 'valid',
        })
        renewal.certificate_id = current_certificate
        self.env.flush_all()
        report_model.invalidate_model()
        report = report_model.search([('course_id', '=', revision.id)])
        self.assertEqual(report.total_completed, 1)
        self.assertEqual(report.total_overdue, 0)
