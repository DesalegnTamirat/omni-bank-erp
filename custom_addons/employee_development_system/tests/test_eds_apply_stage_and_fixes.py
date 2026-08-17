# -*- coding: utf-8 -*-

from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError, UserError
from datetime import date, timedelta


class TestEdsApplyStageAndFixes(TransactionCase):

    def setUp(self):
        super().setUp()

        self.group_base_user = self.env.ref('base.group_user')
        self.group_admin = self.env.ref('employee_development_system.group_eds_admin')
        self.group_officer = self.env.ref('employee_development_system.group_eds_officer')
        self.group_line_manager = self.env.ref('employee_development_system.group_eds_line_manager')

        self.user_manager = self.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create({
            'name': 'Line Manager User',
            'login': 'eds_manager_user',
            'email': False,
            'group_ids': [(6, 0, [self.group_base_user.id, self.group_line_manager.id])]
        })
        self.user_admin = self.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create({
            'name': 'EDS Admin User',
            'login': 'eds_admin_user',
            'email': False,
            'group_ids': [(6, 0, [self.group_base_user.id, self.group_admin.id])]
        })

        self.employee_manager = self.env['hr.employee'].create({
            'name': 'Manager Employee',
            'user_id': self.user_manager.id,
        })
        self.employee_trainee = self.env['hr.employee'].create({
            'name': 'Trainee Employee',
        })

        self.course = self.env['eds.course'].create({
            'name': 'Advanced Banking Operations',
            'category': 'technical_compliance',
        })
        self.session = self.env['eds.session'].create({
            'course_id': self.course.id,
            'date_start': fields.Date.today(),
            'date_end': fields.Date.today() + timedelta(days=5),
        })

    def test_01_ojt_assignment_lifecycle(self):
        """Test OJT assignment creation, progress logging, and completion."""
        ojt = self.env['eds.ojt.assignment'].create({
            'employee_id': self.employee_trainee.id,
            'supervisor_id': self.employee_manager.id,
            'assignment_type': 'new_hire',
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=90),
            'notes': 'OJT for new teller onboarding.',
        })
        self.assertEqual(ojt.state, 'draft')
        
        ojt.action_start()
        self.assertEqual(ojt.state, 'in_progress')

        self.env['eds.ojt.progress'].create({
            'assignment_id': ojt.id,
            'checklist_item': 'CBS Cash Deposit Module',
            'is_completed': True,
            'supervisor_evaluation': 'exceeds',
        })
        
        ojt.action_evaluate()
        self.assertEqual(ojt.state, 'evaluated')
        
        ojt.action_complete()
        self.assertEqual(ojt.state, 'completed')

    def test_02_coaching_and_mentoring_plans(self):
        """Test Coaching plan and Mentoring program workflows."""
        coaching = self.env['eds.coaching.plan'].create({
            'coachee_id': self.employee_trainee.id,
            'coach_type': 'internal',
            'internal_coach_id': self.employee_manager.id,
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=60),
            'objectives': 'Executive leadership coaching.',
        })
        coaching.action_activate()
        self.assertEqual(coaching.state, 'active')

        self.env['eds.coaching.session'].create({
            'coaching_plan_id': coaching.id,
            'session_date': fields.Date.today(),
            'summary': 'Session 1 completed.',
        })
        coaching.action_complete()
        self.assertEqual(coaching.state, 'completed')

        mentoring = self.env['eds.mentoring.program'].create({
            'mentee_id': self.employee_trainee.id,
            'mentor_type': 'internal',
            'internal_mentor_id': self.employee_manager.id,
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=180),
            'objectives': 'Branch management succession mentoring.',
        })
        mentoring.action_activate()
        self.assertEqual(mentoring.state, 'active')

        self.env['eds.mentoring.review'].create({
            'program_id': mentoring.id,
            'review_date': fields.Date.today(),
            'mentor_feedback': 'Demonstrates rapid progress in credit risk.',
        })
        mentoring.action_complete()
        self.assertEqual(mentoring.state, 'completed')

    def test_03_induction_and_learning_events(self):
        """Test Induction program and Learning Event management."""
        induction = self.env['eds.induction.program'].create({
            'program_type': 'blended',
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=14),
            'coordinator_id': self.employee_manager.id,
        })
        self.env['eds.induction.participant'].create({
            'program_id': induction.id,
            'employee_id': self.employee_trainee.id,
        })
        self.env['eds.induction.checklist'].create({
            'program_id': induction.id,
            'task_name': 'IT Account Provisioning',
            'assigned_to': 'it_support',
        })
        induction.action_schedule()
        induction.action_start()
        induction.action_complete()
        self.assertEqual(induction.state, 'completed')

        event = self.env['eds.learning.event'].create({
            'topic': 'Digital Banking Security Innovations',
            'initiator_type': 'ppdd',
            'event_type': 'workshop',
            'start_datetime': fields.Datetime.now(),
            'end_datetime': fields.Datetime.now() + timedelta(hours=4),
            'location': 'Head Office Auditorium',
        })
        event.action_schedule()
        event.action_conduct()
        self.assertEqual(event.state, 'conducted')

    def test_04_idp_and_self_development(self):
        """Test IDP creation, review reminders cron, and Self-Development logging."""
        idp = self.env['eds.individual.development.plan'].create({
            'employee_id': self.employee_trainee.id,
            'career_objectives': 'Senior Credit Analyst Path',
            'next_review_date': fields.Date.today() + timedelta(days=2),
        })
        self.env['eds.idp.activity'].create({
            'idp_id': idp.id,
            'name': 'Complete Financial Statement Analysis',
            'activity_type': 'training',
            'target_date': fields.Date.today() + timedelta(days=30),
        })
        idp.action_submit()
        idp.action_approve()
        
        # Test IDP review reminder cron execution
        self.env['eds.individual.development.plan']._cron_idp_review_reminder()

        self.assertEqual(self.employee_trainee.eds_idp_count, 1)

        self_dev = self.env['eds.self.development.activity'].create({
            'name': 'IFRS 9 Financial Instruments Certification',
            'employee_id': self.employee_trainee.id,
            'activity_type': 'certification',
            'completion_date': fields.Date.today(),
            'hours_spent': 40.0,
            'description': 'Completed external self-paced certification.',
        })
        self_dev.action_submit()
        self_dev.with_user(self.user_admin).action_verify()
        self.assertEqual(self_dev.state, 'verified')
        self.assertEqual(self.employee_trainee.eds_self_dev_count, 1)

    def test_05_assessment_center_and_public_api(self):
        """Test Assessment Center candidate evaluation and public API retrieval."""
        ac = self.env['eds.assessment.center'].create({
            'target_job_id': self.env['hr.job'].search([], limit=1).id or False,
            'assessment_tool': 'blended',
            'start_date': fields.Date.today(),
            'end_date': fields.Date.today() + timedelta(days=3),
            'assessor_ids': [(6, 0, [self.employee_manager.id])],
        })
        ac.action_schedule()
        ac.action_start()

        self.env['eds.assessment.center.result'].create({
            'ac_id': ac.id,
            'candidate_id': self.employee_trainee.id,
            'overall_score': 88.5,
            'recommendation': 'recommended',
            'strengths': 'Exceptional problem-solving and situational leadership.',
        })
        ac.action_complete()
        self.assertEqual(ac.state, 'completed')

        # Test Public API method
        payload = self.env['eds.assessment.center'].get_assessment_center_results(self.employee_trainee.id)
        self.assertTrue(len(payload) >= 1)
        self.assertEqual(payload[0]['score'], 88.5)

    def test_06_evaluation_segregation_of_duties_constraint(self):
        """Test that a user who nominated or approved a participant cannot evaluate them."""
        nomination = self.env['eds.nomination'].create({
            'session_id': self.session.id,
            'employee_id': self.employee_trainee.id,
            'nomination_type': 'tna_based',
            'nominated_by': self.user_manager.id,
        })
        nomination.write({
            'lnd_approved_by': self.user_manager.id,
            'approved_by': self.user_manager.id,
            'state': 'approved',
        })

        eval_l1 = self.env['eds.evaluation.level1'].create({
            'session_id': self.session.id,
            'employee_id': self.employee_trainee.id,
        })
        question = self.env['eds.evaluation.instrument.question'].create({
            'name': 'Course Relevance',
            'question_type': 'scale_1_5',
        })
        self.env['eds.evaluation.level1.line'].create({
            'evaluation_id': eval_l1.id,
            'question_id': question.id,
            'rating_val': 5,
        })

        # Attempting evaluation submission by nomination approver user must raise UserError
        with self.assertRaises(UserError):
            eval_l1.with_user(self.user_manager).action_submit_feedback()

    def test_07_tna_unlock_wizard(self):
        """Test TNA cycle unlock wizard requiring mandatory justification."""
        tna_cycle = self.env['eds.tna.cycle'].create({
            'name': '2026 Annual TNA',
            'start_date': fields.Date.today(),
            'submission_end_date': fields.Date.today() + timedelta(days=30),
            'approval_deadline': fields.Date.today() + timedelta(days=45),
        })
        tna_cycle.state = 'locked'

        # Attempting direct unlock returns wizard action dictionary
        action = tna_cycle.with_user(self.user_admin).action_unlock()
        self.assertEqual(action.get('res_model'), 'eds.tna.unlock.wizard')

        wizard = self.env['eds.tna.unlock.wizard'].with_user(self.user_admin).create({
            'cycle_id': tna_cycle.id,
            'change_justification': 'Mandated mid-year strategic curriculum review.',
        })
        wizard.action_confirm_unlock()

        self.assertEqual(tna_cycle.state, 'approved')
        self.assertTrue(len(tna_cycle.unlock_history_ids) >= 1)
        self.assertEqual(tna_cycle.unlock_history_ids[0].justification, 'Mandated mid-year strategic curriculum review.')

    def test_08_automated_certificate_issuance_cron(self):
        """Test automated certificate issuance cron when attendance and Level 2 evaluations pass."""
        self.env['eds.session.attendance'].create({
            'session_id': self.session.id,
            'employee_id': self.employee_trainee.id,
            'attended': True,
            'attendance_percentage': 100.0,
        })

        pre = self.env['eds.assessment'].create({
            'session_id': self.session.id,
            'employee_id': self.employee_trainee.id,
            'assessment_type': 'pre',
            'score': 40.0,
        })
        post = self.env['eds.assessment'].create({
            'session_id': self.session.id,
            'employee_id': self.employee_trainee.id,
            'assessment_type': 'post',
            'score': 85.0,
        })

        l2 = self.env['eds.evaluation.level2'].create({
            'session_id': self.session.id,
            'employee_id': self.employee_trainee.id,
            'pre_assessment_id': pre.id,
            'post_assessment_id': post.id,
        })
        l2.action_evaluate()

        cert = self.env['eds.certificate'].create({
            'session_id': self.session.id,
            'employee_id': self.employee_trainee.id,
            'state': 'pending',
        })

        # Run automated cron
        self.env['eds.certificate']._cron_auto_issue_certificates()
        
        self.assertEqual(cert.state, 'issued')
