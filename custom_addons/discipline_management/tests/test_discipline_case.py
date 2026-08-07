# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError, UserError
from odoo.fields import Date
from datetime import timedelta


class TestDisciplineCase(TransactionCase):

    def setUp(self):
        super().setUp()
        
        # Security groups
        self.group_user = self.env.ref('discipline_management.group_discipline_user')
        self.group_officer = self.env.ref('discipline_management.group_discipline_officer')
        self.group_admin = self.env.ref('discipline_management.group_discipline_admin')

        # Test users
        self.user_initiator = self.env['res.users'].create({
            'name': 'Initiator User',
            'login': 'initiator_user',
            'email': 'initiator@bunnabank.com',
            'groups_id': [(6, 0, [self.group_user.id])]
        })
        self.user_reviewer = self.env['res.users'].create({
            'name': 'Reviewer User',
            'login': 'reviewer_user',
            'email': 'reviewer@bunnabank.com',
            'groups_id': [(6, 0, [self.group_officer.id])]
        })
        self.user_approver = self.env['res.users'].create({
            'name': 'Approver Admin User',
            'login': 'approver_user',
            'email': 'approver@bunnabank.com',
            'groups_id': [(6, 0, [self.group_admin.id])]
        })

        # Test Employee
        self.employee = self.env['hr.employee'].create({
            'name': 'Test Misconduct Employee',
            'work_email': 'test_emp@bunnabank.com',
        })

        # Test Offense Category & Offense Definitions
        self.offense_category = self.env['discipline.offense.category'].create({
            'name': 'Operational Misconduct',
            'code': 'OP_MISCONDUCT',
        })

        # Level 1 Critical Offense (Dismissal)
        self.offense_level1 = self.env['discipline.offense'].sudo(self.user_approver).create({
            'name': 'Fraud & Embezzlement',
            'category_id': self.offense_category.id,
            'severity_level': 'level_1',
            'punishment_type': 'dismissal',
            'penalty_percentage': 0.0,
            'approval_authority': 'executive',
        })

        # Level 4 Moderate Offense (5% penalty)
        self.offense_level4 = self.env['discipline.offense'].sudo(self.user_approver).create({
            'name': 'Unauthorized Absence',
            'category_id': self.offense_category.id,
            'severity_level': 'level_4',
            'punishment_type': 'first_warning_penalty',
            'penalty_percentage': 5.0,
            'approval_authority': 'direct_manager',
        })

    def test_01_duplicate_case_prevention(self):
        """Test that duplicate active disciplinary cases on same incident date are blocked."""
        today = Date.today()
        self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': self.offense_level4.id,
            'incident_date': today,
            'description': 'First absence incident.',
        })

        # Attempting duplicate case on same date and offense should raise ValidationError
        with self.assertRaises(ValidationError):
            self.env['discipline.case'].create({
                'employee_id': self.employee.id,
                'offense_id': self.offense_level4.id,
                'incident_date': today,
                'description': 'Duplicate absence incident.',
            })

    def test_02_segregation_of_duties_constraint(self):
        """Test that Initiator, Reviewer, and Approver cannot be the same user."""
        today = Date.today()
        case = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': self.offense_level4.id,
            'incident_date': today,
            'description': 'Segregation test incident.',
            'initiator_id': self.user_initiator.id,
            'reviewer_id': self.user_initiator.id, # Same as initiator!
            'approver_id': self.user_approver.id,
        })
        case.state = 'pending_approval'

        # Enforcement should fail due to Initiator == Reviewer
        with self.assertRaises(ValidationError):
            case.with_user(self.user_approver).action_approve_and_enforce()

    def test_03_suspension_max_duration_constraint(self):
        """Test that suspension duration cannot exceed 30 working days."""
        today = Date.today()
        case = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': self.offense_level4.id,
            'incident_date': today,
            'description': 'Suspension test incident.',
        })

        # 40 calendar days ~ 28-30 working days. Let's make it 60 calendar days (over 30 working days).
        start_d = today
        end_d = today + timedelta(days=60)

        with self.assertRaises(ValidationError):
            self.env['discipline.suspension'].create({
                'case_id': case.id,
                'start_date': start_d,
                'end_date': end_d,
                'reason': 'Excessive suspension duration test.',
            })

    def test_04_appeal_window_constraint(self):
        """Test that appeals submitted after 10 calendar days are rejected by constraint."""
        today = Date.today()
        case = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': self.offense_level4.id,
            'incident_date': today - timedelta(days=20),
            'description': 'Appeal test incident.',
            'initiator_id': self.user_initiator.id,
            'reviewer_id': self.user_reviewer.id,
            'approver_id': self.user_approver.id,
        })
        case.action_initiate()
        case.action_submit_for_approval()
        case.with_user(self.user_approver).action_approve_and_enforce()

        # Set final_decision_date to 15 days ago
        case.final_decision_date = today - timedelta(days=15)

        # Attempting appeal submission today (15 days after decision) should fail (limit is 10 days)
        with self.assertRaises(ValidationError):
            self.env['discipline.appeal'].create({
                'case_id': case.id,
                'submission_date': today,
                'appeal_grounds': 'Late appeal submission.',
            })

    def test_05_check_discipline_eligibility(self):
        """Test employee recruitment & promotion eligibility check method."""
        # 1. Initially eligible
        is_eligible, reason = self.employee.check_discipline_eligibility()
        self.assertTrue(is_eligible)

        # 2. Suspend employee -> ineligible
        self.employee.is_suspended = True
        self.employee.suspension_type = 'without_pay'
        is_eligible, reason = self.employee.check_discipline_eligibility()
        self.assertFalse(is_eligible)
        self.assertIn('under active disciplinary suspension', reason)
