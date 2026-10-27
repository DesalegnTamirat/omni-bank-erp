# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import ValidationError


@tagged('post_install', '-at_install', 'eds', 'template_alignment')
class TestTemplateAlignment(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.department = cls.env['hr.department'].create({
            'name': 'Retail Banking Directorate',
        })
        cls.course = cls.env['eds.course'].create({
            'name': 'Anti-Money Laundering & KYC Compliance',
            'code': 'AML-001',
            'category': 'technical_compliance',
            'program_category': 'compliance',
            'target_audience': 'all_staff',
            'delivery_place': 'local',
            'delivery_method': 'internal',
            'duration_days': 2.0,
            'status': 'active',
        })
        cls.cycle = cls.env['eds.tna.cycle'].create({
            'name': 'TNA Cycle 2026/27',
            'year': '2026',
            'start_date': '2026-07-01',
            'submission_end_date': '2026-08-15',
            'approval_deadline': '2026-08-30',
            'state': 'closed',
        })

    def test_01_course_fields(self):
        """Test business template course fields."""
        self.assertEqual(self.course.program_category, 'compliance')
        self.assertEqual(self.course.target_audience, 'all_staff')
        self.assertEqual(self.course.delivery_place, 'local')

    def test_02_tna_entry_collective_fields(self):
        """Test TNA entry collective participant count and competency level."""
        tna = self.env['eds.tna.entry'].create({
            'cycle_id': self.cycle.id,
            'department_id': self.department.id,
            'course_id': self.course.id,
            'target_audience': 'below_mlm',
            'target_participant_count': 45,
            'competency_level': 'intermediate',
            'delivery_mode': 'workshop',
            'quarter': 'q1',
            'urgency': 'high',
            'justification': 'Mandatory regulatory AML refresher for all branch staff.',
        })
        self.assertEqual(tna.target_participant_count, 45)
        self.assertEqual(tna.competency_level, 'intermediate')
        self.assertEqual(tna.target_audience, 'below_mlm')

    def test_03_annual_plan_line_financial_formula(self):
        """Verify the exact financial formula matching Cal_BankLevel row 5:
        Total Provider Cost = Participants * Est Provider Cost
        Total Venue Cost = Participants * Duration * Est Venue Cost / Pax / Day
        Budget Allocated = Provider Cost + Venue Cost
        """
        plan = self.env['eds.annual.plan'].create({
            'name': 'Annual Plan 2026/27',
            'fiscal_year': '2026',
        })
        line = self.env['eds.annual.plan.line'].create({
            'plan_id': plan.id,
            'course_id': self.course.id,
            'program_name': 'AML & KYC Compliance Program',
            'program_category': 'compliance',
            'target_audience': 'all_staff',
            'scheduled_month': '2026-08',
            'duration_days': 3.0,
            'planned_participants': 30,
            'num_sessions': 2,
            'est_provider_cost_per_pax': 1200.0,
            'est_venue_cost_per_pax_day': 800.0,
        })

        # Quarter is computed from 2026-08 (August = Q1 in Bunna fiscal calendar)
        self.assertEqual(line.quarter, 'q1')
        # Workbook prices are per participant per session.
        self.assertAlmostEqual(line.total_provider_cost, 72000.0)
        self.assertAlmostEqual(line.total_venue_cost, 144000.0)
        self.assertAlmostEqual(line.budget_allocated, 216000.0)

        line.write({'est_provider_cost_per_pax': 0.0, 'est_venue_cost_per_pax_day': 0.0})
        self.assertEqual(line.budget_allocated, 0.0)
        line.write({'budget_allocated': 75000.0})
        self.assertEqual(line.budget_allocated, 75000.0)
        expense = line.budget_line_ids[0]
        expense.write({'unit_price': 100.0, 'is_per_employee': True, 'is_general': False})
        self.assertEqual(line.budget_allocated, 3000.0)
        expense.unit_price = 0.0
        self.assertEqual(line.budget_allocated, 75000.0)

    def test_04_calendar_generation_populates_template_fields(self):
        """Verify action_generate_calendar maps target_audience, planned_participants, etc."""
        employee = self.env['hr.employee'].create({
            'name': 'Calendar demand employee', 'department_id': self.department.id,
        })
        # Planning now counts named employees on selected course demand.
        tna = self.env['eds.tna.entry'].create({
            'cycle_id': self.cycle.id,
            'department_id': self.department.id,
            'employee_id': employee.id,
            'course_id': self.course.id,
            'target_audience': 'mlm',
            'target_participant_count': 25,
            'competency_level': 'advanced',
            'delivery_mode': 'classroom',
            'quarter': 'q2',
            'state': 'approved',
            'urgency': 'critical',
            'justification': 'Need for Q2',
        })

        plan = self.env['eds.annual.plan'].create({
            'name': 'Annual Plan Generated 2026/27',
            'fiscal_year': '2026',
            'state': 'draft',
            'restrict_tna_cycles': True,
            'selected_tna_cycle_ids': [(6, 0, self.cycle.ids)],
        })
        self.cycle._sync_course_demand()
        plan.action_generate_calendar()

        # Check line created for the course
        lines = plan.line_ids.filtered(lambda l: l.course_id == self.course)
        self.assertTrue(lines, "Plan line should be generated from selected course demand")
        line = lines[0]
        self.assertEqual(line.program_category, 'compliance')
        self.assertEqual(line.target_audience, 'all_staff')
        self.assertEqual(line.planned_participants, 1)

    def test_06_eds_dashboard_role_adaptation(self):
        """Test eds.dashboard persona and KPI metrics."""
        dashboard = self.env['eds.dashboard'].create({'name': 'Test Overview'})
        # Default with admin/test context
        self.assertIn(dashboard.role_persona, ('admin', 'manager', 'employee'))
        self.assertGreaterEqual(dashboard.total_tna_entries, 0)
        self.assertGreaterEqual(dashboard.published_plans_count, 0)
        # Test navigation action helpers
        act_tna = dashboard.action_open_tna_entries()
        self.assertEqual(act_tna['res_model'], 'eds.tna.entry')
        act_sess = dashboard.action_open_sessions()
        self.assertEqual(act_sess['res_model'],
                         'eds.session' if dashboard.role_persona == 'admin' else 'eds.enrollment')
        if dashboard.role_persona == 'admin':
            act_plan = dashboard.action_open_annual_plans()
            self.assertEqual(act_plan['res_model'], 'eds.annual.plan')
            act_completed = dashboard.action_open_completed_sessions()
            self.assertEqual(act_completed['res_model'], 'eds.session')
        act_cert = dashboard.action_open_certificates()
        self.assertEqual(act_cert['res_model'], 'eds.certificate')
        act_nom = dashboard.action_open_nominations()
        self.assertEqual(act_nom['res_model'], 'eds.enrollment')
        act_idp = dashboard.action_open_idps()
        self.assertEqual(act_idp['res_model'], 'eds.idp')
        act_spons = dashboard.action_open_sponsorships()
        self.assertEqual(act_spons['res_model'], 'eds.sponsorship')
