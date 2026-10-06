# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import ValidationError
import base64
import csv
import io

class EdsLevel1Import(models.TransientModel):
    _name = 'eds.level1.import'
    _description = 'Bulk Level 1 Reaction Survey Import Wizard'

    session_id = fields.Many2one('eds.session', string='Default Session', help='Optional if session code is in CSV')
    csv_file = fields.Binary(string='Reaction Survey Responses (CSV)', required=True)
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
            raise ValidationError(_("Please select a feedback survey CSV file to import."))

        try:
            data = base64.b64decode(self.csv_file)
            file_input = io.StringIO(data.decode('utf-8-sig'))
            reader = csv.DictReader(file_input)
        except Exception as e:
            raise ValidationError(_("Failed to read CSV file: %s") % str(e))

        success_count = 0
        skipped_count = 0
        errors = []

        Level1Model = self.env['eds.evaluation.level1']
        EmployeeModel = self.env['hr.employee']
        SessionModel = self.env['eds.session']

        # Pre-fetch default Level 1 questionnaire instrument
        instrument = self.env['eds.evaluation.instrument'].search([
            ('instrument_type', '=', 'level1'),
            ('state', '=', 'published'),
        ], limit=1)
        if not instrument:
            instrument = self.env['eds.evaluation.instrument'].search([
                ('instrument_type', '=', 'level1'),
            ], limit=1)

        q_map = {}
        if instrument:
            for q in instrument.question_ids:
                q_map[q.category] = q

        for line_no, row in enumerate(reader, start=2):
            session_ref = row.get('session_ref', '').strip()
            badge = row.get('employee_badge', '').strip()
            content_str = row.get('content_rating', '5').strip()
            trainer_str = row.get('trainer_rating', '5').strip()
            fac_str = row.get('facilities_rating', '5').strip()
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
                content_r = int(content_str) if content_str else 5
                trainer_r = int(trainer_str) if trainer_str else 5
                fac_r = int(fac_str) if fac_str else 5
            except ValueError:
                errors.append(_("Row %d: Invalid ratings (must be integers 1-5).") % line_no)
                skipped_count += 1
                continue

            # Find existing Level 1 evaluation or create
            existing_eval = Level1Model.search([
                ('session_id', '=', session.id),
                ('employee_id', '=', employee.id),
            ], limit=1)

            line_commands = []
            if 'content' in q_map:
                line_commands.append((0, 0, {'question_id': q_map['content'].id, 'rating_val': content_r}))
            if 'trainer' in q_map:
                line_commands.append((0, 0, {'question_id': q_map['trainer'].id, 'rating_val': trainer_r}))
            if 'venue' in q_map:
                line_commands.append((0, 0, {'question_id': q_map['venue'].id, 'rating_val': fac_r}))

            vals = {
                'session_id': session.id,
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

        summary = _("Import Complete:\n• Successfully imported: %d survey feedback records\n• Skipped/Errors: %d records\n") % (
            success_count, skipped_count
        )
        if errors:
            summary += "\nErrors:\n" + "\n".join(errors[:20])

        self.env['eds.integration.log'].create({
            'name': f"L1-IMP-{fields.Date.today()}",
            'system': 'pms',
            'direction': 'inbound',
            'status': 'success' if skipped_count == 0 else 'retry',
            'error_message': summary,
        })

        self.result_log = summary
        return {
            'type': 'ir.actions.act_window',
            'name': _('Level 1 Survey Import Result'),
            'res_model': 'eds.level1.import',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
