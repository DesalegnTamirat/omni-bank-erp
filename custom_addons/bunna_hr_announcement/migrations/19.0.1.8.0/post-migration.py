# -*- coding: utf-8 -*-


def migrate(cr, version):
    """Missing fields are now reported by one clear message (listing every field),
    so the database no longer rejects empty values first with a generic error."""
    for table, column in (
        ('bunna_announcement', 'name'),
        ('bunna_announcement', 'body'),
        ('bunna_announcement', 'category_id'),
        ('bunna_announcement', 'priority_id'),
        ('bunna_announcement_attachment', 'file_name'),
    ):
        cr.execute('ALTER TABLE "%s" ALTER COLUMN "%s" DROP NOT NULL' % (table, column))
