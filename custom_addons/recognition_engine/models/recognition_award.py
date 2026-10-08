# -*- coding: utf-8 -*-
from datetime import date
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class RecognitionMonthlyAward(models.Model):
    """
    Unified Monthly Recognition Awards (FR-REC-002, FR-REC-003, FR-REC-005, FR-REC-007).
    Honors both Top Knowledge Contributor (KMS) and Best Learner (LMS).
    """
    _name = 'recognition.monthly.award'
    _description = 'Unified Monthly Recognition Award'
    _order = 'period_date desc, award_type asc'

    name = fields.Char(string='Recognition Title', compute='_compute_name', store=True)
    period_date = fields.Date(string='Month Period', required=True, default=fields.Date.context_today)
    award_type = fields.Selection([
        ('best_learner', 'Best Learner of the Month (LMS)'),
        ('best_contributor', 'Best Knowledge Contributor of the Month (KMS)'),
    ], string='Award Type', required=True, index=True)
    employee_id = fields.Many2one('hr.employee', string='Honored Employee', required=True)
    department_id = fields.Many2one('hr.department', related='employee_id.department_id', string='Department', readonly=True)
    branch_name = fields.Char(string='Branch / Operating Unit', compute='_compute_branch_name', store=True)
    points_total = fields.Integer(string='Monthly Points Tally', default=0)
    average_score = fields.Float(string='Average Exam Score (%)', default=0.0)
    courses_completed = fields.Integer(string='Courses Completed', default=0)
    badge = fields.Selection([
        ('gold', 'Gold Champion'),
        ('silver', 'Silver Champion'),
        ('bronze', 'Bronze Champion'),
    ], string='Achievement Badge', default='gold', required=True)
    citation = fields.Text(string='Citation / Highlights')

    @api.depends('period_date', 'award_type', 'employee_id')
    def _compute_name(self):
        for rec in self:
            if rec.period_date and rec.employee_id and rec.award_type:
                month_str = rec.period_date.strftime('%B %Y')
                type_label = dict(rec._fields['award_type'].selection).get(rec.award_type, 'Award')
                rec.name = f"{type_label} - {month_str} ({rec.employee_id.name})"
            else:
                rec.name = _("Monthly Recognition Award")

    @api.depends('employee_id')
    def _compute_branch_name(self):
        for rec in self:
            op_unit = getattr(rec.employee_id, 'default_operating_unit_id', False)
            rec.branch_name = op_unit.name if op_unit else ''

    @api.model
    def cron_calculate_monthly_awards(self):
        """Calculates both Best Learner (LMS) and Best Contributor (KMS) for previous month."""
        today = date.today()
        first_day_prev = (today - relativedelta(months=1)).replace(day=1)
        last_day_prev = today.replace(day=1) - relativedelta(days=1)
        month_label = first_day_prev.strftime('%B %Y')

        created_awards = self.env['recognition.monthly.award']

        # 1. Best Contributor (KMS)
        kms_points = self.env['recognition.point'].read_group(
            [
                ('source_module', '=', 'kms'),
                ('date_earned', '>=', first_day_prev),
                ('date_earned', '<=', last_day_prev),
            ],
            ['employee_id', 'points:sum'],
            ['employee_id'],
            orderby='points desc',
            limit=1
        )
        if kms_points and kms_points[0].get('employee_id'):
            emp_id = kms_points[0]['employee_id'][0]
            pts = kms_points[0]['points']
            emp = self.env['hr.employee'].browse(emp_id)
            award_kms = self.create({
                'period_date': first_day_prev,
                'award_type': 'best_contributor',
                'employee_id': emp.id,
                'points_total': pts,
                'badge': 'gold',
                'citation': _("Recognized as Bunna Bank Top Knowledge Contributor for %s with %s contribution points.") % (month_label, pts),
            })
            created_awards |= award_kms

        # 2. Best Learner (LMS)
        lms_points = self.env['recognition.point'].read_group(
            [
                ('source_module', '=', 'lms'),
                ('date_earned', '>=', first_day_prev),
                ('date_earned', '<=', last_day_prev),
            ],
            ['employee_id', 'points:sum'],
            ['employee_id'],
            orderby='points desc',
            limit=1
        )
        if lms_points and lms_points[0].get('employee_id'):
            emp_id = lms_points[0]['employee_id'][0]
            pts = lms_points[0]['points']
            emp = self.env['hr.employee'].browse(emp_id)
            award_lms = self.create({
                'period_date': first_day_prev,
                'award_type': 'best_learner',
                'employee_id': emp.id,
                'points_total': pts,
                'badge': 'gold',
                'citation': _("Recognized as Bunna Bank Top Learner for %s with %s learning performance points.") % (month_label, pts),
            })
            created_awards |= award_lms

        return created_awards
