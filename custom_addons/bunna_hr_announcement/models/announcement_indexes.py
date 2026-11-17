# -*- coding: utf-8 -*-
"""Database index tuning for the announcement tables.

Two goals, and nothing more:
  1. Remove single-column indexes that a UNIQUE index already covers. They are pure write cost,
     and three of these tables are written on every page view or comment attempt.
  2. Add the few indexes that match queries the module really runs.

Small tables (settings, categories, priorities, announcements, photos, attachments) are left
alone: PostgreSQL reads them faster with a sequential scan than through an extra index.
"""
from odoo import fields, models


def _drop_plain_index(cr, table, column):
    """Drop non-unique single-column btree indexes on table(column), whatever their name."""
    cr.execute("""
        SELECT indexname FROM pg_indexes
        WHERE schemaname = current_schema()
          AND tablename = %s
          AND indexdef NOT LIKE 'CREATE UNIQUE%%'
          AND indexdef LIKE %s
    """, (table, '%% USING btree (' + column + ')'))
    for (name,) in cr.fetchall():
        cr.execute('DROP INDEX IF EXISTS "%s"' % name.replace('"', ''))


class AnnouncementThrottleIndexes(models.Model):
    _inherit = 'bunna.announcement.throttle'

    # UNIQUE (key, bucket) already serves lookups by key
    key = fields.Char(index=False)

    def init(self):
        super().init()
        _drop_plain_index(self.env.cr, 'bunna_announcement_throttle', 'key')


class AnnouncementVisitIndexes(models.Model):
    _inherit = 'bunna.announcement.visit'

    # UNIQUE (announcement_id, token) already serves lookups by announcement
    announcement_id = fields.Many2one(index=False)

    def init(self):
        super().init()
        _drop_plain_index(self.env.cr, 'bunna_announcement_visit', 'announcement_id')


class AnnouncementViewDailyIndexes(models.Model):
    _inherit = 'bunna.announcement.view.daily'

    # UNIQUE (announcement_id, date) already serves lookups by announcement
    announcement_id = fields.Many2one(index=False)

    def init(self):
        super().init()
        _drop_plain_index(self.env.cr, 'bunna_announcement_view_daily', 'announcement_id')


class AnnouncementCommentIndexes(models.Model):
    _inherit = 'bunna.announcement.comment'

    # replaced by the (announcement_id, state) index below
    announcement_id = fields.Many2one(index=False)

    def init(self):
        super().init()
        cr = self.env.cr
        _drop_plain_index(cr, 'bunna_announcement_comment', 'announcement_id')
        # website: approved comments of one announcement, and the "too many pending" check
        cr.execute("""
            CREATE INDEX IF NOT EXISTS bunna_announcement_comment_ann_state_idx
            ON bunna_announcement_comment (announcement_id, state)
        """)
        # dashboard and moderation: reported comments, a tiny slice of the table
        cr.execute("""
            CREATE INDEX IF NOT EXISTS bunna_announcement_comment_reported_idx
            ON bunna_announcement_comment (id) WHERE report_count > 0
        """)


class AnnouncementLogLineIndexes(models.Model):
    _inherit = 'bunna.announcement.log.line'

    # the biggest log table (one row per changed field); it is filtered and grouped by announcement
    announcement_id = fields.Many2one(
        related='log_id.announcement_id', string='Announcement', store=True, index=True)
