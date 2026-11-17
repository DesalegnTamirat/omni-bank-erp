import base64
import logging
import mimetypes
from collections import defaultdict
from hashlib import sha1
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import split_every
from odoo.tools.image import image_process
from odoo.tools.mimetypes import guess_mimetype

IMAGE_MIMETYPES = ('image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/svg+xml', 'image/bmp')
# Files that may be uploaded: PDF, images and office / text documents. Each extension maps to
# the kind of content check applied, so a renamed program or archive is refused.
ALLOWED_FILE_KINDS = {
    'pdf': 'pdf',
    'png': 'image', 'jpg': 'image', 'jpeg': 'image', 'gif': 'image', 'webp': 'image', 'bmp': 'image',
    'doc': 'ole', 'xls': 'ole', 'ppt': 'ole',
    'docx': 'zip', 'xlsx': 'zip', 'pptx': 'zip', 'odt': 'zip', 'ods': 'zip', 'odp': 'zip',
    'rtf': 'rtf', 'txt': 'text', 'csv': 'text',
}
ALLOWED_EXTENSIONS_LABEL = (
    'PDF, images (PNG, JPG, GIF, WEBP, BMP) and documents '
    '(DOC, DOCX, XLS, XLSX, PPT, PPTX, ODT, ODS, ODP, RTF, TXT, CSV)')
OLE_MAGIC = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
THUMBNAIL_MIMETYPES = ('image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/bmp')
THUMBNAIL_SIZE = (256, 256)
VIEWABLE_PREFIXES = ('image/', 'video/', 'audio/', 'text/', 'application/pdf', 'application/json')
WORD_MIMETYPES = (
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/msword',
)
_logger = logging.getLogger(__name__)


class DmsDocument(models.Model):
    _name = 'dms.document'
    _description = 'Document'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(
        string='Enabled', default=True, tracking=True,
        help="Disabled documents are hidden from Viewers and cannot be previewed or downloaded by them. "
             "Admins can still find them with the Disabled filter and enable them again.")
    folder_id = fields.Many2one(
        'dms.folder', string='Folder', required=False, index=True, ondelete='restrict', tracking=True,
        default=lambda self: self._default_folder())
    tag_ids = fields.Many2many('dms.tag', 'dms_document_tag_rel', 'document_id', 'tag_id', string='Tags')
    description = fields.Text()
    company_id = fields.Many2one(related='folder_id.company_id', store=True, index=True)
    file = fields.Binary(string='File', attachment=False, copy=False, prefetch=False)
    file_name = fields.Char(string='File Name', index=True)
    thumbnail = fields.Binary(
        attachment=False, readonly=True, copy=False, prefetch=False,
        help="Small copy of an image, so cards and lists never have to load and resize the full file.")
    mimetype = fields.Char(readonly=True, index=True)
    extension = fields.Char(compute='_compute_extension', store=True)
    file_size = fields.Integer(string='Size (bytes)', readonly=True)
    file_size_human = fields.Char(string='Size', compute='_compute_file_size_human')
    checksum = fields.Char(readonly=True, index=True)
    is_image = fields.Boolean(compute='_compute_is_image', store=True)
    is_viewable = fields.Boolean(compute='_compute_is_image', store=True)
    is_word = fields.Boolean(compute='_compute_is_word', store=True)
    has_duplicate = fields.Boolean(compute='_compute_has_duplicate')
    status = fields.Selection(
        [('enabled', 'Enabled'), ('disabled', 'Disabled')], string='Status',
        compute='_compute_status', store=True, index=True)
    disabled_by_folder = fields.Boolean(
        copy=False, help="Disabled because its folder was disabled; enabled again with the folder.")
    # linked record
    res_model = fields.Char(string='Linked Model', index=True)
    res_id = fields.Many2oneReference(string='Linked Record', model_field='res_model', index=True)
    res_name = fields.Char(string='Linked To', compute='_compute_res_name')
    # versions
    version_no = fields.Integer(string='Version', default=1, readonly=True, copy=False)
    version_ids = fields.One2many('dms.document.version', 'document_id', string='Previous Versions')
    version_count = fields.Integer(compute='_compute_version_count')
    source_attachment_id = fields.Many2one(
        'ir.attachment', string='Source Attachment', ondelete='set null', copy=False, readonly=True, index='btree_not_null')
    content_search = fields.Char(
        string='File Contents', compute='_compute_content_search', search='_search_content')
    # access control
    allow_download = fields.Boolean(
        string='Allow Download', default=True,
        help="If unchecked, users can only preview the file — Download is blocked.")
    file_password = fields.Char(
        string='File Password',
        help="If set, users must enter this password before viewing or downloading.")

    # Custom per-document permission fields (when created without folder or with separate permissions)
    custom_permission = fields.Boolean(
        string='Custom Permission', default=False,
        help="If checked, this document uses its own permission rules rather than folder access.")
    is_restricted = fields.Boolean(
        string='Restricted', default=False,
        help="If checked, only authorized users/groups/departments/units can access this document.")
    read_user_ids = fields.Many2many(
        'res.users', 'dms_doc_read_user_rel', 'doc_id', 'user_id', string='Allowed Users',
        domain=[('share', '=', False)])
    read_group_ids = fields.Many2many(
        'res.groups', 'dms_doc_read_group_rel', 'doc_id', 'group_id', string='Allowed Groups')
    read_department_ids = fields.Many2many(
        'hr.department', 'dms_doc_read_dept_rel', 'doc_id', 'dept_id', string='Allowed Departments')
    read_operating_unit_ids = fields.Many2many(
        'operating.unit', 'dms_doc_read_ou_rel', 'doc_id', 'ou_id', string='Allowed Operating Units')

    # -------------------------------------------------------------- defaults
    @api.model
    def _default_folder(self):
        folder_id = self.env.context.get('default_folder_id')
        if folder_id:
            return folder_id
        inbox = self.env.ref('documents_lite.dms_folder_inbox', raise_if_not_found=False)
        return inbox.id if inbox and inbox.has_access('read') else False

    # -------------------------------------------------------------- computes
    @api.depends('file_name', 'name')
    def _compute_extension(self):
        for doc in self:
            fname = doc.file_name or doc.name or ''
            doc.extension = fname.rsplit('.', 1)[-1].lower()[:8] if '.' in fname else ''

    @api.depends('file_size')
    def _compute_file_size_human(self):
        for doc in self:
            size = float(doc.file_size or 0)
            for unit in ('B', 'KB', 'MB', 'GB'):
                if size < 1024 or unit == 'GB':
                    doc.file_size_human = f'{int(size)} {unit}' if unit == 'B' else f'{size:.1f} {unit}'
                    break
                size /= 1024

    @api.depends('active')
    def _compute_status(self):
        for doc in self:
            doc.status = 'enabled' if doc.active else 'disabled'

    @api.depends('mimetype')
    def _compute_is_image(self):
        for doc in self:
            mime = doc.mimetype or ''
            doc.is_image = mime in IMAGE_MIMETYPES
            doc.is_viewable = mime.startswith(VIEWABLE_PREFIXES)

    @api.depends('extension', 'mimetype')
    def _compute_is_word(self):
        for doc in self:
            ext = (doc.extension or '').lower()
            mime = (doc.mimetype or '').lower()
            doc.is_word = ext in ('doc', 'docx') or mime in WORD_MIMETYPES

    def _compute_has_duplicate(self):
        sums = {c for c in self.mapped('checksum') if c}
        counts = {}
        if sums:
            data = self.env['dms.document']._read_group([('checksum', 'in', list(sums))], ['checksum'], ['__count'])
            counts = dict(data)
        for doc in self:
            doc.has_duplicate = bool(doc.checksum) and counts.get(doc.checksum, 0) > 1

    @api.depends('res_model', 'res_id')
    def _compute_res_name(self):
        """One query per linked model (not per document) for the whole page of records."""
        wanted = defaultdict(set)
        for doc in self:
            if doc.res_model and doc.res_id and doc.res_model in self.env:
                wanted[doc.res_model].add(doc.res_id)
        names = {}
        for model, ids in wanted.items():
            try:
                for rec in self.env[model].browse(ids).exists():
                    names[(model, rec.id)] = rec.display_name
            except AccessError:
                for res_id in ids:
                    try:
                        rec = self.env[model].browse(res_id).exists()
                        names[(model, res_id)] = rec.display_name if rec else False
                    except AccessError:
                        names[(model, res_id)] = _('Restricted record')
        for doc in self:
            doc.res_name = names.get((doc.res_model, doc.res_id)) or False

    @api.depends('version_ids')
    def _compute_version_count(self):
        data = self.env['dms.document.version']._read_group(
            [('document_id', 'in', self.ids)], ['document_id'], ['__count'])
        counts = {doc.id: count for doc, count in data}
        for doc in self:
            doc.version_count = counts.get(doc.id, 0)

    def _compute_content_search(self):
        self.content_search = False

    @api.model
    def _search_content(self, operator, value):
        """Search inside the text extracted by Odoo from PDFs and text files."""
        if operator not in ('ilike', 'like', '=', '!=', 'not ilike') or not value:
            return [('id', '=', 0)] if operator in ('ilike', 'like', '=') else []
        attachments = self.env['ir.attachment'].sudo().search_fetch(
            [('res_model', '=', 'dms.document'), ('res_field', '=', 'file'),
             ('index_content', 'ilike', value)], ['res_id'])
        return [('id', 'in' if operator != 'not ilike' else 'not in', attachments.mapped('res_id'))]

    # -------------------------------------------------------------- file meta & configuration
    @api.model
    def _get_dms_settings(self):
        """Helper to get active DMS settings with safe fallbacks."""
        if 'dms.config.settings' in self.env:
            try:
                return self.env['dms.config.settings'].get_settings()
            except Exception:
                pass
        return None

    @api.model
    def _max_file_size(self):
        """Limit in bytes. Reads from dedicated DMS configuration."""
        settings = self._get_dms_settings()
        if settings and settings.max_file_size_mb:
            return settings.max_file_size_mb * 1024 * 1024
        mb = int(self.env['ir.config_parameter'].sudo().get_param('documents_lite.max_file_size_mb', 25))
        return mb * 1024 * 1024

    @api.model
    def _max_files_per_folder(self):
        """Max documents per folder (0 = unlimited). Reads from dedicated DMS configuration."""
        settings = self._get_dms_settings()
        if settings is not None:
            return settings.max_files_per_folder
        return int(self.env['ir.config_parameter'].sudo().get_param('documents_lite.max_files_per_folder', 500))

    @api.model
    def _get_allowed_extensions(self):
        """Returns set of allowed file extensions (lowercase) configured in DMS settings."""
        settings = self._get_dms_settings()
        if settings:
            if settings.allow_all_extensions:
                return set()  # Empty set denotes all allowed
            if settings.allowed_extensions and settings.allowed_extensions.strip():
                return {ext.strip().lstrip('.').lower() for ext in settings.allowed_extensions.split(',') if ext.strip()}
        param = self.env['ir.config_parameter'].sudo().get_param('documents_lite.allowed_extensions', '')
        if param and param.strip():
            exts = {ext.strip().lstrip('.').lower() for ext in param.split(',') if ext.strip()}
            if exts:
                return exts
        return set(ALLOWED_FILE_KINDS.keys())

    @api.model
    def _check_file_type(self, raw, name):
        """Only allowed extensions are accepted; the content must match the extension."""
        name = name or ''
        ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
        allowed_exts = self._get_allowed_extensions()
        if allowed_exts:
            if not ext or ext not in allowed_exts:
                allowed_label = ', '.join(sorted(allowed_exts)).upper()
                raise ValidationError(_(
                    '"%(name)s" is not an allowed file type. Only files with extension (%(allowed)s) can be uploaded.',
                    name=name, allowed=allowed_label))
        kind = ALLOWED_FILE_KINDS.get(ext)
        if kind:
            head = raw[:16]
            if kind == 'pdf':
                ok = b'%PDF-' in raw[:1024]
            elif kind == 'image':
                ok = (head.startswith((b'\x89PNG\r\n\x1a\n', b'\xff\xd8\xff', b'GIF87a', b'GIF89a', b'BM'))
                      or (head[:4] == b'RIFF' and head[8:12] == b'WEBP'))
            elif kind == 'zip':
                ok = head.startswith(b'PK\x03\x04')
            elif kind == 'ole':
                ok = head.startswith(OLE_MAGIC)
            elif kind == 'rtf':
                ok = head.startswith(b'{\\rtf')
            else:  # txt, csv
                ok = b'\x00' not in raw[:8192]
            if not ok:
                raise ValidationError(_(
                    'The content of "%(name)s" does not match its file type (.%(ext)s).', name=name, ext=ext))

    @api.model
    def _is_file_allowed(self, raw, name):
        """True when the bytes pass the size and type checks (used to skip files silently)."""
        try:
            if len(raw or b'') > self._max_file_size():
                return False
            self._check_file_type(raw or b'', name)
        except ValidationError:
            return False
        return True

    @api.model
    def _file_meta(self, value, name):
        """Mimetype, size and checksum of a value for the ``file`` field."""
        raw = base64.b64decode(value) if value else b''
        if len(raw) > self._max_file_size():
            raise ValidationError(_(
                'The file is %(size).1f MB. The maximum allowed size is %(max)d MB.',
                size=len(raw) / 1048576, max=self._max_file_size() // 1048576))
        if not raw:
            return {'mimetype': False, 'file_size': 0, 'checksum': False, 'thumbnail': False}
        if not self.env.context.get('dms_skip_file_check'):
            self._check_file_type(raw, name)
        mimetype = guess_mimetype(raw, default='application/octet-stream')
        if mimetype in ('application/octet-stream', 'application/zip', 'text/plain') and name:
            mimetype = mimetypes.guess_type(name)[0] or mimetype
        return {'mimetype': mimetype, 'file_size': len(raw), 'checksum': sha1(raw).hexdigest(),
                'thumbnail': self._make_thumbnail(raw, mimetype)}

    @api.model
    def _make_thumbnail(self, raw, mimetype):
        """A small version of an image (base64) or False. Never blocks an upload."""
        if mimetype not in THUMBNAIL_MIMETYPES:
            return False
        try:
            return base64.b64encode(image_process(raw, size=THUMBNAIL_SIZE, quality=80))
        except Exception:  # corrupt or unusual image: the card just shows its icon
            return False

    @api.model
    def _dms_backfill_thumbnails(self):
        """Create the thumbnail of images uploaded before thumbnails existed (cheap when none)."""
        docs = self.with_context(active_test=False).search(
            [('mimetype', 'in', list(THUMBNAIL_MIMETYPES)), ('thumbnail', '=', False)])
        for ids in split_every(50, docs.ids):
            for doc in self.with_context(active_test=False).browse(ids):
                if doc.file:
                    thumb = self._make_thumbnail(base64.b64decode(doc.file), doc.mimetype)
                    if thumb:
                        doc.thumbnail = thumb
            self.env.invalidate_all()  # do not keep the big files in memory

    @api.model_create_multi
    def create(self, vals_list):
        max_files = self._max_files_per_folder()
        folder_counts = {}
        for vals in vals_list:
            fid = vals.get('folder_id')
            if fid and max_files > 0:
                if fid not in folder_counts:
                    folder_counts[fid] = self.search_count([('folder_id', '=', fid), ('active', '=', True)])
                if folder_counts[fid] >= max_files:
                    folder = self.env['dms.folder'].browse(fid)
                    raise ValidationError(_(
                        'Folder "%(folder)s" has reached its maximum file limit of %(max)d documents.',
                        folder=folder.name, max=max_files
                    ))
                folder_counts[fid] += 1
            if vals.get('file'):
                vals.setdefault('file_name', vals.get('name'))
                vals.update(self._file_meta(vals['file'], vals.get('file_name') or vals.get('name')))
            if not vals.get('name') and vals.get('file_name'):
                vals['name'] = vals['file_name']
        docs = super().create(vals_list)
        return docs

    def write(self, vals):
        if 'folder_id' in vals and vals['folder_id']:
            fid = vals['folder_id']
            max_files = self._max_files_per_folder()
            if max_files > 0:
                current_count = self.search_count([('folder_id', '=', fid), ('active', '=', True), ('id', 'not in', self.ids)])
                if current_count + len(self) > max_files:
                    folder = self.env['dms.folder'].browse(fid)
                    raise ValidationError(_(
                        'Cannot move documents to folder "%(folder)s". It exceeds the maximum file limit of %(max)d documents.',
                        folder=folder.name, max=max_files
                    ))
        if 'active' in vals and not self.env.context.get('dms_cascade'):
            if vals['active'] and any(doc.folder_id and not doc.folder_id.active for doc in self):
                raise UserError(_('Enable the folder first: this document is inside a disabled folder.'))
            vals = dict(vals, disabled_by_folder=False)  # a manual choice wins over the folder's
        if 'file' in vals:
            if vals['file']:
                if len(self) > 1:
                    raise UserError(_('Replace the file of one document at a time.'))
                name = vals.get('file_name') or self.file_name or self.name
                vals = dict(vals, **self._file_meta(vals['file'], name))
                vals.setdefault('file_name', name)
                if self.file and not self.env.context.get('dms_skip_version'):
                    self._archive_current_file()
                    vals['version_no'] = self.version_no + 1
            else:
                vals = dict(vals, mimetype=False, file_size=0, checksum=False, thumbnail=False)
        return super().write(vals)

    def _archive_current_file(self):
        self.ensure_one()
        self.env['dms.document.version'].create({
            'document_id': self.id,
            'version_no': self.version_no,
            'file': self.file,
            'file_name': self.file_name or self.name,
            'mimetype': self.mimetype,
            'file_size': self.file_size,
            'checksum': self.checksum,
        })
        self.message_post(body=_('Replaced version %(v)s with a new file.', v=self.version_no))

    def copy_data(self, default=None):
        vals_list = super().copy_data(default)
        for doc, vals in zip(self, vals_list):
            if 'name' not in (default or {}):
                vals['name'] = _('%s (copy)', doc.name)
            vals['file'] = doc.file
        return vals_list

    # -------------------------------------------------------------- actions
    def _dms_can_download(self):
        """Admins can always download; everybody else only when Allow Download is ticked."""
        self.ensure_one()
        return self.allow_download or self.env.user.has_group('documents_lite.group_dms_manager')

    def action_download(self):
        self.ensure_one()
        if not self._dms_can_download():
            raise UserError(_('Downloading this document is not allowed.'))
        return {'type': 'ir.actions.act_url',
                'url': f'/web/content/dms.document/{self.id}/file?download=true', 'target': 'self'}

    def action_disable(self):
        """Hide the documents from Viewers (Admins can enable them again)."""
        for doc in self:
            doc.message_post(body=_('Document disabled by %s.', self.env.user.name))
        self.write({'active': False})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Document Disabled'),
                'message': _('Document "%(name)s" disabled successfully.', name=self.name if len(self) == 1 else _('%d documents', len(self))),
                'type': 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_enable(self):
        self.write({'active': True})
        for doc in self:
            doc.message_post(body=_('Document enabled by %s.', self.env.user.name))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Document Enabled'),
                'message': _('Document "%(name)s" enabled successfully.', name=self.name if len(self) == 1 else _('%d documents', len(self))),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def action_open_details(self):
        """Open the full record (form) straight from the card menu, without the preview."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'res_model': 'dms.document', 'res_id': self.id,
            'views': [(False, 'form')], 'target': 'current',
        }

    def action_open_versions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Versions'), 'res_model': 'dms.document.version',
            'view_mode': 'list,form', 'domain': [('document_id', '=', self.id)],
            'context': {'default_document_id': self.id},
        }

    def action_open_linked_record(self):
        self.ensure_one()
        if not (self.res_model and self.res_id and self.res_model in self.env):
            raise UserError(_('This document is not linked to a record.'))
        return {'type': 'ir.actions.act_window', 'res_model': self.res_model, 'res_id': self.res_id,
                'view_mode': 'form', 'target': 'current'}

    def action_open_duplicates(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Duplicates'), 'res_model': 'dms.document',
            'view_mode': 'kanban,list,form', 'domain': [('checksum', '=', self.checksum)],
        }

    @api.model
    def dms_create_from_upload(self, files, folder=None, res_model=None, res_id=None, tags=None):
        """Create documents from werkzeug FileStorage objects (used by the upload route)."""
        docs = self.browse()
        for ufile in files:
            raw = ufile.read()
            vals = {
                'name': ufile.filename or _('Untitled'),
                'file_name': ufile.filename,
                'file': base64.b64encode(raw).decode(),
                'folder_id': folder.id if folder else self._default_folder(),
            }
            if res_model and res_id:
                vals.update(res_model=res_model, res_id=res_id)
            if tags:
                vals['tag_ids'] = [(6, 0, tags.ids)]
            docs |= self.create(vals)
        return docs


class DmsDocumentVersion(models.Model):
    _name = 'dms.document.version'
    _description = 'Document Version'
    _order = 'document_id, version_no desc'

    document_id = fields.Many2one('dms.document', required=True, ondelete='cascade', index=True)
    version_no = fields.Integer(string='Version', required=True, index=True)
    file = fields.Binary(attachment=False, prefetch=False)
    file_name = fields.Char()
    mimetype = fields.Char(index=True)
    file_size = fields.Integer(string='Size (bytes)')
    checksum = fields.Char(index=True)
    replaced_by_id = fields.Many2one('res.users', string='Replaced By', default=lambda self: self.env.user)
    replaced_on = fields.Datetime(default=fields.Datetime.now)

    def action_restore(self):
        """Make this version current again. The version being replaced is kept as a new version."""
        self.ensure_one()
        doc = self.document_id
        doc.with_context(dms_skip_file_check=True).write({'file': self.file, 'file_name': self.file_name})
        doc.message_post(body=_('Restored the file of version %(v)s.', v=self.version_no))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Version Restored'),
                'message': _('Version %(v)s restored successfully for "%(name)s".', v=self.version_no, name=doc.name),
                'type': 'success',
                'sticky': False,
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': 'dms.document',
                    'res_id': doc.id,
                    'view_mode': 'form',
                    'target': 'current',
                },
            },
        }

    def action_download(self):
        self.ensure_one()
        if not self.document_id._dms_can_download():
            raise UserError(_('Downloading this document is not allowed.'))
        return {'type': 'ir.actions.act_url',
                'url': f'/web/content/dms.document.version/{self.id}/file?download=true', 'target': 'self'}
