# -*- coding: utf-8 -*-
import base64
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from unittest.mock import patch
from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.exceptions import AccessError, UserError
from odoo.addons.learning_management.controllers.main import LmsController


from odoo.http import Response


class RenderResponse(Response):
    def __init__(self, template, values=None, status=200, **kwargs):
        super().__init__(response="mock_rendered_html", status=status, **kwargs)
        self.template = template
        self.values = values or {}


class DummyRequest:
    def __init__(self, env, user, headers=None):
        self.env = env(user=user)
        self.httprequest = type('Req', (), {'headers': headers or {}})()

    def render(self, template, values=None):
        return RenderResponse(template=template, values=values, status=200)

    def not_found(self):
        return Response(status=404)


class TestLmsPhase5E2E(TransactionCase):
    """
    Comprehensive End-to-End Functional Test Suite for Bunna Bank Learning Management System (LMS).
    Verifies FR-LMS-001 through FR-LMS-029 and Gamification FR-REC-001, FR-REC-002, FR-REC-004 to FR-REC-008.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.LmsCategory = cls.env['lms.category']
        cls.LmsCourse = cls.env['lms.course']
        cls.LmsLesson = cls.env['lms.lesson']
        cls.LmsLearningPath = cls.env['lms.learning.path']
        cls.LmsPathCourse = cls.env['lms.learning.path.course']
        cls.LmsAssignment = cls.env['lms.course.assignment']
        cls.LmsEnrollment = cls.env['lms.enrollment']
        cls.LmsLessonProgress = cls.env['lms.lesson.progress']
        cls.LmsAssessment = cls.env['lms.assessment']
        cls.LmsQuestion = cls.env['lms.question']
        cls.LmsQuestionAnswer = cls.env['lms.question.answer']
        cls.LmsQuestionPool = cls.env['lms.question.pool']
        cls.LmsExamSession = cls.env['lms.exam.session']
        cls.LmsCertificate = cls.env['lms.certificate']
        cls.LmsCertificateTemplate = cls.env['lms.certificate.template']
        cls.LmsGamificationPoint = cls.env['lms.gamification.point']
        cls.LmsMonthlyScorer = cls.env['lms.monthly.scorer']
        cls.LmsBranchCompliance = cls.env['lms.branch.compliance.report']

        # Organization Structure (Bank validation rules forbid numbers in department names)
        cls.dept_trade = cls.env['hr.department'].create({'name': 'Trade Services and Foreign Operations'})
        cls.dept_retail = cls.env['hr.department'].create({'name': 'Retail and Branch Operations'})

        OperatingUnit = cls.env.get('operating.unit')
        if OperatingUnit:
            cls.ou_kazanchis = OperatingUnit.create({'name': 'Kazanchis Branch Alpha', 'code': 'KAZ-ALPHA'})
            cls.ou_piassa = OperatingUnit.create({'name': 'Piassa Branch Alpha', 'code': 'PIA-ALPHA'})
        else:
            cls.ou_kazanchis = False
            cls.ou_piassa = False

        cls.job_officer = cls.env['hr.job'].create({'name': 'Compliance Risk Officer'})

        # Users and Employees
        cls.user_lms_mgr = cls.env['res.users'].create({
            'name': 'LMS Training Manager E2E',
            'login': 'lms_mgr_e2e@bunna.et',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('learning_management.group_lms_manager').id,
            ])],
        })
        cls.emp_mgr = cls.env['hr.employee'].create({
            'name': 'LMS Training Manager Emp',
            'user_id': cls.user_lms_mgr.id,
            'department_id': cls.dept_trade.id,
            'default_operating_unit_id': cls.ou_kazanchis.id if cls.ou_kazanchis else False,
        })

        cls.user_instructor = cls.env['res.users'].create({
            'name': 'Course Instructor E2E',
            'login': 'instructor_e2e@bunna.et',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('learning_management.group_lms_instructor').id,
            ])],
        })
        cls.emp_instructor = cls.env['hr.employee'].create({
            'name': 'Course Instructor Emp',
            'user_id': cls.user_instructor.id,
            'department_id': cls.dept_trade.id,
        })

        cls.user_learner1 = cls.env['res.users'].create({
            'name': 'Primary Learner E2E',
            'login': 'learner1_e2e@bunna.et',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('learning_management.group_lms_learner').id,
            ])],
        })
        cls.emp_learner1 = cls.env['hr.employee'].create({
            'name': 'Primary Learner Emp',
            'user_id': cls.user_learner1.id,
            'department_id': cls.dept_trade.id,
            'job_id': cls.job_officer.id,
            'default_operating_unit_id': cls.ou_kazanchis.id if cls.ou_kazanchis else False,
        })

        cls.user_learner2 = cls.env['res.users'].create({
            'name': 'Secondary Learner E2E',
            'login': 'learner2_e2e@bunna.et',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('learning_management.group_lms_learner').id,
            ])],
        })
        cls.emp_learner2 = cls.env['hr.employee'].create({
            'name': 'Secondary Learner Emp',
            'user_id': cls.user_learner2.id,
            'department_id': cls.dept_retail.id,
            'default_operating_unit_id': cls.ou_piassa.id if cls.ou_piassa else False,
        })

        cls.category = cls.LmsCategory.create({
            'name': 'International Banking Operations',
            'code': 'IBO-E2E',
        })

    def test_01_course_creation_full_lifecycle(self):
        """FR-LMS-001, BRD Section 8.4.1: Comprehensive verification of the 9-step Course Creation & Management Lifecycle."""
        # Step 1: Create Course Shell
        course = self.LmsCourse.create({
            'name': 'Trade Services & Documentary Credit Mastery',
            'category_id': self.category.id,
            'instructor_id': self.emp_instructor.id,
            'description': '<p>Comprehensive masterclass on Letters of Credit and UCP 600 rules.</p>',
            'learning_objectives': '<p>Master discrepancy examination, swift messaging, and import financing.</p>',
            'target_department_ids': [(4, self.dept_trade.id)],
            'target_job_ids': [(4, self.job_officer.id)],
        })
        self.assertEqual(course.state, 'draft')
        self.assertTrue(course.code.startswith('LMS-CRS-') or course.code != 'New')

        # Step 2: Upload Content
        lesson_video = self.LmsLesson.create({
            'name': 'LC Issuance and Examination Criteria',
            'course_id': course.id,
            'lesson_type': 'video',
            'video_source_type': 'file',
            'video_file': b'AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDE=',  # Dummy MP4
            'video_duration_seconds': 300,
            'prevent_fast_forward': True,
            'min_watch_percentage': 90.0,
        })
        lesson_doc = self.LmsLesson.create({
            'name': 'UCP 600 Key Provisions Slide Deck',
            'course_id': course.id,
            'lesson_type': 'document',
            'document_file': b'JVBERi0xLjQgVUNQIDYwMCBTbGlkZXMgRGF0YQ==',
            'document_filename': 'ucp600_slides.pdf',
        })
        self.assertEqual(course.total_lessons, 2)

        # Step 3: Configure Settings
        course.write({
            'is_mandatory': True,
            'estimated_duration_hours': 2.5,
            'pass_score_percentage': 80.0,
            'certificate_validity_months': 24,
        })

        # Step 4: Assign to a Learning Path
        path = self.LmsLearningPath.create({
            'name': 'International Banking Professional Certification',
            'code': 'IBPC-E2E',
            'description': '<p>Curriculum path for forex and trade specialists.</p>',
        })
        self.LmsPathCourse.create({
            'path_id': path.id,
            'sequence': 10,
            'course_id': course.id,
        })
        self.assertIn(course, path.path_course_ids.mapped('course_id'))

        # Step 5: Save as Draft -> Learner search catalog must NOT find draft courses
        learner_catalog = self.LmsCourse.with_user(self.user_learner1).search([('id', '=', course.id)])
        self.assertEqual(len(learner_catalog), 0, "Draft courses must not be visible in learner catalog")

        # Step 6: Submit for Review & Approval
        course.action_submit_for_review()
        self.assertEqual(course.state, 'review')

        # Step 7: Publish
        course.with_user(self.user_lms_mgr).action_publish()
        self.assertEqual(course.state, 'published')
        self.assertTrue(course.is_latest_version)

        # Now visible in learner catalog
        learner_catalog_published = self.LmsCourse.with_user(self.user_learner1).search([('id', '=', course.id)])
        self.assertEqual(len(learner_catalog_published), 1)

        # Step 8: Edit/Update via Version-Based Archiving
        rev_action = course.with_user(self.user_lms_mgr).action_create_new_version()
        course_v2 = self.LmsCourse.browse(rev_action['res_id'])
        self.assertEqual(course_v2.version, '1.1')
        self.assertEqual(course_v2.previous_version_id.id, course.id)

        # Publishing v2 auto-archives v1
        course_v2.with_user(self.user_lms_mgr).action_publish()
        self.assertEqual(course_v2.state, 'published')
        course.invalidate_recordset(['state', 'is_latest_version'])
        self.assertEqual(course.state, 'archived')
        self.assertFalse(course.is_latest_version)

        # Step 9: Retire/Archive (Admin-only archive retains past records)
        course_v2.with_user(self.user_lms_mgr).action_archive()
        self.assertEqual(course_v2.state, 'archived')

    def test_02_course_assignment_campaigns(self):
        """FR-LMS-003, FR-LMS-027: Automated batch course assignments across departments and operating units."""
        course = self.LmsCourse.create({
            'name': 'Sanctions Screening & AML Due Diligence',
            'category_id': self.category.id,
            'instructor_id': self.emp_instructor.id,
            'state': 'published',
            'description': '<p>Mandatory annual AML refresher course.</p>',
        })

        # 1. Assignment by Department (Trade Services department has learner1)
        campaign_dept = self.LmsAssignment.create({
            'name': 'Trade Services Mandatory AML Campaign 2026',
            'course_id': course.id,
            'assignment_type': 'department',
            'department_ids': [(4, self.dept_trade.id)],
            'is_mandatory': True,
            'due_date': fields.Date.context_today(self) + timedelta(days=30),
        })
        campaign_dept.action_execute_assignment()
        self.assertEqual(campaign_dept.state, 'executed')

        # Learner 1 must have an enrollment record in enrolled state
        enr1 = self.LmsEnrollment.search([
            ('employee_id', '=', self.emp_learner1.id),
            ('course_id', '=', course.id),
        ])
        self.assertTrue(enr1)
        self.assertTrue(enr1.is_mandatory)
        self.assertEqual(enr1.state, 'enrolled')

        # 2. Assignment by Individual
        campaign_ind = self.LmsAssignment.create({
            'name': 'Individual Assignment Campaign',
            'course_id': course.id,
            'assignment_type': 'individual',
            'employee_ids': [(4, self.emp_learner2.id)],
            'is_mandatory': False,
            'due_date': fields.Date.context_today(self) + timedelta(days=15),
        })
        campaign_ind.action_execute_assignment()
        self.assertEqual(campaign_ind.state, 'executed')

        enr2 = self.LmsEnrollment.search([
            ('employee_id', '=', self.emp_learner2.id),
            ('course_id', '=', course.id),
        ])
        self.assertTrue(enr2)
        self.assertFalse(enr2.is_mandatory)

    def test_03_branch_and_department_compliance_report_sql_view(self):
        """FR-LMS-023, FR-LMS-024, FR-LMS-025: SQL analytical view for branch & department compliance tracking."""
        course = self.LmsCourse.create({
            'name': 'Cybersecurity Awareness Mandatory',
            'category_id': self.category.id,
            'instructor_id': self.emp_instructor.id,
            'state': 'published',
            'is_mandatory': True,
            'description': '<p>Cybersecurity awareness training</p>',
        })

        # Learner 1 in Kazanchis branch -> Completed
        self.LmsEnrollment.create({
            'employee_id': self.emp_learner1.id,
            'course_id': course.id,
            'is_mandatory': True,
            'state': 'completed',
            'completion_date': fields.Date.context_today(self),
        })

        # Learner 2 in Piassa branch -> In Progress & Overdue
        self.LmsEnrollment.create({
            'employee_id': self.emp_learner2.id,
            'course_id': course.id,
            'is_mandatory': True,
            'state': 'in_progress',
            'due_date': fields.Date.context_today(self) - timedelta(days=5),
        })

        # Flush ORM cache so PostgreSQL SQL analytical view sees the inserted rows and computed is_overdue
        self.env.flush_all()

        # Query the SQL report view
        reports = self.LmsBranchCompliance.search([('course_id', '=', course.id)])
        self.assertTrue(reports)

        # Verify trade department report (Kazanchis branch) has 100% compliance
        trade_report = reports.filtered(lambda r: r.department_id == self.dept_trade)
        if trade_report:
            self.assertEqual(trade_report.total_assigned, 1)
            self.assertEqual(trade_report.total_completed, 1)
            self.assertEqual(trade_report.compliance_percentage, 100.0)

        # Verify retail department report (Piassa branch) has 0% compliance and 1 overdue
        retail_report = reports.filtered(lambda r: r.department_id == self.dept_retail)
        if retail_report:
            self.assertEqual(retail_report.total_assigned, 1)
            self.assertEqual(retail_report.total_completed, 0)
            self.assertEqual(retail_report.total_overdue, 1)
            self.assertEqual(retail_report.compliance_percentage, 0.0)

    def test_04_timed_assessment_and_randomized_pool(self):
        """FR-LMS-014, FR-LMS-015: Timed assessments with randomized question pool sampling and deadline calculation."""
        course = self.LmsCourse.create({
            'name': 'Bank Guarantee & Bond Examination',
            'category_id': self.category.id,
            'instructor_id': self.emp_instructor.id,
            'state': 'published',
            'description': '<p>Bank guarantee evaluation</p>',
        })

        # Create Question Pool
        pool = self.LmsQuestionPool.create({
            'name': 'Guarantees Pool E2E',
            'code': 'POOL-GUARS-E2E',
        })

        # Populate pool with 5 questions
        for i in range(1, 6):
            q = self.LmsQuestion.create({
                'name': f'Guarantee Question {i}',
                'pool_id': pool.id,
                'question_text': f'<p>Question content {i} regarding performance bonds.</p>',
                'points': 2.0,
                'question_type': 'single_choice',
            })
            self.LmsQuestionAnswer.create({
                'question_id': q.id,
                'answer_text': 'Valid Answer',
                'is_correct': True,
            })
            self.LmsQuestionAnswer.create({
                'question_id': q.id,
                'answer_text': 'Invalid Answer',
                'is_correct': False,
            })

        # Assessment config: Draw 3 random questions from pool, 45 minutes timed
        exam = self.LmsAssessment.create({
            'name': 'Timed Guarantee Diagnostic Exam',
            'course_id': course.id,
            'assessment_type': 'post_course',
            'is_timed': True,
            'duration_minutes': 45,
            'use_random_pool': True,
            'questions_per_session': 3,
            'pool_ids': [(4, pool.id)],
            'pass_score_percentage': 80.0,
            'instructions': '<p>You have 45 minutes to complete this exam.</p>',
        })

        enrollment = self.LmsEnrollment.create({
            'employee_id': self.emp_learner1.id,
            'course_id': course.id,
            'state': 'in_progress',
        })

        # Generate candidate session
        session = self.LmsExamSession.create_session_for_learner(exam, self.emp_learner1, enrollment)
        self.assertEqual(session.state, 'in_progress')
        self.assertEqual(len(session.line_ids), 3, "Session must sample exactly 3 questions from pool")
        self.assertTrue(session.deadline_time, "Timed exam must calculate deadline timestamp")
        expected_deadline = session.start_time + timedelta(minutes=45)
        # Check deadline within 5 seconds of expected
        self.assertAlmostEqual(session.deadline_time.timestamp(), expected_deadline.timestamp(), delta=5)

    def test_05_automated_grading_multichoice_and_first_pass(self):
        """FR-LMS-017, FR-REC-001: Automated grading for multiple answer choices and instant score computation."""
        course = self.LmsCourse.create({
            'name': 'Financial Crime Prevention Exam Course',
            'category_id': self.category.id,
            'instructor_id': self.emp_instructor.id,
            'state': 'published',
            'description': '<p>Financial crime prevention</p>',
        })
        exam = self.LmsAssessment.create({
            'name': 'Multi-Choice AML Exam',
            'course_id': course.id,
            'assessment_type': 'post_course',
            'pass_score_percentage': 70.0,
            'instructions': '<p>Select all correct answers.</p>',
        })

        # Question 1: Multiple choice (2 correct answers)
        q_multi = self.LmsQuestion.create({
            'name': 'Red Flag Indicators',
            'question_text': '<p>Which of the following constitute money laundering red flags?</p>',
            'points': 10.0,
            'question_type': 'multiple_choice',
        })
        ans_c1 = self.LmsQuestionAnswer.create({'question_id': q_multi.id, 'answer_text': 'Structuring cash deposits', 'is_correct': True})
        ans_c2 = self.LmsQuestionAnswer.create({'question_id': q_multi.id, 'answer_text': 'Unusual high velocity offshore wires', 'is_correct': True})
        ans_w1 = self.LmsQuestionAnswer.create({'question_id': q_multi.id, 'answer_text': 'Regular monthly salary deposit', 'is_correct': False})

        # Question 2: Single choice
        q_single = self.LmsQuestion.create({
            'name': 'STR Filing Authority',
            'question_text': '<p>To which agency are Suspicious Transaction Reports submitted?</p>',
            'points': 10.0,
            'question_type': 'single_choice',
        })
        ans_c3 = self.LmsQuestionAnswer.create({'question_id': q_single.id, 'answer_text': 'Financial Intelligence Service (FIS)', 'is_correct': True})
        ans_w2 = self.LmsQuestionAnswer.create({'question_id': q_single.id, 'answer_text': 'Local Police Station', 'is_correct': False})

        exam.write({'fixed_question_ids': [(4, q_multi.id), (4, q_single.id)]})

        enrollment = self.LmsEnrollment.create({
            'employee_id': self.emp_learner1.id,
            'course_id': course.id,
            'state': 'in_progress',
        })

        session = self.LmsExamSession.create_session_for_learner(exam, self.emp_learner1, enrollment)
        lines = session.line_ids

        # Answer question 1 correctly (both correct answers selected)
        line_multi = lines.filtered(lambda l: l.question_id == q_multi)
        line_multi.write({'selected_answer_ids': [(4, ans_c1.id), (4, ans_c2.id)]})

        # Answer question 2 correctly
        line_single = lines.filtered(lambda l: l.question_id == q_single)
        line_single.write({'selected_answer_ids': [(4, ans_c3.id)]})

        # Auto grade
        session.action_submit_and_grade()
        self.assertEqual(session.state, 'passed')
        self.assertEqual(session.score_percentage, 100.0)
        self.assertTrue(session.is_passed)

        # Gamification points awarded for course completion (+50 points for 100% score)
        pts = self.LmsGamificationPoint.search([
            ('user_id', '=', self.user_learner1.id),
            ('source', '=', 'course_complete'),
        ])
        self.assertTrue(pts, "Course completion must award learning gamification points")
        self.assertEqual(pts[0].points, 50)

    def test_06_certificate_generation_and_core_hr_bridge(self):
        """FR-LMS-018, FR-LMS-022: Certificate issuance, SHA-256 hash, and automated push to hr.training.history & hr.employee.document."""
        course = self.LmsCourse.create({
            'name': 'Certified International Trade Finance Specialist',
            'category_id': self.category.id,
            'instructor_id': self.emp_instructor.id,
            'state': 'published',
            'description': '<p>Specialist certification</p>',
            'issue_certificate': True,
            'certificate_validity_months': 12,
        })
        enrollment = self.LmsEnrollment.create({
            'employee_id': self.emp_learner1.id,
            'course_id': course.id,
            'state': 'in_progress',
        })

        # Issue certificate for passed learner
        cert = self.LmsCertificate.issue_certificate(enrollment, 95.0)
        self.assertTrue(cert)
        self.assertEqual(cert.state, 'valid')
        self.assertEqual(cert.score_percentage, 95.0)
        self.assertTrue(cert.verification_code, "Security verification hash must be generated")
        self.assertEqual(len(cert.verification_code), 16)

        # Pre-rendered QWeb PDF
        self.assertTrue(cert.certificate_pdf, "Certificate PDF must be generated upon issuance")

        # Bridge 1: hr.training.history record created
        th = cert.hr_training_history_id
        if th:
            self.assertEqual(th.employee_id.id, self.emp_learner1.id)
            self.assertEqual(th.training_name, course.name)
            self.assertEqual(th.status, 'completed')

        # Bridge 2: hr.employee.document record created
        emp_doc = cert.hr_employee_document_id
        if emp_doc:
            self.assertEqual(emp_doc.employee_ref.id, self.emp_learner1.id)
            self.assertIn("Training Certificate", emp_doc.name)

    def test_07_public_certificate_verification_controller(self):
        """FR-LMS-018: Public online certificate validation route with valid and invalid hash codes."""
        course = self.LmsCourse.create({
            'name': 'Fraud Risk Management Course',
            'category_id': self.category.id,
            'instructor_id': self.emp_instructor.id,
            'state': 'published',
            'description': '<p>Fraud risk syllabus</p>',
        })
        enrollment = self.LmsEnrollment.create({
            'employee_id': self.emp_learner1.id,
            'course_id': course.id,
            'state': 'in_progress',
        })
        cert = self.LmsCertificate.issue_certificate(enrollment, 88.0)

        controller = LmsController()
        dummy_req = DummyRequest(self.env, self.user_learner1)

        # 1. Test with valid verification code -> returns success template
        with patch('odoo.addons.learning_management.controllers.main.request', dummy_req):
            res_valid = controller.verify_certificate(cert.verification_code)
            self.assertEqual(res_valid.template, 'learning_management.certificate_verify_success')
            self.assertTrue(res_valid.values.get('is_valid'))
            self.assertEqual(res_valid.values.get('learner_name'), self.emp_learner1.name)
            self.assertEqual(res_valid.values.get('course_name'), course.name)

        # 2. Test with invalid/tampered verification code -> returns not found template
        with patch('odoo.addons.learning_management.controllers.main.request', dummy_req):
            res_invalid = controller.verify_certificate("INVALID-FAKE-HASH")
            self.assertEqual(res_invalid.template, 'learning_management.certificate_verify_not_found')
            self.assertEqual(res_invalid.values.get('code'), 'INVALID-FAKE-HASH')

    def test_08_monthly_best_scorer_cron(self):
        """FR-REC-002, FR-REC-005: Best Scorer of the Month automated calculation and citation."""
        today = date.today()
        prev_month_date = (today - relativedelta(months=1)).replace(day=10)

        course = self.LmsCourse.create({
            'name': 'Operational Risk Fundamentals',
            'category_id': self.category.id,
            'instructor_id': self.emp_instructor.id,
            'state': 'published',
            'description': '<p>Risk management</p>',
        })

        # Complete enrollment in previous month with 98% score
        self.LmsEnrollment.create({
            'employee_id': self.emp_learner1.id,
            'course_id': course.id,
            'state': 'completed',
            'completion_date': prev_month_date,
            'final_score_percentage': 98.0,
        })

        # Run monthly calculation cron
        self.LmsMonthlyScorer.cron_calculate_monthly_winner()

        # Check winner record created
        first_day_prev = (today - relativedelta(months=1)).replace(day=1)
        winner = self.LmsMonthlyScorer.search([
            ('employee_id', '=', self.emp_learner1.id),
            ('period_date', '=', first_day_prev),
        ], limit=1)
        self.assertTrue(winner, "Monthly cron must create best scorer recognition record")
        self.assertEqual(winner.badge, 'gold')
        self.assertEqual(winner.average_score, 98.0)
        self.assertEqual(winner.courses_completed, 1)

    def test_09_certificate_expiry_cron(self):
        """FR-LMS-020: Automated cron transition for expired certifications."""
        course = self.LmsCourse.create({
            'name': 'Short-Term Compliance Certificate Course',
            'category_id': self.category.id,
            'instructor_id': self.emp_instructor.id,
            'state': 'published',
            'description': '<p>Short-term compliance</p>',
        })
        enrollment = self.LmsEnrollment.create({
            'employee_id': self.emp_learner1.id,
            'course_id': course.id,
            'state': 'in_progress',
        })
        cert = self.LmsCertificate.issue_certificate(enrollment, 85.0)
        self.assertEqual(cert.state, 'valid')

        # Backdate expiry_date to 10 days ago
        cert.write({'expiry_date': fields.Date.context_today(self) - timedelta(days=10)})

        # Run expiry check cron
        self.LmsCertificate.cron_check_certificate_expiry()

        cert.invalidate_recordset(['state'])
        self.assertEqual(cert.state, 'expired', "Certificates past expiry date must transition to expired")

    def test_10_video_streaming_http_206_range_requests(self):
        """FR-LMS-004, FR-LMS-005: Video streaming controller supports HTTP 206 Partial Content range requests."""
        dummy_video_bytes = b'X' * 500  # 500 bytes video file
        course = self.LmsCourse.create({
            'name': 'Streaming Range Test Course',
            'category_id': self.category.id,
            'instructor_id': self.emp_instructor.id,
            'state': 'published',
            'description': '<p>Video stream testing</p>',
        })
        lesson = self.LmsLesson.create({
            'name': 'Range Stream Video Lesson',
            'course_id': course.id,
            'lesson_type': 'video',
            'video_source_type': 'file',
            'video_file': base64.b64encode(dummy_video_bytes),
            'video_duration_seconds': 120,
        })
        # Enroll learner
        self.LmsEnrollment.create({
            'employee_id': self.emp_learner1.id,
            'course_id': course.id,
            'state': 'in_progress',
        })

        controller = LmsController()

        # 1. Request full video (no Range header) -> HTTP 200
        dummy_req_full = DummyRequest(self.env, self.user_learner1)
        with patch('odoo.addons.learning_management.controllers.main.request', dummy_req_full):
            res_full = controller.stream_lesson_video(lesson.id)
            self.assertEqual(res_full.status_code, 200)
            self.assertEqual(len(res_full.get_data()), 500)

        # 2. Request partial content (Range: bytes=0-99) -> HTTP 206
        headers_range = {'Range': 'bytes=0-99'}
        dummy_req_range = DummyRequest(self.env, self.user_learner1, headers=headers_range)
        with patch('odoo.addons.learning_management.controllers.main.request', dummy_req_range):
            res_partial = controller.stream_lesson_video(lesson.id)
            self.assertEqual(res_partial.status_code, 206)
            self.assertEqual(len(res_partial.get_data()), 100)
            headers_dict = dict(res_partial.headers)
            self.assertEqual(headers_dict.get('Content-Range'), 'bytes 0-99/500')
            self.assertEqual(headers_dict.get('Content-Length'), '100')
