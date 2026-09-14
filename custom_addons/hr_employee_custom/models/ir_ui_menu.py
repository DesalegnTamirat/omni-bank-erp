# -*- coding: utf-8 -*-
from odoo import models


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    def _load_menus_blacklist(self):
        res = super()._load_menus_blacklist()

        user = self.env.user
        is_hr = (
            user.has_group('hr.group_hr_user')
            or user.has_group('hr.group_hr_manager')
            or user.has_group('base.group_system')
            or self.env.is_superuser()
        )

        # Blacklist Directory (hr.menu_hr_employee) so standard users cannot access it to list all employees
        if not is_hr:
            emp_menu = self.env.ref('hr.menu_hr_employee', raise_if_not_found=False)
            if emp_menu and emp_menu.id not in res:
                res.append(emp_menu.id)

        # Allow Departments (hr.menu_hr_department_kanban) for standard users (group_hr_employee_user)
        # Standard Odoo blacklists Departments for non-officers who are not department managers.
        dep_menu = self.env.ref('hr.menu_hr_department_kanban', raise_if_not_found=False)
        if dep_menu and dep_menu.id in res:
            res.remove(dep_menu.id)

        return res
