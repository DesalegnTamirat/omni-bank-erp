"""Read-only employee projection of confirmed pre/post learning scores.

Keep the learner-facing model limited to the four values shown in My Learning.
The underlying Level 2 scorecard also contains staff notes and assessment
history, so granting learners access to that model would expose more data.
"""

from odoo import fields, models, tools


class EdsEmployeePrepostScore(models.Model):
    _name = 'eds.employee.prepost.score'
    _description = 'My Pre/Post Learning Score'
    _auto = False
    _rec_name = 'session_id'
    _order = 'id desc'

    session_id = fields.Many2one('eds.session', string='Training Session', readonly=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', readonly=True)
    maximum_score = fields.Float(string='Maximum Score', readonly=True)
    pre_score = fields.Float(string='Pre Score', readonly=True)
    post_score = fields.Float(string='Post Score', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW eds_employee_prepost_score AS (
                SELECT DISTINCT ON (score.session_id, score.employee_id)
                    score.id,
                    score.session_id,
                    score.employee_id,
                    CASE WHEN COALESCE(score.score_entry_mode, FALSE)
                         THEN score.total_marks ELSE 100.0 END AS maximum_score,
                    CASE WHEN COALESCE(score.score_entry_mode, FALSE)
                         THEN score.pre_test_score
                         WHEN score.pre_assessment_id IS NOT NULL
                              OR score.pre_test_score <> 0
                         THEN score.pre_test_pct
                         ELSE NULL END AS pre_score,
                    CASE WHEN COALESCE(score.score_entry_mode, FALSE)
                         THEN score.post_test_score
                         WHEN score.post_assessment_id IS NOT NULL
                              OR score.post_test_score <> 0
                         THEN score.post_test_pct
                         ELSE NULL END AS post_score
                FROM eds_evaluation_level2 AS score
                WHERE score.state = 'evaluated'
                  AND ((COALESCE(score.score_entry_mode, FALSE)
                        AND score.score_confirmed IS TRUE)
                       OR (NOT COALESCE(score.score_entry_mode, FALSE)
                           AND (score.pre_assessment_id IS NOT NULL
                                OR score.post_assessment_id IS NOT NULL
                                OR score.pre_test_score <> 0
                                OR score.post_test_score <> 0)))
                ORDER BY score.session_id, score.employee_id, score.id DESC
            )
        """)
