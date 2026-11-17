# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from markupsafe import Markup
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
    employee_name = fields.Char(string='Employee Name', compute='_compute_employee_details', store=True, readonly=True)
    employee_identification = fields.Char(string='Employee ID No', compute='_compute_employee_details', store=True, readonly=True)
    department_id = fields.Many2one('hr.department', string='Department', compute='_compute_employee_details', store=True, readonly=True)
    job_id = fields.Many2one('hr.job', string='Job Position', compute='_compute_employee_details', store=True, readonly=True)
    job_title = fields.Char(string='Job Position Title', compute='_compute_employee_details', store=True, readonly=True)

    @api.depends('employee_id', 'case_id', 'case_id.employee_id')
    def _compute_employee_details(self):
        for rec in self:
            emp = rec.sudo().employee_id or (rec.case_id and rec.case_id.sudo().employee_id)
            if emp:
                rec.department_id = emp.department_id.id if emp.department_id else False
                rec.job_id = emp.job_id.id if emp.job_id else False
                rec.job_title = emp.job_id.name or emp.job_title or ''
                rec.employee_name = emp.name or ''
                rec.employee_identification = emp.identification_id or emp.barcode or ''
            else:
                rec.department_id = False
                rec.job_id = False
                rec.job_title = ''
                rec.employee_name = ''
                rec.employee_identification = ''

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
    days_remaining = fields.Integer(string='Remaining Working Days', compute='_compute_days_remaining')

    # Initiation & Authority Matrix Mapping
    initiating_unit = fields.Selection([
        ('directorate', 'Respective Directorate'),
        ('audit', 'Audit Directorate'),
        ('pomd', 'People Operations Management Directorate (POMD)'),
        ('ceo', 'Executive Office (CEO Directive)'),
    ], string='Initiating Unit Key', default='directorate', required=True, readonly=True, tracking=True)
    initiating_unit_name = fields.Char(
        string='Initiating Unit',
        compute='_compute_initiating_unit_name',
        store=True,
        readonly=True
    )

    @api.depends('case_id', 'case_id.operating_unit_id', 'case_id.department_id', 'case_id.initiator_type', 'case_id.director_id')
    def _compute_initiating_unit_name(self):
        for rec in self:
            c = rec.sudo().case_id
            if not c:
                rec.initiating_unit_name = ''
                continue
            if getattr(c, 'initiator_type', False) == 'audit' or rec.is_rmcd_or_iad:
                rec.initiating_unit_name = _('Internal Audit Directorate (IAD)')
            elif c.operating_unit_id:
                rec.initiating_unit_name = c.operating_unit_id.name
            elif c.department_id:
                rec.initiating_unit_name = c.department_id.name
            elif c.director_id and c.director_id.department_id:
                rec.initiating_unit_name = c.director_id.department_id.name
            else:
                rec.initiating_unit_name = _('Initiating Directorate')

    is_rmcd_or_iad = fields.Boolean(string='Is RMCD or IAD Staff', compute='_compute_is_rmcd_or_iad', store=True)
    is_managerial = fields.Boolean(string='Is Managerial Staff', compute='_compute_is_managerial', store=True, readonly=True)

    @api.depends('employee_id', 'employee_id.is_managerial', 'case_id', 'case_id.employee_id', 'case_id.staff_category', 'case_id.is_managerial')
    def _compute_is_managerial(self):
        for rec in self:
            emp = rec.sudo().employee_id or (rec.case_id and rec.case_id.sudo().employee_id)
            is_case_mgr = bool(rec.case_id and (rec.case_id.staff_category == 'managerial' or rec.case_id.is_managerial))
            is_emp_mgr = bool(emp and (emp.is_managerial or self.env['discipline.case']._is_employee_managerial(emp)))
            rec.is_managerial = bool(is_case_mgr or is_emp_mgr)

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

    @api.depends('employee_id', 'case_id', 'case_id.employee_id')
    def _compute_is_rmcd_or_iad(self):
        for rec in self:
            emp = rec.sudo().employee_id or (rec.case_id and rec.case_id.sudo().employee_id)
            dept_name = (emp.department_id.name or '').lower() if emp and emp.department_id else ''
            ou_name = (emp.default_operating_unit_id.name or '').lower() if emp and hasattr(emp, 'default_operating_unit_id') and emp.default_operating_unit_id else ''
            rec.is_rmcd_or_iad = any(kw in dept_name or kw in ou_name for kw in ['risk', 'compliance', 'audit', 'rmcd', 'iad'])

    @api.depends('employee_id', 'employee_id.is_managerial', 'is_managerial', 'is_rmcd_or_iad', 'case_id', 'case_id.employee_id', 'case_id.staff_category', 'case_id.is_managerial')
    def _compute_suspending_authority(self):
        for rec in self:
            emp = rec.sudo().employee_id or (rec.case_id and rec.case_id.sudo().employee_id)
            is_case_mgr = bool(rec.case_id and (rec.case_id.staff_category == 'managerial' or rec.case_id.is_managerial))
            is_emp_mgr = bool(emp and (emp.is_managerial or self.env['discipline.case']._is_employee_managerial(emp)))
            is_mgr = rec.is_managerial or is_case_mgr or is_emp_mgr
            if rec.is_rmcd_or_iad:
                rec.suspending_authority = 'bod'
            elif is_mgr:
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
                calc_start = today
                if rec.state in ['draft', 'pending_approval', 'referred_bod']:
                    calc_start = rec.start_date

                if calc_start > rec.end_date:
                    rec.days_remaining = 0
                elif rec.state in ['active', 'extended', 'draft', 'pending_approval', 'referred_bod']:
                    day_count = 0
                    curr = calc_start
                    while curr <= rec.end_date:
                        if curr.weekday() < 5:  # Monday to Friday
                            day_count += 1
                        curr += timedelta(days=1)
                    rec.days_remaining = day_count
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

    @api.model
    def calculate_suspension_end_date(self, start_date=None, working_days=None):
        """
        Calculate suspension end date strictly based on working days (Monday - Friday).
        Working days duration is dynamically synchronized from discipline.max_suspension_days setting (default: 30).
        """
        if not start_date:
            start_date = fields.Date.context_today(self)
        if isinstance(start_date, str):
            start_date = fields.Date.from_string(start_date)
        if working_days is None:
            ICP = self.env['ir.config_parameter'].sudo()
            working_days = int(ICP.get_param('discipline.max_suspension_days', 30))

        if working_days <= 0:
            return start_date

        curr = start_date
        counted = 0
        while counted < working_days:
            if curr.weekday() < 5:  # Monday to Friday
                counted += 1
                if counted == working_days:
                    break
            curr += timedelta(days=1)
        return curr

    @api.onchange('start_date')
    def _onchange_start_date(self):
        if self.start_date and (not self.end_date or self.state == 'draft'):
            self.end_date = self.calculate_suspension_end_date(self.start_date)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('discipline.suspension') or _('New')
            if vals.get('start_date') and not vals.get('end_date'):
                vals['end_date'] = self.calculate_suspension_end_date(vals['start_date'])
        return super().create(vals_list)

    def write(self, vals):
        protected_fields = {'suspension_type', 'start_date', 'end_date', 'case_id', 'initiating_unit'}
        if not self.env.su and any(f in vals for f in protected_fields):
            for rec in self:
                if rec.state in ['active', 'extended', 'completed', 'converted_dismissal', 'revoked']:
                    if not (self.env.user.has_group('discipline_management.group_discipline_admin') or self.env.user.has_group('base.group_system')):
                        raise UserError(_('Cannot modify core suspension parameters while the suspension is active or finalized.'))
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.state in ['active', 'extended', 'completed', 'converted_dismissal', 'revoked']:
                raise UserError(_('Active Suspension Protection: Active or finalized suspensions cannot be deleted for legal auditability.'))
            user = self.env.user
            is_admin = user.has_group('discipline_management.group_discipline_admin') or user.has_group('base.group_system')
            is_creator = bool(rec.create_uid and rec.create_uid.id == user.id)
            if not (is_admin or is_creator or self.env.su):
                raise UserError(_('Permission Denied: You are not authorized to delete suspension %s.') % rec.name)
        return super().unlink()

    can_user_approve_suspension = fields.Boolean(
        string='Can User Approve Suspension',
        compute='_compute_can_user_approve_suspension'
    )

    def _compute_can_user_approve_suspension(self):
        user = self.env.user
        EmpModel = self.env['hr.employee'].sudo()
        cpco_user = EmpModel.get_cpco_user()
        sec_user = EmpModel.get_secretary_user()
        pomd_user = EmpModel.get_pomd_user()
        is_cpco = bool((cpco_user and user.id == cpco_user.id) or user.has_group('discipline_management.group_discipline_cpco'))
        is_pomd = bool(
            (sec_user and user.id == sec_user.id) or
            (pomd_user and user.id == pomd_user.id) or
            user.has_group('discipline_management.group_discipline_pomd') or
            user.has_group('discipline_management.group_discipline_pomd_director') or
            user.has_group('discipline_management.group_discipline_secretary')
        )
        is_ceo = user.has_group('discipline_management.group_discipline_ceo')
        is_system_admin = bool(user._is_superuser() or user.has_group('discipline_management.group_discipline_admin') or user.has_group('base.group_system'))
        for rec in self:
            can_approve = False
            # CEO is an executive oversight role; operational activation of suspension letters and user account deactivations
            # is strictly handled by POMD (for non-managerial) and CPCO (for managerial).
            if is_ceo and not is_system_admin:
                can_approve = False
            elif is_system_admin:
                can_approve = True
            elif rec.suspending_authority == 'cpco':
                # For managerial cases, ONLY CPCO can perform / activate suspension, NOT POMD and NOT CEO
                can_approve = bool(is_cpco and not is_ceo)
            elif rec.suspending_authority == 'pomd':
                # Non-managerial cases can be approved by POMD or CPCO
                can_approve = bool((is_pomd or is_cpco) and not is_ceo)
            elif rec.suspending_authority == 'bod':
                # BOD suspensions are operationalized by CPCO / Admin
                can_approve = bool((is_cpco and not is_ceo) or is_system_admin)
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

    @api.model
    def get_ethiopic_sadiss_font_css(self):
        """Returns base64 Ethiopic font CSS for QWeb PDF rendering."""
        return self.env['discipline.case'].get_ethiopic_sadiss_font_css()

    def get_salutation_label(self):
        """Returns formal Ethiopian salutation based on gender (Ato / W/ro / W/t)."""
        self.ensure_one()
        emp = self.sudo().employee_id
        gender = getattr(emp, 'gender', False)
        if gender == 'male':
            return 'Ato'
        elif gender == 'female':
            marital = getattr(emp, 'marital', False)
            return 'W/t' if marital == 'single' else 'W/ro'
        return 'Ato/W/ro'

    def get_salutation_title_and_first_name(self):
        """Returns title and first name (e.g. 'Ato Samuel')."""
        self.ensure_one()
        sal = self.get_salutation_label()
        emp = self.sudo().employee_id
        emp_n = emp.name if emp and emp.name else (self.employee_name or '')
        first_name = emp_n.split()[0] if emp_n else _('Employee')
        return f"{sal} {first_name}"

    def action_print_suspension_letter(self):
        """Print official Suspension Notice Letter PDF."""
        self.ensure_one()
        return self.env.ref('discipline_management.action_report_suspension_letter').sudo().report_action(self.sudo())

    # Workflow Actions
    def action_submit_for_approval(self):
        for rec in self:
            if rec.suspending_authority == 'bod':
                rec.write({'state': 'referred_bod'})
                rec.case_id.sudo().message_post(body=_('Suspension case for RMCD/IAD staff referred to Board of Directors (BOD) / Executive Office for review.'))
            else:
                rec.write({'state': 'pending_approval'})
                rec.case_id.sudo().message_post(body=_('Suspension %s submitted for approval to %s.') % (rec.name, rec.suspending_authority.upper()))
            
            # Send Discuss notifications to CPCO, POMD, and Audit (if audit)
            rec._send_suspension_submitted_discuss_notification()

    def _send_suspension_submitted_discuss_notification(self):
        """Send Discuss notification when suspension is submitted for approval."""
        for rec in self:
            EmpModel = self.env['hr.employee'].sudo()
            cpco_user = EmpModel.get_cpco_user()
            pomd_user = EmpModel.get_pomd_user()
            sec_user = EmpModel.get_secretary_user()
            audit_user = EmpModel.get_audit_director_user()
            ceo_user = EmpModel.get_ceo_user()
            emp = rec.sudo().employee_id
            emp_name = emp.name if emp else _('Employee')
            dept_name = rec.department_id.name or 'N/A'
            sender_partner = self.env.user.partner_id

            recipients = [
                ('CPCO', cpco_user),
                ('POMD Director', pomd_user),
                ('Committee Secretary', sec_user),
            ]
            if rec.is_rmcd_or_iad or (rec.case_id and getattr(rec.case_id.sudo(), 'initiator_type', False) == 'audit'):
                recipients.append(('Internal Audit Director', audit_user))
                recipients.append(('CEO', ceo_user))

            msg_body = Markup(
                f"<p><strong>SUSPENSION APPROVAL REQUEST: {rec.name}</strong></p>"
                f"<p>Dear Authority,</p>"
                f"<p>A disciplinary suspension has been prepared and submitted for your review and formal authorization:</p>"
                f"<ul>"
                f"<li><strong>Subject Employee:</strong> {emp_name} ({dept_name})</li>"
                f"<li><strong>Designated Authority:</strong> {dict(rec._fields['suspending_authority'].selection).get(rec.suspending_authority)}</li>"
                f"<li><strong>Effective Period:</strong> {rec.start_date} to {rec.end_date} ({rec.working_days_count} Working Days)</li>"
                f"<li><strong>Grounds:</strong> {rec.reason or 'Precautionary suspension request.'}</li>"
                f"<li><strong>Disciplinary Case:</strong> {rec.case_id.name if rec.case_id else 'N/A'}</li>"
                f"</ul>"
                f"<p>Please access Bunna Bank ERP under <strong>Suspensions</strong> to review and activate this suspension.</p>"
            )
            self._post_discuss_to_recipients(recipients, sender_partner, msg_body)

    def action_activate_suspension(self):
        """Activate suspension, validate approval authority, and deactivate ERP user account."""
        for rec in self:
            current_user = self.env.user
            emp = rec.sudo().employee_id
            emp_name = emp.name if emp else _('Employee')
            if rec.suspending_authority == 'bod' and not rec.bod_resolution_number:
                raise UserError(_('BOD Resolution Reference must be recorded prior to activating suspension for RMCD/IAD personnel.'))
            
            if not rec.can_user_approve_suspension:
                if rec.suspending_authority == 'cpco':
                    raise UserError(_('Authority Restriction: Suspensions for managerial employees must be authorized and performed by the Chief People & Culture Officer (CPCO), not POMD.'))
                elif rec.suspending_authority == 'pomd':
                    raise UserError(_('Authority Restriction: Non-managerial suspensions must be approved by People Operations Directorate (POMD).'))
                elif rec.suspending_authority == 'bod':
                    raise UserError(_('Authority Restriction: RMCD/IAD suspensions require Executive Office (CEO) authorization.'))
                else:
                    raise UserError(_('Authority Restriction: You do not have authorization to approve this suspension.'))

            rec.write({'state': 'active'})
            if emp:
                emp.write({'is_suspended': True, 'suspension_type': rec.suspension_type})
                # Deactivate employee ERP user account during active suspension
                if emp.user_id:
                    emp.user_id.sudo().write({'active': False})
                    rec.message_post(body=_('Employee ERP user account (%s) deactivated for the duration of the suspension.') % emp.user_id.name)

            rec.case_id.sudo().message_post(
                body=_('Suspension %s activated for employee %s (%s) from %s to %s by %s.') % (
                    rec.name, emp_name, rec.suspension_type, rec.start_date, rec.end_date, current_user.name
                )
            )

            # Send Discuss notifications to stakeholders: CPCO, POMD, Audit, Director, Coach, Employee
            rec._send_suspension_activated_discuss_notification()

    def _resolve_suspension_hierarchy_recipients(self):
        """
        Resolve the 5 core management stakeholders for suspension notifications:
        1. Direct Coach
        2. Directorate / District Director
        3. Deputy Chief (if exists)
        4. Employee Chief (Respective Sector Chief Officer)
        5. CEO
        """
        self.ensure_one()
        EmpModel = self.env['hr.employee'].sudo()
        emp = self.sudo().employee_id
        if not emp:
            return False, False, False, False, EmpModel.get_ceo_user()

        chain = emp.get_supervisor_chain()

        # 1. Direct Coach
        coach_emp = emp.coach_id or emp.parent_id
        coach_user = coach_emp.user_id if coach_emp and coach_emp.user_id else False

        # 2. Director
        director_emp = False
        director_user = self.case_id.sudo().director_id.user_id if self.case_id and self.case_id.sudo().director_id else False
        if not director_user:
            for m in chain:
                j = (m.job_id.name or '').lower() if m.job_id else ''
                if ('director' in j or getattr(m, 'executive_level', False) == 'director') and 'deputy' not in j:
                    director_emp = m
                    break
            if not director_emp and emp.department_id and emp.department_id.manager_id:
                director_emp = emp.department_id.manager_id
            director_user = director_emp.user_id if director_emp and director_emp.user_id else False

        # 3. Deputy Chief (if exist)
        deputy_chief_emp = False
        for m in chain:
            j = (m.job_id.name or '').lower() if m.job_id else ''
            if 'deputy' in j and 'chief' in j:
                deputy_chief_emp = m
                break
        if not deputy_chief_emp and emp.department_id:
            dept = emp.department_id
            while dept:
                dm = dept.manager_id
                if dm and dm.job_id and 'deputy' in (dm.job_id.name or '').lower() and 'chief' in (dm.job_id.name or '').lower():
                    deputy_chief_emp = dm
                    break
                dept = dept.parent_id
        deputy_chief_user = deputy_chief_emp.user_id if deputy_chief_emp and deputy_chief_emp.user_id else False

        # 4. Employee Chief
        chief_emp = False
        chief_user = self.case_id.sudo().chief_id.user_id if self.case_id and self.case_id.sudo().chief_id else False
        if not chief_user:
            for m in chain:
                j = (m.job_id.name or '').lower() if m.job_id else ''
                if 'chief' in j and 'deputy' not in j and 'ceo' not in j:
                    chief_emp = m
                    break
            if not chief_emp and emp.department_id:
                dept = emp.department_id
                while dept:
                    dm = dept.manager_id
                    if dm and dm.job_id and 'chief' in (dm.job_id.name or '').lower() and 'deputy' not in (dm.job_id.name or '').lower() and 'ceo' not in (dm.job_id.name or '').lower():
                        chief_emp = dm
                        break
                    dept = dept.parent_id
            chief_user = chief_emp.user_id if chief_emp and chief_emp.user_id else False

        # Fallback for Employee Chief if not in department chain
        if not chief_user:
            chief_user = EmpModel.get_cpco_user()

        # 5. CEO
        ceo_user = EmpModel.get_ceo_user()

        return coach_user, director_user, deputy_chief_user, chief_user, ceo_user

    def _build_suspension_activated_message(self, role_key, target_user):
        """Construct role-tailored notification message for suspension activation."""
        self.ensure_one()
        rec = self
        recipient_name = (target_user.partner_id.name or target_user.name or _('Colleague')).strip()
        emp = rec.sudo().employee_id
        emp_name = emp.name if emp else (rec.employee_name or _('Employee'))
        emp_job = rec.job_title or (emp.job_id.name if emp and emp.job_id else '') or ''
        dept_name = rec.department_id.name if rec.department_id else (emp.department_id.name if emp and emp.department_id else 'N/A')
        case_name = rec.case_id.name if rec.case_id else 'N/A'
        susp_type_label = dict(rec._fields['suspension_type'].selection).get(rec.suspension_type) or rec.suspension_type
        auth_label = dict(rec._fields['suspending_authority'].selection).get(rec.suspending_authority) or rec.suspending_authority
        working_days = rec.working_days_count or 30
        grounds_text = rec.reason or _('Precautionary suspension pending disciplinary proceedings.')

        if role_key == 'ceo':
            return Markup(
                f"<p><strong>EXECUTIVE DIRECTIVE: PRECAUTIONARY SUSPENSION ENFORCEMENT</strong></p>"
                f"<p>Dear {recipient_name},</p>"
                f"<p>This is to formally confirm that in accordance with executive governance directives and Disciplinary Case <strong>{case_name}</strong>, formal suspension has been activated for the following employee:</p>"
                f"<ul>"
                f"<li><strong>Employee:</strong> {emp_name}" + (f" ({emp_job}, {dept_name})" if emp_job else f" ({dept_name})") + f"</li>"
                f"<li><strong>Suspension Ref:</strong> {rec.name}</li>"
                f"<li><strong>Duration &amp; Period:</strong> {rec.start_date} to {rec.end_date} (<strong>{working_days} Working Days</strong>)</li>"
                f"<li><strong>Suspension Type:</strong> {susp_type_label}</li>"
                f"<li><strong>Suspending Authority:</strong> {auth_label}</li>"
                f"<li><strong>Grounds:</strong> {grounds_text}</li>"
                f"</ul>"
                f"<p><strong>Executive Control Actions Executed:</strong></p>"
                f"<ol>"
                f"<li><strong>System Deactivation:</strong> Employee ERP, core banking, and network access credentials have been deactivated immediately.</li>"
                f"<li><strong>Operational Safeguard:</strong> District Director and CPCO have been instructed to ensure physical asset custody and assign acting operational coverage.</li>"
                f"<li><strong>Investigation Referral:</strong> The Internal Audit / Disciplinary Investigation Directorate has full unimpeded access to commence forensic inquiries without administrative interference.</li>"
                f"</ol>"
                f"<p><em>The Executive Office will receive formal progress briefings as audit findings and disciplinary committee hearings conclude.</em></p>"
            )

        elif role_key in ('chief', 'deputy_chief'):
            return Markup(
                f"<p><strong>DIVISIONAL NOTICE: EMPLOYEE SUSPENSION &amp; INTERIM CONTINUITY DIRECTIVE</strong></p>"
                f"<p>Dear {recipient_name},</p>"
                f"<p>Please be advised that an employee within your division/sector has been formally placed on suspension pending disciplinary proceedings:</p>"
                f"<ul>"
                f"<li><strong>Employee:</strong> {emp_name}" + (f" — {emp_job} ({dept_name})" if emp_job else f" ({dept_name})") + f"</li>"
                f"<li><strong>Suspension Ref:</strong> {rec.name} | <strong>Disciplinary Case:</strong> {case_name}</li>"
                f"<li><strong>Effective Period:</strong> {rec.start_date} to {rec.end_date} (<strong>{working_days} Working Days</strong>)</li>"
                f"<li><strong>Type:</strong> {susp_type_label}</li>"
                f"<li><strong>Suspending Authority:</strong> {auth_label}</li>"
                f"</ul>"
                f"<p><strong>Required Divisional Directives:</strong></p>"
                f"<ul>"
                f"<li>Please coordinate with the Department Director to ensure seamless delegation of managerial authorities and designate an Acting Officer.</li>"
                f"<li>Enterprise ERP user account has been deactivated to safeguard institutional assets.</li>"
                f"</ul>"
            )

        elif role_key == 'director':
            return Markup(
                f"<p><strong>OPERATIONAL DIRECTIVE: EMPLOYEE SUSPENSION &amp; ASSET SAFEGUARDING</strong></p>"
                f"<p>Dear {recipient_name},</p>"
                f"<p>An official suspension order has been activated for an employee under your direct organizational supervision:</p>"
                f"<ul>"
                f"<li><strong>Employee:</strong> {emp_name}" + (f" ({emp_job})" if emp_job else "") + f"</li>"
                f"<li><strong>Department / Unit:</strong> {dept_name}</li>"
                f"<li><strong>Suspension Ref:</strong> {rec.name} | <strong>Disciplinary Case:</strong> {case_name}</li>"
                f"<li><strong>Effective Period:</strong> {rec.start_date} to {rec.end_date} (<strong>{working_days} Working Days</strong>)</li>"
                f"<li><strong>Terms:</strong> {susp_type_label}</li>"
                f"<li><strong>Suspending Authority:</strong> {auth_label}</li>"
                f"</ul>"
                f"<p><strong>Immediate Actions Required by Director:</strong></p>"
                f"<ol>"
                f"<li><strong>Asset &amp; Facility Custody:</strong> Immediately secure all official bank property, branch keys, security tokens, official stamps, and files held by the employee.</li>"
                f"<li><strong>Premises Restriction:</strong> Ensure the suspended employee does not enter branch/office premises or engage in official bank duties during the suspension period.</li>"
                f"<li><strong>Acting Arrangement:</strong> Immediately assign and communicate an Acting Officer to maintain normal branch and customer service operations.</li>"
                f"</ol>"
            )

        elif role_key == 'coach':
            return Markup(
                f"<p><strong>SUPERVISORY NOTICE: STAFF SUSPENSION &amp; WORKFLOW REALLOCATION</strong></p>"
                f"<p>Dear {recipient_name},</p>"
                f"<p>Please be informed that <strong>{emp_name}</strong>" + (f" ({emp_job})" if emp_job else "") + f" has been formally placed on suspension starting from <strong>{rec.start_date}</strong> until <strong>{rec.end_date}</strong> (<strong>{working_days} Working Days</strong>) under Disciplinary Reference <strong>{case_name}</strong>.</p>"
                f"<p><strong>Immediate Supervisory Steps:</strong></p>"
                f"<ul>"
                f"<li>Reallocate all active assignments, customer portfolios, and pending approval workflows to other qualified team members.</li>"
                f"<li>Mark the employee's attendance record as <em>Suspension</em> for the duration.</li>"
                f"<li>Promptly notify HR / CPCO if there are unresolved handovers or operational dependencies.</li>"
                f"</ul>"
            )

        elif role_key == 'audit':
            return Markup(
                f"<p><strong>INVESTIGATION BRIEFING: SUSPENSION ACTIVATED FOR AUDIT INQUIRY</strong></p>"
                f"<p>Dear {recipient_name},</p>"
                f"<p>In connection with Case <strong>{case_name}</strong> and audit proceedings, formal precautionary suspension has been activated:</p>"
                f"<ul>"
                f"<li><strong>Subject Employee:</strong> {emp_name}" + (f" ({emp_job}, {dept_name})" if emp_job else f" ({dept_name})") + f"</li>"
                f"<li><strong>Suspension Window:</strong> {rec.start_date} to {rec.end_date} (<strong>{working_days} Working Days</strong>)</li>"
                f"<li><strong>Suspending Authority:</strong> {auth_label}</li>"
                f"<li><strong>System Access:</strong> Deactivated in ERP and Core Banking</li>"
                f"</ul>"
                f"<p>The audit team may now proceed with necessary forensic inquiries, field verifications, and evidence gathering without administrative obstruction.</p>"
            )

        elif role_key == 'employee':
            return Markup(
                f"<p><strong>FORMAL NOTICE OF SUSPENSION</strong></p>"
                f"<p>Dear {recipient_name},</p>"
                f"<p>You are hereby formally notified that you have been placed on suspension effective from <strong>{rec.start_date}</strong> to <strong>{rec.end_date}</strong> (<strong>{working_days} Working Days</strong>) regarding Disciplinary Case <strong>{case_name}</strong>.</p>"
                f"<ul>"
                f"<li><strong>Suspension Type:</strong> {susp_type_label}</li>"
                f"<li><strong>Reason / Offense:</strong> {grounds_text}</li>"
                f"<li><strong>Suspending Authority:</strong> {auth_label}</li>"
                f"</ul>"
                f"<p><strong>Directives During Suspension:</strong></p>"
                f"<ol>"
                f"<li>You are strictly prohibited from entering bank premises or accessing bank systems without prior written authorization.</li>"
                f"<li>You must remain available at your registered contact details to attend summons, interviews, or hearings when requested by the investigation committee or CPCO.</li>"
                f"<li>You retain all rights to submit responses, evidence, and appeals in accordance with the Bank's Disciplinary Policy.</li>"
                f"</ol>"
            )

        else:
            return Markup(
                f"<p><strong>OFFICIAL SUSPENSION NOTICE: {rec.name}</strong></p>"
                f"<p>Dear {recipient_name},</p>"
                f"<p>This is an official notice that an employee under your reporting line / executive purview has been placed on formal suspension:</p>"
                f"<ul>"
                f"<li><strong>Employee:</strong> {emp_name} ({dept_name})</li>"
                f"<li><strong>Type:</strong> {susp_type_label}</li>"
                f"<li><strong>Effective Period:</strong> {rec.start_date} to {rec.end_date} (<strong>{working_days} Working Days</strong>)</li>"
                f"<li><strong>Suspending Authority:</strong> {auth_label}</li>"
                f"<li><strong>Grounds:</strong> {grounds_text}</li>"
                f"<li><strong>Disciplinary Case:</strong> {case_name}</li>"
                f"</ul>"
                f"<p>The employee's ERP user account has been deactivated for the duration of the suspension.</p>"
            )

    def _build_suspension_reinstated_message(self, role_key, target_user):
        """Construct role-tailored notification message for return to duty / reinstatement."""
        self.ensure_one()
        rec = self
        recipient_name = (target_user.partner_id.name or target_user.name or _('Colleague')).strip()
        emp = rec.sudo().employee_id
        emp_name = emp.name if emp else (rec.employee_name or _('Employee'))
        dept_name = rec.department_id.name if rec.department_id else (emp.department_id.name if emp and emp.department_id else 'N/A')
        case_name = rec.case_id.name if rec.case_id else 'N/A'
        reinstatement_dt = rec.reinstatement_date or fields.Date.context_today(self)

        if role_key == 'ceo':
            return Markup(
                f"<p><strong>EXECUTIVE BRIEFING: SUSPENSION ENDED — RETURN TO DUTY</strong></p>"
                f"<p>Dear {recipient_name},</p>"
                f"<p>This is to formally brief the Executive Office that employee <strong>{emp_name}</strong> ({dept_name}) has completed their suspension period and has been returned to active duty effective <strong>{reinstatement_dt}</strong> under Case <strong>{case_name}</strong>.</p>"
                f"<p>ERP system access and operational credentials have been restored in accordance with governance policies.</p>"
            )
        elif role_key == 'employee':
            return Markup(
                f"<p><strong>OFFICIAL NOTICE: RETURN TO ACTIVE DUTY</strong></p>"
                f"<p>Dear {recipient_name},</p>"
                f"<p>You are hereby notified that your suspension period under Case <strong>{case_name}</strong> has officially ended. You are instructed to report to active duty on <strong>{reinstatement_dt}</strong>.</p>"
                f"<p>Your ERP user access has been restored to active status.</p>"
            )
        else:
            return Markup(
                f"<p><strong>SUSPENSION ENDED — RETURN TO DUTY NOTICE: {rec.name}</strong></p>"
                f"<p>Dear {recipient_name},</p>"
                f"<p>This is an official notice that employee <strong>{emp_name}</strong> ({dept_name}) has completed their suspension period and has been formally returned to active duty.</p>"
                f"<ul>"
                f"<li><strong>Employee:</strong> {emp_name}</li>"
                f"<li><strong>Reinstatement Date:</strong> {reinstatement_dt}</li>"
                f"<li><strong>Disciplinary Case:</strong> {case_name}</li>"
                f"<li><strong>ERP Access:</strong> Restored to active status</li>"
                f"</ul>"
            )

    def _send_suspension_activated_discuss_notification(self):
        """
        Send direct Discuss message when POMD or CPCO clicks the Activate Suspension button.
        Notified stakeholders:
        - Direct Coach
        - Director
        - Deputy Chief (if exist)
        - Employee Chief
        - CEO
        Along with Subject Employee, CPCO, POMD, and Case Initiator.
        """
        for rec in self:
            EmpModel = self.env['hr.employee'].sudo()
            cpco_user = EmpModel.get_cpco_user()
            pomd_user = EmpModel.get_pomd_user()
            audit_user = EmpModel.get_audit_director_user()
            
            coach_user, director_user, deputy_chief_user, chief_user, ceo_user = rec._resolve_suspension_hierarchy_recipients()
            
            emp = rec.sudo().employee_id
            emp_user = emp.user_id if emp else False
            case_reported_by = rec.case_id.sudo().reported_by_id.user_id if rec.case_id and rec.case_id.sudo().reported_by_id and rec.case_id.sudo().reported_by_id.user_id else False
            sender_partner = self.env.user.partner_id

            recipient_specs = [
                ('coach', 'Direct Coach', coach_user),
                ('director', 'Director', director_user),
            ]
            if deputy_chief_user:
                recipient_specs.append(('deputy_chief', 'Deputy Chief', deputy_chief_user))
            recipient_specs.extend([
                ('chief', 'Employee Chief', chief_user),
                ('ceo', 'CEO', ceo_user),
                ('employee', 'Subject Employee', emp_user),
                ('initiator', 'Case Initiator', case_reported_by),
                ('cpco', 'CPCO', cpco_user),
                ('pomd', 'POMD Director', pomd_user),
            ])
            # Include Internal Audit Director when employee is RMCD/IAD or case is audit-initiated/investigated
            if rec.is_rmcd_or_iad or (rec.case_id and getattr(rec.case_id.sudo(), 'initiator_type', False) == 'audit') or rec.investigation_id:
                recipient_specs.append(('audit', 'Internal Audit Director', audit_user))

            recipients_with_msgs = []
            for role_key, role_label, target_user in recipient_specs:
                if target_user:
                    msg = rec._build_suspension_activated_message(role_key, target_user)
                    recipients_with_msgs.append((role_key, role_label, target_user, msg))

            self._post_discuss_to_recipients(recipients_with_msgs, sender_partner)

    def _send_suspension_reinstated_discuss_notification(self):
        """Send direct Discuss message when an employee is reinstated / returned to duty from suspension."""
        for rec in self:
            EmpModel = self.env['hr.employee'].sudo()
            cpco_user = EmpModel.get_cpco_user()
            pomd_user = EmpModel.get_pomd_user()
            audit_user = EmpModel.get_audit_director_user()
            
            coach_user, director_user, deputy_chief_user, chief_user, ceo_user = rec._resolve_suspension_hierarchy_recipients()
            
            emp = rec.sudo().employee_id
            emp_user = emp.user_id if emp else False
            case_reported_by = rec.case_id.sudo().reported_by_id.user_id if rec.case_id and rec.case_id.sudo().reported_by_id and rec.case_id.sudo().reported_by_id.user_id else False
            sender_partner = self.env.user.partner_id

            recipient_specs = [
                ('coach', 'Direct Coach', coach_user),
                ('director', 'Director', director_user),
            ]
            if deputy_chief_user:
                recipient_specs.append(('deputy_chief', 'Deputy Chief', deputy_chief_user))
            recipient_specs.extend([
                ('chief', 'Employee Chief', chief_user),
                ('ceo', 'CEO', ceo_user),
                ('employee', 'Subject Employee', emp_user),
                ('initiator', 'Case Initiator', case_reported_by),
                ('cpco', 'CPCO', cpco_user),
                ('pomd', 'POMD Director', pomd_user),
            ])
            if rec.is_rmcd_or_iad or (rec.case_id and getattr(rec.case_id.sudo(), 'initiator_type', False) == 'audit') or rec.investigation_id:
                recipient_specs.append(('audit', 'Internal Audit Director', audit_user))

            recipients_with_msgs = []
            for role_key, role_label, target_user in recipient_specs:
                if target_user:
                    msg = rec._build_suspension_reinstated_message(role_key, target_user)
                    recipients_with_msgs.append((role_key, role_label, target_user, msg))

            self._post_discuss_to_recipients(recipients_with_msgs, sender_partner)

    def _post_discuss_to_recipients(self, recipients, sender_partner, default_msg_body=None):
        """Helper to post Discuss direct message to multiple recipients cleanly."""
        seen_user_ids = set()
        for item in recipients:
            if len(item) == 4:
                role_key, role_label, target_user, msg_body = item
            elif len(item) == 3:
                role_label, target_user, msg_body = item
            else:
                role_label, target_user = item
                msg_body = default_msg_body

            if not target_user or not target_user.partner_id or target_user.id in seen_user_ids or target_user.id == self.env.user.id:
                continue
            seen_user_ids.add(target_user.id)
            try:
                channel = False
                if hasattr(self.env['discuss.channel'], '_get_or_create_chat'):
                    channel = self.env['discuss.channel'].sudo().with_user(self.env.user)._get_or_create_chat(
                        partners_to=[target_user.partner_id.id]
                    )
                elif hasattr(self.env['discuss.channel'], 'channel_get'):
                    channel_info = self.env['discuss.channel'].sudo().channel_get(
                        partners_to=[sender_partner.id, target_user.partner_id.id]
                    )
                    if channel_info and channel_info.get('id'):
                        channel = self.env['discuss.channel'].sudo().browse(channel_info['id'])

                if channel:
                    channel.message_post(
                        body=Markup(msg_body),
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                        author_id=sender_partner.id,
                    )
            except Exception as e:
                _logger.warning("Failed to send suspension notification to %s: %s", role_label, e)

    def action_lift_suspension_early(self):
        """Executive early lift: recall employee to active duty before parent case is finalized."""
        today = fields.Date.context_today(self)
        for rec in self:
            current_user = self.env.user
            if not rec.can_user_approve_suspension:
                raise UserError(_('Authority Restriction: Only the designated suspending authority (%s) or HR Administrator can lift this suspension early.') % rec.suspending_authority.upper())
            emp = rec.sudo().employee_id
            emp_name = emp.name if emp else _('Employee')
            vals = {
                'state': 'completed',
                'reinstatement_date': today,
                'reinstatement_notes': _('Precautionary suspension lifted early by %s on %s prior to parent case closure.') % (current_user.name, today),
            }
            if rec.suspension_type == 'without_pay':
                vals['backpay_status'] = 'pending_payroll'
                vals['backpay_days_count'] = rec.working_days_count

            rec.write(vals)
            if emp:
                emp.write({'is_suspended': False, 'suspension_type': False})
                if emp.user_id:
                    emp.user_id.sudo().write({'active': True})
            rec.message_post(body=_('Precautionary suspension lifted early by %s. Employee %s returned to active duty.') % (current_user.name, emp_name))
            rec.case_id.sudo().message_post(
                body=_('Precautionary suspension %s lifted early by %s. Employee %s returned to active duty while case proceedings continue.') % (
                    rec.name, current_user.name, emp_name
                )
            )
            rec._send_suspension_reinstated_discuss_notification()

    def action_reinstate_employee(self):
        """Reinstate employee, restore ERP user account, and flag backpay if unpaid suspension."""
        today = fields.Date.context_today(self)
        for rec in self:
            current_user = self.env.user
            emp = rec.sudo().employee_id
            emp_name = emp.name if emp else _('Employee')
            is_authorized = (
                self.env.is_superuser() or
                current_user.has_group('discipline_management.group_discipline_ceo') or
                current_user.has_group('discipline_management.group_discipline_admin') or
                current_user.has_group('base.group_system') or
                self.env.context.get('force_reinstate') or
                rec.can_user_approve_suspension
            )
            if not is_authorized:
                raise UserError(_('Authority Restriction: Only the designated authority can reinstate this employee.'))

            vals = {
                'state': 'completed',
                'reinstatement_date': today,
            }
            if rec.suspension_type == 'without_pay':
                vals['backpay_status'] = 'pending_payroll'
                vals['backpay_days_count'] = rec.working_days_count

            rec.write(vals)
            if emp:
                emp.write({
                    'active': True,
                    'is_suspended': False,
                    'suspension_type': False,
                    'departure_date': False,
                    'departure_reason_id': False,
                    'departure_description': False,
                })
                # Reactivate ERP user account
                if emp.user_id:
                    emp.user_id.sudo().write({'active': True})
                    rec.message_post(body=_('Employee ERP user account (%s) reactivated upon formal reinstatement.') % emp.user_id.name)

            rec.case_id.sudo().message_post(
                body=_('Suspension %s completed. Employee %s formally reinstated to active duty on %s by %s.') % (
                    rec.name, emp_name, today, current_user.name
                )
            )
            rec._send_suspension_reinstated_discuss_notification()

    def action_revoke_exonerated(self):
        """Revoke suspension upon employee exoneration, restore access, and flag full backpay."""
        today = fields.Date.context_today(self)
        for rec in self:
            current_user = self.env.user
            emp = rec.sudo().employee_id
            emp_name = emp.name if emp else _('Employee')
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
            if emp:
                emp.write({'is_suspended': False, 'suspension_type': False})
                if emp.user_id:
                    emp.user_id.sudo().write({'active': True})
            
            rec.message_post(
                body=_('Suspension revoked following executive exoneration. System access restored and %d working days flagged for payroll backpay.')
                % rec.working_days_count
            )
            rec.case_id.sudo().message_post(
                body=_('Suspension %s REVOKED (Exonerated) by %s. Employee %s cleared of all charges.')
                % (rec.name, current_user.name, emp_name)
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
            emp = rec.sudo().employee_id
            emp_name = emp.name if emp else _('Employee')
            if emp:
                emp.write({'is_suspended': False, 'suspension_type': False})
            rec.write({
                'state': 'converted_dismissal',
                'backpay_status': 'not_applicable',
            })
            if rec.case_id:
                rec.case_id.sudo()._process_employee_dismissal()
                rec.case_id.sudo().message_post(
                    body=_('Suspension %s converted to DISMISSAL for employee %s by %s. Employee archived and separated.')
                    % (rec.name, emp_name, user.name)
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
                (susp.sudo().employee_id.name if susp.employee_id else _('Employee')),
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
                    admin_user = self.env.ref('base.user_admin', raise_if_not_found=False) or self.env.user
                    channel = False
                    if hasattr(self.env['discuss.channel'], '_get_or_create_chat'):
                        channel = self.env['discuss.channel'].sudo().with_user(admin_user)._get_or_create_chat(
                            partners_to=[target_user.partner_id.id]
                        )
                    elif hasattr(self.env['discuss.channel'], 'channel_get'):
                        admin_partner = admin_user.partner_id
                        channel_info = self.env['discuss.channel'].sudo().channel_get(
                            partners_to=[admin_partner.id, target_user.partner_id.id]
                        )
                        if channel_info and channel_info.get('id'):
                            channel = self.env['discuss.channel'].sudo().browse(channel_info['id'])

                    if channel:
                        channel.message_post(body=msg, message_type='comment', subtype_xmlid='mail.mt_comment')
                except Exception as e:
                    _logger.warning("Failed to send expiry alert to %s: %s", target_user.name, e)
