# -*- coding: utf-8 -*-
from datetime import date, timedelta
from markupsafe import Markup
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class DisciplineAttendanceScanWizard(models.TransientModel):
    _name = 'discipline.attendance.scan.wizard'
    _description = 'Scan Bank Attendance Violations (HR Mandate)'

    @api.model
    def default_get(self, fields_list):
        user = self.env.user
        is_hr_admin = (
            user.has_group('discipline_management.group_discipline_admin') or
            user.has_group('discipline_management.group_discipline_pomd') or
            user.has_group('base.group_system') or
            self.env.su
        )
        if not is_hr_admin:
            raise UserError(_("Access Restricted: Attendance violation scans can only be performed by Human Resources / POMD."))

        res = super().default_get(fields_list)
        today = fields.Date.context_today(self)
        yesterday = today - timedelta(days=1)
        res['period_preset'] = 'this_month'
        start_of_month = today.replace(day=1)
        res['date_from'] = start_of_month
        res['date_to'] = yesterday if yesterday >= start_of_month else today
        return res

    period_preset = fields.Selection([
        ('this_week', 'This Week (Monday to Yesterday)'),
        ('this_month', 'This Month (Month-to-Date)'),
        ('custom', 'Custom Date Range'),
    ], string='Evaluation Period', default='this_month', required=True)

    date_from = fields.Date(string='Scan Start Date', required=True)
    date_to = fields.Date(string='Scan End Date', required=True)

    skip_existing_active_cases = fields.Boolean(
        string='Skip Employees with Open Cases',
        default=True,
        help='If checked, will not create duplicate cases for employees who already have active or pending disciplinary cases in this period.'
    )

    total_employees_count = fields.Integer(
        string='Employees to Evaluate',
        compute='_compute_stats',
        help='Total active bank employees that will be evaluated across the bank.'
    )

    policy_summary_html = fields.Html(
        string='Active Bank Policy Thresholds',
        compute='_compute_stats'
    )

    @api.model
    def _get_active_contracted_employee_ids(self):
        """Returns IDs of employees who are active in hr.employee AND have an active contract in hr.version."""
        self.env.cr.execute("""
            SELECT DISTINCT he.id 
            FROM hr_employee he
            JOIN hr_version hv ON hv.employee_id = he.id
            WHERE he.active = true AND hv.active = true
        """)
        rows = self.env.cr.fetchall()
        if rows:
            return [r[0] for r in rows]
        return self.env['hr.employee'].sudo().search([('active', '=', True)]).ids

    @api.depends('period_preset')
    def _compute_stats(self):
        active_ids = self._get_active_contracted_employee_ids()
        emp_count = len(active_ids)
        for rec in self:
            rec.total_employees_count = emp_count
            rec.policy_summary_html = False

    @api.model
    def _get_preset_dates(self, preset):
        today = fields.Date.context_today(self)
        yesterday = today - timedelta(days=1)
        if preset == 'this_week':
            start_of_week = today - timedelta(days=today.weekday())
            return start_of_week, (yesterday if yesterday >= start_of_week else today)
        elif preset == 'this_month':
            start_of_month = today.replace(day=1)
            return start_of_month, (yesterday if yesterday >= start_of_month else today)
        return False, False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            preset = vals.get('period_preset', 'this_month')
            if preset != 'custom':
                d_from, d_to = self._get_preset_dates(preset)
                if d_from and d_to:
                    vals['date_from'] = d_from
                    vals['date_to'] = d_to
        return super().create(vals_list)

    @api.onchange('period_preset')
    def _onchange_period_preset(self):
        if self.period_preset and self.period_preset != 'custom':
            d_from, d_to = self._get_preset_dates(self.period_preset)
            if d_from and d_to:
                self.date_from = d_from
                self.date_to = d_to

    def action_scan_and_initiate(self):
        """Execute bank-wide attendance & absence scan for HR using central settings."""
        self.ensure_one()
        user = self.env.user
        is_hr_admin = (
            user.has_group('discipline_management.group_discipline_admin') or
            user.has_group('discipline_management.group_discipline_pomd') or
            user.has_group('base.group_system') or
            self.env.su
        )
        if not is_hr_admin:
            raise UserError(_("Access Restricted: Attendance violation scans can only be performed by Human Resources / POMD."))

        # Re-enforce preset dates server-side if preset is active
        if self.period_preset and self.period_preset != 'custom':
            d_from, d_to = self._get_preset_dates(self.period_preset)
            if d_from and d_to:
                self.date_from = d_from
                self.date_to = d_to

        if not self.date_from or not self.date_to:
            raise UserError(_("Please specify both Scan Start Date and Scan End Date."))

        if self.date_from > self.date_to:
            raise UserError(_("Scan Start Date cannot be later than Scan End Date."))

        # 1. Scope: All active bank employees with active contracts in hr.version
        active_ids = self._get_active_contracted_employee_ids()
        all_active_employees = self.env['hr.employee'].sudo().browse(active_ids)
        if not all_active_employees:
            raise UserError(_("No active contracted employees found to evaluate."))

        # 2. Automatically execute scan reading thresholds dynamically from Settings
        cases = self.env['hr.attendance'].scan_and_initiate_attendance_cases(
            employee_ids=all_active_employees,
            date_from=self.date_from,
            date_to=self.date_to,
            violation_type='all',
            skip_existing_active_cases=self.skip_existing_active_cases,
            ignore_disabled_setting=True,
        )

        emp_count = len(all_active_employees)
        case_count = len(cases)

        if not cases:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Bank-Wide Attendance Evaluation Complete'),
                    'message': _(
                        'Evaluation completed across all %d active bank employee(s) for period %s to %s.\n'
                        'Zero unexcused absence or tardiness violations exceeding configured thresholds were found.'
                    ) % (emp_count, self.date_from, self.date_to),
                    'type': 'info',
                    'sticky': False,
                }
            }

        if case_count == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Initiated Attendance Case: %s') % cases.name,
                'res_model': 'discipline.attendance.case',
                'res_id': cases.id,
                'view_mode': 'form',
                'target': 'current',
            }

        return {
            'type': 'ir.actions.act_window',
            'name': _('Initiated Attendance Disciplinary Cases (%d Created)') % case_count,
            'res_model': 'discipline.attendance.case',
            'view_mode': 'list,form',
            'domain': [('id', 'in', cases.ids)],
        }
