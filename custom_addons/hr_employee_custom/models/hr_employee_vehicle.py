# -*- coding: utf-8 -*-
# Migrated from the standalone hr_contract module (models/hr_employee.py)
# so that hr_employee_custom no longer depends on the hr_contract module.
# Only the 'vehicle' field is migrated here: the contract_id/contract_ids/
# first_contract_date/contracts_count/contract_warning/calendar_mismatch
# fields and the write() override already exist (in an improved, Odoo-19
# adapted form) in hr_employee_contract.py, so they are not duplicated here.

from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    vehicle = fields.Char(string='Company Vehicle', groups="hr.group_hr_user")
