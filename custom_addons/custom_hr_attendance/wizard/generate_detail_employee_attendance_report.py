from datetime import datetime
from odoo import models, api, fields, _
from odoo.exceptions import UserError, ValidationError


class GenerateDetailEmployeeAttendanceReport(models.TransientModel):
    _name = 'generate.detail.employee.attendance.report'
    _description = 'Generate Detail Employee Attendance Report Wizard'

    date_from = fields.Date(string="Date From", required=True)
    date_to = fields.Date(string="Date To", required=True)
    report_type = fields.Selection([
        ('attendance_summary', 'Attendance Summary'),
        ('attendance_preapproval', 'PreDefined Attendance'),
        ('acknowledged_attendance', 'Acknowledged Attendance'),
        ('job_position_exception', 'Job Position Exception'),
        ('over_time', 'Over Time'),
    ], required=True, default='attendance_summary')

    @api.constrains('date_from', 'date_to')
    def _check_date_range(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise ValidationError(_("Date From cannot be greater than Date To."))

    def generate(self):
        self.ensure_one()
        p_from = self.date_from
        p_to = self.date_to
        report_type = self.report_type

        # Execute high-performance PostgreSQL function registered by model init()
        self.env.cr.execute(
            "SELECT generate_daily_employee_attendance_detail_report(%s::date, %s::date, %s::varchar)",
            (p_from, p_to, report_type)
        )

        action_map = {
            'attendance_summary': {
                'type': 'ir.actions.act_window',
                'name': _('Employee Attendance Summary'),
                'res_model': 'generate.employee.attendance.details',
                'view_mode': 'list,search',
                'views': [(self.env.ref('custom_hr_attendance.view_employee_attendance_summary_tree').id, 'list')],
                'target': 'current',
            },
            'attendance_preapproval': {
                'type': 'ir.actions.act_window',
                'name': _('Predefined Attendance Report'),
                'res_model': 'attendance.preapproval.report',
                'view_mode': 'list,search',
                'domain': [('date', '>=', p_from), ('date', '<=', p_to)],
                'target': 'current',
            },
            'acknowledged_attendance': {
                'type': 'ir.actions.act_window',
                'name': _('Acknowledged Attendance Report'),
                'res_model': 'acknowledged.attendance.report',
                'view_mode': 'list,search',
                'domain': [('check_in', '>=', p_from), ('check_in', '<=', p_to)],
                'target': 'current',
            },
            'job_position_exception': {
                'type': 'ir.actions.act_window',
                'name': _('Job Position Exception Report'),
                'res_model': 'job.position.exception.report',
                'view_mode': 'list,search',
                'target': 'current',
            },
            'over_time': {
                'type': 'ir.actions.act_window',
                'name': _('Over Time Report'),
                'res_model': 'overtime.report',
                'view_mode': 'list,search',
                'domain': [('date', '>=', p_from), ('date', '<=', p_to)],
                'target': 'current',
            },
        }

        return action_map.get(report_type, action_map['attendance_summary'])



