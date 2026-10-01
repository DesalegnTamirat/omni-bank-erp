# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from .t2_appraisal import detect_period_type, get_target_for_period


class T3Appraisal(models.Model):
    _name = 't3.appraisal'
    _description = 'Tier 3 Performance Appraisal'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_date desc, name'

    name = fields.Char(
        string='Appraisal Name',
        required=True,
    )
    scorecard_id = fields.Many2one(
        't3.scorecard',
        string='Tier 3 Scorecard',
        readonly=True,
    )
    planning_name = fields.Char(
        string='Planning Name',
        readonly=True,
    )
    fiscal_year_id = fields.Many2one(
        'performance.fiscal.year',
        string='Fiscal Year',
        readonly=True,
    )
    fiscal_year_date_start = fields.Date(
        string='Fiscal Year Start Date',
        related='fiscal_year_id.date_start',
        readonly=True,
    )
    fiscal_year_date_end = fields.Date(
        string='Fiscal Year End Date',
        related='fiscal_year_id.date_end',
        readonly=True,
    )
    appraisal_period_id = fields.Many2one(
        'appraisal.period',
        string='Appraisal Period',
        readonly=True,
    )
    appraisal_period_code = fields.Selection(
        related='appraisal_period_id.code',
        store=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company Name',
        default=lambda self: self.env.company,
        readonly=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        default=lambda self: self.env.user.employee_id,
    )
    employee_image_128 = fields.Image(
        string='Employee Photo',
        related='employee_id.image_128',
        max_width=128,
        max_height=128,
        store=True,
    )
    operating_unit_id = fields.Many2one(
        'operating.unit',
        string='Operating Unit Name',
        readonly=True,
    )
    department_id = fields.Many2one(
        'hr.department',
        compute='_compute_department_id',
        string='Department',
        store=True,
    )
    job_id = fields.Many2one(
        'hr.job',
        string='Job Position',
        readonly=True,
    )
    start_date = fields.Date(
        string='Start Date',
        readonly=True,
    )
    end_date = fields.Date(
        string='End Date',
        readonly=True,
    )
    appraisal_date = fields.Date(
        string='Appraisal Date',
        default=fields.Date.context_today,
    )
    accept_by = fields.Date(
        string='Accept By',
        help='Date before which the employee should accept or reject the appraisal.',
    )
    manager_id = fields.Many2one(
        'hr.employee',
        string='Manager',
        readonly=False,
    )
    employee_score = fields.Float(
        string='Employee Score',
        digits=(10, 2),
        compute='_compute_employee_score',
        store=True,
        readonly=False,
    )
    performance_rating = fields.Char(
        string='Performance Rating',
        compute='_compute_performance_rating',
        store=True,
        readonly=True,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('notified', 'Notified'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('confirmed', 'Confirmed'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False)
    rejection_reason = fields.Text(string='Rejection Reason', copy=False)

    is_current_employee = fields.Boolean(
        compute='_compute_current_user_roles',
        string='Is Current Employee',
    )
    is_current_manager = fields.Boolean(
        compute='_compute_current_user_roles',
        string='Is Current Manager',
    )
    is_planning_role = fields.Boolean(
        compute='_compute_current_user_roles',
        string='Is Planning Role',
    )
    is_hr_role = fields.Boolean(
        compute='_compute_current_user_roles',
        string='Is HR Role',
    )
    is_admin_role = fields.Boolean(
        compute='_compute_current_user_roles',
        string='Is Admin Role',
    )

    def _compute_current_user_roles(self):
        user = self.env.user
        is_planning = user.has_group('performance_management.group_performance_planning') or user.has_group('base.group_system')
        is_hr = user.has_group('performance_management.group_performance_hr') or user.has_group('base.group_system')
        is_admin = user.has_group('performance_management.group_performance_admin') or user.has_group('base.group_system')
        user_emp_ids = user.employee_ids.ids

        for rec in self:
            rec.is_planning_role = is_planning
            rec.is_hr_role = is_hr
            rec.is_admin_role = is_admin

            emp_user = rec.employee_id.user_id.id if rec.employee_id else False
            emp_id = rec.employee_id.id if rec.employee_id else False
            rec.is_current_employee = bool(
                (emp_user and emp_user == user.id) or
                (emp_id and emp_id in user_emp_ids)
            )

            mgr_user = rec.manager_id.user_id.id if rec.manager_id else False
            mgr_id = rec.manager_id.id if rec.manager_id else False
            coach_user = rec.employee_id.coach_id.user_id.id if rec.employee_id and rec.employee_id.coach_id else False
            parent_user = rec.employee_id.parent_id.user_id.id if rec.employee_id and rec.employee_id.parent_id else False
            rec.is_current_manager = bool(
                (mgr_user and mgr_user == user.id) or
                (mgr_id and mgr_id in user_emp_ids) or
                (coach_user and coach_user == user.id) or
                (parent_user and parent_user == user.id)
            )

    line_ids = fields.One2many(
        't3.appraisal.line',
        'appraisal_id',
        string='Performance Appraisal Details',
        copy=True,
    )

    @api.depends('employee_id')
    def _compute_department_id(self):
        for rec in self:
            rec.department_id = rec.employee_id.department_id if rec.employee_id else False

    @api.depends('line_ids.appraised_score', 'line_ids.appraised', 'line_ids.weight')
    def _compute_employee_score(self):
        for rec in self:
            appraised_lines = rec.line_ids.filtered(lambda l: l.appraised == 'yes')
            total_appraised_weight = sum(appraised_lines.mapped('weight'))
            total_score = sum(appraised_lines.mapped('appraised_score'))
            if total_appraised_weight > 0:
                rec.employee_score = round((total_score / total_appraised_weight) * 100.0, 2)
            else:
                rec.employee_score = 0.0

    @api.depends('employee_score')
    def _compute_performance_rating(self):
        for rec in self:
            if rec.employee_score:
                lookup_score = max(0.0, min(100.0, rec.employee_score))
                ranking = self.env['pms.ranking'].search([
                    ('score_from', '<=', lookup_score),
                    ('score_to', '>=', lookup_score),
                ], limit=1)
                if not ranking:
                    ranking = self.env['pms.ranking'].search([
                        ('score_from', '<=', lookup_score),
                    ], order='score_from desc', limit=1)
                if not ranking:
                    ranking = self.env['pms.ranking'].search([], order='score_from asc', limit=1)

                if ranking:
                    rec.performance_rating = dict(
                        ranking._fields['ranking'].selection
                    ).get(ranking.ranking, ranking.ranking)
                else:
                    rec.performance_rating = False
            else:
                rec.performance_rating = False

    def action_populate_score(self):
        for rec in self:
            if not (rec.is_current_manager or rec.is_hr_role or rec.is_admin_role or self.env.is_admin()):
                raise UserError('Employees are not permitted to populate appraisal scores.')
            period_type = detect_period_type(
                period_rec=rec.appraisal_period_id or (rec.scorecard_id.appraisal_period_id if rec.scorecard_id else False),
                start_date=rec.start_date,
                end_date=rec.end_date,
                fiscal_year=rec.fiscal_year_id,
            )

            for line in rec.line_ids:
                # Sync target from parent scorecard line
                scorecard = rec.scorecard_id
                if not scorecard and rec.employee_id:
                    scorecard = self.env['t3.scorecard'].search([
                        ('employee_id', '=', rec.employee_id.id),
                        ('fiscal_year_id', '=', rec.fiscal_year_id.id),
                    ], limit=1)

                if scorecard and line.job_measure_id:
                    sc_line = scorecard.line_ids.filtered(
                        lambda sl: sl.job_measure_id == line.job_measure_id
                    )[:1]
                    if sc_line:
                        line.target = get_target_for_period(sc_line, period_type)

                if line.appraised == 'no':
                    line.weight = 0.0
                    line.accomplishment_percent = 0.0
                    line.appraised_score = 0.0
                    line.maximum_score = 0.0
                    line.appraisal_rating = False
                else:
                    if not line.planned_weight and line.weight:
                        line.planned_weight = line.weight
                    line.weight = line.planned_weight or line.weight or 0.0
                    target = line.target or 0.0
                    uploaded = line.uploaded_value or 0.0
                    weight = line.weight or 0.0
                    line.maximum_score = weight
                    app_type = (line.appraisal_type or 'number').lower()
                    accomplished = 0.0

                    if app_type in ('number', 'percent'):
                        if target < 0 and uploaded < 0:
                            accomplished = round(((abs(target) - abs(uploaded)) / abs(target) * 100.0 + 100.0), 2)
                        elif target < 0:
                            accomplished = round(((abs(target) + uploaded) / abs(target) * 100.0), 2)
                        elif target != 0:
                            accomplished = round(((uploaded / target) * 100.0), 2)
                        else:
                            accomplished = 0.0
                    elif app_type in ('expense', 'hours', 'days'):
                        if uploaded != 0:
                            accomplished = round(((target / uploaded) * 100.0), 2)
                        else:
                            accomplished = 0.0
                    else:
                        if target != 0:
                            accomplished = round(((uploaded / target) * 100.0), 2)
                        else:
                            accomplished = 0.0

                    score = round((accomplished / 100.0) * weight, 2)
                    if score < 0:
                        score = 0.0
                    if line.maximum_score > 0 and score > line.maximum_score:
                        score = line.maximum_score

                    line.accomplishment_percent = accomplished
                    line.appraised_score = score

                    lookup_score = max(0.0, min(100.0, accomplished))
                    ranking = self.env['pms.ranking'].search([
                        ('score_from', '<=', lookup_score),
                        ('score_to', '>=', lookup_score),
                    ], limit=1)
                    if not ranking:
                        ranking = self.env['pms.ranking'].search([
                            ('score_from', '<=', lookup_score),
                        ], order='score_from desc', limit=1)
                    if not ranking:
                        ranking = self.env['pms.ranking'].search([], order='score_from asc', limit=1)

                    if ranking:
                        line.appraisal_rating = dict(ranking._fields['ranking'].selection).get(ranking.ranking, ranking.ranking)
                    else:
                        line.appraisal_rating = False

            rec._compute_employee_score()
            rec._compute_performance_rating()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Scores Populated',
                'message': 'Appraisal scores and ratings have been successfully calculated.',
                'type': 'success',
                'sticky': False,
            }
        }

    def action_notify(self):
        for rec in self:
            if not (rec.is_current_manager or rec.is_hr_role or rec.is_admin_role or self.env.is_admin()):
                raise UserError('Only the Manager or HR administrator can notify the employee.')
            rec.write({'state': 'notified'})
            rec.message_post(body='Tier 3 Appraisal has been notified to the employee for review.')

    def action_accept(self):
        for rec in self:
            if not (rec.is_current_employee or self.env.is_admin()):
                raise UserError('Only the assigned employee can accept this Tier 3 Appraisal.')
            rec.write({'state': 'accepted'})
            rec.message_post(body='Tier 3 Appraisal has been accepted by the employee.')

    def action_reject(self):
        for rec in self:
            if not (rec.is_current_employee or self.env.is_admin()):
                raise UserError('Only the assigned employee can reject this Tier 3 Appraisal.')
        return {
            'name': 'Reject Appraisal',
            'type': 'ir.actions.act_window',
            'res_model': 'performance.rejection.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': self._name,
                'default_res_id': self.id,
            },
        }

    def action_confirm(self):
        for rec in self:
            if not (rec.is_current_manager or rec.is_hr_role or rec.is_admin_role or self.env.is_admin()):
                raise UserError('Only the Manager or HR administrator can confirm this Tier 3 Appraisal.')
            rec.write({'state': 'confirmed'})
            rec.message_post(body='Tier 3 Appraisal has been confirmed by the manager.')

    def action_reset_draft(self):
        for rec in self:
            if rec.is_current_employee and not (rec.is_current_manager or rec.is_hr_role or rec.is_admin_role or self.env.is_admin()):
                raise UserError('Employees are not permitted to reset appraisals to draft.')
            if rec.state == 'confirmed':
                if not (rec.is_hr_role or rec.is_admin_role or self.env.is_admin()):
                    raise UserError('Once confirmed by the manager, only the HR administrator can reset this Tier 3 Appraisal to draft.')
            elif not (rec.is_current_manager or rec.is_hr_role or rec.is_admin_role or self.env.is_admin()):
                raise UserError('Only the Manager or HR administrator can reset this Tier 3 Appraisal to draft.')
            rec.write({'state': 'draft'})
            rec.message_post(body='Tier 3 Appraisal has been reset to draft.')

    def write(self, vals):
        for rec in self:
            if rec.is_current_employee and not (rec.is_current_manager or rec.is_hr_role or rec.is_admin_role or self.env.is_admin()):
                allowed_fields = {'state', 'rejection_reason'}
                if not set(vals.keys()).issubset(allowed_fields):
                    raise UserError('Employees are not permitted to edit appraisals.')
            if rec.state in ('accepted', 'confirmed'):
                allowed_fields = {'state', 'rejection_reason'}
                if rec.is_hr_role or rec.is_admin_role or self.env.is_admin():
                    allowed_fields |= {'manager_id', 'employee_id', 'job_id', 'operating_unit_id', 'department_id', 'fiscal_year_id', 'appraisal_period_id'}
                if not set(vals.keys()).issubset(allowed_fields):
                    raise UserError(
                        'This Tier 3 Appraisal is %s and can no longer be edited.'
                        % dict(rec._fields['state'].selection).get(rec.state, rec.state)
                    )
        return super().write(vals)


class T3AppraisalLine(models.Model):
    _name = 't3.appraisal.line'
    _description = 'Tier 3 Performance Appraisal Detail'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    appraisal_id = fields.Many2one(
        't3.appraisal',
        string='Tier 3 Appraisal',
        required=True,
        ondelete='cascade',
    )
    state = fields.Selection(
        related='appraisal_id.state',
        string='Status',
        readonly=True,
        store=True,
    )
    perspective_id = fields.Many2one(
        'performance.perspective',
        string='Perspective',
        readonly=True,
    )
    perspective_name = fields.Char(
        related='perspective_id.name',
        store=True,
        readonly=True,
    )
    parent_objective_id = fields.Many2one(
        'performance.objective',
        string='Objective',
        readonly=True,
    )
    job_objective_id = fields.Many2one(
        'performance.job.objective',
        string='Key Performance Indicator',
        readonly=True,
    )
    job_measure_id = fields.Many2one(
        'performance.job.measure',
        string='Measurements',
        readonly=True,
    )
    planned_weight = fields.Float(
        string='Planned Weight (%)',
        readonly=True,
    )
    weight = fields.Float(
        string='Weight (%)',
        compute='_compute_weight',
        store=True,
        readonly=False,
    )

    @api.depends('planned_weight', 'appraised', 'appraisal_id.scorecard_id', 'job_measure_id')
    def _compute_weight(self):
        for line in self:
            if not line.planned_weight:
                scorecard = line.appraisal_id.scorecard_id if line.appraisal_id else False
                if not scorecard and line.appraisal_id and line.appraisal_id.employee_id:
                    scorecard = self.env['t3.scorecard'].search([
                        ('employee_id', '=', line.appraisal_id.employee_id.id),
                        ('fiscal_year_id', '=', line.appraisal_id.fiscal_year_id.id),
                    ], limit=1)
                if scorecard and line.job_measure_id:
                    sc_line = scorecard.line_ids.filtered(lambda sl: sl.job_measure_id == line.job_measure_id)[:1]
                    if sc_line:
                        line.planned_weight = sc_line.weight
                if not line.planned_weight and line.weight:
                    line.planned_weight = line.weight

            if line.appraised == 'yes':
                line.weight = line.planned_weight or 0.0
            else:
                line.weight = 0.0

    target = fields.Float(
        string='Target',
        compute='_compute_target',
        store=True,
        readonly=False,
    )

    @api.depends('appraisal_id.scorecard_id', 'appraisal_id.appraisal_period_id', 'appraisal_id.start_date', 'appraisal_id.end_date', 'job_measure_id')
    def _compute_target(self):
        for line in self:
            appraisal = line.appraisal_id
            scorecard = appraisal.scorecard_id if appraisal else False
            if not scorecard and appraisal and appraisal.employee_id:
                scorecard = self.env['t3.scorecard'].search([
                    ('employee_id', '=', appraisal.employee_id.id),
                    ('fiscal_year_id', '=', appraisal.fiscal_year_id.id),
                ], limit=1)

            if scorecard and line.job_measure_id:
                sc_line = scorecard.line_ids.filtered(lambda sl: sl.job_measure_id == line.job_measure_id)[:1]
                if sc_line:
                    period_type = detect_period_type(
                        period_rec=appraisal.appraisal_period_id or scorecard.appraisal_period_id,
                        start_date=appraisal.start_date if appraisal else False,
                        end_date=appraisal.end_date if appraisal else False,
                        fiscal_year=appraisal.fiscal_year_id if appraisal else False,
                    )
                    line.target = get_target_for_period(sc_line, period_type)
                else:
                    line.target = line.target or 0.0
            else:
                line.target = line.target or 0.0

    appraisal_type = fields.Selection(
        related='job_measure_id.target_type',
        store=True,
        readonly=True,
        string='Appraisal Type',
    )
    appraisal_criteria = fields.Char(string='Appraisal Criteria')
    uploaded_value = fields.Float(string='Uploaded Value')
    accomplishment_percent = fields.Float(
        string='% Accomplished',
        compute='_compute_scores',
        store=True,
        readonly=False,
    )
    appraised = fields.Selection([
        ('yes', 'Yes'),
        ('no', 'No'),
    ], string='Appraised', default='yes', required=True)

    appraised_score = fields.Float(
        string='Appraised Score',
        compute='_compute_scores',
        store=True,
        readonly=False,
    )
    appraisal_rating = fields.Char(
        string='Appraisal Rating',
        compute='_compute_scores',
        store=True,
        readonly=True,
    )
    maximum_score = fields.Float(
        string='Maximum Score',
        compute='_compute_scores',
        store=True,
        readonly=True,
    )
    recommendations = fields.Text(string='Recommendations')
    comments = fields.Text(string='Comments')

    @api.depends('uploaded_value', 'target', 'weight', 'planned_weight', 'appraised', 'appraisal_type')
    def _compute_scores(self):
        for line in self:
            if line.appraised == 'yes':
                target = line.target or 0.0
                uploaded = line.uploaded_value or 0.0
                weight = line.weight or line.planned_weight or 0.0
                line.maximum_score = weight
                app_type = (line.appraisal_type or 'number').lower()
                accomplished = 0.0

                if app_type in ('number', 'percent'):
                    if target < 0 and uploaded < 0:
                        accomplished = round(((abs(target) - abs(uploaded)) / abs(target) * 100.0 + 100.0), 2)
                    elif target < 0:
                        accomplished = round(((abs(target) + uploaded) / abs(target) * 100.0), 2)
                    elif target != 0:
                        accomplished = round(((uploaded / target) * 100.0), 2)
                    else:
                        accomplished = 0.0
                elif app_type in ('expense', 'hours', 'days'):
                    if uploaded != 0:
                        accomplished = round(((target / uploaded) * 100.0), 2)
                    else:
                        accomplished = 0.0
                else:
                    if target != 0:
                        accomplished = round(((uploaded / target) * 100.0), 2)
                    else:
                        accomplished = 0.0

                score = round((accomplished / 100.0) * weight, 2)
                if score < 0:
                    score = 0.0
                if line.maximum_score > 0 and score > line.maximum_score:
                    score = line.maximum_score

                line.accomplishment_percent = accomplished
                line.appraised_score = score

                lookup_score = max(0.0, min(100.0, accomplished))
                ranking = self.env['pms.ranking'].search([
                    ('score_from', '<=', lookup_score),
                    ('score_to', '>=', lookup_score),
                ], limit=1)
                if not ranking:
                    ranking = self.env['pms.ranking'].search([
                        ('score_from', '<=', lookup_score),
                    ], order='score_from desc', limit=1)
                if not ranking:
                    ranking = self.env['pms.ranking'].search([], order='score_from asc', limit=1)

                if ranking:
                    line.appraisal_rating = dict(ranking._fields['ranking'].selection).get(ranking.ranking, ranking.ranking)
                else:
                    line.appraisal_rating = False
            else:
                line.accomplishment_percent = 0.0
                line.appraised_score = 0.0
                line.maximum_score = 0.0
                line.appraisal_rating = False

    def write(self, vals):
        for rec in self:
            app = rec.appraisal_id
            if app:
                if app.is_current_employee and not (app.is_current_manager or app.is_hr_role or app.is_admin_role or self.env.is_admin()):
                    raise UserError('Employees are not permitted to edit appraisal lines.')
                if 'uploaded_value' in vals and app.state != 'draft':
                    raise UserError('Uploaded Value can only be edited when the Appraisal is in Draft state.')
        return super().write(vals)
