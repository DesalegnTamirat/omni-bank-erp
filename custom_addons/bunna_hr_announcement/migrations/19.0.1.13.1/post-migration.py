# -*- coding: utf-8 -*-
import psycopg2

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Photos are now kept in the database. Move any photo that was saved in the file store."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("""
        SELECT id, res_id, res_field FROM ir_attachment
        WHERE res_model = 'bunna.announcement.photo' AND res_field IN ('image', 'thumb')
    """)
    for attachment_id, photo_id, field in cr.fetchall():
        attachment = env['ir.attachment'].browse(attachment_id)
        raw = attachment.raw
        if raw and photo_id:
            cr.execute(
                'UPDATE bunna_announcement_photo SET "%s" = %%s WHERE id = %%s' % field,
                (psycopg2.Binary(raw), photo_id))
        attachment.unlink()
