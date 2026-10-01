# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID


def post_init_hook(env):
    """
    Assign 'Administrator' performance role to System Administrators
    and 'Employee / User' performance role to other internal users.
    """
    perf_admin_group = env.ref('performance_management.group_performance_admin', raise_if_not_found=False)
    perf_user_group = env.ref('performance_management.group_performance_user', raise_if_not_found=False)
    internal_group = env.ref('base.group_user', raise_if_not_found=False)
    sys_admin_group = env.ref('base.group_system', raise_if_not_found=False)
    erp_manager_group = env.ref('base.group_erp_manager', raise_if_not_found=False)

    if not perf_user_group or not internal_group or not perf_admin_group:
        return

    perf_groups = [
        perf_user_group,
        env.ref('performance_management.group_performance_manager', raise_if_not_found=False),
        env.ref('performance_management.group_performance_planning', raise_if_not_found=False),
        env.ref('performance_management.group_performance_hr', raise_if_not_found=False),
        perf_admin_group,
    ]
    perf_group_ids = tuple(g.id for g in perf_groups if g)
    admin_group_ids = [g.id for g in (sys_admin_group, erp_manager_group) if g]

    # 1. Backfill for System Administrators
    if admin_group_ids:
        env.cr.execute("""
            INSERT INTO res_groups_users_rel (gid, uid)
            SELECT %s, u.id
            FROM res_users u
            WHERE u.share = false
              AND (
                  u.id IN (SELECT uid FROM res_groups_users_rel WHERE gid IN %s)
                  OR u.id IN (1, 2)
              )
              AND u.id NOT IN (SELECT uid FROM res_groups_users_rel WHERE gid = %s)
            ON CONFLICT DO NOTHING;
        """, (perf_admin_group.id, tuple(admin_group_ids), perf_admin_group.id))

    # 2. Backfill for All Internal Users (Employees) without any Performance Role
    env.cr.execute("""
        INSERT INTO res_groups_users_rel (gid, uid)
        SELECT %s, u.id
        FROM res_users u
        WHERE u.share = false
          AND u.id IN (SELECT uid FROM res_groups_users_rel WHERE gid = %s)
          AND u.id NOT IN (SELECT uid FROM res_groups_users_rel WHERE gid IN %s)
        ON CONFLICT DO NOTHING;
    """, (perf_user_group.id, internal_group.id, perf_group_ids))

    env.registry.clear_cache('groups')
    env.invalidate_all()


