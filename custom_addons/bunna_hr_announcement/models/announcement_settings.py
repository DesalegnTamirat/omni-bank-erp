# -*- coding: utf-8 -*-
import re

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

DEFAULT_PAGE_SIZE = 5
DEFAULT_SIGNED_BY = 'Bunna Bank S.C'
DEFAULT_TZ = 'Africa/Addis_Ababa'
# defaults for settings that are not plain numbers
OTHER_DEFAULTS = {'new_unit': 'minutes', 'block_duplicate_titles': True, 'track_views': True,
                  'show_archive': True, 'comments_site_enabled': True, 'comments_default_allow': False,
                  'comment_block_links': True, 'comment_notify_emails': ''}

# setting name: (default, minimum allowed, maximum allowed)
LIMITS = {
    'page_size': (5, 1, 50),
    'new_duration': (120, 0, 10080),
    'visit_retention_days': (90, 7, 730),
    'gallery_max_photos': (12, 1, 30),
    'gallery_max_photo_mb': (8, 1, 20),
    'gallery_max_px': (1600, 800, 4000),
    'gallery_thumb_px': (480, 160, 800),
    'gallery_quality': (85, 50, 95),
    'gallery_caption_max': (150, 20, 500),
    'gallery_cache_hours': (24, 0, 168),
    'comment_max_length': (1000, 50, 5000),
    'comment_rate_per_hour': (3, 1, 30),
    'comment_max_pending': (100, 10, 1000),
    'comment_report_hide_at': (3, 0, 20),
    'title_max_length': (120, 20, 255),
    'summary_max_length': (250, 20, 500),
    'content_min_length': (10, 0, 500),
    'button_text_max_length': (30, 5, 60),
    'footer_note_max_length': (300, 20, 1000),
    'signed_by_max_length': (80, 10, 200),
    'publish_max_days_ahead': (90, 1, 730),
    'expiry_max_days': (365, 1, 1825),
    'expiry_min_minutes': (30, 0, 1440),
    'max_files': (5, 1, 10),
    'max_file_mb': (5, 1, 20),
    'max_total_mb': (15, 1, 50),
}


class BunnaAnnouncementSettings(models.Model):
    """Single-record settings (Announcements > Configuration > Website Settings)."""
    _name = 'bunna.announcement.settings'
    _description = 'Announcement Settings'

    name = fields.Char(default='Announcement Settings')

    # ---- Website page ----
    page_size = fields.Integer(
        string='Announcements per Page', default=LIMITS['page_size'][0], required=True,
        help="How many announcements are listed on one page of the website. "
             "Older ones move to the next pages.")

    new_duration = fields.Integer(
        string='Green Highlight: Show For', default=LIMITS['new_duration'][0], required=True,
        help="A newly published announcement is shown in green (softly blinking) for this long. "
             "Use 0 to switch the green highlight off.")
    new_unit = fields.Selection(
        [('minutes', 'Minutes'), ('hours', 'Hours'), ('days', 'Days')],
        string='Green Highlight: Unit', default='minutes', required=True)

    show_archive = fields.Boolean(
        string='Archive: Allow Opening Expired Announcements', default=True,
        help="On: visitors can tick 'Include expired' on the website to find old announcements, "
             "which stay readable and are marked Expired. Off: an expired announcement disappears "
             "completely. Revoked announcements are never shown.")

    # ---- New announcements ----
    default_signed_by = fields.Char(
        string='Default "Signed By"', default=DEFAULT_SIGNED_BY,
        help="Pre-filled in the footer of every new announcement.")

    # ---- Text limits ----
    title_max_length = fields.Integer(
        string='Title: Maximum Characters', default=LIMITS['title_max_length'][0], required=True)
    summary_max_length = fields.Integer(
        string='Summary: Maximum Characters', default=LIMITS['summary_max_length'][0], required=True)
    content_min_length = fields.Integer(
        string='Content: Minimum Characters', default=LIMITS['content_min_length'][0], required=True,
        help="Stops one-word posts. Use 0 to switch this check off.")
    button_text_max_length = fields.Integer(
        string='Button Text: Maximum Characters', default=LIMITS['button_text_max_length'][0], required=True)
    footer_note_max_length = fields.Integer(
        string='Footer Note: Maximum Characters', default=LIMITS['footer_note_max_length'][0], required=True)
    signed_by_max_length = fields.Integer(
        string='Signed By: Maximum Characters', default=LIMITS['signed_by_max_length'][0], required=True)

    # ---- Dates ----
    publish_max_days_ahead = fields.Integer(
        string='Publish Date: Maximum Days Ahead', default=LIMITS['publish_max_days_ahead'][0], required=True,
        help="Catches typing mistakes such as the wrong year.")
    expiry_max_days = fields.Integer(
        string='Expiry: Maximum Days After Publishing', default=LIMITS['expiry_max_days'][0], required=True)
    expiry_min_minutes = fields.Integer(
        string='Expiry: Minimum Minutes After Publishing', default=LIMITS['expiry_min_minutes'][0], required=True,
        help="Stops a post that would be live for only a moment. "
             "To take a live post down at once use the Expire Now button.")

    # ---- Attachments ----
    max_files = fields.Integer(
        string='Attachments: Maximum Files per Announcement', default=LIMITS['max_files'][0], required=True)
    max_file_mb = fields.Integer(
        string='Attachments: Maximum MB per File', default=LIMITS['max_file_mb'][0], required=True)
    max_total_mb = fields.Integer(
        string='Attachments: Maximum Total MB per Announcement', default=LIMITS['max_total_mb'][0], required=True)

    # ---- Readership tracking ----
    track_views = fields.Boolean(
        string='Count Views', default=True,
        help="Count how many times each announcement is opened (anonymous: no names, no IP addresses).")
    visit_retention_days = fields.Integer(
        string='Keep Visitor Records (Days)', default=LIMITS['visit_retention_days'][0], required=True,
        help="Anonymous visitor identifiers older than this are deleted. The daily totals are kept.")

    # ---- Photo gallery ----
    gallery_max_photos = fields.Integer(
        string='Gallery: Maximum Photos per Announcement', default=LIMITS['gallery_max_photos'][0], required=True)
    gallery_max_photo_mb = fields.Integer(
        string='Gallery: Maximum MB per Uploaded Photo', default=LIMITS['gallery_max_photo_mb'][0], required=True,
        help="Larger pictures are refused. Accepted pictures are shrunk automatically for the website.")

    gallery_max_px = fields.Integer(
        string='Gallery: Largest Photo Side (px)', default=LIMITS['gallery_max_px'][0], required=True,
        help="Uploaded photos are shrunk so neither side is longer than this. "
             "Applies to photos uploaded from now on.")
    gallery_thumb_px = fields.Integer(
        string='Gallery: Thumbnail Side (px)', default=LIMITS['gallery_thumb_px'][0], required=True,
        help="Size of the small pictures in the grid. Applies to photos uploaded from now on.")
    gallery_quality = fields.Integer(
        string='Gallery: Picture Quality (%)', default=LIMITS['gallery_quality'][0], required=True,
        help="Higher looks better but makes files bigger (thumbnails use 5 points less). "
             "Applies to photos uploaded from now on.")
    gallery_caption_max = fields.Integer(
        string='Gallery: Caption Maximum Characters', default=LIMITS['gallery_caption_max'][0], required=True)
    gallery_cache_hours = fields.Integer(
        string='Gallery: Browser Keeps Photos (Hours)', default=LIMITS['gallery_cache_hours'][0], required=True,
        help="How long a visitor's browser keeps a photo before asking again. Longer means less load on the "
             "server; a revoked post's photos can stay in a browser this long. 0 = always check.")

    # ---- Anonymous comments ----
    comments_site_enabled = fields.Boolean(
        string='Comments: Allowed on the Website', default=True,
        help="Master switch. Off: no announcement shows a comment form, whatever its own setting says.")
    comments_default_allow = fields.Boolean(
        string='Comments: Open on New Announcements', default=False,
        help="The starting value of 'Allow Comments' on every new announcement. "
             "It can be changed per announcement, before or after publishing.")
    comment_max_length = fields.Integer(
        string='Comments: Maximum Characters', default=LIMITS['comment_max_length'][0], required=True)
    comment_rate_per_hour = fields.Integer(
        string='Comments: Per Visitor per Hour', default=LIMITS['comment_rate_per_hour'][0], required=True,
        help="How many comments one connection may send per hour. Counted with a daily-changing one-way "
             "code that is deleted after two hours and never stored with a comment.")
    comment_max_pending = fields.Integer(
        string='Comments: Maximum Waiting for Review', default=LIMITS['comment_max_pending'][0], required=True,
        help="When this many comments are waiting on one announcement, new ones are paused until a moderator reviews them.")
    comment_report_hide_at = fields.Integer(
        string='Comments: Hide After This Many Reports', default=LIMITS['comment_report_hide_at'][0], required=True,
        help="A comment reported by this many readers is hidden automatically until a moderator looks at it. 0 = never.")
    comment_block_links = fields.Boolean(
        string='Comments: Refuse Links', default=True,
        help="Comments containing web addresses are refused (the most common kind of spam).")
    comment_notify_emails = fields.Char(
        string='Comments: Alert These Emails',
        help="Optional. Comma-separated addresses told that a comment is waiting for review "
             "(at most one email per announcement every 15 minutes; the comment itself is not emailed).")

    # ---- Checks ----
    block_duplicate_titles = fields.Boolean(
        string='Block Duplicate Titles', default=True,
        help="Refuse an announcement whose title is already used by a live or scheduled announcement.")

    @api.constrains(*LIMITS)
    def _check_limits(self):
        for rec in self:
            for name, (_default, low, high) in LIMITS.items():
                if not low <= rec[name] <= high:
                    raise ValidationError(_(
                        "%(field)s: enter a number between %(low)s and %(high)s.",
                        field=self._fields[name].string, low=low, high=high))
            if rec.gallery_thumb_px > rec.gallery_max_px:
                raise ValidationError(_("Gallery: the thumbnail cannot be larger than the photo itself."))
            if rec.max_total_mb < rec.max_file_mb:
                raise ValidationError(_(
                    "Attachments: the total size allowed per announcement must be at least "
                    "the size allowed per file."))

    @api.constrains('new_duration', 'new_unit')
    def _check_new_duration(self):
        maximum = {'minutes': 10080, 'hours': 720, 'days': 30}
        for rec in self:
            if rec.new_duration > maximum[rec.new_unit]:
                raise ValidationError(_(
                    "Green Highlight: at most %(max)s %(unit)s.", max=maximum[rec.new_unit], unit=rec.new_unit))

    @api.constrains('comment_notify_emails')
    def _check_comment_emails(self):
        for rec in self:
            for address in (rec.comment_notify_emails or '').split(','):
                address = address.strip()
                if address and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', address):
                    raise ValidationError(_("Comments: '%s' is not a valid email address.", address))

    @api.model
    def _get_settings(self):
        return self.sudo().search([], limit=1)

    @api.model
    def get_value(self, name):
        """A setting's value, falling back to the built-in default if no settings record exists."""
        settings = self._get_settings()
        if settings:
            return settings[name]
        if name in LIMITS:
            return LIMITS[name][0]
        return OTHER_DEFAULTS.get(name)

    @api.model
    def get_tz(self):
        """Company time zone (Addis Ababa when the company has none): used for dates on the website."""
        try:
            return pytz.timezone(self.env.company.partner_id.tz or DEFAULT_TZ)
        except Exception:
            return pytz.timezone(DEFAULT_TZ)

    @api.model
    def get_page_size(self):
        return self.get_value('page_size')

    @api.model
    def get_default_signed_by(self):
        return self._get_settings().default_signed_by or DEFAULT_SIGNED_BY
