# -*- coding: utf-8 -*-
import logging
from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SuccessionCandidateInvitation(models.Model):
    _name = 'succession.candidate.invitation'
    _description = 'Succession Candidate Invitation & Expression of Interest'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'
    _rec_name = 'display_name'

    critical_position_id = fields.Many2one(
        'succession.critical.position',
        string='Critical Position',
        required=True,
        ondelete='cascade',
        tracking=True
    )
    job_id = fields.Many2one(
        'hr.job',
        related='critical_position_id.job_id',
        string='Target Job Position',
        store=True,
        readonly=True
    )
    department_id = fields.Many2one(
        'hr.department',
        related='critical_position_id.department_id',
        string='Target Department',
        store=True,
        readonly=True
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Candidate / Employee',
        required=True,
        ondelete='cascade',
        tracking=True
    )
    employee_job_id = fields.Many2one(
        'hr.job',
        string='Current Position',
        compute='_compute_employee_job_details',
        store=True,
        readonly=True
    )
    employee_department_id = fields.Many2one(
        'hr.department',
        string='Current Department',
        compute='_compute_employee_job_details',
        store=True,
        readonly=True
    )
    user_id = fields.Many2one(
        'res.users',
        related='employee_id.user_id',
        string='Employee User',
        store=True,
        readonly=True
    )
    sent_date = fields.Date(
        string='Invitation Date',
        default=fields.Date.today,
        required=True,
        tracking=True
    )
    deadline_date = fields.Date(
        string='Response Deadline',
        compute='_compute_deadline_date',
        store=True,
        readonly=False,
        tracking=True
    )
    state = fields.Selection([
        ('invited', 'Invitation Sent / Pending Response'),
        ('accepted', 'Accepted / Interest Confirmed'),
        ('declined', 'Declined'),
        ('expired', 'Expired'),
        ('nominated', 'Nominated into Pipeline'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='invited', tracking=True)
    is_expired = fields.Boolean(
        string='Is Expired',
        compute='_compute_is_expired',
        search='_search_is_expired'
    )

    invitation_notes = fields.Text(
        string='Invitation Message / Guidance',
        default=lambda self: _(
            "You have been identified as an eligible successor candidate for this critical position "
            "based on Bunna Bank's promotion and recruitment criteria. "
            "Please confirm your interest in being considered for this leadership succession path."
        )
    )
    candidate_response_notes = fields.Text(
        string='Candidate Comments / Reason',
        tracking=True
    )
    response_date = fields.Datetime(
        string='Response Timestamp',
        readonly=True,
        tracking=True
    )
    application_date = fields.Date(
        string='Application Date',
        compute='_compute_application_date',
        store=True,
        tracking=True,
        help="Date when the candidate accepted/applied to the succession invitation."
    )
    nominated_candidate_id = fields.Many2one(
        'succession.candidate',
        string='Succession Pipeline Candidate',
        readonly=True,
        ondelete='set null'
    )

    # Snapshot criteria at invitation time
    grade_name = fields.Char(string='Current Grade')
    tenure_years = fields.Float(string='Bank Service (Yrs)')
    last_promotion_months = fields.Float(string='Months Since Promotion')
    total_exp_years = fields.Float(string='Total Exp (Yrs)')
    qualification_desc = fields.Char(string='Educational Qualification & CGPA')

    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True
    )

    _uniq_position_employee = models.Constraint(
        'unique(critical_position_id, employee_id)',
        'An invitation for this employee and critical position already exists!',
    )

    @api.depends('employee_id', 'employee_id.job_id', 'employee_id.department_id')
    def _compute_employee_job_details(self):
        for rec in self:
            if rec.employee_id:
                rec.employee_job_id = rec.employee_id.job_id
                rec.employee_department_id = rec.employee_id.department_id
            else:
                rec.employee_job_id = False
                rec.employee_department_id = False

    @api.depends('critical_position_id', 'employee_id')
    def _compute_display_name(self):
        for rec in self:
            pos_name = rec.critical_position_id.display_name if rec.critical_position_id else _('Position')
            emp_name = rec.employee_id.name if rec.employee_id else _('Candidate')
            rec.display_name = f"{emp_name} - {pos_name}"

    @api.depends('response_date', 'state')
    def _compute_application_date(self):
        for rec in self:
            if rec.response_date:
                rec.application_date = rec.response_date.date()
            elif rec.state in ('accepted', 'nominated'):
                rec.application_date = rec.application_date or fields.Date.today()
            else:
                rec.application_date = False

    @api.depends('sent_date')
    def _compute_deadline_date(self):
        policy = self.env['succession.governance.policy'].get_policy()
        expiry_days = policy.invitation_expiry_days or 3
        for rec in self:
            if rec.sent_date and not rec.deadline_date:
                rec.deadline_date = rec.sent_date + timedelta(days=expiry_days)

    @api.depends('deadline_date', 'state')
    def _compute_is_expired(self):
        today = fields.Date.today()
        for rec in self:
            expired = bool(rec.deadline_date and rec.deadline_date < today and rec.state in ('invited', 'expired'))
            rec.is_expired = expired
            if expired and rec.state == 'invited':
                rec.write({'state': 'expired'})

    def _search_is_expired(self, operator, value):
        today = fields.Date.today()
        if (operator in ('=', '!=') and value) or (operator == 'in' and True in value):
            return ['|', ('state', '=', 'expired'), '&', ('deadline_date', '<', today), ('state', '=', 'invited')]
        return ['&', ('state', '!=', 'expired'), '|', ('deadline_date', '>=', today), ('deadline_date', '=', False)]

    def action_accept(self):
        """Called by candidate (or HR) to accept the succession invitation."""
        today = fields.Date.today()
        for rec in self:
            if rec.state == 'expired' or (rec.deadline_date and rec.deadline_date < today):
                if rec.state != 'expired':
                    rec.write({'state': 'expired'})
                raise UserError(_(
                    'This succession invitation expired on %s (configured acceptance window has passed). '
                    'Expired invitations can no longer be accepted.'
                ) % (rec.deadline_date or 'N/A'))
            if rec.state != 'invited':
                raise UserError(_('Only pending invitations can be accepted.'))
            rec.write({
                'state': 'accepted',
                'response_date': fields.Datetime.now(),
                'application_date': fields.Date.today(),
            })
            try:
                rec.activity_feedback(['mail.mail_activity_data_todo'])
            except Exception:
                pass
            if rec.critical_position_id:
                rec.sudo().critical_position_id.message_post(
                    body=_('Candidate %s confirmed acceptance of the succession invitation for %s.') % (
                        rec.employee_id.name, rec.critical_position_id.display_name
                    )
                )

    def action_decline(self):
        """Called by candidate (or HR) to decline the succession invitation."""
        today = fields.Date.today()
        for rec in self:
            if rec.state == 'expired' or (rec.deadline_date and rec.deadline_date < today):
                if rec.state != 'expired':
                    rec.write({'state': 'expired'})
                raise UserError(_('This succession invitation has already expired.'))
            if rec.state != 'invited':
                raise UserError(_('Only pending invitations can be declined.'))
            rec.write({
                'state': 'declined',
                'response_date': fields.Datetime.now(),
            })
            try:
                rec.activity_feedback(['mail.mail_activity_data_todo'])
            except Exception:
                pass
            if rec.critical_position_id:
                rec.sudo().critical_position_id.message_post(
                    body=_('Candidate %s declined the succession invitation for %s.') % (
                        rec.employee_id.name, rec.critical_position_id.display_name
                    )
                )

    def action_nominate_to_pipeline(self):
        """Nominate this candidate into succession.candidate."""
        created_candidates = self.env['succession.candidate']
        for rec in self:
            if rec.state != 'accepted':
                raise UserError(_('Candidate %s has not accepted the succession invitation yet (Status: %s). Only accepted candidates can be nominated into the succession pipeline.') % (rec.employee_id.name, rec.state))

            existing = self.env['succession.candidate'].search([
                ('critical_position_id', '=', rec.critical_position_id.id),
                ('employee_id', '=', rec.employee_id.id),
            ], limit=1)

            if existing:
                rec.write({
                    'state': 'nominated',
                    'nominated_candidate_id': existing.id,
                })
                created_candidates |= existing
            else:
                resp_str = rec.response_date.strftime('%Y-%m-%d') if rec.response_date else str(fields.Date.today())
                justification = _(
                    'Auto-Matched based on Recruitment Criteria and Candidate Confirmed Interest on %s. '
                    '(Grade: %s, Bank Service: %.1f yrs, Total Exp: %.1f yrs)'
                ) % (
                    resp_str,
                    rec.grade_name or 'N/A',
                    rec.tenure_years or 0.0,
                    rec.total_exp_years or 0.0,
                )
                cfg = self.env['succession.assessment.config'].get_config()
                pos = rec.critical_position_id
                candidate = self.env['succession.candidate'].with_context(skip_plan_validation=True).create({
                    'critical_position_id': rec.critical_position_id.id,
                    'employee_id': rec.employee_id.id,
                    'nominated_by_id': self.env.user.id,
                    'manager_justification': justification,
                    'plan_include_exam': True,
                    'plan_include_pms': True,
                    # Inherit evaluator scope from the critical position plan if active
                    'plan_include_manager': pos.plan_include_manager if pos.plan_status in ('active', 'draft', 'reopened') else True,
                    'plan_include_self': pos.plan_include_self if pos.plan_status in ('active', 'draft', 'reopened') else bool(cfg.enable_self_assessment),
                    'plan_include_spmc': pos.plan_include_spmc if pos.plan_status in ('active', 'draft', 'reopened') else False,
                })
                # Nominate via savepoint so any SQL failure rolls back only
                # to this point and does not abort the whole transaction.
                try:
                    with self.env.cr.savepoint():
                        candidate.action_nominate()
                except Exception as e:
                    _logger.warning(
                        'action_nominate failed for candidate %s: %s', candidate.id, e)
                # Auto-apply the position assessment plan to the newly nominated candidate
                if rec.critical_position_id.plan_status in ('active', 'draft', 'reopened') and rec.critical_position_id.assessment_line_ids:
                    try:
                        with self.env.cr.savepoint():
                            rec.critical_position_id._apply_position_plan_to_candidate(candidate)
                    except Exception as e:
                        _logger.warning('_apply_position_plan_to_candidate failed: %s', e)
                if candidate.critical_position_id.required_role_mapping_line_ids:
                    try:
                        with self.env.cr.savepoint():
                            candidate.action_compute_gap_analysis()
                    except Exception as e:
                        _logger.warning('action_compute_gap_analysis failed: %s', e)

                rec.write({
                    'state': 'nominated',
                    'nominated_candidate_id': candidate.id,
                })
                created_candidates |= candidate

            rec.critical_position_id.message_post(
                body=_('Candidate %s was nominated into the succession pipeline following invitation acceptance.') % rec.employee_id.name
            )

        cand_names = ", ".join(created_candidates.mapped('employee_id.name'))
        count = len(created_candidates)
        if count == 1:
            title = _('Candidate Successfully Nominated')
            msg = _('Candidate %s was successfully nominated to the Succession Pipeline! Assessment scorecards and evaluation plan has been initialized.') % cand_names
        else:
            title = _('Candidates Successfully Nominated')
            msg = _('Successfully nominated %d candidates (%s) to the Succession Pipeline! Assessment scorecards and evaluation plans have been initialized.') % (count, cand_names)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': msg,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def send_notification_message(self):
        """Send Discuss chat, activity & email notification to employee."""
        self.ensure_one()
        user = self.user_id or self.employee_id.user_id
        pos_title = self.critical_position_id.job_id.name if self.critical_position_id.job_id else self.critical_position_id.display_name
        dept_name = self.department_id.name if self.department_id else ''
        deadline_str = str(self.deadline_date) if self.deadline_date else 'N/A'

        message = (
            f"Dear {self.employee_id.name},\n\n"
            f"You have been identified and shortlisted as an eligible successor candidate for the following Critical Position:\n\n"
            f"• Position: {pos_title}\n"
            f"• Directorate/Department: {dept_name}\n"
            f"• Response Deadline: {deadline_str}\n\n"
            f"Please log in to review your Succession Opportunities under 'My Succession Invitations' "
            f"and confirm your acceptance before the deadline.\n\n"
            f"Best regards,\n"
            f"Bunna Bank Succession Planning Team"
        )

        if user and user.partner_id:
            try:
                channel = self.env['discuss.channel']._get_or_create_chat(partners_to=[user.partner_id.id])
                channel.message_post(
                    body=message,
                    message_type='comment',
                    subtype_xmlid='mail.mt_comment',
                )
            except Exception:
                pass

            try:
                self.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=user.id,
                    summary=f'Succession Opportunity: {pos_title}',
                    note=message,
                    date_deadline=self.deadline_date,
                )
            except Exception:
                pass

        # Email Notification to employee's email if available
        emp_email = self.employee_id.work_email or self.employee_id.private_email or (user.email if user else False)
        if emp_email:
            try:
                mail_vals = {
                    'subject': _('Succession Opportunity Invitation: %s') % pos_title,
                    'body_html': f"""
                        <div style="font-family: Arial, sans-serif; font-size: 14px; line-height: 1.6; color: #333333;">
                            <p>Dear <strong>{self.employee_id.name}</strong>,</p>
                            <p>You have been identified and shortlisted as an eligible successor candidate for the critical leadership position:</p>
                            <div style="background-color: #f8fafc; border-left: 4px solid #0284c7; padding: 12px 16px; margin: 16px 0; border-radius: 4px;">
                                <p style="margin: 4px 0;"><strong>Position:</strong> {pos_title}</p>
                                <p style="margin: 4px 0;"><strong>Department:</strong> {dept_name}</p>
                                <p style="margin: 4px 0;"><strong>Response Deadline:</strong> <span style="color: #dc2626; font-weight: bold;">{deadline_str}</span></p>
                            </div>
                            <p>Please log in to the Bunna Bank HR / Succession Management portal, open <strong>"My Succession Invitations"</strong>, and confirm your acceptance before the deadline.</p>
                            <p style="margin-top: 24px;">Best regards,<br/><strong>Bunna Bank Succession Planning Team</strong></p>
                        </div>
                    """,
                    'email_to': emp_email,
                }
                self.env['mail.mail'].sudo().create(mail_vals).send()
            except Exception:
                pass

    @api.model
    def _check_and_expire_overdue(self):
        """Immediately checks and transitions any pending invitations past deadline to 'expired'."""
        if self.env.context.get('skip_expire_check'):
            return True
        today = fields.Date.today()
        policy = self.env['succession.governance.policy'].get_policy()
        expiry_days = policy.invitation_expiry_days or 3
        ctx_self = self.with_context(skip_expire_check=True).sudo()
        # First ensure pending invitations have deadline_date populated
        missing_deadlines = ctx_self.search([
            ('state', '=', 'invited'),
            ('deadline_date', '=', False),
        ])
        for inv in missing_deadlines:
            base_date = inv.sent_date or (inv.create_date.date() if inv.create_date else today)
            inv.with_context(skip_expire_check=True).write({'deadline_date': base_date + timedelta(days=expiry_days)})

        overdue_invitations = ctx_self.search([
            ('state', '=', 'invited'),
            ('deadline_date', '<', today),
        ])
        for inv in overdue_invitations:
            inv.with_context(skip_expire_check=True).write({'state': 'expired'})
            if inv.critical_position_id:
                try:
                    inv.critical_position_id.message_post(
                        body=_('Succession invitation for candidate %s expired without response (Deadline: %s).') % (
                            inv.employee_id.name, inv.deadline_date
                        )
                    )
                except Exception:
                    pass
        return True

    @api.model
    def search_fetch(self, *args, **kwargs):
        if not self.env.context.get('skip_expire_check'):
            self._check_and_expire_overdue()
        return super().search_fetch(*args, **kwargs)

    @api.model
    def web_search_read(self, *args, **kwargs):
        if not self.env.context.get('skip_expire_check'):
            self._check_and_expire_overdue()
        return super().web_search_read(*args, **kwargs)

    @api.model
    def _cron_expire_pending_invitations(self):
        """Daily cron job: Automatically marks pending invitations past deadline as expired."""
        return self._check_and_expire_overdue()


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    succession_invitation_ids = fields.One2many(
        'succession.candidate.invitation',
        'employee_id',
        string='Succession Invitations',
    )
    succession_invitation_count = fields.Integer(
        string='Succession Invitations Count',
        compute='_compute_succession_invitation_count',
    )

    @api.depends('succession_invitation_ids')
    def _compute_succession_invitation_count(self):
        for rec in self:
            rec.succession_invitation_count = len(rec.succession_invitation_ids)

    def action_view_succession_invitations(self):
        self.ensure_one()
        return {
            'name': _('Succession Invitations'),
            'type': 'ir.actions.act_window',
            'res_model': 'succession.candidate.invitation',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('employee_id', '=', self.id)],
            'context': {
                'default_employee_id': self.id,
                'search_default_employee_id': self.id,
            },
        }
