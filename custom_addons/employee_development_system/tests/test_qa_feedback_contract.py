# -*- coding: utf-8 -*-
"""Regression checks for the participant feedback workflow and its access boundary."""

from lxml import etree

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'eds_qa_feedback_contract')
class TestEdsQaFeedbackContract(TransactionCase):

    def setUp(self):
        super().setUp()
        self.instrument = self.env['eds.evaluation.instrument'].create({
            'name': 'QA participant questionnaire',
            'instrument_type': 'level1',
            'question_ids': [
                (0, 0, {'name': 'Rate the course', 'question_type': 'scale_1_5'}),
                (0, 0, {'name': 'Would you recommend it?', 'question_type': 'yes_no'}),
                (0, 0, {'name': 'What should improve?', 'question_type': 'text'}),
            ],
        })
        self.instrument.action_publish()
        self.course = self.env['eds.course'].create({
            'name': 'QA feedback course',
            'level1_instrument_id': self.instrument.id,
        })
        self.session = self.env['eds.session'].create({
            'course_id': self.course.id,
            'date_start': '2098-04-01 09:00:00',
            'date_end': '2098-04-01 17:00:00',
        })
        self.employee = self.env['hr.employee'].create({'name': 'QA feedback employee'})

    def _feedback(self, employee=None, instrument=None):
        return self.env['eds.evaluation.level1'].create({
            'session_id': self.session.id,
            'employee_id': (employee or self.employee).id,
            'instrument_id': (instrument or self.instrument).id,
        })

    def test_draft_generates_questions_once_and_preserves_answers(self):
        feedback = self._feedback()
        self.assertEqual(feedback.state, 'distributed')
        self.assertFalse(feedback.submitted_date)
        self.assertFalse(feedback.line_ids)

        feedback.action_generate_questions()
        self.assertEqual(len(feedback.line_ids), 3)
        rating = feedback.line_ids.filtered(lambda line: line.question_id.question_type == 'scale_1_5')
        rating.rating_val = 4
        original_ids = feedback.line_ids.ids
        feedback.action_generate_questions()
        self.assertEqual(feedback.line_ids.ids, original_ids)
        self.assertEqual(rating.rating_val, 4)

        with self.assertRaises(ValidationError), self.cr.savepoint():
            feedback.action_submit_feedback()
        feedback.line_ids.filtered(lambda line: line.question_id.question_type == 'yes_no').yes_no_val = 'yes'
        feedback.line_ids.filtered(lambda line: line.question_id.question_type == 'text').text_val = 'More examples'
        feedback.action_submit_feedback()
        self.assertEqual(feedback.state, 'submitted')
        self.assertEqual(feedback.submitted_date, fields.Date.context_today(feedback))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            feedback.action_generate_questions()

    def test_unpublished_instrument_and_duplicate_participant_are_rejected(self):
        unpublished = self.instrument.copy({'name': 'QA unpublished questionnaire', 'state': 'draft'})
        feedback = self._feedback(instrument=unpublished)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            feedback.action_generate_questions()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._feedback()

    def test_feedback_ui_disallows_new_and_manual_question_lines(self):
        form = self.env.ref('employee_development_system.view_eds_evaluation_level1_form')
        list_view = self.env.ref('employee_development_system.view_eds_evaluation_level1_tree')
        form_xml = etree.fromstring(form.arch_db.encode())
        list_xml = etree.fromstring(list_view.arch_db.encode())
        self.assertEqual(form_xml.get('create'), 'false')
        self.assertEqual(list_xml.get('create'), 'false')
        self.assertTrue(form_xml.xpath('.//button[@name="action_generate_questions"]'))
        self.assertTrue(form_xml.xpath('.//field[@name="line_ids"]/list[@create="false"][@delete="false"]'))
        for xml_id in ('action_eds_evaluation_level1', 'action_eds_evaluation_level1_own'):
            action = self.env.ref('employee_development_system.' + xml_id)
            self.assertIn("'create': False", action.context)

    def test_employee_reads_only_own_feedback(self):
        internal = self.env.ref('base.group_user')
        users = self.env['res.users'].with_context(no_reset_password=True).create([
            {'name': 'QA Feedback User A', 'login': 'eds_qa_feedback_a', 'group_ids': [(6, 0, [internal.id])]},
            {'name': 'QA Feedback User B', 'login': 'eds_qa_feedback_b', 'group_ids': [(6, 0, [internal.id])]},
        ])
        self.employee.user_id = users[0]
        other_employee = self.env['hr.employee'].create({'name': 'QA feedback other', 'user_id': users[1].id})
        own = self._feedback()
        other = self._feedback(employee=other_employee)
        visible = self.env['eds.evaluation.level1'].with_user(users[0]).search([
            ('id', 'in', [own.id, other.id]),
        ])
        self.assertEqual(visible, own)
        with self.assertRaises(AccessError), self.cr.savepoint():
            other.with_user(users[0]).write({'general_comments': 'Should be denied'})


@tagged('post_install', '-at_install', 'eds_qa_sourcing_domains')
class TestEdsQaSourcingDomains(TransactionCase):

    def setUp(self):
        super().setUp()
        country = self.env['res.country'].search([], limit=1)
        self.local_provider = self.env['eds.external.provider'].create({
            'name': 'QA local provider', 'category': 'local',
        })
        self.international_provider = self.env['eds.external.provider'].create({
            'name': 'QA international provider', 'category': 'international',
            'country_id': country.id,
        })
        self.local_venue = self.env['eds.venue'].create({
            'name': 'QA local venue', 'location_scope': 'local',
        })
        self.international_venue = self.env['eds.venue'].create({
            'name': 'QA international venue', 'location_scope': 'international',
            'country_id': country.id,
        })
        course = self.env['eds.course'].create({'name': 'QA sourcing course'})
        self.request = self.env['eds.unscheduled.request'].create({
            'course_id': course.id,
            'justification': 'Urgent QA sourcing',
            'delivery_method': 'international',
            'state': 'approved',
        })

    def test_provider_category_filters_in_view_and_model(self):
        view = self.env.ref('employee_development_system.view_eds_course_vendor_selection_form')
        arch = etree.fromstring(view.arch_db.encode())
        domains = [field.get('domain') for field in arch.xpath('.//field[@name="vendor_id"]')]
        self.assertTrue(domains)
        self.assertTrue(all('delivery_category' in domain for domain in domains))

        selection = self.env['eds.course.vendor.selection'].create({
            'source_type': 'unscheduled',
            'unscheduled_request_id': self.request.id,
        })
        self.assertEqual(selection.delivery_method, 'international')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['eds.course.vendor.line'].create({
                'selection_id': selection.id, 'vendor_id': self.local_provider.id,
            })
        valid = self.env['eds.course.vendor.line'].create({
            'selection_id': selection.id, 'vendor_id': self.international_provider.id,
        })
        self.assertEqual(valid.vendor_id, self.international_provider)

    def test_hotel_location_filters_in_view_and_model(self):
        view = self.env.ref('employee_development_system.view_eds_hotel_selection_form')
        arch = etree.fromstring(view.arch_db.encode())
        domains = [field.get('domain') for field in arch.xpath('.//field[@name="venue_id"]')]
        self.assertTrue(domains)
        self.assertTrue(all('venue_scope' in domain for domain in domains))

        selection = self.env['eds.hotel.selection'].create({
            'source_type': 'unscheduled',
            'unscheduled_request_id': self.request.id,
        })
        self.assertEqual(selection.delivery_method, 'international')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['eds.hotel.bid'].create({
                'selection_id': selection.id, 'venue_id': self.local_venue.id,
                'price_quoted': 100, 'technical_score': 8,
            })
        valid = self.env['eds.hotel.bid'].create({
            'selection_id': selection.id, 'venue_id': self.international_venue.id,
            'price_quoted': 100, 'technical_score': 8,
        })
        self.assertEqual(valid.venue_id, self.international_venue)
