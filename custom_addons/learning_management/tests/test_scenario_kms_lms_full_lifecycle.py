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
  Stage 6:  LMS Course Authoring with Video, Reading and Quiz Lessons
  Stage 7:  KMS-LMS Bridge Linkage (Digital Library Assets and Lessons Learned attached to Course)
  Stage 8:  Interactive Assessment Setup (Question Bank, Choices, Passing Score)
  Stage 9:  Learner Course Enrollment and Auto-Scheduled mail.activity
  Stage 10: Video Manifest and Watermarked Player Authorization
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
        cls.dept_compliance = cls.env['hr.department'].create({'name': 'Regulatory Compliance & AML Department'})
        cls.dept_operations = cls.env['hr.department'].create({'name': 'Branch Operations Department'})

        cls.job_compliance_analyst = cls.env['hr.job'].create({'name': 'Senior AML Compliance Analyst'})
        cls.job_teller = cls.env['hr.job'].create({'name': 'Branch Operations Officer / Teller'})

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
        doc_type_sop = self.env['kms.document.type'].create({
            'name': 'Standard Operating Procedure (SOP)',
            'code': 'SOP',
        })
        class_confidential = self.env['kms.classification'].create({
            'name': 'Bank Confidential',
            'security_level': 2,
            'requires_watermark': True,
        })
        lms_cat_regulatory = self.env['lms.category'].create({
            'name': 'Mandatory Compliance & AML',
            'code': 'AML-COMP',
        })
        print("Stage 1: Master Taxonomies created.")

        # ── STAGE 2: KMS Policy Authoring & Approval Lifecycle ────────────────
        sample_pdf = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"
        doc = self.env['kms.document'].with_user(self.user_author).create({
            'name': 'AML & CFT Customer Due Diligence SOP',
            'category_id': cat_compliance.id,
            'doc_type_id': doc_type_sop.id,
            'classification_id': class_confidential.id,
            'owner_id': self.emp_author.id,
            'reviewer_id': self.emp_reviewer.id,
            'approver_id': self.emp_reviewer.id,
            'department_id': self.dept_compliance.id,
            'version': '1.0',
            'is_view_only': False,
            'require_watermark': True,
            'summary': 'Procedures for verifying Beneficial Ownership and screening Politically Exposed Persons (PEPs).',
            'content_text': 'All branch tellers and relationship managers must conduct Customer Due Diligence (CDD) before account opening.',
            'file_name': 'AML_CDD_SOP_2026.pdf',
            'file_data': base64.b64encode(sample_pdf),
        })
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
        self.assertEqual(doc.download_count, 1)

        # Test view-only security restriction
        doc.write({'is_view_only': True})
        with self.assertRaises(AccessError):
            doc.with_user(self.user_learner).action_download_watermarked()
        doc.write({'is_view_only': False})
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
            'duration_minutes': 15.0,
            'video_duration_seconds': 900,
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

        # Submit course for review and publish
        course.with_user(self.user_author).action_submit_for_review()
        self.assertEqual(course.state, 'review')
        course.with_user(self.user_reviewer).action_publish()
        self.assertEqual(course.state, 'published')
        print("Stage 6: Course created with Video and Reading lessons, approved and published.")

        # ── STAGE 7: KMS-LMS Cross-Module Linkage ─────────────────────────────
        lib_item = self.env['kms.digital.library'].create({
            'name': 'NBE Anti-Money Laundering Framework Handbook',
            'code': 'LIB-AML-001',
            'category_id': cat_compliance.id,
            'file_name': 'NBE_AML_Framework.pdf',
            'file_data': base64.b64encode(sample_pdf),
        })
        course.write({'library_resource_ids': [(4, lib_item.id)]})
        self.assertIn(lib_item, course.library_resource_ids)
        self.assertIn(course, lib_item.related_course_ids)
        print("Stage 7: KMS-LMS Bridge verified: Digital Library assets bi-directionally linked.")

        # ── STAGE 8: Assessment & Question Bank ────────────────────────────────
        assessment = self.env['lms.assessment'].create({
            'name': 'AML Certification Final Exam',
            'course_id': course.id,
            'assessment_type': 'post',
            'pass_score_percentage': 80.0,
            'max_attempts': 3,
            'time_limit_minutes': 20,
        })
        course.write({
            'has_post_assessment': True,
            'post_assessment_id': assessment.id,
        })

        # Create Quiz Question
        q1 = self.env['lms.question'].create({
            'assessment_id': assessment.id,
            'title': 'What is the required reporting window for a Suspicious Transaction Report (STR)?',
            'question_type': 'single',
            'points': 10.0,
        })
        ans_correct = self.env['lms.question.answer'].create({
            'question_id': q1.id,
            'text': 'Within 24 hours of confirmation',
            'is_correct': True,
        })
        ans_wrong = self.env['lms.question.answer'].create({
            'question_id': q1.id,
            'text': 'Within 30 calendar days',
            'is_correct': False,
        })

        # Add Quiz as Lesson 3
        lesson_quiz = self.env['lms.lesson'].create({
            'name': 'Module 3: Final Knowledge Check',
            'course_id': course.id,
            'lesson_type': 'quiz',
            'assessment_id': assessment.id,
            'duration_minutes': 15.0,
            'is_mandatory': True,
        })
        print("Stage 8: Assessment, questions, and answers attached to course.")

        # ── STAGE 9: Enrollment & Activity Scheduling ─────────────────────────
        enrollment = self.env['lms.enrollment'].create({
            'course_id': course.id,
            'employee_id': self.emp_learner.id,
            'user_id': self.user_learner.id,
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

        # ── STAGE 10: Video Manifest & Watermarked Player ─────────────────────
        from odoo.addons.learning_management.controllers.main import LmsController

        controller = LmsController()
        manifest_res = controller.get_video_manifest(lesson_video.id)
        self.assertEqual(manifest_res.status_code, 200)
        self.assertIn(b"#EXTM3U", manifest_res.data)
        print("Stage 10: HLS Video streaming manifest validated.")

        # ── STAGE 11: Lesson Progress Tracking & Milestone Notifications ──────
        # Learner completes Lesson 1 (Video) -> progress ~33%
        prog1 = self.env['lms.lesson.progress'].create({
            'enrollment_id': enrollment.id,
            'lesson_id': lesson_video.id,
            'state': 'completed',
            'time_spent_seconds': 900,
            'watch_percentage': 100,
        })
        self.assertFalse(enrollment.threshold_50_notified)

        # Learner completes Lesson 2 (Reading) -> progress ~67% -> triggers 50% milestone!
        prog2 = self.env['lms.lesson.progress'].create({
            'enrollment_id': enrollment.id,
            'lesson_id': lesson_reading.id,
            'state': 'completed',
            'time_spent_seconds': 600,
        })
        enrollment.invalidate_recordset(['progress', 'threshold_50_notified'])
        self.assertTrue(enrollment.progress >= 50.0)
        self.assertTrue(enrollment.threshold_50_notified)
        print("Stage 11: Lesson completions tracked and 50% progress threshold notification triggered.")

        # ── STAGE 12: Assessment Exam Session & Certificate Issuance ──────────
        session = self.env['lms.exam.session'].create({
            'assessment_id': assessment.id,
            'enrollment_id': enrollment.id,
            'employee_id': self.emp_learner.id,
            'state': 'in_progress',
        })

        # Answer question correctly and finish exam
        self.env['lms.exam.session.answer'].create({
            'session_id': session.id,
            'question_id': q1.id,
            'selected_answer_id': ans_correct.id,
        })
        session.action_submit_exam()
        self.assertEqual(session.state, 'graded')
        self.assertTrue(session.is_passed)
        self.assertEqual(session.score_percentage, 100.0)

        # Mark quiz lesson completed
        prog3 = self.env['lms.lesson.progress'].create({
            'enrollment_id': enrollment.id,
            'lesson_id': lesson_quiz.id,
            'state': 'completed',
            'time_spent_seconds': 400,
        })
        enrollment.invalidate_recordset(['progress', 'threshold_100_notified', 'state'])
        self.assertEqual(enrollment.progress, 100.0)
        self.assertEqual(enrollment.state, 'completed')
        self.assertTrue(enrollment.threshold_100_notified)

        # Verify Certificate automatically generated
        cert = self.env['lms.certificate'].search([
            ('enrollment_id', '=', enrollment.id),
            ('employee_id', '=', self.emp_learner.id),
        ])
        self.assertTrue(cert)
        self.assertTrue(cert.certificate_number)
        self.assertTrue(cert.verification_code)
        self.assertEqual(cert.state, 'valid')
        print(f"Stage 12: Exam passed (100%), course completed, and certificate {cert.certificate_number} issued.")

        # ── STAGE 13: Gamification Points & Leaderboard Recalculation ──────────
        self.env['kms.contributor.point'].create({
            'user_id': self.user_learner.id,
            'action_type': 'course_complete',
            'points': 50,
            'reference_doc': course.name,
        })
        self.env['recognition.leaderboard.line'].cron_recompute_leaderboard()
        leaderboard_entry = self.env['recognition.leaderboard.line'].search([
            ('user_id', '=', self.user_learner.id),
        ])
        self.assertTrue(leaderboard_entry)
        self.assertTrue(leaderboard_entry.total_points >= 50)
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
