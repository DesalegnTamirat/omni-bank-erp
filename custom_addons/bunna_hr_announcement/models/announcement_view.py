# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# The same visitor opening the same post again within this time is not counted twice
VIEW_WINDOW_MINUTES = 30

# One row per (announcement, anonymous visitor). Returns a row only when the view must be counted:
#   inserted = True  -> first time this visitor is seen on this announcement
#   inserted = False -> a known visitor, outside the 30-minute window
# No row is returned for a repeated open inside the window.
UPSERT_VISIT = """
    INSERT INTO bunna_announcement_visit (announcement_id, token, first_seen, last_view)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (announcement_id, token) DO UPDATE
        SET last_view = EXCLUDED.last_view
        WHERE bunna_announcement_visit.last_view < %s
    RETURNING (xmax = 0) AS inserted
"""

# One small counter row per announcement per day
UPSERT_DAILY = """
    INSERT INTO bunna_announcement_view_daily
        (announcement_id, date, views, unique_visitors, file_opens, downloads)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (announcement_id, date) DO UPDATE SET
        views = bunna_announcement_view_daily.views + EXCLUDED.views,
        unique_visitors = bunna_announcement_view_daily.unique_visitors + EXCLUDED.unique_visitors,
        file_opens = bunna_announcement_view_daily.file_opens + EXCLUDED.file_opens,
        downloads = bunna_announcement_view_daily.downloads + EXCLUDED.downloads
"""


class BunnaAnnouncementViewDaily(models.Model):
    """Readership counters per announcement per day (anonymous, no personal data)."""
    _name = 'bunna.announcement.view.daily'
    _description = 'Announcement Daily Readership'
    _order = 'date desc, id desc'

    announcement_id = fields.Many2one(
        'bunna.announcement', string='Announcement', required=True,
        ondelete='cascade', index=True, readonly=True)
    date = fields.Date(string='Date', required=True, index=True, readonly=True)
    views = fields.Integer(string='Views', default=0, readonly=True)
    unique_visitors = fields.Integer(
        string='New Visitors', default=0, readonly=True,
        help="Visitors who opened this announcement for the first time on this day.")
    file_opens = fields.Integer(string='File Opens', default=0, readonly=True)
    downloads = fields.Integer(string='Downloads', default=0, readonly=True)

    def init(self):
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS bunna_announcement_view_daily_uniq
            ON bunna_announcement_view_daily (announcement_id, date)
        """)

    @api.model
    def _today_local(self):
        """Days are counted in the company time zone (Addis Ababa if none is set)."""
        tz = self.env['bunna.announcement.settings'].get_tz()
        return datetime.now(pytz.utc).astimezone(tz).date()

    @api.model
    def _record_view(self, announcement_id, token):
        """Count one page view. Runs in its own short transaction so the counter row is locked
        for a moment only, and any problem here can never break the page."""
        now = fields.Datetime.now()
        window = now - timedelta(minutes=VIEW_WINDOW_MINUTES)
        today = self._today_local()
        try:
            with self.env.registry.cursor() as cr:
                cr.execute(UPSERT_VISIT, (announcement_id, token, now, now, window))
                row = cr.fetchone()
                if row:
                    cr.execute(UPSERT_DAILY, (announcement_id, today, 1, 1 if row[0] else 0, 0, 0))
        except Exception:
            _logger.warning("bunna announcement: could not record a view", exc_info=True)

    @api.model
    def _record_file(self, announcement_id, kind):
        """Count one attachment open (kind='open') or download (kind='download')."""
        today = self._today_local()
        opens, downloads = (1, 0) if kind == 'open' else (0, 1)
        try:
            with self.env.registry.cursor() as cr:
                cr.execute(UPSERT_DAILY, (announcement_id, today, 0, 0, opens, downloads))
        except Exception:
            _logger.warning("bunna announcement: could not record a file open", exc_info=True)

    @api.model
    def _cron_purge_visits(self):
        """Forget anonymous visitor records older than the retention period (daily totals are kept)."""
        days = self.env['bunna.announcement.settings'].get_value('visit_retention_days')
        self.env.cr.execute(
            "DELETE FROM bunna_announcement_visit "
            "WHERE last_view < (now() at time zone 'utc') - make_interval(days => %s)", (days,))
        _logger.info("bunna announcement: purged %s old visitor records", self.env.cr.rowcount)


class BunnaAnnouncementVisit(models.Model):
    """Which anonymous visitor (random cookie id, no personal data) has seen which announcement."""
    _name = 'bunna.announcement.visit'
    _description = 'Announcement Visitor Record'

    announcement_id = fields.Many2one(
        'bunna.announcement', required=True, ondelete='cascade', index=True, readonly=True)
    token = fields.Char(required=True, readonly=True)
    first_seen = fields.Datetime(required=True, readonly=True)
    last_view = fields.Datetime(required=True, readonly=True, index=True)

    def init(self):
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS bunna_announcement_visit_uniq
            ON bunna_announcement_visit (announcement_id, token)
        """)
