# -*- coding: utf-8 -*-


def post_init_hook(env):
    """
    Post-installation hook:
    1. Removes the string 'False' placeholder from Attendance privilege.
    2. Automatically synchronizes Attendance security groups for all existing users based on
       whether they manage employees.
    """
    # 1. Clear placeholder string 'False' on Attendance privilege
    priv = env.ref('hr_attendance.res_groups_privilege_attendances', raise_if_not_found=False)
    if priv:
        priv.sudo().write({'placeholder': False})

    # 2. Sync attendance groups for all non-share (internal) users
    users = env['res.users'].sudo().search([('share', '=', False)])
    users._sync_attendance_manager_groups()
