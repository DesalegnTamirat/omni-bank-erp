from odoo import models, fields, api


class OverTimeReport(models.Model):
    _name = 'overtime.report'
    _description = 'Over Time Report'
    _order = 'employee_id'

    employee_id = fields.Many2one("hr.employee", string="Employee")
    employee_identification = fields.Char(string="Employee ID")
    employee_name = fields.Char(string="Employee Name")
    place_of_assignment = fields.Char(string="Place of Assignment")
    work_unit = fields.Char(string="Work Unit")
    job_title = fields.Char(string="Job Title")
    manager_name = fields.Char(string="Manager Name")
    #date = fields.Date(string="Date")
    over_time_hours = fields.Float(
        string="Total Over Time"
    )

    used_hours = fields.Float(
        string="Used Hours"
    )

    remaining_hours = fields.Float(
        string="Remaining Hours",
        compute="_compute_remaining_hours",
        store=True
    )
    state = fields.Char(string="Status")

    @api.depends('over_time_hours', 'used_hours')
    def _compute_remaining_hours(self):
        for rec in self:
            rec.remaining_hours = max(0.0, rec.over_time_hours - rec.used_hours)

