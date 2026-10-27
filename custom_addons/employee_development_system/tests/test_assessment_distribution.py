# -*- coding: utf-8 -*-
"""Session UI actions keep pre/post distribution optional and idempotent."""

import uuid

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'eds_assessment_distribution')
class TestAssessmentDistribution(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        unique = uuid.uuid4().hex[:8]
        cls.officer = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Assessment Distribution Officer',
            'login': 'eds_distribution_officer_' + unique,
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('employee_development_system.group_eds_officer').id,
            ])],
        })
        cls.participant_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Assessment Distribution Participant',
            'login': 'eds_distribution_participant_' + unique,
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.other_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Other Assessment Participant',
            'login': 'eds_distribution_other_' + unique,
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        employee = cls.env['hr.employee'].create({
            'name': 'Assessment Distribution Participant',
            'user_id': cls.participant_user.id,
        })
        course = cls.env['eds.course'].create({'name': 'Distribution Test Course'})
        cls.session = cls.env['eds.session'].create({
            'course_id': course.id,
            'date_start': '2098-05-01 09:00:00',
            'date_end': '2098-05-01 17:00:00',
        })
        cls.env['eds.enrollment'].create({
            'session_id': cls.session.id,
            'employee_id': employee.id,
            'state': 'enrolled',
        })
        cls.env['eds.assessment.question'].create([
            {'session_id': cls.session.id, 'assessment_type': assessment_type,
             'question_text': 'Explain the %s topic' % assessment_type, 'max_points': 2.0}
            for assessment_type in ('pre', 'post')
        ])

    def test_distribution_is_explicit_and_repeat_click_does_not_renotify(self):
        session = self.session.with_user(self.officer)
        self.assertFalse(self.env['eds.assessment'].search([
            ('session_id', '=', self.session.id)]))
        self.session.sudo().write({'status': 'scheduled'})
        self.assertFalse(self.env['eds.assessment'].search([
            ('session_id', '=', self.session.id)]))

        result = session.action_distribute_pre_assessment()
        self.assertEqual(result['tag'], 'display_notification')
        pre = self.env['eds.assessment'].search([
            ('session_id', '=', self.session.id), ('assessment_type', '=', 'pre')])
        self.assertEqual(pre.state, 'distributed')
        self.assertEqual(len(pre.answer_ids), 1)
        first_activities = pre.activity_ids.filtered(
            lambda activity: activity.user_id == self.participant_user)
        self.assertEqual(len(first_activities), 1)
        session.action_distribute_pre_assessment()
        self.assertEqual(len(pre.activity_ids.filtered(
            lambda activity: activity.user_id == self.participant_user)), 1)

        with self.assertRaises(UserError):
            session.action_distribute_post_assessment()
        self.session.sudo().write({'status': 'ongoing'})
        session.action_distribute_post_assessment()
        post = self.env['eds.assessment'].search([
            ('session_id', '=', self.session.id), ('assessment_type', '=', 'post')])
        self.assertEqual(post.state, 'distributed')
        self.assertNotEqual(pre.id, post.id)

    def test_employee_can_only_read_own_question_and_edit_own_open_answer(self):
        self.session.sudo().write({'status': 'scheduled'})
        self.session.with_user(self.officer).action_distribute_pre_assessment()
        assessment = self.env['eds.assessment'].search([
            ('session_id', '=', self.session.id), ('assessment_type', '=', 'pre')])
        answer = assessment.answer_ids
        self.assertEqual(assessment.with_user(self.participant_user).state, 'distributed')
        answer.with_user(self.participant_user).write({'answer_text': 'My response'})
        self.assertEqual(answer.answer_text, 'My response')
        with self.assertRaises(AccessError):
            answer.with_user(self.other_user).write({'answer_text': 'Tampered'})
        with self.assertRaises(AccessError):
            assessment.with_user(self.other_user).write({'state': 'submitted'})

    def test_manual_assessment_is_private_until_staff_choose_distribution(self):
        manual = self.env['eds.assessment'].with_user(self.officer).create({
            'session_id': self.session.id,
            'employee_id': self.session.enrollment_ids.employee_id.id,
            'assessment_type': 'post',
            'entry_method': 'manual',
        })
        manual.action_load_questions()
        manual.answer_ids[0].write({'answer_text': 'Staff recorded answer'})
        other_employee = self.env['hr.employee'].create({
            'name': 'Other Assessment Participant', 'user_id': self.other_user.id,
        })
        self.env['eds.enrollment'].create({
            'session_id': self.session.id,
            'employee_id': other_employee.id,
            'state': 'enrolled',
        })
        self.session.sudo().write({'status': 'ongoing'})
        self.session.with_user(self.officer).action_distribute_post_assessment()
        self.assertEqual(manual.entry_method, 'manual')
        self.assertFalse(manual.distributed_at)
        self.assertEqual(manual.answer_ids[0].answer_text, 'Staff recorded answer')
        staff_assessments = self.env['eds.assessment'].with_user(self.officer).search([
            ('id', '=', manual.id),
        ])
        self.assertIn(manual.id, staff_assessments.ids)
        own_assessments = self.env['eds.assessment'].with_user(self.participant_user).search([
            ('session_id', '=', self.session.id),
        ])
        self.assertNotIn(manual.id, own_assessments.ids)
        own_answers = self.env['eds.assessment.answer'].with_user(self.participant_user).search([
            ('assessment_id', '=', manual.id),
        ])
        self.assertFalse(own_answers)
        own_questions = self.env['eds.assessment.question'].with_user(self.participant_user).search([
            ('id', 'in', manual.answer_ids.mapped('question_id').ids),
        ])
        self.assertFalse(own_questions)

