# -*- coding: utf-8 -*-
from odoo import api, models


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    def _load_menus_blacklist(self):
        res = super()._load_menus_blacklist()
        user = self.env.user

        # HR Officers / Managers / Administrators / System users have full operational access
        is_hr = (
            user.has_group('custom_recruitment.group_recruitment_officer')
            or user.has_group('custom_recruitment.group_recruitment_manager')
            or user.has_group('custom_recruitment.group_recruitment_administrator')
            or user.has_group('hr.group_hr_user')
            or user.has_group('hr.group_hr_manager')
            or user.has_group('base.group_system')
            or self.env.is_superuser()
        )

        has_recruitment_access = bool(
            user.has_group('custom_recruitment.group_recruitment_officer')
            or user.has_group('custom_recruitment.group_recruitment_manager')
            or user.has_group('custom_recruitment.group_recruitment_administrator')
            or user.has_group('base.group_system')
            or self.env.is_superuser()
        )

        emp = user.employee_id or self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)

        is_coach = bool(
            is_hr or (emp and self.env['hr.employee'].sudo().search_count([('coach_id', '=', emp.id)]) > 0)
        )

        # 1. Recruitment Request Management:
        # Display ONLY for users whose employee record is the coach_id of another employee (or HR)
        req_menu = self.env.ref(
            'custom_recruitment.menu_hr_employee_recruitment_request_management',
            raise_if_not_found=False
        )
        if req_menu:
            if not is_coach:
                if req_menu.id not in res:
                    res.append(req_menu.id)
                for child_xmlid in (
                    'custom_recruitment.menu_hr_employee_create_recruitment_request',
                    'custom_recruitment.menu_hr_employee_my_recruitment_requests',
                ):
                    child = self.env.ref(child_xmlid, raise_if_not_found=False)
                    if child and child.id not in res:
                        res.append(child.id)

        # 2. Digital Selection Minutes (Digital signature):
        # Display for users who are committee members, coaches (whose employee ID is coach_id of another employee), or HR
        minute_menu = self.env.ref(
            'custom_recruitment.menu_hr_employee_digital_selection_minute',
            raise_if_not_found=False
        )
        if minute_menu:
            is_committee_or_coach = bool(
                is_hr
                or is_coach
                or user.has_group('custom_recruitment.group_recruitment_approval_committee')
                or self.env['recruitment.committee.signature'].sudo().search_count([('user_id', '=', user.id)]) > 0
                or (emp and self.env['vac.panel.members'].sudo().search_count(['|', ('user_id', '=', user.id), ('employee_id', '=', emp.id)]) > 0)
                or self.env['new.recrt.delegation.team'].sudo().search_count([('employee_name', '=', user.id)]) > 0
            )
            if not is_committee_or_coach:
                if minute_menu.id not in res:
                    res.append(minute_menu.id)

        # 2b. Transfer Committee Minutes:
        # Display under Employee Service & Applications for users who are committee members, coaches (whose employee ID is coach_id of another employee), or HR
        is_transfer_committee_or_coach = bool(
            is_hr
            or is_coach
            or user.has_group('custom_recruitment.group_recruitment_approval_committee')
            or self.env['transfer.committee.signature'].sudo().search_count([('user_id', '=', user.id)]) > 0
            or self.env['transfer.committee.minutes'].sudo().search_count([
                '|', '|', '|',
                ('chairperson_id', '=', user.id),
                ('panel_member_id', '=', user.id),
                ('secretary_id', '=', user.id),
                ('observer_id', '=', user.id),
            ]) > 0
        )

        transfer_minute_menu = self.env.ref(
            'custom_recruitment.menu_hr_employee_transfer_committee_minutes',
            raise_if_not_found=False
        )
        if transfer_minute_menu:
            if not is_transfer_committee_or_coach and transfer_minute_menu.id not in res:
                res.append(transfer_minute_menu.id)

        app_transfer_minute_menu = self.env.ref(
            'custom_recruitment.menu_recruitment_transfer_committee_minutes_app',
            raise_if_not_found=False
        )
        if app_transfer_minute_menu:
            if not is_transfer_committee_or_coach and app_transfer_minute_menu.id not in res:
                res.append(app_transfer_minute_menu.id)

        # 3. Employee Demotion:
        # Display ONLY if user has recruitment module access (Officer, Manager, Administrator)
        demotion_menu = self.env.ref(
            'hr_employee_custom.menu_hr_employee_custom_demotion',
            raise_if_not_found=False
        )
        if demotion_menu:
            if not has_recruitment_access and demotion_menu.id not in res:
                res.append(demotion_menu.id)

        # Also blacklist the Applications menu digital selection minutes if not committee, not coach, and not HR
        app_minute_menu = self.env.ref(
            'custom_recruitment.menu_recruitment_selection_minute',
            raise_if_not_found=False
        )
        if app_minute_menu:
            is_committee_or_coach = bool(
                is_hr
                or is_coach
                or user.has_group('custom_recruitment.group_recruitment_approval_committee')
                or self.env['recruitment.committee.signature'].sudo().search_count([('user_id', '=', user.id)]) > 0
                or (emp and self.env['vac.panel.members'].sudo().search_count(['|', ('user_id', '=', user.id), ('employee_id', '=', emp.id)]) > 0)
                or self.env['new.recrt.delegation.team'].sudo().search_count([('employee_name', '=', user.id)]) > 0
            )
            if not is_committee_or_coach and app_minute_menu.id not in res:
                res.append(app_minute_menu.id)

        # 4. HR Reporting Menu Submenu Filtering (under Employees app):
        # Allow ALL employees to access 'Print Employee Experience Report'.
        # Blacklist all other HR reports for non-HR users (users without administrative HR access).
        if not is_hr:
            reporting_menu = self.env.ref('hr.hr_menu_hr_reports', raise_if_not_found=False)
            exp_report_menu = self.env.ref('hr_employee_custom.menu_print_employee_experience_report', raise_if_not_found=False)
            exp_report_id = exp_report_menu.id if exp_report_menu else False

            if reporting_menu:
                children = self.env['ir.ui.menu'].sudo().search([('id', 'child_of', reporting_menu.id)])
                for child in children:
                    if child.id != reporting_menu.id and child.id != exp_report_id:
                        if child.id not in res:
                            res.append(child.id)

        return res
