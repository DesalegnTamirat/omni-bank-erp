# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestFrameworkIntegrationAndGapFixes(TransactionCase):
    """Unit tests for Framework Integration, AbstractModel DQ Cron, Benchmarking, Deduplication, and Recruitment API."""

    def setUp(self):
        super().setUp()
        self.Job = self.env['hr.job']
        self.Competency = self.env['competency.competency']
        self.Framework = self.env['competency.framework']
        self.FrameworkLine = self.env['competency.framework.line']
        self.Mapping = self.env['competency.role.mapping']
        self.MappingLine = self.env['competency.role.mapping.line']
        self.Assessment = self.env['competency.assessment']
        self.AssessmentLine = self.env['competency.assessment.line']
        self.Cycle = self.env['competency.assessment.cycle']
        self.Benchmark = self.env['competency.benchmark']
        self.BenchmarkComparison = self.env['competency.benchmark.comparison']
        self.SkillsTest = self.env['competency.skills.test']

        self.job = self.Job.create({'name': 'Senior Recruitment Specialist F6'})

        # Competency without approved framework
        self.comp_unapproved = self.Competency.create({
            'name': 'Unapproved Competency F6',
            'code': 'UNAPP_F6_001',
            'pillar': 'technical',
        })

        # Competency with approved framework
        self.comp_approved = self.Competency.create({
            'name': 'Approved Framework Competency F6',
            'code': 'APP_F6_002',
            'pillar': 'core',
        })

        self.framework = self.Framework.create({
            'name': 'Banking Operational Framework F6',
            'code': 'BOF_F6_001',
            'version': 'v1.0',
            'line_ids': [(0, 0, {'competency_id': self.comp_approved.id})]
        })
        self.framework.action_submit_for_approval()
        self.framework.action_approve()

    def test_01_approved_framework_constraint_on_lines(self):
        """1. Verify that saving a line with an unapproved competency raises ValidationError."""
        self.assertTrue(self.comp_approved.approved_framework_ids)
        self.assertFalse(self.comp_unapproved.approved_framework_ids)

        mapping = self.Mapping.create({
            'job_position_id': self.job.id,
            'version': 'v1.0',
        })

        # Saving unapproved competency on role mapping line must fail
        with self.assertRaises(ValidationError):
            self.MappingLine.create({
                'mapping_id': mapping.id,
                'competency_id': self.comp_unapproved.id,
                'required_proficiency': '3',
            })

        # Saving approved competency succeeds
        line = self.MappingLine.create({
            'mapping_id': mapping.id,
            'competency_id': self.comp_approved.id,
            'required_proficiency': '3',
        })
        self.assertTrue(line.id)

    def test_02_data_quality_cron_on_abstract_model(self):
        """2. Verify AbstractModel Data Quality Cron executes cleanly."""
        Validator = self.env['competency.data.validator']
        Validator._cron_validate_competency_data_quality()

    def test_03_case_insensitive_name_deduplication(self):
        """3. Verify case-insensitive dictionary name deduplication constraint."""
        with self.assertRaises(ValidationError):
            self.Competency.create({
                'name': 'APPROVED FRAMEWORK COMPETENCY F6',
                'code': 'DUP_F6_999',
                'pillar': 'technical',
            })

    def test_04_team_dashboard_and_benchmarking(self):
        """4. Verify Benchmarking standard creation and Comparison view."""
        bm = self.Benchmark.create({
            'competency_id': self.comp_approved.id,
            'source': 'internal',
            'benchmark_level': '4',
        })
        self.assertTrue(bm.id)
        self.assertIn('Level 4', bm.name)

    def test_05_recruitment_integration_api(self):
        """5. Verify recruitment candidate screening API method get_role_competency_requirements."""
        mapping = self.Mapping.create({
            'job_position_id': self.job.id,
            'version': 'v1.0',
            'line_ids': [(0, 0, {'competency_id': self.comp_approved.id, 'required_proficiency': '3'})]
        })
        mapping.action_submit_for_approval()
        mapping.action_approve()

        reqs = self.Mapping.get_role_competency_requirements(self.job.id)
        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0]['competency_id'], self.comp_approved.id)
        self.assertEqual(reqs[0]['required_proficiency'], '3')
