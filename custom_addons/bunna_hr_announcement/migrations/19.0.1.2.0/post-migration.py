# -*- coding: utf-8 -*-


def migrate(cr, version):
    """Category/priority moved from fixed selections to configurable records."""
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'bunna_announcement' AND column_name IN ('category', 'priority')
    """)
    old_cols = {row[0] for row in cr.fetchall()}

    def xml_res_id(name):
        cr.execute("SELECT res_id FROM ir_model_data WHERE module = 'bunna_hr_announcement' AND name = %s", (name,))
        row = cr.fetchone()
        return row[0] if row else None

    if 'category' in old_cols:
        news = xml_res_id('category_news')
        notif = xml_res_id('category_notification')
        if notif:
            cr.execute("UPDATE bunna_announcement SET category_id = %s "
                       "WHERE category = 'notification' AND category_id IS NULL", (notif,))
        if news:
            cr.execute("UPDATE bunna_announcement SET category_id = %s WHERE category_id IS NULL", (news,))
        cr.execute("ALTER TABLE bunna_announcement DROP COLUMN category")

    if 'priority' in old_cols:
        normal = xml_res_id('priority_normal')
        important = xml_res_id('priority_important')
        if important:
            cr.execute("UPDATE bunna_announcement SET priority_id = %s "
                       "WHERE priority = 'important' AND priority_id IS NULL", (important,))
        if normal:
            cr.execute("UPDATE bunna_announcement SET priority_id = %s WHERE priority_id IS NULL", (normal,))
        cr.execute("ALTER TABLE bunna_announcement DROP COLUMN priority")

    # Restore the NOT NULL constraint when every row is filled
    for col in ('category_id', 'priority_id'):
        cr.execute("SELECT COUNT(*) FROM bunna_announcement WHERE %s IS NULL" % col)
        if not cr.fetchone()[0]:
            cr.execute("ALTER TABLE bunna_announcement ALTER COLUMN %s SET NOT NULL" % col)
