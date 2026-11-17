# -*- coding: utf-8 -*-
"""Future-cycle rater sampling rules, independent of employee data."""

from collections import Counter
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged

from ..models import competency_assessment as assessment_module
from ..models.assessment_matching import allocate_balanced_assessments


@tagged('post_install', '-at_install', 'competency_assessment_matching')
class TestAssessmentMatching(TransactionCase):

    def setUp(self):
        super().setUp()
        # An unrelated HR create hook expects a res.groups.users field absent
        # from this database. It is irrelevant to rater matching and must not
        # send real employee notifications from these isolated fixtures.
        notification_patch = patch.object(
            type(self.env['hr.employee']),
            '_notify_pomd_manager_on_creation',
            return_value=None,
        )
        notification_patch.start()
        self.addCleanup(notification_patch.stop)

    def _create_new_cap_cycle(self):
        suffix = uuid4().hex[:12]
        today = fields.Date.today()
        self.env['competency.matrix.config'].sudo().get_active_config().write({
            'max_peer_assessments': 2,
            'max_subordinate_assessments': 2,
        })
        coach = self.env['hr.employee'].sudo().create({
            'name': 'Cap Matching Coach ' + suffix,
            'company_id': self.env.company.id,
        })
        employee_group = self.env.ref('competency_management.group_competency_employee')
        admin_group = self.env.ref('competency_management.group_competency_admin')
        internal_group = self.env.ref('base.group_user')
        Users = self.env['res.users'].with_context(no_reset_password=True)
        admin = Users.create({
            'name': 'Cap Matching Administrator ' + suffix,
            'login': 'cap_matching_admin_' + suffix,
            'group_ids': [(6, 0, [internal_group.id, admin_group.id])],
        })
        employees = []
        for index in range(4):
            user = Users.create({
                'name': 'Cap Matching Assessor %s %s' % (index, suffix),
                'login': 'cap_matching_%s_%s' % (index, suffix),
                'group_ids': [(6, 0, [internal_group.id, employee_group.id])],
            })
            employees.append(self.env['hr.employee'].sudo().create({
                'name': 'Cap Matching Employee %s %s' % (index, suffix),
                'coach_id': coach.id,
                'parent_id': coach.id,
                'user_id': user.id,
                'company_id': self.env.company.id,
            }))
        employee_ids = [employee.id for employee in employees]
        cycle = self.env['competency.assessment.cycle'].sudo().create({
            'name': 'Cap Matching Cycle ' + suffix,
            'period_start': today,
            'assessment_deadline': today + timedelta(days=30),
            'is_targeted': True,
            'target_type': 'employee',
            'target_employee_ids': [(6, 0, employee_ids)],
        })
        cycle.with_context(force_write=True, freeze_cycle_scope=True).write({
            'scoped_employee_ids': [(6, 0, employee_ids)],
            'state': 'open',
        })
        return cycle, employees, admin

    def test_peer_group_with_enough_members_is_balanced_both_ways(self):
        # Employee ids and their linked user ids deliberately differ.
        candidates = {
            1: (102, 103, 104),
            2: (101, 103, 104),
            3: (101, 102, 104),
            4: (101, 102, 103),
        }
        assignments = allocate_balanced_assessments(candidates, 2)

        self.assertEqual(len(assignments), 8)
        self.assertEqual(Counter(target for target, _assessor in assignments),
                         {1: 2, 2: 2, 3: 2, 4: 2})
        self.assertEqual(Counter(assessor for _target, assessor in assignments),
                         {101: 2, 102: 2, 103: 2, 104: 2})
        self.assertEqual(len(assignments), len(set(assignments)))
        for target, assessor in assignments:
            self.assertIn(assessor, candidates[target])

    def test_small_peer_group_uses_every_eligible_peer(self):
        assignments = allocate_balanced_assessments({1: [102], 2: [101]}, 2)

        self.assertEqual(set(assignments), {(1, 102), (2, 101)})

    def test_overlapping_subordinate_paths_do_not_double_assign_a_target(self):
        # The same assessor can qualify through the teammate and coach paths.
        candidates = {1: [101, 101, 102, 102], 2: [101, 102]}
        assignments = allocate_balanced_assessments(candidates, 2)

        self.assertEqual(len(assignments), 4)
        self.assertEqual(Counter(target for target, _assessor in assignments),
                         {1: 2, 2: 2})
        self.assertEqual(len(assignments), len(set(assignments)))

    def test_target_coverage_wins_when_one_assessor_is_the_only_option(self):
        candidates = {target: [101] for target in range(1, 6)}
        assignments = allocate_balanced_assessments(candidates, 2)

        self.assertEqual(len(assignments), 5)
        self.assertEqual({target for target, _assessor in assignments}, set(candidates))
        self.assertEqual({assessor for _target, assessor in assignments}, {101})

    def test_existing_assignments_count_toward_limit_and_are_not_recreated(self):
        candidates = {1: [101, 102, 103], 2: [101, 102, 103]}
        existing = {(1, 101), (1, 102), (2, 101)}
        assignments = allocate_balanced_assessments(candidates, 2, existing)

        self.assertEqual(len(assignments), 1)
        self.assertEqual(assignments[0][0], 2)
        self.assertNotIn(assignments[0], existing)
        self.assertEqual(
            allocate_balanced_assessments(candidates, 2, existing | set(assignments)),
            [],
        )

    def test_preexisting_over_limit_target_is_left_untouched(self):
        candidates = {1: [101, 102, 103]}
        existing = {(1, 101), (1, 102), (1, 103)}

        self.assertEqual(allocate_balanced_assessments(candidates, 2, existing), [])

    def test_new_cycle_generates_two_peer_raters_and_assignments_each(self):
        suffix = uuid4().hex[:12]
        today = fields.Date.today()
        self.env['competency.matrix.config'].sudo().get_active_config().write({
            'max_peer_assessments': 2,
        })
        coach = self.env['hr.employee'].sudo().create({
            'name': 'Peer Matching Coach ' + suffix,
            'company_id': self.env.company.id,
        })
        employee_group = self.env.ref('competency_management.group_competency_employee')
        internal_group = self.env.ref('base.group_user')
        Users = self.env['res.users'].with_context(no_reset_password=True)
        employees = self.env['hr.employee'].sudo()
        user_ids = set()
        for index in range(4):
            user = Users.create({
                'name': 'Peer Matching Assessor %s %s' % (index, suffix),
                'login': 'peer_matching_%s_%s' % (index, suffix),
                'group_ids': [(6, 0, [internal_group.id, employee_group.id])],
            })
            employee = self.env['hr.employee'].sudo().create({
                'name': 'Peer Matching Employee %s %s' % (index, suffix),
                'coach_id': coach.id,
                'parent_id': coach.id,
                'user_id': user.id,
                'company_id': self.env.company.id,
            })
            employees |= employee
            user_ids.add(user.id)

        cycle = self.env['competency.assessment.cycle'].sudo().create({
            'name': 'Peer Matching Cycle ' + suffix,
            'period_start': today,
            'assessment_deadline': today + timedelta(days=30),
            'is_targeted': True,
            'target_type': 'employee',
            'target_employee_ids': [(6, 0, employees.ids)],
        })
        cycle.with_context(force_write=True, freeze_cycle_scope=True).write({
            'scoped_employee_ids': [(6, 0, employees.ids)],
            'state': 'open',
        })

        EmployeeModel = type(self.env['hr.employee'])
        original_search = EmployeeModel.search
        active_pool = coach | employees

        def small_employee_pool(records, domain, *args, **kwargs):
            if domain == [('active', '=', True)]:
                return active_pool
            return original_search(records, domain, *args, **kwargs)

        # Generation commits chunks in production. Suppress those commits so
        # TransactionCase can roll back every record created here.
        with patch.object(EmployeeModel, 'search', small_employee_pool), \
                patch.object(self.env.cr, 'commit', return_value=None):
            cycle._generate_cycle_assessments_batch()
            cycle._generate_cycle_assessments_batch()

        assessments = self.env['competency.assessment'].sudo().search([
            ('cycle_id', '=', cycle.id),
            ('assessment_type', '=', 'peer'),
        ])
        self.assertEqual(len(assessments), 8)
        self.assertEqual(set(assessments.mapped('employee_id').ids), set(employees.ids))
        self.assertEqual(set(assessments.mapped('assessor_id').ids), user_ids)
        self.assertEqual(set(Counter(record.employee_id.id for record in assessments).values()), {2})
        self.assertEqual(set(Counter(record.assessor_id.id for record in assessments).values()), {2})

    def test_subordinate_routes_share_one_target_limit(self):
        cycle, employees, _admin = self._create_new_cap_cycle()
        manager, teammate_one, teammate_two, direct_report = employees
        grand_coach = manager.coach_id
        direct_report.sudo().write({
            'coach_id': manager.id,
            'parent_id': manager.id,
        })
        EmployeeModel = type(self.env['hr.employee'])
        PeerConfigModel = type(self.env['competency.director.peer.config'])
        original_search = EmployeeModel.search
        active_pool = grand_coach | manager | teammate_one | teammate_two | direct_report

        def small_employee_pool(records, domain, *args, **kwargs):
            if domain == [('active', '=', True)]:
                return active_pool
            return original_search(records, domain, *args, **kwargs)

        def grade_number(_config, employee):
            if employee.id == manager.id:
                return 2
            if employee.id in (teammate_one.id, teammate_two.id, direct_report.id):
                return 1
            return 0

        candidate_maps = []

        def recording_allocator(candidate_map, limit, existing_pairs=()):
            candidate_maps.append({target: set(raters) for target, raters in candidate_map.items()})
            return allocate_balanced_assessments(candidate_map, limit, existing_pairs)

        with patch.object(EmployeeModel, 'search', small_employee_pool), \
                patch.object(PeerConfigModel, '_get_grade_number', grade_number), \
                patch.object(assessment_module, 'allocate_balanced_assessments', recording_allocator), \
                patch.object(self.env.cr, 'commit', return_value=None):
            cycle._generate_cycle_assessments_batch()

        manager_subordinate_assessments = self.env['competency.assessment'].sudo().search([
            ('cycle_id', '=', cycle.id),
            ('employee_id', '=', manager.id),
            ('assessment_type', '=', 'subordinate'),
        ])
        self.assertEqual(len(manager_subordinate_assessments), 2)
        self.assertEqual(len(set(manager_subordinate_assessments.mapped('assessor_id').ids)), 2)
        eligible = {
            teammate_one.user_id.id,
            teammate_two.user_id.id,
            direct_report.user_id.id,
        }
        self.assertTrue(any(candidates.get(manager.id) == eligible for candidates in candidate_maps))
        self.assertTrue(set(manager_subordinate_assessments.mapped('assessor_id').ids) <= eligible)

    def test_new_cycle_rejects_third_peer_or_subordinate_rater(self):
        cycle, employees, admin = self._create_new_cap_cycle()
        Assessment = self.env['competency.assessment'].with_user(admin)
        for assessment_type, target in (('peer', employees[0]), ('subordinate', employees[1])):
            with self.subTest(assessment_type=assessment_type):
                assessors = [employee.user_id.id for employee in employees if employee != target]
                for assessor_id in assessors[:2]:
                    Assessment.create({
                        'cycle_id': cycle.id,
                        'employee_id': target.id,
                        'assessor_id': assessor_id,
                        'assessment_type': assessment_type,
                    })
                with self.assertRaises(ValidationError):
                    with self.env.cr.savepoint():
                        Assessment.create({
                            'cycle_id': cycle.id,
                            'employee_id': target.id,
                            'assessor_id': assessors[2],
                            'assessment_type': assessment_type,
                        })
                self.assertEqual(self.env['competency.assessment'].sudo().search_count([
                    ('cycle_id', '=', cycle.id),
                    ('employee_id', '=', target.id),
                    ('assessment_type', '=', assessment_type),
                ]), 2)

    def test_new_cycle_rejects_batch_that_would_exceed_target_limit(self):
        cycle, employees, admin = self._create_new_cap_cycle()
        target = employees[0]
        assessor_ids = [employee.user_id.id for employee in employees[1:]]
        Assessment = self.env['competency.assessment'].with_user(admin)
        with self.assertRaises(ValidationError):
            with self.env.cr.savepoint():
                Assessment.create([{
                    'cycle_id': cycle.id,
                    'employee_id': target.id,
                    'assessor_id': assessor_id,
                    'assessment_type': 'peer',
                } for assessor_id in assessor_ids])
        self.assertFalse(self.env['competency.assessment'].sudo().search([
            ('cycle_id', '=', cycle.id),
            ('employee_id', '=', target.id),
            ('assessment_type', '=', 'peer'),
        ]))

    def test_direct_create_rejects_duplicate_peer_pair_with_free_slot(self):
        cycle, employees, admin = self._create_new_cap_cycle()
        target, assessor = employees[:2]
        Assessment = self.env['competency.assessment'].with_user(admin)
        pair = {
            'cycle_id': cycle.id,
            'employee_id': target.id,
            'assessor_id': assessor.user_id.id,
            'assessment_type': 'peer',
        }
        Assessment.create(pair.copy())

        with self.assertRaises(ValidationError):
            with self.env.cr.savepoint():
                Assessment.create(pair.copy())

        self.assertEqual(self.env['competency.assessment'].sudo().search_count([
            ('cycle_id', '=', cycle.id),
            ('employee_id', '=', target.id),
            ('assessment_type', '=', 'peer'),
        ]), 1)

    def test_assessor_change_rejects_duplicate_peer_pair_with_free_slot(self):
        cycle, employees, admin = self._create_new_cap_cycle()
        self.env['competency.matrix.config'].sudo().get_active_config().write({
            'max_peer_assessments': 3,
        })
        target = employees[0]
        Assessment = self.env['competency.assessment'].with_user(admin)
        first = Assessment.create({
            'cycle_id': cycle.id,
            'employee_id': target.id,
            'assessor_id': employees[1].user_id.id,
            'assessment_type': 'peer',
        })
        second = Assessment.create({
            'cycle_id': cycle.id,
            'employee_id': target.id,
            'assessor_id': employees[2].user_id.id,
            'assessment_type': 'peer',
        })

        with self.assertRaises(ValidationError):
            with self.env.cr.savepoint():
                second.write({'assessor_id': first.assessor_id.id})

        self.assertEqual(second.assessor_id.id, employees[2].user_id.id)
        self.assertEqual(self.env['competency.assessment'].sudo().search_count([
            ('cycle_id', '=', cycle.id),
            ('employee_id', '=', target.id),
            ('assessment_type', '=', 'peer'),
        ]), 2)

    def test_reassignment_cannot_overfill_target_but_assessor_swap_is_allowed(self):
        cycle, employees, admin = self._create_new_cap_cycle()
        Assessment = self.env['competency.assessment'].with_user(admin)
        target, second_target = employees[:2]
        first = Assessment.create({
            'cycle_id': cycle.id,
            'employee_id': target.id,
            'assessor_id': employees[1].user_id.id,
            'assessment_type': 'peer',
        })
        Assessment.create({
            'cycle_id': cycle.id,
            'employee_id': target.id,
            'assessor_id': employees[2].user_id.id,
            'assessment_type': 'peer',
        })
        other = Assessment.create({
            'cycle_id': cycle.id,
            'employee_id': second_target.id,
            'assessor_id': employees[3].user_id.id,
            'assessment_type': 'peer',
        })

        with self.assertRaises(ValidationError):
            with self.env.cr.savepoint():
                other.write({'employee_id': target.id})
        self.assertEqual(other.employee_id.id, second_target.id)

        first.write({'assessor_id': employees[3].user_id.id})
        self.assertEqual(first.assessor_id.id, employees[3].user_id.id)
        self.assertEqual(self.env['competency.assessment'].sudo().search_count([
            ('cycle_id', '=', cycle.id),
            ('employee_id', '=', target.id),
            ('assessment_type', '=', 'peer'),
        ]), 2)

    def test_director_peer_sync_respects_existing_target_cap(self):
        cycle, employees, admin = self._create_new_cap_cycle()
        director, target = employees[:2]
        Assessment = self.env['competency.assessment'].with_user(admin)
        for assessor in employees[2:]:
            Assessment.create({
                'cycle_id': cycle.id,
                'employee_id': target.id,
                'assessor_id': assessor.user_id.id,
                'assessment_type': 'peer',
            })
        # This test exercises synchronization, not HR title classification.
        # Mark the fixture employee as eligible only while creating the config.
        DirectorConfigModel = type(self.env['competency.director.peer.config'])
        with patch.object(DirectorConfigModel, '_is_director_or_chief', return_value=True):
            peer_config = self.env['competency.director.peer.config'].sudo().create({
                'director_id': director.id,
                'peer_ids': [(6, 0, [target.id])],
            })

        added, _removed, _preserved = peer_config._sync_peer_assessments_for_cycle(cycle)

        self.assertEqual(added, 0)
        self.assertEqual(self.env['competency.assessment'].sudo().search_count([
            ('cycle_id', '=', cycle.id),
            ('employee_id', '=', target.id),
            ('assessment_type', '=', 'peer'),
        ]), 2)
