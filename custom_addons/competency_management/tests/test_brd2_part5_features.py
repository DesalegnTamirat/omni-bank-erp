# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError, UserError


class TestBRD2Part5Features(TransactionCase):
    """Unit tests for BRD-2 Part 5 features: Clusters, Bulk Mapping, Multi-Source 360, Skills Tests, Coverage, and LMS Link."""

    def setUp(self):
        super().setUp()
        self.Job = self.env['hr.job']
        self.Competency = self.env['competency.competency']
        self.Cluster = self.env['competency.cluster']
        self.Mapping = self.env['competency.role.mapping']
        self.Assessment = self.env['competency.assessment']
        self.AssessmentLine = self.env['competency.assessment.line']
        self.SkillsTest = self.env['competency.skills.test']

        self.job_source = self.Job.create({'name': 'Senior Risk Manager BRD2'})
        self.job_target1 = self.Job.create({'name': 'Senior Operational Risk Manager BRD2'})
        self.job_target2 = self.Job.create({'name': 'Senior Credit Risk Officer BRD2'})

        self.comp1 = self.Competency.create({
            'name': 'Enterprise Risk Governance',
            'code': 'ERG_BRD2_001',
            'pillar': 'technical',
        })
        
        self.comp2 = self.Competency.create({
            'name': 'Strategic Leadership',
            'code': 'STL_BRD2_002',
            'pillar': 'leadership',
        })

    def test_01_competency_cluster_creation_and_mapping(self):
        """1. Verify Competency Cluster definition and role mapping attachment (FR-CFD-0176)."""
        cluster = self.Cluster.create({
            'name': 'Risk Management Cluster',
            'code': 'RMC_001',
            'competency_ids': [(6, 0, [self.comp1.id, self.comp2.id])],
            'min_proficiency': '3',
        })
        self.assertTrue(cluster.id)
        
        mapping = self.Mapping.create({
            'job_position_id': self.job_source.id,
            'version': 'v1.0',
            'cluster_ids': [(4, cluster.id)],
        })
        self.assertIn(cluster, mapping.cluster_ids)

    def test_02_bulk_mapping_clone_and_adapt_wizard(self):
        """2. Verify bulk mapping clone-and-adapt wizard across similar roles (FR-MAP-004)."""
        source_map = self.Mapping.create({
            'job_position_id': self.job_source.id,
            'version': 'v1.0',
            'line_ids': [
                (0, 0, {'competency_id': self.comp1.id, 'required_proficiency': '3'}),
                (0, 0, {'competency_id': self.comp2.id, 'required_proficiency': '4'}),
            ]
        })
        
        wizard = self.env['competency.role.mapping.clone.wizard'].create({
            'source_mapping_id': source_map.id,
            'target_job_ids': [(6, 0, [self.job_target1.id, self.job_target2.id])],
            'target_version': 'v1.0',
            'copy_lines': True,
        })
        res = wizard.action_clone_and_adapt()
        
        target1_map = self.Mapping.search([('job_position_id', '=', self.job_target1.id)], limit=1)
        self.assertTrue(target1_map.id)
        self.assertEqual(len(target1_map.line_ids), 2)

    def test_03_multi_source_consolidation_and_achievement_status(self):
        """3. Verify multi-source 360 rating consolidation and achievement status calculation (FR-ASM-005, FR-ASM-006)."""
        emp = self.env['hr.employee'].search([], limit=1)
        cycle = self.env['competency.assessment.cycle'].create({'name': 'Cycle 360 Test'})
        
        parent_asm = self.Assessment.create({
            'cycle_id': cycle.id,
            'employee_id': emp.id,
            'assessment_type': 'multi_rater',
            'line_ids': [(0, 0, {'competency_id': self.comp1.id, 'current_level': '1', 'required_level': '3'})]
        })
        
        # Add 360 rater submission
        child_asm = self.Assessment.create({
            'parent_assessment_id': parent_asm.id,
            'cycle_id': cycle.id,
            'employee_id': emp.id,
            'is_rater_assessment': True,
            'rater_type': 'peer',
            'is_anonymous': True,
            'state': 'submitted',
            'line_ids': [(0, 0, {'competency_id': self.comp1.id, 'current_level': '3', 'required_level': '3'})]
        })
        
        # Add Skills Test result (FR-ASM-003)
        self.SkillsTest.create({
            'name': 'Risk Certification Exam',
            'employee_id': emp.id,
            'competency_id': self.comp1.id,
            'score_percent': 90.0, # Level 4
        })
        
        parent_asm.action_consolidate_multi_source()
        parent_line = parent_asm.line_ids.filtered(lambda l: l.competency_id == self.comp1)
        
        # Average of 3 (360) and 4 (Skills Test) = 4
        self.assertEqual(parent_line.current_level, '4')
        self.assertEqual(parent_line.achievement_status, 'exceeds')
        self.assertEqual(parent_line.gap_priority, 'low')

    def test_04_coverage_report(self):
        """4. Verify competency coverage report SQL view execution (FR-MAP-007)."""
        report = self.env['competency.coverage.report'].search([('job_id', '=', self.job_source.id)], limit=1)
        self.assertTrue(report)
