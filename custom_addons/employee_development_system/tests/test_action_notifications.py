# -*- coding: utf-8 -*-
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests.common import TransactionCase, tagged

from ..models import eds_action_notification
from ..models.eds_action_notification import notify_action


@tagged('post_install', '-at_install', 'eds_action_notifications')
class TestEdsActionNotifications(TransactionCase):

    def test_direct_eds_recipient_notice_gets_one_linked_popup(self):
        internal = self.env.ref('base.group_user')
        recipient = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'EDS Direct Popup Recipient', 'login': 'eds_direct_popup_test',
            'group_ids': [(6, 0, [internal.id])],
        })
        course = self.env['eds.course'].create({
            'name': 'EDS Direct Popup Course', 'status': 'active',
        })
        with patch.object(eds_action_notification, 'push_action_popup') as popup:
            course.message_post(
                body='Review this course request.', partner_ids=recipient.partner_id.ids)
            popup.assert_called_once()
            args = popup.call_args.args
            self.assertEqual(args[0], course)
            self.assertIn(recipient, args[1])
            self.assertIn('Review this course request.', args[3])

        with patch.object(eds_action_notification, 'push_action_popup') as popup:
            notify_action(course, recipient, 'Course action', 'Confirm this course')
            popup.assert_called_once()

    def test_eds_notice_uses_inbox_even_when_user_prefers_email(self):
        internal = self.env.ref('base.group_user')
        employee_group = self.env.ref('employee_development_system.group_eds_employee')
        recipient = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'EDS Inbox Only Recipient', 'login': 'eds_inbox_only_test',
            'group_ids': [(6, 0, [internal.id, employee_group.id])],
        })
        recipient.notification_type = 'email'
        self.assertEqual(recipient.notification_type, 'email')
        course = self.env['eds.course'].create({
            'name': 'EDS Inbox Only Course', 'status': 'active',
        })
        notify_action(course, recipient, 'Review course',
                      'EDS inbox-only delivery check', action_required=False)
        message = self.env['mail.message'].sudo().search([
            ('model', '=', 'eds.course'), ('res_id', '=', course.id),
            ('body', 'ilike', 'EDS inbox-only delivery check'),
        ], order='id desc', limit=1)
        self.assertTrue(message)
        notice = self.env['mail.notification'].sudo().search([
            ('mail_message_id', '=', message.id),
            ('res_partner_id', '=', recipient.partner_id.id),
        ], limit=1)
        self.assertEqual(notice.notification_type, 'inbox')
        self.assertFalse(self.env['mail.mail'].sudo().search([
            ('mail_message_id', '=', message.id),
        ]))

    def test_development_plan_manager_handoff_and_employee_result(self):
        internal = self.env.ref('base.group_user')
        manager_group = self.env.ref('employee_development_system.group_eds_line_manager')
        employee_group = self.env.ref('employee_development_system.group_eds_employee')
        manager_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'EDS IDP Review Manager', 'login': 'eds_idp_review_manager_test',
            'group_ids': [(6, 0, [internal.id, manager_group.id])],
        })
        employee_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'EDS IDP Review Employee', 'login': 'eds_idp_review_employee_test',
            'group_ids': [(6, 0, [internal.id, employee_group.id])],
        })
        manager = self.env['hr.employee'].create({
            'name': 'EDS IDP Manager', 'user_id': manager_user.id,
            'company_id': self.env.company.id,
        })
        employee = self.env['hr.employee'].create({
            'name': 'EDS IDP Employee', 'user_id': employee_user.id,
            'parent_id': manager.id, 'company_id': self.env.company.id,
        })
        plan = self.env['eds.idp'].create({'employee_id': employee.id})
        plan.action_submit()
        self.assertIn(manager_user, plan.activity_ids.mapped('user_id'))
        plan.with_user(manager_user).action_approve()
        self.assertFalse(plan.activity_ids.filtered(
            lambda activity: (activity.summary or '').startswith('EDS action:')))
        self.assertTrue(self.env['mail.message'].sudo().search([
            ('model', '=', 'eds.idp'), ('res_id', '=', plan.id),
            ('partner_ids', 'in', employee_user.partner_id.ids),
            ('body', 'ilike', 'development plan'),
        ]))

    def test_sponsorship_approval_notifies_manager_officer_and_employee(self):
        internal = self.env.ref('base.group_user')
        roles = {
            'manager': self.env.ref('employee_development_system.group_eds_manager'),
            'officer': self.env.ref('employee_development_system.group_eds_officer'),
            'employee': self.env.ref('employee_development_system.group_eds_employee'),
        }
        users = {}
        for role, group in roles.items():
            users[role] = self.env['res.users'].with_context(
                no_reset_password=True).create({
                    'name': 'EDS Sponsorship ' + role,
                    'login': 'eds_sponsorship_notice_' + role + '_test',
                    'group_ids': [(6, 0, [internal.id, group.id])],
                })
        employee = self.env['hr.employee'].create({
            'name': 'EDS Sponsorship Recipient', 'user_id': users['employee'].id,
            'service_start_date': fields.Date.today() - timedelta(days=500),
            'company_id': self.env.company.id,
        })
        sponsorship = self.env['eds.sponsorship'].create({
            'employee_id': employee.id, 'program_name': 'EDS Test Certification',
            'approved_amount': 1000,
        })
        sponsorship.action_verify_eligibility()
        self.assertIn(users['manager'], sponsorship.activity_ids.mapped('user_id'))
        sponsorship.with_user(users['manager']).action_approve()
        self.assertIn(users['officer'], sponsorship.activity_ids.mapped('user_id'))
        self.assertNotIn(users['manager'], sponsorship.activity_ids.mapped('user_id'))
        self.assertTrue(self.env['mail.message'].sudo().search([
            ('model', '=', 'eds.sponsorship'), ('res_id', '=', sponsorship.id),
            ('partner_ids', 'in', users['employee'].partner_id.ids),
            ('body', 'ilike', 'approved'),
        ]))

    def test_reschedule_reminds_invited_employee_and_cancel_closes_invitation(self):
        internal = self.env.ref('base.group_user')
        employee_group = self.env.ref('employee_development_system.group_eds_employee')
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'EDS Reschedule Recipient',
            'login': 'eds_reschedule_recipient_test',
            'group_ids': [(6, 0, [internal.id, employee_group.id])],
        })
        employee = self.env['hr.employee'].create({
            'name': 'EDS Reschedule Employee', 'user_id': user.id,
            'work_contact_id': user.partner_id.id,
            'company_id': self.env.company.id,
        })
        course = self.env['eds.course'].create({
            'name': 'EDS Reschedule Course', 'status': 'active',
        })
        session = self.env['eds.session'].create({
            'course_id': course.id,
            'date_start': '2099-05-01 09:00:00',
            'date_end': '2099-05-01 17:00:00',
        })
        invitation = self.env['eds.enrollment'].create({
            'session_id': session.id, 'employee_id': employee.id,
            'state': 'invited',
        })
        session._write_workflow_status('rescheduled')
        session.action_confirm_reschedule()
        self.assertEqual(session.status, 'scheduled')
        self.assertIn(user, invitation.activity_ids.mapped('user_id'))
        self.assertTrue(self.env['mail.message'].sudo().search([
            ('model', '=', 'eds.enrollment'), ('res_id', '=', invitation.id),
            ('partner_ids', 'in', user.partner_id.ids),
        ]))

        session.action_cancel()
        self.assertEqual(invitation.state, 'cancelled')
        self.assertFalse(invitation.activity_ids.filtered(
            lambda activity: (activity.summary or '').startswith('EDS action:')))

    def test_nomination_alerts_manager_then_lnd_role(self):
        internal = self.env.ref('base.group_user')
        roles = {
            'employee': self.env.ref('employee_development_system.group_eds_employee'),
            'manager': self.env.ref('employee_development_system.group_eds_line_manager'),
            'officer': self.env.ref('employee_development_system.group_eds_officer'),
        }
        users = {}
        for key, group in roles.items():
            users[key] = self.env['res.users'].with_context(
                no_reset_password=True).create({
                    'name': 'EDS Notice ' + key,
                    'login': 'eds_notice_' + key,
                    'group_ids': [(6, 0, [internal.id, group.id])],
                })
        manager = self.env['hr.employee'].create({
            'name': 'EDS Notice Manager', 'user_id': users['manager'].id,
            'company_id': self.env.company.id,
        })
        employee = self.env['hr.employee'].create({
            'name': 'EDS Notice Participant', 'user_id': users['employee'].id,
            'work_contact_id': users['employee'].partner_id.id,
            'parent_id': manager.id, 'company_id': self.env.company.id,
        })
        course = self.env['eds.course'].create({
            'name': 'EDS Notice Training', 'status': 'active',
        })
        session = self.env['eds.session'].create({
            'course_id': course.id,
            'date_start': '2099-04-01 09:00:00',
            'date_end': '2099-04-01 17:00:00',
        })
        nomination = self.env['eds.nomination'].create({
            'session_id': session.id, 'employee_id': employee.id,
            'nomination_type': 'ad_hoc', 'justification': 'Operational coverage',
        })
        nomination.action_submit()
        self.assertIn(users['manager'], nomination.activity_ids.mapped('user_id'))
        nomination.with_user(users['manager']).action_line_manager_approve()
        self.assertIn(users['officer'], nomination.activity_ids.mapped('user_id'))
        self.assertNotIn(users['manager'], nomination.activity_ids.mapped('user_id'))

    def test_open_cycle_announces_only_targeted_employees_in_background(self):
        internal = self.env.ref('base.group_user')
        employee_group = self.env.ref('employee_development_system.group_eds_employee')
        department = self.env['hr.department'].create({
            'name': 'EDS Notification Target Department',
        })
        other_department = self.env['hr.department'].create({
            'name': 'EDS Notification Other Department',
        })
        users = self.env['res.users'].with_context(no_reset_password=True).create([
            {
                'name': 'EDS Targeted Notification User',
                'login': 'eds_targeted_notification_test',
                'group_ids': [(6, 0, [internal.id, employee_group.id])],
            },
            {
                'name': 'EDS Other Notification User',
                'login': 'eds_other_notification_test',
                'group_ids': [(6, 0, [internal.id, employee_group.id])],
            },
        ])
        employees = self.env['hr.employee'].create([
            {
                'name': 'EDS Targeted Notification Employee',
                'user_id': users[0].id,
                'work_contact_id': users[0].partner_id.id,
                'department_id': department.id,
                'company_id': self.env.company.id,
            },
            {
                'name': 'EDS Other Notification Employee',
                'user_id': users[1].id,
                'work_contact_id': users[1].partner_id.id,
                'department_id': other_department.id,
                'company_id': self.env.company.id,
            },
        ])
        today = fields.Date.context_today(self.env['eds.tna.cycle'])
        cycle = self.env['eds.tna.cycle'].create({
            'start_date': today,
            'submission_end_date': today + timedelta(days=7),
            'restrict_tna_audience': True,
            'target_department_ids': [(6, 0, department.ids)],
        })
        cycle.action_start_collection()
        self.assertEqual(cycle.announcement_state, 'pending')
        self.assertEqual(cycle.announcement_sent_count, 0)

        cycle._cron_send_cycle_announcements(batch_size=1, max_batches=1)
        self.assertEqual(cycle.announcement_sent_count, 1)
        self.assertEqual(cycle.announcement_cursor, employees[0].id)
        notices = self.env['mail.message'].sudo().search([
            ('model', '=', 'eds.tna.cycle'), ('res_id', '=', cycle.id),
            ('body', 'ilike', 'Submit your training needs'),
        ])
        self.assertEqual(len(notices), 1)
        self.assertIn(users[0].partner_id, notices.partner_ids)
        self.assertNotIn(users[1].partner_id, notices.partner_ids)
        self.assertEqual(notices.author_id, self.env.user.partner_id)
        inbox = self.env['mail.notification'].sudo().search([
            ('mail_message_id', '=', notices.id),
            ('res_partner_id', '=', users[0].partner_id.id),
        ])
        self.assertTrue(inbox)

        cycle._cron_send_cycle_announcements(batch_size=1, max_batches=1)
        self.assertEqual(cycle.announcement_state, 'done')
        self.assertEqual(cycle.announcement_sent_count, 1)
        cycle._cron_send_cycle_announcements(batch_size=1, max_batches=1)
        self.assertEqual(self.env['mail.message'].sudo().search_count([
            ('model', '=', 'eds.tna.cycle'), ('res_id', '=', cycle.id),
            ('body', 'ilike', 'Submit your training needs'),
        ]), 1)
