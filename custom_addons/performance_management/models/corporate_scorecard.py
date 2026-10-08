# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from .t2_appraisal import detect_period_type
from .performance_notification_helper import send_performance_notification


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
        readonly=True,
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
        compute_sudo=True,
        max_width=128,
        max_height=128,
        store=True,
    )
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, default=lambda self: self.env.user.employee_id)
    manager_id = fields.Many2one('hr.employee', string='Manager', readonly=True)
    job_id = fields.Many2one('hr.job', string='Job Position', related='employee_id.job_id', compute_sudo=True, store=True, readonly=True)
    operating_unit_id = fields.Many2one('operating.unit', string='Operating Unit', readonly=True)
    department_id = fields.Many2one('hr.department', string='Department', related='employee_id.department_id', compute_sudo=True, store=True, readonly=True)
    accept_by = fields.Date(
        string='Accept By',
        help='Date before which the employee should review and accept or reject the scorecard.',
    )
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

    @api.constrains('fiscal_year_id', 'appraisal_period_id')
    def _check_unique_scorecard(self):
        for rec in self:
            if rec.fiscal_year_id and rec.appraisal_period_id:
                duplicate = self.sudo().search([
                    ('id', '!=', rec.id),
                    ('fiscal_year_id', '=', rec.fiscal_year_id.id),
                    ('appraisal_period_id', '=', rec.appraisal_period_id.id),
                ], limit=1)
                if duplicate:
                    state_label = dict(duplicate._fields['state'].selection).get(duplicate.state, duplicate.state)
                    raise ValidationError(
                        f"A Corporate Scorecard already exists for Fiscal Year '{rec.fiscal_year_id.name}' "
                        f"and Period '{rec.appraisal_period_id.name}' (Status: {state_label})."
                    )

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
        user_emp_ids = user.sudo().employee_ids.ids

        for rec in self:
            rec.is_planning_role = is_planning
            rec.is_hr_role = is_hr
            rec.is_admin_role = is_admin

            emp_sudo = rec.sudo().employee_id
            emp_user = emp_sudo.user_id.id if emp_sudo else False
            emp_id = emp_sudo.id if emp_sudo else False
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
        digits=(16, 2),
        compute='_compute_total_weight',
        store=True,
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
                if not fyl and rec.name:
                    for fy in self.env['performance.fiscal.year'].search([], limit=10):
                        if fy.name and fy.name in rec.name:
                            rec.fiscal_year_id = fy.id
                            break
                if fyl:
                    rec.fiscal_year_id = fyl.year_id.id

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

    def _validate_period_targets_for_notify(self):
        period_target_map = {
            'Q1': ('q1_target', 'Q1 Target'),
            'H1': ('h1_target', 'H1 Target'),
            'Q2': ('h1_target', 'H1 Target'),
            'Q3': ('q3_target', 'Q3 Target'),
            'H2': ('h2_target', 'H2 Target'),
            'Q4': ('h2_target', 'H2 Target'),
            'ANNUAL': ('annual_target', 'Annual Target'),
        }
        for rec in self:
            if not rec.line_ids:
                raise UserError(
                    f"Corporate Scorecard '{rec.name or ''}' cannot be notified because it has no scorecard lines."
                )
            code = rec.appraisal_period_code or detect_period_type(
                period_rec=rec.appraisal_period_id,
                start_date=rec.date_start,
                end_date=rec.date_end,
                fiscal_year=rec.fiscal_year_id,
            ) or 'H1'
            target_field, target_label = period_target_map.get(code, ('h1_target', 'H1 Target'))

            invalid_measures = []
            for line in rec.line_ids:
                target_val = getattr(line, target_field, 0.0) or 0.0
                if target_val <= 0.0:
                    measure_name = line.measure_id.name if line.measure_id else 'KPI Measure'
                    invalid_measures.append(f"{measure_name} (Current {target_label}: {target_val})")

            if invalid_measures:
                period_name = rec.appraisal_period_id.name if rec.appraisal_period_id else code
                raise UserError(
                    f"Corporate Scorecard cannot be notified for appraisal period '{period_name}'. "
                    f"All scorecard lines must have a valid non-zero {target_label} set.\n\n"
                    f"Missing or zero targets found for:\n- " + "\n- ".join(invalid_measures)
                )

    def action_notify(self):
        for rec in self:
            if not (rec.is_planning_role or rec.is_admin_role or self.env.is_admin()):
                raise UserError('Only the Planning administrator can notify the employee.')
            if not rec.accept_by:
                raise UserError(f"Please provide an 'Accept By' deadline before notifying the employee for corporate scorecard '{rec.name or rec.display_name}'.")
        self._validate_period_targets_for_notify()
        for rec in self:
            rec.write({'state': 'notified'})
            emp = rec.employee_id
            emp_user = emp.user_id if emp else False
            emp_partner = emp_user.partner_id if emp_user else False
            partner_ids = [emp_partner.id] if emp_partner else []

            period_name = rec.appraisal_period_id.name if rec.appraisal_period_id else ''
            fy_name = rec.fiscal_year_id.name if rec.fiscal_year_id else ''
            accept_by_str = str(rec.accept_by) if rec.accept_by else 'N/A'
            manager_name = self.env.user.name or 'Planning Administrator'
            emp_name = emp.name if emp else 'Assigned Executive'
            doc_name = rec.name or f"Corporate Scorecard - {fy_name}"

            details = [
                ("Document Name", f"<strong>{doc_name}</strong>"),
                ("Executive / Assignee", f"<strong>{emp_name}</strong>"),
                ("Planning Admin", manager_name),
                ("Appraisal Period", f"{period_name} ({fy_name})"),
                ("Accept By Deadline", f'<span style="color: #c53030; font-weight: bold;">{accept_by_str}</span>'),
                ("Total Weight", f"{rec.total_weight:.2f}%"),
                ("Current Status", '<span style="background-color: #feebc8; color: #7b341e; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">NOTIFIED</span>'),
            ]

            send_performance_notification(
                record=rec,
                title="📋 Corporate Scorecard Notified: Review & Accept",
                badge_text="NOTIFIED",
                badge_bg="#c17540",
                border_color="#c17540",
                intro_text=f"Planning Administrator <strong>{manager_name}</strong> has notified the Corporate Scorecard for <strong>{emp_name}</strong> for period <strong>{period_name}</strong> ({fy_name}). Please review strategic targets and accept or reject before the deadline.",
                details=details,
                action_btn_text="🎯 Review & Accept Corporate Scorecard",
                action_btn_color="#541718",
                footer_note=f"Notified to <b>{emp_name}</b> for review and acceptance before <b>{accept_by_str}</b>.",
                recipient_partner_ids=partner_ids,
                activity_user_id=emp_user.id if emp_user else False,
                activity_summary=f"Review Corporate Scorecard ({period_name}) - Deadline: {accept_by_str}",
                activity_deadline=rec.accept_by,
            )

    def action_accept(self):
        for rec in self:
            if not (rec.is_current_employee or self.env.is_admin()):
                raise UserError('Only the assigned employee can accept this Corporate Scorecard.')
            user_emp_id = self.env.user.sudo().employee_id.id or rec.sudo().employee_id.id
            rec.sudo().write({
                'state': 'accepted',
                'accepted_by': user_emp_id,
            })
            
            period_name = rec.appraisal_period_id.name if rec.appraisal_period_id else ''
            fy_name = rec.fiscal_year_id.name if rec.fiscal_year_id else ''
            emp_name = rec.employee_id.name if rec.employee_id else 'Assigned Executive'
            doc_name = rec.name or f"Corporate Scorecard - {fy_name}"

            try:
                rec.activity_feedback(['mail.mail_activity_data_todo'], feedback="Corporate Scorecard accepted.")
            except Exception:
                pass

            details = [
                ("Document Name", f"<strong>{doc_name}</strong>"),
                ("Executive / Assignee", f"<strong>{emp_name}</strong>"),
                ("Appraisal Period", f"{period_name} ({fy_name})"),
                ("Total Weight", f"{rec.total_weight:.2f}%"),
                ("Accepted By", f"<strong>{rec.accepted_by.name or emp_name}</strong>"),
                ("Current Status", '<span style="background-color: #dcfce7; color: #166534; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">ACCEPTED</span>'),
            ]

            send_performance_notification(
                record=rec,
                title="✅ Corporate Scorecard Accepted",
                badge_text="ACCEPTED",
                badge_bg="#28a745",
                border_color="#28a745",
                intro_text=f"Executive <strong>{emp_name}</strong> has reviewed and <strong>ACCEPTED</strong> the Corporate Scorecard for period <strong>{period_name}</strong> ({fy_name}).",
                details=details,
                action_btn_text="🎯 Open & Confirm Corporate Scorecard",
                action_btn_color="#166534",
                footer_note="Planning Administrator, please confirm this corporate scorecard to finalize targets.",
            )

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
            
            emp = rec.employee_id
            emp_user = emp.user_id if emp else False
            emp_partner = emp_user.partner_id if emp_user else False
            partner_ids = [emp_partner.id] if emp_partner else []

            period_name = rec.appraisal_period_id.name if rec.appraisal_period_id else ''
            fy_name = rec.fiscal_year_id.name if rec.fiscal_year_id else ''
            emp_name = emp.name if emp else 'Assigned Executive'
            manager_name = self.env.user.name or 'Planning Administrator'
            doc_name = rec.name or f"Corporate Scorecard - {fy_name}"

            try:
                rec.activity_feedback(['mail.mail_activity_data_todo'], feedback="Corporate Scorecard confirmed.")
            except Exception:
                pass

            details = [
                ("Document Name", f"<strong>{doc_name}</strong>"),
                ("Executive / Assignee", f"<strong>{emp_name}</strong>"),
                ("Planning Admin", manager_name),
                ("Appraisal Period", f"{period_name} ({fy_name})"),
                ("Total Weight", f"{rec.total_weight:.2f}%"),
                ("Current Status", '<span style="background-color: #dbeafe; color: #1e40af; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">CONFIRMED</span>'),
            ]

            send_performance_notification(
                record=rec,
                title="🔒 Corporate Scorecard Confirmed & Finalized",
                badge_text="CONFIRMED",
                badge_bg="#425727",
                border_color="#425727",
                intro_text=f"Planning Administrator <strong>{manager_name}</strong> has <strong>CONFIRMED</strong> the Corporate Scorecard for <strong>{emp_name}</strong> for period <strong>{period_name}</strong> ({fy_name}).",
                details=details,
                action_btn_text="🎯 View Confirmed Corporate Scorecard",
                action_btn_color="#425727",
                footer_note="Corporate Scorecard targets are finalized and active for strategic appraisal evaluation.",
                recipient_partner_ids=partner_ids,
            )

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

        root_measures = Measure.search([
            ('objective_id.parent_objective_id', '=', False),
            ('objective_id.active', '=', True),
            ('active', '=', True),
        ])

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
        related='measure_id.weight', store=True, readonly=True, digits=(16, 2), string='Weight (%)',
    )
    target_type = fields.Selection(
        related='measure_id.target_type', store=True, readonly=True,
    )

    baseline = fields.Float(string='Baseline')
    q1_target = fields.Float(string='Q1 Target')
    h1_target = fields.Float(string='H1 Target')
    q3_target = fields.Float(string='Q3 Target')
    h2_target = fields.Float(string='H2 Target')
    annual_target = fields.Float(string='Annual Target')
    target_description = fields.Text(string='Target Description')

    def write(self, vals):
        allowed_target_fields = {
            'baseline', 'q1_target', 'h1_target', 'q3_target', 'h2_target',
            'annual_target', 'target_description', 'sequence'
        }
        for rec in self:
            sc = rec.scorecard_id
            if sc:
                if sc.is_current_employee and not (sc.is_planning_role or sc.is_admin_role or self.env.is_admin()):
                    raise UserError('Employees are not permitted to edit scorecard lines.')
                if sc.state != 'draft':
                    raise UserError('Scorecard lines and targets can only be edited when the Scorecard is in Draft state.')
                disallowed = set(vals.keys()) - allowed_target_fields
                if disallowed and not (sc.is_admin_role or self.env.is_admin()):
                    raise UserError(
                        f"Editing measurement definitions or weights is not allowed on scorecard lines. "
                        f"Only targets may be adjusted during draft."
                    )
        return super().write(vals)

    def unlink(self):
        for rec in self:
            sc = rec.scorecard_id
            if sc:
                if sc.is_current_employee and not (sc.is_planning_role or sc.is_admin_role or self.env.is_admin()):
                    raise UserError('Employees are not permitted to delete scorecard lines.')
                if sc.state != 'draft':
                    raise UserError('Scorecard lines can only be deleted when the Scorecard is in Draft state.')
                if not (sc.is_admin_role or self.env.is_admin()):
                    raise UserError('Manual deletion of scorecard lines is restricted. Scorecard lines are populated automatically.')
        return super().unlink()