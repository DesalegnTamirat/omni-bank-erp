import uuid

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'eds', 'trainer_access')
class TestTrainerAccess(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        internal_group = cls.env.ref('base.group_user')
        officer_group = cls.env.ref('employee_development_system.group_eds_officer')
        suffix = uuid.uuid4().hex[:8]
        cls.trainer_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'EDS Trainer Access Test',
            'login': 'eds_trainer_access_' + suffix,
            'group_ids': [(6, 0, [internal_group.id])],
        })
        cls.officer_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'EDS Delivery Officer Test',
            'login': 'eds_delivery_officer_' + suffix,
            'group_ids': [(6, 0, [internal_group.id, officer_group.id])],
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'EDS Trainer Employee', 'user_id': cls.trainer_user.id,
        })
        cls.trainer = cls.env['eds.trainer'].create({
            'name': 'EDS Trainer Profile', 'trainer_type': 'internal',
            'employee_id': cls.employee.id, 'tot_certified': True,
        })
        cls.course = cls.env['eds.course'].create({'name': 'Trainer Access Course'})
        cls.assigned = cls.env['eds.session'].create({
            'course_id': cls.course.id,
            'date_start': '2026-10-20 08:00:00',
            'date_end': '2026-10-20 17:00:00',
            'trainer_ids': [(6, 0, [cls.trainer.id])],
        })
        cls.other = cls.env['eds.session'].create({
            'course_id': cls.course.id,
            'date_start': '2026-10-21 08:00:00',
            'date_end': '2026-10-21 17:00:00',
        })

    def test_trainer_has_only_assigned_session_read_access(self):
        self.assertTrue(self.trainer_user.has_group('employee_development_system.group_eds_trainer'))
        self.assertFalse(self.trainer_user.has_group('employee_development_system.group_eds_officer'))
        sessions = self.env['eds.session'].with_user(self.trainer_user).search([
            ('id', 'in', [self.assigned.id, self.other.id]),
        ])
        self.assertEqual(sessions, self.assigned)
        with self.assertRaises(AccessError):
            self.assigned.with_user(self.trainer_user).write({'notes': 'Unauthorized edit'})

    def test_trainer_cannot_read_or_record_attendance_and_scores(self):
        self.env['eds.enrollment'].create({
            'session_id': self.assigned.id, 'employee_id': self.employee.id,
            'state': 'enrolled',
        })
        self.env['eds.session.attendance'].create({
            'session_id': self.assigned.id, 'employee_id': self.employee.id,
            'attendance_date': '2026-10-20', 'attended': True,
        })
        self.assertTrue(self.env['eds.session.attendance'].with_user(self.officer_user).search([
            ('session_id', '=', self.assigned.id),
        ]))
        for model in ('eds.session.attendance', 'eds.assessment'):
            with self.subTest(model=model), self.assertRaises(AccessError):
                self.env[model].with_user(self.trainer_user).search([])
        with self.assertRaises(AccessError):
            self.assigned.with_user(self.trainer_user).read(['attendance_count'])
        with self.assertRaises(AccessError):
            self.assigned.with_user(self.trainer_user).action_mark_all_attended()
        with self.assertRaises(AccessError):
            self.assigned.with_user(self.trainer_user).action_export_attendance_xlsx()
        with self.assertRaises(AccessError):
            self.env['eds.assessment'].with_user(self.trainer_user).create({
                'session_id': self.assigned.id,
                'employee_id': self.employee.id,
                'assessment_type': 'pre',
                'score': 75,
            })

    def test_personal_session_view_contains_no_results(self):
        view = self.env.ref('employee_development_system.view_eds_session_trainer_form')
        result = self.env['eds.session'].with_user(self.trainer_user).get_views(
            [(view.id, 'form')], options={'toolbar': False})
        arch = result['views']['form']['arch']
        self.assertNotIn('attendance_ids', arch)
        self.assertNotIn('assessment_ids', arch)
        self.assertIn('course_id', arch)

    def test_assignment_notice_is_separate_from_assessment_notice(self):
        self.assigned._notify_assigned_trainers()
        assignment = self.assigned.message_ids.filtered(
            lambda message: 'assigned to deliver' in (message.body or ''))[:1]
        self.assertTrue(assignment)
        self.assertIn(self.trainer_user.partner_id, assignment.partner_ids)

        self.assigned._notify_assessment_coordinators('Record assessment scores')
        assessment = self.assigned.message_ids.filtered(
            lambda message: 'Record assessment scores' in (message.body or ''))[:1]
        self.assertTrue(assessment)
        self.assertIn(self.officer_user.partner_id, assessment.partner_ids)
        self.assertNotIn(self.trainer_user.partner_id, assessment.partner_ids)
