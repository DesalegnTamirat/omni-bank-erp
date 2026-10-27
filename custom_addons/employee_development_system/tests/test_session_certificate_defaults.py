# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'eds_session_certificate_defaults')
class TestSessionCertificateDefaults(TransactionCase):

    def test_course_wording_copies_and_session_edits_survive(self):
        first, second = self.env['eds.course'].create([
            {
                'name': 'Certificate course one',
                'certificate_title': 'First title',
                'certificate_body_text': 'First body for {employee_name}',
                'certificate_signatory_name': 'First signer',
                'certificate_signatory_title': 'First role',
            },
            {
                'name': 'Certificate course two',
                'certificate_title': 'Second title',
                'certificate_body_text': 'Second body for {employee_name}',
                'certificate_signatory_name': 'Second signer',
                'certificate_signatory_title': 'Second role',
            },
        ])
        session = self.env['eds.session'].create({
            'course_id': first.id,
            'date_start': '2098-05-01 09:00:00',
            'date_end': '2098-05-01 17:00:00',
        })
        self.assertEqual(session.certificate_title, first.certificate_title)
        self.assertEqual(session.certificate_body_text, first.certificate_body_text)
        self.assertEqual(session.certificate_signatory_name,
                         first.certificate_signatory_name)
        self.assertEqual(session.certificate_signatory_title,
                         first.certificate_signatory_title)

        session.certificate_title = 'Session specific title'
        session.write({'date_end': '2098-05-01 18:00:00'})
        self.assertEqual(session.certificate_title, 'Session specific title')

        session.write({'course_id': second.id,
                       'certificate_body_text': 'Session specific second body'})
        self.assertEqual(session.certificate_title, second.certificate_title)
        self.assertEqual(session.certificate_body_text, 'Session specific second body')
        self.assertEqual(session.certificate_signatory_name,
                         second.certificate_signatory_name)
        self.assertEqual(session.certificate_signatory_title,
                         second.certificate_signatory_title)

        draft = self.env['eds.session'].new({'course_id': first.id})
        draft._onchange_course_id()
        self.assertEqual(draft.certificate_title, first.certificate_title)
        draft.certificate_title = 'Typed in session form'
        self.assertEqual(draft.certificate_title, 'Typed in session form')
