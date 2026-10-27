# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'eds')
class TestEdsDashboardSecurity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base = cls.env.ref('base.group_user')
        employee_group = cls.env.ref('employee_development_system.group_eds_employee')
        manager_group = cls.env.ref('employee_development_system.group_eds_line_manager')
        officer_group = cls.env.ref('employee_development_system.group_eds_officer')
        Users = cls.env['res.users'].with_context(no_reset_password=True)

        def user(name, groups):
            return Users.create({
                'name': name, 'login': name.lower().replace(' ', '_'),
                'group_ids': [(6, 0, [base.id] + [group.id for group in groups])],
            })

        cls.manager_user = user('EDS Dashboard Manager', [manager_group])
        cls.employee_user = user('EDS Dashboard Employee', [employee_group])
        cls.other_user = user('EDS Dashboard Other', [employee_group])
        cls.officer_user = user('EDS Dashboard Officer', [officer_group])
        Employee = cls.env['hr.employee']
        manager = Employee.create({
            'name': 'EDS Dashboard Manager', 'user_id': cls.manager_user.id,
            'company_id': cls.env.company.id,
        })
        cls.employee = Employee.create({
            'name': 'EDS Dashboard Employee', 'user_id': cls.employee_user.id,
            'parent_id': manager.id, 'company_id': cls.env.company.id,
        })
        cls.other_employee = Employee.create({
            'name': 'EDS Dashboard Other', 'user_id': cls.other_user.id,
            'company_id': cls.env.company.id,
        })
        year = str(fields.Date.today().year)
        cls.cycle = cls.env['eds.tna.cycle'].create({
            'year': year, 'state': 'collecting',
        })
        cls.course = cls.env['eds.course'].create({'name': 'EDS Scoped Dashboard Course'})
        cls.own_need = cls.env['eds.tna.entry'].create({
            'cycle_id': cls.cycle.id, 'employee_id': cls.employee.id,
            'course_id': cls.course.id, 'justification': 'Dashboard scope',
        })
        cls.other_need = cls.env['eds.tna.entry'].create({
            'cycle_id': cls.cycle.id, 'employee_id': cls.other_employee.id,
            'course_id': cls.course.id, 'justification': 'Other employee scope',
            'state': 'submitted',
        })

    def test_dashboard_figures_and_buttons_follow_persona(self):
        Dashboard = self.env['eds.dashboard']
        own = Dashboard.with_user(self.employee_user).create({})
        manager = Dashboard.with_user(self.manager_user).create({})
        officer = Dashboard.with_user(self.officer_user).create({})
        self.assertEqual(own.role_persona, 'employee')
        self.assertEqual(manager.role_persona, 'manager')
        self.assertEqual(officer.role_persona, 'admin')
        self.assertEqual((own.is_admin, own.is_manager, own.is_employee), (False, False, True))
        self.assertEqual((manager.is_admin, manager.is_manager, manager.is_employee), (False, True, False))
        self.assertEqual(manager.team_members_count, 1)
        self.assertEqual(own.my_tna_needs_count, 1)
        self.assertEqual(own.reporting_year, str(fields.Date.today().year))
        self.assertEqual(own.reporting_fiscal_year, own.reporting_year)
        self.assertEqual(
            own.action_open_tna_entries()['id'],
            self.env.ref('employee_development_system.action_eds_tna_entry_own').id,
        )
        self.assertEqual(manager.team_tna_submissions, 0)  # Draft needs are not submissions.
        self.assertGreaterEqual(officer.total_tna_entries, 1)
        self.assertEqual(own.action_open_sessions()['res_model'], 'eds.enrollment')
        self.assertEqual(manager.action_open_sessions()['res_model'], 'eds.enrollment')
        self.assertEqual(officer.action_open_sessions()['res_model'], 'eds.session')
        self.assertEqual(officer.action_open_completed_sessions()['res_model'], 'eds.session')
        self.assertEqual(officer.total_tna_entries, self.env['eds.tna.entry'].sudo().search_count(
            officer.action_open_tna_entries()['domain']))
        self.assertEqual(officer.published_plans_count, self.env['eds.annual.plan'].sudo().search_count(
            officer.action_open_annual_plans()['domain']))
        self.assertEqual(officer.upcoming_sessions_count, self.env['eds.session'].sudo().search_count(
            officer.action_open_sessions()['domain']))
        self.assertEqual(officer.completed_sessions_count, self.env['eds.session'].sudo().search_count(
            officer.action_open_completed_sessions()['domain']))
        self.assertEqual(own.my_certificates_count, self.env['eds.certificate'].sudo().search_count(
            own.action_open_certificates()['domain']))
        with self.assertRaises(UserError):
            own.action_open_annual_plans()
        with self.assertRaises(UserError):
            own.action_open_completed_sessions()

        self.own_need.with_user(self.employee_user).action_submit()
        manager.invalidate_recordset()
        self.assertEqual(manager.team_tna_submissions, 1)
        self.assertEqual(manager.team_tna_submissions, self.env['eds.tna.entry'].sudo().search_count(
            manager.action_open_tna_entries()['domain']))

    def test_dashboard_counts_only_actionable_sessions_and_invitations(self):
        now = fields.Datetime.now()
        start = now + timedelta(days=3)

        def session(status='scheduled', starts=start, ends=None, deadline=None):
            response_deadline = (deadline if deadline is not None else
                                 min(now + timedelta(days=1), starts - timedelta(hours=1)))
            record = self.env['eds.session'].create({
                'course_id': self.course.id,
                'date_start': starts,
                'date_end': ends or starts + timedelta(hours=8),
                'response_deadline': response_deadline,
            })
            record.sudo().write({'status': status})
            return record

        upcoming = session()
        another_upcoming = session()
        expired = session(deadline=now - timedelta(minutes=1))
        past = session(starts=now - timedelta(days=3),
                       ends=now - timedelta(days=2))
        draft = session(status='draft')
        completed = session(status='completed', starts=now - timedelta(days=3),
                            ends=now - timedelta(days=2))
        Enrollment = self.env['eds.enrollment']
        invited = Enrollment.create({
            'session_id': upcoming.id, 'employee_id': self.employee.id,
            'state': 'invited'})
        Enrollment.create({
            'session_id': another_upcoming.id, 'employee_id': self.employee.id,
            'state': 'enrolled'})
        Enrollment.create({
            'session_id': another_upcoming.id, 'employee_id': self.other_employee.id,
            'state': 'enrolled'})
        expired_invitation = Enrollment.create({
            'session_id': expired.id, 'employee_id': self.employee.id,
            'state': 'invited'})
        past_invitation = Enrollment.create({
            'session_id': past.id, 'employee_id': self.employee.id,
            'state': 'invited'})
        draft_invitation = Enrollment.create({
            'session_id': draft.id, 'employee_id': self.employee.id,
            'state': 'invited'})
        own = self.env['eds.dashboard'].with_user(self.employee_user).create({})
        manager = self.env['eds.dashboard'].with_user(self.manager_user).create({})
        officer = self.env['eds.dashboard'].with_user(self.officer_user).create({})

        self.assertEqual(own.my_pending_invitations, 1)
        self.assertEqual(own.my_upcoming_sessions, 1)
        self.assertEqual(manager.pending_team_nominations, 1)
        self.assertEqual(manager.team_confirmed_seats, 1)
        self.assertIn(upcoming, self.env['eds.session'].search(officer.action_open_sessions()['domain']))
        self.assertNotIn(past, self.env['eds.session'].search(officer.action_open_sessions()['domain']))
        self.assertIn(completed, self.env['eds.session'].search(
            officer.action_open_completed_sessions()['domain']))
        pending_ids = self.env['eds.enrollment'].search(own.action_open_nominations()['domain']).ids
        self.assertIn(invited.id, pending_ids)
        self.assertNotIn(expired_invitation.id, pending_ids)
        self.assertNotIn(past_invitation.id, pending_ids)
        self.assertNotIn(draft_invitation.id, pending_ids)

        invited.sudo().write({'state': 'enrolled'})
        own.invalidate_recordset()
        manager.invalidate_recordset()
        self.assertEqual(own.my_pending_invitations, 0)
        self.assertEqual(own.my_upcoming_sessions, 2)
        self.assertEqual(manager.pending_team_nominations, 0)
        self.assertEqual(manager.team_confirmed_seats, 2)
        self.assertEqual(self.env['eds.enrollment'].search_count(
            own.action_open_sessions()['domain']), own.my_upcoming_sessions)
        self.assertEqual(self.env['eds.enrollment'].search_count(
            manager.action_open_sessions()['domain']), manager.team_confirmed_seats)

    def test_direct_workflow_writes_are_rejected(self):
        need = self.own_need.with_user(self.employee_user)
        with self.assertRaises(UserError):
            need.write({'state': 'approved'})
        need.action_submit()
        with self.assertRaises(UserError):
            need.write({'justification': 'Changed after submission'})

        plan = self.env['eds.annual.plan'].sudo().create({
            'fiscal_year': '2199',
        })
        with self.assertRaises(UserError):
            plan.with_user(self.officer_user).write({'state': 'published'})
        line = self.env['eds.annual.plan.line'].sudo().create({
            'plan_id': plan.id, 'course_id': self.course.id,
            'program_name': self.course.name,
        })
        plan.sudo().write({'state': 'published'})
        with self.assertRaises(UserError):
            line.with_user(self.officer_user).write({'program_name': 'Unauthorized change'})

    def test_sessions_are_visible_only_to_invited_people_and_team(self):
        start = fields.Datetime.now() + timedelta(days=3)
        Session = self.env['eds.session']
        own_session = Session.create({
            'course_id': self.course.id, 'date_start': start,
            'date_end': start + timedelta(hours=8),
        })
        other_session = Session.create({
            'course_id': self.course.id, 'date_start': start + timedelta(days=1),
            'date_end': start + timedelta(days=1, hours=8),
        })
        self.env['eds.enrollment'].create({
            'session_id': own_session.id, 'employee_id': self.employee.id,
            'state': 'invited',
        })
        self.env['eds.enrollment'].create({
            'session_id': other_session.id, 'employee_id': self.other_employee.id,
            'state': 'invited',
        })
        with self.assertRaises(UserError):
            own_session.with_user(self.officer_user).write({'status': 'completed'})
        with self.assertRaises(UserError):
            own_session.with_user(self.officer_user).action_confirm()
        domain = [('id', 'in', (own_session | other_session).ids)]
        self.assertEqual(Session.with_user(self.employee_user).search(domain), own_session)
        self.assertEqual(Session.with_user(self.manager_user).search(domain), own_session)
        self.assertEqual(Session.with_user(self.officer_user).search(domain), own_session | other_session)

    def test_plan_delivery_uses_current_enrollment_states_and_paid_costs(self):
        plan = self.env['eds.annual.plan'].create({'fiscal_year': '2097'})
        line = self.env['eds.annual.plan.line'].create({
            'plan_id': plan.id, 'course_id': self.course.id,
            'program_name': self.course.name, 'planned_participants': 2,
        })
        start = fields.Datetime.now() + timedelta(days=3)
        session = self.env['eds.session'].create({
            'plan_line_id': line.id, 'date_start': start,
            'date_end': start + timedelta(hours=8),
        })
        enrollment = self.env['eds.enrollment'].create({
            'session_id': session.id, 'employee_id': self.employee.id,
            'state': 'enrolled',
        })
        cost = self.env['eds.cost'].create({
            'session_id': session.id, 'currency_id': line.budget_currency_id.id,
            'amount': 100, 'payment_state': 'paid',
        })
        self.assertEqual(line.actual_participants, 1)
        self.assertEqual(line.actual_cost, 100)
        self.assertTrue(cost.payment_date)
        cost_rows = self.env['eds.cost']._read_group(
            [('id', '=', cost.id)], ['currency_id', 'payment_date:day'], ['amount:sum'])
        self.assertEqual(cost_rows[0][2], 100)
        cost.amount = 150
        self.assertEqual(line.actual_cost, 150)
        enrollment.state = 'cancelled'
        self.assertEqual(line.actual_participants, 0)
