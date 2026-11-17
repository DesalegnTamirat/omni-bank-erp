"""Live reaction rating lists for providers, venues, and courses.

The overview includes every catalog entity, even when it has no responses.
Only submitted five-point answers contribute, and no respondent identity is
exposed in these views. Session and question views supply source drilldowns.
"""

from odoo import fields, models, tools


_RESULTS = [
    ('satisfactory', 'Satisfactory'),
    ('neutral', 'Neutral (50%)'),
    ('unsatisfactory', 'Unsatisfactory'),
]
_TARGETS = [
    ('vendor', 'Vendor'),
    ('hotel', 'Hotel / Venue'),
    ('course', 'Course'),
]


def _answers_sql():
    """Return the shared, company-scoped set of eligible reaction answers."""
    return """
        SELECT answer.id,
               reaction.id AS survey_id,
               session.id AS session_id,
               session.company_id,
               session.course_id,
               session.awarded_provider_id AS provider_id,
               session.venue_id,
               session.date_end AS session_date,
               question.target_area,
               question.id AS question_id,
               regexp_replace(btrim(question.name), '[[:space:]]+', ' ', 'g')
                   AS question_text,
               question.question_type,
               lower(regexp_replace(btrim(question.name), '[[:space:]]+', ' ', 'g'))
                   AS question_key,
               answer.rating_val
          FROM eds_evaluation_level1_line answer
          JOIN eds_evaluation_level1 reaction
            ON reaction.id = answer.evaluation_id
          JOIN eds_session session
            ON session.id = reaction.session_id
          JOIN eds_evaluation_instrument_question question
            ON question.id = answer.question_id
          JOIN eds_evaluation_instrument instrument
            ON instrument.id = question.instrument_id
         WHERE reaction.state IN ('submitted', 'consolidated')
           AND instrument.instrument_type = 'level1'
           AND question.question_type = 'scale_1_5'
           AND question.target_area IN ('vendor', 'hotel', 'course')
           AND answer.rating_val BETWEEN 1 AND 5
           AND session.company_id IS NOT NULL
    """


class EdsRatingOverview(models.Model):
    _name = 'eds.rating.overview'
    _description = 'Current Vendor, Hotel and Course Ratings'
    _auto = False
    _rec_name = 'name'
    _order = 'average_pct desc, id desc'

    name = fields.Char(string='Rated Entity', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    target_area = fields.Selection(_TARGETS, string='Reporting Area', readonly=True)
    provider_id = fields.Many2one('eds.external.provider', string='Vendor', readonly=True)
    venue_id = fields.Many2one('eds.venue', string='Hotel / Venue', readonly=True)
    course_id = fields.Many2one('eds.course', string='Course', readonly=True)
    response_count = fields.Integer(string='Rating Answers', readonly=True)
    respondent_count = fields.Integer(string='Respondents', readonly=True)
    session_count = fields.Integer(string='Sessions', readonly=True)
    average_rating = fields.Float(string='Average (out of 5)', digits=(5, 2), readonly=True)
    average_pct = fields.Float(string='Average (%)', digits=(5, 2), readonly=True)
    satisfaction = fields.Selection(_RESULTS, string='Result', readonly=True)
    last_session_date = fields.Datetime(string='Latest Session', readonly=True)

    def action_open_sessions(self):
        """Open rated sessions for this entity; list search handles further filters."""
        self.ensure_one()
        self.check_access('read')
        entity_field = {
            'vendor': 'provider_id',
            'hotel': 'venue_id',
            'course': 'course_id',
        }[self.target_area]
        action = self.env.ref(
            'employee_development_system.action_eds_rating_overview_session'
        ).read()[0]
        action['domain'] = [
            ('company_id', '=', self.company_id.id),
            ('target_area', '=', self.target_area),
            (entity_field, '=', self[entity_field].id),
        ]
        action['context'] = {'create': False, 'edit': False, 'delete': False}
        return action

    def action_open_questions(self):
        """Show average answers to this entity's questions across sessions."""
        self.ensure_one()
        self.check_access('read')
        entity_field = {
            'vendor': 'provider_id',
            'hotel': 'venue_id',
            'course': 'course_id',
        }[self.target_area]
        action = self.env.ref(
            'employee_development_system.action_eds_rating_overview_question'
        ).read()[0]
        action['domain'] = [
            ('company_id', '=', self.company_id.id),
            ('target_area', '=', self.target_area),
            (entity_field, '=', self[entity_field].id),
        ]
        action['context'] = {'create': False, 'edit': False, 'delete': False}
        return action

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE VIEW eds_rating_overview AS (
                WITH answers AS (
                    %s
                ), rated AS (
                    SELECT 1 AS kind, company_id, provider_id AS entity_id,
                           survey_id, session_id, session_date, rating_val
                      FROM answers
                     WHERE target_area = 'vendor' AND provider_id IS NOT NULL
                    UNION ALL
                    SELECT 2, company_id, venue_id,
                           survey_id, session_id, session_date, rating_val
                      FROM answers
                     WHERE target_area = 'hotel' AND venue_id IS NOT NULL
                    UNION ALL
                    SELECT 3, company_id, course_id,
                           survey_id, session_id, session_date, rating_val
                      FROM answers
                     WHERE target_area = 'course' AND course_id IS NOT NULL
                ), totals AS (
                    SELECT kind, company_id, entity_id,
                           COUNT(*)::integer AS response_count,
                           COUNT(DISTINCT survey_id)::integer AS respondent_count,
                           SUM(rating_val)::numeric AS score_total
                      FROM rated
                  GROUP BY kind, company_id, entity_id
                ), assigned_sessions AS (
                    SELECT 1 AS kind, company_id,
                           awarded_provider_id AS entity_id,
                           COUNT(*)::integer AS session_count,
                           MAX(date_end) AS last_session_date
                      FROM eds_session
                     WHERE awarded_provider_id IS NOT NULL
                  GROUP BY company_id, awarded_provider_id
                    UNION ALL
                    SELECT 2, company_id, venue_id,
                           COUNT(*)::integer, MAX(date_end)
                      FROM eds_session
                     WHERE venue_id IS NOT NULL
                  GROUP BY company_id, venue_id
                    UNION ALL
                    SELECT 3, company_id, course_id,
                           COUNT(*)::integer, MAX(date_end)
                      FROM eds_session
                     WHERE course_id IS NOT NULL
                  GROUP BY company_id, course_id
                ), inventory AS (
                    SELECT company.id AS company_id, 1 AS kind,
                           provider.id AS entity_id, provider.name,
                           provider.id AS provider_id,
                           NULL::integer AS venue_id,
                           NULL::integer AS course_id
                      FROM res_company company
                CROSS JOIN eds_external_provider provider
                     WHERE provider.active
                    UNION ALL
                    SELECT company.id, 2, venue.id, venue.name,
                           NULL::integer, venue.id, NULL::integer
                      FROM res_company company
                CROSS JOIN eds_venue venue
                     WHERE venue.active
                    UNION ALL
                    SELECT company.id, 3, course.id, course.name,
                           NULL::integer, NULL::integer, course.id
                      FROM res_company company
                CROSS JOIN eds_course course
                )
                SELECT (inventory.company_id::bigint * 1000000000
                        + inventory.kind::bigint * 100000000
                        + inventory.entity_id::bigint) AS id,
                       inventory.name,
                       inventory.company_id,
                       CASE inventory.kind WHEN 1 THEN 'vendor'
                                           WHEN 2 THEN 'hotel'
                                           ELSE 'course' END AS target_area,
                       inventory.provider_id,
                       inventory.venue_id,
                       inventory.course_id,
                       COALESCE(totals.response_count, 0) AS response_count,
                       COALESCE(totals.respondent_count, 0) AS respondent_count,
                       COALESCE(assigned_sessions.session_count, 0) AS session_count,
                       COALESCE(ROUND(totals.score_total
                           / NULLIF(totals.response_count, 0), 2), 0.0) AS average_rating,
                       COALESCE(ROUND(totals.score_total * 20.0
                           / NULLIF(totals.response_count, 0), 2), 0.0) AS average_pct,
                       CASE WHEN totals.response_count IS NULL THEN NULL
                            WHEN totals.score_total * 20.0 / totals.response_count > 50
                                THEN 'satisfactory'
                            WHEN totals.score_total * 20.0 / totals.response_count < 50
                                THEN 'unsatisfactory'
                            ELSE 'neutral' END AS satisfaction,
                       assigned_sessions.last_session_date
                  FROM inventory
             LEFT JOIN totals
                    ON totals.kind = inventory.kind
                   AND totals.company_id = inventory.company_id
                   AND totals.entity_id = inventory.entity_id
             LEFT JOIN assigned_sessions
                    ON assigned_sessions.kind = inventory.kind
                   AND assigned_sessions.company_id = inventory.company_id
                   AND assigned_sessions.entity_id = inventory.entity_id
            )
        """ % _answers_sql())


class EdsRatingOverviewSession(models.Model):
    _name = 'eds.rating.overview.session'
    _description = 'Current Reaction Ratings by Session'
    _auto = False
    _order = 'session_date desc, id desc'

    company_id = fields.Many2one('res.company', readonly=True)
    target_area = fields.Selection(_TARGETS, string='Reporting Area', readonly=True)
    provider_id = fields.Many2one('eds.external.provider', string='Vendor', readonly=True)
    venue_id = fields.Many2one('eds.venue', string='Hotel / Venue', readonly=True)
    course_id = fields.Many2one('eds.course', string='Course', readonly=True)
    session_id = fields.Many2one('eds.session', string='Session', readonly=True)
    session_date = fields.Datetime(string='Session End', readonly=True)
    response_count = fields.Integer(string='Rating Answers', readonly=True)
    respondent_count = fields.Integer(string='Respondents', readonly=True)
    average_rating = fields.Float(string='Average (out of 5)', digits=(5, 2), readonly=True)
    average_pct = fields.Float(string='Average (%)', digits=(5, 2), readonly=True)
    satisfaction = fields.Selection(_RESULTS, string='Result', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE VIEW eds_rating_overview_session AS (
                WITH answers AS (
                    %s
                ), totals AS (
                    SELECT session_id, target_area,
                           COUNT(*)::integer AS response_count,
                           COUNT(DISTINCT survey_id)::integer AS respondent_count,
                           ROUND(AVG(rating_val)::numeric, 2) AS average_rating,
                           ROUND(AVG(rating_val)::numeric * 20.0, 2) AS average_pct
                      FROM answers
                     WHERE (target_area = 'vendor' AND provider_id IS NOT NULL)
                        OR (target_area = 'hotel' AND venue_id IS NOT NULL)
                        OR (target_area = 'course' AND course_id IS NOT NULL)
                  GROUP BY session_id, target_area
                ), inventory AS (
                    SELECT session.id AS session_id, session.company_id,
                           session.awarded_provider_id AS provider_id,
                           session.venue_id, session.course_id,
                           session.date_end AS session_date,
                           1 AS kind, 'vendor' AS target_area
                      FROM eds_session session
                     WHERE session.awarded_provider_id IS NOT NULL
                    UNION ALL
                    SELECT session.id, session.company_id,
                           session.awarded_provider_id, session.venue_id,
                           session.course_id, session.date_end,
                           2, 'hotel'
                      FROM eds_session session
                     WHERE session.venue_id IS NOT NULL
                    UNION ALL
                    SELECT session.id, session.company_id,
                           session.awarded_provider_id, session.venue_id,
                           session.course_id, session.date_end,
                           3, 'course'
                      FROM eds_session session
                     WHERE session.course_id IS NOT NULL
                )
                SELECT (inventory.session_id::bigint * 4 + inventory.kind)::bigint AS id,
                       inventory.company_id, inventory.target_area,
                       inventory.provider_id, inventory.venue_id,
                       inventory.course_id, inventory.session_id,
                       inventory.session_date,
                       COALESCE(totals.response_count, 0) AS response_count,
                       COALESCE(totals.respondent_count, 0) AS respondent_count,
                       COALESCE(totals.average_rating, 0.0) AS average_rating,
                       COALESCE(totals.average_pct, 0.0) AS average_pct,
                       CASE WHEN totals.response_count IS NULL THEN NULL
                            WHEN totals.average_pct > 50 THEN 'satisfactory'
                            WHEN totals.average_pct < 50 THEN 'unsatisfactory'
                            ELSE 'neutral' END AS satisfaction
                  FROM inventory
             LEFT JOIN totals
                    ON totals.session_id = inventory.session_id
                   AND totals.target_area = inventory.target_area
            )
        """ % _answers_sql())


class EdsRatingOverviewQuestion(models.Model):
    """One live average for equivalent question wording across sessions."""

    _name = 'eds.rating.overview.question'
    _description = 'Reaction Question Average by Rated Entity'
    _auto = False
    _rec_name = 'question_text'
    _order = 'response_count desc, question_text, id'

    company_id = fields.Many2one('res.company', readonly=True)
    target_area = fields.Selection(_TARGETS, string='Reporting Area', readonly=True)
    provider_id = fields.Many2one('eds.external.provider', string='Vendor', readonly=True)
    venue_id = fields.Many2one('eds.venue', string='Hotel / Venue', readonly=True)
    course_id = fields.Many2one('eds.course', string='Course', readonly=True)
    question_text = fields.Char(string='Question', readonly=True)
    question_key = fields.Char(string='Normalized Question', readonly=True)
    question_type = fields.Selection(
        [('scale_1_5', '5-point rating')], string='Answer Format', readonly=True)
    source_question_count = fields.Integer(
        string='Question Versions', readonly=True,
        help='Number of configured question records with this wording.')
    response_count = fields.Integer(string='Rating Answers', readonly=True)
    respondent_count = fields.Integer(string='Respondents', readonly=True)
    session_count = fields.Integer(string='Source Session Count', readonly=True)
    average_rating = fields.Float(
        string='Average (out of 5)', digits=(5, 2), readonly=True)
    average_pct = fields.Float(string='Average (%)', digits=(5, 2), readonly=True)
    satisfaction = fields.Selection(_RESULTS, string='Result', readonly=True)
    last_session_date = fields.Datetime(string='Latest Source Session', readonly=True)
    session_source_ids = fields.One2many(
        'eds.rating.overview.question.session', 'summary_id',
        string='Source Sessions', readonly=True)

    def action_open_session_sources(self):
        """Open the contributing sessions for this cross-session average."""
        self.ensure_one()
        self.check_access('read')
        action = self.env.ref(
            'employee_development_system.action_eds_rating_overview_question_session'
        ).read()[0]
        action['domain'] = [('summary_id', '=', self.id)]
        action['context'] = {'create': False, 'edit': False, 'delete': False}
        return action

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE VIEW eds_rating_overview_question AS (
                WITH answers AS (
                    %s
                ), scoped AS (
                    SELECT answers.*,
                           CASE target_area WHEN 'vendor' THEN provider_id
                                            WHEN 'hotel' THEN venue_id
                                            ELSE course_id END AS entity_id
                      FROM answers
                     WHERE (target_area = 'vendor' AND provider_id IS NOT NULL)
                        OR (target_area = 'hotel' AND venue_id IS NOT NULL)
                        OR (target_area = 'course' AND course_id IS NOT NULL)
                )
                SELECT MIN(id)::bigint AS id,
                       company_id, target_area,
                       CASE WHEN target_area = 'vendor' THEN entity_id END AS provider_id,
                       CASE WHEN target_area = 'hotel' THEN entity_id END AS venue_id,
                       CASE WHEN target_area = 'course' THEN entity_id END AS course_id,
                       MIN(question_text) AS question_text,
                       question_key, question_type,
                       COUNT(DISTINCT question_id)::integer AS source_question_count,
                       COUNT(*)::integer AS response_count,
                       COUNT(DISTINCT survey_id)::integer AS respondent_count,
                       COUNT(DISTINCT session_id)::integer AS session_count,
                       ROUND(AVG(rating_val)::numeric, 2) AS average_rating,
                       ROUND(AVG(rating_val)::numeric * 20.0, 2) AS average_pct,
                       CASE WHEN AVG(rating_val) * 20.0 > 50 THEN 'satisfactory'
                            WHEN AVG(rating_val) * 20.0 < 50 THEN 'unsatisfactory'
                            ELSE 'neutral' END AS satisfaction,
                       MAX(session_date) AS last_session_date
                  FROM scoped
              GROUP BY company_id, target_area, entity_id,
                       question_key, question_type
            )
        """ % _answers_sql())


class EdsRatingOverviewQuestionSession(models.Model):
    """One question average for one source session, with no employee data."""

    _name = 'eds.rating.overview.question.session'
    _description = 'Reaction Question Average by Source Session'
    _auto = False
    _rec_name = 'question_text'
    _order = 'session_date desc, id desc'

    summary_id = fields.Many2one(
        'eds.rating.overview.question', string='Question Summary', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    target_area = fields.Selection(_TARGETS, string='Reporting Area', readonly=True)
    provider_id = fields.Many2one('eds.external.provider', string='Vendor', readonly=True)
    venue_id = fields.Many2one('eds.venue', string='Hotel / Venue', readonly=True)
    course_id = fields.Many2one('eds.course', string='Course', readonly=True)
    session_id = fields.Many2one('eds.session', string='Source Session', readonly=True)
    session_date = fields.Datetime(string='Session End', readonly=True)
    question_text = fields.Char(string='Question', readonly=True)
    question_key = fields.Char(string='Normalized Question', readonly=True)
    question_type = fields.Selection(
        [('scale_1_5', '5-point rating')], string='Answer Format', readonly=True)
    response_count = fields.Integer(string='Rating Answers', readonly=True)
    respondent_count = fields.Integer(string='Respondents', readonly=True)
    average_rating = fields.Float(
        string='Average (out of 5)', digits=(5, 2), readonly=True)
    average_pct = fields.Float(string='Average (%)', digits=(5, 2), readonly=True)
    satisfaction = fields.Selection(_RESULTS, string='Result', readonly=True)
    rating_1_count = fields.Integer(string='1 out of 5', readonly=True)
    rating_2_count = fields.Integer(string='2 out of 5', readonly=True)
    rating_3_count = fields.Integer(string='3 out of 5', readonly=True)
    rating_4_count = fields.Integer(string='4 out of 5', readonly=True)
    rating_5_count = fields.Integer(string='5 out of 5', readonly=True)

    def action_open_anonymous_answers(self):
        """Open the existing identity-free answers for this source session."""
        self.ensure_one()
        self.check_access('read')
        action = self.env['eds.level1.question.report'].generate_for_session(
            self.session_id)
        candidates = self.env['eds.level1.question.report'].search([
            ('session_id', '=', self.session_id.id),
            ('target_area', '=', self.target_area),
            ('question_type', '=', 'scale_1_5'),
        ])
        matching = candidates.filtered(
            lambda report: ' '.join((report.question_text or '').split()).lower()
            == self.question_key)
        action['domain'] = [('id', 'in', matching.ids)]
        action['context'] = {'create': False, 'edit': False, 'delete': False}
        return action

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        # Compute the summary ID independently; this view does not depend on
        # Odoo's model initialization order for the summary view.
        self.env.cr.execute("""
            CREATE VIEW eds_rating_overview_question_session AS (
                WITH answers AS (
                    %s
                ), scoped AS (
                    SELECT answers.*,
                           CASE target_area WHEN 'vendor' THEN provider_id
                                            WHEN 'hotel' THEN venue_id
                                            ELSE course_id END AS entity_id
                      FROM answers
                     WHERE (target_area = 'vendor' AND provider_id IS NOT NULL)
                        OR (target_area = 'hotel' AND venue_id IS NOT NULL)
                        OR (target_area = 'course' AND course_id IS NOT NULL)
                ), summary_ids AS (
                    SELECT company_id, target_area, entity_id,
                           question_key, question_type,
                           MIN(id)::bigint AS summary_id
                      FROM scoped
                  GROUP BY company_id, target_area, entity_id,
                           question_key, question_type
                )
                SELECT MIN(scoped.id)::bigint AS id,
                       summary_ids.summary_id,
                       scoped.company_id, scoped.target_area,
                       MAX(scoped.provider_id) AS provider_id,
                       MAX(scoped.venue_id) AS venue_id,
                       MAX(scoped.course_id) AS course_id,
                       scoped.session_id,
                       MAX(scoped.session_date) AS session_date,
                       MIN(scoped.question_text) AS question_text,
                       scoped.question_key, scoped.question_type,
                       COUNT(*)::integer AS response_count,
                       COUNT(DISTINCT scoped.survey_id)::integer AS respondent_count,
                       ROUND(AVG(scoped.rating_val)::numeric, 2) AS average_rating,
                       ROUND(AVG(scoped.rating_val)::numeric * 20.0, 2) AS average_pct,
                       CASE WHEN AVG(scoped.rating_val) * 20.0 > 50 THEN 'satisfactory'
                            WHEN AVG(scoped.rating_val) * 20.0 < 50 THEN 'unsatisfactory'
                            ELSE 'neutral' END AS satisfaction,
                       COUNT(*) FILTER (WHERE scoped.rating_val = 1)::integer
                           AS rating_1_count,
                       COUNT(*) FILTER (WHERE scoped.rating_val = 2)::integer
                           AS rating_2_count,
                       COUNT(*) FILTER (WHERE scoped.rating_val = 3)::integer
                           AS rating_3_count,
                       COUNT(*) FILTER (WHERE scoped.rating_val = 4)::integer
                           AS rating_4_count,
                       COUNT(*) FILTER (WHERE scoped.rating_val = 5)::integer
                           AS rating_5_count
                  FROM scoped
                  JOIN summary_ids
                    ON summary_ids.company_id = scoped.company_id
                   AND summary_ids.target_area = scoped.target_area
                   AND summary_ids.entity_id = scoped.entity_id
                   AND summary_ids.question_key = scoped.question_key
                   AND summary_ids.question_type = scoped.question_type
              GROUP BY summary_ids.summary_id,
                       scoped.company_id, scoped.target_area,
                       scoped.session_id, scoped.question_key,
                       scoped.question_type
            )
        """ % _answers_sql())
