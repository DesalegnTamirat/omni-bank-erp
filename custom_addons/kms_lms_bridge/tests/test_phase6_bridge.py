# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestKmsLmsBridge(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.LmsCourse = cls.env['lms.course']
        cls.LmsCategory = cls.env['lms.category']
        cls.KmsCategory = cls.env['kms.category']
        cls.KmsLibrary = cls.env['kms.digital.library']
        cls.KmsLesson = cls.env['kms.lesson.learned']

        cls.user = cls.env['res.users'].create({
            'name': 'Bridge Officer',
            'login': 'bridge_officer@bunna.et',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('learning_management.group_lms_manager').id,
                cls.env.ref('knowledge_management.group_kms_manager').id,
            ])],
        })
        cls.emp = cls.env['hr.employee'].create({
            'name': 'Bridge Officer Emp',
            'user_id': cls.user.id,
        })

        cls.lms_cat = cls.LmsCategory.create({'name': 'Banking Operations', 'code': 'OPS'})
        cls.kms_cat = cls.KmsCategory.create({'name': 'Regulatory Compliance', 'code': 'REG'})

    def test_bidirectional_course_library_and_lesson_linkage(self):
        # 1. Create Course
        course = self.LmsCourse.create({
            'name': 'Anti-Money Laundering Comprehensive',
            'category_id': self.lms_cat.id,
            'description': '<p>AML Training</p>',
            'instructor_id': self.emp.id,
        })

        # 2. Create Digital Library Item
        lib_item = self.KmsLibrary.create({
            'name': 'National Bank of Ethiopia AML Directives Compendium',
            'category_id': self.kms_cat.id,
            'resource_type': 'regulatory',
            'author': 'NBE Governance',
        })

        # 3. Create Lesson Learned
        lesson = self.KmsLesson.create({
            'name': 'Branch Inspection Finding on Suspicious Transaction Reporting',
            'category_id': self.kms_cat.id,
            'project_initiative': 'Audit Followup 2026',
            'event_summary': 'Summary',
            'root_cause': 'Cause',
            'key_lesson': '<p>Always verify CTR before end of day</p>',
            'mitigation_recommendation': '<p>Automate daily verification checklist</p>',
            'author_id': self.emp.id,
        })

        # Link from course
        course.write({
            'library_resource_ids': [(4, lib_item.id)],
            'lesson_learned_ids': [(4, lesson.id)],
        })

        # Verify course side
        self.assertIn(lib_item, course.library_resource_ids)
        self.assertIn(lesson, course.lesson_learned_ids)
        self.assertEqual(course.library_resource_count, 1)
        self.assertEqual(course.lesson_learned_count, 1)

        # Verify reverse side (bidirectional)
        self.assertIn(course, lib_item.related_course_ids)
        self.assertIn(course, lesson.related_course_ids)

        # Test stat actions
        action_lib = course.action_view_library_resources()
        self.assertEqual(action_lib['res_model'], 'kms.digital.library')
        self.assertIn(lib_item.id, action_lib['domain'][0][2])

        action_les = course.action_view_lessons_learned()
        self.assertEqual(action_les['res_model'], 'kms.lesson.learned')
        self.assertIn(lesson.id, action_les['domain'][0][2])
