# -*- coding: utf-8 -*-
from odoo import models, api
import logging

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model
    def _register_hook(self):
        """Ensure all existing internal users automatically have the Employee/User Performance role."""
        res = super()._register_hook()
        try:
            perf_user_group = self.env.ref('performance_management.group_performance_user', raise_if_not_found=False)
            internal_group = self.env.ref('base.group_user', raise_if_not_found=False)

            if perf_user_group and internal_group:
                # 1. Backfill all existing internal users
                self.env.cr.execute("""
                    INSERT INTO res_groups_users_rel (gid, uid)
                    SELECT %s, u.id
                    FROM res_users u
                    WHERE u.share = false
                      AND u.id IN (SELECT uid FROM res_groups_users_rel WHERE gid = %s)
                      AND u.id NOT IN (SELECT uid FROM res_groups_users_rel WHERE gid = %s)
                    ON CONFLICT DO NOTHING;
                """, (perf_user_group.id, internal_group.id, perf_user_group.id))

                self.env.registry.clear_cache('groups')
        except Exception as e:
            _logger.warning("Could not auto-assign performance user group in hook: %s", e)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        """When creating new internal users, automatically assign Employee/User Performance role by default."""
        users = super().create(vals_list)
        try:
            perf_user_group = self.env.ref('performance_management.group_performance_user', raise_if_not_found=False)
            perf_groups = [
                perf_user_group,
                self.env.ref('performance_management.group_performance_manager', raise_if_not_found=False),
                self.env.ref('performance_management.group_performance_planning', raise_if_not_found=False),
                self.env.ref('performance_management.group_performance_hr', raise_if_not_found=False),
                self.env.ref('performance_management.group_performance_admin', raise_if_not_found=False),
            ]
            perf_group_ids = {g.id for g in perf_groups if g}

            if perf_user_group:
                users_to_assign = users.filtered(
                    lambda u: not u.share and not (set(u.groups_id.ids) & perf_group_ids)
                )
                if users_to_assign:
                    users_to_assign.sudo().write({'groups_id': [(4, perf_user_group.id)]})
        except Exception as e:
            _logger.warning("Could not auto-assign performance user group on create: %s", e)
        return users

    def write(self, vals):
        """Maintain Employee/User role for internal users when groups are updated unless another performance role is selected."""
        res = super().write(vals)
        if 'groups_id' in vals:
            try:
                perf_user_group = self.env.ref('performance_management.group_performance_user', raise_if_not_found=False)
                perf_groups = [
                    perf_user_group,
                    self.env.ref('performance_management.group_performance_manager', raise_if_not_found=False),
                    self.env.ref('performance_management.group_performance_planning', raise_if_not_found=False),
                    self.env.ref('performance_management.group_performance_hr', raise_if_not_found=False),
                    self.env.ref('performance_management.group_performance_admin', raise_if_not_found=False),
                ]
                perf_group_ids = {g.id for g in perf_groups if g}

                if perf_user_group:
                    users_to_assign = self.filtered(
                        lambda u: not u.share and not (set(u.groups_id.ids) & perf_group_ids)
                    )
                    if users_to_assign:
                        users_to_assign.sudo().write({'groups_id': [(4, perf_user_group.id)]})
            except Exception as e:
                _logger.warning("Could not maintain performance user group on write: %s", e)
        return res

    def _action_reset_password(self, signup_type=False):
        """Safely intercept password reset / invitation email dispatch
        to prevent IndexError during user creation when mail auto-delete empties the recordset.
        """
        try:
            return super()._action_reset_password(signup_type=signup_type)
        except IndexError:
            _logger.info("Signup/Reset password email dispatched for user(s) %s", self.ids)
            return True
