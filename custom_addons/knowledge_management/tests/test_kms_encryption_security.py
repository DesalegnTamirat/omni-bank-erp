# -*- coding: utf-8 -*-
import base64
import time
from cryptography.fernet import InvalidToken
from odoo.tests.common import TransactionCase
from odoo.addons.knowledge_management.utils.encryption import (
    get_kms_server_secret,
    derive_symmetric_key,
    encrypt_document_data,
    decrypt_document_data,
    CONFIG_PARAM_KEY,
)
from odoo.addons.knowledge_management.controllers.main import KmsDocumentController


class DummyRequest:
    def __init__(self, env, user, session_sid=None):
        self.env = env(user=user)
        self.session = type('Session', (), {'sid': session_sid})() if session_sid else None
        self.httprequest = type('Req', (), {'headers': {}, 'data': b''})()


class TestKmsEncryptionSecurity(TransactionCase):
    """
    P0 Security Test Suite for KMS Encryption & Watermarking Hardening (FR-KMS-015, FR-KMS-016).
    Verifies:
    1. ir.config_parameter secret storage (no hardcoded keys).
    2. Multi-instance isolation: different server secrets produce different ciphertexts and fail cross-decryption.
    3. Session-bound token encryption: decrypting under a different session fails.
    4. Time-to-Live (TTL) expiration enforcement.
    5. Non-PDF binary protection: mandatory encryption for office files.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.KmsCategory = cls.env['kms.category']
        cls.KmsDocType = cls.env['kms.document.type']
        cls.KmsClassification = cls.env['kms.classification']
        cls.KmsDocument = cls.env['kms.document']

        cls.user_alice = cls.env['res.users'].create({
            'name': 'Alice Auditor Security',
            'login': 'alice_sec@bunna.et',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('knowledge_management.group_kms_employee').id,
            ])],
        })
        cls.emp_alice = cls.env['hr.employee'].create({
            'name': 'Alice Security Emp',
            'user_id': cls.user_alice.id,
        })

        cls.user_bob = cls.env['res.users'].create({
            'name': 'Bob Operations Security',
            'login': 'bob_sec@bunna.et',
            'group_ids': [(6, 0, [
                cls.env.ref('base.group_user').id,
                cls.env.ref('knowledge_management.group_kms_employee').id,
            ])],
        })

        cls.category = cls.KmsCategory.search([('code', '=', 'SEC-POL')], limit=1) or cls.KmsCategory.create({'name': 'Security Policies', 'code': 'SEC-POL'})
        cls.doc_type = cls.KmsDocType.search([('code', '=', 'SOP-SEC')], limit=1) or cls.KmsDocType.create({'name': 'Security SOP', 'code': 'SOP-SEC'})
        cls.class_confidential = cls.KmsClassification.search([('code', '=', 'CONF')], limit=1)
        if not cls.class_confidential:
            cls.class_confidential = cls.KmsClassification.create({'name': 'Confidential', 'code': 'CONF', 'security_level': 3})
        else:
            cls.class_confidential.write({'security_level': 3, 'watermark_mandatory': True})

    def test_01_ir_config_parameter_secret_generation_and_persistence(self):
        """FR-KMS-016: Server secret is read from ir.config_parameter and never hardcoded in source."""
        ICP = self.env['ir.config_parameter'].sudo()
        # Ensure secret exists or is generated
        secret = get_kms_server_secret(self.env)
        self.assertTrue(secret)
        self.assertGreaterEqual(len(secret), 32)
        # Verify it is persisted in database
        persisted = ICP.get_param(CONFIG_PARAM_KEY)
        self.assertEqual(secret, persisted)

    def test_02_multi_instance_ciphertext_isolation(self):
        """FR-KMS-016: Two different install instances (different secrets) produce different ciphertexts and fail cross-decryption."""
        secret_instance_a = "INSTANCE_A_SECRET_KEY_9876543210123456789012"
        secret_instance_b = "INSTANCE_B_SECRET_KEY_1234567890987654321098"

        payload = b"CRITICAL_FINANCIAL_SWIFT_TRANSACTION_PAYLOAD_DATA"
        doc_id = 999
        user_id = self.user_alice.id

        cipher_a = encrypt_document_data(payload, doc_id, user_id, secret=secret_instance_a)
        cipher_b = encrypt_document_data(payload, doc_id, user_id, secret=secret_instance_b)

        # Ciphertexts must be distinct
        self.assertNotEqual(cipher_a, cipher_b)

        # Decrypting instance A ciphertext with instance B secret MUST fail
        with self.assertRaises(InvalidToken):
            decrypt_document_data(cipher_a, doc_id, user_id, secret=secret_instance_b)

        # Decrypting with matching secret succeeds
        decrypted_a = decrypt_document_data(cipher_a, doc_id, user_id, secret=secret_instance_a)
        self.assertEqual(decrypted_a, payload)

    def test_03_session_bound_encryption_validation(self):
        """FR-KMS-016: Encrypted document bound to an active session cannot be decrypted by a different session."""
        payload = b"RESTRICTED_BOARD_MINUTES_CONFIDENTIAL"
        doc_id = 555
        user_id = self.user_alice.id
        session_alpha = "SESSION-ALPHA-UUID-12345"
        session_beta = "SESSION-BETA-UUID-67890"

        # Encrypt bound to session Alpha
        cipher_session = encrypt_document_data(payload, doc_id, user_id, session_id=session_alpha, env=self.env)

        # Decrypt with session Beta must fail
        with self.assertRaises(InvalidToken):
            decrypt_document_data(cipher_session, doc_id, user_id, session_id=session_beta, env=self.env)

        # Decrypt with no session must fail
        with self.assertRaises(InvalidToken):
            decrypt_document_data(cipher_session, doc_id, user_id, session_id=None, env=self.env)

        # Decrypt with Alice under matching session Alpha succeeds
        decrypted = decrypt_document_data(cipher_session, doc_id, user_id, session_id=session_alpha, env=self.env)
        self.assertEqual(decrypted, payload)

        # Decrypt with Bob under session Alpha still fails (identity binding)
        with self.assertRaises(InvalidToken):
            decrypt_document_data(cipher_session, doc_id, self.user_bob.id, session_id=session_alpha, env=self.env)

    def test_04_token_ttl_expiration_fails_decryption(self):
        """FR-KMS-016: Expired tokens (older than TTL window) must fail decryption."""
        payload = b"SHORT_LIVED_CLEARING_HOUSE_TRANSACTION_LOG"
        doc_id = 777
        user_id = self.user_alice.id

        cipher = encrypt_document_data(payload, doc_id, user_id, env=self.env)

        # Immediate decryption with 900s TTL succeeds
        decrypted = decrypt_document_data(cipher, doc_id, user_id, env=self.env, max_age_seconds=900)
        self.assertEqual(decrypted, payload)

        # Decryption with a 1-second TTL after sleeping 2 seconds fails
        time.sleep(2)
        with self.assertRaises(InvalidToken):
            decrypt_document_data(cipher, doc_id, user_id, env=self.env, max_age_seconds=1)

    def test_05_non_pdf_office_files_mandatory_encryption_on_download(self):
        """FR-KMS-015, FR-KMS-016: Non-PDF office documents (.docx/.xlsx) strictly mandate encryption."""
        docx_data = b"PK\x03\x04[Content_Types].xml Mock OOXML Word Template"
        doc = self.KmsDocument.create({
            'name': 'Corporate Banking Facility Application Form',
            'category_id': self.category.id,
            'doc_type_id': self.doc_type.id,
            'classification_id': self.class_confidential.id,
            'owner_id': self.emp_alice.id,
            'file_name': 'facility_application.docx',
            'file_data': base64.b64encode(docx_data),
            'require_encryption': False,  # Should be forced true for non-PDF
        })

        controller = KmsDocumentController()
        dummy_req = DummyRequest(self.env, self.user_alice, session_sid="SESS-ALICE-SEC-01")
        from unittest.mock import patch
        with patch('odoo.addons.knowledge_management.controllers.main.request', dummy_req):
            res = controller.kms_download_document(doc.id)
            self.assertEqual(dict(res.headers).get('X-KMS-Encrypted'), '1')
            self.assertTrue(dict(res.headers).get('Content-Disposition').endswith('.docx.enc"'))

            # Verify downloaded bytes can be decrypted with Alice's session
            downloaded = res.get_data()
            decrypted = decrypt_document_data(
                downloaded, doc.id, self.user_alice.id,
                session_id="SESS-ALICE-SEC-01", env=self.env
            )
            self.assertEqual(decrypted, docx_data)
