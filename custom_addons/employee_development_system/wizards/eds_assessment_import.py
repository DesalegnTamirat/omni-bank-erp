# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import base64
import csv
import io

class EdsAssessmentImport(models.TransientModel):
    _name = 'eds.assessment.import'
    _description = 'Bulk Pre/Post Assessment Scores Import Wizard'

    session_id = fields.Many2one('eds.session', string='Default Session', help='Optional if session code is in CSV')
    csv_file = fields.Binary(string='Assessment Scores (CSV)', required=True)
    filename = fields.Char(string='File Name')
    result_log = fields.Text(string='Import Summary', readonly=True)

    def action_download_template(self):
        """Return sample CSV template format."""
        sample_csv = (
            "session_ref,employee_badge,pre_score,post_score,comments\n"
            "SES/2026/0001,EMP001,35.0,85.0,High engagement and good post-test comprehension\n"
            "SES/2026/0001,EMP002,40.0,55.0,Requires remedial follow-up on module 2\n"
        )
        return {
            'type': 'ir.actions.act_url',
            'url': 'data:text/csv;charset=utf-8;base64,' + base64.b64encode(sample_csv.encode()).decode(),
            'target': 'self',
        }

    def action_import_assessments(self):
        self.ensure_one()
        if not self.csv_file:
            raise ValidationError(_("Please select an assessment CSV file to import."))

        try:
            data = base64.b64decode(self.csv_file)
            file_input = io.StringIO(data.decode('utf-8-sig'))
            reader = csv.DictReader(file_input)
        except Exception as e:
            raise ValidationError(_("Failed to read CSV file: %s") % str(e))

        success_count = 0
        skipped_count = 0
        errors = []

        AssessmentModel = self.env['eds.assessment']
        EmployeeModel = self.env['hr.employee']
        SessionModel = self.env['eds.session']

        for line_no, row in enumerate(reader, start=2):
            session_ref = row.get('session_ref', '').strip()
            badge = row.get('employee_badge', '').strip()
            pre_str = row.get('pre_score', '').strip()
            post_str = row.get('post_score', '').strip()
            comments = row.get('comments', '').strip()

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

            # Resolve employee
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

            try:
                pre_score = float(pre_str) if pre_str else 0.0
                post_score = float(post_str) if post_str else 0.0
            except ValueError:
                errors.append(_("Row %d: Invalid score numbers (pre: '%s', post: '%s').") % (line_no, pre_str, post_str))
                skipped_count += 1
                continue

            # Find or create assessment
            existing_ass = AssessmentModel.search([
                ('session_id', '=', session.id),
                ('employee_id', '=', employee.id),
            ], limit=1)

            if existing_ass:
                existing_ass.sudo().write({
                    'pre_assessment_score': pre_score,
                    'post_assessment_score': post_score,
                    'notes': comments or existing_ass.notes,
                })
            else:
                AssessmentModel.sudo().create({
                    'session_id': session.id,
                    'employee_id': employee.id,
                    'pre_assessment_score': pre_score,
                    'post_assessment_score': post_score,
                    'notes': comments,
                })
            success_count += 1

        summary = _("Import Complete:\n• Successfully scored: %d participant records\n• Skipped/Errors: %d records\n") % (
            success_count, skipped_count
        )
        if errors:
            summary += "\nErrors:\n" + "\n".join(errors[:20])

        self.env['eds.integration.log'].create({
            'name': f"ASSESS-IMP-{fields.Date.today()}",
            'system': 'pms',
            'direction': 'inbound',
            'status': 'success' if skipped_count == 0 else 'retry',
            'error_message': summary,
        })

        self.result_log = summary
        return {
            'type': 'ir.actions.act_window',
            'name': _('Assessment Scores Import Result'),
            'res_model': 'eds.assessment.import',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
