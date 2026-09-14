# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import timedelta


class DisciplineSuspension(models.Model):
    _name = 'discipline.suspension'
    _description = 'Employee Disciplinary Suspension'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_date desc, id desc'

    name = fields.Char(string='Suspension Ref', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    case_id = fields.Many2one('discipline.case', string='Disciplinary Case', required=True, tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', related='case_id.employee_id', store=True, readonly=True)
    department_id = fields.Many2one('hr.department', string='Department', related='employee_id.department_id', store=True, readonly=True)

    # Suspension Type
    suspension_type = fields.Selection([
        ('with_pay', 'Suspension With Pay'),
        ('without_pay', 'Suspension Without Pay'),
    ], string='Suspension Type', required=True, default='without_pay', tracking=True)

    start_date = fields.Date(string='Suspension Start Date', required=True, default=fields.Date.context_today, tracking=True, index=True)
    end_date = fields.Date(string='Suspension End Date', required=True, tracking=True, index=True)
    working_days_count = fields.Integer(string='Working Days Duration', compute='_compute_working_days_count', store=True, tracking=True)
    
    # Initiation & Authority Matrix Mapping
    initiating_unit = fields.Selection([
        ('directorate', 'Respective Directorate'),
        ('audit', 'Audit Directorate'),
        ('pomd', 'People Operations Management Directorate (POMD)'),
    ], string='Initiating Unit', default='directorate', required=True, tracking=True)

    is_rmcd_or_iad = fields.Boolean(string='Is RMCD or IAD Staff', compute='_compute_is_rmcd_or_iad', store=True)
    
    suspending_authority = fields.Selection([
        ('pomd', 'People Operations Management Directorate (POMD)'),
        ('cpco', 'Chief People & Culture Officer (CPCO)'),
        ('bod', 'Board of Directors (BOD via CEO Referral)'),
    ], string='Designated Suspending Authority', compute='_compute_suspending_authority', store=True, tracking=True)

    bod_resolution_number = fields.Char(string='BOD Resolution Reference', tracking=True)
    bod_meeting_date = fields.Date(string='BOD Referral / Meeting Date', tracking=True)
    bod_resolution_file = fields.Binary(string='BOD Resolution Attachment', attachment=True)
    bod_resolution_filename = fields.Char(string='BOD Resolution Filename')

    @api.depends('employee_id', 'employee_id.department_id', 'employee_id.department_id.name')
    def _compute_is_rmcd_or_iad(self):
        for rec in self:
            dept_name = (rec.employee_id.department_id.name or '').lower() if rec.employee_id and rec.employee_id.department_id else ''
            rec.is_rmcd_or_iad = any(kw in dept_name for kw in ['risk', 'compliance', 'audit', 'rmcd', 'iad'])

    @api.depends('employee_id', 'employee_id.is_managerial', 'is_rmcd_or_iad')
    def _compute_suspending_authority(self):
        for rec in self:
            if rec.is_rmcd_or_iad:
                rec.suspending_authority = 'bod'
            elif rec.employee_id and rec.employee_id.is_managerial:
                rec.suspending_authority = 'cpco'
            else:
                rec.suspending_authority = 'pomd'

    reason = fields.Text(string='Reason for Suspension', required=True)
    state = fields.Selection([
        ('draft', 'Draft Request'),
        ('pending_approval', 'Pending Authority Approval'),
        ('referred_bod', 'Referred to BOD'),
        ('active', 'Active Suspension'),
        ('extended', 'Extended'),
        ('completed', 'Completed / Reinstated'),
        ('converted_dismissal', 'Converted to Dismissal'),
    ], string='Status', default='draft', required=True, tracking=True, index=True)

    days_remaining = fields.Integer(string='Days Remaining', compute='_compute_days_remaining')

    @api.depends('start_date', 'end_date')
    def _compute_working_days_count(self):
        for rec in self:
            if rec.start_date and rec.end_date:
                # Calculate total working days (excluding weekends Sat/Sun)
                day_count = 0
                curr = rec.start_date
                while curr <= rec.end_date:
                    if curr.weekday() < 5:  # Monday to Friday
                        day_count += 1
                    curr += timedelta(days=1)
                rec.working_days_count = day_count
            else:
                rec.working_days_count = 0

    @api.depends('end_date')
    def _compute_days_remaining(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.end_date and rec.state in ['active', 'extended']:
                delta = (rec.end_date - today).days
                rec.days_remaining = max(delta, 0)
            else:
                rec.days_remaining = 0

    # Maximum Duration Enforcement (30 Working Days)
    @api.constrains('working_days_count', 'start_date', 'end_date')
    def _check_max_duration(self):
        for rec in self:
            if rec.start_date and rec.end_date and rec.end_date < rec.start_date:
                raise ValidationError(_('Suspension End Date cannot be earlier than Start Date.'))
            if rec.working_days_count > 30:
                raise ValidationError(_('Maximum Duration Violation: Discipline policy restricts maximum suspension duration to thirty (30) working days (%s working days calculated).') % rec.working_days_count)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('discipline.suspension') or _('New')
        return super().create(vals_list)

    # Workflow Actions
    def action_submit_for_approval(self):
        for rec in self:
            if rec.suspending_authority == 'bod':
                rec.write({'state': 'referred_bod'})
                rec.case_id.message_post(body=_('Suspension case for RMCD/IAD staff referred to Board of Directors (BOD) for review.'))
            else:
                rec.write({'state': 'pending_approval'})
                rec.case_id.message_post(body=_('Suspension submitted for approval to %s.') % rec.suspending_authority)

    def action_activate_suspension(self):
        """Activate suspension, validate approval authority, and deactivate ERP user account."""
        for rec in self:
            current_user = self.env.user
            # Authority validation
            if rec.suspending_authority == 'bod':
                if not rec.bod_resolution_number:
                    raise UserError(_('BOD Resolution Reference must be recorded prior to activating suspension for RMCD/IAD staff.'))
            elif rec.suspending_authority == 'cpco':
                if not (current_user.has_group('discipline_management.group_discipline_cpco') or current_user.has_group('discipline_management.group_discipline_admin')):
                    raise UserError(_('Authority Restriction: Suspensions for managerial employees require Chief People & Culture Officer (CPCO) approval.'))
            elif rec.suspending_authority == 'pomd':
                if not (current_user.has_group('discipline_management.group_discipline_pomd') or current_user.has_group('discipline_management.group_discipline_admin') or current_user.has_group('discipline_management.group_discipline_manager')):
                    raise UserError(_('Authority Restriction: Non-managerial suspensions must be approved by People Operations Directorate (POMD).'))

            rec.write({'state': 'active'})
            rec.employee_id.is_suspended = True
            rec.employee_id.suspension_type = rec.suspension_type

            # Deactivate employee ERP user account during active suspension
            if rec.employee_id.user_id:
                rec.employee_id.user_id.sudo().write({'active': False})
                rec.message_post(body=_('Employee ERP user account (%s) deactivated for the duration of the suspension.') % rec.employee_id.user_id.name)

            rec.case_id.message_post(
                body=_('Suspension %s activated for employee %s (%s) from %s to %s by %s.') % (
                    rec.name, rec.employee_id.name, rec.suspension_type, rec.start_date, rec.end_date, current_user.name
                )
            )

    def action_reinstate_employee(self):
        """Reinstate employee and restore ERP user account."""
        for rec in self:
            rec.write({'state': 'completed'})
            rec.employee_id.is_suspended = False
            rec.employee_id.suspension_type = False
            
            # Reactivate ERP user account
            if rec.employee_id.user_id:
                rec.employee_id.user_id.sudo().write({'active': True})
                rec.message_post(body=_('Employee ERP user account (%s) reactivated upon reinstatement.') % rec.employee_id.user_id.name)

            rec.case_id.message_post(body=_('Suspension completed. Employee %s reinstated to duty.') % rec.employee_id.name)

    def action_convert_to_dismissal(self):
        """
/: Convert an active suspension to a dismissal.
        Triggers the full dismissal workflow on the parent case.
        Restricted to HR Administrators only.
        """
        for rec in self:
            if not self.env.user.has_group('discipline_management.group_discipline_admin'):
                raise UserError(_('Only HR Administrators can convert a suspension to dismissal.'))
            if rec.state not in ['active', 'extended']:
                raise UserError(_('Suspension must be in Active or Extended state to be converted to dismissal.'))
            # Clear suspension flag (dismissal takes precedence)
            rec.employee_id.is_suspended = False
            rec.employee_id.suspension_type = False
            rec.write({'state': 'converted_dismissal'})
            # Trigger the case's dismissal workflow
            if rec.case_id:
                rec.case_id._process_employee_dismissal()
                rec.case_id.message_post(
                    body=_('Suspension %s converted to dismissal for employee %s. '
                           'Employee archived and system access revoked.') % (rec.name, rec.employee_id.name)
                )
            _logger = __import__('logging').getLogger(__name__)
            _logger.info('Suspension %s converted to dismissal for employee %s.', rec.name, rec.employee_id.name)

    @api.model
    def _cron_check_suspension_expiry(self):
        """Automated tracking & HR notification prior to expiry."""
        today = fields.Date.context_today(self)
        alert_date = today + timedelta(days=3)
        expiring_suspensions = self.search([
            ('state', 'in', ['active', 'extended']),
            ('end_date', '<=', alert_date)
        ])
        for susp in expiring_suspensions:
            susp.message_post(
                body=_('SUSPENSION EXPIRY NOTICE: Suspension %s for %s will expire on %s (%s days remaining).') % (susp.name, susp.employee_id.name, susp.end_date, susp.days_remaining),
                message_type='notification'
            )

    @api.model
    def _cron_process_monthly_suspension_penalties(self):
        """Process periodic payroll penalty records for active without-pay suspensions."""
        today = fields.Date.context_today(self)
        active_suspensions = self.search([
            ('state', 'in', ['active', 'extended']),
            ('suspension_type', '=', 'without_pay')
        ])
        Penalty = self.env['discipline.payroll.penalty']
        for susp in active_suspensions:
            existing = Penalty.search([
                ('suspension_id', '=', susp.id),
                ('effective_date', '>=', today.replace(day=1))
            ])
            if not existing:
                Penalty.create({
                    'case_id': susp.case_id.id,
                    'employee_id': susp.employee_id.id,
                    'penalty_type': 'suspension_without_pay',
                    'suspension_id': susp.id,
                    'suspension_days': min(susp.working_days_count or 1, 30),
                    'effective_date': today,
                    'state': 'pending',
                    'notes': _('Monthly periodic without-pay suspension penalty for %s.') % susp.name
                })
