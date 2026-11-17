# -*- coding: utf-8 -*-
import io
import base64
import calendar
from datetime import date, datetime, timedelta
import xlsxwriter

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class HrResignationReportWizard(models.TransientModel):
    _name = 'hr.resignation.report.wizard'
    _description = 'Resignation Report Wizard'

    def _default_year(self):
        return str(fields.Date.today().year)

    def _default_month(self):
        return str(fields.Date.today().month)

    def _default_date_from(self):
        today = fields.Date.today()
        return date(today.year, today.month, 1)

    def _default_date_to(self):
        today = fields.Date.today()
        days_in_month = calendar.monthrange(today.year, today.month)[1]
        return date(today.year, today.month, days_in_month)

    filter_type = fields.Selection([
        ('monthly', 'Monthly'),
        ('weekly', 'Weekly'),
        ('annually', 'Annually'),
        ('custom', 'Custom Range'),
    ], string='Period Filter', default='monthly', required=True)

    year = fields.Selection([
        (str(y), str(y)) for y in range(2020, 2036)
    ], string='Year', default=_default_year)

    month = fields.Selection([
        ('1', 'January'),
        ('2', 'February'),
        ('3', 'March'),
        ('4', 'April'),
        ('5', 'May'),
        ('6', 'June'),
        ('7', 'July'),
        ('8', 'August'),
        ('9', 'September'),
        ('10', 'October'),
        ('11', 'November'),
        ('12', 'December'),
    ], string='Month', default=_default_month)

    week_date = fields.Date(string='Reference Date for Week', default=fields.Date.today)

    date_filter_field = fields.Selection([
        ('release_date', 'Date of Separation'),
        ('application_date', 'Date of Request'),
    ], string='Filter Date By', default='release_date', required=True)

    date_from = fields.Date(string='Date From', default=_default_date_from, required=True)
    date_to = fields.Date(string='Date To', default=_default_date_to, required=True)

    department_ids = fields.Many2many('hr.department', string='Departments')
    operating_unit_ids = fields.Many2many('operating.unit', string='Operating Units / Branches')
    resignation_type_ids = fields.Many2many('hr.separation.type', string='Separation Types')

    state = fields.Selection([
        ('all', 'All States'),
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('release_date_set', 'Release Date Set'),
        ('handover_completed', 'Handover Completed'),
        ('clearance_in_progress', 'Clearance In Progress'),
        ('cleared', 'Cleared'),
        ('settled', 'Settled'),
        ('completed', 'Completed'),
        ('returned', 'Returned'),
        ('revoked', 'Revoked'),
    ], string='Status Filter', default='completed', required=True)

    @api.onchange('filter_type', 'year', 'month', 'week_date')
    def _onchange_period(self):
        if self.filter_type == 'monthly':
            try:
                y = int(self.year or fields.Date.today().year)
                m = int(self.month or fields.Date.today().month)
                days_in_month = calendar.monthrange(y, m)[1]
                self.date_from = date(y, m, 1)
                self.date_to = date(y, m, days_in_month)
            except Exception:
                pass
        elif self.filter_type == 'annually':
            try:
                y = int(self.year or fields.Date.today().year)
                self.date_from = date(y, 1, 1)
                self.date_to = date(y, 12, 31)
            except Exception:
                pass
        elif self.filter_type == 'weekly':
            ref = self.week_date or fields.Date.today()
            monday = ref - timedelta(days=ref.weekday())
            sunday = monday + timedelta(days=6)
            self.date_from = monday
            self.date_to = sunday

    @api.onchange('date_from', 'date_to')
    def _onchange_date_range(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            self.date_to = self.date_from

    def action_generate_excel(self):
        self.ensure_one()

        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise UserError(_("Date From cannot be later than Date To."))

        # Build Domain
        domain = []
        if self.date_from and self.date_to:
            if self.date_filter_field == 'release_date':
                domain.extend([
                    '|',
                    '&', ('release_date', '>=', self.date_from), ('release_date', '<=', self.date_to),
                    '&', ('expected_last_day', '>=', self.date_from), ('expected_last_day', '<=', self.date_to),
                ])
            else:
                domain.extend([
                    ('application_date', '>=', self.date_from),
                    ('application_date', '<=', self.date_to),
                ])
        elif self.date_from:
            col = 'release_date' if self.date_filter_field == 'release_date' else 'application_date'
            domain.append((col, '>=', self.date_from))
        elif self.date_to:
            col = 'release_date' if self.date_filter_field == 'release_date' else 'application_date'
            domain.append((col, '<=', self.date_to))

        if self.department_ids:
            domain.append(('department_id', 'in', self.department_ids.ids))

        if self.operating_unit_ids:
            domain.append(('operating_unit_id', 'in', self.operating_unit_ids.ids))

        if self.resignation_type_ids:
            domain.append(('resignation_type_id', 'in', self.resignation_type_ids.ids))

        if self.state and self.state != 'all':
            domain.append(('state', '=', self.state))

        records = self.env['hr.resignation'].sudo().search(domain, order='release_date asc, application_date asc, id asc')

        if not records:
            raise UserError(_("No resignation records found matching the specified filters."))

        # Generate Excel
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        # Sheet Name
        month_names = dict(self._fields['month'].selection)
        if self.filter_type == 'monthly':
            sheet_title = f"{month_names.get(self.month, 'Month')} {self.year}"
        elif self.filter_type == 'annually':
            sheet_title = f"Year {self.year}"
        elif self.filter_type == 'weekly':
            sheet_title = f"Week {self.date_from}"
        else:
            sheet_title = "Resignation Report"
        worksheet = workbook.add_worksheet(sheet_title[:31])

        # Header formatting matching August 2026.xlsx (Bunna Bank theme color: #843C0B with white text)
        header_format = workbook.add_format({
            'bold': True,
            'font_name': 'Barlow Medium',
            'font_size': 12,
            'font_color': '#FFFFFF',
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True,
            'border': 1,
            'border_color': '#595959',
            'bg_color': '#843C0B',
        })

        cell_center = workbook.add_format({
            'font_name': 'Barlow Medium',
            'font_size': 10,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#D9D9D9',
        })

        cell_left = workbook.add_format({
            'font_name': 'Barlow Medium',
            'font_size': 10,
            'align': 'left',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#D9D9D9',
        })

        date_format = workbook.add_format({
            'font_name': 'Barlow Medium',
            'font_size': 10,
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#D9D9D9',
            'num_format': 'yyyy-mm-dd',
        })

        currency_format = workbook.add_format({
            'font_name': 'Barlow Medium',
            'font_size': 10,
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
            'border_color': '#D9D9D9',
            'num_format': '_(* #,##0.00_);_(* (#,##0.00);_(* "-"??_);_(@_)',
        })

        # Columns
        headers = [
            'S.No',
            'Name of Employee',
            'ID NO',
            'Job Title',
            'Job Grade',
            'Employement Date',
            'Managerial Position Start Date',
            'Prior Notice',
            'Date of Request',
            'Date of\nSeparation',
            'Current\nSalary',
            'Resignation Type',
            'Reason for Resignation',
        ]
        col_widths = [7, 33, 10, 44, 13, 20, 22, 15, 20, 22, 18, 24, 26]

        worksheet.set_row(0, 45.6)
        for col_idx, (h, w) in enumerate(zip(headers, col_widths)):
            worksheet.write(0, col_idx, h, header_format)
            worksheet.set_column(col_idx, col_idx, w)

        # Write Data Rows
        for idx, rec in enumerate(records, start=1):
            row_idx = idx
            worksheet.set_row(row_idx, 22)

            emp = rec.employee_id
            emp_name = emp.name if emp else ''
            emp_id_no = emp.barcode or emp.identification_id or emp.employee_identification or ''
            job_title = rec.job_id.name or (emp and emp.job_title) or (rec.current_version_id and rec.current_version_id.job_title) or ''

            # Job Grade (Roman numerals like XII, IX, VII)
            job_grade = ''
            if emp:
                if emp.grade_id and emp.grade_id.grade_code:
                    job_grade = emp.grade_id.grade_code
                elif emp.job_grade and hasattr(emp.job_grade, 'grade_code') and emp.job_grade.grade_code:
                    job_grade = emp.job_grade.grade_code
            if not job_grade and rec.current_version_id and rec.current_version_id.job_grade:
                if hasattr(rec.current_version_id.job_grade, 'grade_code'):
                    job_grade = rec.current_version_id.job_grade.grade_code or ''

            # Employment Date
            emp_date = rec.joined_date or (emp and (emp.service_hire_date or emp.service_start_date)) or False

            # Managerial Position Start Date
            is_mgr = (rec.job_category == 'Managerial')
            mgr_date = rec.joined_date if is_mgr else False

            # Prior Notice
            prior_notice = 'Yes' if (rec.notice_period_accepted == 'yes' or rec.notice_period > 0) else 'No'
            if rec.notice_override_date or rec.notice_period_accepted == 'no':
                prior_notice = 'No'

            # Dates
            req_date = rec.application_date or (rec.create_date and rec.create_date.date()) or False
            sep_date = rec.release_date or rec.expected_last_day or False

            # Salary
            salary = rec.basic_salary or (rec.current_version_id and rec.current_version_id.wage) or (emp and emp.contract_id and emp.contract_id.wage) or 0.0

            # Type & Reason
            res_type = rec.resignation_type_id.name if rec.resignation_type_id else 'Resignation'
            reason = rec.reason or (rec.exit_interview_id and rec.exit_interview_id.primary_reason_id and rec.exit_interview_id.primary_reason_id.name) or ''

            worksheet.write(row_idx, 0, idx, cell_center)
            worksheet.write(row_idx, 1, emp_name, cell_left)
            worksheet.write(row_idx, 2, emp_id_no, cell_center)
            worksheet.write(row_idx, 3, job_title, cell_left)
            worksheet.write(row_idx, 4, job_grade, cell_center)

            if emp_date:
                worksheet.write(row_idx, 5, str(emp_date), date_format)
            else:
                worksheet.write(row_idx, 5, '', cell_center)

            if mgr_date:
                worksheet.write(row_idx, 6, str(mgr_date), date_format)
            else:
                worksheet.write(row_idx, 6, '', cell_center)

            worksheet.write(row_idx, 7, prior_notice, cell_center)

            if req_date:
                worksheet.write(row_idx, 8, str(req_date), date_format)
            else:
                worksheet.write(row_idx, 8, '', cell_center)

            if sep_date:
                worksheet.write(row_idx, 9, str(sep_date), date_format)
            else:
                worksheet.write(row_idx, 9, '', cell_center)

            worksheet.write(row_idx, 10, salary, currency_format)
            worksheet.write(row_idx, 11, res_type, cell_left)
            worksheet.write(row_idx, 12, reason, cell_left)

        workbook.close()
        output.seek(0)
        file_data = output.getvalue()

        # Filename
        if self.filter_type == 'monthly':
            filename = f"Resignation_Report_{month_names.get(self.month, 'Month')}_{self.year}.xlsx"
        elif self.filter_type == 'annually':
            filename = f"Resignation_Report_{self.year}.xlsx"
        elif self.filter_type == 'weekly':
            filename = f"Resignation_Report_Week_{self.date_from}_to_{self.date_to}.xlsx"
        else:
            filename = f"Resignation_Report_{self.date_from}_to_{self.date_to}.xlsx"

        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(file_data),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }
