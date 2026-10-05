# -*- coding: utf-8 -*-
from datetime import date
from dateutil.relativedelta import relativedelta
import logging
from markupsafe import Markup, escape
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


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
        ('manual_award', 'Special Learning Recognition Award'),
    ], string='Event', required=True)
    description = fields.Char(string='Activity Description')
    date_earned = fields.Date(string='Date Earned', default=fields.Date.context_today)

    @api.depends('user_id')
    def _compute_employee_id(self):
        for rec in self:
            rec.employee_id = rec.user_id.employee_id.id if rec.user_id and rec.user_id.employee_id else False

    @api.model
    def award_points(self, user, points=None, source='course_complete', description=None):
        """Helper to create point ledger entries safely with configurable points and milestone checks."""
        if not user:
            return False

        # Config-driven point values via ir.config_parameter
        config_key = f"learning_management.points_{source}"
        cfg_val = self.env['ir.config_parameter'].sudo().get_param(config_key)
        if cfg_val and str(cfg_val).strip().isdigit():
            points = int(cfg_val)

        if points is None:
            default_map = {
                'course_complete': 30,
                'perfect_score': 50,
                'assessment_pass': 15,
                'first_attempt_pass': 10,
                'manual_award': 10,
            }
            points = default_map.get(source, 10)

        employee = user.employee_id
        pts_before = 0
        if employee:
            pts_before = sum(self.search([('employee_id', '=', employee.id)]).mapped('points'))

        try:
            self.env['recognition.point'].sudo().award_points(
                user=user,
                points=points,
                source_module='lms',
                source_action=source or 'course_complete',
                description=description or '',
            )
        except Exception as e:
            _logger.warning("Could not push points to recognition.point: %s", e)

        record = self.sudo().create({
            'user_id': user.id,
            'points': points,
            'source': source,
            'description': description or '',
            'date_earned': fields.Date.context_today(self),
        })

        if employee:
            pts_after = pts_before + points
            self._check_milestone_badges(employee, pts_before, pts_after)

        return record

    @api.model
    def _check_milestone_badges(self, employee, pts_before, pts_after):
        """FR-REC-001, FR-REC-004: Congratulate learner when crossing 50, 200, 500, 1000 points."""
        milestones = [
            (50, 'Bronze Scholar (50 Points)'),
            (200, 'Silver Scholar (200 Points)'),
            (500, 'Gold Scholar (500 Points)'),
            (1000, 'Platinum Scholar (1000 Points)'),
        ]
        action_link = "/web#action=learning_management.action_lms_points_ledger"
        for threshold, title in milestones:
            if pts_before < threshold <= pts_after:
                msg_text = _("🎉 Congratulations %s! You have achieved the %s milestone with %d total learning points!") % (
                    employee.name, title, pts_after
                )
                body = Markup(f"""<p>{escape(msg_text)}</p>
<div style="margin-top: 10px;">
    <a href="{action_link}" style="background-color: #541718; color: #FFFFFF; padding: 6px 14px; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 12px; display: inline-block;">🏆 View My Learning Achievements</a>
</div>""")
                try:
                    partner_ids = [employee.user_id.partner_id.id] if employee.user_id and employee.user_id.partner_id else []
                    employee.message_post(
                        body=body,
                        message_type='notification',
                        subtype_xmlid='mail.mt_note',
                        partner_ids=partner_ids
                    )
                except Exception as e:
                    _logger.debug("Failed to post milestone chatter message: %s", e)


class LmsMonthlyScorer(models.Model):
    """
    Best Scorer of the Month (LMS) (FR-REC-002, FR-REC-005, FR-REC-007).
    Honors top-performing learner each month based on assessment scores and completions.
    """
    _name = 'lms.monthly.scorer'
    _inherit = ['mail.thread']
    _description = 'LMS Best Scorer of the Month'
    _order = 'period_date desc'

    name = fields.Char(string='Recognition Title', compute='_compute_name', store=True)
    period_date = fields.Date(string='Month Period', required=True, default=fields.Date.context_today)
    employee_id = fields.Many2one('hr.employee', string='Best Scorer / Top Learner', required=True, tracking=True)
    department_id = fields.Many2one('hr.department', related='employee_id.department_id', string='Department', readonly=True)
    operating_unit_id = fields.Many2one('operating.unit', related='employee_id.default_operating_unit_id', string='Branch / Unit', readonly=True)
    average_score = fields.Float(string='Average Exam Score (%)', required=True, tracking=True)
    courses_completed = fields.Integer(string='Courses Completed in Month', required=True, tracking=True)
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
        """Monthly cron calculating top learning performer with chatter notifications and leaderboard rebuild."""
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

            rec = self.create({
                'period_date': first_day,
                'employee_id': best_emp_id,
                'average_score': avg,
                'courses_completed': count,
                'badge': 'gold',
                'citation': _('Awarded Best Scorer of the Month for completing %d courses with an outstanding average score of %.1f%%.') % (count, avg),
            })

            winner_partner = emp.user_id.partner_id if emp.user_id else False
            body_msg = _("🏆 Congratulations %s! You have been awarded Best Scorer of the Month (%s) with an average exam score of %.1f%% across %d courses!") % (
                emp.name, first_day.strftime('%B %Y'), avg, count
            )
            try:
                partner_ids = [winner_partner.id] if winner_partner else []
                emp.message_post(
                    body=body_msg,
                    message_type='notification',
                    subtype_xmlid='mail.mt_comment',
                    partner_ids=partner_ids
                )
                rec.message_post(
                    body=body_msg,
                    partner_ids=partner_ids
                )
            except Exception as e:
                _logger.debug("Failed to post winner notification: %s", e)

        # Trigger leaderboard rebuild
        leaderboard_model = self.env.get('recognition.leaderboard.line')
        if leaderboard_model is not None:
            leaderboard_model.rebuild_leaderboards()

