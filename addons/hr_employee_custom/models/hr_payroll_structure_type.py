# -*- coding: utf-8 -*-
# Migrated from the standalone hr_contract module (models/hr_contract_type.py)
# so that hr_employee_custom no longer depends on the hr_contract module.
# Fields and logic are unchanged.

from odoo import fields, models


class HrPayrollStructureType(models.Model):
    _name = 'hr.payroll.structure.type'
    _description = 'Contract Type'

    name = fields.Char('Contract Type')
    default_resource_calendar_id = fields.Many2one(
        'resource.calendar', 'Default Working Hours',
        default=lambda self: self.env.company.resource_calendar_id)
    country_id = fields.Many2one('res.country', string='Country', default=lambda self: self.env.company.country_id)
