# -*- coding: utf-8 -*-
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class DisciplineAttendanceScanWizard(models.TransientModel):
    _name = 'discipline.attendance.scan.wizard'
    _description = 'Scan Attendance & Absence Violations'

    @api.model
    def _default_late_minutes_threshold(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return int(ICP.get_param('discipline.attendance_late_minutes_threshold', 60))

    @api.model
    def _default_absence_cumulative_threshold(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return int(ICP.get_param('discipline.absence_cumulative_days_threshold', 2))

    @api.model
    def _default_absence_warning_days(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return int(ICP.get_param('discipline.absence_warning_consecutive_days', 3))

    @api.model
    def _default_absence_dismissal_days(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return int(ICP.get_param('discipline.absence_dismissal_consecutive_days', 5))

    @api.model
    def _default_enable_force_checkout(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return ICP.get_param('discipline.enable_force_checkout_discipline', 'False').lower() in ('true', '1')

    @api.model
    def _default_force_threshold(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return int(ICP.get_param('discipline.attendance_force_checkout_threshold', 3))

    @api.model
    def _default_scan_scope(self):
        user = self.env.user
        is_admin_or_officer = (
            user.has_group('discipline_management.group_discipline_admin') or
            user.has_group('discipline_management.group_discipline_pomd') or
            user.has_group('discipline_management.group_discipline_cpco') or
            user.has_group('discipline_management.group_discipline_ceo') or
            user.has_group('base.group_system')
        )
        return 'all_bank' if is_admin_or_officer else 'my_team'

    is_hr_admin = fields.Boolean(compute='_compute_user_roles')
    is_supervisor = fields.Boolean(compute='_compute_user_roles')
    mandate_notice = fields.Char(compute='_compute_user_roles')
    
    scan_scope = fields.Selection([
        ('my_team', 'My Supervised Team / Direct Subordinates'),
        ('department', 'Specific Department / Branch Directorate'),
        ('specific_employees', 'Specific Employee(s)'),
        ('all_bank', 'Entire Bank (All Active Employees)'),
    ], string='Scan Scope', default=_default_scan_scope, required=True)

    department_id = fields.Many2one('hr.department', string='Target Department / Branch')
    employee_ids = fields.Many2many(
        'hr.employee',
        'attendance_scan_wizard_employee_rel',
        'wizard_id',
        'employee_id',
        string='Target Employees'
    )

    violation_type = fields.Selection([
        ('all', 'All Violations (Absence, Lateness & Force Check-Out)'),
        ('absence', 'Unexcused Absence (Statutory Escalation)'),
        ('late', 'Cumulative Late Time (Minutes Duration)'),
        ('force_checkout', 'Force Check-Out (Operational Compliance)'),
    ], string='Violation Filter', default='all', required=True)

    period_preset = fields.Selection([
        ('last_7_days', 'Last 7 Days'),
        ('last_14_days', 'Last 14 Days'),
        ('last_30_days', 'Last 30 Days (Rolling Standard)'),
        ('current_month', 'Current Month (Month-to-Date)'),
        ('previous_month', 'Previous Calendar Month'),
        ('custom', 'Custom Date Range'),
    ], string='Evaluation Period', default='last_30_days', required=True)

    date_from = fields.Date(string='Scan Start Date', required=True, default=lambda self: fields.Date.today() - timedelta(days=30))
    date_to = fields.Date(string='Scan End Date', required=True, default=fields.Date.context_today)
    
    late_minutes_threshold = fields.Integer(
        string='Total Late Time Threshold (Minutes)',
        required=True,
        default=_default_late_minutes_threshold,
        help='Cumulative late minutes across the period required to initiate a disciplinary case.'
    )
    absence_cumulative_threshold = fields.Integer(
        string='Cumulative Absence Threshold (Days)',
        required=True,
        default=_default_absence_cumulative_threshold,
        help='Minimum unexcused absent days to trigger a written warning.'
    )
    absence_consecutive_warning = fields.Integer(
        string='Consecutive Absence for Final Warning',
        required=True,
        default=_default_absence_warning_days,
        help='Consecutive unexcused absent days triggering Level 2 Final Warning.'
    )
    absence_consecutive_dismissal = fields.Integer(
        string='Consecutive Absence for Dismissal',
        required=True,
        default=_default_absence_dismissal_days,
        help='Consecutive unexcused absent days triggering Level 1 Dismissal / Committee Escalation.'
    )

    enable_force_checkout = fields.Boolean(
        string='Evaluate Force Check-Out Violations',
        default=_default_enable_force_checkout,
        help='If checked, repeated force check-outs exceeding the threshold will trigger cases.'
    )
    force_threshold = fields.Integer(
        string='Force Check-Out Count Threshold',
        default=_default_force_threshold,
        help='Minimum number of force check-out events required to trigger a case.'
    )

    skip_existing_active_cases = fields.Boolean(
        string='Skip Employees with Open Cases',
        default=True,
        help='If checked, will not create a duplicate case for employees who already have an active/pending disciplinary case in this period.'
    )

    @api.depends('scan_scope')
    def _compute_user_roles(self):
        user = self.env.user
        emp = user.employee_id
        is_admin = (
            user.has_group('discipline_management.group_discipline_admin') or
            user.has_group('discipline_management.group_discipline_pomd') or
            user.has_group('discipline_management.group_discipline_cpco') or
            user.has_group('discipline_management.group_discipline_ceo') or
            user.has_group('base.group_system')
        )
        for rec in self:
            rec.is_hr_admin = is_admin
            if is_admin:
                rec.is_supervisor = True
                rec.mandate_notice = _('Governance Mandate: You have bank-wide authority to scan all departments, branches, or specific employees.')
            elif emp:
                rec.is_supervisor = True
                rec.mandate_notice = _('Supervisory Mandate: You are scanning attendance for your assigned subordinates / supervised staff.')
            else:
                rec.is_supervisor = False
                rec.mandate_notice = _('No direct subordinates linked to your user profile.')

    @api.onchange('period_preset')
    def _onchange_period_preset(self):
        today = fields.Date.today()
        if self.period_preset == 'last_7_days':
            self.date_from = today - timedelta(days=7)
            self.date_to = today
        elif self.period_preset == 'last_14_days':
            self.date_from = today - timedelta(days=14)
            self.date_to = today
        elif self.period_preset == 'last_30_days':
            self.date_from = today - timedelta(days=30)
            self.date_to = today
        elif self.period_preset == 'current_month':
            self.date_from = today.replace(day=1)
            self.date_to = today
        elif self.period_preset == 'previous_month':
            first_this_month = today.replace(day=1)
            last_month_end = first_this_month - timedelta(days=1)
            self.date_from = last_month_end.replace(day=1)
            self.date_to = last_month_end

    @api.onchange('scan_scope')
    def _onchange_scan_scope_domain(self):
        user = self.env.user
        emp = user.employee_id
        is_admin = (
            user.has_group('discipline_management.group_discipline_admin') or
            user.has_group('discipline_management.group_discipline_pomd') or
            user.has_group('discipline_management.group_discipline_cpco') or
            user.has_group('discipline_management.group_discipline_ceo') or
            user.has_group('base.group_system')
        )
        if not is_admin:
            if self.scan_scope in ('all_bank', 'department'):
                self.scan_scope = 'my_team'
            if emp:
                sub_domain = [
                    '|', '|',
                    ('parent_id', '=', emp.id),
                    ('coach_id', '=', emp.id),
                    ('department_id.manager_id', '=', emp.id)
                ]
                return {'domain': {'employee_ids': sub_domain}}
        return {'domain': {'employee_ids': [('active', '=', True)]}}

    def _get_target_employees(self):
        user = self.env.user
        emp = user.employee_id
        is_admin = (
            user.has_group('discipline_management.group_discipline_admin') or
            user.has_group('discipline_management.group_discipline_pomd') or
            user.has_group('discipline_management.group_discipline_cpco') or
            user.has_group('discipline_management.group_discipline_ceo') or
            user.has_group('base.group_system')
        )

        if self.scan_scope == 'specific_employees':
            if not self.employee_ids:
                raise UserError(_('Please select at least one employee to scan.'))
            if not is_admin and emp:
                sub_ids = self.env['hr.employee'].sudo().search([
                    '|', '|',
                    ('parent_id', '=', emp.id),
                    ('coach_id', '=', emp.id),
                    ('department_id.manager_id', '=', emp.id)
                ]).ids
                invalid = self.employee_ids.filtered(lambda e: e.id not in sub_ids and e.id != emp.id)
                if invalid:
                    raise UserError(_('Mandate Restriction: You can only scan attendance for your direct supervised subordinates (%s).') % ', '.join(invalid.mapped('name')))
            return self.employee_ids

        elif self.scan_scope == 'my_team':
            if not emp:
                raise UserError(_('No employee record linked to your user account.'))
            subordinates = self.env['hr.employee'].sudo().search([
                '|', '|',
                ('parent_id', '=', emp.id),
                ('coach_id', '=', emp.id),
                ('department_id.manager_id', '=', emp.id)
            ])
            if not subordinates:
                raise UserError(_('No subordinate employees found under your supervision.'))
            return subordinates

        elif self.scan_scope == 'department':
            if not is_admin:
                raise UserError(_('Authority Restriction: Department-wide scanning requires HR Administrator or Governance role.'))
            if not self.department_id:
                raise UserError(_('Please select a target Department / Branch to scan.'))
            return self.env['hr.employee'].sudo().search([
                ('department_id', '=', self.department_id.id),
                ('active', '=', True)
            ])

        elif self.scan_scope == 'all_bank':
            if not is_admin:
                raise UserError(_('Authority Restriction: Bank-wide scanning is restricted to HR Administrators and Governance Officers.'))
            return self.env['hr.employee'].sudo().search([('active', '=', True)])

        return self.env['hr.employee']

    def action_scan_and_initiate(self):
        """Execute multi-tier attendance & absence scan and open created disciplinary cases."""
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('Scan Start Date cannot be later than Scan End Date.'))
        if self.late_minutes_threshold < 1:
            raise UserError(_('Late Time Threshold must be at least 1 minute.'))

        employees = self._get_target_employees()

        cases = self.env['hr.attendance'].scan_and_initiate_attendance_cases(
            employee_ids=employees,
            date_from=self.date_from,
            date_to=self.date_to,
            violation_type=self.violation_type,
            late_minutes_threshold=self.late_minutes_threshold,
            absence_warning_consecutive_days=self.absence_consecutive_warning,
            absence_dismissal_consecutive_days=self.absence_consecutive_dismissal,
            absence_cumulative_days_threshold=self.absence_cumulative_threshold,
            enable_force_checkout=self.enable_force_checkout,
            force_threshold=self.force_threshold,
            skip_existing_active_cases=self.skip_existing_active_cases,
        )

        emp_count = len(employees)
        case_count = len(cases)

        if not cases:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Attendance & Absence Evaluation Complete'),
                    'message': _(
                        'Evaluation completed across %d employee(s) for period %s to %s.\n'
                        'No attendance or unexcused absence violations exceeding configured thresholds were found.'
                    ) % (emp_count, self.date_from, self.date_to),
                    'type': 'info',
                    'sticky': False,
                }
            }

        if case_count == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Initiated Disciplinary Case: %s') % cases.name,
                'res_model': 'discipline.case',
                'res_id': cases.id,
                'view_mode': 'form',
                'target': 'current',
                'context': {'default_is_system_generated': True},
            }

        return {
            'type': 'ir.actions.act_window',
            'name': _('Initiated Attendance Disciplinary Cases (%d Created)') % case_count,
            'res_model': 'discipline.case',
            'view_mode': 'list,form',
            'domain': [('id', 'in', cases.ids)],
            'context': {'default_is_system_generated': True},
        }
