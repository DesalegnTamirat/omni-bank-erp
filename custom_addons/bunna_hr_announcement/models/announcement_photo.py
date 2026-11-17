# -*- coding: utf-8 -*-
import base64
import io
import logging

from PIL import Image, ImageOps

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .announcement_settings import LIMITS

_logger = logging.getLogger(__name__)

MAX_PIXELS = 50000000       # refuse absurdly large images (decompression bombs)
ALLOWED_FORMATS = {'JPEG', 'PNG', 'WEBP'}

_RESAMPLE = Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else Image.LANCZOS


def _encode(img, fmt, max_px, quality, as_thumbnail=False):
    """Resize and re-encode from the pixels only: camera/GPS data and other hidden metadata are dropped."""
    work = img.copy()
    work.thumbnail((max_px, max_px), _RESAMPLE)
    out = io.BytesIO()
    if as_thumbnail or fmt == 'JPEG':
        if work.mode in ('RGBA', 'LA', 'P'):
            work = work.convert('RGBA')
            background = Image.new('RGB', work.size, (255, 255, 255))
            background.paste(work, mask=work.split()[-1])
            work = background
        elif work.mode != 'RGB':
            work = work.convert('RGB')
        work.save(out, 'JPEG', quality=quality, optimize=True)
    elif fmt == 'PNG':
        work.save(out, 'PNG', optimize=True)
    else:
        work.save(out, 'WEBP', quality=quality)
    return out.getvalue()


def process_photo(raw, max_mb, full_px=1600, thumb_px=480, quality=85):
    """Return (full, thumbnail) bytes, or raise ValueError with a message a person can act on."""
    if len(raw) > max_mb * 1024 * 1024:
        raise ValueError(_("the file is larger than %s MB.", max_mb))
    try:
        img = Image.open(io.BytesIO(raw))
        fmt = img.format
    except Exception:
        raise ValueError(_("this is not a picture file."))
    if fmt not in ALLOWED_FORMATS:
        raise ValueError(_("only PNG, JPG and WebP pictures are allowed."))
    if img.width * img.height > MAX_PIXELS:
        raise ValueError(_("the picture is too large (more than 50 megapixels)."))
    try:
        img.load()
        turned = ImageOps.exif_transpose(img)  # apply the camera's rotation before the data is dropped
        img = turned if turned is not None else img
        return (_encode(img, fmt, full_px, quality),
                _encode(img, fmt, thumb_px, max(50, quality - 5), as_thumbnail=True))
    except Exception:
        _logger.warning("bunna announcement: could not process a photo", exc_info=True)
        raise ValueError(_("the picture could not be read."))


class BunnaAnnouncementPhoto(models.Model):
    _name = 'bunna.announcement.photo'
    _description = 'Announcement Photo'
    _order = 'sequence, id'

    announcement_id = fields.Many2one(
        'bunna.announcement', string='Announcement', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    # attachment=False: the picture is kept in the database itself (a column of this table),
    # not in the file store, so a database backup contains the photos. Not loaded unless asked for.
    image = fields.Binary(string='Photo', attachment=False, prefetch=False)
    thumb = fields.Binary(string='Thumbnail', attachment=False, prefetch=False)
    caption = fields.Char(string='Caption')
    has_image = fields.Boolean(compute='_compute_has_image', store=True)
    cache_key = fields.Char(compute='_compute_cache_key')

    @api.depends('image')
    def _compute_has_image(self):
        for rec in self:
            rec.has_image = bool(rec.image)

    @api.depends('write_date')
    def _compute_cache_key(self):
        for rec in self:
            rec.cache_key = str(int(rec.write_date.timestamp())) if rec.write_date else '0'

    @api.model
    def _prepare_vals(self, vals):
        if vals.get('image'):
            cfg = self.env['bunna.announcement.settings']._get_settings()

            def setting(name):
                return cfg[name] if cfg else LIMITS[name][0]

            try:
                full, thumb = process_photo(
                    base64.b64decode(vals['image']), setting('gallery_max_photo_mb'),
                    full_px=setting('gallery_max_px'), thumb_px=setting('gallery_thumb_px'),
                    quality=setting('gallery_quality'))
            except ValueError as error:
                raise ValidationError(_("Photos: %s", str(error)))
            vals = dict(vals, image=base64.b64encode(full), thumb=base64.b64encode(thumb))
        elif 'image' in vals:
            vals = dict(vals, thumb=False)
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._prepare_vals(vals) for vals in vals_list])

    def write(self, vals):
        return super().write(self._prepare_vals(vals))
