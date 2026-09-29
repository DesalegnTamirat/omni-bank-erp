# -*- coding: utf-8 -*-
from datetime import date, timedelta
from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import ValidationError


@tagged('post_install', '-at_install', 'eds', 'b5')
class TestEdsConstraints(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Bethlehem Tadesse',
        })
        cls.course = cls.env['eds.course'].create({
            'name': 'Customer Experience Excellence',
            'category': 'developmental',
        })
        today = date.today()
        cls.session = cls.env['eds.session'].create({
            'course_id': cls.course.id,
            'date_start': today + timedelta(days=5),
            'date_end': today + timedelta(days=7),
            'capacity': 20,
        })
        cls.manager_user = cls.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create({
            'name': 'L&D Manager Constraints Test',
            'login': 'ld_mgr_constraints_test_unique_b5',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('employee_development_system.group_eds_manager').id,
            ])],
        })

    def test_b5_renomination_after_cancellation_and_rejection(self):
        """B5: Test that re-nomination is allowed when prior nomination was withdrawn or rejected."""
        # 1. First nomination withdrawn
        nom1 = self.env['eds.nomination'].create({
            'session_id': self.session.id,
            'employee_id': self.employee.id,
            'state': 'withdrawn',
        })
        self.assertEqual(nom1.state, 'withdrawn')

        # 2. Second nomination for same session and employee succeeds
        nom2 = self.env['eds.nomination'].create({
            'session_id': self.session.id,
            'employee_id': self.employee.id,
            'state': 'submitted',
        })
        self.assertTrue(nom2.id)

        # 3. Third concurrent active nomination should fail
        with self.assertRaises(ValidationError):
            self.env['eds.nomination'].create({
                'session_id': self.session.id,
                'employee_id': self.employee.id,
                'state': 'submitted',
            })

    def test_b5_reenrollment_after_cancellation(self):
        """B5: Test that re-enrollment is allowed when prior enrollment was cancelled."""
        enr1 = self.env['eds.enrollment'].create({
            'session_id': self.session.id,
            'employee_id': self.employee.id,
            'state': 'cancelled',
        })
        self.assertEqual(enr1.state, 'cancelled')

        enr2 = self.env['eds.enrollment'].create({
            'session_id': self.session.id,
            'employee_id': self.employee.id,
            'state': 'enrolled',
        })
        self.assertTrue(enr2.id)

        with self.assertRaises(ValidationError):
            self.env['eds.enrollment'].create({
                'session_id': self.session.id,
                'employee_id': self.employee.id,
                'state': 'enrolled',
            })

    def test_b5_reissue_certificate_after_void(self):
        """B5: Test that certificate re-issuance is allowed after voiding a prior certificate."""
        cert1 = self.env['eds.certificate'].create({
            'session_id': self.session.id,
            'employee_id': self.employee.id,
            'state': 'issued',
        })
        # Void prior certificate
        cert1.with_user(self.manager_user).action_void()
        self.assertEqual(cert1.state, 'void')

        # Re-issuing for same session and employee succeeds
        cert2 = self.env['eds.certificate'].create({
            'session_id': self.session.id,
            'employee_id': self.employee.id,
            'state': 'pending',
        })
        self.assertTrue(cert2.id)

        # Another active certificate for same session and employee should fail
        with self.assertRaises(ValidationError):
            self.env['eds.certificate'].create({
                'session_id': self.session.id,
                'employee_id': self.employee.id,
                'state': 'pending',
            })
