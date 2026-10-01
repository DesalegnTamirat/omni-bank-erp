import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class HrEmployeeCustom(models.Model):
    _inherit = 'hr.employee'

    job_grade = fields.Char(string='Job Grade')
    job_category = fields.Char(string='Job Category')
    operating_unit = fields.Many2one('operating.unit', string='Operating Unit')

    # Add gender field if it doesn't exist in base hr.employee
    # In Odoo 19, gender might not be a standard field
    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
    ], string='Gender')

    @api.model
    def get_employee_leave_balances(self, employee_id=None):
        """Direct RPC method to fetch accrued and scheduled leave balances."""
        employee = None
        if employee_id:
            try:
                employee = self.browse(int(employee_id)).exists()
            except Exception:
                employee = None

        if not employee or not employee.exists():
            employee = self.env['hr.leave']._get_current_employee()

        if not employee or not employee.exists():
            employee = self.env.user.employee_id or self.env['hr.employee'].sudo().search(
                [('user_id', '=', self.env.user.id)], limit=1
            )

        if not employee or not employee.exists():
            _logger.warning("get_employee_leave_balances: No employee found for user %s", self.env.user.id)
            return {'accrued': 0.0, 'scheduled': 0.0}

        try:
            balances = self.env['hr.leave']._get_leave_balances(employee)
            accrued = round(float(balances.get('accrued', 0.0)), 2)
            scheduled = round(float(balances.get('scheduled', 0.0)), 2)
            _logger.info("get_employee_leave_balances: Employee %s (#%s) -> Accrued: %s, Scheduled: %s",
                         employee.name, employee.id, accrued, scheduled)
            return {
                'accrued': accrued,
                'scheduled': scheduled,
                'employee_id': employee.id,
                'employee_name': employee.name,
            }
        except Exception as e:
            _logger.exception("Error computing leave balances in get_employee_leave_balances: %s", e)
            return {'accrued': 0.0, 'scheduled': 0.0}

    @api.model
    def get_time_off_dashboard_data(self, target_date=None):
        dashboard_data = super().get_time_off_dashboard_data(target_date=target_date)

        ctx_employee_id = self.env.context.get('employee_id') or self.env.context.get('default_employee_id')
        balances = self.get_employee_leave_balances(employee_id=ctx_employee_id)
        dashboard_data['accrued_leave_balance'] = balances.get('accrued', 0.0)
        dashboard_data['scheduled_leave_balance'] = balances.get('scheduled', 0.0)
        return dashboard_data