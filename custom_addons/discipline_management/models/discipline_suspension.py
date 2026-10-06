# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import timedelta
import base64
import os
import logging

_logger = logging.getLogger(__name__)


class DisciplineSuspension(models.Model):
    _name = 'discipline.suspension'
    _description = 'Employee Disciplinary Suspension'
    _inherit = ['mail.thread']
    _order = 'start_date desc, id desc'

    name = fields.Char(string='Suspension Ref', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    case_id = fields.Many2one('discipline.case', string='Disciplinary Case', required=True, readonly=True, ondelete='cascade', tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', related='case_id.employee_id', store=True, readonly=True)
    department_id = fields.Many2one('hr.department', string='Department', related='employee_id.department_id', store=True, readonly=True)
    job_title = fields.Char(string='Job Position', related='employee_id.job_title', store=True, readonly=True)

    # Parent case context
    offense_id = fields.Many2one('discipline.offense', string='Misconduct Clause', related='case_id.offense_id', store=True, readonly=True)
    offense_category_id = fields.Many2one('discipline.offense.category', string='Offense Category', related='case_id.offense_category_id', store=True, readonly=True)
    case_description = fields.Text(string='Incident Fact & Description', related='case_id.description', readonly=True)
    ceo_assignment_notes = fields.Text(string='CEO Assignment Directive', related='case_id.ceo_assignment_notes', readonly=True)

    # Linked investigation (if any)
    investigation_id = fields.Many2one('discipline.investigation', string='Audit Investigation', compute='_compute_investigation_id', store=False)

    def _compute_investigation_id(self):
        for rec in self:
            inv = self.env['discipline.investigation'].search([('case_id', '=', rec.case_id.id)], limit=1)
            rec.investigation_id = inv.id if inv else False

    # Suspension Type
    suspension_type = fields.Selection([
        ('without_pay', 'Suspension Without Pay'),
        ('with_pay', 'Suspension With Pay'),
    ], string='Suspension Type', required=True, default='without_pay', tracking=True)

    start_date = fields.Date(string='Suspension Start Date', required=True, default=fields.Date.context_today, tracking=True, index=True)
    end_date = fields.Date(string='Suspension End Date', required=True, tracking=True, index=True)
    calendar_days_count = fields.Integer(string='Calendar Days', compute='_compute_calendar_days_count', store=True)
    working_days_count = fields.Integer(string='Working Days Duration', compute='_compute_working_days_count', store=True, tracking=True)
    days_remaining = fields.Integer(string='Days Remaining', compute='_compute_days_remaining')

    # Initiation & Authority Matrix Mapping
    initiating_unit = fields.Selection([
        ('directorate', 'Respective Directorate'),
        ('audit', 'Audit Directorate'),
        ('pomd', 'People Operations Management Directorate (POMD)'),
        ('ceo', 'Executive Office (CEO Directive)'),
    ], string='Initiating Unit', default='directorate', required=True, readonly=True, tracking=True)

    is_rmcd_or_iad = fields.Boolean(string='Is RMCD or IAD Staff', compute='_compute_is_rmcd_or_iad', store=True)
    is_managerial = fields.Boolean(string='Is Managerial Staff', related='employee_id.is_managerial', store=True, readonly=True)

    suspending_authority = fields.Selection([
        ('pomd', 'People Operations Management Directorate (POMD)'),
        ('cpco', 'Chief People & Culture Officer (CPCO)'),
        ('bod', 'Board of Directors (BOD via CEO Referral)'),
    ], string='Designated Suspending Authority', compute='_compute_suspending_authority', store=True, tracking=True)

    # BOD Referral Information (for RMCD/IAD)
    bod_resolution_number = fields.Char(string='BOD Resolution Reference', tracking=True)
    bod_meeting_date = fields.Date(string='BOD Referral / Meeting Date', tracking=True)
    bod_resolution_file = fields.Binary(string='BOD Resolution Attachment', attachment=True)
    bod_resolution_filename = fields.Char(string='BOD Resolution Filename')

    # Formal Notice & Delivery Documentation
    notice_letter_file = fields.Binary(string='Official Signed Suspension Letter', attachment=True)
    notice_letter_filename = fields.Char(string='Suspension Letter Filename')
    notice_served_date = fields.Date(string='Notice Served Date', tracking=True)

    # Reinstatement & Post-Case Payroll Backpayment
    reinstatement_date = fields.Date(string='Reinstatement Date', tracking=True)
    reinstatement_notes = fields.Text(string='Reinstatement / Return to Duty Remarks')
    backpay_status = fields.Selection([
        ('not_applicable', 'Not Applicable'),
        ('pending_payroll', 'Pending Payroll Credit'),
        ('settled', 'Settled / Processed'),
    ], string='Backpay Status', default='not_applicable', tracking=True)
    backpay_days_count = fields.Integer(string='Withheld Working Days for Backpay', tracking=True)

    # Extension Tracking
    is_extended = fields.Boolean(string='Has Been Extended', default=False, readonly=True)
    extension_reason = fields.Text(string='Extension Justification', tracking=True)
    extension_date = fields.Date(string='Extension Date', tracking=True)

    reason = fields.Text(string='Grounds for Suspension', required=True)
    state = fields.Selection([
        ('draft', 'Draft Request'),
        ('pending_approval', 'Pending Authority Approval'),
        ('referred_bod', 'Referred to BOD'),
        ('active', 'Active Suspension'),
        ('extended', 'Extended'),
        ('completed', 'Completed / Reinstated'),
        ('converted_dismissal', 'Converted to Dismissal'),
        ('revoked', 'Revoked / Exonerated'),
    ], string='Status', default='draft', required=True, tracking=True, index=True)

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

    @api.depends('start_date', 'end_date')
    def _compute_calendar_days_count(self):
        for rec in self:
            if rec.start_date and rec.end_date:
                delta = (rec.end_date - rec.start_date).days + 1
                rec.calendar_days_count = max(delta, 0)
            else:
                rec.calendar_days_count = 0

    @api.depends('start_date', 'end_date')
    def _compute_working_days_count(self):
        for rec in self:
            if rec.start_date and rec.end_date:
                day_count = 0
                curr = rec.start_date
                while curr <= rec.end_date:
                    if curr.weekday() < 5:  # Monday to Friday
                        day_count += 1
                    curr += timedelta(days=1)
                rec.working_days_count = day_count
            else:
                rec.working_days_count = 0

    @api.depends('start_date', 'end_date', 'state')
    def _compute_days_remaining(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.start_date and rec.end_date:
                if rec.state in ['active', 'extended']:
                    delta = (rec.end_date - today).days
                    rec.days_remaining = max(delta, 0)
                elif rec.state in ['draft', 'pending_approval', 'referred_bod']:
                    rec.days_remaining = max((rec.end_date - rec.start_date).days + 1, 0)
                else:
                    rec.days_remaining = 0
            else:
                rec.days_remaining = 0

    @api.constrains('working_days_count', 'start_date', 'end_date')
    def _check_max_duration(self):
        ICP = self.env['ir.config_parameter'].sudo()
        max_days = int(ICP.get_param('discipline.max_suspension_days', 30))
        for rec in self:
            if rec.start_date and rec.end_date and rec.end_date < rec.start_date:
                raise ValidationError(_('Suspension End Date cannot be earlier than Start Date.'))
            if rec.working_days_count > max_days and not rec.is_extended:
                raise ValidationError(
                    _('Maximum Duration Violation: Standard discipline policy restricts initial suspension duration to %d working days (%s working days calculated).')
                    % (max_days, rec.working_days_count)
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('discipline.suspension') or _('New')
        return super().create(vals_list)

    def write(self, vals):
        protected_fields = {'suspension_type', 'start_date', 'end_date', 'case_id', 'initiating_unit'}
        if not self.env.su and any(f in vals for f in protected_fields):
            for rec in self:
                if rec.state in ['active', 'extended', 'completed', 'converted_dismissal', 'revoked']:
                    if not (self.env.user.has_group('discipline_management.group_discipline_admin') or self.env.user.has_group('base.group_system')):
                        raise UserError(_('Cannot modify core suspension parameters while the suspension is active or finalized.'))
        return super().write(vals)

    can_user_approve_suspension = fields.Boolean(
        string='Can User Approve Suspension',
        compute='_compute_can_user_approve_suspension'
    )

    def _compute_can_user_approve_suspension(self):
        user = self.env.user
        EmpModel = self.env['hr.employee'].sudo()
        cpco_user = EmpModel.get_cpco_user()
        sec_user = EmpModel.get_secretary_user()
        is_admin = user.has_group('discipline_management.group_discipline_admin') or user.has_group('base.group_system')
        for rec in self:
            can_approve = False
            if is_admin:
                can_approve = True
            elif rec.suspending_authority == 'cpco':
                can_approve = bool((cpco_user and user.id == cpco_user.id) or user.has_group('discipline_management.group_discipline_cpco'))
            elif rec.suspending_authority == 'pomd':
                can_approve = bool((sec_user and user.id == sec_user.id) or user.has_group('discipline_management.group_discipline_pomd'))
            elif rec.suspending_authority == 'bod':
                # CEO acts on behalf of the Board
                can_approve = bool(user.has_group('discipline_management.group_discipline_ceo') or is_admin)
            rec.can_user_approve_suspension = can_approve

    # Helpers for QWeb PDF Report
    @api.model
    def get_official_bunna_logo_base64(self):
        """Returns base64 string of the official logo for QWeb PDF rendering."""
        logo_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'static', 'src', 'img', 'bunna_bank_official_logo.png')
        )
        if not os.path.exists(logo_path):
            logo_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), '..', '..', 'custom_recruitment', 'static', 'src', 'img', 'bunna_bank_official_logo.png')
            )
        if os.path.exists(logo_path):
            with open(logo_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        return ""

    def get_salutation_label(self):
        """Returns formal Ethiopian salutation based on gender (Ato / W/ro / W/t)."""
        self.ensure_one()
        gender = getattr(self.employee_id, 'gender', False)
        if gender == 'male':
            return 'Ato'
        elif gender == 'female':
            marital = getattr(self.employee_id, 'marital', False)
            return 'W/t' if marital == 'single' else 'W/ro'
        return 'Ato/W/ro'

    def get_salutation_title_and_first_name(self):
        """Returns title and first name (e.g. 'Ato Samuel')."""
        self.ensure_one()
        sal = self.get_salutation_label()
        first_name = (self.employee_id.name or '').split()[0] if self.employee_id and self.employee_id.name else _('Employee')
        return f"{sal} {first_name}"

    def action_print_suspension_letter(self):
        """Print official Suspension Notice Letter PDF."""
        self.ensure_one()
        return self.env.ref('discipline_management.action_report_suspension_letter').report_action(self)

    # Workflow Actions
    def action_submit_for_approval(self):
        for rec in self:
            if rec.suspending_authority == 'bod':
                rec.write({'state': 'referred_bod'})
                rec.case_id.message_post(body=_('Suspension case for RMCD/IAD staff referred to Board of Directors (BOD) / Executive Office for review.'))
            else:
                rec.write({'state': 'pending_approval'})
                rec.case_id.message_post(body=_('Suspension %s submitted for approval to %s.') % (rec.name, rec.suspending_authority.upper()))

    def action_activate_suspension(self):
        """Activate suspension, validate approval authority, and deactivate ERP user account."""
        for rec in self:
            current_user = self.env.user
            if rec.suspending_authority == 'bod' and not rec.bod_resolution_number:
                raise UserError(_('BOD Resolution Reference must be recorded prior to activating suspension for RMCD/IAD personnel.'))
            
            if not rec.can_user_approve_suspension:
                if rec.suspending_authority == 'cpco':
                    raise UserError(_('Authority Restriction: Suspensions for managerial employees require Chief People & Culture Officer (CPCO) approval.'))
                elif rec.suspending_authority == 'pomd':
                    raise UserError(_('Authority Restriction: Non-managerial suspensions must be approved by People Operations Directorate (POMD).'))
                elif rec.suspending_authority == 'bod':
                    raise UserError(_('Authority Restriction: RMCD/IAD suspensions require Executive Office (CEO) authorization.'))
                else:
                    raise UserError(_('Authority Restriction: You do not have authorization to approve this suspension.'))

            rec.write({'state': 'active'})
            rec.employee_id.sudo().is_suspended = True
            rec.employee_id.sudo().suspension_type = rec.suspension_type

            # Deactivate employee ERP user account during active suspension
            if rec.employee_id.user_id:
                rec.employee_id.user_id.sudo().write({'active': False})
                rec.message_post(body=_('Employee ERP user account (%s) deactivated for the duration of the suspension.') % rec.employee_id.user_id.name)

            rec.case_id.message_post(
                body=_('Suspension %s activated for employee %s (%s) from %s to %s by %s.') % (
                    rec.name, rec.employee_id.name, rec.suspension_type, rec.start_date, rec.end_date, current_user.name
                )
            )

            # Send Discuss notifications to stakeholders
            rec._send_suspension_activated_discuss_notification()

    def _send_suspension_activated_discuss_notification(self):
        """Send direct Discuss message to Subject Employee, Coach, Director, CPCO, CEO."""
        for rec in self:
            EmpModel = self.env['hr.employee'].sudo()
            cpco_user = EmpModel.get_cpco_user()
            ceo_user = EmpModel.get_ceo_user()
            director_user = rec.case_id.director_id.user_id if rec.case_id and rec.case_id.director_id else False
            coach_user = rec.employee_id.coach_id.user_id if rec.employee_id and rec.employee_id.coach_id else False
            emp_user = rec.employee_id.user_id
            sender_partner = self.env.user.partner_id

            recipients = [
                ('Subject Employee', emp_user),
                ('Direct Coach', coach_user),
                ('Director', director_user),
                ('CPCO', cpco_user),
                ('CEO', ceo_user),
            ]
            msg_body = (
                f"<strong>OFFICIAL SUSPENSION NOTICE: {rec.name}</strong><br/>"
                f"Employee: <strong>{rec.employee_id.name}</strong> ({rec.department_id.name or 'N/A'})<br/>"
                f"Type: <strong>{dict(rec._fields['suspension_type'].selection).get(rec.suspension_type)}</strong><br/>"
                f"Effective Period: <strong>{rec.start_date} to {rec.end_date}</strong> ({rec.working_days_count} Working Days)<br/>"
                f"Grounds: {rec.reason or 'Precautionary suspension pending disciplinary proceedings.'}<br/>"
                f"Disciplinary Case: <strong>{rec.case_id.name}</strong>"
            )
            for role_name, target_user in recipients:
                if target_user and target_user.partner_id and target_user.id != self.env.user.id:
                    try:
                        channel = self.env['discuss.channel'].sudo().channel_get(
                            partners_to=[sender_partner.id, target_user.partner_id.id]
                        )
                        if channel and channel.get('id'):
                            ch_record = self.env['discuss.channel'].sudo().browse(channel['id'])
                            ch_record.message_post(
                                body=msg_body,
                                message_type='comment',
                                subtype_xmlid='mail.mt_comment',
                                author_id=sender_partner.id,
                            )
                    except Exception as e:
                        _logger.warning("Failed to send suspension notification to %s: %s", role_name, e)

    def action_reinstate_employee(self):
        """Reinstate employee, restore ERP user account, and flag backpay if unpaid suspension."""
        today = fields.Date.context_today(self)
        for rec in self:
            current_user = self.env.user
            if not rec.can_user_approve_suspension:
                raise UserError(_('Authority Restriction: Only the designated authority can reinstate this employee.'))

            vals = {
                'state': 'completed',
                'reinstatement_date': today,
            }
            if rec.suspension_type == 'without_pay':
                vals['backpay_status'] = 'pending_payroll'
                vals['backpay_days_count'] = rec.working_days_count

            rec.write(vals)
            rec.employee_id.sudo().is_suspended = False
            rec.employee_id.sudo().suspension_type = False
            
            # Reactivate ERP user account
            if rec.employee_id.user_id:
                rec.employee_id.user_id.sudo().write({'active': True})
                rec.message_post(body=_('Employee ERP user account (%s) reactivated upon formal reinstatement.') % rec.employee_id.user_id.name)

            rec.case_id.message_post(
                body=_('Suspension %s completed. Employee %s formally reinstated to active duty on %s by %s.') % (
                    rec.name, rec.employee_id.name, today, current_user.name
                )
            )

    def action_revoke_exonerated(self):
        """Revoke suspension upon employee exoneration, restore access, and flag full backpay."""
        today = fields.Date.context_today(self)
        for rec in self:
            current_user = self.env.user
            if not rec.can_user_approve_suspension:
                raise UserError(_('Authority Restriction: Only the designated authority can revoke this suspension.'))

            vals = {
                'state': 'revoked',
                'reinstatement_date': today,
            }
            if rec.suspension_type == 'without_pay':
                vals['backpay_status'] = 'pending_payroll'
                vals['backpay_days_count'] = rec.working_days_count

            rec.write(vals)
            rec.employee_id.sudo().is_suspended = False
            rec.employee_id.sudo().suspension_type = False
            if rec.employee_id.user_id:
                rec.employee_id.user_id.sudo().write({'active': True})
            
            rec.message_post(
                body=_('Suspension revoked following executive exoneration. System access restored and %d working days flagged for payroll backpay.')
                % rec.working_days_count
            )
            rec.case_id.message_post(
                body=_('Suspension %s REVOKED (Exonerated) by %s. Employee %s cleared of all charges.')
                % (rec.name, current_user.name, rec.employee_id.name)
            )

    def action_convert_to_dismissal(self):
        """Convert an active suspension to a dismissal (CPCO, CEO, Admin)."""
        user = self.env.user
        has_permission = (
            user.has_group('discipline_management.group_discipline_cpco') or
            user.has_group('discipline_management.group_discipline_ceo') or
            user.has_group('discipline_management.group_discipline_admin') or
            user.has_group('base.group_system')
        )
        if not has_permission:
            raise UserError(_('Authority Restriction: Only CPCO, CEO, or HR Administrators can convert a suspension to dismissal.'))

        for rec in self:
            if rec.state not in ['active', 'extended']:
                raise UserError(_('Suspension must be in Active or Extended state to be converted to dismissal.'))
            rec.employee_id.is_suspended = False
            rec.employee_id.suspension_type = False
            rec.write({
                'state': 'converted_dismissal',
                'backpay_status': 'not_applicable',
            })
            if rec.case_id:
                rec.case_id._process_employee_dismissal()
                rec.case_id.message_post(
                    body=_('Suspension %s converted to DISMISSAL for employee %s by %s. Employee archived and separated.')
                    % (rec.name, rec.employee_id.name, user.name)
                )

    @api.model
    def _cron_check_suspension_expiry(self):
        """Automated tracking & authority notification prior to or on expiry (No auto-reactivation)."""
        today = fields.Date.context_today(self)
        alert_date = today + timedelta(days=3)
        expiring_suspensions = self.search([
            ('state', 'in', ['active', 'extended']),
            ('end_date', '<=', alert_date)
        ])
        EmpModel = self.env['hr.employee'].sudo()
        cpco_user = EmpModel.get_cpco_user()
        sec_user = EmpModel.get_secretary_user()
        ceo_user = EmpModel.get_ceo_user()

        for susp in expiring_suspensions:
            is_expired = susp.end_date <= today
            notice_type = "SUSPENSION EXPIRED" if is_expired else "SUSPENSION EXPIRING SOON"
            msg = _(
                "<strong>%s ALERT: %s</strong><br/>"
                "Employee: <strong>%s</strong> (%s)<br/>"
                "End Date: <strong>%s</strong> (%s working days total)<br/>"
                "Designated Authority: <strong>%s</strong><br/>"
                "<em>Action Required: Please review the case file and execute formal reinstatement or extension.</em>"
            ) % (
                notice_type,
                susp.name,
                susp.employee_id.name,
                susp.department_id.name or 'N/A',
                susp.end_date,
                susp.working_days_count,
                susp.suspending_authority.upper(),
            )
            susp.message_post(body=msg, message_type='notification')

            # Determine which authority user to notify via Discuss
            target_user = False
            if susp.suspending_authority == 'cpco':
                target_user = cpco_user
            elif susp.suspending_authority == 'pomd':
                target_user = sec_user
            elif susp.suspending_authority == 'bod':
                target_user = ceo_user

            if target_user and target_user.partner_id:
                try:
                    admin_partner = self.env.ref('base.partner_admin', raise_if_not_found=False) or target_user.partner_id
                    channel = self.env['discuss.channel'].sudo().channel_get(
                        partners_to=[admin_partner.id, target_user.partner_id.id]
                    )
                    if channel and channel.get('id'):
                        ch = self.env['discuss.channel'].sudo().browse(channel['id'])
                        ch.message_post(body=msg, message_type='comment', subtype_xmlid='mail.mt_comment')
                except Exception as e:
                    _logger.warning("Failed to send expiry alert to %s: %s", target_user.name, e)
