from odoo import models, fields


class AcknowledgedAttendanceReport(models.Model):
    _name = 'acknowledged.attendance.report'
    _description = 'Acknowledged Attendance Report'

    employee_id = fields.Many2one(
        'hr.employee',
        string="Employee",
        readonly=True
    )

    employee_identification = fields.Char(
        string="Employee ID",
        readonly=True
    )

    employee_name = fields.Char(
        string="Employee Name",
        readonly=True
    )

    place_of_assignment = fields.Char(
        string="Place of Assignment",
        readonly=True
    )

    check_in = fields.Datetime(
        string="Check In",
        readonly=True
    )

    check_out = fields.Datetime(
        string="Check Out",
        readonly=True
    )

    reason_type = fields.Char(
        string="Acknowledged Type",
        readonly=True
    )

    reason_name = fields.Char(
        string="Attendance Reason",
        readonly=True
    )

    acknowledged_by = fields.Char(
        string="Acknowledged By",
        readonly=True
    )

    acknowledged_date = fields.Datetime(
        string="Acknowledged Date",
        readonly=True
    )
