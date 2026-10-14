# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'eds')
class TestEdsNavigationAndApproval(TransactionCase):

    def test_eds_course_syncs_to_lms_once(self):
        if not self.env.registry.get('lms.course'):
            self.skipTest('LMS is optional and is not installed')
        manager_group = self.env.ref('employee_development_system.group_eds_manager')
        internal_group = self.env.ref('base.group_user')
        owner = self.env['res.users'].with_context(
            no_reset_password=True, mail_create_nosubscribe=True,
        ).create({
            'name': 'EDS LMS Course Owner', 'login': 'eds_lms_course_owner',
            'group_ids': [(6, 0, [internal_group.id, manager_group.id])],
        })
        self.env['hr.employee'].create({
            'name': 'EDS LMS Course Owner', 'user_id': owner.id,
        })
        course = self.env['eds.course'].with_user(owner).create({
            'name': 'EDS LMS Integration Course', 'duration_days': 2,
            'description': 'Learning content assigned from EDS.',
        })
        routing = self.env['eds.lms.routing'].create({
            'course_id': course.id, 'delivery_mode': 'e_learning',
        })
        routing.with_user(owner).action_sync_to_lms()
        self.assertEqual(routing.sync_state, 'synced', routing.sync_error)
        first_lms_id = int(routing.lms_ref)
        lms_course = self.env['lms.course'].sudo().browse(first_lms_id)
        self.assertEqual(lms_course.name, course.name)
        self.assertEqual(lms_course.estimated_duration_hours, 16)

        routing.with_user(owner).action_sync_to_lms()
        self.assertEqual(routing.sync_state, 'synced', routing.sync_error)
        self.assertEqual(int(routing.lms_ref), first_lms_id)

    def test_active_menu_actions_resolve_and_views_load(self):
        menu_ids = self.env['ir.model.data'].search([
            ('module', '=', 'employee_development_system'),
            ('model', '=', 'ir.ui.menu'),
        ]).mapped('res_id')
        menus = self.env['ir.ui.menu'].browse(menu_ids).filtered('active')
        self.assertTrue(menus)
        for menu in menus:
            if not menu.action:
                continue
            with self.subTest(menu=menu.name):
                action = menu.action
                self.assertTrue(action.exists())
                if action._name == 'ir.actions.act_window':
                    self.assertIn(action.res_model, self.env.registry.models)
                    view_modes = action.view_mode.split(',')
                    self.env[action.res_model].get_views(
                        [(False, mode) for mode in view_modes],
                        options={'toolbar': False},
                    )

    def test_single_navigation_path_and_scoped_register(self):
        ref = self.env.ref
        root = ref('employee_development_system.menu_eds_root')
        planning = ref('employee_development_system.menu_eds_planning')
        delivery = ref('employee_development_system.menu_eds_delivery')
        setup = ref('employee_development_system.menu_eds_configuration_root')
        self.assertEqual(ref('employee_development_system.menu_eds_curricula_root').parent_id, planning)
        self.assertEqual(ref('employee_development_system.menu_eds_unscheduled_requests').parent_id, planning)
        self.assertEqual(ref('employee_development_system.menu_eds_evaluations_root').parent_id, delivery)
        self.assertEqual(ref('employee_development_system.menu_eds_template_import').parent_id, setup)
        self.assertEqual(ref('employee_development_system.menu_eds_provider_appraisals').parent_id, delivery)
        for xml_id in (
            'menu_eds_dashboard', 'menu_eds_tna_consolidations',
            'menu_eds_delivery_certificates', 'menu_eds_my_certificates_delivery',
        ):
            self.assertFalse(ref('employee_development_system.' + xml_id).active)
        self.assertEqual(len(root.child_id.filtered('active')), 5)

        cycle = self.env['eds.tna.cycle'].create({'year': '2026'})
        action = cycle.action_view_consolidations()
        self.assertEqual(action['res_model'], 'eds.tna.consolidation')
        self.assertEqual(action['domain'], [('cycle_id', '=', cycle.id)])
        self.assertEqual(action['context']['default_cycle_id'], cycle.id)

        course = self.env['eds.course'].create({'name': 'Scoped Course Navigation'})
        for method, model in (
            ('action_view_curriculums', 'eds.curriculum'),
            ('action_view_development_requests', 'eds.course.development.request'),
        ):
            scoped_action = getattr(course, method)()
            self.assertEqual(scoped_action['res_model'], model)
            self.assertEqual(scoped_action['domain'], [('course_id', '=', course.id)])
            self.assertEqual(scoped_action['context']['default_course_id'], course.id)

    def test_cycle_approval_follows_consolidation_and_skips_screened_needs(self):
        cycle = self.env['eds.tna.cycle'].create({
            'year': '2026', 'state': 'collecting',
        })
        employee = self.env['hr.employee'].create({'name': 'EDS Approval Trainee'})
        screened_employee = self.env['hr.employee'].create({'name': 'EDS Screened Trainee'})
        need = self.env['eds.tna.entry'].create({
            'cycle_id': cycle.id, 'employee_id': employee.id,
            'proposed_program': 'Operations Training',
            'justification': 'Required for the role', 'state': 'submitted',
        })
        screened = self.env['eds.tna.entry'].create({
            'cycle_id': cycle.id, 'employee_id': screened_employee.id,
            'proposed_program': 'Process Revision',
            'justification': 'This is a process change', 'state': 'submitted',
            'exclusion_type': 'process',
        })
        cycle.action_finish_collection()
        with self.assertRaises(UserError):
            cycle.action_submit_for_approval()

        consolidation = self.env['eds.tna.consolidation'].create({'cycle_id': cycle.id})
        consolidation.action_consolidate()
        self.assertIn(need, consolidation.entry_ids)
        self.assertIn(screened, consolidation.entry_ids)
        cycle.action_submit_for_approval()
        with self.assertRaises(UserError):
            cycle.action_approve()

        manager_group = self.env.ref('employee_development_system.group_eds_manager')
        internal_group = self.env.ref('base.group_user')
        reviewers = []
        for step in range(4):
            reviewers.append(self.env['res.users'].with_context(
                no_reset_password=True, mail_create_nosubscribe=True,
            ).create({
                'name': 'EDS Approval Reviewer %d' % step,
                'login': 'eds_approval_reviewer_%d' % step,
                'group_ids': [(6, 0, [internal_group.id, manager_group.id])],
            }))
        consolidation.action_submit_ppdd()
        consolidation.with_user(reviewers[0]).action_validate_ppdd()
        consolidation.with_user(reviewers[1]).action_director_review()
        consolidation.with_user(reviewers[2]).action_cpco_endorsement()
        with self.assertRaises(UserError):
            consolidation.with_user(reviewers[3]).action_smc_approve()
        screened.write({
            'state': 'excluded',
            'excluded_reason': 'Process revision does not require a training course.',
        })
        consolidation.with_user(reviewers[3]).action_smc_approve()
        self.assertEqual(consolidation.state, 'approved')
        self.assertEqual(cycle.state, 'approved')
        self.assertEqual(need.state, 'approved')
        self.assertEqual(screened.state, 'excluded')
