# -*- coding: utf-8 -*-
from datetime import date, datetime

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class EdsNomination(models.Model):
    """Training nomination & multi-level approval (, ...030).

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
                                  tracking=True)
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
        help='Mandatory for ad-hoc nominations (, business rule).')
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

    # Approval actors (audit of the chain, )
    line_manager_approved_by = fields.Many2one('res.users', string='Line Manager Approved By',
                                               readonly=True)
    lnd_approved_by = fields.Many2one('res.users', string='L&D Approved By', readonly=True)
    approved_by = fields.Many2one('res.users', string='Final Approved By', readonly=True)
    approved_date = fields.Datetime(string='Approval Date', readonly=True)
    rejected_by = fields.Many2one('res.users', string='Rejected By', readonly=True)
    rejected_reason = fields.Text(string='Rejection Reason')

    # Optional Budget/HR gate ( via settings or per-session approval flow)
    budget_hr_required = fields.Boolean(
        string='Budget/HR Approval Required', compute='_compute_budget_hr_required')
    budget_hr_approved = fields.Boolean(string='Budget/HR Approved', readonly=True)
    budget_hr_approved_by = fields.Many2one('res.users', string='Budget/HR Approved By', readonly=True)
    budget_hr_approval_date = fields.Datetime(string='Budget/HR Approval Date', readonly=True)

    # Capacity / waitlist (/028)
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

    _sql_constraints = [
        ('session_employee_uniq', 'unique(session_id, employee_id)',
         'This employee already has a nomination for this session!'),
    ]

    @api.depends('session_id')
    def _compute_budget_hr_required(self):
        require_by_config = self._get_bool_param('eds.nomination_require_budget', False)
        for rec in self:
            rec.budget_hr_required = bool(
                rec.session_id and rec.session_id.approval_flow == 'budget_hr'
                or require_by_config)

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
        """/025: TNA-based needs an approved entry; ad-hoc needs a justification."""
        self.ensure_one()
        if self.nomination_type == 'tna_based':
            if not self.tna_entry_id:
                raise UserError(_('TNA-based nominations must reference an approved training '
                                  'need .'))
            if self.tna_entry_id.state not in ('approved', 'converted'):
                raise UserError(_('The referenced training need is not approved yet .'))
            if self.tna_entry_id.employee_id and self.tna_entry_id.employee_id != self.employee_id:
                raise UserError(_('The training need belongs to a different employee .'))
        elif self.nomination_type == 'ad_hoc' and not self.justification:
            raise UserError(_('Ad-hoc nominations require a mandatory justification and L&D '
                              'approval .'))

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

    def action_line_manager_approve(self):
        """Submitted -> Line Manager Approved (skippable via settings)."""
        for rec in self:
            rec._require_group('group_eds_line_manager')
            if rec.state != 'submitted':
                raise UserError(_('Only submitted nominations can be approved by the line manager.'))
            rec.write({'state': 'line_manager_approved',
                       'line_manager_approved_by': self.env.user.id})
            rec._notify(_('Nomination %s approved by Line Manager.') % rec.name)

    def action_lnd_approve(self):
        """(Submitted | Line Manager Approved) -> L&D Approved.

        L&D is the segregation point against the nominator (EDS-026).
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

    def action_final_approve(self):
        """L&D Approved -> Approved: segregation + capacity assignment (/027)."""
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
            rec._notify(_('Nomination %s approved - seat assigned .') % rec.name)

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
            if rec.state != 'approved':
                raise UserError(_('Only approved nominations can be confirmed by the employee.'))
            rec.write({'employee_confirmed': 'confirmed', 'confirmation_date': fields.Datetime.now()})
            rec._notify(_('%s confirmed their participation.') % rec.employee_id.name)

    def action_employee_decline(self):
        """The employee declines - frees the seat for the next waitlisted participant."""
        for rec in self:
            rec._check_employee_actor()
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

    # ── Capacity & waitlist (/028) ─────────────────────────────────
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
        """chatter notification to the employee (and their manager)."""
        self.ensure_one()
        partner_ids = []
        if self.employee_id and self.employee_id.work_contact_id:
            partner_ids.append(self.employee_id.work_contact_id.id)
        self.message_post(body=body, partner_ids=partner_ids)


class EdsEnrollment(models.Model):
    """Enrollment / participation seat on a session (/028/030).

    Created when a nomination is finally approved: `enrolled` when a seat is free,
    `waitlisted` with a FIFO position otherwise. Auto-promoted by the cron or on
    any seat release (withdrawal / decline / cancellation).
    """
    _name = 'eds.enrollment'
    _description = 'Session Enrollment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'session_id, waitlist_position, id'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    session_id = fields.Many2one('eds.session', string='Session', required=True,
                                 ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    job_position_id = fields.Many2one('hr.job', string='Job Position',
                                      related='employee_id.job_position', readonly=True)
    department_id = fields.Many2one('hr.department', string='Department',
                                    related='employee_id.department_id', readonly=True)
    nomination_id = fields.Many2one('eds.nomination', string='Nomination', ondelete='cascade')
    state = fields.Selection([
        ('enrolled', 'Enrolled'),
        ('waitlisted', 'Waitlisted'),
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed'),
    ], string='Status', default='enrolled', required=True, tracking=True)
    enrolled_date = fields.Date(string='Enrolled Date', default=fields.Date.context_today)
    waitlist_position = fields.Integer(string='Waitlist Position', default=0)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    _sql_constraints = [
        ('session_employee_uniq', 'unique(session_id, employee_id)',
         'This employee is already enrolled (or waitlisted) for this session!'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.enrollment') or _('New')
        return super().create(vals_list)

    def action_cancel(self):
        """Cancel the enrollment (withdrawal / decline / session cancellation) and promote."""
        sessions = self.mapped('session_id')
        for rec in self:
            if rec.state in ('cancelled', 'completed'):
                continue
            rec.write({'state': 'cancelled'})
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
            enrollment.write({'state': 'enrolled'})
            if enrollment.nomination_id:
                enrollment.nomination_id.write({'waitlisted': False, 'waitlist_position': 0})
            enrollment.message_post(
                body=_('Promoted from the waitlist - a seat became available .'))
            enrolled |= enrollment
        return True
