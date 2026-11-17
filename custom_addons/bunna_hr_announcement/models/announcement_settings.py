# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

DEFAULT_PAGE_SIZE = 5
DEFAULT_SIGNED_BY = 'Bunna Bank S.C'
# defaults for settings that are not plain numbers
OTHER_DEFAULTS = {'new_unit': 'minutes', 'block_duplicate_titles': True}

# setting name: (default, minimum allowed, maximum allowed)
LIMITS = {
    'page_size': (5, 1, 50),
    'new_duration': (120, 0, 10080),
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
    def get_page_size(self):
        return self.get_value('page_size')

    @api.model
    def get_default_signed_by(self):
        return self._get_settings().default_signed_by or DEFAULT_SIGNED_BY
