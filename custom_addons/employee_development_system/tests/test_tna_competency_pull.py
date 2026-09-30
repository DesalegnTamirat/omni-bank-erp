# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import fields
from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import ValidationError


@tagged('post_install', '-at_install', 'eds', 'tna_pull')
class TestEdsTnaCompetencyPull(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dept = cls.env['hr.department'].create({'name': 'Retail Banking Test Dept'})
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Abebe Bikila Test',
            'department_id': cls.dept.id,
        })
        cls.competency = cls.env['competency.competency'].create({
            'name': 'Credit Analysis Test',
            'code': 'COMP_CREDIT_TEST_01',
            'pillar': 'technical',
            'state': 'approved',
            'status': 'active',
        })
        # Create an open TNA cycle
        cls.tna_cycle = cls.env['eds.tna.cycle'].create({
            'name': 'TNA Cycle 2026 Test',
            'year': '2026',
            'state': 'collecting',
        })
        # Create a closed competency assessment cycle
        cls.comp_cycle = cls.env['competency.assessment.cycle'].create({
            'name': 'Annual Competency Cycle 2025 Test',
            'code': 'COMP_2025_TEST',
            'period_start': fields.Date.today() - timedelta(days=180),
            'period_end': fields.Date.today() - timedelta(days=30),
            'state': 'closed',
        })
        # Create an assessment and line with gap
        cls.assessment = cls.env['competency.assessment'].create({
            'cycle_id': cls.comp_cycle.id,
            'employee_id': cls.employee.id,
            'assessment_type': 'team',
            'state': 'approved',
        })
        cls.assessment_line = cls.env['competency.assessment.line'].create({
            'assessment_id': cls.assessment.id,
            'competency_id': cls.competency.id,
            'required_level': '3',
            'current_level': '1',
            'active': True,
        })

    def test_pull_competency_gaps_from_closed_cycle(self):
        """Verify that competency gaps are pulled directly from a closed cycle without file upload."""
        # Launch wizard
        wizard = self.env['eds.competency.gap.import'].create({
            'cycle_id': self.tna_cycle.id,
            'competency_cycle_id': self.comp_cycle.id,
            'min_gap': 1,
        })
        wizard.action_pull_competency_gaps()

        # Check TNA entries created
        entry = self.env['eds.tna.entry'].search([
            ('cycle_id', '=', self.tna_cycle.id),
            ('employee_id', '=', self.employee.id),
            ('competency_id', '=', self.competency.id),
        ])
        self.assertTrue(entry, "A TNA entry should have been created for the employee and competency.")
        self.assertEqual(entry.source, 'competency_gap')
        self.assertEqual(entry.competency_gap_level_diff, 2)
        self.assertEqual(entry.gap_severity, 'high')
        self.assertEqual(entry.state, 'submitted')

    def test_pull_competency_gaps_rejects_open_cycle(self):
        """Verify that wizard rejects an open (non-closed) competency cycle."""
        open_cycle = self.env['competency.assessment.cycle'].create({
            'name': 'Open Competency Cycle Test',
            'code': 'COMP_OPEN_TEST',
            'state': 'open',
        })
        wizard = self.env['eds.competency.gap.import'].create({
            'cycle_id': self.tna_cycle.id,
            'competency_cycle_id': open_cycle.id,
            'min_gap': 1,
        })
        with self.assertRaises(ValidationError):
            wizard.action_pull_competency_gaps()
