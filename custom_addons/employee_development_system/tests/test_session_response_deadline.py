# -*- coding: utf-8 -*-
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from ..models import eds_nomination
from ..wizards import eds_enrollment_response


@tagged('post_install', '-at_install', 'eds_session_response_deadline')
class TestSessionResponseDeadline(TransactionCase):

    def test_invitation_shows_course_provider_venue_location_and_dates(self):
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'EDS Invitation Details Recipient',
            'login': 'eds_invitation_details_recipient_test',
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('employee_development_system.group_eds_employee').id,
            ])],
        })
        employee = self.env['hr.employee'].create({
            'name': 'EDS Invitation Details Employee', 'user_id': user.id,
            'company_id': self.env.company.id,
        })
        course = self.env['eds.course'].create({'name': 'Invitation details course'})
        provider = self.env['eds.external.provider'].create({
            'name': 'Invitation details provider',
        })
        country = self.env.ref('base.ke')
        venue = self.env['eds.venue'].create({
            'name': 'Riverside Hotel', 'location_scope': 'international',
            'country_id': country.id, 'city': 'Nairobi',
            'location': 'Conference wing', 'address': 'Floor 2, Riverside Road',
        })
        session = self.env['eds.session'].create({
            'course_id': course.id, 'awarded_provider_id': provider.id,
            'venue_id': venue.id, 'delivery_method': 'local_external',
            'date_start': '2099-05-01 09:00:00',
            'date_end': '2099-05-01 17:00:00',
        })
        invitation = self.env['eds.enrollment'].create({
            'session_id': session.id, 'employee_id': employee.id,
        })

        self.assertEqual(invitation.course_id, course)
        self.assertEqual(invitation.training_provider_name, provider.name)
        self.assertEqual(invitation.venue_id, venue)
        self.assertEqual(invitation.session_start, session.date_start)
        self.assertEqual(invitation.session_end, session.date_end)
        for detail in ('Conference wing', 'Floor 2, Riverside Road',
                       'Nairobi', country.name):
            self.assertIn(detail, invitation.venue_location_details)
        employee_view = invitation.with_user(user).read([
            'course_id', 'training_provider_name', 'venue_id',
            'venue_location_details', 'session_start', 'session_end',
        ])[0]
        self.assertEqual(employee_view['training_provider_name'], provider.name)
        self.assertIn('Floor 2, Riverside Road', employee_view['venue_location_details'])

        with patch.object(eds_nomination, 'notify_action') as notice:
            invitation._send_invitation_notice()
        self.assertEqual(notice.call_count, 1)
        message = notice.call_args.args[3]
        for detail in (course.name, provider.name, venue.name,
                       'Conference wing', 'Floor 2, Riverside Road',
                       'Nairobi', country.name, 'Starts:', 'Ends:'):
            self.assertIn(detail, message)

    def test_invitation_selection_and_replacement_review(self):
        start = fields.Datetime.now() + timedelta(days=7)
        course = self.env['eds.course'].create({'name': 'Invitation response course'})
        plan = self.env['eds.annual.plan'].create({'fiscal_year': str(start.year)})
        line = self.env['eds.annual.plan.line'].create({
            'plan_id': plan.id, 'course_id': course.id,
            'planned_participants': 2, 'duration_days': 1,
        })
        session = self.env['eds.session'].create({
            'plan_line_id': line.id,
            'date_start': start, 'date_end': start + timedelta(hours=8),
        })
        session._write_workflow_status('scheduled')
        groups = [self.env.ref('base.group_user').id,
                  self.env.ref('employee_development_system.group_eds_employee').id]
        users = self.env['res.users'].with_context(no_reset_password=True).create([
            {'name': 'First invitee', 'login': 'eds_first_invitee_test',
             'group_ids': [(6, 0, groups)]},
            {'name': 'Second invitee', 'login': 'eds_second_invitee_test',
             'group_ids': [(6, 0, groups)]},
        ])
        employees = self.env['hr.employee'].create([
            {'name': 'First invitee', 'user_id': users[0].id,
             'company_id': self.env.company.id},
            {'name': 'Second invitee', 'user_id': users[1].id,
             'company_id': self.env.company.id},
        ])
        first = self.env['eds.enrollment'].with_context(eds_manual_roster=True).create({
            'session_id': session.id, 'employee_id': employees[0].id,
            'state': 'enrolled', 'selected': True,
        })
        self.assertEqual(first.state, 'suggested')
        with self.assertRaises(UserError):
            first.write({'state': 'enrolled'})
        with patch.object(eds_nomination, 'notify_action') as notice:
            session.action_invite_selected()
            self.assertEqual(notice.call_count, 1)
        self.assertEqual(first.state, 'invited')
        self.assertFalse(first.selected)
        self.assertFalse(first.enrolled_date)

        session.write({'enrollment_ids': [(0, 0, {
            'employee_id': employees[1].id,
            'state': 'enrolled', 'selected': True,
        })]})
        second = session.enrollment_ids.filtered(
            lambda row: row.employee_id == employees[1])
        self.assertEqual(second.state, 'suggested')
        with patch.object(eds_nomination, 'notify_action') as notice:
            session.action_invite_selected()
            self.assertEqual(notice.call_count, 1)
        self.assertEqual(first.state, 'invited')
        self.assertFalse(first.selected)
        self.assertEqual(second.state, 'invited')
        self.assertFalse(second.selected)

        replacement = self.env['hr.employee'].create({
            'name': 'Suggested employee without a login',
            'company_id': self.env.company.id,
        })
        wizard = self.env['eds.enrollment.response.wizard'].create({
            'enrollment_id': first.id, 'response': 'replace',
            'replacement_employee_id': replacement.id,
            'reason': 'Unable to attend',
        })
        with patch.object(eds_enrollment_response, 'notify_action') as notice:
            wizard.with_user(users[0]).action_submit()
            self.assertEqual(notice.call_count, 1)
        self.assertEqual(first.state, 'replaced')
        self.assertEqual(first.replacement_employee_id, replacement)
        self.assertFalse(session.enrollment_ids.filtered(
            lambda row: row.employee_id == replacement))

    def test_counts_expiry_and_scheduled_roster(self):
        start = fields.Datetime.now() + timedelta(days=7)
        course = self.env['eds.course'].create({'name': 'Response deadline course'})
        plan = self.env['eds.annual.plan'].create({'fiscal_year': str(start.year)})
        line = self.env['eds.annual.plan.line'].create({
            'plan_id': plan.id, 'course_id': course.id,
            'planned_participants': 3, 'duration_days': 1,
        })
        session = self.env['eds.session'].create({
            'plan_line_id': line.id,
            'date_start': start, 'date_end': start + timedelta(hours=8),
        })
        self.assertEqual(session.response_deadline, start - timedelta(days=2))
        self.assertEqual(session.planned_participant_count, 3)
        session._write_workflow_status('scheduled')

        employees = self.env['hr.employee'].create([
            {'name': 'Pending response', 'company_id': self.env.company.id},
            {'name': 'Accepted response', 'company_id': self.env.company.id},
        ])
        pending = self.env['eds.enrollment'].create({
            'session_id': session.id, 'employee_id': employees[0].id,
            'state': 'invited',
        })
        accepted = self.env['eds.enrollment'].create({
            'session_id': session.id, 'employee_id': employees[1].id,
            'state': 'enrolled', 'response_date': fields.Datetime.now(),
        })
        self.assertEqual(session.pending_count, 1)
        self.assertEqual(session.enrolled_count, 1)

        session.response_deadline = fields.Datetime.now() - timedelta(minutes=1)
        session.web_read({'pending_count': {}, 'enrolled_count': {}})
        self.assertEqual(pending.state, 'declined')
        self.assertTrue(pending.auto_rejected)
        self.assertEqual(session.pending_count, 0)
        self.assertEqual(session.enrolled_count, 1)
        self.assertEqual(pending.action_open_response()['tag'], 'display_notification')
        with self.assertRaises(UserError):
            accepted.unlink()
