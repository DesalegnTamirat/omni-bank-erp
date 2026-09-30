# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError
from .t2_appraisal import detect_period_type


class T3Scorecard(models.Model):
    _name = "t3.scorecard"
    _description = "Tier 3 Scorecard"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = "employee_id"
    _order = "employee_id"

    employee_id = fields.Many2one("hr.employee", string="Employee", readonly=True, default=lambda self: self.env.user.employee_id)
    manager_id = fields.Many2one("hr.employee", string="Manager")

    planning_name = fields.Char(readonly=True)
    name = fields.Char(
        string='Scorecard Name',
        related='planning_name',
        readonly=True,
    )
    fiscal_year_id = fields.Many2one(
        'performance.fiscal.year',
        string='Fiscal Year',
        compute='_compute_fiscal_year_id',
        store=True,
        readonly=False,
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
        'appraisal.period', string='Appraisal Period', readonly=False,
    )
    appraisal_period_name = fields.Char(
        related='appraisal_period_id.name', store=True, readonly=True,
    )
    appraisal_period_code = fields.Selection(
        selection=[
            ('Q1', 'Q1'),
            ('Q2', 'Q2'),
            ('H1', 'H1'),
            ('Q3', 'Q3'),
            ('Q4', 'Q4'),
            ('H2', 'H2'),
            ('ANNUAL', 'Annual'),
        ],
        string='Period Code',
        compute='_compute_appraisal_period_code',
        store=True,
        readonly=True,
    )

    company_id = fields.Many2one("res.company", readonly=True)
    operating_unit_id = fields.Many2one("operating.unit", readonly=True)

    department_id = fields.Many2one(
        "hr.department",
        compute='_compute_department_id',
        string="Department",
    )

    def _compute_department_id(self):
        for rec in self:
            rec.department_id = rec.employee_id.department_id if rec.employee_id else False

    job_id = fields.Many2one("hr.job", string="Job Position", readonly=True)

    start_date = fields.Date(readonly=True)
    end_date = fields.Date(readonly=True)

    accepted_by = fields.Many2one("hr.employee", string="Accepted By")

    employee_image_128 = fields.Image(
        string='Employee Photo',
        related='employee_id.image_128',
        max_width=128,
        max_height=128,
        store=True,
    )

    line_ids = fields.One2many(
        "t3.scorecard.line",
        "scorecard_id",
        string="Score Card Plan Details",
    )

    total_weight = fields.Float(
        compute="_compute_total_weight",
        store=True,
    )

    state = fields.Selection([
        ("draft", "Draft"),
        ("notified", "Notified"),
        ("accepted", "Accepted"),
        ("rejected", "Rejected"),
        ("confirmed", "Confirmed"),
        ("appraisal_started", "Appraisal Started"),
    ], default="draft", tracking=True)
    rejection_reason = fields.Text(string="Rejection Reason", copy=False)

    @api.depends('appraisal_period_id', 'start_date', 'end_date', 'planning_name')
    def _compute_fiscal_year_id(self):
        for rec in self:
            if not rec.fiscal_year_id:
                start = rec.start_date
                end = rec.end_date
                period = rec.appraisal_period_id

                fyl = False
                if period and start:
                    fyl = self.env['fiscal.year.line'].search([
                        ('appraisal_period', '=', period.id),
                        ('date_start', '<=', start),
                        ('date_end', '>=', end or start),
                    ], limit=1)
                    if not fyl:
                        fyl = self.env['fiscal.year.line'].search([
                            ('appraisal_period', '=', period.id),
                            ('date_start', '=', start),
                        ], limit=1)
                if not fyl and period:
                    fyl = self.env['fiscal.year.line'].search([
                        ('appraisal_period', '=', period.id),
                    ], limit=1)
                if not fyl and start:
                    fy = self.env['performance.fiscal.year'].search([
                        ('date_start', '<=', start),
                        ('date_end', '>=', end or start),
                    ], limit=1)
                    if fy:
                        rec.fiscal_year_id = fy.id
                        continue
                if not fyl and rec.planning_name:
                    for fy in self.env['performance.fiscal.year'].search([], limit=10):
                        if fy.name and fy.name in rec.planning_name:
                            rec.fiscal_year_id = fy.id
                            break
                if fyl:
                    rec.fiscal_year_id = fyl.year_id.id

    @api.depends('appraisal_period_id', 'appraisal_period_id.code', 'appraisal_period_id.name', 'start_date', 'end_date', 'fiscal_year_id')
    def _compute_appraisal_period_code(self):
        for rec in self:
            code = rec.appraisal_period_id.code if rec.appraisal_period_id and rec.appraisal_period_id.code else False
            if not code:
                code = detect_period_type(
                    period_rec=rec.appraisal_period_id,
                    start_date=rec.start_date,
                    end_date=rec.end_date,
                    fiscal_year=rec.fiscal_year_id,
                )
            rec.appraisal_period_code = code if code in ('Q1', 'Q2', 'H1', 'Q3', 'Q4', 'H2', 'ANNUAL') else 'H1'

    @api.onchange('fiscal_year_id', 'appraisal_period_id')
    def _onchange_fiscal_year_period(self):
        if self.fiscal_year_id and self.appraisal_period_id:
            line = self.fiscal_year_id.line_ids.filtered(
                lambda l: l.appraisal_period == self.appraisal_period_id
            )[:1]
            if line:
                self.start_date = line.date_start
                self.end_date = line.date_end

    @api.depends("line_ids.weight")
    def _compute_total_weight(self):
        for rec in self:
            rec.total_weight = sum(rec.line_ids.mapped("weight"))

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

    def action_notify(self):
        for rec in self:
            if not (rec.is_current_manager or rec.is_hr_role or rec.is_admin_role or self.env.is_admin()):
                raise UserError('Only the Manager or HR administrator can notify the employee.')
            rec.write({'state': 'notified'})
            rec.message_post(body='Tier 3 Scorecard has been notified to the employee for review.')

    def action_accept(self):
        for rec in self:
            if not (rec.is_current_employee or self.env.is_admin()):
                raise UserError('Only the assigned employee can accept this Tier 3 Scorecard.')
            rec.write({
                'state': 'accepted',
                'accepted_by': self.env.user.employee_id.id or rec.employee_id.id,
            })
            rec.message_post(body='Tier 3 Scorecard has been accepted by the employee.')

    def action_reject(self):
        for rec in self:
            if not (rec.is_current_employee or self.env.is_admin()):
                raise UserError('Only the assigned employee can reject this Tier 3 Scorecard.')
        return {
            'name': 'Reject Scorecard',
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
                raise UserError('Only the Manager or HR administrator can confirm this Tier 3 Scorecard.')
            rec.write({'state': 'confirmed'})
            rec.message_post(body='Tier 3 Scorecard has been confirmed by the manager.')

    def action_reset_draft(self):
        for rec in self:
            if rec.is_current_employee and not (rec.is_current_manager or rec.is_hr_role or rec.is_admin_role or self.env.is_admin()):
                raise UserError('Employees are not permitted to reset scorecards to draft.')
            if rec.state == 'confirmed':
                if not (rec.is_hr_role or rec.is_admin_role or self.env.is_admin()):
                    raise UserError('Once confirmed by the manager, only the HR administrator can reset this Tier 3 Scorecard to draft.')
            elif not (rec.is_current_manager or rec.is_hr_role or rec.is_admin_role or self.env.is_admin()):
                raise UserError('Only the Manager or HR administrator can reset this Tier 3 Scorecard to draft.')
            rec.write({'state': 'draft'})
            rec.message_post(body='Tier 3 Scorecard has been reset to draft.')

    def write(self, vals):
        for rec in self:
            if rec.is_current_employee and not (rec.is_current_manager or rec.is_hr_role or rec.is_admin_role or self.env.is_admin()):
                allowed_fields = {'state', 'accepted_by', 'rejection_reason'}
                if not set(vals.keys()).issubset(allowed_fields):
                    raise UserError('Employees are not permitted to edit scorecards.')
            if rec.state in ('accepted', 'confirmed', 'appraisal_started'):
                allowed_fields = {'state', 'accepted_by', 'rejection_reason'}
                if rec.is_hr_role or rec.is_admin_role or self.env.is_admin():
                    allowed_fields |= {'manager_id', 'employee_id', 'job_id', 'operating_unit_id', 'fiscal_year_id', 'appraisal_period_id'}
                if not set(vals.keys()).issubset(allowed_fields):
                    raise UserError(
                        'This Tier 3 Scorecard is %s and can no longer be edited.'
                        % dict(rec._fields['state'].selection).get(rec.state, rec.state)
                    )
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.state in ('accepted', 'confirmed', 'appraisal_started'):
                raise UserError(
                    'This Tier 3 Scorecard is %s and cannot be deleted.'
                    % dict(rec._fields['state'].selection).get(rec.state, rec.state)
                )
        return super().unlink()

    def action_populate_lines(self):
        for rec in self:
            if not (rec.is_current_manager or rec.is_hr_role or rec.is_admin_role or self.env.is_admin()):
                raise UserError('Employees are not permitted to populate scorecard lines.')
        """ For each Tier3 Scorecard in self, find every Job Measurement
            configured for this scorecard's Operating Unit + Job Position
            combination, and create one line per Measurement. """
        JobMeasure = self.env['performance.job.measure']
        Line = self.env['t3.scorecard.line']

        vals_list = []
        for scorecard in self:
            measures = JobMeasure.search([
                ('operating_unit_id', '=', scorecard.operating_unit_id.id),
                ('job_id', '=', scorecard.job_id.id),
            ])
            existing_measure_ids = set(scorecard.line_ids.mapped('job_measure_id').ids)

            for measure in measures:
                if measure.id in existing_measure_ids:
                    continue
                vals_list.append({
                    'scorecard_id': scorecard.id,
                    'job_measure_id': measure.id,
                })

        if not vals_list:
            return Line.browse()

        new_lines = Line.create(vals_list)
        self._compute_total_weight()
        return new_lines


class T3ScorecardLine(models.Model):
    _name = "t3.scorecard.line"
    _description = "Tier 3 Scorecard Line"

    scorecard_id = fields.Many2one(
        "t3.scorecard",
        required=True,
        ondelete="cascade",
    )
    state = fields.Selection(
        related='scorecard_id.state',
        string='Status',
        readonly=True,
        store=True,
    )
    scorecard_operating_unit_id = fields.Many2one(
        related='scorecard_id.operating_unit_id', store=True, readonly=True,
    )
    scorecard_job_id = fields.Many2one(
        related='scorecard_id.job_id', store=True, readonly=True,
    )
    period_name = fields.Char(
        related='scorecard_id.planning_name',
        store=True,
        readonly=True,
    )
    period_code = fields.Selection(
        selection=[
            ('Q1', 'Q1'),
            ('Q2', 'Q2'),
            ('H1', 'H1'),
            ('Q3', 'Q3'),
            ('Q4', 'Q4'),
            ('H2', 'H2'),
            ('ANNUAL', 'Annual'),
        ],
        string='Period Code',
        compute='_compute_period_code',
        store=True,
        readonly=True,
    )

    @api.depends('scorecard_id.appraisal_period_id', 'scorecard_id.appraisal_period_id.code', 'scorecard_id.appraisal_period_id.name', 'scorecard_id.planning_name', 'scorecard_id.start_date', 'scorecard_id.end_date', 'scorecard_id.fiscal_year_id')
    def _compute_period_code(self):
        for line in self:
            sc = line.scorecard_id
            period = sc.appraisal_period_id
            code = period.code if period and period.code else False
            if not code:
                code = detect_period_type(
                    period_rec=period,
                    start_date=sc.start_date,
                    end_date=sc.end_date,
                    fiscal_year=sc.fiscal_year_id,
                )
            line.period_code = code if code in ('Q1', 'Q2', 'H1', 'Q3', 'Q4', 'H2', 'ANNUAL') else 'H1'

    job_measure_id = fields.Many2one(
        'performance.job.measure',
        string='Measurement',
        required=True,
        domain="[('operating_unit_id', '=', scorecard_operating_unit_id), "
               "('job_id', '=', scorecard_job_id)]",
    )
    job_objective_id = fields.Many2one(
        related='job_measure_id.job_objective_id', store=True, readonly=True,
        string='Key Performance Indicator',
    )
    parent_objective_id = fields.Many2one(
        related='job_measure_id.parent_objective_id', store=True, readonly=True,
        string='Objective',
    )
    perspective_id = fields.Many2one(
        related='job_measure_id.perspective_id', store=True, readonly=True,
    )
    perspective_name = fields.Char(
        related='perspective_id.name',
        store=True,
        readonly=True,
    )
    weight = fields.Float(
        related='job_measure_id.weight', store=True, readonly=True, string='Weight (%)',
    )
    target_type = fields.Selection(
        related='job_measure_id.target_type', store=True, readonly=True,
    )

    baseline = fields.Float(string='Baseline')
    q1_target = fields.Float(string='Q1 Target')
    h1_target = fields.Float(string='H1 Target')
    q3_target = fields.Float(string='Q3 Target')
    h2_target = fields.Float(string='H2 Target')
    annual_target = fields.Float(
        string='Annual Target', compute='_compute_annual_target', store=True, readonly=False,
    )
    target_description = fields.Text(string='Target Description')

    @api.depends('q1_target', 'h1_target', 'q3_target', 'h2_target')
    def _compute_annual_target(self):
        for line in self:
            line.annual_target = (
                (line.q1_target or 0.0) + (line.h1_target or 0.0)
                + (line.q3_target or 0.0) + (line.h2_target or 0.0)
            )

    def write(self, vals):
        for rec in self:
            sc = rec.scorecard_id
            if sc:
                if sc.is_current_employee and not (sc.is_current_manager or sc.is_hr_role or sc.is_admin_role or self.env.is_admin()):
                    raise UserError('Employees are not permitted to edit scorecard lines.')
                if sc.state != 'draft':
                    raise UserError('Scorecard lines and targets can only be edited when the Scorecard is in Draft state.')
        return super().write(vals)

    def unlink(self):
        for rec in self:
            sc = rec.scorecard_id
            if sc:
                if sc.is_current_employee and not (sc.is_current_manager or sc.is_hr_role or sc.is_admin_role or self.env.is_admin()):
                    raise UserError('Employees are not permitted to delete scorecard lines.')
                if sc.state != 'draft':
                    raise UserError('Scorecard lines can only be deleted when the Scorecard is in Draft state.')
        return super().unlink()