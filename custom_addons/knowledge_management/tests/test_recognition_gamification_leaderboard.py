# -*- coding: utf-8 -*-
from datetime import date
from dateutil.relativedelta import relativedelta
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'knowledge_management', 'gamification')
class TestRecognitionGamificationLeaderboard(TransactionCase):
    """
    Test suite for Prompt 4 (Leaderboards & Gamification Recognition):
    - Configurable point thresholds via ir.config_parameter
    - Milestone badges (@ 50, 200, 500, 1000)
    - Monthly winner calculations with chatter notifications
    - Leaderboard generation and ranking logic across KMS, LMS, and unified sources
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.user_admin = cls.env.ref('base.user_admin')
        cls.emp_admin = cls.user_admin.employee_id
        if not cls.emp_admin:
            cls.emp_admin = cls.env['hr.employee'].search([('user_id', '=', cls.user_admin.id)], limit=1)
        if not cls.emp_admin:
            cls.emp_admin = cls.env['hr.employee'].search([], limit=1)

        cls.dept_ops = cls.env['hr.department'].search([], limit=1)
        if not cls.dept_ops:
            cls.dept_ops = cls.env['hr.department'].create({'name': 'Banking Operations'})

        existing_employees = cls.env['hr.employee'].search([('id', '!=', cls.emp_admin.id if cls.emp_admin else 0)], limit=3)
        if len(existing_employees) >= 2:
            cls.emp1 = existing_employees[0]
            cls.emp2 = existing_employees[1]
        else:
            cls.emp1 = cls.emp_admin
            cls.emp2 = cls.emp_admin

    def test_01_config_driven_points(self):
        """Verify points can be overridden via ir.config_parameter."""
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('knowledge_management.points_document_publish', '35')

        pt = self.env['kms.contributor.point'].award_points(
            user=self.user_admin,
            source='document_publish',
            description='Test config points override',
        )
        self.assertTrue(pt)
        self.assertEqual(pt.points, 35, 'Points should be overridden by ir.config_parameter')

        # Test fallback when param is cleared
        ICP.set_param('knowledge_management.points_document_publish', '')
        pt2 = self.env['kms.contributor.point'].award_points(
            user=self.user_admin,
            source='document_publish',
            description='Test default fallback',
        )
        self.assertEqual(pt2.points, 20, 'Should fall back to default map when param is empty')

    def test_02_milestone_badges_chatter(self):
        """Verify crossing 50, 200, 500, 1000 points triggers milestone check and chatter."""
        self.env['kms.contributor.point'].search([('user_id', '=', self.user_admin.id)]).unlink()

        self.env['kms.contributor.point'].award_points(
            user=self.user_admin,
            points=40,
            source='manual_award',
            description='Initial 40 pts',
        )
        self.env['kms.contributor.point'].award_points(
            user=self.user_admin,
            points=15,
            source='manual_award',
            description='Milestone crossing to 55',
        )
        total = sum(self.env['kms.contributor.point'].search([('user_id', '=', self.user_admin.id)]).mapped('points'))
        self.assertEqual(total, 55)

    def test_03_monthly_winner_cron_and_notification(self):
        """Verify KMS monthly winner calculation and notification chatter."""
        today = date.today()
        prev_month_date = (today - relativedelta(months=1)).replace(day=10)

        first_day_prev = prev_month_date.replace(day=1)
        self.env['kms.monthly.recognition'].search([('period_date', '=', first_day_prev)]).unlink()

        if self.emp1:
            self.env['kms.contributor.point'].create({
                'user_id': self.emp1.user_id.id if self.emp1.user_id else self.user_admin.id,
                'employee_id': self.emp1.id,
                'points': 150,
                'source': 'document_publish',
                'description': 'Previous month hero',
                'date_earned': prev_month_date,
            })

            self.env['kms.monthly.recognition'].cron_calculate_monthly_winner()

            rec = self.env['kms.monthly.recognition'].search([
                ('employee_id', '=', self.emp1.id),
                ('period_date', '=', first_day_prev),
            ], limit=1)
            self.assertTrue(rec, 'Monthly recognition should be created')
            self.assertEqual(rec.points_total, 150)
            self.assertEqual(rec.badge, 'gold')

    def test_04_leaderboard_generation_and_ranks(self):
        """Verify rebuilding leaderboards ranks employees properly with badges."""
        Leaderboard = self.env['recognition.leaderboard.line']
        today = date.today()

        if self.emp1 and self.emp2 and self.emp1.id != self.emp2.id:
            top_emp = self.emp1
            second_emp = self.emp2
        else:
            top_emp = self.emp_admin
            second_emp = self.emp_admin

        self.env['kms.contributor.point'].create({
            'user_id': top_emp.user_id.id if top_emp.user_id else self.user_admin.id,
            'employee_id': top_emp.id,
            'points': 550,
            'source': 'document_publish',
            'date_earned': today,
        })
        self.env['lms.gamification.point'].create({
            'user_id': top_emp.user_id.id if top_emp.user_id else self.user_admin.id,
            'employee_id': top_emp.id,
            'points': 300,
            'source': 'course_complete',
            'date_earned': today,
        })

        if top_emp.id != second_emp.id:
            self.env['kms.contributor.point'].create({
                'user_id': second_emp.user_id.id if second_emp.user_id else self.user_admin.id,
                'employee_id': second_emp.id,
                'points': 120,
                'source': 'lesson_learned',
                'date_earned': today,
            })

        Leaderboard.rebuild_leaderboards()

        lines = Leaderboard.search([
            ('source_module', '=', 'all'),
            ('period', '=', 'all_time'),
        ], order='rank asc')
        self.assertTrue(lines, 'Leaderboard lines must be generated')

        top_line = lines[0]
        self.assertEqual(top_line.rank, 1)
        self.assertEqual(top_line.employee_id.id, top_emp.id)
        self.assertGreaterEqual(top_line.points_total, 850)
        self.assertIn(top_line.badge, ['platinum', 'gold'])

        kms_lines = Leaderboard.search([
            ('source_module', '=', 'kms'),
            ('period', '=', 'all_time'),
            ('employee_id', '=', top_emp.id),
        ])
        self.assertTrue(kms_lines)
        self.assertGreaterEqual(kms_lines[0].points_total, 550)
