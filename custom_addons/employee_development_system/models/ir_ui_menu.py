# -*- coding: utf-8 -*-
from odoo import models


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    def _load_menus_blacklist(self):
        res = super()._load_menus_blacklist()
        user = self.env.user

        # L&D staff (Officer and above), Administrators, and Superuser have full access
        is_lnd = (
            user.has_group('employee_development_system.group_eds_officer')
            or user.has_group('base.group_system')
            or self.env.is_superuser()
        )

        # Non-L&D users must manage at least one operating unit to see Unscheduled Requests
        if not is_lnd:
            compat = self.env['eds.hr.compat']
            managed_units = compat.get_managed_operating_units(user=user)
            if not managed_units:
                menu = self.env.ref(
                    'employee_development_system.menu_eds_unscheduled_requests',
                    raise_if_not_found=False
                )
                if menu and menu.id not in res:
                    res.append(menu.id)

        return res
