# -*- coding: utf-8 -*-
import base64
from unittest.mock import patch
from cryptography.fernet import InvalidToken
from odoo.tests.common import TransactionCase
from odoo.addons.knowledge_management.controllers.main import KmsDocumentController
from odoo.addons.knowledge_management.utils.encryption import encrypt_document_data, decrypt_document_data


class DummyRequest:
    def __init__(self, env, user, data=b''):
        self.env = env(user=user)
        self.httprequest = type('Req', (), {'data': data})()

    def render(self, template, values=None):
        return type('RenderResponse', (), {'status_code': 403, 'values': values})()

    def not_found(self):
        return type('NotFoundResponse', (), {'status_code': 404})()


class TestKmsPhase4Functional(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.KmsDocument = cls.env['kms.document']
        cls.KmsCategory = cls.env['kms.category']
        cls.KmsClassification = cls.env['kms.classification']
        cls.KmsDocType = cls.env['kms.document.type']
        cls.KmsDigitalLibrary = cls.env['kms.digital.library']
        cls.KmsCop = cls.env['kms.cop']
        cls.KmsForumTopic = cls.env['kms.forum.topic']
        cls.KmsForumPost = cls.env['kms.forum.post']
        cls.KmsLessonLearned = cls.env['kms.lesson.learned']
        cls.KmsAuditLog = cls.env['kms.audit.log']

        # Departments
        cls.dept_hr = cls.env['hr.department'].create({'name': 'HR Functional Testing'})
        cls.dept_fin = cls.env['hr.department'].create({'name': 'Finance Functional Testing'})

        # Users and Employees
        cls.user_hr = cls.env['res.users'].create({
            'name': 'HR Functional User',
            'login': 'hr_func_test@bunna.et',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('knowledge_management.group_kms_employee').id,
                cls.env.ref('knowledge_management.group_kms_contributor').id,
            ])],
        })
        cls.emp_hr = cls.env['hr.employee'].create({
            'name': 'HR Functional Employee',
            'user_id': cls.user_hr.id,
            'department_id': cls.dept_hr.id,
        })

        cls.user_fin = cls.env['res.users'].create({
            'name': 'Finance Functional User',
            'login': 'fin_func_test@bunna.et',
            'group_ids': [(6, 0, [cls.env.ref('base.group_user').id, cls.env.ref('knowledge_management.group_kms_employee').id])],
        })
        cls.emp_fin = cls.env['hr.employee'].create({
            'name': 'Finance Functional Employee',
            'user_id': cls.user_fin.id,
            'department_id': cls.dept_fin.id,
        })

        cls.category = cls.KmsCategory.create({'name': 'Governance Docs', 'code': 'GOV-TEST-P4'})
        cls.doc_type = cls.env.ref('knowledge_management.kms_type_sop', raise_if_not_found=False) or cls.KmsDocType.search([('code', '=', 'SOP')], limit=1) or cls.KmsDocType.create({'name': 'Standard Operating Procedure', 'code': 'SOP-TEST-P4'})
        cls.class_pub = cls.env.ref('knowledge_management.kms_class_public')

    def test_11_encrypted_download_and_non_pdf_protection(self):
        controller = KmsDocumentController()
        fake_pdf = b'%PDF-1.4 Minimal PDF header content'

        # 1. Governed PDF with require_encryption=True
        doc_pdf = self.KmsDocument.create({
            'name': 'Encrypted Board Policy',
            'category_id': self.category.id,
            'doc_type_id': self.doc_type.id,
            'classification_id': self.class_pub.id,
            'owner_id': self.emp_hr.id,
            'file_name': 'board_policy.pdf',
            'file_data': base64.b64encode(fake_pdf),
            'require_watermark': False,
            'require_encryption': True,
        })

        dummy_req_hr = DummyRequest(self.env, self.user_hr)
        with patch('odoo.addons.knowledge_management.controllers.main.request', dummy_req_hr):
            res = controller.kms_download_document(doc_pdf.id)
            self.assertEqual(dict(res.headers).get('X-KMS-Encrypted'), '1')
            downloaded_bytes = res.get_data()

            # Verify downloaded bytes cannot be decrypted outside session / by another user
            with self.assertRaises(InvalidToken):
                decrypt_document_data(downloaded_bytes, doc_pdf.id, self.user_fin.id)

            # Authorized user can decrypt
            decrypted = decrypt_document_data(downloaded_bytes, doc_pdf.id, self.user_hr.id)
            self.assertEqual(decrypted, fake_pdf)

        # 2. Governed non-PDF document (DOCX/XLSX) must be protected
        docx_bytes = b'PK\x03\x04 Fake Word Document Byte Stream'
        doc_docx = self.KmsDocument.create({
            'name': 'Confidential Balance Template',
            'category_id': self.category.id,
            'doc_type_id': self.doc_type.id,
            'classification_id': self.class_pub.id,
            'owner_id': self.emp_hr.id,
            'file_name': 'balance_template.docx',
            'file_data': base64.b64encode(docx_bytes),
            'require_watermark': True,
            'require_encryption': False,  # Non-PDF must be automatically protected
        })

        with patch('odoo.addons.knowledge_management.controllers.main.request', dummy_req_hr):
            res_docx = controller.kms_download_document(doc_docx.id)
            self.assertEqual(dict(res_docx.headers).get('X-KMS-Encrypted'), '1')
            downloaded_docx_bytes = res_docx.get_data()

            # Outside session / wrong user cannot decrypt
            with self.assertRaises(InvalidToken):
                decrypt_document_data(downloaded_docx_bytes, doc_docx.id, self.user_fin.id)

            # Downloader session can decrypt
            decrypted_docx = decrypt_document_data(downloaded_docx_bytes, doc_docx.id, self.user_hr.id)
            self.assertEqual(decrypted_docx, docx_bytes)

    def test_12_audit_logging_across_all_kms_surfaces(self):
        # 1. Digital Library Auditing
        lib_item = self.KmsDigitalLibrary.create({
            'name': 'Basel III Compliance Manual',
            'category_id': self.category.id,
            'file_data': base64.b64encode(b'PDF Content'),
            'file_name': 'basel3.pdf',
        })

        lib_item.with_user(self.user_hr).action_read_resource()
        log_read = self.KmsAuditLog.search([
            ('resource_type', '=', 'digital_library'),
            ('action', '=', 'view'),
            ('user_id', '=', self.user_hr.id),
        ], limit=1)
        self.assertTrue(log_read, 'Reading digital library item must create audit log entry')

        lib_item.with_user(self.user_hr).action_download_resource()
        log_dl = self.KmsAuditLog.search([
            ('resource_type', '=', 'digital_library'),
            ('action', '=', 'download'),
            ('user_id', '=', self.user_hr.id),
        ], limit=1)
        self.assertTrue(log_dl, 'Downloading digital library item must create audit log entry')

        # 2. Community of Practice Join/Leave Auditing
        cop = self.KmsCop.create({
            'name': 'Trade Finance Community',
            'code': 'COP-TF-TEST',
            'lead_id': self.emp_hr.id,
            'category_id': self.category.id,
            'description': '<p>Trade Finance knowledge sharing</p>',
        })

        cop.with_user(self.user_fin).action_join()
        log_join = self.KmsAuditLog.search([
            ('resource_type', '=', 'cop'),
            ('action', '=', 'join'),
            ('user_id', '=', self.user_fin.id),
        ], limit=1)
        self.assertTrue(log_join, 'Joining CoP must create audit log entry')

        cop.with_user(self.user_fin).action_leave()
        log_leave = self.KmsAuditLog.search([
            ('resource_type', '=', 'cop'),
            ('action', '=', 'leave'),
            ('user_id', '=', self.user_fin.id),
        ], limit=1)
        self.assertTrue(log_leave, 'Leaving CoP must create audit log entry')

        # 3. Knowledge Forum Auditing
        topic = self.KmsForumTopic.with_user(self.user_hr).create({
            'name': 'SWIFT MT103 Processing Clarification',
            'category_id': self.category.id,
            'author_id': self.emp_hr.id,
            'content': '<p>Clarification question</p>',
        })
        log_topic = self.KmsAuditLog.search([
            ('resource_type', '=', 'forum'),
            ('action', '=', 'upload'),
            ('user_id', '=', self.user_hr.id),
        ], limit=1)
        self.assertTrue(log_topic, 'Creating forum topic must create audit log entry')

        post = self.KmsForumPost.with_user(self.user_fin).create({
            'topic_id': topic.id,
            'author_id': self.emp_fin.id,
            'content': '<p>Follow the standard SOP</p>',
        })
        log_post = self.KmsAuditLog.search([
            ('resource_type', '=', 'forum'),
            ('action', '=', 'upload'),
            ('user_id', '=', self.user_fin.id),
        ], limit=1)
        self.assertTrue(log_post, 'Posting forum reply must create audit log entry')

        # 4. Tacit Lesson Learned Auditing
        lesson = self.KmsLessonLearned.with_user(self.user_hr).create({
            'name': 'Disaster Recovery Network Failover Test',
            'category_id': self.category.id,
            'project_initiative': 'DRP Drill 2026',
            'event_summary': 'Summary',
            'root_cause': 'Cause',
            'key_lesson': '<p>Lesson</p>',
            'mitigation_recommendation': '<p>Mitigation</p>',
            'author_id': self.emp_hr.id,
        })
        log_lesson = self.KmsAuditLog.search([
            ('resource_type', '=', 'lesson_learned'),
            ('action', '=', 'upload'),
            ('user_id', '=', self.user_hr.id),
        ], limit=1)
        self.assertTrue(log_lesson, 'Creating lesson learned must create audit log entry')

        lesson.with_user(self.user_hr).action_approve()
        log_appr = self.KmsAuditLog.search([
            ('resource_type', '=', 'lesson_learned'),
            ('action', '=', 'approve'),
            ('user_id', '=', self.user_hr.id),
        ], limit=1)
        self.assertTrue(log_appr, 'Approving lesson learned must create audit log entry')
