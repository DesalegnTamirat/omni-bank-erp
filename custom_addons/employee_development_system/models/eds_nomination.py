# -*- coding: utf-8 -*-
from datetime import date
from markupsafe import Markup, escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from .eds_action_notification import (
    clear_action_activities, notify_action, push_action_popup, role_users,
    valid_google_maps_url,
)
from .eds_employee_projection import safe_employee_web_read


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

    def web_read(self, specification):
        return safe_employee_web_read(
            self, specification, super().web_read, ('employee_id',))

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
                        rec.employee_id.sudo().name, rec.session_id.name
                    ))

    @api.constrains('session_id', 'employee_id', 'state')
    def _check_unique_sourcing_nomination(self):
        for rec in self:
            sourcing = rec.session_id.sourcing_id
            if (not sourcing or not rec.employee_id
                    or rec.state in ('cancelled', 'rejected', 'withdrawn', 'declined')):
                continue
            others = self.sudo().search([
                ('id', '!=', rec.id),
                ('employee_id', '=', rec.employee_id.id),
                ('session_id.sourcing_id', '=', sourcing.id),
                ('session_id', '!=', rec.session_id.id),
                ('session_id.status', '!=', 'cancelled'),
                ('state', 'not in', ('cancelled', 'rejected', 'withdrawn', 'declined')),
            ])
            if others:
                raise ValidationError(_(
                    '%s already has a nomination for another session under provider sourcing %s.')
                    % (rec.employee_id.sudo().name, sourcing.name))
            allocations = self.env['eds.enrollment'].sudo().search([
                ('employee_id', '=', rec.employee_id.id),
                ('session_id.sourcing_id', '=', sourcing.id),
                ('session_id', '!=', rec.session_id.id),
                ('session_id.status', '!=', 'cancelled'),
                ('state', 'in', ('suggested', 'invited', 'enrolled',
                                'waitlisted', 'completed', 'incomplete', 'absent')),
            ])
            if allocations.filtered(lambda row: row.state != 'suggested' or row.selected):
                raise ValidationError(_(
                    '%s is already selected for another session under provider sourcing %s.')
                    % (rec.employee_id.sudo().name, sourcing.name))

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
        self.env['eds.enrollment']._lock_sourcing_employee_pairs([
            (vals.get('session_id'), vals.get('employee_id')) for vals in vals_list
        ])
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.nomination') or _('New')
            if vals.get('nomination_type') == 'tna_based' and not vals.get('justification') \
                    and vals.get('tna_entry_id'):
                entry = self.env['eds.tna.entry'].browse(vals['tna_entry_id'])
                vals['justification'] = entry.justification
        return super().create(vals_list)

    def write(self, vals):
        if {'session_id', 'employee_id', 'state'} & vals.keys():
            self.env['eds.enrollment']._lock_sourcing_employee_pairs([
                (vals.get('session_id', rec.session_id.id),
                 vals.get('employee_id', rec.employee_id.id)) for rec in self
            ])
        return super().write(vals)

    # ── Eligibility & guards ─────────────────────────────────────────────────
    def _check_submission_rules(self):
        """Validate TNA basis, justifications, and service tenure."""
        self.ensure_one()
        if self.nomination_type == 'tna_based':
            if not self.tna_entry_id:
                raise UserError(_('TNA-based nominations must reference an approved training need.'))
            if self.tna_entry_id.state not in ('approved', 'converted'):
                raise UserError(_('The referenced training need is not approved yet.'))
            entry = self.tna_entry_id
            target_employee_ids = (
                set(entry.sudo().work_unit_employee_ids.ids)
                if entry.request_level == 'work_unit'
                else {entry.sudo().employee_id.id}
            )
            if self.employee_id.id not in target_employee_ids:
                raise UserError(_('The training need does not include this employee.'))
            requested_courses = (entry.requested_course_ids | entry.suggested_course_ids
                                 | entry.course_id)
            if not self.session_id.course_id or self.session_id.course_id not in requested_courses:
                raise UserError(_('The training need does not request this session course.'))
            demands = (self.session_id.plan_line_id.course_demand_ids
                       | self.session_id.plan_line_id.course_demand_id)
            if demands:
                evidence = demands.mapped('employee_demand_ids').filtered(
                    lambda demand: demand.employee_id == self.employee_id
                    and not demand.excluded_from_planning).mapped('evidence_ids.entry_id')
                if entry not in evidence:
                    raise UserError(_(
                        'The training need is not selected as evidence for this employee and plan course.'))
        elif self.nomination_type == 'ad_hoc' and not (self.justification or '').strip():
            raise UserError(_('Ad-hoc nominations require a mandatory justification and L&D approval.'))

        # Missing course prerequisites are advisory when invitations are sent.
        # Minimum service tenure remains an eligibility rule.
        course = self.session_id.course_id
        if course:
            if getattr(course, 'min_tenure_months', 0) > 0:
                emp = self.employee_id.sudo()
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

    def _ensure_session_open_for_approval(self):
        """A nomination cannot advance after invitations or delivery have closed."""
        self.ensure_one()
        session = self.session_id.sudo()
        now = fields.Datetime.now()
        if session.status != 'scheduled':
            raise UserError(_('Schedule the session before submitting or approving nominations.'))
        if not session.date_start or session.date_start <= now:
            raise UserError(_('Nominations must be approved before the session starts.'))
        if not session.response_deadline or session.response_deadline <= now:
            raise UserError(_('Extend the invitation response deadline before approving nominations.'))

    # ── Approval workflow  ───────────────────────────────────────
    def action_submit(self):
        """Draft -> Submitted (opens the approval chain)."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft nominations can be submitted.'))
            rec._ensure_session_open_for_approval()
            rec._check_submission_rules()
            requires_manager = rec._get_bool_param('eds.nomination_require_line_manager', True)
            if requires_manager:
                manager_user = rec.employee_id.sudo().parent_id.user_id
                if (not manager_user or not manager_user.active
                        or not manager_user.has_group(
                            'employee_development_system.group_eds_line_manager')):
                    raise UserError(_(
                        'Assign an active EDS line-manager user to this employee before submitting.'))
                reviewers = manager_user
                title = _('Review training nomination')
                message = _('Nomination %s for %s awaits line manager review.')
            else:
                reviewers = role_users(rec, 'group_eds_officer')
                title = _('Review training nomination')
                message = _('Nomination %s for %s awaits L&D review.')
            rec.state = 'submitted'
            rec._notify(_('Nomination %s submitted for approval.') % rec.name)
            clear_action_activities(rec)
            notify_action(
                rec, reviewers, title, message % (rec.name, rec.employee_id.sudo().name))

    def action_line_manager_approve(self):
        """Submitted -> Line Manager Approved (skippable via settings)."""
        for rec in self:
            rec._require_group('group_eds_line_manager')
            if rec.state != 'submitted':
                raise UserError(_('Only submitted nominations can be approved by the line manager.'))
            rec._ensure_session_open_for_approval()
            actual_manager = rec.employee_id.sudo().parent_id.user_id
            if not actual_manager or not actual_manager.active:
                raise UserError(_('Assign an active user to this employee’s line manager before approval.'))
            if not self.env.su and self.env.user != actual_manager:
                raise UserError(_('Only this employee’s line manager can approve the nomination.'))
            rec.write({'state': 'line_manager_approved',
                       'line_manager_approved_by': self.env.user.id})
            rec._notify(_('Nomination %s approved by Line Manager.') % rec.name)
            rec._notify_review_role(
                'group_eds_officer', _('Approve training nomination'),
                _('Nomination %s for %s awaits L&D review.')
                % (rec.name, rec.employee_id.sudo().name))

    def action_lnd_approve(self):
        """(Submitted | Line Manager Approved) -> L&D Approved.

        L&D is the segregation point against the nominator.
        """
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.state not in ('submitted', 'line_manager_approved'):
                raise UserError(_('Only submitted (or line-manager-approved) nominations can be '
                                  'approved by L&D.'))
            rec._ensure_session_open_for_approval()
            if (rec.state == 'submitted'
                    and rec._get_bool_param('eds.nomination_require_line_manager', True)):
                raise UserError(_('The employee’s line manager must approve this nomination first.'))
            if rec.nominated_by == self.env.user:
                raise UserError(_('Segregation of Duties : the nominator cannot '
                                  'approve their own nomination at the L&D step.'))
            rec.write({'state': 'lnd_approved', 'lnd_approved_by': self.env.user.id})
            rec._notify(_('Nomination %s approved by L&D.') % rec.name)
            next_role = 'group_eds_manager' if rec.budget_hr_required else 'group_eds_officer'
            rec._notify_review_role(
                next_role, _('Complete nomination approval'),
                _('Nomination %s for %s awaits %s.') % (
                    rec.name, rec.employee_id.sudo().name,
                    _('Budget/HR review') if rec.budget_hr_required else _('final L&D approval')))

    def action_approve_budget_hr(self):
        """Optional Budget/HR gate (only when budget_hr_required)."""
        for rec in self:
            rec._require_group('group_eds_manager')
            if not rec.budget_hr_required:
                raise UserError(_('Budget/HR approval is not required for this nomination.'))
            if rec.state != 'lnd_approved':
                raise UserError(_('Approve at the L&D step before the Budget/HR gate.'))
            rec._ensure_session_open_for_approval()
            rec.write({'budget_hr_approved': True,
                       'budget_hr_approved_by': self.env.user.id,
                       'budget_hr_approval_date': fields.Datetime.now()})
            rec._notify(_('Nomination %s passed the Budget/HR gate.') % rec.name)
            rec._notify_review_role(
                'group_eds_officer', _('Finalize training nomination'),
                _('Nomination %s for %s is ready for final L&D approval.')
                % (rec.name, rec.employee_id.sudo().name))

    def action_final_approve(self):
        """L&D Approved -> Approved: segregation + capacity assignment."""
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.state != 'lnd_approved':
                raise UserError(_('Only L&D-approved nominations can be finally approved.'))
            rec._ensure_session_open_for_approval()
            rec._check_submission_rules()
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
            employee_user = rec.employee_id.sudo().user_id
            if deadline and employee_user:
                deadline = fields.Datetime.context_timestamp(
                    rec.with_user(employee_user), deadline).strftime('%Y-%m-%d %H:%M %Z')
            message = _(
                'Your nomination %s for %s is approved. Training: %s to %s. Location/arrangement: %s. '
                'Please accept or decline your participation by %s.') % (
                    rec.name, rec.session_id.course_id.name or rec.session_id.program_name,
                    rec.session_id.date_start, rec.session_id.date_end,
                    rec.session_id._training_location_label(), deadline)
            if rec.session_id.commitment_required:
                message += _('\nTraining commitment: %s year(s). Terms: %s\n'
                             'You must explicitly accept these terms to join the session.') % (
                                 rec.session_id.commitment_years,
                                 rec.session_id.commitment_terms)
            if employee_user:
                notify_action(rec, employee_user,
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
            if rec.session_id.status == 'rescheduled':
                raise UserError(_(
                    'Wait for the confirmed rescheduled invitation before responding.'))
            if rec.enrollment_id and (
                    rec.enrollment_id._expire_overdue()
                    or rec.enrollment_id._was_auto_rejected()):
                return rec.enrollment_id._expired_response_notice()
            if rec.state != 'approved':
                raise UserError(_('Only approved nominations can be confirmed by the employee.'))
            if rec.enrollment_id.reschedule_reconfirmation_required:
                if rec.enrollment_id.state != 'invited':
                    raise UserError(_(
                        'Your previous enrollment no longer counts. Wait for the new invitation.'))
                return rec.enrollment_id.action_open_response()
            if rec.session_id.commitment_required:
                return rec.enrollment_id.action_open_response()
            now = fields.Datetime.now()
            rec.write({'employee_confirmed': 'confirmed', 'confirmation_date': now})
            if rec.enrollment_id:
                rec.enrollment_id.sudo().write({'response_date': now})
            rec._notify(_('%s confirmed their participation.') % rec.employee_id.sudo().name)

    def action_employee_decline(self):
        """The employee declines - frees the seat for the next waitlisted participant."""
        for rec in self:
            rec._check_employee_actor()
            if rec.session_id.status == 'rescheduled':
                raise UserError(_(
                    'Wait for the confirmed rescheduled invitation before responding.'))
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
                        % (rec.employee_id.sudo().name, rec.decline_reason))
            rec._promote_waitlisted()

    def _check_employee_actor(self):
        """Only the employee themselves - or an EDS officer acting on their behalf -
        may accept/decline a nomination (block unrelated employees)."""
        self.ensure_one()
        if self.env.su:
            return
        is_self = self.employee_id.sudo().user_id == self.env.user
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
        if session.commitment_required:
            state, waitlisted, position = 'invited', False, 0
        elif len(enrolled) < session.capacity:
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
            'enrolled_date': date.today() if state == 'enrolled' else False,
        })
        self.write({'enrollment_id': enrollment.id, 'waitlisted': waitlisted,
                    'waitlist_position': position})
        if waitlisted:
            self.message_post(
                body=_('Session is at full capacity - %s placed on the waitlist at position %d '
                       '.') % (self.employee_id.sudo().name, position))

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
        employee = self.employee_id.sudo()
        partners = employee.work_contact_id | employee.parent_id.work_contact_id
        partner_ids = partners.ids

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
        users = self.employee_id.sudo().user_id.filtered(
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
    _order = 'session_id, priority_score desc, source_count desc, waitlist_position, create_date desc, id desc'
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
    reschedule_reconfirmation_required = fields.Boolean(
        string='New Acceptance Required After Reschedule', readonly=True,
        copy=False, tracking=True)
    reschedule_previous_state = fields.Selection([
        ('invited', 'Previously Invited'),
        ('enrolled', 'Previously Enrolled'),
        ('waitlisted', 'Previously Waitlisted'),
    ], string='Status Before Reschedule', readonly=True, copy=False)
    invitation_revision = fields.Integer(
        string='Invitation Revision', default=0, readonly=True, copy=False)
    response_note = fields.Text(string='Response / Rejection Reason', readonly=True)
    response_date = fields.Datetime(string='Response Date', readonly=True)
    commitment_years_at_accept = fields.Integer(
        string='Accepted Commitment (Years)', readonly=True, copy=False)
    commitment_terms_at_accept = fields.Text(
        string='Accepted Commitment Terms', readonly=True, copy=False)
    commitment_accepted_at = fields.Datetime(
        string='Commitment Accepted At', readonly=True, copy=False)
    commitment_accepted_by_id = fields.Many2one(
        'res.users', string='Commitment Accepted By', readonly=True, copy=False)
    training_commitment_ids = fields.One2many(
        'training.commitment', 'eds_enrollment_id', string='Training Commitments', readonly=True)
    provider_certificate_file = fields.Binary(
        string='Provider Certificate Document', attachment=True)
    provider_certificate_filename = fields.Char(string='Certificate Filename')
    provider_certificate_number = fields.Char(string='Certificate No. / Reference')
    provider_certificate_issue_date = fields.Date(string='Certificate Issue Date')
    auto_rejected = fields.Boolean(string='Automatically Rejected', readonly=True, copy=False)
    replacement_employee_id = fields.Many2one('hr.employee', string='Manager Replacement', readonly=True)
    replaces_enrollment_id = fields.Many2one('eds.enrollment', string='Replaces', readonly=True)
    manager_replacement_decision = fields.Selection([
        ('pending', 'Awaiting Manager Decision'),
        ('replace', 'Replacement Selected'),
        ('none', 'No Replacement'),
    ], string='Manager Decision', default='pending', readonly=True, copy=False,
        tracking=True)
    manager_replacement_decided_by_id = fields.Many2one(
        'res.users', string='Decision By', readonly=True, copy=False)
    manager_replacement_decided_at = fields.Datetime(
        string='Decision Date', readonly=True, copy=False)
    manager_replacement_note = fields.Text(
        string='Manager Decision Note', readonly=True, copy=False)
    can_manage_replacement = fields.Boolean(
        compute='_compute_can_manage_replacement', compute_sudo=True)
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
        ('incomplete', 'Attended / Did Not Complete'),
        ('absent', 'Absent'),
    ], string='Status', default='suggested', required=True, tracking=True)
    enrolled_date = fields.Date(string='Enrolled Date')
    waitlist_position = fields.Integer(string='Waitlist Position', default=0)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.depends('state', 'manager_replacement_decision',
                 'employee_id.parent_id.user_id', 'employee_id.coach_id.user_id')
    @api.depends_context('uid')
    def _compute_can_manage_replacement(self):
        for rec in self:
            employee = rec.employee_id.sudo()
            decision_user = employee.parent_id.user_id or employee.coach_id.user_id
            rec.can_manage_replacement = bool(
                rec.state == 'declined'
                and rec.manager_replacement_decision in (False, 'pending')
                and self.env.uid == decision_user.id
            )

    def action_open_manager_replacement(self):
        self.ensure_one()
        self.check_access('read')
        if not self.can_manage_replacement:
            raise UserError(_(
                'Only the employee’s boss can decide on a replacement '
                '(or the coach when no boss account exists).'))
        return {
            'name': _('Decide on Training Replacement'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.enrollment.replacement.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_enrollment_id': self.id},
        }

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

    @api.depends('session_id.is_virtual', 'session_id.venue_id.location', 'session_id.venue_id.address',
                 'session_id.venue_id.city', 'session_id.venue_id.country_id',
                 'session_id.venue_id.location_scope')
    def _compute_venue_location_details(self):
        for rec in self:
            rec.venue_location_details = (rec.session_id._training_location_label()
                                          if rec.session_id.is_virtual and not rec.venue_id
                                          else '\n'.join(rec._invitation_location_lines()))

    def _notify_response_supervisors(self, accepted):
        """Give the boss the response and send a rejection to the coach too."""
        for rec in self:
            employee = rec.employee_id.sudo()
            session = rec.session_id.sudo()
            boss = employee.parent_id.user_id
            coach = employee.coach_id.user_id
            recipients = [(boss or coach, True)]
            if not accepted and coach and coach != boss:
                if boss:
                    recipients.append((coach, False))
            for user, is_boss in recipients:
                if not user or not user.active or user.share:
                    continue
                local_start = fields.Datetime.context_timestamp(
                    rec.with_user(user), session.date_start)
                local_end = fields.Datetime.context_timestamp(
                    rec.with_user(user), session.date_end)
                details = [
                    _('Course: %s') % (session.course_id.name or session.program_name or ''),
                    _('Session: %s') % session.name,
                    _('Starts: %s') % local_start.strftime('%Y-%m-%d %H:%M %Z'),
                    _('Ends: %s') % local_end.strftime('%Y-%m-%d %H:%M %Z'),
                ]
                if session.google_maps_url:
                    details.append(_('Google Maps: %s') % session.google_maps_url)
                if accepted:
                    title = _('Team training invitation accepted')
                    opening = _('%s accepted the invitation%s.') % (
                        employee.name,
                        _(' and is waitlisted') if rec.state == 'waitlisted' else '')
                else:
                    title = (_('Choose a training replacement') if is_boss
                             else _('Coachee rejected training invitation'))
                    opening = _('%s rejected the training invitation. Reason: %s') % (
                        employee.name, rec.response_note or '')
                    if is_boss:
                        details.append(_(
                            'Open the enrollment to choose a replacement from your team '
                            'or close the request without a replacement.'))
                notify_action(
                    rec.sudo(), user, title, '\n'.join([opening] + details),
                    action_required=not accepted and is_boss,
                    map_url=session.google_maps_url)

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

    @api.constrains('session_id', 'employee_id', 'state', 'selected')
    def _check_unique_sourcing_enrollment(self):
        reserved_states = ('invited', 'enrolled', 'waitlisted', 'completed', 'incomplete', 'absent')
        for rec in self:
            sourcing = rec.session_id.sourcing_id
            if (not sourcing or not rec.employee_id or rec.session_id.status == 'cancelled'
                    or rec.state not in reserved_states + ('suggested',)
                    or rec.state == 'suggested' and not rec.selected):
                continue
            others = self.sudo().search([
                ('id', '!=', rec.id),
                ('employee_id', '=', rec.employee_id.id),
                ('session_id.sourcing_id', '=', sourcing.id),
                ('session_id.status', '!=', 'cancelled'),
                ('state', 'in', reserved_states + ('suggested',)),
            ])
            if others.filtered(lambda row: row.state != 'suggested' or row.selected):
                raise ValidationError(_(
                    '%s is already selected for another session under provider sourcing %s. '
                    'Deselect, decline, replace, or cancel that allocation before assigning this employee again.')
                    % (rec.employee_id.sudo().name, sourcing.name))
            nominations = self.env['eds.nomination'].sudo().search([
                ('employee_id', '=', rec.employee_id.id),
                ('session_id.sourcing_id', '=', sourcing.id),
                ('session_id', '!=', rec.session_id.id),
                ('session_id.status', '!=', 'cancelled'),
                ('state', 'not in', ('cancelled', 'rejected', 'withdrawn', 'declined')),
            ], limit=1)
            if nominations:
                raise ValidationError(_(
                    '%s already has a nomination for another session under provider sourcing %s.')
                    % (rec.employee_id.sudo().name, sourcing.name))

    @api.model_create_multi
    def create(self, vals_list):
        acceptance_fields = {'commitment_years_at_accept', 'commitment_terms_at_accept',
                             'commitment_accepted_at', 'commitment_accepted_by_id'}
        for vals in vals_list:
            if acceptance_fields & vals.keys():
                raise UserError(_('Commitment acceptance must be recorded by the invited employee.'))
            if vals.get('state') in ('enrolled', 'waitlisted') and vals.get('session_id'):
                session = self.env['eds.session'].browse(vals['session_id'])
                if session.commitment_required:
                    raise UserError(_('Invite the employee to accept the training commitment first.'))
        self._lock_enrollment_pairs([
            (vals.get('session_id'), vals.get('employee_id')) for vals in vals_list
        ])
        self._lock_sourcing_employee_pairs([
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
        acceptance_fields = {'commitment_years_at_accept', 'commitment_terms_at_accept',
                             'commitment_accepted_at', 'commitment_accepted_by_id'}
        if acceptance_fields & vals.keys():
            if (not self.env.su or not self.env.context.get('eds_commitment_acceptance')
                    or any(rec.employee_id.sudo().user_id.id != self.env.uid for rec in self)):
                raise UserError(_('Commitment acceptance must be recorded by the invited employee.'))
        if 'reschedule_previous_state' in vals and not self.env.su:
            raise UserError(_('Reschedule history is set by the session workflow.'))
        if 'invitation_revision' in vals and not self.env.su:
            raise UserError(_('Invitation revisions are set by the session workflow.'))
        if 'reschedule_reconfirmation_required' in vals and (
                not self.env.su or vals['reschedule_reconfirmation_required']
                or any(rec.reschedule_reconfirmation_required
                       and rec.employee_id.sudo().user_id.id != self.env.uid for rec in self)):
            raise UserError(_('Only the invited employee can answer the rescheduled invitation.'))
        if {'session_id', 'employee_id'} & vals.keys():
            self._lock_enrollment_pairs([
                (vals.get('session_id', rec.session_id.id),
                 vals.get('employee_id', rec.employee_id.id)) for rec in self
            ])
        if {'session_id', 'employee_id', 'state', 'selected'} & vals.keys():
            self._lock_sourcing_employee_pairs([
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
        if vals.get('state') in ('enrolled', 'waitlisted') and any(
                rec.reschedule_reconfirmation_required for rec in self):
            if (not self.env.su or not self.env.context.get('eds_reschedule_acceptance')
                    or any(rec.state != 'invited'
                           or rec.employee_id.sudo().user_id.id != self.env.uid
                           for rec in self if rec.reschedule_reconfirmation_required)):
                raise UserError(_(
                    'The previous enrollment no longer counts. The invited employee must '
                    'accept the rescheduled invitation again.'))
        if vals.get('state') in ('enrolled', 'waitlisted'):
            if any(rec.session_id.commitment_required and not (
                    vals.get('commitment_accepted_at') or rec.commitment_accepted_at)
                   for rec in self):
                raise UserError(_('Accept the training commitment before joining this session.'))
        if vals.get('selected') is False and vals.get('state') not in ('invited', 'declined', 'replaced', 'cancelled'):
            if any(rec.reschedule_reconfirmation_required and rec.state == 'suggested'
                   for rec in self):
                raise UserError(_(
                    'Previously invited participants must receive a new invitation '
                    'after rescheduling. Cancel the participant record if they will not attend.'))
            if any(rec.session_id.status != 'draft' and rec.state != 'suggested' for rec in self):
                raise UserError(_('A scheduled invitation cannot be removed from the roster. The employee may reject it instead.'))
        return super().write(vals)

    def _reset_for_session_reschedule(self):
        """Invalidate pending invitations and prior seats before schedule edits."""
        if not (self.env.su or self.env.user.has_group(
                'employee_development_system.group_eds_officer')):
            raise UserError(_('Only L&D staff may reschedule participant invitations.'))
        if any(row.session_id.status != 'rescheduled' for row in self):
            raise UserError(_('Put the session into Rescheduled status first.'))
        active = self.filtered(lambda row: row.state in ('invited', 'enrolled', 'waitlisted'))
        active.check_access('write')
        for row in active:
            prior_state = row.state
            prior_acceptance = row.commitment_accepted_at
            prior_years = row.commitment_years_at_accept
            prior_terms = row.commitment_terms_at_accept
            super(EdsEnrollment, row).write({
                'state': 'suggested', 'selected': True,
                'response_date': False, 'response_note': False,
                'enrolled_date': False, 'waitlist_position': 0,
                'commitment_years_at_accept': 0,
                'commitment_terms_at_accept': False,
                'commitment_accepted_at': False,
                'commitment_accepted_by_id': False,
                'auto_rejected': False,
                'reschedule_reconfirmation_required': True,
                'reschedule_previous_state': prior_state,
                'invitation_revision': row.invitation_revision + 1,
            })
            if row.nomination_id:
                row.nomination_id.sudo().write({
                    'employee_confirmed': 'pending', 'confirmation_date': False,
                    'waitlisted': False, 'waitlist_position': 0,
                })
            clear_action_activities(row.sudo())
            if prior_acceptance:
                row.sudo().message_post(
                    body=_('Prior commitment acceptance on %s for %s year(s) '
                           '(terms: %s) was invalidated by rescheduling. New acceptance is required.')
                    % (prior_acceptance, prior_years, prior_terms or ''),
                    subtype_xmlid='mail.mt_note')
            if prior_state == 'invited':
                previous = _('Your earlier invitation is no longer valid.')
            elif prior_state == 'waitlisted':
                previous = _('Your earlier waitlist place no longer counts.')
            else:
                previous = _('Your earlier enrollment no longer counts; you are not enrolled now.')
            message = _(
                'Session %s is being rescheduled. %s You will receive a new invitation '
                'after the dates and any commitment terms are confirmed. Accept that new '
                'invitation to join the session.') % (row.session_id.name, previous)
            if row.session_id.google_maps_url:
                message += '\n%s' % (_('Google Maps: %s') % row.session_id.google_maps_url)
            employee = row.employee_id.sudo()
            user = employee.user_id
            if user and user.active and not user.share:
                notify_action(row.sudo(), user, _('Training rescheduled'), message,
                              action_required=False,
                              map_url=row.session_id.google_maps_url)
            elif employee.work_contact_id:
                row.sudo().message_post(
                    body=message, partner_ids=[employee.work_contact_id.id])
        return active

    def _reinvite_after_session_reschedule(self):
        """Send new invitations only after the revised schedule is confirmed."""
        if any(row.session_id.status != 'scheduled' for row in self):
            raise UserError(_('Confirm the rescheduled session before inviting employees.'))
        pending = self.filtered(
            lambda row: row.reschedule_reconfirmation_required
            and row.state == 'suggested')
        if pending:
            pending.check_access('write')
            for row in pending:
                super(EdsEnrollment, row).write({
                    'invitation_revision': row.invitation_revision + 1,
                    'selected': True,
                })
            pending.action_invite()
        return pending

    def _cancel_rescheduled_invitations(self):
        """Notify participants whose old seats were voided before cancellation."""
        pending = self.filtered(
            lambda row: row.reschedule_reconfirmation_required
            and row.state == 'suggested')
        if not pending:
            return pending
        if any(row.session_id.status != 'cancelled' for row in pending):
            raise UserError(_('Cancel the session before closing its pending invitations.'))
        pending.check_access('write')
        for row in pending:
            super(EdsEnrollment, row).write({
                'state': 'cancelled', 'selected': False,
                'reschedule_reconfirmation_required': False,
            })
            clear_action_activities(row.sudo())
            message = _(
                'Rescheduled session %s has been cancelled. Your earlier enrollment '
                'or invitation no longer counts, and no new invitation will be sent.') % (
                    row.session_id.name)
            employee = row.employee_id.sudo()
            user = employee.user_id
            if user and user.active and not user.share:
                notify_action(row.sudo(), user, _('Rescheduled training cancelled'),
                              message, action_required=False)
            elif employee.work_contact_id:
                row.sudo().message_post(
                    body=message, partner_ids=[employee.work_contact_id.id])
        return pending

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

    def _lock_sourcing_employee_pairs(self, pairs):
        """Serialize allocations across sessions sharing one provider sourcing."""
        session_ids = {int(session_id) for session_id, employee_id in pairs
                       if session_id and employee_id}
        sessions = {session.id: session for session in
                    self.env['eds.session'].sudo().browse(list(session_ids)).exists()}
        keys = {(sessions[session_id].sourcing_id.id, int(employee_id))
                for session_id, employee_id in pairs if session_id in sessions
                and employee_id and sessions[session_id].sourcing_id}
        for sourcing_id, employee_id in sorted(keys):
            self.env.cr.execute(
                'SELECT pg_advisory_xact_lock(%s, hashtext(%s))',
                (454454, '%s:%s' % (sourcing_id, employee_id)),
            )

    def unlink(self):
        if any(rec.session_id.status != 'draft' for rec in self):
            raise UserError(_('Participants cannot be deleted after scheduling. They may reject the invitation, and you may add another employee.'))
        if not self.env.context.get('eds_replacing_source'):
            # The removed participant may be outside an officer's HR visibility.
            # Keep the omission marker server-side while retaining the actor's
            # enrollment deletion and session write checks.
            self.check_access('unlink')
            for enrollment in self.filtered(lambda row: row.state == 'suggested'
                                            and row.course_demand_employee_id
                                            and row.session_id.status == 'draft'):
                enrollment.session_id.check_access('write')
                enrollment.session_id.sudo().write({
                    'omitted_suggestion_employee_ids': [(4, enrollment.employee_id.id)],
                })
        return super().unlink()

    def _expire_overdue(self):
        """Reject unanswered roster entries lazily when viewed or acted upon."""
        now = fields.Datetime.now()
        expired = self.filtered(
            lambda row: row.session_id.status in ('scheduled', 'ongoing')
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
        for enrollment in expired:
            message = _(
                'Your invitation to %s expired because the response deadline passed. '
                'Contact L&D if you still need this training.') % (
                    enrollment.session_id.course_id.name or enrollment.session_id.program_name)
            employee_user = enrollment.employee_id.sudo().user_id
            if employee_user and employee_user.active:
                notify_action(enrollment.sudo(), employee_user,
                              _('Training invitation expired'), message,
                              action_required=False)
            elif enrollment.employee_id.sudo().work_contact_id:
                enrollment.sudo().message_post(
                    body=message, partner_ids=[enrollment.employee_id.sudo().work_contact_id.id])
        for session in expired.mapped('session_id'):
            count = len(expired.filtered(lambda row: row.session_id == session))
            notify_action(
                session.sudo(), role_users(session, 'group_eds_officer'),
                _('Training invitations expired'),
                _('%s invitation(s) for %s expired. Review the roster and replacements.')
                % (count, session.name), action_required=False)
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
        return safe_employee_web_read(
            self, specification, super().web_read,
            ('employee_id', 'replacement_employee_id'))

    @api.model
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None, count_limit=None):
        self.search(domain, offset=offset, limit=limit or 80, order=order)._expire_overdue()
        return super().web_search_read(
            domain, specification, offset=offset, limit=limit,
            order=order, count_limit=count_limit)

    @api.model
    def get_my_pending_action_alerts(self):
        """Replay only this employee's outstanding invitations and commitments."""
        user = self.env.user
        if not user.active or user.share:
            return []
        invitations = self.search([
            ('employee_id.user_id', '=', user.id),
            ('state', '=', 'invited'),
            ('session_id.status', 'in', ('scheduled', 'ongoing')),
            ('session_id.response_deadline', '>', fields.Datetime.now()),
        ], order='create_date desc, id desc', limit=20)
        action = self.env.ref('employee_development_system.action_eds_enrollment_my')
        form = self.env.ref('employee_development_system.view_eds_enrollment_form')
        alerts = []
        for invitation in invitations:
            row = invitation.sudo()
            session = row.session_id
            deadline = fields.Datetime.context_timestamp(
                invitation, session.response_deadline)
            message = _(
                'Your invitation to %s is waiting for your response. Respond by %s.') % (
                    session.course_id.name or session.program_name or session.name,
                    deadline.strftime('%Y-%m-%d %H:%M %Z'))
            if session.commitment_required:
                message += '\n' + _(
                    'This invitation includes a %s-year training commitment. '
                    'Review the terms before accepting.') % session.commitment_years
            alerts.append({
                'title': _('Training invitation and commitment')
                         if session.commitment_required else _('Training invitation'),
                'message': message,
                'actor': _('Employee Development'),
                'actor_partner_id': False,
                'model': self._name,
                'res_id': row.id,
                'action_required': True,
                'action_id': action.id,
                'form_view_id': form.id,
                'action_label': _('Respond to invitation'),
                'map_url': valid_google_maps_url(session.google_maps_url) or False,
                'notification_key': 'eds.enrollment:%s:%s' % (
                    row.id, row.invitation_revision),
            })
        commitment_activities = self.env['mail.activity'].sudo().search([
            ('res_model_id', '=', self.env.ref(
                'employee_development_system.model_eds_enrollment').id),
            ('user_id', '=', user.id),
            ('summary', '=', 'EDS action: Training commitment recorded'),
        ], order='create_date desc, id desc', limit=10)
        commitment_rows = {
            row.id: row.sudo() for row in self.search([
                ('id', 'in', commitment_activities.mapped('res_id')),
                ('employee_id.user_id', '=', user.id),
            ])
        }
        for activity in commitment_activities:
            row = commitment_rows.get(activity.res_id)
            if not row or not row.training_commitment_ids:
                continue
            commitment = row.training_commitment_ids[:1]
            session = row.session_id
            alerts.append({
                'title': _('Training commitment recorded'),
                'message': _(
                    'Your training commitment for %s has been recorded. '
                    'Service period: %s to %s. Review the accepted terms.') % (
                        session.course_id.name or session.program_name or session.name,
                        commitment.start_date, commitment.end_date),
                'actor': _('Employee Development'),
                'actor_partner_id': False,
                'model': self._name,
                'res_id': row.id,
                'action_required': True,
                'action_id': action.id,
                'form_view_id': form.id,
                'action_label': _('View commitment'),
                'map_url': False,
                'notification_key': 'eds.commitment:%s' % activity.id,
            })
        return alerts

    def _send_invitation_notice(self):
        for rec in self:
            user = rec.employee_id.sudo().user_id
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
                (_('Delivery: No hotel needed') if session.is_virtual and not venue
                 else _('Venue: %s') % session._training_location_label()),
            ]
            details.extend(rec._invitation_location_lines())
            if session.google_maps_url:
                details.append(_('Google Maps: %s') % session.google_maps_url)
            if session.batch_id:
                details.append(_('Batch: %s') % session.batch_id.display_name)
            details.append(_('Training provider: %s') % rec.training_provider_name)
            if session.commitment_required:
                details.extend([
                    _('Training commitment: %s year(s)') % session.commitment_years,
                    _('Commitment terms: %s') % session.commitment_terms,
                    _('Accepting this invitation requires your explicit agreement to these terms.'),
                ])
            if session.trainer_ids:
                details.append(_('Trainers: %s') % ', '.join(session.trainer_ids.mapped('name')))
            if rec.reschedule_reconfirmation_required:
                introduction = _(
                    'This session has been rescheduled. Your previous invitation, enrollment, '
                    'or waitlist place no longer counts. You are not enrolled until you accept '
                    'this new invitation. Review the revised dates and commitment terms, then '
                    'accept or reject it. Give a reason if you reject it.')
                title = _('Rescheduled training invitation: respond again')
            else:
                introduction = _(
                    'Please accept or reject your training invitation. Give a reason if you reject it.')
                title = (_('Training invitation and commitment')
                         if session.commitment_required else _('Training invitation'))
            message = '%s\n%s' % (introduction, '\n'.join(details))
            notify_action(rec.sudo(), user, title, message,
                          action_id=rec.env.ref(
                              'employee_development_system.action_eds_enrollment_my').id,
                          form_view_id=rec.env.ref(
                              'employee_development_system.view_eds_enrollment_form').id,
                          action_label=_('Respond to invitation'),
                          map_url=session.google_maps_url)

    def action_invite(self):
        if any(rec.state == 'suggested' and rec.session_id.response_deadline
               and rec.session_id.response_deadline <= fields.Datetime.now() for rec in self):
            raise UserError(_('The invitation response deadline has passed. Extend it before inviting more employees.'))
        missing = self.filtered(
            lambda row: row.state == 'suggested' and row.selected
            and row.session_id.status == 'scheduled'
            and (not row.employee_id.sudo().user_id or not row.employee_id.sudo().user_id.active
                 or row.employee_id.sudo().user_id.share
                 or not row.employee_id.sudo().user_id.partner_id))
        if missing:
            names = ', '.join(missing[:5].sudo().mapped('employee_id.name'))
            raise UserError(_(
                'These selected employees need active internal user accounts to receive in-app '
                'training invitations: %s%s. Link their accounts or remove them from the invitation list.')
                % (names, '…' if len(missing) > 5 else ''))
        for rec in self:
            if rec.state != 'suggested' or not rec.selected or rec.session_id.status != 'scheduled':
                continue
            rec.write({
                'state': 'invited', 'selected': False,
            })
            rec._send_invitation_notice()

    def action_open_response(self):
        self.ensure_one()
        if self.session_id.status == 'rescheduled':
            raise UserError(_(
                'The schedule is being revised. Wait for the confirmed new invitation.'))
        if self._expire_overdue() or self._was_auto_rejected():
            return self._expired_response_notice()
        if self.state != 'invited':
            raise UserError(_('Only pending invitations can be answered.'))
        return {
            'name': _('Respond to Training Invitation'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.enrollment.response.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
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
            if rec.state in ('cancelled', 'completed', 'incomplete', 'absent'):
                continue
            was_awaiting_reconfirmation = rec.reschedule_reconfirmation_required
            rec.write({'state': 'cancelled', 'selected': False})
            if was_awaiting_reconfirmation:
                super(EdsEnrollment, rec).write({
                    'reschedule_reconfirmation_required': False,
                })
            clear_action_activities(rec.sudo())
            if rec.nomination_id:
                rec.nomination_id.write({'waitlisted': False, 'waitlist_position': 0})
            rec.message_post(body=_('Enrollment %s cancelled - seat released .') % rec.name)
            if was_awaiting_reconfirmation:
                message = _(
                    'Your participant place for rescheduled session %s was cancelled. '
                    'Your previous enrollment no longer counts, and no new invitation '
                    'will be sent.') % rec.session_id.name
                employee = rec.employee_id.sudo()
                user = employee.user_id
                if user and user.active and not user.share:
                    notify_action(rec.sudo(), user,
                                  _('Rescheduled training participation cancelled'),
                                  message, action_required=False)
                elif employee.work_contact_id:
                    rec.sudo().message_post(
                        body=message, partner_ids=[employee.work_contact_id.id])
        for session in sessions:
            self.env['eds.enrollment']._promote_waitlisted(session)

    @api.model
    def _cron_waitlist_promote(self):
        """Expire overdue invitations, then promote available seats every hour."""
        self.search([
            ('session_id.status', 'in', ('scheduled', 'ongoing')),
            ('session_id.response_deadline', '<', fields.Datetime.now()),
            ('state', 'in', ('invited', 'suggested', 'enrolled', 'waitlisted')),
        ])._expire_overdue()
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
        if session.status not in ('scheduled', 'ongoing'):
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
                'A seat is now available for %s. Training runs from %s to %s. Location/arrangement: %s.') % (
                    session.course_id.name or session.program_name or session.name,
                    session.date_start, session.date_end,
                    session._training_location_label())
            employee_user = enrollment.employee_id.sudo().user_id
            if employee_user:
                notify_action(enrollment.sudo(), employee_user,
                              _('Training seat confirmed'), message,
                              action_required=False)
            elif enrollment.employee_id.sudo().work_contact_id:
                enrollment.sudo().message_post(
                    body=message,
                    partner_ids=[enrollment.employee_id.sudo().work_contact_id.id])
            enrolled |= enrollment
        return True
