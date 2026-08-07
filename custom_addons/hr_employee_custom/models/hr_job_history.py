from odoo import models, fields, api


class HrJobHistory(models.Model):
    _name = 'hr.job.history'
    _description = 'Employee Job History'
    _order = 'job_history_start_date'

    employee_id = fields.Many2one('hr.employee', string='Employee Name', required=True, ondelete='cascade')
    job_id = fields.Many2one('hr.job', string='Job Name')
    grade_id = fields.Many2one('employee.grade', string='Grade')
    operating_unit_id = fields.Many2one('operating.unit', string='Operating Unit')
    position = fields.Char(string='Position')
    job_history_start_date = fields.Date(string='Job History Start Date')
    job_history_end_date = fields.Date(string='Job History End Date')
    reason_for_change = fields.Selection([
        ('promotion', 'Promotion'),
        ('transfer', 'Transfer'),
        ('demotion', 'Demotion'),
        ('resignation', 'Resignation'),
        ('termination', 'Termination'),
        ('other', 'Other'),
    ], string='Reason for Change')


class HrEmployeeJobHistoryLink(models.Model):
    """Adds job_history_ids reverse One2many to hr.employee
    so the experience letter report can loop over job history rows."""
    _inherit = 'hr.employee'

    job_history_ids = fields.One2many(
        'hr.job.history', 'employee_id',
        string='Job History',
        help="Chronological list of job positions — used by the Experience Letter report.",
    )