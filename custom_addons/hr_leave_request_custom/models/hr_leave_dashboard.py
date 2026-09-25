# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class HrLeaveDashboard(models.TransientModel):
    """Lightweight landing page shown when the Time Off app is opened.

    Deliberately a TransientModel so nothing is ever persisted: every time
    it's opened, default_get() recomputes the employee's balances fresh
    via the same logic hr.leave already uses, so the numbers can never
    go stale.
    """
    _name = 'hr.leave.dashboard'
    _description = 'Time Off Dashboard'

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        HrLeave = self.env['hr.leave']
        employee = HrLeave._get_current_employee()

        if not employee:
            return defaults

        balances = HrLeave._get_leave_balances(employee)
        defaults.update({
            'employee_id': employee.id,
            'accrued_leave_balance': balances.get('accrued', 0.0),
            'scheduled_leave_balance': balances.get('scheduled', 0.0),
        })
        return defaults

    employee_id = fields.Many2one('hr.employee', string='Employee', readonly=True)
    accrued_leave_balance = fields.Float(string='Accrued Leave Balance', digits=(16, 2), readonly=True)
    scheduled_leave_balance = fields.Float(string='Scheduled Leave Balance', digits=(16, 2), readonly=True)

    def action_open_my_requests(self):
        """Go to the existing My Time Off list/kanban (custom_saved=True only)."""
        self.ensure_one()
        action = self.env.ref('hr_holidays.hr_leave_action_my', raise_if_not_found=False)
        if action:
            act_dict = action.read()[0]
            act_dict['target'] = 'main'
            return act_dict
        return {
            'type': 'ir.actions.act_window',
            'name': _('My Time Off'),
            'res_model': 'hr.leave',
            'view_mode': 'list,form,kanban,activity',
            'domain': [('user_id', '=', self.env.user.id), ('custom_saved', '=', True)],
            'target': 'main',
        }

    def action_new_request(self):
        """Open a blank Leave Request form directly.

        Note: this module also ships an hr.leave.request.wizard model, but
        it has no access rights or view defined anywhere in the module, so
        it isn't usable as-is. Going straight to the hr.leave form matches
        exactly what the standard "New" button already does elsewhere in
        this app (same permissions, same custom form/Save/Notify flow),
        so this is the safe, already-working path.
        """
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Leave Request'),
            'res_model': 'hr.leave',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    def action_refresh(self):
        """Reopen the dashboard action so balances recompute."""
        return self.env.ref('hr_leave_request_custom.action_hr_leave_dashboard').read()[0]
