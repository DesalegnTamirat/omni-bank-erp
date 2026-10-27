"""Retire bid-only contract status and enforce one awarded provider per selection."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    # If legacy data has multiple winners, keep the signed-contract bid first,
    # then the oldest award. Preserve the other bids and files as rejected bids.
    cr.execute("""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY selection_id
                       ORDER BY CASE WHEN status = 'contract' THEN 0 ELSE 1 END, id
                   ) AS winner_rank
              FROM eds_course_vendor_line
             WHERE status IN ('awarded', 'contract')
        )
        UPDATE eds_course_vendor_line AS bid
           SET status = 'rejected'
          FROM ranked
         WHERE bid.id = ranked.id AND ranked.winner_rank > 1
    """)
    cr.execute("""
        UPDATE eds_course_vendor_line
           SET status = CASE status
               WHEN 'pending' THEN 'draft'
               WHEN 'contract' THEN 'awarded'
               ELSE status END
         WHERE status IN ('pending', 'contract')
    """)
    cr.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS eds_course_vendor_line_one_award
            ON eds_course_vendor_line (selection_id)
         WHERE status = 'awarded'
    """)
    # The parent winner is stored; synchronize it after direct migration SQL.
    cr.execute("""
        UPDATE eds_course_vendor_selection AS selection
           SET awarded_vendor_id = (
               SELECT bid.vendor_id
                 FROM eds_course_vendor_line AS bid
                WHERE bid.selection_id = selection.id AND bid.status = 'awarded'
                ORDER BY bid.id LIMIT 1
           )
         WHERE EXISTS (
               SELECT 1 FROM eds_course_vendor_line AS bid
                WHERE bid.selection_id = selection.id
           )
    """)
    api.Environment(cr, SUPERUSER_ID, {}).invalidate_all()
