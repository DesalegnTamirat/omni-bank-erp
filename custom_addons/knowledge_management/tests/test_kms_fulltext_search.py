# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class TestKmsFulltextSearch(TransactionCase):
    """
    FR-KMS-006: Deep full-text indexed search on kms.document across Title, Summary, and Content.
    Verifies:
    1. GIN fulltext index exists in PostgreSQL catalog.
    2. Model method _search_fulltext performs ts_rank ordered retrieval.
    3. Search field fts_query executes indexed queries in ORM domains.
    4. Complex / punctuated query resilience without SQL errors.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.KmsCategory = cls.env['kms.category']
        cls.KmsDocType = cls.env['kms.document.type']
        cls.KmsClassification = cls.env['kms.classification']
        cls.KmsDocument = cls.env['kms.document']

        cls.category = cls.KmsCategory.search([('code', '=', 'AUD-FTS')], limit=1) or cls.KmsCategory.create({
            'name': 'FTS Test Audit',
            'code': 'AUD-FTS',
        })
        cls.doc_type = cls.KmsDocType.search([('code', '=', 'SOP-FTS')], limit=1) or cls.KmsDocType.create({
            'name': 'FTS Test SOP',
            'code': 'SOP-FTS',
        })
        cls.classification = cls.KmsClassification.search([('code', '=', 'PUB')], limit=1)
        if not cls.classification:
            cls.classification = cls.KmsClassification.create({
                'name': 'Public',
                'code': 'PUB',
                'security_level': 1,
            })

        cls.emp = cls.env['hr.employee'].search([], limit=1)
        if not cls.emp:
            cls.emp = cls.env['hr.employee'].create({'name': 'KMS Search Owner'})

        # Ensure index is applied in test DB
        cls.env['kms.document'].init()

        # Create test documents with specific searchable text
        cls.doc_anti_money = cls.KmsDocument.create({
            'name': 'Anti-Money Laundering Framework',
            'category_id': cls.category.id,
            'doc_type_id': cls.doc_type.id,
            'classification_id': cls.classification.id,
            'owner_id': cls.emp.id,
            'summary': 'Framework for detecting suspicious financial transactions and AML/CFT compliance.',
            'content_text': 'All branch compliance officers must file CTR and STR reports to the Financial Intelligence Center.',
            'state': 'approved',
        })

        cls.doc_swift_wire = cls.KmsDocument.create({
            'name': 'Cross-Border Wire Transfer Procedures',
            'category_id': cls.category.id,
            'doc_type_id': cls.doc_type.id,
            'classification_id': cls.classification.id,
            'owner_id': cls.emp.id,
            'summary': 'Standard operating procedures for outgoing international SWIFT payments.',
            'content_text': 'Dual authorization is mandatory for MT103 and MT202 messages exceeding threshold.',
            'state': 'approved',
        })

        cls.doc_cyber_sec = cls.KmsDocument.create({
            'name': 'Information Security Policy',
            'category_id': cls.category.id,
            'doc_type_id': cls.doc_type.id,
            'classification_id': cls.classification.id,
            'owner_id': cls.emp.id,
            'summary': 'Core banking cybersecurity rules and firewall configurations.',
            'content_text': 'Zero trust architecture is enforced. Two-factor authentication is required for all administrative access.',
            'state': 'approved',
        })

    def test_01_gin_index_exists_in_database(self):
        """Verify that GIN full-text index is created on kms_document."""
        self.env.cr.execute("""
            SELECT indexname, indexdef FROM pg_indexes 
            WHERE tablename = 'kms_document' AND indexname = 'kms_document_fts_gin_idx'
        """)
        row = self.env.cr.fetchone()
        self.assertTrue(row, "kms_document_fts_gin_idx should exist in pg_indexes")
        self.assertIn("gin", row[1].lower())

    def test_02_search_fulltext_method_by_content_and_summary(self):
        """_search_fulltext finds records based on words in content_text or summary."""
        # Search by term in content_text
        results_swift = self.KmsDocument._search_fulltext("MT103")
        self.assertIn(self.doc_swift_wire, results_swift)
        self.assertNotIn(self.doc_cyber_sec, results_swift)

        # Search by term in summary
        results_aml = self.KmsDocument._search_fulltext("AML/CFT")
        self.assertIn(self.doc_anti_money, results_aml)

        # Search by term in name
        results_cyber = self.KmsDocument._search_fulltext("Cybersecurity")
        self.assertIn(self.doc_cyber_sec, results_cyber)

    def test_03_fts_query_search_field_in_domain(self):
        """Searching using fts_query in ORM search domains works via _search_fts."""
        docs = self.KmsDocument.search([('fts_query', '=', 'Financial Intelligence')])
        self.assertIn(self.doc_anti_money, docs)

        docs_zero_trust = self.KmsDocument.search([('fts_query', '=', 'Zero trust')])
        self.assertIn(self.doc_cyber_sec, docs_zero_trust)

    def test_04_search_resilience_special_chars(self):
        """Full-text search handles complex input, quotes, and punctuation gracefully."""
        # Unmatched quotes or odd punctuation shouldn't throw an unhandled DB exception
        results = self.KmsDocument._search_fulltext('! & | "unclosed quote')
        self.assertIsNotNone(results)
        # Empty search returns records subject to limit
        empty_res = self.KmsDocument._search_fulltext("")
        self.assertTrue(len(empty_res) >= 3)
