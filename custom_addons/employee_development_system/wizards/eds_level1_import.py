# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import base64
import csv
import io
import re

try:
    import openpyxl
except ImportError:
    openpyxl = None


def _clean_str(s):
    return re.sub(r'[^a-z0-9\s]', '', (s or '').lower()).strip()


def _match_question_text(header_val, q_name):
    h_clean = _clean_str(header_val)
    q_clean = _clean_str(q_name)
    if not h_clean or not q_clean:
        return False
    if q_clean in h_clean or h_clean in q_clean:
        return True
    q_words = set(w for w in q_clean.split() if len(w) > 2)
    h_words = set(w for w in h_clean.split() if len(w) > 2)
    if not q_words or not h_words:
        return False
    intersection = q_words & h_words
    return (len(intersection) / float(len(q_words))) >= 0.5


class EdsLevel1Import(models.TransientModel):
    _name = 'eds.level1.import'
    _description = 'Bulk Level 1 Reaction Survey Import Wizard'

    session_id = fields.Many2one('eds.session', string='Default Session', help='Optional if session code is in file')
    csv_file = fields.Binary(string='Reaction Survey Responses (Excel / CSV)', required=True)
    filename = fields.Char(string='File Name')
    result_log = fields.Text(string='Import Summary', readonly=True)

    def action_download_template(self):
        """Return sample CSV template format."""
        sample_csv = (
            "session_ref,employee_badge,content_rating,trainer_rating,facilities_rating,comments\n"
            "SES/2026/0001,EMP001,5,5,4,Excellent practical case studies and clear delivery\n"
            "SES/2026/0001,EMP002,4,4,5,Good training pace, venue acoustics were great\n"
        )
        return {
            'type': 'ir.actions.act_url',
            'url': 'data:text/csv;charset=utf-8;base64,' + base64.b64encode(sample_csv.encode()).decode(),
            'target': 'self',
        }

    def action_import_level1(self):
        self.ensure_one()
        if not self.csv_file:
            raise ValidationError(_("Please select a feedback survey Excel or CSV file to import."))

        data = base64.b64decode(self.csv_file)
        if data.startswith(b'PK\x03\x04') or (self.filename and self.filename.lower().endswith(('.xlsx', '.xlsm'))):
            return self._import_excel_level1(data)
        else:
            return self._import_csv_level1(data)

    def _import_excel_level1(self, data):
        if not openpyxl:
            raise ValidationError(_("openpyxl library is required to import Excel feedback sheets."))

        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        except Exception as e:
            raise ValidationError(_("Failed to open Excel workbook: %s") % str(e))

        ws = None
        for name in ('Responses_Import', 'Google Form Responses', 'Form Responses 1', 'Sheet1'):
            if name in wb.sheetnames:
                ws = wb[name]
                break
        if not ws:
            ws = wb.worksheets[-1] if len(wb.worksheets) > 1 and wb.worksheets[0].title == 'Google_Form_Setup' else wb.active

        # Find header row with highest score
        header_row = 1
        best_score = -1
        for r in range(1, min(10, ws.max_row + 1)):
            score = 0
            for c in range(1, min(30, ws.max_column + 1)):
                v = str(ws.cell(r, c).value or '').strip().lower()
                if any(k in v for k in ('timestamp', 'badge', 'emp', 'trainer', 'content', 'venue', 'facility', 'question', 'comment', '[')):
                    score += 1
            if score > best_score and score >= 2:
                best_score = score
                header_row = r

        col_badge = None
        col_content = []
        col_trainer = []
        col_facility = []
        col_material = []
        col_overall = []
        col_comments = None
        col_question_map = {}

        # Resolve instrument questions if available
        session = self.session_id
        instrument = None
        if session:
            session._ensure_level1_instrument()
            instrument = session.level1_session_instrument_id
        if not instrument:
            instrument = self.env['eds.evaluation.instrument'].search([
                ('instrument_type', '=', 'level1'),
                ('state', '=', 'published'),
            ], limit=1) or self.env['eds.evaluation.instrument'].search([
                ('instrument_type', '=', 'level1'),
            ], limit=1)

        for c in range(1, min(40, ws.max_column + 1)):
            raw_val = str(ws.cell(header_row, c).value or '').strip()
            val = raw_val.lower()
            if not val or val == 'timestamp':
                continue

            matched_q = False
            if instrument and instrument.question_ids:
                for q in instrument.question_ids:
                    if q.id in col_question_map:
                        continue
                    q_text = getattr(q, 'name', None) or getattr(q, 'question_text', '') or ''
                    cat_tag = f"[{q.category}]"
                    if _match_question_text(raw_val, q_text) or (cat_tag in val):
                        col_question_map[q.id] = c
                        matched_q = True
                        break

            if matched_q:
                continue

            if col_badge is None and (any(k in val for k in ('badge', 'emp id', 'employee id', 'staff id')) or val in ('id', 'emp')):
                col_badge = c
            elif col_comments is None and any(k in val for k in ('comment', 'suggestion', 'feedback', 'remark')):
                col_comments = c
            elif any(k in val for k in ('[trainer]', 'trainer', 'instructor', 'facilitator')):
                col_trainer.append(c)
            elif any(k in val for k in ('[content]', 'content', 'relevance', 'objective')):
                col_content.append(c)
            elif any(k in val for k in ('[venue]', 'venue', 'facility', 'facilities', 'logistics', 'hotel')):
                col_facility.append(c)
            elif any(k in val for k in ('[material]', 'material', 'methodology', 'handout')):
                col_material.append(c)
            elif any(k in val for k in ('[overall]', 'overall', 'satisfaction', '[impact]')):
                col_overall.append(c)

        rows = []
        for r in range(header_row + 1, ws.max_row + 1):
            badge = str(ws.cell(r, col_badge).value or '').strip() if col_badge else ''
            comments = str(ws.cell(r, col_comments).value or '').strip() if col_comments else ''

            question_scores = {}
            for q_id, c in col_question_map.items():
                cell_val = ws.cell(r, c).value
                if cell_val is not None and str(cell_val).strip() != '':
                    question_scores[q_id] = cell_val

            def get_col_val(col_list):
                for c in col_list:
                    v = ws.cell(r, c).value
                    if v is not None and str(v).strip() != '':
                        return v
                return None

            content = get_col_val(col_content)
            trainer = get_col_val(col_trainer)
            facility = get_col_val(col_facility)
            material = get_col_val(col_material)
            overall = get_col_val(col_overall)

            if not any([badge, content, trainer, facility, material, overall, comments, question_scores]):
                continue

            rows.append({
                'line_no': r,
                'session_ref': '',
                'badge': badge,
                'content': content,
                'trainer': trainer,
                'facility': facility,
                'material': material,
                'overall': overall,
                'comments': comments,
                'question_scores': question_scores,
            })

        return self._process_level1_rows(rows)

    def _import_csv_level1(self, data):
        try:
            file_input = io.StringIO(data.decode('utf-8-sig'))
            reader = csv.DictReader(file_input)
        except Exception as e:
            raise ValidationError(_("Failed to read CSV file: %s") % str(e))

        session = self.session_id
        instrument = None
        if session:
            session._ensure_level1_instrument()
            instrument = session.level1_session_instrument_id
        if not instrument:
            instrument = self.env['eds.evaluation.instrument'].search([
                ('instrument_type', '=', 'level1'),
                ('state', '=', 'published'),
            ], limit=1) or self.env['eds.evaluation.instrument'].search([
                ('instrument_type', '=', 'level1'),
            ], limit=1)

        fieldnames = reader.fieldnames or []
        col_question_map = {}
        col_badge = None
        col_comments = None

        if instrument and instrument.question_ids:
            for field in fieldnames:
                f_val = str(field).strip()
                for q in instrument.question_ids:
                    if q.id in col_question_map:
                        continue
                    q_text = getattr(q, 'name', None) or getattr(q, 'question_text', '') or ''
                    if _match_question_text(f_val, q_text):
                        col_question_map[q.id] = field
                        break

        for field in fieldnames:
            f_lower = str(field).strip().lower()
            if col_badge is None and (any(k in f_lower for k in ('badge', 'emp id', 'employee id', 'staff id')) or f_lower in ('id', 'emp')):
                col_badge = field
            elif col_comments is None and any(k in f_lower for k in ('comment', 'suggestion', 'feedback', 'remark')):
                col_comments = field

        rows = []
        for line_no, row in enumerate(reader, start=2):
            session_ref = row.get('session_ref', '').strip()
            badge = (row.get(col_badge) if col_badge else None) or (row.get('employee_badge') or row.get('employee_id') or row.get('badge') or '').strip()
            content = row.get('content_rating') or row.get('content')
            trainer = row.get('trainer_rating') or row.get('trainer')
            facility = row.get('facilities_rating') or row.get('venue_rating') or row.get('facility')
            comments = (row.get(col_comments) if col_comments else None) or (row.get('comments') or row.get('comment') or '').strip()

            question_scores = {}
            for q_id, f_name in col_question_map.items():
                val = row.get(f_name)
                if val is not None and str(val).strip() != '':
                    question_scores[q_id] = val

            rows.append({
                'line_no': line_no,
                'session_ref': session_ref,
                'badge': badge,
                'content': content,
                'trainer': trainer,
                'facility': facility,
                'material': None,
                'overall': None,
                'comments': comments,
                'question_scores': question_scores,
            })

        return self._process_level1_rows(rows)

    def _process_level1_rows(self, rows):
        success_count = 0
        skipped_count = 0
        errors = []

        Level1Model = self.env['eds.evaluation.level1'].sudo()
        EmployeeModel = self.env['hr.employee'].sudo()
        SessionModel = self.env['eds.session'].sudo()

        session = self.session_id
        instrument = None
        if session:
            session._ensure_level1_instrument()
            instrument = session.level1_session_instrument_id

        if not instrument:
            instrument = self.env['eds.evaluation.instrument'].search([
                ('instrument_type', '=', 'level1'),
                ('state', '=', 'published'),
            ], limit=1) or self.env['eds.evaluation.instrument'].search([
                ('instrument_type', '=', 'level1'),
            ], limit=1)

        q_map = {}
        if instrument:
            for q in instrument.question_ids:
                q_map[q.category] = q

        # Pool of enrolled participants to assign anonymous submissions to
        available_enrolled_emps = []
        if session:
            enrolled_emps = session.enrollment_ids.filtered(
                lambda e: e.state in ('enrolled', 'completed', 'attended', 'suggested')
            ).mapped('employee_id')
            already_evaluated = Level1Model.search([('session_id', '=', session.id)]).mapped('employee_id')
            available_enrolled_emps = list(enrolled_emps - already_evaluated)

        for item in rows:
            line_no = item['line_no']
            session_ref = item['session_ref']
            badge = item['badge']
            comments = item['comments']

            sess = session
            if session_ref:
                sess = SessionModel.search([('name', '=', session_ref)], limit=1) or sess

            if not sess:
                errors.append(_("Row %d: Training session not specified or found.") % line_no)
                skipped_count += 1
                continue

            employee = None
            if badge:
                if badge.isdigit():
                    employee = EmployeeModel.browse(int(badge)).exists()
                if not employee:
                    employee = EmployeeModel.search([
                        '|', '|',
                        ('identification_id', '=', badge),
                        ('barcode', '=', badge),
                        ('name', '=ilike', badge)
                    ], limit=1)

            if not employee:
                # If anonymous submission from Google Form, assign to next available participant in session
                if available_enrolled_emps:
                    employee = available_enrolled_emps.pop(0)
                elif sess.enrollment_ids:
                    employee = sess.enrollment_ids[:1].employee_id
                else:
                    errors.append(_("Row %d: Could not resolve participant for feedback.") % line_no)
                    skipped_count += 1
                    continue

            def parse_rating(val):
                if val in (None, ''):
                    return 5
                try:
                    r = int(float(val))
                    return max(1, min(5, r))
                except (ValueError, TypeError):
                    return 5

            content_r = parse_rating(item.get('content'))
            trainer_r = parse_rating(item.get('trainer'))
            fac_r = parse_rating(item.get('facility'))
            overall_r = parse_rating(item.get('overall') or item.get('material'))
            q_scores = item.get('question_scores') or {}

            existing_eval = Level1Model.search([
                ('session_id', '=', sess.id),
                ('employee_id', '=', employee.id),
            ], limit=1)

            line_commands = []
            if instrument and instrument.question_ids:
                for q in instrument.question_ids:
                    if q.id in q_scores:
                        line_commands.append((0, 0, {'question_id': q.id, 'rating_val': parse_rating(q_scores[q.id])}))
                    elif q.category == 'content' and item.get('content') is not None:
                        line_commands.append((0, 0, {'question_id': q.id, 'rating_val': content_r}))
                    elif q.category == 'trainer' and item.get('trainer') is not None:
                        line_commands.append((0, 0, {'question_id': q.id, 'rating_val': trainer_r}))
                    elif q.category == 'venue' and item.get('facility') is not None:
                        line_commands.append((0, 0, {'question_id': q.id, 'rating_val': fac_r}))
                    elif q.category in ('objective', 'impact') and (item.get('overall') is not None or item.get('material') is not None):
                        line_commands.append((0, 0, {'question_id': q.id, 'rating_val': overall_r}))
                    else:
                        fallback_r = content_r if q.category == 'content' else (trainer_r if q.category == 'trainer' else (fac_r if q.category == 'venue' else overall_r))
                        line_commands.append((0, 0, {'question_id': q.id, 'rating_val': fallback_r}))
            else:
                if 'content' in q_map:
                    line_commands.append((0, 0, {'question_id': q_map['content'].id, 'rating_val': content_r}))
                if 'trainer' in q_map:
                    line_commands.append((0, 0, {'question_id': q_map['trainer'].id, 'rating_val': trainer_r}))
                if 'venue' in q_map:
                    line_commands.append((0, 0, {'question_id': q_map['venue'].id, 'rating_val': fac_r}))

            vals = {
                'session_id': sess.id,
                'employee_id': employee.id,
                'instrument_id': instrument.id if instrument else False,
                'general_comments': comments,
                'state': 'submitted',
                'submitted_date': fields.Date.context_today(self),
            }
            if line_commands:
                vals['line_ids'] = line_commands

            if existing_eval:
                existing_eval.line_ids.unlink()
                existing_eval.sudo().write(vals)
            else:
                Level1Model.sudo().create(vals)
            success_count += 1

        summary = _("Import Complete:\n• Successfully imported: %d survey feedback responses\n• Skipped/Errors: %d records\n") % (
            success_count, skipped_count
        )
        if errors:
            summary += "\nErrors / Warnings:\n" + "\n".join(errors[:20])

        self.env['eds.integration.log'].create({
            'name': f"L1-IMP-{fields.Date.today()}",
            'system': 'pms',
            'direction': 'inbound',
            'status': 'success' if skipped_count == 0 else 'retry',
            'details': summary,
        })

        self.write({'result_log': summary})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Level 1 Survey Import Result'),
            'res_model': 'eds.level1.import',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
