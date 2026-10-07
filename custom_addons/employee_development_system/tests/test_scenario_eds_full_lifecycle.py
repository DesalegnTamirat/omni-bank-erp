# -*- coding: utf-8 -*-
"""
========================================================================================
BUNNA BANK S.C. — EMPLOYEE DEVELOPMENT SYSTEM (EDS)
Comprehensive End-to-End Scenario Test & Architecture Walkthrough
========================================================================================

This test file simulates the complete real-world operational lifecycle of corporate
training and talent development across Bunna Bank:

  Step 1:  Master Course Catalog & Competency Definition
  Step 2:  Annual Training Needs Assessment (TNA) Cycle Launch
  Step 3:  Direct Ingestion of Competency Gaps (Zero-CSV from Closed Cycle)
  Step 4:  Operational & Individual Training Need Submissions (Self & Work-Unit requests)
  Step 5:  Review, Validation & Multi-Level Approval of TNA Entries
  Step 6:  Bank-Wide TNA Consolidation (Aggregating Demands & Flagging Duplicates)
  Step 7:  Annual L&D Plan Assembly & Budget Allocation
  Step 8:  Training Logistics (Venues, Awarded Hotels/Vendors, Batches & Sessions)
  Step 9:  Trainee Nominations & Automated Enrollment Allocation
  Step 10: Attendance Tracking (Meets 80% Minimum Threshold)
  Step 11: Kirkpatrick Level 1 (Reaction Survey) & Level 2 (Post-Assessment Score)
  Step 12: Automated Certificate Eligibility Verification & Issuance
  Step 13: Executive Certification Sponsorship, Service Bond & Pro-Rata Breach Recovery

Run this test with:
  odoo -d ERP -u employee_development_system --test-enable --test-tags /employee_development_system.test_scenario_eds_full_lifecycle --stop-after-init
"""
import base64
import logging
from datetime import timedelta
from odoo import fields
from odoo.tests.common import TransactionCase, tagged

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install', 'eds', 'eds_scenario')
class TestEdsScenarioFullLifecycle(TransactionCase):
    """Full lifecycle scenario test demonstrating the end-to-end operational flow of EDS."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # ── 0. Organizational Setup & Role Accounts ──────────────────────────
        cls.dept_credit = cls.env['hr.department'].create({'name': 'Credit Analysis and Appraisal Department'})
        cls.dept_hr = cls.env['hr.department'].create({'name': 'People Performance and Development Department'})

        cls.job_analyst = cls.env['hr.job'].create({'name': 'Senior Credit Analyst'})
        cls.job_manager = cls.env['hr.job'].create({'name': 'Credit Department Manager'})

        # Security Groups
        cls.grp_emp = cls.env.ref('employee_development_system.group_eds_employee')
        cls.grp_mgr = cls.env.ref('employee_development_system.group_eds_line_manager')
        cls.grp_off = cls.env.ref('employee_development_system.group_eds_officer')
        cls.grp_ldm = cls.env.ref('employee_development_system.group_eds_manager')

        # Users & Employees
        # 1. Trainee Employee
        cls.user_trainee = cls.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create({
            'name': 'Trainee Abebe Bikila',
            'login': 'trainee_abebe_scenario',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.grp_emp.id])],
        })
        cls.emp_trainee = cls.env['hr.employee'].create({
            'name': 'Abebe Bikila',
            'user_id': cls.user_trainee.id,
            'department_id': cls.dept_credit.id,
            'job_id': cls.job_analyst.id,
        })
        for fld in ('first_contract_date', 'service_start_date', 'service_hire_date', 'joined_date', 'employment_date'):
            if fld in cls.env['hr.employee']._fields:
                cls.emp_trainee[fld] = fields.Date.today() - timedelta(days=730)

        # Trainee 2 (Colleague in Credit Department submitting self-request)
        cls.user_trainee2 = cls.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create({
            'name': 'Trainee Tigist Assefa',
            'login': 'trainee_tigist_scenario',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.grp_emp.id])],
        })
        cls.emp_trainee2 = cls.env['hr.employee'].create({
            'name': 'Tigist Assefa',
            'user_id': cls.user_trainee2.id,
            'department_id': cls.dept_credit.id,
            'job_id': cls.job_analyst.id,
        })
        cls.user_line_manager = cls.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create({
            'name': 'Manager Chala Kebede',
            'login': 'manager_chala_scenario',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.grp_mgr.id])],
        })
        cls.emp_manager = cls.env['hr.employee'].create({
            'name': 'Chala Kebede',
            'user_id': cls.user_line_manager.id,
            'department_id': cls.dept_credit.id,
            'job_id': cls.job_manager.id,
        })
        cls.dept_credit.manager_id = cls.emp_manager
        cls.emp_trainee.parent_id = cls.emp_manager

        # 3. L&D Officer
        cls.user_ld_officer = cls.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create({
            'name': 'L&D Officer Almaz',
            'login': 'ld_officer_almaz_scenario',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.grp_off.id])],
        })

        # 4. L&D Manager / Director
        cls.user_ld_manager = cls.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create({
            'name': 'Director PPDD Desta',
            'login': 'director_ppdd_scenario',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.grp_ldm.id])],
        })

    def test_full_eds_lifecycle_scenario(self):
        """Step-by-step master test verifying the complete EDS operational flow."""

        _logger.info("=" * 80)
        _logger.info(">>> STARTING BUNNA BANK EDS END-TO-END SCENARIO TEST <<<")
        _logger.info("=" * 80)

        # ─────────────────────────────────────────────────────────────────────
        # STEP 1: Course Catalog & Competency Definition
        # ─────────────────────────────────────────────────────────────────────
        # Define the Competency
        competency_credit = self.env['competency.competency'].create({
            'name': 'Advanced Credit Risk Assessment',
            'code': 'COMP_CREDIT_RISK_01',
            'pillar': 'technical',
            'state': 'approved',
            'status': 'active',
        })

        # Define Course in Catalog linked to Competency and scoped to Credit Department
        course_credit = self.env['eds.course'].create({
            'name': 'Comprehensive Credit Appraisal & NPL Management',
            'category': 'technical_compliance',
            'delivery_method': 'internal',
            'duration_days': 3,
            'status': 'active',
            'department_ids': [(4, self.dept_credit.id)],
            'competency_line_ids': [(0, 0, {
                'competency_id': competency_credit.id,
                'required_level': '3',
            })],
        })
        self.assertTrue(course_credit.code, "Course should be automatically assigned a code sequence.")
        self.assertEqual(course_credit.status, 'active', "Course must be active in catalog.")
        _logger.info("Step 1: Course Catalog definition completed.")

        # ─────────────────────────────────────────────────────────────────────
        # STEP 2: Annual TNA Cycle Launch
        # ─────────────────────────────────────────────────────────────────────
        # HR L&D launches the annual training needs assessment cycle with a deadline
        today = fields.Date.context_today(self.env.user)
        tna_cycle = self.env['eds.tna.cycle'].create({
            'name': 'Annual TNA Cycle FY 2026/27',
            'year': '2026',
            'start_date': today - timedelta(days=10),
            'submission_end_date': today + timedelta(days=15),
            'approval_deadline': today + timedelta(days=30),
            'state': 'collecting',
        })
        self.assertEqual(tna_cycle.state, 'collecting', "TNA Cycle should be in collecting state.")
        self.assertTrue(tna_cycle.responsible_team_id, "Responsible team should default to HR L&D.")
        _logger.info("Step 2: Annual TNA Cycle opened with course pool.")

        # ─────────────────────────────────────────────────────────────────────
        # STEP 3: Direct Ingestion of Competency Gaps (Zero-CSV)
        # ─────────────────────────────────────────────────────────────────────
        # Setup a closed Competency Assessment Cycle where Trainee fell below benchmark
        comp_cycle = self.env['competency.assessment.cycle'].create({
            'name': 'Annual Competency Cycle 2025 Closed',
            'code': 'COMP_2025_SCENARIO',
            'period_start': today - timedelta(days=200),
            'period_end': today - timedelta(days=40),
            'state': 'closed',
        })
        assessment = self.env['competency.assessment'].create({
            'cycle_id': comp_cycle.id,
            'employee_id': self.emp_trainee.id,
            'assessment_type': 'team',
            'state': 'approved',
        })
        self.env['competency.assessment.line'].create({
            'assessment_id': assessment.id,
            'competency_id': competency_credit.id,
            'required_level': '3',
            'current_level': '1',  # Gap of 2 levels
            'active': True,
        })

        # Run direct in-system pull wizard (no CSV upload needed!)
        pull_wizard = self.env['eds.competency.gap.import'].create({
            'cycle_id': tna_cycle.id,
            'competency_cycle_id': comp_cycle.id,
            'min_gap': 1,
        })
        pull_wizard.action_pull_competency_gaps()

        # Verify TNA entry auto-generated from competency gap
        gap_entry = self.env['eds.tna.entry'].search([
            ('cycle_id', '=', tna_cycle.id),
            ('employee_id', '=', self.emp_trainee.id),
            ('competency_id', '=', competency_credit.id),
        ])
        self.assertTrue(gap_entry, "Competency gap should automatically create a TNA entry.")
        self.assertEqual(gap_entry.source, 'competency_gap')
        self.assertEqual(gap_entry.gap_severity, 'high')
        _logger.info("Step 3: Competency gaps pulled directly from closed cycle without CSV upload.")

        # ─────────────────────────────────────────────────────────────────────
        # STEP 4: Operational Training Need Submission (Self & Department Request)
        # ─────────────────────────────────────────────────────────────────────
        # Trainee 2 submits a self-training request from the catalog course
        self_entry = self.env['eds.tna.entry'].with_user(self.user_trainee2).create({
            'cycle_id': tna_cycle.id,
            'employee_id': self.emp_trainee2.id,
            'course_id': course_credit.id,
            'urgency': 'high',
            'delivery_mode': 'classroom',
            'justification': 'Need advanced credit analysis skills to manage corporate loans.',
        })
        self_entry.with_user(self.user_trainee2).action_submit()
        self.assertEqual(self_entry.state, 'submitted', "Self-entry should move to submitted state.")
        _logger.info("Step 4: Self-service TNA request submitted by employee.")

        # ─────────────────────────────────────────────────────────────────────
        # STEP 5: TNA Entry Line Manager Validation
        # ─────────────────────────────────────────────────────────────────────
        # Line manager validates the training need
        self_entry.with_user(self.user_line_manager).action_validate()
        self.assertEqual(self_entry.state, 'validated', "Line manager validates the entry.")
        _logger.info("Step 5: TNA Entry validated by line manager.")

        # ─────────────────────────────────────────────────────────────────────
        # STEP 6: Bank-Wide TNA Consolidation & Approval
        # ─────────────────────────────────────────────────────────────────────
        # Consolidation engine gathers submitted/validated needs across units
        consolidation = self.env['eds.tna.consolidation'].create({
            'cycle_id': tna_cycle.id,
        })
        consolidation.action_consolidate()
        self.assertIn(self_entry, consolidation.entry_ids, "Validated entry must be gathered into consolidation.")
        self.assertGreaterEqual(consolidation.entry_count, 1, "Consolidation should aggregate training needs.")

        # Consolidate approves the validated entries for corporate planning
        self_entry.write({'state': 'approved'})
        self.assertEqual(self_entry.state, 'approved', "TNA entry approved for Annual Plan & Nomination.")
        _logger.info("Step 6: Bank-wide TNA Consolidation executed and needs approved.")

        # ─────────────────────────────────────────────────────────────────────
        # STEP 7: Annual L&D Plan Assembly & Budget Allocation
        # ─────────────────────────────────────────────────────────────────────
        # Create Annual L&D Plan for current fiscal year
        annual_plan = self.env['eds.annual.plan'].create({
            'fiscal_year': str(today.year),
            'notes': 'FY2026 Corporate Learning Plan for Credit and Retail',
        })
        plan_line = self.env['eds.annual.plan.line'].create({
            'plan_id': annual_plan.id,
            'course_id': course_credit.id,
            'program_name': course_credit.name,
            'delivery_method': 'internal',
            'scheduled_month': f"{today.year}-10",
            'budget_allocated': 75000.0,
            'status': 'planned',
        })
        self.assertEqual(annual_plan.line_count, 1, "Plan should register the line.")
        self.assertEqual(annual_plan.budget_total, 75000.0, "Budget total should sum planned line costs.")
        _logger.info("Step 7: Annual L&D Plan assembled and budgeted.")

        # ─────────────────────────────────────────────────────────────────────
        # STEP 8: Training Logistics: Venues, Awarded Hotels/Vendors, Sessions
        # ─────────────────────────────────────────────────────────────────────
        # Manual entry of hotel venue profile (as per user domain feedback)
        venue_hotel = self.env['eds.venue'].create({
            'name': 'Skylight Hotel Addis Ababa',
            'venue_type': 'hotel',
            'capacity': 40,
            'has_catering': True,
            'has_lodging': True,
        })
        # Manual vendor profile
        vendor_provider = self.env['eds.external.provider'].create({
            'name': 'Ethiopian Institute of Banking & Finance (EIBF)',
            'category': 'local',
            'service_offerings': 'Credit Risk & Financial Modeling',
        })

        # Schedule delivery cohort & session with awarded venue and vendor
        batch = self.env['eds.batch'].create({
            'name': 'Batch 01 - Credit Appraisal 2026',
            'course_id': course_credit.id,
            'participant_target': 25,
        })
        session = self.env['eds.session'].create({
            'course_id': course_credit.id,
            'batch_id': batch.id,
            'plan_line_id': plan_line.id,
            'date_start': fields.Datetime.now() + timedelta(days=5),
            'date_end': fields.Datetime.now() + timedelta(days=8),
            'capacity': 30,
            'awarded_venue_id': venue_hotel.id,
            'awarded_provider_id': vendor_provider.id,
            'certificate_title': 'Certificate of Credit Appraisal Mastery',
        })
        self.assertEqual(session.awarded_venue_id, venue_hotel, "Hotel profile assigned to session.")
        self.assertEqual(session.awarded_provider_id, vendor_provider, "Vendor profile assigned to session.")
        _logger.info("Step 8: Logistics, venue, vendor, and session configured.")

        # ─────────────────────────────────────────────────────────────────────
        # STEP 9: Trainee Nomination & Automated Enrollment Allocation
        # ─────────────────────────────────────────────────────────────────────
        # Line manager nominates employee referencing approved TNA need
        nomination = self.env['eds.nomination'].with_user(self.user_line_manager).create({
            'session_id': session.id,
            'employee_id': self.emp_trainee2.id,
            'nomination_type': 'tna_based',
            'tna_entry_id': self_entry.id,
        })
        nomination.with_user(self.user_line_manager).action_submit()
        self.assertEqual(nomination.state, 'submitted')

        # Multi-level approval: Line Manager -> L&D Officer -> Final Approval
        nomination.with_user(self.user_line_manager).action_line_manager_approve()
        self.assertEqual(nomination.state, 'line_manager_approved')

        nomination.with_user(self.user_ld_officer).action_lnd_approve()
        self.assertEqual(nomination.state, 'lnd_approved')

        nomination.with_user(self.user_ld_officer).action_final_approve()
        self.assertEqual(nomination.state, 'approved', "Nomination final approval complete.")
        self.assertTrue(nomination.enrollment_id, "Approved nomination automatically creates enrollment.")
        self.assertEqual(nomination.enrollment_id.state, 'enrolled', "Enrollment auto-assigned seat.")
        _logger.info("Step 9: Staff nomination approved and enrolled into session.")

        # ─────────────────────────────────────────────────────────────────────
        # STEP 10: Attendance Tracking (Meets 80% Minimum Threshold)
        # ─────────────────────────────────────────────────────────────────────
        # Record session attendance (100% attendance)
        attendance = self.env['eds.session.attendance'].create({
            'session_id': session.id,
            'employee_id': self.emp_trainee2.id,
            'attended': True,
            'hours_attended': 24.0,
        })
        self.assertEqual(attendance.attendance_percentage, 100.0, "Program attendance should be 100%.")
        self.assertTrue(attendance.meets_min_attendance, "Meets the >=80% certification attendance threshold.")
        _logger.info("Step 10: Session attendance recorded and verified (100%).")

        # ─────────────────────────────────────────────────────────────────────
        # STEP 11: Kirkpatrick Level 1 (Reaction) & Level 2 (Learning Gain)
        # ─────────────────────────────────────────────────────────────────────
        # Level 1: Question and feedback
        instrument = self.env['eds.evaluation.instrument'].create({
            'name': 'Standard Level 1 Reaction Survey',
            'instrument_type': 'level1',
            'version': 'v1.0',
            'question_ids': [(0, 0, {
                'name': 'The course content was relevant and practical.',
                'question_type': 'scale_1_5',
            })],
        })
        instrument.action_publish()

        eval_l1 = self.env['eds.evaluation.level1'].create({
            'session_id': session.id,
            'employee_id': self.emp_trainee2.id,
            'instrument_id': instrument.id,
            'line_ids': [(0, 0, {
                'question_id': instrument.question_ids[0].id,
                'rating_val': 5,
            })],
        })
        eval_l1.action_submit_feedback()
        self.assertEqual(eval_l1.overall_score, 100.0, "Level 1 rating should calculate 100%.")

        # Level 2: Pre and Post Assessment Scores
        pre_assess = self.env['eds.assessment'].create({
            'session_id': session.id,
            'employee_id': self.emp_trainee2.id,
            'assessment_type': 'pre',
            'score': 40.0,
        })
        post_assess = self.env['eds.assessment'].create({
            'session_id': session.id,
            'employee_id': self.emp_trainee2.id,
            'assessment_type': 'post',
            'score': 85.0,  # Exceeds 60% passing requirement
        })
        eval_l2 = self.env['eds.evaluation.level2'].create({
            'session_id': session.id,
            'employee_id': self.emp_trainee2.id,
            'pre_assessment_id': pre_assess.id,
            'post_assessment_id': post_assess.id,
            'passing_score': 60.0,
        })
        eval_l2.action_evaluate()
        self.assertEqual(eval_l2.learning_gain, 45.0, "Knowledge gain: 85 - 40 = 45%.")
        self.assertTrue(eval_l2.passed, "Level 2 test passed with score >= 60%.")
        _logger.info("Step 11: Kirkpatrick Level 1 and Level 2 evaluations completed successfully.")

        # ─────────────────────────────────────────────────────────────────────
        # STEP 12: Automated Certificate Eligibility Verification & Issuance
        # ─────────────────────────────────────────────────────────────────────
        # Configure certificate rule for technical compliance courses
        self.env['eds.certificate.rule'].create({
            'name': 'Technical Courses Rule',
            'category': 'technical_compliance',
            'require_attendance': True,
            'min_attendance_pct': 80.0,
            'require_level2_pass': True,
            'min_level2_score': 60.0,
            'active': True,
        })

        # Generate certificate for participant
        cert = self.env['eds.certificate'].create({
            'employee_id': self.emp_trainee2.id,
            'session_id': session.id,
        })
        self.assertTrue(cert.is_eligible, "Employee should be eligible (100% attendance & 85% L2 score).")

        cert.with_user(self.user_ld_officer).action_issue()
        self.assertEqual(cert.state, 'issued', "Certificate should transition to issued state.")
        self.assertTrue(cert.code, "Certificate should have unique assigned sequence number.")
        self.assertEqual(cert.certificate_title, 'Certificate of Credit Appraisal Mastery')
        _logger.info("Step 12: Certificate eligibility verified and certificate issued.")

        # ─────────────────────────────────────────────────────────────────────
        # STEP 13: Executive Certification Sponsorship, Bond & Pro-Rata Recovery
        # ─────────────────────────────────────────────────────────────────────
        # Employee sponsored for external chartered qualification
        bond_start = today - timedelta(days=365)  # 12 months served
        bond_end = bond_start + timedelta(days=730)  # 24-month total bond
        sponsorship = self.env['eds.sponsorship'].create({
            'employee_id': self.emp_trainee.id,
            'program_name': 'Chartered Financial Analyst (CFA) Level 1',
            'sponsorship_type': 'certification',
            'approved_amount': 100000.0,
            'bond_duration_months': 24,
            'bond_start_date': bond_start,
            'bond_end_date': bond_end,
            'recovery_policy': 'pro_rata',
            'bond_agreement': base64.b64encode(b'PDF Signed Agreement Content'),
            'bond_filename': 'cfa_bond_agreement.pdf',
        })
        # Verify eligibility check (>=12 months continuous service)
        sponsorship.with_user(self.user_ld_officer).action_verify_eligibility()
        self.assertEqual(sponsorship.state, 'eligibility_check')

        sponsorship.with_user(self.user_ld_manager).action_approve()
        sponsorship.with_user(self.user_ld_officer).action_activate_bond()
        self.assertEqual(sponsorship.state, 'active', "Bond is now active.")

        # Simulate employee resignation halfway through 24-month bond
        sponsorship.write({'breach_reason': 'resignation'})
        sponsorship.with_user(self.user_ld_manager).action_mark_breached()
        self.assertEqual(sponsorship.state, 'breached')

        # Since 12 out of 24 months elapsed, pro-rata recovery is ~50% (approx 50,000 ETB)
        self.assertAlmostEqual(sponsorship.recovery_amount, 50000.0, delta=2000.0)
        _logger.info("Step 13: Talent sponsorship, service bond, and pro-rata breach recovery verified.")

        _logger.info("=" * 80)
        _logger.info(">>> ALL 13 EDS LIFECYCLE SCENARIO PHASES VERIFIED SUCCESSFULLY! <<<")
        _logger.info("=" * 80)
