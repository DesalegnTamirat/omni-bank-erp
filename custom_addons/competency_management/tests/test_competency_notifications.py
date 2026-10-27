# -*- coding: utf-8 -*-
from unittest.mock import patch

from markupsafe import Markup

from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install', 'competency_notifications')
class TestCompetencyNotifications(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.recipient = new_test_user(
            cls.env, login='competency_notification_recipient',
            groups='base.group_user,competency_management.group_competency_employee',
        )
        cls.other_user = new_test_user(
            cls.env, login='competency_notification_other',
            groups='base.group_user,competency_management.group_competency_employee',
        )
        cls.employee = cls.env['hr.employee'].sudo().create({
            'name': 'Competency Notification Recipient',
            'user_id': cls.recipient.id,
        })
        cls.cycle = cls.env['competency.assessment.cycle'].sudo().create({
            'name': 'Notification Test Cycle 2026/27',
        })
        cls.assessment = cls.env['competency.assessment'].sudo().create({
            'cycle_id': cls.cycle.id,
            'employee_id': cls.employee.id,
            'assessor_id': cls.recipient.id,
            'assessment_type': 'self',
        })

    def test_cycle_title_popup_private_history_and_read_inbox(self):
        bus_model = type(self.env['bus.bus'])
        with patch.object(bus_model, '_sendone') as send_popup:
            self.assessment._notify_user_inbox_and_activity(
                self.recipient,
                'Fill Competency Assessment',
                'Your assessment is ready.',
                Markup('<p>Open your assigned assessment.</p>'),
                event_key='test-cycle-open:%s:%s' % (self.cycle.id, self.recipient.id),
            )

            history = self.env['competency.notification'].sudo().search([
                ('user_id', '=', self.recipient.id),
                ('event_key', '=', 'test-cycle-open:%s:%s' % (self.cycle.id, self.recipient.id)),
            ])
            self.assertEqual(len(history), 1)
            self.assertTrue(history.name.startswith(self.cycle.name))
            self.assertIn('<strong>%s</strong>' % self.cycle.name, history.body)
            self.assertEqual(history.mail_message_id.subject, history.name)

            popup_calls = [
                call for call in send_popup.call_args_list
                if len(call.args) > 1 and call.args[1] == 'simple_notification'
            ]
            self.assertEqual(len(popup_calls), 1)
            popup_args = popup_calls[0].args
            self.assertEqual(popup_args[1], 'simple_notification')
            self.assertEqual(popup_args[2]['title'], self.cycle.name)
            self.assertTrue(popup_args[2]['sticky'])

            inbox = self.env['mail.notification'].sudo().search([
                ('mail_message_id', '=', history.mail_message_id.id),
                ('res_partner_id', '=', self.recipient.partner_id.id),
            ])
            self.assertEqual(len(inbox), 1)
            self.assertEqual(inbox.notification_type, 'inbox')
            self.assertFalse(inbox.is_read)
            self.assertEqual(len(self.assessment.activity_ids.filtered(
                lambda activity: activity.user_id == self.recipient and activity.summary == history.name
            )), 1)

            inbox.write({'is_read': True})
            self.assertTrue(self.env['competency.notification'].with_user(self.recipient).search([
                ('id', '=', history.id),
            ]))
            self.assertFalse(self.env['competency.notification'].with_user(self.other_user).search([
                ('id', '=', history.id),
            ]))

            self.assessment._notify_user_inbox_and_activity(
                self.recipient,
                'Fill Competency Assessment',
                'Your assessment is ready.',
                Markup('<p>Open your assigned assessment.</p>'),
                event_key='test-cycle-open:%s:%s' % (self.cycle.id, self.recipient.id),
            )
            self.assertEqual(len([
                call for call in send_popup.call_args_list
                if len(call.args) > 1 and call.args[1] == 'simple_notification'
            ]), 1)
            self.assertEqual(self.env['competency.notification'].sudo().search_count([
                ('event_key', '=', 'test-cycle-open:%s:%s' % (self.cycle.id, self.recipient.id)),
            ]), 1)

    def test_non_cycle_notification_uses_its_own_subject(self):
        summary = 'Competency Data Quality Audit'
        bus_model = type(self.env['bus.bus'])
        with patch.object(bus_model, '_sendone') as send_popup:
            self.env['competency.assessment']._notify_user_inbox_and_activity(
                self.recipient, summary, 'One role needs a mapping.',
                Markup('<p>Review the role mapping.</p>'),
                event_key='test-data-quality:%s' % self.recipient.id,
            )
        history = self.env['competency.notification'].sudo().search([
            ('event_key', '=', 'test-data-quality:%s' % self.recipient.id),
        ])
        self.assertEqual(history.name, summary)
        self.assertFalse(history.cycle_id)
        self.assertFalse(history.assessment_id)
        self.assertEqual(history.mail_message_id.subject, summary)
        popup_calls = [
            call for call in send_popup.call_args_list
            if len(call.args) > 1 and call.args[1] == 'simple_notification'
        ]
        self.assertEqual(len(popup_calls), 1)
        self.assertEqual(popup_calls[0].args[2]['title'], summary)

    def test_non_cycle_record_target_keeps_activity(self):
        summary = 'Baseline Competency Assessment Due'
        self.env['competency.assessment']._notify_user_inbox_and_activity(
            self.recipient, summary, 'Please review the baseline assessment.',
            Markup('<p>Review the baseline assessment.</p>'),
            target_rec=self.employee,
            event_key='test-baseline:%s:%s' % (self.employee.id, self.recipient.id),
        )
        history = self.env['competency.notification'].sudo().search([
            ('event_key', '=', 'test-baseline:%s:%s' % (self.employee.id, self.recipient.id)),
        ])
        self.assertEqual(history.name, summary)
        self.assertFalse(history.cycle_id)
        self.assertTrue(self.employee.activity_ids.filtered(
            lambda activity: activity.user_id == self.recipient and activity.summary == summary
        ))
