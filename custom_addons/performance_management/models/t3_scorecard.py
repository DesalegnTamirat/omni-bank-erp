# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from .t2_appraisal import detect_period_type
from .performance_notification_helper import send_performance_notification


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
        'appraisal.period', string='Appraisal Period', readonly=True,
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
        compute_sudo=True,
        string="Department",
    )

    def _compute_department_id(self):
        for rec in self:
            rec.department_id = rec.sudo().employee_id.department_id if rec.sudo().employee_id else False

    job_id = fields.Many2one("hr.job", string="Job Position", readonly=True)

    start_date = fields.Date(readonly=True)
    end_date = fields.Date(readonly=True)

    accept_by = fields.Date(
        string='Accept By',
        help='Date before which the employee should review and accept or reject the scorecard.',
    )
    accepted_by = fields.Many2one("hr.employee", string="Accepted By")

    employee_image_128 = fields.Image(
        string='Employee Photo',
        related='employee_id.image_128',
        compute_sudo=True,
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
        string="Total Weight (%)",
        digits=(16, 2),
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

    @api.constrains('employee_id', 'fiscal_year_id', 'appraisal_period_id')
    def _check_unique_scorecard(self):
        # 1. In-memory duplicate check within the current batch
        seen = set()
        for rec in self:
            if rec.employee_id and rec.fiscal_year_id and rec.appraisal_period_id:
                key = (rec.employee_id.id, rec.fiscal_year_id.id, rec.appraisal_period_id.id)
                if key in seen:
                    raise ValidationError(
                        f"Employee '{rec.employee_id.name}' has multiple Tier 3 Scorecards in this batch for "
                        f"Fiscal Year '{rec.fiscal_year_id.name}' and Period '{rec.appraisal_period_id.name}'."
                    )
                seen.add(key)

        if not self:
            return

        # 2. Single batch SQL query against existing records in the database
        emp_ids = self.mapped('employee_id').ids
        fy_ids = self.mapped('fiscal_year_id').ids
        period_ids = self.mapped('appraisal_period_id').ids
        self_ids = self.ids

        duplicates = self.sudo().search([
            ('id', 'not in', self_ids),
            ('employee_id', 'in', emp_ids),
            ('fiscal_year_id', 'in', fy_ids),
            ('appraisal_period_id', 'in', period_ids),
        ])
        if duplicates:
            dup_map = {
                (d.employee_id.id, d.fiscal_year_id.id, d.appraisal_period_id.id): d
                for d in duplicates
            }
            for rec in self:
                key = (rec.employee_id.id, rec.fiscal_year_id.id, rec.appraisal_period_id.id)
                if key in dup_map:
                    duplicate = dup_map[key]
                    state_label = dict(duplicate._fields['state'].selection).get(duplicate.state, duplicate.state)
                    raise ValidationError(
                        f"Employee '{rec.employee_id.name}' already has a Tier 3 Scorecard for "
                        f"Fiscal Year '{rec.fiscal_year_id.name}' and Period '{rec.appraisal_period_id.name}' "
                        f"(Status: {state_label}). Each employee can only have one Scorecard per appraisal period."
                    )

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
        user_emp_ids = user.sudo().employee_ids.ids

        for rec in self:
            rec.is_planning_role = is_planning
            rec.is_hr_role = is_hr
            rec.is_admin_role = is_admin

            emp_sudo = rec.sudo().employee_id
            mgr_sudo = rec.sudo().manager_id

            emp_user = emp_sudo.user_id.id if emp_sudo else False
            emp_id = emp_sudo.id if emp_sudo else False
            rec.is_current_employee = bool(
                (emp_user and emp_user == user.id) or
                (emp_id and emp_id in user_emp_ids)
            )

            mgr_user = mgr_sudo.user_id.id if mgr_sudo else False
            mgr_id = mgr_sudo.id if mgr_sudo else False
            coach_user = emp_sudo.coach_id.user_id.id if emp_sudo and emp_sudo.coach_id else False
            parent_user = emp_sudo.parent_id.user_id.id if emp_sudo and emp_sudo.parent_id else False
            rec.is_current_manager = bool(
                (mgr_user and mgr_user == user.id) or
                (mgr_id and mgr_id in user_emp_ids) or
                (coach_user and coach_user == user.id) or
                (parent_user and parent_user == user.id)
            )

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
                    f"Tier 3 Scorecard for '{rec.sudo().employee_id.name or 'Employee'}' cannot be notified "
                    f"because it has no scorecard lines."
                )
            code = rec.appraisal_period_code or detect_period_type(
                period_rec=rec.appraisal_period_id,
                start_date=rec.start_date,
                end_date=rec.end_date,
                fiscal_year=rec.fiscal_year_id,
            ) or 'H1'
            target_field, target_label = period_target_map.get(code, ('h1_target', 'H1 Target'))

            invalid_measures = []
            for line in rec.line_ids:
                target_val = getattr(line, target_field, 0.0) or 0.0
                if target_val <= 0.0:
                    measure_name = line.job_measure_id.name if line.job_measure_id else 'KPI Measure'
                    invalid_measures.append(f"{measure_name} (Current {target_label}: {target_val})")

            if invalid_measures:
                period_name = rec.appraisal_period_id.name if rec.appraisal_period_id else code
                raise UserError(
                    f"Scorecard for '{rec.sudo().employee_id.name}' cannot be notified for appraisal period '{period_name}'. "
                    f"All scorecard lines must have a valid non-zero {target_label} set.\n\n"
                    f"Missing or zero targets found for:\n- " + "\n- ".join(invalid_measures)
                )

    def action_notify(self):
        for rec in self:
            if not (rec.is_current_manager or rec.is_hr_role or rec.is_admin_role or self.env.is_admin()):
                raise UserError('Only the Manager or HR administrator can notify the employee.')
            if not rec.accept_by:
                raise UserError(f"Please provide an 'Accept By' deadline before notifying the employee for scorecard '{rec.planning_name or rec.name or rec.display_name}'.")
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
            manager_name = (rec.manager_id.name if rec.manager_id else (self.env.user.name or 'Manager'))
            emp_name = emp.name if emp else 'Employee'
            doc_name = rec.planning_name or rec.name or f"Scorecard - {emp_name}"

            details = [
                ("Document Name", f"<strong>{doc_name}</strong>"),
                ("Employee", f"<strong>{emp_name}</strong>"),
                ("Manager", manager_name),
                ("Appraisal Period", f"{period_name} ({fy_name})"),
                ("Accept By Deadline", f'<span style="color: #c53030; font-weight: bold;">{accept_by_str}</span>'),
                ("Total Weight", f"{rec.total_weight:.2f}%"),
                ("Current Status", '<span style="background-color: #feebc8; color: #7b341e; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">NOTIFIED</span>'),
            ]

            send_performance_notification(
                record=rec,
                title="📋 Tier 3 Scorecard Notified for Review",
                badge_text="NOTIFIED",
                badge_bg="#c17540",
                border_color="#c17540",
                intro_text=f"Manager <strong>{manager_name}</strong> has notified your Tier 3 Scorecard for period <strong>{period_name}</strong> ({fy_name}). Please review your assigned targets and accept or reject before the deadline.",
                details=details,
                action_btn_text="🎯 Review & Accept Scorecard",
                action_btn_color="#541718",
                footer_note=f"Notified to <b>{emp_name}</b> for review and acceptance before <b>{accept_by_str}</b>.",
                recipient_partner_ids=partner_ids,
                activity_user_id=emp_user.id if emp_user else False,
                activity_summary=f"Review & Accept Scorecard ({period_name}) - Deadline: {accept_by_str}",
                activity_deadline=rec.accept_by,
            )

    def action_accept(self):
        for rec in self:
            if not (rec.is_current_employee or self.env.is_admin()):
                raise UserError('Only the assigned employee can accept this Tier 3 Scorecard.')
            user_emp_id = self.env.user.sudo().employee_id.id or rec.sudo().employee_id.id
            rec.sudo().write({
                'state': 'accepted',
                'accepted_by': user_emp_id,
            })
            
            # Locate manager to notify
            manager = rec.manager_id or rec.employee_id.parent_id or rec.employee_id.coach_id
            mgr_user = manager.user_id if manager else False
            mgr_partner = mgr_user.partner_id if mgr_user else False
            partner_ids = [mgr_partner.id] if mgr_partner else []

            period_name = rec.appraisal_period_id.name if rec.appraisal_period_id else ''
            fy_name = rec.fiscal_year_id.name if rec.fiscal_year_id else ''
            emp_name = rec.employee_id.name if rec.employee_id else 'Employee'
            manager_name = manager.name if manager else 'Manager'
            doc_name = rec.planning_name or rec.name or f"Scorecard - {emp_name}"

            try:
                rec.activity_feedback(['mail.mail_activity_data_todo'], feedback="Scorecard accepted by employee.")
            except Exception:
                pass

            details = [
                ("Document Name", f"<strong>{doc_name}</strong>"),
                ("Employee", f"<strong>{emp_name}</strong>"),
                ("Appraisal Period", f"{period_name} ({fy_name})"),
                ("Total Weight", f"{rec.total_weight:.2f}%"),
                ("Accepted By", f"<strong>{rec.accepted_by.name or emp_name}</strong>"),
                ("Current Status", '<span style="background-color: #dcfce7; color: #166534; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">ACCEPTED</span>'),
            ]

            send_performance_notification(
                record=rec,
                title="✅ Scorecard Accepted by Employee",
                badge_text="ACCEPTED",
                badge_bg="#28a745",
                border_color="#28a745",
                intro_text=f"Employee <strong>{emp_name}</strong> has reviewed and <strong>ACCEPTED</strong> their Tier 3 Scorecard for period <strong>{period_name}</strong> ({fy_name}).",
                details=details,
                action_btn_text="🎯 Open & Confirm Scorecard",
                action_btn_color="#166534",
                footer_note=f"Manager <b>{manager_name}</b>, please confirm this scorecard to finalize targets.",
                recipient_partner_ids=partner_ids,
                activity_user_id=mgr_user.id if mgr_user else False,
                activity_summary=f"Scorecard Accepted by {emp_name} - Action: Confirm",
            )

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
            
            emp = rec.employee_id
            emp_user = emp.user_id if emp else False
            emp_partner = emp_user.partner_id if emp_user else False
            partner_ids = [emp_partner.id] if emp_partner else []

            period_name = rec.appraisal_period_id.name if rec.appraisal_period_id else ''
            fy_name = rec.fiscal_year_id.name if rec.fiscal_year_id else ''
            emp_name = emp.name if emp else 'Employee'
            manager_name = (rec.manager_id.name if rec.manager_id else (self.env.user.name or 'Manager'))
            doc_name = rec.planning_name or rec.name or f"Scorecard - {emp_name}"

            try:
                rec.activity_feedback(['mail.mail_activity_data_todo'], feedback="Scorecard confirmed by manager.")
            except Exception:
                pass

            details = [
                ("Document Name", f"<strong>{doc_name}</strong>"),
                ("Employee", f"<strong>{emp_name}</strong>"),
                ("Manager", manager_name),
                ("Appraisal Period", f"{period_name} ({fy_name})"),
                ("Total Weight", f"{rec.total_weight:.2f}%"),
                ("Current Status", '<span style="background-color: #dbeafe; color: #1e40af; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">CONFIRMED</span>'),
            ]

            send_performance_notification(
                record=rec,
                title="🔒 Scorecard Confirmed & Finalized",
                badge_text="CONFIRMED",
                badge_bg="#425727",
                border_color="#425727",
                intro_text=f"Manager <strong>{manager_name}</strong> has <strong>CONFIRMED &amp; FINALIZED</strong> the Tier 3 Scorecard for <strong>{emp_name}</strong> for period <strong>{period_name}</strong> ({fy_name}).",
                details=details,
                action_btn_text="🎯 View Confirmed Scorecard",
                action_btn_color="#425727",
                footer_note="Scorecard targets are confirmed and active for appraisal evaluation.",
                recipient_partner_ids=partner_ids,
            )

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
        Template = self.env['performance.job.template']
        Line = self.env['t3.scorecard.line']

        # Pre-cache active complete templates
        active_templates = Template.search([
            ('active', '=', True),
            ('weight_status', '=', 'complete'),
        ])
        if active_templates:
            active_templates._sync_to_job_measures()

        direct_template_map = {}
        branch_template_map = {}
        for t in active_templates:
            measures = t.line_ids.mapped('job_measure_id').filtered(lambda m: m and m.exists() and m.active)
            if t.operating_unit_id:
                direct_template_map[(t.operating_unit_id.id, t.job_id.id)] = measures
            if t.is_branch_unit:
                branch_template_map[t.job_id.id] = measures

        branch_types = ('branch', 'sub_branch', 'service_center')
        vals_list = []
        for scorecard in self:
            emp_unit = scorecard.operating_unit_id
            emp_job = scorecard.job_id
            if not emp_job:
                continue

            measures = self.env['performance.job.measure']
            if emp_unit and (emp_unit.id, emp_job.id) in direct_template_map:
                measures = direct_template_map[(emp_unit.id, emp_job.id)]
            else:
                is_branch = emp_unit and hasattr(emp_unit, 'work_unit_type') and emp_unit.work_unit_type in branch_types
                if not is_branch and scorecard.employee_id:
                    emp_ou = scorecard.employee_id.default_operating_unit_id
                    if emp_ou and hasattr(emp_ou, 'work_unit_type') and emp_ou.work_unit_type in branch_types:
                        is_branch = True
                if is_branch and emp_job.id in branch_template_map:
                    measures = branch_template_map[emp_job.id]

            if not measures:
                # Fallback to direct JobMeasures if configured outside templates
                measures = self.env['performance.job.measure'].search([
                    ('operating_unit_id', '=', emp_unit.id if emp_unit else False),
                    ('job_id', '=', emp_job.id),
                    ('active', '=', True),
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
        ondelete='cascade',
        domain="['|', ('operating_unit_id', '=', scorecard_operating_unit_id), ('operating_unit_id.work_unit_type', 'in', ('branch', 'sub_branch', 'service_center')), ('job_id', '=', scorecard_job_id)]",
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
        related='job_measure_id.weight', store=True, readonly=True, digits=(16, 2), string='Weight (%)',
    )
    target_type = fields.Selection(
        related='job_measure_id.target_type', store=True, readonly=True,
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
                if sc.is_current_employee and not (sc.is_current_manager or sc.is_hr_role or sc.is_admin_role or self.env.is_admin()):
                    raise UserError('Employees are not permitted to edit scorecard lines.')
                if sc.state != 'draft':
                    raise UserError('Scorecard lines and targets can only be edited when the Scorecard is in Draft state.')
                # Block editing structural fields like weight, target_type, job_measure_id
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
                if sc.is_current_employee and not (sc.is_current_manager or sc.is_hr_role or sc.is_admin_role or self.env.is_admin()):
                    raise UserError('Employees are not permitted to delete scorecard lines.')
                if sc.state != 'draft':
                    raise UserError('Scorecard lines can only be deleted when the Scorecard is in Draft state.')
                if not (sc.is_admin_role or self.env.is_admin()):
                    raise UserError('Manual deletion of scorecard lines is restricted. Scorecard lines are populated automatically from templates.')
        return super().unlink()