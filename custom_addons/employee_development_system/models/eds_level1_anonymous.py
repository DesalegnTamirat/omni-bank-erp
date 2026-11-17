"""Read-only Level 1 answer projections for staff, without respondent identity.

The underlying survey and answer ACLs remain respondent-only.  Staff read
separate SQL views that contain no employee relation, and free text is
sanitized server-side before it is sent to the client.
"""

from collections import defaultdict
from hashlib import md5
import re

from odoo import api, fields, models, tools, _


_SUBMITTED = ('submitted', 'consolidated')
_EMAIL_RE = re.compile(r'(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}')


def anonymous_level1_labels(surveys):
    """Return survey-id -> per-session Employee N without using roster order.

    Pass *all* submitted surveys for each session, even when a report will
    display only one question.  The database UUID is an internal ordering salt;
    no employee metadata is returned or stored in the projection.
    """
    if not surveys:
        return {}
    salt = (surveys.env['ir.config_parameter'].sudo().get_param('database.uuid')
            or surveys.env.cr.dbname)
    by_session = defaultdict(list)
    for survey in surveys:
        if survey.state in _SUBMITTED:
            by_session[survey.session_id.id].append(survey.id)
    labels = {}
    for session_id, ids in by_session.items():
        ordered = sorted(ids, key=lambda survey_id: (
            md5(f'{salt}:{session_id}:{survey_id}'.encode()).hexdigest(),
            survey_id,
        ))
        labels.update({survey_id: 'Employee %s' % sequence
                       for sequence, survey_id in enumerate(ordered, 1)})
    return labels


def redact_level1_text(value, survey):
    """Mask explicit participant names and email addresses in free text.

    This removes obvious self-identifiers; subtle personal details in prose
    still need editorial review before publishing a report externally.
    """
    text = _EMAIL_RE.sub('[redacted]', value or '')
    session = survey.sudo().session_id
    people = (session.enrollment_ids.sudo().mapped('employee_id')
              | survey.sudo().employee_id)
    names = set()
    for person in people:
        if person.name:
            names.add(person.name.strip())
        if person == survey.employee_id and person.name:
            names.update(part for part in person.name.split() if len(part) >= 4)
    for name in sorted(names, key=len, reverse=True):
        text = re.sub(re.escape(name), '[redacted]', text, flags=re.IGNORECASE)
    return text


class EdsLevel1AnonymousResponse(models.Model):
    _name = 'eds.level1.anonymous.response'
    _description = 'Anonymous Level 1 Response'
    _auto = False
    _rec_name = 'anonymous_label'
    _order = 'session_id, anonymous_sequence, id'

    session_id = fields.Many2one('eds.session', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    anonymous_sequence = fields.Integer(readonly=True)
    anonymous_label = fields.Char(string='Response', readonly=True)
    answer_ids = fields.One2many(
        'eds.level1.anonymous.answer', 'response_id', string='Questions and Answers',
        readonly=True)
    answer_count = fields.Integer(string='Answers', compute='_compute_answer_count')

    @api.depends('answer_ids')
    def _compute_answer_count(self):
        for rec in self:
            rec.answer_count = len(rec.answer_ids)

    def action_open_answers(self):
        self.ensure_one()
        view = self.env.ref(
            'employee_development_system.view_eds_level1_anonymous_response_form')
        return {
            'type': 'ir.actions.act_window',
            'name': self.anonymous_label,
            'res_model': self._name,
            'view_mode': 'form',
            'views': [(view.id, 'form')],
            'res_id': self.id,
            'target': 'current',
            'context': {'create': False, 'edit': False, 'delete': False},
        }

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE VIEW {self._table} AS
            WITH pseudonym_salt AS (
                SELECT COALESCE(
                    (SELECT value FROM ir_config_parameter
                     WHERE key = 'database.uuid' LIMIT 1),
                    current_database()
                ) AS value
            ), numbered AS (
                SELECT survey.id,
                       survey.session_id,
                       session.company_id,
                       row_number() OVER (
                           PARTITION BY survey.session_id
                           ORDER BY md5(pseudonym_salt.value || ':' ||
                               survey.session_id::text || ':' || survey.id::text),
                               survey.id
                       )::integer AS anonymous_sequence
                  FROM eds_evaluation_level1 AS survey
                  JOIN eds_session AS session ON session.id = survey.session_id
                  CROSS JOIN pseudonym_salt
                 WHERE survey.state IN ('submitted', 'consolidated')
            )
            SELECT id, session_id, company_id, anonymous_sequence,
                   'Employee ' || anonymous_sequence::text AS anonymous_label
              FROM numbered
        """)


class EdsLevel1AnonymousAnswer(models.Model):
    _name = 'eds.level1.anonymous.answer'
    _description = 'Anonymous Level 1 Question Answer'
    _auto = False
    _order = 'id'

    response_id = fields.Many2one(
        'eds.level1.anonymous.response', string='Anonymous Response', readonly=True)
    session_id = fields.Many2one('eds.session', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    question_text = fields.Char(string='Question', readonly=True)
    answer_text = fields.Text(string='Answer', compute='_compute_answer_text')

    def _compute_answer_text(self):
        source_by_id = {
            line.id: line for line in
            self.env['eds.evaluation.level1.line'].sudo().browse(self.ids).exists()
        }
        for rec in self:
            line = source_by_id.get(rec.id)
            if not line or line.evaluation_id.state not in _SUBMITTED:
                rec.answer_text = False
                continue
            question_type = line.question_id.question_type
            if question_type == 'scale_1_5':
                rec.answer_text = ('%s / 5' % line.rating_val
                                   if line.rating_val else _('No answer'))
            elif question_type == 'scale_1_10':
                rec.answer_text = ('%s / 10' % line.rating_val
                                   if line.rating_val else _('No answer'))
            elif question_type == 'yes_no':
                rec.answer_text = (
                    _('Yes') if line.yes_no_val == 'yes' else
                    _('No') if line.yes_no_val == 'no' else _('No answer'))
            else:
                rec.answer_text = (redact_level1_text(line.text_val, line.evaluation_id)
                                   or _('No answer'))

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE VIEW {self._table} AS
            SELECT answer.id,
                   survey.id AS response_id,
                   survey.session_id,
                   session.company_id,
                   question.name AS question_text
              FROM eds_evaluation_level1_line AS answer
              JOIN eds_evaluation_level1 AS survey
                ON survey.id = answer.evaluation_id
              JOIN eds_session AS session ON session.id = survey.session_id
              JOIN eds_evaluation_instrument_question AS question
                ON question.id = answer.question_id
             WHERE survey.state IN ('submitted', 'consolidated')
        """)


class EdsSessionAnonymousLevel1(models.Model):
    _inherit = 'eds.session'

    level1_anonymous_response_ids = fields.One2many(
        'eds.level1.anonymous.response', 'session_id',
        string='Anonymous Participant Responses', readonly=True)

    def action_open_level1_anonymous_responses(self):
        self.ensure_one()
        self.check_access('read')
        action = self.env.ref(
            'employee_development_system.action_eds_level1_anonymous_responses'
        ).read()[0]
        action['domain'] = [('session_id', '=', self.id)]
        action['context'] = {'create': False, 'edit': False, 'delete': False}
        return action
