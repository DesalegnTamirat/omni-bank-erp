from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ManagerDailyAttendanceWizard(models.TransientModel):
    """
    Lightweight wizard for managers to view their subordinate employees'
    attendance for a specific date. Unlike the branch-level report wizard
    (generate.detail.employee.attendance.report), this does NOT write to
    the generate_employee_attendance_details table. It returns a filtered
    list action directly so the manager sees live hr.attendance records.
    """
    _name = 'manager.daily.attendance.wizard'
    _description = 'Manager Daily Attendance Wizard'

    date_from = fields.Date(
        string='From Date',
        required=True,
        default=fields.Date.context_today,
    )
    date_to = fields.Date(
        string='To Date',
        required=True,
        default=fields.Date.context_today,
    )
    employee_ids = fields.Many2many(
        'hr.employee',
        string='Employees',
        help="Leave empty to include all employees under your management.",
    )
    include_all = fields.Boolean(
        string='Include All My Employees',
        default=True,
        help="When checked, all subordinate employees are included regardless of the Employees selection.",
    )

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise ValidationError(_("From Date cannot be greater than To Date."))

    def _get_subordinate_employee_ids(self):
        """
        Collect all employee IDs under this manager.
        Falls back to all active employees if the manager has no subordinates configured.
        """
        user = self.env.user
        manager_employee = user.employee_id

        if manager_employee:
            # Use Odoo's built-in subordinate traversal (includes indirect reports)
            subordinates = self.env['hr.employee'].search([
                ('parent_id', 'child_of', manager_employee.id),
                ('active', '=', True),
            ])
            if subordinates:
                return subordinates.ids

        # Fallback: all active employees (for top-level managers / HR)
        return self.env['hr.employee'].search([('active', '=', True)]).ids

    def action_generate_report(self):
        """
        Generates daily attendance report for the selected date range by calling the
        generate_detail_employee_attendance_report stored procedure to populate the
        generate_employee_attendance_details table, then opens the Daily Employee Attendance Detail view.
        """
        self.ensure_one()

        # Execute stored procedure to populate generate_employee_attendance_details table
        self.env.cr.execute(
            "SELECT generate_daily_employee_attendance_detail_report(%s, %s, %s)",
            (self.date_from, self.date_to, 'daily_detail')
        )

        return {
            'type': 'ir.actions.act_window',
            'name': _('Daily Employee Attendance Detail'),
            'res_model': 'generate.employee.attendance.details',
            'view_mode': 'list,search',
            'target': 'current',
        }

    # Backward-compatibility alias
    action_view_attendance = action_generate_report

