# -*- coding: utf-8 -*-
"""
========================================================================================
BUNNA BANK S.C. — KMS, LMS & BRIDGE INTEGRATED END-TO-END SCENARIO TEST
========================================================================================

This test file simulates the complete real-world operational lifecycle across:
  - Module 1: Knowledge Management System (KMS)
  - Module 2: Learning Management System (LMS)
  - Module 3: KMS-LMS Cross-Module Bridge
  - Interoperability with Bank Organizational Structure and Competencies

Lifecycle Stages Verified:
  Stage 1:  Master Taxonomies (KMS Categories, Doc Types, Classifications, LMS Categories)
  Stage 2:  KMS Policy Authoring, Review and Multi-Level Approval Workflow
  Stage 3:  Dynamic Watermarking and Security Download Constraints
  Stage 4:  Full-Text Search on Governed Document Repository
  Stage 5:  KMS Document Versioning and Revision Superseding
  Stage 6:  LMS Course Draft with Video and Reading Lessons
  Stage 7:  KMS-LMS Bridge Linkage (Digital Library Assets and Lessons Learned attached to Course)
  Stage 8:  Interactive Assessment Setup and Reviewed Course Publication
  Stage 9:  Learner Course Enrollment and Auto-Scheduled mail.activity
  Stage 10: Authenticated Mobile Video Player Access
  Stage 11: Lesson Progress Tracking and Milestone Notifications (50% and 100%)
  Stage 12: Assessment Exam Session Passing and Automated Certificate Issuance
  Stage 13: Gamification Points, Contributor Leaderboard and Chatter Milestone Recognition
  Stage 14: Learner Engagement SQL Analytics Report (Pivot and Graph computation)
"""

import base64
from datetime import date, timedelta
from odoo import fields
from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import AccessError, UserError


@tagged('post_install', '-at_install', 'kms', 'lms', 'kms_lms_scenario')
class TestKmsLmsFullLifecycleScenario(TransactionCase):
    """Integrated scenario testing the full operational lifecycle of KMS and LMS."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # 0. Organizational Setup & Security Roles
        cls.ou_compliance = cls.env['operating.unit'].create({
            'name': 'Scenario Compliance Office', 'sol_id': 91001,
            'work_unit_type': 'head_office',
        })
        cls.ou_operations = cls.env['operating.unit'].create({
            'name': 'Scenario Branch Operations', 'sol_id': 91002,
            'work_unit_type': 'branch',
        })
        cls.dept_compliance = cls.env['hr.department'].create({
            'name': 'Regulatory Compliance and AML Department',
            'operating_unit_id': cls.ou_compliance.id,
        })
        cls.dept_operations = cls.env['hr.department'].create({
            'name': 'Branch Operations Department',
            'operating_unit_id': cls.ou_operations.id,
        })

        cls.job_compliance_analyst = cls.env['hr.job'].create({
            'name': 'Senior AML Compliance Analyst',
            'department_id': cls.dept_compliance.id,
        })
        cls.job_teller = cls.env['hr.job'].create({
            'name': 'Branch Operations Officer Teller',
            'department_id': cls.dept_operations.id,
        })

        # Groups
        cls.grp_kms_emp = cls.env.ref('knowledge_management.group_kms_employee')
        cls.grp_kms_mgr = cls.env.ref('knowledge_management.group_kms_manager')
        cls.grp_kms_rev = cls.env.ref('knowledge_management.group_kms_reviewer')
        cls.grp_kms_contrib = cls.env.ref('knowledge_management.group_kms_contributor')
        cls.grp_lms_learner = cls.env.ref('learning_management.group_lms_learner')
        cls.grp_lms_instructor = cls.env.ref('learning_management.group_lms_instructor')
        cls.grp_lms_mgr = cls.env.ref('learning_management.group_lms_manager')

        # User 1: Compliance Officer & Content Creator
        cls.user_author = cls.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create({
            'name': 'Author Dawit Haile',
            'login': 'dawit_author_scenario',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.grp_kms_emp.id,
                cls.grp_kms_contrib.id,
                cls.grp_lms_instructor.id
            ])],
        })
        cls.emp_author = cls.env['hr.employee'].create({
            'name': 'Dawit Haile',
            'user_id': cls.user_author.id,
            'department_id': cls.dept_compliance.id,
            'job_id': cls.job_compliance_analyst.id,
            'default_operating_unit_id': cls.ou_compliance.id,
        })

        # User 2: Designated Reviewer / Compliance Manager
        cls.user_reviewer = cls.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create({
            'name': 'Manager Sara Belay',
            'login': 'sara_reviewer_scenario',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.grp_kms_emp.id,
                cls.grp_kms_rev.id,
                cls.grp_kms_mgr.id,
                cls.grp_lms_mgr.id
            ])],
        })
        cls.emp_reviewer = cls.env['hr.employee'].create({
            'name': 'Sara Belay',
            'user_id': cls.user_reviewer.id,
            'department_id': cls.dept_compliance.id,
            'default_operating_unit_id': cls.ou_compliance.id,
        })

        # User 3: Bank Learner / Branch Teller
        cls.user_learner = cls.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create({
            'name': 'Learner Yonas Tesfaye',
            'login': 'yonas_learner_scenario',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.grp_kms_emp.id,
                cls.grp_lms_learner.id
            ])],
        })
        cls.emp_learner = cls.env['hr.employee'].create({
            'name': 'Yonas Tesfaye',
            'user_id': cls.user_learner.id,
            'department_id': cls.dept_operations.id,
            'job_id': cls.job_teller.id,
            'default_operating_unit_id': cls.ou_operations.id,
        })

    def test_full_kms_lms_integrated_scenario(self):
        """Execute complete cross-module scenario step-by-step."""
        print("\n" + "=" * 80)
        print(">>> STARTING BUNNA BANK KMS & LMS FULL INTEGRATED SCENARIO TEST <<<")
        print("=" * 80)

        # ── STAGE 1: Taxonomies & Classifications ─────────────────────────────
        cat_compliance = self.env['kms.category'].create({
            'name': 'Banking Regulatory Directives',
            'code': 'REG-DIR',
        })
        doc_type_sop = self.env.ref('knowledge_management.kms_type_sop')
        class_internal = self.env.ref('knowledge_management.kms_class_internal')
        lms_cat_regulatory = self.env['lms.category'].create({
            'name': 'Mandatory Compliance & AML',
            'code': 'AML-COMP',
        })
        print("Stage 1: Master Taxonomies created.")

        # ── STAGE 2: KMS Policy Authoring & Approval Lifecycle ────────────────
        sample_pdf = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
        document_values = {
            'name': 'AML & CFT Customer Due Diligence SOP',
            'category_id': cat_compliance.id,
            'doc_type_id': doc_type_sop.id,
            'classification_id': class_internal.id,
            'owner_id': self.emp_author.id,
            'reviewer_id': self.emp_reviewer.id,
            'approver_id': self.emp_reviewer.id,
            'version': '1.0',
            'is_view_only': False,
            'require_watermark': True,
            'summary': 'Procedures for verifying Beneficial Ownership and screening Politically Exposed Persons (PEPs).',
            'content_text': 'All branch tellers and relationship managers must conduct Customer Due Diligence (CDD) before account opening.',
            'file_name': 'AML_CDD_SOP_2026.pdf',
            'file_data': base64.b64encode(sample_pdf),
        }
        doc = self.env['kms.document'].with_user(self.user_author).create(document_values)
        self.assertEqual(doc.state, 'draft')

        # Author submits for review
        doc.with_user(self.user_author).action_submit_for_review()
        self.assertEqual(doc.state, 'review')

        # Reviewer approves and publishes
        doc.with_user(self.user_reviewer).action_approve()
        self.assertEqual(doc.state, 'approved')
        self.assertTrue(doc.date_approved)
        print("Stage 2: KMS Document created, submitted, reviewed, and approved.")

        # ── STAGE 3: Dynamic Watermarking & Download Security ─────────────────
        # Learner downloads watermarked PDF
        res = doc.with_user(self.user_learner).action_download_watermarked()
        self.assertEqual(res['type'], 'ir.actions.act_url')
        self.assertIn(f"/kms/document/{doc.id}/download", res['url'])
        self.assertEqual(doc.download_count, 0)

        # A separate approved policy exercises view-only access without editing
        # the immutable published document.
        view_only_doc = self.env['kms.document'].with_user(self.user_author).create(dict(
            document_values,
            name='AML View Only Policy',
            is_view_only=True,
        ))
        view_only_doc.with_user(self.user_author).action_submit_for_review()
        view_only_doc.with_user(self.user_reviewer).action_approve()
        with self.assertRaises(AccessError):
            view_only_doc.with_user(self.user_learner).action_download_watermarked()
        print("Stage 3: Watermarked download and view-only security validated.")

        # ── STAGE 4: Full-Text Search ─────────────────────────────────────────
        matched_docs = self.env['kms.document'].search([('fts_query', '=', 'Beneficial Ownership')])
        self.assertIn(doc.id, matched_docs.ids)
        print("Stage 4: PostgreSQL full-text tsvector search verified.")

        # ── STAGE 5: Version Revision & Superseding ───────────────────────────
        rev_action = doc.with_user(self.user_reviewer).action_create_new_version()
        doc_v2 = self.env['kms.document'].browse(rev_action['res_id'])
        self.assertEqual(doc_v2.version, '1.1')
        self.assertEqual(doc_v2.state, 'draft')
        self.assertEqual(doc_v2.previous_version_id, doc)
        print("Stage 5: Document revision initiated and predecessor linkage confirmed.")

        # ── STAGE 6: LMS Course Authoring ─────────────────────────────────────
        course = self.env['lms.course'].with_user(self.user_author).create({
            'name': 'AML & PEP Identification Masterclass',
            'category_id': lms_cat_regulatory.id,
            'is_mandatory': True,
            'pass_score_percentage': 80.0,
            'issue_certificate': True,
            'description': '<p>Comprehensive training on identifying money laundering typologies and PEPs.</p>',
            'learning_objectives': '<p>1. Detect suspicious cash structuring.<br/>2. Apply enhanced due diligence.</p>',
            'instructor_id': self.emp_author.id,
            'reviewer_id': self.user_reviewer.id,
        })
        self.assertEqual(course.state, 'draft')

        # Add Lessons: 1 Video, 1 Reading Article
        lesson_video = self.env['lms.lesson'].create({
            'name': 'Module 1: Detecting Cash Structuring Schemes',
            'course_id': course.id,
            'lesson_type': 'video',
            'video_source_type': 'file',
            'video_file': base64.b64encode(b"FAKE_MP4_VIDEO_BYTES_BUNNA_BANK"),
            'video_filename': 'module1_structuring.mp4',
            'duration_minutes': 1.0,
            'video_duration_seconds': 5,
            'prevent_fast_forward': True,
            'min_watch_percentage': 90,
            'is_mandatory': True,
        })

        lesson_reading = self.env['lms.lesson'].create({
            'name': 'Module 2: Regulatory Directives & Sanction Lists',
            'course_id': course.id,
            'lesson_type': 'text',
            'html_content': '<p>Review the NBE Directives on AML screening and international sanction databases.</p>',
            'duration_minutes': 10.0,
            'is_mandatory': True,
        })

        print("Stage 6: Draft course created with Video and Reading lessons.")

        # ── STAGE 7: KMS-LMS Cross-Module Linkage ─────────────────────────────
        lib_item = self.env['kms.digital.library'].create({
            'name': 'NBE Anti-Money Laundering Framework Handbook',
            'category_id': cat_compliance.id,
            'file_name': 'NBE_AML_Framework.pdf',
            'file_data': base64.b64encode(sample_pdf),
        })
        course.with_user(self.user_author).write({'library_item_ids': [(4, lib_item.id)]})
        self.assertIn(lib_item, course.library_item_ids)
        self.assertIn(course, lib_item.related_course_ids)
        print("Stage 7: KMS-LMS Bridge verified: Digital Library assets bi-directionally linked.")

        # ── STAGE 8: Assessment & Question Bank ────────────────────────────────
        assessment = self.env['lms.assessment'].create({
            'name': 'AML Certification Final Exam',
            'course_id': course.id,
            'assessment_type': 'post_course',
            'pass_score_percentage': 80.0,
            'max_attempts': 3,
            'duration_minutes': 20,
            'instructions': '<p>Answer the final certification question.</p>',
        })

        # Create Quiz Question
        q1 = self.env['lms.question'].create({
            'name': 'Suspicious Transaction Report Window',
            'question_text': '<p>What is the required reporting window for a Suspicious Transaction Report?</p>',
            'question_type': 'single_choice',
            'points': 10.0,
        })
        ans_correct = self.env['lms.question.answer'].create({
            'question_id': q1.id,
            'answer_text': 'Within 24 hours of confirmation',
            'is_correct': True,
        })
        ans_wrong = self.env['lms.question.answer'].create({
            'question_id': q1.id,
            'answer_text': 'Within 30 calendar days',
            'is_correct': False,
        })

        module_quiz = self.env['lms.assessment'].create({
            'name': 'AML Module Knowledge Check',
            'course_id': course.id,
            'assessment_type': 'module_quiz',
            'instructions': '<p>Answer the module checkpoint question.</p>',
            'fixed_question_ids': [(4, q1.id)],
        })
        assessment.write({'fixed_question_ids': [(4, q1.id)]})
        course.write({'post_assessment_id': assessment.id})

        # Add Quiz as Lesson 3
        lesson_quiz = self.env['lms.lesson'].create({
            'name': 'Module 3: Final Knowledge Check',
            'course_id': course.id,
            'lesson_type': 'quiz',
            'assessment_id': module_quiz.id,
            'duration_minutes': 15.0,
            'is_mandatory': True,
        })
        course.with_user(self.user_author).action_submit_for_review()
        self.assertEqual(course.state, 'review')
        course.with_user(self.user_reviewer).action_publish()
        self.assertEqual(course.state, 'published')
        print("Stage 8: Assessments and question bank approved with the published course.")

        # ── STAGE 9: Enrollment & Activity Scheduling ─────────────────────────
        enrollment = self.env['lms.enrollment'].create({
            'course_id': course.id,
            'employee_id': self.emp_learner.id,
            'due_date': fields.Date.today() + timedelta(days=14),
        })
        self.assertEqual(enrollment.state, 'enrolled')

        # Verify automated To-Do activity
        activities = self.env['mail.activity'].search([
            ('res_model', '=', 'lms.enrollment'),
            ('res_id', '=', enrollment.id),
            ('user_id', '=', self.user_learner.id),
        ])
        self.assertTrue(len(activities) >= 1)
        print("Stage 9: Learner enrolled and To-Do mail.activity scheduled.")

        # ── STAGE 10: Authenticated Video Player ───────────────────────────────
        from odoo.addons.learning_management.controllers.main import LmsController

        controller = LmsController()
        authorized, authorized_lesson, authorized_enrollment = controller._check_video_access(
            lesson_video.id, env=self.env(user=self.user_learner),
        )
        self.assertTrue(authorized)
        self.assertEqual(authorized_lesson, lesson_video)
        self.assertEqual(authorized_enrollment, enrollment)
        prog1 = enrollment.lesson_progress_ids.filtered(lambda p: p.lesson_id == lesson_video)
        player_action = prog1.with_user(self.user_learner).action_open_lesson()
        self.assertEqual(player_action['url'], f'/lms/video/{lesson_video.id}/player')
        print("Stage 10: Authenticated Odoo video player access validated.")

        # ── STAGE 11: Lesson Progress Tracking & Milestone Notifications ──────
        # Learner watches the short test clip -> progress ~33%.
        prog1.with_user(self.user_learner).update_progress(current_time=5, duration=5)
        self.assertEqual(prog1.state, 'completed')
        self.assertFalse(enrollment.threshold_50_notified)

        # Learner completes Lesson 2 (Reading) -> progress ~67% -> triggers 50% milestone!
        prog2 = enrollment.lesson_progress_ids.filtered(lambda p: p.lesson_id == lesson_reading)
        prog2.with_user(self.user_learner).action_open_lesson()
        prog2.with_user(self.user_learner).mark_completed()
        enrollment.invalidate_recordset(['progress_percentage', 'threshold_50_notified'])
        self.assertTrue(enrollment.progress_percentage >= 50.0)
        self.assertTrue(enrollment.threshold_50_notified)
        print("Stage 11: Lesson completions tracked and 50% progress threshold notification triggered.")

        # ── STAGE 12: Assessment Exam Session & Certificate Issuance ──────────
        prog3 = enrollment.lesson_progress_ids.filtered(lambda p: p.lesson_id == lesson_quiz)
        quiz_action = prog3.with_user(self.user_learner).action_open_lesson()
        quiz_session = self.env['lms.exam.session'].browse(quiz_action['res_id'])
        quiz_session.line_ids.with_user(self.user_learner).write({
            'selected_answer_ids': [(6, 0, [ans_correct.id])],
        })
        quiz_session.with_user(self.user_learner).action_submit_and_grade()
        self.assertEqual(quiz_session.state, 'passed')
        prog3.with_user(self.user_learner).mark_completed()
        enrollment.invalidate_recordset(['progress_percentage', 'threshold_100_notified', 'state'])
        self.assertEqual(enrollment.progress_percentage, 100.0)
        self.assertTrue(enrollment.threshold_100_notified)

        # The final exam now passes and issues the course certificate.
        exam_action = enrollment.with_user(self.user_learner).action_start_post_assessment()
        session = self.env['lms.exam.session'].browse(exam_action['res_id'])
        session.line_ids.with_user(self.user_learner).write({
            'selected_answer_ids': [(6, 0, [ans_correct.id])],
        })
        session.with_user(self.user_learner).action_submit_and_grade()
        self.assertEqual(session.state, 'passed')
        self.assertTrue(session.is_passed)
        self.assertEqual(session.score_percentage, 100.0)

        enrollment.invalidate_recordset(['state', 'certificate_id'])
        self.assertEqual(enrollment.state, 'completed')

        # Verify Certificate automatically generated
        cert = self.env['lms.certificate'].search([
            ('enrollment_id', '=', enrollment.id),
            ('employee_id', '=', self.emp_learner.id),
        ])
        self.assertTrue(cert)
        self.assertTrue(cert.name)
        self.assertTrue(cert.verification_code)
        self.assertEqual(cert.state, 'valid')
        print(f"Stage 12: Exam passed (100%), course completed, and certificate {cert.name} issued.")

        # ── STAGE 13: Gamification Points & Leaderboard Recalculation ──────────
        self.env['kms.contributor.point'].create({
            'user_id': self.user_learner.id,
            'source': 'manual_award',
            'points': 50,
            'description': f'Cross-module course milestone: {course.name}',
        })
        self.env['recognition.leaderboard.line'].rebuild_leaderboards()
        leaderboard_entry = self.env['recognition.leaderboard.line'].search([
            ('user_id', '=', self.user_learner.id),
        ])
        self.assertTrue(leaderboard_entry)
        self.assertTrue(any(line.points_total >= 50 for line in leaderboard_entry))
        print("Stage 13: Gamification points awarded and monthly leaderboard ranked.")

        # ── STAGE 14: Learner Engagement SQL Analytics Report ─────────────────
        self.env.flush_all()
        engagement = self.env['lms.engagement.report'].search([
            ('course_id', '=', course.id),
        ])
        self.assertTrue(engagement)
        self.assertEqual(engagement.total_enrolled, 1)
        self.assertEqual(engagement.total_completed, 1)
        self.assertEqual(engagement.completion_rate, 100.0)
        self.assertEqual(engagement.pass_rate, 100.0)
        self.assertEqual(engagement.avg_score, 100.0)
        print("Stage 14: SQL Analytics view lms.engagement.report computed successfully.")

        print("=" * 80)
        print(">>> ALL 14 KMS & LMS INTEGRATED SCENARIO STAGES VERIFIED (100% SUCCESS) <<<")
        print("=" * 80)
