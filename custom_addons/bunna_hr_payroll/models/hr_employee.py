from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'
    _description = 'Employee'

    slip_ids = fields.One2many('hr.payslip', 'employee_id', string='Payslips', readonly=True)
    payslip_count = fields.Integer(compute='_compute_payslip_count', string='Payslip Count',
                                   groups="om_bunna_hr_payroll.group_hr_payroll_user")
    struct_id = fields.Many2one(
        related="current_version_id.struct_id",
        string='Salary Structure',
        store=True,
        readonly=False
    )
    exclude_from_payroll = fields.Boolean(
        string='Hold / Exclude from Payroll',
        default=False,
        tracking=True,
        help='If checked, this employee will be automatically excluded during payroll batch generation.'
    )
    payroll_exclude_reason = fields.Char(
        string='Payroll Exclusion Reason',
        help='Reason why this employee is excluded from payroll (e.g. Pending Clearance, Sabbatical, Disciplinary Investigation, Account Freeze).'
    )
    def _compute_payslip_count(self):
        for employee in self:
            employee.payslip_count = len(employee.slip_ids)
