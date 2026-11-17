# -*- coding: utf-8 -*-
import base64
import io
import logging
import zipfile

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools.image import image_process

_logger = logging.getLogger(__name__)

# Number of files and sizes are set in Announcements > Configuration > Website Settings
IMAGE_MAX_PX = 1600                 # larger images are shrunk on upload
IMAGE_EXT = {'png', 'jpg', 'jpeg'}
VIEWABLE_EXT = {'pdf'} | IMAGE_EXT  # can be shown in the browser
ALLOWED_EXT = VIEWABLE_EXT | {'doc', 'docx', 'xls', 'xlsx'}


def _content_matches_extension(ext, raw):
    """True if the file's real content fits its extension (a renamed program is not a .pdf)."""
    if ext == 'pdf':
        return b'%PDF-' in raw[:1024]
    if ext == 'png':
        return raw.startswith(b'\x89PNG\r\n\x1a\n')
    if ext in ('jpg', 'jpeg'):
        return raw.startswith(b'\xff\xd8\xff')
    if ext in ('doc', 'xls'):
        return raw.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1')
    if ext in ('docx', 'xlsx'):
        if not raw.startswith(b'PK\x03\x04'):
            return False
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                names = archive.namelist()
        except zipfile.BadZipFile:
            return False
        folder = 'word/' if ext == 'docx' else 'xl/'
        return '[Content_Types].xml' in names and any(n.startswith(folder) for n in names)
    return False


class BunnaAnnouncementAttachment(models.Model):
    _name = 'bunna.announcement.attachment'
    _description = 'Announcement Attachment'
    _order = 'sequence, id'

    announcement_id = fields.Many2one(
        'bunna.announcement', string='Announcement', required=True,
        ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    # attachment=True stores the content in the filestore, not in the database
    file = fields.Binary(string='File', attachment=True)
    file_name = fields.Char(string='File Name')

    extension = fields.Char(compute='_compute_extension')
    file_size = fields.Integer(string='Size (bytes)', compute='_compute_file_size', store=True)
    size_display = fields.Char(string='Size', compute='_compute_size_display')
    is_image = fields.Boolean(compute='_compute_extension')
    is_viewable = fields.Boolean(compute='_compute_extension')
    icon_class = fields.Char(compute='_compute_extension')

    @api.depends('file_name')
    def _compute_extension(self):
        for rec in self:
            name = rec.file_name or ''
            ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
            rec.extension = ext
            rec.is_image = ext in IMAGE_EXT
            rec.is_viewable = ext in VIEWABLE_EXT
            if ext == 'pdf':
                rec.icon_class = 'fa-file-pdf-o text-danger'
            elif ext in ('doc', 'docx'):
                rec.icon_class = 'fa-file-word-o text-primary'
            elif ext in ('xls', 'xlsx'):
                rec.icon_class = 'fa-file-excel-o text-success'
            elif ext in IMAGE_EXT:
                rec.icon_class = 'fa-file-image-o text-info'
            else:
                rec.icon_class = 'fa-file-o'

    @api.depends('file')
    def _compute_file_size(self):
        for rec in self:
            rec.file_size = len(rec.file or b'') * 3 // 4

    @api.depends('file_size')
    def _compute_size_display(self):
        for rec in self:
            size = rec.file_size or 0
            if size >= 1024 * 1024:
                rec.size_display = '%.1f MB' % (size / (1024 * 1024))
            else:
                rec.size_display = '%d KB' % max(1, round(size / 1024)) if size else ''

    # ---- Validation ----------------------------------------------------
    @api.constrains('file', 'file_name', 'announcement_id')
    def _check_file(self):
        settings = self.env['bunna.announcement.settings']
        max_mb = settings.get_value('max_file_mb')
        max_files = settings.get_value('max_files')
        for rec in self:
            if not rec.file:
                # An empty row is reported by the announcement: "Attachments: row N has no file"
                continue
            if not rec.file_name:
                raise ValidationError(_("Attachments: a file was added without a name. Remove it and add it again."))
            if rec.extension not in ALLOWED_EXT:
                raise ValidationError(_(
                    "Attachments: '%(name)s' is not an allowed file type. Allowed types: %(allowed)s.",
                    name=rec.file_name, allowed=', '.join(sorted(ALLOWED_EXT))))
            if len(rec.file) * 3 // 4 > max_mb * 1024 * 1024:
                raise ValidationError(_(
                    "Attachments: '%(name)s' is larger than %(mb)s MB.", name=rec.file_name, mb=max_mb))
            if not _content_matches_extension(rec.extension, base64.b64decode(rec.file)):
                raise ValidationError(_(
                    "Attachments: '%(name)s' is not a real .%(ext)s file (its contents do not match its name).",
                    name=rec.file_name, ext=rec.extension))
            announcement = rec.announcement_id
            if len(announcement.attachment_ids) > max_files:
                raise ValidationError(_("Attachments: an announcement can have at most %s files.", max_files))
            if not announcement.allow_download and not rec.is_viewable:
                raise ValidationError(_(
                    "Attachments: downloads are disabled for this announcement, so '%s' cannot be shown. "
                    "Only PDF and image files can be view-only.", rec.file_name))

    # ---- Shrink big images so pages stay light -----------------------------
    @api.model
    def _shrink_image(self, data, file_name):
        ext = (file_name or '').rsplit('.', 1)[-1].lower()
        if not data or ext not in IMAGE_EXT:
            return data
        try:
            raw = base64.b64decode(data)
            out = image_process(raw, size=(IMAGE_MAX_PX, IMAGE_MAX_PX))
            if out and len(out) < len(raw):
                return base64.b64encode(out)
        except Exception:  # keep the original if anything goes wrong
            _logger.warning("Could not shrink image %s", file_name, exc_info=True)
        return data

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('file'):
                vals['file'] = self._shrink_image(vals['file'], vals.get('file_name'))
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('file'):
            name = vals.get('file_name') or (self[:1].file_name if self else '')
            vals = dict(vals, file=self._shrink_image(vals['file'], name))
        return super().write(vals)
