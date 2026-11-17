# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Start the audit log with what is already known about existing announcements."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    log = env['bunna.announcement.log']
    if log.search_count([]):
        return
    note = 'Backfilled from existing data'
    vals = []
    for rec in env['bunna.announcement'].with_context(active_test=False).search([], order='id'):
        vals.append({
            'announcement_id': rec.id, 'announcement_title': rec.name, 'action': 'created',
            'user_id': rec.create_uid.id or SUPERUSER_ID, 'date': rec.create_date,
            'state_after': 'draft', 'details': note,
        })
        if rec.published_by and rec.date_published:
            vals.append({
                'announcement_id': rec.id, 'announcement_title': rec.name, 'action': 'published',
                'user_id': rec.published_by.id, 'date': rec.date_published,
                'state_after': 'published', 'details': note,
            })
        if rec.revoked_by:
            vals.append({
                'announcement_id': rec.id, 'announcement_title': rec.name, 'action': 'revoked',
                'user_id': rec.revoked_by.id, 'date': rec.write_date,
                'state_after': 'revoked', 'details': note + ' (date approximate)',
            })
    if vals:
        log.create(vals)
