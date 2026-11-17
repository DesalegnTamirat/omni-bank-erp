# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        try:
            records._sync_employee_operating_units()
        except Exception as e:
            _logger.warning("Bunna Helpdesk: hr.employee create OU sync skipped: %s", e)
        return records

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ("default_operating_unit_id", "operating_unit_id", "operating_unit_ids")):
            try:
                self._sync_employee_operating_units()
            except Exception as e:
                _logger.warning("Bunna Helpdesk: hr.employee write OU sync skipped: %s", e)
        return res

    def _sync_employee_operating_units(self):
        """When an employee is assigned an operating unit, ensure the unit and all its parents have teams synced.
        Guarded so that any failure in helpdesk synchronization never affects HR employee operations.
        """
        try:
            ous = self.mapped("default_operating_unit_id")
            if hasattr(self, "operating_unit_ids"):
                ous |= self.mapped("operating_unit_ids")
            if hasattr(self, "operating_unit_id"):
                ous |= self.mapped("operating_unit_id")

            all_units = self.env["operating.unit"]
            for ou in ous.filtered(lambda o: o.active):
                curr = ou
                visited = set()
                while curr and curr.id not in visited:
                    visited.add(curr.id)
                    all_units |= curr
                    curr = curr.parent_unit if curr.parent_unit and curr.parent_unit != curr else False
            if all_units:
                all_units._sync_helpdesk_teams()
        except Exception as e:
            _logger.warning("Bunna Helpdesk: _sync_employee_operating_units error: %s", e)
