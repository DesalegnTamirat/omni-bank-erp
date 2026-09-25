# -*- coding: utf-8 -*-
from odoo import http, SUPERUSER_ID, _
from odoo.http import request
from odoo.addons.hr_org_chart.controllers.hr_org_chart import HrOrgChartController


class CustomHrOrgChartController(HrOrgChartController):

    @http.route('/hr/get_org_chart', type='jsonrpc', auth='user')
    def get_org_chart(self, employee_id, new_parent_id=None, **kw):
        res = super().get_org_chart(employee_id, new_parent_id=new_parent_id, **kw)
        if not res or not isinstance(res, dict):
            return res

        user = request.env.user
        # Check if user has HR Administrative Access (Officer or Manager or System Admin)
        is_hr_admin = (
            user.has_group('hr.group_hr_user')
            or user.has_group('hr.group_hr_manager')
            or user.has_group('base.group_system')
            or request.env.is_superuser()
        )

        if is_hr_admin:
            # HR Administrators have unrestricted bank-wide org chart visibility
            return res

        # For non-administrative users, restrict org chart to employees they have read permission for
        allowed_employee_ids = set(request.env['hr.employee'].search([]).ids)

        if 'managers' in res and res['managers']:
            filtered_managers = [
                m for m in res['managers']
                if m.get('id') in allowed_employee_ids
            ]
            res['managers'] = filtered_managers
            res['managers_more'] = False

        if 'children' in res and res['children']:
            filtered_children = [
                c for c in res['children']
                if c.get('id') in allowed_employee_ids
            ]
            res['children'] = filtered_children

        return res
