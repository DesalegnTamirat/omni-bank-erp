# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from .t2_appraisal import detect_period_type


class CorporateScorecard(models.Model):
    _name = 'corporate.scorecard'
    _description = 'Corporate Score Card'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, name'

    name = fields.Char(
        string='Planning Name',
        required=True,
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
        'appraisal.period',
        string='Appraisal Period',
        required=True,
        readonly=False,
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
    employee_image_128 = fields.Image(
        string='Employee Photo',
        related='employee_id.image_128',
        max_width=128,
        max_height=128,
        store=True,
    )
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    manager_id = fields.Many2one('hr.employee', string='Manager', readonly=True)
    job_id = fields.Many2one('hr.job', string='Job Position', related='employee_id.job_id', store=True, readonly=True)
    operating_unit_id = fields.Many2one('operating.unit', string='Operating Unit', readonly=True)
    department_id = fields.Many2one('hr.department', string='Department', related='employee_id.department_id', store=True, readonly=True)
    accepted_by = fields.Many2one('hr.employee', string='Accepted By')

    date_start = fields.Date(
        string='Planning Period Start Date',
        required=True,
        readonly=True,
    )
    date_end = fields.Date(
        string='Planning Period End Date',
        required=True,
        readonly=True,
    )
    start_date = fields.Date(
        string='Start Date',
        related='date_start',
        readonly=True,
    )
    end_date = fields.Date(
        string='End Date',
        related='date_end',
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company Name',
        default=lambda self: self.env.company,
        readonly=True,
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('notified', 'Notified'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('confirmed', 'Confirmed'),
        ('appraisal_started', 'Appraisal Started'),
        ('completed', 'Completed'),
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

            rec.is_current_manager = False

    line_ids = fields.One2many(
        'corporate.scorecard.line',
        'scorecard_id',
        string='Corporate Score Card Plan Details',
        copy=True,
    )
    total_weight = fields.Float(
        string='Total Weight (%)',
        compute='_compute_total_weight',
    )

    @api.depends('appraisal_period_id', 'date_start', 'date_end', 'name')
    def _compute_fiscal_year_id(self):
        for rec in self:
            if not rec.fiscal_year_id:
                start = rec.date_start
                end = rec.date_end
                period = rec.appraisal_period_id

                fyl = False
                if period and start:
                    fyl = self.env['performance.fiscal.year.line'].search([
                        ('appraisal_period', '=', period.id),
                        ('date_start', '<=', start),
                        ('date_end', '>=', end or start),
                    ], limit=1)
                    if not fyl:
                        fyl = self.env['performance.fiscal.year.line'].search([
                            ('appraisal_period', '=', period.id),
                            ('date_start', '=', start),
                        ], limit=1)
                if not fyl and period:
                    fyl = self.env['performance.fiscal.year.line'].search([
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
                if not fyl and rec.name:
                    for fy in self.env['performance.fiscal.year'].search([], limit=10):
                        if fy.name and fy.name in rec.name:
                            rec.fiscal_year_id = fy.id
                            break
                if fyl:
                    rec.fiscal_year_id = fyl.fiscal_year_id.id

    @api.depends('appraisal_period_id', 'appraisal_period_id.code', 'appraisal_period_id.name', 'date_start', 'date_end', 'fiscal_year_id')
    def _compute_appraisal_period_code(self):
        for rec in self:
            code = rec.appraisal_period_id.code if rec.appraisal_period_id and rec.appraisal_period_id.code else False
            if not code:
                code = detect_period_type(
                    period_rec=rec.appraisal_period_id,
                    start_date=rec.date_start,
                    end_date=rec.date_end,
                    fiscal_year=rec.fiscal_year_id,
                )
            rec.appraisal_period_code = code if code in ('Q1', 'Q2', 'H1', 'Q3', 'Q4', 'H2', 'ANNUAL') else 'H1'

    @api.depends('line_ids.weight')
    def _compute_total_weight(self):
        for rec in self:
            rec.total_weight = sum(rec.line_ids.mapped('weight'))

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_start > rec.date_end:
                raise ValidationError(
                    'Planning Period Start Date must be before the Planning Period End Date.'
                )

    @api.onchange('fiscal_year_id')
    def _onchange_fiscal_year_id(self):
        if self.fiscal_year_id:
            lines = self.fiscal_year_id.line_ids.sorted('date_start')
            if lines and not self.appraisal_period_id:
                self.appraisal_period_id = lines[0].appraisal_period
                self.date_start = lines[0].date_start
                self.date_end = lines[0].date_end
            return {
                'domain': {
                    'appraisal_period_id': [
                        ('id', 'in', lines.mapped('appraisal_period').ids)
                    ]
                }
            }

    @api.onchange('appraisal_period_id')
    def _onchange_appraisal_period_id(self):
        self.date_start = False
        self.date_end = False

        if self.fiscal_year_id and self.appraisal_period_id:
            line = self.fiscal_year_id.line_ids.filtered(
                lambda l: l.appraisal_period == self.appraisal_period_id
            )[:1]

            if line:
                self.date_start = line.date_start
                self.date_end = line.date_end

    def action_notify(self):
        for rec in self:
            if not (rec.is_planning_role or rec.is_admin_role or self.env.is_admin()):
                raise UserError('Only the Planning administrator can notify the employee.')
            rec.write({'state': 'notified'})
            rec.message_post(body='Corporate Scorecard has been notified to the employee for review.')

    def action_accept(self):
        for rec in self:
            if not (rec.is_current_employee or self.env.is_admin()):
                raise UserError('Only the assigned employee can accept this Corporate Scorecard.')
            rec.write({
                'state': 'accepted',
                'accepted_by': self.env.user.employee_id.id or rec.employee_id.id,
            })
            rec.message_post(body='Corporate Scorecard has been accepted by the employee.')

    def action_reject(self):
        for rec in self:
            if not (rec.is_current_employee or self.env.is_admin()):
                raise UserError('Only the assigned employee can reject this Corporate Scorecard.')
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
            if not (rec.is_planning_role or rec.is_admin_role or self.env.is_admin()):
                raise UserError('Only the Planning administrator can confirm this Corporate Scorecard.')
            rec.write({'state': 'confirmed'})
            rec.message_post(body='Corporate Scorecard has been confirmed.')

    def action_complete(self):
        self.write({'state': 'completed'})

    def action_start_appraisal(self):
        self.write({'state': 'appraisal_started'})

    def action_reset_draft(self):
        for rec in self:
            if rec.is_current_employee and not (rec.is_planning_role or rec.is_admin_role or self.env.is_admin()):
                raise UserError('Employees are not permitted to reset scorecards to draft.')
            if not (rec.is_planning_role or rec.is_admin_role or self.env.is_admin()):
                raise UserError('Only the Planning administrator can reset this Corporate Scorecard to draft.')
            rec.write({'state': 'draft'})
            rec.message_post(body='Corporate Scorecard has been reset to draft.')

    def write(self, vals):
        for rec in self:
            if rec.is_current_employee and not (rec.is_planning_role or rec.is_admin_role or self.env.is_admin()):
                allowed_fields = {'state', 'accepted_by', 'rejection_reason'}
                if not set(vals.keys()).issubset(allowed_fields):
                    raise UserError('Employees are not permitted to edit scorecards.')
            if rec.state in ('accepted', 'confirmed', 'appraisal_started', 'completed'):
                allowed_fields = {'state', 'accepted_by', 'rejection_reason'}
                if rec.is_planning_role or rec.is_admin_role or self.env.is_admin():
                    allowed_fields |= {'employee_id', 'manager_id', 'job_id', 'operating_unit_id', 'department_id', 'fiscal_year_id', 'appraisal_period_id', 'date_start', 'date_end'}
                if not set(vals.keys()).issubset(allowed_fields):
                    raise UserError(
                        'This Corporate Scorecard is %s and can no longer be edited.'
                        % dict(rec._fields['state'].selection).get(rec.state, rec.state)
                    )
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.state in ('appraisal_started', 'completed'):
                raise UserError(
                    'This Corporate Scorecard is %s and cannot be deleted.'
                    % dict(rec._fields['state'].selection).get(rec.state, rec.state)
                )
        return super().unlink()

    def action_populate_lines(self):
        self.ensure_one()
        if not (self.is_planning_role or self.is_admin_role or self.env.is_admin()):
            raise UserError('Only the Planning administrator can populate scorecard lines.')
        Measure = self.env['performance.measure']
        Line = self.env['corporate.scorecard.line']

        root_measures = Measure.search([('objective_id.parent_objective_id', '=', False)])

        vals_list = [
            {'scorecard_id': self.id, 'measure_id': measure.id}
            for measure in root_measures
        ]

        if not vals_list:
            return Line.browse()

        new_lines = Line.create(vals_list)
        self._compute_total_weight()
        return new_lines


class CorporateScorecardLine(models.Model):
    _name = 'corporate.scorecard.line'
    _description = 'Corporate Score Card Plan Detail'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    scorecard_id = fields.Many2one(
        'corporate.scorecard',
        string='Corporate Score Card',
        required=True,
        ondelete='cascade',
    )
    state = fields.Selection(
        related='scorecard_id.state',
        string='Status',
        readonly=True,
        store=True,
    )
    period_name = fields.Char(
        related='scorecard_id.appraisal_period_id.name',
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

    @api.depends('scorecard_id.appraisal_period_id', 'scorecard_id.appraisal_period_id.code', 'scorecard_id.appraisal_period_id.name', 'scorecard_id.name', 'scorecard_id.date_start', 'scorecard_id.date_end', 'scorecard_id.fiscal_year_id')
    def _compute_period_code(self):
        for line in self:
            sc = line.scorecard_id
            period = sc.appraisal_period_id
            code = period.code if period and period.code else False
            if not code:
                code = detect_period_type(
                    period_rec=period,
                    start_date=sc.date_start,
                    end_date=sc.date_end,
                    fiscal_year=sc.fiscal_year_id,
                )
            line.period_code = code if code in ('Q1', 'Q2', 'H1', 'Q3', 'Q4', 'H2', 'ANNUAL') else 'H1'

    measure_id = fields.Many2one(
        'performance.measure',
        string='Performance Measure',
        required=True,
        domain="[('objective_id.parent_objective_id', '=', False)]",
    )
    objective_id = fields.Many2one(
        related='measure_id.objective_id',
        store=True, readonly=True,
        string='Strategic Objective',
    )
    perspective_id = fields.Many2one(
        related='measure_id.objective_id.perspective_id',
        store=True, readonly=True,
        string='Perspective',
    )
    perspective_name = fields.Char(
        related='perspective_id.name',
        store=True,
        readonly=True,
    )
    weight = fields.Float(
        related='measure_id.weight', store=True, readonly=True, string='Weight (%)',
    )
    target_type = fields.Selection(
        related='measure_id.target_type', store=True, readonly=True,
    )

    baseline = fields.Float(string='Baseline')
    q1_target = fields.Float(string='Q1 Target')
    h1_target = fields.Float(string='H1 Target')
    q3_target = fields.Float(string='Q3 Target')
    h2_target = fields.Float(string='H2 Target')
    annual_target = fields.Float(
        string='Annual Target', compute='_compute_annual_target', store=True, readonly=True,
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
                if sc.is_current_employee and not (sc.is_planning_role or sc.is_admin_role or self.env.is_admin()):
                    raise UserError('Employees are not permitted to edit scorecard lines.')
                if sc.state != 'draft':
                    raise UserError('Scorecard lines and targets can only be edited when the Scorecard is in Draft state.')
        return super().write(vals)

    def unlink(self):
        for rec in self:
            sc = rec.scorecard_id
            if sc:
                if sc.is_current_employee and not (sc.is_planning_role or sc.is_admin_role or self.env.is_admin()):
                    raise UserError('Employees are not permitted to delete scorecard lines.')
                if sc.state != 'draft':
                    raise UserError('Scorecard lines can only be deleted when the Scorecard is in Draft state.')
        return super().unlink()