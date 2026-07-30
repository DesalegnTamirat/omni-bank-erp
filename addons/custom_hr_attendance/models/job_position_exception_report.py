from odoo import models, fields, api


class JobPositionExceptionReport(models.Model):
    _name = 'job.position.exception.report'
    _description = 'Job Position Exception Report'

    employee_id = fields.Many2one("hr.employee", string="Employee")
    employee_identification = fields.Char(string="Employee ID", required=True)
    employee_name = fields.Char(string="Employee Name")
    place_of_assignment = fields.Char(string="Place of Assignment")
    work_unit = fields.Char(string="Work Unit")
    job_title = fields.Char(string="Job Title")
    manager_name = fields.Char(string="Manager Name")

    shift_name = fields.Char(string= 'Shift Name')
    time_range = fields.Char(string= 'Time Range')
    day_off = fields.Date(string='Day Off')
    status = fields.Char(string='Status')


