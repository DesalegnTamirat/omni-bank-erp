# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import ValidationError


@tagged('post_install', '-at_install', 'competency_primary_reporting')
class TestPrimaryReportingLine(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].sudo().create({
            'name': 'Primary Reporting Test Employee',
        })
        cls.cycle = cls.env['competency.assessment.cycle'].sudo().create({
            'name': 'Primary Reporting Test Cycle',
        })
        cls.competency = cls.env['competency.competency'].sudo().create({
            'name': 'Primary Reporting Test Competency',
            'code': 'TEST_PRIMARY_REPORTING_LINE',
            'pillar': 'core',
            'state': 'approved',
        })
        cls.other_competency = cls.env['competency.competency'].sudo().create({
            'name': 'Other Primary Reporting Test Competency',
            'code': 'TEST_PRIMARY_REPORTING_OTHER',
            'pillar': 'core',
            'state': 'approved',
        })

    def _create_line(self, assessment_type, competency=None, current_level='2'):
        assessment = self.env['competency.assessment'].sudo().create({
            'cycle_id': self.cycle.id,
            'employee_id': self.employee.id,
            'assessment_type': assessment_type,
        })
        return self.env['competency.assessment.line'].sudo().create({
            'assessment_id': assessment.id,
            'competency_id': (competency or self.competency).id,
            'current_level': current_level,
            'required_level': '2',
        })

    def _primary_lines(self, competency=None):
        return self.env['competency.assessment.line'].sudo().search([
            ('employee_id', '=', self.employee.id),
            ('cycle_id', '=', self.cycle.id),
            ('competency_id', '=', (competency or self.competency).id),
            ('is_primary_reporting_line', '=', True),
        ])

    def test_supervisor_first_then_self_has_one_reporting_line(self):
        supervisor = self._create_line('team')
        self.assertEqual(self._primary_lines(), supervisor)

        self_line = self._create_line('self')
        self.assertEqual(self._primary_lines(), self_line)
        self.assertFalse(supervisor.is_primary_reporting_line)

        peer = self._create_line('peer')
        self.assertEqual(self._primary_lines(), self_line)
        self.assertFalse(peer.is_primary_reporting_line)

    def test_deleting_primary_re_elects_existing_line(self):
        self_line = self._create_line('self', current_level='1')
        supervisor = self._create_line('team', current_level='3')
        self.assertEqual(self._primary_lines(), self_line)
        self.assertEqual(supervisor.self_rating, 1.0)

        self_line.unlink()
        self.assertEqual(self._primary_lines(), supervisor)
        self.assertEqual(supervisor.self_rating, 0.0)
        self.assertEqual(supervisor.weighted_current_level, 3.0)

        peer = self._create_line('peer')
        supervisor.unlink()
        self.assertEqual(self._primary_lines(), peer)

    def test_moving_line_re_elects_both_competencies(self):
        supervisor = self._create_line('team')
        self_line = self._create_line('self')
        peer = self._create_line('peer', self.other_competency)
        self.assertEqual(self._primary_lines(), self_line)
        self.assertEqual(self._primary_lines(self.other_competency), peer)

        self_line.write({'competency_id': self.other_competency.id})
        self.assertEqual(self._primary_lines(), supervisor)
        self.assertEqual(self._primary_lines(self.other_competency), self_line)

    def test_code_repairs_stale_reporting_flags(self):
        supervisor = self._create_line('team')
        self_line = self._create_line('self')
        self.env.flush_all()

        # Simulate the saved flags left by the old sibling compute behavior.
        self.env.cr.execute(
            """UPDATE competency_assessment_line
                  SET is_primary_reporting_line = TRUE
                WHERE id = ANY(%s)""",
            ([supervisor.id, self_line.id],),
        )
        repaired = self.env['competency.assessment.line']._repair_legacy_primary_reporting_flags(
            cycle_ids=[self.cycle.id]
        )
        self.assertEqual(repaired, 1)
        self.env.invalidate_all(flush=False)
        self.env.cr.execute(
            """SELECT id FROM competency_assessment_line
                WHERE id = ANY(%s) AND is_primary_reporting_line""",
            ([supervisor.id, self_line.id],),
        )
        self.assertEqual([row[0] for row in self.env.cr.fetchall()], [self_line.id])

    def test_same_assessment_cannot_repeat_a_competency(self):
        first_line = self._create_line('team')
        with self.assertRaises(ValidationError):
            with self.env.cr.savepoint():
                self.env['competency.assessment.line'].sudo().create({
                    'assessment_id': first_line.assessment_id.id,
                    'competency_id': self.competency.id,
                    'current_level': '3',
                    'required_level': '2',
                })
