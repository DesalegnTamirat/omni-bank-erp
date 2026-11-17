# -*- coding: utf-8 -*-


def migrate(cr, version):
    """Categories got an icon: give the default 'Notification' category a bell."""
    cr.execute("""
        UPDATE bunna_announcement_category SET icon = 'fa-bell'
        WHERE id = (
            SELECT res_id FROM ir_model_data
            WHERE module = 'bunna_hr_announcement'
              AND model = 'bunna.announcement.category'
              AND name = 'category_notification')
    """)
