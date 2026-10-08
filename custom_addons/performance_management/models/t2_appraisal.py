# -*- coding: utf-8 -*-
import datetime
import re
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from .performance_notification_helper import send_performance_notification


def detect_period_type(period_rec=None, start_date=None, end_date=None, fiscal_year=None):
    if period_rec:
        code = (getattr(period_rec, 'code', '') or '').strip().upper()
        if code in ('H1', 'Q2', 'H-1', 'H 1'):
            return 'H1'
        if code in ('H2', 'Q4', 'H-2', 'H 2'):
            return 'H2'
        if code in ('Q1', 'Q-1', 'Q 1'):
            return 'Q1'
        if code in ('Q3', 'Q-3', 'Q 3'):
            return 'Q3'

        name = (getattr(period_rec, 'name', '') or '').strip().upper()
        normalized = re.sub(r'[^A-Z0-9]', ' ', name)
        words = normalized.split()

        # Check H1 / Q2 patterns
        if any(w in ('H1', 'Q2', 'SEM1', 'SEMESTER1') for w in words) or \
           'H1' in name or 'Q2' in name or \
           'HALF 1' in normalized or 'FIRST HALF' in normalized or '1ST HALF' in normalized or \
           'SEMESTER 1' in normalized or 'QUARTER 2' in normalized or '2ND QUARTER' in normalized or \
           'SECOND QUARTER' in normalized:
            return 'H1'

        # Check H2 / Q4 patterns
        if any(w in ('H2', 'Q4', 'SEM2', 'SEMESTER2') for w in words) or \
           'H2' in name or 'Q4' in name or \
           'HALF 2' in normalized or 'SECOND HALF' in normalized or '2ND HALF' in normalized or \
           'SEMESTER 2' in normalized or 'QUARTER 4' in normalized or '4TH QUARTER' in normalized or \
           'FOURTH QUARTER' in normalized:
            return 'H2'

        # Check Q1 patterns
        if any(w in ('Q1',) for w in words) or 'Q1' in name or \
           'QUARTER 1' in normalized or 'FIRST QUARTER' in normalized or '1ST QUARTER' in normalized:
            return 'Q1'

        # Check Q3 patterns
        if any(w in ('Q3',) for w in words) or 'Q3' in name or \
           'QUARTER 3' in normalized or 'THIRD QUARTER' in normalized or '3RD QUARTER' in normalized:
            return 'Q3'

    if start_date and end_date and fiscal_year:
        fy_start = fiscal_year.date_start
        fy_end = fiscal_year.date_end
        if fy_start and fy_end:
            total_days = (fy_end - fy_start).days
            mid_date = fy_start + datetime.timedelta(days=total_days // 2)
            if end_date <= mid_date:
                return 'H1'
            else:
                return 'H2'

    return False


def get_target_for_period(sc_line, period_type):
    if not sc_line:
        return 0.0
    if period_type == 'H1':
        return sc_line.h1_target or 0.0
    elif period_type == 'H2':
        return sc_line.h2_target or 0.0
    elif period_type == 'Q1':
        return sc_line.q1_target or 0.0
    elif period_type == 'Q3':
        return sc_line.q3_target or 0.0
    elif period_type == 'ANNUAL':
        return sc_line.annual_target or 0.0
    return 0.0


class T2Appraisal(models.Model):
    _name = 't2.appraisal'
    _description = 'Tier 2 Performance Appraisal'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_date desc, name'

    name = fields.Char(
        string='Appraisal Name',
        compute='_compute_name',
        store=True,
        readonly=True,
    )
    scorecard_id = fields.Many2one(
        't2.scorecard',
        string='Tier 2 Scorecard',
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
        compute_sudo=True,
        max_width=128,
        max_height=128,
        store=True,
    )
    operating_unit_id = fields.Many2one(
        'operating.unit',
        string='Operating Unit Name',
        compute='_compute_operating_unit_id',
        store=True,
        readonly=False,
    )
    department_id = fields.Many2one(
        'hr.department',
        compute='_compute_department_id',
        compute_sudo=True,
        string='Department',
        store=True,
    )
    job_id = fields.Many2one(
        'hr.job',
        string='Job Position',
        readonly=True,
    )
    start_date = fields.Date(
        string='Period Start Date',
        readonly=True,
    )
    end_date = fields.Date(
        string='Period End Date',
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

    @api.depends('employee_id', 'scorecard_id')
    def _compute_operating_unit_id(self):
        for rec in self:
            if rec.scorecard_id and rec.scorecard_id.operating_unit_id:
                rec.operating_unit_id = rec.scorecard_id.operating_unit_id
            elif rec.employee_id:
                obj = self.env['performance.objective'].search([('employee_id', '=', rec.employee_id.id)], limit=1)
                if obj and obj.employee_operating_unit_id:
                    rec.operating_unit_id = obj.employee_operating_unit_id
                elif hasattr(rec.employee_id, 'default_operating_unit_id') and rec.employee_id.default_operating_unit_id:
                    rec.operating_unit_id = rec.employee_id.default_operating_unit_id

    @api.depends('operating_unit_id', 'employee_id', 'fiscal_year_id', 'appraisal_period_id')
    def _compute_name(self):
        for rec in self:
            unit = rec.operating_unit_id.name if rec.operating_unit_id else (rec.employee_id.name if rec.employee_id else '')
            fy = rec.fiscal_year_id.name if rec.fiscal_year_id else ''
            period = rec.appraisal_period_id.name if rec.appraisal_period_id else ''
            parts = [unit, 'Appraisal', fy, period]
            rec.name = ' '.join([p for p in parts if p]).strip() or 'Tier 2 Appraisal'
    manager_id = fields.Many2one(
        'hr.employee',
        string='Manager',
        readonly=True,
    )
    employee_score = fields.Float(
        string='Employee Score',
        digits=(16, 2),
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

    line_ids = fields.One2many(
        't2.appraisal.line',
        'appraisal_id',
        string='Performance Appraisal Details',
        copy=True,
    )

    @api.depends('employee_id')
    def _compute_department_id(self):
        for rec in self:
            rec.department_id = rec.sudo().employee_id.department_id if rec.sudo().employee_id else False

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
            if not (rec.is_current_manager or rec.is_planning_role or rec.is_admin_role or self.env.is_admin()):
                raise UserError('Employees are not permitted to populate appraisal scores.')
            
            invalid_lines = rec.line_ids.filtered(lambda l: l.appraised == 'yes' and (l.uploaded_value or 0.0) <= 0.0)
            if invalid_lines:
                measure_names = ", ".join(invalid_lines.mapped(lambda l: l.measure_id.name or 'KPI Measure'))
                raise UserError(
                    f"Uploaded value must be greater than 0 for all appraised measures before calculating scores.\n"
                    f"Please enter valid uploaded values for:\n- {measure_names}"
                )
            
            invalid_percent_lines = rec.line_ids.filtered(
                lambda l: (l.appraisal_type or '').lower() in ('percent', 'percentage') and (l.uploaded_value or 0.0) > 100.0
            )
            if invalid_percent_lines:
                measure_names = ", ".join(invalid_percent_lines.mapped(lambda l: f"{l.measure_id.name or 'KPI Measure'} ({l.uploaded_value}%)"))
                raise UserError(
                    f"Uploaded value for percentage-based measures cannot exceed 100%.\n"
                    f"Please correct the following measures:\n- {measure_names}"
                )

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
                    scorecard = self.env['t2.scorecard'].search([
                        ('employee_id', '=', rec.employee_id.id),
                        ('fiscal_year_id', '=', rec.fiscal_year_id.id),
                    ], limit=1)

                if scorecard and line.measure_id:
                    sc_line = scorecard.line_ids.filtered(
                        lambda sl: sl.measure_id == line.measure_id
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
            if not (rec.is_current_manager or rec.is_planning_role or rec.is_admin_role or self.env.is_admin()):
                raise UserError('Only the Manager or Planning administrator can notify the employee.')
            if not rec.accept_by:
                raise UserError(f"Please provide an 'Accept By' deadline before notifying the employee for appraisal '{rec.name or rec.display_name}'.")
            
            invalid_lines = rec.line_ids.filtered(lambda l: l.appraised == 'yes' and (l.uploaded_value or 0.0) <= 0.0)
            if invalid_lines:
                measure_names = ", ".join(invalid_lines.mapped(lambda l: l.measure_id.name or 'KPI Measure'))
                raise UserError(
                    f"Tier 2 Appraisal cannot be notified because some appraised measures have 0 or missing uploaded values.\n"
                    f"Please provide valid uploaded values for:\n- {measure_names}"
                )
            
            invalid_percent_lines = rec.line_ids.filtered(
                lambda l: (l.appraisal_type or '').lower() in ('percent', 'percentage') and (l.uploaded_value or 0.0) > 100.0
            )
            if invalid_percent_lines:
                measure_names = ", ".join(invalid_percent_lines.mapped(lambda l: f"{l.measure_id.name or 'KPI Measure'} ({l.uploaded_value}%)"))
                raise UserError(
                    f"Tier 2 Appraisal cannot be notified because some percentage-based measures exceed 100%:\n- {measure_names}"
                )
            
            rec.write({'state': 'notified'})
            emp = rec.employee_id
            emp_user = emp.user_id if emp else False
            emp_partner = emp_user.partner_id if emp_user else False
            partner_ids = [emp_partner.id] if emp_partner else []

            period_name = rec.appraisal_period_id.name if rec.appraisal_period_id else ''
            fy_name = rec.fiscal_year_id.name if rec.fiscal_year_id else ''
            accept_by_str = str(rec.accept_by) if rec.accept_by else 'N/A'
            manager_name = (rec.manager_id.name if rec.manager_id else (self.env.user.name or 'Manager / Planning'))
            emp_name = emp.name if emp else (rec.operating_unit_id.name or 'Work Unit Manager')
            score = rec.employee_score or 0.0
            rating = rec.performance_rating or 'Not Rated'
            doc_name = rec.name or f"Tier 2 Appraisal - {emp_name}"

            details = [
                ("Document Name", f"<strong>{doc_name}</strong>"),
                ("Work Unit / Employee", f"<strong>{emp_name}</strong>"),
                ("Operating Unit", rec.operating_unit_id.name if rec.operating_unit_id else "N/A"),
                ("Manager / Planning", manager_name),
                ("Appraisal Period", f"{period_name} ({fy_name})"),
                ("Overall Evaluated Score", f'<span style="font-size: 14px; font-weight: bold; color: #541718;">{score:.2f}%</span>'),
                ("Performance Rating", f'<span style="font-weight: bold; color: #2b6cb0;">{rating}</span>'),
                ("Accept By Deadline", f'<span style="color: #c53030; font-weight: bold;">{accept_by_str}</span>'),
                ("Current Status", '<span style="background-color: #feebc8; color: #7b341e; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">NOTIFIED</span>'),
            ]

            send_performance_notification(
                record=rec,
                title="🏆 Tier 2 Appraisal Notified: Review & Accept Score",
                badge_text="NOTIFIED",
                badge_bg="#c17540",
                border_color="#c17540",
                intro_text=f"Manager / Planning <strong>{manager_name}</strong> has evaluated and notified the <strong>Tier 2 Appraisal</strong> for <strong>{emp_name}</strong> for period <strong>{period_name}</strong> ({fy_name}) with an overall score of <strong>{score:.2f}% ({rating})</strong>. Please review and accept or reject before the deadline.",
                details=details,
                action_btn_text="🎯 Review & Accept Tier 2 Appraisal",
                action_btn_color="#541718",
                footer_note=f"Notified to <b>{emp_name}</b> for evaluation review and acceptance before <b>{accept_by_str}</b>.",
                recipient_partner_ids=partner_ids,
                activity_user_id=emp_user.id if emp_user else False,
                activity_summary=f"Review Tier 2 Appraisal ({score:.2f}%, {rating}) - Deadline: {accept_by_str}",
                activity_deadline=rec.accept_by,
            )

    def action_accept(self):
        for rec in self:
            if not (rec.is_current_employee or self.env.is_admin()):
                raise UserError('Only the assigned employee can accept this Tier 2 Appraisal.')
            rec.sudo().write({'state': 'accepted'})
            
            manager = rec.manager_id or rec.employee_id.parent_id or rec.employee_id.coach_id
            mgr_user = manager.user_id if manager else False
            mgr_partner = mgr_user.partner_id if mgr_user else False
            partner_ids = [mgr_partner.id] if mgr_partner else []

            period_name = rec.appraisal_period_id.name if rec.appraisal_period_id else ''
            fy_name = rec.fiscal_year_id.name if rec.fiscal_year_id else ''
            emp_name = rec.employee_id.name if rec.employee_id else (rec.operating_unit_id.name or 'Work Unit Manager')
            manager_name = manager.name if manager else 'Manager / Planning'
            score = rec.employee_score or 0.0
            rating = rec.performance_rating or 'Not Rated'
            doc_name = rec.name or f"Tier 2 Appraisal - {emp_name}"

            try:
                rec.activity_feedback(['mail.mail_activity_data_todo'], feedback="Tier 2 Appraisal accepted by employee.")
            except Exception:
                pass

            details = [
                ("Document Name", f"<strong>{doc_name}</strong>"),
                ("Work Unit / Employee", f"<strong>{emp_name}</strong>"),
                ("Operating Unit", rec.operating_unit_id.name if rec.operating_unit_id else "N/A"),
                ("Appraisal Period", f"{period_name} ({fy_name})"),
                ("Accepted Score", f'<span style="font-weight: bold; color: #166534; font-size: 14px;">{score:.2f}%</span>'),
                ("Performance Rating", f'<span style="font-weight: bold; color: #2b6cb0;">{rating}</span>'),
                ("Current Status", '<span style="background-color: #dcfce7; color: #166534; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">ACCEPTED</span>'),
            ]

            send_performance_notification(
                record=rec,
                title="🎉 Tier 2 Appraisal Accepted",
                badge_text="ACCEPTED",
                badge_bg="#28a745",
                border_color="#28a745",
                intro_text=f"<strong>{emp_name}</strong> has reviewed and <strong>ACCEPTED</strong> the evaluated Tier 2 Appraisal (Score: <strong>{score:.2f}%</strong>, Rating: <strong>{rating}</strong>) for period <strong>{period_name}</strong> ({fy_name}).",
                details=details,
                action_btn_text="🎯 Open & Confirm Tier 2 Appraisal",
                action_btn_color="#166534",
                footer_note=f"Manager / Planning <b>{manager_name}</b>, please confirm this Tier 2 appraisal to finalize.",
                recipient_partner_ids=partner_ids,
                activity_user_id=mgr_user.id if mgr_user else False,
                activity_summary=f"Tier 2 Appraisal Accepted by {emp_name} ({score:.2f}%) - Action: Confirm",
            )

    def action_reject(self):
        for rec in self:
            if not (rec.is_current_employee or self.env.is_admin()):
                raise UserError('Only the assigned employee can reject this Tier 2 Appraisal.')
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
            if not (rec.is_current_manager or rec.is_planning_role or rec.is_admin_role or self.env.is_admin()):
                raise UserError('Only the Manager or Planning administrator can confirm this Tier 2 Appraisal.')
            
            invalid_lines = rec.line_ids.filtered(lambda l: l.appraised == 'yes' and (l.uploaded_value or 0.0) <= 0.0)
            if invalid_lines:
                measure_names = ", ".join(invalid_lines.mapped(lambda l: l.measure_id.name or 'KPI Measure'))
                raise UserError(
                    f"Tier 2 Appraisal cannot be confirmed because some appraised measures have 0 or missing uploaded values:\n- {measure_names}"
                )
            
            invalid_percent_lines = rec.line_ids.filtered(
                lambda l: (l.appraisal_type or '').lower() in ('percent', 'percentage') and (l.uploaded_value or 0.0) > 100.0
            )
            if invalid_percent_lines:
                measure_names = ", ".join(invalid_percent_lines.mapped(lambda l: f"{l.measure_id.name or 'KPI Measure'} ({l.uploaded_value}%)"))
                raise UserError(
                    f"Tier 2 Appraisal cannot be confirmed because some percentage-based measures exceed 100%:\n- {measure_names}"
                )
            
            rec.write({'state': 'confirmed'})
            
            emp = rec.employee_id
            emp_user = emp.user_id if emp else False
            emp_partner = emp_user.partner_id if emp_user else False
            partner_ids = [emp_partner.id] if emp_partner else []

            period_name = rec.appraisal_period_id.name if rec.appraisal_period_id else ''
            fy_name = rec.fiscal_year_id.name if rec.fiscal_year_id else ''
            emp_name = emp.name if emp else (rec.operating_unit_id.name or 'Work Unit Manager')
            manager_name = self.env.user.name or 'Manager / Planning'
            score = rec.employee_score or 0.0
            rating = rec.performance_rating or 'Not Rated'
            doc_name = rec.name or f"Tier 2 Appraisal - {emp_name}"

            try:
                rec.activity_feedback(['mail.mail_activity_data_todo'], feedback="Tier 2 Appraisal confirmed.")
            except Exception:
                pass

            details = [
                ("Document Name", f"<strong>{doc_name}</strong>"),
                ("Work Unit / Employee", f"<strong>{emp_name}</strong>"),
                ("Operating Unit", rec.operating_unit_id.name if rec.operating_unit_id else "N/A"),
                ("Manager / Planning", manager_name),
                ("Appraisal Period", f"{period_name} ({fy_name})"),
                ("Final Confirmed Score", f'<span style="font-weight: bold; color: #425727; font-size: 14px;">{score:.2f}%</span>'),
                ("Final Performance Rating", f'<span style="font-weight: bold; color: #2b6cb0;">{rating}</span>'),
                ("Current Status", '<span style="background-color: #dbeafe; color: #1e40af; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">CONFIRMED</span>'),
            ]

            send_performance_notification(
                record=rec,
                title="🔒 Tier 2 Appraisal Confirmed & Finalized",
                badge_text="CONFIRMED",
                badge_bg="#425727",
                border_color="#425727",
                intro_text=f"Manager / Planning <strong>{manager_name}</strong> has <strong>CONFIRMED &amp; FINALIZED</strong> the Tier 2 Appraisal for <strong>{emp_name}</strong> for period <strong>{period_name}</strong> ({fy_name}). Final Score: <strong>{score:.2f}%</strong> | Rating: <strong>{rating}</strong>.",
                details=details,
                action_btn_text="🎯 View Confirmed Tier 2 Appraisal",
                action_btn_color="#425727",
                footer_note="Tier 2 Appraisal evaluation concluded and recorded.",
                recipient_partner_ids=partner_ids,
            )

    def action_reset_draft(self):
        for rec in self:
            if rec.is_current_employee and not (rec.is_current_manager or rec.is_planning_role or rec.is_admin_role or self.env.is_admin()):
                raise UserError('Employees are not permitted to reset appraisals to draft.')
            if rec.state == 'confirmed':
                if not (rec.is_planning_role or rec.is_admin_role or self.env.is_admin()):
                    raise UserError('Once confirmed by the manager, only the Planning administrator can reset this Tier 2 Appraisal to draft.')
            elif not (rec.is_current_manager or rec.is_planning_role or rec.is_admin_role or self.env.is_admin()):
                raise UserError('Only the Manager or Planning administrator can reset this Tier 2 Appraisal to draft.')
            rec.write({'state': 'draft'})
            rec.message_post(body='Tier 2 Appraisal has been reset to draft.')

    def write(self, vals):
        for rec in self:
            if rec.is_current_employee and not (rec.is_current_manager or rec.is_planning_role or rec.is_admin_role or self.env.is_admin()):
                allowed_fields = {'state', 'rejection_reason'}
                if not set(vals.keys()).issubset(allowed_fields):
                    raise UserError('Employees are not permitted to edit appraisals.')
            if rec.state in ('accepted', 'confirmed'):
                allowed_fields = {'state', 'rejection_reason'}
                if rec.is_planning_role or rec.is_admin_role or self.env.is_admin():
                    allowed_fields |= {'employee_id', 'manager_id', 'job_id', 'operating_unit_id', 'department_id', 'fiscal_year_id', 'appraisal_period_id'}
                if not set(vals.keys()).issubset(allowed_fields):
                    raise UserError(
                        'This Tier 2 Appraisal is %s and can no longer be edited.'
                        % dict(rec._fields['state'].selection).get(rec.state, rec.state)
                    )
        return super().write(vals)


class T2AppraisalLine(models.Model):
    _name = 't2.appraisal.line'
    _description = 'Tier 2 Performance Appraisal Detail'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    appraisal_id = fields.Many2one(
        't2.appraisal',
        string='Tier 2 Appraisal',
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
    objective_id = fields.Many2one(
        'performance.objective',
        string='Objective',
        readonly=True,
        ondelete='cascade',
    )
    measure_id = fields.Many2one(
        'performance.measure',
        string='Measurements',
        readonly=True,
        ondelete='cascade',
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

    @api.depends('planned_weight', 'appraised', 'appraisal_id.scorecard_id', 'measure_id')
    def _compute_weight(self):
        for line in self:
            if not line.planned_weight:
                scorecard = line.appraisal_id.scorecard_id if line.appraisal_id else False
                if not scorecard and line.appraisal_id and line.appraisal_id.employee_id:
                    scorecard = self.env['t2.scorecard'].search([
                        ('employee_id', '=', line.appraisal_id.employee_id.id),
                        ('fiscal_year_id', '=', line.appraisal_id.fiscal_year_id.id),
                    ], limit=1)
                if scorecard and line.measure_id:
                    sc_line = scorecard.line_ids.filtered(lambda sl: sl.measure_id == line.measure_id)[:1]
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

    @api.depends('appraisal_id.scorecard_id', 'appraisal_id.appraisal_period_id', 'appraisal_id.start_date', 'appraisal_id.end_date', 'measure_id')
    def _compute_target(self):
        for line in self:
            appraisal = line.appraisal_id
            scorecard = appraisal.scorecard_id if appraisal else False
            if not scorecard and appraisal and appraisal.employee_id:
                scorecard = self.env['t2.scorecard'].search([
                    ('employee_id', '=', appraisal.employee_id.id),
                    ('fiscal_year_id', '=', appraisal.fiscal_year_id.id),
                ], limit=1)

            if scorecard and line.measure_id:
                sc_line = scorecard.line_ids.filtered(lambda sl: sl.measure_id == line.measure_id)[:1]
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
        related='measure_id.target_type',
        store=True,
        readonly=True,
        string='Appraisal Type',
    )
    appraisal_criteria = fields.Char(string='Appraisal Criteria')
    uploaded_value = fields.Float(string='Uploaded Value')

    @api.onchange('uploaded_value', 'appraisal_type')
    def _onchange_uploaded_value_percent(self):
        for line in self:
            app_type = (line.appraisal_type or '').lower()
            if app_type in ('percent', 'percentage') and (line.uploaded_value or 0.0) > 100.0:
                val = line.uploaded_value
                line.uploaded_value = 100.0
                return {
                    'warning': {
                        'title': 'Invalid Uploaded Value',
                        'message': f"Percentage-based measures cannot exceed 100%. The value has been adjusted from {val}% to 100%."
                    }
                }

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
                if app.is_current_employee and not (app.is_current_manager or app.is_planning_role or app.is_admin_role or self.env.is_admin()):
                    raise UserError('Employees are not permitted to edit appraisal lines.')
                if 'uploaded_value' in vals and app.state != 'draft':
                    raise UserError('Uploaded Value can only be edited when the Appraisal is in Draft state.')
        return super().write(vals)
