# -*- coding: utf-8 -*-
"""Timing and once-only delivery for post-training manager assessments."""

from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'eds_level3_review_timing')
class TestLevel3ReviewTiming(TransactionCase):

    def test_configured_intervals_include_minutes_and_calendar_months(self):
        params = self.env['ir.config_parameter'].sudo()
        reviews = self.env['eds.evaluation.level3']
        base = fields.Datetime.to_datetime('2026-01-31 12:00:00')

        params.set_param('eds.level3_delay_value', 2)
        params.set_param('eds.level3_delay_unit', 'minutes')
        when, period = reviews._configured_notification_time(base)
        self.assertEqual(when, base + timedelta(minutes=2))
        self.assertEqual(period, 'custom')

        params.set_param('eds.level3_delay_value', 1)
        params.set_param('eds.level3_delay_unit', 'months')
        when, period = reviews._configured_notification_time(base)
        self.assertEqual(when, fields.Datetime.to_datetime('2026-02-28 12:00:00'))
        self.assertEqual(period, 'custom')

        params.set_param('eds.level3_delay_value', 60)
        params.set_param('eds.level3_delay_unit', 'days')
        self.assertEqual(reviews._configured_notification_time(base)[1], '60_days')

    def test_completion_schedules_review_and_cron_notifies_once(self):
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('eds.level3_delay_value', 2)
        params.set_param('eds.level3_delay_unit', 'minutes')
        internal = self.env.ref('base.group_user')
        manager_group = self.env.ref('employee_development_system.group_eds_line_manager')
        manager_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Review timing manager', 'login': 'eds_review_timing_manager_test',
            'group_ids': [(6, 0, [internal.id, manager_group.id])],
        })
        manager = self.env['hr.employee'].create({
            'name': 'Review timing manager', 'user_id': manager_user.id,
            'company_id': self.env.company.id,
        })
        employee = self.env['hr.employee'].create({
            'name': 'Review timing participant', 'parent_id': manager.id,
            'company_id': self.env.company.id,
        })
        course = self.env['eds.course'].create({'name': 'Review timing course'})
        session = self.env['eds.session'].create({
            'course_id': course.id,
            'date_start': '2098-06-01 09:00:00',
            'date_end': '2098-06-01 17:00:00',
        })
        self.env['eds.enrollment'].create({
            'session_id': session.id, 'employee_id': employee.id,
            'state': 'completed',
        })
        before = fields.Datetime.now()
        session._distribute_completion_evaluations()
        review = self.env['eds.evaluation.level3'].search([
            ('session_id', '=', session.id), ('employee_id', '=', employee.id),
        ])
        self.assertEqual(len(review), 1)
        self.assertEqual(review.evaluation_period, 'custom')
        self.assertGreaterEqual(review.notification_at, before + timedelta(minutes=2))
        self.assertLessEqual(review.notification_at,
                             fields.Datetime.now() + timedelta(minutes=2))
        self.assertFalse(review.notification_sent_at)
        self.assertFalse(review.message_ids.filtered(
            lambda message: 'on-the-job application' in (message.body or '')))

        review.notification_at = fields.Datetime.now() - timedelta(minutes=1)
        reviews = self.env['eds.evaluation.level3']
        reviews._cron_notify_due_level3()
        self.assertTrue(review.notification_sent_at)
        notices = review.message_ids.filtered(
            lambda message: 'on-the-job application' in (message.body or ''))
        self.assertEqual(len(notices), 1)
        self.assertIn(manager_user, review.activity_ids.mapped('user_id'))
        reviews._cron_notify_due_level3()
        self.assertEqual(len(review.message_ids.filtered(
            lambda message: 'on-the-job application' in (message.body or ''))), 1)
