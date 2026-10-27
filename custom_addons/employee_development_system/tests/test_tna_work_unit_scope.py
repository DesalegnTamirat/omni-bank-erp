# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'eds', 'tna_work_unit_scope')
class TestTnaWorkUnitScope(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Unit = cls.env['operating.unit']
        cls.unit_a = Unit.create({
            'name': 'EDS Scope Alpha Unit', 'sol_id': 998101,
            'work_unit_type': 'head_office',
        })
        cls.unit_b = Unit.create({
            'name': 'EDS Scope Beta Unit', 'sol_id': 998102,
            'work_unit_type': 'head_office',
        })
        cls.unit_c = Unit.create({
            'name': 'EDS Scope Gamma Unit', 'sol_id': 998103,
            'work_unit_type': 'head_office',
        })
        Department = cls.env['hr.department']
        cls.department_a = Department.create({
            'name': 'EDS Scope Alpha Division', 'operating_unit_id': cls.unit_a.id,
        })
        cls.department_b = Department.create({
            'name': 'EDS Scope Gamma Division', 'operating_unit_id': cls.unit_c.id,
        })
        cls.unit_a.department = cls.department_a
        cls.unit_b.department = cls.department_a
        cls.unit_c.department = cls.department_b
        cls.job_a = cls.env['hr.job'].create({'name': 'EDS Scope Operations Officer'})
        cls.job_b = cls.env['hr.job'].create({'name': 'EDS Scope Service Officer'})
        cls.leader_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'EDS Reporting Leader', 'login': 'eds_reporting_leader_scope_test',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id,
                                   cls.env.ref('employee_development_system.group_eds_employee').id])],
        })
        cls.leader = cls.env['hr.employee'].create({
            'name': 'EDS Reporting Leader', 'user_id': cls.leader_user.id,
            'department_id': cls.department_a.id,
            'default_operating_unit_id': cls.unit_a.id,
        })
        cls.staff = cls.env['hr.employee'].create([
            {'name': 'EDS Scope First Officer', 'parent_id': cls.leader.id,
             'department_id': cls.department_a.id,
             'default_operating_unit_id': cls.unit_a.id, 'job_position': cls.job_a.id},
            {'name': 'EDS Scope Second Officer', 'parent_id': cls.leader.id,
             'department_id': cls.department_a.id,
             'default_operating_unit_id': cls.unit_a.id, 'job_position': cls.job_b.id},
        ])
        cls.courses = cls.env['eds.course'].create({
            'name': 'EDS Scope Course', 'code': 'EDS-SCOPE-COURSE', 'status': 'active',
        })
        cls.cycle = cls.env['eds.tna.cycle'].create({'state': 'collecting'})

    def test_normal_employee_leader_can_request_for_all_unit_jobs(self):
        Entry = self.env['eds.tna.entry'].with_user(self.leader_user).sudo(False)
        draft = Entry.new({'cycle_id': self.cycle.id})
        self.assertTrue(draft.can_request_work_unit)
        draft.request_level = 'work_unit'
        draft._onchange_request_level()
        self.assertEqual(draft.department_id._origin, self.department_a)
        self.assertEqual(draft.work_unit_id._origin, self.unit_a)
        self.assertFalse(draft.can_choose_department)
        self.assertFalse(draft.can_choose_work_unit)
        self.assertFalse(draft.job_position_id)
        self.assertNotIn(self.unit_c, draft.allowed_work_unit_ids._origin)
        # The leader is also an employee of this unit and may be nominated.
        self.assertEqual(set(draft.eligible_work_unit_employee_ids._origin.ids),
                         set((self.staff | self.leader).ids))
        self.assertEqual(
            len(self.staff.with_user(self.leader_user).sudo(False).read(['name'])), 2)

        request = Entry.create({
            'cycle_id': self.cycle.id, 'request_level': 'work_unit',
            'department_id': self.department_a.id, 'work_unit_id': self.unit_a.id,
            'course_id': self.courses.id,
            'work_unit_employee_ids': [(6, 0, self.staff.ids)],
            'target_participant_count': 1,
            'justification': 'Both job positions need the same training.',
        })
        self.assertFalse(request.job_position_id)
        self.assertFalse(request.employee_id)
        self.assertEqual(request.target_participant_count, 2)
        request.write({
            'work_unit_employee_ids': [(6, 0, self.staff[:1].ids)],
            'target_participant_count': 99,
        })
        self.assertEqual(request.target_participant_count, 1)
        request.write({'work_unit_employee_ids': [(6, 0, self.staff.ids)]})
        self.assertEqual(request.target_participant_count, 2)
        request.action_submit()
        self.assertEqual(request.state, 'submitted')

    def test_unit_and_department_choices_follow_reporting_scope(self):
        other_staff = self.env['hr.employee'].create([
            {'name': 'EDS Scope Beta Officer', 'parent_id': self.leader.id,
             'department_id': self.department_a.id,
             'default_operating_unit_id': self.unit_b.id},
            {'name': 'EDS Scope Gamma Officer', 'parent_id': self.leader.id,
             'department_id': self.department_b.id,
             'default_operating_unit_id': self.unit_c.id},
        ])
        Entry = self.env['eds.tna.entry'].with_user(self.leader_user).sudo(False)
        draft = Entry.new({'cycle_id': self.cycle.id, 'request_level': 'work_unit',
                           'department_id': self.department_a.id})
        self.assertTrue(draft.can_choose_department)
        self.assertEqual(set(draft.available_work_unit_ids._origin.ids),
                         set((self.unit_a | self.unit_b).ids))
        self.assertNotIn(self.unit_c.id, draft.available_work_unit_ids._origin.ids)
        draft.work_unit_id = self.unit_b
        draft._onchange_work_unit_id()
        self.assertEqual(draft.work_unit_id._origin, self.unit_b)
        self.assertIn(other_staff[0], draft.eligible_work_unit_employee_ids._origin)
        draft.department_id = self.department_b
        draft._onchange_department_id()
        self.assertEqual(draft.available_work_unit_ids._origin, self.unit_c)
        self.assertEqual(draft.work_unit_id._origin, self.unit_c)
        with self.assertRaises(ValidationError):
            Entry.create({
                'cycle_id': self.cycle.id, 'request_level': 'work_unit',
                'department_id': self.department_b.id, 'work_unit_id': self.unit_a.id,
                'course_id': self.courses.id,
                'justification': 'Unit and department do not match.',
            })

        # A department head also inherits child departments and their units.
        self.department_b.parent_id = self.department_a
        department_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'EDS Department Head', 'login': 'eds_department_head_scope_test',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        department_head = self.env['hr.employee'].create({
            'name': 'EDS Department Head', 'user_id': department_user.id,
            'department_id': self.department_a.id,
            'default_operating_unit_id': self.unit_a.id,
        })
        self.department_a.manager_id = department_head

        # Imported HR records may omit unit-to-department links; employee
        # assignments still establish the department head's work-unit scope.
        self.unit_b.department = False
        self.unit_c.department = False
        self.department_b.operating_unit_id = False
        units, departments = self.env['eds.hr.compat'].with_user(
            department_user).get_managed_training_scope()
        self.assertIn(self.unit_b, units)
        self.assertIn(self.unit_c, units)
        self.assertIn(self.department_b, departments)

    def test_supervisor_below_unit_head_cannot_request_for_entire_unit(self):
        supervisor_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'EDS Unit Supervisor', 'login': 'eds_unit_supervisor_scope_test',
            'group_ids': [(6, 0, [self.env.ref('base.group_user').id,
                                   self.env.ref('employee_development_system.group_eds_employee').id])],
        })
        supervisor = self.env['hr.employee'].create({
            'name': 'EDS Unit Supervisor', 'user_id': supervisor_user.id,
            'parent_id': self.leader.id, 'department_id': self.department_a.id,
            'default_operating_unit_id': self.unit_a.id,
        })
        self.env['hr.employee'].create({
            'name': 'EDS Supervisor Report', 'parent_id': supervisor.id,
            'department_id': self.department_a.id,
            'default_operating_unit_id': self.unit_a.id,
        })
        Entry = self.env['eds.tna.entry'].with_user(supervisor_user).sudo(False)
        units, _departments = self.env['eds.hr.compat'].with_user(
            supervisor_user).get_managed_training_scope()
        self.assertFalse(
            Entry.new({'cycle_id': self.cycle.id}).can_request_work_unit,
            f'Unexpected units {units.ids}; parent {supervisor.parent_id.id}; '
            f'unit manager {self.unit_a.manager_id.id}; '
            f'department manager {self.department_a.manager_id.id}')
        with self.assertRaises(ValidationError):
            Entry.create({
                'cycle_id': self.cycle.id, 'request_level': 'work_unit',
                'department_id': self.department_a.id, 'work_unit_id': self.unit_a.id,
                'course_id': self.courses.id,
                'work_unit_employee_ids': [(6, 0, [supervisor.id])],
                'justification': 'A supervisor should not represent the whole unit.',
            })

    def test_cyclic_ancestor_does_not_stall_scope_lookup(self):
        root = self.env['hr.employee'].create({
            'name': 'EDS Legacy Root',
            'department_id': self.department_b.id,
            'default_operating_unit_id': self.unit_c.id,
        })
        self.leader.parent_id = root
        # Legacy HR imports can contain a self-parent link. Bypass the ORM's
        # new-record cycle protection to reproduce that existing data shape.
        self.env.cr.execute(
            'UPDATE hr_employee SET parent_id = id WHERE id = %s', [root.id])
        self.env.invalidate_all()
        units, _departments = self.env['eds.hr.compat'].with_user(
            self.leader_user).get_managed_training_scope()
        self.assertIn(self.unit_a, units)
        self.assertNotIn(self.unit_c, units)
