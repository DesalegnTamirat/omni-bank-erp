# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged
from odoo import fields


@tagged('post_install', '-at_install', 'eds', 'extended_pack')
class TestExtendedFormPack(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.department = cls.env['hr.department'].create({
            'name': 'Corporate Banking Division Test',
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Tadesse Gemechu Test 11',
            'department_id': cls.department.id,
            'identification_id': 'TESTEMP883',
            'barcode': 'TESTEMP883',
        })
        cls.manager = cls.env['hr.employee'].create({
            'name': 'Almaz Worku Manager 11',
            'department_id': cls.department.id,
            'identification_id': 'TESTMGR884',
            'barcode': 'TESTMGR884',
        })
        cls.course = cls.env['eds.course'].create({
            'name': 'Advanced Credit Risk Management',
            'code': 'ACRM-2026',
            'category': 'technical_compliance',
            'target_audience': 'all_staff',
            'status': 'active',
            'duration_days': 5.0,
        })
        now = fields.Datetime.now()
        cls.session = cls.env['eds.session'].create({
            'name': 'Advanced Credit Risk - Batch 1',
            'course_id': cls.course.id,
            'date_start': now,
            'date_end': now,
            'status': 'completed',
        })

    def test_01_eds_f_11_level4_roi_report(self):
        """Test EDS-F-11 Level 4 Business Impact and ROI Report creation, calculation, and PDF action."""
        l4 = self.env['eds.evaluation.level4'].create({
            'course_id': self.course.id,
            'session_id': self.session.id,
            'measurement_date': fields.Date.context_today(self),
            'total_program_cost': 50000.0,
            'estimated_financial_benefit': 125000.0,
            'impact_summary': 'Reduced loan default turnaround and enhanced recovery rates.',
            'sign_tl_lnd': 'Verified by Team Leader',
            'sign_director_ppdd': 'Approved by Director',
        })
        self.assertEqual(l4.roi_percentage, 150.0)

        kpi = self.env['eds.evaluation.level4.kpi'].create({
            'level4_id': l4.id,
            'kpi_name': 'NPL Reduction Ratio',
            'baseline_value': 4.5,
            'target_value': 3.0,
            'achieved_value': 2.7,
        })
        self.assertTrue(kpi.improvement_pct != 0.0)

        report_action = l4.action_print_form()
        self.assertIsNotNone(report_action)
        self.assertEqual(report_action.get('type'), 'ir.actions.report')

    def test_02_eds_f_12_knowledge_sharing(self):
        """Test EDS-F-12 Knowledge Sharing Debrief workflow, sequence, and PDF action."""
        ksh = self.env['eds.knowledge.sharing'].create({
            'employee_id': self.employee.id,
            'session_id': self.session.id,
            'course_id': self.course.id,
            'session_date': fields.Date.context_today(self),
            'completion_date': fields.Date.context_today(self),
            'training_type': 'local_specialized',
            'target_audience': 'Credit Analysts & Officers',
            'attendees_count': 12,
            'key_takeaways': 'Disseminated new credit scoring parameters and compliance checklist.',
            'workplace_action_plan': 'Adopted revised loan application verification SOP across branch.',
            'sign_employee': 'Tadesse Gemechu',
            'sign_manager': 'Almaz Worku',
        })
        self.assertTrue(ksh.name.startswith('KSH/'))
        self.assertEqual(ksh.state, 'draft')

        ksh.action_schedule()
        self.assertEqual(ksh.state, 'scheduled')

        ksh.action_complete()
        self.assertEqual(ksh.state, 'completed')

        report_action = ksh.action_print_form()
        self.assertIsNotNone(report_action)
        self.assertEqual(report_action.get('type'), 'ir.actions.report')

    def test_03_eds_f_13_provider_performance_appraisal(self):
        """Test EDS-F-13 Provider Performance Appraisal creation, ratings, and PDF action."""
        provider = self.env['eds.external.provider'].create({
            'name': 'Ethiopian Management Institute (EMI)',
            'provider_type': 'university',
            'email': 'contact@emi.edu.et',
        })
        appraisal = self.env['eds.provider.performance.history'].create({
            'provider_id': provider.id,
            'course_id': self.course.id,
            'session_id': self.session.id,
            'evaluation_date': fields.Date.context_today(self),
            'service_quality': '5',
            'rating': '5',
            'score_content_relevance': '5',
            'score_trainer_quality': '5',
            'score_time_management': '4',
            'score_logistics_handouts': '4',
            'score_responsiveness': '5',
            'recommend_future_tenders': 'strongly_recommend',
            'evaluated_by_officer': 'L&D Officer Abebe',
            'approved_by_tl': 'Team Leader Chala',
        })
        self.assertEqual(appraisal.recommend_future_tenders, 'strongly_recommend')

        report_action = appraisal.action_print_appraisal()
        self.assertIsNotNone(report_action)
        self.assertEqual(report_action.get('type'), 'ir.actions.report')

    def test_04_eds_f_14_internship_clearance_appraisal(self):
        """Test EDS-F-14 Internship Appraisal and Exit Clearance fields and PDF action."""
        import base64
        intern = self.env['eds.internship.application'].create({
            'applicant_name': 'Hirut Bekele Intern',
            'institution': 'Addis Ababa University',
            'field_of_study': 'Information Systems',
            'scanned_application': base64.b64encode(b'DummyPDFContentForInternshipApplication'),
            'scanned_filename': 'application.pdf',
            'submitted_date': fields.Date.context_today(self),
            'department_id': self.department.id,
            'supervisor_id': self.manager.id,
            'start_date': fields.Date.context_today(self),
            'end_date': fields.Date.context_today(self),
            'clearance_library': True,
            'clearance_id_badge': True,
            'clearance_it_assets': True,
            'clearance_notes': 'All assets surrendered in excellent working order.',
            'clearance_officer_name': 'Yared Officer',
            'clearance_date': fields.Date.context_today(self),
            'final_intern_rating': '5',
            'mentor_overall_recommendation': 'highly_recommended',
            'mentor_sign_name': 'Almaz Worku',
        })
        self.assertTrue(intern.name.startswith('INT-APP/'))

        report_action = intern.action_print_clearance_form()
        self.assertIsNotNone(report_action)
        self.assertEqual(report_action.get('type'), 'ir.actions.report')

    def test_05_eds_f_15_sponsorship_application_matrix(self):
        """Test EDS-F-15 Staff Sponsorship Application and Scoring Matrix and PDF action."""
        spo = self.env['eds.sponsorship'].create({
            'employee_id': self.employee.id,
            'program_name': 'MSc in Banking & Finance',
            'sponsorship_type': 'education',
            'approved_amount': 150000.0,
            'bond_duration_months': 36,
            'institution_name': 'Addis Ababa University Graduate School',
            'field_of_study': 'Finance & Investment',
            'admission_letter_attached': True,
            'tenure_score': 28.0,
            'performance_score': 38.0,
            'strategic_alignment_score': 27.0,
            'committee_decision': 'recommended',
            'committee_chair_name': 'Dr. Solomon Committee Chair',
            'ppdd_director_name': 'W/ro Selamawit Director',
        })
        self.assertEqual(spo.total_matrix_score, 93.0)
        self.assertTrue(spo.name.startswith('SPO/'))

        report_action = spo.action_print_application_form()
        self.assertIsNotNone(report_action)
        self.assertEqual(report_action.get('type'), 'ir.actions.report')
