# Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class HrPayslipEmployees(models.TransientModel):
    _name = 'hr.payslip.employees'
    _description = 'Generate payslips for all selected employees'

    employee_ids = fields.Many2many('hr.employee', 'hr_employee_group_rel', 'payslip_id', 'employee_id', 'Employees')

    def compute_sheet(self):
        payslips = self.env['hr.payslip']
        [data] = self.read()
        active_id = self.env.context.get('active_id')
        if active_id:
            [run_data] = self.env['hr.payslip.run'].browse(active_id).read(['date_start', 'date_end', 'credit_note', 'period_id', 'payment_date'])
        from_date = run_data.get('date_start')
        to_date = run_data.get('date_end')
        period_id = run_data.get('period_id') and run_data.get('period_id')[0] or False
        if period_id:
            period = self.env['hr.payroll.period'].browse(period_id)
            if period.state == 'closed':
                raise UserError(_("Cannot generate payslips for a closed payroll period ('%s'). Finalized periods are locked in viewing mode.") % period.name)
        payment_date = run_data.get('payment_date') or False
        if not data['employee_ids']:
            raise UserError(_("You must select employee(s) to generate payslip(s)."))
        skipped = []
        slip_vals_list = []
        for employee in self.env['hr.employee'].browse(data['employee_ids']):
            version_ids = self.env['hr.payslip'].sudo().get_versions(employee, from_date, to_date)
            if not version_ids:
                skipped.append(employee.name)
                continue
            slip_data = self.env['hr.payslip'].sudo().onchange_employee_id(from_date, to_date, employee.id, contract_id=False)
            res = {
                'employee_id': employee.id,
                'name': slip_data['value'].get('name'),
                'struct_id': slip_data['value'].get('struct_id'),
                'version_id': slip_data['value'].get('version_id'),
                'payslip_run_id': active_id,
                'period_id': period_id,
                'payment_date': payment_date,
                'input_line_ids': [(0, 0, x) for x in slip_data['value'].get('input_line_ids')],
                'worked_days_line_ids': [(0, 0, x) for x in slip_data['value'].get('worked_days_line_ids')],
                'date_from': from_date,
                'date_to': to_date,
                'credit_note': run_data.get('credit_note'),
                'company_id': employee.company_id.id,
            }
            slip_vals_list.append(res)
        if slip_vals_list:
            payslips = self.env['hr.payslip'].sudo().create(slip_vals_list)
            payslips.sudo().compute_sheet()
        if skipped and not payslips:
            raise UserError(_("No payslips could be generated. The following employee(s) have no active contract/version for the period (%s - %s):\n\n%s") % (from_date, to_date, ', '.join(skipped)))
        return {'type': 'ir.actions.act_window_close'}
