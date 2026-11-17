# -*- coding: utf-8 -*-
import io
import os
import base64
from datetime import datetime
from odoo import models, fields, api, _
from odoo.exceptions import UserError

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class SuccessionReportWizard(models.TransientModel):
    """Excel Report Generation Wizard for PPDD Succession Management."""
    _name = 'succession.report.wizard'
    _description = 'Succession Management Excel Report Generator'

    report_type = fields.Selection([
        ('consolidated', 'All-in-One Succession Report (4 Tabs: Positions, Assessments, Readiness, Selected Pool)'),
        ('job_position', '1. By Job Position Report'),
        ('assessment', '2. Candidate Assessment Report (Scores, PMS & Results)'),
        ('readiness', '3. Candidate Readiness Report (Readiness Levels & Grade Gap)'),
        ('selected_pool', '4. Selected Report (SPMC Approved Talent Pool)'),
    ], string='Report Type', default='consolidated', required=True)

    department_id = fields.Many2one(
        'hr.department', string='Department',
        help='Filter by specific department (leave empty for all departments).')

    critical_position_id = fields.Many2one(
        'succession.critical.position', string='Critical Position',
        domain="[('active', '=', True), ('state', 'in', ['approved', 'placed'])]",
        help='Filter by a specific critical job position.')

    risk_level_id = fields.Many2one(
        'succession.risk.level', string='Risk Level',
        help='Filter positions by risk level (e.g., High, Medium, Low).')

    readiness_level_id = fields.Many2one(
        'succession.readiness.level', string='Readiness Level',
        help='Filter candidates by readiness level (e.g., Ready Now, Ready in 1-2 Years).')

    include_draft_positions = fields.Boolean(
        string='Include Draft Positions', default=False)

    file_data = fields.Binary(string='Generated File', readonly=True)
    file_name = fields.Char(string='File Name', readonly=True)

    @api.onchange('department_id')
    def _onchange_department_id(self):
        """Dynamically filter Critical Positions when Department is selected."""
        domain = [('active', '=', True), ('state', 'in', ['approved', 'placed'])]
        if self.department_id:
            # If current critical position doesn't belong to this department, clear it
            if self.critical_position_id and self.critical_position_id.department_id != self.department_id:
                self.critical_position_id = False
            domain.append(('department_id', '=', self.department_id.id))
        return {'domain': {'critical_position_id': domain}}

    def web_read(self, specification):
        return super(SuccessionReportWizard, self.sudo()).web_read(specification)

    def read(self, fields=None, load='_classic_read'):
        return super(SuccessionReportWizard, self.sudo()).read(fields=fields, load=load)

    def _get_logo_path(self):
        """Locate Bunna Bank official logo on disk."""
        candidate_paths = [
            os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'custom_recruitment', 'static', 'src', 'img', 'bunna_bank_official_logo.png')),
            os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'competency_management', 'static', 'src', 'img', 'bunna_bank_official_logo.png')),
            '/mnt/extra-addons/custom_recruitment/static/src/img/bunna_bank_official_logo.png',
            '/mnt/extra-addons/competency_management/static/src/img/bunna_bank_official_logo.png',
        ]
        for path in candidate_paths:
            if os.path.exists(path):
                return path
        return False

    def _setup_worksheet_print(self, worksheet, title):
        """Configure page margins, header/footer, and print scaling."""
        worksheet.set_landscape()
        worksheet.set_paper(9)  # A4
        worksheet.fit_to_pages(1, 0)  # Fit all columns to 1 page wide
        worksheet.set_margins(left=0.4, right=0.4, top=0.6, bottom=0.6)
        worksheet.set_header('&C&12&"Arial,Bold"BUNNA BANK S.C.&R&D')
        worksheet.set_footer('&LConfidential - PPDD Succession Management&RPage &P of &N')

    def _write_common_header(self, workbook, worksheet, report_title, max_col_letter='L'):
        """Writes corporate Bunna Bank header banner and export metadata."""
        logo_path = self._get_logo_path()
        if logo_path:
            worksheet.insert_image('A1', logo_path, {
                'x_scale': 0.26,
                'y_scale': 0.26,
                'x_offset': 6,
                'y_offset': 4,
            })

        title_fmt = workbook.add_format({
            'bold': True, 'font_name': 'Arial', 'font_size': 14,
            'font_color': '#541718', 'valign': 'vcenter'
        })
        subtitle_fmt = workbook.add_format({
            'bold': True, 'font_name': 'Arial', 'font_size': 10,
            'font_color': '#1F4E79', 'valign': 'vcenter'
        })
        meta_fmt = workbook.add_format({
            'italic': True, 'font_name': 'Arial', 'font_size': 9,
            'font_color': '#555555', 'valign': 'vcenter'
        })

        worksheet.set_row(0, 22)
        worksheet.set_row(1, 18)
        worksheet.set_row(2, 16)
        worksheet.set_row(3, 8)

        # Write text starting at column C
        worksheet.write('C1', 'BUNNA BANK S.C. — PEOPLE & PERFORMANCE DEVELOPMENT DIRECTORATE (PPDD)', title_fmt)
        worksheet.write('C2', report_title, subtitle_fmt)

        dept_str = self.department_id.name if self.department_id else 'All Departments'
        pos_str = self.critical_position_id.job_id.name if self.critical_position_id else 'All Critical Positions'
        user_name = self.env.user.name or 'PPDD'
        now_str = fields.Datetime.now().strftime('%d-%b-%Y %H:%M')
        meta_line = f"Scope: {dept_str} | Position Filter: {pos_str} | Exported By: {user_name} on {now_str}"
        worksheet.write('C3', meta_line, meta_fmt)

        # Header row will be at row 4 (0-indexed)
        worksheet.repeat_rows(4)
        return 4

    def action_export_xlsx(self):
        """Primary action: build and return the requested Excel file."""
        if not xlsxwriter:
            raise UserError(_("The Python library 'xlsxwriter' is required. Please install it on the server."))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        # Formats dictionary
        fmt = {
            'th': workbook.add_format({
                'bold': True, 'font_name': 'Arial', 'font_size': 10,
                'font_color': '#FFFFFF', 'bg_color': '#541718',
                'align': 'center', 'valign': 'vcenter', 'border': 1, 'text_wrap': True
            }),
            'left': workbook.add_format({
                'font_name': 'Arial', 'font_size': 9,
                'align': 'left', 'valign': 'vcenter', 'border': 1
            }),
            'left_bold': workbook.add_format({
                'bold': True, 'font_name': 'Arial', 'font_size': 9,
                'align': 'left', 'valign': 'vcenter', 'border': 1
            }),
            'center': workbook.add_format({
                'font_name': 'Arial', 'font_size': 9,
                'align': 'center', 'valign': 'vcenter', 'border': 1
            }),
            'num': workbook.add_format({
                'font_name': 'Arial', 'font_size': 9,
                'align': 'center', 'valign': 'vcenter', 'border': 1, 'num_format': '#,##0'
            }),
            'float': workbook.add_format({
                'font_name': 'Arial', 'font_size': 9,
                'align': 'center', 'valign': 'vcenter', 'border': 1, 'num_format': '0.0'
            }),
            'pct': workbook.add_format({
                'font_name': 'Arial', 'font_size': 9,
                'align': 'center', 'valign': 'vcenter', 'border': 1, 'num_format': '0.0%'
            }),
            'date': workbook.add_format({
                'font_name': 'Arial', 'font_size': 9,
                'align': 'center', 'valign': 'vcenter', 'border': 1, 'num_format': 'yyyy-mm-dd'
            }),
            'badge_green': workbook.add_format({
                'bold': True, 'font_name': 'Arial', 'font_size': 9,
                'align': 'center', 'valign': 'vcenter', 'border': 1,
                'bg_color': '#E2F0D9', 'font_color': '#385723'
            }),
            'badge_blue': workbook.add_format({
                'bold': True, 'font_name': 'Arial', 'font_size': 9,
                'align': 'center', 'valign': 'vcenter', 'border': 1,
                'bg_color': '#D9E1F2', 'font_color': '#1F4E79'
            }),
            'badge_amber': workbook.add_format({
                'bold': True, 'font_name': 'Arial', 'font_size': 9,
                'align': 'center', 'valign': 'vcenter', 'border': 1,
                'bg_color': '#FFF2CC', 'font_color': '#7F6000'
            }),
            'badge_red': workbook.add_format({
                'bold': True, 'font_name': 'Arial', 'font_size': 9,
                'align': 'center', 'valign': 'vcenter', 'border': 1,
                'bg_color': '#FCE4D6', 'font_color': '#C00000'
            }),
            'summary_lbl': workbook.add_format({
                'bold': True, 'font_name': 'Arial', 'font_size': 9,
                'align': 'right', 'valign': 'vcenter',
                'bg_color': '#F2F2F2', 'top': 1, 'bottom': 6
            }),
            'summary_num': workbook.add_format({
                'bold': True, 'font_name': 'Arial', 'font_size': 9,
                'align': 'center', 'valign': 'vcenter',
                'bg_color': '#F2F2F2', 'top': 1, 'bottom': 6, 'num_format': '#,##0'
            }),
            'summary_float': workbook.add_format({
                'bold': True, 'font_name': 'Arial', 'font_size': 9,
                'align': 'center', 'valign': 'vcenter',
                'bg_color': '#F2F2F2', 'top': 1, 'bottom': 6, 'num_format': '0.0'
            }),
            'summary_pct': workbook.add_format({
                'bold': True, 'font_name': 'Arial', 'font_size': 9,
                'align': 'center', 'valign': 'vcenter',
                'bg_color': '#F2F2F2', 'top': 1, 'bottom': 6, 'num_format': '0.0%'
            }),
        }

        # Generate selected sheets
        if self.report_type in ('consolidated', 'job_position'):
            self._render_job_position_sheet(workbook, fmt)

        if self.report_type in ('consolidated', 'assessment'):
            self._render_assessment_sheet(workbook, fmt)

        if self.report_type in ('consolidated', 'readiness'):
            self._render_readiness_sheet(workbook, fmt)

        if self.report_type in ('consolidated', 'selected_pool'):
            self._render_selected_pool_sheet(workbook, fmt)

        workbook.close()
        output.seek(0)
        file_bytes = output.getvalue()

        # Build clean filename
        now_date = fields.Date.today().strftime('%Y_%m_%d')
        if self.report_type == 'job_position':
            filename = f"Succession_Job_Positions_Report_{now_date}.xlsx"
        elif self.report_type == 'assessment':
            filename = f"Succession_Assessment_Report_{now_date}.xlsx"
        elif self.report_type == 'readiness':
            filename = f"Succession_Readiness_Report_{now_date}.xlsx"
        elif self.report_type == 'selected_pool':
            filename = f"Succession_Selected_Talent_Pool_Report_{now_date}.xlsx"
        else:
            filename = f"Succession_Management_Consolidated_Report_{now_date}.xlsx"

        attachment = self.env['ir.attachment'].sudo().create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(file_bytes),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    # =========================================================================
    # TAB 1: BY JOB POSITION REPORT
    # =========================================================================
    def _render_job_position_sheet(self, workbook, fmt):
        worksheet = workbook.add_worksheet('Job Positions')
        self._setup_worksheet_print(worksheet, 'Job Positions Report')
        header_row = self._write_common_header(workbook, worksheet, 'Critical Positions Succession Report')

        headers = [
            ('No.', 5),
            ('Job Position', 30),
            ('Department', 24),
            ('Work Unit', 20),
            ('Current Incumbent', 24),
            ('Criticality Reason', 24),
            ('Risk Level', 14),
            ('Target Timeframe', 18),
            ('Ready Now', 12),
            ('Ready 1-2 Yrs', 14),
            ('Ready 3-5 Yrs', 14),
            ('Total Bench', 12),
            ('Bench Health', 20),
            ('Position Status', 18),
        ]

        # Set column widths & write header
        worksheet.set_row(header_row, 26)
        for col_idx, (col_name, col_width) in enumerate(headers):
            worksheet.set_column(col_idx, col_idx, col_width)
            worksheet.write(header_row, col_idx, col_name, fmt['th'])

        # Data query: Active approved/placed positions
        domain = [('active', '=', True)]
        if hasattr(self, 'include_draft_positions') and not self.include_draft_positions:
            domain.append(('state', 'in', ['approved', 'placed']))
        elif not hasattr(self, 'include_draft_positions'):
            domain.append(('state', 'in', ['approved', 'placed']))
        if self.department_id:
            domain.append(('department_id', '=', self.department_id.id))
        if self.critical_position_id:
            domain.append(('id', '=', self.critical_position_id.id))
        if self.risk_level_id:
            domain.append(('risk_level_id', '=', self.risk_level_id.id))

        positions = self.env['succession.critical.position'].sudo().search(domain, order='department_id, job_id')

        row_idx = header_row + 1
        bench_health_dict = dict(positions._fields['bench_health'].selection) if 'bench_health' in positions._fields else {}
        state_dict = dict(positions._fields['state'].selection) if 'state' in positions._fields else {}

        for i, pos in enumerate(positions, start=1):
            worksheet.set_row(row_idx, 20)
            worksheet.write(row_idx, 0, i, fmt['center'])
            worksheet.write(row_idx, 1, pos.job_id.name or '', fmt['left_bold'])
            worksheet.write(row_idx, 2, pos.department_id.name or '', fmt['left'])
            worksheet.write(row_idx, 3, pos.work_unit_id.name or '', fmt['left'])
            worksheet.write(row_idx, 4, pos.current_incumbent_id.name or 'Vacant', fmt['left'])
            worksheet.write(row_idx, 5, pos.criticality_category_id.name or '', fmt['left'])
            worksheet.write(row_idx, 6, pos.risk_level_id.name or '', fmt['center'])
            worksheet.write(row_idx, 7, pos.vacancy_timeframe_id.name or '', fmt['center'])

            worksheet.write(row_idx, 8, pos.ready_now_count or 0, fmt['num'])
            worksheet.write(row_idx, 9, pos.ready_1_2_yrs_count or 0, fmt['num'])
            worksheet.write(row_idx, 10, pos.ready_3_5_yrs_count or 0, fmt['num'])
            worksheet.write(row_idx, 11, pos.total_bench_count or 0, fmt['num'])

            # Bench health format
            health_code = pos.bench_health or ''
            health_text = bench_health_dict.get(health_code, health_code)
            if health_code == 'strong':
                health_fmt = fmt['badge_green']
            elif health_code == 'adequate':
                health_fmt = fmt['badge_blue']
            elif health_code == 'at_risk':
                health_fmt = fmt['badge_amber']
            elif health_code == 'critical':
                health_fmt = fmt['badge_red']
            else:
                health_fmt = fmt['center']
            worksheet.write(row_idx, 12, health_text, health_fmt)

            worksheet.write(row_idx, 13, state_dict.get(pos.state, pos.state or ''), fmt['center'])
            row_idx += 1

        # Summary Row
        if len(positions) > 0:
            worksheet.set_row(row_idx, 22)
            worksheet.merge_range(row_idx, 0, row_idx, 7, f'Total Positions: {len(positions)}', fmt['summary_lbl'])
            start_num = header_row + 2
            end_num = row_idx
            worksheet.write_formula(row_idx, 8, f'=SUM(I{start_num}:I{end_num})', fmt['summary_num'])
            worksheet.write_formula(row_idx, 9, f'=SUM(J{start_num}:J{end_num})', fmt['summary_num'])
            worksheet.write_formula(row_idx, 10, f'=SUM(K{start_num}:K{end_num})', fmt['summary_num'])
            worksheet.write_formula(row_idx, 11, f'=SUM(L{start_num}:L{end_num})', fmt['summary_num'])
            worksheet.write(row_idx, 12, '', fmt['summary_lbl'])
            worksheet.write(row_idx, 13, '', fmt['summary_lbl'])

    # =========================================================================
    # TAB 2: CANDIDATE ASSESSMENT REPORT
    # =========================================================================
    def _render_assessment_sheet(self, workbook, fmt):
        worksheet = workbook.add_worksheet('Assessments')
        self._setup_worksheet_print(worksheet, 'Candidate Assessment Report')
        header_row = self._write_common_header(workbook, worksheet, 'Candidate Evaluation Scores & Assessment Results')

        headers = [
            ('No.', 5),
            ('Target Critical Position', 28),
            ('Candidate Name', 24),
            ('Current Position', 24),
            ('Department', 22),
            ('Latest PMS Score', 16),
            ('Competency Match', 18),
            ('Assessment Score', 16),
            ('Result', 14),
            ('Evaluation Status', 16),
            ('Readiness Level', 22),
            ('State', 16),
        ]

        worksheet.set_row(header_row, 26)
        for col_idx, (col_name, col_width) in enumerate(headers):
            worksheet.set_column(col_idx, col_idx, col_width)
            worksheet.write(header_row, col_idx, col_name, fmt['th'])

        domain = [
            ('critical_position_id.active', '=', True),
            ('critical_position_id.state', 'in', ['approved', 'placed']),
        ]
        if self.department_id:
            domain.append(('department_id', '=', self.department_id.id))
        if self.critical_position_id:
            domain.append(('critical_position_id', '=', self.critical_position_id.id))
        if self.readiness_level_id:
            domain.append(('readiness_level_id', '=', self.readiness_level_id.id))

        candidates = self.env['succession.candidate'].sudo().search(domain, order='critical_position_id, final_assessment_score desc')

        row_idx = header_row + 1
        res_dict = dict(candidates._fields['assessment_result'].selection) if 'assessment_result' in candidates._fields else {}
        stat_dict = dict(candidates._fields['assessment_status'].selection) if 'assessment_status' in candidates._fields else {}
        state_dict = dict(candidates._fields['state'].selection) if 'state' in candidates._fields else {}

        for i, c in enumerate(candidates, start=1):
            worksheet.set_row(row_idx, 20)
            worksheet.write(row_idx, 0, i, fmt['center'])
            worksheet.write(row_idx, 1, c.critical_position_id.job_id.name or '', fmt['left_bold'])
            worksheet.write(row_idx, 2, c.employee_id.name or '', fmt['left'])
            worksheet.write(row_idx, 3, c.job_id.name or '', fmt['left'])
            worksheet.write(row_idx, 4, c.department_id.name or '', fmt['left'])
            worksheet.write(row_idx, 5, c.latest_pms_score or 0.0, fmt['float'])

            match_pct = (c.competency_match_percent or 0.0) / 100.0
            worksheet.write(row_idx, 6, match_pct, fmt['pct'])

            worksheet.write(row_idx, 7, c.final_assessment_score or 0.0, fmt['float'])

            # Assessment Result Badge
            res_val = c.assessment_result or ''
            res_label = res_dict.get(res_val, res_val.capitalize() if res_val else 'Pending')
            if res_val == 'pass':
                res_fmt = fmt['badge_green']
            elif res_val == 'fail':
                res_fmt = fmt['badge_red']
            elif res_val == 'waived':
                res_fmt = fmt['badge_blue']
            else:
                res_fmt = fmt['center']
            worksheet.write(row_idx, 8, res_label, res_fmt)

            worksheet.write(row_idx, 9, stat_dict.get(c.assessment_status, c.assessment_status or ''), fmt['center'])
            worksheet.write(row_idx, 10, c.readiness_level_id.name or '', fmt['center'])
            worksheet.write(row_idx, 11, state_dict.get(c.state, c.state or ''), fmt['center'])
            row_idx += 1

        # Summary Row
        if len(candidates) > 0:
            worksheet.set_row(row_idx, 22)
            worksheet.merge_range(row_idx, 0, row_idx, 4, f'Total Candidates Evaluated: {len(candidates)}', fmt['summary_lbl'])
            start_num = header_row + 2
            end_num = row_idx
            worksheet.write_formula(row_idx, 5, f'=AVERAGE(F{start_num}:F{end_num})', fmt['summary_float'])
            worksheet.write_formula(row_idx, 6, f'=AVERAGE(G{start_num}:G{end_num})', fmt['summary_pct'])
            worksheet.write_formula(row_idx, 7, f'=AVERAGE(H{start_num}:H{end_num})', fmt['summary_float'])
            worksheet.write_formula(row_idx, 8, f'=COUNTIF(I{start_num}:I{end_num}, "Pass")', fmt['summary_num'])
            worksheet.write(row_idx, 9, '', fmt['summary_lbl'])
            worksheet.write(row_idx, 10, '', fmt['summary_lbl'])
            worksheet.write(row_idx, 11, '', fmt['summary_lbl'])

    # =========================================================================
    # TAB 3: CANDIDATE READINESS REPORT
    # =========================================================================
    def _render_readiness_sheet(self, workbook, fmt):
        worksheet = workbook.add_worksheet('Readiness')
        self._setup_worksheet_print(worksheet, 'Candidate Readiness Report')
        header_row = self._write_common_header(workbook, worksheet, 'Talent Bench Readiness & Development Timeline')

        headers = [
            ('No.', 5),
            ('Target Critical Position', 28),
            ('Candidate Name', 24),
            ('Current Position', 24),
            ('Department', 22),
            ('Current Grade', 14),
            ('Target Grade', 14),
            ('Grade Gap', 12),
            ('Readiness Level', 22),
            ('Target Readiness Date', 20),
            ('Active IDP', 14),
            ('IDP Progress', 14),
            ('Pipeline State', 16),
        ]

        worksheet.set_row(header_row, 26)
        for col_idx, (col_name, col_width) in enumerate(headers):
            worksheet.set_column(col_idx, col_idx, col_width)
            worksheet.write(header_row, col_idx, col_name, fmt['th'])

        domain = [
            ('critical_position_id.active', '=', True),
            ('critical_position_id.state', 'in', ['approved', 'placed']),
            ('readiness_level_id', '!=', False),
        ]
        if self.department_id:
            domain.append(('department_id', '=', self.department_id.id))
        if self.critical_position_id:
            domain.append(('critical_position_id', '=', self.critical_position_id.id))
        if self.readiness_level_id:
            domain.append(('readiness_level_id', '=', self.readiness_level_id.id))

        candidates = self.env['succession.candidate'].sudo().search(domain, order='critical_position_id, readiness_level_id')

        row_idx = header_row + 1
        state_dict = dict(candidates._fields['state'].selection) if 'state' in candidates._fields else {}

        for i, c in enumerate(candidates, start=1):
            worksheet.set_row(row_idx, 20)
            worksheet.write(row_idx, 0, i, fmt['center'])
            worksheet.write(row_idx, 1, c.critical_position_id.job_id.name or '', fmt['left_bold'])
            worksheet.write(row_idx, 2, c.employee_id.name or '', fmt['left'])
            worksheet.write(row_idx, 3, c.job_id.name or '', fmt['left'])
            worksheet.write(row_idx, 4, c.department_id.name or '', fmt['left'])

            worksheet.write(row_idx, 5, c.current_grade_display or '', fmt['center'])
            worksheet.write(row_idx, 6, c.target_grade_display or '', fmt['center'])
            worksheet.write(row_idx, 7, c.grade_gap or 0, fmt['num'])

            # Readiness level badge
            lvl_name = c.readiness_level_id.name or ''
            if c.readiness_level_id.is_ready_for_deployment or 'Now' in lvl_name:
                lvl_fmt = fmt['badge_green']
            elif '1-2' in lvl_name:
                lvl_fmt = fmt['badge_blue']
            elif '3-5' in lvl_name:
                lvl_fmt = fmt['badge_amber']
            else:
                lvl_fmt = fmt['center']
            worksheet.write(row_idx, 8, lvl_name, lvl_fmt)

            target_date_str = c.target_readiness_display or (c.target_readiness_date.strftime('%Y-%m-%d') if c.target_readiness_date else '')
            worksheet.write(row_idx, 9, target_date_str, fmt['center'])

            worksheet.write(row_idx, 10, 'Yes' if c.active_idp_id else 'No', fmt['center'])
            idp_progress_pct = (c.active_idp_progress or 0) / 100.0
            worksheet.write(row_idx, 11, idp_progress_pct, fmt['pct'])

            worksheet.write(row_idx, 12, state_dict.get(c.state, c.state or ''), fmt['center'])
            row_idx += 1

        # Summary Row
        if len(candidates) > 0:
            worksheet.set_row(row_idx, 22)
            worksheet.merge_range(row_idx, 0, row_idx, 6, f'Total Bench Successors: {len(candidates)}', fmt['summary_lbl'])
            start_num = header_row + 2
            end_num = row_idx
            worksheet.write_formula(row_idx, 7, f'=AVERAGE(H{start_num}:H{end_num})', fmt['summary_float'])
            worksheet.write(row_idx, 8, '', fmt['summary_lbl'])
            worksheet.write(row_idx, 9, '', fmt['summary_lbl'])
            worksheet.write(row_idx, 10, '', fmt['summary_lbl'])
            worksheet.write_formula(row_idx, 11, f'=AVERAGE(L{start_num}:L{end_num})', fmt['summary_pct'])
            worksheet.write(row_idx, 12, '', fmt['summary_lbl'])

    # =========================================================================
    # TAB 4: SELECTED REPORT (APPROVED TALENT POOL)
    # =========================================================================
    def _render_selected_pool_sheet(self, workbook, fmt):
        worksheet = workbook.add_worksheet('Selected Pool')
        self._setup_worksheet_print(worksheet, 'Selected Talent Pool Report')
        header_row = self._write_common_header(workbook, worksheet, 'Selected Successors (SPMC Approved Talent Pool)')

        headers = [
            ('No.', 5),
            ('Target Critical Position', 28),
            ('Approved Candidate Name', 24),
            ('Current Job Position', 24),
            ('Department', 22),
            ('Assessment Score', 16),
            ('Readiness Level', 22),
            ('Target Readiness Date', 20),
            ('IDP Progress', 14),
            ('SPMC Approved Date', 18),
            ('Approved By', 20),
            ('Deployment Status', 20),
        ]

        worksheet.set_row(header_row, 26)
        for col_idx, (col_name, col_width) in enumerate(headers):
            worksheet.set_column(col_idx, col_idx, col_width)
            worksheet.write(header_row, col_idx, col_name, fmt['th'])

        domain = [
            ('critical_position_id.active', '=', True),
            ('critical_position_id.state', 'in', ['approved', 'placed']),
            ('state', 'in', ['approved', 'deployment_lm', 'deployment_po', 'deployment_ppdd', 'deployment_spmc', 'placed']),
        ]
        if self.department_id:
            domain.append(('department_id', '=', self.department_id.id))
        if self.critical_position_id:
            domain.append(('critical_position_id', '=', self.critical_position_id.id))
        if self.readiness_level_id:
            domain.append(('readiness_level_id', '=', self.readiness_level_id.id))

        candidates = self.env['succession.candidate'].sudo().search(domain, order='critical_position_id, approval_date desc')

        row_idx = header_row + 1
        state_dict = dict(candidates._fields['state'].selection) if 'state' in candidates._fields else {}

        for i, c in enumerate(candidates, start=1):
            worksheet.set_row(row_idx, 20)
            worksheet.write(row_idx, 0, i, fmt['center'])
            worksheet.write(row_idx, 1, c.critical_position_id.job_id.name or '', fmt['left_bold'])
            worksheet.write(row_idx, 2, c.employee_id.name or '', fmt['left'])
            worksheet.write(row_idx, 3, c.job_id.name or '', fmt['left'])
            worksheet.write(row_idx, 4, c.department_id.name or '', fmt['left'])
            worksheet.write(row_idx, 5, c.final_assessment_score or 0.0, fmt['float'])

            lvl_name = c.readiness_level_id.name or ''
            if c.readiness_level_id.is_ready_for_deployment or 'Now' in lvl_name:
                lvl_fmt = fmt['badge_green']
            else:
                lvl_fmt = fmt['center']
            worksheet.write(row_idx, 6, lvl_name, lvl_fmt)

            target_date_str = c.target_readiness_display or (c.target_readiness_date.strftime('%Y-%m-%d') if c.target_readiness_date else '')
            worksheet.write(row_idx, 7, target_date_str, fmt['center'])

            idp_progress_pct = (c.active_idp_progress or 0) / 100.0
            worksheet.write(row_idx, 8, idp_progress_pct, fmt['pct'])

            appr_date_str = c.approval_date.strftime('%Y-%m-%d') if c.approval_date else ''
            worksheet.write(row_idx, 9, appr_date_str, fmt['center'])
            worksheet.write(row_idx, 10, c.approved_by_id.name or '', fmt['left'])

            dep_status = state_dict.get(c.state, c.state or '')
            if c.state == 'placed':
                dep_fmt = fmt['badge_blue']
            elif c.state == 'approved':
                dep_fmt = fmt['badge_green']
            else:
                dep_fmt = fmt['badge_amber']
            worksheet.write(row_idx, 11, dep_status, dep_fmt)
            row_idx += 1

        # Summary Row
        if len(candidates) > 0:
            worksheet.set_row(row_idx, 22)
            worksheet.merge_range(row_idx, 0, row_idx, 4, f'Total Selected Successors: {len(candidates)}', fmt['summary_lbl'])
            start_num = header_row + 2
            end_num = row_idx
            worksheet.write_formula(row_idx, 5, f'=AVERAGE(F{start_num}:F{end_num})', fmt['summary_float'])
            worksheet.write(row_idx, 6, '', fmt['summary_lbl'])
            worksheet.write(row_idx, 7, '', fmt['summary_lbl'])
            worksheet.write_formula(row_idx, 8, f'=AVERAGE(I{start_num}:I{end_num})', fmt['summary_pct'])
            worksheet.write(row_idx, 9, '', fmt['summary_lbl'])
            worksheet.write(row_idx, 10, '', fmt['summary_lbl'])
            worksheet.write(row_idx, 11, '', fmt['summary_lbl'])
