# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from .t2_appraisal import detect_period_type, get_target_for_period
from .performance_notification_helper import send_performance_notification


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
        compute_sudo=True,
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
        digits=(16, 2),
        compute='_compute_employee_score',
        store=True,
        readonly=False,
    )
    work_unit_score = fields.Float(
        string='Work Unit Score',
        digits=(10, 2),
        compute='_compute_work_unit_score',
        readonly=True,
        help='Score of the employee’s operating unit from Tier 2 Appraisals for this fiscal year and appraisal period.',
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

    @api.depends('operating_unit_id', 'fiscal_year_id', 'appraisal_period_id', 'employee_id')
    def _compute_work_unit_score(self):
        for rec in self:
            ou = rec.operating_unit_id
            if not ou and rec.employee_id:
                ou = rec.employee_id.default_operating_unit_id
            if not ou or not rec.fiscal_year_id or not rec.appraisal_period_id:
                rec.work_unit_score = 0.0
                continue
            t2_app = self.env['t2.appraisal'].sudo().search([
                ('operating_unit_id', '=', ou.id),
                ('fiscal_year_id', '=', rec.fiscal_year_id.id),
                ('appraisal_period_id', '=', rec.appraisal_period_id.id),
            ], limit=1)
            rec.work_unit_score = t2_app.employee_score if (t2_app and t2_app.employee_score) else 0.0

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
        't3.appraisal.line',
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
            if not (rec.is_current_manager or rec.is_hr_role or rec.is_admin_role or self.env.is_admin()):
                raise UserError('Employees are not permitted to populate appraisal scores.')
            
            # Validation: uploaded_value must be > 0 for measures marked as appraised = 'yes'
            invalid_lines = rec.line_ids.filtered(lambda l: l.appraised == 'yes' and (l.uploaded_value or 0.0) <= 0.0)
            if invalid_lines:
                measure_names = ", ".join(invalid_lines.mapped(lambda l: l.job_measure_id.name or 'KPI Measure'))
                raise UserError(
                    f"Uploaded value must be greater than 0 for all appraised measures before calculating scores.\n"
                    f"Please enter valid uploaded values for:\n- {measure_names}"
                )
            
            invalid_percent_lines = rec.line_ids.filtered(
                lambda l: (l.appraisal_type or '').lower() in ('percent', 'percentage') and (l.uploaded_value or 0.0) > 100.0
            )
            if invalid_percent_lines:
                measure_names = ", ".join(invalid_percent_lines.mapped(lambda l: f"{l.job_measure_id.name or 'KPI Measure'} ({l.uploaded_value}%)"))
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
            if not rec.accept_by:
                raise UserError(f"Please provide an 'Accept By' deadline before notifying the employee for appraisal '{rec.name or rec.display_name}'.")
            
            invalid_lines = rec.line_ids.filtered(lambda l: l.appraised == 'yes' and (l.uploaded_value or 0.0) <= 0.0)
            if invalid_lines:
                measure_names = ", ".join(invalid_lines.mapped(lambda l: l.job_measure_id.name or 'KPI Measure'))
                raise UserError(
                    f"Tier 3 Appraisal for '{rec.employee_id.name}' cannot be notified because some appraised measures have 0 or missing uploaded values.\n"
                    f"Please provide valid uploaded values for:\n- {measure_names}"
                )
            
            invalid_percent_lines = rec.line_ids.filtered(
                lambda l: (l.appraisal_type or '').lower() in ('percent', 'percentage') and (l.uploaded_value or 0.0) > 100.0
            )
            if invalid_percent_lines:
                measure_names = ", ".join(invalid_percent_lines.mapped(lambda l: f"{l.job_measure_id.name or 'KPI Measure'} ({l.uploaded_value}%)"))
                raise UserError(
                    f"Tier 3 Appraisal for '{rec.employee_id.name}' cannot be notified because some percentage-based measures exceed 100%:\n- {measure_names}"
                )
            
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
            score = rec.employee_score or 0.0
            rating = rec.performance_rating or 'Not Rated'
            doc_name = rec.name or f"Appraisal - {emp_name}"

            details = [
                ("Document Name", f"<strong>{doc_name}</strong>"),
                ("Employee", f"<strong>{emp_name}</strong>"),
                ("Manager / Evaluator", manager_name),
                ("Appraisal Period", f"{period_name} ({fy_name})"),
                ("Overall Evaluated Score", f'<span style="font-size: 14px; font-weight: bold; color: #541718;">{score:.2f}%</span>'),
                ("Performance Rating", f'<span style="font-weight: bold; color: #2b6cb0;">{rating}</span>'),
            ]
            if hasattr(rec, 'work_unit_score') and (rec.work_unit_score or 0.0) > 0.0:
                details.append(("Work Unit Score", f'<span style="font-weight: bold; color: #425727;">{rec.work_unit_score:.2f}%</span>'))
            details.extend([
                ("Accept By Deadline", f'<span style="color: #c53030; font-weight: bold;">{accept_by_str}</span>'),
                ("Current Status", '<span style="background-color: #feebc8; color: #7b341e; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">NOTIFIED</span>'),
            ])

            send_performance_notification(
                record=rec,
                title="🏆 Tier 3 Performance Appraisal Notified",
                badge_text="NOTIFIED",
                badge_bg="#c17540",
                border_color="#c17540",
                intro_text=f"Manager <strong>{manager_name}</strong> has evaluated and notified your <strong>Tier 3 Appraisal</strong> for period <strong>{period_name}</strong> ({fy_name}) with an overall score of <strong>{score:.2f}% ({rating})</strong>. Please review and accept or reject before the deadline.",
                details=details,
                action_btn_text="🎯 Review & Accept Appraisal",
                action_btn_color="#541718",
                footer_note=f"Notified to <b>{emp_name}</b> for evaluation review and acceptance before <b>{accept_by_str}</b>.",
                recipient_partner_ids=partner_ids,
                activity_user_id=emp_user.id if emp_user else False,
                activity_summary=f"Review Appraisal ({score:.2f}%, {rating}) - Deadline: {accept_by_str}",
                activity_deadline=rec.accept_by,
            )

    def action_accept(self):
        for rec in self:
            if not (rec.is_current_employee or self.env.is_admin()):
                raise UserError('Only the assigned employee can accept this Tier 3 Appraisal.')
            rec.sudo().write({'state': 'accepted'})
            
            manager = rec.manager_id or rec.employee_id.parent_id or rec.employee_id.coach_id
            mgr_user = manager.user_id if manager else False
            mgr_partner = mgr_user.partner_id if mgr_user else False
            partner_ids = [mgr_partner.id] if mgr_partner else []

            period_name = rec.appraisal_period_id.name if rec.appraisal_period_id else ''
            fy_name = rec.fiscal_year_id.name if rec.fiscal_year_id else ''
            emp_name = rec.employee_id.name if rec.employee_id else 'Employee'
            manager_name = manager.name if manager else 'Manager'
            score = rec.employee_score or 0.0
            rating = rec.performance_rating or 'Not Rated'
            doc_name = rec.name or f"Appraisal - {emp_name}"

            try:
                rec.activity_feedback(['mail.mail_activity_data_todo'], feedback="Tier 3 Appraisal accepted by employee.")
            except Exception:
                pass

            details = [
                ("Document Name", f"<strong>{doc_name}</strong>"),
                ("Employee", f"<strong>{emp_name}</strong>"),
                ("Appraisal Period", f"{period_name} ({fy_name})"),
                ("Accepted Score", f'<span style="font-weight: bold; color: #166534; font-size: 14px;">{score:.2f}%</span>'),
                ("Performance Rating", f'<span style="font-weight: bold; color: #2b6cb0;">{rating}</span>'),
                ("Current Status", '<span style="background-color: #dcfce7; color: #166534; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">ACCEPTED</span>'),
            ]

            send_performance_notification(
                record=rec,
                title="🎉 Performance Appraisal Accepted",
                badge_text="ACCEPTED",
                badge_bg="#28a745",
                border_color="#28a745",
                intro_text=f"Employee <strong>{emp_name}</strong> has reviewed and <strong>ACCEPTED</strong> their evaluated Tier 3 Appraisal (Score: <strong>{score:.2f}%</strong>, Rating: <strong>{rating}</strong>) for period <strong>{period_name}</strong> ({fy_name}).",
                details=details,
                action_btn_text="🎯 Open & Confirm Appraisal",
                action_btn_color="#166534",
                footer_note=f"Manager <b>{manager_name}</b>, please confirm this appraisal to finalize the performance evaluation cycle.",
                recipient_partner_ids=partner_ids,
                activity_user_id=mgr_user.id if mgr_user else False,
                activity_summary=f"Appraisal Accepted by {emp_name} ({score:.2f}%) - Action: Confirm",
            )

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
            
            invalid_lines = rec.line_ids.filtered(lambda l: l.appraised == 'yes' and (l.uploaded_value or 0.0) <= 0.0)
            if invalid_lines:
                measure_names = ", ".join(invalid_lines.mapped(lambda l: l.job_measure_id.name or 'KPI Measure'))
                raise UserError(
                    f"Tier 3 Appraisal for '{rec.employee_id.name}' cannot be confirmed because some appraised measures have 0 or missing uploaded values:\n- {measure_names}"
                )
            
            invalid_percent_lines = rec.line_ids.filtered(
                lambda l: (l.appraisal_type or '').lower() in ('percent', 'percentage') and (l.uploaded_value or 0.0) > 100.0
            )
            if invalid_percent_lines:
                measure_names = ", ".join(invalid_percent_lines.mapped(lambda l: f"{l.job_measure_id.name or 'KPI Measure'} ({l.uploaded_value}%)"))
                raise UserError(
                    f"Tier 3 Appraisal for '{rec.employee_id.name}' cannot be confirmed because some percentage-based measures exceed 100%:\n- {measure_names}"
                )
            
            rec.write({'state': 'confirmed'})
            
            emp = rec.employee_id
            emp_user = emp.user_id if emp else False
            emp_partner = emp_user.partner_id if emp_user else False
            partner_ids = [emp_partner.id] if emp_partner else []

            period_name = rec.appraisal_period_id.name if rec.appraisal_period_id else ''
            fy_name = rec.fiscal_year_id.name if rec.fiscal_year_id else ''
            emp_name = emp.name if emp else 'Employee'
            manager_name = (rec.manager_id.name if rec.manager_id else (self.env.user.name or 'Manager'))
            score = rec.employee_score or 0.0
            rating = rec.performance_rating or 'Not Rated'
            doc_name = rec.name or f"Appraisal - {emp_name}"

            try:
                rec.activity_feedback(['mail.mail_activity_data_todo'], feedback="Tier 3 Appraisal confirmed by manager.")
            except Exception:
                pass

            details = [
                ("Document Name", f"<strong>{doc_name}</strong>"),
                ("Employee", f"<strong>{emp_name}</strong>"),
                ("Manager", manager_name),
                ("Appraisal Period", f"{period_name} ({fy_name})"),
                ("Final Confirmed Score", f'<span style="font-weight: bold; color: #425727; font-size: 14px;">{score:.2f}%</span>'),
                ("Final Performance Rating", f'<span style="font-weight: bold; color: #2b6cb0;">{rating}</span>'),
            ]
            if hasattr(rec, 'work_unit_score') and (rec.work_unit_score or 0.0) > 0.0:
                details.append(("Work Unit Score", f'<span style="font-weight: bold; color: #425727;">{rec.work_unit_score:.2f}%</span>'))
            details.append(("Current Status", '<span style="background-color: #dbeafe; color: #1e40af; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 11px;">CONFIRMED</span>'))

            send_performance_notification(
                record=rec,
                title="🔒 Performance Appraisal Confirmed & Finalized",
                badge_text="CONFIRMED",
                badge_bg="#425727",
                border_color="#425727",
                intro_text=f"Manager <strong>{manager_name}</strong> has <strong>CONFIRMED &amp; FINALIZED</strong> the Tier 3 Appraisal for <strong>{emp_name}</strong> for period <strong>{period_name}</strong> ({fy_name}). Final Score: <strong>{score:.2f}%</strong> | Rating: <strong>{rating}</strong>.",
                details=details,
                action_btn_text="🎯 View Confirmed Appraisal",
                action_btn_color="#425727",
                footer_note="Appraisal cycle concluded and recorded in employee performance history.",
                recipient_partner_ids=partner_ids,
            )

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
                if app.is_current_employee and not (app.is_current_manager or app.is_hr_role or app.is_admin_role or self.env.is_admin()):
                    raise UserError('Employees are not permitted to edit appraisal lines.')
                if 'uploaded_value' in vals and app.state != 'draft':
                    raise UserError('Uploaded Value can only be edited when the Appraisal is in Draft state.')
        return super().write(vals)
