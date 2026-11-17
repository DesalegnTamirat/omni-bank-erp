# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Access is now by role only: stop giving every system administrator the app automatically.

    People who were already in the old 'Announcement Manager' group keep access as
    Announcement Administrators (that group is now the Administrator role).
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    system = env.ref('base.group_system', raise_if_not_found=False)
    manager = env.ref('bunna_hr_announcement.group_announcement_manager', raise_if_not_found=False)
    if system and manager and manager in system.implied_ids:
        system.write({'implied_ids': [(3, manager.id)]})
