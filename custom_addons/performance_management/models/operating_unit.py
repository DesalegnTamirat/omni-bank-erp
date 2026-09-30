# -*- coding: utf-8 -*-
from odoo import api, fields, models


class OperatingUnit(models.Model):
    _inherit = 'operating.unit'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_performance_objectives()
        return records

    def write(self, vals):
        old_managers = self.mapped('manager_id') if 'manager_id' in vals else self.env['hr.employee']
        res = super().write(vals)
        if 'manager_id' in vals:
            self._sync_performance_objectives(old_managers=old_managers)
        return res

    def _sync_performance_objectives(self, old_managers=None):
        Objective = self.env['performance.objective'].sudo()
        emp_ids = set()

        for unit in self:
            if unit.manager_id:
                emp_ids.add(unit.manager_id.id)

        if old_managers:
            for old_mgr in old_managers:
                if old_mgr:
                    emp_ids.add(old_mgr.id)

        if emp_ids:
            objectives = Objective.search([
                '|',
                ('employee_id', 'in', list(emp_ids)),
                ('coach_id', 'in', list(emp_ids)),
            ])
            for obj in objectives:
                obj._compute_operating_units()
                self.env.cr.execute("""
                    UPDATE performance_objective
                    SET employee_operating_unit_id = %s,
                        coach_operating_unit_id = %s
                    WHERE id = %s
                """, (
                    obj.employee_operating_unit_id.id or None,
                    obj.coach_operating_unit_id.id or None,
                    obj.id
                ))
            self.env.invalidate_all()