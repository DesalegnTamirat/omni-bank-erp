# -*- coding: utf-8 -*-
from datetime import date
from dateutil.relativedelta import relativedelta
from odoo.tests.common import TransactionCase
from odoo.exceptions import AccessError


class TestRecognitionEnginePhase5(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.RecognitionPoint = cls.env['recognition.point']
        cls.RecognitionAward = cls.env['recognition.monthly.award']

        cls.user1 = cls.env['res.users'].create({
            'name': 'Participant One',
            'login': 'part1@bunna.et',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('recognition_engine.group_recognition_user').id])],
        })
        cls.emp1 = cls.env['hr.employee'].create({
            'name': 'Participant One Emp',
            'user_id': cls.user1.id,
        })

        cls.user2 = cls.env['res.users'].create({
            'name': 'Participant Two',
            'login': 'part2@bunna.et',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('recognition_engine.group_recognition_user').id])],
        })
        cls.emp2 = cls.env['hr.employee'].create({
            'name': 'Participant Two Emp',
            'user_id': cls.user2.id,
        })

    def test_01_polymorphic_points_ledger(self):
        # 1. KMS Contribution points
        pt_kms = self.RecognitionPoint.award_points(
            user=self.user1,
            points=20,
            source_module='kms',
            source_action='document_publish',
            source_model='kms.document',
            source_res_id=101,
            description='Published AML Policy 2026'
        )
        self.assertTrue(pt_kms, 'KMS Point must be recorded')
        self.assertEqual(pt_kms.employee_id.id, self.emp1.id)
        self.assertEqual(pt_kms.source_module, 'kms')
        self.assertEqual(pt_kms.points, 20)

        # 2. LMS Learning points
        pt_lms = self.RecognitionPoint.award_points(
            user=self.user2,
            points=30,
            source_module='lms',
            source_action='course_complete',
            source_model='lms.course',
            source_res_id=202,
            description='Completed Trade Finance Mastery'
        )
        self.assertTrue(pt_lms, 'LMS Point must be recorded')
        self.assertEqual(pt_lms.employee_id.id, self.emp2.id)
        self.assertEqual(pt_lms.source_module, 'lms')
        self.assertEqual(pt_lms.points, 30)

    def test_02_monthly_awards_calculation(self):
        today = date.today()
        prev_month = (today - relativedelta(months=1)).replace(day=15)

        # Create points in previous month
        self.RecognitionPoint.create({
            'user_id': self.user1.id,
            'points': 50,
            'source_module': 'kms',
            'source_action': 'tacit_session',
            'date_earned': prev_month,
        })
        self.RecognitionPoint.create({
            'user_id': self.user2.id,
            'points': 75,
            'source_module': 'lms',
            'source_action': 'perfect_score',
            'date_earned': prev_month,
        })

        # Run monthly award calculation
        awards = self.RecognitionAward.cron_calculate_monthly_awards()
        self.assertTrue(len(awards) >= 2, 'Must calculate both KMS Best Contributor and LMS Best Learner')

        award_kms = awards.filtered(lambda a: a.award_type == 'best_contributor')
        self.assertTrue(award_kms, 'KMS award must be created')
        self.assertEqual(award_kms[0].employee_id.id, self.emp1.id)
        self.assertEqual(award_kms[0].points_total, 50)

        award_lms = awards.filtered(lambda a: a.award_type == 'best_learner')
        self.assertTrue(award_lms, 'LMS award must be created')
        self.assertEqual(award_lms[0].employee_id.id, self.emp2.id)
        self.assertEqual(award_lms[0].points_total, 75)
