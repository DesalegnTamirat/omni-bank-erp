# -*- coding: utf-8 -*-
import base64
import io
from datetime import timedelta

from openpyxl import load_workbook
from psycopg2 import IntegrityError

from odoo.exceptions import UserError, ValidationError
from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'eds', 'cycle_demand_vendor_matrix')
class TestCycleDemandVendorMatrix(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env['operating.unit'].create({
            'name': 'EDS Demand Test Unit',
            'sol_id': 987654,
            'work_unit_type': 'head_office',
        })
        cls.employees = cls.env['hr.employee'].create([
            {'name': 'EDS Demand Employee One', 'default_operating_unit_id': cls.unit.id},
            {'name': 'EDS Demand Employee Two', 'default_operating_unit_id': cls.unit.id},
        ])
        cls.courses = cls.env['eds.course'].create([
            {'name': 'EDS Demand Course A', 'code': 'EDS-DEMAND-A', 'status': 'active'},
            {'name': 'EDS Demand Course B', 'code': 'EDS-DEMAND-B', 'status': 'active'},
        ])
        cls.cycle = cls.env['eds.tna.cycle'].create({
            'name': 'EDS Demand Test Cycle',
            'year': str(fields.Date.today().year), 'state': 'collecting',
        })

    def test_restricted_cycle_offers_only_selected_courses_for_manual_requests(self):
        today = fields.Date.today()
        cycle = self.env['eds.tna.cycle'].create({
            'start_date': today,
            'submission_end_date': today + timedelta(days=10),
            'restrict_tna_courses': True,
        })
        with self.assertRaises(UserError):
            cycle.action_start_collection()
        cycle.request_course_ids = self.courses[0]
        cycle.action_start_collection()
        self.assertEqual(cycle.state, 'collecting')
        with self.assertRaises(UserError):
            cycle.write({'request_course_ids': [(6, 0, self.courses.ids)]})

        Entry = self.env['eds.tna.entry']
        common = {'cycle_id': cycle.id, 'source': 'manual', 'justification': 'Required training'}
        individual = Entry.create(dict(common,
            request_level='individual', employee_id=self.employees[0].id,
            requested_course_ids=[(6, 0, self.courses[0].ids)], state='submitted'))
        self.assertTrue(individual.restrict_request_courses)
        self.assertEqual(individual.allowed_request_course_ids, self.courses[0])
        with self.assertRaises(ValidationError):
            individual.write({'requested_course_ids': [(6, 0, self.courses.ids)]})
        with self.assertRaises(ValidationError):
            Entry.create(dict(common,
                request_level='individual', employee_id=self.employees[1].id,
                requested_course_ids=[(6, 0, self.courses[1].ids)]))
        work_unit = Entry.create(dict(common,
            request_level='work_unit', work_unit_id=self.unit.id,
            work_unit_employee_ids=[(6, 0, self.employees.ids)],
            course_id=self.courses[0].id, state='submitted'))
        self.assertEqual(work_unit.course_id, self.courses[0])
        with self.assertRaises(ValidationError):
            work_unit.write({'course_id': self.courses[1].id})
        with self.assertRaises(ValidationError):
            Entry.create(dict(common,
                request_level='work_unit', work_unit_id=self.unit.id,
                is_custom_course=True, custom_course_title='Outside Catalog'))
        diagnostic = Entry.create({
            'cycle_id': cycle.id, 'source': 'pms', 'request_level': 'individual',
            'employee_id': self.employees[1].id, 'course_id': self.courses[1].id,
            'justification': 'PMS gap', 'state': 'submitted',
        })
        self.assertEqual(diagnostic.course_id, self.courses[1])

    def test_course_list_label_covers_multi_course_legacy_and_work_unit_requests(self):
        Entry = self.env['eds.tna.entry']
        common = {'cycle_id': self.cycle.id, 'source': 'manual',
                  'justification': 'Required training'}
        multiple = Entry.create(dict(common,
            request_level='individual', employee_id=self.employees[0].id,
            requested_course_ids=[(6, 0, self.courses.ids)]))
        legacy = Entry.create(dict(common,
            request_level='individual', employee_id=self.employees[1].id,
            course_id=self.courses[0].id))
        proposed = Entry.create(dict(common,
            request_level='work_unit', work_unit_id=self.unit.id,
            is_custom_course=True, custom_course_title='Branch Coaching'))
        self.assertEqual(multiple.course_request_display,
                         'EDS Demand Course A, EDS Demand Course B')
        self.assertEqual(legacy.course_request_display, 'EDS Demand Course A')
        self.assertEqual(proposed.course_request_display,
                         'Branch Coaching (outside catalog)')

    def test_unique_course_demand_and_selected_planning(self):
        Entry = self.env['eds.tna.entry']
        common = {'cycle_id': self.cycle.id, 'justification': 'Required training'}
        individual = Entry.create(dict(common,
            request_level='individual', source='manual', employee_id=self.employees[0].id,
            requested_course_ids=[(6, 0, self.courses.ids)], state='submitted'))
        self.assertFalse(individual.proposed_program)
        self.assertFalse(individual.suggested_course_ids)
        self.assertFalse(individual.course_match_status)
        Entry.create(dict(common,
            request_level='work_unit', source='manual', work_unit_id=self.unit.id,
            work_unit_employee_ids=[(6, 0, [self.employees[0].id])],
            is_custom_course=True, custom_course_title='EDS Custom Course', state='submitted'))
        Entry.create(dict(common,
            request_level='work_unit', source='manual', work_unit_id=self.unit.id,
            course_id=self.courses[0].id,
            work_unit_employee_ids=[(6, 0, self.employees.ids)], state='submitted'))
        Entry.create(dict(common,
            request_level='individual', source='competency_gap',
            employee_id=self.employees[1].id, course_id=self.courses[0].id,
            state='submitted'))
        pms_entry = Entry.create(dict(common,
            request_level='individual', source='pms', employee_id=self.employees[1].id,
            course_id=self.courses[1].id, state='submitted'))
        Entry.create(dict(common,
            request_level='individual', source='pms', employee_id=self.employees[1].id,
            course_id=self.courses[0].id, state='submitted'))

        self.assertTrue(self.cycle.course_demand_dirty)
        self.cycle.web_read({'course_summary_count': {}})
        self.assertFalse(self.cycle.course_demand_dirty)
        first = self.cycle.course_summary_ids.filtered(lambda line: line.course_id == self.courses[0])
        second = self.cycle.course_summary_ids.filtered(lambda line: line.course_id == self.courses[1])
        custom = self.cycle.course_summary_ids.filtered(lambda line: line.course_name == 'EDS Custom Course')
        self.assertEqual(len(self.cycle.course_summary_ids), 3)
        self.assertEqual((first.catalog_status, second.catalog_status, custom.catalog_status),
                         ('catalog', 'catalog', 'outside_catalog'))
        self.assertEqual((first.count_individual, first.count_work_unit,
                          first.count_competency, first.total_employees, first.request_count), (1, 2, 1, 2, 4))
        self.assertEqual(first.count_pms, 1)
        self.assertEqual((second.count_individual, second.count_pms,
                          second.total_employees, second.request_count), (1, 1, 2, 2))
        self.assertEqual(custom.total_employees, 1)
        ranked = self.env['eds.tna.cycle.course.employee'].search([
            ('course_line_id', '=', first.id)])
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0].employee_id, self.employees[1])
        multi_source = ranked.filtered(lambda row: row.employee_id == self.employees[1])
        self.assertEqual(multi_source.source_count, 3)
        self.assertEqual(multi_source.overall_priority_score, 50)
        self.assertEqual(multi_source.need_severity, 'medium')
        self.assertTrue(multi_source.from_competency)
        self.assertTrue(multi_source.from_work_unit)
        self.assertTrue(multi_source.from_pms)
        self.assertEqual(len(multi_source.evidence_ids), 3)
        demand_id = multi_source.id
        evidence_ids = set(multi_source.evidence_ids.ids)
        self.cycle._sync_course_demand()
        self.assertEqual(multi_source.id, demand_id)
        self.assertEqual(set(multi_source.evidence_ids.ids), evidence_ids)

        second.selected_for_planning = False
        custom.selected_for_planning = False
        pms_entry.is_duplicate = True
        self.assertTrue(self.cycle.course_demand_dirty)
        self.cycle.web_read({'course_summary_count': {}})
        self.assertFalse(second.selected_for_planning)
        self.assertEqual((second.count_pms, second.total_employees, second.request_count), (0, 1, 1))
        self.assertEqual(multi_source.id, demand_id)
        self.cycle.state = 'closed'
        action = self.cycle.action_go_to_planning()
        plan = self.env['eds.annual.plan'].browse(action['res_id'])
        source_line = plan.line_ids.filtered(
            lambda item: item.course_id == self.courses[0])
        self.assertEqual(len(source_line), 1)
        self.assertEqual(source_line.planned_participants, 2)

    def test_course_demand_averages_source_scores_and_shows_highest_severity(self):
        Entry = self.env['eds.tna.entry']
        competencies = self.env['competency.competency'].create([
            {'name': 'EDS Demand Priority Competency A', 'code': 'EDS-PRIORITY-A',
             'pillar': 'technical'},
            {'name': 'EDS Demand Priority Competency B', 'code': 'EDS-PRIORITY-B',
             'pillar': 'technical'},
        ])
        common = {
            'cycle_id': self.cycle.id, 'employee_id': self.employees[0].id,
            'course_id': self.courses[0].id, 'state': 'submitted',
            'justification': 'Training need',
        }
        individual = Entry.create(dict(common, source='manual', urgency='low'))
        competency_critical = Entry.create(dict(common, source='competency_gap',
            competency_id=competencies[0].id, competency_gap_level_diff=3,
            gap_severity='critical'))
        competency_medium = Entry.create(dict(common, source='competency_gap',
            competency_id=competencies[1].id, competency_gap_level_diff=1,
            gap_severity='medium'))
        pms = Entry.create(dict(common, source='pms', gap_severity='high'))

        # Programmatic/manual submissions must not rely on the form onchange.
        self.assertEqual(individual.gap_severity, 'medium')
        self.assertEqual(individual.score_gap_severity, 25)
        self.assertEqual(individual.priority_score, 35)

        self.cycle._sync_course_demand()
        demand = self.cycle.course_summary_ids.filtered(
            lambda line: line.course_id == self.courses[0]).employee_demand_ids
        self.assertEqual(len(demand), 1)
        self.assertEqual(demand.source_count, 3)
        self.assertEqual(demand.evidence_count, 4)
        self.assertEqual(demand.need_severity, 'critical')
        severities = {e.entry_id.id: e.need_severity for e in demand.evidence_ids}
        self.assertEqual(severities, {
            individual.id: 'low', competency_critical.id: 'critical',
            competency_medium.id: 'medium', pms.id: 'high',
        })
        competency_average = (
            competency_critical.priority_score + competency_medium.priority_score) / 2
        expected = round((individual.priority_score + competency_average
                          + pms.priority_score) / 3 + 10)
        self.assertEqual(demand.overall_priority_score, expected)

    def test_repeat_work_unit_nomination_counts_once_and_uses_highest_score(self):
        Entry = self.env['eds.tna.entry']
        common = {
            'cycle_id': self.cycle.id, 'request_level': 'work_unit',
            'source': 'manual', 'work_unit_id': self.unit.id,
            'course_id': self.courses[0].id, 'state': 'submitted',
            'justification': 'Unit training need',
        }
        lower = Entry.create(dict(common,
            work_unit_employee_ids=[(6, 0, self.employees.ids)],
            urgency='low', score_strategic_alignment=20,
            score_tom_impact=20, score_risk_level=20,
            score_future_capability=20))
        higher = Entry.create(dict(common,
            work_unit_employee_ids=[(6, 0, [self.employees[0].id])],
            urgency='critical', score_strategic_alignment=80,
            score_tom_impact=80, score_risk_level=80,
            score_future_capability=80))
        individual = Entry.create({
            'cycle_id': self.cycle.id, 'request_level': 'individual',
            'source': 'manual', 'employee_id': self.employees[0].id,
            'course_id': self.courses[0].id, 'state': 'submitted',
            'justification': 'Individual training need',
        })
        self.assertGreater(higher.priority_score, lower.priority_score)

        self.cycle._sync_course_demand()
        line = self.cycle.course_summary_ids.filtered(
            lambda item: item.course_id == self.courses[0])
        self.assertEqual((line.total_employees, line.count_work_unit,
                          line.count_individual, line.request_count), (2, 2, 1, 3))
        demand = line.employee_demand_ids.filtered(
            lambda item: item.employee_id == self.employees[0])
        self.assertEqual(len(demand), 1)
        self.assertEqual((demand.source_count, demand.evidence_count), (2, 3))
        self.assertEqual(set(demand.evidence_ids.mapped('entry_id').ids),
                         {lower.id, higher.id, individual.id})
        expected = round((higher.priority_score + individual.priority_score) / 2 + 5)
        self.assertEqual(demand.overall_priority_score, expected)

        warning = Entry.new({
            'cycle_id': self.cycle.id, 'request_level': 'work_unit',
            'source': 'manual', 'work_unit_id': self.unit.id,
            'course_id': self.courses[0].id,
            'work_unit_employee_ids': [(6, 0, [self.employees[0].id])],
        })._onchange_repeat_work_unit_nomination()
        self.assertIn(self.employees[0].name, warning['warning']['message'])

        self.cycle.state = 'closed'
        action = self.cycle.action_go_to_planning()
        plan = self.env['eds.annual.plan'].browse(action['res_id'])
        plan_line = plan.line_ids.filtered(lambda item: item.course_id == self.courses[0])
        self.assertEqual(plan_line.planned_participants, 2)

        higher.is_duplicate = True
        self.cycle._sync_course_demand()
        self.assertEqual(demand.overall_priority_score,
                         round((lower.priority_score + individual.priority_score) / 2 + 5))
        self.assertEqual(line.total_employees, 2)

    def test_cycle_audience_filters_requests_and_diagnostics(self):
        department = self.env['hr.department'].create({'name': 'EDS Target Department'})
        job = self.env['hr.job'].create({
            'name': 'EDS Target Job', 'department_id': department.id,
        })
        self.employees.write({'department_id': department.id, 'job_id': job.id})
        cycle = self.env['eds.tna.cycle'].create({
            'year': str(fields.Date.today().year), 'state': 'draft',
            'restrict_tna_audience': True,
            'target_department_ids': [(6, 0, department.ids)],
            'target_work_unit_ids': [(6, 0, self.unit.ids)],
            'target_job_position_ids': [(6, 0, job.ids)],
            'target_employee_ids': [(6, 0, self.employees[0].ids)],
        })
        self.assertIn(self.unit, cycle.available_target_unit_ids)
        self.assertIn(job, cycle.available_target_job_ids)
        cycle.state = 'collecting'
        self.assertTrue(cycle._is_employee_targeted(self.employees[0]))
        self.assertFalse(cycle._is_employee_targeted(self.employees[1]))
        available = self.env['eds.tna.entry'].new({
            'request_level': 'individual', 'employee_id': self.employees[0].id,
        }).available_cycle_ids
        self.assertIn(cycle.id, available._origin.ids)
        unavailable = self.env['eds.tna.entry'].new({
            'request_level': 'individual', 'employee_id': self.employees[1].id,
        }).available_cycle_ids
        self.assertNotIn(cycle.id, unavailable._origin.ids)
        with self.assertRaises(ValidationError):
            self.env['eds.tna.entry'].create({
                'cycle_id': cycle.id, 'source': 'manual',
                'employee_id': self.employees[1].id,
                'course_id': self.courses[0].id,
                'justification': 'Out of audience',
            })
        with self.assertRaises(ValidationError):
            self.env['eds.tna.entry'].create({
                'cycle_id': cycle.id, 'source': 'manual',
                'request_level': 'work_unit', 'work_unit_id': self.unit.id,
                'work_unit_employee_ids': [(6, 0, self.employees.ids)],
                'course_id': self.courses[0].id,
                'justification': 'Mixed audience',
            })

    def test_planning_uses_only_closed_same_year_cycles_and_unique_employees(self):
        year = str(fields.Date.today().year)
        Entry = self.env['eds.tna.entry']
        Entry.create({
            'cycle_id': self.cycle.id, 'employee_id': self.employees[0].id,
            'course_id': self.courses[0].id, 'state': 'submitted',
            'justification': 'First cycle',
        })
        second = self.env['eds.tna.cycle'].create({
            'year': year, 'state': 'closed',
        })
        for employee in self.employees:
            Entry.create({
                'cycle_id': second.id, 'employee_id': employee.id,
                'course_id': self.courses[0].id, 'state': 'submitted',
                'justification': 'Second cycle',
            })
        open_cycle = self.env['eds.tna.cycle'].create({
            'year': year, 'state': 'collecting',
        })
        Entry.create({
            'cycle_id': open_cycle.id, 'employee_id': self.employees[0].id,
            'course_id': self.courses[1].id, 'state': 'submitted',
            'justification': 'Open cycle',
        })
        self.cycle._sync_course_demand()
        with self.assertRaises(UserError):
            self.cycle.action_go_to_planning()
        self.cycle.action_finish_collection()
        self.env['eds.annual.plan'].create({'fiscal_year': year})
        action = self.cycle.action_go_to_planning()
        plan = self.env['eds.annual.plan'].browse(action['res_id'])
        line = plan.line_ids.filtered(lambda item: item.course_id == self.courses[0])
        self.assertTrue(plan.restrict_tna_cycles)
        self.assertEqual(plan.selected_tna_cycle_ids, self.cycle)
        self.assertEqual(len(line), 1)
        self.assertEqual(line.planned_participants, 1)
        self.assertEqual(line.course_demand_ids.mapped('cycle_id'), self.cycle)
        self.assertNotIn(second.name, line.source_cycle_names)
        plan.action_generate_calendar()
        self.assertEqual(line.planned_participants, 1)
        self.assertNotIn(self.courses[1], plan.line_ids.mapped('course_id'))

        plan.selected_tna_cycle_ids = self.cycle | second
        plan.action_generate_calendar()
        self.assertEqual(line.planned_participants, 2)
        self.assertEqual(set(line.course_demand_ids.mapped('cycle_id').ids),
                         {self.cycle.id, second.id})
        self.assertIn(self.cycle.name, line.source_cycle_names)
        self.assertIn(second.name, line.source_cycle_names)
        self.assertEqual(sum(line.course_demand_ids.mapped('request_count')), 3)
        self.assertGreaterEqual(plan._get_preview_summary()['request_count'], 3)

        plan.write({
            'restrict_tna_cycles': True,
            'selected_tna_cycle_ids': [(6, 0, second.ids)],
        })
        plan.action_generate_calendar()
        self.assertEqual(line.course_demand_ids.mapped('cycle_id'), second)
        plan.selected_tna_cycle_ids = self.cycle | second
        plan.action_generate_calendar()
        self.assertEqual(set(line.course_demand_ids.mapped('cycle_id').ids),
                         {self.cycle.id, second.id})
        session = self.env['eds.session'].create({
            'plan_line_id': line.id, 'course_id': self.courses[0].id,
            'date_start': '%s-11-01 09:00:00' % year,
            'date_end': '%s-11-01 17:00:00' % year,
        })
        self.assertEqual(set(session.enrollment_ids.mapped('employee_id').ids),
                         set(self.employees.ids))
        self.assertNotIn(self.courses[1], plan.line_ids.mapped('course_id'))

        selected_plan = self.env['eds.annual.plan'].create({
            'restrict_tna_cycles': True,
            'selected_tna_cycle_ids': [(6, 0, second.ids)],
        })
        selected_plan.action_generate_calendar()
        selected_line = selected_plan.line_ids.filtered(
            lambda item: item.course_id == self.courses[0])
        self.assertEqual(selected_line.planned_participants, 2)
        self.assertEqual(selected_line.course_demand_ids.mapped('cycle_id'), second)
        self.assertNotIn(self.courses[1], selected_plan.line_ids.mapped('course_id'))

        with self.assertRaises(ValidationError), self.cr.savepoint():
            selected_plan.selected_tna_cycle_ids = open_cycle

    def test_plan_course_picker_uses_closed_selected_tna_demand(self):
        Entry = self.env['eds.tna.entry']
        Entry.create({
            'cycle_id': self.cycle.id, 'employee_id': self.employees[0].id,
            'course_id': self.courses[0].id, 'state': 'submitted',
            'justification': 'First closed cycle',
        })
        second = self.env['eds.tna.cycle'].create({'state': 'closed'})
        Entry.create({
            'cycle_id': second.id, 'employee_id': self.employees[1].id,
            'course_id': self.courses[1].id, 'state': 'submitted',
            'justification': 'Second closed cycle',
        })
        open_cycle = self.env['eds.tna.cycle'].create({'state': 'collecting'})
        outside_course = self.env['eds.course'].create({
            'name': 'EDS Outside Picker Course', 'status': 'active',
        })
        Entry.create({
            'cycle_id': open_cycle.id, 'employee_id': self.employees[0].id,
            'course_id': outside_course.id, 'state': 'submitted',
            'justification': 'Still collecting',
        })
        self.cycle._sync_course_demand()
        second._sync_course_demand()
        self.cycle.state = 'closed'
        plan = self.env['eds.annual.plan'].create({
            'restrict_tna_cycles': True,
            'selected_tna_cycle_ids': [(6, 0, self.cycle.ids)],
        })
        Line = self.env['eds.annual.plan.line']
        choice = Line.new({'plan_id': plan.id})
        self.assertEqual(choice.available_tna_course_ids._origin, self.courses[0])
        self.assertFalse(choice.course_identity_locked)
        choice.course_id = self.courses[0]
        choice._onchange_course_id()
        self.assertTrue(choice.course_identity_locked)
        self.assertEqual(choice.program_name, self.courses[0].name)
        self.assertEqual(choice.program_category, self.courses[0].program_category)
        self.assertNotIn(outside_course, choice.available_tna_course_ids._origin)

        plan.restrict_tna_cycles = False
        all_closed_courses = Line.new({'plan_id': plan.id}).available_tna_course_ids._origin
        self.assertTrue(set(self.courses.ids).issubset(set(all_closed_courses.ids)))
        self.assertNotIn(outside_course, all_closed_courses)
        second.course_summary_ids.selected_for_planning = False
        filtered_courses = Line.new({'plan_id': plan.id}).available_tna_course_ids._origin
        self.assertIn(self.courses[0], filtered_courses)
        self.assertNotIn(self.courses[1], filtered_courses)
        with self.assertRaises(ValidationError):
            Line.new({'plan_id': plan.id, 'course_id': self.courses[1].id,
                      'program_name': self.courses[1].name})._check_planning_course_scope()

    def test_nameless_requests_do_not_create_unassigned_plan_program(self):
        entry = self.env['eds.tna.entry'].create({
            'cycle_id': self.cycle.id,
            'employee_id': self.employees[0].id,
            'source': 'pms', 'state': 'submitted',
            'justification': 'Legacy request without a course',
        })
        self.cycle._sync_course_demand()
        self.assertFalse(self.cycle.course_summary_ids)
        self.assertTrue(entry.exists())

    def test_collection_can_close_without_requests_but_cannot_plan_empty_demand(self):
        self.cycle.action_finish_collection()
        self.assertEqual(self.cycle.state, 'closed')
        self.assertFalse(self.cycle.course_summary_ids)
        with self.assertRaises(UserError):
            self.cycle.action_go_to_planning()

    def test_invalidate_course_candidate_updates_demand_plan_and_session(self):
        for employee in self.employees:
            self.env['eds.tna.entry'].create({
                'cycle_id': self.cycle.id,
                'employee_id': employee.id,
                'requested_course_ids': [(6, 0, self.courses[0].ids)],
                'source': 'manual', 'state': 'submitted',
                'justification': 'Training requested',
            })
        self.cycle.action_finish_collection()
        self.env['eds.annual.plan'].create({
            'fiscal_year': str(fields.Date.today().year),
        })
        plan = self.env['eds.annual.plan'].browse(
            self.cycle.action_go_to_planning()['res_id'])
        course_line = self.cycle.course_summary_ids.filtered(
            lambda line: line.course_id == self.courses[0])
        plan_line = plan.line_ids.filtered(lambda line: line.course_id == self.courses[0])
        session = self.env['eds.session'].create({
            'plan_line_id': plan_line.id, 'course_id': self.courses[0].id,
            'date_start': '%s-11-01 09:00:00' % fields.Date.today().year,
            'date_end': '%s-11-01 17:00:00' % fields.Date.today().year,
        })
        self.assertEqual(len(session.enrollment_ids), 2)
        candidate = course_line.employee_demand_ids.filtered(
            lambda row: row.employee_id == self.employees[0])
        self.assertEqual(candidate.action_open_invalidate_wizard()['res_model'],
                         'eds.tna.demand.invalidate.wizard')
        with self.assertRaises(UserError):
            candidate.action_invalidate_with_reason('  ')

        candidate.action_invalidate_with_reason('Role does not need this course')
        self.assertTrue(candidate.excluded_from_planning)
        self.assertEqual(candidate.exclusion_reason, 'Role does not need this course')
        self.assertTrue(candidate.evidence_ids)
        self.assertEqual(course_line.total_employees, 1)
        self.assertEqual(course_line.request_count, 1)
        self.assertEqual(course_line.employee_ids, self.employees[1])
        self.assertEqual(plan_line.planned_participants, 1)
        self.assertEqual(session.enrollment_ids.mapped('employee_id'), self.employees[1])
        self.cycle._sync_course_demand()
        self.assertTrue(candidate.excluded_from_planning)

        candidate.action_restore()
        self.assertFalse(candidate.excluded_from_planning)
        self.assertEqual(course_line.total_employees, 2)
        self.assertEqual(plan_line.planned_participants, 2)
        session.action_refresh_suggested_employees()
        self.assertEqual(set(session.enrollment_ids.mapped('employee_id').ids),
                         set(self.employees.ids))

    def test_bulk_invalidation_wizard_preserves_evidence(self):
        for employee in self.employees:
            self.env['eds.tna.entry'].create({
                'cycle_id': self.cycle.id,
                'employee_id': employee.id,
                'requested_course_ids': [(6, 0, self.courses[0].ids)],
                'source': 'manual', 'state': 'submitted',
                'justification': 'Training requested',
            })
        self.cycle.action_finish_collection()
        course_line = self.cycle.course_summary_ids.filtered(
            lambda line: line.course_id == self.courses[0])
        candidates = course_line.employee_demand_ids
        wizard = self.env['eds.tna.demand.invalidate.wizard'].create({
            'demand_ids': [(6, 0, candidates.ids)],
            'reason': 'Outside the current training cohort',
        })
        self.assertEqual(wizard.employee_count, 2)
        wizard.action_confirm()
        self.assertEqual(course_line.total_employees, 0)
        self.assertFalse(course_line.employee_ids)
        self.assertTrue(all(candidates.mapped('excluded_from_planning')))
        self.assertEqual(len(candidates.mapped('evidence_ids')), 2)
        self.assertEqual(self.cycle._sync_course_demand()[0], 1)
        with self.assertRaises(UserError):
            self.cycle.action_go_to_planning()
        candidates.action_restore()
        self.assertEqual(course_line.total_employees, 2)

    def test_custom_course_match_does_not_create_extra_demand_or_combined_course(self):
        consolidation = self.env['eds.tna.consolidation'].create({
            'cycle_id': self.cycle.id, 'state': 'approved',
        })
        Entry = self.env['eds.tna.entry']
        common = {
            'cycle_id': self.cycle.id, 'consolidation_id': consolidation.id,
            'justification': 'Required training', 'state': 'approved',
        }
        individual = Entry.create(dict(common,
            request_level='individual', source='manual', employee_id=self.employees[0].id,
            requested_course_ids=[(6, 0, self.courses.ids)]))
        custom = Entry.create(dict(common,
            request_level='work_unit', source='manual', work_unit_id=self.unit.id,
            work_unit_employee_ids=[(6, 0, [self.employees[1].id])],
            is_custom_course=True, custom_course_title='EDS Demand Course'))
        self.assertEqual(custom.course_match_status, 'higher')
        self.assertTrue(custom.recommended_course_id)
        self.assertEqual(custom.catalog_status, 'outside_catalog')

        self.cycle._sync_course_demand()
        self.assertEqual(len(self.cycle.course_summary_ids), 3)
        proposed = self.cycle.course_summary_ids.filtered(
            lambda line: line.course_name == 'EDS Demand Course')
        self.assertEqual((proposed.catalog_status, proposed.total_employees),
                         ('outside_catalog', 1))
        self.assertFalse(proposed.course_id)
        self.assertEqual(sum(self.cycle.course_summary_ids.mapped('request_count')), 3)

        consolidation.action_generate_courses_from_tna()
        self.assertFalse(individual.converted_course_ref)
        self.assertEqual(custom.converted_course_ref, 'EDS Demand Course')
        self.assertFalse(self.env['eds.course'].search([
            ('name', 'ilike', 'EDS Demand Course A, EDS Demand Course B'),
        ]))

    def test_cycle_tabs_separate_requests_diagnostics_and_screened_needs(self):
        Entry = self.env['eds.tna.entry']
        common = {'cycle_id': self.cycle.id, 'justification': 'Scope test'}
        individual = Entry.create(dict(common, request_level='individual', source='manual',
            employee_id=self.employees[0].id,
            requested_course_ids=[(6, 0, [self.courses[0].id])], state='submitted'))
        diagnostic = Entry.create(dict(common, request_level='individual', source='pms',
            employee_id=self.employees[1].id, pms_measurement_name='Service Accuracy',
            state='submitted'))
        draft_work_unit = Entry.create(dict(common, request_level='work_unit', source='manual',
            work_unit_id=self.unit.id, state='draft'))
        flagged = Entry.create(dict(common, request_level='individual', source='competency_gap',
            employee_id=self.employees[1].id, is_duplicate=True, state='submitted'))
        self.assertIn(individual, self.cycle.individual_entry_ids)
        self.assertEqual(individual.work_unit_id, self.unit)
        with self.assertRaises(UserError):
            individual.work_unit_id = False
        self.assertNotIn(diagnostic, self.cycle.individual_entry_ids)
        self.assertIn(diagnostic, self.cycle.diagnostic_entry_ids)
        self.assertNotIn(draft_work_unit, self.cycle.work_unit_entry_ids)
        self.assertIn(flagged, self.cycle.duplicate_entry_ids)
        self.assertEqual(diagnostic.competency_or_measurement, 'Service Accuracy')
        with self.assertRaises(ValidationError):
            Entry.create(dict(common, request_level='individual', source='manual',
                employee_id=self.employees[1].id, is_custom_course=True,
                custom_course_title='Unsupported Self Service Course', state='submitted'))

    def test_work_unit_request_is_limited_to_managed_units(self):
        manager_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'EDS Work Unit Manager', 'login': 'eds_work_unit_manager_scope_test',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                   self.env.ref('employee_development_system.group_eds_line_manager').id])],
        })
        manager_employee = self.env['hr.employee'].create({
            'name': 'EDS Work Unit Manager', 'user_id': manager_user.id,
            'default_operating_unit_id': self.unit.id,
        })
        self.unit.manager_id = manager_employee
        other_unit = self.env['operating.unit'].create({
            'name': 'EDS Other Unit', 'sol_id': 987655, 'work_unit_type': 'head_office',
        })
        Entry = self.env['eds.tna.entry'].with_user(manager_user).sudo(False)
        self.assertFalse(Entry.env.su)
        self.assertFalse(manager_user.has_group('employee_development_system.group_eds_officer'))
        self.assertNotIn(other_unit, self.env['eds.hr.compat'].with_user(manager_user).get_managed_operating_units())
        allowed = Entry.create({
            'cycle_id': self.cycle.id, 'request_level': 'work_unit',
            'work_unit_id': self.unit.id, 'course_id': self.courses[0].id,
            'work_unit_employee_ids': [(6, 0, [self.employees[0].id])],
            'justification': 'Managed unit request', 'state': 'draft',
        })
        allowed.action_submit()
        self.assertEqual(allowed.state, 'submitted')
        self.assertEqual(allowed.work_unit_id, self.unit)
        with self.assertRaises(ValidationError):
            Entry.create({
                'cycle_id': self.cycle.id, 'request_level': 'work_unit',
                'work_unit_id': other_unit.id, 'course_id': self.courses[0].id,
                'justification': 'Unmanaged unit request', 'state': 'draft',
            })

    def test_pms_only_course_compiles_measurement_outcome(self):
        employee = self.employees[0]
        job = self.env['hr.job'].create({'name': 'EDS PMS Outcome Test Job'})
        objective = self.env['performance.objective'].create({
            'name': 'EDS PMS Outcome Objective', 'employee_id': employee.id,
        })
        parent_measure = self.env['performance.measure'].create({
            'name': 'EDS Parent Measure', 'objective_id': objective.id,
            'weight': 100.0,
        })
        kpi = self.env['performance.job.objective'].create({
            'name': 'EDS Service Quality KPI', 'operating_unit_id': self.unit.id,
            'job_id': job.id, 'parent_measure_id': parent_measure.id,
            'measure_ids': [(0, 0, {
                'name': 'Customer Response Time', 'weight': 100.0,
                'target_type': 'percent',
            })],
        })
        self.env['eds.course.pms.line'].create({
            'course_id': self.courses[0].id,
            'job_measure_id': kpi.measure_ids.id,
            'min_threshold': 75.0,
            'notes': 'Practice timely customer follow-up.',
        })
        self.courses[0].action_generate_learning_objectives()
        self.assertIn('Customer Response Time', self.courses[0].learning_outcomes)
        self.assertIn('Practice timely customer follow-up.', self.courses[0].learning_outcomes)

    def test_vendor_matrix_threshold_and_single_award(self):
        plan = self.env['eds.annual.plan'].create({
            'name': 'EDS Vendor Matrix Plan', 'fiscal_year': '2098', 'state': 'published',
        })
        plan_line = self.env['eds.annual.plan.line'].create({
            'plan_id': plan.id, 'course_id': self.courses[0].id,
            'program_name': self.courses[0].name,
            'delivery_method': 'local_external',
        })
        self.assertEqual(plan_line.display_name, self.courses[0].name)
        draft_selection = self.env['eds.course.vendor.selection'].new({'annual_plan_id': plan.id})
        draft_selection._onchange_annual_plan_id()
        self.assertEqual(draft_selection.plan_line_id, plan_line)
        selection = self.env['eds.course.vendor.selection'].create({
            'annual_plan_id': plan.id, 'plan_line_id': plan_line.id,
        })
        self.assertEqual(selection.course_id, self.courses[0])
        session = self.env['eds.session'].create({
            'plan_line_id': plan_line.id, 'course_id': self.courses[0].id,
            'date_start': '2098-03-01 09:00:00', 'date_end': '2098-03-01 17:00:00',
        })
        vendor = self.env['eds.external.provider'].create({
            'name': 'EDS Vendor Matrix Provider',
        })
        winning = self.env['eds.course.vendor.line'].create({
            'selection_id': selection.id, 'vendor_id': vendor.id, 'vendor_name': 'Vendor A',
            'quality_score': 8, 'experience_score': 8,
            'scalability_score': 8, 'demo_score': 8, 'price_score': 7,
        })
        failing = self.env['eds.course.vendor.line'].create({
            'selection_id': selection.id, 'vendor_name': 'Vendor B',
            'quality_score': 4, 'experience_score': 4,
            'scalability_score': 4, 'demo_score': 4, 'price_score': 10,
        })
        self.assertTrue(winning.technical_threshold_met)
        self.assertAlmostEqual(winning.total_score, 77.0)
        self.assertFalse(failing.technical_threshold_met)
        self.assertEqual(failing.total_score, 0.0)
        invalid = self.env['eds.course.vendor.line'].new({
            'selection_id': selection.id, 'quality_score': 32,
        })
        warning = invalid._onchange_score_range()
        self.assertEqual(invalid.quality_score, 0)
        self.assertIn('warning', warning)
        with self.assertRaises(ValidationError):
            self.env['eds.course.vendor.line'].create({
                'selection_id': selection.id, 'quality_score': 32,
            })
        selection.action_start_evaluation()
        with self.assertRaises(UserError):
            selection.action_mark_awarded()
        with self.assertRaises(UserError):
            failing.action_award()
        winning.action_award()
        self.assertEqual(winning.status, 'awarded')
        self.assertEqual(selection.state, 'evaluation')
        self.assertFalse(winning.award_attachment)
        self.assertFalse(winning.contract_attachment)
        self.assertEqual(selection.awarded_vendor_id, vendor)
        self.assertFalse(session.awarded_provider_id)
        other_vendor = self.env['eds.external.provider'].create({
            'name': 'EDS Second Qualified Provider',
        })
        second = self.env['eds.course.vendor.line'].create({
            'selection_id': selection.id, 'vendor_id': other_vendor.id,
            'quality_score': 8, 'experience_score': 8,
            'scalability_score': 8, 'demo_score': 8, 'price_score': 8,
        })
        with self.assertRaises(UserError):
            second.action_award()
        selection.action_mark_awarded()
        self.assertEqual(selection.state, 'awarded')
        self.assertEqual(session.awarded_provider_id, vendor)
        selection.action_mark_awarded()
        self.assertEqual(selection.state, 'awarded')
        with self.assertRaises(ValidationError):
            self.env['eds.session'].create({
                'plan_line_id': plan_line.id, 'course_id': self.courses[0].id,
                'date_start': '2098-03-02 09:00:00', 'date_end': '2098-03-02 17:00:00',
            })
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.cr.execute(
                'UPDATE eds_course_vendor_line SET status = %s WHERE id = %s',
                ['awarded', second.id])
        second.invalidate_recordset(['status'])
        self.assertEqual(selection.awarded_vendor_id, vendor)
        self.assertEqual(second.status, 'draft')
        winning.contract_attachment = base64.b64encode(b'signed contract')
        self.assertEqual(winning.status, 'awarded')

    def test_custom_program_requires_catalog_course(self):
        plan = self.env['eds.annual.plan'].create({
            'name': 'EDS Custom Program Plan', 'fiscal_year': '2098', 'state': 'published',
        })
        with self.assertRaises(ValidationError):
            self.env['eds.annual.plan.line'].create({
                'plan_id': plan.id, 'program_name': 'Custom Leadership Workshop',
            })

    def test_plan_checker_director_chief_approval_chain(self):
        officer_group = self.env.ref('employee_development_system.group_eds_officer')
        checker_group = self.env.ref('employee_development_system.group_eds_team_leader')
        director_group = self.env.ref('employee_development_system.group_eds_director')
        chief_group = self.env.ref('employee_development_system.group_eds_chief')
        users = []
        for label, group in [('Creator', officer_group), ('Checker', checker_group),
                             ('Director', director_group), ('Chief', chief_group)]:
            users.append(self.env['res.users'].with_context(no_reset_password=True).create({
                'name': 'EDS Plan ' + label,
                'login': 'eds_plan_' + label.lower() + '@example.test',
                'group_ids': [(6, 0, [self.env.ref('base.group_user').id, group.id])],
            }))
        creator, checker, director, chief = users
        plan = self.env['eds.annual.plan'].create({
            'name': 'EDS Approval Test Plan', 'fiscal_year': '2099',
            'creator_id': creator.id, 'team_leader_id': checker.id,
            'reviewer_id': director.id, 'approver_id': chief.id,
        })
        self.env['eds.annual.plan.line'].create({
            'plan_id': plan.id, 'course_id': self.courses[0].id,
            'program_name': self.courses[0].name,
        })
        plan.with_user(creator).action_submit_to_team_leader()
        with self.assertRaises(UserError):
            plan.with_user(creator).action_team_leader_forward()
        plan.with_user(checker).action_team_leader_forward()
        plan.with_user(director).action_return_plan_from_wizard(
            'Please revise the budget.')
        self.assertEqual(plan.state, 'team_leader_review')
        plan.with_user(checker).action_team_leader_forward()
        plan.with_user(director).action_director_forward()
        with self.assertRaises(UserError):
            plan.with_user(director).action_chief_approve()
        plan.with_user(chief).action_chief_approve()
        self.assertEqual(plan.state, 'published')
        self.assertEqual(len(plan.line_ids.session_ids), 1)

    def test_attendance_export_import_dates_and_certificate_preview(self):
        session = self.env['eds.session'].create({
            'course_id': self.courses[0].id,
            'date_start': '2098-05-01 09:00:00',
            'date_end': '2098-05-02 17:00:00',
        })
        self.env['eds.enrollment'].create({
            'session_id': session.id, 'employee_id': self.employees[0].id,
            'state': 'enrolled',
        })
        self.assertEqual(session.action_open_attendance_import()['res_model'], 'eds.attendance.import')
        action = session.action_export_attendance_xlsx()
        attachment_id = int(action['url'].split('/')[3].split('?')[0])
        attachment = self.env['ir.attachment'].browse(attachment_id)
        workbook = load_workbook(io.BytesIO(base64.b64decode(attachment.datas)))
        sheet = workbook.active
        self.assertEqual(sheet['A7'].value, 'Employee ID')
        self.assertEqual(sheet['A8'].value, self.employees[0].id)
        sheet['F8'] = 'Present'
        sheet['G8'] = 'Absent'
        output = io.BytesIO()
        workbook.save(output)
        wizard = self.env['eds.attendance.import'].create({
            'session_id': session.id,
            'csv_file': base64.b64encode(output.getvalue()),
            'filename': 'attendance.xlsx',
        })
        wizard.action_import_attendance()
        attendance = self.env['eds.session.attendance'].search([
            ('session_id', '=', session.id),
            ('employee_id', '=', self.employees[0].id),
        ])
        self.assertEqual(len(attendance), 2)
        self.assertEqual(sum(attendance.mapped('attended')), 1)
        certificate = self.env['eds.certificate'].create({
            'session_id': session.id, 'employee_id': self.employees[0].id,
        })
        certificate._compute_eligibility()
        self.assertIn('50.0%', certificate.eligibility_reason)
        course_action = self.courses[0].action_preview_certificate()
        session_action = session.action_preview_certificate()
        self.assertEqual(course_action['type'], 'ir.actions.report')
        self.assertEqual(session_action['type'], 'ir.actions.report')
        self.assertNotEqual(course_action['report_name'], session_action['report_name'])
        report = self.env['ir.actions.report']
        for action, record in [
            (course_action, self.courses[0]),
            (session_action, session),
        ]:
            self.assertEqual(report._get_report_from_name(action['report_name']).model, record._name)
            html, _format = report._render_qweb_html(action['report_name'], [record.id])
            self.assertIn(b'SAMPLE EMPLOYEE NAME', html)
            pdf, _format = report.with_context(force_report_rendering=True)._render_qweb_pdf(
                action['report_name'], [record.id]
            )
            self.assertEqual(_format, 'pdf')
            self.assertTrue(pdf.startswith(b'%PDF'))

    def test_hotel_award_and_evaluation_distribution(self):
        plan = self.env['eds.annual.plan'].create({
            'name': 'EDS Delivery Test Plan', 'fiscal_year': '2098', 'state': 'published',
        })
        line = self.env['eds.annual.plan.line'].create({
            'plan_id': plan.id, 'course_id': self.courses[0].id,
            'program_name': self.courses[0].name,
        })
        plan_html, _format = self.env['ir.actions.report']._render_qweb_html(
            'employee_development_system.action_report_eds_annual_plan_preview', [plan.id])
        self.assertIn(b'EDS Delivery Test Plan', plan_html)
        session = self.env['eds.session'].create({
            'plan_line_id': line.id, 'course_id': self.courses[0].id,
            'date_start': '2098-06-01 09:00:00',
            'date_end': '2098-06-01 17:00:00',
        })
        hotel = self.env['eds.venue'].create({
            'name': 'EDS Awarded Hotel', 'venue_type': 'hotel',
        })
        selection = self.env['eds.hotel.selection'].create({
            'plan_line_id': line.id, 'delivery_method': 'local_external',
            'delivery_override': True,
            'delivery_change_reason': 'Offsite delivery requires a hotel.',
        })
        bid = self.env['eds.hotel.bid'].create({
            'selection_id': selection.id, 'venue_id': hotel.id,
            'price_quoted': 1000, 'technical_score': 8,
            'award_attachment': base64.b64encode(b'award letter'),
        })
        selection.action_start_evaluation()
        bid.action_award()
        self.assertEqual(session.awarded_venue_id, hotel)
        self.assertEqual(session.venue_id, hotel)
        self.assertAlmostEqual(bid.total_score, 88.0)
        self.env['eds.enrollment'].create({
            'session_id': session.id, 'employee_id': self.employees[0].id,
            'state': 'completed',
        })
        session._distribute_completion_evaluations()
        survey = self.env['eds.evaluation.level1'].search([
            ('session_id', '=', session.id),
            ('employee_id', '=', self.employees[0].id),
        ])
        self.assertEqual(survey.state, 'distributed')
        self.assertFalse(survey.line_ids)
        survey.action_generate_questions()
        question_ids = survey.line_ids.mapped('question_id').ids
        self.assertTrue(question_ids)
        survey.action_generate_questions()
        self.assertEqual(survey.line_ids.mapped('question_id').ids, question_ids)
        for assessment_type, score in [('pre', 45), ('post', 85)]:
            self.env['eds.assessment'].create({
                'session_id': session.id, 'employee_id': self.employees[0].id,
                'assessment_type': assessment_type, 'score': score,
            })
        gain = self.env['eds.evaluation.level2'].search([
            ('session_id', '=', session.id),
            ('employee_id', '=', self.employees[0].id),
        ])
        self.assertEqual(gain.pre_score, 45)
        self.assertEqual(gain.post_score, 85)
        self.assertTrue(gain.passed)
