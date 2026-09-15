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
    
    reason = fields.Text(string='Reason for Suspension', required=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted for Approval'),
        ('approved', 'Approved'),
        ('active', 'Active Suspension'),
        ('extended', 'Extended'),
        ('completed', 'Completed / Reinstated'),
        ('converted_dismissal', 'Converted to Dismissal'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', required=True, tracking=True, index=True)

    # -------------------------------------------------------------
    # Suspending Authority Routing per BRD (Page 10)
    # -------------------------------------------------------------
    approval_authority = fields.Selection([
        ('cpco', 'Chief People & Culture Officer (CPCO)'),
        ('pomd', 'People Operations Management Directorate (POMD)'),
        ('bod', 'Board of Directors (BOD via CEO Referral)'),
    ], string='Required Approving Authority', compute='_compute_approval_authority', store=True, tracking=True,
        help='Suspension Approval Authority per BRD: '
             '1. For managerial employees related with discipline committee: Chief People & Culture Officer (CPCO). '
             '2. For non-managerial employees: People Operations Management Directorate (POMD). '
             '3. For (RMCD & IAD): CEO refers the matter to the Board of Directors (BOD) for the appropriate decision. '
             'The system prevents a user from approving or executing a suspension that exceeds his/her delegated authority.')

    initiator_id = fields.Many2one('res.users', string='Suspension Initiator', default=lambda self: self.env.user, readonly=True, tracking=True)
    approver_id = fields.Many2one('res.users', string='Approved By', readonly=True, tracking=True)
    approval_date = fields.Date(string='Approval Date', readonly=True, tracking=True)
    rejection_reason = fields.Text(string='Rejection Reason', tracking=True)

    is_rmcd_iad_staff = fields.Boolean(
        string='RMCD / IAD Staff',
        compute='_compute_is_rmcd_iad_staff',
        store=True,
        readonly=False,
        tracking=True,
        help='Risk Management & Compliance Directorate (RMCD) or Internal Audit Directorate (IAD) staff. '
             'For RMCD & IAD staff, the CEO shall refer the matter to the Board of Directors (BOD) for the appropriate decision.'
    )

    can_current_user_approve = fields.Boolean(string='Can Current User Approve', compute='_compute_can_current_user_approve')

    @api.depends('employee_id', 'employee_id.department_id')
    def _compute_is_rmcd_iad_staff(self):
        for rec in self:
            emp = rec.employee_id
            dept_name = (emp.department_id.name or '').upper() if emp and emp.department_id else ''
            dept_code = (getattr(emp.department_id, 'code', '') or '').upper() if emp and emp.department_id else ''
            if any(kw in dept_name for kw in ['RMCD', 'RISK', 'IAD', 'AUDIT', 'COMPLIANCE']) or dept_code in ('RMCD', 'IAD'):
                rec.is_rmcd_iad_staff = True
            elif not rec.is_rmcd_iad_staff:
                rec.is_rmcd_iad_staff = False

    @api.depends('employee_id', 'employee_id.is_managerial', 'is_rmcd_iad_staff')
    def _compute_approval_authority(self):
        for rec in self:
            if rec.is_rmcd_iad_staff:
                rec.approval_authority = 'bod'
            elif rec.employee_id and rec.employee_id.is_managerial:
                rec.approval_authority = 'cpco'
            else:
                rec.approval_authority = 'pomd'

    @api.depends('state', 'approval_authority')
    def _compute_can_current_user_approve(self):
        user = self.env.user
        is_admin = user.has_group('discipline_management.group_discipline_admin')
        for rec in self:
            if rec.state != 'submitted':
                rec.can_current_user_approve = False
                continue
            if is_admin:
                rec.can_current_user_approve = True
                continue
            if rec.approval_authority == 'cpco':
                rec.can_current_user_approve = user.has_group('discipline_management.group_discipline_cpco')
            elif rec.approval_authority == 'pomd':
                rec.can_current_user_approve = (
                    user.has_group('discipline_management.group_discipline_pomd') or
                    user.has_group('discipline_management.group_discipline_committee_secretary') or
                    user.has_group('discipline_management.group_discipline_director')
                )
            elif rec.approval_authority == 'bod':
                rec.can_current_user_approve = user.has_group('discipline_management.group_discipline_ceo')
            else:
                rec.can_current_user_approve = False

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

    # -------------------------------------------------------------
    # Workflow Actions (FR-DIS-026 / FR-DIS-030A Approval Routing)
    # -------------------------------------------------------------
    def action_submit_for_approval(self):
        """Route the suspension to its required approving authority."""
        for rec in self:
            if not rec.reason:
                raise UserError(_('Reason for Suspension is mandatory before submission.'))
            rec.write({'state': 'submitted'})
            authority_label = dict(rec._fields['approval_authority'].selection).get(rec.approval_authority)
            rec.case_id.message_post(body=_(
                'Suspension %s submitted for approval. Required approving authority: %s.'
            ) % (rec.name, authority_label))

            # Notify the relevant approver group per BRD
            group_xmlid = {
                'cpco': 'discipline_management.group_discipline_cpco',
                'pomd': 'discipline_management.group_discipline_pomd',
                'bod': 'discipline_management.group_discipline_ceo',
            }.get(rec.approval_authority, 'discipline_management.group_discipline_pomd')
            grp = self.env.ref(group_xmlid, raise_if_not_found=False) if group_xmlid else False
            approver_user = (grp.user_ids[0] if grp and grp.user_ids else False)
            if approver_user:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('Suspension Approval Required: %s') % rec.name,
                    note=_('Suspension of %s requires your approval as %s.') % (rec.employee_id.name, authority_label),
                    user_id=approver_user.id
                )

    def action_approve_suspension(self):
        """Enforces delegated authority per BRD Page 10:
        1. Managerial employees related with discipline committee: Chief People & Culture Officer (CPCO).
        2. Non-managerial employees: People Operations Management Directorate (POMD).
        3. RMCD & IAD: CEO refers to the Board of Directors (BOD).
        Prevents any user from approving a suspension that exceeds their delegated authority.
        """
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Only suspensions in "Submitted for Approval" state can be approved.'))
            if not rec.can_current_user_approve:
                if rec.approval_authority == 'cpco':
                    msg = _('Delegated Authority Violation: For managerial employees, only the Chief People & Culture Officer (CPCO) has the delegated authority to approve this suspension.')
                elif rec.approval_authority == 'pomd':
                    msg = _('Delegated Authority Violation: For non-managerial employees, such cases shall be handled and approved through People Operations Management Directorate (POMD).')
                elif rec.approval_authority == 'bod':
                    msg = _('Delegated Authority Violation: For RMCD and IAD staff, the CEO shall refer the matter to the Board of Directors (BOD) for the appropriate decision.')
                else:
                    msg = _('Delegated Authority Violation: You do not possess the required approving authority for this suspension.')
                raise UserError(msg)
            rec.write({
                'state': 'approved',
                'approver_id': self.env.user.id,
                'approval_date': fields.Date.context_today(self),
            })
            rec.case_id.message_post(body=_('Suspension %s approved by %s (%s).') % (
                rec.name, self.env.user.name, dict(rec._fields['approval_authority'].selection).get(rec.approval_authority)
            ))
            rec.action_activate_suspension()

    def action_reject_suspension(self):
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Only suspensions in "Submitted for Approval" state can be rejected.'))
            if not rec.can_current_user_approve:
                raise UserError(_('Delegated Authority Violation: You are not authorized to reject this suspension.'))
            if not rec.rejection_reason:
                raise UserError(_('A rejection reason is required.'))
            rec.write({'state': 'rejected'})
            rec.case_id.message_post(body=_('Suspension %s rejected by %s: %s') % (rec.name, self.env.user.name, rec.rejection_reason))

    def action_activate_suspension(self):
        """Execute and activate suspension.
        The system prevents a user from approving or executing a suspension that exceeds his/her delegated authority.
        """
        for rec in self:
            if rec.state not in ('approved',) and not self.env.user.has_group('discipline_management.group_discipline_admin'):
                raise UserError(_('Suspension %s must be Approved before it can be activated.') % rec.name)
            if not rec.can_current_user_approve and not self.env.user.has_group('discipline_management.group_discipline_admin'):
                raise UserError(_('Delegated Authority Violation: You do not have the delegated authority to execute this suspension.'))
            rec.write({'state': 'active'})
            rec.employee_id.is_suspended = True
            rec.employee_id.suspension_type = rec.suspension_type
            if 'status' in rec.employee_id._fields:
                rec.employee_id.sudo().write({'status': 'suspended'})
            rec.case_id.message_post(
                body=_('Suspension %s activated for employee %s (%s) from %s to %s.') % (rec.name, rec.employee_id.name, rec.suspension_type, rec.start_date, rec.end_date)
            )
            # FR-DIS-029: deactivate ERP user access effective the suspension start date.
            if rec.employee_id.user_id and rec.employee_id.user_id.active:
                rec.employee_id.user_id.sudo().write({'active': False})
                rec.case_id.message_post(body=_('System user access for %s disabled effective %s due to suspension.') % (rec.employee_id.user_id.name, rec.start_date))

    def action_reinstate_employee(self):
        for rec in self:
            rec.write({'state': 'completed'})
            rec.employee_id.is_suspended = False
            rec.employee_id.suspension_type = False
            if 'status' in rec.employee_id._fields and rec.employee_id.status == 'suspended':
                rec.employee_id.sudo().write({'status': 'active'})
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
