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
        """Fix 3: Test competency dashboard get_dashboard_data RPC method and persona switching."""
        dashboard_model = self.env['competency.dashboard']
        data = dashboard_model.get_dashboard_data(cycle_id=self.cycle.id, persona='executive')
        self.assertTrue(data.get('stats'))
        self.assertIn('total_assessments', data['stats'])
        self.assertGreaterEqual(data['stats']['total_assessments'], 0)

        # Test persona switching via RPC get_dashboard_data
        data_hrbp = dashboard_model.get_dashboard_data(cycle_id=self.cycle.id, persona='hrbp')
        self.assertEqual(data_hrbp['persona'], 'hrbp')

        data_manager = dashboard_model.get_dashboard_data(cycle_id=self.cycle.id, persona='manager')
        self.assertEqual(data_manager['persona'], 'manager')

        data_emp = dashboard_model.get_dashboard_data(cycle_id=self.cycle.id, persona='employee')
        self.assertEqual(data_emp['persona'], 'employee')

    def test_02_heatmap_rows_generation(self):
        """Fix 3 & Fix 5: Test Department x Pillar gap heatmap data returned by get_dashboard_data."""
        dashboard_model = self.env['competency.dashboard']
        data = dashboard_model.get_dashboard_data(cycle_id=self.cycle.id)
        self.assertIn('heatmap_rows', data)
        self.assertIsInstance(data['heatmap_rows'], list)

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
        snapshot_model = self.env['competency.dashboard.snapshot']
        res = snapshot_model._cron_send_scheduled_competency_reports()
        self.assertIsNotNone(res)
