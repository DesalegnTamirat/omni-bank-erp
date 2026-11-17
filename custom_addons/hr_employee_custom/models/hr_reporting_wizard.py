import os
# -*- coding: utf-8 -*-
import base64
import datetime
import io
import xlsxwriter
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class HrReportingWizard(models.TransientModel):
    def _get_bunna_logo_path(self):
        """Returns path to the official Bunna Bank header logo."""
        custom_logo = os.path.abspath(os.path.join(
            os.path.dirname(__file__), '..', 'static', 'src', 'img', 'bunna_report_header_logo.png'
        ))
        if os.path.exists(custom_logo):
            return custom_logo
        fallback = os.path.abspath(os.path.join(
            os.path.dirname(__file__), '..', '..', 'competency_management', 'static', 'src', 'img', 'bunna_bank_official_logo.png'
        ))
        return fallback if os.path.exists(fallback) else False

    """
    Configurable HR Reporting & Analytics Generator for Bunna Bank S.C.
    Supports interactive list, pivot, and graph views, plus full Excel (.xlsx) exports
    across 18 standard HR analytical report domains.
    """
    _name = 'hr.reporting.wizard'
    _description = 'HR Reporting & Analytics Wizard'

    report_type = fields.Selection([
        ('profile', 'Employee Profile Report'),
        ('headcount', 'Headcount Report'),
        ('headcount_dept', 'Headcount by Department'),
        ('headcount_branch', 'Headcount by Branch (Operating Unit)'),
        ('headcount_grade', 'Headcount by Grade'),
        ('headcount_position', 'Headcount by Position'),
        ('demographic', 'Employee Demographic Report'),
        ('gender', 'Gender Report'),
        ('age_profile', 'Age Profile Report'),
        ('length_of_service', 'Length of Service Report'),
        ('work_permit_expiry', 'Work Permit Expiry Report'),
        ('document', 'Employee Document Report'),
        ('status', 'Employee Status Report'),
    ], string='Report Type', required=True, default='profile')

    date_from = fields.Date(string='Date From')
    date_to = fields.Date(string='Date To')
    department_id = fields.Many2one('hr.department', string='Department')
    operating_unit_id = fields.Many2one('operating.unit', string='Branch / Operating Unit')
    job_id = fields.Many2one('hr.job', string='Job Position')
    grade_id = fields.Many2one('employee.grade', string='Employee Grade')
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

    def _get_employee_domain(self):
        self.ensure_one()
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

    def action_generate_report(self):
        """Launches interactive list, pivot, and graph views inside Odoo."""
        self.ensure_one()
        rtype = self.report_type
        emp_domain = self._get_employee_domain()
        report_label = dict(self._fields['report_type'].selection).get(rtype, rtype)

        if rtype in ('profile', 'headcount', 'headcount_dept', 'headcount_branch', 'headcount_grade',
                     'headcount_position', 'demographic', 'gender', 'age_profile', 'length_of_service',
                     'work_permit_expiry', 'status'):
            res_model = 'hr.employee'
            view_mode = 'list,pivot,graph'
            ctx = dict(self.env.context)

            if rtype == 'headcount_dept':
                ctx['group_by'] = ['department_id']
                view_mode = 'pivot,graph,list'
            elif rtype == 'headcount_branch':
                ctx['group_by'] = ['default_operating_unit_id']
                view_mode = 'pivot,graph,list'
            elif rtype == 'headcount_grade':
                ctx['group_by'] = ['job_grade']
                view_mode = 'pivot,graph,list'
            elif rtype == 'headcount_position':
                ctx['group_by'] = ['job_position']
                view_mode = 'pivot,graph,list'
            elif rtype == 'gender':
                ctx['group_by'] = ['gender']
                view_mode = 'pivot,graph,list'
            elif rtype == 'age_profile':
                ctx['group_by'] = ['age_group']
                view_mode = 'pivot,graph,list'
            elif rtype == 'length_of_service':
                ctx['group_by'] = ['tenure_group']
                view_mode = 'pivot,graph,list'
            elif rtype == 'work_permit_expiry':
                emp_domain.append(('work_permit_status', 'in', ['valid', 'expiring_soon', 'expired']))
                ctx['group_by'] = ['work_permit_status']
                view_mode = 'list,pivot'
            elif rtype == 'status':
                ctx['group_by'] = ['validation_state']
                view_mode = 'pivot,list'

            return {
                'name': _("HR Report: %s") % report_label,
                'type': 'ir.actions.act_window',
                'res_model': res_model,
                'view_mode': view_mode,
                'domain': emp_domain,
                'context': ctx,
                'target': 'current',
            }

        elif rtype in ('movement', 'promotion'):
            res_model = 'hr.job.history'
            hist_domain = []
            if self.date_from:
                hist_domain.append(('job_history_start_date', '>=', self.date_from))
            if self.date_to:
                hist_domain.append(('job_history_start_date', '<=', self.date_to))
            if self.department_id:
                hist_domain.append(('department_id', '=', self.department_id.id))
            if self.operating_unit_id:
                hist_domain.append(('operating_unit_id', '=', self.operating_unit_id.id))
            if self.job_id:
                hist_domain.append(('job_id', '=', self.job_id.id))

            return {
                'name': _("HR Report: %s") % report_label,
                'type': 'ir.actions.act_window',
                'res_model': res_model,
                'view_mode': 'list,pivot,graph',
                'domain': hist_domain,
                'context': {'group_by': ['job_id', 'department_id']},
                'target': 'current',
            }

        elif rtype == 'transfer':
            res_model = 'hr.employee.transfer.history'
            trf_domain = []
            if self.date_from:
                trf_domain.append(('date', '>=', self.date_from))
            if self.date_to:
                trf_domain.append(('date', '<=', self.date_to))
            if self.department_id:
                trf_domain.append(('to_department_id', '=', self.department_id.id))
            if self.operating_unit_id:
                trf_domain.append(('to_operating_unit_id', '=', self.operating_unit_id.id))

            return {
                'name': _("HR Report: %s") % report_label,
                'type': 'ir.actions.act_window',
                'res_model': res_model,
                'view_mode': 'list,pivot',
                'domain': trf_domain,
                'context': {'group_by': ['to_operating_unit_id']},
                'target': 'current',
            }

        elif rtype == 'recruitment':
            res_model = 'hr.applicant'
            app_domain = []
            if self.date_from:
                app_domain.append(('create_date', '>=', self.date_from))
            if self.date_to:
                app_domain.append(('create_date', '<=', self.date_to))
            if self.department_id:
                app_domain.append(('department_id', '=', self.department_id.id))
            if self.job_id:
                app_domain.append(('job_id', '=', self.job_id.id))

            return {
                'name': _("HR Report: %s") % report_label,
                'type': 'ir.actions.act_window',
                'res_model': res_model,
                'view_mode': 'list,pivot,graph',
                'domain': app_domain,
                'context': {'group_by': ['stage_id', 'department_id']},
                'target': 'current',
            }

        elif rtype == 'separation':
            res_model = 'hr.resignation'
            sep_domain = []
            if self.date_from:
                sep_domain.append(('expected_last_day', '>=', self.date_from))
            if self.date_to:
                sep_domain.append(('expected_last_day', '<=', self.date_to))
            if self.department_id:
                sep_domain.append(('department_id', '=', self.department_id.id))
            if self.operating_unit_id:
                sep_domain.append(('operating_unit_id', '=', self.operating_unit_id.id))

            return {
                'name': _("HR Report: %s") % report_label,
                'type': 'ir.actions.act_window',
                'res_model': res_model,
                'view_mode': 'list,pivot,graph',
                'domain': sep_domain,
                'context': {'group_by': ['state', 'resignation_type_id']},
                'target': 'current',
            }

        elif rtype == 'document':
            res_model = 'hr.employee.document'
            doc_domain = []
            if self.department_id:
                doc_domain.append(('employee_ref.department_id', '=', self.department_id.id))
            if self.operating_unit_id:
                doc_domain.append(('employee_ref.default_operating_unit_id', '=', self.operating_unit_id.id))

            return {
                'name': _("HR Report: %s") % report_label,
                'type': 'ir.actions.act_window',
                'res_model': res_model,
                'view_mode': 'list,pivot',
                'domain': doc_domain,
                'context': {'group_by': ['document_type_id']},
                'target': 'current',
            }

        return {'type': 'ir.actions.act_window_close'}

    def action_export_excel(self):
        """Generates a professional styled Excel (.xlsx) report with Bunna Bank logo and corporate branding."""
        self.ensure_one()
        rtype = self.report_type
        report_label = dict(self._fields['report_type'].selection).get(rtype, rtype)

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Report')
        worksheet.hide_gridlines(0)

        # Corporate Bunna Bank Styles
        title_style = workbook.add_format({
            'bold': True, 'font_size': 14, 'font_name': 'Arial',
            'font_color': '#000000', 'align': 'center', 'valign': 'vcenter'
        })
        sub_style = workbook.add_format({
            'bold': True, 'font_size': 12, 'font_name': 'Arial',
            'font_color': '#000000', 'align': 'center', 'valign': 'vcenter'
        })
        period_style = workbook.add_format({
            'font_size': 11, 'font_name': 'Arial',
            'font_color': '#222222', 'align': 'center', 'valign': 'vcenter'
        })
        meta_style = workbook.add_format({
            'font_size': 10, 'font_name': 'Arial', 'italic': True,
            'font_color': '#444444', 'align': 'center', 'valign': 'vcenter'
        })
        th_style = workbook.add_format({
            'bold': True, 'font_name': 'Arial', 'font_size': 10,
            'font_color': '#FFFFFF', 'bg_color': '#6A1A24', 'align': 'center', 'valign': 'vcenter',
            'border': 1, 'border_color': '#555555', 'text_wrap': True
        })
        cell_style = workbook.add_format({
            'font_name': 'Arial', 'font_size': 9, 'valign': 'vcenter',
            'border': 1, 'border_color': '#D3D3D3'
        })
        cell_alt_style = workbook.add_format({
            'font_name': 'Arial', 'font_size': 9, 'valign': 'vcenter',
            'border': 1, 'border_color': '#D3D3D3', 'bg_color': '#FDFCF7'
        })
        num_style = workbook.add_format({
            'font_name': 'Arial', 'font_size': 9, 'align': 'right', 'valign': 'vcenter',
            'border': 1, 'border_color': '#D3D3D3', 'num_format': '#,##0'
        })
        num_alt_style = workbook.add_format({
            'font_name': 'Arial', 'font_size': 9, 'align': 'right', 'valign': 'vcenter',
            'border': 1, 'border_color': '#D3D3D3', 'bg_color': '#FDFCF7', 'num_format': '#,##0'
        })
        total_style = workbook.add_format({
            'bold': True, 'font_name': 'Arial', 'font_size': 10,
            'font_color': '#000000', 'bg_color': '#E8EFE5', 'border': 1, 'border_color': '#6A1A24',
            'align': 'right', 'valign': 'vcenter', 'num_format': '#,##0'
        })
        total_label_style = workbook.add_format({
            'bold': True, 'font_name': 'Arial', 'font_size': 10,
            'font_color': '#000000', 'bg_color': '#E8EFE5', 'border': 1, 'border_color': '#6A1A24',
            'align': 'left', 'valign': 'vcenter'
        })

        # Fetch Data and build headers based on report type
        headers, rows, is_summary = self._prepare_report_data(rtype)

        num_cols = max(len(headers), 5)
        last_col_idx = num_cols - 1

        # Adjust height of top rows reserved for logo
        worksheet.set_row(0, 20)
        worksheet.set_row(1, 20)
        worksheet.set_row(2, 25)
        worksheet.set_row(3, 15)

        # 1. Main Title (Row 5 / index 4)
        worksheet.set_row(4, 24)
        worksheet.merge_range(4, 0, 4, last_col_idx, 'BUNNA BANK S.C.', title_style)

        # 2. Subtitle (Row 6 / index 5)
        worksheet.set_row(5, 20)
        worksheet.merge_range(5, 0, 5, last_col_idx, f'HR REPORTING & ANALYTICS - {report_label.upper()}', sub_style)

        # 3. Reporting Period (Row 7 / index 6)
        d_from = str(self.date_from) if self.date_from else 'All'
        d_to = str(self.date_to) if self.date_to else 'All'
        worksheet.set_row(6, 18)
        worksheet.merge_range(6, 0, 6, last_col_idx, f'Reporting Period: {d_from} To {d_to}', period_style)

        # 4. Metadata (Row 8 / index 7)
        dept_name = self.department_id.name if self.department_id else 'All Departments'
        ou_name = self.operating_unit_id.name if self.operating_unit_id else 'All Branches / Operating Units'
        now_str = fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        meta_text = f"Generated on: {now_str} | Department: {dept_name} | Branch: {ou_name}"
        worksheet.set_row(7, 18)
        worksheet.merge_range(7, 0, 7, last_col_idx, meta_text, meta_style)

        # Row 9 (index 8) is blank spacing
        worksheet.set_row(8, 10)

        # Table Header Row (Row 10 / index 9)
        start_row = 9
        worksheet.set_row(start_row, 26)
        for c_idx, h in enumerate(headers):
            worksheet.write(start_row, c_idx, h, th_style)

        # Write Data Rows
        cur_row = start_row + 1
        col_max_lens = [len(h) for h in headers]

        for r_idx, row in enumerate(rows):
            is_alt = (r_idx % 2 == 1)
            worksheet.set_row(cur_row, 20)
            for c_idx, val in enumerate(row):
                str_val = str(val if val is not None else '')
                col_max_lens[c_idx] = max(col_max_lens[c_idx], len(str_val))

                if isinstance(val, (int, float)) and c_idx > 0:
                    worksheet.write(cur_row, c_idx, val, num_alt_style if is_alt else num_style)
                else:
                    worksheet.write(cur_row, c_idx, str_val, cell_alt_style if is_alt else cell_style)
            cur_row += 1

        # Summary Total Row for count/aggregations
        if is_summary and rows:
            worksheet.set_row(cur_row, 22)
            worksheet.write(cur_row, 0, 'TOTAL', total_label_style)
            for c_idx in range(1, len(headers)):
                if any(isinstance(r[c_idx], (int, float)) for r in rows):
                    total_val = sum(r[c_idx] for r in rows if isinstance(r[c_idx], (int, float)))
                    worksheet.write(cur_row, c_idx, total_val, total_style)
                else:
                    worksheet.write(cur_row, c_idx, '', total_label_style)

        # Auto-fit Column Widths and Calculate Pixel Positions
        col_widths_px = []
        for c_idx in range(num_cols):
            m_len = col_max_lens[c_idx] if c_idx < len(col_max_lens) else 10
            col_w = min(max(m_len + 4, 13), 40)
            worksheet.set_column(c_idx, c_idx, col_w)
            col_widths_px.append(int(col_w * 7.5 + 5))

        # Position Bunna Logo Centered Horizontally
        total_px = sum(col_widths_px)
        center_px = total_px / 2.0
        img_w = 180
        img_h = 70
        logo_left_px = max(0, center_px - (img_w / 2.0))

        cum_px = 0
        anchor_col = 0
        x_offset = 0
        for idx, c_px in enumerate(col_widths_px):
            if cum_px + c_px > logo_left_px:
                anchor_col = idx
                x_offset = int(logo_left_px - cum_px)
                break
            cum_px += c_px

        logo_path = self._get_bunna_logo_path()
        if logo_path and os.path.exists(logo_path):
            try:
                worksheet.insert_image(0, anchor_col, logo_path, {
                    'x_offset': x_offset,
                    'y_offset': 5,
                    'x_scale': img_w / 228.0,
                    'y_scale': img_h / 93.0,
                    'positioning': 1,
                })
            except Exception:
                pass

        worksheet.freeze_panes(start_row + 1, 0)
        workbook.close()
        output.seek(0)
        file_data = output.getvalue()

        # Save to ir.attachment and download
        filename = f"{report_label.replace(' ', '_').replace('.', '')}_{fields.Date.today()}.xlsx"
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(file_data),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'res_model': self._name,
            'res_id': self.id,
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def _prepare_report_data(self, rtype):
        """Prepares structured (headers, rows, is_summary) data for the Excel engine."""
        domain = self._get_employee_domain()

        # 1. Employee Profile Report
        if rtype == 'profile':
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
            return headers, rows, False

        # 2. Headcount Report (Summary by Department & Branch)
        elif rtype == 'headcount':
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
            return headers, rows, True

        # 3. Headcount by Department
        elif rtype == 'headcount_dept':
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
            return headers, rows, True

        # 4. Headcount by Branch (Operating Unit)
        elif rtype == 'headcount_branch':
            headers = ['No.', 'Branch / Operating Unit', 'Work Unit Type', 'Total Staff', 'Male', 'Female', '% Share']
            employees = self.env['hr.employee'].search(domain)
            total_all = len(employees) or 1
            ous = {}
            for emp in employees:
                ou = emp.default_operating_unit_id
                ouid = ou.id if ou else 0
                ou_name = ou.name if ou else 'Head Office / Unassigned'
                ou_type = getattr(ou, 'work_unit_type', '') or ''
                if ouid not in ous:
                    ous[ouid] = {'name': ou_name, 'type': ou_type.capitalize(), 'total': 0, 'male': 0, 'female': 0}
                ous[ouid]['total'] += 1
                if emp.gender == 'male':
                    ous[ouid]['male'] += 1
                elif emp.gender == 'female':
                    ous[ouid]['female'] += 1
            rows = []
            for idx, (_, odata) in enumerate(sorted(ous.items(), key=lambda x: x[1]['total'], reverse=True), 1):
                share = round((odata['total'] / total_all) * 100, 1)
                rows.append([idx, odata['name'], odata['type'], odata['total'], odata['male'], odata['female'], f"{share}%"])
            return headers, rows, True

        # 5. Headcount by Grade
        elif rtype == 'headcount_grade':
            headers = ['No.', 'Job Grade', 'Grade Level', 'Headcount', 'Male Count', 'Female Count', '% Share']
            employees = self.env['hr.employee'].search(domain)
            total_all = len(employees) or 1
            grades = {}
            for emp in employees:
                g = emp.job_grade
                gid = g.id if g else 0
                gname = g.grade_name if g else 'Unassigned Grade'
                glevel = (g.grade_level or '').capitalize() if g else ''
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
            return headers, rows, True

        # 6. Headcount by Position
        elif rtype == 'headcount_position':
            headers = ['No.', 'Job Position Title', 'Department', 'Job Grade', 'Total Headcount', 'Male', 'Female']
            employees = self.env['hr.employee'].search(domain)
            jobs = {}
            for emp in employees:
                j = emp.job_position
                jid = j.id if j else 0
                jname = j.name if j else 'Unassigned Position'
                dname = emp.department_id.name if emp.department_id else ''
                gname = emp.job_grade.grade_name if emp.job_grade else ''
                if jid not in jobs:
                    jobs[jid] = {'name': jname, 'dept': dname, 'grade': gname, 'total': 0, 'male': 0, 'female': 0}
                jobs[jid]['total'] += 1
                if emp.gender == 'male':
                    jobs[jid]['male'] += 1
                elif emp.gender == 'female':
                    jobs[jid]['female'] += 1
            rows = []
            for idx, (_, jdata) in enumerate(sorted(jobs.items(), key=lambda x: x[1]['total'], reverse=True), 1):
                rows.append([idx, jdata['name'], jdata['dept'], jdata['grade'], jdata['total'], jdata['male'], jdata['female']])
            return headers, rows, True

        # 7. Employee Demographic Report
        elif rtype == 'demographic':
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
            return headers, rows, False

        # 8. Gender Report
        elif rtype == 'gender':
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
            return headers, rows, True

        # 9. Age Profile Report
        elif rtype == 'age_profile':
            headers = ['No.', 'Employee ID', 'Full Name', 'Gender', 'Birth Date', 'Age', 'Age Bracket',
                       'Department', 'Branch / Operating Unit', 'Job Position']
            employees = self.env['hr.employee'].search(domain, order='birthday asc')
            rows = []
            today = fields.Date.today()
            for idx, emp in enumerate(employees, 1):
                age = 0
                if emp.birthday:
                    age = today.year - emp.birthday.year - ((today.month, today.day) < (emp.birthday.month, emp.birthday.day))
                elif emp.age and emp.age.isdigit():
                    age = int(emp.age)

                if age < 25:
                    bracket = 'Under 25 Years'
                elif age <= 35:
                    bracket = '25 – 35 Years'
                elif age <= 45:
                    bracket = '36 – 45 Years'
                elif age <= 55:
                    bracket = '46 – 55 Years'
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
            return headers, rows, False

        # 10. Length of Service (Tenure) Report
        elif rtype == 'length_of_service':
            headers = ['No.', 'Employee ID', 'Full Name', 'Hire / Start Date', 'Service Years', 'Service Months',
                       'Tenure Bracket', 'Department', 'Branch / Operating Unit', 'Job Grade']
            employees = self.env['hr.employee'].search(domain, order='name asc')
            rows = []
            today = fields.Date.today()
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
                    bracket = '1 – 3 Years'
                elif years <= 5:
                    bracket = '3 – 5 Years'
                elif years <= 10:
                    bracket = '5 – 10 Years'
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
            return headers, rows, False

        # 11. Employee Movement Report
        elif rtype == 'movement':
            headers = ['No.', 'Employee ID', 'Employee Name', 'Start Date', 'End Date', 'Previous Position',
                       'New Position', 'Department', 'Branch / Operating Unit', 'Reason / Remarks']
            hist_domain = []
            if self.date_from:
                hist_domain.append(('job_history_start_date', '>=', self.date_from))
            if self.date_to:
                hist_domain.append(('job_history_start_date', '<=', self.date_to))
            if self.department_id:
                hist_domain.append(('department_id', '=', self.department_id.id))
            if self.operating_unit_id:
                hist_domain.append(('operating_unit_id', '=', self.operating_unit_id.id))

            history = self.env['hr.job.history'].search(hist_domain, order='job_history_start_date desc', limit=3000)
            rows = []
            for idx, h in enumerate(history, 1):
                rows.append([
                    idx,
                    h.employee_id.identification_id if h.employee_id else '',
                    h.employee_id.name if h.employee_id else '',
                    str(h.job_history_start_date or ''),
                    str(h.job_history_end_date or ''),
                    h.from_job_id.name if hasattr(h, 'from_job_id') and h.from_job_id else '',
                    h.job_id.name if h.job_id else (h.to_job_id.name if hasattr(h, 'to_job_id') and h.to_job_id else ''),
                    h.department_id.name if h.department_id else '',
                    h.operating_unit_id.name if h.operating_unit_id else '',
                    h.reason_for_change or '',
                ])
            return headers, rows, False

        # 12. Promotion Report
        elif rtype == 'promotion':
            headers = ['No.', 'Employee ID', 'Employee Name', 'Promotion Date', 'Promoted Position', 'Job Grade',
                       'Department', 'Branch / Operating Unit', 'New Wage']
            hist_domain = [('reason_for_change', 'ilike', 'promotion')]
            if self.date_from:
                hist_domain.append(('job_history_start_date', '>=', self.date_from))
            if self.date_to:
                hist_domain.append(('job_history_start_date', '<=', self.date_to))
            if self.department_id:
                hist_domain.append(('department_id', '=', self.department_id.id))
            if self.operating_unit_id:
                hist_domain.append(('operating_unit_id', '=', self.operating_unit_id.id))

            promotions = self.env['hr.job.history'].search(hist_domain, order='job_history_start_date desc', limit=2000)
            if not promotions:
                promotions = self.env['hr.job.history'].search([], order='job_history_start_date desc', limit=200)

            rows = []
            for idx, p in enumerate(promotions, 1):
                rows.append([
                    idx,
                    p.employee_id.identification_id if p.employee_id else '',
                    p.employee_id.name if p.employee_id else '',
                    str(p.job_history_start_date or ''),
                    p.job_id.name if p.job_id else '',
                    p.grade_id.grade_name if p.grade_id else '',
                    p.department_id.name if p.department_id else '',
                    p.operating_unit_id.name if p.operating_unit_id else '',
                    p.new_wage or 0.0,
                ])
            return headers, rows, False

        # 13. Transfer Report
        elif rtype == 'transfer':
            headers = ['No.', 'Employee ID', 'Employee Name', 'Transfer Date', 'From Work Unit', 'To Work Unit',
                       'From Department', 'To Department', 'Transfer Reason']
            trf_domain = []
            if self.date_from:
                trf_domain.append(('date', '>=', self.date_from))
            if self.date_to:
                trf_domain.append(('date', '<=', self.date_to))
            if self.department_id:
                trf_domain.append(('to_department_id', '=', self.department_id.id))
            if self.operating_unit_id:
                trf_domain.append(('to_operating_unit_id', '=', self.operating_unit_id.id))

            transfers = self.env['hr.employee.transfer.history'].search(trf_domain, order='date desc')
            rows = []
            for idx, t in enumerate(transfers, 1):
                rows.append([
                    idx,
                    t.employee_id.identification_id if t.employee_id else '',
                    t.employee_id.name if t.employee_id else '',
                    str(t.date or t.start_date or ''),
                    t.from_operating_unit_id.name if t.from_operating_unit_id else '',
                    t.to_operating_unit_id.name if t.to_operating_unit_id else '',
                    t.from_department_id.name if t.from_department_id else '',
                    t.to_department_id.name if t.to_department_id else '',
                    t.transfer_reason or '',
                ])
            return headers, rows, False

        # 14. Recruitment Report
        elif rtype == 'recruitment':
            headers = ['No.', 'Candidate / Employee Name', 'Application Date', 'Applied Position', 'Department',
                       'Gender', 'Recruitment Stage', 'Application Type']
            app_domain = []
            if self.date_from:
                app_domain.append(('create_date', '>=', self.date_from))
            if self.date_to:
                app_domain.append(('create_date', '<=', self.date_to))
            if self.department_id:
                app_domain.append(('department_id', '=', self.department_id.id))
            if self.job_id:
                app_domain.append(('job_id', '=', self.job_id.id))

            applicants = self.env['hr.applicant'].search(app_domain, order='create_date desc', limit=2000)
            rows = []
            for idx, app in enumerate(applicants, 1):
                c_date = app.create_date.strftime('%Y-%m-%d') if app.create_date else ''
                rows.append([
                    idx,
                    app.partner_name or '',
                    c_date,
                    app.job_id.name if app.job_id else '',
                    app.department_id.name if app.department_id else '',
                    (app.gender or '').capitalize(),
                    app.stage_id.name if app.stage_id else '',
                    app.application_type or 'External',
                ])
            return headers, rows, False

        # 15. Separation Report
        elif rtype == 'separation':
            headers = ['No.', 'Employee ID', 'Employee Name', 'Resignation Ref', 'Notice Date', 'Expected Last Day',
                       'Release Date', 'Department', 'Branch / Operating Unit', 'Status', 'Reason']
            sep_domain = []
            if self.date_from:
                sep_domain.append(('expected_last_day', '>=', self.date_from))
            if self.date_to:
                sep_domain.append(('expected_last_day', '<=', self.date_to))
            if self.department_id:
                sep_domain.append(('department_id', '=', self.department_id.id))
            if self.operating_unit_id:
                sep_domain.append(('operating_unit_id', '=', self.operating_unit_id.id))

            resignations = self.env['hr.resignation'].search(sep_domain, order='expected_last_day desc')
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
            return headers, rows, False

        # 16. Work Permit Expiry Report
        elif rtype == 'work_permit_expiry':
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
            return headers, rows, False

        # 17. Employee Document Report
        elif rtype == 'document':
            headers = ['No.', 'Employee ID', 'Employee Name', 'Document Name', 'Document Type', 'Issue Date',
                       'Expiry Date', 'Status', 'Branch / Operating Unit']
            doc_domain = []
            if self.operating_unit_id:
                doc_domain.append(('employee_ref.default_operating_unit_id', '=', self.operating_unit_id.id))
            docs = self.env['hr.employee.document'].search(doc_domain, order='issue_date desc')
            rows = []
            today = fields.Date.today()
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
            return headers, rows, False

        # 18. Employee Status Report
        elif rtype == 'status':
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
            return headers, rows, False

        return [], [], False