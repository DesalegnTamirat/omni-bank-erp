# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestEdsLmsRoutingFeedback(TransactionCase):

    def test_nightly_sync_waits_for_lms_publication(self):
        if not self.env.registry.get('lms.enrollment'):
            self.skipTest('Learning Management is not installed')

        manager = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'EDS LMS Nightly Owner',
            'login': 'eds_lms_nightly_owner@example.test',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('employee_development_system.group_eds_manager').id,
            ])],
        })
        employee = self.env['hr.employee'].create({
            'name': 'EDS LMS Nightly Owner', 'user_id': manager.id,
        })
        eds_course = self.env['eds.course'].with_user(manager).create({
            'name': 'Nightly Digital Course',
            'description': 'Reviewed learning material.',
        })
        today = fields.Date.context_today(self.env['eds.session'])
        session = self.env['eds.session'].create({
            'course_id': eds_course.id,
            'date_start': today + timedelta(days=5),
            'date_end': today + timedelta(days=6),
            'capacity': 10,
        })
        participant = self.env['eds.enrollment'].create({
            'session_id': session.id,
            'employee_id': employee.id,
            'state': 'enrolled',
        })
        routing = self.env['eds.lms.routing'].create({
            'course_id': eds_course.id,
            'session_id': session.id,
            'delivery_mode': 'e_learning',
        })

        routing.with_user(manager).action_sync_to_lms()
        self.assertEqual(routing.sync_state, 'synced', routing.sync_error)
        lms_course = self.env['lms.course'].sudo().browse(int(routing.lms_ref))
        self.assertEqual(lms_course.state, 'draft')
        self.assertFalse(participant.lms_enrollment_ref)

        lms_course.write({'has_post_assessment': False})
        self.env['lms.lesson'].create({
            'name': 'Reviewed guide', 'course_id': lms_course.id,
            'lesson_type': 'text', 'html_content': '<p>Read this guide.</p>',
        })
        lms_course.write({'state': 'review'})
        lms_course.write({'state': 'published'})

        routing.cron_sync_lms()
        self.assertTrue(participant.lms_enrollment_ref)
        self.assertEqual(participant.lms_completion_state, 'enrolled')
        self.assertEqual(routing.lms_completion_pct, 0.0)
        first_ref = participant.lms_enrollment_ref
        routing.cron_sync_lms()
        self.assertEqual(participant.lms_enrollment_ref, first_ref)
        self.assertEqual(self.env['lms.enrollment'].search_count([
            ('employee_id', '=', employee.id), ('course_id', '=', lms_course.id),
        ]), 1)

    def test_session_participant_feedback_is_idempotent(self):
        if not self.env.registry.get('lms.enrollment'):
            self.skipTest('Learning Management is not installed')

        employee = self.env['hr.employee'].create({'name': 'EDS LMS Participant'})
        eds_course = self.env['eds.course'].create({
            'name': 'EDS Recurring Digital Training',
        })
        curriculum = self.env['eds.curriculum'].create({
            'course_id': eds_course.id,
            'learning_objectives': 'Understand the current procedure.',
        })
        today = fields.Date.context_today(self.env['eds.session'])
        session = self.env['eds.session'].create({
            'course_id': eds_course.id,
            'date_start': today + timedelta(days=5),
            'date_end': today + timedelta(days=6),
            'capacity': 10,
        })
        participant = self.env['eds.enrollment'].create({
            'session_id': session.id,
            'employee_id': employee.id,
            'state': 'enrolled',
        })
        category = self.env['lms.category'].create({
            'name': 'EDS Routing Test', 'code': 'EDS-ROUTING-TEST',
        })
        lms_course = self.env['lms.course'].create({
            'name': 'EDS Recurring Digital Training',
            'category_id': category.id,
            'description': '<p>Digital training.</p>',
            'instructor_id': employee.id,
            'has_post_assessment': False,
        })
        self.env['lms.lesson'].create({
            'name': 'Recurring training guide', 'course_id': lms_course.id,
            'lesson_type': 'text', 'html_content': '<p>Read this guide.</p>',
        })
        lms_course.write({'state': 'review'})
        lms_course.write({'state': 'published'})
        routing = self.env['eds.lms.routing'].create({
            'course_id': eds_course.id,
            'curriculum_id': curriculum.id,
            'session_id': session.id,
            'lms_ref': str(lms_course.id),
            'sync_state': 'synced',
        })

        self.assertEqual(routing.curriculum_id, curriculum)
        self.assertEqual(routing._sync_lms_enrollments(lms_course), 1)
        self.assertEqual(routing._sync_lms_enrollments(lms_course), 0)
        lms_enrollment = self.env['lms.enrollment'].browse(int(participant.lms_enrollment_ref))
        self.assertEqual(lms_enrollment.employee_id, employee)

        lms_enrollment.write({'state': 'completed', 'completion_date': today})
        routing.action_reconcile_lms()
        self.assertEqual(participant.state, 'enrolled')
        self.assertEqual(participant.lms_completion_state, 'completed')
        self.assertEqual(participant.lms_completion_date, today)
        self.assertEqual(routing.lms_completion_pct, 100.0)

    def test_nightly_sync_routes_new_participants_to_latest_version(self):
        if not self.env.registry.get('lms.enrollment'):
            self.skipTest('Learning Management is not installed')

        original_employee = self.env['hr.employee'].create({'name': 'Original LMS Learner'})
        new_employee = self.env['hr.employee'].create({'name': 'New LMS Learner'})
        eds_course = self.env['eds.course'].create({'name': 'Versioned EDS Course'})
        today = fields.Date.context_today(self.env['eds.session'])
        session = self.env['eds.session'].create({
            'course_id': eds_course.id,
            'date_start': today + timedelta(days=5),
            'date_end': today + timedelta(days=6),
            'capacity': 10,
        })
        original_participant = self.env['eds.enrollment'].create({
            'session_id': session.id,
            'employee_id': original_employee.id,
            'state': 'enrolled',
        })
        category = self.env['lms.category'].create({
            'name': 'Versioned EDS Routing', 'code': 'EDS-VERSION-ROUTING',
        })
        original_course = self.env['lms.course'].create({
            'name': 'Versioned EDS Course',
            'category_id': category.id,
            'description': '<p>Approved learning guide.</p>',
            'instructor_id': original_employee.id,
            'has_post_assessment': False,
        })
        self.env['lms.lesson'].create({
            'name': 'Original guide', 'course_id': original_course.id,
            'lesson_type': 'text', 'html_content': '<p>Read this guide.</p>',
        })
        original_course.write({'state': 'review'})
        original_course.write({'state': 'published'})
        routing = self.env['eds.lms.routing'].create({
            'course_id': eds_course.id,
            'session_id': session.id,
            'lms_ref': str(original_course.id),
            'sync_state': 'synced',
        })
        self.assertEqual(routing._sync_lms_enrollments(original_course), 1)
        original_enrollment = self.env['lms.enrollment'].browse(
            int(original_participant.lms_enrollment_ref)
        )
        original_enrollment.write({'state': 'completed', 'completion_date': today})
        routing.action_reconcile_lms()

        revision_action = original_course.action_create_new_version()
        new_course = self.env['lms.course'].browse(revision_action['res_id'])
        new_course.write({'state': 'review'})
        new_course.write({'state': 'published'})
        new_participant = self.env['eds.enrollment'].create({
            'session_id': session.id,
            'employee_id': new_employee.id,
            'state': 'enrolled',
        })

        routing.cron_sync_lms()
        self.assertEqual(routing.lms_ref, str(new_course.id))
        self.assertEqual(original_participant.lms_enrollment_ref, str(original_enrollment.id))
        self.assertEqual(original_participant.lms_completion_state, 'completed')
        self.assertEqual(original_enrollment.course_id, original_course)
        new_enrollment = self.env['lms.enrollment'].browse(int(new_participant.lms_enrollment_ref))
        self.assertEqual(new_enrollment.course_id, new_course)
        self.assertEqual(new_enrollment.employee_id, new_employee)
        self.assertEqual(routing.lms_completion_pct, 50.0)
        routing.cron_sync_lms()
        self.assertEqual(original_participant.lms_enrollment_ref, str(original_enrollment.id))
        self.assertEqual(new_participant.lms_enrollment_ref, str(new_enrollment.id))
        self.assertEqual(self.env['lms.enrollment'].search_count([
            ('employee_id', '=', original_employee.id), ('course_id', '=', new_course.id),
        ]), 0)
