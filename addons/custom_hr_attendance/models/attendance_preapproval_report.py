from odoo import models, fields


class AttendancepreApprovalReport(models.Model):
    _name = 'attendance.preapproval.report'
    _description = 'PreDefined Attendance Report'

    employee_id = fields.Many2one("hr.employee", string="Employee")
    employee_identification = fields.Char(string="Employee ID", required=True)
    employee_name = fields.Char(string="Employee Name")
    place_of_assignment = fields.Char(string="Place of Assignment")
    work_unit = fields.Char(string="Work Unit")
    # manager_name = fields.Char(string="Manager Name")

    exception_type = fields.Char(string="Exception Type")
    approval_reason = fields.Char(string="Approval Reason")
    date = fields.Date(string="Date")
    start_time = fields.Float(string="Start Time")
    end_time = fields.Float(string="End Time")
    status = fields.Char(string="Status")
    approved_by = fields.Char(string="Approved By")
