# -*- coding: utf-8 -*-
from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'eds', 'pms_pull')
class TestEdsTnaPmsPull(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dept = cls.env['hr.department'].create({'name': 'Operations Test Department'})
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Dawit Lemma Test',
            'department_id': cls.dept.id,
        })
        # Create an open TNA cycle
        cls.tna_cycle = cls.env['eds.tna.cycle'].create({
            'name': 'TNA Cycle 2026 Test PMS',
            'year': '2026',
            'state': 'collecting',
        })

        # Create PMS test appraisal if PMS models exist
        if 't3.appraisal' in cls.env:
            cls.fy = cls.env['performance.fiscal.year'].search([], limit=1)
            if not cls.fy:
                cls.fy = cls.env['performance.fiscal.year'].create({
                    'name': '2025/2026 Test FY',
                    'date_start': '2025-07-01',
                    'date_end': '2026-06-30',
                })
            cls.appraisal = cls.env['t3.appraisal'].create({
                'name': '2025 Annual Appraisal - Dawit Lemma',
                'employee_id': cls.employee.id,
                'fiscal_year_id': cls.fy.id,
                'performance_rating': 'Needs Improvement',
                'state': 'draft',
                'line_ids': [(0, 0, {
                    'appraisal_criteria': 'Loan Documentation Accuracy',
                    'planned_weight': 100.0,
                    'weight': 100.0,
                    'target': 100.0,
                    'uploaded_value': 58.0,
                    'accomplishment_percent': 58.0,
                    'appraised_score': 58.0,
                    'recommendations': 'Needs comprehensive training on Loan Documentation and Branch Credit Approval',
                    'appraised': 'yes',
                })],
            })
            cls.appraisal._compute_employee_score()
            cls.appraisal.write({'state': 'confirmed'})

    def test_pull_pms_gaps_into_tna_cycle(self):
        """Verify that PMS appraisal gaps below threshold are ingested directly into TNA entries."""
        if 't3.appraisal' not in self.env:
            return

        wizard = self.env['eds.pms.gap.import'].create({
            'cycle_id': self.tna_cycle.id,
            'max_score_threshold': 75.0,
            'state_filter': 'all_evaluated',
        })
        wizard.action_pull_pms_gaps()

        # Verify entry created in TNA cycle
        entries = self.tna_cycle.entry_ids.filtered(lambda e: e.source == 'pms' and e.employee_id == self.employee)
        self.assertEqual(len(entries), 1, "Should have created exactly one TNA entry from the low PMS appraisal.")
        entry = entries[0]
        self.assertEqual(entry.source, 'pms')
        self.assertEqual(entry.pms_measurement_name, 'Loan Documentation Accuracy')
        self.assertEqual(entry.competency_or_measurement, 'Loan Documentation Accuracy')
        self.assertEqual(entry.pms_appraisal_score, 58.0)
        self.assertEqual(entry.pms_target_value, 100.0)
        self.assertEqual(entry.pms_actual_value, 58.0)
        self.assertTrue(wizard.ingestion_done)
        self.assertGreaterEqual(wizard.created_count, 1)
        self.assertEqual(entry.urgency, 'high')  # 50 <= 58 < 65 -> high
        self.assertGreater(entry.priority_score, 0.0)
        self.assertIn("Loan Documentation", entry.justification)
        self.assertIn("Needs comprehensive training", entry.justification)

        # Run again - verify duplicate protection
        wizard2 = self.env['eds.pms.gap.import'].create({
            'cycle_id': self.tna_cycle.id,
            'max_score_threshold': 75.0,
            'state_filter': 'all_evaluated',
        })
        wizard2.action_pull_pms_gaps()
        entries_after = self.tna_cycle.entry_ids.filtered(lambda e: e.source == 'pms' and e.employee_id == self.employee)
        self.assertEqual(len(entries_after), 1, "Duplicate TNA entries for same employee and cycle should be skipped.")

    def test_restricted_cycle_filters_pms_mappings_without_losing_gap(self):
        if 't3.appraisal' not in self.env:
            return
        unit = self.env['operating.unit'].create({
            'name': 'EDS PMS Restriction Unit', 'sol_id': 987653,
            'work_unit_type': 'head_office',
        })
        job = self.env['hr.job'].create({'name': 'EDS PMS Restriction Job'})
        objective = self.env['performance.objective'].create({
            'name': 'EDS PMS Restriction Objective', 'employee_id': self.employee.id,
        })
        parent_measure = self.env['performance.measure'].create({
            'name': 'EDS PMS Parent Measure', 'objective_id': objective.id,
            'weight': 100.0,
        })
        kpi = self.env['performance.job.objective'].create({
            'name': 'EDS PMS Restriction KPI', 'operating_unit_id': unit.id,
            'job_id': job.id, 'parent_measure_id': parent_measure.id,
            'measure_ids': [(0, 0, {
                'name': 'EDS Loan Documentation Accuracy', 'weight': 100.0,
                'target_type': 'percent',
            })],
        })
        measure = kpi.measure_ids
        self.appraisal.line_ids.write({'job_measure_id': measure.id})
        courses = self.env['eds.course'].create([
            {'name': 'EDS PMS Offered Course', 'code': 'EDS-PMS-01', 'status': 'active'},
            {'name': 'EDS PMS Excluded Course', 'code': 'EDS-PMS-02', 'status': 'active'},
            {'name': 'EDS PMS Unrelated Course', 'code': 'EDS-PMS-03', 'status': 'active'},
        ])
        for course in courses[:2]:
            self.env['eds.course.pms.line'].create({
                'course_id': course.id, 'job_measure_id': measure.id,
                'min_threshold': 75.0,
            })

        for selected_course, expected_course in ((courses[0], courses[0]),
                                                 (courses[2], self.env['eds.course'])):
            cycle = self.env['eds.tna.cycle'].create({
                'state': 'collecting', 'restrict_tna_courses': True,
                'request_course_ids': [(6, 0, selected_course.ids)],
            })
            self.env['eds.pms.gap.import'].create({
                'cycle_id': cycle.id, 'max_score_threshold': 75.0,
                'state_filter': 'all_evaluated',
                'department_id': self.dept.id,
            }).action_pull_pms_gaps()
            entry = cycle.diagnostic_entry_ids.filtered(
                lambda need: need.employee_id == self.employee and need.pms_measure_id == measure)
            self.assertEqual(len(entry), 1)
            self.assertEqual(entry.suggested_course_ids, expected_course)
            self.assertEqual(entry.cycle_course_status,
                             'offered' if expected_course else 'not_offered')
            cycle._sync_course_demand()
            self.assertEqual(cycle.course_summary_ids.course_id, expected_course)
