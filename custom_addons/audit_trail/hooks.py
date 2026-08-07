# -*- coding: utf-8 -*-
"""
Post-install / post-upgrade hook.
Grants the Audit Manager group to the admin user via res.users
(since res.groups no longer has a 'users' field in Odoo 19).
"""
import logging
_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Called after the module is installed."""
    _assign_admin_to_audit_manager(env)


def uninstall_hook(env):
    """Clean up audit logs and rules when module is uninstalled."""
    pass  # Odoo handles cascade deletion via ondelete on ir.model.data


def _assign_admin_to_audit_manager(env):
    try:
        manager_group = env.ref('audit_trail.group_audit_manager', raise_if_not_found=False)
        if not manager_group:
            return
        admin_users = env['res.users'].sudo().search([
            ('id', 'in', [env.ref('base.user_admin').id, env.ref('base.user_root').id])
        ])
        for user in admin_users:
            if manager_group not in user.groups_id:
                user.sudo().write({'groups_id': [(4, manager_group.id)]})
        _logger.info('audit_trail: Admin users assigned to Audit Manager group.')
    except Exception as e:
        _logger.warning('audit_trail: Could not assign admin to audit group: %s', e)
