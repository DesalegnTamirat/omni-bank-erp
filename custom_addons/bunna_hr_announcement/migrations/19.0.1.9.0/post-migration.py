# -*- coding: utf-8 -*-


def migrate(cr, version):
    """The green highlight duration now has a unit (minutes / hours / days).

    Keep the number of days that was configured before, then drop the old column.
    """
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'bunna_announcement_settings' AND column_name = 'new_badge_days'
    """)
    if cr.fetchone():
        cr.execute("UPDATE bunna_announcement_settings SET new_duration = new_badge_days, new_unit = 'days'")
        cr.execute("ALTER TABLE bunna_announcement_settings DROP COLUMN new_badge_days")
