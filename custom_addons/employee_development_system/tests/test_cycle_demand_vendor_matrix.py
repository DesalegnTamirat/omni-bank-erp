# -*- coding: utf-8 -*-
import base64
import io

from openpyxl import load_workbook

from odoo.exceptions import UserError, ValidationError
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
            'name': 'EDS Demand Test Cycle', 'year': '2098', 'state': 'collecting',
        })

    def test_unique_course_demand_and_selected_planning(self):
        Entry = self.env['eds.tna.entry']
        common = {'cycle_id': self.cycle.id, 'justification': 'Required training'}
        Entry.create(dict(common,
            request_level='individual', source='manual', employee_id=self.employees[0].id,
            requested_course_ids=[(6, 0, self.courses.ids)], state='submitted'))
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
        self.assertGreaterEqual(
            multi_source.overall_priority_score,
            max(multi_source.evidence_ids.mapped('entry_id.priority_score')))
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
        action = self.cycle.action_go_to_planning()
        plan = self.env['eds.annual.plan'].browse(action['res_id'])
        self.assertEqual(len(plan.line_ids), 1)
        self.assertEqual(plan.line_ids.planned_participants, 2)

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

    def test_vendor_matrix_threshold_and_award_files(self):
        plan = self.env['eds.annual.plan'].create({
            'name': 'EDS Vendor Matrix Plan', 'fiscal_year': '2098', 'state': 'published',
        })
        plan_line = self.env['eds.annual.plan.line'].create({
            'plan_id': plan.id, 'course_id': self.courses[0].id,
            'program_name': self.courses[0].name,
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
            winning.action_award()
        winning.award_attachment = base64.b64encode(b'award letter')
        winning.action_award()
        self.assertEqual(selection.awarded_vendor_id, vendor)
        self.assertEqual(session.awarded_provider_id, vendor)
        later_session = self.env['eds.session'].create({
            'plan_line_id': plan_line.id, 'course_id': self.courses[0].id,
            'date_start': '2098-03-02 09:00:00', 'date_end': '2098-03-02 17:00:00',
        })
        self.assertEqual(later_session.awarded_provider_id, vendor)
        with self.assertRaises(UserError):
            winning.action_contract()
        winning.contract_attachment = base64.b64encode(b'signed contract')
        winning.action_contract()
        self.assertEqual(winning.status, 'contract')

    def test_custom_program_and_awarded_hotel_booked(self):
        plan = self.env['eds.annual.plan'].create({
            'name': 'EDS Custom Program Plan', 'fiscal_year': '2098', 'state': 'published',
        })
        plan_line = self.env['eds.annual.plan.line'].create({
            'plan_id': plan.id, 'program_name': 'Custom Leadership Workshop',
        })
        selection = self.env['eds.course.vendor.selection'].create({
            'annual_plan_id': plan.id, 'plan_line_id': plan_line.id,
        })
        self.assertFalse(selection.course_id)
        self.assertEqual(selection.program_name, 'Custom Leadership Workshop')
        hotel = self.env['eds.venue'].create({
            'name': 'EDS Test Hotel', 'venue_type': 'hotel',
        })
        session = self.env['eds.session'].create({
            'plan_line_id': plan_line.id, 'program_name': plan_line.program_name,
            'date_start': '2098-04-01 09:00:00', 'date_end': '2098-04-01 17:00:00',
            'status': 'scheduled',
        })
        session.awarded_venue_id = hotel
        self.assertEqual(session.venue_id, hotel)
        self.assertEqual(session.booking_id.venue_id, hotel)

    def test_plan_checker_director_chief_approval_chain(self):
        officer_group = self.env.ref('employee_development_system.group_eds_officer')
        manager_group = self.env.ref('employee_development_system.group_eds_manager')
        admin_group = self.env.ref('employee_development_system.group_eds_admin')
        users = []
        for label, group in [('Creator', officer_group), ('Checker', manager_group),
                             ('Director', manager_group), ('Chief', admin_group)]:
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
            'team_leader_review', 'Please revise the budget.')
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
        selection = self.env['eds.hotel.selection'].create({'plan_line_id': line.id})
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
        self.assertTrue(survey.line_ids)
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
