# -*- coding: utf-8 -*-
import io
import base64
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class HrSickLeaveThresholdReportWizard(models.TransientModel):
    _name = 'hr.sick.leave.threshold.report.wizard'
    _description = 'Sick Leave Threshold (6 Months / 365 Days) Report Wizard'

    def _default_is_hr_or_admin(self):
        return bool(
            self.env.user.has_group('hr_holidays.group_hr_holidays_user')
            or self.env.user.has_group('hr_holidays.group_hr_holidays_manager')
        )

    threshold_days = fields.Float(
        string='Threshold Days (6 Mos)',
        default=180.0,
        required=True,
        help="Target number of sick leave days to detect within any 365-day period (e.g. 180 for 6 months, or 60 for testing)."
    )
    is_hr_or_admin = fields.Boolean(
        string='Is HR or Admin',
        default=_default_is_hr_or_admin
    )
    date_from = fields.Date(
        string='From Date (Optional)',
        help="Optional: Only consider leaves starting on or after this date. Leave empty to evaluate all history."
    )
    date_to = fields.Date(
        string='To Date (Optional)',
        help="Optional: Only consider leaves starting on or before this date. Leave empty for no upper limit."
    )
    state_selection = fields.Selection([
        ('approved', 'Approved Only (Validated)'),
        ('all_active', 'Approved & Submitted (Active Requests)'),
    ], string='Leave State Scope', default='approved', required=True)

    operating_unit_ids = fields.Many2many(
        'operating.unit',
        string='Operating Units',
        help="Filter by specific Operating Units, or leave blank for all (locked to your unit for Managers)."
    )
    department_ids = fields.Many2many(
        'hr.department',
        string='Departments',
        help="Filter by specific Departments, or leave blank for all (locked to your department for Managers)."
    )
    employee_ids = fields.Many2many(
        'hr.employee',
        string='Specific Employees',
        help="Leave blank to evaluate all accessible active employees (or restricted to your Subordinates if Manager)."
    )
    line_ids = fields.One2many(
        'hr.sick.leave.threshold.report.line',
        'wizard_id',
        string='Flagged Lines'
    )
    flagged_employee_count = fields.Integer(
        string='Flagged Employees',
        compute='_compute_totals'
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        is_hr_or_admin = bool(
            self.env.user.has_group('hr_holidays.group_hr_holidays_user')
            or self.env.user.has_group('hr_holidays.group_hr_holidays_manager')
        )
        res['is_hr_or_admin'] = is_hr_or_admin
        if not is_hr_or_admin:
            emp = self.env.user.employee_id
            ou = emp.default_operating_unit_id if emp else False
            if ou:
                res['operating_unit_ids'] = [(6, 0, [ou.id])]
            # Pre-set manager's department(s)
            dept_ids = []
            if emp:
                if emp.department_id:
                    dept_ids.append(emp.department_id.id)
                managed_depts = self.env['hr.department'].sudo().search([('manager_id', '=', emp.id)])
                dept_ids.extend(managed_depts.ids)
            if dept_ids:
                res['department_ids'] = [(6, 0, list(set(dept_ids)))]
            # Pre-set subordinate employees and lock
            subordinate_emps = self.env['hr.employee'].sudo().search(self._get_accessible_employee_domain())
            if subordinate_emps:
                res['employee_ids'] = [(6, 0, subordinate_emps.ids)]
        return res

    @api.depends('line_ids')
    def _compute_totals(self):
        for rec in self:
            rec.flagged_employee_count = len(rec.line_ids)

    def _get_sick_leave_types(self):
        """Finds all hr.leave.type records corresponding to Sick Leave."""
        LeaveType = self.env['hr.leave.type'].sudo()
        domain = [
            '|', '|', '|',
            ('name', '=ilike', '%sick%'),
            ('name', '=ilike', '%medical%'),
            ('name', '=ilike', '%ሕመም%'),
            ('name', '=ilike', '%ህመም%'),
        ]
        sick_types = LeaveType.search(domain)
        if 'hr.leave.reason.config' in self.env:
            configs = self.env['hr.leave.reason.config'].sudo().search([('leave_reason', '=', 'sick_leave')])
            if configs:
                config_types = configs.mapped('holiday_status_id')
                sick_types = sick_types | config_types
        return sick_types

    def _get_accessible_employee_domain(self):
        """Enforces role-based visibility:
        - Admin & HR: See all active employees.
        - Managers: Can ONLY see employees who report to them (subordinates).
        """
        is_hr_or_admin = bool(
            self.env.user.has_group('hr_holidays.group_hr_holidays_user')
            or self.env.user.has_group('hr_holidays.group_hr_holidays_manager')
        )
        base_domain = [('active', '=', True)]

        if not is_hr_or_admin:
            curr_emp = self.env.user.employee_id
            if not curr_emp:
                return [('id', '=', -1)]

            manager_domain = [
                '|', '|', '|', '|',
                ('parent_id', '=', curr_emp.id),
                ('coach_id', '=', curr_emp.id),
                ('leave_manager_id', '=', self.env.user.id),
                ('department_id.manager_id', '=', curr_emp.id),
                ('id', '=', curr_emp.id),
            ]
            base_domain += manager_domain

        return base_domain

    def _get_report_data(self):
        self.ensure_one()
        sick_types = self._get_sick_leave_types()
        if not sick_types:
            raise UserError(_("No 'Sick Leave' type was found in the system. Please verify Leave Types configuration."))

        emp_domain = self._get_accessible_employee_domain()
        if self.operating_unit_ids:
            emp_domain.append(('default_operating_unit_id', 'in', self.operating_unit_ids.ids))
        if self.department_ids:
            emp_domain.append(('department_id', 'in', self.department_ids.ids))
        if self.employee_ids:
            emp_domain.append(('id', 'in', self.employee_ids.ids))

        employees = self.env['hr.employee'].sudo().search(emp_domain, order='name asc')
        if not employees:
            return []

        # Leave state domain
        if self.state_selection == 'approved':
            state_domain = [('state', 'in', ['validate', 'validate1'])]
        else:
            state_domain = [('state', 'not in', ['cancel', 'refuse'])]

        data = []
        threshold = self.threshold_days or 180.0

        for emp in employees:
            leave_domain = [
                ('employee_id', '=', emp.id),
                ('holiday_status_id', 'in', sick_types.ids),
            ] + state_domain

            if self.date_to:
                leave_domain.append(('date_from', '<=', fields.Datetime.to_datetime(self.date_to) + timedelta(days=1)))
            if self.date_from:
                leave_domain.append(('date_from', '>=', fields.Datetime.to_datetime(self.date_from)))

            leaves = self.env['hr.leave'].sudo().search(leave_domain, order='date_from asc')
            if not leaves:
                continue

            # SHORTCUT: If total days requested by this employee is less than threshold, skip immediately!
            total_employee_sick_days = sum(lv.number_of_days for lv in leaves)
            if total_employee_sick_days < threshold:
                continue

            # Parse individual leave requests
            intervals = []
            for lv in leaves:
                s_dt = lv.date_from
                e_dt = lv.date_to
                if not s_dt or not e_dt:
                    continue
                s_d = s_dt.date()
                e_d = e_dt.date()
                days = lv.number_of_days if lv.number_of_days > 0 else float((e_d - s_d).days + 1)
                
                ref = (
                    getattr(lv, 'leave_reference', None)
                    or getattr(lv, 'name', None)
                    or f"LR-{lv.id:06d}"
                )
                intervals.append({
                    'id': lv.id,
                    'ref': str(ref).strip(),
                    'start': s_d,
                    'end': e_d,
                    'days': days,
                    'leave_type_name': lv.holiday_status_id.name or 'Sick Leave',
                })

            if not intervals:
                continue

            # Consecutive 365-day anchor loop
            for anchor in intervals:
                w_start = anchor['start']
                w_end = w_start + timedelta(days=364)

                window_sum = 0.0
                qualifying_leaves = []

                for it in intervals:
                    inter_start = max(it['start'], w_start)
                    inter_end = min(it['end'], w_end)
                    if inter_start <= inter_end:
                        total_span = (it['end'] - it['start']).days + 1
                        overlap_span = (inter_end - inter_start).days + 1
                        if total_span > 0:
                            ratio = float(overlap_span) / float(total_span)
                            eff_days = it['days'] * ratio
                            window_sum += eff_days
                            qualifying_leaves.append({
                                'ref': it['ref'],
                                'start': it['start'],
                                'end': it['end'],
                                'days': it['days'],
                                'eff_days': eff_days,
                                'type': it['leave_type_name'],
                            })

                if window_sum >= threshold:
                    emp_code = (
                        emp.identification_id
                        or getattr(emp, 'employee_identification', '')
                        or emp.barcode
                        or f"EMP-{emp.id:04d}"
                    )
                    ou = emp.default_operating_unit_id
                    ou_name = ou.name if ou else 'Unassigned'
                    sol_id = str(ou.sol_id) if (ou and hasattr(ou, 'sol_id') and ou.sol_id) else 'N/A'

                    distinct_types = list(set(q['type'] for q in qualifying_leaves))
                    types_str = ", ".join(distinct_types)

                    refs_list_str = ", ".join(q['ref'] for q in qualifying_leaves)

                    breakdown_items = []
                    for q in qualifying_leaves:
                        breakdown_items.append(
                            f"{q['ref']} [{q['start']} to {q['end']} : {q['days']:.1f} days]"
                        )
                    details_str = " | ".join(breakdown_items)

                    remark = _("Exceeded: %.1f sick days requested within 365 consecutive days (%s to %s). Requests: %s") % (
                        window_sum,
                        w_start.strftime('%Y-%m-%d'),
                        w_end.strftime('%Y-%m-%d'),
                        refs_list_str,
                    )

                    data.append({
                        'employee_id': emp.id,
                        'employee_code': str(emp_code).strip(),
                        'employee_name': emp.name or '',
                        'sol_id': sol_id,
                        'operating_unit_id': ou.id if ou else False,
                        'operating_unit_name': ou_name,
                        'leave_type_name': types_str,
                        'leave_references': refs_list_str,
                        'leave_details': details_str,
                        'total_days_requested': round(window_sum, 2),
                        'window_start_date': w_start,
                        'window_end_date': w_end,
                        'remark': remark,
                    })
                    break  # Flagged, continue to next employee

        return data

    def _populate_lines(self):
        self.ensure_one()
        self.line_ids.unlink()
        data = self._get_report_data()
        line_vals = [dict(d, wizard_id=self.id) for d in data]
        if line_vals:
            self.env['hr.sick.leave.threshold.report.line'].create(line_vals)

    def action_view_list(self):
        """Generates lines and displays them in interactive List view."""
        self.ensure_one()
        self._populate_lines()
        return {
            'name': _('Sick Leave >= %.0f Days Threshold') % (self.threshold_days or 180.0),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.sick.leave.threshold.report.line',
            'view_mode': 'list',
            'domain': [('wizard_id', '=', self.id)],
            'context': {},
            'target': 'current',
        }

    def action_export_excel(self):
        """Generates Excel (.xlsx) file and triggers download."""
        self.ensure_one()
        if not xlsxwriter:
            raise UserError(_("The Python module 'xlsxwriter' is required for Excel export."))

        data = self._get_report_data()
        if not data:
            raise UserError(_("No employees met or exceeded the %.1f-day sick leave threshold within a 365-day period.") % (self.threshold_days or 180.0))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Sick Leave >= 6 Months')

        # Formats
        title_fmt = workbook.add_format({
            'bold': True, 'font_size': 14, 'font_color': '#541718', 'align': 'left', 'valign': 'vcenter'
        })
        subtitle_fmt = workbook.add_format({
            'bold': True, 'font_size': 11, 'font_color': '#333333', 'align': 'left', 'valign': 'vcenter'
        })
        meta_fmt = workbook.add_format({
            'font_size': 9, 'font_color': '#666666', 'italic': True
        })
        header_fmt = workbook.add_format({
            'bold': True, 'font_size': 10, 'font_color': '#FFFFFF', 'bg_color': '#541718',
            'align': 'center', 'valign': 'vcenter', 'border': 1, 'border_color': '#3b1011'
        })
        cell_fmt = workbook.add_format({
            'font_size': 10, 'align': 'left', 'valign': 'vcenter', 'border': 1, 'border_color': '#E0E0E0'
        })
        cell_center_fmt = workbook.add_format({
            'font_size': 10, 'align': 'center', 'valign': 'vcenter', 'border': 1, 'border_color': '#E0E0E0'
        })
        cell_num_fmt = workbook.add_format({
            'font_size': 10, 'align': 'right', 'valign': 'vcenter', 'num_format': '#,##0.00',
            'border': 1, 'border_color': '#E0E0E0', 'bold': True, 'font_color': '#B71C1C'
        })
        remark_fmt = workbook.add_format({
            'font_size': 9, 'align': 'left', 'valign': 'vcenter', 'border': 1, 'border_color': '#E0E0E0', 'text_wrap': True
        })

        # Title Block
        worksheet.write(0, 0, "BUNNA BANK S.C.", title_fmt)
        worksheet.write(1, 0, "SICK LEAVE THRESHOLD REPORT (>= 6 MONTHS IN 365 CONSECUTIVE DAYS)", subtitle_fmt)
        run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        date_scope = f"Scope: All Historical Leaves" if not self.date_to and not self.date_from else f"Date Filter: {self.date_from or 'Start'} to {self.date_to or 'Latest'}"
        worksheet.write(2, 0, f"Threshold: {self.threshold_days} Days    |    {date_scope}    |    Generated on: {run_ts}", meta_fmt)

        headers = [
            ("No.", 6),
            ("Employee ID", 15),
            ("Employee Name", 26),
            ("SOL ID", 12),
            ("Operating Unit", 22),
            ("Leave Type", 18),
            ("Leave Reference(s)", 22),
            ("Breakdown of Requests [Ref: Dates : Days]", 50),
            ("Total Days", 14),
            ("365-Day Window Period", 25),
            ("Remark", 40),
        ]

        row = 4
        for col_idx, (header_text, width) in enumerate(headers):
            worksheet.write(row, col_idx, header_text, header_fmt)
            worksheet.set_column(col_idx, col_idx, width)

        worksheet.freeze_panes(row + 1, 0)

        # Rows
        row += 1
        for idx, item in enumerate(data, start=1):
            w_period = f"{item['window_start_date']} to {item['window_end_date']}" if item.get('window_start_date') else "N/A"
            worksheet.write(row, 0, idx, cell_center_fmt)
            worksheet.write(row, 1, item['employee_code'], cell_center_fmt)
            worksheet.write(row, 2, item['employee_name'], cell_fmt)
            worksheet.write(row, 3, item['sol_id'], cell_center_fmt)
            worksheet.write(row, 4, item['operating_unit_name'], cell_fmt)
            worksheet.write(row, 5, item['leave_type_name'], cell_fmt)
            worksheet.write(row, 6, item['leave_references'], cell_center_fmt)
            worksheet.write(row, 7, item['leave_details'], remark_fmt)
            worksheet.write(row, 8, item['total_days_requested'], cell_num_fmt)
            worksheet.write(row, 9, w_period, cell_center_fmt)
            worksheet.write(row, 10, item['remark'], remark_fmt)
            row += 1

        worksheet.autofilter(4, 0, row - 1, len(headers) - 1)
        workbook.close()
        output.seek(0)

        filename = f"Sick_Leave_Threshold_Report.xlsx"
        attachment = self.env['ir.attachment'].sudo().create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(output.getvalue()),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def action_print_pdf(self):
        """Generates QWeb PDF report."""
        self.ensure_one()
        self._populate_lines()
        if not self.line_ids:
            raise UserError(_("No employees met or exceeded the %.1f-day sick leave threshold within a 365-day period.") % (self.threshold_days or 180.0))
        return self.env.ref(
            'hr_leave_request_custom.action_report_sick_leave_threshold_pdf'
        ).report_action(self)


class HrSickLeaveThresholdReportLine(models.TransientModel):
    _name = 'hr.sick.leave.threshold.report.line'
    _description = 'Sick Leave Threshold Report Line'
    _order = 'operating_unit_name, employee_name'

    wizard_id = fields.Many2one(
        'hr.sick.leave.threshold.report.wizard',
        string='Wizard',
        ondelete='cascade',
        index=True
    )
    employee_id = fields.Many2one('hr.employee', string='Employee', readonly=True)
    employee_code = fields.Char(string='Employee ID', readonly=True)
    employee_name = fields.Char(string='Employee Name', readonly=True)
    sol_id = fields.Char(string='SOL ID', readonly=True)
    operating_unit_id = fields.Many2one('operating.unit', string='Operating Unit', readonly=True)
    operating_unit_name = fields.Char(string='Operating Unit', readonly=True)
    leave_type_name = fields.Char(string='Leave Type', readonly=True)
    leave_references = fields.Char(string='Leave Reference(s)', readonly=True)
    leave_details = fields.Text(string='Leave Breakdown', readonly=True)
    total_days_requested = fields.Float(string='Total Days Requested', digits=(16, 2), readonly=True)
    window_start_date = fields.Date(string='Window Start', readonly=True)
    window_end_date = fields.Date(string='Window End', readonly=True)
    remark = fields.Char(string='Remark', readonly=True)
