# -*- coding: utf-8 -*-
import base64
import io
import os
import xlsxwriter
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class CompetencyMultiCycleReportWizard(models.TransientModel):
    """Dedicated wizard for Multi-Cycle Competency Capability, Gap Evolution & Trend Reporting."""
    _name = 'competency.multi.cycle.report.wizard'
    _description = 'Multi-Cycle Competency Gap & Trend Report'

    cycle_ids = fields.Many2many(
        'competency.assessment.cycle',
        'comp_multi_cycle_wizard_cycle_rel',
        'wizard_id', 'cycle_id',
        string='Assessment Cycles to Compare',
        required=True,
        default=lambda self: self.env['competency.assessment.cycle'].search([], order='id desc', limit=2)
    )

    assessment_type_filter = fields.Selection([
        ('all', 'All Ratings (Consolidated 360°)'),
        ('self', 'Self-Assessment Only'),
        ('peer', 'Peer Evaluation Only'),
        ('subordinate', 'Subordinate Evaluation Only'),
        ('supervisor', 'Supervisor Rating Only'),
    ], string='Rating Basis', default='all', required=True,
       help="Select whether to compare overall 360° consolidated ratings or focus specifically on a single rater perspective.")

    # Organizational Filters
    department_ids = fields.Many2many('hr.department', string='Departments')
    operating_unit_ids = fields.Many2many('operating.unit', string='Workunits / Branches')
    job_ids = fields.Many2many('hr.job', string='Job Roles / Positions')
    grade_ids = fields.Many2many('employee.grade', string='Job Grades')
    employee_ids = fields.Many2many('hr.employee', string='Specific Employees')
    competency_ids = fields.Many2many('competency.competency', string='Specific Competencies')

    pillar = fields.Selection([
        ('all', 'All Pillars'),
        ('core', 'Core Competencies'),
        ('leadership', 'Leadership Competencies'),
        ('technical', 'Technical Competencies'),
    ], string='Competency Pillar', default='all')

    gender_filter = fields.Selection([
        ('all', 'All Genders'),
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
    ], string='Gender Filter', default='all')

    @api.model
    def default_get(self, fields_list):
        user = self.env.user
        if not (self.env.is_admin() or self.env.su or user.has_group('competency_management.group_competency_officer') or user.has_group('competency_management.group_competency_admin')):
            raise AccessError(_("Access Denied: Only HR Officers and Competency Administrators can access reporting."))
        self = self.with_context(competency_employee_select=True)
        return super(CompetencyMultiCycleReportWizard, self).default_get(fields_list)

    def web_read(self, specification):
        user = self.env.user
        if not (self.env.is_admin() or self.env.su or user.has_group('competency_management.group_competency_officer') or user.has_group('competency_management.group_competency_admin')):
            raise AccessError(_("Access Denied: Only HR Officers and Competency Administrators can access reporting."))
        return super(CompetencyMultiCycleReportWizard, self.sudo().with_context(competency_employee_select=True)).web_read(specification)

    def read(self, fields=None, load='_classic_read'):
        user = self.env.user
        if not (self.env.is_admin() or self.env.su or user.has_group('competency_management.group_competency_officer') or user.has_group('competency_management.group_competency_admin')):
            raise AccessError(_("Access Denied: Only HR Officers and Competency Administrators can access reporting."))
        return super(CompetencyMultiCycleReportWizard, self.sudo().with_context(competency_employee_select=True)).read(fields=fields, load=load)

    @api.onchange('department_ids')
    def _onchange_department_ids(self):
        """Cascading Filter: Department -> Operating Unit, Jobs, and Employees."""
        if self.department_ids:
            ou_direct = self.env['operating.unit'].search([('department', 'in', self.department_ids.ids)])
            ou_from_dept = self.department_ids.mapped('operating_unit_id')
            dept_emps = self.env['hr.employee'].with_context(competency_employee_select=True).search([('department_id', 'in', self.department_ids.ids)])
            ou_from_emps = dept_emps.mapped('default_operating_unit_id') | dept_emps.mapped('operating_unit_id')
            allowed_ous = (ou_direct | ou_from_dept | ou_from_emps).filtered(lambda u: u.id)
            domain_ou = [('id', 'in', allowed_ous.ids)]
            domain_job = [('department_id', 'in', self.department_ids.ids)]
            domain_emp = [('department_id', 'in', self.department_ids.ids)]

            if self.operating_unit_ids:
                self.operating_unit_ids = self.operating_unit_ids.filtered(lambda u: u.id in allowed_ous.ids)
            if self.job_ids:
                matching_jobs = self.env['hr.job'].search(domain_job)
                self.job_ids = self.job_ids & matching_jobs
            if self.employee_ids:
                self.employee_ids = self.employee_ids.filtered(lambda e: e.department_id.id in self.department_ids.ids)

            return {
                'domain': {
                    'operating_unit_ids': domain_ou,
                    'job_ids': domain_job,
                    'employee_ids': domain_emp,
                }
            }
        return {
            'domain': {
                'operating_unit_ids': [],
                'job_ids': [],
                'employee_ids': [],
            }
        }

    def _build_domain_for_cycle(self, cycle):
        """Construct search domain for lines belonging to a specific cycle."""
        domain = [('cycle_id', '=', cycle.id), ('is_primary_reporting_line', '=', True)]

        user = self.env.user.sudo()
        emp = user.employee_id
        is_admin = bool(
            user.has_group('competency_management.group_competency_admin')
            or user.has_group('base.group_system')
            or self.env.su
            or self.env.is_admin()
        )

        if not is_admin and emp:
            managed_depts = self.env['hr.department'].sudo().search([('manager_id', '=', emp.id)])
            is_dept_manager = bool(managed_depts or (emp.department_id and emp.department_id.manager_id.id == emp.id))
            if is_dept_manager:
                depts = managed_depts or emp.department_id
                domain.append(('department_id', 'in', depts.ids))
            else:
                is_supervisor = user.has_group('competency_management.group_competency_supervisor') or bool(emp.child_ids)
                if not is_supervisor:
                    domain.append(('employee_id', '=', emp.id))

        if self.department_ids:
            domain.append(('department_id', 'in', self.department_ids.ids))
        if self.operating_unit_ids:
            domain.append('|')
            domain.append(('employee_id.default_operating_unit_id', 'in', self.operating_unit_ids.ids))
            domain.append(('department_id.operating_unit_id', 'in', self.operating_unit_ids.ids))
        if self.job_ids:
            domain.append(('employee_id.job_id', 'in', self.job_ids.ids))
        if self.grade_ids:
            domain.append(('employee_id.grade_id', 'in', self.grade_ids.ids))
        if self.employee_ids:
            domain.append(('employee_id', 'in', self.employee_ids.ids))
        if self.competency_ids:
            domain.append(('competency_id', 'in', self.competency_ids.ids))
        if self.pillar != 'all':
            domain.append(('pillar', '=', self.pillar))
        if self.gender_filter != 'all':
            domain.append(('employee_id.gender', '=', self.gender_filter))

        if self.assessment_type_filter == 'self':
            domain.append(('self_rating', '>', 0))
        elif self.assessment_type_filter == 'peer':
            domain.append(('peer_avg', '>', 0))
        elif self.assessment_type_filter == 'subordinate':
            domain.append(('subordinate_avg', '>', 0))
        elif self.assessment_type_filter == 'supervisor':
            domain.append(('supervisor_avg', '>', 0))

        return domain

    def _setup_worksheet_header(self, worksheet, workbook, title):
        """Inserts Bunna Bank logo and corporate branding header onto an xlsx worksheet."""
        logo_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'src', 'img', 'bunna_bank_official_logo.png')
        )
        if not os.path.exists(logo_path):
            alt_path = '/mnt/extra-addons/custom_recruitment/static/src/img/bunna_bank_official_logo.png'
            if os.path.exists(alt_path):
                logo_path = alt_path

        if os.path.exists(logo_path):
            worksheet.insert_image('A1', logo_path, {'x_scale': 0.28, 'y_scale': 0.28, 'x_offset': 8, 'y_offset': 6})

        title_fmt = workbook.add_format({
            'bold': True, 'font_name': 'Arial', 'font_size': 13,
            'font_color': '#541718', 'valign': 'vcenter'
        })
        sub_fmt = workbook.add_format({
            'bold': True, 'font_name': 'Arial', 'font_size': 10,
            'font_color': '#726732', 'valign': 'vcenter'
        })
        meta_fmt = workbook.add_format({
            'italic': True, 'font_name': 'Arial', 'font_size': 9,
            'font_color': '#475569', 'valign': 'vcenter'
        })

        worksheet.set_row(0, 20)
        worksheet.set_row(1, 18)
        worksheet.set_row(2, 16)
        worksheet.set_row(3, 10)

        worksheet.write('D1', 'BUNNA BANK S.C.', title_fmt)
        worksheet.write('D2', title or 'Multi-Cycle Competency Gap & Trend Analysis', sub_fmt)

        cycles_str = ", ".join(self.cycle_ids.mapped('name'))
        focus_label = dict(self._fields['assessment_type_filter'].selection).get(self.assessment_type_filter, 'All 360° Ratings')
        now_str = fields.Datetime.now().strftime('%Y-%m-%d %H:%M')
        meta_text = f"Cycles: {cycles_str}   |   Rating Basis: {focus_label}   |   Exported: {now_str}"
        worksheet.write('D3', meta_text, meta_fmt)

        worksheet.set_header('&C&12&"Arial,Bold"BUNNA BANK S.C.&R&D')
        worksheet.set_footer('&LConfidential - Internal Banking Capability Trend&RPage &P of &N')
        worksheet.repeat_rows(4)

        return 4

    def action_export_xlsx(self):
        """Export multi-cycle comparative gap and evolution report to Excel."""
        self.ensure_one()
        if len(self.cycle_ids) < 2:
            raise UserError(_("Please select at least 2 assessment cycles to generate a comparative trend report."))

        user = self.env.user
        if not (self.env.is_admin() or self.env.su or user.has_group('competency_management.group_competency_officer') or user.has_group('competency_management.group_competency_admin')):
            raise AccessError(_("Access Denied: Only HR Officers and Competency Administrators can export reports."))

        # Sort cycles chronologically by date/id
        sorted_cycles = self.cycle_ids.sorted(lambda c: (c.period_start or fields.Date.today(), c.id))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        # Styling
        fmt_title = workbook.add_format({
            'bold': True, 'font_size': 13, 'font_color': '#FFFFFF',
            'bg_color': '#541718', 'align': 'center', 'valign': 'vcenter'
        })
        fmt_header = workbook.add_format({
            'bold': True, 'font_size': 10, 'font_color': '#FFFFFF',
            'bg_color': '#541718', 'align': 'center', 'valign': 'vcenter',
            'border': 1, 'text_wrap': True
        })
        fmt_cycle_header = workbook.add_format({
            'bold': True, 'font_size': 10, 'font_color': '#FFFFFF',
            'bg_color': '#726732', 'align': 'center', 'valign': 'vcenter',
            'border': 1, 'text_wrap': True
        })
        fmt_trend_header = workbook.add_format({
            'bold': True, 'font_size': 10, 'font_color': '#FFFFFF',
            'bg_color': '#1d2b32', 'align': 'center', 'valign': 'vcenter',
            'border': 1, 'text_wrap': True
        })
        fmt_cell = workbook.add_format({'border': 1, 'valign': 'vcenter', 'font_size': 9.5})
        fmt_num = workbook.add_format({'border': 1, 'valign': 'vcenter', 'font_size': 9.5, 'num_format': '0.00'})
        fmt_center = workbook.add_format({'border': 1, 'valign': 'vcenter', 'align': 'center', 'font_size': 9.5})
        fmt_improved = workbook.add_format({'border': 1, 'valign': 'vcenter', 'align': 'center', 'font_size': 9.5, 'bg_color': '#dcfce7', 'font_color': '#166534', 'bold': True})
        fmt_regressed = workbook.add_format({'border': 1, 'valign': 'vcenter', 'align': 'center', 'font_size': 9.5, 'bg_color': '#fee2e2', 'font_color': '#991b1b', 'bold': True})
        fmt_maintained = workbook.add_format({'border': 1, 'valign': 'vcenter', 'align': 'center', 'font_size': 9.5, 'bg_color': '#f1f5f9', 'font_color': '#334155'})

        # Gather data per cycle
        cycle_data = {}  # cycle.id -> {(emp_id, comp_id): {'rating': ..., 'gap': ..., 'status': ...}}
        all_keys = set()
        meta_info = {}   # (emp_id, comp_id) -> metadata dict

        for cyc in sorted_cycles:
            domain = self._build_domain_for_cycle(cyc)
            lines = self.env['competency.assessment.line'].sudo().search(domain)
            cycle_map = {}

            for line in lines:
                key = (line.employee_id.id, line.competency_id.id)
                all_keys.add(key)

                # Determine active rating & gap according to filter
                if self.assessment_type_filter == 'self':
                    r_val = line.self_rating
                    g_val = line.self_gap
                elif self.assessment_type_filter == 'peer':
                    r_val = line.peer_avg
                    g_val = line.peer_gap
                elif self.assessment_type_filter == 'subordinate':
                    r_val = line.subordinate_avg
                    g_val = line.subordinate_gap
                elif self.assessment_type_filter == 'supervisor':
                    r_val = line.supervisor_avg
                    g_val = line.supervisor_gap
                else:
                    r_val = line.weighted_current_level
                    g_val = line.gap

                # Determine status
                if g_val is not None:
                    if g_val > 0:
                        st = 'Underqualified'
                    elif g_val < 0:
                        st = 'Overqualified'
                    else:
                        st = 'Fit / Qualified'
                else:
                    st = 'Not Evaluated'

                cycle_map[key] = {
                    'rating': r_val if r_val is not None and r_val > 0 else 'N/A',
                    'gap': g_val if g_val is not None else 'N/A',
                    'status': st,
                }

                if key not in meta_info:
                    emp = line.employee_id
                    comp = line.competency_id
                    ou = getattr(emp, 'default_operating_unit_id', False) or getattr(emp, 'operating_unit_id', False) or getattr(emp.department_id, 'operating_unit_id', False)
                    grade = getattr(emp, 'grade_id', False)
                    gender_lbl = 'N/A'
                    if hasattr(emp, 'gender') and emp.gender:
                        gender_lbl = dict(emp._fields['gender'].selection).get(emp.gender, emp.gender.capitalize())

                    meta_info[key] = {
                        'emp_code': emp.id,
                        'emp_name': emp.name,
                        'gender': gender_lbl,
                        'ou_name': ou.name if ou else 'N/A',
                        'dept_name': emp.department_id.name if emp.department_id else 'N/A',
                        'job_name': line.job_id.name if line.job_id else 'N/A',
                        'grade_name': (getattr(grade, 'grade_name', False) or getattr(grade, 'name', False) or 'N/A') if grade else 'N/A',
                        'comp_name': comp.name,
                        'pillar': dict(comp._fields['pillar'].selection).get(comp.pillar, comp.pillar or 'N/A'),
                        'req_level': line.required_level or 'Level 2',
                    }

            cycle_data[cyc.id] = cycle_map

        # -------------------------------------------------------------
        # SHEET 1: Multi-Cycle Comparative Matrix
        # -------------------------------------------------------------
        ws1 = workbook.add_worksheet('Multi-Cycle Gap Matrix')
        start_row = self._setup_worksheet_header(ws1, workbook, 'Multi-Cycle Competency Progression & Gap Matrix')
        base_headers = [
            'Emp ID', 'Employee Name', 'Gender', 'Operating Unit', 'Department',
            'Job Position', 'Job Grade', 'Competency Name', 'Pillar', 'Required Level'
        ]

        col_c = len(base_headers)
        for h_i, h_name in enumerate(base_headers):
            ws1.write(start_row, h_i, h_name, fmt_header)
            ws1.set_column(h_i, h_i, 16 if h_i > 2 else 12)
        ws1.set_column(1, 1, 24)
        ws1.set_column(7, 7, 26)

        # Write cycle dynamic column headers
        for cyc in sorted_cycles:
            ws1.write(start_row, col_c, f"{cyc.name}\nRating", fmt_cycle_header)
            ws1.set_column(col_c, col_c, 13)
            ws1.write(start_row, col_c + 1, f"{cyc.name}\nGap", fmt_cycle_header)
            ws1.set_column(col_c + 1, col_c + 1, 13)
            ws1.write(start_row, col_c + 2, f"{cyc.name}\nStatus", fmt_cycle_header)
            ws1.set_column(col_c + 2, col_c + 2, 14)
            col_c += 3

        # Evolution trend headers
        first_cyc = sorted_cycles[0]
        last_cyc = sorted_cycles[-1]
        ws1.write(start_row, col_c, f"Rating Delta\n({last_cyc.name} vs {first_cyc.name})", fmt_trend_header)
        ws1.set_column(col_c, col_c, 15)
        ws1.write(start_row, col_c + 1, f"Gap Reduction\n(Capability Gain)", fmt_trend_header)
        ws1.set_column(col_c + 1, col_c + 1, 15)
        ws1.write(start_row, col_c + 2, "Growth Trajectory", fmt_trend_header)
        ws1.set_column(col_c + 2, col_c + 2, 18)
        ws1.set_row(start_row, 32)

        # Write rows
        row_idx = start_row + 1
        for key in sorted(all_keys, key=lambda k: (meta_info.get(k, {}).get('emp_name', ''), meta_info.get(k, {}).get('comp_name', ''))):
            meta = meta_info.get(key, {})
            if not meta:
                continue

            ws1.write(row_idx, 0, meta['emp_code'], fmt_center)
            ws1.write(row_idx, 1, meta['emp_name'], fmt_cell)
            ws1.write(row_idx, 2, meta['gender'], fmt_center)
            ws1.write(row_idx, 3, meta['ou_name'], fmt_cell)
            ws1.write(row_idx, 4, meta['dept_name'], fmt_cell)
            ws1.write(row_idx, 5, meta['job_name'], fmt_cell)
            ws1.write(row_idx, 6, meta['grade_name'], fmt_center)
            ws1.write(row_idx, 7, meta['comp_name'], fmt_cell)
            ws1.write(row_idx, 8, meta['pillar'], fmt_center)
            ws1.write(row_idx, 9, meta['req_level'], fmt_center)

            curr_c = len(base_headers)
            first_rating, first_gap = None, None
            last_rating, last_gap = None, None

            for i, cyc in enumerate(sorted_cycles):
                c_vals = cycle_data[cyc.id].get(key, {'rating': 'N/A', 'gap': 'N/A', 'status': 'Not Evaluated'})
                r = c_vals['rating']
                g = c_vals['gap']
                st = c_vals['status']

                if isinstance(r, (int, float)):
                    ws1.write(row_idx, curr_c, r, fmt_num)
                    if first_rating is None:
                        first_rating = r
                    last_rating = r
                else:
                    ws1.write(row_idx, curr_c, r, fmt_center)

                if isinstance(g, (int, float)):
                    ws1.write(row_idx, curr_c + 1, g, fmt_num)
                    if first_gap is None:
                        first_gap = g
                    last_gap = g
                else:
                    ws1.write(row_idx, curr_c + 1, g, fmt_center)

                ws1.write(row_idx, curr_c + 2, st, fmt_center)
                curr_c += 3

            # Calculate Evolution Metrics
            if isinstance(first_rating, (int, float)) and isinstance(last_rating, (int, float)) and isinstance(first_gap, (int, float)) and isinstance(last_gap, (int, float)):
                rating_delta = round(last_rating - first_rating, 2)
                gap_reduction = round(first_gap - last_gap, 2)

                ws1.write(row_idx, curr_c, rating_delta, fmt_num)
                ws1.write(row_idx, curr_c + 1, gap_reduction, fmt_num)

                if first_gap > 0 and last_gap <= 0:
                    traj_str = "Gap Closed / Qualified"
                    traj_fmt = fmt_improved
                elif gap_reduction > 0.3:
                    traj_str = "Significant Progress"
                    traj_fmt = fmt_improved
                elif gap_reduction > 0:
                    traj_str = "Improved"
                    traj_fmt = fmt_improved
                elif gap_reduction == 0:
                    traj_str = "Maintained Fit" if last_gap <= 0 else "Unchanged Gap"
                    traj_fmt = fmt_maintained
                else:
                    traj_str = "Regressed / Gap Widened"
                    traj_fmt = fmt_regressed

                ws1.write(row_idx, curr_c + 2, traj_str, traj_fmt)
            else:
                ws1.write(row_idx, curr_c, 'N/A', fmt_center)
                ws1.write(row_idx, curr_c + 1, 'N/A', fmt_center)
                ws1.write(row_idx, curr_c + 2, 'N/A (Partial Cycle)', fmt_center)

            ws1.set_row(row_idx, 19)
            row_idx += 1

        # -------------------------------------------------------------
        # SHEET 2: Cycle Comparison Summary
        # -------------------------------------------------------------
        ws2 = workbook.add_worksheet('Cycle Trend Summary')
        start_row2 = self._setup_worksheet_header(ws2, workbook, 'Assessment Cycles Capability & Gap Trend Summary')

        sum_headers = ['Assessment Cycle', 'Total Evaluated Lines', 'Fit / Qualified %', 'Underqualified %', 'Overqualified %', 'Average Gap', 'Average Rating']
        for s_i, s_h in enumerate(sum_headers):
            ws2.write(start_row2, s_i, s_h, fmt_header)
            ws2.set_column(s_i, s_i, 20)
        ws2.set_row(start_row2, 26)

        for s_idx, cyc in enumerate(sorted_cycles, start=start_row2 + 1):
            cmap = cycle_data[cyc.id]
            eval_items = [v for v in cmap.values() if isinstance(v['gap'], (int, float))]
            total_n = len(eval_items)

            if total_n > 0:
                fit_cnt = sum(1 for v in eval_items if v['gap'] == 0)
                under_cnt = sum(1 for v in eval_items if v['gap'] > 0)
                over_cnt = sum(1 for v in eval_items if v['gap'] < 0)
                avg_g = round(sum(v['gap'] for v in eval_items) / total_n, 2)
                ratings = [v['rating'] for v in eval_items if isinstance(v['rating'], (int, float))]
                avg_r = round(sum(ratings) / len(ratings), 2) if ratings else 0.0

                pct_fit = f"{round((fit_cnt / total_n) * 100, 1)}%"
                pct_under = f"{round((under_cnt / total_n) * 100, 1)}%"
                pct_over = f"{round((over_cnt / total_n) * 100, 1)}%"
            else:
                pct_fit, pct_under, pct_over, avg_g, avg_r = '0.0%', '0.0%', '0.0%', 0.0, 0.0

            ws2.write(s_idx, 0, cyc.name, fmt_cell)
            ws2.write(s_idx, 1, total_n, fmt_center)
            ws2.write(s_idx, 2, pct_fit, fmt_center)
            ws2.write(s_idx, 3, pct_under, fmt_center)
            ws2.write(s_idx, 4, pct_over, fmt_center)
            ws2.write(s_idx, 5, avg_g, fmt_num)
            ws2.write(s_idx, 6, avg_r, fmt_num)
            ws2.set_row(s_idx, 22)

        workbook.close()
        xlsx_bytes = output.getvalue()
        output.close()

        attachment = self.env['ir.attachment'].create({
            'name': f'Multi_Cycle_Gap_Analysis_{first_cyc.name}_to_{last_cyc.name}.xlsx',
            'datas': base64.b64encode(xlsx_bytes),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def action_view_filtered_lines(self):
        """Action: Open competency assessment lines across all selected cycles."""
        self.ensure_one()
        user = self.env.user
        if not (self.env.is_admin() or self.env.su or user.has_group('competency_management.group_competency_officer') or user.has_group('competency_management.group_competency_admin')):
            raise AccessError(_("Access Denied: Only HR Officers and Competency Administrators can access reporting."))

        domain = [('cycle_id', 'in', self.cycle_ids.ids), ('is_primary_reporting_line', '=', True)]
        if self.department_ids:
            domain.append(('department_id', 'in', self.department_ids.ids))
        if self.operating_unit_ids:
            domain.append('|')
            domain.append(('employee_id.default_operating_unit_id', 'in', self.operating_unit_ids.ids))
            domain.append(('department_id.operating_unit_id', 'in', self.operating_unit_ids.ids))
        if self.job_ids:
            domain.append(('employee_id.job_id', 'in', self.job_ids.ids))
        if self.grade_ids:
            domain.append(('employee_id.grade_id', 'in', self.grade_ids.ids))
        if self.employee_ids:
            domain.append(('employee_id', 'in', self.employee_ids.ids))
        if self.competency_ids:
            domain.append(('competency_id', 'in', self.competency_ids.ids))
        if self.pillar != 'all':
            domain.append(('pillar', '=', self.pillar))
        if self.gender_filter != 'all':
            domain.append(('employee_id.gender', '=', self.gender_filter))

        if self.assessment_type_filter == 'self':
            domain.append(('self_rating', '>', 0))
        elif self.assessment_type_filter == 'peer':
            domain.append(('peer_avg', '>', 0))
        elif self.assessment_type_filter == 'subordinate':
            domain.append(('subordinate_avg', '>', 0))
        elif self.assessment_type_filter == 'supervisor':
            domain.append(('supervisor_avg', '>', 0))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Multi-Cycle Competency Comparison Lines'),
            'res_model': 'competency.assessment.line',
            'view_mode': 'list,pivot,graph,form',
            'views': [
                (self.env.ref('competency_management.view_competency_assessment_line_report_list').id, 'list'),
                (self.env.ref('competency_management.view_competency_assessment_line_report_pivot').id, 'pivot'),
                (self.env.ref('competency_management.view_competency_assessment_line_report_graph').id, 'graph'),
                (self.env.ref('competency_management.view_competency_assessment_line_report_form').id, 'form'),
            ],
            'domain': domain,
            'context': {
                'search_default_filter_primary_reporting': 1,
                'assessment_type_filter': self.assessment_type_filter or 'all',
                'group_by': ['employee_id', 'competency_id'],
                'create': False,
                'edit': False,
                'delete': False,
            },
            'target': 'current',
        }
