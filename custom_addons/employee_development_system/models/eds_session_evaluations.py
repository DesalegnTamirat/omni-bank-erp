"""Session controls for direct learning scores and Kirkpatrick reviews."""

import base64
import io
try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
except ImportError:
    Workbook = None
    get_column_letter = None

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from .eds_action_notification import notify_action


class EdsSessionEvaluationControls(models.Model):
    _inherit = 'eds.session'

    level2_score_ids = fields.One2many(
        'eds.evaluation.level2', 'session_id', string='Pre/Post Scores',
        domain=[('score_entry_mode', '=', True)])
    legacy_level2_score_ids = fields.One2many(
        'eds.evaluation.level2', 'session_id', string='Historical Pre/Post Results',
        domain=[('score_entry_mode', '!=', True)], readonly=True)
    assessment_max_marks = fields.Float(
        string='Pre/Post Maximum Score', default=100.0, required=True,
        help='Maximum possible mark for both pre and post results in this session. '
             'New scorecards use it; changing it updates unconfirmed scorecards '
             'while confirmed results keep their original maximum.')
    level1_session_instrument_id = fields.Many2one(
        'eds.evaluation.instrument', string='Session Level 1 Questions', copy=False,
        help='A private copy of the reaction questionnaire for this session. '
             'Publish it before completing the session.')
    level1_question_ids = fields.One2many(
        related='level1_session_instrument_id.question_ids',
        string='Level 1 Questions', readonly=False)
    level1_questions_locked = fields.Boolean(
        string='Level 1 Questions Sent', compute='_compute_level1_questions_locked')
    level1_feedback_ids = fields.One2many(
        'eds.evaluation.level1', 'session_id', string='Level 1 Responses')
    level3_question_ids = fields.One2many(
        'eds.session.level3.question', 'session_id', string='Level 3 Questions')
    level3_review_ids = fields.One2many(
        'eds.evaluation.level3', 'session_id', string='Level 3 Reviews')
    level4_review_ids = fields.One2many(
        'eds.evaluation.level4', 'session_id', string='Level 4 Impact Reviews')

    @api.depends('level1_feedback_ids')
    def _compute_level1_questions_locked(self):
        for session in self:
            session.level1_questions_locked = bool(session.level1_feedback_ids)

    @api.constrains('assessment_max_marks')
    def _check_assessment_max_marks(self):
        for session in self:
            if session.assessment_max_marks <= 0:
                raise ValidationError(_('The pre/post maximum score must be greater than zero.'))

    def _ensure_level1_instrument(self):
        for session in self:
            if not session.level1_session_instrument_id:
                source = (session.course_id.level1_instrument_id or self.env.ref(
                    'employee_development_system.inst_level1_standard',
                    raise_if_not_found=False))
                name = _('%s - %s Level 1 Questions') % (
                    session.course_id.name or session.name, session.name)
                instrument = self.env['eds.evaluation.instrument'].create({
                    'name': name,
                    'instrument_type': 'level1',
                    'state': 'draft',
                })
                if source:
                    Question = self.env['eds.evaluation.instrument.question']
                    for q in source.question_ids:
                        Question.create({
                            'instrument_id': instrument.id,
                            'name': q.name,
                            'sequence': q.sequence,
                            'category': q.category,
                            'question_type': q.question_type,
                            'weight': q.weight,
                        })
                session.level1_session_instrument_id = instrument
        return self.mapped('level1_session_instrument_id')

    def write(self, vals):
        if 'level1_question_ids' in vals:
            for session in self:
                if not session.level1_session_instrument_id:
                    session._ensure_level1_instrument()
        if 'assessment_max_marks' not in vals:
            return super().write(vals)
        self._require_ld_delivery_access()
        self.check_access('write')
        result = super().write(vals)
        for session in self:
            # Preserve confirmed and historical scorecards. Only unconfirmed
            # direct entries follow a corrected session-wide maximum.
            draft_scores = self.env['eds.evaluation.level2'].sudo().search([
                ('session_id', '=', session.id),
                ('score_entry_mode', '=', True),
                ('state', '=', 'draft'),
            ])
            if draft_scores:
                draft_scores.write({'total_marks': session.assessment_max_marks})
        return result

    def action_prepare_level2_scores(self):
        """Create one direct scorecard per active session participant."""
        self._require_ld_delivery_access()
        self.ensure_one()
        self.check_access('write')
        if self.status not in ('scheduled', 'ongoing', 'completed'):
            raise UserError(_('Prepare scores after the schedule is confirmed.'))
        participant_rows = self.enrollment_ids.filtered(
            lambda row: row.state in (
                'suggested', 'invited', 'enrolled', 'completed', 'incomplete', 'absent')
            and (row.state != 'suggested' or row.selected))
        employee_ids = sorted(set(participant_rows.sudo().mapped('employee_id').ids))
        if not employee_ids:
            raise UserError(_('Add participants to this session before preparing scores.'))
        Evaluation = self.env['eds.evaluation.level2'].sudo()
        existing_employee_ids = set(Evaluation.search([
            ('session_id', '=', self.id), ('employee_id', 'in', employee_ids),
        ]).mapped('employee_id').ids)
        values = [
            {
                'session_id': self.id,
                'employee_id': employee_id,
                'score_entry_mode': True,
                'total_marks': self.assessment_max_marks,
            }
            for employee_id in employee_ids if employee_id not in existing_employee_ids
        ]
        if values:
            Evaluation.create(values)
        if not values and not self.level2_score_ids:
            raise UserError(_(
                'These participants already have historical pre/post assessment '
                'records. Open Level 2 Evaluations to review them.'))
        return {
            'type': 'ir.actions.client', 'tag': 'bunna_refresh_form',
            'params': {'res_model': self._name, 'res_id': self.id},
        }

    def action_open_level2_scores(self):
        self._require_ld_delivery_access()
        self.ensure_one()
        return {
            'name': _('Pre/Post Learning Scores'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.evaluation.level2',
            'view_mode': 'list,form',
            'domain': [('session_id', '=', self.id)],
            'context': {'default_session_id': self.id},
        }

    def action_export_prepost_scores_xlsx(self):
        self._require_ld_delivery_access()
        self.ensure_one()
        if Workbook is None:
            raise UserError(_('The openpyxl library is required to export Excel score templates.'))

        self.action_prepare_level2_scores()

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'Pre_Post_Scores'

        sheet['A1'], sheet['B1'] = 'Program', self.course_id.name or self.program_name or ''
        sheet['A2'], sheet['B2'] = 'Session Code', self.name
        sheet['A3'], sheet['B3'] = 'Dates', '%s to %s' % (self.date_start or '', self.date_end or '')
        sheet['A4'], sheet['B4'] = 'Total Marks', self.assessment_max_marks

        sheet['A5'] = 'Instructions: Enter Pre-Test and Post-Test numeric marks for each participant. Max score is %s. Leave blank if not taken.' % self.assessment_max_marks
        sheet.merge_cells('A5:I5')

        headers = [
            'Employee ID', 'Employee Name', 'Work Unit', 'Department',
            'Job Position', 'Total Marks', 'Pre-Test Score', 'Post-Test Score', 'Remarks'
        ]
        for col_idx, label in enumerate(headers, start=1):
            cell = sheet.cell(row=7, column=col_idx, value=label)
            cell.font = Font(color='FFFFFF', bold=True)
            cell.fill = PatternFill('solid', fgColor='541718')
            cell.alignment = Alignment(horizontal='center', vertical='center')

        records = self.level2_score_ids.sorted(key=lambda r: r.employee_id.sudo().name or '')
        for row_idx, score_rec in enumerate(records, start=8):
            emp = score_rec.employee_id.sudo()
            enrollment = self.enrollment_ids.filtered(lambda e: e.employee_id == emp)[:1]
            work_unit = enrollment.work_unit_id.name or emp.operating_unit_id.name or ''
            dept = enrollment.department_id.name or emp.department_id.name or ''
            job = enrollment.job_position_id.name or emp.job_id.name or ''
            total_m = score_rec.total_marks or self.assessment_max_marks
            pre_val = score_rec.pre_test_score if score_rec.pre_score_entered else ''
            post_val = score_rec.post_test_score if score_rec.post_score_entered else ''

            sheet.cell(row=row_idx, column=1, value=emp.barcode or emp.identification_id or emp.id)
            sheet.cell(row=row_idx, column=2, value=emp.name)
            sheet.cell(row=row_idx, column=3, value=work_unit)
            sheet.cell(row=row_idx, column=4, value=dept)
            sheet.cell(row=row_idx, column=5, value=job)
            sheet.cell(row=row_idx, column=6, value=total_m)
            sheet.cell(row=row_idx, column=7, value=pre_val)
            sheet.cell(row=row_idx, column=8, value=post_val)
            sheet.cell(row=row_idx, column=9, value=score_rec.remarks or '')

        widths = {'A': 16, 'B': 28, 'C': 26, 'D': 24, 'E': 24, 'F': 14, 'G': 16, 'H': 16, 'I': 30}
        for col_letter, width in widths.items():
            sheet.column_dimensions[col_letter].width = width

        output = io.BytesIO()
        workbook.save(output)
        attachment = self.env['ir.attachment'].with_context(skip_eds_file_check=True).create({
            'name': 'Pre_Post_Scores_%s.xlsx' % self.name.replace('/', '_'),
            'type': 'binary',
            'datas': base64.b64encode(output.getvalue()),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'res_model': self._name,
            'res_id': self.id,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % attachment.id,
            'target': 'self',
        }

    def action_open_prepost_scores_import(self):
        self._require_ld_delivery_access()
        self.ensure_one()
        return {
            'name': _('Import Pre/Post Assessment Scores'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.prepost.score.import',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_session_id': self.id},
        }

    def action_prepare_level1_questions(self):
        """Copy the shared questionnaire so edits affect this session only."""
        self._require_ld_delivery_access()
        self.ensure_one()
        if self.level1_feedback_ids:
            raise UserError(_(
                'Level 1 feedback has already been sent. Open the questions '
                'in view mode to see their original wording.'))
        if not self.level1_session_instrument_id:
            self._ensure_level1_instrument()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Questions Loaded'),
                'message': _('Level 1 reaction questions have been loaded. You can edit, reorder, or add new lines directly below.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def action_open_level1_questions(self):
        self._require_ld_delivery_access()
        self.ensure_one()
        if not self.level1_session_instrument_id:
            return self.action_prepare_level1_questions()
        return {
            'name': _('Session Level 1 Questions'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.evaluation.instrument',
            'res_id': self.level1_session_instrument_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_send_level1_feedback(self):
        self._require_ld_delivery_access()
        for session in self:
            if session.status != 'completed':
                raise UserError(_('Complete the session before sending Level 1 feedback.'))
            session._distribute_completion_evaluations()
        if len(self) == 1:
            return {
                'type': 'ir.actions.client', 'tag': 'bunna_refresh_form',
                'params': {'res_model': self._name, 'res_id': self.id},
            }
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_open_level1_feedback(self):
        self._require_ld_delivery_access()
        self.ensure_one()
        return {
            'name': _('Level 1 Responses'), 'type': 'ir.actions.act_window',
            'res_model': 'eds.evaluation.level1', 'view_mode': 'list,form',
            'domain': [('session_id', '=', self.id)],
            'context': {'default_session_id': self.id},
        }

    def action_export_level1_google_template(self):
        self._require_ld_delivery_access()
        self.ensure_one()
        if Workbook is None:
            raise UserError(_('The openpyxl library is required to export Google Form templates.'))

        self._ensure_level1_instrument()
        instrument = self.level1_session_instrument_id

        workbook = Workbook()

        # Sheet 1: Setup Instructions & Questions
        sheet1 = workbook.active
        sheet1.title = 'Google_Form_Setup'
        sheet1['A1'] = 'EDS Level 1 Reaction — Google Form Preparation Guide'
        sheet1['A1'].font = Font(size=14, bold=True, color='541718')
        sheet1['A2'] = 'Session: %s | Program: %s' % (self.name, self.course_id.name or self.program_name or '')
        sheet1['A2'].font = Font(italic=True)

        instructions = [
            "Step 1: Open Google Forms (https://forms.google.com) and create a New Form titled '%s - Participant Feedback'." % (self.name),
            "Step 2: Add each question below with Question Type 'Linear scale' (1 to 5: 1 = Strongly Disagree / Poor, 5 = Strongly Agree / Excellent).",
            "Step 3: (Optional) Add a Short Answer question for 'Employee ID / Badge' if tracking individual participation.",
            "Step 4: Add a Paragraph question: 'Any suggestions for improving this training or other comments?'.",
            "Step 5: Go to the 'Responses' tab in your Google Form and click 'Link to Sheets' to generate the responses spreadsheet.",
            "Step 6: When responses are collected, download the Google Sheet as Excel (.xlsx) or copy into the 'Responses_Import' sheet of this workbook.",
            "Step 7: In Odoo EDS, open this session and click 'Import Google Form Responses' to automatically ingest all participant feedback!"
        ]
        for idx, text in enumerate(instructions, start=4):
            sheet1.cell(row=idx, column=1, value=text)

        q_row_start = 13
        sheet1.cell(row=q_row_start, column=1, value='Category').font = Font(bold=True, color='FFFFFF')
        sheet1.cell(row=q_row_start, column=1).fill = PatternFill('solid', fgColor='541718')
        sheet1.cell(row=q_row_start, column=2, value='Google Form Question Prompt (Copy & Paste Directly)').font = Font(bold=True, color='FFFFFF')
        sheet1.cell(row=q_row_start, column=2).fill = PatternFill('solid', fgColor='541718')
        sheet1.cell(row=q_row_start, column=3, value='Question Type in Google Form').font = Font(bold=True, color='FFFFFF')
        sheet1.cell(row=q_row_start, column=3).fill = PatternFill('solid', fgColor='541718')

        questions = instrument.question_ids if instrument else []
        curr_row = q_row_start + 1

        # Participant identifier row
        sheet1.cell(row=curr_row, column=1, value='Identification')
        sheet1.cell(row=curr_row, column=2, value='Employee ID / Badge')
        sheet1.cell(row=curr_row, column=3, value='Short answer (Optional)')
        curr_row += 1

        prompt_list = []
        for q in questions:
            cat_key = q.category or 'general'
            cat_label = dict(q._fields['category'].selection).get(cat_key, cat_key.capitalize()) if hasattr(q, '_fields') and 'category' in q._fields else cat_key.capitalize()
            q_text = (getattr(q, 'name', None) or getattr(q, 'question_text', '')).strip()
            q_prompt = q_text
            prompt_list.append(q_prompt)

            if q.question_type == 'scale_1_5':
                q_scale = 'Linear scale (1 to 5: 1=Poor/Disagree, 5=Excellent/Agree)'
            elif q.question_type == 'scale_1_10':
                q_scale = 'Linear scale (1 to 10)'
            elif q.question_type == 'yes_no':
                q_scale = 'Multiple choice (Yes / No)'
            else:
                q_scale = 'Paragraph / Text'

            sheet1.cell(row=curr_row, column=1, value=cat_label)
            sheet1.cell(row=curr_row, column=2, value=q_prompt)
            sheet1.cell(row=curr_row, column=3, value=q_scale)
            curr_row += 1

        # General comments row
        sheet1.cell(row=curr_row, column=1, value='Feedback / Remarks')
        sheet1.cell(row=curr_row, column=2, value='Any additional comments or suggestions for improvement?')
        sheet1.cell(row=curr_row, column=3, value='Paragraph (Optional)')

        # Sheet 2: Standard Google Form Responses template matching exact prompts
        sheet2 = workbook.create_sheet(title='Responses_Import')
        sheet2_headers = ['Timestamp', 'Employee ID / Badge'] + prompt_list + ['Any additional comments or suggestions for improvement?']

        for col_idx, label in enumerate(sheet2_headers, start=1):
            cell = sheet2.cell(row=1, column=col_idx, value=label)
            cell.font = Font(color='FFFFFF', bold=True)
            cell.fill = PatternFill('solid', fgColor='541718')
            cell.alignment = Alignment(horizontal='center', vertical='center')

        sample_row = ['2026-11-11 10:00:00', 'EMP001'] + [5] * len(prompt_list) + ['Great practical insights and highly engaging facilitation!']
        for col_idx, val in enumerate(sample_row, start=1):
            sheet2.cell(row=2, column=col_idx, value=val)

        sheet1.column_dimensions['A'].width = 25
        sheet1.column_dimensions['B'].width = 75
        sheet1.column_dimensions['C'].width = 32
        for col_idx in range(1, len(sheet2_headers) + 1):
            col_letter = get_column_letter(col_idx) if get_column_letter else chr(64 + col_idx)
            sheet2.column_dimensions[col_letter].width = 30

        output = io.BytesIO()
        workbook.save(output)
        attachment = self.env['ir.attachment'].with_context(skip_eds_file_check=True).create({
            'name': 'Level1_Google_Form_Template_%s.xlsx' % self.name.replace('/', '_'),
            'type': 'binary',
            'datas': base64.b64encode(output.getvalue()),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'res_model': self._name,
            'res_id': self.id,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % attachment.id,
            'target': 'self',
        }

    def action_open_level1_import_wizard(self):
        self._require_ld_delivery_access()
        self.ensure_one()
        return {
            'name': _('Import Google Form Responses / Survey'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.level1.import',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_session_id': self.id},
        }

    def action_prepare_level3_questions(self):
        self._require_ld_delivery_access()
        self.ensure_one()
        existing = set(self.level3_question_ids.mapped('competency_id').ids)
        Question = self.env['eds.session.level3.question']
        for competency in self.course_id.competency_line_ids.mapped('competency_id'):
            if competency.id not in existing:
                Question.create({
                    'session_id': self.id, 'competency_id': competency.id,
                    'prompt': _('How has the participant applied %s on the job?')
                              % competency.name,
                })
        return {
            'type': 'ir.actions.client', 'tag': 'bunna_refresh_form',
            'params': {'res_model': self._name, 'res_id': self.id},
        }

    def action_apply_level3_questions(self):
        """Update only pending reviews that have not yet been sent."""
        self._require_ld_delivery_access()
        self.ensure_one()
        if not self.level3_question_ids:
            raise UserError(_('Add at least one Level 3 question first.'))
        Line = self.env['eds.evaluation.level3.line']
        for review in self.level3_review_ids.filtered(
                lambda row: row.status == 'pending'
                and not row.notification_sent_at):
            for question in self.level3_question_ids:
                line = review.line_ids.filtered(
                    lambda row: row.competency_id == question.competency_id)[:1]
                if line:
                    # Level 3 lines start with default ratings, so an untouched
                    # line is not empty. Preserve any changed rating or evidence.
                    if (review.status == 'pending' and not line.comment
                            and ((not line.frequency_rating and not line.observed_level)
                                 or (line.frequency_rating == '4'
                                     and line.observed_level == '2'))):
                        line.behavior_description = question.prompt
                else:
                    Line.create({
                        'evaluation_id': review.id,
                        'competency_id': question.competency_id.id,
                        'behavior_description': question.prompt,
                    })
        return {
            'type': 'ir.actions.client', 'tag': 'bunna_refresh_form',
            'params': {'res_model': self._name, 'res_id': self.id},
        }

    def action_send_level3_reviews(self):
        self._require_ld_delivery_access()
        self.ensure_one()
        if self.status != 'completed':
            raise UserError(_('Complete the session before sending Level 3 reviews.'))
        if not self.level3_review_ids:
            raise UserError(_('There are no coach reviews to send.'))
        for review in self.level3_review_ids.filtered(
                lambda row: row.status in ('pending', 'in_progress')
                and not row.notification_sent_at):
            manager_user = review.manager_id.sudo().user_id
            if manager_user and manager_user.active and notify_action(
                    review, manager_user, _('Review training impact'),
                    _('Review %s’s application of %s after training.') % (
                        review.employee_id.sudo().name,
                        self.course_id.name or self.name)):
                review.notification_sent_at = fields.Datetime.now()
        return {
            'type': 'ir.actions.client', 'tag': 'bunna_refresh_form',
            'params': {'res_model': self._name, 'res_id': self.id},
        }

    def action_open_level3_reviews(self):
        self._require_ld_delivery_access()
        self.ensure_one()
        return {
            'name': _('Level 3 Coach Reviews'), 'type': 'ir.actions.act_window',
            'res_model': 'eds.evaluation.level3', 'view_mode': 'list,form',
            'domain': [('session_id', '=', self.id)],
            'context': {'default_session_id': self.id},
        }

    def action_prepare_level4_review(self):
        self._require_ld_delivery_access()
        self.ensure_one()
        if self.status != 'completed':
            raise UserError(_('Complete the session before preparing Level 4 impact.'))
        review = self.level4_review_ids[:1]
        if not review:
            review = self.env['eds.evaluation.level4'].create({
                'session_id': self.id, 'course_id': self.course_id.id,
                'evaluator_id': self.env.uid,
            })
        return {
            'name': _('Level 4 Total Session Impact'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.evaluation.level4', 'res_id': review.id,
            'view_mode': 'form', 'target': 'current',
        }

    def action_send_level4_review(self):
        self._require_ld_delivery_access()
        self.ensure_one()
        review = self.level4_review_ids[:1]
        if not review:
            raise UserError(_('Prepare a Level 4 impact review first.'))
        if not (review.kpi_ids or review.estimated_financial_benefit
                or (review.impact_summary or '').strip()):
            raise UserError(_(
                'Add an organizational impact measure, financial benefit, or '
                'impact summary before sending.'))
        reviewer = review.evaluator_id
        if not reviewer or not reviewer.active or reviewer.share or reviewer == self.env.user:
            raise UserError(_('Assign another active L&D evaluator on the Level 4 review.'))
        try:
            review.with_user(reviewer).check_access('read')
        except AccessError as exc:
            raise UserError(_(
                'The selected evaluator cannot open the Level 4 review. '
                'Assign an L&D officer or manager.')) from exc
        notify_action(review, reviewer, _('Evaluate training impact'),
                      _('Review the business KPI results for %s (%s).') % (
                          self.course_id.name or self.name, self.name))
        return {
            'type': 'ir.actions.client', 'tag': 'bunna_refresh_form',
            'params': {'res_model': self._name, 'res_id': self.id},
        }


class EdsSessionLevel3Question(models.Model):
    _name = 'eds.session.level3.question'
    _description = 'Session Level 3 Behavioral Question'
    _order = 'sequence, create_date desc, id desc'

    session_id = fields.Many2one(
        'eds.session', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(
        'res.company', related='session_id.company_id', store=True, readonly=True)
    sequence = fields.Integer(default=10)
    competency_id = fields.Many2one(
        'competency.competency', required=True, ondelete='restrict')
    prompt = fields.Char(string='Question / Observable Behavior', required=True)

    _session_competency_unique = models.Constraint(
        'UNIQUE(session_id, competency_id)',
        'This competency already has a Level 3 question in the session.')


def _locked_session_instruments(env, instruments):
    """Return questionnaires already used by distributed session feedback."""
    if not instruments:
        return instruments
    sessions = env['eds.session'].sudo().search([
        ('level1_session_instrument_id', 'in', instruments.ids),
    ])
    return sessions.filtered('level1_feedback_ids').mapped(
        'level1_session_instrument_id')


class EdsSessionInstrumentLock(models.Model):
    _inherit = 'eds.evaluation.instrument'

    def write(self, vals):
        if 'question_ids' in vals and _locked_session_instruments(self.env, self):
            raise UserError(_(
                'This session questionnaire has already been sent. Its '
                'questions cannot be changed.'))
        return super().write(vals)

    def unlink(self):
        if _locked_session_instruments(self.env, self):
            raise UserError(_(
                'This session questionnaire has already been sent and '
                'cannot be deleted.'))
        return super().unlink()


class EdsSessionInstrumentQuestionLock(models.Model):
    _inherit = 'eds.evaluation.instrument.question'

    @api.model_create_multi
    def create(self, vals_list):
        instruments = self.env['eds.evaluation.instrument'].browse([
            vals['instrument_id'] for vals in vals_list if vals.get('instrument_id')
        ])
        if _locked_session_instruments(self.env, instruments):
            raise UserError(_(
                'This session questionnaire has already been sent. Its '
                'questions cannot be changed.'))
        return super().create(vals_list)

    def write(self, vals):
        instruments = self.mapped('instrument_id')
        if vals.get('instrument_id'):
            instruments |= self.env['eds.evaluation.instrument'].browse(
                vals['instrument_id'])
        if _locked_session_instruments(self.env, instruments):
            raise UserError(_(
                'This session questionnaire has already been sent. Its '
                'questions cannot be changed.'))
        return super().write(vals)

    def unlink(self):
        if _locked_session_instruments(self.env, self.mapped('instrument_id')):
            raise UserError(_(
                'This session questionnaire has already been sent. Its '
                'questions cannot be deleted.'))
        return super().unlink()


class EdsEvaluationLevel2DirectScores(models.Model):
    _inherit = 'eds.evaluation.level2'

    score_entry_mode = fields.Boolean(
        string='Direct Score Entry', default=False, readonly=True,
        help='Enter pre and post marks against a maximum score; no questions are sent.')
    pre_score_entered = fields.Boolean(
        string='Pre Value Entered', copy=False,
        help='Mark this when a genuine pre-training score is 0.')
    post_score_entered = fields.Boolean(
        string='Post Value Entered', copy=False,
        help='Mark this when a genuine post-training score is 0.')
    score_confirmed = fields.Boolean(string='Scores Confirmed', copy=False)
    display_max_score = fields.Float(
        string='Maximum Score', compute='_compute_display_scores')
    display_pre_score = fields.Float(
        string='Pre Value', compute='_compute_display_scores')
    display_post_score = fields.Float(
        string='Post Value', compute='_compute_display_scores')
    gap_status = fields.Selection([
        ('pending', 'Awaiting Scores'),
        ('improved', 'Improved'),
        ('unchanged', 'Unchanged'),
        ('declined', 'Declined'),
    ], compute='_compute_gap_status', store=True, string='Learning Change')

    @api.depends('score_entry_mode', 'total_marks', 'pre_test_score',
                 'post_test_score', 'pre_test_pct', 'post_test_pct',
                 'pre_assessment_id', 'post_assessment_id')
    def _compute_display_scores(self):
        for evaluation in self:
            if (evaluation.pre_assessment_id or evaluation.post_assessment_id):
                # Older question-based records stored their final results as
                # percentages. Show them as marks out of 100 without changing
                # or discarding the historical assessments.
                evaluation.display_max_score = 100.0
                evaluation.display_pre_score = evaluation.pre_test_pct
                evaluation.display_post_score = evaluation.post_test_pct
            else:
                evaluation.display_max_score = evaluation.total_marks
                evaluation.display_pre_score = evaluation.pre_test_score
                evaluation.display_post_score = evaluation.post_test_score

    @api.depends('score_entry_mode', 'score_confirmed',
                 'pre_test_pct', 'post_test_pct')
    def _compute_gap_status(self):
        for evaluation in self:
            if not evaluation.score_entry_mode or not evaluation.score_confirmed:
                evaluation.gap_status = 'pending'
            elif evaluation.post_test_pct > evaluation.pre_test_pct:
                evaluation.gap_status = 'improved'
            elif evaluation.post_test_pct < evaluation.pre_test_pct:
                evaluation.gap_status = 'declined'
            else:
                evaluation.gap_status = 'unchanged'

    @api.constrains('score_entry_mode', 'pre_test_score', 'post_test_score',
                    'total_marks', 'pre_assessment_id', 'post_assessment_id',
                    'pre_score_entered', 'post_score_entered', 'score_confirmed',
                    'state')
    def _check_direct_scores(self):
        for evaluation in self.filtered('score_entry_mode'):
            if evaluation.total_marks <= 0:
                raise ValidationError(_('The maximum possible score must be greater than zero.'))
            if not (0 <= evaluation.pre_test_score <= evaluation.total_marks
                    and 0 <= evaluation.post_test_score <= evaluation.total_marks):
                raise ValidationError(_(
                    'Pre and post values must be between zero and the maximum possible score.'))
            if evaluation.pre_assessment_id or evaluation.post_assessment_id:
                raise ValidationError(_(
                    'Direct score entry cannot be combined with question-based assessments.'))
            if (evaluation.score_confirmed or evaluation.state == 'evaluated') and not (
                    evaluation.pre_score_entered and evaluation.post_score_entered):
                raise ValidationError(_(
                    'Enter both pre and post values before confirming the scorecard.'))

    def write(self, vals):
        if {'total_marks', 'pre_test_score', 'post_test_score'} & vals.keys():
            direct = self.filtered('score_entry_mode')
            if any(row.state == 'evaluated' for row in direct):
                raise UserError(_(
                    'Reopen a completed scorecard before changing its maximum or values.'))
            if direct:
                vals = dict(vals, score_confirmed=False)
                if 'pre_test_score' in vals:
                    vals['pre_score_entered'] = True
                if 'post_test_score' in vals:
                    vals['post_score_entered'] = True
        return super().write(vals)

    def action_reopen_direct_scores(self):
        if not self.env.su and not self.env.user.has_group(
                'employee_development_system.group_eds_officer'):
            raise AccessError(_('Only L&D staff may reopen learning scores.'))
        for evaluation in self:
            if not evaluation.score_entry_mode or evaluation.state != 'evaluated':
                raise UserError(_('Only a completed direct scorecard can be reopened.'))
            evaluation.write({'state': 'draft', 'score_confirmed': False})
            evaluation.message_post(body=_('Direct pre/post scores reopened for correction.'))
        return True


    def action_evaluate(self):
        legacy = self.filtered(lambda row: not row.score_entry_mode)
        direct = self - legacy
        if legacy:
            super(EdsEvaluationLevel2DirectScores, legacy).action_evaluate()
        if direct:
            if not self.env.su and not self.env.user.has_group(
                    'employee_development_system.group_eds_officer'):
                raise AccessError(_('Only L&D staff may confirm learning scores.'))
            for evaluation in direct:
                if evaluation.state != 'draft':
                    raise UserError(_('Reopen this scorecard before confirming it again.'))
                if not (evaluation.pre_score_entered and evaluation.post_score_entered):
                    raise ValidationError(_(
                        'Enter both pre and post values before confirming the scorecard.'))
                evaluation.write({'state': 'evaluated', 'score_confirmed': True})
                evaluation.message_post(body=_(
                    'Direct learning scores confirmed: Pre %.1f%%, Post %.1f%%, '
                    'Change %.1f%% (%s).') % (
                        evaluation.pre_test_pct, evaluation.post_test_pct,
                        evaluation.learning_gain,
                        dict(evaluation._fields['gap_status'].selection)[
                            evaluation.gap_status],
                    ))
                if not evaluation.passed and evaluation.course_id:
                    evaluation._flag_tna_gap_candidate()
                else:
                    evaluation.tna_gap_pending = False
                evaluation.env['eds.certificate']._sync_session_candidates(
                    evaluation.session_id)
        return True


class EdsEvaluationLevel4KpiDirection(models.Model):
    _inherit = 'eds.evaluation.level4.kpi'

    improvement_direction = fields.Selection([
        ('higher', 'Higher Is Better'),
        ('lower', 'Lower Is Better'),
    ], string='Success Direction', default='higher', required=True)

    @api.depends('baseline_value', 'achieved_value', 'improvement_direction')
    def _compute_improvement(self):
        for kpi in self:
            if kpi.baseline_value:
                change = kpi.achieved_value - kpi.baseline_value
                if kpi.improvement_direction == 'lower':
                    change = -change
                kpi.improvement_pct = round(
                    100.0 * change / abs(kpi.baseline_value), 2)
            else:
                kpi.improvement_pct = 0.0
