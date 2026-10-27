# -*- coding: utf-8 -*-
from datetime import date
from markupsafe import Markup, escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from .eds_action_notification import (
    clear_action_activities, notify_action, push_action_popup, role_users,
)


class EdsNomination(models.Model):
    """Training nomination & multi-level approval.

    Nominations originate from approved TNA needs  or as documented
    ad-hoc exceptions with mandatory justification and L&D approval .
    The approval chain is configurable (Line Manager -> L&D, with an optional
    Budget/HR gate) and enforces segregation of duties (nominator != final
    approver). Capacity is capped per session ; excess nominations go
    waitlisted and are auto-promoted FIFO when a seat frees .
    Participants are notified on every status change  and can withdraw
    before the session start with a mandatory reason .
    """
    _name = 'eds.nomination'
    _description = 'Training Nomination'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    session_id = fields.Many2one('eds.session', string='Session', required=True,
                                 ondelete='cascade', index=True, tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True,
                                  index=True, tracking=True)
    job_position_id = fields.Many2one('hr.job', string='Job Position', related='employee_id.job_position',
                                      readonly=True)
    department_id = fields.Many2one('hr.department', string='Department',
                                    related='employee_id.department_id', readonly=True)
    work_unit_id = fields.Many2one('operating.unit', string='Work Unit',
                                   related='employee_id.default_operating_unit_id', readonly=True)
    nominated_by = fields.Many2one('res.users', string='Nominated By',
                                   default=lambda self: self.env.user, readonly=True, copy=False)
    nomination_type = fields.Selection([
        ('tna_based', 'TNA-Based'),
        ('ad_hoc', 'Ad-Hoc (Justified Exception)'),
    ], string='Nomination Type', default='tna_based', required=True, tracking=True)
    tna_entry_id = fields.Many2one(
        'eds.tna.entry', string='Source TNA Need',
        domain="[('state', 'in', ('approved', 'converted')), "
               "('delivery_mode', 'in', ('classroom', 'blended'))]",
        help='Required for TNA-based nominations - must reference an approved training '
             'need .')
    justification = fields.Text(
        string='Justification',
        help='Mandatory for ad-hoc nominations.')
    course_name = fields.Char(string='Program', related='session_id.program_name', readonly=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('line_manager_approved', 'Line Manager Approved'),
        ('lnd_approved', 'L&D Approved'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('withdrawn', 'Withdrawn'),
        ('declined', 'Declined by Employee'),
    ], string='Status', default='draft', required=True, tracking=True)

    # Approval actors (audit of the chain)
    line_manager_approved_by = fields.Many2one('res.users', string='Line Manager Approved By',
                                               readonly=True)
    lnd_approved_by = fields.Many2one('res.users', string='L&D Approved By', readonly=True)
    approved_by = fields.Many2one('res.users', string='Final Approved By', readonly=True)
    approved_date = fields.Datetime(string='Approval Date', readonly=True)
    rejected_by = fields.Many2one('res.users', string='Rejected By', readonly=True)
    rejected_reason = fields.Text(string='Rejection Reason')

    # Optional Budget/HR gate configured for nominations.
    budget_hr_required = fields.Boolean(
        string='Budget/HR Approval Required', compute='_compute_budget_hr_required')
    budget_hr_approved = fields.Boolean(string='Budget/HR Approved', readonly=True)
    budget_hr_approved_by = fields.Many2one('res.users', string='Budget/HR Approved By', readonly=True)
    budget_hr_approval_date = fields.Datetime(string='Budget/HR Approval Date', readonly=True)

    # Capacity / waitlist
    waitlisted = fields.Boolean(string='Waitlisted', default=False, tracking=True)
    waitlist_position = fields.Integer(string='Waitlist Position', default=0, readonly=True)
    enrollment_id = fields.Many2one('eds.enrollment', string='Enrollment', readonly=True)

    # Employee confirmation (portal / My Nominations - accept or decline)
    employee_confirmed = fields.Selection([
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('declined', 'Declined'),
    ], string='Employee Confirmation', default='pending', tracking=True)
    confirmation_date = fields.Datetime(string='Confirmation Date', readonly=True)
    decline_reason = fields.Text(string='Decline Reason')

    withdraw_reason = fields.Text(string='Withdrawal Reason')
    withdrawn_by = fields.Many2one('res.users', string='Withdrawn By', readonly=True)
    withdrawn_date = fields.Datetime(string='Withdrawal Date', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.constrains('session_id', 'employee_id', 'state')
    def _check_unique_active_nomination(self):
        for rec in self:
            if rec.session_id and rec.employee_id and rec.state not in ('cancelled', 'rejected', 'withdrawn', 'declined'):
                domain = [
                    ('session_id', '=', rec.session_id.id),
                    ('employee_id', '=', rec.employee_id.id),
                    ('state', 'not in', ('cancelled', 'rejected', 'withdrawn', 'declined')),
                    ('id', '!=', rec.id),
                ]
                if self.search_count(domain) > 0:
                    raise ValidationError(_("An active nomination already exists for employee '%s' in session '%s'.") % (
                        rec.employee_id.name, rec.session_id.name
                    ))

    @api.depends('session_id')
    def _compute_budget_hr_required(self):
        require_by_config = self._get_bool_param('eds.nomination_require_budget', False)
        for rec in self:
            rec.budget_hr_required = require_by_config

    @api.model
    def _get_bool_param(self, key, default):
        raw = self.env['ir.config_parameter'].sudo().get_param(key, '')
        if raw == '':
            return default
        return raw.strip().lower() in ('1', 'true', 'yes', 'on')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.nomination') or _('New')
            if vals.get('nomination_type') == 'tna_based' and not vals.get('justification') \
                    and vals.get('tna_entry_id'):
                entry = self.env['eds.tna.entry'].browse(vals['tna_entry_id'])
                vals['justification'] = entry.justification
        return super().create(vals_list)

    # ── Eligibility & guards ─────────────────────────────────────────────────
    def _check_submission_rules(self):
        """Validate TNA basis, justifications, and service tenure."""
        self.ensure_one()
        if self.nomination_type == 'tna_based':
            if not self.tna_entry_id:
                raise UserError(_('TNA-based nominations must reference an approved training need.'))
            if self.tna_entry_id.state not in ('approved', 'converted'):
                raise UserError(_('The referenced training need is not approved yet.'))
            if self.tna_entry_id.employee_id and self.tna_entry_id.employee_id != self.employee_id:
                raise UserError(_('The training need belongs to a different employee.'))
        elif self.nomination_type == 'ad_hoc' and not self.justification:
            raise UserError(_('Ad-hoc nominations require a mandatory justification and L&D approval.'))

        # Missing course prerequisites are advisory when invitations are sent.
        # Minimum service tenure remains an eligibility rule.
        course = self.session_id.course_id
        if course:
            if getattr(course, 'min_tenure_months', 0) > 0:
                emp = self.employee_id
                hire_date = getattr(emp, 'hire_date', False) or getattr(emp, 'join_date', False) or (emp.first_contract_date if hasattr(emp, 'first_contract_date') else False)
                if hire_date:
                    tenure_days = (date.today() - hire_date).days
                    tenure_months = tenure_days // 30
                    if tenure_months < course.min_tenure_months:
                        raise ValidationError(_(
                            "Tenure Eligibility Violation: Course '%s' requires minimum %d months of service tenure. %s has only %d months."
                        ) % (course.name, course.min_tenure_months, emp.name, tenure_months))

    def _require_group(self, group_xml_id):
        if not (self.env.su or self.env.user.has_group('employee_development_system.' + group_xml_id)):
            raise UserError(_('You do not have the required authority for this step.'))

    # ── Approval workflow  ───────────────────────────────────────
    def action_submit(self):
        """Draft -> Submitted (opens the approval chain)."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft nominations can be submitted.'))
            rec._check_submission_rules()
            rec.state = 'submitted'
            rec._notify(_('Nomination %s submitted for approval .') % rec.name)
            manager_user = rec.employee_id.parent_id.user_id if rec.employee_id.parent_id else False
            reviewers = manager_user or role_users(rec, 'group_eds_line_manager')
            clear_action_activities(rec)
            notify_action(
                rec, reviewers, _('Review training nomination'),
                _('Nomination %s for %s awaits line manager review.')
                % (rec.name, rec.employee_id.name))

    def action_line_manager_approve(self):
        """Submitted -> Line Manager Approved (skippable via settings)."""
        for rec in self:
            rec._require_group('group_eds_line_manager')
            if rec.state != 'submitted':
                raise UserError(_('Only submitted nominations can be approved by the line manager.'))
            rec.write({'state': 'line_manager_approved',
                       'line_manager_approved_by': self.env.user.id})
            rec._notify(_('Nomination %s approved by Line Manager.') % rec.name)
            rec._notify_review_role(
                'group_eds_officer', _('Approve training nomination'),
                _('Nomination %s for %s awaits L&D review.')
                % (rec.name, rec.employee_id.name))

    def action_lnd_approve(self):
        """(Submitted | Line Manager Approved) -> L&D Approved.

        L&D is the segregation point against the nominator.
        """
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.state not in ('submitted', 'line_manager_approved'):
                raise UserError(_('Only submitted (or line-manager-approved) nominations can be '
                                  'approved by L&D.'))
            if rec.nominated_by == self.env.user:
                raise UserError(_('Segregation of Duties : the nominator cannot '
                                  'approve their own nomination at the L&D step.'))
            rec.write({'state': 'lnd_approved', 'lnd_approved_by': self.env.user.id})
            rec._notify(_('Nomination %s approved by L&D.') % rec.name)
            next_role = 'group_eds_manager' if rec.budget_hr_required else 'group_eds_officer'
            rec._notify_review_role(
                next_role, _('Complete nomination approval'),
                _('Nomination %s for %s awaits %s.') % (
                    rec.name, rec.employee_id.name,
                    _('Budget/HR review') if rec.budget_hr_required else _('final L&D approval')))

    def action_approve_budget_hr(self):
        """Optional Budget/HR gate (only when budget_hr_required)."""
        for rec in self:
            rec._require_group('group_eds_manager')
            if not rec.budget_hr_required:
                raise UserError(_('Budget/HR approval is not required for this nomination.'))
            if rec.state != 'lnd_approved':
                raise UserError(_('Approve at the L&D step before the Budget/HR gate.'))
            rec.write({'budget_hr_approved': True,
                       'budget_hr_approved_by': self.env.user.id,
                       'budget_hr_approval_date': fields.Datetime.now()})
            rec._notify(_('Nomination %s passed the Budget/HR gate.') % rec.name)
            rec._notify_review_role(
                'group_eds_officer', _('Finalize training nomination'),
                _('Nomination %s for %s is ready for final L&D approval.')
                % (rec.name, rec.employee_id.name))

    def action_final_approve(self):
        """L&D Approved -> Approved: segregation + capacity assignment."""
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.state != 'lnd_approved':
                raise UserError(_('Only L&D-approved nominations can be finally approved.'))
            if rec.nominated_by == self.env.user:
                raise UserError(_('Segregation of Duties : the nominator cannot be '
                                  'the final approver.'))
            if rec.budget_hr_required and not rec.budget_hr_approved:
                raise UserError(_('This session requires Budget/HR approval before the final '
                                  'approval .'))
            rec.write({'state': 'approved',
                       'approved_by': self.env.user.id,
                       'approved_date': fields.Datetime.now()})
            rec._assign_enrollment()
            clear_action_activities(rec)
            deadline = rec.session_id.response_deadline
            if deadline and rec.employee_id.user_id:
                deadline = fields.Datetime.context_timestamp(
                    rec.with_user(rec.employee_id.user_id), deadline).strftime('%Y-%m-%d %H:%M %Z')
            message = _(
                'Your nomination %s for %s is approved. Training: %s to %s at %s. '
                'Please accept or decline your participation by %s.') % (
                    rec.name, rec.session_id.course_id.name or rec.session_id.program_name,
                    rec.session_id.date_start, rec.session_id.date_end,
                    rec.session_id.venue_id.name or _('venue to be confirmed'), deadline)
            if rec.employee_id.user_id:
                notify_action(rec, rec.employee_id.user_id,
                              _('Respond to approved nomination'), message)
            else:
                rec._notify(message)

    def action_reject(self):
        """Reject at any pre-approval stage (mandatory reason)."""
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.state not in ('submitted', 'line_manager_approved', 'lnd_approved'):
                raise UserError(_('Only pending nominations can be rejected.'))
            if not rec.rejected_reason:
                raise UserError(_('A rejection reason is required.'))
            rec.write({'state': 'rejected', 'rejected_by': self.env.user.id})
            rec._notify(_('Nomination %s rejected: %s') % (rec.name, rec.rejected_reason))

    def action_withdraw(self):
        """Withdraw before the session starts - mandatory reason, frees the seat .

        Allowed at any stage up to the session start (including after approval, which
        frees the seat for the next waitlisted participant).
        """
        for rec in self:
            if rec.state in ('withdrawn', 'rejected', 'declined'):
                raise UserError(_('This nomination cannot be withdrawn anymore.'))
            if rec.session_id.date_start and rec.session_id.date_start <= fields.Datetime.now():
                raise UserError(_('Withdrawal is only allowed before the session starts '
                                  '.'))
            if not rec.withdraw_reason:
                raise UserError(_('A withdrawal reason is mandatory .'))
            rec.write({'state': 'withdrawn',
                       'withdrawn_by': self.env.user.id,
                       'withdrawn_date': fields.Datetime.now()})
            if rec.enrollment_id:
                rec.enrollment_id.action_cancel()
            rec._notify(_('Nomination %s withdrawn: %s') % (rec.name, rec.withdraw_reason))
            rec._promote_waitlisted()

    # ── Employee confirmation (My Nominations - accept/decline) ─────────────
    def action_employee_accept(self):
        """The employee confirms their participation in the approved training."""
        for rec in self:
            rec._check_employee_actor()
            if rec.enrollment_id and (
                    rec.enrollment_id._expire_overdue()
                    or rec.enrollment_id._was_auto_rejected()):
                return rec.enrollment_id._expired_response_notice()
            if rec.state != 'approved':
                raise UserError(_('Only approved nominations can be confirmed by the employee.'))
            now = fields.Datetime.now()
            rec.write({'employee_confirmed': 'confirmed', 'confirmation_date': now})
            if rec.enrollment_id:
                rec.enrollment_id.sudo().write({'response_date': now})
            rec._notify(_('%s confirmed their participation.') % rec.employee_id.name)

    def action_employee_decline(self):
        """The employee declines - frees the seat for the next waitlisted participant."""
        for rec in self:
            rec._check_employee_actor()
            if rec.enrollment_id and (
                    rec.enrollment_id._expire_overdue()
                    or rec.enrollment_id._was_auto_rejected()):
                return rec.enrollment_id._expired_response_notice()
            if rec.state != 'approved':
                raise UserError(_('Only approved nominations can be declined by the employee.'))
            if not rec.decline_reason:
                raise UserError(_('Enter a decline reason.'))
            rec.write({'state': 'declined',
                       'employee_confirmed': 'declined',
                       'confirmation_date': fields.Datetime.now()})
            if rec.enrollment_id:
                rec.enrollment_id.action_cancel()
            rec._notify(_('%s declined the nomination: %s')
                        % (rec.employee_id.name, rec.decline_reason))
            rec._promote_waitlisted()

    def _check_employee_actor(self):
        """Only the employee themselves - or an EDS officer acting on their behalf -
        may accept/decline a nomination (block unrelated employees)."""
        self.ensure_one()
        if self.env.su:
            return
        is_self = self.employee_id.user_id == self.env.user
        is_officer = self.env.user.has_group('employee_development_system.group_eds_officer')
        if not (is_self or is_officer):
            raise UserError(_('Only the nominated employee (or an EDS officer) can accept or '
                              'decline this nomination.'))

    # ── Capacity & waitlist ─────────────────────────────────
    def _assign_enrollment(self):
        """Create the enrollment: enrolled while seats are free, otherwise waitlisted
        with the FIFO position ."""
        self.ensure_one()
        session = self.session_id
        enrolled = session.enrollment_ids.filtered(lambda e: e.state == 'enrolled')
        if len(enrolled) < session.capacity:
            state, waitlisted, position = 'enrolled', False, 0
        else:
            existing = session.enrollment_ids.filtered(lambda e: e.state == 'waitlisted')
            position = max(existing.mapped('waitlist_position') or [0]) + 1
            state, waitlisted = 'waitlisted', True
        enrollment = self.env['eds.enrollment'].create({
            'session_id': session.id,
            'employee_id': self.employee_id.id,
            'nomination_id': self.id,
            'state': state,
            'waitlist_position': position,
            'enrolled_date': date.today(),
        })
        self.write({'enrollment_id': enrollment.id, 'waitlisted': waitlisted,
                    'waitlist_position': position})
        if waitlisted:
            self.message_post(
                body=_('Session is at full capacity - %s placed on the waitlist at position %d '
                       '.') % (self.employee_id.name, position))

    def _promote_waitlisted(self):
        """FIFO promotion for this nomination's session ."""
        self.ensure_one()
        self.env['eds.enrollment']._promote_waitlisted(self.session_id)

    def action_open_enrollment(self):
        self.ensure_one()
        if not self.enrollment_id:
            return
        return {
            'name': _('Enrollment'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.enrollment',
            'res_id': self.enrollment_id.id,
            'view_mode': 'form',
        }

    def _notify(self, body):
        """Chatter notification to the employee (and their manager) with direct action link."""
        self.ensure_one()
        partner_ids = []
        if self.employee_id and self.employee_id.work_contact_id:
            partner_ids.append(self.employee_id.work_contact_id.id)
        if self.employee_id and self.employee_id.parent_id and self.employee_id.parent_id.work_contact_id:
            if self.employee_id.parent_id.work_contact_id.id not in partner_ids:
                partner_ids.append(self.employee_id.parent_id.work_contact_id.id)

        action_link = f"/web#id={self.id}&model=eds.nomination"
        buttons_html = f"""<div style="margin-top: 10px;">
    <a href="{action_link}" style="background-color: #541718; color: #FFFFFF; padding: 6px 14px; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 12px; display: inline-block;">👉 View Nomination Details</a>"""
        if self.enrollment_id:
            seat_link = f"/web#id={self.enrollment_id.id}&model=eds.enrollment"
            buttons_html += f""" <a href="{seat_link}" style="background-color: #541718; color: #FFFFFF; padding: 6px 14px; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 12px; display: inline-block; margin-left: 6px;">🎓 View Session Seat</a>"""
        buttons_html += "</div>"

        formatted_body = Markup(f"<p>{escape(str(body))}</p>{buttons_html}")
        self.with_context(eds_popup_managed=True).message_post(
            body=formatted_body, partner_ids=partner_ids)
        users = self.employee_id.user_id.filtered(
            lambda user: user.active and not user.share)
        push_action_popup(self, users, _('Training nomination update'), str(body))

    def _notify_review_role(self, group_xml_id, title, message):
        self.ensure_one()
        clear_action_activities(self)
        notify_action(self, role_users(self, group_xml_id), title, message)


class EdsEnrollment(models.Model):
    """Enrollment / participation seat on a session.

    Created when a nomination is finally approved: `enrolled` when a seat is free,
    `waitlisted` with a FIFO position otherwise. Auto-promoted by the cron or on
    any seat release (withdrawal / decline / cancellation).
    """
    _name = 'eds.enrollment'
    _description = 'Session Enrollment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'session_id, priority_score desc, source_count desc, waitlist_position, id'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    session_id = fields.Many2one('eds.session', string='Session', required=True,
                                 ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, index=True)
    course_id = fields.Many2one('eds.course', string='Course',
                                related='session_id.course_id', readonly=True)
    session_start = fields.Datetime(string='Start Date and Time',
                                    related='session_id.date_start', readonly=True)
    session_end = fields.Datetime(string='End Date and Time',
                                  related='session_id.date_end', readonly=True)
    venue_id = fields.Many2one('eds.venue', string='Hotel / Venue',
                               related='session_id.venue_id', readonly=True)
    training_provider_name = fields.Char(string='Training Provider',
                                         compute='_compute_training_provider_name',
                                         compute_sudo=True)
    venue_location_details = fields.Text(string='Location Details',
                                         compute='_compute_venue_location_details')
    job_position_id = fields.Many2one('hr.job', string='Job Position',
                                      related='employee_id.job_position', readonly=True, store=True)
    department_id = fields.Many2one('hr.department', string='Department',
                                    related='employee_id.department_id', readonly=True, store=True)
    work_unit_id = fields.Many2one('operating.unit', string='Work Unit',
                                   related='employee_id.default_operating_unit_id', readonly=True, store=True)
    course_demand_employee_id = fields.Many2one(
        'eds.tna.cycle.course.employee', string='TNA Course Demand', ondelete='set null')
    priority_score = fields.Float(
        related='course_demand_employee_id.overall_priority_score', store=True,
        string='TNA Priority Score', readonly=True,
        help='Highest aggregated employee priority for this course across the plan’s source TNA cycles.')
    source_summary = fields.Char(string='Why Suggested', readonly=True)
    source_count = fields.Integer(string='Source Types', readonly=True)
    selected = fields.Boolean(string='Invite', default=True,
                              help='Select new participants to receive an invitation.')
    response_note = fields.Text(string='Response / Replacement Reason', readonly=True)
    response_date = fields.Datetime(string='Response Date', readonly=True)
    auto_rejected = fields.Boolean(string='Automatically Rejected', readonly=True, copy=False)
    replacement_employee_id = fields.Many2one('hr.employee', string='Suggested Replacement', readonly=True)
    replaces_enrollment_id = fields.Many2one('eds.enrollment', string='Replaces', readonly=True)
    nomination_id = fields.Many2one('eds.nomination', string='Nomination', ondelete='cascade')
    state = fields.Selection([
        ('suggested', 'Suggested'),
        ('invited', 'Invitation Sent'),
        ('enrolled', 'Enrolled'),
        ('waitlisted', 'Waitlisted'),
        ('declined', 'Declined'),
        ('replaced', 'Replaced'),
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed'),
        ('absent', 'Absent / Did Not Complete'),
    ], string='Status', default='suggested', required=True, tracking=True)
    enrolled_date = fields.Date(string='Enrolled Date')
    waitlist_position = fields.Integer(string='Waitlist Position', default=0)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.depends('session_id.awarded_provider_id.name', 'session_id.delivery_method')
    def _compute_training_provider_name(self):
        for rec in self:
            provider = rec.session_id.awarded_provider_id
            rec.training_provider_name = (provider.name if provider else
                                          _('Internal / ToT') if rec.session_id.delivery_method == 'internal'
                                          else _('To be confirmed'))

    def _invitation_location_lines(self):
        self.ensure_one()
        venue = self.session_id.venue_id
        if not venue:
            return []
        details = []
        for label, value in (
                (_('Location'), venue.location),
                (_('Address'), venue.address),
                (_('City'), venue.city),
                (_('Country'), venue.country_id.name if venue.location_scope == 'international' else False)):
            value = ' '.join((value or '').split())
            if value:
                details.append('%s: %s' % (label, value))
        return details

    @api.depends('session_id.venue_id.location', 'session_id.venue_id.address',
                 'session_id.venue_id.city', 'session_id.venue_id.country_id',
                 'session_id.venue_id.location_scope')
    def _compute_venue_location_details(self):
        for rec in self:
            rec.venue_location_details = '\n'.join(rec._invitation_location_lines())

    @api.constrains('session_id', 'employee_id')
    def _check_unique_session_enrollment(self):
        for rec in self:
            if rec.session_id and rec.employee_id:
                domain = [
                    ('session_id', '=', rec.session_id.id),
                    ('employee_id', '=', rec.employee_id.id),
                    ('id', '!=', rec.id),
                ]
                if self.search_count(domain) > 0:
                    raise ValidationError(_(
                        "This employee already has a participant record for this session, "
                        "including cancelled or rejected invitations. Review the existing record instead."))

    @api.model_create_multi
    def create(self, vals_list):
        self._lock_enrollment_pairs([
            (vals.get('session_id'), vals.get('employee_id')) for vals in vals_list
        ])
        for vals in vals_list:
            if self.env.context.get('eds_manual_roster') and not vals.get('nomination_id'):
                vals['state'] = 'suggested'
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.enrollment') or _('New')
        return super().create(vals_list)

    def write(self, vals):
        if {'session_id', 'employee_id'} & vals.keys():
            self._lock_enrollment_pairs([
                (vals.get('session_id', rec.session_id.id),
                 vals.get('employee_id', rec.employee_id.id)) for rec in self
            ])
        if {'employee_id', 'session_id'} & vals.keys() and any(
                rec.session_id.status != 'draft' for rec in self):
            raise UserError(_('A scheduled session roster cannot move an employee or change their session. Add a new participant instead.'))
        if vals.get('state') == 'enrolled' and any(
                rec.state not in ('invited', 'waitlisted') and not rec.nomination_id
                for rec in self):
            raise UserError(_(
                'A participant becomes enrolled only after accepting an invitation. '
                'Send the invitation first.'))
        if vals.get('selected') is False and vals.get('state') not in ('invited', 'declined', 'replaced', 'cancelled'):
            if any(rec.session_id.status != 'draft' and rec.state != 'suggested' for rec in self):
                raise UserError(_('A scheduled invitation cannot be removed from the roster. The employee may reject it instead.'))
        return super().write(vals)

    def _lock_enrollment_pairs(self, pairs):
        """Serialize simultaneous invitations for the same session and employee.

        The Python uniqueness check alone permits two concurrent transactions to
        create the same participant. Keep historic duplicate rows intact while
        preventing new ones without a destructive data migration.
        """
        for session_id, employee_id in sorted({
                (int(session_id), int(employee_id)) for session_id, employee_id in pairs
                if session_id and employee_id}):
            self.env.cr.execute(
                'SELECT pg_advisory_xact_lock(%s, hashtext(%s))',
                (454453, '%s:%s' % (session_id, employee_id)),
            )

    def unlink(self):
        if any(rec.session_id.status != 'draft' for rec in self):
            raise UserError(_('Participants cannot be deleted after scheduling. They may reject the invitation, and you may add another employee.'))
        if not self.env.context.get('eds_replacing_source'):
            for enrollment in self.filtered(lambda row: row.state == 'suggested'
                                            and row.course_demand_employee_id
                                            and row.session_id.status == 'draft'):
                enrollment.session_id.omitted_suggestion_employee_ids = [
                    (4, enrollment.employee_id.id)]
        return super().unlink()

    def _expire_overdue(self):
        """Reject unanswered roster entries lazily when viewed or acted upon."""
        now = fields.Datetime.now()
        expired = self.filtered(
            lambda row: row.session_id.status in ('scheduled', 'rescheduled', 'ongoing')
            and row.session_id.response_deadline and row.session_id.response_deadline < now
            and (row.state == 'invited'
                 or row.state == 'suggested' and row.selected
                 or row.state in ('enrolled', 'waitlisted') and row.nomination_id
                 and row.nomination_id.employee_confirmed == 'pending'))
        if not expired:
            return expired
        note = _('Automatically rejected because the invitation response deadline passed.')
        expired.sudo().write({
            'state': 'declined', 'selected': False,
            'response_date': now, 'response_note': note, 'auto_rejected': True,
        })
        nominations = expired.mapped('nomination_id').filtered(
            lambda nomination: nomination.employee_confirmed == 'pending')
        if nominations:
            nominations.sudo().write({
                'state': 'declined', 'employee_confirmed': 'declined',
                'confirmation_date': now, 'decline_reason': note,
            })
        clear_action_activities(expired.sudo())
        for session in expired.mapped('session_id'):
            self._promote_waitlisted(session)
        return expired

    def _expired_response_notice(self):
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': _('Invitation expired'),
                'message': _('The response deadline passed, so this invitation was automatically rejected.'),
                'type': 'warning', 'sticky': True,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _was_auto_rejected(self):
        self.ensure_one()
        return self.state == 'declined' and self.auto_rejected

    def web_read(self, specification):
        self._expire_overdue()
        return super().web_read(specification)

    @api.model
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None, count_limit=None):
        self.search(domain, offset=offset, limit=limit or 80, order=order)._expire_overdue()
        return super().web_search_read(
            domain, specification, offset=offset, limit=limit,
            order=order, count_limit=count_limit)

    def _send_invitation_notice(self):
        for rec in self:
            user = rec.employee_id.user_id
            if not user:
                continue
            session = rec.session_id
            venue = session.venue_id
            local_start = fields.Datetime.context_timestamp(rec.with_user(user), session.date_start)
            local_end = fields.Datetime.context_timestamp(rec.with_user(user), session.date_end)
            local_deadline = fields.Datetime.context_timestamp(
                rec.with_user(user), session.response_deadline)
            details = [
                _('Session: %s') % session.name,
                _('Course: %s') % (session.course_id.name or session.program_name or ''),
                _('Starts: %s') % local_start.strftime('%Y-%m-%d %H:%M %Z'),
                _('Ends: %s') % local_end.strftime('%Y-%m-%d %H:%M %Z'),
                _('Duration: %s hours') % session.duration_hours,
                _('Respond by: %s') % local_deadline.strftime('%Y-%m-%d %H:%M %Z'),
                _('Venue: %s') % (venue.name if venue else _('To be confirmed')),
            ]
            details.extend(rec._invitation_location_lines())
            if session.batch_id:
                details.append(_('Batch: %s') % session.batch_id.display_name)
            details.append(_('Training provider: %s') % rec.training_provider_name)
            if session.trainer_ids:
                details.append(_('Trainers: %s') % ', '.join(session.trainer_ids.mapped('name')))
            message = '%s\n%s' % (_('Please accept, reject, or suggest a replacement for your training invitation.'),
                                   '\n'.join(details))
            notify_action(rec.sudo(), user, _('Training invitation'), message)

    def action_invite(self):
        if any(rec.state == 'suggested' and rec.session_id.response_deadline
               and rec.session_id.response_deadline <= fields.Datetime.now() for rec in self):
            raise UserError(_('The invitation response deadline has passed. Extend it before inviting more employees.'))
        missing = self.filtered(
            lambda row: row.state == 'suggested'
            and row.session_id.status in ('scheduled', 'rescheduled')
            and (not row.employee_id.user_id or not row.employee_id.user_id.active
                 or row.employee_id.user_id.share or not row.employee_id.user_id.partner_id))
        if missing:
            names = ', '.join(missing[:5].mapped('employee_id.name'))
            raise UserError(_(
                'These selected employees need active internal user accounts to receive in-app '
                'training invitations: %s%s. Link their accounts or remove them from the invitation list.')
                % (names, '…' if len(missing) > 5 else ''))
        for rec in self:
            if rec.state != 'suggested' or rec.session_id.status not in ('scheduled', 'rescheduled'):
                continue
            rec.write({
                'state': 'invited', 'selected': False,
            })
            rec._send_invitation_notice()

    def action_open_response(self):
        self.ensure_one()
        if self._expire_overdue() or self._was_auto_rejected():
            return self._expired_response_notice()
        if self.state != 'invited':
            raise UserError(_('Only pending invitations can be answered or replaced.'))
        return {
            'name': _('Respond to Training Invitation'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.enrollment.response.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_enrollment_id': self.id},
        }

    def action_open_materials(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/eds/session/{self.session_id.id}/materials',
            'target': 'new',
        }

    def action_cancel(self):
        """Cancel the enrollment (withdrawal / decline / session cancellation) and promote."""
        sessions = self.mapped('session_id')
        for rec in self:
            if rec.state in ('cancelled', 'completed', 'absent'):
                continue
            rec.write({'state': 'cancelled', 'selected': False})
            clear_action_activities(rec.sudo())
            if rec.nomination_id:
                rec.nomination_id.write({'waitlisted': False, 'waitlist_position': 0})
            rec.message_post(body=_('Enrollment %s cancelled - seat released .') % rec.name)
        for session in sessions:
            self.env['eds.enrollment']._promote_waitlisted(session)

    @api.model
    def _cron_waitlist_promote(self):
        """Hourly cron: promote waitlisted participants FIFO wherever a seat is free
        ."""
        sessions = self.search([('state', '=', 'waitlisted')]).mapped('session_id')
        for session in sessions:
            self._promote_waitlisted(session)
        return True

    @api.model
    def _promote_waitlisted(self, session):
        """Promote the FIFO waitlist of one session while seats are available.

        Cancelled/completed sessions never promote - nobody is placed into a session
        that will not run."""
        if not session:
            return
        if session.status not in ('scheduled', 'ongoing', 'rescheduled'):
            return
        enrolled = session.enrollment_ids.filtered(lambda e: e.state == 'enrolled')
        waitlisted = session.enrollment_ids.filtered(lambda e: e.state == 'waitlisted') \
            .sorted(key=lambda e: (e.waitlist_position, e.id))
        for enrollment in waitlisted:
            if len(enrolled) >= session.capacity:
                break
            enrollment.write({
                'state': 'enrolled',
                'enrolled_date': fields.Date.context_today(enrollment),
            })
            if enrollment.nomination_id:
                enrollment.nomination_id.write({'waitlisted': False, 'waitlist_position': 0})
            enrollment.message_post(
                body=_('Promoted from the waitlist - a seat became available .'))
            message = _(
                'A seat is now available for %s. Training runs from %s to %s at %s.') % (
                    session.course_id.name or session.program_name or session.name,
                    session.date_start, session.date_end,
                    session.venue_id.name or _('venue to be confirmed'))
            if enrollment.employee_id.user_id:
                notify_action(enrollment.sudo(), enrollment.employee_id.user_id,
                              _('Training seat confirmed'), message,
                              action_required=False)
            elif enrollment.employee_id.work_contact_id:
                enrollment.sudo().message_post(
                    body=message,
                    partner_ids=[enrollment.employee_id.work_contact_id.id])
            enrolled |= enrollment
        return True
