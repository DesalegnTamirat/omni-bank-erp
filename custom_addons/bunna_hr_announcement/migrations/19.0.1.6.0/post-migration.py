# -*- coding: utf-8 -*-


def migrate(cr, version):
    """Announcements can now be archived: make sure all existing ones are active."""
    cr.execute("UPDATE bunna_announcement SET active = TRUE WHERE active IS NULL")
