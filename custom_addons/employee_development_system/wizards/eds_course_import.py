# -*- coding: utf-8 -*-
import base64
import csv
import io
from markupsafe import Markup, escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

try:
    import openpyxl
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.worksheet.datavalidation import DataValidation
except ImportError:
    openpyxl = None
    Workbook = None
    DataValidation = None


class EdsCourseImport(models.TransientModel):
    _name = 'eds.course.import'
    _description = 'Course Catalog Bulk Ingestion Wizard'

    file = fields.Binary(string='Courses Spreadsheet (.xlsx or .csv)', required=True)
    filename = fields.Char(string='File Name')
    default_status = fields.Selection([
        ('active', 'Active (Available for Planning)'),
        ('draft', 'Draft (Pending Review)'),
    ], string='Initial Status for New Courses', default='active', required=True)
    update_existing = fields.Boolean(
        string='Update Existing Courses',
        default=True,
        help='If checked, existing courses matching by Course Code or Course Name will be updated with values from the spreadsheet.')
    result_log = fields.Html(string='Import Summary', readonly=True)

    # ══════════════════════════════════════════════════════════════════
    # Template Generation
    # ══════════════════════════════════════════════════════════════════

    def action_download_template(self, *args, **kwargs):
        """Generate and download the official Bunna Course Catalog Excel template (.xlsx)."""
        if Workbook is None:
            raise UserError(_("The openpyxl library is required to generate Excel templates."))

        wb = Workbook()

        # Sheet 1: Course Import Data Sheet
        ws = wb.active
        ws.title = 'Course_Catalog_Template'

        # Colors & Styling
        primary_color = '541718'  # Bunna Burgundy
        accent_color = '8A1538'
        header_font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
        header_fill = PatternFill('solid', fgColor=primary_color)
        thin_border = Border(
            left=Side(style='thin', color='DDDDDD'),
            right=Side(style='thin', color='DDDDDD'),
            top=Side(style='thin', color='DDDDDD'),
            bottom=Side(style='thin', color='DDDDDD'),
        )
        sample_fill = PatternFill('solid', fgColor='F9F9F9')

        # Title Banner
        ws['A1'] = 'BUNNA BANK S.C. — COURSE CATALOG BULK IMPORT TEMPLATE'
        ws['A1'].font = Font(name='Calibri', size=14, bold=True, color=primary_color)
        ws.merge_cells('A1:O1')

        # Instructions
        ws['A2'] = (
            'INSTRUCTIONS: Fill in your courses starting at Row 5. "Course Name" is mandatory. '
            'If "Course Code" is left blank, the system will auto-assign sequential codes (e.g. CRS-0001). '
            'Target Departments, Job Positions, and Competencies can be comma-separated. '
            'See the "Allowed_Values_Guide" tab for recognized categories, delivery methods, and audience codes.'
        )
        ws['A2'].font = Font(name='Calibri', size=9, italic=True, color='555555')
        ws['A2'].alignment = Alignment(wrap_text=True, vertical='center')
        ws.row_dimensions[2].height = 36
        ws.merge_cells('A2:O2')

        # Blank spacer row 3
        ws.row_dimensions[3].height = 8

        # Headers on Row 4
        headers = [
            'Course Name *',
            'Course Code',
            'Category',
            'Program Category',
            'Delivery Method',
            'Delivery Place',
            'Duration (Days)',
            'Schedule / Frequency',
            'Target Audience',
            'Min Service Tenure (Months)',
            'Status',
            'Target Departments',
            'Target Job Positions',
            'Target Competencies',
            'Description & Objectives',
        ]
        ws.row_dimensions[4].height = 28
        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=4, column=col_idx, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

        # Sample realistic bank training courses on rows 5 to 9
        sample_rows = [
            [
                'Branch Operations & Cash Management Fundamentals',
                '',
                'Developmental',
                'Technical / Functional',
                'Internal Delivery',
                'Local',
                3,
                'Annual',
                'Staff Below MLM',
                0,
                'Active',
                'Branch Operations, Retail Banking',
                'Customer Service Officer, Branch Cashier',
                'Cash Operations, Customer Service',
                'Covers day-to-day branch teller and back-office banking operations, vault management, and internal controls.',
            ],
            [
                'Anti-Money Laundering (AML) & Counter-Terrorist Financing (CFT)',
                '',
                'Technical / Compliance',
                'Compliance',
                'Internal Delivery',
                'Local',
                2,
                'Annual',
                'All Staff',
                0,
                'Active',
                '',
                '',
                'Regulatory Compliance, AML/CFT',
                'Mandatory annual refresher on KYC, suspicious transaction identification, and NBE reporting compliance.',
            ],
            [
                'Credit Appraisal & Financial Statement Analysis for Corporates',
                'CRS-CRED-01',
                'Developmental',
                'Technical / Functional',
                'Local External Provider',
                'Local',
                5,
                'Semi-Annual',
                'MLM (Middle Level Management)',
                6,
                'Active',
                'Credit Underwriting, Corporate Banking, Risk Management',
                'Credit Analyst, Senior Loan Officer, Relationship Manager',
                'Credit Risk Analysis, Financial Modeling',
                'Comprehensive workshop on cash flow lending, ratio analysis, balance sheet audit, and working capital appraisal.',
            ],
            [
                'Executive Strategic Leadership & Banking Transformation',
                '',
                'Developmental',
                'Leadership',
                'International Provider',
                'International',
                5,
                'Annual',
                'SMC (Senior Management Committee)',
                12,
                'Active',
                '',
                '',
                'Strategic Thinking, Executive Leadership',
                'Executive immersion in digital banking disruption, corporate governance, and change leadership.',
            ],
            [
                'Cybersecurity Hygiene & Information Security Awareness',
                '',
                'Technical / Compliance',
                'Digital & IT',
                'E-Learning',
                'Local',
                1,
                'Continuous',
                'All Staff',
                0,
                'Active',
                'Information Technology, Information Security',
                '',
                'Information Security, Digital Hygiene',
                'Interactive e-learning module on phishing defense, password management, and data privacy protection.',
            ],
        ]

        for row_idx, row_data in enumerate(sample_rows, start=5):
            ws.row_dimensions[row_idx].height = 24
            for col_idx, val in enumerate(row_data, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.font = Font(name='Calibri', size=10)
                cell.border = thin_border
                if row_idx % 2 == 1:
                    cell.fill = sample_fill
                if col_idx in (7, 10):
                    cell.alignment = Alignment(horizontal='center', vertical='center')
                else:
                    cell.alignment = Alignment(vertical='center')

        # Auto-fit column widths
        widths = {
            'A': 42,  # Name
            'B': 16,  # Code
            'C': 24,  # Category
            'D': 26,  # Program Category
            'E': 26,  # Delivery Method
            'F': 16,  # Delivery Place
            'G': 16,  # Duration
            'H': 22,  # Schedule
            'I': 28,  # Target Audience
            'J': 26,  # Min Tenure
            'K': 14,  # Status
            'L': 38,  # Target Departments
            'M': 38,  # Target Jobs
            'N': 35,  # Competencies
            'O': 50,  # Description
        }
        for col_letter, width in widths.items():
            ws.column_dimensions[col_letter].width = width

        # ── Sheet 2: Allowed Values Reference Guide ───────────────────────
        ws_guide = wb.create_sheet(title='Allowed_Values_Guide')
        guide_headers = ['Field Name', 'Recognized Allowed Values / Options', 'Notes & Defaults']
        ws_guide.row_dimensions[1].height = 26
        for c_idx, gh in enumerate(guide_headers, start=1):
            cell = ws_guide.cell(row=1, column=c_idx, value=gh)
            cell.font = header_font
            cell.fill = PatternFill('solid', fgColor=accent_color)
            cell.alignment = Alignment(horizontal='center', vertical='center')

        guide_rows = [
            ('Course Name', 'Any valid title string (e.g. Trade Finance Operations)', 'MANDATORY. Identifies the course.'),
            ('Course Code', 'Custom code (e.g. CRS-OPS-01) or leave empty', 'OPTIONAL. If empty, system auto-generates sequential code (CRS-0001).'),
            ('Category', 'Developmental | Values & Ethics | Technical / Compliance', 'Default: Developmental'),
            ('Program Category', 'Technical / Functional | Induction Program | Compliance | Leadership | Digital & IT | Soft Skills | Risk & Audit | Customer Service | Other', 'Default: Technical / Functional'),
            ('Delivery Method', 'Internal Delivery | Local External Provider | International Provider | E-Learning', 'Default: Internal Delivery'),
            ('Delivery Place', 'Local | International', 'Default: Local'),
            ('Duration (Days)', 'Numeric whole integer (e.g. 1, 2, 3, 5, 10)', 'Default: 1 day'),
            ('Schedule / Frequency', 'Annual | Semi-Annual | Quarterly | Monthly | On-Demand | Continuous', 'Default: Annual (Once a Year)'),
            ('Target Audience', 'All Staff | Staff Below MLM | MLM (Middle Level Management) | SMC (Senior Management Committee) | BoD (Board of Directors)', 'Default: All Staff'),
            ('Min Service Tenure (Months)', 'Integer number of months (e.g. 0, 6, 12, 24)', 'Default: 0 months (no tenure restriction)'),
            ('Status', 'Active | Draft', 'Default: Active (if blank, wizard setting applies)'),
            ('Target Departments', 'Comma-separated department names (e.g. Credit Underwriting, Retail Banking)', 'Optional. Leave blank to apply bank-wide.'),
            ('Target Job Positions', 'Comma-separated job position titles (e.g. Credit Analyst, Branch Manager)', 'Optional. Leave blank to apply to all positions.'),
            ('Target Competencies', 'Comma-separated competency names from Competency Framework', 'Optional. Automatically maps competency lines.'),
            ('Description & Objectives', 'Course syllabus, key learning topics, behavioral goals', 'Optional text overview of the curriculum.'),
        ]

        for r_idx, (fname, val_opt, notes) in enumerate(guide_rows, start=2):
            ws_guide.row_dimensions[r_idx].height = 22
            c1 = ws_guide.cell(row=r_idx, column=1, value=fname)
            c2 = ws_guide.cell(row=r_idx, column=2, value=val_opt)
            c3 = ws_guide.cell(row=r_idx, column=3, value=notes)
            for c in (c1, c2, c3):
                c.font = Font(name='Calibri', size=10)
                c.border = thin_border
            c1.font = Font(name='Calibri', size=10, bold=True)
            if r_idx % 2 == 1:
                c1.fill = sample_fill
                c2.fill = sample_fill
                c3.fill = sample_fill

        ws_guide.column_dimensions['A'].width = 28
        ws_guide.column_dimensions['B'].width = 65
        ws_guide.column_dimensions['C'].width = 45

        # ── Sheet 3: Dedicated Dropdown Lookup Lists ──────────────────────
        ws_lists = wb.create_sheet(title='Dropdown_Selections')

        categories = ['Developmental', 'Values & Ethics', 'Technical / Compliance']
        program_categories = [
            'Technical / Functional', 'Induction Program', 'Compliance', 'Leadership',
            'Digital & IT', 'Soft Skills', 'Risk & Audit', 'Customer Service', 'Other'
        ]
        delivery_methods = [
            'Internal Delivery', 'Local External Provider', 'International Provider', 'E-Learning'
        ]
        delivery_places = ['Local', 'International']
        schedules = [
            'Annual', 'Semi-Annual', 'Quarterly', 'Monthly', 'On-Demand', 'Continuous'
        ]
        target_audiences = [
            'All Staff', 'Staff Below MLM', 'MLM (Middle Level Management)',
            'SMC (Senior Management Committee)', 'BoD (Board of Directors)'
        ]
        statuses = ['Active', 'Draft']

        list_cols = [
            ('Category', categories),
            ('Program Category', program_categories),
            ('Delivery Method', delivery_methods),
            ('Delivery Place', delivery_places),
            ('Schedule', schedules),
            ('Target Audience', target_audiences),
            ('Status', statuses),
        ]

        ws_lists.row_dimensions[1].height = 24
        for col_idx, (col_title, items) in enumerate(list_cols, start=1):
            hdr = ws_lists.cell(row=1, column=col_idx, value=col_title)
            hdr.font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
            hdr.fill = PatternFill('solid', fgColor=primary_color)
            hdr.alignment = Alignment(horizontal='center', vertical='center')
            for r_idx, val in enumerate(items, start=2):
                cell = ws_lists.cell(row=r_idx, column=col_idx, value=val)
                cell.font = Font(name='Calibri', size=10)
                cell.border = thin_border

        for col_letter in ('A', 'B', 'C', 'D', 'E', 'F', 'G'):
            ws_lists.column_dimensions[col_letter].width = 30

        # ── Attach Excel Data Validations (Dropdown Selection Lists) ───────
        if DataValidation:
            # 1. Category -> Column C (C5:C1000)
            dv_cat = DataValidation(type='list', formula1=f'Dropdown_Selections!$A$2:$A${len(categories) + 1}', allow_blank=True)
            dv_cat.error = 'Please select a recognized Category from the list.'
            dv_cat.errorTitle = 'Invalid Category'
            dv_cat.prompt = 'Select Category from dropdown'
            dv_cat.promptTitle = 'Course Category'
            ws.add_data_validation(dv_cat)
            dv_cat.add('C5:C1000')

            # 2. Program Category -> Column D (D5:D1000)
            dv_pcat = DataValidation(type='list', formula1=f'Dropdown_Selections!$B$2:$B${len(program_categories) + 1}', allow_blank=True)
            dv_pcat.error = 'Please select a recognized Program Category from the list.'
            dv_pcat.errorTitle = 'Invalid Program Category'
            dv_pcat.prompt = 'Select Program Category from dropdown'
            dv_pcat.promptTitle = 'Program Category'
            ws.add_data_validation(dv_pcat)
            dv_pcat.add('D5:D1000')

            # 3. Delivery Method -> Column E (E5:E1000)
            dv_deliv = DataValidation(type='list', formula1=f'Dropdown_Selections!$C$2:$C${len(delivery_methods) + 1}', allow_blank=True)
            dv_deliv.error = 'Please select a recognized Delivery Method from the list.'
            dv_deliv.errorTitle = 'Invalid Delivery Method'
            dv_deliv.prompt = 'Select Delivery Method from dropdown'
            dv_deliv.promptTitle = 'Delivery Method'
            ws.add_data_validation(dv_deliv)
            dv_deliv.add('E5:E1000')

            # 4. Delivery Place -> Column F (F5:F1000)
            dv_place = DataValidation(type='list', formula1=f'Dropdown_Selections!$D$2:$D${len(delivery_places) + 1}', allow_blank=True)
            dv_place.error = 'Select Local or International from the list.'
            dv_place.errorTitle = 'Invalid Delivery Place'
            dv_place.prompt = 'Select Local or International'
            dv_place.promptTitle = 'Delivery Place'
            ws.add_data_validation(dv_place)
            dv_place.add('F5:F1000')

            # 5. Schedule / Frequency -> Column H (H5:H1000)
            dv_sched = DataValidation(type='list', formula1=f'Dropdown_Selections!$E$2:$E${len(schedules) + 1}', allow_blank=True)
            dv_sched.error = 'Select a recognized Schedule frequency from the list.'
            dv_sched.errorTitle = 'Invalid Schedule'
            dv_sched.prompt = 'Select Schedule from dropdown'
            dv_sched.promptTitle = 'Schedule / Frequency'
            ws.add_data_validation(dv_sched)
            dv_sched.add('H5:H1000')

            # 6. Target Audience -> Column I (I5:I1000)
            dv_aud = DataValidation(type='list', formula1=f'Dropdown_Selections!$F$2:$F${len(target_audiences) + 1}', allow_blank=True)
            dv_aud.error = 'Select a recognized Target Audience group from the list.'
            dv_aud.errorTitle = 'Invalid Target Audience'
            dv_aud.prompt = 'Select Target Audience from dropdown'
            dv_aud.promptTitle = 'Target Audience'
            ws.add_data_validation(dv_aud)
            dv_aud.add('I5:I1000')

            # 7. Status -> Column K (K5:K1000)
            dv_stat = DataValidation(type='list', formula1=f'Dropdown_Selections!$G$2:$G${len(statuses) + 1}', allow_blank=True)
            dv_stat.error = 'Select Active or Draft from the list.'
            dv_stat.errorTitle = 'Invalid Status'
            dv_stat.prompt = 'Select Active or Draft'
            dv_stat.promptTitle = 'Course Status'
            ws.add_data_validation(dv_stat)
            dv_stat.add('K5:K1000')

            # 8. Duration (Days) -> Column G (G5:G1000) (Integer >= 1)
            dv_dur = DataValidation(type='whole', operator='greaterThanOrEqual', formula1=1, allow_blank=True)
            dv_dur.error = 'Duration must be an integer of 1 or more days.'
            dv_dur.errorTitle = 'Invalid Duration'
            ws.add_data_validation(dv_dur)
            dv_dur.add('G5:G1000')

            # 9. Min Service Tenure -> Column J (J5:J1000) (Integer >= 0)
            dv_ten = DataValidation(type='whole', operator='greaterThanOrEqual', formula1=0, allow_blank=True)
            dv_ten.error = 'Minimum Service Tenure must be 0 or more months.'
            dv_ten.errorTitle = 'Invalid Tenure'
            ws.add_data_validation(dv_ten)
            dv_ten.add('J5:J1000')

        output = io.BytesIO()
        wb.save(output)
        out_val = output.getvalue()
        output.close()

        attachment = self.env['ir.attachment'].with_context(skip_eds_file_check=True).create({
            'name': 'Bunna_Course_Catalog_Import_Template.xlsx',
            'type': 'binary',
            'datas': base64.b64encode(out_val),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'res_model': self._name,
            'res_id': self.id,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def action_download_csv_template(self, *args, **kwargs):
        """Generate and download a standard CSV template for course catalog ingestion."""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'Course Name', 'Course Code', 'Category', 'Program Category',
            'Delivery Method', 'Delivery Place', 'Duration (Days)', 'Schedule',
            'Target Audience', 'Min Tenure Months', 'Status',
            'Target Departments', 'Target Job Positions', 'Target Competencies', 'Description'
        ])
        writer.writerow([
            'Branch Operations & Cash Management Fundamentals', '', 'Developmental',
            'Technical / Functional', 'Internal Delivery', 'Local', '3', 'Annual',
            'Staff Below MLM', '0', 'Active', 'Branch Operations, Retail Banking',
            'Customer Service Officer, Branch Cashier', 'Cash Operations',
            'Covers day-to-day teller, vault management, and branch internal controls.'
        ])
        writer.writerow([
            'Anti-Money Laundering (AML) & Counter-Terrorist Financing (CFT)', '', 'Technical / Compliance',
            'Compliance', 'Internal Delivery', 'Local', '2', 'Annual',
            'All Staff', '0', 'Active', '', '', 'Regulatory Compliance',
            'Mandatory annual refresher on KYC, suspicious transaction identification, and NBE reporting.'
        ])
        csv_data = output.getvalue().encode('utf-8-sig')
        output.close()

        attachment = self.env['ir.attachment'].with_context(skip_eds_file_check=True).create({
            'name': 'Bunna_Course_Catalog_Import_Template.csv',
            'type': 'binary',
            'datas': base64.b64encode(csv_data),
            'mimetype': 'text/csv',
            'res_model': self._name,
            'res_id': self.id,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    # ══════════════════════════════════════════════════════════════════
    # Course Ingestion & Parsing
    # ══════════════════════════════════════════════════════════════════

    def action_import_courses(self, *args, **kwargs):
        """Parse the uploaded Excel or CSV file and ingest courses into eds.course."""
        self.ensure_one()
        if not self.file:
            raise ValidationError(_("Please choose an Excel (.xlsx) or CSV file to import."))

        raw_data = base64.b64decode(self.file)
        if raw_data.startswith(b'PK\x03\x04') or (self.filename and self.filename.lower().endswith(('.xlsx', '.xlsm'))):
            rows = self._read_excel(raw_data)
        else:
            rows = self._read_csv(raw_data)

        if not rows:
            raise UserError(_("No course data rows were found in the uploaded file."))

        return self._process_course_rows(rows)

    def _read_excel(self, data):
        if not openpyxl:
            raise ValidationError(_("The openpyxl library is required to import Excel course catalogs."))

        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        except Exception as e:
            raise ValidationError(_("Failed to read Excel workbook: %s") % str(e))

        ws = wb.active

        # Header detection: scan rows 1 through 10
        header_row = None
        col_map = {}
        for r in range(1, min(12, ws.max_row + 1)):
            row_vals = [str(ws.cell(r, c).value or '').strip().lower() for c in range(1, ws.max_column + 1)]
            for col_idx, val in enumerate(row_vals, start=1):
                if 'course name' in val or ('name' in val and 'course' in val) or val == 'title' or val == 'course':
                    header_row = r
                    break
            if header_row:
                break

        if not header_row:
            header_row = 1

        # Map column positions to canonical fields
        for c in range(1, ws.max_column + 1):
            val = str(ws.cell(header_row, c).value or '').strip().lower()
            if not val:
                continue
            if 'name' in val or 'title' in val or val == 'course':
                col_map.setdefault('name', c)
            elif 'code' in val or 'ref' in val or 'id' in val:
                col_map.setdefault('code', c)
            elif 'program category' in val or 'program_cat' in val:
                col_map.setdefault('program_category', c)
            elif 'category' in val:
                col_map.setdefault('category', c)
            elif 'delivery method' in val or 'method' in val or 'mode' in val:
                col_map.setdefault('delivery_method', c)
            elif 'delivery place' in val or 'place' in val or 'location' in val:
                col_map.setdefault('delivery_place', c)
            elif 'duration' in val or 'days' in val:
                col_map.setdefault('duration_days', c)
            elif 'schedule' in val or 'frequency' in val or 'cadence' in val:
                col_map.setdefault('schedule', c)
            elif 'target audience' in val or 'audience' in val:
                col_map.setdefault('target_audience', c)
            elif 'tenure' in val:
                col_map.setdefault('min_tenure_months', c)
            elif 'status' in val or 'state' in val:
                col_map.setdefault('status', c)
            elif 'department' in val:
                col_map.setdefault('departments', c)
            elif 'job' in val or 'position' in val:
                col_map.setdefault('jobs', c)
            elif 'competenc' in val:
                col_map.setdefault('competencies', c)
            elif 'description' in val or 'objective' in val or 'syllabus' in val or 'summary' in val:
                col_map.setdefault('description', c)

        if 'name' not in col_map:
            raise UserError(_("Could not locate a 'Course Name' header column in the uploaded spreadsheet."))

        rows = []
        for r in range(header_row + 1, ws.max_row + 1):
            row_dict = {'row_num': r}
            has_data = False
            for field_name, col_idx in col_map.items():
                cell_val = ws.cell(r, col_idx).value
                if cell_val is not None and str(cell_val).strip():
                    has_data = True
                row_dict[field_name] = cell_val
            if has_data and row_dict.get('name'):
                rows.append(row_dict)

        return rows

    def _read_csv(self, data):
        try:
            file_input = io.StringIO(data.decode('utf-8-sig'))
            reader = csv.reader(file_input)
        except Exception:
            try:
                file_input = io.StringIO(data.decode('latin1'))
                reader = csv.reader(file_input)
            except Exception as e:
                raise ValidationError(_("Failed to read CSV file: %s") % str(e))

        raw_rows = list(reader)
        if not raw_rows:
            return []

        # Find header row
        header_row_idx = 0
        for idx, row in enumerate(raw_rows[:10]):
            lowered = [str(x).strip().lower() for x in row]
            if any('name' in x or 'title' in x or 'course' in x for x in lowered):
                header_row_idx = idx
                break

        header_vals = [str(x).strip().lower() for x in raw_rows[header_row_idx]]
        col_map = {}
        for c_idx, val in enumerate(header_vals):
            if not val:
                continue
            if 'name' in val or 'title' in val or val == 'course':
                col_map.setdefault('name', c_idx)
            elif 'code' in val or 'ref' in val:
                col_map.setdefault('code', c_idx)
            elif 'program category' in val:
                col_map.setdefault('program_category', c_idx)
            elif 'category' in val:
                col_map.setdefault('category', c_idx)
            elif 'delivery method' in val or 'method' in val or 'mode' in val:
                col_map.setdefault('delivery_method', c_idx)
            elif 'delivery place' in val or 'place' in val:
                col_map.setdefault('delivery_place', c_idx)
            elif 'duration' in val or 'days' in val:
                col_map.setdefault('duration_days', c_idx)
            elif 'schedule' in val or 'frequency' in val:
                col_map.setdefault('schedule', c_idx)
            elif 'audience' in val:
                col_map.setdefault('target_audience', c_idx)
            elif 'tenure' in val:
                col_map.setdefault('min_tenure_months', c_idx)
            elif 'status' in val or 'state' in val:
                col_map.setdefault('status', c_idx)
            elif 'department' in val:
                col_map.setdefault('departments', c_idx)
            elif 'job' in val or 'position' in val:
                col_map.setdefault('jobs', c_idx)
            elif 'competenc' in val:
                col_map.setdefault('competencies', c_idx)
            elif 'description' in val or 'objective' in val or 'summary' in val:
                col_map.setdefault('description', c_idx)

        if 'name' not in col_map:
            raise UserError(_("Could not locate a 'Course Name' header column in the uploaded CSV file."))

        rows = []
        for r_idx, row in enumerate(raw_rows[header_row_idx + 1:], start=header_row_idx + 2):
            if not any(str(x).strip() for x in row):
                continue
            row_dict = {'row_num': r_idx}
            for field_name, c_idx in col_map.items():
                val = row[c_idx] if c_idx < len(row) else ''
                row_dict[field_name] = val
            if row_dict.get('name'):
                rows.append(row_dict)

        return rows

    # ══════════════════════════════════════════════════════════════════
    # Normalizers
    # ══════════════════════════════════════════════════════════════════

    def _normalize_category(self, val):
        s = str(val or '').strip().lower()
        if 'value' in s or 'ethic' in s:
            return 'values_ethics'
        elif 'tech' in s or 'compliance' in s:
            return 'technical_compliance'
        return 'developmental'

    def _normalize_program_category(self, val):
        s = str(val or '').strip().lower()
        if 'induction' in s or 'onboard' in s:
            return 'induction'
        elif 'compliance' in s or 'regulat' in s:
            return 'compliance'
        elif 'leader' in s or 'manage' in s or 'executive' in s:
            return 'leadership'
        elif 'digital' in s or ' it' in s or s.startswith('it') or 'cyber' in s or 'tech' in s and 'functional' not in s:
            return 'digital_it'
        elif 'soft' in s or 'interpersonal' in s or 'communication' in s:
            return 'soft_skills'
        elif 'risk' in s or 'audit' in s:
            return 'risk_audit'
        elif 'customer' in s or 'service' in s or 'client' in s:
            return 'customer_service'
        elif 'technical' in s or 'functional' in s or 'credit' in s or 'trade' in s or 'operation' in s:
            return 'technical_functional'
        return 'technical_functional'

    def _normalize_delivery_method(self, val):
        s = str(val or '').strip().lower()
        if 'international' in s:
            return 'international'
        elif 'local' in s or 'external' in s or 'provider' in s or 'vendor' in s:
            return 'local_external'
        elif 'elearning' in s or 'e_learning' in s or 'e-learning' in s or 'online' in s or 'digital' in s:
            return 'elearning'
        return 'internal'

    def _normalize_delivery_place(self, val):
        s = str(val or '').strip().lower()
        if 'international' in s or 'abroad' in s or 'overseas' in s:
            return 'international'
        return 'local'

    def _normalize_schedule(self, val):
        s = str(val or '').strip().lower()
        if 'semi' in s or 'twice' in s:
            return 'semi_annual'
        elif 'quarter' in s:
            return 'quarterly'
        elif 'month' in s:
            return 'monthly'
        elif 'demand' in s or 'needed' in s:
            return 'on_demand'
        elif 'continuous' in s or 'roll' in s:
            return 'continuous'
        return 'annual'

    def _normalize_target_audience(self, val):
        s = str(val or '').strip().lower()
        if 'bod' in s or 'board' in s:
            return 'bod'
        elif 'smc' in s or 'senior management' in s or 'executive' in s:
            return 'smc'
        elif 'mlm' in s and 'below' not in s:
            return 'mlm'
        elif 'below' in s or 'officer' in s or 'clerk' in s or 'specialist' in s:
            return 'below_mlm'
        return 'all_staff'

    def _normalize_status(self, val):
        s = str(val or '').strip().lower()
        if 'draft' in s or 'pending' in s:
            return 'draft'
        elif 'active' in s or 'approved' in s or 'publish' in s:
            return 'active'
        return self.default_status or 'active'

    # ══════════════════════════════════════════════════════════════════
    # Processing Logic
    # ══════════════════════════════════════════════════════════════════

    def _process_course_rows(self, rows):
        Course = self.env['eds.course'].sudo()
        Dept = self.env['hr.department'].sudo()
        Job = self.env['hr.job'].sudo()
        Competency = self.env['competency.competency'].sudo() if 'competency.competency' in self.env else None

        created_count = 0
        updated_count = 0
        skipped_count = 0
        log_entries = []

        for row in rows:
            r_num = row.get('row_num', '?')
            course_name = str(row.get('name') or '').strip()
            if not course_name:
                skipped_count += 1
                log_entries.append((
                    'warning',
                    f"Row {r_num}: Skipped because Course Name is empty."
                ))
                continue

            course_code = str(row.get('code') or '').strip()
            if course_code.lower() in ('new', 'auto', 'none', '-'):
                course_code = ''

            # Find existing course
            existing = None
            if self.update_existing:
                if course_code:
                    existing = Course.search([('code', '=ilike', course_code)], limit=1)
                if not existing:
                    existing = Course.search([('name', '=ilike', course_name)], limit=1)

            # Parse numeric duration
            duration = 1
            try:
                raw_dur = row.get('duration_days')
                if raw_dur is not None and str(raw_dur).strip():
                    duration = max(1, int(float(str(raw_dur).strip())))
            except (ValueError, TypeError):
                duration = 1

            # Parse tenure
            min_tenure = 0
            try:
                raw_tenure = row.get('min_tenure_months')
                if raw_tenure is not None and str(raw_tenure).strip():
                    min_tenure = max(0, int(float(str(raw_tenure).strip())))
            except (ValueError, TypeError):
                min_tenure = 0

            # Target departments
            dept_ids = []
            dept_raw = str(row.get('departments') or '').strip()
            if dept_raw:
                for d_name in [x.strip() for x in dept_raw.replace(';', ',').split(',') if x.strip()]:
                    found_dept = Dept.search([('name', '=ilike', d_name)], limit=1)
                    if found_dept:
                        dept_ids.append(found_dept.id)

            # Target job positions
            job_ids = []
            job_raw = str(row.get('jobs') or '').strip()
            if job_raw:
                for j_name in [x.strip() for x in job_raw.replace(';', ',').split(',') if x.strip()]:
                    found_job = Job.search([('name', '=ilike', j_name)], limit=1)
                    if found_job:
                        job_ids.append(found_job.id)

            # Target competencies
            comp_lines = []
            comp_raw = str(row.get('competencies') or '').strip()
            if comp_raw and Competency:
                for c_name in [x.strip() for x in comp_raw.replace(';', ',').split(',') if x.strip()]:
                    found_comp = Competency.search([('name', '=ilike', c_name)], limit=1)
                    if found_comp:
                        comp_lines.append((0, 0, {
                            'competency_id': found_comp.id,
                            'required_level': '2',
                            'weight_pct': 100,
                        }))

            vals = {
                'name': course_name,
                'category': self._normalize_category(row.get('category')),
                'program_category': self._normalize_program_category(row.get('program_category')),
                'delivery_method': self._normalize_delivery_method(row.get('delivery_method')),
                'delivery_place': self._normalize_delivery_place(row.get('delivery_place')),
                'duration_days': duration,
                'schedule': self._normalize_schedule(row.get('schedule')),
                'target_audience': self._normalize_target_audience(row.get('target_audience')),
                'min_tenure_months': min_tenure,
                'status': self._normalize_status(row.get('status')),
                'description': str(row.get('description') or '').strip() or False,
            }

            if dept_ids:
                vals['department_ids'] = [(6, 0, list(set(dept_ids)))]
            if job_ids:
                vals['target_audience_ids'] = [(6, 0, list(set(job_ids)))]

            try:
                if existing:
                    if course_code and not existing.code:
                        vals['code'] = course_code
                    existing.write(vals)
                    if comp_lines and not existing.competency_line_ids:
                        existing.write({'competency_line_ids': comp_lines})
                    updated_count += 1
                    log_entries.append((
                        'success',
                        f"Row {r_num}: Updated existing course <b>{escape(existing.code or '')} - {escape(existing.name)}</b>."
                    ))
                else:
                    if course_code:
                        vals['code'] = course_code
                    if comp_lines:
                        vals['competency_line_ids'] = comp_lines
                    new_course = Course.create(vals)
                    created_count += 1
                    log_entries.append((
                        'success',
                        f"Row {r_num}: Created new course <b>{escape(new_course.code)} - {escape(new_course.name)}</b> "
                        f"({dict(new_course._fields['program_category'].selection).get(new_course.program_category, '')}, "
                        f"{new_course.duration_days} Days, Status: {dict(new_course._fields['status'].selection).get(new_course.status, '')})."
                    ))
            except Exception as e:
                skipped_count += 1
                log_entries.append((
                    'danger',
                    f"Row {r_num} ({escape(course_name)}): Failed to import — {escape(str(e))}"
                ))

        # Format summary HTML
        html_log = f"""
        <div class="mb-3">
            <div class="row g-2 text-center mb-3">
                <div class="col-4">
                    <div class="p-2 border rounded bg-success-subtle text-success">
                        <div class="fs-4 fw-bold">{created_count}</div>
                        <div class="small fw-semibold">Courses Created</div>
                    </div>
                </div>
                <div class="col-4">
                    <div class="p-2 border rounded bg-primary-subtle text-primary">
                        <div class="fs-4 fw-bold">{updated_count}</div>
                        <div class="small fw-semibold">Courses Updated</div>
                    </div>
                </div>
                <div class="col-4">
                    <div class="p-2 border rounded bg-warning-subtle text-warning">
                        <div class="fs-4 fw-bold">{skipped_count}</div>
                        <div class="small fw-semibold">Skipped / Errors</div>
                    </div>
                </div>
            </div>
            <h6 class="fw-bold mb-2">Ingestion Activity Log:</h6>
            <div style="max-height: 280px; overflow-y: auto; font-size: 0.88rem; border: 1px solid #e2e8f0; border-radius: 4px; padding: 8px;">
        """
        for badge_type, text in log_entries:
            text_color = 'text-success' if badge_type == 'success' else ('text-warning' if badge_type == 'warning' else 'text-danger')
            icon = 'fa-check-circle' if badge_type == 'success' else ('fa-exclamation-triangle' if badge_type == 'warning' else 'fa-times-circle')
            html_log += f'<div class="py-1 border-bottom"><i class="fa {icon} me-1 {text_color}"></i> {text}</div>'
        html_log += "</div></div>"

        self.write({'result_log': Markup(html_log)})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
