# -*- coding: utf-8 -*-
from odoo import models, api
import logging

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _action_reset_password(self, signup_type=False):
        """Safely intercept password reset / invitation email dispatch
        to prevent IndexError during user creation when mail auto-delete empties the recordset.
        """
        try:
            return super()._action_reset_password(signup_type=signup_type)
        except IndexError:
            _logger.info("Signup/Reset password email dispatched for user(s) %s", self.ids)
            return True

    def _default_groups(self):
        """Include Employee / User performance group in default groups."""
        groups = super()._default_groups()
        perf_user_group = self.env.ref('performance_management.group_performance_user', raise_if_not_found=False)
        if perf_user_group:
            groups |= perf_user_group
        return groups

    @api.model
    def default_get(self, fields_list):
        """Pre-select Employee / User role by default when opening New User form."""
        res = super().default_get(fields_list)
        perf_user_group = self.env.ref('performance_management.group_performance_user', raise_if_not_found=False)
        if perf_user_group:
            for fname in ('group_ids', 'groups_id'):
                if fname in fields_list or fname in res:
                    cmds = list(res.get(fname, []))
                    existing_ids = set()
                    for cmd in cmds:
                        if isinstance(cmd, (tuple, list)):
                            if len(cmd) > 1 and cmd[0] == 4:
                                existing_ids.add(cmd[1])
                            elif len(cmd) > 2 and cmd[0] == 6:
                                existing_ids.update(cmd[2])
                    if perf_user_group.id not in existing_ids:
                        cmds.append((4, perf_user_group.id))
                    res[fname] = cmds
        return res

    @api.model
    def _register_hook(self):
        """Ensure all system administrators have the Performance Administrator role,
        and all other existing internal users have the default Employee/User group assigned.
        """
        super()._register_hook()
        try:
            perf_admin_group = self.env.ref('performance_management.group_performance_admin', raise_if_not_found=False)
            perf_user_group = self.env.ref('performance_management.group_performance_user', raise_if_not_found=False)
            internal_group = self.env.ref('base.group_user', raise_if_not_found=False)
            sys_admin_group = self.env.ref('base.group_system', raise_if_not_found=False)
            erp_manager_group = self.env.ref('base.group_erp_manager', raise_if_not_found=False)

            if not perf_user_group or not internal_group or not perf_admin_group:
                return

            perf_groups = [
                perf_user_group,
                self.env.ref('performance_management.group_performance_manager', raise_if_not_found=False),
                self.env.ref('performance_management.group_performance_planning', raise_if_not_found=False),
                self.env.ref('performance_management.group_performance_hr', raise_if_not_found=False),
                perf_admin_group,
            ]
            perf_group_ids = tuple(g.id for g in perf_groups if g)

            admin_group_ids = [g.id for g in (sys_admin_group, erp_manager_group) if g]

            # 1. Backfill for System Administrators
            if admin_group_ids:
                self.env.cr.execute("""
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
            self.env.cr.execute("""
                INSERT INTO res_groups_users_rel (gid, uid)
                SELECT %s, u.id
                FROM res_users u
                WHERE u.share = false
                  AND u.id IN (SELECT uid FROM res_groups_users_rel WHERE gid = %s)
                  AND u.id NOT IN (SELECT uid FROM res_groups_users_rel WHERE gid IN %s)
                ON CONFLICT DO NOTHING;
            """, (perf_user_group.id, internal_group.id, perf_group_ids))

            # Invalidate caches so UI immediately picks up the new groups
            self.env.registry.clear_cache('groups')
            self.env.invalidate_all()
            _logger.info("Synchronized default performance management groups for all existing users.")
        except Exception as e:
            _logger.warning("Failed to auto-assign performance groups in _register_hook: %s", e)

    @api.model_create_multi
    def create(self, vals_list):
        """Automatically assign group_performance_admin to new system admins,
        and group_performance_user to new internal employees if no role is chosen.
        """
        users = super().create(vals_list)
        try:
            perf_admin_group = self.env.ref('performance_management.group_performance_admin', raise_if_not_found=False)
            perf_user_group = self.env.ref('performance_management.group_performance_user', raise_if_not_found=False)
            internal_group = self.env.ref('base.group_user', raise_if_not_found=False)
            sys_admin_group = self.env.ref('base.group_system', raise_if_not_found=False)
            erp_manager_group = self.env.ref('base.group_erp_manager', raise_if_not_found=False)

            if perf_user_group and perf_admin_group and internal_group:
                perf_groups = [
                    perf_user_group,
                    self.env.ref('performance_management.group_performance_manager', raise_if_not_found=False),
                    self.env.ref('performance_management.group_performance_planning', raise_if_not_found=False),
                    self.env.ref('performance_management.group_performance_hr', raise_if_not_found=False),
                    perf_admin_group,
                ]
                all_perf_ids = set(g.id for g in perf_groups if g)

                for user in users:
                    if not user.share:
                        user_group_ids = set(user.group_ids.ids)
                        if not (user_group_ids & all_perf_ids):
                            # Check if user is an admin
                            is_sys_admin = (sys_admin_group and sys_admin_group.id in user_group_ids) or \
                                           (erp_manager_group and erp_manager_group.id in user_group_ids)
                            target_group = perf_admin_group if is_sys_admin else perf_user_group
                            self.env.cr.execute("""
                                INSERT INTO res_groups_users_rel (gid, uid)
                                VALUES (%s, %s)
                                ON CONFLICT DO NOTHING;
                            """, (target_group.id, user.id))
                self.env.registry.clear_cache('groups')
                self.env.invalidate_all()
        except Exception as e:
            _logger.warning("Failed to auto-assign performance user group on create: %s", e)
        return users

