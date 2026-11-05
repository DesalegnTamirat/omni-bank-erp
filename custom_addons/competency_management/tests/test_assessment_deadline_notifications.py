# -*- coding: utf-8 -*-
from datetime import timedelta
from uuid import uuid4

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'competency_deadline_notifications')
class TestAssessmentDeadlineNotifications(TransactionCase):

    def setUp(self):
        super().setUp()
        suffix = uuid4().hex[:12]
        employee_group = self.env.ref('competency_management.group_competency_employee')
        officer_group = self.env.ref('competency_management.group_competency_officer')
        admin_group = self.env.ref('competency_management.group_competency_admin')
        internal_group = self.env.ref('base.group_user')
        Users = self.env['res.users'].with_context(no_reset_password=True)
        self.assessor_user = Users.create({
            'name': 'Competency Deadline Assessor',
            'login': 'competency_deadline_assessor_' + suffix,
            'group_ids': [(6, 0, [internal_group.id, employee_group.id])],
        })
        self.officer_user = Users.create({
            'name': 'Competency Deadline Officer',
            'login': 'competency_deadline_officer_' + suffix,
            'group_ids': [(6, 0, [internal_group.id, officer_group.id])],
        })
        self.admin_user = Users.create({
            'name': 'Competency Deadline Administrator',
            'login': 'competency_deadline_admin_' + suffix,
            'group_ids': [(6, 0, [internal_group.id, admin_group.id])],
        })
        self.employee = self.env['hr.employee'].sudo().create({
            'name': 'Competency Deadline Assessor',
            'user_id': self.assessor_user.id,
            'company_id': self.env.company.id,
        })
        self.today = fields.Date.today()
        self.cycle = self.env['competency.assessment.cycle'].sudo().create({
            'name': 'Deadline Test Cycle ' + suffix,
            'period_start': self.today - timedelta(days=30),
            'assessment_deadline': self.today - timedelta(days=1),
            'state': 'open',
        })
        self.assessment = self.env['competency.assessment'].sudo().create({
            'cycle_id': self.cycle.id,
            'employee_id': self.employee.id,
            'assessor_id': self.assessor_user.id,
            'assessment_type': 'self',
        })

    def test_expired_assessment_cannot_be_submitted_by_assessor_or_admin(self):
        for user in (self.assessor_user, self.admin_user):
            with self.subTest(user=user.login):
                with self.assertRaisesRegex(UserError, 'deadline'):
                    with self.env.cr.savepoint():
                        self.assessment.with_user(user).action_submit()
                self.assertEqual(self.assessment.state, 'draft')

    def test_direct_state_write_cannot_bypass_expired_deadline(self):
        for user in (self.assessor_user, self.admin_user):
            with self.subTest(user=user.login):
                with self.assertRaisesRegex(UserError, 'deadline'):
                    with self.env.cr.savepoint():
                        self.assessment.with_user(user).write({'state': 'submitted'})
                self.assertEqual(self.assessment.state, 'draft')

    def test_assessor_can_submit_through_deadline_day(self):
        self.cycle.sudo().write({'assessment_deadline': self.today})
        competency = self.env['competency.competency'].sudo().search([
            ('state', '=', 'approved'),
        ], limit=1)
        if not competency:
            competency = self.env['competency.competency'].sudo().create({
                'name': 'Deadline Test Competency',
                'code': 'DEADLINE-' + uuid4().hex[:8],
                'pillar': 'core',
                'state': 'approved',
            })
        self.env['competency.assessment.line'].sudo().create({
            'assessment_id': self.assessment.id,
            'competency_id': competency.id,
            'current_level': '2',
            'required_level': '2',
        })
        self.assessment.with_user(self.assessor_user).action_submit()
        self.assertEqual(self.assessment.state, 'submitted')

    def test_closed_cycle_rejects_submission_even_before_deadline(self):
        self.cycle.sudo().write({
            'assessment_deadline': self.today + timedelta(days=2),
            'state': 'closed',
        })
        with self.assertRaisesRegex(UserError, 'closed|open'):
            with self.env.cr.savepoint():
                self.assessment.with_user(self.assessor_user).action_submit()
        self.assertEqual(self.assessment.state, 'draft')

    def test_officer_and_admin_can_extend_open_cycle_deadline(self):
        officer_deadline = self.today + timedelta(days=5)
        admin_deadline = self.today + timedelta(days=10)
        self.cycle.with_user(self.officer_user).write({
            'assessment_deadline': officer_deadline,
        })
        self.assertEqual(self.cycle.assessment_deadline, officer_deadline)
        self.cycle.with_user(self.admin_user).write({
            'assessment_deadline': admin_deadline,
        })
        self.assertEqual(self.cycle.assessment_deadline, admin_deadline)
        with self.assertRaises(AccessError):
            with self.env.cr.savepoint():
                self.cycle.with_user(self.assessor_user).write({
                    'assessment_deadline': self.today + timedelta(days=15),
                })
        self.assertEqual(self.cycle.assessment_deadline, admin_deadline)

    def test_notification_reaches_document_chatter_and_discuss(self):
        marker = 'Competency deadline notification ' + uuid4().hex[:12]
        self.assessment.sudo()._notify_user_inbox_and_activity(
            self.assessor_user,
            summary=marker,
            note=marker,
            msg_text=marker,
            target_rec=self.assessment,
            sender_user=self.admin_user,
        )
        Message = self.env['mail.message'].sudo()
        chatter = Message.search([
            ('model', '=', 'competency.assessment'),
            ('res_id', '=', self.assessment.id),
            ('body', 'ilike', marker),
        ], limit=1)
        self.assertTrue(chatter, 'Assessment notification must remain on its chatter.')
        inbox = self.env['mail.notification'].sudo().search([
            ('mail_message_id', '=', chatter.id),
            ('res_partner_id', '=', self.assessor_user.partner_id.id),
            ('notification_type', '=', 'inbox'),
        ], limit=1)
        self.assertTrue(inbox, 'Recipient must have an in-app notification.')
        discuss_message = Message.search([
            ('model', '=', 'discuss.channel'),
            ('body', 'ilike', marker),
        ], limit=1)
        self.assertTrue(discuss_message, 'Recipient must receive a Discuss message.')
        channel = self.env['discuss.channel'].sudo().browse(discuss_message.res_id)
        self.assertIn(
            self.assessor_user.partner_id,
            channel.channel_member_ids.mapped('partner_id'),
        )

    def test_deadline_cron_notifies_assessor_once_per_milestone(self):
        self.cycle.sudo().write({
            'assessment_deadline': self.today + timedelta(days=7),
        })
        Assessment = self.env['competency.assessment'].sudo()
        Assessment._cron_pending_assessment_reminders()
        Activity = self.env['mail.activity'].sudo()
        activity_domain = [
            ('res_model', '=', 'competency.assessment.cycle'),
            ('res_id', '=', self.cycle.id),
            ('user_id', '=', self.assessor_user.id),
            ('summary', 'ilike', self.cycle.name),
        ]
        self.assertEqual(Activity.search_count(activity_domain), 1)
        Message = self.env['mail.message'].sudo()
        dm_domain = [
            ('model', '=', 'discuss.channel'),
            ('body', 'ilike', self.cycle.name),
        ]
        self.assertEqual(
            Message.search_count(dm_domain), 1,
            [(msg.id, str(msg.body)[:300]) for msg in Message.search([('model', '=', 'discuss.channel')], limit=5)],
        )
        Assessment._cron_pending_assessment_reminders()
        self.assertEqual(Activity.search_count(activity_domain), 1)
        self.assertEqual(Message.search_count(dm_domain), 1)
