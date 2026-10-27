# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase


class TestLmsRecertification(TransactionCase):

    def setUp(self):
        super().setUp()
        self.learner = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Renewal Learner',
            'login': 'lms_renewal_learner@example.test',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('learning_management.group_lms_learner').id,
            ])],
        })
        self.employee = self.env['hr.employee'].create({
            'name': 'Renewal Learner', 'user_id': self.learner.id,
        })
        category = self.env['lms.category'].create({
            'name': 'Renewal Compliance', 'code': 'RENEWAL-COMPLIANCE',
        })
        self.course = self.env['lms.course'].create({
            'name': 'Annual Compliance Renewal',
            'category_id': category.id,
            'description': '<p>Annual compliance training.</p>',
            'instructor_id': self.employee.id,
            'is_mandatory': True,
            'has_post_assessment': True,
            'issue_certificate': True,
            'state': 'published',
        })
        self.lesson = self.env['lms.lesson'].create({
            'name': 'Compliance guide', 'course_id': self.course.id,
            'lesson_type': 'text', 'html_content': '<p>Read this guide.</p>',
        })
        self.enrollment = self.env['lms.enrollment'].create({
            'employee_id': self.employee.id, 'course_id': self.course.id,
            'is_mandatory': True,
        })

    def _completed_with_certificate(self, expiry_date):
        today = fields.Date.context_today(self.enrollment)
        self.enrollment.write({
            'state': 'completed', 'completion_date': today,
        })
        certificate = self.env['lms.certificate'].create({
            'name': 'RENEWAL-001',
            'employee_id': self.employee.id,
            'course_id': self.course.id,
            'enrollment_id': self.enrollment.id,
            'issue_date': today - timedelta(days=365),
            'expiry_date': expiry_date,
            'state': 'valid',
        })
        self.enrollment.certificate_id = certificate
        return certificate

    def test_expiry_creates_one_new_attempt_and_keeps_history(self):
        today = fields.Date.context_today(self.enrollment)
        certificate = self._completed_with_certificate(today - timedelta(days=1))

        certificate.cron_check_certificate_expiry()
        attempts = self.env['lms.enrollment'].search([
            ('employee_id', '=', self.employee.id),
            ('course_id', '=', self.course.id),
        ], order='attempt_number')
        self.assertEqual(attempts.mapped('attempt_number'), [1, 2])
        self.assertEqual(attempts[0].state, 'completed')
        self.assertEqual(attempts[0].certificate_id, certificate)
        self.assertEqual(attempts[1].state, 'enrolled')
        self.assertEqual(certificate.state, 'expired')

        certificate.cron_check_certificate_expiry()
        self.assertEqual(self.env['lms.enrollment'].search_count([
            ('employee_id', '=', self.employee.id),
            ('course_id', '=', self.course.id),
        ]), 2)
        self.assertEqual(self.enrollment._create_recertification_enrollment(), attempts[1])
        with self.assertRaises(UserError):
            self.env['lms.enrollment'].create({
                'employee_id': self.employee.id, 'course_id': self.course.id,
            })

    def test_early_manual_renewal_gets_deadline_and_expiry_repairs_missing_date(self):
        today = fields.Date.context_today(self.enrollment)
        expiry = today + timedelta(days=15)
        certificate = self._completed_with_certificate(expiry)

        action = self.enrollment.with_user(self.learner).action_create_recertification()
        renewal = self.env['lms.enrollment'].browse(action['res_id'])
        self.assertTrue(renewal.is_mandatory)
        self.assertEqual(renewal.due_date, expiry + timedelta(days=30))

        # Reconcile an older active attempt that was created without a deadline.
        renewal.due_date = False
        certificate.expiry_date = today - timedelta(days=1)
        certificate.cron_check_certificate_expiry()
        self.assertEqual(renewal.due_date, today + timedelta(days=30))
        self.assertEqual(self.env['lms.enrollment'].search_count([
            ('employee_id', '=', self.employee.id),
            ('course_id', '=', self.course.id),
        ]), 2)

    def test_manager_cannot_mint_change_or_delete_certification_evidence(self):
        manager = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Certificate Manager',
            'login': 'lms_certificate_manager@example.test',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('learning_management.group_lms_manager').id,
            ])],
        })
        today = fields.Date.context_today(self.enrollment)
        certificate = self._completed_with_certificate(today + timedelta(days=30))
        with self.assertRaises(AccessError):
            self.env['lms.certificate'].with_user(manager).create({
                'name': 'FORGED',
                'employee_id': self.employee.id,
                'course_id': self.course.id,
                'state': 'valid',
            })
        with self.assertRaises(AccessError):
            certificate.with_user(manager).write({'state': 'revoked'})
        with self.assertRaises(AccessError):
            certificate.with_user(manager).unlink()
        self.assertEqual(certificate.state, 'valid')

    def test_manager_revocation_requires_reason_and_preserves_history(self):
        manager = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Revocation Manager',
            'login': 'lms_revocation_manager@example.test',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('learning_management.group_lms_manager').id,
            ])],
        })
        certificate = self._completed_with_certificate(
            fields.Date.context_today(self.enrollment) + timedelta(days=30)
        )
        with self.assertRaises(AccessError):
            certificate.with_user(self.learner).action_revoke('Unsupported correction')
        with self.assertRaises(UserError):
            certificate.with_user(manager).action_revoke('  ')
        self.assertEqual(certificate.state, 'valid')

        action = certificate.with_user(manager).action_open_revoke_wizard()
        self.assertEqual(action['res_model'], 'lms.certificate.revoke.wizard')
        wizard = self.env['lms.certificate.revoke.wizard'].with_user(manager).create({
            'certificate_id': certificate.id,
            'reason': 'Duplicate identity evidence',
        })
        wizard.action_confirm_revoke()
        certificate.invalidate_recordset()
        self.assertEqual(certificate.state, 'revoked')
        self.assertEqual(certificate.revocation_reason, 'Duplicate identity evidence')
        self.assertEqual(certificate.revoked_by_id, manager)
        self.assertTrue(certificate.revoked_at)
        self.assertTrue(any('Duplicate identity evidence' in (msg.body or '')
                            for msg in certificate.message_ids))
        with self.assertRaises(UserError):
            certificate.with_user(manager).action_revoke('Second revocation')

    def test_expired_and_revoked_certificate_remove_compliance(self):
        today = fields.Date.context_today(self.enrollment)
        certificate = self._completed_with_certificate(today + timedelta(days=30))
        report = self.env['lms.branch.compliance.report'].search([
            ('course_id', '=', self.course.id),
        ])
        self.assertEqual(report.total_assigned, 1)
        self.assertEqual(report.total_completed, 1)

        certificate.state = 'revoked'
        certificate.flush_recordset(['state'])
        report.invalidate_recordset()
        self.assertEqual(report.total_completed, 0)

        certificate.write({'state': 'valid', 'expiry_date': today - timedelta(days=1)})
        certificate.flush_recordset(['state', 'expiry_date'])
        report.invalidate_recordset()
        self.assertEqual(report.total_completed, 0)

    def test_text_completion_records_learner_acknowledgment(self):
        progress = self.enrollment.lesson_progress_ids.with_user(self.learner)
        self.assertEqual(progress.lesson_type, 'text')
        with self.assertRaisesRegex(UserError, 'Open the lesson'):
            progress.mark_completed()
        progress.action_open_lesson()
        self.assertTrue(progress.opened_at)
        progress.mark_completed()
        self.assertEqual(progress.completion_method, 'learner_acknowledgment')
        self.assertTrue(progress.acknowledged_at)
        self.assertTrue(progress.date_completed)

    def test_renewal_gets_fresh_exam_allowance_and_certificate(self):
        assessment = self.env['lms.assessment'].create({
            'name': 'Annual compliance final',
            'course_id': self.course.id,
            'assessment_type': 'post_course',
            'instructions': '<p>Choose the correct answer.</p>',
            'use_random_pool': False,
            'is_timed': False,
            'max_attempts': 1,
            'cooldown_hours': 72,
        })
        question = self.env['lms.question'].create({
            'name': 'Annual compliance question',
            'question_text': '<p>Which answer is correct?</p>',
            'question_type': 'single_choice',
        })
        correct = self.env['lms.question.answer'].create({
            'question_id': question.id,
            'answer_text': 'Correct',
            'is_correct': True,
        })
        self.env['lms.question.answer'].create({
            'question_id': question.id,
            'answer_text': 'Incorrect',
        })
        assessment.fixed_question_ids = [(4, question.id)]
        self.course.post_assessment_id = assessment

        first_progress = self.enrollment.lesson_progress_ids.with_user(self.learner)
        first_progress.action_open_lesson()
        first_progress.mark_completed()
        first_action = self.enrollment.with_user(self.learner).action_start_post_assessment()
        first_session = self.env['lms.exam.session'].browse(first_action['res_id'])
        first_session.line_ids.with_user(self.learner).write({
            'selected_answer_ids': [(6, 0, correct.ids)],
        })
        first_session.with_user(self.learner).action_submit_and_grade()
        self.assertEqual(first_session.state, 'passed')
        self.assertEqual(self.enrollment.state, 'completed')
        first_certificate = self.enrollment.certificate_id
        self.assertTrue(first_certificate)

        today = fields.Date.context_today(self.enrollment)
        first_certificate.expiry_date = today - timedelta(days=1)
        first_certificate.cron_check_certificate_expiry()
        renewal = self.env['lms.enrollment'].search([
            ('employee_id', '=', self.employee.id),
            ('course_id', '=', self.course.id),
            ('attempt_number', '=', 2),
        ], limit=1)
        self.assertTrue(renewal)

        renewal_progress = renewal.lesson_progress_ids.with_user(self.learner)
        renewal_progress.action_open_lesson()
        renewal_progress.mark_completed()
        renewal_action = renewal.with_user(self.learner).action_start_post_assessment()
        renewal_session = self.env['lms.exam.session'].browse(renewal_action['res_id'])
        self.assertNotEqual(renewal_session, first_session)
        self.assertEqual(renewal_session.attempt_number, 1)
        renewal_session.line_ids.with_user(self.learner).write({
            'selected_answer_ids': [(6, 0, correct.ids)],
        })
        renewal_session.with_user(self.learner).action_submit_and_grade()
        self.assertEqual(renewal.state, 'completed')
        self.assertTrue(renewal.certificate_id)
        self.assertNotEqual(renewal.certificate_id, first_certificate)
