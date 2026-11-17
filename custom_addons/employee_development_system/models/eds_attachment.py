# -*- coding: utf-8 -*-
"""EDS file upload restrictions: strictly PDF or Image format, configurable max size."""

import base64
from pathlib import PurePath
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

ALLOWED_EDS_EXTENSIONS = {
    '.pdf',
    '.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tiff', '.tif', '.svg',
}
ALLOWED_EDS_MIMETYPES = {
    'application/pdf',
    'image/png', 'image/jpeg', 'image/pjpeg', 'image/webp', 'image/gif',
    'image/bmp', 'image/x-ms-bmp', 'image/tiff', 'image/svg+xml', 'image/x-icon',
    'application/octet-stream',  # generic binary, will fall back to filename extension
}


def _is_pdf_or_image_bytes(data):
    if not data:
        return False
    if data.startswith(b'%PDF'):
        return True
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return True
    if data.startswith(b'\xff\xd8\xff'):
        return True
    if data.startswith(b'GIF87a') or data.startswith(b'GIF89a'):
        return True
    if data.startswith(b'RIFF') and b'WEBP' in data[:16]:
        return True
    if data.startswith(b'BM'):
        return True
    if data.startswith(b'II*\x00') or data.startswith(b'MM\x00*'):
        return True
    sample = data[:1024].lstrip().lower()
    if (sample.startswith(b'<?xml') or sample.startswith(b'<svg')) and b'<svg' in sample:
        return True
    return False


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    def _is_eds_attachment(self, vals=None):
        """Determine whether this attachment is associated with an EDS model/record."""
        if self.env.context.get('skip_eds_file_check'):
            return False

        res_model = (vals and vals.get('res_model')) or self.res_model or self.env.context.get('default_res_model')
        if res_model:
            if res_model.startswith('eds.') or res_model == 'training.commitment':
                model_cls = self.env.get(res_model)
                if model_cls is not None and model_cls._transient:
                    return False
                return True
            return False

        active_model = self.env.context.get('active_model') or self.env.context.get('params', {}).get('model')
        if active_model and (active_model.startswith('eds.') or active_model == 'training.commitment'):
            model_cls = self.env.get(active_model)
            if model_cls is not None and model_cls._transient:
                return False
            return True

        return False

    def _validate_eds_file(self, vals, record=None):
        if not self._is_eds_attachment(vals):
            return

        filename = vals.get('name') or (record and record.name) or ''
        mimetype = vals.get('mimetype') or (record and record.mimetype) or ''

        # If attachment is created for a model binary field, look for companion filename field on record
        res_field = vals.get('res_field') or (record and record.res_field)
        res_id = vals.get('res_id') or (record and record.res_id)
        res_model = (vals and vals.get('res_model')) or self.res_model
        if res_field and res_id and res_model and res_model in self.env:
            try:
                target_rec = self.env[res_model].browse(res_id)
                for fn in ('filename', 'file_name', 'document_name', 'certificate_image_filename',
                           'ceo_memo_filename', 'award_filename', 'contract_filename',
                           'scanned_filename', 'presentation_filename', 'mou_filename', 'mou_document_name',
                           'proof_filename', 'bond_filename'):
                    if hasattr(target_rec, fn) and getattr(target_rec, fn):
                        filename = getattr(target_rec, fn)
                        break
            except Exception:
                pass

        ext = PurePath(filename).suffix.lower()

        # Extract sample bytes to check content
        sample_bytes = b''
        if 'raw' in vals and vals['raw']:
            sample_bytes = vals['raw'][:1024] if isinstance(vals['raw'], (bytes, bytearray)) else b''
        elif 'datas' in vals and vals['datas']:
            try:
                raw_val = vals['datas']
                if isinstance(raw_val, str):
                    raw_val = raw_val.encode('ascii')
                padding = b'=' * ((4 - len(raw_val[:256]) % 4) % 4)
                sample_bytes = base64.b64decode(raw_val[:256] + padding)
            except Exception:
                sample_bytes = b''
        elif record and record.raw:
            sample_bytes = record.raw[:1024]
        elif record and record.datas:
            try:
                raw_val = record.datas
                if isinstance(raw_val, str):
                    raw_val = raw_val.encode('ascii')
                padding = b'=' * ((4 - len(raw_val[:256]) % 4) % 4)
                sample_bytes = base64.b64decode(raw_val[:256] + padding)
            except Exception:
                sample_bytes = b''

        # Format validation: only PDF or Image allowed
        is_pdf_or_image = False
        if ext in ALLOWED_EDS_EXTENSIONS:
            is_pdf_or_image = True
        elif mimetype and (mimetype.startswith('image/') or mimetype == 'application/pdf'):
            is_pdf_or_image = True
        elif _is_pdf_or_image_bytes(sample_bytes):
            is_pdf_or_image = True

        has_data = bool(vals.get('raw') or vals.get('datas') or (record and (record.raw or record.datas)))
        if has_data and not is_pdf_or_image:
            raise ValidationError(
                _('Upload restricted: Only PDF documents and image files are allowed in EDS. ("%s" is not an accepted format)') % filename
            )

        # Size validation: configurable in EDS settings
        max_mb_param = self.env['ir.config_parameter'].sudo().get_param('eds.max_upload_size_mb', 10)
        try:
            max_mb = int(max_mb_param)
            if max_mb < 1:
                max_mb = 10
        except (ValueError, TypeError):
            max_mb = 10
        max_bytes = max_mb * 1024 * 1024

        size = 0
        if 'raw' in vals and vals['raw']:
            size = len(vals['raw'])
        elif 'datas' in vals and vals['datas']:
            data = vals['datas']
            if isinstance(data, str):
                size = (len(data) * 3) // 4
            elif isinstance(data, bytes):
                size = len(data)
        elif record and record.file_size:
            size = record.file_size

        if size > max_bytes:
            raise ValidationError(
                _('Upload restricted: File "%s" (%.2f MB) exceeds the maximum allowed file size of %s MB configured in EDS Settings.')
                % (filename or 'Attachment', size / (1024 * 1024), max_mb)
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._validate_eds_file(vals)
        return super().create(vals_list)

    def write(self, vals):
        for record in self:
            record._validate_eds_file(vals, record=record)
        return super().write(vals)


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        info = super().session_info()
        max_mb_param = self.env['ir.config_parameter'].sudo().get_param('eds.max_upload_size_mb', 10)
        try:
            max_mb = int(max_mb_param)
            if max_mb < 1:
                max_mb = 10
        except (ValueError, TypeError):
            max_mb = 10
        info['eds_max_upload_size_mb'] = max_mb
        return info
