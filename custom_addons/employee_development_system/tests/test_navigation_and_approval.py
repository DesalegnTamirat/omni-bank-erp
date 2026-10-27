# -*- coding: utf-8 -*-
import base64
from datetime import date
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'eds')
class TestEdsNavigationAndApproval(TransactionCase):

    def test_session_course_follows_approved_source(self):
        course = self.env['eds.course'].sudo().create({'name': 'Session source catalog course'})
        other = self.env['eds.course'].sudo().create({'name': 'Unrelated catalog course'})
        plan = self.env['eds.annual.plan'].sudo().create({'fiscal_year': '2197'})
        line = self.env['eds.annual.plan.line'].sudo().create({
            'plan_id': plan.id, 'course_id': course.id,
            'planned_participants': 1, 'duration_days': 1,
        })
        session = self.env['eds.session'].sudo().create({
            'plan_line_id': line.id, 'course_id': other.id,
            'date_start': '2197-07-01 08:00:00',
            'date_end': '2197-07-01 16:00:00',
        })
        self.assertEqual(session.source_type, 'annual_plan')
        self.assertEqual(session.approved_plan_id, plan)
        self.assertEqual(session.course_id, course)
        self.assertEqual(session.program_name, course.name)
        with self.assertRaisesRegex(UserError, 'approved annual plan'):
            session.action_confirm()
        plan.write({'state': 'published'})
        session.write({'course_id': other.id})
        with self.assertRaisesRegex(UserError, 'must match the approved source'):
            session.action_confirm()

        request = self.env['eds.unscheduled.request'].sudo().create({
            'course_id': other.id, 'justification': 'Operational deadline',
            'state': 'approved',
        })
        direct = self.env['eds.session'].sudo().create({
            'unscheduled_request_id': request.id,
            'date_start': '2197-08-01 08:00:00',
            'date_end': '2197-08-01 16:00:00',
        })
        self.assertEqual(direct.source_type, 'unscheduled')
        self.assertEqual(direct.course_id, other)
        self.assertEqual(direct.program_name, other.name)
        request.write({'state': 'submitted'})
        with self.assertRaisesRegex(UserError, 'approved unscheduled training request'):
            direct.action_confirm()

        addendum_plan = self.env['eds.annual.plan'].sudo().create({
            'fiscal_year': '2196',
        })
        addendum_request = self.env['eds.unscheduled.request'].sudo().create({
            'annual_plan_id': addendum_plan.id,
            'course_id': other.id,
            'justification': 'Additional training required',
            'state': 'approved',
        })
        addendum_request._append_addendum()
        self.assertEqual(addendum_request.plan_line_ids.course_id, other)
        self.assertEqual(addendum_request.plan_line_ids.session_ids.source_type, 'unscheduled')
        self.assertEqual(addendum_request.plan_line_ids.session_ids.unscheduled_request_id,
                         addendum_request)

    def test_unscheduled_sourcing_without_annual_plan(self):
        course = self.env['eds.course'].sudo().create({'name': 'Unplanned sourcing course'})
        request = self.env['eds.unscheduled.request'].sudo().create({
            'course_id': course.id, 'justification': 'Urgent operational training',
            'delivery_method': 'local_external', 'state': 'approved',
        })
        self.assertFalse(request.plan_line_ids)
        provider = self.env['eds.external.provider'].sudo().create({
            'name': 'Unplanned training provider', 'category': 'local',
        })
        trainer = self.env['eds.trainer'].sudo().create({
            'name': 'Unplanned external trainer', 'trainer_type': 'external',
            'external_provider_id': provider.id,
        })
        vendor_selection = self.env['eds.course.vendor.selection'].sudo().create({
            'source_type': 'unscheduled', 'unscheduled_request_id': request.id,
        })
        self.assertEqual(vendor_selection.course_id, course)
        self.assertFalse(vendor_selection.plan_line_id)
        winning_vendor = self.env['eds.course.vendor.line'].sudo().create({
            'selection_id': vendor_selection.id, 'vendor_id': provider.id,
            'trainer_id': trainer.id, 'price_quoted': 100,
            'quality_score': 8, 'experience_score': 8,
            'scalability_score': 8, 'demo_score': 8, 'price_score': 8,
        })
        vendor_selection.action_start_evaluation()
        winning_vendor.action_award()
        vendor_selection.action_mark_awarded()

        venue = self.env['eds.venue'].sudo().create({
            'name': 'Unplanned training hotel', 'venue_type': 'hotel',
        })
        hotel_selection = self.env['eds.hotel.selection'].sudo().create({
            'source_type': 'unscheduled', 'unscheduled_request_id': request.id,
        })
        self.assertEqual(hotel_selection.program_name, course.name)
        winning_hotel = self.env['eds.hotel.bid'].sudo().create({
            'selection_id': hotel_selection.id, 'venue_id': venue.id,
            'price_quoted': 100, 'technical_score': 8,
            'award_attachment': base64.b64encode(b'award letter'),
        })
        hotel_selection.action_start_evaluation()
        winning_hotel.action_award()
        session = self.env['eds.session'].sudo().create({
            'unscheduled_request_id': request.id,
            'date_start': '2197-08-01 08:00:00',
            'date_end': '2197-08-01 16:00:00',
        })
        self.assertEqual(session.awarded_provider_id, provider)
        self.assertEqual(session.awarded_venue_id, venue)
        self.assertEqual(session.venue_id, venue)
        # The provider is sourced; HR chooses an eligible trainer from it.
        session.trainer_ids = trainer
        self.assertIn(trainer, session.trainer_ids)

    def test_delivery_override_and_session_internal_fallback(self):
        course = self.env['eds.course'].sudo().create({'name': 'Delivery decision course'})
        plan = self.env['eds.annual.plan'].sudo().create({
            'fiscal_year': '2198', 'state': 'published',
        })
        sourced_line = self.env['eds.annual.plan.line'].sudo().create({
            'plan_id': plan.id, 'course_id': course.id,
            'delivery_method': 'local_external',
        })
        selection = self.env['eds.course.vendor.selection'].sudo().create({
            'annual_plan_id': plan.id, 'plan_line_id': sourced_line.id,
        })
        self.assertEqual(selection.delivery_method, 'local_external')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            selection.write({'delivery_method': 'internal'})
        selection.write({
            'delivery_override': True, 'delivery_method': 'internal',
            'delivery_change_reason': 'Internal trainer is now available',
        })
        selection.action_mark_awarded()
        self.assertEqual(selection.state, 'awarded')

        fallback_line = self.env['eds.annual.plan.line'].sudo().create({
            'plan_id': plan.id, 'course_id': course.id,
            'delivery_method': 'local_external',
        })
        session = self.env['eds.session'].sudo().create({
            'plan_line_id': fallback_line.id,
            'date_start': '2198-08-01 08:00:00',
            'date_end': '2198-08-01 16:00:00',
        })
        session.write({'internal_fallback': True})
        self.assertEqual(session.delivery_method, 'internal')
        with self.assertRaisesRegex(UserError, 'Explain why'):
            session.action_confirm()

    def test_external_provider_location(self):
        country = self.env['res.country'].search([], limit=1)
        provider_model = self.env['eds.external.provider'].sudo()
        local = provider_model.create({
            'name': 'Local provider location test', 'category': 'local',
            'city': 'Addis Ababa', 'country_id': country.id,
            'accreditation': 'Professional training license',
        })
        self.assertFalse(local.country_id)
        self.assertEqual(local.city, 'Addis Ababa')
        self.assertNotIn('partner_id', provider_model._fields)
        self.assertEqual(local.accreditation, 'Professional training license')
        with self.assertRaises(ValidationError):
            local.write({'country_id': country.id})
        international = provider_model.create({
            'name': 'International provider location test',
            'category': 'international', 'country_id': country.id,
            'city': 'Nairobi',
        })
        self.assertEqual(international.country_id, country)
        self.assertEqual(international.city, 'Nairobi')
        international.write({'category': 'local'})
        self.assertFalse(international.country_id)
        self.assertEqual(international.city, 'Nairobi')

    def test_venue_country_only_for_international(self):
        country = self.env['res.country'].search([], limit=1)
        venues = self.env['eds.venue']
        local = venues.create({
            'name': 'Local training room', 'location_scope': 'local',
            'country_id': country.id,
        })
        self.assertFalse(local.country_id)
        with self.assertRaises(ValidationError):
            local.write({'country_id': country.id})
        with self.assertRaises(ValidationError):
            venues.create({'name': 'International venue without country',
                           'location_scope': 'international'})
        international = venues.create({
            'name': 'International conference room',
            'location_scope': 'international', 'country_id': country.id,
        })
        self.assertEqual(international.country_id, country)
        international.write({'location_scope': 'local'})
        self.assertFalse(international.country_id)

    def test_mark_reviewed_uses_today_for_both_trainer_types(self):
        officer_group = self.env.ref('employee_development_system.group_eds_officer')
        employee_group = self.env.ref('employee_development_system.group_eds_employee')
        internal_group = self.env.ref('base.group_user')
        officer = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'EDS Trainer Review Officer', 'login': 'eds_trainer_review_officer_test',
            'group_ids': [(6, 0, [internal_group.id, officer_group.id])],
        })
        employee = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'EDS Trainer Review Employee', 'login': 'eds_trainer_review_employee_test',
            'group_ids': [(6, 0, [internal_group.id, employee_group.id])],
        })
        trainers = self.env['eds.trainer'].sudo().create([
            {'name': 'Internal review test', 'trainer_type': 'internal'},
            {'name': 'External review test', 'trainer_type': 'external'},
        ])
        with self.assertRaises(AccessError):
            trainers[0].with_user(employee).action_mark_reviewed()
        trainers.with_user(officer).action_mark_reviewed()
        today = fields.Date.context_today(trainers.with_user(officer))
        for trainer in trainers:
            self.assertEqual(trainer.last_review_date, today)
            self.assertFalse(trainer.quarterly_review_ids)

    def test_annual_plan_reviews_route_to_every_stage_role_member(self):
        # The shared local database already has an official plan for the real
        # current year. Treat a future year as "today" only inside this test.
        date_patch = patch.object(fields.Date, 'context_today', return_value=date(2199, 1, 1))
        date_patch.start()
        self.addCleanup(date_patch.stop)
        internal = self.env.ref('base.group_user')
        roles = {
            'creator': 'group_eds_officer',
            'checker_one': 'group_eds_team_leader',
            'checker_two': 'group_eds_team_leader',
            'director_one': 'group_eds_director',
            'director_two': 'group_eds_director',
            'chief_one': 'group_eds_chief',
            'chief_two': 'group_eds_chief',
        }
        users = {}
        for key, role_xml_id in roles.items():
            group = self.env.ref('employee_development_system.' + role_xml_id)
            users[key] = self.env['res.users'].with_context(
                no_reset_password=True, mail_create_nosubscribe=True,
            ).create({
                'name': 'EDS Plan Role ' + key,
                'login': 'eds_plan_role_' + key,
                'group_ids': [(6, 0, [internal.id, group.id])],
            })

        Plan = self.env['eds.annual.plan']
        year = str(fields.Date.context_today(Plan).year)
        with self.assertRaises(UserError):
            Plan.with_user(users['creator']).create({'fiscal_year': '2099'})
        plan = Plan.with_user(users['creator']).create({
            'fiscal_year': year,
            'team_leader_id': users['checker_one'].id,
        })
        self.assertEqual(plan.fiscal_year, year)
        self.assertFalse(plan.team_leader_id)
        self.assertFalse(plan.reviewer_id)
        with self.assertRaises(UserError):
            plan.with_user(users['creator']).write({'team_leader_id': users['checker_one'].id})
        with self.assertRaises(UserError):
            plan.with_user(users['creator']).write({'fiscal_year': '2099'})
        course = self.env['eds.course'].sudo().create({'name': 'EDS Role Routing Training'})
        self.env['eds.annual.plan.line'].sudo().create({
            'plan_id': plan.id, 'course_id': course.id,
            'scheduled_date': '2199-01-01',
        })

        self.assertTrue({users['checker_one'].id, users['checker_two'].id}.issubset(
            set(plan._stage_role_users('team_leader').ids)))
        plan.with_user(users['creator']).action_submit_to_team_leader()
        team_notice = self.env['mail.message'].sudo().search([
            ('model', '=', 'eds.annual.plan'), ('res_id', '=', plan.id),
            ('body', 'ilike', 'pending Team Leader review'),
        ], order='id desc', limit=1)
        self.assertTrue(team_notice)
        self.assertTrue({users['checker_one'].partner_id.id,
                         users['checker_two'].partner_id.id}.issubset(set(team_notice.partner_ids.ids)))
        self.assertEqual(team_notice.author_id, users['creator'].partner_id)
        self.assertEqual(set(plan.activity_ids.filtered(
            lambda activity: (activity.summary or '').startswith('EDS action:')).mapped('user_id').ids),
            set(plan._stage_role_users('team_leader').ids))
        with self.assertRaises(UserError):
            plan.with_user(users['director_one']).action_team_leader_forward()

        self.env['eds.plan.return.wizard'].with_user(users['checker_one']).create({
            'plan_id': plan.id, 'reason': 'Please revise the first draft.',
        }).action_confirm_return()
        self.assertEqual(plan.state, 'draft')
        self.assertIn(users['creator'], plan.activity_ids.mapped('user_id'))
        plan.with_user(users['creator']).action_submit_to_team_leader()

        plan.with_user(users['checker_one']).write({'review_remarks': 'Budget reviewed.'})
        plan.with_user(users['checker_one']).action_team_leader_forward()
        self.assertEqual(plan.team_leader_id, users['checker_one'])
        self.assertFalse(plan.review_remarks)
        director_notice = self.env['mail.message'].sudo().search([
            ('model', '=', 'eds.annual.plan'), ('res_id', '=', plan.id),
            ('body', 'ilike', 'pending Director PPDD review'),
        ], order='id desc', limit=1)
        self.assertTrue({users['director_one'].partner_id.id,
                         users['director_two'].partner_id.id}.issubset(
                             set(director_notice.partner_ids.ids)))

        self.env['eds.plan.return.wizard'].with_user(users['director_one']).create({
            'plan_id': plan.id, 'reason': 'Please revise the schedule.',
        }).action_confirm_return()
        self.assertEqual(plan.last_return_reason, 'Please revise the schedule.')
        self.assertEqual(plan.reviewer_id, users['director_one'])
        return_notice = self.env['mail.message'].sudo().search([
            ('model', '=', 'eds.annual.plan'), ('res_id', '=', plan.id),
            ('body', 'ilike', 'returned for revision'),
        ], order='id desc', limit=1)
        self.assertIn(users['checker_one'].partner_id, return_notice.partner_ids)
        self.assertNotIn(users['checker_two'].partner_id, return_notice.partner_ids)
        self.assertEqual(return_notice.author_id, users['director_one'].partner_id)
        plan.with_user(users['checker_two']).action_team_leader_forward()
        plan.with_user(users['director_two']).action_director_forward()
        chief_notice = self.env['mail.message'].sudo().search([
            ('model', '=', 'eds.annual.plan'), ('res_id', '=', plan.id),
            ('body', 'ilike', 'requires Chief approval'),
        ], order='id desc', limit=1)
        self.assertTrue({users['chief_one'].partner_id.id,
                         users['chief_two'].partner_id.id}.issubset(
                             set(chief_notice.partner_ids.ids)))
        self.env['eds.plan.return.wizard'].with_user(users['chief_two']).create({
            'plan_id': plan.id, 'reason': 'Please review the budget again.',
        }).action_confirm_return()
        self.assertEqual(plan.state, 'director_review')
        self.assertIn(users['director_two'], plan.activity_ids.mapped('user_id'))
        self.assertNotIn(users['director_one'], plan.activity_ids.mapped('user_id'))
        plan.with_user(users['director_two']).action_director_forward()
        plan.with_user(users['chief_one']).action_chief_approve()
        self.assertEqual(plan.state, 'published')
        self.assertEqual(plan.approver_id, users['chief_one'])
        self.assertTrue(any('Please revise the schedule.' in comment
                            for comment in plan.approval_history_ids.mapped('comment')))
        self.assertFalse(plan.activity_ids.filtered(
            lambda activity: (activity.summary or '').startswith('EDS action:')))

    def test_module_roles_also_control_unplanned_training(self):
        internal = self.env.ref('base.group_user')
        roles = {
            'creator': 'group_eds_officer',
            'manager_only': 'group_eds_manager',
            'team_leader': 'group_eds_team_leader',
            'director': 'group_eds_director',
            'chief': 'group_eds_chief',
        }
        users = {}
        for name, role in roles.items():
            group = self.env.ref('employee_development_system.' + role)
            users[name] = self.env['res.users'].with_context(
                no_reset_password=True, mail_create_nosubscribe=True,
            ).create({
                'name': 'EDS Shared Role ' + name,
                'login': 'eds_shared_role_' + name,
                'group_ids': [(6, 0, [internal.id, group.id])],
            })

        course = self.env['eds.course'].sudo().create({'name': 'Shared Role Training'})
        request = self.env['eds.unscheduled.request'].with_user(users['creator']).create({
            'course_id': course.id,
            'justification': 'Urgent operational need',
        })
        request.with_user(users['creator']).action_submit()
        self.assertTrue(any(
            users['team_leader'].partner_id in message.partner_ids
            for message in request.message_ids
        ))
        with self.assertRaises(UserError):
            request.with_user(users['manager_only']).action_lnd_approve()
        request.with_user(users['team_leader']).action_lnd_approve()
        with self.assertRaises(UserError):
            request.with_user(users['team_leader']).action_director_approve()
        request.with_user(users['director']).action_director_approve()
        with self.assertRaises(UserError):
            request.with_user(users['director']).action_approve()
        request.with_user(users['chief']).action_approve()
        self.assertEqual(request.state, 'approved')

        course = self.env['eds.course'].sudo().create({'name': 'Shared Role Venue Course'})
        venue = self.env['eds.venue.requirement'].with_user(users['creator']).create({
            'course_id': course.id,
            'facilities_required': 'Training room',
        })
        venue.with_user(users['creator']).action_submit()
        with self.assertRaises(UserError):
            venue.with_user(users['manager_only']).action_director_approve()
        venue.with_user(users['director']).action_director_approve()
        self.assertEqual(venue.state, 'director_approved')

    def test_training_currency_policy_and_budget_basis(self):
        etb = self.env['res.currency'].with_context(active_test=False).search([('name', '=', 'ETB')], limit=1)
        usd = self.env['res.currency'].with_context(active_test=False).search([('name', '=', 'USD')], limit=1)
        self.assertTrue(etb and usd)
        self.assertTrue(self.env['eds.annual.plan.line']._fields['budget_allocated'].readonly)
        plan = self.env['eds.annual.plan'].sudo().create({})
        course = self.env['eds.course'].sudo().create({'name': 'Currency Policy Training'})
        foreign_course = self.env['eds.course'].sudo().create({'name': 'International Currency Test'})
        line = self.env['eds.annual.plan.line'].sudo().create({
            'plan_id': plan.id, 'course_id': course.id,
            'delivery_method': 'internal',
        })
        self.assertEqual(line.budget_currency_id, etb)
        with self.assertRaises(ValidationError):
            line.write({'budget_currency_id': usd.id})
        with self.assertRaises(ValidationError):
            self.env['eds.annual.plan.budget.line'].sudo().create({
                'plan_line_id': line.id, 'name': 'Invalid double basis',
                'is_per_employee': True, 'is_general': True,
            })
        line.write({'delivery_method': 'international'})
        self.assertEqual(line.budget_currency_id, usd)
        wizard = self.env['eds.currency.quick.create'].create({'code': 'XZZ'})
        wizard.action_create_currency()
        extra_currency = self.env['res.currency'].search([('name', '=', 'XZZ')], limit=1)
        self.assertTrue(extra_currency)
        line.write({'budget_currency_id': extra_currency.id})
        self.assertEqual(line.budget_currency_id, extra_currency)
        line.write({'delivery_method': 'local_external'})
        self.assertEqual(line.budget_currency_id, etb)
        self.assertIn('ETB', plan.budget_by_currency_html)
        line.write({'manual_budget_allocated': 75.0})
        self.assertEqual(line.budget_allocated_display, f'{etb.symbol or etb.name} 75.00')
        foreign_line = self.env['eds.annual.plan.line'].sudo().create({
            'plan_id': plan.id, 'course_id': foreign_course.id,
            'delivery_method': 'international', 'manual_budget_allocated': 25.0,
        })
        self.assertEqual(foreign_line.budget_currency_id, usd)
        self.assertEqual(foreign_line.budget_allocated_display,
                         f'{usd.symbol or usd.name} 25.00')
        self.assertEqual(dict(plan._get_preview_summary()['currency_totals']), {
            etb: 75.0, usd: 25.0,
        })
        report_html, _ = self.env['ir.actions.report']._render_qweb_html(
            'employee_development_system.action_report_eds_annual_plan_preview', [plan.id])
        self.assertIn(b'Total in ETB', report_html)
        self.assertIn(b'Total in USD', report_html)

        request = self.env['eds.unscheduled.request'].sudo().create({
            'program_name': 'Unplanned International Training',
            'justification': 'Urgent regulatory need',
            'delivery_method': 'international',
        })
        self.assertEqual(request.currency_id, usd)
        request.write({'delivery_method': 'local_external'})
        self.assertEqual(request.currency_id, etb)
        with self.assertRaises(ValidationError):
            request.write({'currency_id': usd.id})

        approved_plan = self.env['eds.annual.plan'].sudo().create({'fiscal_year': '2300'})
        approved_line = self.env['eds.annual.plan.line'].sudo().create({
            'plan_id': approved_plan.id, 'course_id': course.id,
            'delivery_method': 'local_external',
        })
        approved_plan.sudo().write({'state': 'published'})
        with self.assertRaises(ValidationError):
            self.env['eds.hotel.selection'].sudo().create({
                'plan_line_id': approved_line.id, 'currency_id': usd.id,
            })
        hotel_selection = self.env['eds.hotel.selection'].sudo().create({
            'plan_line_id': approved_line.id,
        })
        self.assertEqual(hotel_selection.currency_id, etb)
        with self.assertRaises(ValidationError):
            self.env['eds.course.vendor.selection'].sudo().create({
                'annual_plan_id': approved_plan.id, 'plan_line_id': approved_line.id,
                'currency_id': usd.id,
            })
        vendor_selection = self.env['eds.course.vendor.selection'].sudo().create({
            'annual_plan_id': approved_plan.id, 'plan_line_id': approved_line.id,
        })
        self.assertEqual(vendor_selection.currency_id, etb)
        with self.assertRaises(ValidationError):
            self.env['eds.course.vendor.line'].sudo().create({
                'selection_id': vendor_selection.id, 'vendor_name': 'Local Vendor',
                'currency_id': usd.id,
            })

        with self.assertRaises(ValidationError):
            self.env['eds.external.provider'].sudo().create({
                'name': 'Invalid Local Provider', 'category': 'local',
                'currency_id': usd.id,
            })
        local_provider = self.env['eds.external.provider'].sudo().create({
            'name': 'Local Currency Provider', 'category': 'local',
        })
        self.assertEqual(local_provider.currency_id, etb)
        foreign_provider = self.env['eds.external.provider'].sudo().create({
            'name': 'International Currency Provider', 'category': 'international',
        })
        self.assertEqual(foreign_provider.currency_id, usd)
        contract = self.env['eds.training.contract'].sudo().create({
            'provider_id': local_provider.id,
        })
        self.assertEqual(contract.currency_id, etb)
        with self.assertRaises(ValidationError):
            contract.write({'currency_id': usd.id})
        course = self.env['eds.course'].sudo().create({'name': 'Venue Currency Test'})
        requirement = self.env['eds.venue.requirement'].sudo().create({
            'course_id': course.id,
        })
        self.assertEqual(requirement.currency_id, etb)
        with self.assertRaises(ValidationError):
            requirement.write({'currency_id': usd.id})

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
        self.assertEqual(ref('employee_development_system.menu_eds_curricula_root').parent_id, planning)
        self.assertEqual(ref('employee_development_system.menu_eds_unscheduled_requests').parent_id, planning)
        self.assertEqual(ref('employee_development_system.menu_eds_evaluations_root').parent_id, delivery)
        self.assertFalse(ref('employee_development_system.menu_eds_template_import',
                             raise_if_not_found=False))
        self.assertFalse(ref('employee_development_system.menu_eds_report_tna',
                             raise_if_not_found=False))
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

    def test_cycle_closes_without_consolidation_approval(self):
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
        self.assertEqual(cycle.state, 'closed')
        self.assertEqual(cycle.course_summary_ids.mapped('course_name'), ['Operations Training'])

        consolidation = self.env['eds.tna.consolidation'].create({'cycle_id': cycle.id})
        consolidation.action_consolidate()
        self.assertIn(need, consolidation.entry_ids)
        self.assertIn(screened, consolidation.entry_ids)

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
        self.assertEqual(cycle.state, 'closed')
        self.assertEqual(need.state, 'approved')
        self.assertEqual(screened.state, 'excluded')
