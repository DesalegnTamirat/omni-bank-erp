# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged
from odoo import fields


@tagged('post_install', '-at_install', 'eds', 'operational_pack')
class TestOperationalFormPack(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Department & Employee
        cls.department = cls.env['hr.department'].create({
            'name': 'Corporate Banking Division',
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Tadesse Gemechu Test',
            'department_id': cls.department.id,
            'identification_id': 'TESTEMP881',
            'barcode': 'TESTEMP881',
        })
        cls.manager = cls.env['hr.employee'].create({
            'name': 'Almaz Worku Manager',
            'department_id': cls.department.id,
            'identification_id': 'TESTMGR882',
            'barcode': 'TESTMGR882',
        })

        # Competency
        cls.competency = cls.env['competency.competency'].create({
            'name': 'Credit Analysis & Assessment',
            'code': 'COMP-CR-01',
            'pillar': 'technical',
        })

        # Course
        cls.course = cls.env['eds.course'].create({
            'name': 'Advanced Credit Appraisal',
            'code': 'ACA-2026',
            'category': 'technical_compliance',
            'target_audience': 'all_staff',
            'status': 'active',
            'duration_days': 4.0,
        })

        # Venue
        cls.venue = cls.env['eds.venue'].create({
            'name': 'Grand Palace Hotel Hall A',
            'capacity': 40,
        })

        # Session
        now = fields.Datetime.now()
        cls.session = cls.env['eds.session'].create({
            'name': 'Advanced Credit Appraisal - Cohort 1',
            'course_id': cls.course.id,
            'venue_id': cls.venue.id,
            'date_start': now,
            'date_end': now,
            'status': 'ongoing',
        })

    def test_01_level1_reaction_survey_pack(self):
        """Test EDS-F-02 Level 1 Survey sub-scores calculation and action_print_form."""
        # Create dedicated test questions to guarantee presence
        instrument = self.env['eds.evaluation.instrument'].create({
            'name': 'Test L1 Instrument',
            'instrument_type': 'level1',
        })
        q_c1 = self.env['eds.evaluation.instrument.question'].create({
            'instrument_id': instrument.id,
            'name': 'Content relevance',
            'category': 'content',
            'question_type': 'scale_1_5',
        })
        q_c2 = self.env['eds.evaluation.instrument.question'].create({
            'instrument_id': instrument.id,
            'name': 'Content organization',
            'category': 'content',
            'question_type': 'scale_1_5',
        })
        q_tr = self.env['eds.evaluation.instrument.question'].create({
            'instrument_id': instrument.id,
            'name': 'Trainer expertise',
            'category': 'trainer',
            'question_type': 'scale_1_5',
        })
        q_vn = self.env['eds.evaluation.instrument.question'].create({
            'instrument_id': instrument.id,
            'name': 'Venue comfort',
            'category': 'venue',
            'question_type': 'scale_1_5',
        })
        q_ob = self.env['eds.evaluation.instrument.question'].create({
            'instrument_id': instrument.id,
            'name': 'Objectives met',
            'category': 'objective',
            'question_type': 'scale_1_5',
        })

        survey = self.env['eds.evaluation.level1'].create({
            'session_id': self.session.id,
            'employee_id': self.employee.id,
            'most_valuable_feedback': 'Practical credit case studies with real financial statements.',
            'improvement_suggestions': 'More time for SME assessment exercises.',
        })

        # Content: 5/5 (100%), 4/5 (80%) -> avg 90%
        self.env['eds.evaluation.level1.line'].create({
            'evaluation_id': survey.id,
            'question_id': q_c1.id,
            'rating_val': 5,
        })
        self.env['eds.evaluation.level1.line'].create({
            'evaluation_id': survey.id,
            'question_id': q_c2.id,
            'rating_val': 4,
        })
        # Trainer: 5/5 -> 100%
        self.env['eds.evaluation.level1.line'].create({
            'evaluation_id': survey.id,
            'question_id': q_tr.id,
            'rating_val': 5,
        })
        # Venue: 3/5 -> 60%
        self.env['eds.evaluation.level1.line'].create({
            'evaluation_id': survey.id,
            'question_id': q_vn.id,
            'rating_val': 3,
        })
        # Objective: 4/5 -> 80%
        self.env['eds.evaluation.level1.line'].create({
            'evaluation_id': survey.id,
            'question_id': q_ob.id,
            'rating_val': 4,
        })

        survey._compute_category_scores()
        survey._compute_overall_score()

        self.assertAlmostEqual(survey.score_content, 90.0, places=1)
        self.assertAlmostEqual(survey.score_trainer, 100.0, places=1)
        self.assertAlmostEqual(survey.score_venue, 60.0, places=1)
        self.assertAlmostEqual(survey.score_objective, 80.0, places=1)
        self.assertGreater(survey.overall_score, 80.0)

        # Test report action
        action = survey.action_print_form()
        self.assertEqual(action.get('type'), 'ir.actions.report')
        self.assertEqual(action.get('report_name'), 'employee_development_system.report_eds_level1_document')

    def test_02_level2_pre_post_assessment_sheet(self):
        """Test EDS-F-03 Level 2 Pre/Post scoring formulas and report action."""
        l2 = self.env['eds.evaluation.level2'].create({
            'session_id': self.session.id,
            'employee_id': self.employee.id,
            'total_marks': 50.0,
            'pre_test_score': 25.0,   # 50%
            'post_test_score': 42.0,  # 84%
            'passing_score': 65.0,
            'trainer_assessor_name': 'Solomon Tesfaye',
            'training_coordinator_name': 'Hanna Girma',
            'approved_by_tl_name': 'Dawit Kebede',
            'remarks': 'Strong analytical capability demonstrated.',
        })

        self.assertAlmostEqual(l2.pre_test_pct, 50.0, places=1)
        self.assertAlmostEqual(l2.post_test_pct, 84.0, places=1)
        self.assertAlmostEqual(l2.learning_gain, 34.0, places=1)
        self.assertTrue(l2.passed)

        action = l2.action_print_form()
        self.assertEqual(action.get('type'), 'ir.actions.report')
        self.assertEqual(action.get('report_name'), 'employee_development_system.report_eds_level2_document')

    def test_03_level3_behavioral_form(self):
        """Test EDS-F-04 Level 3 Behavioral Application Form and report action."""
        l3 = self.env['eds.evaluation.level3'].create({
            'session_id': self.session.id,
            'employee_id': self.employee.id,
            'manager_id': self.manager.id,
            'due_date': fields.Date.today(),
            'evaluation_period': '60_days',
            'overall_result': 'significant_improvement',
            'business_impact_observed': 'Reduced loan turnaround time by 2 days; zero loan classification errors.',
            'recommended_support': 'Cross-functional attachment to Corporate Credit Appraisal Team.',
            'sign_manager_name': 'Almaz Worku',
            'sign_trainee_name': 'Tadesse Gemechu',
            'sign_officer_name': 'Kassahun Bekele',
        })

        self.env['eds.evaluation.level3.line'].create({
            'evaluation_id': l3.id,
            'competency_id': self.competency.id,
            'behavior_description': 'Accurately computes DSCR and cash-flow sensitivity for loan files.',
            'frequency_rating': '5',
            'observed_level': '3',
            'comment': 'Consistently identifies risk red flags.',
        })

        l3._compute_behavior_score()
        self.assertAlmostEqual(l3.behavior_score, 100.0, places=1)

        action = l3.action_print_form()
        self.assertEqual(action.get('type'), 'ir.actions.report')
        self.assertEqual(action.get('report_name'), 'employee_development_system.report_eds_level3_document')

    def test_04_vrs_form_procurement(self):
        """Test EDS-F-05 Venue Requirement Specification form and report action."""
        vrs = self.env['eds.venue.requirement'].create({
            'course_id': self.course.id,
            'session_id': self.session.id,
            'capacity_required': 35,
            'location_preference': 'Bishoftu / Debre Zeit',
            'date_start': fields.Date.today(),
            'date_end': fields.Date.today(),
            'participant_count': 32,
            'facilitator_count': 2,
            'estimated_budget': 180000.0,
            'seating_layout': 'cluster',
            'breakout_rooms': 2,
            'has_projector': True,
            'has_sound_system': True,
            'has_flipcharts': True,
            'has_wifi': True,
            'has_power_backup': True,
            'has_air_conditioning': True,
            'catering_morning_tea': True,
            'catering_lunch': True,
            'catering_afternoon_tea': True,
            'catering_water': True,
            'menu_type': 'mixed',
            'catering_count': 35,
            'accommodation_required': True,
            'rooms_required': 35,
            'room_nights': 140,
            'prepared_by': 'L&D Officer Abebe',
            'reviewed_by': 'TL L&D Chala',
            'director_sign': 'Director PPDD Marta',
        })

        self.assertEqual(vrs.duration_days, 1)
        action = vrs.action_print_vrs()
        self.assertEqual(action.get('type'), 'ir.actions.report')
        self.assertEqual(action.get('report_name'), 'employee_development_system.report_eds_vrs_document')

    def test_05_trainer_profile_pack(self):
        """Test EDS-F-06 Trainer Profile registration, sub-tables and report action."""
        trainer = self.env['eds.trainer'].create({
            'name': 'Dr. Yohannes Hailu',
            'trainer_type': 'external',
            'trainer_id_code': 'TR-EXT-2026-009',
            'organization_name': 'Financial Markets Institute',
            'phone': '+251911223344',
            'email': 'yohannes@fmi.edu.et',
            'address': 'Bole Sub-City, Addis Ababa',
            'banking_experience_years': 15.0,
            'trainer_experience_years': 10.0,
            'institutions_worked_with': 'Commercial Bank of Ethiopia, Awash Bank, Dashen Bank',
            'daily_fee': 15000.0,
            'hourly_fee': 2000.0,
            'tax_status': 'VAT Inclusive',
            'fee_validity_period': '2026/27 Fiscal Year',
            'declaration_agreed': True,
            'reviewed_by_officer': 'L&D Officer Abebe',
            'approved_by_tl': 'TL L&D Chala',
        })

        # Add education
        self.env['eds.trainer.education'].create({
            'trainer_id': trainer.id,
            'degree_title': 'PhD in Banking & Finance',
            'field_of_study': 'Financial Risk Management',
            'institution_name': 'Addis Ababa University',
            'year_obtained': '2016',
        })

        # Add expertise
        self.env['eds.trainer.expertise'].create({
            'trainer_id': trainer.id,
            'subject_domain': 'Risk Management & Treasury',
            'course_topics': 'Credit Risk, ALM, Basel II/III Standards',
            'target_level': 'advanced',
            'years_experience': 10,
        })

        # Add delivery history
        self.env['eds.trainer.delivery.history'].create({
            'trainer_id': trainer.id,
            'program_title': 'Executive Credit Risk Modeling',
            'client_organization': 'Bunna Bank S.C.',
            'delivery_year': '2025',
            'participant_count': 25,
            'participant_rating': 4.8,
        })

        self.assertEqual(len(trainer.education_ids), 1)
        self.assertEqual(len(trainer.expertise_ids), 1)
        self.assertEqual(len(trainer.delivery_history_ids), 1)

        action = trainer.action_print_profile()
        self.assertEqual(action.get('type'), 'ir.actions.report')
        self.assertEqual(action.get('report_name'), 'employee_development_system.report_eds_trainer_profile_document')

    def test_06_unscheduled_request_pack(self):
        """Test EDS-F-09 Unscheduled Training Request with 4-tier approval and report action."""
        request = self.env['eds.unscheduled.request'].create({
            'employee_id': self.employee.id,
            'department_id': self.department.id,
            'course_id': self.course.id,
            'contact_phone_email': '+251911556677 / tadesse@bunnabank.et',
            'unit_head_id': self.manager.id,
            'participant_count': 12,
            'delivery_mode': 'classroom',
            'preferred_provider': 'Ethiopian Institute of Financial Studies',
            'duration_text': '3 Days (24 Contact Hours)',
            'proposed_dates_text': 'November 15 - 17, 2026',
            'urgency_category': 'urgent_2weeks',
            'reason': 'urgent_operational',
            'justification': 'NBE regulatory audit mandated retraining on revised Asset Classification directives.',
            'risk_regulatory': True,
            'risk_financial': True,
            'risk_details': 'Failure to comply before next audit cycle will result in central bank penalties.',
            'estimated_cost': 75000.0,
            'budget_source': 'training_budget',
            'cost_centre_code': 'CC-PPDD-2026-TRN',
            'sign_unit_head': 'Almaz Worku (Unit Head)',
            'sign_tl_lnd': 'Dawit Kebede (TL L&D)',
            'sign_finance': 'Biniam Tekle (Director Finance)',
            'sign_director': 'Marta Assefa (Director PPDD)',
            'decision_type': 'approved',
            'decision_comments': 'Approved under emergency regulatory compliance quota.',
        })

        self.assertEqual(request.cost_per_participant, 6250.0)
        self.assertTrue(request.risk_regulatory)

        action = request.action_print_form()
        self.assertEqual(action.get('type'), 'ir.actions.report')
        self.assertEqual(action.get('report_name'), 'employee_development_system.report_eds_unscheduled_document')
