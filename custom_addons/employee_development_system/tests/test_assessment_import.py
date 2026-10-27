# -*- coding: utf-8 -*-
"""Pre/post assessment CSV round-trip and idempotent import checks."""

import base64
import csv
import io
import uuid

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'eds_assessment_import')
class TestAssessmentImport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.course = cls.env['eds.course'].create({
            'name': 'Question Import Course', 'category': 'developmental',
        })
        cls.session = cls.env['eds.session'].create({
            'name': 'Question Import Session',
            'course_id': cls.course.id,
            'date_start': '2026-10-20 08:00:00',
            'date_end': '2026-10-20 17:00:00',
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'CSV Assessment Participant',
            'identification_id': 'EDS-CSV-001',
        })
        cls.env['eds.enrollment'].create({
            'session_id': cls.session.id,
            'employee_id': cls.employee.id,
            'state': 'enrolled',
        })
        cls.questions = cls.env['eds.assessment.question'].create([
            {'session_id': cls.session.id, 'assessment_type': 'pre',
             'sequence': 10, 'question_text': 'What is the first step?',
             'max_points': 5},
            {'session_id': cls.session.id, 'assessment_type': 'pre',
             'sequence': 20, 'question_text': 'Explain the second step.',
             'max_points': 10},
        ])

    def _wizard(self):
        return self.env['eds.assessment.import'].create({
            'session_id': self.session.id,
            'assessment_type': 'pre',
        })

    @staticmethod
    def _csv_file(rows, fieldnames):
        output = io.StringIO(newline='')
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        return base64.b64encode(output.getvalue().encode('utf-8-sig'))

    def _template_rows(self, wizard):
        wizard.action_download_template()
        decoded = base64.b64decode(wizard.template_file).decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(decoded))
        return list(reader), reader.fieldnames

    def test_round_trip_is_itemized_and_idempotent(self):
        wizard = self._wizard()
        rows, columns = self._template_rows(wizard)
        self.assertEqual(len(rows), 2)
        self.assertEqual({int(row['question_id']) for row in rows}, set(self.questions.ids))
        self.assertEqual({int(row['employee_id']) for row in rows}, {self.employee.id})
        for row, answer, points in zip(rows, ('Answer one', 'Answer two'), ('4', '10')):
            row['answer'] = answer
            row['awarded_points'] = points
        wizard.csv_file = self._csv_file(rows, columns)
        wizard.action_import_assessments()
        assessment = self.env['eds.assessment'].search([
            ('session_id', '=', self.session.id),
            ('employee_id', '=', self.employee.id),
            ('assessment_type', '=', 'pre'),
        ])
        self.assertEqual(len(assessment), 1)
        self.assertEqual(assessment.entry_method, 'import')
        self.assertEqual(assessment.state, 'graded')
        self.assertEqual(len(assessment.answer_ids), 2)
        self.assertAlmostEqual(assessment.score, 93.33, places=2)
        wizard.action_import_assessments()
        self.assertEqual(len(assessment.answer_ids), 2)
        self.assertEqual(self.env['eds.assessment'].search_count([
            ('session_id', '=', self.session.id),
            ('employee_id', '=', self.employee.id),
            ('assessment_type', '=', 'pre'),
        ]), 1)

    def test_blank_grades_wait_for_staff_without_losing_answers(self):
        wizard = self._wizard()
        rows, columns = self._template_rows(wizard)
        for index, row in enumerate(rows):
            row['answer'] = 'Completed response %d' % index
        rows[0]['awarded_points'] = '0'
        wizard.csv_file = self._csv_file(rows, columns)
        wizard.action_import_assessments()
        assessment = self.env['eds.assessment'].search([
            ('session_id', '=', self.session.id),
            ('employee_id', '=', self.employee.id),
            ('assessment_type', '=', 'pre'),
        ])
        self.assertEqual(assessment.state, 'submitted')
        self.assertEqual(assessment.score, 0)
        self.assertEqual(len(assessment.answer_ids), 2)
        self.assertEqual(len(assessment.answer_ids.filtered('is_graded')), 1)

    def test_formula_like_answer_is_safe_in_export_and_round_trips(self):
        wizard = self._wizard()
        rows, columns = self._template_rows(wizard)
        for row in rows:
            row['answer'] = '=SUM(1,2)'
            row['awarded_points'] = '1'
        wizard.csv_file = self._csv_file(rows, columns)
        wizard.action_import_assessments()
        exported, exported_columns = self._template_rows(wizard)
        self.assertTrue(all(row['answer'] == "'=SUM(1,2)" for row in exported))
        wizard.csv_file = self._csv_file(exported, exported_columns)
        wizard.action_import_assessments()
        assessment = self.env['eds.assessment'].search([
            ('session_id', '=', self.session.id),
            ('employee_id', '=', self.employee.id),
            ('assessment_type', '=', 'pre'),
        ])
        self.assertEqual(set(assessment.answer_ids.mapped('answer_text')),
                         {'=SUM(1,2)'})

    def test_literal_apostrophe_before_formula_round_trips(self):
        wizard = self._wizard()
        rows, columns = self._template_rows(wizard)
        # The first apostrophe is the CSV escape; the second is literal text.
        rows[0]['answer'] = "''=A1"
        rows[1]['answer'] = 'Plain answer'
        for row in rows:
            row['awarded_points'] = '1'
        wizard.csv_file = self._csv_file(rows, columns)
        wizard.action_import_assessments()
        exported, exported_columns = self._template_rows(wizard)
        self.assertEqual(exported[0]['answer'], "''=A1")
        wizard.csv_file = self._csv_file(exported, exported_columns)
        wizard.action_import_assessments()
        assessment = self.env['eds.assessment'].search([
            ('session_id', '=', self.session.id),
            ('employee_id', '=', self.employee.id),
            ('assessment_type', '=', 'pre'),
        ])
        self.assertIn("'=A1", assessment.answer_ids.mapped('answer_text'))

    def test_text_whitespace_round_trips_without_changing_question_or_answer(self):
        self.session.name = '  Question Import Session  '
        self.questions[0].question_text = '  First step?\nExplain it.  '
        wizard = self._wizard()
        rows, columns = self._template_rows(wizard)
        rows[0]['answer'] = '  An answer\nwith a second line.  '
        rows[1]['answer'] = 'Another answer'
        for row in rows:
            row['awarded_points'] = '1'
        wizard.csv_file = self._csv_file(rows, columns)
        wizard.action_import_assessments()
        assessment = self.env['eds.assessment'].search([
            ('session_id', '=', self.session.id),
            ('employee_id', '=', self.employee.id),
            ('assessment_type', '=', 'pre'),
        ])
        self.assertEqual(assessment.answer_ids.filtered(
            lambda line: line.question_id == self.questions[0]).answer_text,
            '  An answer\nwith a second line.  ')

    def test_importing_partial_grades_takes_over_open_employee_form(self):
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Assessment CSV Participant',
            'login': 'assessment_csv_participant_' + uuid.uuid4().hex[:8],
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        self.employee.user_id = user
        assessment = self.env['eds.assessment'].distribute_for_session(
            self.session, 'pre')
        assessment.answer_ids[0].with_user(user).write({
            'answer_text': 'Employee first answer',
        })
        wizard = self._wizard()
        rows, columns = self._template_rows(wizard)
        rows[1]['answer'] = 'Staff entered missing answer'
        rows[0]['awarded_points'] = '2'
        wizard.csv_file = self._csv_file(rows, columns)
        wizard.action_import_assessments()
        self.assertEqual(assessment.state, 'submitted')
        self.assertEqual(assessment.entry_method, 'import')
        self.assertTrue(assessment.taken_over_at)
        self.assertEqual(len(assessment.answer_ids.filtered('is_graded')), 1)
        with self.assertRaises(AccessError):
            assessment.answer_ids[0].with_user(user).write({
                'answer_text': 'A late change',
            })

    def test_post_uses_its_own_question_bank_and_assessment(self):
        post_question = self.env['eds.assessment.question'].create({
            'session_id': self.session.id,
            'assessment_type': 'post',
            'question_text': 'What changed after training?',
            'max_points': 4,
        })
        wizard = self.env['eds.assessment.import'].create({
            'session_id': self.session.id,
            'assessment_type': 'post',
        })
        rows, columns = self._template_rows(wizard)
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0]['question_id']), post_question.id)
        rows[0]['answer'] = 'I can now apply the process.'
        rows[0]['awarded_points'] = '3'
        wizard.csv_file = self._csv_file(rows, columns)
        wizard.action_import_assessments()
        post = self.env['eds.assessment'].search([
            ('session_id', '=', self.session.id),
            ('employee_id', '=', self.employee.id),
            ('assessment_type', '=', 'post'),
        ])
        self.assertEqual(post.state, 'graded')
        self.assertEqual(post.score, 75)
        self.assertFalse(self.env['eds.assessment'].search([
            ('session_id', '=', self.session.id),
            ('employee_id', '=', self.employee.id),
            ('assessment_type', '=', 'pre'),
        ]))

    def test_invalid_row_does_not_import_valid_rows(self):
        wizard = self._wizard()
        rows, columns = self._template_rows(wizard)
        for row in rows:
            row['answer'] = 'A completed response'
            row['awarded_points'] = '1'
        rows[1]['question_id'] = '999999999'
        wizard.csv_file = self._csv_file(rows, columns)
        with self.assertRaises(ValidationError):
            wizard.action_import_assessments()
        self.assertFalse(self.env['eds.assessment'].search([
            ('session_id', '=', self.session.id),
            ('employee_id', '=', self.employee.id),
            ('assessment_type', '=', 'pre'),
        ]))

    def test_employee_answer_requires_explicit_override(self):
        wizard = self._wizard()
        rows, columns = self._template_rows(wizard)
        for row in rows:
            row['answer'] = 'Employee submitted response'
            row['awarded_points'] = '1'
        wizard.csv_file = self._csv_file(rows, columns)
        wizard.action_import_assessments()
        assessment = self.env['eds.assessment'].search([
            ('session_id', '=', self.session.id),
            ('employee_id', '=', self.employee.id),
            ('assessment_type', '=', 'pre'),
        ])
        assessment.write({'entry_method': 'employee', 'state': 'submitted'})
        rows[0]['answer'] = 'A different response'
        wizard.csv_file = self._csv_file(rows, columns)
        with self.assertRaises(ValidationError):
            wizard.action_import_assessments()
        self.assertIn('Employee submitted response', assessment.answer_ids.mapped('answer_text'))

    def test_existing_legacy_score_needs_explicit_replacement(self):
        legacy = self.env['eds.assessment'].create({
            'session_id': self.session.id,
            'employee_id': self.employee.id,
            'assessment_type': 'pre',
        })
        legacy.write({'score': 40})
        wizard = self._wizard()
        rows, columns = self._template_rows(wizard)
        for row in rows:
            row['answer'] = 'An offline answer'
            row['awarded_points'] = '1'
        wizard.csv_file = self._csv_file(rows, columns)
        with self.assertRaises(ValidationError):
            wizard.action_import_assessments()
        self.assertEqual(legacy.score, 40)
        self.assertFalse(legacy.answer_ids)
        wizard.replace_legacy_score = True
        wizard.action_import_assessments()
        self.assertEqual(legacy.entry_method, 'import')
        self.assertEqual(legacy.state, 'graded')
        self.assertEqual(len(legacy.answer_ids), 2)

    def test_graded_legacy_score_can_be_explicitly_replaced(self):
        legacy = self.env['eds.assessment'].create({
            'session_id': self.session.id,
            'employee_id': self.employee.id,
            'assessment_type': 'pre',
            'entry_method': 'score_only',
            'state': 'graded',
        })
        legacy.write({'score': 40})
        wizard = self._wizard()
        rows, columns = self._template_rows(wizard)
        for row in rows:
            row['answer'] = 'An offline answer'
            row['awarded_points'] = '1'
        wizard.csv_file = self._csv_file(rows, columns)
        wizard.replace_legacy_score = True
        wizard.action_import_assessments()
        self.assertEqual(legacy.entry_method, 'import')
        self.assertEqual(legacy.state, 'graded')
        self.assertEqual(len(legacy.answer_ids), 2)
        self.assertAlmostEqual(legacy.score, 13.33, places=2)

