"""Anonymous, refreshable question summaries for Level 1 session feedback."""

from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .eds_level1_anonymous import anonymous_level1_labels, redact_level1_text


QUESTION_TYPES = [
    ('scale_1_5', '5-point rating'),
    ('scale_1_10', '10-point rating'),
    ('yes_no', 'Yes / No'),
    ('text', 'Open text'),
]
RESULTS = [
    ('satisfactory', 'Satisfactory'),
    ('unsatisfactory', 'Unsatisfactory'),
    ('neutral', 'At 50%'),
    ('not_scored', 'Not scored'),
]
TARGETS = [
    ('course', 'Course'),
    ('vendor', 'Vendor'),
    ('hotel', 'Hotel'),
]


def _result_for_pct(value):
    if value > 50:
        return 'satisfactory'
    if value < 50:
        return 'unsatisfactory'
    return 'neutral'


def _format_number(value):
    return ('%.2f' % value).rstrip('0').rstrip('.')


class EdsLevel1QuestionReport(models.Model):
    _name = 'eds.level1.question.report'
    _description = 'Reaction Question Satisfaction Report'
    _order = 'session_id desc, sequence, id'
    _rec_name = 'question_text'

    session_id = fields.Many2one('eds.session', string='Session', required=True,
                                 readonly=True, ondelete='cascade', index=True)
    company_id = fields.Many2one('res.company', related='session_id.company_id',
                                 string='Company', store=True, readonly=True, index=True)
    course_id = fields.Many2one('eds.course', related='session_id.course_id',
                                string='Course', store=True, readonly=True)
    question_id = fields.Many2one('eds.evaluation.instrument.question',
                                  string='Question Source', readonly=True,
                                  ondelete='set null')
    sequence = fields.Integer(readonly=True)
    question_text = fields.Char(string='Question', required=True, readonly=True)
    question_type = fields.Selection(QUESTION_TYPES, string='Answer Format', readonly=True)
    target_area = fields.Selection(TARGETS, string='Question Target', readonly=True)
    average_value = fields.Float(string='Average Raw Value', digits=(12, 2), readonly=True)
    average_pct = fields.Float(string='Average (%)', digits=(12, 2), readonly=True)
    average_display = fields.Char(string='Average Rating', readonly=True)
    satisfaction = fields.Selection(RESULTS, string='Assessment', readonly=True)
    answered_count = fields.Integer(string='Employees Answered', readonly=True)
    satisfactory_count = fields.Integer(string='Satisfactory Answers', readonly=True)
    unsatisfactory_count = fields.Integer(string='Unsatisfactory Answers', readonly=True)
    neutral_count = fields.Integer(string='At 50%', readonly=True)
    answer_ids = fields.One2many('eds.level1.question.answer', 'report_id',
                                 string='Anonymous Answers', readonly=True)
    generated_at = fields.Datetime(string='Generated At', default=fields.Datetime.now,
                                   readonly=True)

    @api.model
    def generate_for_session(self, session):
        """Replace one session's report with submitted, identity-free answers."""
        session.ensure_one()
        if not (self.env.su or self.env.user.has_group(
                'employee_development_system.group_eds_officer') or
                self.env.user.has_group(
                    'employee_development_system.group_eds_executive')):
            raise AccessError(_('Only EDS reporting roles may generate reaction reports.'))
        session.check_access('read')
        if not self.env.su and session.company_id not in self.env.companies:
            raise AccessError(_('The selected session is outside your allowed companies.'))
        surveys = self.env['eds.evaluation.level1'].sudo().search([
            ('session_id', '=', session.id),
            ('state', 'in', ('submitted', 'consolidated')),
        ], order='id')
        if not surveys:
            raise UserError(_('No submitted reaction responses exist for this session.'))

        labels = anonymous_level1_labels(surveys)
        questions = (session.sudo().level1_question_ids |
                     surveys.mapped('line_ids.question_id')).sorted(
                         key=lambda question: (question.sequence, question.id))
        grouped = defaultdict(list)
        for survey in surveys:
            for line in survey.line_ids:
                kind = line.question_id.question_type
                if kind in ('scale_1_5', 'scale_1_10'):
                    if not line.rating_val:
                        continue
                    denominator = 5 if kind == 'scale_1_5' else 10
                    answer = '%d / %d' % (line.rating_val, denominator)
                    pct = (line.rating_val / denominator) * 100.0
                elif kind == 'yes_no':
                    if not line.yes_no_val:
                        continue
                    answer = _('Yes') if line.yes_no_val == 'yes' else _('No')
                    pct = 100.0 if line.yes_no_val == 'yes' else 0.0
                else:
                    if not (line.text_val or '').strip():
                        continue
                    answer = redact_level1_text(line.text_val.strip(), survey)
                    pct = False
                grouped[line.question_id.id].append({
                    'anonymous_label': labels[survey.id],
                    'answer_value': answer,
                    'score_pct': pct if pct is not False else 0.0,
                    'satisfaction': _result_for_pct(pct) if pct is not False
                                    else 'not_scored',
                })

        Report = self.sudo()
        with self.env.cr.savepoint():
            Report.search([('session_id', '=', session.id)]).unlink()
            for question in questions:
                answers = grouped.get(question.id, [])
                scored = [answer['score_pct'] for answer in answers
                          if answer['satisfaction'] != 'not_scored']
                average_pct = sum(scored) / len(scored) if scored else 0.0
                if question.question_type in ('scale_1_5', 'scale_1_10') and scored:
                    maximum = 5 if question.question_type == 'scale_1_5' else 10
                    average_value = sum(
                        int(answer['answer_value'].split(' / ')[0])
                        for answer in answers) / len(answers)
                    display = '%s / %d' % (_format_number(average_value), maximum)
                elif question.question_type == 'yes_no' and scored:
                    average_value = average_pct
                    display = '%s%% Yes' % _format_number(average_pct)
                else:
                    average_value = 0.0
                    display = _('Text answers') if answers else _('No answers')
                Report.create({
                    'session_id': session.id,
                    'question_id': question.id,
                    'sequence': question.sequence,
                    'question_text': question.name,
                    'question_type': question.question_type,
                    'target_area': question.target_area or False,
                    'average_value': average_value,
                    'average_pct': round(average_pct, 2),
                    'average_display': display,
                    'satisfaction': _result_for_pct(average_pct) if scored
                                    else 'not_scored',
                    'answered_count': len(answers),
                    'satisfactory_count': sum(
                        item['satisfaction'] == 'satisfactory' for item in answers),
                    'unsatisfactory_count': sum(
                        item['satisfaction'] == 'unsatisfactory' for item in answers),
                    'neutral_count': sum(
                        item['satisfaction'] == 'neutral' for item in answers),
                    'answer_ids': [(0, 0, answer) for answer in answers],
                })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reaction Question Satisfaction'),
            'res_model': self._name,
            'view_mode': 'list,form',
            'domain': [('session_id', '=', session.id)],
            'context': {'search_default_group_by_session': 0},
        }

    def action_refresh(self):
        self.ensure_one()
        return self.generate_for_session(self.session_id)


class EdsLevel1QuestionAnswer(models.Model):
    _name = 'eds.level1.question.answer'
    _description = 'Anonymous Reaction Question Answer'
    _order = 'anonymous_label, id'
    _rec_name = 'anonymous_label'

    report_id = fields.Many2one('eds.level1.question.report', string='Question Report',
                                required=True, readonly=True, ondelete='cascade', index=True)
    anonymous_label = fields.Char(string='Respondent', required=True, readonly=True)
    answer_value = fields.Text(string='Answer', readonly=True)
    score_pct = fields.Float(string='Score (%)', digits=(12, 2), readonly=True)
    satisfaction = fields.Selection(RESULTS, string='Assessment', readonly=True)


class EdsLevel1QuestionReportWizard(models.TransientModel):
    _name = 'eds.level1.question.report.wizard'
    _description = 'Generate Reaction Question Report'

    session_id = fields.Many2one('eds.session', string='Session', required=True,
                                 domain=[('status', '=', 'completed')])

    def action_generate(self):
        self.ensure_one()
        return self.env['eds.level1.question.report'].generate_for_session(
            self.session_id)


class EdsSession(models.Model):
    _inherit = 'eds.session'

    def action_open_level1_question_report(self):
        self.ensure_one()
        return self.env['eds.level1.question.report'].generate_for_session(self)

    def action_generate_level1_question_report(self):
        self.ensure_one()
        return self.action_open_level1_question_report()
