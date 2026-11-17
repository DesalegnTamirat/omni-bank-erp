# -*- coding: utf-8 -*-
from odoo import http, SUPERUSER_ID, _
from odoo.http import request
from odoo.addons.hr_org_chart.controllers.hr_org_chart import HrOrgChartController


class CustomHrOrgChartController(HrOrgChartController):

    def _get_employee(self, employee_id, **kw):
        """
        Override _get_employee using sudo() so that all users (including default users
        with base.group_user access and without department menu access) can load the
        org chart hierarchy structure for any employee.
        """
        try:
            emp_id = int(employee_id) if employee_id else False
        except (ValueError, TypeError):
            emp_id = False

        if not emp_id:
            return request.env['hr.employee.public'].sudo().browse()

        context = kw.get('context', request.env.context) or {}
        if 'allowed_company_ids' in context:
            cids = context['allowed_company_ids']
        elif request.env.company:
            cids = [request.env.company.id]
        else:
            cids = []

        Employee = request.env['hr.employee.public'].sudo().with_context(allowed_company_ids=cids)
        employee = Employee.browse(emp_id)
        return employee if employee.exists() else Employee.browse()

    @http.route('/hr/get_org_chart', type='jsonrpc', auth='user')
    def get_org_chart(self, employee_id, new_parent_id=None, **kw):
        """
        Returns the org chart hierarchy structure starting from the total root head
        of the organization (CEO/top manager) all the way down to the leaf employee.
        """
        employee = self._get_employee(employee_id, **kw)
        new_parent = self._get_employee(new_parent_id, **kw).sudo()
        if not employee:
            return {
                'managers': [],
                'children': [],
            }

        ancestors, current = request.env['hr.employee.public'].sudo(), employee.sudo()
        current_parent = new_parent if new_parent_id is not None else current.parent_id

        # Traverse parent managers up to the absolute root (top head / CEO)
        while current_parent and current != current_parent and employee.sudo() != current_parent:
            current = current_parent
            current_parent = current.parent_id if current != employee or not new_parent else new_parent
            if current_parent in ancestors:
                break
            ancestors += current

        values = dict(
            self=self._prepare_employee_data(employee),
            managers=[
                self._prepare_employee_data(ancestor)
                for ancestor in ancestors
            ],
            managers_more=False,
            children=[self._prepare_employee_data(child) for child in employee.child_ids if child != employee],
        )
        values['managers'].reverse()
        return values



