# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import AccessError


class HrEmployeeAttendanceCounters(models.Model):
    """
    Delegates violation counter increments and resets to the decoupled
    hr.employee.discipline.profile model, keeping hr_employee table 100% clean.
    """
    _inherit = 'hr.employee'

    def _check_private_fields(self, field_names):
        """ Prevent AccessError for non-HR employees when accessing employee records """
        try:
            super()._check_private_fields(field_names)
        except AccessError:
            if self.env.user.has_group('custom_hr_attendance.group_hr_attendance_manual_user') or self.env.user.has_group('base.group_user'):
                return
            raise

    def _increment_late_count(self):
        self.ensure_one()
        return self.env['hr.employee.discipline.profile']._increment_late_count(self.id)

    def _increment_force_checkout_count(self):
        self.ensure_one()
        return self.env['hr.employee.discipline.profile']._increment_force_checkout_count(self.id)

    def _increment_missing_lunch_tap_count(self):
        self.ensure_one()
        return self.env['hr.employee.discipline.profile']._increment_missing_lunch_tap_count(self.id)

    def _reset_late_count(self):
        self.ensure_one()
        return self.env['hr.employee.discipline.profile']._reset_late_count(self.id)

    def _reset_force_checkout_count(self):
        self.ensure_one()
        return self.env['hr.employee.discipline.profile']._reset_force_checkout_count(self.id)

    def _reset_missing_lunch_tap_count(self):
        self.ensure_one()
        return self.env['hr.employee.discipline.profile']._reset_missing_lunch_tap_count(self.id)

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        managers = employees.mapped('parent_id')
        if managers:
            managers.mapped('user_id')._sync_attendance_manager_groups()
        return employees

    def write(self, vals):
        old_parents = self.mapped('parent_id')
        res = super().write(vals)
        if 'parent_id' in vals or 'user_id' in vals:
            new_parents = self.mapped('parent_id')
            all_managers = (old_parents | new_parents)
            all_managers.mapped('user_id')._sync_attendance_manager_groups()
            self.mapped('user_id')._sync_attendance_manager_groups()
        return res


