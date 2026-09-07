# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestFrameworkIntegrationAndGapFixes(TransactionCase):
    """Unit tests for Competency Approval Workflow, Retired Auto-Disappearance, and Role Mapping Hierarchy."""

    def setUp(self):
        super().setUp()
        self.Job = self.env['hr.job']
        self.Competency = self.env['competency.competency']
        self.Mapping = self.env['competency.role.mapping']
        self.MappingLine = self.env['competency.role.mapping.line']
        self.Cluster = self.env['competency.cluster']

        self.job = self.Job.create({'name': 'Senior Recruitment Specialist F6'})

        self.comp_draft = self.Competency.create({
            'name': 'Draft Competency F6',
            'code': 'DRAFT_F6_001',
            'pillar': 'technical',
            'state': 'draft',
        })

        self.comp_approved = self.Competency.create({
            'name': 'Approved Competency F6',
            'code': 'APP_F6_002',
            'pillar': 'core',
            'state': 'approved',
            'status': 'active',
        })

    def test_01_competency_approval_and_retirement(self):
        """Verify competency approval workflow and auto-disappearance upon retirement."""
        # Setup proficiency levels for draft competency
        for lvl in ['1', '2', '3', '4']:
            self.env['competency.proficiency.level'].create({
                'competency_id': self.comp_draft.id,
                'level': lvl,
                'definition': f'Level {lvl}',
                'behavioral_indicators': f'Indicator {lvl}',
            })
        
        self.comp_draft.action_submit()
        self.assertEqual(self.comp_draft.state, 'submitted')
        self.comp_draft.action_approve()
        self.assertEqual(self.comp_draft.state, 'approved')
        self.assertEqual(self.comp_draft.status, 'active')

        # Map approved competency to a role mapping
        mapping = self.Mapping.create({
            'job_position_id': self.job.id,
            'version': 'v1.0',
        })
        line = self.MappingLine.create({
            'mapping_id': mapping.id,
            'competency_id': self.comp_draft.id,
            'required_proficiency': '3',
        })
        self.assertIn(line, mapping.line_ids)

        # Retire competency -> should auto-disappear from mapping lines
        self.comp_draft.action_retire()
        self.assertEqual(self.comp_draft.state, 'retired')
        self.assertFalse(self.MappingLine.search([('competency_id', '=', self.comp_draft.id)]))
