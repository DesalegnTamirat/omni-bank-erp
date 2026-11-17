# -*- coding: utf-8 -*-
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'competency_cycle_scope')
class TestCompetencyCycleScope(TransactionCase):

    def setUp(self):
        super().setUp()
        # HR department names in this installation reject numeric characters.
        suffix = ''.join(chr(ord('a') + int(digit, 16)) for digit in uuid4().hex[:12])
        today = fields.Date.today()
        self.today = today
        self.department = self.env['hr.department'].sudo().create({
            'name': 'Scope Department ' + suffix,
            'company_id': self.env.company.id,
        })
        self.other_department = self.env['hr.department'].sudo().create({
            'name': 'Other Scope Department ' + suffix,
            'company_id': self.env.company.id,
        })
        self.operating_unit = self.env['operating.unit'].sudo().create({
            'name': 'Scope Work Unit ' + suffix,
            'sol_id': uuid4().int % 1_000_000_000 + 1,
            'work_unit_type': 'other',
            'company_id': self.env.company.id,
        })
        employee_group = self.env.ref('competency_management.group_competency_employee')
        admin_group = self.env.ref('competency_management.group_competency_admin')
        internal_group = self.env.ref('base.group_user')
        Users = self.env['res.users'].with_context(no_reset_password=True)
        self.included_user = Users.create({
            'name': 'Scoped Employee ' + suffix,
            'login': 'scoped_employee_' + suffix,
            'group_ids': [(6, 0, [internal_group.id, employee_group.id])],
        })
        self.excluded_user = Users.create({
            'name': 'Outside Employee ' + suffix,
            'login': 'outside_employee_' + suffix,
            'group_ids': [(6, 0, [internal_group.id, employee_group.id])],
        })
        self.admin_user = Users.create({
            'name': 'Scope Administrator ' + suffix,
            'login': 'scope_admin_' + suffix,
            'group_ids': [(6, 0, [internal_group.id, admin_group.id])],
        })
        Employee = self.env['hr.employee'].sudo()
        self.department_employee = Employee.create({
            'name': 'Department Participant ' + suffix,
            'department_id': self.department.id,
            'user_id': self.included_user.id,
            'company_id': self.env.company.id,
        })
        self.unit_employee = Employee.create({
            'name': 'Work Unit Participant ' + suffix,
            'department_id': self.other_department.id,
            'default_operating_unit_id': self.operating_unit.id,
            'company_id': self.env.company.id,
        })
        self.explicit_employee = Employee.create({
            'name': 'Individual Participant ' + suffix,
            'department_id': self.other_department.id,
            'company_id': self.env.company.id,
        })
        self.excluded_employee = Employee.create({
            'name': 'Excluded Participant ' + suffix,
            'department_id': self.other_department.id,
            'user_id': self.excluded_user.id,
            'company_id': self.env.company.id,
        })
        self.cycle = self.env['competency.assessment.cycle'].sudo().create({
            'name': 'Targeted Cycle ' + suffix,
            'period_start': today,
            'period_end': today + timedelta(days=30),
            'assessment_deadline': today + timedelta(days=20),
            'is_targeted': True,
            'target_type': 'department',
            'target_department_ids': [(6, 0, self.department.ids)],
            # Inactive selectors may retain old form values. They must not
            # widen a department-only cycle.
            'target_operating_unit_ids': [(6, 0, self.operating_unit.ids)],
            'target_employee_ids': [(6, 0, self.explicit_employee.ids)],
        })

    def _open_with_frozen_scope(self):
        selected_ids = self.cycle._get_scope_employee_ids()
        self.cycle.sudo().with_context(force_write=True, freeze_cycle_scope=True).write({
            'scoped_employee_ids': [(6, 0, list(selected_ids))],
            'state': 'open',
        })

    def test_department_target_ignores_inactive_selectors(self):
        expected = {self.department_employee.id}
        self.assertEqual(self.cycle._get_scope_employee_ids(), expected)
        self.assertEqual(self.cycle.scope_employee_count, 1)
        self.assertNotIn(self.unit_employee.id, expected)
        self.assertNotIn(self.explicit_employee.id, expected)

    def test_operating_unit_target_includes_only_unit_employees(self):
        self.cycle.sudo().write({'target_type': 'operating_unit'})
        self.assertEqual(self.cycle._get_scope_employee_ids(), {self.unit_employee.id})
        self.assertEqual(self.cycle.scope_employee_count, 1)

    def test_employee_target_includes_only_selected_employees(self):
        self.cycle.sudo().write({'target_type': 'employee'})
        self.assertEqual(self.cycle._get_scope_employee_ids(), {self.explicit_employee.id})
        self.assertEqual(self.cycle.scope_employee_count, 1)

    def test_targeted_cycle_requires_target_type_before_opening(self):
        self.cycle.sudo().write({'target_type': False})
        with self.assertRaises(UserError):
            with self.env.cr.savepoint():
                self.cycle.with_user(self.admin_user).action_start()

    def test_selected_type_requires_matching_employees_before_opening(self):
        self.cycle.sudo().write({
            'target_type': 'employee',
            'target_employee_ids': [(5, 0, 0)],
        })
        with self.assertRaises(UserError):
            with self.env.cr.savepoint():
                self.cycle.with_user(self.admin_user).action_start()

    def test_bankwide_cycle_includes_active_employee_by_default(self):
        bankwide = self.env['competency.assessment.cycle'].sudo().create({
            'name': 'Bankwide Scope Cycle ' + uuid4().hex[:12],
            'period_start': self.today,
            'assessment_deadline': self.today + timedelta(days=20),
        })
        self.assertFalse(bankwide.is_targeted)
        self.assertTrue(bankwide._includes_employee(self.excluded_employee))

    def test_overlapping_targeted_cycles_are_allowed(self):
        second = self.env['competency.assessment.cycle'].sudo().create({
            'name': 'Parallel Targeted Cycle ' + uuid4().hex[:12],
            'period_start': self.cycle.period_start,
            'period_end': self.cycle.period_end,
            'assessment_deadline': self.cycle.assessment_deadline,
            'is_targeted': True,
            'target_type': 'employee',
            'target_employee_ids': [(6, 0, self.excluded_employee.ids)],
        })
        self.assertTrue(second.exists())
        self.assertEqual(second._get_scope_employee_ids(), {self.excluded_employee.id})
        self._open_with_frozen_scope()
        second.sudo().with_context(force_write=True, freeze_cycle_scope=True).write({
            'scoped_employee_ids': [(6, 0, self.excluded_employee.ids)],
            'state': 'open',
        })
        self.assertEqual(self.cycle.state, 'open')
        self.assertEqual(second.state, 'open')

    def test_competency_admin_can_search_employee_selector(self):
        results = self.env['hr.employee'].with_user(self.admin_user).with_context(
            competency_employee_select=True,
        ).name_search(self.department_employee.name)
        self.assertIn(self.department_employee.id, [employee_id for employee_id, _name in results])

    def test_competency_admin_can_search_department_and_unit_selectors(self):
        for model_name, record in (
            ('hr.department', self.department),
            ('operating.unit', self.operating_unit),
        ):
            with self.subTest(model=model_name):
                results = self.env[model_name].with_user(self.admin_user).name_search(record.name)
                self.assertIn(record.id, [record_id for record_id, _name in results])

    def test_regular_employee_cannot_read_cycle_target_fields(self):
        field_names = [
            'is_targeted', 'target_type', 'target_department_ids', 'target_operating_unit_ids',
            'target_employee_ids', 'scoped_employee_ids', 'scope_employee_count',
        ]
        available = self.env['competency.assessment.cycle'].with_user(
            self.excluded_user,
        ).fields_get(field_names)
        for name in field_names:
            self.assertNotIn(name, available)

    def test_dashboard_excludes_unrelated_open_cycle(self):
        self._open_with_frozen_scope()
        Dashboard = self.env['competency.dashboard']
        self.assertEqual(
            Dashboard.with_user(self.included_user)._default_cycle_id().id,
            self.cycle.id,
        )
        self.assertNotEqual(
            Dashboard.with_user(self.excluded_user)._default_cycle_id().id,
            self.cycle.id,
        )
        outside_dashboard = Dashboard.sudo().create({'cycle_id': self.cycle.id})
        with self.assertRaises(UserError):
            with self.env.cr.savepoint():
                outside_dashboard.with_user(self.excluded_user).action_start_self_assessment()
        inside_dashboard = Dashboard.sudo().create({'cycle_id': self.cycle.id})
        result = inside_dashboard.with_user(self.included_user).action_start_self_assessment()
        assessment = self.env['competency.assessment'].sudo().browse(result['res_id'])
        self.assertEqual(assessment.employee_id, self.department_employee)
        self.assertEqual(assessment.cycle_id, self.cycle)

    def test_outside_employee_cannot_create_self_assessment_in_cycle(self):
        self._open_with_frozen_scope()
        with self.assertRaises(UserError):
            with self.env.cr.savepoint():
                self.env['competency.assessment'].with_user(self.excluded_user).create({
                    'cycle_id': self.cycle.id,
                    'employee_id': self.excluded_employee.id,
                    'assessor_id': self.excluded_user.id,
                    'assessment_type': 'self',
                })
        with self.assertRaises(UserError):
            with self.env.cr.savepoint():
                self.env['competency.assessment'].sudo().create({
                    'cycle_id': self.cycle.id,
                    'employee_id': self.excluded_employee.id,
                    'assessor_id': self.excluded_user.id,
                    'assessment_type': 'self',
                })

    def test_external_manager_can_assess_selected_employee(self):
        self.department_employee.sudo().write({
            'parent_id': self.excluded_employee.id,
            'coach_id': self.excluded_employee.id,
        })
        self._open_with_frozen_scope()
        manager_assessment = self.env['competency.assessment'].sudo().create({
            'cycle_id': self.cycle.id,
            'employee_id': self.department_employee.id,
            'assessor_id': self.excluded_user.id,
            'assessment_type': 'team',
        })
        self.assertEqual(manager_assessment.employee_id, self.department_employee)
        self.assertNotIn(self.excluded_employee.id, self.cycle.scoped_employee_ids.ids)
        with self.assertRaises(UserError):
            with self.env.cr.savepoint():
                manager_assessment.sudo().write({'employee_id': self.excluded_employee.id})

    def test_generation_keeps_outside_manager_as_rater_only(self):
        self.department_employee.sudo().write({'parent_id': self.excluded_employee.id})
        self._open_with_frozen_scope()
        EmployeeModel = type(self.env['hr.employee'])
        original_search = EmployeeModel.search
        active_pool = self.department_employee | self.excluded_employee

        def small_employee_pool(records, domain, *args, **kwargs):
            if domain == [('active', '=', True)]:
                return active_pool
            return original_search(records, domain, *args, **kwargs)

        # Production generation commits every chunk. Keep this TransactionCase
        # isolated while exercising the real pair-building and create paths.
        with patch.object(EmployeeModel, 'search', small_employee_pool), \
                patch.object(self.env.cr, 'commit', return_value=None):
            self.cycle._generate_cycle_assessments_batch()

        assessments = self.env['competency.assessment'].sudo().search([
            ('cycle_id', '=', self.cycle.id),
        ])
        self.assertTrue(assessments)
        self.assertEqual(set(assessments.mapped('employee_id').ids), {self.department_employee.id})
        self.assertTrue(assessments.filtered(lambda assessment:
            assessment.employee_id == self.department_employee
            and assessment.assessor_id == self.excluded_user
            and assessment.assessment_type == 'team'
        ))

    def test_generation_excludes_outside_peer_but_keeps_outside_boss(self):
        peer_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Outside Peer ' + uuid4().hex[:8],
            'login': 'outside_scope_peer_' + uuid4().hex[:12],
            'group_ids': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('competency_management.group_competency_employee').id,
            ])],
        })
        outside_peer = self.env['hr.employee'].sudo().create({
            'name': 'Outside Peer Employee',
            'department_id': self.department.id,
            'parent_id': self.excluded_employee.id,
            'coach_id': self.excluded_employee.id,
            'user_id': peer_user.id,
            'company_id': self.env.company.id,
        })
        self.department_employee.sudo().write({
            'parent_id': self.excluded_employee.id,
            'coach_id': self.excluded_employee.id,
        })
        # Same coach, department, grade and job make this a normal peer pair;
        # explicit employee targeting excludes that peer from the cohort.
        self.assertEqual(self.department_employee.coach_id, outside_peer.coach_id)
        self.assertEqual(self.department_employee.department_id, outside_peer.department_id)
        self.cycle.sudo().write({
            'target_type': 'employee',
            'target_employee_ids': [(6, 0, self.department_employee.ids)],
        })
        self._open_with_frozen_scope()

        EmployeeModel = type(self.env['hr.employee'])
        original_search = EmployeeModel.search
        active_pool = self.department_employee | self.excluded_employee | outside_peer

        def small_employee_pool(records, domain, *args, **kwargs):
            if domain == [('active', '=', True)]:
                return active_pool
            return original_search(records, domain, *args, **kwargs)

        with patch.object(EmployeeModel, 'search', small_employee_pool), \
                patch.object(self.env.cr, 'commit', return_value=None):
            self.cycle._generate_cycle_assessments_batch()

        assessments = self.env['competency.assessment'].sudo().search([
            ('cycle_id', '=', self.cycle.id),
        ])
        self.assertEqual(set(assessments.mapped('employee_id').ids), {self.department_employee.id})
        self.assertTrue(assessments.filtered(lambda assessment:
            assessment.assessment_type == 'team'
            and assessment.assessor_id == self.excluded_user
        ))
        self.assertFalse(assessments.filtered(lambda assessment:
            assessment.assessor_id == peer_user
            and assessment.assessment_type in ('peer', 'subordinate')
        ))
        with self.assertRaises(UserError):
            with self.env.cr.savepoint():
                self.env['competency.assessment'].sudo().create({
                    'cycle_id': self.cycle.id,
                    'employee_id': self.department_employee.id,
                    'assessor_id': peer_user.id,
                    'assessment_type': 'peer',
                })

    def test_scope_cannot_change_after_opening(self):
        self._open_with_frozen_scope()
        with self.assertRaises(ValidationError):
            with self.env.cr.savepoint():
                self.cycle.with_user(self.admin_user).write({
                    'target_employee_ids': [(6, 0, self.excluded_employee.ids)],
                })
        with self.assertRaises(ValidationError):
            with self.env.cr.savepoint():
                self.cycle.with_user(self.admin_user).write({'target_type': 'employee'})
        self.assertEqual(self.cycle._get_scope_employee_ids(), {
            self.department_employee.id,
        })

