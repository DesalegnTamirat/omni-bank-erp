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

    def test_restricted_cycle_keeps_gap_but_offers_only_selected_mapped_courses(self):
        courses = self.env['eds.course'].create([
            {'name': 'EDS Credit Analysis Offered', 'code': 'EDS-CREDIT-01', 'status': 'active'},
            {'name': 'EDS Credit Analysis Excluded', 'code': 'EDS-CREDIT-02', 'status': 'active'},
            {'name': 'EDS Unrelated Offered', 'code': 'EDS-OTHER-03', 'status': 'active'},
        ])
        for course in courses[:2]:
            self.env['eds.course.competency.line'].create({
                'course_id': course.id,
                'competency_id': self.competency.id,
                'required_level': '3',
            })

        Cycle = self.env['eds.tna.cycle']
        offered_cycle = Cycle.create({
            'state': 'collecting', 'restrict_tna_courses': True,
            'request_course_ids': [(6, 0, courses[0].ids)],
        })
        self.env['eds.competency.gap.import'].create({
            'cycle_id': offered_cycle.id,
            'competency_cycle_id': self.comp_cycle.id,
            'min_gap': 1,
        }).action_pull_competency_gaps()
        entry = offered_cycle.diagnostic_entry_ids.filtered(
            lambda need: need.employee_id == self.employee and need.competency_id == self.competency)
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.suggested_course_ids, courses[0])
        self.assertEqual(entry.cycle_course_status, 'offered')
        offered_cycle._sync_course_demand()
        self.assertEqual(offered_cycle.course_summary_ids.course_id, courses[0])

        unmatched_cycle = Cycle.create({
            'state': 'collecting', 'restrict_tna_courses': True,
            'request_course_ids': [(6, 0, courses[2].ids)],
        })
        self.env['eds.competency.gap.import'].create({
            'cycle_id': unmatched_cycle.id,
            'competency_cycle_id': self.comp_cycle.id,
            'min_gap': 1,
        }).action_pull_competency_gaps()
        unmatched = unmatched_cycle.diagnostic_entry_ids.filtered(
            lambda need: need.employee_id == self.employee and need.competency_id == self.competency)
        self.assertEqual(len(unmatched), 1)
        self.assertFalse(unmatched.suggested_course_ids)
        self.assertEqual(unmatched.cycle_course_status, 'not_offered')
        unmatched_cycle._sync_course_demand()
        self.assertFalse(unmatched_cycle.course_summary_ids)

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

    def test_direct_pull_uses_latest_cycles_primary_line(self):
        """A non-primary rater gap must not become a TNA entry."""
        closed_cycles = self.env['competency.assessment.cycle'].search([
            ('state', '=', 'closed'), ('active', '=', True),
        ])
        latest_end = max(
            [cycle.period_end for cycle in closed_cycles if cycle.period_end]
            or [fields.Date.today()]
        ) + timedelta(days=1)
        latest_cycle = self.env['competency.assessment.cycle'].create({
            'name': 'Latest Competency Cycle for TNA Test',
            'period_start': latest_end - timedelta(days=20),
            'period_end': latest_end,
            'state': 'closed',
        })
        team_assessment = self.env['competency.assessment'].create({
            'cycle_id': latest_cycle.id,
            'employee_id': self.employee.id,
            'assessment_type': 'team',
            'state': 'approved',
        })
        team_line = self.env['competency.assessment.line'].create({
            'assessment_id': team_assessment.id,
            'competency_id': self.competency.id,
            'required_level': '3',
            'current_level': '1',
        })
        self_assessment = self.env['competency.assessment'].create({
            'cycle_id': latest_cycle.id,
            'employee_id': self.employee.id,
            'assessment_type': 'self',
            'state': 'approved',
        })
        self_line = self.env['competency.assessment.line'].create({
            'assessment_id': self_assessment.id,
            'competency_id': self.competency.id,
            'required_level': '3',
            'current_level': '3',
        })
        self.assertFalse(team_line.is_primary_reporting_line)
        self.assertTrue(self_line.is_primary_reporting_line)

        self.tna_cycle.action_pull_competency_gaps()
        entries = self.env['eds.tna.entry'].search([
            ('cycle_id', '=', self.tna_cycle.id),
            ('employee_id', '=', self.employee.id),
            ('competency_id', '=', self.competency.id),
        ])
        self.assertFalse(entries)
