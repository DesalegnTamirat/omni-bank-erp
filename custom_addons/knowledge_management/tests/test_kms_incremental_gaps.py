"""Focused regressions for the KMS requirement gaps closed incrementally."""

import base64
import io
import zipfile
from unittest.mock import patch

from odoo.http import Response
from odoo.tests.common import TransactionCase
from odoo.addons.knowledge_management.controllers.main import KmsDocumentController
from odoo.addons.knowledge_management.utils.encryption import decrypt_document_data


def _docx_with_text(value):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr(
            'word/document.xml',
            ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
             '<w:body><w:p><w:r><w:t>%s</w:t></w:r></w:p></w:body></w:document>') % value,
        )
    return output.getvalue()


class _Request:
    def __init__(self, env, user):
        self.env = env(user=user)
        self.session = type('Session', (), {'sid': 'kms-gap-test-session'})()
        self.httprequest = type('Request', (), {'data': b''})()

    def render(self, _template, values):
        return Response(values.get('message', ''), status=403)

    def not_found(self):
        return Response('Not found', status=404)


class TestKmsIncrementalGaps(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category = cls.env['kms.category'].create({'name': 'Gap Test', 'code': 'GAP-KMS'})
        cls.doc_type = cls.env['kms.document.type'].create({'name': 'Gap Test Type', 'code': 'GAP-TYPE'})
        cls.public = cls.env['kms.classification'].search([('code', '=', 'PUB')], limit=1)
        if not cls.public:
            cls.public = cls.env['kms.classification'].create({
                'name': 'Public', 'code': 'PUB', 'security_level': 1,
            })
        cls.department = cls.env['hr.department'].create({'name': 'KMS Gap Test Department'})
        cls.job = cls.env['hr.job'].create({'name': 'KMS Gap Test Role'})
        cls.reader = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'KMS Gap Reader', 'login': 'kms_gap_reader@example.invalid',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('knowledge_management.group_kms_employee').id,
            ])],
        })
        cls.employee = cls.env['hr.employee'].create({
            'name': 'KMS Gap Employee', 'user_id': cls.reader.id,
            'department_id': cls.department.id, 'job_id': cls.job.id,
        })

    def _document(self, name, filename, payload, **extra):
        vals = {
            'name': name, 'category_id': self.category.id,
            'doc_type_id': self.doc_type.id,
            'classification_id': self.public.id,
            'owner_id': self.employee.id,
            'file_name': filename,
            'file_data': base64.b64encode(payload),
        }
        vals.update(extra)
        return self.env['kms.document'].create(vals)

    def _approve(self, document):
        document.sudo().write({'state': 'review'})
        document.sudo().write({'state': 'approved'})

    def test_uploaded_docx_text_is_searchable_and_replaced(self):
        document = self._document('Extract Test', 'test.docx', _docx_with_text('uniquebranchtoken'))
        self.assertIn('uniquebranchtoken', document.content_text)
        self.assertIn(document, self.env['kms.document'].search([
            ('fts_query', '=', 'uniquebranchtoken'),
        ]))
        document.write({'file_data': base64.b64encode(_docx_with_text('newsearchtoken'))})
        self.assertIn('newsearchtoken', document.content_text)
        self.assertNotIn('uniquebranchtoken', document.content_text)

    def test_role_targeted_library_recommendations(self):
        library = self.env['kms.digital.library'].create({
            'name': 'Role Guide', 'category_id': self.category.id,
            'is_recommended': True,
            'target_job_ids': [(4, self.job.id)],
        })
        mine = self.env['kms.digital.library'].with_user(self.reader).search([
            ('recommended_for_me', '=', True),
        ])
        self.assertIn(library, mine)

    def test_library_upload_points_are_deduplicated_and_audited(self):
        data = base64.b64encode(b'One reusable library file')
        first = self.env['kms.digital.library'].create({
            'name': 'Library File One', 'category_id': self.category.id,
            'file_name': 'resource.txt', 'file_data': data,
        })
        second = self.env['kms.digital.library'].create({
            'name': 'Library File Two', 'category_id': self.category.id,
            'file_name': 'resource.txt', 'file_data': data,
        })
        ledger = self.env['kms.contributor.point'].sudo().search([
            ('user_id', '=', self.env.user.id),
            ('source', '=', 'library_upload'),
        ])
        self.assertEqual(len(ledger), 1)
        first.write({'summary': 'Updated summary'})
        first.unlink()
        events = self.env['kms.audit.log'].sudo().search([
            ('resource_type', '=', 'digital_library'),
            ('resource_name', 'ilike', 'Library File One'),
        ]).mapped('action')
        self.assertTrue({'upload', 'modify', 'delete'}.issubset(set(events)))
        second.unlink()

    def test_cop_join_points_are_one_time(self):
        cop = self.env['kms.cop'].create({
            'name': 'Gap Test CoP', 'code': 'GAP-COP',
            'description': '<p>Knowledge sharing</p>',
            'category_id': self.category.id,
            'lead_id': self.employee.id,
        })
        actor = cop.with_user(self.reader)
        actor.action_join()
        actor.action_join()
        actor.action_leave()
        actor.action_join()
        points = self.env['kms.contributor.point'].sudo().search_count([
            ('user_id', '=', self.reader.id),
            ('source', '=', 'cop_participation'),
            ('description', '=', f'CoP membership: {cop.id}'),
        ])
        self.assertEqual(points, 1)

    def test_public_pdf_download_encrypted_and_view_only_blocked(self):
        from reportlab.pdfgen import canvas

        output = io.BytesIO()
        pdf = canvas.Canvas(output)
        pdf.drawString(72, 720, 'KMS protected document')
        pdf.save()
        document = self._document('Protected PDF', 'protected.pdf', output.getvalue(),
                                  require_watermark=False)
        self._approve(document)
        fake_request = _Request(self.env, self.reader)
        with patch('odoo.addons.knowledge_management.controllers.main.request', fake_request):
            response = KmsDocumentController().kms_download_document(document.id)
            self.assertEqual(response.headers.get('X-KMS-Encrypted'), '1')
            recovered = decrypt_document_data(
                response.get_data(), document.id, self.reader.id,
                session_id='kms-gap-test-session', env=fake_request.env,
            )
            self.assertIn(b'%PDF-', recovered)

        restricted = self._document('View Only PDF', 'view-only.pdf', output.getvalue(),
                                    is_view_only=True)
        self._approve(restricted)
        with patch('odoo.addons.knowledge_management.controllers.main.request', fake_request):
            denied = KmsDocumentController().kms_download_document(restricted.id)
            self.assertEqual(denied.status_code, 403)

    def test_non_pdf_text_preview_escapes_uploaded_content(self):
        document = self._document(
            'Office Preview', 'office.docx', _docx_with_text('Ordinary text'),
            content_text='<script>alert(1)</script> Review text',
            is_view_only=True,
        )
        self._approve(document)
        fake_request = _Request(self.env, self.reader)
        with patch('odoo.addons.knowledge_management.controllers.main.request', fake_request):
            response = KmsDocumentController().kms_view_document(document.id)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'<script>', response.get_data())
        self.assertIn(b'&lt;script&gt;', response.get_data())
        self.assertEqual(response.headers.get('Cache-Control'), 'private, no-store')
