from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ResetEmployeeLoginWizard(models.TransientModel):
    _name = 'reset.employee.login.wizard'
    _description = 'Reset Employee Login Wizard'

    employee_id = fields.Many2one('hr.employee', string='Employee Name', required=True)
    user_login = fields.Char(string='User Login')

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id and self.employee_id.user_id:
            self.user_login = self.employee_id.user_id.login
        else:
            self.user_login = False

    def action_reset_employee_login(self):
        if not self.employee_id:
            raise UserError(_('Please select an employee.'))
        if not self.employee_id.user_id:
            raise UserError(_('This employee has no linked user.'))
        if not self.user_login:
            raise UserError(_('Please enter a new login.'))

        self.employee_id.user_id.sudo().write({'login': self.user_login})
        return {'type': 'ir.actions.act_window_close'}