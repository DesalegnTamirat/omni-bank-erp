# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import base64
import csv
import io
from datetime import datetime

class EdsAttendanceImport(models.TransientModel):
    _name = 'eds.attendance.import'
    _description = 'Bulk Attendance Import Wizard'

    session_id = fields.Many2one('eds.session', string='Default Session', help='Optional if session code is in CSV')
    csv_file = fields.Binary(string='Attendance Sheet (CSV)', required=True)
    filename = fields.Char(string='File Name')
    result_log = fields.Text(string='Import Summary', readonly=True)

    def action_download_template(self):
        """Return sample CSV template format."""
        sample_csv = (
            "session_ref,employee_badge,attendance_date,attended,notes\n"
            "SES/2026/0001,EMP001,2026-10-12,1,Present on time\n"
            "SES/2026/0001,EMP002,2026-10-12,0,Sick leave\n"
        )
        return {
            'type': 'ir.actions.act_url',
            'url': 'data:text/csv;charset=utf-8;base64,' + base64.b64encode(sample_csv.encode()).decode(),
            'target': 'self',
        }

    def action_import_attendance(self):
        self.ensure_one()
        if not self.csv_file:
            raise ValidationError(_("Please select an attendance CSV file to import."))

        try:
            data = base64.b64decode(self.csv_file)
            file_input = io.StringIO(data.decode('utf-8-sig'))
            reader = csv.DictReader(file_input)
        except Exception as e:
            raise ValidationError(_("Failed to read CSV file: %s") % str(e))

        success_count = 0
        skipped_count = 0
        errors = []

        AttendanceModel = self.env['eds.session.attendance']
        EmployeeModel = self.env['hr.employee']
        SessionModel = self.env['eds.session']

        for line_no, row in enumerate(reader, start=2):
            session_ref = row.get('session_ref', '').strip()
            badge = row.get('employee_badge', '').strip()
            date_str = row.get('attendance_date', '').strip()
            attended_str = row.get('attended', '').strip().lower()
            notes = row.get('notes', '').strip()

            # Resolve session
            session = None
            if session_ref:
                session = SessionModel.search([('name', '=', session_ref)], limit=1)
            elif self.session_id:
                session = self.session_id

            if not session:
                errors.append(_("Row %d: Session '%s' not found.") % (line_no, session_ref))
                skipped_count += 1
                continue

            # Resolve employee by badge (identification_id or barcode) or name
            employee = EmployeeModel.search([
                '|', '|',
                ('identification_id', '=', badge),
                ('barcode', '=', badge),
                ('name', '=', badge)
            ], limit=1)

            if not employee:
                errors.append(_("Row %d: Employee '%s' not found.") % (line_no, badge))
                skipped_count += 1
                continue

            # Parse date
            att_date = None
            if date_str:
                try:
                    att_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                except ValueError:
                    try:
                        att_date = datetime.strptime(date_str, '%d/%m/%Y').date()
                    except ValueError:
                        att_date = fields.Date.today()
            else:
                att_date = fields.Date.today()

            is_attended = attended_str in ('1', 'true', 'yes', 'present', 'y')

            # Look for existing attendance or create new
            existing_att = AttendanceModel.search([
                ('session_id', '=', session.id),
                ('employee_id', '=', employee.id),
                ('date', '=', att_date)
            ], limit=1)

            if existing_att:
                existing_att.sudo().write({
                    'attended': is_attended,
                    'notes': notes or existing_att.notes,
                })
            else:
                AttendanceModel.sudo().create({
                    'session_id': session.id,
                    'employee_id': employee.id,
                    'date': att_date,
                    'attended': is_attended,
                    'notes': notes,
                })
            success_count += 1

        summary = _("Import Complete:\n• Successfully processed: %d records\n• Skipped/Errors: %d records\n") % (
            success_count, skipped_count
        )
        if errors:
            summary += "\nErrors:\n" + "\n".join(errors[:20])

        self.env['eds.integration.log'].create({
            'name': f"ATT-IMP-{fields.Date.today()}",
            'system': 'pms',
            'direction': 'inbound',
            'status': 'success' if skipped_count == 0 else 'retry',
            'error_message': summary,
        })

        self.result_log = summary
        return {
            'type': 'ir.actions.act_window',
            'name': _('Attendance Import Result'),
            'res_model': 'eds.attendance.import',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
