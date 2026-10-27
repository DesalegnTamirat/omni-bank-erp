# -*- coding: utf-8 -*-
from psycopg2 import IntegrityError
from odoo.tests.common import TransactionCase
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import mute_logger


class TestKmsPhase3Access(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.KmsDocument = cls.env['kms.document']
        cls.KmsCategory = cls.env['kms.category']
        cls.KmsClassification = cls.env['kms.classification']
        cls.KmsDocType = cls.env['kms.document.type']
        cls.KmsForumTopic = cls.env['kms.forum.topic']
        cls.KmsForumPost = cls.env['kms.forum.post']
        cls.KmsLessonLearned = cls.env['kms.lesson.learned']

        # Departments
        cls.dept_hr = cls.env['hr.department'].create({'name': 'Human Resources Testing'})
        cls.dept_fin = cls.env['hr.department'].create({'name': 'Finance Testing'})

        # Users and Employees
        cls.user_hr = cls.env['res.users'].create({
            'name': 'HR Employee User',
            'login': 'hr_employee_test@bunna.et',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('knowledge_management.group_kms_employee').id])],
        })
        cls.emp_hr = cls.env['hr.employee'].create({
            'name': 'HR Employee',
            'user_id': cls.user_hr.id,
            'department_id': cls.dept_hr.id,
        })

        cls.user_fin = cls.env['res.users'].create({
            'name': 'Finance Employee User',
            'login': 'fin_employee_test@bunna.et',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('knowledge_management.group_kms_employee').id])],
        })
        cls.emp_fin = cls.env['hr.employee'].create({
            'name': 'Finance Employee',
            'user_id': cls.user_fin.id,
            'department_id': cls.dept_fin.id,
        })

        cls.user_kms_mgr = cls.env['res.users'].create({
            'name': 'KMS Manager User',
            'login': 'kms_manager_test@bunna.et',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('knowledge_management.group_kms_manager').id])],
        })

        # Category and DocType
        cls.category = cls.KmsCategory.create({'name': 'Policy Test Category', 'code': 'POL-TEST'})
        cls.doc_type = cls.env.ref('knowledge_management.kms_type_policy', raise_if_not_found=False) or cls.KmsDocType.search([('code', '=', 'POL')], limit=1) or cls.KmsDocType.create({'name': 'Internal Policy', 'code': 'POL-TEST-P3'})

        cls.class_pub = cls.env.ref('knowledge_management.kms_class_public')
        cls.class_conf = cls.env.ref('knowledge_management.kms_class_confidential')
        cls.class_sconf = cls.env.ref('knowledge_management.kms_class_strictly_confidential')

    def test_08_nested_boolean_security_rule(self):
        """Fix 8: Record rule domain evaluates correctly across public, departmental confidential, and restricted documents."""
        # 1. Public document -> both HR and Finance can read
        doc_pub = self.KmsDocument.create({
            'name': 'Public Bank Charter',
            'category_id': self.category.id,
            'doc_type_id': self.doc_type.id,
            'classification_id': self.class_pub.id,
            'owner_id': self.emp_hr.id,
            'state': 'approved',
        })
        self.assertTrue(doc_pub.with_user(self.user_hr).read(['name']))
        self.assertTrue(doc_pub.with_user(self.user_fin).read(['name']))

        # 2. Confidential document scoped to HR department -> HR can read, Finance cannot
        doc_conf_hr = self.KmsDocument.create({
            'name': 'HR Confidential Compensation Review',
            'category_id': self.category.id,
            'doc_type_id': self.doc_type.id,
            'classification_id': self.class_conf.id,
            'owner_id': self.emp_hr.id,
            'department_id': self.dept_hr.id,
            'state': 'approved',
        })
        self.assertTrue(doc_conf_hr.with_user(self.user_hr).read(['name']))
        with self.assertRaises(AccessError):
            doc_conf_hr.with_user(self.user_fin).read(['name'])

        # 3. Confidential document with NO department (department_id=False) -> both can read
        doc_conf_all = self.KmsDocument.create({
            'name': 'Bank-Wide Confidential Strategy',
            'category_id': self.category.id,
            'doc_type_id': self.doc_type.id,
            'classification_id': self.class_conf.id,
            'owner_id': self.emp_hr.id,
            'department_id': False,
            'state': 'approved',
        })
        self.assertTrue(doc_conf_all.with_user(self.user_hr).read(['name']))
        self.assertTrue(doc_conf_all.with_user(self.user_fin).read(['name']))

        # 4. Restricted document -> only explicitly authorized employee can read
        doc_restricted = self.KmsDocument.create({
            'name': 'Strictly Restricted Executive Board Minutes',
            'category_id': self.category.id,
            'doc_type_id': self.doc_type.id,
            'classification_id': self.class_sconf.id,
            'owner_id': self.emp_hr.id,
            'authorized_employee_ids': [(4, self.emp_hr.id)],
            'state': 'approved',
        })
        self.assertTrue(doc_restricted.with_user(self.user_hr).read(['name']))
        with self.assertRaises(AccessError):
            doc_restricted.with_user(self.user_fin).read(['name'])

    def test_09_state_transition_guards(self):
        """Fix 9: Non-managers cannot transition kms.document or lms.course state directly to published/archived."""
        # KMS Document guard
        doc = self.KmsDocument.create({
            'name': 'Audit Guard Doc',
            'category_id': self.category.id,
            'doc_type_id': self.doc_type.id,
            'classification_id': self.class_pub.id,
            'owner_id': self.emp_hr.id,
            'state': 'draft',
            'file_data': b'JVBERi0xLjQK',
        })
        doc.action_submit_for_review()
        # Employee cannot set state to approved/archived
        with self.assertRaises(AccessError):
            doc.with_user(self.user_hr).write({'state': 'approved'})
        with self.assertRaises(AccessError):
            doc.with_user(self.user_hr).write({'state': 'archived'})

        # KMS Manager approves through the governed workflow, creating a snapshot.
        doc.with_user(self.user_kms_mgr).action_approve()
        self.assertEqual(doc.state, 'approved')
        self.assertEqual(len(doc.version_ids), 1)
        with self.assertRaises(AccessError):
            doc.with_user(self.user_hr).read(['file_data'])
        with self.assertRaises(AccessError):
            doc.version_ids.with_user(self.user_hr).read(['file_data'])
        doc.with_user(self.user_kms_mgr).write({'state': 'archived'})
        self.assertEqual(doc.state, 'archived')

    def test_approved_document_and_snapshot_are_immutable(self):
        doc = self.KmsDocument.create({
            'name': 'Controlled Operations Policy',
            'category_id': self.category.id,
            'doc_type_id': self.doc_type.id,
            'classification_id': self.class_pub.id,
            'owner_id': self.emp_hr.id,
            'file_name': 'operations.pdf',
            'file_data': b'JVBERi0xLjQK',
        })
        doc.with_user(self.user_kms_mgr).action_submit_for_review()
        doc.with_user(self.user_kms_mgr).action_approve()
        original_file = doc.sudo().file_data
        self.assertEqual(
            doc.with_user(self.user_hr).action_view_document()['url'],
            f'/kms/document/{doc.id}/view',
        )

        for changes in (
            {'file_data': b'Y2hhbmdlZA=='},
            {'name': 'Changed after approval'},
            {'classification_id': self.class_conf.id},
            {'state': 'review'},
        ):
            with self.assertRaises(UserError):
                doc.with_user(self.user_kms_mgr).write(changes)
        self.assertEqual(doc.sudo().file_data, original_file)
        self.assertEqual(doc.state, 'approved')

        snapshot = doc.version_ids
        self.assertEqual(len(snapshot), 1)
        with self.assertRaises(UserError):
            snapshot.with_user(self.user_kms_mgr).write({'version_number': '9.9'})
        with self.assertRaises(UserError):
            snapshot.with_user(self.user_kms_mgr).unlink()

    def test_audit_records_cannot_be_forged(self):
        Audit = self.env['kms.audit.log']
        forged = {
            'user_id': self.user_kms_mgr.id,
            'action': 'approve',
            'resource_type': 'document',
            'resource_name': 'Forged approval',
        }
        with self.assertRaises(AccessError):
            Audit.with_user(self.user_hr).create(forged)
        with self.assertRaises(AccessError):
            Audit.with_user(self.user_hr).with_context(_kms_internal_audit=True).create(forged)

        logged = Audit.with_user(self.user_hr)._log_audit_event(
            action='view', resource_type='document', resource_name='Test document',
        )
        self.assertEqual(logged.user_id, self.user_hr)
        self.assertEqual(logged.employee_id, self.emp_hr)

    def test_draft_deletion_keeps_audit_history(self):
        doc = self.KmsDocument.create({
            'name': 'Discarded Draft Procedure',
            'category_id': self.category.id,
            'doc_type_id': self.doc_type.id,
            'classification_id': self.class_pub.id,
            'owner_id': self.emp_hr.id,
        })
        code = doc.code
        doc.with_user(self.user_kms_mgr).unlink()
        self.assertFalse(doc.exists())
        audit = self.env['kms.audit.log'].search([
            ('action', '=', 'delete'), ('resource_name', 'like', code),
        ])
        self.assertEqual(len(audit), 1)
        self.assertFalse(audit.document_id)

    def test_new_classification_codes_fail_closed(self):
        custom_class = self.KmsClassification.create({
            'name': 'Executive Sensitive Test',
            'code': 'EXEC-SENSITIVE-TEST',
            'security_level': 79,
        })
        doc = self.KmsDocument.create({
            'name': 'Executive Strategy Test',
            'category_id': self.category.id,
            'doc_type_id': self.doc_type.id,
            'classification_id': custom_class.id,
            'owner_id': self.emp_hr.id,
        })
        self.assertEqual(doc.classification, 'restricted')
        with self.assertRaises(AccessError):
            doc.with_user(self.user_hr).write({'classification': 'public'})

    def test_published_classification_scope_cannot_change_via_taxonomy(self):
        classification = self.KmsClassification.create({
            'name': 'Restricted Operations Test',
            'code': 'SCONF-OPERATIONS-TEST',
            'security_level': 80,
        })
        doc = self.KmsDocument.create({
            'name': 'Restricted Operations Procedure',
            'category_id': self.category.id,
            'doc_type_id': self.doc_type.id,
            'classification_id': classification.id,
            'owner_id': self.emp_hr.id,
            'file_name': 'restricted.pdf',
            'file_data': b'JVBERi0xLjQK',
        })
        doc.with_user(self.user_kms_mgr).action_submit_for_review()
        doc.with_user(self.user_kms_mgr).action_approve()

        with self.assertRaises(UserError):
            classification.with_user(self.user_kms_mgr).write({'code': 'PUB-OPERATIONS-TEST'})
        with self.assertRaises(UserError):
            classification.with_user(self.user_kms_mgr).unlink()
        self.assertEqual(doc.classification, 'restricted')

    def test_10_vote_deduplication(self):
        """Fix 10: Forum and tacit knowledge voting prevents double counting and toggles cleanly."""
        # 1. Forum Post Vote Deduplication
        topic = self.KmsForumTopic.create({
            'name': 'How to handle exception?',
            'category_id': self.category.id,
            'author_id': self.emp_hr.id,
            'content': '<p>Details</p>',
        })
        post = self.KmsForumPost.create({
            'topic_id': topic.id,
            'author_id': self.emp_fin.id,
            'content': '<p>Follow the SOP.</p>',
        })

        self.assertEqual(post.upvote_count, 0)
        # First upvote by HR user -> increases count to 1
        post.with_user(self.user_hr).action_upvote()
        self.assertEqual(post.upvote_count, 1)

        # Second upvote by same user -> toggles/removes vote, count becomes 0
        post.with_user(self.user_hr).action_upvote()
        self.assertEqual(post.upvote_count, 0)

        # Vote again to create vote record
        post.with_user(self.user_hr).action_upvote()
        self.assertEqual(post.upvote_count, 1)

        # Direct duplicate vote creation in ORM must raise unique constraint violation
        with mute_logger('odoo.sql_db'):
            try:
                with self.cr.savepoint():
                    self.env['kms.forum.post.vote'].create({
                        'post_id': post.id,
                        'user_id': self.user_hr.id,
                        'vote_type': 'up',
                    })
                self.fail("Duplicate vote on forum post should raise constraint violation")
            except (IntegrityError, ValidationError):
                pass

        # 2. Tacit Lesson Learned Helpful Vote Deduplication
        lesson = self.KmsLessonLearned.create({
            'name': 'Core Banking Migration Lesson',
            'category_id': self.category.id,
            'project_initiative': 'CBS V2 Upgrade',
            'event_summary': 'Summary',
            'root_cause': 'Cause',
            'key_lesson': '<p>Lesson</p>',
            'mitigation_recommendation': '<p>Mitigation</p>',
            'author_id': self.emp_hr.id,
        })
        lesson.action_approve()

        self.assertEqual(lesson.helpful_votes, 0)
        # First vote by Fin user -> count becomes 1
        lesson.with_user(self.user_fin).action_vote_helpful()
        self.assertEqual(lesson.helpful_votes, 1)

        # Second vote by same user -> toggles/removes vote, count becomes 0
        lesson.with_user(self.user_fin).action_vote_helpful()
        self.assertEqual(lesson.helpful_votes, 0)

        # Vote again to create record
        lesson.with_user(self.user_fin).action_vote_helpful()
        self.assertEqual(lesson.helpful_votes, 1)

        # Direct duplicate vote creation in ORM must raise unique constraint violation
        with mute_logger('odoo.sql_db'):
            try:
                with self.cr.savepoint():
                    self.env['kms.lesson.learned.vote'].create({
                        'lesson_id': lesson.id,
                        'user_id': self.user_fin.id,
                    })
                self.fail("Duplicate vote on lesson learned should raise constraint violation")
            except (IntegrityError, ValidationError):
                pass

    def test_11_operating_unit_branch_isolation(self):
        """FR-KMS-011: Confidential documents restricted to an operating unit/branch can only be read by employees in that branch."""
        OperatingUnit = self.env.get('operating.unit')
        if not OperatingUnit:
            return
        ou_bole = OperatingUnit.create({'name': 'Bole Branch Test', 'code': 'BOLE_TEST'})
        ou_arada = OperatingUnit.create({'name': 'Arada Branch Test', 'code': 'ARADA_TEST'})

        self.emp_hr.write({'default_operating_unit_id': ou_bole.id})
        self.emp_fin.write({'default_operating_unit_id': ou_arada.id})

        # Document restricted to Bole branch
        doc_bole = self.KmsDocument.create({
            'name': 'Bole Branch Cash Handling SOP',
            'category_id': self.category.id,
            'doc_type_id': self.doc_type.id,
            'classification_id': self.class_conf.id,
            'owner_id': self.emp_hr.id,
            'department_id': False,
            'operating_unit_id': ou_bole.id,
            'state': 'approved',
        })

        # HR employee in Bole can read
        self.assertTrue(doc_bole.with_user(self.user_hr).read(['name']))
        # Finance employee in Arada cannot read
        with self.assertRaises(AccessError):
            doc_bole.with_user(self.user_fin).read(['name'])

