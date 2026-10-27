# -*- coding: utf-8 -*-
from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'competency_reporting_deduplication')
class TestReportingDeduplication(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].sudo().create({
            'name': 'Reporting Deduplication Employee',
        })
        cls.cycle = cls.env['competency.assessment.cycle'].sudo().create({
            'name': 'Reporting Deduplication Cycle',
        })
        cls.competency = cls.env['competency.competency'].sudo().create({
            'name': 'Reporting Deduplication Competency',
            'code': 'TEST_REPORTING_DEDUPLICATION',
            'pillar': 'core',
            'state': 'approved',
        })
        cls.second_competency = cls.env['competency.competency'].sudo().create({
            'name': 'Second Reporting Deduplication Competency',
            'code': 'TEST_REPORTING_DEDUPLICATION_SECOND',
            'pillar': 'core',
            'state': 'approved',
        })

    def _create_assessment(self, assessment_type):
        return self.env['competency.assessment'].sudo().create({
            'cycle_id': self.cycle.id,
            'employee_id': self.employee.id,
            'assessment_type': assessment_type,
        })

    def _create_line(self, assessment, competency, current_level):
        return self.env['competency.assessment.line'].sudo().create({
            'assessment_id': assessment.id,
            'competency_id': competency.id,
            'required_level': '2',
            'current_level': current_level,
        })

    def test_daily_snapshot_counts_one_employee_and_one_line_per_competency(self):
        self_assessment = self._create_assessment('self')
        peer_assessment = self._create_assessment('peer')
        self_line = self._create_line(self_assessment, self.competency, '2')
        peer_line = self._create_line(peer_assessment, self.competency, '1')
        self._create_line(peer_assessment, self.second_competency, '1')
        self.env.flush_all()
        # Existing databases can still carry two saved primary flags.
        self.env.cr.execute(
            "UPDATE competency_assessment_line SET is_primary_reporting_line = TRUE WHERE id = %s",
            (peer_line.id,),
        )
        self.env.invalidate_all(flush=False)

        snapshot_model = self.env['competency.dashboard.snapshot'].sudo()
        snapshot_model._cron_take_dashboard_snapshot(cycle_ids=[self.cycle.id])
        domain = [
            ('cycle_id', '=', self.cycle.id),
            ('snapshot_date', '=', fields.Date.context_today(self.env.user)),
            ('department_id', '=', False),
            ('pillar', '=', 'core'),
        ]
        snapshots = snapshot_model.search(domain)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots.total_assessed, 1)
        self.assertEqual(snapshots.meets_count, 1)
        self.assertEqual(snapshots.below_count, 1)

        # Simulate a duplicate bank-wide row left by an earlier cron run.
        snapshot_model.create({
            'snapshot_date': fields.Date.context_today(self.env.user),
            'cycle_id': self.cycle.id,
            'pillar': 'core',
            'total_assessed': 99,
        })
        self_line.write({'current_level': '3'})
        self.env.flush_all()
        snapshot_model._cron_take_dashboard_snapshot(cycle_ids=[self.cycle.id])
        snapshots = snapshot_model.search(domain)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots.total_assessed, 1)
        self.assertEqual(snapshots.exceeds_count, 1)
        self.assertEqual(snapshots.meets_count, 0)

    def test_team_gap_dashboard_always_selects_primary_lines(self):
        action = self.env.ref('competency_management.action_competency_team_gap_dashboard')
        self.assertIn("('is_primary_reporting_line', '=', True)", action.domain)
        self.assertIn('search_default_filter_current_cycle', action.context)

    def test_individual_profile_uses_one_employee_and_one_line_per_competency(self):
        self_assessment = self._create_assessment('self')
        peer_assessment = self._create_assessment('peer')
        self._create_line(self_assessment, self.competency, '2')
        peer_line = self._create_line(peer_assessment, self.competency, '1')
        self._create_line(peer_assessment, self.second_competency, '1')
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE competency_assessment_line SET is_primary_reporting_line = TRUE WHERE id = %s",
            (peer_line.id,),
        )
        self.env.invalidate_all(flush=False)

        wizard = self.env['competency.report.wizard'].sudo().create({
            'cycle_id': self.cycle.id,
            'report_type': 'individual',
        })
        profiles = wizard._get_individual_profile_rows()
        employee_profiles = [
            profile for profile in profiles if profile['employee'].id == self.employee.id
        ]
        self.assertEqual(len(employee_profiles), 1)
        self.assertEqual(employee_profiles[0]['total_competencies'], 2)
        self.assertEqual(len(self_assessment.get_reporting_lines()), 2)
        matrix_rows = [
            row for row in wizard._get_360_report_data_rows()
            if row['emp_name'] == self.employee.name
        ]
        self.assertEqual(len(matrix_rows), 2)
        multi_cycle = self.env['competency.multi.cycle.report.wizard'].sudo().create({
            'cycle_ids': [(6, 0, [self.cycle.id])],
        })
        canonical_lines = multi_cycle._get_canonical_cycle_lines(self.cycle)
        self.assertEqual(len(canonical_lines.filtered(
            lambda line: line.employee_id.id == self.employee.id
        )), 2)
        action = wizard.action_apply_filter()
        self.assertEqual(action['res_model'], 'competency.assessment.line')
        self.assertIn(('is_primary_reporting_line', '=', True), action['domain'])

    def test_coverage_counts_competency_once_across_approved_mappings(self):
        job = self.env['hr.job'].sudo().create({'name': 'Reporting Coverage Job'})
        mapping_model = self.env['competency.role.mapping'].sudo().with_context(
            skip_mapping_unique_check=True,
        )
        for version in ('v1.0', 'v1.1'):
            mapping_model.create({
                'job_position_id': job.id,
                'version': version,
                'state': 'approved',
                'line_ids': [(0, 0, {'competency_id': self.competency.id})],
            })
        self.env.flush_all()

        coverage = self.env['competency.coverage.report'].sudo().search([
            ('job_id', '=', job.id),
        ])
        self.assertEqual(len(coverage), 1)
        self.assertEqual(coverage.mapped_competencies_count, 1)

