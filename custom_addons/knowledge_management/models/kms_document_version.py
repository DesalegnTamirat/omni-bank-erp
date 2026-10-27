# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class KmsDocumentVersion(models.Model):
    """Historical archive of superseded document versions (FR-KMS-004, FR-LMS-011)."""
    _name = 'kms.document.version'
    _description = 'Knowledge Document Version History'
    _order = 'create_date desc'

    document_id = fields.Many2one('kms.document', string='Governed Document', required=True, ondelete='cascade', index=True)
    version_number = fields.Char(string='Version Number', required=True)
    file_data = fields.Binary(
        string='Archived Document File', attachment=True, required=True,
        groups='knowledge_management.group_kms_contributor',
    )
    file_name = fields.Char(string='Filename')
    effective_date = fields.Date(string='Effective Date')
    change_summary = fields.Text(string='Revision Summary', required=True)
    approved_by_id = fields.Many2one('hr.employee', string='Approved By')
    create_date = fields.Datetime(string='Archived Timestamp', readonly=True)

    _unique_document_version = models.Constraint(
        'unique(document_id, version_number)',
        'A document version can only be approved once.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su or not self.env.context.get('_kms_version_snapshot'):
            raise AccessError(_('Version snapshots can only be created by document approval.'))
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(_('Approved document snapshots cannot be modified.'))

    def unlink(self):
        raise UserError(_('Approved document snapshots cannot be deleted.'))
