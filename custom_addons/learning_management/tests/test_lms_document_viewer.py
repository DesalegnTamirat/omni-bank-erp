# -*- coding: utf-8 -*-
import base64
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError
from odoo.addons.learning_management.controllers.main import LmsController


class TestLmsDocumentViewer(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category = cls.env['lms.category'].create({'name': 'Document Banking Tech', 'code': 'DOC_TECH'})
        cls.instructor_user = cls.env['res.users'].create({
            'name': 'Doc Instructor',
            'login': 'doc_instructor@bunna.et',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('learning_management.group_lms_instructor').id])],
        })
        cls.instructor_emp = cls.env['hr.employee'].create({
            'name': 'Doc Instructor Employee',
            'user_id': cls.instructor_user.id,
        })
        cls.learner_user = cls.env['res.users'].create({
            'name': 'Doc Learner',
            'login': 'doc_learner@bunna.et',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('learning_management.group_lms_learner').id])],
        })
        cls.learner_emp = cls.env['hr.employee'].create({
            'name': 'Doc Learner Employee',
            'user_id': cls.learner_user.id,
        })

        # Sample PDF binary
        sample_pdf = b'%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/Parent 2 0 R>>endobj\nxref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000052 00000 n\n0000000102 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n149\n%%EOF\n'

        cls.course = cls.env['lms.course'].create({
            'name': 'Python & Document Banking Mastery',
            'category_id': cls.category.id,
            'instructor_id': cls.instructor_emp.id,
            'description': '<p>Comprehensive banking tech syllabus.</p>',
            'has_post_assessment': False,
            'is_mandatory': False,
        })

        cls.video_lesson = cls.env['lms.lesson'].create({
            'name': 'Video Introduction',
            'course_id': cls.course.id,
            'sequence': 10,
            'lesson_type': 'video',
            'video_source_type': 'url',
            'video_url': 'https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4',
            'video_duration_seconds': 10,
            'min_watch_percentage': 85.0,
            'is_mandatory': False,
        })

        cls.doc_lesson = cls.env['lms.lesson'].create({
            'name': 'Financial Python Playbook (PDF)',
            'course_id': cls.course.id,
            'sequence': 20,
            'lesson_type': 'document',
            'document_file': base64.b64encode(sample_pdf),
            'document_filename': 'playbook.pdf',
            'duration_minutes': 15,
            'is_mandatory': False,
        })

        cls.text_lesson = cls.env['lms.lesson'].create({
            'name': 'Python Architecture Best Practices (Guide)',
            'course_id': cls.course.id,
            'sequence': 30,
            'lesson_type': 'text',
            'html_content': '<h2>Banking Code Guidelines</h2><p>Always use Decimal for currency.</p>',
            'duration_minutes': 10,
            'is_mandatory': False,
        })

        cls.course.sudo().write({'state': 'review'})
        cls.course.sudo().write({'state': 'published'})

        cls.enrollment = cls.env['lms.enrollment'].create({
            'course_id': cls.course.id,
            'employee_id': cls.learner_emp.id,
        })
        cls.enrollment.action_start_course()

    def test_navigation_target_is_self_same_tab(self):
        """Video and document lessons must open in current tab (target: self) to prevent duplicate tabs."""
        prog_video = self.enrollment.lesson_progress_ids.filtered(lambda p: p.lesson_id == self.video_lesson)
        prog_doc = self.enrollment.lesson_progress_ids.filtered(lambda p: p.lesson_id == self.doc_lesson)

        # Video lesson action
        action_video = prog_video.with_user(self.learner_user).action_open_lesson()
        self.assertEqual(action_video['type'], 'ir.actions.act_url')
        self.assertEqual(action_video.get('target'), 'self', "Video lesson must navigate in the same tab")
        self.assertIn(f"/lms/video/{self.video_lesson.id}/player", action_video['url'])

        # Document lesson action
        action_doc = prog_doc.with_user(self.learner_user).action_open_lesson()
        self.assertEqual(action_doc['type'], 'ir.actions.act_url')
        self.assertEqual(action_doc.get('target'), 'self', "Document lesson must navigate in the same tab")
        self.assertEqual(action_doc['url'], f"/lms/document/{self.doc_lesson.id}/viewer")

        # Lesson action_open_document directly
        direct_action = self.doc_lesson.action_open_document()
        self.assertEqual(direct_action.get('target'), 'self')
        self.assertEqual(direct_action['url'], f"/lms/document/{self.doc_lesson.id}/viewer")

    def test_document_completion_flow(self):
        """Reviewing document and clicking complete sets completed state and increments course progress."""
        prog_doc = self.enrollment.lesson_progress_ids.filtered(lambda p: p.lesson_id == self.doc_lesson)
        self.assertEqual(prog_doc.state, 'not_started')

        # Opening lesson records opened_at
        prog_doc.with_user(self.learner_user).action_open_lesson()
        self.assertTrue(prog_doc.opened_at)

        # Mark completed via confirmation
        prog_doc.with_user(self.learner_user).mark_completed()
        self.assertEqual(prog_doc.state, 'completed')
        self.assertEqual(prog_doc.completion_method, 'learner_acknowledgment')
        self.assertTrue(prog_doc.date_completed)
        self.assertTrue(prog_doc.acknowledged_at)

    def test_unopened_document_cannot_be_completed(self):
        """A document that was never opened cannot be marked as reviewed without manager override."""
        prog_doc = self.enrollment.lesson_progress_ids.filtered(lambda p: p.lesson_id == self.doc_lesson)
        prog_doc.sudo().write({'opened_at': False, 'state': 'not_started'})
        with self.assertRaises(UserError):
            prog_doc.with_user(self.learner_user).mark_completed()

    def test_text_lesson_navigation_and_action_open_text(self):
        """Text lessons must navigate to /lms/text/<id>/viewer with target='self'."""
        prog_text = self.enrollment.lesson_progress_ids.filtered(lambda p: p.lesson_id == self.text_lesson)
        action_text = prog_text.with_user(self.learner_user).action_open_lesson()
        self.assertEqual(action_text['type'], 'ir.actions.act_url')
        self.assertEqual(action_text.get('target'), 'self', "Text lesson must navigate in the same tab")
        self.assertEqual(action_text['url'], f"/lms/text/{self.text_lesson.id}/viewer")

        # Direct model action
        direct_action = self.text_lesson.action_open_text()
        self.assertEqual(direct_action.get('target'), 'self')
        self.assertEqual(direct_action['url'], f"/lms/text/{self.text_lesson.id}/viewer")

    def test_text_lesson_completion_flow(self):
        """Reviewing text article and clicking complete records acknowledgment and completion."""
        prog_text = self.enrollment.lesson_progress_ids.filtered(lambda p: p.lesson_id == self.text_lesson)
        self.assertEqual(prog_text.state, 'not_started')

        # Opening lesson records opened_at
        prog_text.with_user(self.learner_user).action_open_lesson()
        self.assertTrue(prog_text.opened_at)

        # Mark completed via acknowledgment
        prog_text.with_user(self.learner_user).mark_completed()
        self.assertEqual(prog_text.state, 'completed')
        self.assertEqual(prog_text.completion_method, 'learner_acknowledgment')
        self.assertTrue(prog_text.date_completed)
        self.assertTrue(prog_text.acknowledged_at)

    def test_lesson_navigation_resolution(self):
        """Previous and next buttons correctly link the curriculum sequence."""
        controller = LmsController()
        # For middle lesson (doc_lesson), previous is video_lesson, next is text_lesson
        nav_doc = controller._get_lesson_navigation(self.doc_lesson, enrollment=self.enrollment, is_staff=True)
        self.assertEqual(nav_doc['prev_lesson'].id, self.video_lesson.id)
        self.assertEqual(nav_doc['prev_url'], f"/lms/video/{self.video_lesson.id}/player")
        self.assertEqual(nav_doc['next_lesson'].id, self.text_lesson.id)
        self.assertEqual(nav_doc['next_url'], f"/lms/text/{self.text_lesson.id}/viewer")
        self.assertFalse(nav_doc['next_locked'])

        # For first lesson (video_lesson), previous is None
        nav_video = controller._get_lesson_navigation(self.video_lesson, enrollment=self.enrollment, is_staff=True)
        self.assertIsNone(nav_video['prev_lesson'])
        self.assertEqual(nav_video['next_lesson'].id, self.doc_lesson.id)

        # For last lesson (text_lesson), next is None
        nav_text = controller._get_lesson_navigation(self.text_lesson, enrollment=self.enrollment, is_staff=True)
        self.assertEqual(nav_text['prev_lesson'].id, self.doc_lesson.id)
        self.assertIsNone(nav_text['next_lesson'])
