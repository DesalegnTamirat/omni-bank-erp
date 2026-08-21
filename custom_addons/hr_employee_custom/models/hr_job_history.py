# -*- coding: utf-8 -*-
from odoo import api, models, fields


class HrJobHistory(models.Model):
    _name = 'hr.job.history'
    _description = 'Employee Job History'
    _order = 'job_history_start_date desc, id desc'
    _rec_name = 'employee_id'

    employee_id = fields.Many2one(
        'hr.employee', string='Employee Name', required=True,
        ondelete='cascade', index=True,
    )
    job_id = fields.Many2one('hr.job', string='Job Name')
    grade_id = fields.Many2one('employee.grade', string='Grade')
    operating_unit_id = fields.Many2one('operating.unit', string='Operating Unit')
    department_id = fields.Many2one('hr.department', string='Department')
    position = fields.Char(string='Position')
    job_history_start_date = fields.Date(string='Job History Start Date')
    job_history_end_date = fields.Date(string='Job History End Date')
    reason_for_change = fields.Selection([
        ('promotion', 'Promotion'),
        ('transfer', 'Transfer'),
        ('demotion', 'Demotion'),
        ('acting_role', 'Acting Role'),
        ('recruitment', 'Recruitment / New Hire'),
        ('resignation', 'Resignation'),
        ('termination', 'Termination'),
        ('other', 'Other'),
    ], string='Reason for Change', default='other')
    is_current = fields.Boolean(
        string='Current Position', compute='_compute_is_current', store=True,
        help="True when this row has no end date, i.e. it is the employee's active position.",
    )

    @api.depends('job_history_end_date')
    def _compute_is_current(self):
        for rec in self:
            rec.is_current = not rec.job_history_end_date


class HrEmployeeJobHistory(models.Model):
    """Automatically maintains hr.job.history whenever an employee's
    position, grade, department, or operating unit changes — regardless
    of which flow triggers the change (promotion, demotion, transfer,
    acting role, recruitment, or a direct edit on the employee form).

    Every write that touches a tracked field:
      1. closes the currently-open history row (sets its end date), and
      2. opens a new history row starting the same day.

    No wizard needs to write to hr.job.history itself anymore — they
    just need to write the new job_position/job_grade/etc. on
    hr.employee, optionally passing a reason via context, e.g.:

        employee.with_context(job_history_reason='promotion').write({
            'job_position': new_job.id,
            'job_grade': new_grade.id,
        })

    If no reason is passed in context, it defaults to 'other'.
    """
    _inherit = 'hr.employee'

    job_history_ids = fields.One2many(
        'hr.job.history', 'employee_id',
        string='Job History',
        help="Chronological list of job positions — used by the Experience Letter report.",
    )

    # Fields on hr.employee whose change should be historized.
    # Adjust this list if you add more trackable fields later
    # (e.g. a custom job_category field).
    _JOB_HISTORY_TRACKED_FIELDS = (
        'job_position',
        'job_grade',
        'default_operating_unit_id',
        'department_id',
    )

    def write(self, vals):
        if self.env.context.get('in_job_history_logging'):
            return super().write(vals)
        tracked_fields = [f for f in self._JOB_HISTORY_TRACKED_FIELDS if f in vals]

        before = {}
        if tracked_fields:
            for emp in self:
                before[emp.id] = {f: emp[f].id for f in self._JOB_HISTORY_TRACKED_FIELDS}

        res = super().write(vals)

        if tracked_fields:
            self.with_context(in_job_history_logging=True)._log_job_history_changes(before)

        return res

    def _log_job_history_changes(self, before):
        JobHistory = self.env['hr.job.history']
        today = fields.Date.context_today(self)
        reason = self.env.context.get('job_history_reason', 'other')

        for emp in self:
            old = before.get(emp.id)
            if old is None:
                continue

            new = {f: emp[f].id for f in self._JOB_HISTORY_TRACKED_FIELDS}
            if old == new:
                continue  # nothing actually changed for this employee

            # Close the currently open history row, if one exists.
            # NOTE: always CLOSE it, never delete it — even if this is a
            # second change on the same calendar day. Deleting here was
            # the earlier bug: it silently erased every prior change
            # whenever two changes landed on the same day, leaving only
            # the most recent row. The `if old == new: continue` guard
            # above already prevents duplicate no-op writes from ever
            # reaching this point, so there's no need to delete anything
            # here — every real change, same day or not, gets its own row.
            open_history = JobHistory.search([
                ('employee_id', '=', emp.id),
                ('job_history_end_date', '=', False),
            ], order='job_history_start_date desc', limit=1)

            if open_history:
                open_history.job_history_end_date = today

            JobHistory.create({
                'employee_id': emp.id,
                'job_id': new['job_position'],
                'grade_id': new['job_grade'],
                'operating_unit_id': new['default_operating_unit_id'],
                'department_id': new['department_id'],
                'position': emp.job_position.name if emp.job_position else False,
                'job_history_start_date': today,
                'reason_for_change': reason,
            })

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        # Seed an initial (open-ended) job history row for brand-new
        # employees, so history is complete from day one of employment.
        for emp in employees:
            if emp.job_position or emp.job_grade:
                self.env['hr.job.history'].create({
                    'employee_id': emp.id,
                    'job_id': emp.job_position.id,
                    'grade_id': emp.job_grade.id,
                    'operating_unit_id': emp.default_operating_unit_id.id,
                    'department_id': emp.department_id.id,
                    'position': emp.job_position.name if emp.job_position else False,
                    'job_history_start_date': fields.Date.context_today(self),
                    'reason_for_change': 'recruitment',
                })
        return employees