# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    dms_max_file_size_mb = fields.Integer(
        string='Maximum File Size (MB)',
        config_parameter='documents_lite.max_file_size_mb',
        default=25,
        help="Maximum allowed file size in megabytes for uploaded documents (e.g. 25 MB).",
    )
    dms_allowed_extensions = fields.Char(
        string='Allowed File Extensions',
        config_parameter='documents_lite.allowed_extensions',
        default='pdf, png, jpg, jpeg, gif, webp, bmp, doc, docx, xls, xlsx, ppt, pptx, odt, ods, odp, rtf, txt, csv',
        help="Comma-separated list of allowed file extensions (e.g. pdf, docx, xlsx, png, jpg). Leave empty to use system defaults.",
    )
    dms_max_files_per_folder = fields.Integer(
        string='Maximum Files Per Folder',
        config_parameter='documents_lite.max_files_per_folder',
        default=500,
        help="Maximum number of active documents allowed in a single folder (set to 0 for unlimited).",
    )
    dms_storage_optimization = fields.Boolean(
        string='Filestore Storage Optimization',
        config_parameter='documents_lite.storage_optimization',
        default=True,
        help="Store binary files in Odoo filestore with deduplication rather than bloating the PostgreSQL database table.",
    )
