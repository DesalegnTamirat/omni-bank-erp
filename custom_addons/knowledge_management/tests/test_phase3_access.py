# -*- coding: utf-8 -*-
from psycopg2 import IntegrityError
from odoo.tests.common import TransactionCase
from odoo.exceptions import AccessError, ValidationError
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
        cls.doc_type = cls.KmsDocType.create({'name': 'Internal Policy', 'code': 'POL'})

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
        })
        # Employee cannot set state to approved/archived
        with self.assertRaises(AccessError):
            doc.with_user(self.user_hr).write({'state': 'approved'})
        with self.assertRaises(AccessError):
            doc.with_user(self.user_hr).write({'state': 'archived'})

        # KMS Manager CAN set state to approved/archived
        doc.with_user(self.user_kms_mgr).write({'state': 'approved'})
        self.assertEqual(doc.state, 'approved')
        doc.with_user(self.user_kms_mgr).write({'state': 'archived'})
        self.assertEqual(doc.state, 'archived')

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
