from odoo import api, fields, models


class HrEmployeeTransferHistory(models.Model):
    _name = 'hr.employee.transfer.history'
    _description = 'Employee Transfer History'
    _order = 'start_date desc, id desc'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        ondelete='cascade',
        index=True,
    )
    date = fields.Date(
        string='Date',
        default=fields.Date.context_today,
        required=True,
    )
    start_date = fields.Date(
        string='Start Date',
        default=fields.Date.context_today,
    )
    end_date = fields.Date(
        string='End Date',
    )
    is_current = fields.Boolean(
        string='Current Transfer', compute='_compute_is_current', store=True,
        help="True when this row has no end date.",
    )
    transfer_reason = fields.Char(string='Transfer Reason')

    # From
    from_operating_unit_id = fields.Many2one('operating.unit', string='From Operating Unit')
    from_department_id = fields.Many2one('hr.department', string='From Department')
    from_job_id = fields.Many2one('hr.job', string='From Position')
    from_grade_id = fields.Many2one('employee.grade', string='From Grade')

    # To
    to_operating_unit_id = fields.Many2one('operating.unit', string='To Operating Unit')
    to_department_id = fields.Many2one('hr.department', string='To Department')
    to_job_id = fields.Many2one('hr.job', string='To Position')
    to_grade_id = fields.Many2one('employee.grade', string='To Grade')

    @api.depends('end_date')
    def _compute_is_current(self):
        for rec in self:
            rec.is_current = not rec.end_date