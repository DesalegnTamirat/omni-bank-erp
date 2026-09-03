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
        """Test that committee route enforcement requires all member signatures and completed state."""
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
        case.action_send_to_committee()
        
        meeting = case.committee_meeting_ids[0]
        # Attempting enforcement while committee meeting is incomplete must raise UserError
        with self.assertRaises(UserError):
            case.with_user(self.user_approver).action_approve_and_enforce()

        # Fill digital signatures for all statutory members
        for line in meeting.signature_line_ids:
            line.write({
                'signature': b'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
                'is_signed': True,
                'signed_date': fields.Date.context_today(self),
            })
        meeting.write({'state': 'completed'})
        case.with_user(self.user_approver).action_approve_and_enforce()
        self.assertEqual(case.state, 'enforced')

    def test_07_direct_decision_non_dismissal_by_manager(self):
        """Test manager can directly decide and enforce non-dismissal cases without committee."""
        today = Date.today()
        case = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': self.offense_level4.id,
            'incident_date': today,
            'description': 'Tardiness incident.',
            'initiator_id': self.user_initiator.id,
            'manager_id': self.user_initiator.id,
        })
        case.action_initiate()
        self.assertEqual(case.state, 'initiated')

        # Directly decide and enforce
        case.with_user(self.user_initiator).action_decide_and_enforce()
        self.assertEqual(case.state, 'enforced')
        self.assertTrue(self.employee.active_disciplinary_action)

    def test_08_direct_decision_dismissal_blocked(self):
        """Test manager/director cannot directly enforce dismissal (dismissal must go to committee)."""
        today = Date.today()
        case = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': self.offense_level1.id,
            'incident_date': today,
            'description': 'Severe theft incident.',
            'initiator_id': self.user_initiator.id,
        })
        case.action_initiate()
        
        # Calling action_decide_and_enforce on a dismissal case must raise UserError
        with self.assertRaises(UserError):
            case.action_decide_and_enforce()

    def test_09_escalation_chain_to_audit_and_ceo_notification(self):
        """Test escalation flow: Manager -> Director -> Chief -> Audit with automated CEO alert."""
        today = Date.today()
        case = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': self.offense_level1.id,
            'incident_date': today,
            'description': 'High severity financial embezzlement.',
            'initiator_id': self.user_initiator.id,
            'director_id': self.user_reviewer.id,
            'chief_id': self.user_reviewer.id,
            'ceo_id': self.user_approver.id,
        })
        case.action_initiate()
        self.assertEqual(case.state, 'initiated')

        # Step 1: Escalate to Director
        case.action_escalate_to_director()
        self.assertEqual(case.state, 'escalated_director')

        # Step 2: Escalate to Chief
        case.action_escalate_to_chief()
        self.assertEqual(case.state, 'escalated_chief')

        # Step 3: Chief forwards directly to Audit (CEO is automatically alerted per FR-DIS-012)
        case.action_chief_forward_to_audit()
        self.assertEqual(case.state, 'investigating')
        self.assertTrue(len(case.investigation_ids) > 0)

        # Step 4: Audit submits to Disciplinary Committee
        case.action_audit_submit_to_committee()
        self.assertEqual(case.state, 'committee_review')
        self.assertTrue(len(case.committee_meeting_ids) > 0)
        self.assertEqual(case.committee_meeting_ids[0].state, 'scheduling')

    def test_10_statutory_committee_secretary_and_signatures(self):
        """Test statutory committee secretary scheduling, deliberation lock, and sequential signatures."""
        today = Date.today()
        case = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': self.offense_level1.id,
            'incident_date': today,
            'description': 'Embezzlement audit case.',
        })
        case.action_audit_submit_to_committee()
        meeting = case.committee_meeting_ids[0]
        self.assertEqual(meeting.state, 'scheduling')

        # Secretary schedules
        meeting.action_schedule_and_notify()
        self.assertEqual(meeting.state, 'scheduled')

        # Hearing begins
        meeting.action_start_meeting()
        self.assertEqual(meeting.state, 'in_progress')

        # Secretary modifies punishment and requests signatures
        meeting.write({
            'decided_punishment_type': 'final_warning_penalty',
            'decided_penalty_percentage': 20.0,
            'meeting_minutes': 'Comprehensive defense heard. Sanction set to Final Warning + 20% penalty.',
        })
        meeting.action_request_signatures()
        self.assertEqual(meeting.state, 'signing')

        # Members sign sequentially: Director line must sign before Chair line
        dir_line = meeting.signature_line_ids.filtered(lambda l: l.role == 'director')
        chair_line = meeting.signature_line_ids.filtered(lambda l: l.role == 'chair')
        dummy_sig = b'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='

        # Chair attempting to sign before Director must be blocked
        with self.assertRaises(UserError):
            chair_line.write({'signature': dummy_sig})

        # All sign in correct order
        for line in meeting.signature_line_ids.sorted(key=lambda l: l.sign_sequence):
            line.write({'signature': dummy_sig})

        self.assertTrue(meeting.all_signed)

        # Finalize and enforce
        meeting.action_finalize_and_enforce()
        self.assertEqual(meeting.state, 'completed')
        self.assertEqual(case.state, 'enforced')
        self.assertEqual(case.punishment_type, 'final_warning_penalty')

    def test_11_attendance_discipline_coach_assignment(self):
        """Test attendance threshold breach auto-initiates case assigned to coach with reminder."""
        coach_emp = self.env['hr.employee'].create({
            'name': 'Assigned Coach',
            'user_id': self.user_initiator.id,
        })
        self.employee.coach_id = coach_emp.id

        today = fields.Datetime.now()
        for i in range(3):
            self.env['hr.attendance'].create({
                'employee_id': self.employee.id,
                'check_in': today - timedelta(days=5 - i),
                'check_out': today - timedelta(days=5 - i, hours=-2), # forced checkout / short duration
            })

        self.env['hr.attendance']._cron_escalate_attendance_violations()
        
        case = self.env['discipline.case'].search([
            ('employee_id', '=', self.employee.id),
            ('is_attendance_case', '=', True),
        ], limit=1)
        self.assertTrue(case.id)
        self.assertEqual(case.coach_id.id, coach_emp.id)
        self.assertEqual(case.state, 'initiated')

    def test_12_payroll_and_analytics_payload_apis(self):
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
