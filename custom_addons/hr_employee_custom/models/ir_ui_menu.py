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

        # Blacklist Delegation & Supplementary menus for anyone who does not have an Employee Master access role
        # (Officer/Admin) AND is not an active coach of other employees
        emp = user.employee_id or self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        is_coach = bool(
            user.has_group('hr_employee_custom.group_hr_coach')
            or (emp and self.env['hr.employee'].sudo().search_count(['|', ('coach_id', '=', emp.id), ('parent_id', '=', emp.id)]) > 0)
        )

        if not is_hr and not is_coach:
            restricted_menus = [
                'hr_employee_custom.menu_employee_delegation',
                'hr_employee_custom.menu_delegated_approvals',
                'hr_employee_custom.menu_supplementary_role_list',
                'hr_employee_custom.menu_employee_service_probation',
                'hr_employee_custom.menu_hr_org_chart_custom',
            ]
            for xml_id in restricted_menus:
                menu = self.env.ref(xml_id, raise_if_not_found=False)
                if menu and menu.id not in res:
                    res.append(menu.id)

        # Check if user has administrative access in HR / Recruitment
        is_recruitment_admin = bool(
            user.has_group('custom_recruitment.group_recruitment_administrator')
            or user.has_group('custom_recruitment.group_recruitment_manager')
            or user.has_group('hr.group_hr_manager')
            or user.has_group('base.group_system')
            or self.env.is_superuser()
        )

        # Check if the employee is registered as the manager of an Operating Unit (operating.unit.manager_id)
        is_ou_manager = bool(
            emp and self.env['operating.unit'].sudo().with_context(active_test=False).search_count([('manager_id', '=', emp.id)]) > 0
        )

        # Release Form should ONLY be visible to:
        #   - HR / Recruitment Managers/Admins
        #   - Employees who are manager of an Operating Unit (is_ou_manager)
        # (Strictly NOT available to employees who are merely coach_id of other employees)
        is_release_form_allowed = (
            is_recruitment_admin
            or is_ou_manager
        )
        if not is_release_form_allowed:
            release_form_menus = [
                'custom_recruitment.menu_hr_employee_custom_candidate_release_form',
                'custom_recruitment.menu_top_candidate_release_form',
            ]
            for xml_id in release_form_menus:
                menu = self.env.ref(xml_id, raise_if_not_found=False)
                if menu and menu.id not in res:
                    res.append(menu.id)

        # Digital Selection Minutes & Transfer Committee Minutes under Employee Service
        # must display ONLY for employees who are registered as the manager of an Operating Unit (manager_id on operating.unit),
        # or for users who have administrative access from the recruitment module (Recruitment Administrator/Manager).
        if not is_recruitment_admin and not is_ou_manager:
            committee_menus = [
                'custom_recruitment.menu_hr_employee_digital_selection_minute',
                'custom_recruitment.menu_hr_employee_transfer_committee_minutes',
            ]
            for xml_id in committee_menus:
                menu = self.env.ref(xml_id, raise_if_not_found=False)
                if menu and menu.id not in res:
                    res.append(menu.id)

        # Allow Departments (hr.menu_hr_department_kanban) for standard users (group_hr_employee_user)
        # Standard Odoo blacklists Departments for non-officers who are not department managers.
        dep_menu = self.env.ref('hr.menu_hr_department_kanban', raise_if_not_found=False)
        if dep_menu and dep_menu.id in res:
            res.remove(dep_menu.id)

        return res

    def load_web_menus(self, debug):
        web_menus = super().load_web_menus(debug)
        if 'root' in web_menus and 'children' in web_menus['root']:
            root_children = web_menus['root']['children']
            web_menus['root']['children'] = sorted(
                root_children,
                key=lambda menu_id: (web_menus.get(menu_id, {}).get('name') or '').lower()
            )
        return web_menus

