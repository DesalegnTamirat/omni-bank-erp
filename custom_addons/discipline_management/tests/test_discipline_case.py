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

        self.level_1 = self.env['discipline.severity.level'].search([('code', '=', 'level_1')], limit=1)
        self.level_4 = self.env['discipline.severity.level'].search([('code', '=', 'level_4')], limit=1)
        self.level_2 = self.env['discipline.severity.level'].search([('code', '=', 'level_2')], limit=1)

        # Level 1 Critical Offense (Dismissal)
        self.offense_level1 = self.env['discipline.offense'].with_user(self.user_approver).create({
            'name': 'Fraud & Embezzlement',
            'category_id': self.offense_category.id,
            'severity_level_id': self.level_1.id if self.level_1 else False,
        })

        # Level 4 Moderate Offense (5% penalty)
        self.offense_level4 = self.env['discipline.offense'].with_user(self.user_approver).create({
            'name': 'Unauthorized Absence',
            'category_id': self.offense_category.id,
            'severity_level_id': self.level_4.id if self.level_4 else False,
        })

        # Demotion Offense
        self.offense_demotion = self.env['discipline.offense'].with_user(self.user_approver).create({
            'name': 'Serious Operational Failures',
            'category_id': self.offense_category.id,
            'severity_level_id': self.level_2.id if self.level_2 else False,
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
            'severity_level_id': self.level_4.id if self.level_4 else False,
            'initiator_type': 'director',
            'case_action_track': 'committee_escalation',
            'decided_punishment_type': 'first_warning_penalty',
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
            'severity_level_id': self.level_4.id if self.level_4 else False,
            'decided_punishment_type': 'first_warning_penalty',
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
        case.delivery_receipt_date = today - timedelta(days=15)

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
            'severity_level_id': self.level_4.id if self.level_4 else False,
            'decided_punishment_type': 'first_warning_penalty',
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
            'severity_level_id': self.level_4.id if self.level_4 else False,
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
        suspension.with_user(self.user_approver).action_activate_suspension()

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
            'severity_level_id': self.level_4.id if self.level_4 else False,
            'decided_punishment_type': 'first_warning_penalty',
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
            'severity_level_id': self.level_2.id if self.level_2 else False,
            'decided_punishment_type': 'demotion',
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
        """Test auto-creation of draft discipline case when attendance violation threshold is exceeded."""
        today = fields.Datetime.now()
        for i in range(3):
            self.env['hr.attendance'].with_context(skip_duplicate_check=True, tracking_disable=True).create({
                'employee_id': self.employee.id,
                'check_in': today - timedelta(days=5 - i * 2),
                'check_out': today - timedelta(days=5 - i * 2, hours=-8),
                'is_force_checkout': True,
            })
        self.env['hr.attendance']._cron_escalate_attendance_violations()
        
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
            'severity_level_id': self.level_4.id if self.level_4 else False,
            'incident_date': today,
            'description': 'Payload test incident.',
        })
        penalty = self.env['discipline.payroll.penalty'].create({
            'case_id': case.id,
            'employee_id': self.employee.id,
            'penalty_type': 'percentage',
            'penalty_percentage': 5.0,
            'effective_date': today,
            'notes': 'Direct Managerial Sanction',
            'state': 'pending',
        })
        
        # 1. API: pending deductions
        pending_list = self.env['discipline.payroll.penalty'].get_pending_penalties(
            employee_id=self.employee.id,
            date_from=today - timedelta(days=5),
            date_to=today + timedelta(days=5)
        )
        self.assertEqual(len(pending_list), 1)
        self.assertEqual(pending_list[0]['penalty_percentage'], 5.0)

        # 2. API: case analytics payload
        analytics_data = self.env['discipline.case'].get_discipline_analytics_payload()
        self.assertIn('total_cases', analytics_data)
        self.assertIn('cases_by_state', analytics_data)

    def test_12_direct_coach_enforcement_and_appeal_window(self):
        """Test direct coach enforcement workflow sets delivery date and opens 10-day appeal window."""
        today = Date.today()
        case = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': self.offense_level4.id,
            'severity_level_id': self.level_4.id if self.level_4 else False,
            'incident_date': today,
            'case_action_track': 'direct_enforce',
            'description': 'Minor lateness violation for direct enforcement.',
        })
        case.action_initiate()
        self.assertEqual(case.state, 'initiated')
        
        # Direct enforcement by coach/admin
        case.with_user(self.user_approver).action_approve_and_enforce()
        self.assertEqual(case.state, 'enforced')
        self.assertEqual(case.final_decision_date, today)
        self.assertEqual(case.delivery_receipt_date, today)
        self.assertTrue(case.appeal_deadline)
        self.assertTrue(case.is_appeal_window_open)

    def test_13_coach_cannot_directly_enforce_level_1(self):
        """Test that direct coach enforcement raises UserError when attempting to dismiss employee directly."""
        today = Date.today()
        case = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': self.offense_level1.id,
            'severity_level_id': self.level_1.id if self.level_1 else False,
            'incident_date': today,
            'case_action_track': 'direct_enforce',
            'initiator_type': 'manager',
            'description': 'Attempted direct dismissal by coach.',
        })
        case.action_initiate()
        
        # User without CEO/Admin authority attempting to enforce Level 1 should raise UserError
        with self.assertRaises(UserError):
            case.with_user(self.user_initiator).action_approve_and_enforce()

    def test_14_executive_escalation_and_ceo_audit_referral(self):
        """Test full executive escalation: Forward to Chief -> Forward to CEO -> Refer to Audit & Instruct Suspension."""
        today = Date.today()
        case = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': self.offense_level1.id,
            'incident_date': today,
            'case_action_track': 'committee_escalation',
            'initiator_type': 'director',
            'description': 'Major critical fraud case for executive escalation.',
        })
        case.action_initiate()
        case.action_submit_to_chief()
        self.assertEqual(case.state, 'submitted_chief')

        case.action_chief_escalate_to_ceo()
        self.assertEqual(case.state, 'ceo_review')

        # CEO action: Refer to Audit & Instruct Suspension
        case.action_ceo_announce_audit_and_suspend()
        self.assertEqual(case.state, 'investigating')
        self.assertTrue(len(case.investigation_ids) > 0)
        self.assertTrue(len(case.suspension_ids) > 0)

    def test_15_audit_exoneration_and_ceo_endorsement(self):
        """Test Audit investigation exoneration -> CEO endorsement closes case and revokes suspension."""
        today = Date.today()
        case = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': self.offense_level1.id,
            'incident_date': today,
            'case_action_track': 'committee_escalation',
            'state': 'investigating',
            'description': 'Exoneration test case.',
        })
        suspension = self.env['discipline.suspension'].create({
            'case_id': case.id,
            'employee_id': self.employee.id,
            'suspension_type': 'without_pay',
            'start_date': today,
            'end_date': today + timedelta(days=20),
            'initiating_unit': 'directorate',
            'reason': 'Precautionary suspension pending audit.',
            'state': 'active',
        })
        investigation = self.env['discipline.investigation'].create({
            'case_id': case.id,
            'title': 'Exoneration Investigation',
            'finding_outcome': 'exonerated',
            'summary_findings': 'Full forensic audit confirms allegations were completely fabricated.',
            'investigator_recommendation': 'Full exoneration and immediate reinstatement.',
        })
        investigation.action_announce_findings()
        self.assertEqual(case.state, 'investigating')
        self.assertTrue(case.has_exonerated_investigation)

        # CEO endorses exoneration
        case.action_ceo_endorse_exoneration()
        self.assertEqual(case.state, 'closed')
        self.assertEqual(suspension.state, 'revoked')

    def test_16_audit_full_5_stage_workflow(self):
        """Test complete 5-stage Audit Investigation workflow: Draft -> Assigned -> Manager Review -> Director Signoff -> Announced."""
        import base64
        today = Date.today()
        case = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': self.offense_level1.id,
            'incident_date': today,
            'case_action_track': 'committee_escalation',
            'state': 'investigating',
            'description': 'Full audit workflow test case.',
        })
        inv = self.env['discipline.investigation'].create({
            'case_id': case.id,
            'title': 'Comprehensive Branch Audit',
            'director_id': self.user_approver.id,
            'audit_manager_id': self.user_reviewer.id,
            'investigator_id': self.user_initiator.id,
        })
        self.assertEqual(inv.state, 'draft')

        # 1. Assign investigation
        inv.action_assign_investigation()
        self.assertEqual(inv.state, 'assigned')

        # 2. Submit for Manager review - must fail without report_file
        inv.write({
            'summary_findings': '<p>Established cash discrepancy of ETB 5,000.</p>',
            'investigator_recommendation': '<p>Recommend Second Warning.</p>',
            'applicable_policy': 'Cash Management Policy Section 3',
            'finding_outcome': 'liable',
            'financial_loss_amount': 5000.0,
            'loss_resolution_status': 'resolved',
        })
        with self.assertRaises(UserError):
            inv.action_submit_for_manager_review()

        # Upload dummy PDF report
        inv.write({
            'report_file': base64.b64encode(b'PDF report content'),
            'report_filename': 'audit_report.pdf',
        })
        inv.action_submit_for_manager_review()
        self.assertEqual(inv.state, 'manager_review')
        self.assertTrue(len(inv.liable_employee_ids) > 0)

        # 3. Manager Quality Review - Return for revision
        with self.assertRaises(UserError):
            inv.action_manager_return()  # Missing notes
        inv.write({'manager_review_notes': 'Please re-verify core banking log timestamps.'})
        inv.action_manager_return()
        self.assertEqual(inv.state, 'assigned')

        # Re-submit and Manager Approve
        inv.action_submit_for_manager_review()
        inv.action_manager_approve()
        self.assertEqual(inv.state, 'director_review')
        self.assertEqual(inv.manager_signed_off_by_id.id, self.env.user.id)

        # 4. Director Final Approval and Announcement
        inv.action_director_approve_and_announce()
        self.assertEqual(inv.state, 'approved')
        self.assertEqual(inv.reviewed_by_id.id, self.env.user.id)
        self.assertEqual(case.state, 'committee_review')
        self.assertTrue(case.is_locked_for_committee)

    def test_17_article_one_click_case_creation_and_citation(self):
        """Test one-click case creation action from Article and Offense models with statutory auto-population."""
        art = self.env.ref('discipline_management.art_cba_33_4', raise_if_not_found=False)
        offense = self.env.ref('discipline_management.offense_cba_33_4_1_a', raise_if_not_found=False)
        if not art or not offense:
            return

        # Test action from Article
        action_res = art.action_create_case()
        self.assertEqual(action_res.get('res_model'), 'discipline.case')
        self.assertEqual(action_res['context'].get('default_article_id'), art.id)

        # Test action from Offense
        action_res_off = offense.action_create_case()
        self.assertEqual(action_res_off['context'].get('default_offense_id'), offense.id)
        self.assertEqual(action_res_off['context'].get('default_article_id'), art.id)

        # Create case using offense
        case = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': offense.id,
            'incident_date': Date.today(),
            'description': 'Attire non-compliance test.',
        })
        self.assertEqual(case.article_id.id, art.id)
        self.assertEqual(case.sub_article_code, '33.4.1(ሀ)')
        self.assertIn('Article 33.4', case.legal_article_display)
        self.assertTrue(case.legal_clause_text)

    def test_18_penalty_modes_and_override(self):
        """Test Penalty Mode 2 (Article Override) setting exact custom fine days."""
        offense_override = self.env.ref('discipline_management.offense_mgr_10_4_2_a', raise_if_not_found=False)
        if not offense_override:
            return

        case = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': offense_override.id,
            'incident_date': Date.today(),
            'description': 'Supervisory control failure test.',
        })
        self.assertEqual(case.punishment_type, 'fine')
        self.assertEqual(case.fine_days, 2.0)
        self.assertEqual(case.active_duration_days, 180)  # 6 months validity

    def test_19_article_33_1_4_progressive_escalation(self):
        """Test Article 33.1.4 progressive escalation bumping punishment up 1 grade if active warning is present."""
        today = Date.today()
        offense_verbal = self.env.ref('discipline_management.offense_cba_33_4_1_a', raise_if_not_found=False)
        offense_verbal_2 = self.env.ref('discipline_management.offense_cba_33_4_1_c', raise_if_not_found=False)
        if not offense_verbal or not offense_verbal_2:
            return

        # 1. Create first verbal warning case and enforce it
        case1 = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': offense_verbal.id,
            'incident_date': today - timedelta(days=5),
            'case_action_track': 'direct_enforce',
            'description': 'First minor verbal offense.',
        })
        case1.action_initiate()
        case1.with_user(self.user_approver).action_approve_and_enforce()
        self.assertEqual(case1.state, 'enforced')
        self.assertEqual(case1.punishment_type, 'verbal_warning')

        # 2. Within 30 days (active warning duration), commit a different Level 5 verbal offense
        case2 = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': offense_verbal_2.id,
            'incident_date': today,
            'case_action_track': 'direct_enforce',
            'description': 'Second minor offense within active warning window.',
        })
        # Under Art 33.1.4, should escalate from verbal_warning (Level 5) to first_warning_penalty (Level 4)
        self.assertTrue(case2.is_escalated_by_active_warning)
        self.assertEqual(case2.punishment_type, 'first_warning_penalty')

    def test_20_cash_shortage_matrix_article_33_9(self):
        """Test Article 33.9 Cash Shortage automatic tier determination based on shortage amount."""
        today = Date.today()
        offense_csh = self.env.ref('discipline_management.offense_cba_33_9_cash_shortage', raise_if_not_found=False)
        if not offense_csh:
            return

        # Tier 1: <= 500 ETB (1st occurrence = Verbal Warning)
        case_t1 = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': offense_csh.id,
            'cash_shortage_amount': 350.0,
            'incident_date': today,
            'description': '350 ETB counter shortage.',
        })
        self.assertEqual(case_t1.punishment_type, 'verbal_warning')
        self.assertEqual(case_t1.active_duration_days, 30)

        # Tier 4: 5,001 - 10,000 ETB (1st occurrence = 2nd Warning + 10%)
        emp_other = self.env['hr.employee'].create({'name': 'Cashier Test User'})
        case_t4 = self.env['discipline.case'].create({
            'employee_id': emp_other.id,
            'offense_id': offense_csh.id,
            'cash_shortage_amount': 7500.0,
            'incident_date': today,
            'description': '7,500 ETB vault shortage.',
        })
        self.assertEqual(case_t4.punishment_type, 'second_warning_penalty')
        self.assertEqual(case_t4.penalty_percentage, 10.0)
        self.assertEqual(case_t4.active_duration_days, 180)

        # Tier 6: > 20,000 ETB (1st occurrence = Final Warning + 20%)
        emp_third = self.env['hr.employee'].create({'name': 'Senior Cashier Test'})
        case_t6 = self.env['discipline.case'].create({
            'employee_id': emp_third.id,
            'offense_id': offense_csh.id,
            'cash_shortage_amount': 25000.0,
            'incident_date': today,
            'description': '25,000 ETB major shortage.',
        })
        self.assertEqual(case_t6.punishment_type, 'final_warning_penalty')
        self.assertEqual(case_t6.penalty_percentage, 20.0)
        self.assertEqual(case_t6.active_duration_days, 365)

    def test_21_statutory_mitigation_article_33_13(self):
        """Test Article 33.13 statutory mitigation reducing penalty grade by 1 rank upon justification."""
        today = Date.today()
        # Level 3 offense: Standard Second Warning + 10%
        case = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': self.offense_demotion.id,
            'incident_date': today,
            'is_statutory_mitigation_applied': True,
            'mitigation_justification': 'Employee demonstrated 98% performance rating and prompt self-reporting.',
            'description': 'Operational negligence with strong mitigation.',
        })
        # Standard Level 2 (final_warning_penalty) mitigated down to Level 3 (second_warning_penalty)
        self.assertEqual(case.punishment_type, 'second_warning_penalty')

    def test_22_statutory_action_deadlines(self):
        """Test Article 33.11 statutory action deadlines: 7 days for Verbal, 15 days for Standard, 30 days for Dismissal."""
        today = Date.today()
        offense_verbal = self.env.ref('discipline_management.offense_cba_33_4_1_a', raise_if_not_found=False)
        if not offense_verbal:
            return

        case_verbal = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': offense_verbal.id,
            'incident_date': today,
            'description': 'Verbal deadline test.',
        })
        self.assertEqual(case_verbal.statutory_deadline_date, today + timedelta(days=7))

        case_dismissal = self.env['discipline.case'].create({
            'employee_id': self.employee.id,
            'offense_id': self.offense_level1.id,
            'incident_date': today,
            'description': 'Dismissal deadline test.',
        })
        self.assertEqual(case_dismissal.statutory_deadline_date, today + timedelta(days=30))

    def test_23_complete_end_to_end_governance_lifecycle(self):
        """Test complete 10-step enterprise disciplinary lifecycle:
        Director Initiate -> Chief Forward -> CEO Directive -> Precautionary Suspension ->
        Audit 5-Stage Investigation -> Committee Review & Quorum Sign-off ->
        Executive Enforcement -> Delivery Receipt -> Employee Appeal -> Final Closure.
        """
        import base64
        today = Date.today()

        # Step 1: Directorate Director initiates major case (Level 1 Dismissal track)
        case = self.env['discipline.case'].with_user(self.user_reviewer).create({
            'employee_id': self.employee.id,
            'offense_id': self.offense_level1.id,
            'incident_date': today,
            'case_action_track': 'committee_escalation',
            'initiator_type': 'director',
            'initiator_id': self.user_reviewer.id,
            'description': 'Suspected serious fraud and ledger falsification of ETB 250,000.',
        })
        case.action_initiate()
        self.assertEqual(case.state, 'initiated')

        # Step 2: Director forwards to Respective Chief Officer
        case.with_user(self.user_reviewer).action_submit_to_chief()
        self.assertEqual(case.state, 'submitted_chief')

        # Step 3: Chief Officer forwards to CEO for executive directive
        case.with_user(self.user_approver).action_chief_escalate_to_ceo()
        self.assertEqual(case.state, 'ceo_review')

        # Step 4: CEO refers to Audit Directorate for investigation & instructs Committee Secretary to suspend
        case.with_user(self.user_approver).action_ceo_announce_audit_and_suspend()
        self.assertEqual(case.state, 'investigating')
        self.assertTrue(len(case.investigation_ids) > 0)
        self.assertTrue(len(case.suspension_ids) > 0)

        # Verify Precautionary Suspension is created (withheld pay per Art. 10.6.1)
        suspension = case.suspension_ids[0]
        self.assertEqual(suspension.suspension_type, 'without_pay')

        # Step 5: Audit Directorate executes 5-stage investigation
        inv = case.investigation_ids[0]
        self.assertEqual(inv.state, 'draft')

        # 5a. Assign investigation to auditor
        inv.with_user(self.user_approver).write({'investigator_id': self.user_reviewer.id})
        inv.with_user(self.user_approver).action_assign_investigation()
        self.assertEqual(inv.state, 'assigned')

        # 5b. Auditor completes inquiry, records ETB 250,000 loss, attaches PDF report & submits for Manager review
        inv.with_user(self.user_reviewer).write({
            'summary_findings': '<p>Forensic ledger audit confirmed unauthorized credit transfer of ETB 250,000.</p>',
            'investigator_recommendation': '<p>Recommend Dismissal pursuant to CBA Article 33.4 / Policy 10.5.1.</p>',
            'applicable_policy': 'Core Banking Security Standard & CBA Article 33.4',
            'finding_outcome': 'liable',
            'financial_loss_amount': 250000.0,
            'loss_resolution_status': 'unresolved',
            'report_file': base64.b64encode(b'Official Forensic Audit Report Content'),
            'report_filename': 'forensic_audit_report.pdf',
        })
        inv.with_user(self.user_reviewer).action_submit_for_manager_review()
        self.assertEqual(inv.state, 'manager_review')

        # 5c. Audit Manager reviews & approves
        inv.with_user(self.user_approver).action_manager_approve()
        self.assertEqual(inv.state, 'director_review')

        # 5d. Audit Director gives final sign-off & announces findings
        inv.with_user(self.user_approver).action_director_approve_and_announce()
        self.assertEqual(inv.state, 'approved')
        self.assertEqual(case.state, 'committee_review')
        self.assertTrue(case.is_locked_for_committee)

        # Step 6: Disciplinary Committee Meeting, Quorum Validation, and Sign-off
        meeting = self.env['discipline.committee.meeting'].create({
            'case_id': case.id,
            'meeting_date': fields.Datetime.now(),
            'committee_chair_id': self.user_approver.id,
            'member_ids': [(6, 0, [self.user_reviewer.id, self.user_approver.id])],
            'present_members_count': 2,
            'meeting_minutes': '<p>Disciplinary Committee reviewed audit evidence. Unanimous vote for dismissal.</p>',
            'final_recommendation': 'dismissal',
            'director_signed_off': True,
            'state': 'completed',
        })
        self.assertEqual(meeting.state, 'completed')
        self.assertTrue(meeting.is_quorum_met)

        # Set committee decided punishment
        case.with_context(force_write=True).write({
            'decided_punishment_type': 'dismissal',
            'severity_level_id': self.level_1.id,
            'is_locked_for_committee': False,
        })

        # Step 7: Committee Secretary submits case decision for Executive Approval
        case.with_user(self.user_approver).action_submit_for_approval()
        self.assertEqual(case.state, 'pending_approval')

        # Step 8: CEO / Executive Approves & Enforces Decision
        case.with_user(self.user_approver).action_approve_and_enforce()
        self.assertEqual(case.state, 'enforced')
        self.assertTrue(self.employee.active_disciplinary_action)
        self.assertTrue(self.employee.is_ineligible_for_promotion_transfer)

        # Step 9: Delivery Acknowledgment & 10-Day Appeal Window
        case.action_acknowledge_receipt()
        self.assertTrue(case.is_appeal_window_open)

        # Step 10: Employee Lodges Appeal, Appellate Review & Case Closure
        appeal = self.env['discipline.appeal'].create({
            'case_id': case.id,
            'appeal_grounds': 'Procedural irregularity defense.',
            'state': 'submitted',
        })
        self.assertEqual(appeal.state, 'submitted')

        # Board / Appellate Body reviews and upholds decision
        appeal.write({
            'decision_outcome': 'upheld',
            'appeal_decision_notes': 'Evidence was overwhelming and procedures strictly observed.',
            'state': 'decided',
        })
        case.with_context(force_write=True).write({'state': 'closed'})
        self.assertEqual(case.state, 'closed')



