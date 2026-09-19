# -*- coding: utf-8 -*-
from odoo import fields, models


class OperatingUnit(models.Model):
    _inherit = 'operating.unit'

    def write(self, vals):
        res = super().write(vals)
        if 'manager_id' in vals:
            for unit in self:
                objectives = self.env['performance.objective'].search([
                    ('employee_operating_unit_id', '=', unit.id),
                ])
                if not objectives:
                    continue

                new_manager = unit.manager_id
                new_coach = new_manager.coach_id

                for obj in objectives:
                    update_vals = {'employee_id': new_manager.id}

                    if obj.parent_objective_id:
                        # Only clear it if the new manager's coach no longer
                        # matches who the current parent Objective actually
                        # belongs to. If they match, the cascade is still
                        # valid — leave it untouched.
                        current_owner = obj.parent_objective_id.employee_id
                        if not new_coach or current_owner != new_coach:
                            update_vals['parent_objective_id'] = False

                    obj.write(update_vals)

                objectives._compute_operating_units()
        return res