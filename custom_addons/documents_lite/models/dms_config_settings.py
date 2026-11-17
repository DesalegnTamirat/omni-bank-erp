# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class DmsConfigSettings(models.Model):
    _name = 'dms.config.settings'
    _description = 'Documents Configuration & Storage Settings'

    name = fields.Char(string='Setting Name', default='Documents Settings', required=True)
    
    # File Sizing & Quotas
    max_file_size_mb = fields.Integer(
        string='Maximum File Size (MB)',
        default=25,
        required=True,
        help="Maximum upload file size allowed per document in megabytes."
    )
    max_files_per_folder = fields.Integer(
        string='Maximum Files Per Folder',
        default=500,
        required=True,
        help="Maximum number of active documents allowed in a single folder (set to 0 for unlimited)."
    )
    warning_file_size_mb = fields.Integer(
        string='Large File Warning Threshold (MB)',
        default=10,
        help="Documents exceeding this size will be flagged as large files in dashboards and filters."
    )

    # Allowed Extensions & File Types
    allowed_extensions = fields.Char(
        string='Allowed File Extensions',
        default='pdf, png, jpg, jpeg, gif, webp, bmp, doc, docx, xls, xlsx, ppt, pptx, odt, ods, odp, rtf, txt, csv',
        required=True,
        help="Comma-separated list of allowed file extensions."
    )
    allow_all_extensions = fields.Boolean(
        string='Allow All File Types',
        default=False,
        help="If checked, any non-executable file format is accepted without restricting to extension list."
    )

    # Base64 & PostgreSQL Optimization
    enable_base64_optimization = fields.Boolean(
        string='PostgreSQL Base64 TOAST Optimization',
        default=True,
        help="Optimizes base64 binary chunks in PostgreSQL with inline memory prefetch disable (prefetch=False) and out-of-line TOAST table storage."
    )
    auto_generate_thumbnails = fields.Boolean(
        string='Auto Generate Image Thumbnails',
        default=True,
        help="Automatically generate lightweight compressed base64 thumbnails (256x256) so kanban cards load instantly without reading the full file bytea."
    )
    thumbnail_quality = fields.Integer(
        string='Thumbnail Image Quality (%)',
        default=80,
        help="JPEG/PNG compression quality percentage for generated thumbnails (1-100)."
    )

    # Versioning & Security
    enable_versioning = fields.Boolean(
        string='Enable Document Versioning',
        default=True,
        help="Automatically save previous file revisions when an existing document is updated."
    )
    max_versions_per_document = fields.Integer(
        string='Maximum Versions Kept',
        default=10,
        help="Maximum historical revisions preserved per document (0 for unlimited)."
    )
    allow_public_downloads_default = fields.Boolean(
        string='Allow Downloads by Default',
        default=True,
        help="Default download permission for newly uploaded documents."
    )
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company,
        index=True,
    )

    @api.model
    def get_settings(self):
        """Retrieve the active configuration record, creating singleton if not present."""
        record = self.search([('company_id', '=', self.env.company.id)], limit=1)
        if not record:
            record = self.search([], limit=1)
        if not record:
            record = self.sudo().create({
                'name': 'Default Documents Configuration',
                'company_id': self.env.company.id,
            })
        return record

    @api.model
    def action_open_settings(self):
        """Action for Configuration > Document Settings menu to open the singleton form view."""
        settings = self.get_settings()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Document Settings'),
            'res_model': 'dms.config.settings',
            'res_id': settings.id,
            'view_mode': 'form',
            'target': 'current',
        }
