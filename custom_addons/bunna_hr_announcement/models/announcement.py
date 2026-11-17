# -*- coding: utf-8 -*-
import base64
import re
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import html2plaintext
from odoo.tools.mimetypes import guess_mimetype

from .announcement_settings import LIMITS

DEFAULT_FOOTER = "For any questions, please contact the Human Resources Department."
LINK_RE = re.compile(r'^(https?://\S+|/\S*)$', re.IGNORECASE)
ALLOWED_IMAGE_MIMETYPES = {'image/png', 'image/jpeg', 'image/gif', 'image/webp'}
# A publish date may be 'now' typed a few minutes ago, but never earlier than this
PUBLISH_DATE_GRACE = timedelta(minutes=5)
COMPLETENESS_FIELDS = {
    'name', 'summary', 'body', 'category_id', 'priority_id', 'date_published', 'date_expire',
    'link_url', 'link_label', 'footer_note', 'signed_by', 'attachment_ids',
}
# Changing any of these on a published announcement is written to the audit log
AUDITED_FIELDS = {
    'name', 'summary', 'body', 'category_id', 'priority_id', 'date_published', 'date_expire',
    'link_url', 'link_label', 'footer_note', 'signed_by', 'image', 'attachment_ids', 'allow_download',
}
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
        values = list(value) if isinstance(value, (list, tuple, set)) else [value]
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
            rec.excerpt = text[:220] + ('…' if len(text) > 220 else '')

    @api.model
    def _website_domain(self):
        """Single source of truth for what employees may see on the website."""
        now = fields.Datetime.now()
        return [
            ('state', '=', 'published'),
            ('date_published', '<=', now),
            '|', ('date_expire', '=', False), ('date_expire', '>', now),
        ]

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
        # a person changing a PUBLISHED announcement is recorded in the audit log
        live_before = self.browse()
        if not self.env.su and AUDITED_FIELDS & set(vals):
            live_before = self.filtered(lambda rec: rec.state == 'published')
        res = super().write(vals)
        if not self.env.su and COMPLETENESS_FIELDS & set(vals):
            self._check_complete(check_publish_date='date_published' in vals,
                                 check_duplicates='name' in vals)
        if live_before:
            changed = ', '.join(sorted(self._fields[name].string for name in AUDITED_FIELDS & set(vals)))
            live_before._log_event('edited', _("Changed while published: %s", changed))
        if 'active' in vals:
            self._log_event('unarchived' if vals['active'] else 'archived')
        return res

    def _log_event(self, action, details=''):
        """Append one audit-log line per announcement (who = the logged-in user, when = now)."""
        if not self:
            return
        self.env['bunna.announcement.log'].sudo().create([{
            'announcement_id': rec.id,
            'announcement_title': rec.name,
            'action': action,
            'user_id': self.env.uid,
            'state_after': rec.state,
            'details': details,
        } for rec in self])

    def _state_label(self, rec):
        return dict(self._fields['state'].selection).get(rec.state, rec.state)

    def action_publish(self):
        self._check_publisher()
        now = fields.Datetime.now()
        for rec in self:
            if rec.state == 'published':
                raise UserError(_("'%s' is already published.", rec.name))
            if rec.date_expire and rec.date_expire <= now:
                raise UserError(_(
                    "'%s' cannot be published: its Expiry Date has already passed. "
                    "An Administrator must change the Expiry Date first.", rec.name))
            rec._check_complete(
                check_duplicates=True,
                intro=_("'%s' cannot be published yet. Please correct the following:", rec.name))
        for rec in self.sudo():
            rec.write({
                'state': 'published',
                'published_by': self.env.uid,
                'revoked_by': False,
                # keep a future (scheduled) date, otherwise publish now
                'date_published': (rec.date_published if rec.date_published
                                   and rec.date_published > fields.Datetime.now()
                                   else fields.Datetime.now()),
            })
        for rec in self:
            rec._log_event('published', _("Live from %s (UTC)", fields.Datetime.to_string(rec.date_published)))

    def action_revoke(self):
        self._check_publisher()
        for rec in self:
            if rec.state != 'published':
                raise UserError(_("Only a published announcement can be revoked ('%(name)s' is %(state)s).",
                                  name=rec.name, state=self._state_label(rec)))
        self.sudo().write({'state': 'revoked', 'revoked_by': self.env.uid})
        self._log_event('revoked')

    def action_set_draft(self):
        self._check_publisher()
        for rec in self:
            if rec.state != 'revoked':
                raise UserError(_("Only a revoked announcement can be set back to draft ('%(name)s' is %(state)s).",
                                  name=rec.name, state=self._state_label(rec)))
        self.sudo().write({'state': 'draft'})
        self._log_event('set_draft')

    def action_expire_now(self):
        """Take a live announcement off the website now, keeping the record."""
        self._check_publisher()
        for rec in self:
            if rec.live_status != 'live':
                raise UserError(_("Only a live announcement can be expired now ('%s' is not live).", rec.name))
        self.sudo().write({'date_expire': fields.Datetime.now()})
        self._log_event('expired_now')

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
