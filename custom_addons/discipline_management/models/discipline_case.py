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
    severity_level = fields.Selection(related='offense_id.severity_level', string='Severity Level', store=True, readonly=True)
    punishment_type = fields.Selection([
        ('dismissal', 'Dismissal / Separation'),
        ('demotion', 'Demotion to Lower Grade / Position'),
        ('final_warning_penalty', 'Final Written Warning + 20% Salary Deduction'),
        ('second_warning_penalty', 'Second Written Warning + 10% Salary Deduction'),
        ('first_warning_penalty', 'First Written Warning + 5% Salary Deduction'),
        ('verbal_warning', 'Recorded Verbal Warning'),
        ('custom', 'Custom Administrative Action'),
    ], string='Applicable Punishment', compute='_compute_punishment_type', store=True, readonly=False, tracking=True)

    penalty_percentage = fields.Float(string='Penalty Percentage (%)', compute='_compute_penalty_percentage', store=True, readonly=False, tracking=True)

    # Demotion fields
    new_job_id = fields.Many2one('hr.job', string='Demotion Target Job Position', tracking=True)
    new_grade_id = fields.Char(string='Demotion Target Grade Scale', tracking=True)

    # Automatic routing & authority
    required_final_authority = fields.Selection([
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

    reported_by_id = fields.Many2one(
        'hr.employee', 
        string='Reported By', 
        default=lambda self: self.env.user.employee_id
    )
    
    reference = fields.Char(string='Reference')
    # State Machine
    state = fields.Selection([
        ('draft', 'Draft'),
        ('initiated', 'Initiated / Under Review'),
        ('investigating', 'Under Investigation'),
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

    @api.depends('offense_id', 'offense_id.punishment_type')
    def _compute_punishment_type(self):
        for rec in self:
            if rec.offense_id and rec.offense_id.punishment_type:
                rec.punishment_type = rec.offense_id.punishment_type

    @api.depends('offense_id')
    def _compute_penalty_percentage(self):
        for rec in self:
            if rec.offense_id:
                rec.penalty_percentage = rec.offense_id.penalty_percentage
            else:
                rec.penalty_percentage = 0.0

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

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            if self.employee_id.parent_id and self.employee_id.parent_id.user_id:
                self.reviewer_id = self.employee_id.parent_id.user_id
            if self.employee_id.department_id and self.employee_id.department_id.manager_id and self.employee_id.department_id.manager_id.user_id:
                self.approver_id = self.employee_id.department_id.manager_id.user_id

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
                    severity_field = rec._fields['severity_level']
                    if hasattr(severity_field, '_description_selection'):
                        severity_sel = severity_field._description_selection(rec.env)
                    elif isinstance(severity_field.selection, list):
                        severity_sel = severity_field.selection
                    elif callable(severity_field.selection):
                        severity_sel = severity_field.selection(rec.env)
                    else:
                        severity_sel = []
                    severity_label = dict(severity_sel).get(rec.severity_level, rec.severity_level)
                    raise ValidationError(_(
                        'Duplicate Severity Prevention: Employee %s already has an open %s case '
                        'on incident date %s (Case Ref: %s). Consolidate into the existing case instead.'
                    ) % (rec.employee_id.name, severity_label,
                         rec.incident_date, same_severity[0].name))

    def _validate_segregation_of_duties(self):
        for rec in self:
            current_user = self.env.user
            if rec.initiator_id and rec.reviewer_id and rec.initiator_id == rec.reviewer_id:
                raise ValidationError(_('Segregation of Duties Violation: Case Initiator and Reviewer must be different individuals.'))
            if rec.initiator_id and rec.approver_id and rec.initiator_id == rec.approver_id:
                raise ValidationError(_('Segregation of Duties Violation: Case Initiator and Approver must be different individuals.'))
            if rec.reviewer_id and rec.approver_id and rec.reviewer_id == rec.approver_id:
                raise ValidationError(_('Segregation of Duties Violation: Case Reviewer and Approver must be different individuals.'))

            if rec.severity_level == 'level_1' or rec.required_final_authority == 'ceo':
                if not current_user.has_group('discipline_management.group_discipline_admin') and not current_user.has_group('discipline_management.group_discipline_ceo'):
                    raise ValidationError(_(
                        'Approval Restriction: Decisions requiring CEO / Senior Executive Authority are restricted '
                        'exclusively to authorized executive approvers.'
                    ))
                if not rec.dismissal_authority_id:
                    raise ValidationError(_(
                        'Authority Record Required: For executive or dismissal cases, you must record the designated '
                        'CEO or CPCO approver in the "Dismissal Authority" field.'
                    ))
                if rec.required_final_authority == 'ceo' and rec.dismissal_authority_id:
                    if not rec.dismissal_authority_id.has_group('discipline_management.group_discipline_ceo') and not rec.dismissal_authority_id.has_group('discipline_management.group_discipline_admin'):
                        raise ValidationError(_('Authority Mismatch: Dismissal authority assigned must hold CEO / Executive approval authority.'))
            elif rec.required_final_authority == 'cpco' and rec.dismissal_authority_id:
                if not rec.dismissal_authority_id.has_group('discipline_management.group_discipline_cpco') and not rec.dismissal_authority_id.has_group('discipline_management.group_discipline_admin'):
                    raise ValidationError(_('Authority Mismatch: Dismissal authority assigned must hold CPCO approval authority.'))

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
            whitelisted_fields = {'state', 'revocation_reason', 'revocation_date', 'revoked_by_id', 'is_revoked', 'message_follower_ids', 'message_ids', 'activity_ids', 'is_locked_for_committee', 'approver_id', 'final_decision_date'}
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

    def action_approve_and_enforce(self):
        for rec in self:
            rec.approver_id = self.env.user
            rec._validate_segregation_of_duties()

            # Verify linked committee meetings are completed with quorum and signoff
            if rec.committee_meeting_ids:
                for meeting in rec.committee_meeting_ids:
                    if meeting.state != 'completed' or not meeting.director_signed_off or not meeting.is_quorum_met:
                        raise UserError(_('Cannot enforce case decision. Linked committee meeting (%s) must be in Completed state with director sign-off and valid quorum.') % meeting.name)

            rec.final_decision_date = fields.Date.context_today(self)
            rec.with_context(force_write=True).write({'state': 'enforced'})

            # Update Employee Master Disciplinary Info & Internal Mobility Ineligibility
            rec.employee_id.sudo().with_context(no_leave_resource_calendar_update=True).write({
                'active_disciplinary_action': True,
                'is_ineligible_for_promotion_transfer': True,
                'disciplinary_warning_count': rec.employee_id.disciplinary_warning_count + 1,
                'last_disciplinary_date': rec.final_decision_date,
            })

            # Demotion handling (preserves basic salary while downgrading position scale/allowances)
            if rec.punishment_type == 'demotion':
                rec.action_apply_demotion()

            # Trigger Payroll Penalty Deduction if applicable
            if rec.penalty_percentage > 0.0:
                self.env['discipline.payroll.penalty'].create({
                    'case_id': rec.id,
                    'employee_id': rec.employee_id.id,
                    'penalty_type': 'percentage',
                    'penalty_percentage': rec.penalty_percentage,
                    'effective_date': rec.final_decision_date,
                    'state': 'pending',
                    'notes': _('Automatic percentage penalty of %s%% from Case %s.') % (rec.penalty_percentage, rec.name)
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
        """Gap 1: Demotion execution preserving basic salary while downgrading position scale/allowances."""
        for rec in self:
            if rec.new_job_id:
                rec.employee_id.sudo().with_context(no_leave_resource_calendar_update=True).write({'job_id': rec.new_job_id.id})
                rec.message_post(body=_('Demotion enforced: Reassigned to position %s. Basic wage/salary scale preserved.') % rec.new_job_id.name)

    def action_approve_dismissal(self):
        """Gap 3: Final approval of Level 1 Dismissal creating separation record and revoking system access."""
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
        if not self.is_appeal_window_open:
            raise UserError(_(
                'Appeal Window Closed: The 10-calendar-day appeal submission window has expired. '
                'Appeal deadline was %s.'
            ) % (self.appeal_deadline or 'N/A'))
        return {
            'name': _('Submit Appeal for Case %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'discipline.appeal',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_case_id': self.id,
                'default_employee_id': self.employee_id.id,
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
