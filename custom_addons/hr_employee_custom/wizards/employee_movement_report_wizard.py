# -*- coding: utf-8 -*-
import base64
import io
import os
from datetime import date, datetime
from dateutil.relativedelta import relativedelta

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.drawing.image import Image as OpenpyxlImage
from openpyxl.drawing.spreadsheet_drawing import OneCellAnchor, AnchorMarker
from openpyxl.drawing.xdr import XDRPositiveSize2D
from openpyxl.utils import get_column_letter
from openpyxl.utils.units import pixels_to_EMU

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class HrEmployeeMovementReportWizard(models.TransientModel):
    _name = 'hr.employee.movement.report.wizard'
    _description = 'Employee Movement & Recruitment Report Wizard'

    report_type = fields.Selection([
        # Movement & Staffing Reports
        ('promotion', 'Employee Promotion Report'),
        ('demotion', 'Employee Demotion Report'),
        ('acting_assignment', 'Employee Acting Assignment Report'),
        ('assignment', 'Employee Assignment Report'),
        ('transfer', 'Employee Transfer Report'),
        ('external_recruitment', 'Employee External Recruitment Report'),
        ('separation', 'Employee Separation / Exit Report'),
        # Analytical HR Excel Reports
        ('profile', 'Employee Profile Report'),
        ('headcount', 'Headcount Report (Summary by Dept & Branch)'),
        ('headcount_dept', 'Headcount by Department'),
        ('headcount_branch', 'Headcount by Branch (Operating Unit)'),
        ('headcount_grade', 'Headcount by Grade'),
        ('headcount_position', 'Headcount by Position'),
        ('demographic', 'Employee Demographic Report'),
        ('gender', 'Gender Profile Report'),
        ('age_profile', 'Age Profile Report'),
        ('length_of_service', 'Length of Service (Tenure) Report'),
        ('work_permit_expiry', 'Work Permit Expiry Report'),
        ('document', 'Employee Document Report'),
        ('status', 'Employee Status Report'),
    ], string='Report Type', default='promotion', required=True)

    date_from = fields.Date(
        string='Date From',
        default=lambda self: date.today().replace(day=1)
    )
    date_to = fields.Date(
        string='Date To',
        default=fields.Date.context_today
    )

    department_id = fields.Many2one(
        'hr.department',
        string='Directorate / Department',
        help='Optional: Filter by specific directorate or department'
    )
    operating_unit_id = fields.Many2one(
        'operating.unit',
        string='Place of Assignment / Branch',
        help='Optional: Filter by specific operating unit or branch'
    )
    job_id = fields.Many2one(
        'hr.job',
        string='Job Position',
        help='Optional: Filter by specific job position'
    )
    grade_id = fields.Many2one(
        'employee.grade',
        string='Job Grade',
        help='Optional: Filter by specific job grade'
    )
    gender = fields.Selection([
        ('all', 'All Genders'),
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
    ], string='Gender', default='all')
    work_permit_status = fields.Selection([
        ('all', 'All Statuses'),
        ('none', 'Not Applicable'),
        ('valid', 'Valid'),
        ('expiring_soon', 'Expiring Soon'),
        ('expired', 'Expired'),
    ], string='Work Permit Status', default='all')

    prepared_by = fields.Char(
        string='Prepared By',
        default=lambda self: self.env.user.name or ''
    )

    excel_file = fields.Binary(string='Excel File', readonly=True)
    file_name = fields.Char(string='File Name', readonly=True)

    def _get_bunna_logo_path(self):
        """Returns path to the official Bunna Bank header logo matching user template."""
        custom_logo = os.path.abspath(os.path.join(
            os.path.dirname(__file__), '..', 'static', 'src', 'img', 'bunna_report_header_logo.png'
        ))
        if os.path.exists(custom_logo):
            return custom_logo
        fallback = os.path.abspath(os.path.join(
            os.path.dirname(__file__), '..', '..', 'competency_management', 'static', 'src', 'img', 'bunna_bank_official_logo.png'
        ))
        return fallback if os.path.exists(fallback) else False

    def _apply_header_banner(self, ws, main_title, sub_title, max_col):
        """Builds centered header banner matching Bunna Bank report template."""
        # Adjust height of top rows reserved for centered logo
        ws.row_dimensions[1].height = 20
        ws.row_dimensions[2].height = 20
        ws.row_dimensions[3].height = 25
        ws.row_dimensions[4].height = 15

        # 1. Main Title (Row 5)
        ws.row_dimensions[5].height = 24
        ws.merge_cells(start_row=5, start_column=1, end_row=5, end_column=max_col)
        cell_m = ws.cell(5, 1, main_title)
        cell_m.font = Font(name='Arial', size=14, bold=True, color='000000')
        cell_m.alignment = Alignment(horizontal='center', vertical='center')

        # 2. Subtitle (Row 6)
        ws.row_dimensions[6].height = 20
        ws.merge_cells(start_row=6, start_column=1, end_row=6, end_column=max_col)
        cell_s = ws.cell(6, 1, sub_title)
        cell_s.font = Font(name='Arial', size=12, bold=True, color='000000')
        cell_s.alignment = Alignment(horizontal='center', vertical='center')

        # 3. Reporting Period (Row 7)
        period_str = f"Reporting Period: {self.date_from} To {self.date_to}"
        ws.row_dimensions[7].height = 18
        ws.merge_cells(start_row=7, start_column=1, end_row=7, end_column=max_col)
        cell_p = ws.cell(7, 1, period_str)
        cell_p.font = Font(name='Arial', size=11, bold=False, color='222222')
        cell_p.alignment = Alignment(horizontal='center', vertical='center')

        # 4. Generated Date & Metadata (Row 8)
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        meta_parts = [f"Generated on: {now_str}"]
        if self.prepared_by:
            meta_parts.append(f"Prepared By: {self.prepared_by}")
        if self.department_id:
            meta_parts.append(f"Directorate / Dept: {self.department_id.name}")
        if self.operating_unit_id:
            meta_parts.append(f"Branch / OU: {self.operating_unit_id.name}")

        ws.row_dimensions[8].height = 18
        ws.merge_cells(start_row=8, start_column=1, end_row=8, end_column=max_col)
        cell_g = ws.cell(8, 1, " | ".join(meta_parts))
        cell_g.font = Font(name='Arial', size=10, italic=True, color='444444')
        cell_g.alignment = Alignment(horizontal='center', vertical='center')

        # Row 9 is blank spacing before table headers
        ws.row_dimensions[9].height = 10

    def _add_centered_logo(self, ws, max_col, img_width=180, img_height=70):
        """
        Positions Bunna logo centered horizontally across columns 1 to max_col,
        perfectly aligned with the centered header titles.
        """
        logo_path = self._get_bunna_logo_path()
        if not logo_path or not os.path.exists(logo_path):
            return

        col_widths_px = []
        for c in range(1, max_col + 1):
            letter = get_column_letter(c)
            dim = ws.column_dimensions.get(letter)
            w = dim.width if (dim and dim.width) else 13
            col_px = int(w * 7.5 + 5)
            col_widths_px.append(col_px)

        total_px = sum(col_widths_px)
        center_px = total_px / 2.0
        logo_left_px = max(0, center_px - (img_width / 2.0))

        cum_px = 0
        anchor_col = 0
        anchor_col_off = 0
        for idx, c_px in enumerate(col_widths_px):
            if cum_px + c_px > logo_left_px:
                anchor_col = idx
                anchor_col_off = int(logo_left_px - cum_px)
                break
            cum_px += c_px

        try:
            marker = AnchorMarker(
                col=anchor_col,
                colOff=pixels_to_EMU(anchor_col_off),
                row=0,
                rowOff=pixels_to_EMU(6)
            )
            size = XDRPositiveSize2D(pixels_to_EMU(img_width), pixels_to_EMU(img_height))
            img = OpenpyxlImage(logo_path)
            img.anchor = OneCellAnchor(_from=marker, ext=size)
            ws.add_image(img)
        except Exception:
            try:
                img = OpenpyxlImage(logo_path)
                img.width = img_width
                img.height = img_height
                center_letter = get_column_letter(max(1, (max_col + 1) // 2))
                ws.add_image(img, f"{center_letter}1")
            except Exception:
                pass

    def _get_table_styles(self):
        """Returns standard fonts, borders, and fills matching Bunna Bank theme."""
        # Bunna Coffee Maroon header fill (#6A1A24)
        header_fill = PatternFill(start_color='6A1A24', end_color='6A1A24', fill_type='solid')
        header_font = Font(name='Arial', size=10, bold=True, color='FFFFFF')
        data_font = Font(name='Arial', size=10, color='000000')

        thin_side = Side(border_style='thin', color='D3D3D3')
        data_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

        header_border_side = Side(border_style='thin', color='FFFFFF')
        header_border = Border(left=header_border_side, right=header_border_side, top=header_border_side, bottom=header_border_side)

        align_center = Alignment(horizontal='center', vertical='center', wrap_text=True)
        align_left = Alignment(horizontal='left', vertical='center', wrap_text=True)
        align_right = Alignment(horizontal='right', vertical='center')

        return {
            'header_fill': header_fill,
            'header_font': header_font,
            'data_font': data_font,
            'data_border': data_border,
            'header_border': header_border,
            'align_center': align_center,
            'align_left': align_left,
            'align_right': align_right,
        }

    def _auto_fit_columns(self, ws, max_col=None, min_row=10):
        """Auto fits column widths with comfortable padding and adds centered logo."""
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                if cell.row >= min_row and cell.value:
                    val_str = str(cell.value)
                    max_len = max(max_len, len(val_str))
            ws.column_dimensions[col_letter].width = max(max_len + 4, 13)

        if max_col:
            self._add_centered_logo(ws, max_col)

    # ──────────────────────────────────────────────────────────────────────────
    # 1. PROMOTION REPORT
    # ──────────────────────────────────────────────────────────────────────────
    def _generate_promotion_report(self, wb):
        ws = wb.active
        ws.title = "Promotion Report"

        columns = [
            'No.', 'Employee ID', 'Employee Full Name', 'Gender', 'Category',
            'Current Job Title', 'Current Grade', 'Current salary',
            'Current Directorate / Department', 'Current Place of Assignment',
            'New Job Title', 'New Grade', 'New Salary',
            'New Directorate / Department', 'New Place of Assignment',
            'Promotion Effective Date', 'Promotion Reason'
        ]
        self._apply_header_banner(ws, "EMPLOYEE PROMOTION REPORT", "Detail Employee Promotion Report", len(columns))
        styles = self._get_table_styles()

        # Header Row (Row 10)
        ws.row_dimensions[10].height = 28
        for col_idx, col_name in enumerate(columns, 1):
            c = ws.cell(10, col_idx, col_name)
            c.fill = styles['header_fill']
            c.font = styles['header_font']
            c.alignment = styles['align_center']
            c.border = styles['header_border']

        # Query Promotion records
        domain = [
            '|', ('reason_for_movement', '=', 'promotion'), ('reason_for_change', '=', 'promotion'),
            ('job_history_start_date', '>=', self.date_from),
            ('job_history_start_date', '<=', self.date_to),
        ]
        if self.department_id:
            domain.append('|')
            domain.append(('to_department_id', '=', self.department_id.id))
            domain.append(('from_department_id', '=', self.department_id.id))
        if self.operating_unit_id:
            domain.append('|')
            domain.append(('to_operating_unit_id', '=', self.operating_unit_id.id))
            domain.append(('from_operating_unit_id', '=', self.operating_unit_id.id))

        records = self.env['hr.job.history'].search(domain, order='job_history_start_date desc, id desc')
        
        row_idx = 11
        for num, r in enumerate(records, 1):
            emp = r.employee_id
            emp_id_code = emp.identification_id or ''
            gender = dict(emp._fields['gender'].selection).get(emp.gender, '') if emp.gender else ''
            
            # Category: Managerial vs Non Managerial
            cat = (
                (r.to_job_id and getattr(r.to_job_id, 'employee_category', False))
                or (emp.job_position and getattr(emp.job_position, 'employee_category', False))
                or ''
            )
            cur_job = r.from_job_id.name if r.from_job_id else ''
            cur_grade = r.from_grade_id.grade_code or r.from_grade_id.grade_name if r.from_grade_id else ''
            cur_salary = r.old_wage or 0.0
            cur_dept = r.from_department_id.name if r.from_department_id else ''
            cur_ou = r.from_operating_unit_id.name if r.from_operating_unit_id else ''

            new_job = r.to_job_id.name if r.to_job_id else (r.position or '')
            new_grade = r.to_grade_id.grade_code or r.to_grade_id.grade_name if r.to_grade_id else ''
            new_salary = r.new_wage or 0.0
            new_dept = r.to_department_id.name if r.to_department_id else ''
            new_ou = r.to_operating_unit_id.name if r.to_operating_unit_id else ''
            eff_date = str(r.job_history_start_date or '')
            reason_txt = dict(r._fields['reason_for_movement'].selection).get(r.reason_for_movement, '') if r.reason_for_movement else 'Promotion'

            row_data = [
                num, emp_id_code, emp.name or '', gender, cat,
                cur_job, cur_grade, cur_salary, cur_dept, cur_ou,
                new_job, new_grade, new_salary, new_dept, new_ou,
                eff_date, reason_txt
            ]

            ws.row_dimensions[row_idx].height = 20
            for col_i, val in enumerate(row_data, 1):
                cell = ws.cell(row_idx, col_i, val)
                cell.font = styles['data_font']
                cell.border = styles['data_border']
                if col_i in (1, 2, 4, 16):
                    cell.alignment = styles['align_center']
                elif col_i in (8, 13):
                    cell.alignment = styles['align_right']
                    cell.number_format = '#,##0.00'
                else:
                    cell.alignment = styles['align_left']
            row_idx += 1

        self._auto_fit_columns(ws, max_col=len(columns), min_row=10)

    # ──────────────────────────────────────────────────────────────────────────
    # 2. DEMOTION REPORT
    # ──────────────────────────────────────────────────────────────────────────
    def _generate_demotion_report(self, wb):
        ws = wb.active
        ws.title = "Demotion Report"

        columns = [
            'No.', 'Employee ID', 'Employee Full Name', 'Gender', 'Category',
            'Current Job Title', 'Current Job Grade', 'Current Directorate / Department', 'Current Place of Assignment',
            'Demoted Job Title', 'Demoted Job Grade', 'Demoted Directorate / Department', 'Demoted Place of Assignment',
            'Effective Date', 'Reason for Demotion', 'Status'
        ]
        self._apply_header_banner(ws, "EMPLOYEE DEMOTION REPORT", "Detail Employee Demotion Report", len(columns))
        styles = self._get_table_styles()

        ws.row_dimensions[10].height = 28
        for col_idx, col_name in enumerate(columns, 1):
            c = ws.cell(10, col_idx, col_name)
            c.fill = styles['header_fill']
            c.font = styles['header_font']
            c.alignment = styles['align_center']
            c.border = styles['header_border']

        domain = []
        if self.date_from:
            domain.append(('change_date', '>=', self.date_from))
        if self.date_to:
            domain.append(('change_date', '<=', self.date_to))
        if self.department_id:
            domain.append('|')
            domain.append(('employee_name.department_id', '=', self.department_id.id))
            domain.append(('new_job_title.department_id', '=', self.department_id.id))
        if self.operating_unit_id:
            domain.append('|')
            domain.append(('current_work_unit_id', '=', self.operating_unit_id.id))
            domain.append(('new_work_unit', '=', self.operating_unit_id.id))

        demotions = self.env['employee.demotion'].search(domain, order='create_date desc, id desc') if 'employee.demotion' in self.env else []

        row_idx = 11
        for num, d in enumerate(demotions, 1):
            emp = d.employee_name
            emp_id_code = (emp.identification_id or '') if emp else ''
            emp_name = emp.name if emp else ''
            gender = dict(emp._fields['gender'].selection).get(emp.gender, '') if emp and emp.gender else ''
            cat = getattr(d.new_job_title, 'employee_category', '') if d.new_job_title else ''

            cur_job = d.current_job_position_id.name if d.current_job_position_id else (d.job_position or (emp.job_position.name if emp and emp.job_position else ''))
            cur_grade = d.job_grade or (d.current_job_grade_id.grade_code or d.current_job_grade_id.grade_name if d.current_job_grade_id else '')
            cur_dept = emp.department_id.name if emp and emp.department_id else ''
            cur_ou = d.current_work_unit_id.name if d.current_work_unit_id else (d.current_work_unit or (emp.default_operating_unit_id.name if emp and emp.default_operating_unit_id else ''))

            new_job = d.new_job_title.name if d.new_job_title else ''
            new_grade = d.new_job_grade.grade_code or d.new_job_grade.grade_name if d.new_job_grade else ''
            new_dept = d.new_job_title.department_id.name if d.new_job_title and d.new_job_title.department_id else ''
            new_ou = d.new_work_unit.name if d.new_work_unit else ''
            eff_date = str(d.change_date or (d.create_date.date() if d.create_date else ''))
            reason_txt = dict(d._fields['reason'].selection).get(d.reason, d.reason) if hasattr(d, 'reason') and d.reason else ''
            status_txt = dict(d._fields['state'].selection).get(d.state, d.state) if hasattr(d, 'state') and d.state else 'Approved'

            row_data = [
                num, emp_id_code, emp_name, gender, cat,
                cur_job, cur_grade, cur_dept, cur_ou,
                new_job, new_grade, new_dept, new_ou,
                eff_date, reason_txt, status_txt
            ]

            ws.row_dimensions[row_idx].height = 20
            for col_i, val in enumerate(row_data, 1):
                cell = ws.cell(row_idx, col_i, val)
                cell.font = styles['data_font']
                cell.border = styles['data_border']
                if col_i in (1, 2, 4, 14, 16):
                    cell.alignment = styles['align_center']
                else:
                    cell.alignment = styles['align_left']
            row_idx += 1

        # Also include any demotions from hr.job.history
        domain_jh = [('reason_for_movement', '=', 'demotion')]
        if self.date_from:
            domain_jh.append(('job_history_start_date', '>=', self.date_from))
        if self.date_to:
            domain_jh.append(('job_history_start_date', '<=', self.date_to))
        if self.department_id:
            domain_jh.append('|')
            domain_jh.append(('to_department_id', '=', self.department_id.id))
            domain_jh.append(('from_department_id', '=', self.department_id.id))
        if self.operating_unit_id:
            domain_jh.append('|')
            domain_jh.append(('to_operating_unit_id', '=', self.operating_unit_id.id))
            domain_jh.append(('from_operating_unit_id', '=', self.operating_unit_id.id))

        jh_demotions = self.env['hr.job.history'].search(domain_jh, order='job_history_start_date desc, id desc')
        seen_emp_dates = {(d.employee_name.id if d.employee_name else 0, str(d.change_date or '')) for d in demotions}

        for r in jh_demotions:
            emp = r.employee_id
            start_d = str(r.job_history_start_date or '')
            if (emp.id if emp else 0, start_d) in seen_emp_dates:
                continue

            emp_id_code = (emp.identification_id or '') if emp else ''
            emp_name = emp.name if emp else ''
            gender = dict(emp._fields['gender'].selection).get(emp.gender, '') if emp and emp.gender else ''
            cat = getattr(r.to_job_id or (emp.job_position if emp else False), 'employee_category', '')

            cur_job = r.from_job_id.name if r.from_job_id else ''
            cur_grade = r.from_grade_id.grade_code or r.from_grade_id.grade_name if r.from_grade_id else ''
            cur_dept = r.from_department_id.name if r.from_department_id else ''
            cur_ou = r.from_operating_unit_id.name if r.from_operating_unit_id else ''

            new_job = r.to_job_id.name if r.to_job_id else ''
            new_grade = r.to_grade_id.grade_code or r.to_grade_id.grade_name if r.to_grade_id else ''
            new_dept = r.to_department_id.name if r.to_department_id else ''
            new_ou = r.to_operating_unit_id.name if r.to_operating_unit_id else ''
            eff_date = start_d
            reason_txt = r.reason_for_change or 'Demotion'
            status_txt = 'Approved'

            row_data = [
                row_idx - 10, emp_id_code, emp_name, gender, cat,
                cur_job, cur_grade, cur_dept, cur_ou,
                new_job, new_grade, new_dept, new_ou,
                eff_date, reason_txt, status_txt
            ]

            ws.row_dimensions[row_idx].height = 20
            for col_i, val in enumerate(row_data, 1):
                cell = ws.cell(row_idx, col_i, val)
                cell.font = styles['data_font']
                cell.border = styles['data_border']
                if col_i in (1, 2, 4, 14, 16):
                    cell.alignment = styles['align_center']
                else:
                    cell.alignment = styles['align_left']
            row_idx += 1

        self._auto_fit_columns(ws, max_col=len(columns), min_row=10)

    # ──────────────────────────────────────────────────────────────────────────
    # 3. ACTING ASSIGNMENT REPORT
    # ──────────────────────────────────────────────────────────────────────────
    def _generate_acting_report(self, wb):
        ws = wb.active
        ws.title = "Acting Assignment Report"

        columns = [
            'No.', 'Employee ID', 'Employee Full Name', 'Gender', 'Category',
            'Current Job Title', 'Original Place of Assignment', 'Origina Dept.',
            'Acting Place of Assignment', 'Acting Dep,t', 'Acting Job Title', 'Acting  Grade',
            'Start Date', 'End Date', 'Reason for Assignment'
        ]
        self._apply_header_banner(ws, "EMPLOYEE ACTING ASSIGNMENT REPORT", "Detail Employee Acting Assignment Report", len(columns))
        styles = self._get_table_styles()

        ws.row_dimensions[10].height = 28
        for col_idx, col_name in enumerate(columns, 1):
            c = ws.cell(10, col_idx, col_name)
            c.fill = styles['header_fill']
            c.font = styles['header_font']
            c.alignment = styles['align_center']
            c.border = styles['header_border']

        # 1. Query acting assignment records from hr.job.history
        domain_jh = [
            ('reason_for_movement', '=', 'acting_assignment'),
        ]
        if self.date_from:
            domain_jh.append(('job_history_start_date', '>=', self.date_from))
        if self.date_to:
            domain_jh.append(('job_history_start_date', '<=', self.date_to))
        if self.department_id:
            domain_jh.append('|')
            domain_jh.append(('to_department_id', '=', self.department_id.id))
            domain_jh.append(('from_department_id', '=', self.department_id.id))
        if self.operating_unit_id:
            domain_jh.append('|')
            domain_jh.append(('to_operating_unit_id', '=', self.operating_unit_id.id))
            domain_jh.append(('from_operating_unit_id', '=', self.operating_unit_id.id))

        jh_recs = self.env['hr.job.history'].search(domain_jh, order='job_history_start_date desc, id desc')

        # 2. Query supplementary.role if present
        domain_supp = []
        if self.date_from:
            domain_supp.append(('start_date', '>=', self.date_from))
        if self.date_to:
            domain_supp.append(('start_date', '<=', self.date_to))
        if self.operating_unit_id:
            domain_supp.append('|')
            domain_supp.append(('requesting_operating_unit', '=', self.operating_unit_id.id))
            domain_supp.append(('current_work_unit', '=', self.operating_unit_id.id))

        supp_recs = self.env['supplementary.role'].search(domain_supp, order='start_date desc, id desc') if 'supplementary.role' in self.env else []

        row_idx = 11
        seen_keys = set()

        # Render supplementary.role records first
        for r in supp_recs:
            emp = False
            if hasattr(r, 'acting_employee') and r.acting_employee:
                emp = r.acting_employee
            elif hasattr(r, 'employee_name') and r.employee_name:
                emp = r.employee_name
            elif hasattr(r, 'employee_id') and r.employee_id:
                if isinstance(r.employee_id, models.Model):
                    emp = r.employee_id
                else:
                    emp = self.env['hr.employee'].search([
                        '|', ('identification_id', '=', str(r.employee_id)),
                             ('id', '=', int(r.employee_id) if str(r.employee_id).isdigit() else 0)
                    ], limit=1)

            # Employee ID strictly means employee identification from hr_employee table
            emp_id_code = (emp.identification_id or '') if (emp and hasattr(emp, 'identification_id')) else (str(r.employee_id or '') if hasattr(r, 'employee_id') and r.employee_id else '')
            emp_name = emp.name if emp else ''
            gender = dict(emp._fields['gender'].selection).get(emp.gender, '') if (emp and hasattr(emp, 'gender') and emp.gender) else ''

            acting_job = r.acting_job_position or getattr(r, 'acting_position', False)
            cat = getattr(acting_job or (emp.job_position if emp else False), 'employee_category', '')
            orig_job = r.current_job_position.name if r.current_job_position else (emp.job_position.name if emp and emp.job_position else '')
            orig_ou = r.current_work_unit.name if r.current_work_unit else (emp.default_operating_unit_id.name if emp and emp.default_operating_unit_id else '')
            orig_dept = emp.department_id.name if emp and emp.department_id else ''

            act_ou = r.requesting_operating_unit.name if r.requesting_operating_unit else (r.acting_work_unit or '')
            act_dept = acting_job.department_id.name if acting_job and hasattr(acting_job, 'department_id') and acting_job.department_id else ''
            act_job = acting_job.name if acting_job else ''
            act_grade_txt = (r.job_grade1.grade_name or r.job_grade1.grade_code) if hasattr(r, 'job_grade1') and r.job_grade1 else ''

            start_d = str(r.start_date or '')
            end_d = str(r.end_date or '')
            reason_txt = r.acting_reason or 'Acting Assignment'

            seen_keys.add((emp.id if emp else emp_id_code, start_d))

            row_data = [
                row_idx - 10, emp_id_code, emp_name, gender, cat,
                orig_job, orig_ou, orig_dept,
                act_ou, act_dept, act_job, act_grade_txt,
                start_d, end_d, reason_txt
            ]

            ws.row_dimensions[row_idx].height = 20
            for col_i, val in enumerate(row_data, 1):
                cell = ws.cell(row_idx, col_i, val)
                cell.font = styles['data_font']
                cell.border = styles['data_border']
                if col_i in (1, 2, 4, 13, 14):
                    cell.alignment = styles['align_center']
                else:
                    cell.alignment = styles['align_left']
            row_idx += 1

        # Render hr.job.history acting assignment records
        for r in jh_recs:
            emp = r.employee_id
            start_d = str(r.job_history_start_date or '')
            emp_key = (emp.id if emp else False, start_d)
            if emp_key in seen_keys:
                continue

            emp_id_code = (emp.identification_id or '') if (emp and hasattr(emp, 'identification_id')) else ''
            emp_name = emp.name if emp else ''
            gender = dict(emp._fields['gender'].selection).get(emp.gender, '') if (emp and hasattr(emp, 'gender') and emp.gender) else ''

            acting_job = r.to_job_id or r.job_id
            orig_job = r.from_job_id
            cat = getattr(acting_job or (emp.job_position if emp else False), 'employee_category', '')
            orig_job_title = orig_job.name if orig_job else (emp.job_position.name if emp and emp.job_position else '')
            orig_ou = r.from_operating_unit_id.name if r.from_operating_unit_id else (emp.default_operating_unit_id.name if emp and emp.default_operating_unit_id else '')
            orig_dept = r.from_department_id.name if r.from_department_id else (emp.department_id.name if emp and emp.department_id else '')

            act_ou = r.to_operating_unit_id.name if r.to_operating_unit_id else (r.operating_unit_id.name if r.operating_unit_id else '')
            act_dept = r.to_department_id.name if r.to_department_id else (r.department_id.name if r.department_id else '')
            act_job = acting_job.name if acting_job else ''
            act_grade_txt = (r.to_grade_id.grade_code or r.to_grade_id.grade_name) if r.to_grade_id else ((r.grade_id.grade_code or r.grade_id.grade_name) if r.grade_id else '')
            end_d = str(r.job_history_end_date or '')
            reason_txt = r.reason_for_change or 'Acting Assignment'

            row_data = [
                row_idx - 10, emp_id_code, emp_name, gender, cat,
                orig_job_title, orig_ou, orig_dept,
                act_ou, act_dept, act_job, act_grade_txt,
                start_d, end_d, reason_txt
            ]

            ws.row_dimensions[row_idx].height = 20
            for col_i, val in enumerate(row_data, 1):
                cell = ws.cell(row_idx, col_i, val)
                cell.font = styles['data_font']
                cell.border = styles['data_border']
                if col_i in (1, 2, 4, 13, 14):
                    cell.alignment = styles['align_center']
                else:
                    cell.alignment = styles['align_left']
            row_idx += 1

        self._auto_fit_columns(ws, max_col=len(columns), min_row=10)

    # 4. ASSIGNMENT REPORT
    # ──────────────────────────────────────────────────────────────────────────
    def _generate_assignment_report(self, wb):
        ws = wb.active
        ws.title = "Assignment Report"

        columns = [
            'No.', 'Employee ID', 'Employee Full Name', 'Gender', 'Current Job Title',
            'Job Grade', 'Current Directorate / Department', 'Current Place of Assignment',
            'Assigned Job Title / Role', 'Assigned Directorate / Department', 'Assigned Place of Assignment',
            'Start Date', 'End Date'
        ]
        self._apply_header_banner(ws, "EMPLOYEE ASSIGNMENT REPORT", "Detail Employee Assignment Report", len(columns))
        styles = self._get_table_styles()

        ws.row_dimensions[10].height = 28
        for col_idx, col_name in enumerate(columns, 1):
            c = ws.cell(10, col_idx, col_name)
            c.fill = styles['header_fill']
            c.font = styles['header_font']
            c.alignment = styles['align_center']
            c.border = styles['header_border']

        domain = [
            ('reason_for_movement', '=', 'assignment'),
            ('job_history_start_date', '>=', self.date_from),
            ('job_history_start_date', '<=', self.date_to),
        ]
        if self.department_id:
            domain.append('|')
            domain.append(('to_department_id', '=', self.department_id.id))
            domain.append(('from_department_id', '=', self.department_id.id))
        if self.operating_unit_id:
            domain.append('|')
            domain.append(('to_operating_unit_id', '=', self.operating_unit_id.id))
            domain.append(('from_operating_unit_id', '=', self.operating_unit_id.id))

        recs = self.env['hr.job.history'].search(domain, order='job_history_start_date desc, id desc')

        row_idx = 11
        for num, r in enumerate(recs, 1):
            emp = r.employee_id
            emp_id_code = emp.identification_id or '' if emp else ''
            emp_name = emp.name if emp else ''
            gender = dict(emp._fields['gender'].selection).get(emp.gender, '') if emp and emp.gender else ''

            cur_job = r.from_job_id.name if r.from_job_id else ''
            grade_txt = r.from_grade_id.grade_code or r.from_grade_id.grade_name if r.from_grade_id else ''
            cur_dept = r.from_department_id.name if r.from_department_id else ''
            cur_ou = r.from_operating_unit_id.name if r.from_operating_unit_id else ''

            new_job = r.to_job_id.name if r.to_job_id else (r.position or '')
            new_dept = r.to_department_id.name if r.to_department_id else ''
            new_ou = r.to_operating_unit_id.name if r.to_operating_unit_id else ''
            start_d = str(r.job_history_start_date or '')
            end_d = str(r.job_history_end_date or '')

            row_data = [
                num, emp_id_code, emp_name, gender, cur_job,
                grade_txt, cur_dept, cur_ou,
                new_job, new_dept, new_ou,
                start_d, end_d
            ]

            ws.row_dimensions[row_idx].height = 20
            for col_i, val in enumerate(row_data, 1):
                cell = ws.cell(row_idx, col_i, val)
                cell.font = styles['data_font']
                cell.border = styles['data_border']
                if col_i in (1, 2, 4, 12, 13):
                    cell.alignment = styles['align_center']
                else:
                    cell.alignment = styles['align_left']
            row_idx += 1

        self._auto_fit_columns(ws, max_col=len(columns), min_row=10)

    # ──────────────────────────────────────────────────────────────────────────
    # 5. TRANSFER REPORT (with Summary Sheet)
    # ──────────────────────────────────────────────────────────────────────────
    def _generate_transfer_report(self, wb):
        ws = wb.active
        ws.title = "Transfer Report"

        columns = [
            'No.', 'Employee ID', 'Employee Full Name', 'Gender', 'Category',
            'Current Job Title', 'Current  Job Grade', 'Current Directorate / Department', 'Current Place of Assignment',
            'New Job Title', 'New Grade', 'New Directorate / Department', 'New Place of Assignment',
            'Transfer Effective Date', 'Transfer intiated by ', 'Transfer Reason'
        ]
        self._apply_header_banner(ws, "EMPLOYEE TRANSFER REPORT", "Detail Employee Transfer Report", len(columns))
        styles = self._get_table_styles()

        ws.row_dimensions[10].height = 28
        for col_idx, col_name in enumerate(columns, 1):
            c = ws.cell(10, col_idx, col_name)
            c.fill = styles['header_fill']
            c.font = styles['header_font']
            c.alignment = styles['align_center']
            c.border = styles['header_border']

        domain = [
            ('start_date', '>=', self.date_from),
            ('start_date', '<=', self.date_to),
        ]
        if self.department_id:
            domain.append('|')
            domain.append(('to_department_id', '=', self.department_id.id))
            domain.append(('from_department_id', '=', self.department_id.id))
        if self.operating_unit_id:
            domain.append('|')
            domain.append(('to_operating_unit_id', '=', self.operating_unit_id.id))
            domain.append(('from_operating_unit_id', '=', self.operating_unit_id.id))

        transfers = self.env['hr.employee.transfer.history'].search(domain, order='start_date desc, id desc') if 'hr.employee.transfer.history' in self.env else []

        female_count = 0
        male_count = 0
        bank_init_count = 0
        emp_init_count = 0

        row_idx = 11
        for num, t in enumerate(transfers, 1):
            emp = t.employee_id
            emp_id_code = emp.identification_id or '' if emp else ''
            emp_name = emp.name if emp else ''
            gender = dict(emp._fields['gender'].selection).get(emp.gender, '') if emp and emp.gender else ''
            if gender.lower().startswith('f'):
                female_count += 1
            elif gender.lower().startswith('m'):
                male_count += 1

            cat = (
                (t.to_job_id and getattr(t.to_job_id, 'employee_category', False))
                or (emp.job_position and getattr(emp.job_position, 'employee_category', False))
                or ''
            )
            cur_job = t.from_job_id.name if t.from_job_id else ''
            cur_grade = t.from_grade_id.grade_code or t.from_grade_id.grade_name if t.from_grade_id else ''
            cur_dept = t.from_department_id.name if t.from_department_id else ''
            cur_ou = t.from_operating_unit_id.name if t.from_operating_unit_id else ''

            new_job = t.to_job_id.name if t.to_job_id else ''
            new_grade = t.to_grade_id.grade_code or t.to_grade_id.grade_name if t.to_grade_id else ''
            new_dept = t.to_department_id.name if t.to_department_id else ''
            new_ou = t.to_operating_unit_id.name if t.to_operating_unit_id else ''
            eff_date = str(t.start_date or t.date or '')

            init_type = getattr(t, 'transfer_initiation_type', False)
            if init_type == 'self_initiated':
                init_txt = 'Employee-initiated'
                emp_init_count += 1
            else:
                init_txt = 'Bank-initiated'
                bank_init_count += 1

            reason_txt = getattr(t, 'transfer_reason', False) or getattr(t, 'reason_for_movement', 'Transfer')

            row_data = [
                num, emp_id_code, emp_name, gender, cat,
                cur_job, cur_grade, cur_dept, cur_ou,
                new_job, new_grade, new_dept, new_ou,
                eff_date, init_txt, reason_txt
            ]

            ws.row_dimensions[row_idx].height = 20
            for col_i, val in enumerate(row_data, 1):
                cell = ws.cell(row_idx, col_i, val)
                cell.font = styles['data_font']
                cell.border = styles['data_border']
                if col_i in (1, 2, 4, 14, 15):
                    cell.alignment = styles['align_center']
                else:
                    cell.alignment = styles['align_left']
            row_idx += 1

        self._auto_fit_columns(ws, max_col=len(columns), min_row=10)

        # ── Sheet 2: Summary Sheet ──────────────────────────────────────────
        ws_sum = wb.create_sheet(title="Summary")
        self._apply_header_banner(ws_sum, "BUNNA BANK S.C.", "TRANSFER SUMMARY", 4)

        # Transfer requests metrics from employee.transfer.request if available
        req_domain = [
            ('request_date', '>=', self.date_from),
            ('request_date', '<=', self.date_to),
        ]
        TransferReq = self.env.get('employee.transfer.request')
        if TransferReq:
            total_reqs = TransferReq.search_count(req_domain)
            approved_reqs = TransferReq.search_count(req_domain + [('state', 'in', ['approved', 'transferred'])])
            pending_reqs = TransferReq.search_count(req_domain + [('state', 'in', ['submitted', 'under_review'])])
            rejected_reqs = TransferReq.search_count(req_domain + [('state', 'in', ['rejected', 'refused'])])
        else:
            total_reqs = len(transfers)
            approved_reqs = len(transfers)
            pending_reqs = 0
            rejected_reqs = 0

        sum_columns = ['Indicator', 'Value']
        ws_sum.row_dimensions[10].height = 25
        for col_i, col_name in enumerate(sum_columns, 2):
            c = ws_sum.cell(10, col_i, col_name)
            c.fill = styles['header_fill']
            c.font = styles['header_font']
            c.alignment = styles['align_center']
            c.border = styles['header_border']

        summary_rows = [
            ('Total transfer requests', total_reqs),
            ('Approved transfers', approved_reqs),
            ('Pending approval', pending_reqs),
            ('Rejected transfers', rejected_reqs),
            ('Bank-initiated transfers', bank_init_count),
            ('Employee-initiated transfers', emp_init_count),
            ('Female employees transferred', female_count),
            ('Male employees transferred', male_count),
        ]

        for s_idx, (k, v) in enumerate(summary_rows, 11):
            ws_sum.row_dimensions[s_idx].height = 22
            c_k = ws_sum.cell(s_idx, 2, k)
            c_k.font = styles['data_font']
            c_k.border = styles['data_border']
            c_k.alignment = styles['align_left']

            c_v = ws_sum.cell(s_idx, 3, v)
            c_v.font = Font(name='Arial', size=10, bold=True, color='000000')
            c_v.border = styles['data_border']
            c_v.alignment = styles['align_right']
            c_v.number_format = '#,##0'

        ws_sum.column_dimensions['A'].width = 8
        ws_sum.column_dimensions['B'].width = 35
        ws_sum.column_dimensions['C'].width = 18
        self._add_centered_logo(ws_sum, max_col=3)

    # ──────────────────────────────────────────────────────────────────────────
    # 6. EXTERNAL RECRUITMENT REPORT
    # ──────────────────────────────────────────────────────────────────────────
    def _generate_recruitment_report(self, wb):
        ws = wb.active
        ws.title = "Recruitment Report"

        columns = [
            'No.', 'Employee ID', 'Employee Full Name', 'Gender', 'Category',
            'Job Title', 'Job Grade', 'Salary', 'Hire Date',
            'Directorate/Department', 'Place of Assignment',
            'Recruitment Type', 'Recruitment Reason'
        ]
        self._apply_header_banner(ws, "EMPLOYEE RECRUITMENT REPORT", "Detail Employee External Recruitment Report", len(columns))
        styles = self._get_table_styles()

        ws.row_dimensions[10].height = 28
        for col_idx, col_name in enumerate(columns, 1):
            c = ws.cell(10, col_idx, col_name)
            c.fill = styles['header_fill']
            c.font = styles['header_font']
            c.alignment = styles['align_center']
            c.border = styles['header_border']

        domain = []
        if self.date_from:
            domain.append(('service_hire_date', '>=', self.date_from))
        if self.date_to:
            domain.append(('service_hire_date', '<=', self.date_to))
        if self.department_id:
            domain.append(('department_id', '=', self.department_id.id))
        if self.operating_unit_id:
            domain.append(('default_operating_unit_id', '=', self.operating_unit_id.id))

        employees = self.env['hr.employee'].search(domain, order='service_hire_date desc, id desc')

        row_idx = 11
        for num, emp in enumerate(employees, 1):
            emp_id_code = emp.identification_id or ''
            gender = dict(emp._fields['gender'].selection).get(emp.gender, '') if emp.gender else ''
            cat = getattr(emp.job_position, 'employee_category', '') if emp.job_position else ''
            job_title = emp.job_position.name if emp.job_position else (emp.job_id.name if emp.job_id else '')
            grade_txt = emp.job_grade.grade_code or emp.job_grade.grade_name if emp.job_grade else ''

            # Salary from active contract
            contract = emp.contract_id or self.env['hr.version'].search([('employee_id', '=', emp.id)], order='id desc', limit=1)
            salary = getattr(contract, 'wage', 0.0) or getattr(contract, 'base_salary', 0.0) if contract else 0.0

            hire_date = str(emp.service_hire_date or emp.first_contract_date or '')
            dept = emp.department_id.name if emp.department_id else ''
            ou = emp.default_operating_unit_id.name if emp.default_operating_unit_id else ''
            rec_type = 'External Recruitment'
            rec_reason = 'New Hire / Vacancy Placement'

            row_data = [
                num, emp_id_code, emp.name or '', gender, cat,
                job_title, grade_txt, salary, hire_date,
                dept, ou, rec_type, rec_reason
            ]

            ws.row_dimensions[row_idx].height = 20
            for col_i, val in enumerate(row_data, 1):
                cell = ws.cell(row_idx, col_i, val)
                cell.font = styles['data_font']
                cell.border = styles['data_border']
                if col_i in (1, 2, 4, 9):
                    cell.alignment = styles['align_center']
                elif col_i == 8:
                    cell.alignment = styles['align_right']
                    cell.number_format = '#,##0.00'
                else:
                    cell.alignment = styles['align_left']
            row_idx += 1

        self._auto_fit_columns(ws, max_col=len(columns), min_row=10)

    # ──────────────────────────────────────────────────────────────────────────
    # Main Export Action
    # ──────────────────────────────────────────────────────────────────────────
    def _get_common_employee_domain(self):
        """Constructs common domain for HR analytics & employee reports."""
        domain = []
        if self.department_id:
            domain.append(('department_id', '=', self.department_id.id))
        if self.operating_unit_id:
            domain.append(('default_operating_unit_id', '=', self.operating_unit_id.id))
        if self.job_id:
            domain.append(('job_position', '=', self.job_id.id))
        if self.grade_id:
            domain.append(('job_grade', '=', self.grade_id.id))
        if self.gender and self.gender != 'all':
            domain.append(('gender', '=', self.gender))
        if self.work_permit_status and self.work_permit_status != 'all':
            domain.append(('work_permit_status', '=', self.work_permit_status))
        return domain

    def _prepare_analytical_report_data(self, rtype):
        """Prepares structured (headers, rows, is_summary, sheet_title, sub_title) for analytical Excel reports."""
        domain = self._get_common_employee_domain()

        if rtype == 'profile':
            sheet_title = "Employee Profile"
            sub_title = "Employee Profile Detailed Report"
            headers = ['No.', 'Employee ID', 'Full Name', 'Gender', 'Date of Birth', 'Age', 'Marital Status',
                       'Department', 'Branch / Operating Unit', 'Job Position', 'Job Grade', 'Hire Date',
                       'Work Email', 'Phone', 'Education Field']
            employees = self.env['hr.employee'].search(domain, order='name asc')
            rows = []
            for idx, emp in enumerate(employees, 1):
                dob = str(emp.birthday) if emp.birthday else ''
                hire = str(emp.service_hire_date or emp.service_start_date or emp.start_date or '')
                rows.append([
                    idx,
                    emp.identification_id or '',
                    emp.name or '',
                    (emp.gender or '').capitalize(),
                    dob,
                    emp.age or '',
                    (emp.marital or '').capitalize(),
                    emp.department_id.name if emp.department_id else '',
                    emp.default_operating_unit_id.name if emp.default_operating_unit_id else '',
                    emp.job_position.name if emp.job_position else '',
                    emp.job_grade.grade_name if emp.job_grade else '',
                    hire,
                    emp.work_email or '',
                    emp.mobile_phone or emp.work_phone or '',
                    emp.study_field or '',
                ])
            return headers, rows, False, sheet_title, sub_title

        elif rtype == 'headcount':
            sheet_title = "Headcount Summary"
            sub_title = "Headcount Report (Summary by Department & Branch)"
            headers = ['No.', 'Department', 'Branch / Operating Unit', 'Total Headcount', 'Male Count', 'Female Count']
            employees = self.env['hr.employee'].search(domain)
            groups = {}
            for emp in employees:
                dept = emp.department_id.name if emp.department_id else 'Unassigned Dept'
                ou = emp.default_operating_unit_id.name if emp.default_operating_unit_id else 'Head Office / Other'
                key = (dept, ou)
                if key not in groups:
                    groups[key] = {'total': 0, 'male': 0, 'female': 0}
                groups[key]['total'] += 1
                if emp.gender == 'male':
                    groups[key]['male'] += 1
                elif emp.gender == 'female':
                    groups[key]['female'] += 1
            rows = []
            for idx, ((dept, ou), counts) in enumerate(sorted(groups.items()), 1):
                rows.append([idx, dept, ou, counts['total'], counts['male'], counts['female']])
            return headers, rows, True, sheet_title, sub_title

        elif rtype == 'headcount_dept':
            sheet_title = "Headcount by Dept"
            sub_title = "Headcount Distribution by Department"
            headers = ['No.', 'Department Name', 'Department Manager', 'Total Headcount', 'Male Count', 'Female Count', '% Share']
            employees = self.env['hr.employee'].search(domain)
            total_all = len(employees) or 1
            depts = {}
            for emp in employees:
                d = emp.department_id
                did = d.id if d else 0
                dname = d.name if d else 'Unassigned'
                mgr = d.manager_id.name if d and d.manager_id else ''
                if did not in depts:
                    depts[did] = {'name': dname, 'manager': mgr, 'total': 0, 'male': 0, 'female': 0}
                depts[did]['total'] += 1
                if emp.gender == 'male':
                    depts[did]['male'] += 1
                elif emp.gender == 'female':
                    depts[did]['female'] += 1
            rows = []
            for idx, (_, ddata) in enumerate(sorted(depts.items(), key=lambda x: x[1]['total'], reverse=True), 1):
                share = round((ddata['total'] / total_all) * 100, 1)
                rows.append([idx, ddata['name'], ddata['manager'], ddata['total'], ddata['male'], ddata['female'], f"{share}%"])
            return headers, rows, True, sheet_title, sub_title

        elif rtype == 'headcount_branch':
            sheet_title = "Headcount by Branch"
            sub_title = "Headcount Distribution by Operating Unit / Branch"
            headers = ['No.', 'Branch / Operating Unit', 'Total Staff', 'Male Staff', 'Female Staff', '% Share']
            employees = self.env['hr.employee'].search(domain)
            total_all = len(employees) or 1
            ous = {}
            for emp in employees:
                ou = emp.default_operating_unit_id
                ouid = ou.id if ou else 0
                ou_name = ou.name if ou else 'Head Office / Unassigned'
                if ouid not in ous:
                    ous[ouid] = {'name': ou_name, 'total': 0, 'male': 0, 'female': 0}
                ous[ouid]['total'] += 1
                if emp.gender == 'male':
                    ous[ouid]['male'] += 1
                elif emp.gender == 'female':
                    ous[ouid]['female'] += 1
            rows = []
            for idx, (_, odata) in enumerate(sorted(ous.items(), key=lambda x: x[1]['total'], reverse=True), 1):
                share = round((odata['total'] / total_all) * 100, 1)
                rows.append([idx, odata['name'], odata['total'], odata['male'], odata['female'], f"{share}%"])
            return headers, rows, True, sheet_title, sub_title

        elif rtype == 'headcount_grade':
            sheet_title = "Headcount by Grade"
            sub_title = "Staff Headcount by Job Grade"
            headers = ['No.', 'Job Grade', 'Grade Level', 'Total Employees', 'Male Staff', 'Female Staff', '% Share']
            employees = self.env['hr.employee'].search(domain)
            total_all = len(employees) or 1
            grades = {}
            for emp in employees:
                g = emp.job_grade
                gid = g.id if g else 0
                gname = g.grade_name if g else 'Ungraded / None'
                glevel = g.grade_level if g and hasattr(g, 'grade_level') else ''
                if gid not in grades:
                    grades[gid] = {'name': gname, 'level': glevel, 'total': 0, 'male': 0, 'female': 0}
                grades[gid]['total'] += 1
                if emp.gender == 'male':
                    grades[gid]['male'] += 1
                elif emp.gender == 'female':
                    grades[gid]['female'] += 1
            rows = []
            for idx, (_, gdata) in enumerate(sorted(grades.items(), key=lambda x: x[1]['total'], reverse=True), 1):
                share = round((gdata['total'] / total_all) * 100, 1)
                rows.append([idx, gdata['name'], gdata['level'], gdata['total'], gdata['male'], gdata['female'], f"{share}%"])
            return headers, rows, True, sheet_title, sub_title

        elif rtype == 'headcount_position':
            sheet_title = "Headcount by Position"
            sub_title = "Staff Headcount by Job Position"
            headers = ['No.', 'Job Position', 'Department', 'Total Count', 'Male Count', 'Female Count', '% Share']
            employees = self.env['hr.employee'].search(domain)
            total_all = len(employees) or 1
            positions = {}
            for emp in employees:
                p = emp.job_position
                pid = p.id if p else 0
                pname = p.name if p else 'Unassigned Position'
                dname = emp.department_id.name if emp.department_id else 'General'
                key = (pid, pname, dname)
                if key not in positions:
                    positions[key] = {'total': 0, 'male': 0, 'female': 0}
                positions[key]['total'] += 1
                if emp.gender == 'male':
                    positions[key]['male'] += 1
                elif emp.gender == 'female':
                    positions[key]['female'] += 1
            rows = []
            for idx, ((_, pname, dname), pdata) in enumerate(sorted(positions.items(), key=lambda x: x[1]['total'], reverse=True), 1):
                share = round((pdata['total'] / total_all) * 100, 1)
                rows.append([idx, pname, dname, pdata['total'], pdata['male'], pdata['female'], f"{share}%"])
            return headers, rows, True, sheet_title, sub_title

        elif rtype == 'demographic':
            sheet_title = "Demographic Report"
            sub_title = "Employee Demographic Profile Report"
            headers = ['No.', 'Employee ID', 'Full Name', 'Gender', 'Age', 'Marital Status', 'Religion', 'Blood Group',
                       'Department', 'Branch / Operating Unit', 'Region', 'City']
            employees = self.env['hr.employee'].search(domain, order='name asc')
            rows = []
            for idx, emp in enumerate(employees, 1):
                rows.append([
                    idx,
                    emp.identification_id or '',
                    emp.name or '',
                    (emp.gender or '').capitalize(),
                    emp.age or '',
                    (emp.marital or '').capitalize(),
                    emp.religion or '',
                    emp.blood_group or '',
                    emp.department_id.name if emp.department_id else '',
                    emp.default_operating_unit_id.name if emp.default_operating_unit_id else '',
                    emp.region or '',
                    emp.city or '',
                ])
            return headers, rows, False, sheet_title, sub_title

        elif rtype == 'gender':
            sheet_title = "Gender Profile"
            sub_title = "Gender Distribution & Diversity Report"
            headers = ['No.', 'Department', 'Branch / Operating Unit', 'Male Count', 'Female Count', 'Total', 'Female Ratio']
            employees = self.env['hr.employee'].search(domain)
            groups = {}
            for emp in employees:
                dname = emp.department_id.name if emp.department_id else 'Head Office / Other'
                ouname = emp.default_operating_unit_id.name if emp.default_operating_unit_id else 'Main Unit'
                key = (dname, ouname)
                if key not in groups:
                    groups[key] = {'male': 0, 'female': 0}
                if emp.gender == 'male':
                    groups[key]['male'] += 1
                elif emp.gender == 'female':
                    groups[key]['female'] += 1
            rows = []
            for idx, ((dname, ouname), c) in enumerate(sorted(groups.items()), 1):
                tot = c['male'] + c['female']
                ratio = f"{round((c['female'] / tot) * 100, 1)}%" if tot > 0 else "0%"
                rows.append([idx, dname, ouname, c['male'], c['female'], tot, ratio])
            return headers, rows, True, sheet_title, sub_title

        elif rtype == 'age_profile':
            sheet_title = "Age Profile"
            sub_title = "Employee Age Profile & Generation Distribution"
            headers = ['No.', 'Employee ID', 'Full Name', 'Gender', 'Birth Date', 'Age', 'Age Bracket',
                       'Department', 'Branch / Operating Unit', 'Job Position']
            employees = self.env['hr.employee'].search(domain, order='birthday asc')
            rows = []
            today = date.today()
            for idx, emp in enumerate(employees, 1):
                age = 0
                if emp.birthday:
                    age = today.year - emp.birthday.year - ((today.month, today.day) < (emp.birthday.month, emp.birthday.day))
                elif emp.age and str(emp.age).isdigit():
                    age = int(emp.age)

                if age < 25:
                    bracket = 'Under 25 Years'
                elif age <= 35:
                    bracket = '25 - 35 Years'
                elif age <= 45:
                    bracket = '36 - 45 Years'
                elif age <= 55:
                    bracket = '46 - 55 Years'
                else:
                    bracket = 'Above 55 Years'

                rows.append([
                    idx,
                    emp.identification_id or '',
                    emp.name or '',
                    (emp.gender or '').capitalize(),
                    str(emp.birthday or ''),
                    age if age > 0 else '',
                    bracket,
                    emp.department_id.name if emp.department_id else '',
                    emp.default_operating_unit_id.name if emp.default_operating_unit_id else '',
                    emp.job_position.name if emp.job_position else '',
                ])
            return headers, rows, False, sheet_title, sub_title

        elif rtype == 'length_of_service':
            sheet_title = "Length of Service"
            sub_title = "Employee Length of Service (Tenure) Report"
            headers = ['No.', 'Employee ID', 'Full Name', 'Hire / Start Date', 'Service Years', 'Service Months',
                       'Tenure Bracket', 'Department', 'Branch / Operating Unit', 'Job Grade']
            employees = self.env['hr.employee'].search(domain, order='name asc')
            rows = []
            today = date.today()
            for idx, emp in enumerate(employees, 1):
                hire_d = emp.service_hire_date or emp.service_start_date or emp.start_date
                years = 0.0
                months = 0
                if hire_d:
                    diff_days = (today - hire_d).days
                    years = round(diff_days / 365.25, 1)
                    months = int(diff_days / 30.4375)

                if years < 1:
                    bracket = 'Less than 1 Year'
                elif years <= 3:
                    bracket = '1 - 3 Years'
                elif years <= 5:
                    bracket = '3 - 5 Years'
                elif years <= 10:
                    bracket = '5 - 10 Years'
                else:
                    bracket = 'Above 10 Years'

                rows.append([
                    idx,
                    emp.identification_id or '',
                    emp.name or '',
                    str(hire_d or ''),
                    years,
                    months,
                    bracket,
                    emp.department_id.name if emp.department_id else '',
                    emp.default_operating_unit_id.name if emp.default_operating_unit_id else '',
                    emp.job_grade.grade_name if emp.job_grade else '',
                ])
            return headers, rows, False, sheet_title, sub_title

        elif rtype == 'separation':
            sheet_title = "Separation Report"
            sub_title = "Employee Separation & Exit Detailed Report"
            headers = ['No.', 'Employee ID', 'Employee Name', 'Resignation Ref', 'Notice Date', 'Expected Last Day',
                       'Release Date', 'Department', 'Branch / Operating Unit', 'Status', 'Reason']
            sep_domain = []
            if self.date_from:
                sep_domain.append(('application_date', '>=', self.date_from))
            if self.date_to:
                sep_domain.append(('application_date', '<=', self.date_to))
            if self.department_id:
                sep_domain.append(('department_id', '=', self.department_id.id))
            if self.operating_unit_id:
                sep_domain.append(('operating_unit_id', '=', self.operating_unit_id.id))

            resignations = self.env['hr.resignation'].search(sep_domain, order='application_date desc')
            rows = []
            for idx, res in enumerate(resignations, 1):
                rows.append([
                    idx,
                    res.employee_id.identification_id if res.employee_id else '',
                    res.employee_id.name if res.employee_id else '',
                    res.name or '',
                    str(res.application_date or ''),
                    str(res.expected_last_day or ''),
                    str(res.release_date or ''),
                    res.department_id.name if res.department_id else '',
                    res.operating_unit_id.name if res.operating_unit_id else '',
                    (res.state or '').capitalize(),
                    res.reason or '',
                ])
            return headers, rows, False, sheet_title, sub_title

        elif rtype == 'work_permit_expiry':
            sheet_title = "Work Permit Expiry"
            sub_title = "Work Permit & Visa Expiration Report"
            headers = ['No.', 'Employee ID', 'Employee Name', 'Nationality', 'Permit No.', 'Work Permit Expiry Date',
                       'Visa Expiry Date', 'Status', 'Department', 'Branch / Operating Unit']
            emp_domain = [('work_permit_status', 'in', ['valid', 'expiring_soon', 'expired'])]
            if self.operating_unit_id:
                emp_domain.append(('default_operating_unit_id', '=', self.operating_unit_id.id))
            employees = self.env['hr.employee'].search(emp_domain, order='work_permit_expiration_date asc')
            rows = []
            for idx, emp in enumerate(employees, 1):
                rows.append([
                    idx,
                    emp.identification_id or '',
                    emp.name or '',
                    emp.country_id.name if hasattr(emp, 'country_id') and emp.country_id else '',
                    emp.permit_no or '',
                    str(emp.work_permit_expiration_date or ''),
                    str(emp.visa_expire or ''),
                    (emp.work_permit_status or '').replace('_', ' ').capitalize(),
                    emp.department_id.name if emp.department_id else '',
                    emp.default_operating_unit_id.name if emp.default_operating_unit_id else '',
                ])
            return headers, rows, False, sheet_title, sub_title

        elif rtype == 'document':
            sheet_title = "Employee Documents"
            sub_title = "Employee Document & Compliance Status Report"
            headers = ['No.', 'Employee ID', 'Employee Name', 'Document Name', 'Document Type', 'Issue Date',
                       'Expiry Date', 'Status', 'Branch / Operating Unit']
            doc_domain = []
            if self.operating_unit_id:
                doc_domain.append(('employee_ref.default_operating_unit_id', '=', self.operating_unit_id.id))
            docs = self.env['hr.employee.document'].search(doc_domain, order='issue_date desc')
            rows = []
            today = date.today()
            for idx, d in enumerate(docs, 1):
                stat = 'Valid'
                if d.expiry_date and d.expiry_date < today:
                    stat = 'Expired'
                elif d.expiry_date and (d.expiry_date - today).days <= 30:
                    stat = 'Expiring Soon'
                rows.append([
                    idx,
                    d.employee_ref.identification_id if d.employee_ref else '',
                    d.employee_ref.name if d.employee_ref else '',
                    d.name or d.document_name or '',
                    d.document_type_id.name if d.document_type_id else '',
                    str(d.issue_date or ''),
                    str(d.expiry_date or ''),
                    stat,
                    d.employee_ref.default_operating_unit_id.name if d.employee_ref and d.employee_ref.default_operating_unit_id else '',
                ])
            return headers, rows, False, sheet_title, sub_title

        elif rtype == 'status':
            sheet_title = "Employee Status"
            sub_title = "Employee Validation & Employment Status Report"
            headers = ['No.', 'Employee ID', 'Full Name', 'Validation Status', 'Active', 'Department',
                       'Branch / Operating Unit', 'Job Position', 'Hire Date']
            employees = self.env['hr.employee'].search(domain, order='name asc')
            rows = []
            for idx, emp in enumerate(employees, 1):
                hire = str(emp.service_hire_date or emp.service_start_date or emp.start_date or '')
                rows.append([
                    idx,
                    emp.identification_id or '',
                    emp.name or '',
                    (emp.validation_state or 'Approved').capitalize(),
                    'Yes' if emp.active else 'No',
                    emp.department_id.name if emp.department_id else '',
                    emp.default_operating_unit_id.name if emp.default_operating_unit_id else '',
                    emp.job_position.name if emp.job_position else '',
                    hire,
                ])
            return headers, rows, False, sheet_title, sub_title

        return [], [], False, "HR Report", "HR Report"

    def _generate_analytical_excel_report(self, wb, rtype):
        """Generates analytical HR Excel reports using OpenPyXL with Bunna Bank theme and centered logo."""
        headers, rows, is_summary, sheet_title, sub_title = self._prepare_analytical_report_data(rtype)
        ws = wb.active
        ws.title = sheet_title[:31]

        self._apply_header_banner(ws, "BUNNA BANK S.C.", sub_title, max_col=len(headers))
        styles = self._get_table_styles()

        # Table Header Row (Row 10)
        ws.row_dimensions[10].height = 26
        for c_idx, h in enumerate(headers, 1):
            cell = ws.cell(10, c_idx, h)
            cell.fill = styles['header_fill']
            cell.font = styles['header_font']
            cell.border = styles['header_border']
            cell.alignment = styles['align_center']

        # Data Rows (Row 11+)
        alt_fill = PatternFill(start_color='FDFCF7', end_color='FDFCF7', fill_type='solid')
        cur_row = 11
        for r_idx, row in enumerate(rows):
            is_alt = (r_idx % 2 == 1)
            ws.row_dimensions[cur_row].height = 20
            for c_idx, val in enumerate(row, 1):
                cell = ws.cell(cur_row, c_idx, val)
                cell.font = styles['data_font']
                cell.border = styles['data_border']
                if is_alt:
                    cell.fill = alt_fill

                if isinstance(val, (int, float)) and c_idx > 1:
                    cell.alignment = styles['align_right']
                    cell.number_format = '#,##0'
                elif c_idx == 1:
                    cell.alignment = styles['align_center']
                else:
                    cell.alignment = styles['align_left']
            cur_row += 1

        # Summary Total Row
        if is_summary and rows:
            ws.row_dimensions[cur_row].height = 22
            total_fill = PatternFill(start_color='E8EFE5', end_color='E8EFE5', fill_type='solid')
            total_font = Font(name='Arial', size=10, bold=True, color='000000')
            t_label = ws.cell(cur_row, 1, 'TOTAL')
            t_label.font = total_font
            t_label.fill = total_fill
            t_label.border = styles['data_border']
            t_label.alignment = styles['align_center']

            for c_idx in range(2, len(headers) + 1):
                col_nums = [r[c_idx - 1] for r in rows if isinstance(r[c_idx - 1], (int, float))]
                cell = ws.cell(cur_row, c_idx)
                cell.fill = total_fill
                cell.font = total_font
                cell.border = styles['data_border']
                if col_nums:
                    cell.value = sum(col_nums)
                    cell.alignment = styles['align_right']
                    cell.number_format = '#,##0'
                else:
                    cell.value = ''

        self._auto_fit_columns(ws, max_col=len(headers), min_row=10)

    def action_export_excel(self):
        """Generates and downloads the Excel report according to selected type."""
        self.ensure_one()
        wb = openpyxl.Workbook()

        type_map = {
            'promotion': (self._generate_promotion_report, 'Employee_Promotion_Report'),
            'demotion': (self._generate_demotion_report, 'Employee_Demotion_Report'),
            'acting_assignment': (self._generate_acting_report, 'Employee_Acting_Assignment_Report'),
            'assignment': (self._generate_assignment_report, 'Employee_Assignment_Report'),
            'transfer': (self._generate_transfer_report, 'Employee_Transfer_Report'),
            'external_recruitment': (self._generate_recruitment_report, 'Employee_External_Recruitment_Report'),
        }

        if self.report_type in type_map:
            gen_func, base_filename = type_map[self.report_type]
            gen_func(wb)
        else:
            base_filename = f"Employee_{self.report_type.title()}_Report"
            self._generate_analytical_excel_report(wb, self.report_type)

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        file_bytes = output.getvalue()

        now_str = fields.Date.today().strftime('%Y%m%d')
        full_filename = f"{base_filename}_{now_str}.xlsx"

        self.write({
            'excel_file': base64.b64encode(file_bytes),
            'file_name': full_filename,
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/?model={self._name}&id={self.id}&field=excel_file&filename={self.file_name}&download=true',
            'target': 'self',
        }
