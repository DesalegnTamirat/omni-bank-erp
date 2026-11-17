# -*- coding: utf-8 -*-
import io
import base64
from odoo import api, fields, models, _
from odoo.exceptions import UserError

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
except ImportError:
    openpyxl = None


class PmProjectDocument(models.Model):
    _name = 'pm.project.document'
    _description = 'Project Documentation & Evidence'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Document Title', required=True, tracking=True)
    document_type = fields.Selection([
        ('requirement', 'Requirements'),
        ('gap_analysis', 'Gap Analysis'),
        ('test_case', 'Test Cases Specification'),
        ('architecture', 'Architecture / Design'),
        ('other', 'Other Specification')
    ], string='Document Type', default='requirement', required=True, tracking=True)

    project_id = fields.Many2one('pm.project', string='Project', required=True, ondelete='cascade', tracking=True)
    milestone_id = fields.Many2one('pm.milestone', string='Milestone', ondelete='set null',
                                  domain="[('project_id', '=', project_id)]", tracking=True)
    deliverable_id = fields.Many2one('pm.deliverable', string='Deliverable / Major Activity', ondelete='set null',
                                    domain="milestone_id and [('milestone_id', '=', milestone_id)] or [('project_id', '=', project_id)]", tracking=True)

    file = fields.Binary(string='Attachment / Document', required=True)
    filename = fields.Char(string='File Name')
    description = fields.Text(string='Description / Scope Notes')
    date_uploaded = fields.Date(string='Uploaded On', default=fields.Date.context_today, readonly=True)
    uploaded_by_id = fields.Many2one('res.users', string='Uploaded By', default=lambda self: self.env.user, readonly=True)
    active = fields.Boolean(string='Active', default=True)

    # Test Cases Parsed from Document Excel
    test_case_line_ids = fields.One2many('pm.test.case.line', 'document_id', string='Test Cases Specification')
    has_test_cases = fields.Boolean(string='Has Test Cases', compute='_compute_has_test_cases', store=True)

    @api.depends('test_case_line_ids', 'document_type')
    def _compute_has_test_cases(self):
        for rec in self:
            rec.has_test_cases = bool(rec.test_case_line_ids or rec.document_type == 'test_case')

    def unlink(self):
        """Soft delete: archive document instead of permanent deletion."""
        return self.write({'active': False})

    @api.onchange('project_id')
    def _onchange_project_id(self):
        domain = {
            'milestone_id': [],
            'deliverable_id': [],
        }
        if self.project_id:
            if self.milestone_id and self.milestone_id.project_id != self.project_id:
                self.milestone_id = False
            if self.deliverable_id and self.deliverable_id.project_id != self.project_id:
                self.deliverable_id = False
            domain['milestone_id'] = [('project_id', '=', self.project_id.id)]
            if self.milestone_id:
                domain['deliverable_id'] = [('milestone_id', '=', self.milestone_id.id)]
            else:
                domain['deliverable_id'] = [('project_id', '=', self.project_id.id)]
        else:
            self.milestone_id = False
            self.deliverable_id = False
        return {'domain': domain}

    @api.onchange('milestone_id')
    def _onchange_milestone_id(self):
        if self.milestone_id:
            if not self.project_id or self.project_id != self.milestone_id.project_id:
                self.project_id = self.milestone_id.project_id
            if self.deliverable_id and self.deliverable_id.milestone_id != self.milestone_id:
                self.deliverable_id = False
            return {'domain': {'deliverable_id': [('milestone_id', '=', self.milestone_id.id)]}}
        elif self.project_id:
            return {'domain': {'deliverable_id': [('project_id', '=', self.project_id.id)]}}
        else:
            return {'domain': {'deliverable_id': []}}

    @api.onchange('deliverable_id')
    def _onchange_deliverable_id(self):
        if self.deliverable_id:
            if self.deliverable_id.milestone_id:
                self.milestone_id = self.deliverable_id.milestone_id
            if self.deliverable_id.project_id:
                self.project_id = self.deliverable_id.project_id

    # -------------------------------------------------------------------------
    # TEMPLATE DOWNLOAD GENERATOR
    # -------------------------------------------------------------------------
    def action_download_template(self):
        if not openpyxl:
            raise UserError(_('openpyxl library is required to generate templates.'))

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Test Cases"

        headers = [
            "Test ID", "Test Case Name", "Deliverable Name", "Category", 
            "Severity", "Preconditions", "Test Steps", "Expected Result"
        ]
        ws.append(headers)

        header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")

        sample_rows = [
            ["TC-001", "User Login with Multi-Factor Authentication", "", "Security", "Critical", "User account active, MFA configured", "1. Enter valid credentials\n2. Request SMS OTP\n3. Input OTP code", "User successfully authenticated and redirected to Dashboard"],
            ["TC-002", "API Endpoint Response Rate Under Load", "", "API / Integration", "High", "Gateway service running", "1. Dispatch 1000 concurrent REST requests\n2. Monitor latency and HTTP status", "All responses HTTP 200 with response time < 250ms"],
            ["TC-003", "Transaction Settlement End-to-End Validation", "", "Functional", "High", "Ledger balance initialized", "1. Post debit ledger transaction\n2. Verify double-entry credit ledger", "Both debit and credit balance reflect accurately"],
        ]
        for row in sample_rows:
            ws.append(row)

        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 14)

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        file_content = base64.b64encode(output.read())

        attachment = self.env['ir.attachment'].create({
            'name': 'TestCase_Template.xlsx',
            'type': 'binary',
            'datas': file_content,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'res_model': 'pm.project.document',
            'res_id': self.id or 0,
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    # -------------------------------------------------------------------------
    # AUTOMATED EXCEL PARSER ON UPLOAD
    # -------------------------------------------------------------------------
    def _parse_test_case_excel(self):
        self.ensure_one()
        if not openpyxl or not self.file:
            return

        filename = (self.filename or '').lower()
        if not (filename.endswith('.xlsx') or filename.endswith('.xlsm') or filename.endswith('.xltx')):
            return

        try:
            file_data = base64.b64decode(self.file)
            wb = openpyxl.load_workbook(filename=io.BytesIO(file_data), data_only=True)
            sheet = wb.active
        except Exception:
            return

        if not sheet:
            return

        header_row_idx = None
        col_mapping = {}
        for row_idx, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            if not row or all(v is None for v in row):
                continue
            row_str = [str(v or '').strip().lower() for v in row]
            for col_idx, val in enumerate(row_str):
                if any(k in val for k in ['deliverable', 'activity', 'module']):
                    col_mapping['deliverable'] = col_idx
                elif any(k in val for k in ['test id', 'case id', 'tc id', 'code']):
                    col_mapping['code'] = col_idx
                elif any(k in val for k in ['test case name', 'case name', 'test case', 'test title', 'scenario', 'title', 'name']):
                    col_mapping['name'] = col_idx
                elif any(k in val for k in ['category', 'type']):
                    col_mapping['category'] = col_idx
                elif any(k in val for k in ['severity', 'priority']):
                    col_mapping['severity'] = col_idx
                elif any(k in val for k in ['precondition', 'setup', 'prereq']):
                    col_mapping['preconditions'] = col_idx
                elif any(k in val for k in ['step', 'procedure', 'action']):
                    col_mapping['steps'] = col_idx
                elif any(k in val for k in ['expected', 'expected result', 'outcome']):
                    col_mapping['expected_result'] = col_idx

            if 'name' in col_mapping or 'code' in col_mapping:
                header_row_idx = row_idx
                break

        if header_row_idx is None:
            return

        deliverables = self.env['pm.deliverable'].search([
            '|',
            ('project_id', '=', self.project_id.id if self.project_id else False),
            ('milestone_id', '=', self.milestone_id.id if self.milestone_id else False)
        ])
        deliv_name_map = {d.name.strip().lower(): d.id for d in deliverables}
        deliv_code_map = {d.code.strip().lower(): d.id for d in deliverables if d.code}

        new_cases = []
        seq = 1
        for row_idx, row in enumerate(sheet.iter_rows(min_row=header_row_idx + 1, values_only=True), start=header_row_idx + 1):
            if not row or all(v is None for v in row):
                continue

            name_val = str(row[col_mapping['name']]).strip() if 'name' in col_mapping and col_mapping['name'] < len(row) and row[col_mapping['name']] else None
            code_val = str(row[col_mapping['code']]).strip() if 'code' in col_mapping and col_mapping['code'] < len(row) and row[col_mapping['code']] else None

            if not name_val and not code_val:
                continue
            if not name_val:
                name_val = code_val
            if not code_val:
                code_val = 'TC-%03d' % seq

            deliv_id = False
            if 'deliverable' in col_mapping and col_mapping['deliverable'] < len(row) and row[col_mapping['deliverable']]:
                d_str = str(row[col_mapping['deliverable']]).strip().lower()
                deliv_id = deliv_name_map.get(d_str) or deliv_code_map.get(d_str) or False

            cat_val = 'functional'
            if 'category' in col_mapping and col_mapping['category'] < len(row) and row[col_mapping['category']]:
                c_str = str(row[col_mapping['category']]).strip().lower()
                if 'sec' in c_str: cat_val = 'security'
                elif 'api' in c_str or 'integ' in c_str: cat_val = 'api_integration'
                elif 'ui' in c_str or 'ux' in c_str: cat_val = 'ui_ux'
                elif 'perf' in c_str: cat_val = 'performance'

            sev_val = 'medium'
            if 'severity' in col_mapping and col_mapping['severity'] < len(row) and row[col_mapping['severity']]:
                s_str = str(row[col_mapping['severity']]).strip().lower()
                if 'crit' in s_str or 'block' in s_str: sev_val = 'critical'
                elif 'high' in s_str: sev_val = 'high'
                elif 'low' in s_str: sev_val = 'low'

            pre_val = str(row[col_mapping['preconditions']]).strip() if 'preconditions' in col_mapping and col_mapping['preconditions'] < len(row) and row[col_mapping['preconditions']] else ''
            steps_val = str(row[col_mapping['steps']]).strip() if 'steps' in col_mapping and col_mapping['steps'] < len(row) and row[col_mapping['steps']] else ''
            exp_val = str(row[col_mapping['expected_result']]).strip() if 'expected_result' in col_mapping and col_mapping['expected_result'] < len(row) and row[col_mapping['expected_result']] else ''

            new_cases.append({
                'document_id': self.id,
                'project_id': self.project_id.id if self.project_id else False,
                'milestone_id': self.milestone_id.id if self.milestone_id else False,
                'deliverable_id': deliv_id or self.deliverable_id.id or False,
                'sequence': seq,
                'code': code_val,
                'name': name_val,
                'category': cat_val,
                'severity': sev_val,
                'preconditions': pre_val,
                'steps': steps_val,
                'expected_result': exp_val,
            })
            seq += 1

        if new_cases:
            self.test_case_line_ids.unlink()
            self.env['pm.test.case.line'].create(new_cases)
            if self.document_type != 'test_case':
                self.document_type = 'test_case'
            self.message_post(body=_('Automatically parsed and displayed <strong>%d</strong> test cases in the table below.') % len(new_cases))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.file and not rec.test_case_line_ids:
                rec._parse_test_case_excel()
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'file' in vals and vals.get('file'):
            for rec in self:
                rec._parse_test_case_excel()
        return res


class PmTestCase(models.Model):
    _name = 'pm.test.case'
    _description = 'Deliverable & Milestone Test Case'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'test_date desc, id desc'

    name = fields.Char(string='Test Case Name', required=True, tracking=True)
    code = fields.Char(string='Test Case ID', readonly=True, copy=False, default=lambda self: _('New'))
    
    project_id = fields.Many2one('pm.project', string='Project', required=True, ondelete='cascade', tracking=True)
    milestone_id = fields.Many2one('pm.milestone', string='Milestone', ondelete='set null',
                                  domain="[('project_id', '=', project_id)]", tracking=True)
    deliverable_id = fields.Many2one('pm.deliverable', string='Deliverable / Major Activity', ondelete='set null',
                                    domain="milestone_id and [('milestone_id', '=', milestone_id)] or [('project_id', '=', project_id)]", tracking=True)

    description = fields.Text(string='Description', tracking=True)
    status = fields.Selection([
        ('not_tested', 'Not Tested'),
        ('tested', 'Tested'),
    ], string='Status', default='not_tested', required=True, tracking=True)
    test_round = fields.Char(string='Test Round', default='Round 1', tracking=True)
    result = fields.Selection([
        ('pass', 'Pass'),
        ('fail', 'Fail'),
        ('indifferent', 'Indifferent'),
    ], string='Result', tracking=True)
    remark = fields.Text(string='Remark', tracking=True)
    test_date = fields.Date(string='Test Date', default=fields.Date.context_today, tracking=True)

    evidence_attachment = fields.Binary(string='Evidence / Attachment')
    evidence_filename = fields.Char(string='Evidence File Name')
    active = fields.Boolean(string='Active', default=True)

    @api.onchange('project_id')
    def _onchange_project_id(self):
        domain = {
            'milestone_id': [],
            'deliverable_id': [],
        }
        if self.project_id:
            if self.milestone_id and self.milestone_id.project_id != self.project_id:
                self.milestone_id = False
            if self.deliverable_id and self.deliverable_id.project_id != self.project_id:
                self.deliverable_id = False
            domain['milestone_id'] = [('project_id', '=', self.project_id.id)]
            if self.milestone_id:
                domain['deliverable_id'] = [('milestone_id', '=', self.milestone_id.id)]
            else:
                domain['deliverable_id'] = [('project_id', '=', self.project_id.id)]
        else:
            self.milestone_id = False
            self.deliverable_id = False
        return {'domain': domain}

    @api.onchange('milestone_id')
    def _onchange_milestone_id(self):
        if self.milestone_id:
            if not self.project_id or self.project_id != self.milestone_id.project_id:
                self.project_id = self.milestone_id.project_id
            if self.deliverable_id and self.deliverable_id.milestone_id != self.milestone_id:
                self.deliverable_id = False
            return {'domain': {'deliverable_id': [('milestone_id', '=', self.milestone_id.id)]}}
        elif self.project_id:
            return {'domain': {'deliverable_id': [('project_id', '=', self.project_id.id)]}}
        else:
            return {'domain': {'deliverable_id': []}}

    @api.onchange('deliverable_id')
    def _onchange_deliverable_id(self):
        if self.deliverable_id:
            if self.deliverable_id.milestone_id:
                self.milestone_id = self.deliverable_id.milestone_id
            if self.deliverable_id.project_id:
                self.project_id = self.deliverable_id.project_id

    @api.onchange('result', 'test_date')
    def _onchange_result_or_date(self):
        if self.result or (self.test_date and self.test_date <= fields.Date.today()):
            if self.status != 'tested':
                self.status = 'tested'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code') or vals.get('code') == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('pm.test.case') or _('New')
            if vals.get('result') and not vals.get('status'):
                vals['status'] = 'tested'
        return super().create(vals_list)

    def unlink(self):
        """Soft delete: archive test case instead of permanent deletion."""
        return self.write({'active': False})


class PmTestResult(models.Model):
    _name = 'pm.test.result'
    _description = 'Test Case Execution Result'
    _order = 'execution_date desc, id desc'

    test_case_id = fields.Many2one('pm.test.case', string='Test Case', required=True, ondelete='cascade')
    project_id = fields.Many2one('pm.project', string='Project', related='test_case_id.project_id', store=True, readonly=True)
    milestone_id = fields.Many2one('pm.milestone', string='Milestone', related='test_case_id.milestone_id', store=True, readonly=True)
    deliverable_id = fields.Many2one('pm.deliverable', string='Deliverable', related='test_case_id.deliverable_id', store=True, readonly=True)

    execution_date = fields.Date(string='Execution Date', default=fields.Date.context_today, required=True)
    tester_id = fields.Many2one('res.users', string='Tested By', default=lambda self: self.env.user, required=True)
    status = fields.Selection([
        ('pass', 'Pass'),
        ('fail', 'Fail'),
        ('blocked', 'Blocked'),
        ('retest', 'Retest Needed')
    ], string='Execution Status', default='pass', required=True)

    actual_result = fields.Text(string='Actual Result')
    defect_notes = fields.Text(string='Defect / Remark Notes')
    evidence_attachment = fields.Binary(string='Evidence Screenshot / Log File')
    evidence_filename = fields.Char(string='Evidence File Name')
    active = fields.Boolean(string='Active', default=True)

    def unlink(self):
        """Soft delete: archive test result instead of permanent deletion."""
        return self.write({'active': False})

