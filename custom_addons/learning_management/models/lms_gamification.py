# -*- coding: utf-8 -*-
from datetime import date
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _


class LmsGamificationPoint(models.Model):
    """
    Learning Gamification Points Ledger (FR-REC-001, FR-REC-004).
    Tracks training performance points earned from course completions, quizzes, and speed.
    """
    _name = 'lms.gamification.point'
    _description = 'LMS Learning Points Ledger'
    _order = 'create_date desc'

    user_id = fields.Many2one('res.users', string='User', required=True, index=True)
    employee_id = fields.Many2one('hr.employee', string='Learner', compute='_compute_employee_id', store=True, index=True)
    points = fields.Integer(string='Points Earned', required=True)
    source = fields.Selection([
        ('course_complete', 'Course Completed (+30)'),
        ('perfect_score', 'Perfect Exam Score 100% (+50)'),
        ('assessment_pass', 'Passed Assessment (+15)'),
        ('first_attempt_pass', 'Passed on First Attempt (+10)'),
    ], string='Event', required=True)
    description = fields.Char(string='Activity Description')
    date_earned = fields.Date(string='Date Earned', default=fields.Date.context_today)

    @api.depends('user_id')
    def _compute_employee_id(self):
        for rec in self:
            rec.employee_id = rec.user_id.employee_id.id if rec.user_id and rec.user_id.employee_id else False

    @api.model
    def award_points(self, user, points, source, description=None):
        if not user:
            return
        return self.sudo().create({
            'user_id': user.id,
            'points': points,
            'source': source,
            'description': description or '',
            'date_earned': fields.Date.context_today(self),
        })


class LmsMonthlyScorer(models.Model):
    """
    Best Scorer of the Month (LMS) (FR-REC-002, FR-REC-005, FR-REC-007).
    Honors top-performing learner each month based on assessment scores and completions.
    """
    _name = 'lms.monthly.scorer'
    _description = 'LMS Best Scorer of the Month'
    _order = 'period_date desc'

    name = fields.Char(string='Recognition Title', compute='_compute_name', store=True)
    period_date = fields.Date(string='Month Period', required=True, default=fields.Date.context_today)
    employee_id = fields.Many2one('hr.employee', string='Best Scorer / Top Learner', required=True)
    department_id = fields.Many2one('hr.department', related='employee_id.department_id', string='Department', readonly=True)
    operating_unit_id = fields.Many2one('operating.unit', related='employee_id.default_operating_unit_id', string='Branch / Unit', readonly=True)
    average_score = fields.Float(string='Average Exam Score (%)', required=True)
    courses_completed = fields.Integer(string='Courses Completed in Month', required=True)
    badge = fields.Selection([
        ('gold', 'Gold Learning Scholar'),
        ('silver', 'Silver Learning Scholar'),
        ('bronze', 'Bronze Learning Scholar'),
    ], string='Honor Badge', default='gold', required=True)
    citation = fields.Text(string='Citation')

    @api.depends('period_date', 'employee_id')
    def _compute_name(self):
        for rec in self:
            if rec.period_date and rec.employee_id:
                m_str = rec.period_date.strftime('%B %Y')
                rec.name = f"Best Scorer of the Month - {m_str} ({rec.employee_id.name})"
            else:
                rec.name = _("Monthly Best Scorer")

    @api.model
    def cron_calculate_monthly_winner(self):
        """Monthly cron calculating top learning performer."""
        today = date.today()
        first_day = (today - relativedelta(months=1)).replace(day=1)
        last_day = today.replace(day=1) - relativedelta(days=1)

        enrollments = self.env['lms.enrollment'].search([
            ('completion_date', '>=', first_day),
            ('completion_date', '<=', last_day),
            ('state', '=', 'completed')
        ])

        emp_scores = {}
        for en in enrollments:
            emp_id = en.employee_id.id
            if emp_id not in emp_scores:
                emp_scores[emp_id] = {'scores': [], 'count': 0}
            emp_scores[emp_id]['scores'].append(en.final_score_percentage or 100.0)
            emp_scores[emp_id]['count'] += 1

        if emp_scores:
            best_emp_id = max(emp_scores.keys(), key=lambda e: (sum(emp_scores[e]['scores']) / len(emp_scores[e]['scores']), emp_scores[e]['count']))
            avg = sum(emp_scores[best_emp_id]['scores']) / len(emp_scores[best_emp_id]['scores'])
            count = emp_scores[best_emp_id]['count']
            emp = self.env['hr.employee'].browse(best_emp_id)

            self.create({
                'period_date': first_day,
                'employee_id': best_emp_id,
                'average_score': avg,
                'courses_completed': count,
                'badge': 'gold',
                'citation': _('Awarded Best Scorer of the Month for completing %d courses with an outstanding average score of %.1f%%.') % (count, avg),
            })
