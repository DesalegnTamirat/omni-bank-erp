# -*- coding: utf-8 -*-
"""Level 2 consumes the same graded result from every assessment entry path."""

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'eds_assessment_level2')
class TestAssessmentLevel2Consistency(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course = cls.env['eds.course'].create({
            'name': 'Assessment Consistency Course',
            'category': 'developmental',
        })
        cls.session = cls.env['eds.session'].create({
            'name': 'Assessment Consistency Session',
            'course_id': cls.course.id,
            'date_start': '2026-10-20 08:00:00',
            'date_end': '2026-10-20 17:00:00',
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Assessment Consistency Participant',
        })
        cls.env['eds.enrollment'].create({
            'session_id': cls.session.id,
            'employee_id': cls.employee.id,
            'state': 'enrolled',
        })
        cls.env['eds.assessment.question'].create([
            {
                'session_id': cls.session.id,
                'assessment_type': assessment_type,
                'question_text': '%s assessment question' % assessment_type,
                'max_points': 10.0,
            }
            for assessment_type in ('pre', 'post')
        ])

    def _itemized(self, assessment_type, awarded_points):
        assessment = self.env['eds.assessment'].create({
            'session_id': self.session.id,
            'employee_id': self.employee.id,
            'assessment_type': assessment_type,
            'entry_method': 'manual',
        })
        assessment.action_load_questions()
        assessment.answer_ids.write({
            'answer_text': 'An actual response to the question',
            'awarded_points': awarded_points,
            'is_graded': True,
        })
        assessment.action_finalize()
        return assessment

    def test_level2_uses_linked_question_results_over_raw_fields(self):
        pre = self._itemized('pre', 4.0)
        evaluation = self.env['eds.evaluation.level2'].search([
            ('session_id', '=', self.session.id),
            ('employee_id', '=', self.employee.id),
        ])
        self.assertEqual(evaluation.pre_assessment_id, pre)
        with self.assertRaises(ValidationError):
            evaluation.action_evaluate()

        post = self._itemized('post', 9.0)
        evaluation.write({
            'pre_test_score': 100.0,
            'post_test_score': 1.0,
            'total_marks': 100.0,
        })
        self.assertEqual(evaluation.post_assessment_id, post)
        self.assertEqual(evaluation.pre_test_pct, 40.0)
        self.assertEqual(evaluation.post_test_pct, 90.0)
        self.assertEqual(evaluation.learning_gain, 50.0)
        self.assertTrue(evaluation.passed)
        evaluation.action_evaluate()
        self.assertEqual(evaluation.state, 'evaluated')

        post.answer_ids.write({'awarded_points': 0.0})
        self.assertEqual(post.state, 'submitted')
        self.assertEqual(post.score, 0.0)
        self.assertEqual(evaluation.post_test_pct, 0.0)
        self.assertFalse(evaluation.passed)
        with self.assertRaises(ValidationError):
            evaluation.action_evaluate()

    def test_historical_score_only_assessments_remain_usable(self):
        # Old records have no question rows and must keep their score.
        legacy_session = self.env['eds.session'].create({
            'name': 'Historical Level 2 Session',
            'course_id': self.course.id,
            'date_start': '2026-09-20 08:00:00',
            'date_end': '2026-09-20 17:00:00',
        })
        self.env['eds.enrollment'].create({
            'session_id': legacy_session.id,
            'employee_id': self.employee.id,
            'state': 'enrolled',
        })
        for assessment_type, score in (('pre', 30.0), ('post', 88.0)):
            self.env['eds.assessment'].create({
                'session_id': legacy_session.id,
                'employee_id': self.employee.id,
                'assessment_type': assessment_type,
                'score': score,
            })
        evaluation = self.env['eds.evaluation.level2'].search([
            ('session_id', '=', legacy_session.id),
            ('employee_id', '=', self.employee.id),
        ])
        self.assertEqual(evaluation.pre_test_pct, 30.0)
        self.assertEqual(evaluation.post_test_pct, 88.0)
        self.assertEqual(evaluation.learning_gain, 58.0)
        evaluation.action_evaluate()
        self.assertEqual(evaluation.state, 'evaluated')
