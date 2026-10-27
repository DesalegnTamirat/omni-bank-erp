# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import ValidationError
import base64
import csv
import io
from datetime import datetime

try:
    import openpyxl
except ImportError:
    openpyxl = None


class EdsAttendanceImport(models.TransientModel):
    _name = 'eds.attendance.import'
    _description = 'Bulk Attendance Import Wizard'

    session_id = fields.Many2one('eds.session', string='Default Session', help='Optional if session code is in file')
    csv_file = fields.Binary(string='Attendance Sheet (CSV or Excel .xlsx)', required=True)
    filename = fields.Char(string='File Name')
    result_log = fields.Text(string='Import Summary', readonly=True)

    def action_download_template(self):
        """Return sample CSV template format."""
        sample_csv = (
            "session_ref,employee_badge,attendance_date,attendance_slot,attended,notes\n"
            "SES/2026/0001,EMP001,2026-10-12,day,Present,Present on time\n"
            "SES/2026/0001,EMP002,2026-10-12,day,Absent,Sick leave\n"
        )
        return {
            'type': 'ir.actions.act_url',
            'url': 'data:text/csv;charset=utf-8;base64,' + base64.b64encode(sample_csv.encode()).decode(),
            'target': 'self',
        }

    def action_import_attendance(self):
        self.ensure_one()
        if not self.csv_file:
            raise ValidationError(_("Please select an attendance CSV or Excel file to import."))

        data = base64.b64decode(self.csv_file)
        # Check if Excel XLSX (ZIP magic bytes PK\x03\x04)
        if data.startswith(b'PK\x03\x04') or (self.filename and self.filename.lower().endswith(('.xlsx', '.xlsm'))):
            return self._import_excel_attendance(data)
        else:
            return self._import_csv_attendance(data)

    def _import_excel_attendance(self, data):
        if not openpyxl:
            raise ValidationError(_("openpyxl Python library is required to import Excel attendance sheets."))

        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        except Exception as e:
            raise ValidationError(_("Failed to open Excel workbook: %s") % str(e))

        if wb.worksheets and str(wb.worksheets[0].cell(7, 1).value or '').strip() == 'Employee ID':
            return self._import_eds_roster(wb.worksheets[0])

        AttendanceModel = self.env['eds.session.attendance']
        EmployeeModel = self.env['hr.employee'].sudo()
        SessionModel = self.env['eds.session']

        success_count = 0
        skipped_count = 0
        errors = []
        accepted_ids_by_session = {}

        for sname in wb.sheetnames:
            ws = wb[sname]
            if ws.max_row < 6:
                continue

            # Detect Session from Title in rows 1-6
            session = self.session_id
            if not session:
                for r in range(1, min(7, ws.max_row + 1)):
                    for c in range(1, min(5, ws.max_column + 1)):
                        val = str(ws.cell(r, c).value or '').strip()
                        if 'training title' in val.lower() or 'program' in val.lower():
                            parts = val.split(':', 1)
                            title_candidate = parts[1].strip() if len(parts) > 1 else val
                            # Search session by course name or session name
                            found_s = SessionModel.search([
                                '|',
                                ('name', '=ilike', title_candidate),
                                ('course_id.name', '=ilike', title_candidate),
                            ], limit=1)
                            if found_s:
                                session = found_s
                                break
                    if session:
                        break

            if not session:
                session = self.session_id

            # Find participant header row
            header_row = None
            col_name = None
            col_id = None
            slot_cols = []

            for r in range(1, min(12, ws.max_row + 1)):
                row_texts = {c: str(ws.cell(r, c).value or '').strip().lower() for c in range(1, ws.max_column + 1)}
                for c, text in row_texts.items():
                    if any(k in text for k in ('badge', 'emp id', 'employee id', 'staff id')) or text in ('id', 'code'):
                        col_id = c
                        header_row = r
                    elif any(k in text for k in ('participant', 'trainee', 'staff name', 'full name', 'employee name')) or ('name' in text and not col_name):
                        col_name = c
                        header_row = r
                    elif 'employee' in text and not col_id and not col_name:
                        col_name = c
                        header_row = r
                if header_row and (col_name or col_id):
                    break

            if not header_row:
                continue

            # Look for morning/afternoon slots in rows header_row, header_row+1, header_row+2
            for check_r in range(header_row, min(header_row + 3, ws.max_row + 1)):
                for c in range(1, ws.max_column + 1):
                    val = str(ws.cell(check_r, c).value or '').strip().lower()
                    if val in ('morning', 'afternoon', 'signature', 'present') and c not in slot_cols:
                        slot_cols.append(c)

            if not slot_cols:
                # Default slot cols to any columns to the right of Name/ID
                min_slot_c = max(col_name or 2, col_id or 2) + 1
                slot_cols = list(range(min_slot_c, min(min_slot_c + 6, ws.max_column + 1)))

            # Read participants
            for r in range(header_row + 1, ws.max_row + 1):
                p_name = str(ws.cell(r, col_name or 2).value or '').strip() if col_name else ''
                p_id = str(ws.cell(r, col_id or 3).value or '').strip() if col_id else ''

                if not p_name and not p_id:
                    continue
                # Skip sub-headers or footers
                if any(k in p_name.lower() for k in ('name of', 'morning', 'afternoon', 'signature', 'facilitated', 'prepared', 'approved')):
                    continue

                # Match employee
                emp = False
                if p_id:
                    emp = EmployeeModel.search([
                        '|',
                        ('identification_id', '=ilike', p_id),
                        ('barcode', '=ilike', p_id)
                    ], limit=1)
                if not emp and p_name:
                    emp = EmployeeModel.search([('name', '=ilike', p_name)], limit=1)

                if not emp:
                    errors.append(_("Sheet '%s' Row %d: Employee '%s' (%s) not found.") % (sname, r, p_name, p_id))
                    skipped_count += 1
                    continue

                if not session:
                    errors.append(_("Sheet '%s': No session mapped for participant %s.") % (sname, emp.name))
                    skipped_count += 1
                    continue

                if session.id not in accepted_ids_by_session:
                    accepted_ids_by_session[session.id] = set(
                        session._accepted_attendance_enrollments().mapped('employee_id').ids)
                if emp.id not in accepted_ids_by_session[session.id]:
                    errors.append(_("Sheet '%s' Row %d: %s has not accepted this session.")
                                  % (sname, r, emp.name))
                    skipped_count += 1
                    continue

                configured_slots = session._attendance_slots()
                if session.attendance_mode == 'split':
                    if len(slot_cols) != len(configured_slots):
                        raise ValidationError(_(
                            'The morning/afternoon columns do not match this session schedule. '
                            'Export its attendance sheet and mark that sheet instead.'))
                    marks = [(column, day, slot) for column, (day, slot, _hours)
                             in zip(slot_cols, configured_slots)]
                else:
                    # Legacy sign-in sheets have no dated slot headers. Their signatures
                    # represent the first scheduled daily attendance mark only.
                    marks = [(slot_cols, configured_slots[0][0], 'day')] if configured_slots else []
                for source, day, slot in marks:
                    values = [ws.cell(r, column).value for column in source] if isinstance(source, list) else [ws.cell(r, source).value]
                    if not any(value is not None and str(value).strip() for value in values):
                        continue
                    attended = any(str(value or '').strip().casefold() not in
                                   ('', '0', 'absent', 'a', 'false', 'no') for value in values)
                    existing = AttendanceModel.search([
                        ('session_id', '=', session.id), ('employee_id', '=', emp.id),
                        ('attendance_date', '=', day), ('attendance_slot', '=', slot),
                    ], limit=1)
                    if existing:
                        existing.attended = attended
                    else:
                        AttendanceModel.create({
                            'session_id': session.id, 'employee_id': emp.id,
                            'attendance_date': day, 'attendance_slot': slot,
                            'attended': attended,
                        })
                    success_count += 1

        summary = _("Excel Import Completed: %d participant attendance records processed, %d skipped.") % (success_count, skipped_count)
        if errors:
            summary += "\n\n" + _("Details:\n") + "\n".join(errors[:25])
        self.result_log = summary

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'eds.attendance.import',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _import_eds_roster(self, sheet):
        """Round-trip the dated XLSX sheet exported from a session."""
        session_ref = str(sheet.cell(2, 2).value or '').strip()
        session = self.session_id or self.env['eds.session'].search([('name', '=', session_ref)], limit=1)
        if not session or session.name != session_ref:
            raise ValidationError(_('The attendance sheet does not match the selected session.'))
        dated_columns = []
        for column in range(6, sheet.max_column + 1):
            raw = sheet.cell(7, column).value
            if not raw:
                continue
            if isinstance(raw, datetime):
                attendance_date = raw.date()
            else:
                try:
                    attendance_date = fields.Date.to_date(raw)
                except (TypeError, ValueError):
                    raise ValidationError(_('Column %s has an invalid attendance date.') % column)
            if not attendance_date:
                raise ValidationError(_('Column %s has an invalid attendance date.') % column)
            slot_label = str(sheet.cell(6, column).value or 'Daily').strip().casefold()
            slot = {'daily': 'day', 'day': 'day', 'morning': 'morning',
                    'afternoon': 'afternoon'}.get(slot_label)
            if not slot:
                raise ValidationError(_('Column %s has an invalid attendance period.') % column)
            dated_columns.append((column, attendance_date, slot))
        if not dated_columns:
            raise ValidationError(_('Add at least one dated attendance column.'))
        expected = {(day, slot) for day, slot, _hours in session._attendance_slots()}
        actual = [(day, slot) for _column, day, slot in dated_columns]
        if set(actual) != expected or len(actual) != len(expected):
            raise ValidationError(_(
                'The attendance dates or periods do not match this session schedule. '
                'Export a fresh attendance sheet.'))

        eligible = set(session._accepted_attendance_enrollments().mapped('employee_id').ids)
        attendance_model = self.env['eds.session.attendance'].with_context(
            eds_defer_attendance_refresh=True)
        existing = {(record.employee_id.id, record.attendance_date, record.attendance_slot): record
                    for record in attendance_model.search([('session_id', '=', session.id)])}
        new_records = []
        seen_employees = set()
        processed = 0
        for row in range(8, sheet.max_row + 1):
            raw_id = sheet.cell(row, 1).value
            if raw_id in (None, ''):
                continue
            try:
                employee_id = int(raw_id)
            except (TypeError, ValueError):
                raise ValidationError(_('Row %s has an invalid employee ID.') % row)
            if employee_id not in eligible:
                raise ValidationError(_('Row %s employee is not enrolled in this session.') % row)
            if employee_id in seen_employees:
                raise ValidationError(_('Employee ID %s appears more than once in the sheet.') % employee_id)
            seen_employees.add(employee_id)
            for column, attendance_date, slot in dated_columns:
                raw = sheet.cell(row, column).value
                if raw in (None, ''):
                    continue
                value = str(raw).strip().casefold()
                if value in ('present', 'p', 'yes', 'y', '1', 'true'):
                    attended = True
                elif value in ('absent', 'a', 'no', 'n', '0', 'false'):
                    attended = False
                else:
                    raise ValidationError(_('Row %s, column %s must say Present or Absent.') % (row, column))
                key = (employee_id, attendance_date, slot)
                if key in existing:
                    existing[key].attended = attended
                else:
                    new_records.append({
                        'session_id': session.id, 'employee_id': employee_id,
                        'attendance_date': attendance_date, 'attendance_slot': slot,
                        'attended': attended,
                    })
                processed += 1
        if new_records:
            attendance_model.create(new_records)
        if seen_employees:
            self.env['eds.session.attendance']._refresh_program_attendance({
                (employee_id, session.id) for employee_id in seen_employees})
        self.result_log = _('%s dated attendance cells imported for session %s.') % (processed, session.name)
        return {
            'type': 'ir.actions.act_window', 'res_model': 'eds.attendance.import',
            'res_id': self.id, 'view_mode': 'form', 'target': 'new',
        }

    def _import_csv_attendance(self, data):
        try:
            file_input = io.StringIO(data.decode('utf-8-sig'))
            reader = csv.DictReader(file_input)
        except Exception as e:
            raise ValidationError(_("Failed to read CSV file: %s") % str(e))

        success_count = 0
        skipped_count = 0
        errors = []
        AttendanceModel = self.env['eds.session.attendance'].with_context(
            eds_defer_attendance_refresh=True)
        EmployeeModel = self.env['hr.employee'].sudo()
        SessionModel = self.env['eds.session']

        rows = list(reader)
        session_refs = set(r.get('session_ref', '').strip() for r in rows if r.get('session_ref', '').strip())
        badges = set(r.get('employee_badge', '').strip() for r in rows if r.get('employee_badge', '').strip())

        # Pre-fetch sessions
        session_map = {}
        if session_refs:
            for s in SessionModel.search([('name', 'in', list(session_refs))]):
                session_map[s.name] = s
        if self.session_id:
            session_map[self.session_id.name] = self.session_id

        # Pre-fetch employees
        employee_map = {}
        if badges:
            emps = EmployeeModel.search([
                '|', '|',
                ('identification_id', 'in', list(badges)),
                ('barcode', 'in', list(badges)),
                ('name', 'in', list(badges)),
            ])
            for emp in emps:
                if emp.identification_id:
                    employee_map[emp.identification_id] = emp
                if emp.barcode:
                    employee_map[emp.barcode] = emp
                if emp.name:
                    employee_map[emp.name] = emp

        session_ids = [s.id for s in session_map.values()]
        existing_att_map = {}
        if session_ids:
            for att in AttendanceModel.search([('session_id', 'in', session_ids)]):
                existing_att_map[(att.session_id.id, att.employee_id.id,
                                  att.attendance_date, att.attendance_slot)] = att

        new_vals_list = []
        seen_keys = set()
        affected_pairs = set()
        allowed_slots = {session.id: {(day, slot) for day, slot, _hours
                                      in session._attendance_slots()}
                         for session in session_map.values()}
        accepted_employee_ids = {
            session.id: set(session._accepted_attendance_enrollments().mapped('employee_id').ids)
            for session in session_map.values()
        }
        for line_no, row in enumerate(rows, start=2):
            session_ref = row.get('session_ref', '').strip()
            badge = row.get('employee_badge', '').strip()
            date_str = row.get('attendance_date', '').strip()
            slot = row.get('attendance_slot', '').strip().casefold()
            attended_str = row.get('attended', '').strip().lower()

            session = session_map.get(session_ref) or self.session_id
            if not session:
                errors.append(_("Row %d: Session '%s' not found.") % (line_no, session_ref))
                skipped_count += 1
                continue

            employee = employee_map.get(badge)
            if not employee:
                errors.append(_("Row %d: Employee '%s' not found.") % (line_no, badge))
                skipped_count += 1
                continue

            if employee.id not in accepted_employee_ids.get(session.id, set()):
                errors.append(_('Row %d: Employee %s has not accepted this session.')
                              % (line_no, employee.name))
                skipped_count += 1
                continue

            try:
                att_date = (datetime.strptime(date_str, '%Y-%m-%d').date()
                            if date_str else None)
            except ValueError:
                try:
                    att_date = datetime.strptime(date_str, '%d/%m/%Y').date()
                except ValueError:
                    errors.append(_('Row %d has an invalid attendance date.') % line_no)
                    skipped_count += 1
                    continue
            if not att_date:
                errors.append(_('Row %d needs an attendance date.') % line_no)
                skipped_count += 1
                continue
            if not slot:
                slot = 'day'
            if (att_date, slot) not in allowed_slots.get(session.id, set()):
                errors.append(_(
                    'Row %d date or period does not match the session attendance schedule.') % line_no)
                skipped_count += 1
                continue
            if attended_str in ('1', 'true', 'yes', 'present', 'y', 'p'):
                is_attended = True
            elif attended_str in ('0', 'false', 'no', 'absent', 'n', 'a'):
                is_attended = False
            else:
                errors.append(_('Row %d must say Present or Absent.') % line_no)
                skipped_count += 1
                continue
            key = (session.id, employee.id, att_date, slot)
            if key in seen_keys:
                errors.append(_('Row %d repeats an attendance mark in this file.') % line_no)
                skipped_count += 1
                continue
            seen_keys.add(key)
            affected_pairs.add((employee.id, session.id))
            existing_att = existing_att_map.get(key)
            if existing_att:
                existing_att.write({
                    'attended': is_attended,
                    'notes': row.get('notes', '').strip(),
                })
                success_count += 1
            else:
                new_vals_list.append({
                    'session_id': session.id,
                    'employee_id': employee.id,
                    'attendance_date': att_date,
                    'attendance_slot': slot,
                    'attended': is_attended,
                    'notes': row.get('notes', '').strip(),
                })
                success_count += 1

        if new_vals_list:
            AttendanceModel.create(new_vals_list)
        if affected_pairs:
            self.env['eds.session.attendance']._refresh_program_attendance(affected_pairs)

        summary = _("CSV Import Completed: %d attendance records processed, %d skipped.") % (success_count, skipped_count)
        if errors:
            summary += "\n\n" + _("Details:\n") + "\n".join(errors[:20])
        self.result_log = summary

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'eds.attendance.import',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
