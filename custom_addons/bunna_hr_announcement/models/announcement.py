# -*- coding: utf-8 -*-
import base64
import hashlib
import logging
import re
from datetime import timedelta

import pytz
from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import html2plaintext
from odoo.tools.mimetypes import guess_mimetype

from .. import helpers
from .announcement_settings import LIMITS

DEFAULT_FOOTER = "For any questions, please contact the Human Resources Department."
LINK_RE = re.compile(r'^(https?://\S+|/\S*)$', re.IGNORECASE)
ALLOWED_IMAGE_MIMETYPES = {'image/png', 'image/jpeg', 'image/gif', 'image/webp'}
# A publish date may be 'now' typed a few minutes ago, but never earlier than this
PUBLISH_DATE_GRACE = timedelta(minutes=5)
COMPLETENESS_FIELDS = {
    'name', 'summary', 'body', 'category_id', 'priority_id', 'date_published', 'date_expire',
    'link_url', 'link_label', 'footer_note', 'signed_by', 'attachment_ids', 'photo_ids',
}
# Changing any of these on a published announcement is written to the audit log
AUDITED_FIELDS = {
    'name', 'summary', 'body', 'category_id', 'priority_id', 'date_published', 'date_expire',
    'link_url', 'link_label', 'footer_note', 'signed_by', 'image', 'attachment_ids', 'photo_ids',
    'allow_download', 'allow_comments',
}
_logger = logging.getLogger(__name__)
GROUP_DRAFTER = 'bunna_hr_announcement.group_announcement_drafter'
GROUP_PUBLISHER = 'bunna_hr_announcement.group_announcement_publisher'
GROUP_ADMIN = 'bunna_hr_announcement.group_announcement_manager'


class BunnaAnnouncement(models.Model):
    _name = 'bunna.announcement'
    _description = 'Website Announcement'
    _inherit = ['mail.thread']
    _order = 'date_published desc, id desc'
    _mail_post_access = 'read'  # anyone who can see a post may comment in its history

    @api.model
    def _default_category(self):
        return self.env['bunna.announcement.category'].search([], limit=1).id

    @api.model
    def _default_priority(self):
        return self.env['bunna.announcement.priority'].search([], limit=1).id

    @api.model
    def _default_allow_comments(self):
        return bool(self.env['bunna.announcement.settings'].get_value('comments_default_allow'))

    @api.model
    def _default_signed_by(self):
        return self.env['bunna.announcement.settings'].get_default_signed_by()

    # ---- Header -------------------------------------------------------
    name = fields.Char(string='Title', tracking=True)
    summary = fields.Text(
        string='Summary',
        help="One or two lines shown on the announcements list page. "
             "If empty, the beginning of the content is used.")
    category_id = fields.Many2one(
        'bunna.announcement.category', string='Category',
        default=_default_category, tracking=True, ondelete='restrict', index=True)
    priority_id = fields.Many2one(
        'bunna.announcement.priority', string='Priority',
        default=_default_priority, tracking=True, ondelete='restrict', index=True)
    is_highlighted = fields.Boolean(related='priority_id.is_highlighted', string='Highlighted')
    image = fields.Image(
        string='Cover Image', max_width=1280, max_height=1280,
        help="Optional. Shown before the text on the website. "
             "If empty, the category icon is shown instead.")
    image_256 = fields.Image(
        related='image', max_width=256, max_height=256, store=True, string='Thumbnail')
    has_image = fields.Boolean(compute='_compute_has_image', store=True)

    # ---- Content ------------------------------------------------------
    body = fields.Html(string='Content', sanitize=True)

    # ---- Optional link ------------------------------------------------
    link_url = fields.Char(
        string='Link URL',
        help="Optional. Shown as a button on the announcement page. "
             "Use a full address (https://...) or a site path (/jobs).")
    link_label = fields.Char(string='Button Text', help="Defaults to 'Open link'.")

    # ---- Attachments --------------------------------------------------
    attachment_ids = fields.One2many(
        'bunna.announcement.attachment', 'announcement_id', string='Attachments')
    attachment_count = fields.Integer(compute='_compute_attachment_count')
    photo_ids = fields.One2many('bunna.announcement.photo', 'announcement_id', string='Photos')
    photo_count = fields.Integer(compute='_compute_photo_count')
    allow_download = fields.Boolean(
        string='Allow Download', default=True, tracking=True,
        help="On: employees can view and download the attachments.\n"
             "Off: employees can only view PDF/image attachments in the browser.")

    # ---- Footer -------------------------------------------------------
    footer_note = fields.Text(string='Footer Note', default=DEFAULT_FOOTER)
    signed_by = fields.Char(string='Signed By', default=_default_signed_by)

    # ---- Publishing ---------------------------------------------------
    state = fields.Selection(
        [('draft', 'Draft'), ('published', 'Published'), ('revoked', 'Revoked')],
        string='Status', default='draft', required=True, tracking=True, copy=False, index=True)
    date_published = fields.Datetime(
        string='Publish Date', copy=False, tracking=True, index=True,
        help="Shown on the website from this date. Leave empty to publish immediately.")
    date_expire = fields.Datetime(
        string='Expiry Date', tracking=True, index=True,
        help="Optional. After this date the announcement disappears from the website.")
    author_id = fields.Many2one(
        'res.users', string='Created By', default=lambda self: self.env.user,
        readonly=True, copy=False)
    published_by = fields.Many2one('res.users', string='Published By', readonly=True, copy=False)
    revoked_by = fields.Many2one('res.users', string='Revoked By', readonly=True, copy=False)

    is_visible_on_website = fields.Boolean(
        string='Visible on Website', compute='_compute_is_visible_on_website')
    excerpt = fields.Text(string='Excerpt', compute='_compute_excerpt')
    live_status = fields.Selection(
        [('draft', 'Draft'), ('scheduled', 'Scheduled'), ('live', 'Live'),
         ('expired', 'Expired'), ('revoked', 'Revoked')],
        string='Website Status', compute='_compute_live_status', search='_search_live_status',
        help="What employees see right now: Live = visible on the website, "
             "Scheduled = waiting for its publish date, Expired = past its expiry date.")
    active = fields.Boolean(default=True, tracking=True,
                            help="Archive an announcement to hide it everywhere without deleting it.")
    can_edit = fields.Boolean(compute='_compute_can_edit')
    is_new = fields.Boolean(compute='_compute_is_new')
    allow_comments = fields.Boolean(
        string='Allow Comments', default=_default_allow_comments, tracking=True,
        help="Readers can send anonymous comments, which appear only after a moderator approves them. "
             "The starting value comes from Website Settings. A Publisher can open or close comments "
             "at any time, also after publishing.")
    comment_ids = fields.One2many('bunna.announcement.comment', 'announcement_id', string='Comments')
    comment_count = fields.Integer(string='Visible Comments', compute='_compute_comment_counts')
    comment_pending_count = fields.Integer(string='Waiting for Review', compute='_compute_comment_counts')
    comment_last_alert = fields.Datetime(copy=False, readonly=True)
    search_text = fields.Text(compute='_compute_search_text', store=True)
    view_count = fields.Integer(string='Views', compute='_compute_view_stats')
    unique_visitor_count = fields.Integer(string='Visitors', compute='_compute_view_stats')
    file_open_count = fields.Integer(string='File Opens', compute='_compute_view_stats')
    download_count = fields.Integer(string='Downloads', compute='_compute_view_stats')

    def _check_complete(self, check_publish_date=False, check_duplicates=False, intro=None):
        """One message listing EVERY field that is empty or wrong (not just the first one).

        Limits come from Announcements > Configuration > Website Settings.
        """
        settings = self.env['bunna.announcement.settings']
        cfg = settings._get_settings()

        def limit(name):
            return cfg[name] if cfg else LIMITS[name][0]

        block_duplicates = cfg.block_duplicate_titles if cfg else True
        now = fields.Datetime.now()
        for rec in self:
            problems = []

            # ---- Header ----
            title = (rec.name or '').strip()
            if not title:
                problems.append(_("Title: please enter a title."))
            elif len(title) > limit('title_max_length'):
                problems.append(_("Title: at most %(max)s characters (now %(now)s).",
                                  max=limit('title_max_length'), now=len(title)))
            elif check_duplicates and block_duplicates:
                escaped = title.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
                duplicate = self.sudo().search([
                    ('id', '!=', rec.id), ('name', '=ilike', escaped), ('state', '=', 'published'),
                    '|', ('date_expire', '=', False), ('date_expire', '>', now)], limit=1)
                if duplicate:
                    problems.append(_("Title: another live or scheduled announcement already uses this title."))
            if not rec.category_id:
                problems.append(_("Category: please choose a category."))
            if not rec.priority_id:
                problems.append(_("Priority: please choose a priority."))
            summary = (rec.summary or '').strip()
            if not summary:
                problems.append(_("Summary: please write a short summary (one or two lines)."))
            elif len(summary) > limit('summary_max_length'):
                problems.append(_("Summary: at most %(max)s characters (now %(now)s).",
                                  max=limit('summary_max_length'), now=len(summary)))

            # ---- Content ----
            text = ' '.join(html2plaintext(rec.body or '').split())
            if not text:
                problems.append(_("Content: please write the announcement text."))
            elif len(text) < limit('content_min_length'):
                problems.append(_("Content: write at least %(min)s characters (now %(now)s).",
                                  min=limit('content_min_length'), now=len(text)))

            # ---- Dates ----
            if rec.date_published and check_publish_date:
                if rec.date_published < now - PUBLISH_DATE_GRACE:
                    problems.append(_("Publish Date: must be now or a future date and time (past dates are not allowed)."))
                elif rec.date_published > now + timedelta(days=limit('publish_max_days_ahead')):
                    problems.append(_("Publish Date: cannot be more than %s days ahead.",
                                      limit('publish_max_days_ahead')))
            if rec.date_expire:
                start = rec.date_published or now
                start_label = _("the Publish Date") if rec.date_published else _("now")
                if rec.date_expire <= start:
                    problems.append(_("Expiry Date: must be later than %s.", start_label))
                elif rec.date_expire < start + timedelta(minutes=limit('expiry_min_minutes')):
                    problems.append(_(
                        "Expiry Date: must be at least %s minutes after %s "
                        "(to take a live post down right away use Expire Now).",
                        limit('expiry_min_minutes'), start_label))
                elif rec.date_expire > start + timedelta(days=limit('expiry_max_days')):
                    problems.append(_("Expiry Date: must be within %(days)s days after %(start)s.",
                                      days=limit('expiry_max_days'), start=start_label))
            elif rec.category_id.expiry_required:
                problems.append(_("Expiry Date: required for the category '%s'.", rec.category_id.name))

            # ---- Link, footer ----
            link = (rec.link_url or '').strip()
            if link and not LINK_RE.match(link):
                # Only http(s) links or site paths: blocks javascript:/data: URLs.
                problems.append(_("Link URL: must start with http://, https:// or / (a page on this website)."))
            if rec.link_label and not link:
                problems.append(_("Link URL: required because Button Text is filled in."))
            if len(rec.link_label or '') > limit('button_text_max_length'):
                problems.append(_("Button Text: at most %s characters.", limit('button_text_max_length')))
            if len(rec.footer_note or '') > limit('footer_note_max_length'):
                problems.append(_("Footer Note: at most %(max)s characters (now %(now)s).",
                                  max=limit('footer_note_max_length'), now=len(rec.footer_note)))
            if len(rec.signed_by or '') > limit('signed_by_max_length'):
                problems.append(_("Signed By: at most %(max)s characters (now %(now)s).",
                                  max=limit('signed_by_max_length'), now=len(rec.signed_by)))

            # ---- Attachments ----
            seen_names = set()
            total_size = 0
            for index, line in enumerate(rec.attachment_ids, start=1):
                if not line.file_size:
                    problems.append(_("Attachments: row %s has no file. Choose a file or remove the row.", index))
                    continue
                total_size += line.file_size
                key = (line.file_name or '').strip().lower()
                if key in seen_names:
                    problems.append(_("Attachments: '%s' is attached more than once.", line.file_name))
                seen_names.add(key)
            if total_size > limit('max_total_mb') * 1024 * 1024:
                problems.append(_("Attachments: total size %(now).1f MB is more than the %(max)s MB allowed per announcement.",
                                  now=total_size / (1024 * 1024), max=limit('max_total_mb')))

            # ---- Photo gallery ----
            photos = rec.photo_ids
            if len(photos) > limit('gallery_max_photos'):
                problems.append(_("Photos: at most %s photos per announcement.", limit('gallery_max_photos')))
            for index, photo in enumerate(photos, start=1):
                if not photo.has_image:
                    problems.append(_("Photos: row %s has no picture. Choose a photo or remove the row.", index))
                elif len(photo.caption or '') > limit('gallery_caption_max'):
                    problems.append(_("Photos: the caption of photo %(index)s is longer than %(max)s characters.",
                                      index=index, max=limit('gallery_caption_max')))

            if problems:
                raise ValidationError(
                    (intro or _("Please correct the following before saving:")) + "\n"
                    + "\n".join("- %s" % problem for problem in problems))

    @api.depends('image')
    def _compute_has_image(self):
        for rec in self:
            rec.has_image = bool(rec.image)

    @api.constrains('image')
    def _check_image_type(self):
        # Only common bitmap formats: SVG and other types are refused (safety).
        for rec in self:
            if rec.image:
                head = base64.b64decode(rec.image[:2048])
                if guess_mimetype(head) not in ALLOWED_IMAGE_MIMETYPES:
                    raise ValidationError(_("Cover Image: must be a PNG, JPG, GIF or WebP file."))

    @api.constrains('allow_download', 'attachment_ids')
    def _check_attachments(self):
        max_files = self.env['bunna.announcement.settings'].get_value('max_files')
        for rec in self:
            if len(rec.attachment_ids) > max_files:
                raise ValidationError(_("Attachments: an announcement can have at most %s files.", max_files))
            if not rec.allow_download and any(not a.is_viewable for a in rec.attachment_ids):
                raise ValidationError(_(
                    "Attachments: downloads are disabled, so files must be PDF or images "
                    "(Word and Excel files cannot be viewed online). "
                    "Remove those files or allow downloads."))

    @api.depends('attachment_ids')
    def _compute_attachment_count(self):
        for rec in self:
            rec.attachment_count = len(rec.attachment_ids)

    @api.depends('state', 'date_published', 'date_expire')
    def _compute_is_visible_on_website(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.is_visible_on_website = bool(
                rec.state == 'published'
                and (not rec.date_published or rec.date_published <= now)
                and (not rec.date_expire or rec.date_expire > now)
            )

    @api.depends('photo_ids.has_image')
    def _compute_photo_count(self):
        for rec in self:
            rec.photo_count = len(rec.photo_ids.filtered('has_image'))

    def _compute_comment_counts(self):
        counts = {}
        ids = [rec_id for rec_id in self.ids if isinstance(rec_id, int)]
        if ids:
            self.env['bunna.announcement.comment'].flush_model(['announcement_id', 'state'])
            self.env.cr.execute("""
                SELECT announcement_id, state, COUNT(*) FROM bunna_announcement_comment
                WHERE announcement_id IN %s GROUP BY announcement_id, state
            """, (tuple(ids),))
            for announcement_id, state, count in self.env.cr.fetchall():
                counts.setdefault(announcement_id, {})[state] = count
        for rec in self:
            per_state = counts.get(rec.id, {})
            rec.comment_count = per_state.get('approved', 0)
            rec.comment_pending_count = per_state.get('pending', 0)

    def _compute_view_stats(self):
        """Totals from the small daily counter table (one grouped query for all rows shown)."""
        stats = {}
        ids = [rec_id for rec_id in self.ids if isinstance(rec_id, int)]
        if ids:
            self.env.cr.execute("""
                SELECT announcement_id, SUM(views), SUM(unique_visitors), SUM(file_opens), SUM(downloads)
                FROM bunna_announcement_view_daily
                WHERE announcement_id IN %s
                GROUP BY announcement_id
            """, (tuple(ids),))
            stats = {row[0]: row[1:] for row in self.env.cr.fetchall()}
        for rec in self:
            views, visitors, opens, downloads = (int(v or 0) for v in stats.get(rec.id, (0, 0, 0, 0)))
            rec.view_count = views
            rec.unique_visitor_count = visitors
            rec.file_open_count = opens
            rec.download_count = downloads

    def action_open_view_stats(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Readership: %s", self.name),
            'res_model': 'bunna.announcement.view.daily',
            'view_mode': 'list,pivot,graph',
            'domain': [('announcement_id', '=', self.id)],
        }

    @api.depends('name', 'summary', 'body')
    def _compute_search_text(self):
        """Plain text of title + summary + content, so website search never matches hidden HTML."""
        for rec in self:
            content = ' '.join(html2plaintext(rec.body or '').split())
            rec.search_text = ' '.join(part for part in (rec.name, rec.summary, content) if part)

    @api.depends('state', 'date_published')
    def _compute_is_new(self):
        """Recently published: the website shows the card in green (duration set in Website Settings)."""
        settings = self.env['bunna.announcement.settings']
        duration = settings.get_value('new_duration')
        unit = settings.get_value('new_unit') or 'days'
        now = fields.Datetime.now()
        since = now - timedelta(**{unit: duration})
        for rec in self:
            rec.is_new = bool(
                duration and rec.state == 'published' and rec.date_published
                and since <= rec.date_published <= now)

    @api.depends('state', 'create_uid')
    @api.depends_context('uid')
    def _compute_can_edit(self):
        user = self.env.user
        is_admin = user.has_group(GROUP_ADMIN)
        is_drafter = user.has_group(GROUP_DRAFTER)
        for rec in self:
            if is_admin:
                rec.can_edit = True
            elif is_drafter:
                rec.can_edit = rec.state == 'draft' and (not rec.create_uid or rec.create_uid == user)
            else:
                rec.can_edit = False

    @api.depends('state', 'date_published', 'date_expire')
    def _compute_live_status(self):
        now = fields.Datetime.now()
        for rec in self:
            if rec.state != 'published':
                rec.live_status = rec.state  # draft / revoked
            elif rec.date_published and rec.date_published > now:
                rec.live_status = 'scheduled'
            elif rec.date_expire and rec.date_expire <= now:
                rec.live_status = 'expired'
            else:
                rec.live_status = 'live'

    @api.model
    def _search_live_status(self, operator, value):
        all_values = ['draft', 'scheduled', 'live', 'expired', 'revoked']
        # Odoo 19 passes a set-like value (OrderedSet) for '=' / 'in': accept any iterable but a string
        if isinstance(value, str) or not hasattr(value, '__iter__'):
            values = [value]
        else:
            values = list(value)
        if operator in ('=', 'in'):
            wanted = values
        elif operator in ('!=', 'not in'):
            wanted = [v for v in all_values if v not in values]
        else:
            raise UserError(_("This search is not supported on Website Status."))
        now = fields.Datetime.now()
        domains = {
            'draft': [('state', '=', 'draft')],
            'revoked': [('state', '=', 'revoked')],
            'scheduled': [('state', '=', 'published'), ('date_published', '>', now)],
            'expired': [('state', '=', 'published'), ('date_expire', '!=', False),
                        ('date_expire', '<=', now)],
            'live': [('state', '=', 'published'),
                     '|', ('date_published', '=', False), ('date_published', '<=', now),
                     '|', ('date_expire', '=', False), ('date_expire', '>', now)],
        }
        ids = set()
        for key in wanted:
            if key in domains:
                ids.update(self.search(domains[key]).ids)
        return [('id', 'in', list(ids))]

    @api.depends('summary', 'body')
    def _compute_excerpt(self):
        for rec in self:
            if rec.summary:
                rec.excerpt = rec.summary
                continue
            text = ' '.join(html2plaintext(rec.body or '').split())
            rec.excerpt = text[:220] + ('â€¦' if len(text) > 220 else '')

    @api.model
    def _website_domain(self, include_expired=False):
        """What visitors may see: published, already started and (unless include_expired) not expired.

        Draft and revoked announcements are never included.
        """
        now = fields.Datetime.now()
        domain = [('state', '=', 'published'), ('date_published', '<=', now)]
        if not include_expired:
            domain += ['|', ('date_expire', '=', False), ('date_expire', '>', now)]
        return domain

    # ---- Roles: enforced on the server, not only by hidden buttons ----------
    def _is_privileged(self):
        """Publishers (and the system itself) may change the publishing state."""
        return self.env.su or self.env.user.has_group(GROUP_PUBLISHER)

    def _check_publisher(self):
        if not self._is_privileged():
            raise AccessError(_("Only Announcement Publishers can publish, revoke or expire announcements."))

    @api.model_create_multi
    def create(self, vals_list):
        if not self._is_privileged():
            for vals in vals_list:
                if vals.get('state', 'draft') != 'draft' or vals.get('published_by') or vals.get('revoked_by'):
                    raise AccessError(_("Drafters can only create draft announcements."))
        records = super().create(vals_list)
        if not self.env.su:
            records._check_complete(check_publish_date=True, check_duplicates=True)
        records._log_event('created')
        return records

    def write(self, vals):
        if not self._is_privileged():
            changes_state = 'state' in vals and any(rec.state != vals['state'] for rec in self)
            if changes_state or {'published_by', 'revoked_by'} & set(vals):
                raise AccessError(_("Only Announcement Publishers can publish, revoke or expire announcements."))
        # a person changing a PUBLISHED announcement is recorded in the audit log, with old and new values
        audited = AUDITED_FIELDS & set(vals)
        before = {}
        if audited and not self.env.su:
            for rec in self.filtered(lambda r: r.state == 'published'):
                before[rec.id] = rec._audit_snapshot(audited)
        res = super().write(vals)
        if not self.env.su and COMPLETENESS_FIELDS & set(vals):
            self._check_complete(check_publish_date='date_published' in vals,
                                 check_duplicates='name' in vals)
        for rec_id, old in before.items():
            rec = self.browse(rec_id)
            new = rec._audit_snapshot(audited)
            changes = [(rec._fields[name].string, old[name][0], new[name][0])
                       for name in sorted(audited) if old[name][1] != new[name][1]]
            if changes:
                rec._log_event('edited', _("Changed: %s", ', '.join(label for label, _old, _new in changes)),
                               changes=changes)
        if 'active' in vals:
            self._log_event('unarchived' if vals['active'] else 'archived')
        return res

    # ---- Audit log --------------------------------------------------------
    def _log_event(self, action, details='', changes=None):
        """Append one audit-log entry per announcement (who = the logged-in user, when = now).

        changes: list of (field label, old value, new value) shown as separate lines.
        """
        if not self:
            return
        lines = [(0, 0, {'field_label': label, 'old_value': old, 'new_value': new})
                 for label, old, new in (changes or [])]
        self.env['bunna.announcement.log'].sudo().create([{
            'announcement_id': rec.id,
            'announcement_title': rec.name,
            'action': action,
            'user_id': self.env.uid,
            'state_after': rec.state,
            'details': details,
            'line_ids': lines,
        } for rec in self])

    def _local_str(self, value):
        """A date and time in the company time zone (Addis Ababa by default)."""
        if not value:
            return _("none")
        tz = self.env['bunna.announcement.settings'].get_tz()
        return pytz.utc.localize(fields.Datetime.to_datetime(value)).astimezone(tz).strftime('%d %b %Y, %H:%M')

    def _audit_child_name(self, child):
        if child._name == 'bunna.announcement.attachment':
            return child.file_name or _("(unnamed file)")
        if child._name == 'bunna.announcement.photo':
            return child.caption or _("Photo #%s", child.id)
        return child.display_name or str(child.id)

    def _audit_value(self, name):
        """(text shown in the log, key that tells whether the value really changed)."""
        self.ensure_one()
        field = self._fields[name]
        empty = _("(empty)")
        if name == 'image':
            raw = self.image
            if not raw:
                return empty, ''
            return _("a cover image"), hashlib.md5(raw if isinstance(raw, bytes) else raw.encode()).hexdigest()
        value = self[name]
        if field.type == 'many2one':
            text = value.display_name or empty
        elif field.type == 'datetime':
            text = self._local_str(value) if value else empty
        elif field.type == 'boolean':
            text = _("Yes") if value else _("No")
        elif field.type == 'html':
            plain = ' '.join(html2plaintext(value or '').split())
            return (helpers.shorten(plain) or empty), plain
        elif field.type == 'one2many':
            text = ', '.join(sorted(self._audit_child_name(child) for child in value)) or empty
        else:
            plain = str(value or '')
            return (helpers.shorten(plain) or empty), plain
        return text, text

    def _audit_snapshot(self, names):
        return {name: self._audit_value(name) for name in names}

    # ---- Messages shown after an action ---------------------------------------
    def _notify(self, message, level='success', sticky=False):
        """A pop-up message; the screen behind it refreshes afterwards."""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Done") if level == 'success' else _("Please note"),
                'message': message,
                'type': level,
                'sticky': sticky,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _partition(self, problem_of):
        """Split the selection into announcements that can go ahead and reasons why others cannot."""
        valid, skipped = self.browse(), []
        for rec in self:
            problem = problem_of(rec)
            if problem:
                skipped.append(_("'%(title)s': %(why)s", title=rec.name, why=problem))
            else:
                valid |= rec
        return valid, skipped

    def _finish(self, valid, skipped, message):
        """Nothing could be done: an error the user must read. Otherwise a success (or warning) pop-up."""
        if not valid:
            raise UserError("\n".join(skipped))
        if skipped:
            return self._notify(message + " " + _("Not done:") + " " + " ".join(skipped), 'warning', True)
        return self._notify(message)

    def _state_label(self, rec):
        return dict(self._fields['state'].selection).get(rec.state, rec.state)

    # ---- Workflow actions ----------------------------------------------------------
    def action_publish(self):
        self._check_publisher()
        now = fields.Datetime.now()

        def problem(rec):
            if rec.state == 'published':
                return _("it is already published.")
            if rec.date_expire and rec.date_expire <= now:
                return _("its Expiry Date has already passed. An Administrator must change it before it can be published.")
            try:
                rec._check_complete(
                    check_duplicates=True,
                    intro=_("it cannot be published yet. Please correct the following:"))
            except ValidationError as error:
                return error.args[0]
            return False

        valid, skipped = self._partition(problem)
        if valid:
            for rec in valid.sudo():
                rec.write({
                    'state': 'published',
                    'published_by': self.env.uid,
                    'revoked_by': False,
                    # keep a future (scheduled) date, otherwise publish now
                    'date_published': (rec.date_published if rec.date_published
                                       and rec.date_published > fields.Datetime.now()
                                       else fields.Datetime.now()),
                })
            for rec in valid:
                rec._log_event('published', _("Live from %s (UTC)", fields.Datetime.to_string(rec.date_published)))
        if len(valid) == 1:
            tz_name = self.env['bunna.announcement.settings'].get_tz().zone
            when = self._local_str(valid.date_published)
            if valid.date_published > fields.Datetime.now():
                message = _("'%(title)s' is scheduled and will go live on %(when)s (%(tz)s).",
                            title=valid.name, when=when, tz=tz_name)
            else:
                message = _("'%(title)s' is now live on the website. Published %(when)s (%(tz)s).",
                            title=valid.name, when=when, tz=tz_name)
            if valid.date_expire:
                message += " " + _("It expires on %s.", self._local_str(valid.date_expire))
        else:
            message = _("%s announcements were published.", len(valid))
        return self._finish(valid, skipped, message)

    def action_revoke(self):
        self._check_publisher()
        valid, skipped = self._partition(
            lambda rec: _("only a published announcement can be revoked (it is %s).", self._state_label(rec))
            if rec.state != 'published' else False)
        if valid:
            valid.sudo().write({'state': 'revoked', 'revoked_by': self.env.uid})
            valid._log_event('revoked')
        message = (_("'%s' was revoked. It is no longer shown on the website; the record is kept.", valid.name)
                   if len(valid) == 1 else _("%s announcements were revoked.", len(valid)))
        return self._finish(valid, skipped, message)

    def action_set_draft(self):
        self._check_publisher()
        valid, skipped = self._partition(
            lambda rec: _("only a revoked announcement can be set back to draft (it is %s).", self._state_label(rec))
            if rec.state != 'revoked' else False)
        if valid:
            valid.sudo().write({'state': 'draft'})
            valid._log_event('set_draft')
        message = (_("'%s' was set back to draft. It is not visible on the website.", valid.name)
                   if len(valid) == 1 else _("%s announcements were set back to draft.", len(valid)))
        return self._finish(valid, skipped, message)

    def action_expire_now(self):
        """Take a live announcement off the website now, keeping the record."""
        self._check_publisher()
        valid, skipped = self._partition(
            lambda rec: _("only a live announcement can be expired now.") if rec.live_status != 'live' else False)
        if valid:
            valid.sudo().write({'date_expire': fields.Datetime.now()})
            valid._log_event('expired_now')
        message = (_("'%(title)s' was taken off the website at %(when)s. The record is kept.",
                     title=valid.name, when=self._local_str(valid.date_expire))
                   if len(valid) == 1 else _("%s announcements were taken off the website.", len(valid)))
        return self._finish(valid, skipped, message)

    def action_open_comments(self):
        self._check_publisher()

        def problem(rec):
            if rec.state != 'published' or rec.live_status == 'expired':
                return _("comments can only be opened on a published announcement that has not expired.")
            return _("comments are already open.") if rec.allow_comments else False

        valid, skipped = self._partition(problem)
        if valid:
            valid.sudo().write({'allow_comments': True})
            for rec in valid:
                rec._log_event('comments_opened', _("Comments opened"),
                               changes=[(_("Allow Comments"), _("No"), _("Yes"))])
        message = (_("Comments are now open on '%s'. New comments appear only after a moderator approves them.", valid.name)
                   if len(valid) == 1 else _("Comments were opened on %s announcements.", len(valid)))
        if valid and not self.env['bunna.announcement.settings'].get_value('comments_site_enabled'):
            message += " " + _("Note: comments are switched off for the whole website in Website Settings, "
                               "so visitors will not see the form yet.")
        return self._finish(valid, skipped, message)

    def action_close_comments(self):
        self._check_publisher()

        def problem(rec):
            if rec.state != 'published':
                return _("it is not published.")
            return _("comments are already closed.") if not rec.allow_comments else False

        valid, skipped = self._partition(problem)
        if valid:
            valid.sudo().write({'allow_comments': False})
            for rec in valid:
                rec._log_event('comments_closed', _("Comments closed"),
                               changes=[(_("Allow Comments"), _("Yes"), _("No"))])
        message = (_("Comments are now closed on '%s'. Comments already approved stay visible.", valid.name)
                   if len(valid) == 1 else _("Comments were closed on %s announcements.", len(valid)))
        return self._finish(valid, skipped, message)

    def action_view_comments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Comments: %s", self.name),
            'res_model': 'bunna.announcement.comment',
            'view_mode': 'list,form',
            'domain': [('announcement_id', '=', self.id)],
        }

    def action_archive(self):
        result = super().action_archive()
        if isinstance(result, dict) and result:
            return result
        return self._notify(_("%s announcement(s) archived. They are hidden from the website and from the "
                              "default list; use the Archived filter to find them.", len(self)))

    def action_unarchive(self):
        result = super().action_unarchive()
        if isinstance(result, dict) and result:
            return result
        return self._notify(_("%s announcement(s) restored. They show again according to their status.", len(self)))

    def _alert_new_comment(self):
        """Tell the configured addresses a comment is waiting (at most one email per announcement per 15 minutes)."""
        self.ensure_one()
        emails = (self.env['bunna.announcement.settings'].get_value('comment_notify_emails') or '').strip()
        if not emails:
            return
        now = fields.Datetime.now()
        if self.comment_last_alert and now - self.comment_last_alert < timedelta(minutes=15):
            return
        try:
            body = Markup("<p>%s</p><p>%s</p>") % (
                _("A comment is waiting for review on the announcement: %s", self.name),
                _("Open Odoo: Announcements, Comments."))
            mail = self.env['mail.mail'].sudo().create({
                'subject': _("Announcement comment waiting for review"),
                'email_to': emails,
                'body_html': body,
                'auto_delete': True,
            })
            mail.send()
            self.sudo().write({'comment_last_alert': now})
        except Exception:
            _logger.warning("bunna announcement: could not send the comment alert email", exc_info=True)

    def unlink(self):
        if not self.env.context.get('module_uninstall'):
            raise UserError(_(
                "Announcements cannot be deleted. Archive the announcement, "
                "or set an expiry date (or use Expire Now), instead."))
        return super().unlink()

    def init(self):
        """One partial index that matches the website query exactly (live announcements, newest first)."""
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS bunna_announcement_live_idx
            ON bunna_announcement (date_published DESC, id DESC)
            WHERE state = 'published' AND active
        """)
