# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'eds_delivery_integrity')
class TestDeliveryIntegrity(TransactionCase):

    def test_attendance_is_scoped_to_session_and_scheduled_period(self):
        course = self.env['eds.course'].create({'name': 'Repeated delivery course'})
        employee = self.env['hr.employee'].create({'name': 'Repeated delivery participant'})
        sessions = self.env['eds.session'].create([
            {'course_id': course.id, 'date_start': '2098-04-01 09:00:00',
             'date_end': '2098-04-01 17:00:00'},
            {'course_id': course.id, 'date_start': '2098-04-08 09:00:00',
             'date_end': '2098-04-08 17:00:00'},
        ])
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['eds.session.attendance'].create({
                'session_id': sessions[0].id, 'employee_id': employee.id,
                'attendance_date': sessions[0]._attendance_slots()[0][0],
                'attended': True,
            })
        self.env['eds.enrollment'].create([
            {'session_id': session.id, 'employee_id': employee.id, 'state': 'enrolled'}
            for session in sessions
        ])
        first_day = sessions[0]._attendance_slots()[0][0]
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['eds.session.attendance'].create({
                'session_id': sessions[0].id, 'employee_id': employee.id,
                'attendance_date': first_day + timedelta(days=1), 'attended': True,
            })
        first = self.env['eds.session.attendance'].create({
            'session_id': sessions[0].id, 'employee_id': employee.id,
            'attendance_date': first_day, 'attended': True,
        })
        second = self.env['eds.session.attendance'].create({
            'session_id': sessions[1].id, 'employee_id': employee.id,
            'attendance_date': sessions[1]._attendance_slots()[0][0],
            'attended': False,
        })
        self.assertEqual(first.attendance_percentage, 100.0)
        self.assertEqual(second.attendance_percentage, 0.0)
        with self.assertRaises(UserError):
            sessions[0].write({'date_start': '2098-04-01 10:00:00'})

    def test_partial_marks_cannot_satisfy_certificate_threshold(self):
        course = self.env['eds.course'].create({'name': 'Incomplete marks course'})
        employee = self.env['hr.employee'].create({'name': 'Incomplete marks participant'})
        session = self.env['eds.session'].create({
            'course_id': course.id, 'date_start': '2098-04-01 09:00:00',
            'date_end': '2098-04-02 17:00:00',
        })
        self.env['eds.enrollment'].create({
            'session_id': session.id, 'employee_id': employee.id, 'state': 'enrolled',
        })
        attendance = self.env['eds.session.attendance'].create({
            'session_id': session.id, 'employee_id': employee.id,
            'attendance_date': session._attendance_slots()[0][0], 'attended': True,
        })
        self.assertEqual(attendance.attendance_percentage, 50.0)
        self.assertEqual(session.attendance_rate, 50.0)
        certificate = self.env['eds.certificate'].create({
            'session_id': session.id, 'employee_id': employee.id,
        })
        certificate._compute_eligibility()
        self.assertFalse(certificate.is_eligible)

    def test_certificate_print_ignores_other_session_and_pending(self):
        course = self.env['eds.course'].create({'name': 'Certificate separation course'})
        employee = self.env['hr.employee'].create({'name': 'Certificate separation employee'})
        sessions = self.env['eds.session'].create([
            {'course_id': course.id, 'date_start': '2098-04-01 09:00:00',
             'date_end': '2098-04-01 17:00:00'},
            {'course_id': course.id, 'date_start': '2098-04-08 09:00:00',
             'date_end': '2098-04-08 17:00:00'},
        ])
        self.env['eds.certificate'].create({
            'session_id': sessions[0].id, 'employee_id': employee.id,
            'state': 'pending',
        })
        self.env['eds.certificate'].create({
            'session_id': sessions[1].id, 'employee_id': employee.id,
            'state': 'issued',
        })
        with self.assertRaises(UserError):
            sessions[0].action_print_all_certificates()

    def test_list_views_expire_overdue_invitations(self):
        course = self.env['eds.course'].create({'name': 'List deadline course'})
        employee = self.env['hr.employee'].create({'name': 'List deadline participant'})
        start = fields.Datetime.now() + timedelta(days=7)
        session = self.env['eds.session'].create({
            'course_id': course.id, 'date_start': start,
            'date_end': start + timedelta(hours=8),
        })
        session._write_workflow_status('scheduled')
        invitation = self.env['eds.enrollment'].create({
            'session_id': session.id, 'employee_id': employee.id, 'state': 'invited',
        })
        session.response_deadline = fields.Datetime.now() - timedelta(minutes=1)
        self.env['eds.enrollment'].web_search_read(
            [('id', '=', invitation.id)], {'state': {}}, limit=80)
        self.assertEqual(invitation.state, 'declined')
        self.assertTrue(invitation.auto_rejected)

        second_employee = self.env['hr.employee'].create({
            'name': 'Second list deadline participant',
        })
        second_invitation = self.env['eds.enrollment'].create({
            'session_id': session.id, 'employee_id': second_employee.id,
            'state': 'invited',
        })
        self.env['eds.session'].web_search_read(
            [('id', '=', session.id)], {'pending_count': {}}, limit=80)
        self.assertEqual(second_invitation.state, 'declined')
        self.assertTrue(second_invitation.auto_rejected)

