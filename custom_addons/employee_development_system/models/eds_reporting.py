# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class EdsReportTna(models.Model):
    _name = 'eds.report.tna'
    _description = 'Bank-wide TNA Summary Report'
    _auto = False

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
        self._cr.execute("""
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

    annual_plan_id = fields.Many2one('eds.annual.plan', string='Annual Plan', readonly=True)
    course_id = fields.Many2one('eds.course', string='Course', readonly=True)
    scheduled_month = fields.Char(string='Scheduled Month', readonly=True)
    budget_allocated = fields.Float(string='BudgetAllocated', readonly=True)
    status = fields.Selection([
        ('planned', 'Planned'),
        ('scheduled', 'Scheduled'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
        ('delayed', 'Delayed'),
    ], string='Status', readonly=True)
    total_lines = fields.Integer(string='Count', readonly=True)

    def init(self):
        self._cr.execute("""
            CREATE OR REPLACE VIEW eds_report_annual_plan AS (
                SELECT
                    l.id as id,
                    l.plan_id as annual_plan_id,
                    l.course_id,
                    l.scheduled_month,
                    l.budget_allocated,
                    l.status,
                    1 as total_lines
                FROM eds_annual_plan_line l
            );
        """)

class EdsReportDelivery(models.Model):
    _name = 'eds.report.delivery'
    _description = 'Training Delivery & Attendance Report'
    _auto = False

    session_id = fields.Many2one('eds.session', string='Session', readonly=True)
    course_id = fields.Many2one('eds.course', string='Course', readonly=True)
    employee_id = fields.Many2one('hr.employee', string='Participant', readonly=True)
    attended = fields.Boolean(string='Attended', readonly=True)
    attendance_percentage = fields.Float(string='Attendance Percentage (%)', readonly=True)

    def init(self):
        self._cr.execute("""
            CREATE OR REPLACE VIEW eds_report_delivery AS (
                SELECT
                    a.id as id,
                    a.session_id,
                    s.course_id,
                    a.employee_id,
                    a.attended,
                    a.attendance_percentage
                FROM eds_session_attendance a
                JOIN eds_session s ON s.id = a.session_id
            );
        """)

class EdsReportEvaluation(models.Model):
    _name = 'eds.report.evaluation'
    _description = 'Consolidated L1-L4 Training Evaluation Report'
    _auto = False

    session_id = fields.Many2one('eds.session', string='Session', readonly=True)
    course_id = fields.Many2one('eds.course', string='Course', readonly=True)
    employee_id = fields.Many2one('hr.employee', string='Participant', readonly=True)
    l1_score = fields.Float(string='L1 Reaction Score (%)', readonly=True)
    l2_post_score = fields.Float(string='L2 Learning Score (%)', readonly=True)
    l2_passed = fields.Boolean(string='L2 Passed', readonly=True)

    def init(self):
        self._cr.execute("""
            CREATE OR REPLACE VIEW eds_report_evaluation AS (
                SELECT
                    row_number() OVER () as id,
                    s.id as session_id,
                    s.course_id,
                    e.id as employee_id,
                    coalesce(l1.overall_score, 0.0) as l1_score,
                    coalesce(l2.post_score, 0.0) as l2_post_score,
                    coalesce(l2.passed, false) as l2_passed
                FROM eds_session s
                JOIN eds_enrollment en ON en.session_id = s.id
                JOIN hr_employee e ON e.id = en.employee_id
                LEFT JOIN eds_evaluation_level1 l1 ON (l1.session_id = s.id AND l1.employee_id = e.id)
                LEFT JOIN eds_evaluation_level2 l2 ON (l2.session_id = s.id AND l2.employee_id = e.id)
            );
        """)

class EdsReportTranscript(models.Model):
    _name = 'eds.report.transcript'
    _description = 'Employee Learning & Certification Transcript'
    _auto = False

    employee_id = fields.Many2one('hr.employee', string='Employee', readonly=True)
    course_id = fields.Many2one('eds.course', string='Course', readonly=True)
    session_id = fields.Many2one('eds.session', string='Session', readonly=True)
    completion_date = fields.Date(string='Completion Date', readonly=True)
    certificate_code = fields.Char(string='Certificate Code', readonly=True)

    def init(self):
        self._cr.execute("""
            CREATE OR REPLACE VIEW eds_report_transcript AS (
                SELECT
                    c.id as id,
                    c.employee_id,
                    c.course_id,
                    c.session_id,
                    c.issue_date as completion_date,
                    c.code as certificate_code
                FROM eds_certificate c
                WHERE c.state = 'issued'
            );
        """)

class EdsDashboard(models.TransientModel):
    _name = 'eds.dashboard'
    _description = 'EDS Executive Dashboard Provider'

    @api.model
    def get_eds_dashboard_data(self):
        tna_count = self.env['eds.tna.entry'].search_count([])
        session_count = self.env['eds.session'].search_count([])
        completed_sessions = self.env['eds.session'].search_count([('status', '=', 'completed')])
        cert_count = self.env['eds.certificate'].search_count([('state', '=', 'issued')])
        total_budget = sum(self.env['eds.budget'].search([('state', '=', 'approved')]).mapped('allocated'))
        spent_budget = sum(self.env['eds.budget'].search([('state', '=', 'approved')]).mapped('spent'))

        return {
            'tna_requests': tna_count,
            'total_sessions': session_count,
            'completed_sessions': completed_sessions,
            'issued_certificates': cert_count,
            'total_budget': total_budget,
            'spent_budget': spent_budget,
            'budget_utilization_pct': (spent_budget / total_budget * 100.0) if total_budget > 0 else 0.0,
        }
