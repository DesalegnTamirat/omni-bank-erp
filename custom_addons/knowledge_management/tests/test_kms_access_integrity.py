# -*- coding: utf-8 -*-
"""Regression checks for KMS audience rules and contribution integrity."""

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase


class TestKmsAccessIntegrity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dept_a = cls.env['hr.department'].create({'name': 'KMS Access Operations'})
        cls.dept_b = cls.env['hr.department'].create({'name': 'KMS Access Finance'})
        employee = cls.env.ref('knowledge_management.group_kms_employee')
        contributor = cls.env.ref('knowledge_management.group_kms_contributor')
        reviewer = cls.env.ref('knowledge_management.group_kms_reviewer')

        def make_user(suffix, department, groups):
            user = cls.env['res.users'].create({
                'name': f'KMS Access {suffix}',
                'login': f'kms_access_{suffix.lower()}@example.test',
                'group_ids': [(6, 0, [cls.env.ref('base.group_user').id] + [group.id for group in groups])],
            })
            person = cls.env['hr.employee'].create({
                'name': f'KMS Access {suffix}',
                'user_id': user.id,
                'department_id': department.id,
            })
            return user, person

        cls.author, cls.author_employee = make_user('Author', cls.dept_a, [employee, contributor])
        cls.mentor, cls.mentor_employee = make_user('Mentor', cls.dept_a, [employee])
        cls.reviewer, cls.reviewer_employee = make_user('Reviewer', cls.dept_a, [employee, reviewer])
        cls.outsider, cls.outsider_employee = make_user('Outsider', cls.dept_b, [employee, contributor])
        cls.category = cls.env['kms.category'].create({'name': 'KMS Access Policy', 'code': 'KMS-ACCESS'})
        cls.doc_type = cls.env.ref('knowledge_management.kms_type_sop')

    def test_targeted_public_document_and_version_are_not_bank_wide(self):
        branch_a = self.env['operating.unit'].create({
            'name': 'KMS Access Branch A', 'sol_id': 99101001, 'work_unit_type': 'branch',
        })
        branch_b = self.env['operating.unit'].create({
            'name': 'KMS Access Branch B', 'sol_id': 99101002, 'work_unit_type': 'branch',
        })
        self.author_employee.default_operating_unit_id = branch_a
        self.mentor_employee.default_operating_unit_id = branch_b
        self.outsider_employee.default_operating_unit_id = branch_b
        doc = self.env['kms.document'].create({
            'name': 'Targeted Public Procedure',
            'category_id': self.category.id,
            'doc_type_id': self.doc_type.id,
            'classification_id': self.env.ref('knowledge_management.kms_class_public').id,
            'owner_id': self.author_employee.id,
            'department_id': self.dept_a.id,
            'operating_unit_id': branch_a.id,
            'file_name': 'targeted.pdf',
            'file_data': b'JVBERi0xLjQK',
        })
        doc.action_submit_for_review()
        doc.action_approve()
        version = doc.version_ids
        self.assertEqual(len(version), 1)
        self.assertTrue(doc.with_user(self.author).read(['name']))
        self.assertTrue(version.with_user(self.author).read(['version_number']))
        for user in (self.mentor, self.outsider):
            with self.assertRaises(AccessError):
                doc.with_user(user).read(['name'])
            with self.assertRaises(AccessError):
                version.with_user(user).read(['version_number'])

    def test_contributor_can_notify_reviewer_without_hr_private_access(self):
        document = self.env['kms.document'].with_user(self.author).create({
            'name': 'Reviewer notification for authored policy',
            'category_id': self.category.id,
            'doc_type_id': self.doc_type.id,
            'classification_id': self.env.ref('knowledge_management.kms_class_internal').id,
            'owner_id': self.author_employee.id,
            'reviewer_id': self.reviewer_employee.id,
            'approver_id': self.reviewer_employee.id,
            'file_name': 'review-policy.pdf',
            'file_data': b'JVBERi0xLjQK',
        })
        document.sudo().write({'authorized_employee_ids': [(4, self.author_employee.id)]})
        self.assertTrue(self.reviewer_employee.sudo().work_contact_id)
        with self.assertRaises(AccessError):
            self.reviewer_employee.with_user(self.author).read(['work_contact_id'])

        document.with_user(self.author).action_submit_for_review()
        self.assertEqual(document.state, 'review')
        self.assertTrue(self.env['mail.activity'].sudo().search([
            ('res_model', '=', 'kms.document'),
            ('res_id', '=', document.id),
            ('user_id', '=', self.reviewer.id),
        ], limit=1))
        with self.assertRaises(AccessError):
            document.with_user(self.outsider).action_approve()
        document.with_user(self.reviewer).action_approve()
        self.assertEqual(document.state, 'approved')

        revision_action = document.with_user(self.reviewer).action_create_new_version()
        revision = self.env['kms.document'].with_user(self.reviewer).browse(revision_action['res_id'])
        self.assertEqual(revision.state, 'draft')
        self.assertEqual(revision.previous_version_id, document)
        self.assertEqual(revision.sudo().authorized_employee_ids.ids, [self.author_employee.id])
        revision.write({'summary': 'Draft revision prepared by reviewer'})

    def test_mentoring_signoff_is_owned_and_awarded_once(self):
        track = self.env['kms.mentoring.track'].create({
            'name': 'Operations mentoring',
            'mentor_id': self.mentor_employee.id,
            'mentee_id': self.author_employee.id,
            'transfer_focus': 'Policy handover',
            'target_end_date': fields.Date.context_today(self),
        })
        with self.assertRaises(AccessError):
            track.with_user(self.outsider).write({'transfer_focus': 'Tampered'})
        with self.assertRaises(AccessError):
            track.with_user(self.author).action_complete()
        track.with_user(self.mentor).write({'transfer_focus': 'Private handover details'})
        audit = self.env['kms.audit.log'].search([
            ('resource_type', '=', 'mentoring'), ('action', '=', 'modify'),
            ('user_id', '=', self.mentor.id), ('details', 'ilike', 'transfer_focus'),
        ], limit=1)
        self.assertTrue(audit)
        self.assertNotIn('Private handover details', audit.details)
        track.with_user(self.mentor).action_start()
        milestone = self.env['kms.mentoring.milestone'].with_user(self.mentor).create({
            'mentoring_id': track.id,
            'name': 'Demonstrate policy handover',
            'target_date': fields.Date.context_today(self),
        })
        with self.assertRaises(UserError):
            track.with_user(self.mentor).action_complete()
        milestone.with_user(self.mentor).write({'is_achieved': True})
        track.with_user(self.mentor).action_complete()
        with self.assertRaises(UserError):
            track.with_user(self.mentor).action_complete()
        self.assertEqual(self.env['kms.contributor.point'].search_count([
            ('user_id', '=', self.mentor.id), ('source', '=', 'mentoring_signoff'),
        ]), 1)

    def test_lesson_and_session_awards_require_review_or_participation(self):
        lesson = self.env['kms.lesson.learned'].with_user(self.author).create({
            'name': 'Lessons from an incident',
            'category_id': self.category.id,
            'project_initiative': 'Operations incident',
            'department_id': self.dept_a.id,
            'event_summary': 'Summary',
            'root_cause': 'Cause',
            'key_lesson': '<p>Lesson</p>',
            'mitigation_recommendation': '<p>Action</p>',
            'author_id': self.author_employee.id,
        })
        with self.assertRaises(AccessError):
            lesson.with_user(self.author).action_approve()
        with self.assertRaises(AccessError):
            lesson.with_user(self.outsider).write({'event_summary': 'Tampered'})
        lesson.with_user(self.reviewer).action_approve()
        with self.assertRaises(UserError):
            lesson.with_user(self.reviewer).action_approve()
        self.assertEqual(self.env['kms.contributor.point'].search_count([
            ('user_id', '=', self.author.id), ('source', '=', 'lesson_learned'),
        ]), 1)

        session = self.env['kms.knowledge.session'].create({
            'name': 'Expert transfer',
            'expert_id': self.mentor_employee.id,
            'facilitator_id': self.author_employee.id,
            'summary': '<p>Context</p>',
            'key_takeaways': '<p>Takeaways</p>',
        })
        with self.assertRaises(AccessError):
            session.with_user(self.outsider).action_complete_session()
        session.with_user(self.author).action_complete_session()
        with self.assertRaises(UserError):
            session.with_user(self.author).action_complete_session()
        self.assertEqual(self.env['kms.contributor.point'].search_count([
            ('user_id', '=', self.mentor.id), ('source', '=', 'session_delivery'),
        ]), 1)

    def test_forum_solution_and_votes_cannot_farm_points(self):
        topic = self.env['kms.forum.topic'].with_user(self.author).create({
            'name': 'How should this procedure work?',
            'category_id': self.category.id,
            'author_id': self.author_employee.id,
            'content': '<p>Question</p>',
        })
        post = self.env['kms.forum.post'].with_user(self.mentor).create({
            'topic_id': topic.id,
            'author_id': self.mentor_employee.id,
            'content': '<p>Answer</p>',
        })
        with self.assertRaises(AccessError):
            post.with_user(self.outsider).action_accept_solution()
        with self.assertRaises(AccessError):
            post.with_user(self.mentor).write({'is_accepted': True})
        with self.assertRaises(AccessError):
            self.env['kms.forum.post.vote'].with_user(self.outsider).create({
                'post_id': post.id, 'user_id': self.author.id,
            })
        post.with_user(self.outsider).action_upvote()
        post.with_user(self.outsider).action_upvote()
        post.with_user(self.outsider).action_upvote()
        self.assertEqual(post.upvote_count, 1)
        self.assertEqual(self.env['kms.contributor.point'].search_count([
            ('user_id', '=', self.mentor.id), ('source', '=', 'answer_upvote'),
        ]), 1)
        topic.with_user(self.outsider).action_upvote()
        topic.with_user(self.outsider).action_upvote()
        self.assertEqual(topic.upvote_count, 0)
        post.with_user(self.author).action_accept_solution()
        post.with_user(self.author).action_accept_solution()
        self.assertEqual(self.env['kms.contributor.point'].search_count([
            ('user_id', '=', self.mentor.id), ('source', '=', 'accepted_answer'),
        ]), 1)

    def test_cancel_and_terminate_require_participation(self):
        session = self.env['kms.knowledge.session'].create({
            'name': 'Cancelled expert session',
            'expert_id': self.mentor_employee.id,
            'facilitator_id': self.author_employee.id,
            'summary': '<p>Context</p>',
            'key_takeaways': '<p>Takeaways</p>',
        })
        with self.assertRaises(AccessError):
            session.with_user(self.outsider).action_cancel_session()
        session.with_user(self.author).action_cancel_session()
        self.assertEqual(session.state, 'cancelled')
        with self.assertRaises(UserError):
            session.with_user(self.author).action_complete_session()

        track = self.env['kms.mentoring.track'].create({
            'name': 'Cancelled mentoring',
            'mentor_id': self.mentor_employee.id,
            'mentee_id': self.author_employee.id,
            'transfer_focus': 'Policy handover',
            'target_end_date': fields.Date.context_today(self),
        })
        with self.assertRaises(AccessError):
            track.with_user(self.outsider).action_terminate()
        track.with_user(self.mentor).action_terminate()
        self.assertEqual(track.state, 'terminated')
        with self.assertRaises(UserError):
            track.with_user(self.mentor).action_complete()
