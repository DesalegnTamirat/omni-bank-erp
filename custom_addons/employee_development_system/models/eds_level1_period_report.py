"""Anonymous Level 1 rating reports by provider, hotel, or course.

The report stores only aggregates. It never stores a respondent or a response
record, and it uses the session's actual awarded provider and venue.
"""

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


_TARGETS = [
    ('vendor', 'Provider / Vendor'),
    ('hotel', 'Hotel / Venue'),
    ('course', 'Course'),
]
_PERIODS = [
    ('quarter', 'Quarterly'),
    ('half', 'Semiannual'),
    ('annual', 'Annual'),
]
_RESULTS = [
    ('satisfactory', 'Satisfactory'),
    ('neutral', 'Neutral (50%)'),
    ('unsatisfactory', 'Unsatisfactory'),
]


class EdsLevel1RatingReport(models.Model):
    _name = 'eds.level1.rating.report'
    _description = 'Reaction Provider, Hotel and Course Rating Report'
    _order = 'generated_at desc, create_date desc, id desc'

    @api.model
    def _default_fiscal_year(self):
        today = fields.Date.context_today(self)
        return today.year if today.month >= 7 else today.year - 1

    @api.model
    def _default_period_index(self):
        today = fields.Date.context_today(self)
        return str(((today.month - 7) % 12) // 3 + 1)

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company, index=True)
    target_area = fields.Selection(_TARGETS, string='Rating Target',
                                   required=True, default='vendor', index=True)
    provider_id = fields.Many2one(
        'eds.external.provider', string='Provider / Vendor', index=True,
        help='Leave empty to compare every provider. Combine with a course to '
             'see that provider on one programme.')
    venue_id = fields.Many2one(
        'eds.venue', string='Hotel / Venue', index=True,
        help='Leave empty to compare every hotel or venue.')
    course_id = fields.Many2one(
        'eds.course', string='Course', index=True,
        help='Leave empty to see all courses. Combine with a provider to see '
             'that provider on this course.')
    fiscal_year = fields.Integer(
        string='Fiscal Year Starting July', required=True,
        default=_default_fiscal_year, index=True,
        help='FY 2026 runs from 1 July 2026 through 30 June 2027.')
    period_kind = fields.Selection(
        _PERIODS, string='Period', required=True, default='quarter', index=True)
    period_index = fields.Selection(
        [('1', '1'), ('2', '2'), ('3', '3'), ('4', '4')],
        string='Quarter / Half Number', required=True,
        default=_default_period_index, index=True,
        help='Choose 1–4 for a quarter, 1–2 for a half-year; annual uses 1.')
    date_from = fields.Date(
        string='From', compute='_compute_period_dates', store=True)
    date_to = fields.Date(
        string='Through', compute='_compute_period_dates', store=True)
    state = fields.Selection(
        [('draft', 'Not Generated'), ('generated', 'Generated')],
        required=True, default='draft', readonly=True)
    generated_at = fields.Datetime(string='Generated At', readonly=True)
    line_ids = fields.One2many(
        'eds.level1.rating.report.line', 'report_id', string='Ratings', readonly=True)
    response_count = fields.Integer(
        string='Rating Answers', compute='_compute_summary')
    respondent_count = fields.Integer(
        string='Respondents', compute='_compute_summary')
    session_count = fields.Integer(
        string='Sessions', compute='_compute_summary')
    average_rating = fields.Float(
        string='Average (out of 5)', digits=(5, 2), compute='_compute_summary')
    average_pct = fields.Float(
        string='Average (%)', digits=(5, 2), compute='_compute_summary')
    satisfaction = fields.Selection(
        _RESULTS, string='Result', compute='_compute_summary')

    @api.depends('target_area', 'provider_id', 'venue_id', 'course_id',
                 'fiscal_year', 'period_kind', 'period_index')
    def _compute_name(self):
        target_labels = dict(_TARGETS)
        for rec in self:
            period = {
                'quarter': 'Q%s' % (rec.period_index or '1'),
                'half': 'H%s' % (rec.period_index or '1'),
                'annual': 'Full year',
            }.get(rec.period_kind, '')
            entity = ((rec.provider_id.name if rec.target_area == 'vendor'
                       and rec.provider_id else False)
                      or (rec.venue_id.name if rec.target_area == 'hotel'
                          and rec.venue_id else False)
                      or (rec.course_id.name if rec.target_area == 'course'
                          and rec.course_id else False)
                      or _('All'))
            rec.name = '%s: %s · FY%s %s' % (
                target_labels.get(rec.target_area, _('Reaction Ratings')),
                entity, rec.fiscal_year or '', period)

    @api.depends('fiscal_year', 'period_kind', 'period_index')
    def _compute_period_dates(self):
        for rec in self:
            if not rec.fiscal_year or not rec.period_kind or not rec.period_index:
                rec.date_from = False
                rec.date_to = False
                continue
            number = int(rec.period_index)
            months = {'quarter': 3, 'half': 6, 'annual': 12}[rec.period_kind]
            start = date(rec.fiscal_year, 7, 1)
            start += relativedelta(months=(number - 1) * months)
            rec.date_from = start
            rec.date_to = start + relativedelta(months=months) - timedelta(days=1)

    @api.depends('line_ids.response_count', 'line_ids.respondent_count',
                 'line_ids.session_count', 'line_ids.score_total')
    def _compute_summary(self):
        for rec in self:
            rec.response_count = sum(rec.line_ids.mapped('response_count'))
            rec.respondent_count = sum(rec.line_ids.mapped('respondent_count'))
            rec.session_count = sum(rec.line_ids.mapped('session_count'))
            total = sum(rec.line_ids.mapped('score_total'))
            average = total / rec.response_count if rec.response_count else 0.0
            percentage = average * 20
            rec.average_rating = (
                round(average, 2) if rec.response_count else 0.0)
            rec.average_pct = round(percentage, 2)
            rec.satisfaction = (
                'satisfactory' if percentage > 50 else
                'unsatisfactory' if percentage < 50 and rec.response_count else
                'neutral' if rec.response_count else False)

    @api.onchange('period_kind')
    def _onchange_period_kind(self):
        for rec in self:
            if rec.period_kind == 'annual' or (
                    rec.period_kind == 'half' and rec.period_index not in ('1', '2')):
                rec.period_index = '1'

    @api.onchange('target_area')
    def _onchange_target_area(self):
        for rec in self:
            if rec.target_area != 'hotel':
                rec.venue_id = False

    @api.constrains('fiscal_year', 'period_kind', 'period_index', 'target_area',
                    'provider_id', 'venue_id')
    def _check_scope(self):
        for rec in self:
            if rec.fiscal_year < 1900 or rec.fiscal_year > 2100:
                raise ValidationError(_('Enter a valid fiscal year.'))
            number = int(rec.period_index or '0')
            limit = {'quarter': 4, 'half': 2, 'annual': 1}.get(rec.period_kind, 0)
            if number < 1 or number > limit:
                raise ValidationError(_(
                    'Choose a quarter from 1 to 4, a half-year from 1 to 2, '
                    'or 1 for an annual report.'))
            if rec.target_area != 'hotel' and rec.venue_id:
                raise ValidationError(_(
                    'A hotel filter applies only to hotel ratings.'))

    def write(self, vals):
        scope_fields = {
            'company_id', 'target_area', 'provider_id', 'venue_id', 'course_id',
            'fiscal_year', 'period_kind', 'period_index',
        }
        result = super().write(vals)
        if scope_fields.intersection(vals):
            self.mapped('line_ids').sudo().unlink()
            super(EdsLevel1RatingReport, self).write({
                'state': 'draft', 'generated_at': False,
            })
        return result

    def action_generate(self):
        self.ensure_one()
        if not (self.env.su or self.env.user.has_group(
                'employee_development_system.group_eds_officer')):
            raise AccessError(_('Only Learning and Development staff can generate this report.'))
        if self.company_id not in self.env.companies and not self.env.su:
            raise AccessError(_('Switch to the report company before generating it.'))
        if not self.date_from or not self.date_to:
            raise ValidationError(_('Select a valid reporting period.'))

        # Only submitted answers to five-point Level 1 questions with an
        # explicit target contribute. Open text and incomplete surveys do not.
        start = datetime.combine(self.date_from, time.min)
        end_exclusive = datetime.combine(self.date_to + timedelta(days=1), time.min)
        domain = [
            ('evaluation_id.state', 'in', ('submitted', 'consolidated')),
            ('evaluation_id.session_id.company_id', '=', self.company_id.id),
            ('evaluation_id.session_id.date_end', '>=', fields.Datetime.to_string(start)),
            ('evaluation_id.session_id.date_end', '<', fields.Datetime.to_string(end_exclusive)),
            ('question_id.instrument_id.instrument_type', '=', 'level1'),
            ('question_id.question_type', '=', 'scale_1_5'),
            ('question_id.target_area', '=', self.target_area),
            ('rating_val', '>=', 1),
            ('rating_val', '<=', 5),
        ]
        if self.course_id:
            domain.append(('evaluation_id.session_id.course_id', '=', self.course_id.id))
        if self.provider_id:
            domain.append(('evaluation_id.session_id.awarded_provider_id', '=', self.provider_id.id))
        if self.venue_id:
            domain.append(('evaluation_id.session_id.venue_id', '=', self.venue_id.id))
        answers = self.env['eds.evaluation.level1.line'].sudo().search(domain)
        groups = defaultdict(lambda: {
            'ratings': [], 'survey_ids': set(), 'session_ids': set(),
            'question_ids': set(), 'provider_id': False,
            'venue_id': False, 'course_id': False,
        })
        for answer in answers:
            session = answer.evaluation_id.session_id
            provider = session.awarded_provider_id
            venue = session.venue_id
            course = session.course_id
            if self.target_area == 'vendor':
                if not provider:
                    continue
                key = (provider.id, course.id if self.course_id else 0)
            elif self.target_area == 'hotel':
                if not venue:
                    continue
                key = (venue.id, course.id if self.course_id else 0)
            else:
                if not course:
                    continue
                key = (course.id, provider.id if self.provider_id else 0)
            group = groups[key]
            group['ratings'].append(answer.rating_val)
            group['survey_ids'].add(answer.evaluation_id.id)
            group['session_ids'].add(session.id)
            group['question_ids'].add(answer.question_id.id)
            if self.target_area == 'vendor' or self.provider_id:
                group['provider_id'] = provider.id
            if self.target_area == 'hotel':
                group['venue_id'] = venue.id
            if self.target_area == 'course' or self.course_id:
                group['course_id'] = course.id

        values = []
        for group in groups.values():
            ratings = group['ratings']
            count = len(ratings)
            average = sum(ratings) / count
            percent = average * 20
            values.append({
                'report_id': self.id,
                'provider_id': group['provider_id'],
                'venue_id': group['venue_id'],
                'course_id': group['course_id'],
                'response_count': count,
                'respondent_count': len(group['survey_ids']),
                'session_count': len(group['session_ids']),
                'question_count': len(group['question_ids']),
                'score_total': sum(ratings),
                'average_rating': round(average, 2),
                'average_pct': round(percent, 2),
                'satisfaction': (
                    'satisfactory' if percent > 50 else
                    'unsatisfactory' if percent < 50 else 'neutral'),
            })
        # A savepoint leaves the previous generated report intact if the new
        # computation or row creation fails.
        with self.env.cr.savepoint():
            self.env.cr.execute(
                'SELECT id FROM eds_level1_rating_report WHERE id = %s FOR UPDATE',
                [self.id],
            )
            self.line_ids.sudo().unlink()
            if values:
                self.env['eds.level1.rating.report.line'].sudo().create(values)
            self.invalidate_recordset(['line_ids'])
            self.write({'state': 'generated', 'generated_at': fields.Datetime.now()})
        return {
            'type': 'ir.actions.client', 'tag': 'bunna_refresh_form',
            'params': {'res_model': self._name, 'res_id': self.id},
        }

    def action_open_results(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reaction Rating Results'),
            'res_model': 'eds.level1.rating.report.line',
            'view_mode': 'list,form',
            'domain': [('report_id', '=', self.id)],
            'context': {'search_default_report_id': self.id},
        }


class EdsLevel1RatingReportLine(models.Model):
    _name = 'eds.level1.rating.report.line'
    _description = 'Anonymous Reaction Rating Result'
    _order = 'average_pct desc, id desc'

    report_id = fields.Many2one(
        'eds.level1.rating.report', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(
        'res.company', related='report_id.company_id', store=True, index=True)
    target_area = fields.Selection(
        related='report_id.target_area', store=True, index=True)
    fiscal_year = fields.Integer(
        related='report_id.fiscal_year', store=True, index=True)
    period_kind = fields.Selection(
        related='report_id.period_kind', store=True, index=True)
    period_index = fields.Selection(
        related='report_id.period_index', store=True, index=True)
    date_from = fields.Date(related='report_id.date_from', store=True)
    date_to = fields.Date(related='report_id.date_to', store=True)
    provider_id = fields.Many2one('eds.external.provider', string='Provider / Vendor')
    venue_id = fields.Many2one('eds.venue', string='Hotel / Venue')
    course_id = fields.Many2one('eds.course', string='Course')
    response_count = fields.Integer(string='Rating Answers', readonly=True)
    respondent_count = fields.Integer(string='Respondents', readonly=True)
    session_count = fields.Integer(string='Sessions', readonly=True)
    question_count = fields.Integer(string='Questions', readonly=True)
    score_total = fields.Integer(string='Sum of Ratings', readonly=True)
    average_rating = fields.Float(string='Average (out of 5)', digits=(5, 2), readonly=True)
    average_pct = fields.Float(string='Average (%)', digits=(5, 2), readonly=True)
    satisfaction = fields.Selection(_RESULTS, string='Result', readonly=True)
