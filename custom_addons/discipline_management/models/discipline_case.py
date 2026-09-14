# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import timedelta


class DisciplineCase(models.Model):
    _name = 'discipline.case'
    _description = 'Disciplinary Case Record'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'incident_date desc, id desc'

    name = fields.Char(string='Case Reference', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, tracking=True)
    department_id = fields.Many2one('hr.department', string='Department', related='employee_id.department_id', store=True, readonly=True)
    job_id = fields.Many2one('hr.job', string='Job Position', related='employee_id.job_id', store=True, readonly=True)
    work_location_id = fields.Many2one('hr.work.location', string='Work Location', related='employee_id.work_location_id', store=True, readonly=True)
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)

    offense_id = fields.Many2one('discipline.offense', string='Offense Type', required=True, tracking=True)
    offense_category_id = fields.Many2one('discipline.offense.category', string='Offense Category', related='offense_id.category_id', store=True, readonly=True)
    severity_level_id = fields.Many2one('discipline.severity.level', string='Severity Level', required=True, tracking=True)
    severity_level = fields.Char(string='Severity Code', related='severity_level_id.code', store=True, readonly=True)
    punishment_type = fields.Selection([
        ('dismissal', 'Dismissal / Separation'),
        ('demotion', 'Demotion to Lower Grade / Position'),
        ('final_warning_penalty', 'Final Warning + Penalty'),
        ('second_warning_penalty', 'Second Warning + Penalty'),
        ('first_warning_penalty', 'First Warning + Penalty'),
        ('verbal_warning', 'Recorded Verbal Warning'),
        ('custom', 'Custom Administrative Action'),
    ], string='Applicable Punishment', compute='_compute_punishment_details', store=True, readonly=True, tracking=True)

    original_punishment_type = fields.Selection([
        ('dismissal', 'Dismissal / Separation'),
        ('demotion', 'Demotion to Lower Grade / Position'),
        ('final_warning_penalty', 'Final Warning + Penalty'),
        ('second_warning_penalty', 'Second Warning + Penalty'),
        ('first_warning_penalty', 'First Warning + Penalty'),
        ('verbal_warning', 'Recorded Verbal Warning'),
        ('custom', 'Custom Administrative Action'),
    ], string='Original Standard Punishment', compute='_compute_punishment_details', store=True, readonly=True)

    original_penalty_percentage = fields.Float(string='Original Penalty Percentage (%)', compute='_compute_punishment_details', store=True, readonly=True)
    original_fine_days = fields.Float(string='Original Salary Fine (Days)', compute='_compute_punishment_details', store=True, readonly=True)

    decided_punishment_type = fields.Selection([
        ('dismissal', 'Dismissal / Separation'),
        ('demotion', 'Demotion to Lower Grade / Position'),
        ('final_warning_penalty', 'Final Warning + Penalty'),
        ('second_warning_penalty', 'Second Warning + Penalty'),
        ('first_warning_penalty', 'First Warning + Penalty'),
        ('verbal_warning', 'Recorded Verbal Warning'),
        ('custom', 'Custom Administrative Action'),
    ], string='Final Committee Decided Punishment', tracking=True)

    decided_penalty_percentage = fields.Float(string='Final Decided Penalty (%)', tracking=True)
    decided_fine_days = fields.Float(string='Final Decided Salary Fine (Days)', tracking=True)
    is_punishment_modified_by_committee = fields.Boolean(string='Punishment Modified by Committee', compute='_compute_is_punishment_modified', store=True)

    @api.depends('original_punishment_type', 'punishment_type', 'original_penalty_percentage', 'penalty_percentage', 'original_fine_days', 'fine_days')
    def _compute_is_punishment_modified(self):
        for rec in self:
            rec.is_punishment_modified_by_committee = (
                (rec.punishment_type and rec.original_punishment_type and rec.punishment_type != rec.original_punishment_type) or
                (rec.penalty_percentage != rec.original_penalty_percentage) or
                (rec.fine_days != rec.original_fine_days)
            )

    @api.depends('severity_level_id', 'offense_id', 'employee_id')
    def _compute_punishment_details(self):
        for rec in self:
            if rec.severity_level_id:
                emp = rec.employee_id
                job_name = (emp.job_id.name or '').lower() if emp and emp.job_id else ''
                is_managerial = getattr(emp, 'is_managerial', False) or any(kw in job_name for kw in ['manager', 'director', 'chief', 'head', 'vp', 'supervisor'])

                matching_line = False
                if rec.offense_id and rec.offense_id.line_ids:
                    matching_line = rec.offense_id.line_ids.filtered(lambda l: l.severity_level_id == rec.severity_level_id)

                if matching_line:
                    line = matching_line[0]
                    punish = line.punishment_type
                    if line.approval_authority and line.approval_authority in ['cpco', 'ceo']:
                        rec.required_final_authority = line.approval_authority
                    pct = line.managerial_penalty_pct if is_managerial else line.non_managerial_penalty_pct
                    days = line.managerial_fine_days if is_managerial else line.non_managerial_fine_days
                else:
                    lvl = rec.severity_level_id
                    punish = lvl.default_punishment_type
                    if lvl.default_approval_authority and lvl.default_approval_authority in ['cpco', 'ceo']:
                        rec.required_final_authority = lvl.default_approval_authority
                    pct = (getattr(lvl, 'default_managerial_penalty_pct', 0.0) if is_managerial else getattr(lvl, 'default_non_managerial_penalty_pct', 0.0)) or getattr(lvl, 'default_penalty_percentage', 0.0)
                    days = (getattr(lvl, 'default_managerial_fine_days', 0.0) if is_managerial else getattr(lvl, 'default_non_managerial_fine_days', 0.0)) or getattr(lvl, 'default_fine_days', 0.0)

                rec.original_punishment_type = punish
                rec.original_penalty_percentage = pct
                rec.original_fine_days = days

                rec.punishment_type = rec.decided_punishment_type or punish
                rec.penalty_percentage = rec.decided_penalty_percentage if rec.decided_penalty_percentage > 0 else pct
                rec.fine_days = rec.decided_fine_days if rec.decided_fine_days > 0 else days
            else:
                rec.original_punishment_type = False
                rec.original_penalty_percentage = 0.0
                rec.original_fine_days = 0.0
                rec.punishment_type = False
                rec.penalty_percentage = 0.0
                rec.fine_days = 0.0

    @api.onchange('severity_level_id', 'offense_id', 'employee_id')
    def _onchange_offense_severity_resolve_rules(self):
        """Re-trigger rule resolution immediately when severity level, offense, or employee changes."""
        self._compute_punishment_details()

    penalty_percentage = fields.Float(string='Penalty Percentage (%)', compute='_compute_punishment_details', store=True, readonly=True, tracking=True)
    fine_days = fields.Float(string='Salary Fine (Days)', compute='_compute_punishment_details', store=True, readonly=True, tracking=True)
    property_repair_cost = fields.Float(string='Property Repair / Replacement Cost (ETB)', tracking=True)
    is_managerial = fields.Boolean(string='Is Managerial Employee', related='employee_id.is_managerial', store=True, readonly=True)
    staff_category_display = fields.Char(string='Staff Category', compute='_compute_staff_category_display', store=True)

    def _default_initiator_type(self):
        user = self.env.user
        has_audit_group = user.has_group('discipline_management.group_discipline_auditor')
        user_dept_name = (user.employee_id.department_id.name or '').lower() if user.employee_id and user.employee_id.department_id else ''
        is_audit = has_audit_group or ('audit' in user_dept_name or 'compliance' in user_dept_name)
        return 'audit' if is_audit else 'manager'

    initiator_type = fields.Selection([
        ('manager', 'Coach / Line Manager'),
        ('director', 'Directorate Director'),
        ('audit', 'Internal Audit / Compliance'),
    ], string='Case Initiator Source', default=_default_initiator_type, store=True, readonly=False, tracking=True)

    chief_id = fields.Many2one('res.users', string='Respective Chief Officer', tracking=True)
    escalation_target = fields.Selection([
        ('audit', 'Audit Directorate'),
        ('ceo', 'Chief Executive Officer (CEO)'),
    ], string='Chief Escalation Target', tracking=True)
    ceo_assignment_notes = fields.Text(string='CEO Assignment Remarks', tracking=True)
    delivery_receipt_date = fields.Date(string='Decision Letter Delivery / Receipt Date', tracking=True)

    active_duration_days = fields.Integer(string='Penalty Active Duration (Days)', related='severity_level_id.active_duration_days', store=True, readonly=True)
    active_penalty_end_date = fields.Date(string='Penalty Active Expiration Date', compute='_compute_active_penalty_end_date', store=True, tracking=True)

    @api.depends('final_decision_date', 'active_duration_days', 'state')
    def _compute_active_penalty_end_date(self):
        for rec in self:
            if rec.final_decision_date and rec.state == 'enforced':
                rec.active_penalty_end_date = rec.final_decision_date + timedelta(days=rec.active_duration_days or 365)
            else:
                rec.active_penalty_end_date = False

    is_coach_or_manager = fields.Boolean(string='Is Coach or Line Manager', compute='_compute_is_coach_or_manager')

    def _compute_is_coach_or_manager(self):
        current_emp = self.env.user.employee_id
        for rec in self:
            if not current_emp or not rec.employee_id:
                rec.is_coach_or_manager = False
                continue
            is_sub = (
                rec.employee_id.parent_id.id == current_emp.id or
                rec.employee_id.coach_id.id == current_emp.id or
                rec.employee_id.id in self.env['hr.employee'].search([('id', 'child_of', current_emp.id)]).ids
            )
            rec.is_coach_or_manager = is_sub or self.env.user.has_group('discipline_management.group_discipline_manager') or self.env.user.has_group('discipline_management.group_discipline_admin')

    allowed_severity_level_ids = fields.Many2many(
        'discipline.severity.level',
        compute='_compute_allowed_severity_level_ids',
        string='Allowed Severity Levels'
    )

    subordinate_employee_ids = fields.Many2many(
        'hr.employee',
        compute='_compute_subordinate_employee_ids',
        string='Subordinate Employees'
    )

    @api.depends('reported_by_id', 'create_uid')
    def _compute_subordinate_employee_ids(self):
        for rec in self:
            reporter = rec.reported_by_id or self.env.user.employee_id
            if reporter:
                subs = self.env['hr.employee'].search([
                    '|',
                    ('id', 'child_of', reporter.id),
                    ('coach_id', '=', reporter.id)
                ])
                rec.subordinate_employee_ids = subs
            else:
                rec.subordinate_employee_ids = self.env['hr.employee'].search([])

    @api.depends('offense_id', 'offense_id.line_ids')
    def _compute_allowed_severity_level_ids(self):
        all_levels = self.env['discipline.severity.level'].search([])
        for rec in self:
            if rec.offense_id and rec.offense_id.line_ids:
                rec.allowed_severity_level_ids = rec.offense_id.line_ids.mapped('severity_level_id')
            else:
                rec.allowed_severity_level_ids = all_levels

    @api.depends('employee_id', 'employee_id.is_managerial')
    def _compute_staff_category_display(self):
        for rec in self:
            if rec.employee_id:
                rec.staff_category_display = _('Managerial Staff') if rec.employee_id.is_managerial else _('Non-Managerial Staff')
            else:
                rec.staff_category_display = _('Non-Managerial Staff')

    # Demotion fields
    new_job_id = fields.Many2one('hr.job', string='Demotion Target Job Position', tracking=True)
    new_grade_id = fields.Char(string='Demotion Target Grade Scale', tracking=True)

    # Automatic routing & authority
    required_final_authority = fields.Selection([
        ('direct_manager', 'Coach / Line Manager'),
        ('cpco', 'Chief People Officer (CPCO)'),
        ('ceo', 'Chief Executive Officer (CEO)'),
    ], string='Required Final Approval Authority', compute='_compute_required_final_authority', store=True, tracking=True)

    incident_date = fields.Date(string='Incident Date', required=True, default=fields.Date.context_today, tracking=True)
    description = fields.Text(string='Detailed Description of Misconduct', required=True)
    is_system_generated = fields.Boolean(string='System Generated', default=False, readonly=True)
    is_locked_for_committee = fields.Boolean(string='Locked for Committee Review', default=False, tracking=True)

    # Workflow Roles (Segregation of Duties)
    initiator_id = fields.Many2one('res.users', string='Initiator', default=lambda self: self.env.user, readonly=True, tracking=True)
    reviewer_id = fields.Many2one('res.users', string='Reviewer / Investigator', tracking=True)
    approver_id = fields.Many2one('res.users', string='Final Approver', tracking=True)

    def _default_reported_by_id(self):
        return self.env.user.employee_id or self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)

    reported_by_id = fields.Many2one(
        'hr.employee', 
        string='Reported By', 
        default=_default_reported_by_id,
        readonly=True
    )
    
    reference = fields.Char(string='Reference')
    # State Machine
    state = fields.Selection([
        ('draft', 'Draft'),
        ('initiated', 'Initiated'),
        ('submitted_chief', 'Submitted to Respective Chief'),
        ('ceo_review', 'Under CEO Review'),
        ('investigating', 'Under Audit Investigation'),
        ('committee_review', 'Committee Review'),
        ('pending_approval', 'Pending Final Approval'),
        ('enforced', 'Enforced / Finalized'),
        ('appealed', 'Appealed'),
        ('revoked', 'Revoked'),
        ('closed', 'Closed'),
    ], string='Status', default='draft', required=True, tracking=True)

    # SLA Tracking
    sla_deadline = fields.Date(string='SLA Resolution Deadline', compute='_compute_sla_deadline', store=True)
    is_sla_exceeded = fields.Boolean(string='SLA Breached', compute='_compute_is_sla_exceeded', store=True, tracking=True)
    sla_target_days = fields.Integer(string='SLA Target (Days)', default=7, help='Target resolution days per policy')

    # Associated Records
    investigation_ids = fields.One2many('discipline.investigation', 'case_id', string='Investigations')
    committee_meeting_ids = fields.One2many('discipline.committee.meeting', 'case_id', string='Committee Meetings')
    suspension_ids = fields.One2many('discipline.suspension', 'case_id', string='Suspensions')
    appeal_ids = fields.One2many('discipline.appeal', 'case_id', string='Appeals')
    payroll_penalty_ids = fields.One2many('discipline.payroll.penalty', 'case_id', string='Payroll Penalties')

    # Flags & Decision Summary
    final_decision_date = fields.Date(string='Final Decision Date', readonly=True, tracking=True)
    decision_summary = fields.Text(string='Final Decision Summary', tracking=True)
    appeal_deadline = fields.Date(string='Appeal Deadline', compute='_compute_appeal_deadline', store=True, tracking=True)
    is_appeal_window_open = fields.Boolean(string='Appeal Window Open', compute='_compute_is_appeal_window_open')
    
    # Revocation Data
    is_revoked = fields.Boolean(string='Is Revoked', default=False, readonly=True, tracking=True)
    revocation_reason = fields.Text(string='Revocation Justification', readonly=True, tracking=True)
    revoked_by_id = fields.Many2one('res.users', string='Revoked By', readonly=True, tracking=True)
    revocation_date = fields.Date(string='Revocation Date', readonly=True, tracking=True)

    # CEO/CPCO authority split — stores who authorised the dismissal
    dismissal_authority_id = fields.Many2one(
        'res.users',
        string='Dismissal Authority (CEO/CPCO)',
        tracking=True,
        help='For Level 1 Dismissals and executive cases, records the CEO or CPCO who provided final authority.'
    )

    # Computed counts for smart buttons
    appeal_count = fields.Integer(string='Appeal Count', compute='_compute_appeal_count')
    suspension_count = fields.Integer(string='Suspension Count', compute='_compute_suspension_count')

    @api.depends('employee_id', 'employee_id.job_id', 'severity_level', 'punishment_type')
    def _compute_required_final_authority(self):
        for rec in self:
            job_name = (rec.employee_id.job_id.name or '').lower() if rec.employee_id and rec.employee_id.job_id else ''
            is_executive = any(kw in job_name for kw in ['manager', 'director', 'chief', 'vp', 'executive', 'head'])
            if is_executive or rec.severity_level == 'level_1' or rec.punishment_type == 'dismissal':
                rec.required_final_authority = 'ceo'
            else:
                rec.required_final_authority = 'cpco'

    def _compute_appeal_count(self):
        for rec in self:
            rec.appeal_count = len(rec.appeal_ids)

    def _compute_suspension_count(self):
        for rec in self:
            rec.suspension_count = len(rec.suspension_ids)

    @api.depends('create_date', 'incident_date', 'sla_target_days')
    def _compute_sla_deadline(self):
        for rec in self:
            if rec.create_date:
                base_date = rec.create_date.date()
            elif rec.incident_date:
                base_date = rec.incident_date
            else:
                base_date = fields.Date.context_today(self)
            rec.sla_deadline = base_date + timedelta(days=rec.sla_target_days or 7)

    @api.depends('sla_deadline', 'state')
    def _compute_is_sla_exceeded(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.state not in ['enforced', 'closed', 'revoked'] and rec.sla_deadline and today > rec.sla_deadline:
                rec.is_sla_exceeded = True
            else:
                rec.is_sla_exceeded = False

    @api.depends('final_decision_date')
    def _compute_appeal_deadline(self):
        for rec in self:
            if rec.final_decision_date:
                rec.appeal_deadline = rec.final_decision_date + timedelta(days=10)
            else:
                rec.appeal_deadline = False

    @api.depends('appeal_deadline', 'state')
    def _compute_is_appeal_window_open(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.state == 'enforced' and rec.appeal_deadline and today <= rec.appeal_deadline:
                rec.is_appeal_window_open = True
            else:
                rec.is_appeal_window_open = False

    is_hr_admin = fields.Boolean(compute='_compute_is_hr_admin', string='Is HR Admin User')

    def _compute_is_hr_admin(self):
        is_admin = self.env.user.has_group('discipline_management.group_discipline_admin') or self.env.user.has_group('base.group_system')
        for rec in self:
            rec.is_hr_admin = is_admin

    is_current_user_employee = fields.Boolean(
        string='Is Current User Subject Employee',
        compute='_compute_current_user_roles'
    )
    can_submit_appeal = fields.Boolean(
        string='Can Submit Appeal',
        compute='_compute_current_user_roles'
    )
    can_lodge_appeal_on_behalf = fields.Boolean(
        string='Can Lodge Appeal On Behalf',
        compute='_compute_current_user_roles'
    )
    is_pomd_user = fields.Boolean(
        string='Is POMD User',
        compute='_compute_current_user_roles'
    )

    def _compute_current_user_roles(self):
        current_user = self.env.user
        is_pomd = current_user.has_group('discipline_management.group_discipline_pomd') or current_user.has_group('discipline_management.group_discipline_admin')
        for rec in self:
            rec.is_pomd_user = is_pomd

            # Check if current user is the employee under this case
            is_emp = bool(
                rec.employee_id and (
                    (rec.employee_id.user_id and rec.employee_id.user_id.id == current_user.id) or
                    (current_user.employee_id and current_user.employee_id.id == rec.employee_id.id) or
                    (hasattr(current_user, 'employee_ids') and rec.employee_id.id in current_user.employee_ids.ids)
                )
            )
            rec.is_current_user_employee = is_emp

            has_pending_appeal = bool(rec.appeal_ids.filtered(lambda a: a.state in ['submitted', 'under_review']))

            # Direct Appeal: ONLY visible for the subject employee, when appeal window is open, in enforced state, and no pending appeal
            rec.can_submit_appeal = is_emp and rec.is_appeal_window_open and not has_pending_appeal and rec.state == 'enforced'

            # On-Behalf Appeal: ONLY visible for POMD Director / Admin, when enforcement is dismissal AND employee is inactive
            is_dismissal = rec.severity_level == 'level_1' or rec.punishment_type == 'dismissal'
            is_emp_inactive = bool(
                rec.employee_id and (
                    not rec.employee_id.active or
                    (rec.employee_id.user_id and not rec.employee_id.user_id.active)
                )
            )
            rec.can_lodge_appeal_on_behalf = (
                is_pomd and
                is_dismissal and
                is_emp_inactive and
                rec.state in ('enforced', 'closed') and
                rec.is_appeal_window_open and
                not has_pending_appeal
            )

    @api.onchange('reported_by_id', 'employee_id', 'initiator_type')
    def _onchange_employee_id(self):
        self.reviewer_id = False
        if self.initiator_type == 'manager':
            # Approver is inferred from the REPORTER (the Line Manager initiating the case), NOT the employee under case!
            reporter_emp = self.reported_by_id or self.env.user.employee_id
            if reporter_emp:
                dept_mgr = reporter_emp.department_id.manager_id.user_id if reporter_emp.department_id and reporter_emp.department_id.manager_id else False
                if dept_mgr and dept_mgr != self.env.user:
                    self.approver_id = dept_mgr
                elif reporter_emp.parent_id and reporter_emp.parent_id.user_id and reporter_emp.parent_id.user_id != self.env.user:
                    self.approver_id = reporter_emp.parent_id.user_id
                else:
                    # Fallback to HR Manager / CPCO if the reporter is already the Department Director
                    hr_mgr = self.env['res.users'].search([('name', 'ilike', 'Marta Bekele')], limit=1)
                    self.approver_id = hr_mgr or self.env.user
            else:
                self.approver_id = False
        else:
            self.approver_id = False

        if self.severity_level_id:
            self._onchange_offense_severity_resolve_rules()

    @api.constrains('employee_id', 'incident_date', 'offense_id')
    def _check_duplicate_case(self):
        for rec in self:
            duplicate = self.search([
                ('id', '!=', rec.id),
                ('employee_id', '=', rec.employee_id.id),
                ('incident_date', '=', rec.incident_date),
                ('offense_id', '=', rec.offense_id.id),
                ('state', '!=', 'revoked')
            ])
            if duplicate:
                raise ValidationError(_(
                    'Duplicate Case Prevention: A disciplinary case already exists for Employee %s '
                    'on incident date %s for offense "%s" (Case Reference: %s).'
                ) % (rec.employee_id.name, rec.incident_date, rec.offense_id.name, duplicate[0].name))

            if rec.offense_id and rec.severity_level:
                same_severity = self.search([
                    ('id', '!=', rec.id),
                    ('employee_id', '=', rec.employee_id.id),
                    ('incident_date', '=', rec.incident_date),
                    ('severity_level', '=', rec.severity_level),
                    ('state', 'not in', ['revoked', 'closed']),
                ])
                if same_severity:
                    raise ValidationError(_(
                        'Duplicate Severity Prevention: Employee %s already has an open %s case '
                        'on incident date %s (Case Ref: %s). Consolidate into the existing case instead.'
                    ) % (rec.employee_id.name, rec.severity_level_id.name if rec.severity_level_id else (rec.severity_level or ''),
                         rec.incident_date, same_severity[0].name))

    def _validate_segregation_of_duties(self):
        for rec in self:
            current_user = self.env.user
            # Coach / Line Manager direct enforcement on subordinates for Levels 2-5 is permitted
            is_direct_mgr_enforcement = (
                rec.initiator_type == 'manager' and
                rec.severity_level != 'level_1' and
                rec.punishment_type != 'dismissal'
            )
            if not is_direct_mgr_enforcement:
                if rec.initiator_id and rec.reviewer_id and rec.initiator_id == rec.reviewer_id:
                    raise ValidationError(_('Segregation of Duties Violation: Case Initiator and Reviewer must be different individuals.'))
                if rec.initiator_id and rec.approver_id and rec.initiator_id == rec.approver_id and rec.initiator_type != 'manager':
                    raise ValidationError(_('Segregation of Duties Violation: Case Initiator and Approver must be different individuals for escalated cases.'))
                if rec.reviewer_id and rec.approver_id and rec.reviewer_id == rec.approver_id:
                    raise ValidationError(_('Segregation of Duties Violation: Case Reviewer and Approver must be different individuals.'))

            if rec.severity_level == 'level_1' or rec.punishment_type == 'dismissal':
                if not current_user.has_group('discipline_management.group_discipline_admin') and not current_user.has_group('discipline_management.group_discipline_ceo'):
                    raise ValidationError(_(
                        'Approval Restriction: Decisions requiring Dismissal / Separation are restricted '
                        'exclusively to authorized executive approvers (CEO / Disciplinary Committee).'
                    ))
                if not rec.dismissal_authority_id:
                    rec.dismissal_authority_id = current_user

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('discipline.case') or _('New')
        cases = super().create(vals_list)
        return cases

    def write(self, vals):
        force_write = self.env.context.get('force_write')
        if not force_write:
            whitelisted_fields = {'state', 'revocation_reason', 'revocation_date', 'revoked_by_id', 'is_revoked', 'message_follower_ids', 'message_ids', 'activity_ids', 'is_locked_for_committee', 'approver_id', 'final_decision_date', 'delivery_receipt_date', 'chief_id', 'escalation_target', 'ceo_assignment_notes'}
            for rec in self:
                if rec.state in ('enforced', 'closed', 'appealed'):
                    if set(vals.keys()) - whitelisted_fields:
                        raise UserError(_('Enforced, closed, or appealed disciplinary cases are immutable and cannot be edited. Use formal revocation if required.'))
                if rec.is_locked_for_committee:
                    if set(vals.keys()) - whitelisted_fields:
                        raise UserError(_('Case %s is currently locked for committee review and cannot be edited.') % rec.name)
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.state in ['enforced', 'closed', 'appealed']:
                raise UserError(_('Preservation Policy Violation: Enforced or finalized disciplinary records cannot be deleted. Use formal Revocation if required.'))
        return super().unlink()

    def action_initiate(self):
        for rec in self:
            if not rec.description:
                raise UserError(_('Detailed Description is mandatory before initiating a case.'))
            rec.with_context(force_write=True).write({'state': 'initiated'})
            rec.message_post(body=_('Disciplinary case initiated for employee %s.') % rec.employee_id.name)

    def action_submit_to_chief(self):
        """Submit the initiated disciplinary case to the respective Chief Officer for review and escalation routing."""
        for rec in self:
            if not rec.chief_id:
                # Resolve chief user from group if not explicitly set
                chief_group = self.env.ref('discipline_management.group_discipline_chief', raise_if_not_found=False)
                if chief_group and chief_group.users:
                    rec.chief_id = chief_group.users[0]
            rec.with_context(force_write=True).write({'state': 'submitted_chief'})
            rec.message_post(body=_('Case submitted to Respective Chief (%s) for review.') % (rec.chief_id.name if rec.chief_id else 'Chief Officer'))

    def action_chief_escalate_to_audit(self):
        """Escalate the case to the Audit Directorate for investigation, notifying the CEO simultaneously."""
        for rec in self:
            rec.escalation_target = 'audit'
            rec.with_context(force_write=True).write({'state': 'investigating'})
            rec.message_post(body=_('Chief reviewed case and escalated to Audit Directorate for investigation.'))
            
            # Send informational activity notification to executive management
            ceo_group = self.env.ref('discipline_management.group_discipline_ceo', raise_if_not_found=False)
            ceo_users = ceo_group.users if ceo_group else self.env['res.users']
            for ceo in ceo_users:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('CEO Notification: Chief Escalated Disciplinary Case %s') % rec.name,
                    note=_('Disciplinary Case %s for employee %s was escalated by Chief to Audit Directorate for investigation.') % (rec.name, rec.employee_id.name),
                    user_id=ceo.id
                )

    def action_chief_escalate_to_ceo(self):
        """Escalate the case directly to the Chief Executive Officer for review."""
        for rec in self:
            rec.escalation_target = 'ceo'
            rec.with_context(force_write=True).write({'state': 'ceo_review'})
            rec.message_post(body=_('Chief escalated case directly to CEO for executive review.'))
            
            ceo_group = self.env.ref('discipline_management.group_discipline_ceo', raise_if_not_found=False)
            ceo_users = ceo_group.users if ceo_group else self.env['res.users']
            for ceo in ceo_users:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('Executive Review Required: Disciplinary Case %s') % rec.name,
                    note=_('Disciplinary Case %s has been submitted by Chief for CEO review and assignment.') % rec.name,
                    user_id=ceo.id
                )

    def action_ceo_assign_to_audit(self):
        """Assign the case to the Audit Directorate for formal investigation with CEO directives."""
        for rec in self:
            rec.with_context(force_write=True).write({'state': 'investigating'})
            rec.message_post(body=_('CEO reviewed case and assigned to Audit Directorate for investigation. Remarks: %s') % (rec.ceo_assignment_notes or 'None'))

    def action_start_investigation(self):
        for rec in self:
            rec.reviewer_id = self.env.user
            rec.with_context(force_write=True).write({'state': 'investigating'})
            rec.message_post(body=_('Investigation process started by %s.') % self.env.user.name)

    def action_send_to_committee(self):
        for rec in self:
            rec.with_context(force_write=True).write({'state': 'committee_review', 'is_locked_for_committee': True})
            rec.message_post(body=_('Case submitted for Disciplinary Committee Review and locked for feedback.'))

    def action_committee_feedback_received(self):
        """Unlock case when committee feedback is received and notify HR officer."""
        for rec in self:
            rec.with_context(force_write=True).write({'is_locked_for_committee': False})
            rec.message_post(body=_('Committee feedback received. Case unlocked for review.'))
            target_user = rec.reviewer_id or rec.initiator_id or rec.create_uid
            if target_user:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('Committee Feedback Received: Case %s') % rec.name,
                    note=_('Disciplinary Committee feedback is ready for your review.'),
                    user_id=target_user.id
                )

    def action_submit_for_approval(self):
        for rec in self:
            rec.with_context(force_write=True).write({'state': 'pending_approval'})
            rec.message_post(body=_('Case submitted for final approval.'))

    def action_return_revision(self):
        """Return case to Initiator / Line Manager for revision."""
        for rec in self:
            if rec.state not in ['pending_approval', 'submitted_chief', 'ceo_review']:
                raise UserError(_('Only cases under review/pending approval can be returned for revision.'))
            rec.with_context(force_write=True).write({'state': 'draft'})
            rec.message_post(body=_('Case returned to Initiator for revision by %s.') % self.env.user.name)

    def action_reject(self):
        """Reject disciplinary case."""
        for rec in self:
            if rec.state not in ['pending_approval', 'initiated', 'investigating', 'submitted_chief', 'ceo_review']:
                raise UserError(_('Case cannot be rejected in its current state.'))
            rec.with_context(force_write=True).write({'state': 'closed'})
            rec.message_post(body=_('Disciplinary case rejected and closed by %s.') % self.env.user.name)

    def action_acknowledge_receipt(self):
        """Record official delivery and acknowledgment of the disciplinary notice, starting the appeal window."""
        for rec in self:
            rec.delivery_receipt_date = fields.Date.context_today(self)
            rec.message_post(body=_('Disciplinary decision letter delivery acknowledged on %s. 10-day appeal countdown is active.') % rec.delivery_receipt_date)

    def action_approve_and_enforce(self):
        """Enforces the disciplinary penalty (Coach/Manager direct enforcement for Levels 2-5, or Committee/Executive enforcement)."""
        for rec in self:
            current_user = self.env.user
            # Coach / Manager direct enforcement validation
            if rec.initiator_type == 'manager' and (rec.severity_level == 'level_1' or rec.punishment_type == 'dismissal'):
                if not current_user.has_group('discipline_management.group_discipline_admin') and not current_user.has_group('discipline_management.group_discipline_ceo'):
                    raise UserError(_(
                        'Dismissal Authority Restriction: Level 1 Dismissal cannot be directly enforced by a Coach or Line Manager. '
                        'Please escalate through the Chief / Executive Committee route.'
                    ))

            rec.approver_id = current_user
            rec._validate_segregation_of_duties()

            # Verify linked committee meetings are completed with quorum and signoff (only if committee route)
            if rec.initiator_type == 'audit' and rec.committee_meeting_ids:
                for meeting in rec.committee_meeting_ids:
                    if meeting.state != 'completed' or not meeting.director_signed_off or not meeting.is_quorum_met:
                        raise UserError(_('Cannot enforce case decision. Linked committee meeting (%s) must be in Completed state with director sign-off and valid quorum.') % meeting.name)

            rec.final_decision_date = fields.Date.context_today(self)
            if not rec.delivery_receipt_date:
                rec.delivery_receipt_date = rec.final_decision_date
            rec.with_context(force_write=True).write({'state': 'enforced'})

            # Update employee disciplinary record and set internal mobility restrictions
            is_ineligible = (
                rec.severity_level in ['level_1', 'level_2'] or
                rec.punishment_type in ['dismissal', 'demotion', 'final_warning_penalty']
            )
            rec.employee_id.sudo().with_context(no_leave_resource_calendar_update=True).write({
                'active_disciplinary_action': True,
                'is_ineligible_for_promotion_transfer': is_ineligible,
                'disciplinary_warning_count': rec.employee_id.disciplinary_warning_count + 1,
                'last_disciplinary_date': rec.final_decision_date,
            })

            # Demotion handling (preserves basic salary while downgrading position scale/allowances)
            if rec.punishment_type == 'demotion':
                rec.action_apply_demotion()

            # Enqueue pending deduction records for downstream payroll processing
            # 1. Percentage deduction for non-managerial employees
            if not rec.is_managerial and rec.penalty_percentage > 0.0:
                self.env['discipline.payroll.penalty'].create({
                    'case_id': rec.id,
                    'employee_id': rec.employee_id.id,
                    'penalty_type': 'percentage',
                    'penalty_percentage': rec.penalty_percentage,
                    'effective_date': rec.final_decision_date,
                    'state': 'pending',
                    'notes': _('Automatic percentage penalty of %s%% from Case %s.') % (rec.penalty_percentage, rec.name)
                })
            # 2. Daily wage unit deduction for managerial staff
            elif rec.is_managerial and rec.fine_days > 0.0:
                self.env['discipline.payroll.penalty'].create({
                    'case_id': rec.id,
                    'employee_id': rec.employee_id.id,
                    'penalty_type': 'managerial',
                    'managerial_days': int(rec.fine_days),
                    'effective_date': rec.final_decision_date,
                    'state': 'pending',
                    'notes': _('Automatic managerial penalty of %d day(s) from Case %s.') % (int(rec.fine_days), rec.name)
                })

            # Suspension without-pay deduction for active suspensions
            active_swp = rec.suspension_ids.filtered(
                lambda s: s.suspension_type == 'without_pay' and s.state in ['active', 'extended', 'completed']
            )
            for susp in active_swp:
                self.env['discipline.payroll.penalty'].create({
                    'case_id': rec.id,
                    'employee_id': rec.employee_id.id,
                    'penalty_type': 'suspension_without_pay',
                    'suspension_id': susp.id,
                    'suspension_days': susp.working_days_count,
                    'effective_date': rec.final_decision_date,
                    'state': 'pending',
                    'notes': _('Without-pay suspension deduction for %d days from Suspension %s.') % (susp.working_days_count, susp.name)
                })

            # Dismissal Handling & Separation Workflow
            if rec.severity_level == 'level_1' or rec.punishment_type == 'dismissal':
                rec.action_approve_dismissal()

            # Auto-attach the warning letter PDF
            rec._attach_warning_letter()

            rec.message_post(body=_('Disciplinary case decision approved and enforced. Warning letter auto-attached.'))

    def _attach_warning_letter(self):
        """Generate and auto-attach the warning letter PDF to chatter."""
        self.ensure_one()
        report_ref = 'discipline_management.action_report_disciplinary_warning_letter'
        try:
            report = self.env.ref(report_ref, raise_if_not_found=True)
            pdf_content, _ = self.env['ir.actions.report']._render_qweb_pdf(
                report, [self.id]
            )
            filename = 'Warning_Letter_%s.pdf' % self.name.replace('/', '_')
            attachment = self.env['ir.attachment'].create({
                'name': filename,
                'type': 'binary',
                'datas': pdf_content,
                'res_model': self._name,
                'res_id': self.id,
                'mimetype': 'application/pdf',
            })
            self.message_post(
                body=_('Warning letter attached: %s') % filename,
                attachment_ids=[attachment.id]
            )
        except Exception:
            import base64
            body_text = (
                'WARNING LETTER\n'
                '==============\n'
                'Case Reference : %s\n'
                'Employee       : %s\n'
                'Decision Date  : %s\n'
                'Offense        : %s\n'
                'Penalty        : %s%%\n\n'
                'This is a system-generated warning letter stub. '
                'Please replace with the signed copy.'
            ) % (self.name, self.employee_id.name, self.final_decision_date,
                 self.offense_id.name if self.offense_id else 'N/A', self.penalty_percentage)
            self.env['ir.attachment'].create({
                'name': 'Warning_Letter_%s.txt' % self.name.replace('/', '_'),
                'type': 'binary',
                'datas': base64.b64encode(body_text.encode('utf-8')),
                'res_model': self._name,
                'res_id': self.id,
                'mimetype': 'text/plain',
            })

    def action_apply_demotion(self):
        """Execute demotion by reassigning job position while preserving basic salary scale."""
        for rec in self:
            if rec.new_job_id:
                rec.employee_id.sudo().with_context(no_leave_resource_calendar_update=True).write({'job_id': rec.new_job_id.id})
                rec.message_post(body=_('Demotion enforced: Reassigned to position %s. Basic wage/salary scale preserved.') % rec.new_job_id.name)

    def action_approve_dismissal(self):
        """Execute final approval of Level 1 Dismissal, triggering separation and revoking system access."""
        for rec in self:
            rec._process_employee_dismissal()

    def _process_employee_dismissal(self):
        """Handle separation and access revocation with extensible hook."""
        for rec in self:
            emp = rec.employee_id
            write_vals = {'active': False}
            departure_reason = self.env.ref('hr.departure_fired', raise_if_not_found=False)
            if departure_reason and 'departure_reason_id' in emp._fields:
                write_vals['departure_reason_id'] = departure_reason.id
            if 'departure_date' in emp._fields:
                write_vals['departure_date'] = rec.final_decision_date
            if 'departure_description' in emp._fields:
                write_vals['departure_description'] = _('Dismissed under Disciplinary Case %s on %s.') % (rec.name, rec.final_decision_date)
            emp.with_context(no_leave_resource_calendar_update=True).write(write_vals)
            if emp.user_id:
                emp.user_id.sudo().write({'active': False})
                rec.message_post(body=_('System user access for user %s disabled due to dismissal.') % emp.user_id.name)
            
            rec._on_employee_dismissed(emp)

    def _on_employee_dismissed(self, employee):
        """Extensible event hook for separation management module integration."""
        Separation = self.env.get('hr.separation') or self.env.get('employee.separation')
        if Separation:
            Separation.sudo().create({
                'employee_id': employee.id,
                'separation_type': 'dismissal',
                'case_id': self.id,
                'reason': _('Disciplinary dismissal under Case %s.') % self.name,
            })

    def action_open_revocation_wizard(self):
        self.ensure_one()
        if not self.env.user.has_group('discipline_management.group_discipline_admin'):
            raise UserError(_('Revocation Authority Violation: Only HR Administrators can initiate case revocation.'))
        return {
            'name': _('Revoke Disciplinary Case'),
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.revocation.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_case_id': self.id}
        }

    def action_create_appeal(self):
        self.ensure_one()
        current_user = self.env.user
        is_emp = bool(
            (self.employee_id.user_id and self.employee_id.user_id.id == current_user.id) or
            (current_user.employee_id and current_user.employee_id.id == self.employee_id.id) or
            (hasattr(current_user, 'employee_ids') and self.employee_id.id in current_user.employee_ids.ids)
        )
        if not is_emp:
            raise UserError(_('Appeal Access Restriction: Direct appeals can only be submitted by the employee (%s) subject to this disciplinary case.') % self.employee_id.name)
        if not self.is_appeal_window_open:
            raise UserError(_(
                'Appeal Window Closed: The 10-calendar-day appeal submission window has expired. '
                'Appeal deadline was %s.'
            ) % (self.appeal_deadline or 'N/A'))
        existing_pending = self.appeal_ids.filtered(lambda a: a.state in ['submitted', 'under_review'])
        if existing_pending:
            raise UserError(_('An appeal (%s) is already pending review for this case.') % existing_pending[0].name)
        return {
            'name': _('Submit Appeal for Case %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.appeal',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_case_id': self.id,
                'default_is_submitted_on_behalf': False,
                'default_submission_date': fields.Date.context_today(self),
            }
        }

    def action_create_appeal_on_behalf(self):
        self.ensure_one()
        current_user = self.env.user
        if not current_user.has_group('discipline_management.group_discipline_pomd') and not current_user.has_group('discipline_management.group_discipline_admin'):
            raise UserError(_('Authority Restriction: Only the People Operations Management Directorate (POMD) or HR Administrator can lodge an appeal on behalf of an employee.'))
        if not (self.severity_level == 'level_1' or self.punishment_type == 'dismissal'):
            raise UserError(_('On-behalf appeals can only be lodged for Level 1 Dismissal cases.'))
        is_emp_inactive = bool(
            not self.employee_id.active or
            (self.employee_id.user_id and not self.employee_id.user_id.active)
        )
        if not is_emp_inactive:
            raise UserError(_('On-behalf appeals can only be lodged when the employee has been deactivated following a dismissal.'))
        if not self.is_appeal_window_open:
            raise UserError(_('Appeal Window Closed: The 10-calendar-day appeal submission window has expired.'))
        existing_pending = self.appeal_ids.filtered(lambda a: a.state in ['submitted', 'under_review'])
        if existing_pending:
            raise UserError(_('An appeal (%s) is already pending review for this case.') % existing_pending[0].name)
        return {
            'name': _('Lodge Appeal on Behalf of %s') % self.employee_id.name,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.appeal',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_case_id': self.id,
                'default_is_submitted_on_behalf': True,
                'default_submitted_by_id': current_user.id,
                'default_submission_date': fields.Date.context_today(self),
            }
        }

    def action_view_appeals(self):
        self.ensure_one()
        return {
            'name': _('Appeals — %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.appeal',
            'view_mode': 'list,form',
            'domain': [('case_id', '=', self.id)],
            'context': {'default_case_id': self.id},
        }

    @api.model
    def get_discipline_analytics_payload(self, date_from=None, date_to=None):
        """Public API method returning aggregated disciplinary statistics for external HR Analytics integration."""
        domain = []
        if date_from:
            domain.append(('incident_date', '>=', date_from))
        if date_to:
            domain.append(('incident_date', '<=', date_to))
            
        cases = self.search(domain)
        total_cases = len(cases)
        
        by_state = {}
        by_severity = {}
        by_department = {}
        by_punishment = {}
        
        for c in cases:
            st = c.state or 'unknown'
            by_state[st] = by_state.get(st, 0) + 1
            
            sev = c.severity_level or 'unclassified'
            by_severity[sev] = by_severity.get(sev, 0) + 1
            
            dept = c.department_id.name if c.department_id else 'Unassigned'
            by_department[dept] = by_department.get(dept, 0) + 1
            
            pish = c.punishment_type or 'none'
            by_punishment[pish] = by_punishment.get(pish, 0) + 1
            
        return {
            'total_cases': total_cases,
            'cases_by_state': by_state,
            'cases_by_severity': by_severity,
            'cases_by_department': by_department,
            'cases_by_punishment': by_punishment,
        }

    @api.model
    def _cron_check_sla_escalations(self):
        today = fields.Date.context_today(self)
        breached_cases = self.search([
            ('state', 'in', ['initiated', 'investigating', 'committee_review', 'pending_approval']),
            ('sla_deadline', '<', today),
            ('is_sla_exceeded', '=', True)
        ])
        for case in breached_cases:
            case.message_post(
                body=_('SLA BREACH ALERT: Disciplinary Case %s has exceeded its resolution SLA deadline of %s.') % (case.name, case.sla_deadline),
                message_type='notification'
            )

    @api.model
    def _cron_check_appeal_window_expiry(self):
        today = fields.Date.context_today(self)
        expired_cases = self.search([
            ('state', '=', 'enforced'),
            ('appeal_deadline', '<', today)
        ])
        for case in expired_cases:
            case.message_post(body=_('Appeal submission window of 10 calendar days has expired for Case %s.') % case.name)
