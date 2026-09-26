# -*- coding: utf-8 -*-
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
import logging
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


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
        ('mentoring_signoff', 'Mentoring Cycle Concluded (+25)'),
        ('manual_award', 'Special Recognition Award'),
    ], string='Contribution Event', required=True)
    description = fields.Char(string='Activity Description')
    date_earned = fields.Date(string='Date', default=fields.Date.context_today)

    @api.depends('user_id')
    def _compute_employee_id(self):
        for rec in self:
            rec.employee_id = rec.user_id.employee_id.id if rec.user_id and rec.user_id.employee_id else False

    @api.model
    def award_points(self, user, points=None, source='manual_award', description=None):
        """Helper to create point ledger entries safely with configurable points and milestone checks."""
        if not user:
            return False

        # Config-driven point values via ir.config_parameter
        config_key = f"knowledge_management.points_{source}"
        cfg_val = self.env['ir.config_parameter'].sudo().get_param(config_key)
        if cfg_val and str(cfg_val).strip().isdigit():
            points = int(cfg_val)

        if points is None:
            default_map = {
                'document_publish': 20,
                'session_delivery': 15,
                'lesson_learned': 10,
                'accepted_answer': 10,
                'answer_upvote': 1,
                'mentoring_signoff': 25,
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
                source_module='kms',
                source_action=source or 'manual_award',
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
        """FR-REC-001, FR-REC-004: Congratulate employee when reaching 50, 200, 500, 1000 points."""
        milestones = [
            (50, 'Bronze Contributor (50 Points)'),
            (200, 'Silver Contributor (200 Points)'),
            (500, 'Gold Champion (500 Points)'),
            (1000, 'Platinum Legend (1000 Points)'),
        ]
        for threshold, title in milestones:
            if pts_before < threshold <= pts_after:
                msg = _("🎉 Congratulations %s! You have reached the %s milestone with %d total knowledge points!") % (
                    employee.name, title, pts_after
                )
                try:
                    partner_ids = [employee.user_id.partner_id.id] if employee.user_id and employee.user_id.partner_id else []
                    employee.message_post(
                        body=msg,
                        message_type='notification',
                        subtype_xmlid='mail.mt_note',
                        partner_ids=partner_ids
                    )
                except Exception as e:
                    _logger.debug("Failed to post milestone chatter message: %s", e)


class KmsMonthlyRecognition(models.Model):
    """
    Best Contributor of the Month (FR-REC-003, FR-REC-005, FR-REC-007).
    Monthly automated recognition honoring the top knowledge contributor.
    """
    _name = 'kms.monthly.recognition'
    _inherit = ['mail.thread']
    _description = 'KMS Best Contributor of the Month'
    _order = 'period_date desc'

    name = fields.Char(string='Recognition Title', compute='_compute_name', store=True)
    period_date = fields.Date(string='Month Period', required=True, default=fields.Date.context_today)
    employee_id = fields.Many2one('hr.employee', string='Honored Employee (Best Contributor)', required=True, tracking=True)
    department_id = fields.Many2one('hr.department', related='employee_id.department_id', string='Department', readonly=True)
    operating_unit_id = fields.Many2one('operating.unit', related='employee_id.default_operating_unit_id', string='Branch / Unit', readonly=True)
    points_total = fields.Integer(string='Monthly Points Tally', required=True, tracking=True)
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
        """Calculates best contributor for previous month with chatter notification and leaderboard refresh."""
        today = date.today()
        first_day_prev_month = (today - relativedelta(months=1)).replace(day=1)
        last_day_prev_month = today.replace(day=1) - relativedelta(days=1)

        domain = [
            ('date_earned', '>=', first_day_prev_month),
            ('date_earned', '<=', last_day_prev_month),
            ('employee_id', '!=', False)
        ]
        groups = self.env['kms.contributor.point']._read_group(
            domain=domain,
            groupby=['employee_id'],
            aggregates=['points:sum'],
            order='points:sum desc',
            limit=1
        )
        if groups:
            employee, total_pts = groups[0]
            if employee:
                rec = self.create({
                    'period_date': first_day_prev_month,
                    'employee_id': employee.id,
                    'points_total': int(total_pts or 0),
                    'citation': _('Awarded Best Contributor of the Month for outstanding contributions to Bunna Bank institutional knowledge base with %d points.') % int(total_pts or 0),
                    'badge': 'gold',
                })

                # Notify winner via chatter message
                winner_partner = employee.user_id.partner_id if employee.user_id else False
                body_msg = _("🏆 Congratulations %s! You have been awarded Best Contributor of the Month (%s) with %d points!") % (
                    employee.name, first_day_prev_month.strftime('%B %Y'), int(total_pts or 0)
                )
                try:
                    partner_ids = [winner_partner.id] if winner_partner else []
                    employee.message_post(
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


class RecognitionLeaderboardLine(models.Model):
    """
    Unified Gamification & Recognition Leaderboard (FR-REC-001 through FR-REC-007).
    Aggregates points across KMS, LMS, and unified sources for all-time and monthly rankings.
    """
    _name = 'recognition.leaderboard.line'
    _description = 'Recognition Leaderboard Line'
    _order = 'rank asc, points_total desc'

    employee_id = fields.Many2one('hr.employee', string='Staff Member', required=True, index=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', related='employee_id.user_id', string='User', readonly=True, store=True)
    department_id = fields.Many2one('hr.department', related='employee_id.department_id', string='Department', store=True, readonly=True)
    operating_unit_id = fields.Many2one('operating.unit', related='employee_id.default_operating_unit_id', string='Branch / Unit', store=True, readonly=True)
    points_total = fields.Integer(string='Points Total', default=0, index=True)
    rank = fields.Integer(string='Rank', index=True)
    source_module = fields.Selection([
        ('all', 'All / Unified'),
        ('kms', 'Knowledge Management (KMS)'),
        ('lms', 'Learning Management (LMS)'),
    ], string='Source Module', default='all', required=True, index=True)
    period = fields.Selection([
        ('all_time', 'All Time'),
        ('monthly', 'Monthly'),
    ], string='Period', default='all_time', required=True, index=True)
    period_date = fields.Date(string='Period Date', default=fields.Date.context_today, index=True)
    badge = fields.Selection([
        ('platinum', 'Platinum Champion'),
        ('gold', 'Gold Champion'),
        ('silver', 'Silver Champion'),
        ('bronze', 'Bronze Champion'),
        ('participant', 'Active Contributor/Learner'),
    ], string='Badge Tier', compute='_compute_badge', store=True)

    @api.depends('rank', 'points_total')
    def _compute_badge(self):
        for rec in self:
            if rec.rank == 1 or rec.points_total >= 1000:
                rec.badge = 'platinum'
            elif rec.rank in (2, 3) or rec.points_total >= 500:
                rec.badge = 'gold'
            elif rec.rank in (4, 5) or rec.points_total >= 200:
                rec.badge = 'silver'
            elif rec.rank in range(6, 11) or rec.points_total >= 50:
                rec.badge = 'bronze'
            else:
                rec.badge = 'participant'

    @api.model
    def rebuild_leaderboards(self):
        """
        FR-REC-001 through FR-REC-007:
        Aggregates points across KMS and LMS modules for all-time and monthly periods,
        and regenerates ranked leaderboard entries.
        """
        today = fields.Date.context_today(self)
        first_day_curr_month = today.replace(day=1)

        # Clear existing lines to prevent stale ranks
        self.sudo().search([]).unlink()

        def _build_and_insert(emp_points_map, module_code, period_type, p_date):
            sorted_items = sorted(emp_points_map.items(), key=lambda x: x[1], reverse=True)
            for rank_num, (emp_id, total_pts) in enumerate(sorted_items, start=1):
                if total_pts > 0:
                    self.sudo().create({
                        'employee_id': emp_id,
                        'points_total': total_pts,
                        'rank': rank_num,
                        'source_module': module_code,
                        'period': period_type,
                        'period_date': p_date,
                    })

        kms_pts_all = {}
        kms_pts_month = {}
        lms_pts_all = {}
        lms_pts_month = {}
        all_pts_all = {}
        all_pts_month = {}

        # 1. KMS Contributor Points
        kms_model = self.env.get('kms.contributor.point')
        if kms_model is not None:
            for pt in kms_model.sudo().search([('employee_id', '!=', False)]):
                emp_id = pt.employee_id.id
                pts = pt.points or 0
                is_curr_month = bool(pt.date_earned and pt.date_earned >= first_day_curr_month)
                kms_pts_all[emp_id] = kms_pts_all.get(emp_id, 0) + pts
                all_pts_all[emp_id] = all_pts_all.get(emp_id, 0) + pts
                if is_curr_month:
                    kms_pts_month[emp_id] = kms_pts_month.get(emp_id, 0) + pts
                    all_pts_month[emp_id] = all_pts_month.get(emp_id, 0) + pts

        # 2. LMS Gamification Points
        lms_model = self.env.get('lms.gamification.point')
        if lms_model is not None:
            for pt in lms_model.sudo().search([('employee_id', '!=', False)]):
                emp_id = pt.employee_id.id
                pts = pt.points or 0
                is_curr_month = bool(pt.date_earned and pt.date_earned >= first_day_curr_month)
                lms_pts_all[emp_id] = lms_pts_all.get(emp_id, 0) + pts
                all_pts_all[emp_id] = all_pts_all.get(emp_id, 0) + pts
                if is_curr_month:
                    lms_pts_month[emp_id] = lms_pts_month.get(emp_id, 0) + pts
                    all_pts_month[emp_id] = all_pts_month.get(emp_id, 0) + pts

        # 3. Insert ranked lines
        _build_and_insert(all_pts_all, 'all', 'all_time', today)
        _build_and_insert(all_pts_month, 'all', 'monthly', first_day_curr_month)
        _build_and_insert(kms_pts_all, 'kms', 'all_time', today)
        _build_and_insert(kms_pts_month, 'kms', 'monthly', first_day_curr_month)
        _build_and_insert(lms_pts_all, 'lms', 'all_time', today)
        _build_and_insert(lms_pts_month, 'lms', 'monthly', first_day_curr_month)
        return True
