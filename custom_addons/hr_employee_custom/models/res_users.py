# -*- coding: utf-8 -*-
# Migrated from the standalone hr_contract module (models/res_users.py)
# so that hr_employee_custom no longer depends on the hr_contract module.
# Fields and logic are unchanged.

from odoo import models, fields, api, _
from odoo import api, models, SUPERUSER_ID
from odoo.exceptions import AccessDenied
from odoo.modules.registry import Registry

class User(models.Model):
    _inherit = 'res.users'

    vehicle = fields.Char(related='employee_id.vehicle')

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + ['vehicle']


# ─────────────────────────────────────────────────────────────────────────
# Merged from the standalone 'operating_unit' module (OCA/operating-unit)
# so that hr_employee_custom no longer depends on a separate addon.
# Kept as its own class (rather than folded into User above) to preserve
# the original module's logic unchanged and make future diffing/upgrades
# against upstream 'operating_unit' easier.
# ─────────────────────────────────────────────────────────────────────────
class ResUsersOperatingUnit(models.Model):

    _inherit = "res.users"

    @api.model
    def operating_unit_default_get(self, uid2=False):
        if not uid2:
            uid2 = self.env.uid
        user = self.env["res.users"].browse(uid2)
        return user.default_operating_unit_id

    @api.model
    def _default_operating_unit(self):
        return self.operating_unit_default_get()

    @api.model
    def _default_operating_units(self):
        return self._default_operating_unit()

    operating_unit_ids = fields.One2many(
        comodel_name="operating.unit",
        compute="_compute_operating_unit_ids",
        inverse="_inverse_operating_unit_ids",
        string="Allowed Operating Units",
    )

    assigned_operating_unit_ids = fields.Many2many(
        comodel_name="operating.unit",
        relation="operating_unit_users_rel",
        column1="user_id",
        column2="operating_unit_id",
        string="Operating Units",
        default=lambda self: self._default_operating_units(),
    )

    default_operating_unit_id = fields.Many2one(
        comodel_name="operating.unit",
        string="Default Operating Unit",
        default=lambda self: self._default_operating_unit(),
    )

    @api.onchange("operating_unit_ids")
    def _onchange_operating_unit_ids(self):
        for record in self:
            if (
                record.default_operating_unit_id
                and record.default_operating_unit_id
                not in record.operating_unit_ids._origin
            ):
                record.default_operating_unit_id = False

    @api.depends("group_ids", "assigned_operating_unit_ids")
    def _compute_operating_unit_ids(self):
        for user in self:
            if user.has_group("hr_employee_custom.group_manager_operating_unit"):
                dom = []
                if self.env.context.get("allowed_company_ids"):
                    dom = [
                        "|",
                        ("company_id", "=", False),
                        ("company_id", "in", self.env.context["allowed_company_ids"]),
                    ]
                else:
                    dom = []
                user.operating_unit_ids = self.env["operating.unit"].sudo().search(dom)
            else:
                user.operating_unit_ids = user.assigned_operating_unit_ids

    @api.model
    def default_get(self, fields):
        vals = super().default_get(fields)
        if (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("base_setup.default_user_rights", "False")
            == "True"
        ):
            default_user = self.env.ref("base.default_user")
            vals[
                "default_operating_unit_id"
            ] = default_user.default_operating_unit_id.id
            vals["operating_unit_ids"] = [(6, 0, default_user.operating_unit_ids.ids)]
        return vals

    def _inverse_operating_unit_ids(self):
        for user in self:
            user.assigned_operating_unit_ids = user.operating_unit_ids
        self.env.registry.clear_cache()



class Users(models.Model):
    _inherit = 'res.users'

    def _has_valid_employee_and_contract(self):
        """
        Validates whether the user has both:
        1. An active record in hr.employee (Master Data)
        2. A valid record in hr.version (Contract Data)
        System Administrators (SUPERUSER_ID or base.group_system) are always valid.
        """
        self.ensure_one()
        if self.id == SUPERUSER_ID or self.has_group('base.group_system'):
            return True

        employee = self.env['hr.employee'].sudo().search([
            ('user_id', '=', self.id),
            ('active', '=', True),
        ], limit=1)
        if not employee:
            return False

        has_contract = self.env['hr.version'].sudo().search_count([
            ('employee_id', '=', employee.id),
            ('state', '!=', 'cancel'),
        ])
        return bool(has_contract)

    def _get_employee_validation_status(self):
        """
        Returns a dictionary indicating the status of master and contract data.
        """
        self.ensure_one()
        if self.id == SUPERUSER_ID or self.has_group('base.group_system'):
            return {'is_valid': True, 'missing_master': False, 'missing_contract': False}

        employee = self.env['hr.employee'].sudo().search([
            ('user_id', '=', self.id),
            ('active', '=', True),
        ], limit=1)
        if not employee:
            return {'is_valid': False, 'missing_master': True, 'missing_contract': True}

        has_contract = self.env['hr.version'].sudo().search_count([
            ('employee_id', '=', employee.id),
            ('state', '!=', 'cancel'),
        ])
        return {
            'is_valid': bool(has_contract),
            'missing_master': False,
            'missing_contract': not bool(has_contract),
        }

    def _login(self, credential, user_agent_env=None):
        try:
            return super()._login(credential, user_agent_env=user_agent_env)
        except AccessDenied:
            login = credential.get('login', '')
            self.env.cr.execute("SELECT id FROM res_users WHERE lower(login)=%s", (login.lower().strip(),))
            res = self.env.cr.fetchone()
            if res:
                raise

            Ldap = self.env['res.company.ldap'].sudo()
            for conf in Ldap._get_ldap_dicts():
                entry = Ldap._authenticate(conf, login, credential.get('password'))
                if entry:
                    return {
                        'uid': Ldap._get_or_create_user(conf, login, entry),
                        'auth_method': 'ldap',
                        'mfa': 'default',
                    }
            raise

    def _check_credentials(self, credential, env):
        try:
            return super()._check_credentials(credential, env)
        except AccessDenied:
            if not (isinstance(credential, dict) and credential.get('type') == 'password' and credential.get('password')):
                raise
            env_interactive = env.get('interactive', False) if isinstance(env, dict) else False
            has_rpc_api_keys_only = hasattr(self.env.user, '_rpc_api_keys_only') and self.env.user._rpc_api_keys_only()
            passwd_allowed = env_interactive or not has_rpc_api_keys_only
            if passwd_allowed and self.env.user.active:
                Ldap = self.env['res.company.ldap'].sudo()
                for conf in Ldap._get_ldap_dicts():
                    if Ldap._authenticate(conf, self.env.user.login, credential['password']):
                        return {
                            'uid': self.env.user.id,
                            'auth_method': 'ldap',
                            'mfa': 'default',
                        }
            raise

    @api.model
    def change_password(self, old_passwd, new_passwd):
        if new_passwd:
            Ldap = self.env['res.company.ldap'].sudo()
            for conf in Ldap._get_ldap_dicts():
                changed = Ldap._change_password(conf, self.env.user.login, old_passwd, new_passwd)
                if changed:
                    self.env.user._set_empty_password()
                    return True
        return super().change_password(old_passwd, new_passwd)

    def _set_empty_password(self):
        self.flush_recordset(['password'])
        self.env.cr.execute(
            'UPDATE res_users SET password=NULL WHERE id=%s',
            (self.id,)
        )
        self.invalidate_recordset(['password'])

    @api.model
    def _register_hook(self):
        super()._register_hook()
        base_group = self.env.ref('base.group_user', raise_if_not_found=False)
        user_group = self.env.ref('hr_employee_custom.group_hr_employee_user', raise_if_not_found=False)
        if base_group and user_group and user_group not in base_group.implied_ids:
            base_group.sudo().write({'implied_ids': [(4, user_group.id)]})

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        user_group = self.env.ref('hr_employee_custom.group_hr_employee_user', raise_if_not_found=False)
        if user_group:
            for user in users:
                if user.has_group('base.group_user') and not user.has_group('hr_employee_custom.group_hr_employee_user'):
                    user.sudo().write({'group_ids': [(4, user_group.id)]})
        return users

    def write(self, vals):
        res = super().write(vals)
        user_group = self.env.ref('hr_employee_custom.group_hr_employee_user', raise_if_not_found=False)
        if user_group and ('group_ids' in vals or 'groups_id' in vals):
            for user in self:
                if user.has_group('base.group_user') and not user.has_group('hr_employee_custom.group_hr_employee_user'):
                    user.sudo().write({'group_ids': [(4, user_group.id)]})
        return res
