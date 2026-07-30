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
            "SELECT generate_detail_employee_attendance_report(%s::date, %s::date, %s::varchar)",
            (p_from, p_to, report_type)
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Report Generated'),
                'message': _('Employee Attendance Report data has been populated successfully.'),
                'sticky': False,
                'type': 'success',
            }
        }



