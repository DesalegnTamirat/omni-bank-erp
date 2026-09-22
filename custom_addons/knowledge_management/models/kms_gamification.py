# -*- coding: utf-8 -*-
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _


class KmsContributorPoint(models.Model):
    """
    Knowledge Contribution Gamification Points (FR-REC-003, FR-REC-004).
    Tracks contribution events and points earned by employees for sharing institutional knowledge.
    """
    _name = 'kms.contributor.point'
    _description = 'KMS Contributor Points Ledger'
    _order = 'create_date desc'

    user_id = fields.Many2one('res.users', string='User', required=True, index=True)
    employee_id = fields.Many2one('hr.employee', string='Staff Member', compute='_compute_employee_id', store=True, index=True)
    points = fields.Integer(string='Points Earned', required=True)
    source = fields.Selection([
        ('document_publish', 'Approved Policy / SOP Published (+20)'),
        ('session_delivery', 'Tacit Knowledge Session Delivered (+15)'),
        ('lesson_learned', 'Validated Lesson Learned Contributed (+10)'),
        ('accepted_answer', 'Accepted Forum Solution (+10)'),
        ('answer_upvote', 'Peer Upvote on Knowledge Answer (+1)'),
        ('manual_award', 'Special Recognition Award'),
    ], string='Contribution Event', required=True)
    description = fields.Char(string='Activity Description')
    date_earned = fields.Date(string='Date', default=fields.Date.context_today)

    @api.depends('user_id')
    def _compute_employee_id(self):
        for rec in self:
            rec.employee_id = rec.user_id.employee_id.id if rec.user_id and rec.user_id.employee_id else False

    @api.model
    def award_points(self, user, points, source, description=None):
        """Helper to create point ledger entries safely."""
        if not user:
            return
        try:
            self.env['recognition.point'].sudo().award_points(
                user=user,
                points=points,
                source_module='kms',
                source_action=source,
                description=description or '',
            )
        except Exception as e:
            _logger = __import__('logging').getLogger(__name__)
            _logger.warning("Could not push points to recognition.point: %s", e)

        return self.sudo().create({
            'user_id': user.id,
            'points': points,
            'source': source,
            'description': description or '',
            'date_earned': fields.Date.context_today(self),
        })


class KmsMonthlyRecognition(models.Model):
    """
    Best Contributor of the Month (FR-REC-003, FR-REC-005, FR-REC-007).
    Monthly automated recognition honoring the top knowledge contributor.
    """
    _name = 'kms.monthly.recognition'
    _description = 'KMS Best Contributor of the Month'
    _order = 'period_date desc'

    name = fields.Char(string='Recognition Title', compute='_compute_name', store=True)
    period_date = fields.Date(string='Month Period', required=True, default=fields.Date.context_today)
    employee_id = fields.Many2one('hr.employee', string='Honored Employee (Best Contributor)', required=True)
    department_id = fields.Many2one('hr.department', related='employee_id.department_id', string='Department', readonly=True)
    operating_unit_id = fields.Many2one('operating.unit', related='employee_id.default_operating_unit_id', string='Branch / Unit', readonly=True)
    points_total = fields.Integer(string='Monthly Points Tally', required=True)
    citation = fields.Text(string='Citation / Achievement Highlights')
    badge = fields.Selection([
        ('gold', 'Gold Knowledge Champion'),
        ('silver', 'Silver Knowledge Champion'),
        ('bronze', 'Bronze Knowledge Champion'),
    ], string='Achievement Badge', default='gold', required=True)

    @api.depends('period_date', 'employee_id')
    def _compute_name(self):
        for rec in self:
            if rec.period_date and rec.employee_id:
                month_str = rec.period_date.strftime('%B %Y')
                rec.name = f"Best Contributor of the Month - {month_str} ({rec.employee_id.name})"
            else:
                rec.name = _("Monthly Recognition")

    @api.model
    def cron_calculate_monthly_winner(self):
        """Calculates best contributor for previous month."""
        today = date.today()
        first_day_prev_month = (today - relativedelta(months=1)).replace(day=1)
        last_day_prev_month = today.replace(day=1) - relativedelta(days=1)

        # Query point sums for prev month
        points = self.env['kms.contributor.point'].read_group(
            [('date_earned', '>=', first_day_prev_month), ('date_earned', '<=', last_day_prev_month)],
            ['employee_id', 'points:sum'],
            ['employee_id'],
            orderby='points desc',
            limit=1
        )
        if points and points[0].get('employee_id'):
            emp_id = points[0]['employee_id'][0]
            total_pts = points[0]['points']
            emp = self.env['hr.employee'].browse(emp_id)
            self.create({
                'period_date': first_day_prev_month,
                'employee_id': emp_id,
                'points_total': total_pts,
                'citation': _('Awarded Best Contributor of the Month for outstanding contributions to Bunna Bank institutional knowledge base with %d points.') % total_pts,
                'badge': 'gold',
            })
