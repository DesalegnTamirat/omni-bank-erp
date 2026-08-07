from odoo import models, fields


class HrTimesheetCostHistory(models.Model):
    _name = 'hr.timesheet.cost.history'
    _description = 'Employee Timesheet Cost History'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, ondelete='cascade')
    updated_on = fields.Date(string='Updated On')
    current_cost = fields.Float(string='Current Cost')