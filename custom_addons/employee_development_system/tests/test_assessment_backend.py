# -*- coding: utf-8 -*-
import uuid

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'eds_assessment_backend')
class TestAssessmentBackend(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.officer = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Assessment Officer',
            'login': 'eds_assessment_officer_' + uuid.uuid4().hex[:8],
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('employee_development_system.group_eds_officer').id,
            ])],
        })
        cls.participant = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Assessment Participant',
            'login': 'eds_assessment_participant_' + uuid.uuid4().hex[:8],
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id])],
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Assessment Participant', 'user_id': cls.participant.id,
        })
        cls.course = cls.env['eds.course'].create({'name': 'Assessment Test Course'})
        cls.session = cls.env['eds.session'].create({
            'course_id': cls.course.id,
            'date_start': '2098-04-01 09:00:00',
            'date_end': '2098-04-01 17:00:00',
        })
        cls.env['eds.enrollment'].create({
            'session_id': cls.session.id,
            'employee_id': cls.employee.id,
            'state': 'enrolled',
        })
        cls.questions = cls.env['eds.assessment.question'].create([
            {'session_id': cls.session.id, 'assessment_type': 'pre',
             'sequence': 10, 'question_text': 'First question?', 'max_points': 2},
            {'session_id': cls.session.id, 'assessment_type': 'pre',
             'sequence': 20, 'question_text': 'Second question?', 'max_points': 2},
        ])

    def test_employee_distribution_response_and_grading(self):
        model = self.env['eds.assessment'].with_user(self.officer)
        first = model.distribute_for_session(self.session, 'pre')
        self.assertEqual(len(first), 1)
        self.assertEqual(first.entry_method, 'employee')
        self.assertEqual(first.state, 'distributed')
        self.assertEqual(len(first.answer_ids), 2)
        self.assertFalse(model.distribute_for_session(self.session, 'pre'))

        own = first.with_user(self.participant)
        with self.assertRaises(AccessError):
            own.write({'score': 100})
        with self.assertRaises(AccessError):
            own.answer_ids[0].write({'awarded_points': 2, 'is_graded': True})
        for line in own.answer_ids:
            line.write({'answer_text': 'Participant response'})
        own.action_submit_answers()
        self.assertEqual(first.state, 'submitted')
        for line in first.answer_ids:
            line.with_user(self.officer).write({
                'awarded_points': 2 if line.question_id == self.questions[0] else 0,
                'is_graded': True,
            })
        first.with_user(self.officer).action_finalize()
        self.assertEqual(first.state, 'graded')
        self.assertEqual(first.score, 50.0)
        with self.assertRaises(ValidationError):
            first.with_user(self.officer).with_context(
                eds_assessment_finalize=True).write({'score': 99})
        with self.assertRaises(ValidationError):
            self.questions[0].with_user(self.officer).write({'question_text': 'Changed prompt'})

        evaluation = self.env['eds.evaluation.level2'].search([
            ('session_id', '=', self.session.id),
            ('employee_id', '=', self.employee.id),
        ])
        evaluation.write({'state': 'evaluated'})
        first.answer_ids[0].with_user(self.officer).write({'awarded_points': 1})
        self.assertEqual(first.state, 'submitted')
        self.assertEqual(first.score, 0.0)
        self.assertEqual(evaluation.state, 'draft')
        first.answer_ids[0].with_user(self.officer).write({
            'answer_text': 'A revised response needing a new grade',
        })
        self.assertFalse(first.answer_ids[0].is_graded)
        self.assertEqual(first.answer_ids[0].awarded_points, 0.0)
        with self.assertRaises(ValidationError):
            first.with_user(self.officer).action_finalize()

    def test_manual_requires_each_answer_and_grade(self):
        with self.assertRaises(ValidationError):
            self.env['eds.assessment'].with_user(self.officer).create({
                'session_id': self.session.id,
                'employee_id': self.employee.id,
                'assessment_type': 'pre',
                'entry_method': 'manual',
                'score': 75,
            })
        manual = self.env['eds.assessment'].with_user(self.officer).create({
            'session_id': self.session.id,
            'employee_id': self.employee.id,
            'assessment_type': 'pre',
            'entry_method': 'manual',
        })
        manual.action_load_questions()
        self.assertEqual(len(manual.answer_ids), 2)
        with self.assertRaises(ValidationError):
            manual.action_finalize()
        manual.answer_ids[0].write({'answer_text': 'Recorded response'})
        with self.assertRaises(ValidationError):
            self.questions[0].write({'max_points': 5})
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.env['eds.assessment.question'].create({
                'session_id': self.session.id,
                'assessment_type': 'pre',
                'question_text': 'Late question?',
                'max_points': 1,
            })
        for line in manual.answer_ids:
            line.write({'answer_text': 'Recorded response', 'is_graded': True,
                        'awarded_points': 1})
        manual.action_finalize()
        self.assertEqual(manual.score, 50.0)

    def test_unused_loaded_question_can_be_corrected(self):
        manual = self.env['eds.assessment'].with_user(self.officer).create({
            'session_id': self.session.id,
            'employee_id': self.employee.id,
            'assessment_type': 'pre',
            'entry_method': 'manual',
        })
        manual.action_load_questions()
        self.questions[0].write({'question_text': 'Corrected before answering?'})
        self.questions[1].unlink()
        self.assertEqual(len(manual.answer_ids), 1)
        self.assertEqual(manual.answer_ids.question_id, self.questions[0])

    def test_practical_skills_test_keeps_its_score_entry_path(self):
        skills = self.env['eds.assessment'].with_user(self.officer).create({
            'session_id': self.session.id,
            'employee_id': self.employee.id,
            'assessment_type': 'skills_test',
            'entry_method': 'manual',  # Default from the staff assessment action.
            'score': 70,
        })
        self.assertEqual(skills.entry_method, 'score_only')
        skills.action_finalize_skills_test()
        self.assertEqual(skills.state, 'graded')
        self.assertEqual(skills.passed, skills.score >= skills.threshold)
        with self.assertRaises(ValidationError):
            skills.write({'score': 80})
        skills.action_reopen_skills_test()
        skills.write({'score': 80})
        skills.action_finalize_skills_test()
        self.assertEqual(skills.score, 80)

    def test_direct_employee_submission_sets_timestamp(self):
        assessment = self.env['eds.assessment'].with_user(self.officer).distribute_for_session(
            self.session, 'pre')
        own = assessment.with_user(self.participant)
        for line in own.answer_ids:
            line.write({'answer_text': 'Answer entered by participant'})
        own.write({'state': 'submitted'})
        self.assertEqual(assessment.state, 'submitted')
        self.assertTrue(assessment.submitted_at)

    def test_staff_takeover_keeps_answers_and_closes_employee_editing(self):
        assessment = self.env['eds.assessment'].with_user(self.officer).distribute_for_session(
            self.session, 'pre')
        own = assessment.with_user(self.participant)
        own.answer_ids[0].write({'answer_text': 'Answer before takeover'})
        distributed_at = assessment.distributed_at
        assessment.with_user(self.officer).action_take_over_manual_entry()
        self.assertEqual(assessment.state, 'submitted')
        self.assertEqual(assessment.entry_method, 'manual')
        self.assertEqual(assessment.answer_ids[0].answer_text, 'Answer before takeover')
        self.assertEqual(assessment.distributed_at, distributed_at)
        self.assertEqual(assessment.taken_over_by, self.officer)
        self.assertTrue(assessment.taken_over_at)
        self.assertTrue(self.env['eds.assessment'].with_user(self.participant).search([
            ('id', '=', assessment.id),
        ]))
        with self.assertRaises(AccessError):
            own.answer_ids[0].write({'answer_text': 'Late change'})

    def test_new_itemized_record_requires_accepted_enrollment(self):
        other_session = self.env['eds.session'].create({
            'course_id': self.course.id,
            'date_start': '2098-04-02 09:00:00',
            'date_end': '2098-04-02 17:00:00',
        })
        with self.assertRaises(ValidationError):
            self.env['eds.assessment'].with_user(self.officer).create({
                'session_id': other_session.id,
                'employee_id': self.employee.id,
                'assessment_type': 'pre',
                'entry_method': 'manual',
            })

    def test_legacy_score_is_preserved_on_distribution(self):
        # The score existed before a question bank was introduced for the session.
        self.questions.unlink()
        legacy = self.env['eds.assessment'].create({
            'session_id': self.session.id,
            'employee_id': self.employee.id,
            'assessment_type': 'pre',
            'entry_method': 'score_only',
            'score': 72,
        })
        self.env['eds.assessment.question'].create({
            'session_id': self.session.id,
            'assessment_type': 'pre',
            'question_text': 'New question added later?',
            'max_points': 2,
        })
        self.assertFalse(self.env['eds.assessment'].with_user(self.officer).distribute_for_session(
            self.session, 'pre'))
        self.assertEqual(legacy.score, 72)
        with self.assertRaises(ValidationError):
            self.env['eds.assessment'].with_user(self.officer).create({
                'session_id': self.session.id,
                'employee_id': self.employee.id,
                'assessment_type': 'post',
                'score': 72,
            })
        blank_legacy = self.env['eds.assessment'].with_user(self.officer).create({
            'session_id': self.session.id,
            'employee_id': self.employee.id,
            'assessment_type': 'post',
        })
        with self.assertRaises(ValidationError):
            blank_legacy.with_user(self.officer).write({'score': 72})
        with self.assertRaises(ValidationError):
            legacy.action_load_questions()
        with self.assertRaises(ValidationError):
            legacy.with_user(self.officer).write({'entry_method': 'import'})
