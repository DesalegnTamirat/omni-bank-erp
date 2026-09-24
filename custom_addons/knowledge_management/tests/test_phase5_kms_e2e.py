# -*- coding: utf-8 -*-
from datetime import date
from dateutil.relativedelta import relativedelta
from psycopg2 import IntegrityError
from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import mute_logger


class TestKmsPhase5E2E(TransactionCase):
    """
    Comprehensive End-to-End Test Suite for Bunna Bank Knowledge Management System (KMS).
    Verifies FR-KMS-001 through FR-KMS-032 and Gamification FR-REC-003 to FR-REC-008.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.KmsDocument = cls.env['kms.document']
        cls.KmsDocVersion = cls.env['kms.document.version']
        cls.KmsCategory = cls.env['kms.category']
        cls.KmsDocType = cls.env['kms.document.type']
        cls.KmsClassification = cls.env['kms.classification']
        cls.KmsTag = cls.env['kms.tag']
        cls.KmsDigitalLibrary = cls.env['kms.digital.library']
        cls.KmsExpert = cls.env['kms.expert']
        cls.KmsExpertEndorsement = cls.env['kms.expert.endorsement']
        cls.KmsCop = cls.env['kms.cop']
        cls.KmsKnowledgeSession = cls.env['kms.knowledge.session']
        cls.KmsLessonLearned = cls.env['kms.lesson.learned']
        cls.KmsMentoringTrack = cls.env['kms.mentoring.track']
        cls.KmsMentoringMilestone = cls.env['kms.mentoring.milestone']
        cls.KmsForumTopic = cls.env['kms.forum.topic']
        cls.KmsForumPost = cls.env['kms.forum.post']
        cls.KmsContributorPoint = cls.env['kms.contributor.point']
        cls.KmsMonthlyRecognition = cls.env['kms.monthly.recognition']
        cls.KmsAuditLog = cls.env['kms.audit.log']

        # Departments (Bank validation rule forbids numbers in department names)
        cls.dept_operations = cls.env['hr.department'].create({'name': 'Banking Operations Governance Dept'})
        cls.dept_compliance = cls.env['hr.department'].create({'name': 'Compliance and AML Oversight Dept'})

        # Users and Employees
        cls.user_kms_mgr = cls.env['res.users'].create({
            'name': 'KMS Manager E2E',
            'login': 'kms_mgr_e2e@bunna.et',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('knowledge_management.group_kms_manager').id,
            ])],
        })
        cls.emp_mgr = cls.env['hr.employee'].create({
            'name': 'KMS Manager Emp',
            'user_id': cls.user_kms_mgr.id,
            'department_id': cls.dept_compliance.id,
        })

        cls.user_emp = cls.env['res.users'].create({
            'name': 'KMS Standard Employee E2E',
            'login': 'kms_emp_e2e@bunna.et',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('knowledge_management.group_kms_employee').id,
                cls.env.ref('knowledge_management.group_kms_contributor').id,
            ])],
        })
        cls.emp_std = cls.env['hr.employee'].create({
            'name': 'KMS Standard Emp',
            'user_id': cls.user_emp.id,
            'department_id': cls.dept_operations.id,
        })

        cls.user_mentor = cls.env['res.users'].create({
            'name': 'Senior Mentor User E2E',
            'login': 'kms_mentor_e2e@bunna.et',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('knowledge_management.group_kms_employee').id,
            ])],
        })
        cls.emp_mentor = cls.env['hr.employee'].create({
            'name': 'Senior Mentor Emp',
            'user_id': cls.user_mentor.id,
            'department_id': cls.dept_operations.id,
        })

        # Taxonomy Setup
        cls.parent_category = cls.KmsCategory.create({
            'name': 'Banking Operations Governance',
            'code': 'BOG-E2E',
        })
        cls.sub_category = cls.KmsCategory.create({
            'name': 'Cash & Vault Management',
            'code': 'CVM-E2E',
            'parent_id': cls.parent_category.id,
        })

        cls.doc_type_sop = cls.KmsDocType.create({
            'name': 'Standard Operating Procedure E2E',
            'code': 'SOP-E2E',
            'requires_approval': True,
        })

        cls.class_internal = cls.KmsClassification.create({
            'name': 'Internal Use E2E',
            'code': 'INT-E2E',
            'security_level': 21,
            'badge_color': 'info',
            'watermark_mandatory': True,
        })
        cls.class_confidential = cls.KmsClassification.create({
            'name': 'Confidential E2E',
            'code': 'CONF-E2E',
            'security_level': 31,
            'badge_color': 'warning',
            'view_only_default': True,
        })

    def test_01_taxonomy_configuration_and_hierarchy(self):
        """FR-KMS-002, FR-KMS-003: Taxonomy hierarchy, complete names, and unique constraints."""
        # 1. Recursive complete name calculation
        self.assertEqual(self.sub_category.complete_name, "Banking Operations Governance / Cash & Vault Management")

        # 2. Category code uniqueness
        with mute_logger('odoo.sql_db'):
            try:
                with self.cr.savepoint():
                    self.KmsCategory.create({'name': 'Duplicate Code', 'code': 'BOG-E2E'})
                self.fail("Unique constraint on category code must prevent duplicates")
            except (IntegrityError, ValidationError):
                pass

        # 3. Document tags creation
        tag1 = self.KmsTag.create({'name': 'Audit High Priority', 'color': 3})
        tag2 = self.KmsTag.create({'name': 'NBE Directive', 'color': 5})
        self.assertTrue(tag1.id and tag2.id)

    def test_02_document_lifecycle_and_version_bumping(self):
        """FR-KMS-004: Strict 4-stage document lifecycle (Draft -> Review -> Approved -> Archived) and versioning."""
        # 1. Create document in Draft
        doc = self.KmsDocument.create({
            'name': 'Vault Cash Limits and Balancing SOP',
            'category_id': self.sub_category.id,
            'doc_type_id': self.doc_type_sop.id,
            'classification_id': self.class_internal.id,
            'owner_id': self.emp_std.id,
            'file_name': 'vault_balancing_v1.pdf',
            'file_data': b'JVBERi0xLjQgQXVkaXQgVmVyc2lvbiAx',
            'version': '1.0',
            'state': 'draft',
        })
        self.assertEqual(doc.state, 'draft')
        self.assertTrue(doc.code.startswith('KMS-DOC-') or doc.code != 'New')

        # 2. Submit for review
        doc.action_submit_for_review()
        self.assertEqual(doc.state, 'review')

        # 3. Approve and publish
        doc.with_user(self.user_kms_mgr).action_approve()
        self.assertEqual(doc.state, 'approved')
        self.assertTrue(doc.is_latest_version)
        self.assertTrue(doc.date_approved)

        # Snapshot record must be stored in kms.document.version
        versions = self.KmsDocVersion.search([('document_id', '=', doc.id)])
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0].version_number, '1.0')

        # 4. Initiate new version update
        rev_action = doc.action_create_new_version()
        self.assertEqual(rev_action['res_model'], 'kms.document')
        new_doc = self.KmsDocument.browse(rev_action['res_id'])
        self.assertEqual(new_doc.version, '1.1')
        self.assertEqual(new_doc.state, 'draft')
        self.assertEqual(new_doc.previous_version_id.id, doc.id)

        # 5. Archive older document
        doc.with_user(self.user_kms_mgr).action_archive()
        self.assertEqual(doc.state, 'archived')
        self.assertFalse(doc.is_latest_version)

    def test_03_view_only_and_role_download_restrictions(self):
        """FR-KMS-014, FR-KMS-018: Strict view-only documents and role-based download restrictions."""
        # 1. View-Only document download blocking
        doc_view_only = self.KmsDocument.create({
            'name': 'Strict Executive Compensation Circular',
            'category_id': self.sub_category.id,
            'doc_type_id': self.doc_type_sop.id,
            'classification_id': self.class_confidential.id,
            'owner_id': self.emp_mgr.id,
            'file_name': 'compensation.pdf',
            'file_data': b'JVBERi0xLjQgQXVkaXQgVmlldyBPbmx5',
            'is_view_only': True,
            'state': 'approved',
        })

        # Regular employee calling action_download_watermarked -> AccessError
        with self.assertRaises(AccessError) as cm:
            doc_view_only.with_user(self.user_emp).action_download_watermarked()
        self.assertIn("Strict View-Only", str(cm.exception))

        # 2. Role-based download permissions check
        doc_role_restricted = self.KmsDocument.create({
            'name': 'Trade Secret Strategy Protocol',
            'category_id': self.sub_category.id,
            'doc_type_id': self.doc_type_sop.id,
            'classification_id': self.class_internal.id,
            'owner_id': self.emp_mgr.id,
            'file_name': 'strategy.pdf',
            'file_data': b'JVBERi0xLjQgQXVkaXQgUm9sZSBEb3dubG9hZA==',
            'is_view_only': False,
            'allowed_download_group_ids': [(4, self.env.ref('knowledge_management.group_kms_manager').id)],
            'state': 'approved',
        })

        # Regular employee (not in KMS Manager group) -> AccessError
        with self.assertRaises(AccessError) as cm:
            doc_role_restricted.with_user(self.user_emp).action_download_watermarked()
        self.assertIn("does not have download permissions", str(cm.exception))

        # Manager user calling download action succeeds and returns download url
        act = doc_role_restricted.with_user(self.user_kms_mgr).action_download_watermarked()
        self.assertIn(f"/kms/document/{doc_role_restricted.id}/download", act['url'])

    def test_04_digital_library_curation_and_recommendations(self):
        """FR-KMS-006, FR-KMS-008, FR-KMS-009: Digital library curation, role targeting, and external links."""
        # 1. Curated e-book with role and department targeting
        job_teller = self.env['hr.job'].create({'name': 'Branch Operations Teller E2E'})
        lib_item = self.KmsDigitalLibrary.create({
            'name': 'Principles of Modern Commercial Banking',
            'resource_type': 'ebook',
            'category_id': self.sub_category.id,
            'author': 'Banking Research Institute',
            'is_recommended': True,
            'curator_notes': 'Essential reading for new operations staff',
            'target_job_ids': [(4, job_teller.id)],
            'target_department_ids': [(4, self.dept_operations.id)],
            'file_name': 'commercial_banking.pdf',
            'file_data': b'JVBERi0xLjQgQXVkaXQgTGlicmFyeSBCb29r',
        })
        self.assertTrue(lib_item.is_recommended)
        self.assertIn(job_teller, lib_item.target_job_ids)

        # 2. External regulatory link resource
        ext_item = self.KmsDigitalLibrary.create({
            'name': 'National Bank of Ethiopia Directive SBB/80/2026',
            'resource_type': 'regulatory',
            'category_id': self.sub_category.id,
            'is_external_link': True,
            'external_url': 'https://nbe.gov.et/directives/sbb-80-2026.pdf',
        })
        self.assertTrue(ext_item.is_external_link)
        self.assertEqual(ext_item.external_url, 'https://nbe.gov.et/directives/sbb-80-2026.pdf')

    def test_05_subject_matter_expert_directory_and_endorsements(self):
        """FR-KMS-027: SME directory, competency integration, and peer endorsements."""
        # Create competency if model exists
        competency_model = self.env.get('competency.competency')
        comp = None
        if competency_model:
            comp = competency_model.create({
                'name': 'Credit Appraisal & Risk Analysis E2E',
                'code': 'CRED-APP-E2E',
            })

        expert = self.KmsExpert.create({
            'employee_id': self.emp_mentor.id,
            'primary_domain': 'credit',
            'expertise_summary': '<p>Over 15 years experience in trade finance and lending evaluation.</p>',
            'years_experience': 15.0,
            'availability_status': 'available',
        })
        if comp:
            expert.write({'competency_ids': [(4, comp.id)]})
            self.assertIn(comp, expert.competency_ids)

        # Peer endorsement by standard employee
        self.assertEqual(expert.endorsement_count, 0)
        expert.with_user(self.user_emp).action_endorse()
        expert.invalidate_recordset(['endorsement_count'])
        self.assertEqual(expert.endorsement_count, 1)

    def test_06_cop_and_tacit_capture_sessions(self):
        """FR-KMS-028, FR-KMS-029: Communities of Practice and tacit capture sessions with point awards."""
        cop = self.KmsCop.create({
            'name': 'Foreign Operations Specialists Community',
            'code': 'COP-FOREX-E2E',
            'category_id': self.sub_category.id,
            'lead_id': self.emp_mentor.id,
            'description': '<p>Forex operations best practice sharing</p>',
            'member_ids': [(4, self.emp_mentor.id), (4, self.emp_std.id)],
        })
        self.assertIn(self.emp_std, cop.member_ids)

        # Schedule and complete tacit capture session
        session = self.KmsKnowledgeSession.create({
            'name': 'SME Debrief on Letters of Credit Discrepancy Handling',
            'cop_id': cop.id,
            'session_type': 'expert_interview',
            'expert_id': self.emp_mentor.id,
            'facilitator_id': self.emp_mgr.id,
            'summary': '<p>Debrief on documentary LC compliance checks.</p>',
            'key_takeaways': '<p>Always verify discrepancy notice deadlines under UCP 600 Article 16.</p>',
        })
        self.assertEqual(session.state, 'planned')

        # Complete session -> triggers point award (+15 points to expert)
        session.action_complete_session()
        self.assertEqual(session.state, 'completed')

        points = self.KmsContributorPoint.search([
            ('user_id', '=', self.user_mentor.id),
            ('source', '=', 'session_delivery'),
        ])
        self.assertTrue(points, "Completing tacit knowledge session must award contributor points to the expert")
        self.assertEqual(points[0].points, 15)

    def test_07_mentoring_and_knowledge_transfer_tracking(self):
        """FR-KMS-031: Bilateral mentoring tracking, milestones, and completion sign-off."""
        track = self.KmsMentoringTrack.create({
            'name': 'New Branch Accountant Knowledge Transfer 2026',
            'mentor_id': self.emp_mentor.id,
            'mentee_id': self.emp_std.id,
            'transfer_focus': 'General ledger balancing, cash vault dual control, and NBE reporting.',
            'target_end_date': fields.Date.context_today(self) + relativedelta(months=3),
        })
        self.assertEqual(track.state, 'draft')

        # Add transfer milestone
        m1 = self.KmsMentoringMilestone.create({
            'mentoring_id': track.id,
            'name': 'Master Daily GL Reconciliation',
            'target_date': fields.Date.context_today(self) + relativedelta(weeks=2),
        })
        m1.write({'is_achieved': True, 'completion_date': fields.Date.context_today(self)})

        # Start mentoring track
        track.action_start()
        self.assertEqual(track.state, 'in_progress')

        # Complete track -> sign-off and award points to mentor (+25 points)
        track.action_complete()
        self.assertEqual(track.state, 'completed')
        self.assertTrue(track.actual_end_date)

        mentor_points = self.KmsContributorPoint.search([
            ('user_id', '=', self.user_mentor.id),
            ('source', '=', 'mentoring_signoff'),
        ])
        self.assertTrue(mentor_points, "Mentoring completion signoff must award 25 contributor points")
        self.assertEqual(mentor_points[0].points, 25)

    def test_08_discussion_forum_accepted_answer(self):
        """FR-KMS-032: Forum Q&A, accepted answer designation, and contributor rewards."""
        topic = self.KmsForumTopic.create({
            'name': 'What is the required retention period for CTR logs?',
            'category_id': self.sub_category.id,
            'author_id': self.emp_std.id,
            'content': '<p>Seeking clarification on CTR record retention timeframe.</p>',
        })
        post = self.KmsForumPost.create({
            'topic_id': topic.id,
            'author_id': self.emp_mentor.id,
            'content': '<p>Under NBE Directive, all CTR and STR documentation must be retained for at least 10 years.</p>',
        })
        self.assertFalse(topic.is_solved)
        self.assertFalse(post.is_accepted)

        # Mark answer as accepted
        post.with_user(self.user_emp).action_accept_solution()
        self.assertTrue(post.is_accepted)
        topic.invalidate_recordset(['is_solved', 'state'])
        self.assertTrue(topic.is_solved)
        self.assertEqual(topic.state, 'solved')

        # Post author receives 10 points
        pts = self.KmsContributorPoint.search([
            ('user_id', '=', self.user_mentor.id),
            ('source', '=', 'accepted_answer'),
        ])
        self.assertTrue(pts, "Marking accepted answer must award contributor points")
        self.assertEqual(pts[0].points, 10)

    def test_09_monthly_best_contributor_cron(self):
        """FR-REC-003, FR-REC-005: Best Contributor of the Month calculation and citation."""
        today = date.today()
        prev_month_date = (today - relativedelta(months=1)).replace(day=15)

        # Award points in previous month to mentor
        self.KmsContributorPoint.create({
            'user_id': self.user_mentor.id,
            'employee_id': self.emp_mentor.id,
            'points': 80,
            'source': 'document_publish',
            'description': 'Published 4 key banking SOPs',
            'date_earned': prev_month_date,
        })

        # Run monthly calculation cron
        self.KmsMonthlyRecognition.cron_calculate_monthly_winner()

        # Verify recognition record created
        recognition = self.KmsMonthlyRecognition.search([
            ('employee_id', '=', self.emp_mentor.id),
            ('period_date', '=', prev_month_date.replace(day=1)),
        ], limit=1)
        self.assertTrue(recognition, "Monthly cron must create recognition record for top contributor")
        self.assertEqual(recognition.badge, 'gold')
        self.assertEqual(recognition.points_total, 80)
        self.assertIn("Best Contributor of the Month", recognition.name)

    def test_10_immutable_audit_log_security_guard(self):
        """FR-KMS-022, Section 10 NFR: Immutable audit log security guard prevents write and unlink."""
        log = self.KmsAuditLog.sudo().create({
            'user_id': self.user_emp.id,
            'action': 'view',
            'resource_type': 'document',
            'resource_name': 'Confidential Audit Test Log',
            'details': 'Employee viewed document',
        })

        # Attempt to modify audit log record -> UserError
        with self.assertRaises(UserError) as cm_write:
            log.write({'details': 'Tampered log content'})
        self.assertIn("Audit Trail records are immutable and cannot be modified", str(cm_write.exception))

        # Attempt to delete audit log record -> UserError
        with self.assertRaises(UserError) as cm_unlink:
            log.unlink()
        self.assertIn("Audit Trail records are permanent and cannot be deleted", str(cm_unlink.exception))
