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

        # Blacklist Delegation & Supplementary menus for anyone who is not an active coach of staff (and not HR Admin)
        is_hr_admin = (
            user.has_group('hr.group_hr_manager')
            or user.has_group('base.group_system')
            or self.env.is_superuser()
        )
        if not is_hr_admin:
            emp = user.employee_id
            is_coach = False
            if emp:
                count = self.env['hr.employee'].sudo().search_count([
                    ('coach_id', '=', emp.id)
                ])
                is_coach = bool(count > 0)

            if not is_coach:
                restricted_menus = [
                    'hr_employee_custom.menu_employee_delegation',
                    'hr_employee_custom.menu_delegated_approvals',
                    'hr_employee_custom.menu_supplementary_role_list',
                ]
                for xml_id in restricted_menus:
                    menu = self.env.ref(xml_id, raise_if_not_found=False)
                    if menu and menu.id not in res:
                        res.append(menu.id)

        # Allow Departments (hr.menu_hr_department_kanban) for standard users (group_hr_employee_user)
        # Standard Odoo blacklists Departments for non-officers who are not department managers.
        dep_menu = self.env.ref('hr.menu_hr_department_kanban', raise_if_not_found=False)
        if dep_menu and dep_menu.id in res:
            res.remove(dep_menu.id)

        return res
