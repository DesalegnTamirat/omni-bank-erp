# -*- coding: utf-8 -*-
from odoo import api, fields, models, tools, _


class LmsBranchComplianceReport(models.Model):
    """
    Branch & Operating Unit Compliance Matrix (FR-LMS-023, FR-LMS-024, FR-LMS-025).
    Aggregates training enrollments, completions, and compliance percentage by Operating Unit and Course.
    """
    _name = 'lms.branch.compliance.report'
    _description = 'Branch LMS Compliance Matrix'
    _auto = False
    _order = 'operating_unit_id, course_id'

    operating_unit_id = fields.Many2one('operating.unit', string='Operating Unit / Branch', readonly=True)
    department_id = fields.Many2one('hr.department', string='Department', readonly=True)
    course_id = fields.Many2one('lms.course', string='Mandatory Course', readonly=True)
    is_mandatory = fields.Boolean(string='Mandatory', readonly=True)

    total_assigned = fields.Integer(string='Total Assigned', readonly=True)
    total_completed = fields.Integer(string='Completed', readonly=True)
    total_in_progress = fields.Integer(string='In Progress', readonly=True)
    total_overdue = fields.Integer(string='Overdue', readonly=True)
    compliance_percentage = fields.Float(string='Compliance Rate (%)', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                -- One approved course represents the current obligation for
                -- every version in its lineage; enrollments remain historical.
                WITH RECURSIVE course_lineage AS (
                    SELECT course.id AS course_id, course.id AS root_id,
                           0 AS version_depth
                      FROM lms_course course
                     WHERE course.previous_version_id IS NULL
                    UNION ALL
                    SELECT successor.id, lineage.root_id,
                           lineage.version_depth + 1
                      FROM lms_course successor
                      JOIN course_lineage lineage
                        ON successor.previous_version_id = lineage.course_id
                ), current_course AS (
                    SELECT root_id, course_id
                      FROM (
                            SELECT lineage.root_id, course.id AS course_id,
                                   ROW_NUMBER() OVER (
                                       PARTITION BY lineage.root_id
                                       ORDER BY lineage.version_depth DESC, course.id DESC
                                   ) AS version_rank
                              FROM course_lineage lineage
                              JOIN lms_course course ON course.id = lineage.course_id
                             WHERE course.state = 'published'
                               AND course.is_latest_version = true
                               AND course.active = true
                           ) published_versions
                     WHERE version_rank = 1
                ), latest_enrollment AS (
                    SELECT en.*, lineage.root_id,
                           current_course.course_id AS current_course_id,
                           ROW_NUMBER() OVER (
                               PARTITION BY en.employee_id, lineage.root_id
                               ORDER BY en.is_mandatory DESC,
                                        (en.course_id = current_course.course_id) DESC,
                                        lineage.version_depth DESC,
                                        en.attempt_number DESC,
                                        en.enrollment_date DESC NULLS LAST, en.id DESC
                           ) AS attempt_rank
                      FROM lms_enrollment en
                      JOIN course_lineage lineage ON lineage.course_id = en.course_id
                      JOIN current_course ON current_course.root_id = lineage.root_id
                ), current_status AS (
                    SELECT en.*,
                           (CASE WHEN source_course.issue_certificate THEN COALESCE((
                                   SELECT cert.state = 'valid'
                                          AND (cert.expiry_date IS NULL
                                               OR cert.expiry_date >= CURRENT_DATE)
                                     FROM lms_certificate cert
                                     JOIN course_lineage cert_lineage
                                       ON cert_lineage.course_id = cert.course_id
                                    WHERE cert.employee_id = en.employee_id
                                      AND cert_lineage.root_id = en.root_id
                                      -- A new mandatory attempt on the current
                                      -- version must earn its own certificate.
                                      AND (en.course_id != en.current_course_id
                                           OR NOT en.is_mandatory
                                           OR cert.enrollment_id = en.id)
                                    ORDER BY cert.issue_date DESC, cert.id DESC
                                    LIMIT 1
                               ), FALSE) ELSE en.state = 'completed' END) AS is_compliant
                      FROM latest_enrollment en
                      JOIN lms_course source_course ON source_course.id = en.course_id
                     WHERE en.attempt_rank = 1
                )
                SELECT
                    row_number() OVER () AS id,
                    e.default_operating_unit_id AS operating_unit_id,
                    e.department_id AS department_id,
                    en.current_course_id AS course_id,
                    en.is_mandatory AS is_mandatory,
                    COUNT(en.id) AS total_assigned,
                    COUNT(CASE WHEN en.is_compliant THEN 1 END) AS total_completed,
                    COUNT(CASE WHEN en.state = 'in_progress' THEN 1 END) AS total_in_progress,
                    COUNT(CASE WHEN en.is_overdue = true THEN 1 END) AS total_overdue,
                    CASE 
                        WHEN COUNT(en.id) > 0 THEN 
                            ROUND((COUNT(CASE WHEN en.is_compliant THEN 1 END)::numeric / COUNT(en.id)::numeric) * 100.0, 2)
                        ELSE 0.0 
                    END AS compliance_percentage
                FROM current_status en
                JOIN hr_employee e ON e.id = en.employee_id
                GROUP BY e.default_operating_unit_id, e.department_id,
                         en.current_course_id, en.is_mandatory
            )
        """)


class LmsEngagementReport(models.Model):
    """
    LMS Course Engagement & Learning Analytics (FR-LMS-023, FR-LMS-024).
    Aggregates completion rate, average time spent (minutes), pass rate, and average score
    grouped by course, department, operating unit.
    """
    _name = 'lms.engagement.report'
    _description = 'LMS Course Engagement & Analytics Report'
    _auto = False
    _order = 'course_id, department_id'

    course_id = fields.Many2one('lms.course', string='Course', readonly=True)
    department_id = fields.Many2one('hr.department', string='Department', readonly=True)
    operating_unit_id = fields.Many2one('operating.unit', string='Branch / Unit', readonly=True)

    total_enrolled = fields.Integer(string='Total Enrolled', readonly=True)
    total_completed = fields.Integer(string='Completed', readonly=True)
    total_passed = fields.Integer(string='Passed Assessment', readonly=True)
    total_assessed = fields.Integer(string='Learners with Graded Final Exam', readonly=True)
    total_dropped_out = fields.Integer(
        string='Inactive Learners (30 Days)', readonly=True,
        help='Learners still in progress whose last recorded course activity was at least 30 days ago.'
    )
    completion_rate = fields.Float(string='Completion Rate (%)', readonly=True)
    drop_off_rate = fields.Float(string='Drop-off Rate (%)', readonly=True)
    pass_rate = fields.Float(string='Pass Rate (%)', readonly=True)
    avg_score = fields.Float(
        string='Avg Final Exam Score (%)', readonly=True,
        help='Mean of each assessed learner’s graded post-course attempts. See Learners with Graded Final Exam for sample size.',
    )
    avg_time_spent_minutes = fields.Float(string='Avg Time Spent (Minutes)', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                WITH latest_enrollment AS (
                    SELECT en.*,
                           ROW_NUMBER() OVER (
                               PARTITION BY en.employee_id, en.course_id
                               ORDER BY en.attempt_number DESC, en.id DESC
                           ) AS attempt_rank
                      FROM lms_enrollment en
                ), enroll_time AS (
                    SELECT 
                        enrollment_id, 
                        COALESCE(SUM(total_seconds_watched), 0) AS total_seconds,
                        MAX(write_date) AS last_activity
                    FROM lms_lesson_progress
                    GROUP BY enrollment_id
                ),
                exam_scores AS (
                    SELECT s.enrollment_id,
                           AVG(s.score_percentage) AS avg_score
                      FROM lms_exam_session s
                      JOIN lms_assessment assessment ON assessment.id = s.assessment_id
                     WHERE s.enrollment_id IS NOT NULL
                       AND assessment.assessment_type = 'post_course'
                       AND s.state IN ('passed', 'failed')
                     GROUP BY s.enrollment_id
                )
                SELECT
                    row_number() OVER () AS id,
                    en.course_id AS course_id,
                    e.department_id AS department_id,
                    e.default_operating_unit_id AS operating_unit_id,
                    COUNT(en.id) AS total_enrolled,
                    COUNT(CASE WHEN en.state = 'completed' THEN 1 END) AS total_completed,
                    COUNT(CASE WHEN en.post_assessment_passed = true THEN 1 END) AS total_passed,
                    COUNT(exam_scores.enrollment_id) AS total_assessed,
                    COUNT(CASE WHEN en.state = 'in_progress'
                               AND COALESCE(et.last_activity, en.write_date, en.create_date)
                                   < CURRENT_TIMESTAMP - INTERVAL '30 days'
                          THEN 1 END) AS total_dropped_out,
                    CASE 
                        WHEN COUNT(en.id) > 0 THEN 
                            ROUND((COUNT(CASE WHEN en.state = 'completed' THEN 1 END)::numeric / COUNT(en.id)::numeric) * 100.0, 2)
                        ELSE 0.0 
                    END AS completion_rate,
                    CASE WHEN COUNT(en.id) > 0 THEN ROUND((
                        COUNT(CASE WHEN en.state = 'in_progress'
                                    AND COALESCE(et.last_activity, en.write_date, en.create_date)
                                        < CURRENT_TIMESTAMP - INTERVAL '30 days'
                                   THEN 1 END)::numeric / COUNT(en.id)::numeric
                    ) * 100.0, 2) ELSE 0.0 END AS drop_off_rate,
                    CASE 
                        WHEN COUNT(en.id) > 0 THEN 
                            ROUND((COUNT(CASE WHEN en.post_assessment_passed = true THEN 1 END)::numeric / COUNT(en.id)::numeric) * 100.0, 2)
                        ELSE 0.0 
                    END AS pass_rate,
                    COALESCE(ROUND(AVG(exam_scores.avg_score)::numeric, 2), 0.0) AS avg_score,
                    ROUND((AVG(COALESCE(et.total_seconds, 0)) / 60.0)::numeric, 2) AS avg_time_spent_minutes
                FROM latest_enrollment en
                JOIN hr_employee e ON e.id = en.employee_id
                LEFT JOIN enroll_time et ON et.enrollment_id = en.id
                LEFT JOIN exam_scores ON exam_scores.enrollment_id = en.id
                WHERE en.attempt_rank = 1
                GROUP BY en.course_id, e.department_id, e.default_operating_unit_id
            )
        """)

