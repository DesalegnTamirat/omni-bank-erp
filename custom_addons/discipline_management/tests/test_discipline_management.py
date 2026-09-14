# -*- coding: utf-8 -*-
from datetime import date, timedelta
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError, ValidationError


class TestDisciplineManagement(TransactionCase):
    """
    Automated Test Suite for Discipline Management Module.
    Covers end-to-end scenarios for direct manager enforcement, multi-tier escalation,
    committee workflows, suspensions, two-level appeals, and downstream payroll integrations.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Create Test Department
        cls.department = cls.env['hr.department'].create({
            'name': 'Retail Banking Directorate',
        })

        # Reference Security Groups
        cls.group_officer = cls.env.ref('discipline_management.group_discipline_officer')
        cls.group_manager = cls.env.ref('discipline_management.group_discipline_manager')
        cls.group_director = cls.env.ref('discipline_management.group_discipline_director')
        cls.group_chief = cls.env.ref('discipline_management.group_discipline_chief')
        cls.group_cpco = cls.env.ref('discipline_management.group_discipline_cpco')
        cls.group_pomd = cls.env.ref('discipline_management.group_discipline_pomd')
        cls.group_legal = cls.env.ref('discipline_management.group_discipline_legal')

        cls.user_manager = cls.env['res.users'].create({
            'name': 'Branch Line Manager',
            'login': 'manager_user_test',
            'email': 'manager@test.com',
            'group_ids': [(6, 0, [cls.group_manager.id])],
        })

        cls.user_director = cls.env['res.users'].create({
            'name': 'Retail Banking Director',
            'login': 'director_user_test',
            'email': 'director@test.com',
            'group_ids': [(6, 0, [cls.group_director.id])],
        })

        cls.user_cpco = cls.env['res.users'].create({
            'name': 'Chief People Officer',
            'login': 'cpco_user_test',
            'email': 'cpco@test.com',
            'group_ids': [(6, 0, [cls.group_cpco.id])],
        })

        cls.user_pomd = cls.env['res.users'].create({
            'name': 'POMD Secretary User',
            'login': 'pomd_user_test',
            'email': 'pomd@test.com',
            'group_ids': [(6, 0, [cls.group_pomd.id])],
        })

        # Set Department Manager
        cls.emp_director = cls.env['hr.employee'].create({
            'name': 'Retail Director Emp',
            'user_id': cls.user_director.id,
            'department_id': cls.department.id,
        })
        cls.department.manager_id = cls.emp_director

        # Create Non-Managerial Employee
        cls.user_emp_non_mgr = cls.env['res.users'].create({
            'name': 'Test Clerk Non-Mgr',
            'login': 'clerk_test',
            'email': 'clerk@test.com',
        })
        cls.emp_non_mgr = cls.env['hr.employee'].create({
            'name': 'Test Clerk Non-Mgr',
            'user_id': cls.user_emp_non_mgr.id,
            'department_id': cls.department.id,
            'is_managerial': False,
        })

        # Create Managerial Employee
        cls.user_emp_mgr = cls.env['res.users'].create({
            'name': 'Test Assistant Branch Manager',
            'login': 'abm_test',
            'email': 'abm@test.com',
        })
        cls.emp_mgr = cls.env['hr.employee'].create({
            'name': 'Test Assistant Branch Manager',
            'user_id': cls.user_emp_mgr.id,
            'department_id': cls.department.id,
            'is_managerial': True,
        })

        # Create RMCD / Audit Employee
        cls.audit_department = cls.env['hr.department'].create({
            'name': 'Internal Audit Directorate',
        })
        cls.emp_audit = cls.env['hr.employee'].create({
            'name': 'Senior Auditor Emp',
            'department_id': cls.audit_department.id,
            'is_managerial': False,
        })

        # Setup Offense Category and Offense
        cls.category = cls.env['discipline.offense.category'].create({
            'name': 'Operational Non-Compliance',
            'code': 'OP-01',
        })
        cls.offense = cls.env['discipline.offense'].create({
            'name': 'Unauthorized Cash Variance',
            'code': 'OFF-001',
            'category_id': cls.category.id,
            'severity_level': 'level_4',
        })

    def test_01_non_managerial_level_4_first_warning_enforcement(self):
        case = self.env['discipline.case'].with_user(self.user_manager).create({
            'employee_id': self.emp_non_mgr.id,
            'offense_id': self.offense.id,
            'incident_date': date.today(),
            'description': 'Minor cash drawer imbalance.',
            'initiator_type': 'manager',
            'severity_level': 'level_4',
            'punishment_type': 'first_written_warning',
            'penalty_percentage': 5.0,
            'warning_letter_type': 'first_warning',
        })
        self.assertEqual(case.state, 'draft')
        self.assertFalse(case.is_managerial)

        case.action_manager_enforce_penalty()

        self.assertEqual(case.state, 'enforced')
        self.assertTrue(case.has_generated_letter)
        self.assertTrue(self.emp_non_mgr.active_disciplinary_action)
        self.assertEqual(self.emp_non_mgr.disciplinary_warning_count, 1)

        payroll_penalties = self.env['discipline.payroll.penalty'].search([
            ('case_id', '=', case.id),
            ('employee_id', '=', self.emp_non_mgr.id)
        ])
        self.assertEqual(len(payroll_penalties), 1)
        self.assertEqual(payroll_penalties.penalty_type, 'percentage')
        self.assertEqual(payroll_penalties.penalty_percentage, 5.0)
        self.assertEqual(payroll_penalties.state, 'pending')

    def test_02_managerial_level_2_final_warning_enforcement(self):
        case = self.env['discipline.case'].with_user(self.user_manager).create({
            'employee_id': self.emp_mgr.id,
            'offense_id': self.offense.id,
            'incident_date': date.today(),
            'description': 'Failure to lock branch vault overnight.',
            'initiator_type': 'manager',
            'severity_level': 'level_2',
            'punishment_type': 'final_warning_penalty',
            'managerial_fine_days': 3,
            'warning_letter_type': 'final_warning',
        })
        self.assertTrue(case.is_managerial)

        case.action_manager_enforce_penalty()

        self.assertEqual(case.state, 'enforced')
        self.assertTrue(self.emp_mgr.is_ineligible_for_promotion_transfer)

        payroll_penalties = self.env['discipline.payroll.penalty'].search([
            ('case_id', '=', case.id),
            ('employee_id', '=', self.emp_mgr.id)
        ])
        self.assertEqual(len(payroll_penalties), 1)
        self.assertEqual(payroll_penalties.penalty_type, 'daily_wage')
        self.assertEqual(payroll_penalties.managerial_days, 3)

    def test_03_manager_dismissal_enforcement_restricted(self):
        case = self.env['discipline.case'].with_user(self.user_manager).create({
            'employee_id': self.emp_non_mgr.id,
            'offense_id': self.offense.id,
            'incident_date': date.today(),
            'description': 'Severe gross misconduct.',
            'initiator_type': 'manager',
            'severity_level': 'level_1',
            'punishment_type': 'dismissal',
        })

        with self.assertRaises(UserError):
            case.action_manager_enforce_penalty()

    def test_04_committee_workflow_and_investigation(self):
        case = self.env['discipline.case'].create({
            'employee_id': self.emp_non_mgr.id,
            'offense_id': self.offense.id,
            'incident_date': date.today(),
            'description': 'Severe audit irregularity involving cash shortage.',
            'initiator_type': 'head_office',
            'severity_level': 'level_1',
        })
        case.action_submit()
        self.assertEqual(case.state, 'submitted')

        case.action_director_approve()
        self.assertEqual(case.state, 'director_approved')

        case.action_chief_approve()
        self.assertEqual(case.state, 'committee')

        investigation = self.env['discipline.investigation'].create({
            'case_id': case.id,
            'employee_id': self.emp_non_mgr.id,
            'title': 'Audit Review on Cash Shortage',
            'introduction': 'Mandated investigation following internal audit findings.',
            'scope_limitations': 'Audited Q3 cash register records.',
            'summary_findings': 'Cash reconciliation revealed missing balance without ticket.',
            'financial_loss_amount': 50000.0,
            'loss_resolution_status': 'unresolved',
            'applicable_policy': 'Article 14 - Cash Handling Operations',
        })
        self.assertEqual(investigation.financial_loss_amount, 50000.0)

        committee = self.env['discipline.committee'].create({
            'case_id': case.id,
            'meeting_date': date.today() + timedelta(days=2),
            'location': 'HQ Boardroom 4B',
            'committee_chair_id': self.user_cpco.id,
            'respective_director_id': self.user_director.id,
            'pomd_secretary_id': self.user_pomd.id,
            'required_quorum_percentage': 75.0,
            'present_members_count': 3,
            'member_ids': [(6, 0, [self.user_cpco.id, self.user_director.id, self.user_pomd.id, self.user_manager.id])],
        })
        committee._compute_quorum()
        self.assertTrue(committee.is_quorum_met)

        committee.with_user(self.user_director).action_sign_off_director()
        self.assertTrue(committee.director_signed_off)
        self.assertEqual(committee.director_signoff_by_id, self.user_director)

    def test_05_non_managerial_suspension_pomd_approval(self):
        case = self.env['discipline.case'].create({
            'employee_id': self.emp_non_mgr.id,
            'offense_id': self.offense.id,
            'incident_date': date.today(),
            'description': 'Under investigation for ledger alteration.',
        })
        suspension = self.env['discipline.suspension'].create({
            'case_id': case.id,
            'employee_id': self.emp_non_mgr.id,
            'suspension_type': 'without_pay',
            'start_date': date.today(),
            'end_date': date.today() + timedelta(days=10),
            'reason': 'Pending formal investigation.',
        })
        self.assertEqual(suspension.suspending_authority, 'pomd')

        suspension.with_user(self.user_pomd).action_activate_suspension()
        self.assertEqual(suspension.state, 'active')
        self.assertTrue(self.emp_non_mgr.is_suspended)
        self.assertFalse(self.user_emp_non_mgr.active)

        suspension.action_reinstate_employee()
        self.assertEqual(suspension.state, 'completed')
        self.assertFalse(self.emp_non_mgr.is_suspended)
        self.assertTrue(self.user_emp_non_mgr.active)

    def test_06_suspension_max_30_working_days_limit(self):
        case = self.env['discipline.case'].create({
            'employee_id': self.emp_non_mgr.id,
            'offense_id': self.offense.id,
            'incident_date': date.today(),
            'description': 'Extended inquiry.',
        })
        with self.assertRaises(ValidationError):
            self.env['discipline.suspension'].create({
                'case_id': case.id,
                'employee_id': self.emp_non_mgr.id,
                'suspension_type': 'with_pay',
                'start_date': date.today(),
                'end_date': date.today() + timedelta(days=60),
                'reason': 'Excessive duration suspension request.',
            })

    def test_07_two_level_appeal_exoneration_reversal(self):
        case = self.env['discipline.case'].with_user(self.user_manager).create({
            'employee_id': self.emp_non_mgr.id,
            'offense_id': self.offense.id,
            'incident_date': date.today(),
            'description': 'Procedural non-compliance.',
            'initiator_type': 'manager',
            'severity_level': 'level_3',
            'punishment_type': 'second_written_warning',
            'penalty_percentage': 10.0,
            'warning_letter_type': 'second_warning',
        })
        case.action_manager_enforce_penalty()
        self.assertTrue(self.emp_non_mgr.active_disciplinary_action)

        appeal = self.env['discipline.appeal'].create({
            'case_id': case.id,
            'employee_id': self.emp_non_mgr.id,
            'appeal_level': 'first',
            'reason': 'Technical glitch caused late ticket posting.',
        })
        self.assertEqual(appeal.case_origin_type, 'manager')
        self.assertEqual(appeal.appeal_target_authority, 'directorate')

        appeal.action_start_review()
        appeal.write({
            'decision_outcome': 'overturned',
            'decision_reason': 'Evidence presented proved technical outage.',
        })
        appeal.action_render_decision()

        self.assertEqual(appeal.state, 'decided')
        self.assertFalse(self.emp_non_mgr.active_disciplinary_action)
        self.assertFalse(self.emp_non_mgr.is_ineligible_for_promotion_transfer)

        payroll_penalties = self.env['discipline.payroll.penalty'].search([
            ('case_id', '=', case.id),
            ('employee_id', '=', self.emp_non_mgr.id)
        ])
        self.assertTrue(all(p.state == 'cancelled' for p in payroll_penalties))

    def test_08_downstream_payroll_and_mobility_apis(self):
        case = self.env['discipline.case'].with_user(self.user_manager).create({
            'employee_id': self.emp_mgr.id,
            'offense_id': self.offense.id,
            'incident_date': date.today(),
            'description': 'Managerial breach.',
            'initiator_type': 'manager',
            'severity_level': 'level_2',
            'punishment_type': 'final_warning_penalty',
            'managerial_fine_days': 2,
            'warning_letter_type': 'final_warning',
        })
        case.action_manager_enforce_penalty()

        # 1. Downstream Payroll API
        pending_list = self.env['discipline.payroll.penalty'].get_pending_penalties(
            employee_id=self.emp_mgr.id,
            date_from=date.today() - timedelta(days=1),
            date_to=date.today() + timedelta(days=30),
            mark_processed=True
        )
        self.assertEqual(len(pending_list), 1)
        self.assertEqual(pending_list[0]['penalty_type'], 'daily_wage')
        self.assertEqual(pending_list[0]['managerial_days'], 2)

        penalty_rec = self.env['discipline.payroll.penalty'].browse(pending_list[0]['penalty_id'])
        self.assertEqual(penalty_rec.state, 'processed')

        # 2. Mobility Eligibility API: Standard promotion blocked
        eligible, reason = self.emp_mgr.check_discipline_eligibility(action_type='promotion')
        self.assertFalse(eligible)

        # 3. Mobility Eligibility API: Administrative / Forced transfer permitted
        forced_eligible, forced_reason = self.emp_mgr.check_discipline_eligibility(
            action_type='transfer', is_forced=True
        )
        self.assertTrue(forced_eligible)
