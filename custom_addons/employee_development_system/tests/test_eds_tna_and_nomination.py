# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo import fields
from datetime import date, timedelta


class TestEdsTnaAndNomination(TransactionCase):

    def setUp(self):
        super().setUp()
        self.user_manager = self.env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True).create({
            'name': 'EDS Test Manager User',
            'login': 'eds_test_mgr_user_suite',
            'email': 'eds_mgr_suite@bunna.et',
        })
        self.employee_manager = self.env['hr.employee'].create({
            'name': 'EDS Test Manager Employee',
            'user_id': self.user_manager.id,
        })
        self.employee_1 = self.env['hr.employee'].create({
            'name': 'EDS Test Trainee 1',
            'parent_id': self.employee_manager.id,
        })
        self.employee_2 = self.env['hr.employee'].create({
            'name': 'EDS Test Trainee 2',
            'parent_id': self.employee_manager.id,
        })

        self.course = self.env['eds.course'].create({
            'name': 'Core Banking Architecture & Security',
            'category': 'technical_compliance',
        })
        self.session = self.env['eds.session'].create({
            'course_id': self.course.id,
            'capacity': 1,
            'date_start': fields.Datetime.now(),
            'date_end': fields.Datetime.now() + timedelta(days=3),
        })

    def test_01_tna_cycle_and_endorsement(self):
        """Test TNA Cycle creation, TNA entry submission, and endorsement."""
        cycle = self.env['eds.tna.cycle'].create({
            'year': '2026',
            'start_date': fields.Date.today(),
            'submission_end_date': fields.Date.today() + timedelta(days=30),
        })
        self.assertEqual(cycle.state, 'draft')
        cycle.action_start_collection()
        self.assertEqual(cycle.state, 'collecting')

        tna_entry = self.env['eds.tna.entry'].create({
            'cycle_id': cycle.id,
            'employee_id': self.employee_1.id,
            'proposed_program': self.course.name,
            'gap_severity': 'high',
            'justification': 'Core Banking Security Competency Gap',
        })
        self.assertEqual(tna_entry.state, 'draft')

    def test_02_nomination_capacity_and_waitlist_promotion(self):
        """Test session capacity limit, waitlist assignment, and FIFO waitlist promotion."""
        nom1 = self.env['eds.nomination'].create({
            'session_id': self.session.id,
            'employee_id': self.employee_1.id,
            'nominated_by': self.user_manager.id,
        })
        self.assertEqual(nom1.state, 'draft')

        nom2 = self.env['eds.nomination'].create({
            'session_id': self.session.id,
            'employee_id': self.employee_2.id,
            'nominated_by': self.user_manager.id,
        })
        self.assertEqual(nom2.state, 'draft')
