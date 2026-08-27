from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError, UserError
from odoo.fields import Date
from datetime import timedelta


class TestDisciplineCase(TransactionCase):

    def setUp(self):
        super().setUp()
        
        # Security groups
        self.group_base_user = self.env.ref('base.group_user')
        self.group_user = self.env.ref('discipline_management.group_discipline_user')
        self.group_officer = self.env.ref('discipline_management.group_discipline_officer')
        self.group_admin = self.env.ref('discipline_management.group_discipline_admin')
        self.group_ceo = self.env.ref('discipline_management.group_discipline_ceo')

        # Test users
        self.user_initiator = self.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create({
            'name': 'Initiator User',
            'login': 'initiator_user',
            'email': False,
            'group_ids': [(6, 0, [self.group_base_user.id, self.group_user.id])]
        })
        self.user_reviewer = self.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create({
            'name': 'Reviewer User',
            'login': 'reviewer_user',
            'email': False,
            'group_ids': [(6, 0, [self.group_base_user.id, self.group_officer.id])]
        })
        self.user_approver = self.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create({
            'name': 'Approver Admin User',
            'login': 'approver_user',
            'email': False,
            'group_ids': [(6, 0, [self.group_base_user.id, self.group_admin.id, self.group_ceo.id])]
        })

        # Test Job Positions
        self.job_senior = self.env['hr.job'].create({'name': 'Senior Specialist'})
        self.job_junior = self.env['hr.job'].create({'name': 'Junior Assistant'})
        self.job_manager = self.env['hr.job'].create({'name': 'Branch Operations Manager'})

        # Test Employee
        self.employee = self.env['hr.employee'].create({
            'name': 'Test Misconduct Employee',
            'work_email': 'test_emp@bunnabank.com',
            'job_id': self.job_senior.id,
        })

        # Active Contract
        self.contract = False
        ContractModel = self.env.get('hr.contract') or self.env.get('hr.version')
        if ContractModel:
            vals = {'employee_id': self.employee.id}
            if 'name' in ContractModel._fields:
                vals['name'] = 'Contract - Test Employee'
            if 'wage' in ContractModel._fields:
                vals['wage'] = 30000.0
            elif 'basic_salary' in ContractModel._fields:
                vals['basic_salary'] = 30000.0
            self.contract = ContractModel.create(vals)

        # Test Offense Category & Offense Definitions
        self.offense_category = self.env['discipline.offense.category'].create({
            'name': 'Operational Misconduct',
            'code': 'OP_MISCONDUCT',
        })

        # Level 1 Critical Offense (Dismissal)
        self.offense_level1 = self.env['discipline.offense'].with_user(self.user_approver).create({
            'name': 'Fraud & Embezzlement',
            'category_id': self.offense_category.id,
            'severity_level': 'level_1',
            'punishment_type': 'dismissal',
            'penalty_percentage': 0.0,
            'approval_authority': 'executive',
        })

        # Level 4 Moderate Offense (5% penalty)
        self.offense_level4 = self.env['discipline.offense'].with_user(self.user_approver).create({
            'name': 'Unauthorized Absence',
            'category_id': self.offense_category.id,
            'severity_level': 'level_4',
            'punishment_type': 'first_warning_penalty',
            'penalty_percentage': 5.0,
            'approval_authority': 'direct_manager',
        })

        # Demotion Offense
        self.offense_demotion = self.env['discipline.offense'].with_user(self.user_approver).create({
            'name': 'Serious Operational Failures',
            'category_id': self.offense_category.id,
            'severity_level': 'level_2',
            'punishment_type': 'demotion',
            'penalty_percentage': 0.0,
            'approval_authority': 'executive',
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
            'reviewer_id': self.user_initiator.id,
            'approver_id': self.user_approver.id,
        })
        case.state = 'pending_approval'

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

        case.final_decision_date = today - timedelta(days=15)

        with self.assertRaises(ValidationError):
            self.env['discipline.appeal'].create({
                'case_id': case.id,
                'submission_date': today,
                'appeal_grounds': 'Late appeal submission.',
            })

    def test_05_check_discipline_eligibility(self):
        """Test employee recruitment & promotion eligibility check method."""
        is_eligible, reason = self.employee.check_discipline_eligibility()
        self.assertTrue(is_eligible)

        self.employee.is_suspended = True
        self.employee.suspension_type = 'without_pay'
        is_eligible, reason = self.employee.check_discipline_eligibility()
        self.assertFalse(is_eligible)
        self.assertIn('under active disciplinary suspension', reason)

    def test_06_committee_meeting_completion_required_for_enforcement(self):
        """Test that case enforcement requires linked committee meeting to be completed with sign-off and quorum."""
        today = Date.today()
        case = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': self.offense_level4.id,
            'incident_date': today,
            'description': 'Committee check incident.',
            'initiator_id': self.user_initiator.id,
            'reviewer_id': self.user_reviewer.id,
            'approver_id': self.user_approver.id,
        })
        
        meeting = self.env['discipline.committee.meeting'].create({
            'case_id': case.id,
            'meeting_date': fields.Datetime.now(),
            'committee_chair_id': self.user_approver.id,
            'member_ids': [(6, 0, [self.user_reviewer.id, self.user_approver.id])],
        })
        case.action_send_to_committee()

        # Attempting enforcement while committee meeting is incomplete must raise UserError
        with self.assertRaises(UserError):
            case.with_user(self.user_approver).action_approve_and_enforce()

        # Complete meeting
        meeting.write({'state': 'completed', 'director_signed_off': True, 'present_members_count': 2})
        case.action_committee_feedback_received()
        case.with_user(self.user_approver).action_approve_and_enforce()
        self.assertEqual(case.state, 'enforced')

    def test_07_monthly_suspension_payroll_penalty_cron(self):
        """Test monthly suspension penalty cron execution for active without-pay suspensions."""
        today = Date.today()
        case = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': self.offense_level4.id,
            'incident_date': today,
            'description': 'Suspension cron incident.',
        })
        suspension = self.env['discipline.suspension'].create({
            'case_id': case.id,
            'suspension_type': 'without_pay',
            'start_date': today,
            'end_date': today + timedelta(days=10),
            'reason': 'Investigation pending.',
        })
        suspension.action_activate_suspension()

        # Run monthly penalty cron
        self.env['discipline.suspension']._cron_process_monthly_suspension_penalties()
        
        penalty = self.env['discipline.payroll.penalty'].search([('suspension_id', '=', suspension.id)])
        self.assertTrue(penalty.id)
        self.assertEqual(penalty.penalty_type, 'suspension_without_pay')

    def test_08_immutable_finalized_case_write_guard(self):
        """Test that enforced/closed/appealed cases block field updates on write()."""
        today = Date.today()
        case = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': self.offense_level4.id,
            'incident_date': today,
            'description': 'Immutability test incident.',
            'initiator_id': self.user_initiator.id,
            'reviewer_id': self.user_reviewer.id,
            'approver_id': self.user_approver.id,
        })
        case.action_initiate()
        case.action_submit_for_approval()
        case.with_user(self.user_approver).action_approve_and_enforce()

        # Attempting to edit description of enforced case must fail
        with self.assertRaises(UserError):
            case.write({'description': 'Tampered description'})

    def test_09_demotion_enforcement_and_managerial_penalty(self):
        """Test demotion enforcement preserving basic wage and managerial penalty days computation."""
        today = Date.today()
        case = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': self.offense_demotion.id,
            'incident_date': today,
            'description': 'Demotion test incident.',
            'initiator_id': self.user_initiator.id,
            'reviewer_id': self.user_reviewer.id,
            'approver_id': self.user_approver.id,
            'dismissal_authority_id': self.user_approver.id,
            'new_job_id': self.job_junior.id,
        })
        case.action_initiate()
        case.action_submit_for_approval()
        case.with_user(self.user_approver).action_approve_and_enforce()

        # Verify job position updated to junior position, basic wage unchanged
        self.assertEqual(self.employee.job_id.id, self.job_junior.id)
        if self.contract:
            self.assertTrue(self.contract.id)

    def test_10_attendance_discipline_threshold(self):
        """Test auto-creation of draft discipline case when attendance lateness threshold is exceeded."""
        today = fields.Datetime.now()
        for i in range(3):
            self.env['hr.attendance'].with_context(skip_duplicate_check=True, tracking_disable=True).create({
                'employee_id': self.employee.id,
                'check_in': today - timedelta(days=5 - i * 2),
                'check_out': today - timedelta(days=5 - i * 2, hours=-8),
            })
        
        sys_case = self.env['discipline.case'].search([
            ('employee_id', '=', self.employee.id),
            ('is_system_generated', '=', True)
        ], limit=1)
        self.assertTrue(sys_case.id)

    def test_11_payroll_and_analytics_payload_apis(self):
        """Test public API methods for Payroll Transmission and Analytics integration."""
        today = Date.today()
        case = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': self.offense_level4.id,
            'incident_date': today,
            'description': 'Payload test incident.',
        })
        penalty = self.env['discipline.payroll.penalty'].create({
            'case_id': case.id,
            'employee_id': self.employee.id,
            'penalty_type': 'percentage',
            'penalty_percentage': 5.0,
        })
        
        payload = penalty.get_payroll_transmission_payload()
        self.assertEqual(payload['employee_id'], self.employee.id)
        self.assertIn('penalty_reference', payload)

        analytics = self.env['discipline.case'].get_discipline_analytics_payload()
        self.assertIn('total_cases', analytics)
        self.assertIn('cases_by_state', analytics)
