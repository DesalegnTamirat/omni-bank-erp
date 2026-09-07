# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo import fields


class TestCompetencyDashboard(TransactionCase):

    def setUp(self):
        super(TestCompetencyDashboard, self).setUp()
        self.cycle = self.env['competency.assessment.cycle'].search([('state', '=', 'open')], limit=1)
        if not self.cycle:
            self.cycle = self.env['competency.assessment.cycle'].create({
                'name': 'Test Assessment Cycle 2026',
                'state': 'open',
            })

    def test_01_dashboard_metrics_and_persona(self):
        """Test competency dashboard singleton instantiation, metric computations, and persona switching."""
        dashboard = self.env['competency.dashboard'].create({
            'cycle_id': self.cycle.id,
            'persona_role': 'executive',
        })
        self.assertTrue(dashboard.cycle_name)
        self.assertGreaterEqual(dashboard.total_active_competencies, 0)
        self.assertEqual(dashboard.persona_role, 'executive')

        # Test persona switching
        dashboard.persona_role = 'hrbp'
        self.assertEqual(dashboard.persona_role, 'hrbp')

        dashboard.persona_role = 'manager'
        self.assertEqual(dashboard.persona_role, 'manager')

        dashboard.persona_role = 'employee'
        self.assertEqual(dashboard.persona_role, 'employee')

    def test_02_heatmap_html_generation(self):
        """Test Department x Pillar gap heat map HTML rendering."""
        dashboard = self.env['competency.dashboard'].create({
            'cycle_id': self.cycle.id,
        })
        self.assertTrue(dashboard.heatmap_html)
        self.assertIn('Department × Pillar Competency Gap Heat Map', str(dashboard.heatmap_html))

    def test_03_dashboard_snapshot_cron_deduplication(self):
        """Test automated snapshot generation cron with active cycle guards & deduplication (FR-RPT-010)."""
        snapshot_model = self.env['competency.dashboard.snapshot']
        
        # First execution creates snapshots
        initial_count = snapshot_model._cron_take_dashboard_snapshot()
        total_after_first = snapshot_model.search_count([('cycle_id', '=', self.cycle.id)])

        # Second execution on same date should deduplicate and create 0 new snapshots
        second_count = snapshot_model._cron_take_dashboard_snapshot()
        total_after_second = snapshot_model.search_count([('cycle_id', '=', self.cycle.id)])

        self.assertEqual(second_count, 0)
        self.assertEqual(total_after_first, total_after_second)

    def test_04_scheduled_report_distribution_cron(self):
        """Test scheduled email report distribution cron with supervisor group support (FR-RPT-008)."""
        dashboard_model = self.env['competency.dashboard']
        res = dashboard_model._cron_send_scheduled_competency_reports()
        self.assertIsNotNone(res)
