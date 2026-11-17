# -*- coding: utf-8 -*-
import io
import base64
from datetime import datetime, date
from odoo import models, fields, api, _
from odoo.exceptions import UserError

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class HrLeaveBalanceReportWizard(models.TransientModel):
    _name = 'hr.leave.balance.report.wizard'
    _description = 'Employee Leave Balance Report Wizard'

    def _default_is_hr_or_admin(self):
        return bool(
            self.env.user.has_group('hr_holidays.group_hr_holidays_user')
            or self.env.user.has_group('hr_holidays.group_hr_holidays_manager')
        )

    as_of_date = fields.Date(
        string='As of Date',
        default=fields.Date.context_today,
        required=True,
        help="Calculate leave balances as of this date."
    )
    is_hr_or_admin = fields.Boolean(
        string='Is HR or Admin',
        default=_default_is_hr_or_admin
    )
    operating_unit_ids = fields.Many2many(
        'operating.unit',
        string='Operating Units',
        help="Leave blank to include all Operating Units (or restricted to your Operating Unit if Manager)."
    )
    department_ids = fields.Many2many(
        'hr.department',
        string='Departments',
        help="Leave blank to include all Departments (or restricted to your Department if Manager)."
    )
    employee_ids = fields.Many2many(
        'hr.employee',
        string='Specific Employees',
        help="Leave blank to include all accessible active employees (or restricted to your Subordinates if Manager)."
    )
    line_ids = fields.One2many(
        'hr.leave.balance.report.line',
        'wizard_id',
        string='Report Lines'
    )
    employee_count = fields.Integer(
        string='Total Employees',
        compute='_compute_totals'
    )
    total_accrued = fields.Float(
        string='Total Accrued',
        digits=(16, 2),
        compute='_compute_totals'
    )
    total_scheduled = fields.Float(
        string='Total Scheduled',
        digits=(16, 2),
        compute='_compute_totals'
    )

    def _get_accessible_employee_domain(self):
        """Enforces role-based visibility:
        - Admin & HR: See all active employees across the entire bank.
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
                return [('id', '=', -1)]  # No employee record, no access

            # Subordinates only: employees where current user/employee is manager
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

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        is_hr_or_admin = bool(
            self.env.user.has_group('hr_holidays.group_hr_holidays_user')
            or self.env.user.has_group('hr_holidays.group_hr_holidays_manager')
        )
        res['is_hr_or_admin'] = is_hr_or_admin
        # If manager (not HR/Admin), pre-set and lock their Operating Unit, Department, and Subordinate Employees
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
            rec.employee_count = len(rec.line_ids)
            rec.total_accrued = sum(line.accrued_balance for line in rec.line_ids)
            rec.total_scheduled = sum(line.scheduled_balance for line in rec.line_ids)

    def _get_report_data(self):
        self.ensure_one()
        domain = self._get_accessible_employee_domain()
        if self.operating_unit_ids:
            domain.append(('default_operating_unit_id', 'in', self.operating_unit_ids.ids))
        if self.department_ids:
            domain.append(('department_id', 'in', self.department_ids.ids))
        if self.employee_ids:
            domain.append(('id', 'in', self.employee_ids.ids))

        employees = self.env['hr.employee'].sudo().search(domain, order='name asc')
        LeaveModel = self.env['hr.leave'].sudo()

        data = []
        for emp in employees:
            balances = LeaveModel._get_leave_balances(emp, as_of_date=self.as_of_date)
            emp_code = (
                emp.identification_id
                or getattr(emp, 'employee_identification', '')
                or emp.barcode
                or f"EMP-{emp.id:04d}"
            )
            ou_name = emp.default_operating_unit_id.name if emp.default_operating_unit_id else 'Unassigned'
            mgr_name = emp.parent_id.name if emp.parent_id else 'None'

            data.append({
                'employee_id': emp.id,
                'employee_code': str(emp_code).strip(),
                'employee_name': emp.name or '',
                'operating_unit_id': emp.default_operating_unit_id.id if emp.default_operating_unit_id else False,
                'operating_unit_name': ou_name,
                'manager_id': emp.parent_id.id if emp.parent_id else False,
                'manager_name': mgr_name,
                'accrued_balance': float(balances.get('accrued', 0.0)),
                'scheduled_balance': float(balances.get('scheduled', 0.0)),
                'as_of_date': self.as_of_date,
            })
        return data

    def _populate_lines(self):
        self.ensure_one()
        self.line_ids.unlink()
        data = self._get_report_data()
        line_vals = [dict(d, wizard_id=self.id) for d in data]
        if line_vals:
            self.env['hr.leave.balance.report.line'].create(line_vals)

    def action_view_list(self):
        """Generates the lines and displays them in an interactive List/Tree view."""
        self.ensure_one()
        self._populate_lines()
        return {
            'name': _('Employee Leave Balances (As of %s)') % self.as_of_date,
            'type': 'ir.actions.act_window',
            'res_model': 'hr.leave.balance.report.line',
            'view_mode': 'list',
            'domain': [('wizard_id', '=', self.id)],
            'context': {},
            'target': 'current',
        }

    def action_export_excel(self):
        """Generates a styled Excel (.xlsx) file and triggers browser download."""
        self.ensure_one()
        if not xlsxwriter:
            raise UserError(_("The Python module 'xlsxwriter' is required for Excel export."))

        data = self._get_report_data()
        if not data:
            raise UserError(_("No active employees found matching the selected criteria."))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Leave Balances')

        # Formats
        title_fmt = workbook.add_format({
            'bold': True,
            'font_size': 14,
            'font_color': '#541718',
            'align': 'left',
            'valign': 'vcenter',
        })
        subtitle_fmt = workbook.add_format({
            'bold': True,
            'font_size': 11,
            'font_color': '#333333',
            'align': 'left',
            'valign': 'vcenter',
        })
        meta_fmt = workbook.add_format({
            'font_size': 9,
            'font_color': '#666666',
            'italic': True,
        })
        header_fmt = workbook.add_format({
            'bold': True,
            'font_size': 10,
            'font_color': '#FFFFFF',
            'bg_color': '#541718',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#3b1011',
        })
        cell_fmt = workbook.add_format({
            'font_size': 10,
            'align': 'left',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#E0E0E0',
        })
        cell_center_fmt = workbook.add_format({
            'font_size': 10,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#E0E0E0',
        })
        cell_num_fmt = workbook.add_format({
            'font_size': 10,
            'align': 'right',
            'valign': 'vcenter',
            'num_format': '#,##0.00',
            'border': 1,
            'border_color': '#E0E0E0',
        })
        total_label_fmt = workbook.add_format({
            'bold': True,
            'font_size': 10,
            'font_color': '#541718',
            'bg_color': '#F8F9FA',
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#BDBDBD',
        })
        total_num_fmt = workbook.add_format({
            'bold': True,
            'font_size': 10,
            'font_color': '#541718',
            'bg_color': '#F8F9FA',
            'align': 'right',
            'valign': 'vcenter',
            'num_format': '#,##0.00',
            'border': 1,
            'border_color': '#BDBDBD',
        })

        # Title Block
        worksheet.write(0, 0, "BUNNA BANK S.C.", title_fmt)
        worksheet.write(1, 0, "EMPLOYEE LEAVE BALANCE REPORT", subtitle_fmt)
        run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        worksheet.write(2, 0, f"As of Date: {self.as_of_date}    |    Generated on: {run_ts}", meta_fmt)

        ou_filter = ", ".join(self.operating_unit_ids.mapped('name')) if self.operating_unit_ids else "All Operating Units"
        worksheet.write(3, 0, f"Scope: {ou_filter}", meta_fmt)

        # Header Row
        headers = [
            ("No.", 6),
            ("Employee ID", 15),
            ("Employee Name", 30),
            ("Operating Unit", 25),
            ("Manager", 25),
            ("Accrued Balance", 18),
            ("Scheduled Balance", 18),
            ("As of Date", 14),
        ]

        row = 5
        for col_idx, (header_text, width) in enumerate(headers):
            worksheet.write(row, col_idx, header_text, header_fmt)
            worksheet.set_column(col_idx, col_idx, width)

        # Data Rows
        row += 1
        start_data_row = row
        total_accrued = 0.0
        total_scheduled = 0.0

        for idx, item in enumerate(data, start=1):
            worksheet.write(row, 0, idx, cell_center_fmt)
            worksheet.write(row, 1, item['employee_code'], cell_center_fmt)
            worksheet.write(row, 2, item['employee_name'], cell_fmt)
            worksheet.write(row, 3, item['operating_unit_name'], cell_fmt)
            worksheet.write(row, 4, item['manager_name'], cell_fmt)
            worksheet.write(row, 5, item['accrued_balance'], cell_num_fmt)
            worksheet.write(row, 6, item['scheduled_balance'], cell_num_fmt)
            worksheet.write(row, 7, str(item['as_of_date']), cell_center_fmt)

            total_accrued += item['accrued_balance']
            total_scheduled += item['scheduled_balance']
            row += 1

        # Summary Row
        worksheet.write(row, 0, "", total_label_fmt)
        worksheet.write(row, 1, "", total_label_fmt)
        worksheet.write(row, 2, "", total_label_fmt)
        worksheet.write(row, 3, "", total_label_fmt)
        worksheet.write(row, 4, f"Total ({len(data)} Employees):", total_label_fmt)
        worksheet.write(row, 5, total_accrued, total_num_fmt)
        worksheet.write(row, 6, total_scheduled, total_num_fmt)
        worksheet.write(row, 7, "", total_label_fmt)

        worksheet.freeze_panes(6, 0)
        worksheet.autofilter(5, 0, row - 1, len(headers) - 1)
        workbook.close()
        output.seek(0)

        filename = f"Leave_Balances_AsOf_{self.as_of_date}.xlsx"
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
        """Generates the QWeb PDF printable report."""
        self.ensure_one()
        self._populate_lines()
        return self.env.ref(
            'hr_leave_request_custom.action_report_leave_balance_pdf'
        ).report_action(self)


class HrLeaveBalanceReportLine(models.TransientModel):
    _name = 'hr.leave.balance.report.line'
    _description = 'Employee Leave Balance Report Line'
    _order = 'operating_unit_name, employee_name'

    wizard_id = fields.Many2one(
        'hr.leave.balance.report.wizard',
        string='Wizard',
        ondelete='cascade',
        index=True
    )
    employee_id = fields.Many2one('hr.employee', string='Employee', readonly=True)
    employee_code = fields.Char(string='Employee ID', readonly=True)
    employee_name = fields.Char(string='Employee Name', readonly=True)
    operating_unit_id = fields.Many2one('operating.unit', string='Operating Unit', readonly=True)
    operating_unit_name = fields.Char(string='Operating Unit', readonly=True)
    manager_id = fields.Many2one('hr.employee', string='Manager', readonly=True)
    manager_name = fields.Char(string='Manager', readonly=True)
    accrued_balance = fields.Float(string='Accrued Balance', digits=(16, 2), readonly=True)
    scheduled_balance = fields.Float(string='Scheduled Balance', digits=(16, 2), readonly=True)
    as_of_date = fields.Date(string='As of Date', readonly=True)
