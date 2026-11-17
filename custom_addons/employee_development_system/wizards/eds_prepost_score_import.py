# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import base64
import csv
import io

try:
    import openpyxl
except ImportError:
    openpyxl = None


class EdsPrePostScoreImport(models.TransientModel):
    _name = 'eds.prepost.score.import'
    _description = 'Bulk Pre/Post Assessment Scores Import Wizard'

    session_id = fields.Many2one('eds.session', string='Training Session', required=True)
    file = fields.Binary(string='Scores File (Excel or CSV)', required=True)
    filename = fields.Char(string='File Name')
    result_log = fields.Text(string='Import Summary', readonly=True)

    def action_import_scores(self):
        self.ensure_one()
        if not self.file:
            raise ValidationError(_("Please select an Excel or CSV file to import."))

        data = base64.b64decode(self.file)
        if data.startswith(b'PK\x03\x04') or (self.filename and self.filename.lower().endswith(('.xlsx', '.xlsm'))):
            return self._import_excel(data)
        else:
            return self._import_csv(data)

    def _import_excel(self, data):
        if not openpyxl:
            raise ValidationError(_("The openpyxl library is required to import Excel score sheets."))

        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        except Exception as e:
            raise ValidationError(_("Failed to open Excel workbook: %s") % str(e))

        ws = wb.active
        # Find header row
        header_row = 7
        col_id = 1
        col_name = 2
        col_total = 6
        col_pre = 7
        col_post = 8
        col_remarks = 9

        for r in range(1, min(15, ws.max_row + 1)):
            for c in range(1, min(15, ws.max_column + 1)):
                val = str(ws.cell(r, c).value or '').strip().lower()
                if 'employee id' in val or 'emp id' in val or 'badge' in val:
                    col_id = c
                    header_row = r
                elif 'pre' in val and ('score' in val or 'test' in val or 'mark' in val or 'value' in val):
                    col_pre = c
                    header_row = r
                elif 'post' in val and ('score' in val or 'test' in val or 'mark' in val or 'value' in val):
                    col_post = c
                    header_row = r
                elif 'total' in val and ('mark' in val or 'score' in val or 'max' in val):
                    col_total = c
                elif 'remark' in val or 'comment' in val:
                    col_remarks = c

        rows_data = []
        for r in range(header_row + 1, ws.max_row + 1):
            emp_id_val = ws.cell(r, col_id).value
            emp_name_val = ws.cell(r, col_name).value if col_name else ''
            pre_val = ws.cell(r, col_pre).value if col_pre else None
            post_val = ws.cell(r, col_post).value if col_post else None
            total_val = ws.cell(r, col_total).value if col_total else None
            rem_val = ws.cell(r, col_remarks).value if col_remarks else ''

            if not emp_id_val and not emp_name_val and pre_val is None and post_val is None:
                continue

            rows_data.append({
                'line_no': r,
                'employee_key': str(emp_id_val or '').strip(),
                'employee_name': str(emp_name_val or '').strip(),
                'pre_score': pre_val,
                'post_score': post_val,
                'total_marks': total_val,
                'remarks': str(rem_val or '').strip(),
            })

        return self._process_score_rows(rows_data)

    def _import_csv(self, data):
        try:
            file_input = io.StringIO(data.decode('utf-8-sig'))
            reader = csv.DictReader(file_input)
        except Exception as e:
            raise ValidationError(_("Failed to read CSV file: %s") % str(e))

        rows_data = []
        for line_no, row in enumerate(reader, start=2):
            emp_key = (row.get('employee_id') or row.get('employee_badge') or row.get('badge') or row.get('Employee ID') or '').strip()
            emp_name = (row.get('employee_name') or row.get('name') or row.get('Employee Name') or '').strip()
            pre_val = row.get('pre_test_score') or row.get('pre_score') or row.get('Pre-Test Score')
            post_val = row.get('post_test_score') or row.get('post_score') or row.get('Post-Test Score')
            total_val = row.get('total_marks') or row.get('Total Marks')
            remarks = (row.get('remarks') or row.get('Remarks') or row.get('comments') or '').strip()

            if not emp_key and not emp_name:
                continue

            rows_data.append({
                'line_no': line_no,
                'employee_key': emp_key,
                'employee_name': emp_name,
                'pre_score': pre_val,
                'post_score': post_val,
                'total_marks': total_val,
                'remarks': remarks,
            })

        return self._process_score_rows(rows_data)

    def _process_score_rows(self, rows_data):
        session = self.session_id
        session.action_prepare_level2_scores()

        EvaluationModel = self.env['eds.evaluation.level2'].sudo()
        EmployeeModel = self.env['hr.employee'].sudo()

        success_count = 0
        skipped_count = 0
        errors = []

        existing_scores = {
            rec.employee_id.id: rec
            for rec in session.level2_score_ids
        }

        for item in rows_data:
            line_no = item['line_no']
            emp_key = item['employee_key']
            emp_name = item['employee_name']

            employee = None
            if emp_key:
                # Try ID, barcode, identification_id
                if emp_key.isdigit():
                    employee = EmployeeModel.browse(int(emp_key)).exists()
                if not employee:
                    employee = EmployeeModel.search([
                        '|', ('barcode', '=', emp_key), ('identification_id', '=', emp_key)
                    ], limit=1)

            if not employee and emp_name:
                employee = EmployeeModel.search([('name', '=ilike', emp_name)], limit=1)

            if not employee:
                errors.append(_("Row %d: Employee '%s' not found.") % (line_no, emp_key or emp_name))
                skipped_count += 1
                continue

            score_rec = existing_scores.get(employee.id)
            if not score_rec:
                score_rec = EvaluationModel.create({
                    'session_id': session.id,
                    'employee_id': employee.id,
                    'score_entry_mode': True,
                    'total_marks': session.assessment_max_marks,
                })
                existing_scores[employee.id] = score_rec

            if score_rec.score_confirmed:
                errors.append(_("Row %d: Employee '%s' scores are already confirmed.") % (line_no, employee.name))
                skipped_count += 1
                continue

            vals = {}
            if item['total_marks'] not in (None, ''):
                try:
                    vals['total_marks'] = float(item['total_marks'])
                except (ValueError, TypeError):
                    pass

            if item['pre_score'] not in (None, ''):
                try:
                    vals['pre_test_score'] = float(item['pre_score'])
                    vals['pre_score_entered'] = True
                except (ValueError, TypeError):
                    errors.append(_("Row %d: Invalid pre-test score '%s'.") % (line_no, item['pre_score']))

            if item['post_score'] not in (None, ''):
                try:
                    vals['post_test_score'] = float(item['post_score'])
                    vals['post_score_entered'] = True
                except (ValueError, TypeError):
                    errors.append(_("Row %d: Invalid post-test score '%s'.") % (line_no, item['post_score']))

            if item['remarks']:
                vals['remarks'] = item['remarks']

            if vals:
                score_rec.write(vals)
                success_count += 1
            else:
                skipped_count += 1

        summary = _("Import Complete:\n• Successfully updated: %d participant scores\n• Skipped/Errors: %d records\n") % (
            success_count, skipped_count
        )
        if errors:
            summary += "\nErrors / Warnings:\n" + "\n".join(errors[:20])

        self.write({'result_log': summary})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
