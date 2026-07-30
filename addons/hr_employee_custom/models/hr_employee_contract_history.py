from odoo import fields, models


class HrEmployeeContractHistory(models.Model):
    _name = 'hr.employee.contract.history'
    _description = 'Employee Contract History'
    _order = 'updated_on desc'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        ondelete='cascade',
        index=True,
    )
    updated_on = fields.Datetime(
        string='Updated On',
        default=fields.Datetime.now,
        required=True,
    )
    changed_field = fields.Char(string='Changed Field')
    previous_value = fields.Char(string='Previous Value')
    new_value = fields.Char(string='New Value')
    current_contract_id = fields.Many2one(
        'hr.employee',
        string='Current Contract',
    )