# -*- coding: utf-8 -*-
from odoo import models, fields


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    def _load_menus_blacklist(self):
        res = super()._load_menus_blacklist()

        user = self.env.user
        emp = user.employee_id or self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)

        # A user is eligible to see "My Team's Resignations" if:
        # 1. They belong to the Coach / Supervisor security group (group_hr_coach), OR
        # 2. Their employee record is configured as the coach_id or direct manager (parent_id) of active employees, OR
        # 3. They are acting as an active delegate for a manager/coach who has subordinates.
        is_coach = False
        if user.has_group('hr_employee_custom.group_hr_coach'):
            is_coach = True
        elif emp:
            is_coach = bool(self.env['hr.employee'].sudo().search_count([
                '|',
                ('coach_id', '=', emp.id),
                ('parent_id', '=', emp.id),
            ]) > 0)

        # Check active delegation if delegation model exists
        if not is_coach and emp and 'hr.employee.delegation' in self.env:
            today = fields.Date.today()
            delegations = self.env['hr.employee.delegation'].sudo().search([
                ('delegate_id', '=', emp.id),
                ('state', '=', 'submitted'),
                ('start_date', '<=', today),
                ('end_date', '>=', today),
            ])
            delegator_ids = delegations.mapped('employee_id.id')
            if delegator_ids:
                is_coach = bool(self.env['hr.employee'].sudo().search_count([
                    '|',
                    ('coach_id', 'in', delegator_ids),
                    ('parent_id', 'in', delegator_ids),
                ]) > 0)

        # If user is not a coach of any employee, blacklist "My Team's Resignations"
        if not is_coach:
            team_menu = self.env.ref('hr_resignation.menu_hr_resignation_team_restricted', raise_if_not_found=False)
            if team_menu and team_menu.id not in res:
                res.append(team_menu.id)

        return res
