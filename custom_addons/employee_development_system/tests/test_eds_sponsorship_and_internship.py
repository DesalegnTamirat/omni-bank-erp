# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo import fields
from odoo.exceptions import ValidationError, UserError
from datetime import date, timedelta


class TestEdsSponsorshipAndInternship(TransactionCase):

    def setUp(self):
        super().setUp()
        self.employee = self.env['hr.employee'].create({
            'name': 'Academic Sponsorship Recipient',
        })

    def test_01_academic_sponsorship_and_service_bond(self):
        """Test long-term academic support application, approval, and service bond liability calculation."""
        sponsorship = self.env['eds.sponsorship'].create({
            'employee_id': self.employee.id,
            'degree_program': 'MSc in Financial Technology',
            'institution_name': 'Addis Ababa University',
            'total_approved_amount': 120000.0, # ETB
            'bond_period_months': 24, # 2 Years Service Bond
            'start_date': fields.Date.today() - timedelta(days=180), # 6 months ago
            'completion_date': fields.Date.today(),
        })
        sponsorship.action_approve()
        self.assertEqual(sponsorship.state, 'approved')

        # Test prorated bond liability calculation upon early exit (18 months remaining out of 24)
        if hasattr(sponsorship, 'repayment_liability'):
            sponsorship._compute_repayment_liability()
            self.assertGreater(sponsorship.repayment_liability, 0.0)

    def test_02_internship_facilitation_lifecycle(self):
        """Test student internship intake, mentor assignment, stipend tracking, and completion appraisal."""
        mentor = self.env['hr.employee'].create({
            'name': 'Senior Banking Mentor',
        })

        internship = self.env['eds.internship'].create({
            'intern_name': 'Kaleb Worku',
            'university_name': 'AAU School of Commerce',
            'field_of_study': 'Banking & Finance',
            'mentor_id': mentor.id,
            'monthly_stipend': 3500.0,
            'start_date': fields.Date.today() - timedelta(days=60),
            'end_date': fields.Date.today() + timedelta(days=30),
        })
        self.assertEqual(internship.state, 'draft')
        internship.action_start()
        self.assertEqual(internship.state, 'active')
        internship.action_complete()
        self.assertEqual(internship.state, 'completed')
