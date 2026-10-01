# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class DisciplineAttendanceScanWizard(models.TransientModel):
    _name = 'discipline.attendance.scan.wizard'
    _description = 'Scan Attendance Violations & Initiate Disciplinary Cases'

    department_id = fields.Many2one('hr.department', string='Department / Branch')
    employee_ids = fields.Many2many('hr.employee', string='Specific Employees', help='Leave blank to scan all employees in selected department/company.')
    date_from = fields.Date(string='Scan Start Date', required=True, default=lambda self: fields.Date.today() - timedelta(days=30))
    date_to = fields.Date(string='Scan End Date', required=True, default=fields.Date.context_today)

    def action_scan_and_initiate(self):
        """Execute attendance scan and open created disciplinary cases."""
        self.ensure_one()
        employees = self.employee_ids
        if not employees and self.department_id:
            employees = self.env['hr.employee'].search([('department_id', '=', self.department_id.id), ('active', '=', True)])

        cases = self.env['hr.attendance'].scan_and_initiate_attendance_cases(
            employee_ids=employees,
            date_from=self.date_from,
            date_to=self.date_to
        )

        if not cases:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Attendance Scan Complete'),
                    'message': _('Scan completed for period %s to %s. No attendance violations exceeding threshold were found.') % (self.date_from, self.date_to),
                    'type': 'info',
                    'sticky': False,
                }
            }

        return {
            'type': 'ir.actions.act_window',
            'name': _('Initiated Attendance Disciplinary Cases'),
            'res_model': 'discipline.case',
            'view_mode': 'list,form',
            'domain': [('id', 'in', cases.ids)],
            'context': {'default_is_system_generated': True},
        }
