# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class KmsDocumentVersion(models.Model):
    """Historical archive of superseded document versions (FR-KMS-004, FR-LMS-011)."""
    _name = 'kms.document.version'
    _description = 'Knowledge Document Version History'
    _order = 'create_date desc'

    document_id = fields.Many2one('kms.document', string='Governed Document', required=True, ondelete='cascade', index=True)
    version_number = fields.Char(string='Version Number', required=True)
    file_data = fields.Binary(string='Archived Document File', attachment=True, required=True)
    file_name = fields.Char(string='Filename')
    effective_date = fields.Date(string='Effective Date')
    change_summary = fields.Text(string='Revision Summary', required=True)
    approved_by_id = fields.Many2one('hr.employee', string='Approved By')
    create_date = fields.Datetime(string='Archived Timestamp', readonly=True)
