# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class SuccessionManagerCareerDiscussion(models.Model):
    """
    Structured Career Discussion Record (FR-MHT-003).
    Managers document career discussions, guidance, agreed development
    actions, employee aspirations, and follow-up commitments.
    """
    _name = 'succession.career.discussion'
    _description = 'Manager Career Discussion Record'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'
    _rec_name = 'display_name'

    # Sudo Access Layer for Employee Relations (Preserves Bank-wide Privacy)
    def read(self, fields=None, load='_classic_read'):
        self.check_access('read')
        return super(SuccessionManagerCareerDiscussion, self.sudo()).read(fields=fields, load=load)

    def web_read(self, specification: dict[str, dict]) -> list[dict]:
        self.check_access('read')
        return super(SuccessionManagerCareerDiscussion, self.sudo()).web_read(specification)

    @api.model
    def web_search_read(self, domain=None, specification=None, offset=0, limit=None, order=None, count_limit=None):
        records = self.search_fetch(domain or [], (specification or {}).keys(), offset=offset, limit=limit, order=order)
        values_records = records.sudo().web_read(specification or {})
        return self._format_web_search_read_results(domain or [], values_records, offset, limit, count_limit)


    display_name = fields.Char(
        string='Discussion', compute='_compute_display_name', store=True)

    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True,
        tracking=True, ondelete='restrict', index=True)
    can_select_all_employees = fields.Boolean(
        string='Can Select All Employees',
        compute='_compute_can_select_all_employees',
        default=lambda self: self._is_privileged_discussion_user())
    candidate_id = fields.Many2one(
        'succession.candidate', string='Succession Candidate',
        domain="[('state', 'in', ('approved', 'placed'))]",
        required=True, tracking=True, ondelete='restrict', index=True)
    dev_plan_id = fields.Many2one(
        'succession.development.plan', string='Development Plan',
        required=False, tracking=True, ondelete='set null', index=True)
    manager_id = fields.Many2one(
        'hr.employee', string='Manager', required=True,
        default=lambda self: self.env.user.employee_id,
        tracking=True, index=True)
    discussion_date = fields.Date(
        string='Discussion Date', required=True,
        default=fields.Date.today, tracking=True, index=True)
    discussion_type = fields.Selection([
        ('career_review', 'Career Development Review'),
        ('aspiration_alignment', 'Aspiration Alignment'),
        ('readiness_discussion', 'Readiness Discussion'),
        ('performance_career', 'Performance & Career Link'),
        ('succession_nomination', 'Succession Nomination Discussion'),
        ('annual_pdp', 'Annual PDP Review'),
    ], string='Discussion Type', required=True,
       default='career_review', tracking=True, index=True)

    # --- Discussion Content (All Mandatory) ---
    career_interests = fields.Text(
        string='Employee Career Interests & Aspirations', required=True,
        help="Record the employee's stated career interests discussed in this session.")
    manager_guidance = fields.Text(
        string='Manager Guidance & Expectations', required=False)
    strengths_discussed = fields.Text(
        string='Key Strengths Discussed', required=True)
    development_areas = fields.Text(
        string='Development Areas Identified', required=True)

    # --- Action Commitments (All Mandatory) ---
    agreed_actions = fields.Html(
        string='Agreed Development Actions', required=False,
        help='What actions were agreed upon (employee and manager commitments)?')
    follow_up_date = fields.Date(
        string='Follow-Up Review Date', required=True, tracking=True)
    follow_up_notes = fields.Text(
        string='Follow-Up Notes', required=False)

    # --- Outcome ---
    outcome_id = fields.Many2one(
        'succession.career.discussion.outcome', domain="[('active', '=', True)]",
        string='Discussion Outcome',
        required=True,
        tracking=True,
        ondelete='restrict',
        index=True,
        help='Formal consensus outcome from the career discussion session.'
    )
    outcome = fields.Char(
        string='Discussion Outcome Name',
        related='outcome_id.name',
        readonly=True
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed / Signed Off'),
    ], string='Status', default='draft', tracking=True, index=True)

    employee_acknowledgement = fields.Boolean(
        string='Employee Acknowledges This Record', default=False)

    @api.model
    def _is_privileged_discussion_user(self):
        """Return True when the active user belongs to Admin, PPDD, or SPMC."""
        user = self.env['res.users'].sudo().browse(self.env.uid)
        if not user.exists():
            return False
        return (
            self.env.uid == 1
            or user.has_group('base.group_system')
            or user.has_group('bunna_succession_management.group_succession_admin')
            or user.has_group('bunna_succession_management.group_succession_ppdd')
            or user.has_group('bunna_succession_management.group_succession_spmc')
        )

    @api.depends_context('uid')
    def _compute_can_select_all_employees(self):
        is_privileged = self._is_privileged_discussion_user()
        for rec in self:
            rec.can_select_all_employees = is_privileged

    @api.constrains('employee_id')
    def _check_employee_selection_scope(self):
        """Restrict non-privileged managers to their subordinates and coachees."""
        if self._is_privileged_discussion_user():
            return
        uid = self.env.uid
        for rec in self:
            emp = rec.employee_id.sudo()
            if not emp:
                continue
            is_subordinate = emp.parent_id and emp.parent_id.user_id.id == uid
            is_coachee = emp.coach_id and emp.coach_id.user_id.id == uid
            if not (is_subordinate or is_coachee):
                raise ValidationError(_(
                    'You can only create career discussions for employees under you '
                    'or employees for whom you are their coach.'
                ))

    @api.constrains('candidate_id')
    def _check_candidate_spmc_approved(self):
        for rec in self:
            if rec.candidate_id and rec.candidate_id.state not in ('approved', 'placed'):
                status_label = dict(rec.candidate_id._fields['state'].selection).get(
                    rec.candidate_id.state, rec.candidate_id.state)
                raise ValidationError(_(
                    "Cannot Conduct Career Discussion: SPMC Approval Required!\n\n"
                    "Candidate '%(emp)s' is currently in status '%(status)s'.\n\n"
                    "Career Discussions can only be conducted after the SPMC Committee has officially reviewed and approved the candidate's assessment.",
                    emp=rec.candidate_id.employee_id.name or rec.candidate_id.display_name,
                    status=status_label,
                ))

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            current_user_emp = self.env.user.employee_id
            if current_user_emp and (self.employee_id.coach_id == current_user_emp or self.employee_id.parent_id == current_user_emp):
                self.manager_id = current_user_emp
            elif self.employee_id.coach_id:
                self.manager_id = self.employee_id.coach_id
            elif self.employee_id.parent_id:
                self.manager_id = self.employee_id.parent_id

            cand = self.env['succession.candidate'].search([
                ('employee_id', '=', self.employee_id.id),
                ('active', '=', True),
                ('state', 'in', ('approved', 'placed')),
            ], limit=1)
            if cand:
                self.candidate_id = cand

    @api.depends('employee_id', 'discussion_date', 'discussion_type')
    def _compute_display_name(self):
        for rec in self:
            emp = rec.sudo().employee_id.name if rec.employee_id else '?'
            dtype = dict(rec._fields['discussion_type'].selection).get(
                rec.discussion_type, '') if rec.discussion_type else ''
            date = rec.discussion_date.strftime('%d %b %Y') if rec.discussion_date else ''
            rec.display_name = '%s — %s (%s)' % (emp, dtype, date)

    def action_confirm(self):
        self.write({'state': 'confirmed'})
        self.message_post(body=_('Career discussion confirmed and signed off by %s.') % self.env.user.name)
        if self.candidate_id:
            self.candidate_id.message_post(
                body=_('Career discussion (%s) confirmed and signed off by %s.') % (
                    self.display_name or self.discussion_type, self.env.user.name
                )
            )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Discussion Confirmed'),
                'message': _('Career discussion with %s has been confirmed and signed off.') % (self.sudo().employee_id.name or ''),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    def write(self, vals):
        allowed_confirmed_fields = {
            'state', 'message_follower_ids', 'message_ids', 'activity_ids',
        }
        for rec in self:
            if rec.state == 'confirmed' and not self.env.context.get('bypass_discussion_lock'):
                restricted = set(vals.keys()) - allowed_confirmed_fields
                if restricted:
                    field_labels = [rec._fields[f].string for f in restricted if f in rec._fields]
                    raise UserError(_(
                        "Cannot modify Career Discussion '%(name)s'!\n\n"
                        "This career discussion has already been confirmed and signed off and cannot be edited.\n\n"
                        "Confirmed career discussions are immutable official records.\n\n"
                        "Restricted field(s): %(fields)s",
                        name=rec.display_name or 'Discussion',
                        fields=', '.join(field_labels) or ', '.join(restricted),
                    ))
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.state == 'confirmed' and not self.env.context.get('bypass_discussion_lock'):
                raise UserError(_(
                    "Cannot delete confirmed Career Discussion '%(name)s'!\n\n"
                    "Confirmed discussion records cannot be deleted.",
                    name=rec.display_name or 'Discussion',
                ))
        return super().unlink()


class SuccessionCareerDiscussionOutcome(models.Model):
    _name = 'succession.career.discussion.outcome'
    _description = 'Career Discussion Outcome'
    _order = 'sequence, name, id'

    name = fields.Char(string='Discussion Outcome', required=True, translate=True, index='trigram')
    code = fields.Char(string='Code', index=True)
    sequence = fields.Integer(string='Sequence', default=10, index=True)
    description = fields.Text(string='Description')
    active = fields.Boolean(default=True, index=True)
