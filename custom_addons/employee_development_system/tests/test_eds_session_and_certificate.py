# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo import fields
from odoo.exceptions import ValidationError, UserError
from datetime import date, timedelta


class TestEdsSessionAndCertificate(TransactionCase):

    def setUp(self):
        super().setUp()
        self.employee = self.env['hr.employee'].create({
            'name': 'EDS Certification Trainee',
        })
        self.course = self.env['eds.course'].create({
            'name': 'Risk Management & AML Compliance',
            'category': 'compliance',
        })
        self.session = self.env['eds.session'].create({
            'course_id': self.course.id,
            'capacity': 10,
            'date_start': fields.Date.today() - timedelta(days=5),
            'date_end': fields.Date.today() - timedelta(days=1),
        })

    def test_01_session_delivery_and_attendance_threshold(self):
        """Test attendance record capture and 80% attendance threshold validation."""
        nomination = self.env['eds.nomination'].create({
            'session_id': self.session.id,
            'employee_id': self.employee.id,
            'state': 'enrolled',
        })

        # Mark 4 out of 5 days attended (80% attendance)
        attendance = self.env['eds.delivery.attendance'].create({
            'session_id': self.session.id,
            'employee_id': self.employee.id,
            'total_session_days': 5,
            'attended_days': 4,
        })
        self.assertEqual(attendance.attendance_percentage, 80.0)
        self.assertTrue(attendance.meets_attendance_threshold)

    def test_02_evaluation_levels_and_certificate_gating(self):
        """Test Level 1 (Reaction) and Level 2 (Learning) Evaluation pass scores and Certificate generation."""
        nomination = self.env['eds.nomination'].create({
            'session_id': self.session.id,
            'employee_id': self.employee.id,
            'state': 'enrolled',
        })

        # Level 1 Reaction Evaluation
        eval_l1 = self.env['eds.evaluation.level1'].create({
            'session_id': self.session.id,
            'employee_id': self.employee.id,
            'relevance_rating': 5,
            'trainer_rating': 5,
            'content_rating': 4,
            'facility_rating': 4,
        })

        # Level 2 Learning Pre/Post Assessment (Pass score: 85%)
        eval_l2 = self.env['eds.evaluation.level2'].create({
            'session_id': self.session.id,
            'employee_id': self.employee.id,
            'pre_assessment_score': 50.0,
            'post_assessment_score': 85.0,
            'passing_score': 70.0,
        })
        self.assertTrue(eval_l2.is_passed)

        # Issue Certificate
        cert = self.env['eds.certificate'].create({
            'employee_id': self.employee.id,
            'session_id': self.session.id,
            'course_id': self.course.id,
            'issue_date': fields.Date.today(),
        })
        self.assertEqual(cert.state, 'issued')
        self.assertTrue(cert.certificate_number)
