# -*- coding: utf-8 -*-


def migrate(cr, version):
    """New default for the green highlight is 120 minutes.

    Only a settings record that still has the old default (3 days) is changed,
    so a value someone chose on purpose is never overwritten.
    """
    cr.execute("""
        UPDATE bunna_announcement_settings
        SET new_duration = 120, new_unit = 'minutes'
        WHERE new_duration = 3 AND new_unit = 'days'
    """)
