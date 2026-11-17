# -*- coding: utf-8 -*-
from odoo import models, fields, api, tools

from .eds_employee_projection import safe_employee_web_read

class EdsReportTna(models.Model):
    _name = 'eds.report.tna'
    _description = 'Bank-wide TNA Summary Report'
    _auto = False
    _order = 'id desc'

    cycle_id = fields.Many2one('eds.tna.cycle', string='TNA Cycle', readonly=True)
    work_unit_id = fields.Many2one('operating.unit', string='Work Unit', readonly=True)
    competency_id = fields.Many2one('competency.competency', string='Competency', readonly=True)
    gap_severity = fields.Selection([
        ('critical', 'Critical'),
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ], string='Severity', readonly=True)
    delivery_mode = fields.Selection([
        ('classroom', 'Classroom Training'),
        ('e_learning', 'E-Learning'),
        ('blended', 'Blended Learning'),
    ], string='Delivery Mode', readonly=True)
    total_entries = fields.Integer(string='Total Requested Entries', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, 'eds_report_tna')
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW eds_report_tna AS (
                SELECT
                    min(e.id) as id,
                    e.cycle_id,
                    e.work_unit_id,
                    e.competency_id,
                    e.gap_severity,
                    e.delivery_mode,
                    count(e.id) as total_entries
                FROM eds_tna_entry e
                GROUP BY e.cycle_id, e.work_unit_id, e.competency_id, e.gap_severity, e.delivery_mode
            );
        """)

class EdsReportAnnualPlan(models.Model):
    _name = 'eds.report.annual.plan'
    _description = 'Annual L&D Plan Variance Report'
    _auto = False
    _order = 'id desc'

    annual_plan_id = fields.Many2one('eds.annual.plan', string='Annual Plan', readonly=True)
    course_id = fields.Many2one('eds.course', string='Course', readonly=True)
    program_name = fields.Char(string='Program Name', readonly=True)
    quarter = fields.Selection([
        ('q1', 'Q1 (Jul–Sep)'),
        ('q2', 'Q2 (Oct–Dec)'),
        ('q3', 'Q3 (Jan–Mar)'),
        ('q4', 'Q4 (Apr–Jun)'),
        ('unallocated', 'Q1–Q4 / TBD (Unallocated)'),
    ], string='Quarter', readonly=True)
    scheduled_month = fields.Char(string='Scheduled Month', readonly=True)
    planned_participants = fields.Integer(string='Planned Participants', readonly=True)
    actual_participants = fields.Integer(string='Actual Participants', readonly=True)
    participant_variance = fields.Integer(string='Participant Variance', readonly=True)
    budget_allocated = fields.Float(string='Planned Budget (ETB)', readonly=True)
    actual_cost = fields.Float(string='Actual Cost (ETB)', readonly=True)
    cost_variance = fields.Float(string='Cost Variance (ETB)', readonly=True)
    cost_utilization_pct = fields.Float(string='Cost Utilisation %', readonly=True)
    status = fields.Selection([
        ('planned', 'Planned'),
        ('scheduled', 'Scheduled'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
        ('delayed', 'Delayed'),
    ], string='Status', readonly=True)
    total_lines = fields.Integer(string='Count', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, 'eds_report_annual_plan')
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW eds_report_annual_plan AS (
                SELECT
                    l.id as id,
                    l.plan_id as annual_plan_id,
                    l.course_id,
                    l.program_name,
                    l.quarter,
                    l.scheduled_month,
                    l.planned_participants,
                    l.actual_participants,
                    l.participant_variance,
                    l.budget_allocated,
                    l.actual_cost,
                    l.cost_variance,
                    l.cost_utilization_pct,
                    l.status,
                    1 as total_lines
                FROM eds_annual_plan_line l
            );
        """)

class EdsReportDelivery(models.Model):
    _name = 'eds.report.delivery'
    _description = 'Session Participation and Certification Report'
    _auto = False
    _order = 'id desc'

    session_id = fields.Many2one('eds.session', string='Session', readonly=True)
    course_id = fields.Many2one('eds.course', string='Course', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    session_date = fields.Datetime(string='Session Start', readonly=True)
    status = fields.Selection([
        ('draft', 'Draft'), ('scheduled', 'Scheduled'),
        ('ongoing', 'Ongoing'), ('completed', 'Completed'),
        ('cancelled', 'Cancelled'), ('rescheduled', 'Rescheduled'),
    ], string='Session Status', readonly=True)
    planned_count = fields.Integer(
        string='Planned', readonly=True,
        help='Target participants on the approved plan or unscheduled request. '
             'For sessions without either source, selected nominations are used.')
    enrolled_count = fields.Integer(
        string='Enrolled', readonly=True,
        help='Distinct participants with an accepted active seat; waitlisted, '
             'declined, cancelled, and replaced participants are excluded.')
    attended_count = fields.Integer(
        string='Attended', readonly=True,
        help='Distinct enrolled participants with at least one present attendance mark.')
    passed_count = fields.Integer(
        string='Passed', readonly=True,
        help='Distinct enrolled participants with a confirmed, passing pre/post result.')
    certified_count = fields.Integer(
        string='Certified', readonly=True,
        help='Distinct participants with an issued certificate for the session.')

    def action_open_attendance_details(self):
        self.ensure_one()
        self.session_id.check_access('read')
        action = self.env.ref(
            'employee_development_system.action_eds_session_attendance_summary'
        ).read()[0]
        action['domain'] = [('session_id', '=', self.session_id.id)]
        action['context'] = {'create': False, 'edit': False, 'delete': False}
        return action

    def init(self):
        tools.drop_view_if_exists(self.env.cr, 'eds_report_delivery')
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW eds_report_delivery AS (
                WITH accepted_seats AS (
                    SELECT DISTINCT en.session_id, en.employee_id
                      FROM eds_enrollment en
                 LEFT JOIN eds_nomination nom ON nom.id = en.nomination_id
                     WHERE en.state IN ('enrolled', 'completed', 'incomplete', 'absent')
                       AND (en.nomination_id IS NULL OR en.response_date IS NOT NULL
                            OR nom.employee_confirmed = 'confirmed')
                ), selected_counts AS (
                    SELECT session_id, COUNT(DISTINCT employee_id)::integer AS total
                      FROM eds_enrollment
                     WHERE selected
                       AND state IN ('suggested', 'invited', 'enrolled',
                                     'completed', 'incomplete', 'absent')
                  GROUP BY session_id
                ), enrolled_counts AS (
                    SELECT session_id, COUNT(*)::integer AS total
                      FROM accepted_seats
                  GROUP BY session_id
                ), attended_counts AS (
                    SELECT mark.session_id,
                           COUNT(DISTINCT mark.employee_id)::integer AS total
                      FROM eds_session_attendance mark
                      JOIN accepted_seats seat
                        ON seat.session_id = mark.session_id
                       AND seat.employee_id = mark.employee_id
                     WHERE mark.attended
                  GROUP BY mark.session_id
                ), passed_counts AS (
                    SELECT score.session_id,
                           COUNT(DISTINCT score.employee_id)::integer AS total
                      FROM eds_evaluation_level2 score
                      JOIN accepted_seats seat
                        ON seat.session_id = score.session_id
                       AND seat.employee_id = score.employee_id
                 LEFT JOIN eds_assessment pre ON pre.id = score.pre_assessment_id
                 LEFT JOIN eds_assessment post ON post.id = score.post_assessment_id
                     WHERE score.state = 'evaluated'
                       AND score.passed
                       AND ((COALESCE(score.score_entry_mode, FALSE)
                             AND score.score_confirmed IS TRUE)
                            OR (NOT COALESCE(score.score_entry_mode, FALSE)
                                AND pre.id IS NOT NULL AND post.id IS NOT NULL
                                AND (pre.entry_method = 'score_only'
                                     OR pre.state = 'graded')
                                AND (post.entry_method = 'score_only'
                                     OR post.state = 'graded')))
                  GROUP BY score.session_id
                ), certified_counts AS (
                    SELECT session_id, COUNT(DISTINCT employee_id)::integer AS total
                      FROM eds_certificate
                     WHERE state = 'issued'
                  GROUP BY session_id
                )
                SELECT s.id AS id,
                       s.id AS session_id,
                       s.course_id,
                       s.company_id,
                       s.date_start AS session_date,
                       s.status,
                       COALESCE(plan.planned_participants,
                                unscheduled.participant_count,
                                selected.total, 0)::integer AS planned_count,
                       COALESCE(enrolled.total, 0) AS enrolled_count,
                       COALESCE(attended.total, 0) AS attended_count,
                       COALESCE(passed.total, 0) AS passed_count,
                       COALESCE(certified.total, 0) AS certified_count
                  FROM eds_session s
             LEFT JOIN eds_annual_plan_line plan ON plan.id = s.plan_line_id
             LEFT JOIN eds_unscheduled_request unscheduled
                    ON unscheduled.id = s.unscheduled_request_id
             LEFT JOIN selected_counts selected ON selected.session_id = s.id
             LEFT JOIN enrolled_counts enrolled ON enrolled.session_id = s.id
             LEFT JOIN attended_counts attended ON attended.session_id = s.id
             LEFT JOIN passed_counts passed ON passed.session_id = s.id
             LEFT JOIN certified_counts certified ON certified.session_id = s.id
            );
        """)

class EdsReportEvaluation(models.Model):
    _name = 'eds.report.evaluation'
    _description = 'Learning Evaluation Summary'
    _auto = False
    _order = 'id desc'

    def web_read(self, specification):
        return safe_employee_web_read(
            self, specification, super().web_read, ('employee_id',))

    session_id = fields.Many2one('eds.session', string='Session', readonly=True)
    course_id = fields.Many2one('eds.course', string='Course', readonly=True)
    employee_id = fields.Many2one('hr.employee', string='Participant', readonly=True)
    l2_post_score = fields.Float(string='L2 Learning Score (%)', readonly=True)
    l2_passed = fields.Boolean(string='L2 Passed', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, 'eds_report_evaluation')
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW eds_report_evaluation AS (
                SELECT
                    en.id as id,
                    s.id as session_id,
                    s.course_id,
                    e.id as employee_id,
                    coalesce(CASE WHEN l2.score_entry_mode
                                  THEN l2.post_test_pct ELSE l2.post_score END, 0.0)
                        as l2_post_score,
                    coalesce(l2.passed, false) as l2_passed
                FROM eds_session s
                JOIN eds_enrollment en ON en.session_id = s.id
                JOIN hr_employee e ON e.id = en.employee_id
                LEFT JOIN eds_evaluation_level2 l2 ON (l2.session_id = s.id AND l2.employee_id = e.id)
                WHERE en.state IN ('enrolled', 'completed', 'incomplete', 'absent')
            );
        """)

class EdsReportTranscript(models.Model):
    _name = 'eds.report.transcript'
    _description = 'Employee Learning & Certification Transcript'
    _auto = False
    _order = 'session_end_date desc, id desc'

    def web_read(self, specification):
        return safe_employee_web_read(
            self, specification, super().web_read, ('employee_id',))

    employee_id = fields.Many2one('hr.employee', string='Employee', readonly=True)
    course_id = fields.Many2one('eds.course', string='Course', readonly=True)
    session_id = fields.Many2one('eds.session', string='Session', readonly=True)
    completion_date = fields.Date(string='Completion Date', readonly=True)
    session_end_date = fields.Date(string='Session End Date', readonly=True)
    enrollment_state = fields.Selection([
        ('completed', 'Completed'),
        ('incomplete', 'Incomplete'),
        ('absent', 'Absent'),
    ], string='Participation Outcome', readonly=True)
    certificate_id = fields.Many2one('eds.certificate', string='Certificate', readonly=True)
    commitment_id = fields.Many2one('training.commitment', string='Commitment', readonly=True)
    certificate_code = fields.Char(string='Certificate Code', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, 'eds_report_transcript')
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW eds_report_transcript AS (
                SELECT
                    e.id as id,
                    e.employee_id,
                    s.course_id,
                    e.session_id,
                    CASE WHEN e.state = 'completed' THEN s.date_end::date END as completion_date,
                    s.date_end::date as session_end_date,
                    e.state as enrollment_state,
                    c.id as certificate_id,
                    tc.id as commitment_id,
                    c.code as certificate_code
                FROM eds_enrollment e
                JOIN eds_session s ON s.id = e.session_id
                LEFT JOIN eds_certificate c
                    ON c.session_id = e.session_id
                    AND c.employee_id = e.employee_id
                    AND c.state = 'issued'
                LEFT JOIN training_commitment tc ON tc.eds_enrollment_id = e.id
                WHERE e.state IN ('completed', 'incomplete', 'absent')
                UNION ALL
                SELECT
                    -c.id as id,
                    c.employee_id,
                    c.course_id,
                    c.session_id,
                    CASE WHEN s.status = 'completed' THEN s.date_end::date END as completion_date,
                    s.date_end::date as session_end_date,
                    'completed' as enrollment_state,
                    c.id as certificate_id,
                    NULL::integer as commitment_id,
                    c.code as certificate_code
                FROM eds_certificate c
                JOIN eds_session s ON s.id = c.session_id
                WHERE c.state = 'issued'
                  AND NOT EXISTS (
                      SELECT 1 FROM eds_enrollment e
                      WHERE e.session_id = c.session_id
                        AND e.employee_id = c.employee_id)
            );
        """)
