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
    punishment_type = fields.Selection(related='offense_id.punishment_type', string='Applicable Punishment', store=True, readonly=True)
    penalty_percentage = fields.Float(string='Penalty Percentage (%)', compute='_compute_penalty_percentage', store=True, readonly=False, tracking=True)

    incident_date = fields.Date(string='Incident Date', required=True, default=fields.Date.context_today, tracking=True)
    description = fields.Text(string='Detailed Description of Misconduct', required=True)
    
    # Workflow Roles (FR-DIS-010: Segregation of Duties)
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

    # SLA Tracking (FR-DIS-012)
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
    
    # Revocation Data (FR-DIS-039 to FR-DIS-041)
    is_revoked = fields.Boolean(string='Is Revoked', default=False, readonly=True, tracking=True)
    revocation_reason = fields.Text(string='Revocation Justification', readonly=True, tracking=True)
    revoked_by_id = fields.Many2one('res.users', string='Revoked By', readonly=True, tracking=True)
    revocation_date = fields.Date(string='Revocation Date', readonly=True, tracking=True)

    @api.depends('offense_id')
    def _compute_penalty_percentage(self):
        for rec in self:
            if rec.offense_id:
                rec.penalty_percentage = rec.offense_id.penalty_percentage
            else:
                rec.penalty_percentage = 0.0

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
                # FR-DIS-031: 10 Calendar Days appeal window
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

    # FR-DIS-009: Duplicate Case Prevention
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
                    'Duplicate Case Prevention: A disciplinary case already exists for Employee %s on incident date %s for offense "%s" (Case Reference: %s).'
                ) % (rec.employee_id.name, rec.incident_date, rec.offense_id.name, duplicate[0].name))

    # FR-DIS-010 & FR-DIS-011: Segregation of Duties & Approval Restrictions
    def _validate_segregation_of_duties(self):
        for rec in self:
            current_user = self.env.user
            # Check Initiator != Reviewer != Approver
            if rec.initiator_id and rec.reviewer_id and rec.initiator_id == rec.reviewer_id:
                raise ValidationError(_('Segregation of Duties Violation: Case Initiator and Reviewer must be different individuals.'))
            if rec.initiator_id and rec.approver_id and rec.initiator_id == rec.approver_id:
                raise ValidationError(_('Segregation of Duties Violation: Case Initiator and Approver must be different individuals.'))
            if rec.reviewer_id and rec.approver_id and rec.reviewer_id == rec.approver_id:
                raise ValidationError(_('Segregation of Duties Violation: Case Reviewer and Approver must be different individuals.'))

            # FR-DIS-011: Dismissal Decisions (Level 1) restricted exclusively to authorized higher-level HR Admin
            if rec.severity_level == 'level_1' and not current_user.has_group('discipline_management.group_discipline_admin'):
                raise ValidationError(_('Approval Restriction: Dismissal decisions (Level 1 Critical Offense) are restricted exclusively to HR Administrators / Senior Authority.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('discipline.case') or _('New')
        cases = super().create(vals_list)
        return cases

    def unlink(self):
        # FR-DIS-041: Original Record Preservation - Enforced or Finalized cases cannot be deleted
        for rec in self:
            if rec.state in ['enforced', 'closed', 'appealed']:
                raise UserError(_('Preservation Policy Violation: Enforced or finalized disciplinary records cannot be deleted. Use formal Revocation if required.'))
        return super().unlink()

    # --- Workflow Actions ---
    def action_initiate(self):
        for rec in self:
            if not rec.description:
                raise UserError(_('Detailed Description is mandatory before initiating a case.'))
            rec.write({'state': 'initiated'})
            rec.message_post(body=_('Disciplinary case initiated for employee %s.') % rec.employee_id.name)

    def action_start_investigation(self):
        for rec in self:
            rec.reviewer_id = self.env.user
            rec.write({'state': 'investigating'})
            rec.message_post(body=_('Investigation process started by %s.') % self.env.user.name)

    def action_send_to_committee(self):
        for rec in self:
            rec.write({'state': 'committee_review'})
            rec.message_post(body=_('Case submitted for Disciplinary Committee Review.'))

    def action_submit_for_approval(self):
        for rec in self:
            rec.write({'state': 'pending_approval'})
            rec.message_post(body=_('Case submitted for final approval.'))

    # FR-DIS-021 to FR-DIS-025: Decision Enforcement & System Integration
    def action_approve_and_enforce(self):
        for rec in self:
            rec.approver_id = self.env.user
            rec._validate_segregation_of_duties()

            rec.final_decision_date = fields.Date.context_today(self)
            rec.write({'state': 'enforced'})

            # 1. Update Employee Master Disciplinary Info (FR-DIS-022)
            rec.employee_id.active_disciplinary_action = True
            rec.employee_id.disciplinary_warning_count += 1
            rec.employee_id.last_disciplinary_date = rec.final_decision_date

            # 2. Trigger Payroll Penalty Deduction if applicable (FR-DIS-023)
            if rec.penalty_percentage > 0.0:
                self.env['discipline.payroll.penalty'].create({
                    'case_id': rec.id,
                    'employee_id': rec.employee_id.id,
                    'penalty_percentage': rec.penalty_percentage,
                    'effective_date': rec.final_decision_date,
                    'state': 'pending',
                    'notes': _('Automatic penalty deduction of %s%% resulting from Case %s.') % (rec.penalty_percentage, rec.name)
                })

            # 3. Dismissal Handling & Separation Workflow (FR-DIS-024 & FR-DIS-025)
            if rec.severity_level == 'level_1' or rec.punishment_type == 'dismissal':
                rec._process_employee_dismissal()

            rec.message_post(body=_('Disciplinary case decision approved and enforced automatically. Warning letter generated.'))

    def _process_employee_dismissal(self):
        """FR-DIS-024 & FR-DIS-025: Handle separation and access revocation."""
        for rec in self:
            emp = rec.employee_id
            # Build write dict safely - departure fields exist when hr module supports archiving
            write_vals = {'active': False}
            departure_reason = self.env.ref('hr.departure_fired', raise_if_not_found=False)
            if departure_reason and 'departure_reason_id' in emp._fields:
                write_vals['departure_reason_id'] = departure_reason.id
            if 'departure_date' in emp._fields:
                write_vals['departure_date'] = rec.final_decision_date
            if 'departure_description' in emp._fields:
                write_vals['departure_description'] = _('Dismissed under Disciplinary Case %s on %s.') % (rec.name, rec.final_decision_date)
            emp.write(write_vals)
            # Trigger request/action to disable user system access
            if emp.user_id:
                emp.user_id.sudo().write({'active': False})
                rec.message_post(body=_('System user access for user %s disabled due to dismissal.') % emp.user_id.name)

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

    # Cron Methods
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
