# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class EdsAnnualPlan(models.Model):
    """Annual Learning & Development Plan and Calendar (-026, ...022).

    The approved TNA needs and approved curricula are assembled into a draft annual
    plan (/) within the calendar SLA, routed through the
    Director PPDD -> CPCO -> SMC approval chain and published. Publishing
    auto-activates the downstream sessions so nominations can start. Approved
    unscheduled training requests amend the published plan as addenda
    (, /076). Delivery is monitored with planned-vs-actual variance
    per line.
    """
    _name = 'eds.annual.plan'
    _description = 'Annual L&D Plan & Calendar'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    fiscal_year = fields.Char(string='Fiscal Year', required=True, index=True,
                              default=lambda self: str(date.today().year), tracking=True)
    line_ids = fields.One2many('eds.annual.plan.line', 'plan_id', string='Plan Lines')
    line_count = fields.Integer(string='Programs', compute='_compute_counts')
    delivered_count = fields.Integer(string='Delivered', compute='_compute_counts')
    budget_total = fields.Monetary(
        string='Budget Total', compute='_compute_budget', store=True,
        currency_field='budget_currency_id')
    budget_currency_id = fields.Many2one('res.currency', related='company_id.currency_id',
                                         readonly=True)
    execution_rate = fields.Float(
        string='Execution Rate (%)', compute='_compute_execution_rate', store=True,
        help='Share of plan lines whose sessions have been delivered.')
    calendar_generation_date = fields.Date(string='Calendar Generated On', readonly=True)
    calendar_sla_deadline = fields.Date(
        string='Calendar SLA Deadline', compute='_compute_calendar_sla', store=True,
        help='Computed from the calendar SLA in settings (default 5 working days, ).')
    sla_breached = fields.Boolean(
        string='SLA Breached', compute='_compute_calendar_sla', store=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft (Creation)'),
        ('team_leader_review', 'Team Leader Review (Checker)'),
        ('director_review', 'Director Review'),
        ('chief_approval', 'Chief Approval'),
        ('published', 'Published'),
        ('amended', 'Amended'),
    ], string='Status', default='draft', required=True, tracking=True)

    # Multi-Role Workflow Participants
    creator_id = fields.Many2one('res.users', string='Created By', default=lambda self: self.env.user, tracking=True)
    team_leader_id = fields.Many2one('res.users', string='Team Leader (Checker)', tracking=True)
    reviewer_id = fields.Many2one('res.users', string='Director PPDD', tracking=True)
    approver_id = fields.Many2one('res.users', string='Chief / Approver', tracking=True)
    endorser_id = fields.Many2one('res.users', string='Endorser', tracking=True)
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    approval_date = fields.Datetime(string='Approval Date', readonly=True)

    # CEO Signature Memo (Requirement 12 - Optional)
    ceo_memo_attachment = fields.Binary(string='CEO Signature Memo (Optional)', attachment=True)
    ceo_memo_filename = fields.Char(string='CEO Memo Filename')

    # Return remarks & Feedback (Requirement 12)
    last_return_reason = fields.Text(string='Last Return Reason / Remarks', readonly=True, tracking=True)
    review_remarks = fields.Text(string='Reviewer Remarks / Feedback')

    approval_history_ids = fields.One2many(
        'eds.approval.history', 'annual_plan_id', string='Approval History',
        domain=[('model', '=', 'eds.annual.plan')])

    amendment_ids = fields.One2many(
        'eds.unscheduled.request', 'annual_plan_id', string='Amendments',
        help='Approved unscheduled training requests appended as addenda (/075/076).')
    amendment_count = fields.Integer(string='Amendment Count', compute='_compute_counts')
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.depends('line_ids', 'line_ids.status')
    def _compute_counts(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)
            rec.delivered_count = len(rec.line_ids.filtered(lambda l: l.status == 'delivered'))
            rec.amendment_count = len(rec.amendment_ids)

    @api.depends('line_ids.budget_allocated', 'line_ids.budget_currency_id',
                 'line_ids.scheduled_date')
    def _compute_budget(self):
        for rec in self:
            total = 0.0
            for line in rec.line_ids:
                source_currency = line.budget_currency_id or rec.budget_currency_id
                if source_currency and rec.budget_currency_id and source_currency != rec.budget_currency_id:
                    total += source_currency._convert(
                        line.budget_allocated, rec.budget_currency_id,
                        rec.company_id, line.scheduled_date or fields.Date.context_today(rec))
                else:
                    total += line.budget_allocated
            rec.budget_total = total

    def _get_preview_summary(self):
        self.ensure_one()
        lines = self.line_ids
        methods = [('internal', _('Internal')), ('local_external', _('Local External')),
                   ('international', _('International'))]
        by_method = [{
            'key': key, 'label': label,
            'lines': lines.filtered(lambda line, method=key: line.delivery_method == method),
        } for key, label in methods]
        currency_totals = {}
        for line in lines:
            currency = line.budget_currency_id or self.budget_currency_id
            if currency:
                currency_totals[currency] = currency_totals.get(currency, 0.0) + line.budget_allocated
        return {
            'program_count': len(lines),
            'request_count': sum(lines.mapped('course_demand_id.request_count')),
            'by_method': by_method,
            'currency_totals': [(currency, amount) for currency, amount in currency_totals.items()],
        }

    def action_preview_pdf(self):
        self.ensure_one()
        return self.env.ref('employee_development_system.action_report_eds_annual_plan_preview').report_action(self)

    @api.depends('line_ids', 'line_ids.status')
    def _compute_execution_rate(self):
        for rec in self:
            rec.execution_rate = round(
                len(rec.line_ids.filtered(lambda l: l.status == 'delivered')) * 100.0
                / len(rec.line_ids), 2) if rec.line_ids else 0.0

    @api.depends('create_date', 'calendar_generation_date')
    def _compute_calendar_sla(self):
        today = date.today()
        for rec in self:
            if rec.create_date:
                days = rec._get_int_param('eds.calendar_sla_days', 5)
                rec.calendar_sla_deadline = self.env['eds.tna.cycle']._add_working_days(
                    rec.create_date.date(), days)
            else:
                rec.calendar_sla_deadline = False
            rec.sla_breached = bool(
                rec.calendar_sla_deadline and rec.calendar_sla_deadline < today
                and rec.state == 'draft')

    @api.constrains('fiscal_year', 'state')
    def _check_fiscal_year_unique(self):
        for rec in self:
            if rec.fiscal_year and rec.state in ('team_leader_review', 'director_review', 'chief_approval', 'published', 'amended'):
                duplicates = self.search([
                    ('fiscal_year', '=', rec.fiscal_year),
                    ('id', '!=', rec.id),
                    ('state', 'in', ('team_leader_review', 'director_review', 'chief_approval', 'published', 'amended')),
                ])
                if duplicates:
                    raise ValidationError(_(
                        'An approved or active Annual L&D Plan (%s) already exists for Fiscal Year %s. '
                        'Only one official annual plan can be processed per fiscal year.'
                    ) % (duplicates[0].name, rec.fiscal_year))

    @api.model
    def _get_int_param(self, key, default):
        try:
            # sudo(): config parameters are only readable by group_system; computed defaults
            # must resolve for officers/employees (the framework itself always suds here).
            return int(self.env['ir.config_parameter'].sudo().get_param(key, str(default)))
        except ValueError:
            return default

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not self.env.su:
                if vals.get('state', 'draft') != 'draft':
                    raise UserError(_('Annual plans must start as drafts and follow the approval workflow.'))
                vals['creator_id'] = self.env.user.id
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.annual.plan') or _('New')
        return super().create(vals_list)

    def _check_can_edit_content(self):
        """Apply the same actor boundary to form, import and RPC edits."""
        if self.env.su:
            return
        user = self.env.user
        manager = user.has_group('employee_development_system.group_eds_manager')
        chief = user.has_group('employee_development_system.group_eds_admin')
        for rec in self:
            if rec.state == 'draft':
                allowed = user == rec.creator_id or manager
            elif rec.state == 'team_leader_review':
                allowed = manager and user != rec.creator_id and (
                    not rec.team_leader_id or user == rec.team_leader_id)
            elif rec.state == 'director_review':
                allowed = manager and user not in (rec.creator_id, rec.team_leader_id) and (
                    not rec.reviewer_id or user == rec.reviewer_id)
            elif rec.state == 'chief_approval':
                allowed = chief and user not in (
                    rec.creator_id, rec.team_leader_id, rec.reviewer_id) and (
                    not rec.approver_id or user == rec.approver_id)
            elif rec.state == 'amended':
                allowed = manager
            else:
                allowed = False
            if not allowed:
                raise UserError(_('You cannot edit the content of this plan at its current approval stage.'))

    def write(self, vals):
        if not self.env.su:
            if 'state' in vals:
                raise UserError(_('Use the annual plan review actions to change its status.'))
            content_fields = {
                'fiscal_year', 'company_id', 'line_ids', 'amendment_ids', 'notes',
                'review_remarks', 'ceo_memo_attachment', 'ceo_memo_filename',
                'creator_id', 'team_leader_id', 'reviewer_id', 'approver_id',
                'endorser_id', 'approved_by_id', 'approval_date', 'last_return_reason',
            }
            if content_fields.intersection(vals):
                self._check_can_edit_content()
        return super().write(vals)

    def _write_workflow_values(self, vals):
        """Called only after a review action has checked its assigned actor."""
        return super(EdsAnnualPlan, self).write(vals)

    # ── Calendar generation (/020) ───────────────────────────────────
    def action_generate_calendar(self):
        """Build this year's draft calendar from courses explicitly selected in TNA."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('The calendar can only be generated while the plan is a draft.'))
        assessment_year = (self.fiscal_year or '')[:4]
        cycles = self.env['eds.tna.cycle'].search([
            ('year', '=', assessment_year), ('state', '!=', 'draft'),
            ('company_id', '=', self.company_id.id),
        ])
        for cycle in cycles.filtered(lambda rec: rec.course_demand_dirty or not rec.course_demand_last_sync):
            cycle._sync_course_demand()
        selected = cycles.mapped('course_summary_ids').filtered('selected_for_planning')
        if not selected:
            raise UserError(_(
                'Select courses on a TNA cycle for assessment year %s before generating this calendar.')
                % assessment_year)
        existing_course_ids = set(self.line_ids.mapped('course_id.id'))
        existing_prog_names = set(self.line_ids.mapped('program_name'))
        new_lines = []
        for demand in selected:
            course = demand.course_id
            if course and course.id in existing_course_ids:
                continue
            if demand.course_name in existing_prog_names:
                continue
            new_lines.append((0, 0, {
                'course_demand_id': demand.id,
                'course_id': course.id if course else False,
                'program_name': demand.course_name,
                'delivery_method': demand.delivery_method or 'internal',
                'program_category': course.program_category if course else 'technical_functional',
                'target_audience': course.target_audience if course else 'all_staff',
                'duration_days': demand.duration_days or 1,
                'planned_participants': demand.total_employees,
                'quarter': demand.target_quarter or 'q1',
            }))
            if course:
                existing_course_ids.add(course.id)
            existing_prog_names.add(demand.course_name)

        if new_lines:
            self.write({'line_ids': new_lines})
        created = len(new_lines)
        self.calendar_generation_date = date.today()
        self.message_post(
            body=_('Calendar generated for %s - %d programs added. SLA deadline: %s.')
            % (self.name, created, self.calendar_sla_deadline))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'eds.annual.plan',
            'res_id': self.id,
            'view_mode': 'form',
        }

    @api.model
    def _add_approved_curriculum(self, curriculum):
        """Curriculum approval updates catalog content, never annual demand choices."""
        return self.browse()

    # ── Approval chain with segregation of duties ─────────────────
    def _check_segregation(self):
        """Reviewer != Endorser != Approver."""
        self.ensure_one()
        users = [self.reviewer_id.id, self.endorser_id.id, self.approver_id.id]
        present = [u for u in users if u]
        if len(present) != len(set(present)):
            raise ValidationError(_(
                'Segregation of Duties Violation: Reviewer, Endorser and '
                'Approver must all be different individuals.'))

    def _log_approval_step(self, state_from, state_to, comment=''):
        self.env['eds.approval.history'].sudo().create({
            'annual_plan_id': self.id,
            'state_from': state_from,
            'state_to': state_to,
            'comment': comment or _('Moved %s -> %s') % (state_from, state_to),
        })

    def _require_manager(self):
        if not (self.env.su or self.env.user.has_group('employee_development_system.group_eds_manager')
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('This approval step requires L&D Manager authority.'))

    def _notify_role_users(self, group_xml_id, message):
        """Send notification via chatter and system notification."""
        group = self.env.ref('employee_development_system.' + group_xml_id, raise_if_not_found=False)
        assigned = {
            'group_eds_manager': self.team_leader_id if self.state == 'team_leader_review' else self.reviewer_id,
            'group_eds_admin': self.approver_id,
        }.get(group_xml_id)
        recipients = assigned if assigned else (group.user_ids if group else self.env['res.users'])
        partner_ids = recipients.filtered('partner_id').mapped('partner_id').ids
        self.message_post(body=message, partner_ids=partner_ids)

    def _require_stage_actor(self, stage):
        self.ensure_one()
        if self.env.su:
            return
        user = self.env.user
        roles = {
            'creator': ('group_eds_officer', self.creator_id),
            'team_leader': ('group_eds_manager', self.team_leader_id),
            'director': ('group_eds_manager', self.reviewer_id),
            'chief': ('group_eds_admin', self.approver_id),
        }
        group_name, assigned = roles[stage]
        if not user.has_group('employee_development_system.' + group_name):
            raise UserError(_('Your EDS role cannot perform this approval step.'))
        if assigned and assigned != user:
            raise UserError(_('This approval step is assigned to %s.') % assigned.name)
        if stage == 'team_leader' and user == self.creator_id:
            raise UserError(_('The creator cannot check their own plan.'))
        if stage == 'director' and user in (self.creator_id, self.team_leader_id):
            raise UserError(_('The director reviewer must differ from the creator and checker.'))
        if stage == 'chief' and user in (self.creator_id, self.team_leader_id, self.reviewer_id):
            raise UserError(_('The chief approver must differ from previous reviewers.'))

    def action_submit_to_team_leader(self):
        """Officer, Junior, or Senior creates plan and submits to Team Leader (Checker)."""
        for rec in self:
            rec._require_stage_actor('creator')
            if rec.state != 'draft':
                raise UserError(_('Only draft plans can be submitted to the Team Leader.'))
            if not rec.line_ids:
                raise UserError(_('Please add courses/programs to the plan before submitting.'))
            rec._write_workflow_values({'state': 'team_leader_review'})
            rec._log_approval_step('draft', 'team_leader_review', _('Submitted for Team Leader review.'))
            rec.message_post(body=_('Annual plan %s submitted to Team Leader (Checker) for review.') % rec.name)
            rec._notify_role_users('group_eds_manager', _('Annual L&D Plan %s is pending your review.') % rec.name)

    def action_team_leader_forward(self):
        """Team Leader (Checker) edits/verifies and forwards to Director."""
        for rec in self:
            rec._require_stage_actor('team_leader')
            if rec.state != 'team_leader_review':
                raise UserError(_('Only plans under Team Leader review can be forwarded.'))
            rec.team_leader_id = self.env.user.id
            rec._write_workflow_values({'state': 'director_review'})
            rec._log_approval_step('team_leader_review', 'director_review', rec.review_remarks or _('Verified by Team Leader'))
            rec.message_post(body=_('Annual plan %s verified by Team Leader %s and forwarded to Director PPDD.')
                             % (rec.name, self.env.user.name))
            rec._notify_role_users('group_eds_manager', _('Annual L&D Plan %s forwarded to Director PPDD.') % rec.name)

    def action_team_leader_return_wizard(self):
        """Team Leader returns plan to creator with mandatory justification remarks."""
        self.ensure_one()
        self._require_stage_actor('team_leader')
        return {
            'name': _('Return Plan to Creator'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.plan.return.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_plan_id': self.id,
                'default_target_state': 'draft',
                'default_stage_name': 'Team Leader Return to Creator',
            }
        }

    def action_director_forward(self):
        """Director PPDD reviews, attaches optional CEO memo, and forwards to Chief."""
        for rec in self:
            rec._require_stage_actor('director')
            if rec.state != 'director_review':
                raise UserError(_('Only plans under Director review can be forwarded to the Chief.'))
            rec.reviewer_id = self.env.user.id
            rec._write_workflow_values({'state': 'chief_approval'})
            memo_msg = _(" (with CEO signature memo attached)") if rec.ceo_memo_attachment else ""
            rec._log_approval_step('director_review', 'chief_approval', (rec.review_remarks or _('Endorsed by Director')) + memo_msg)
            rec.message_post(body=_('Annual plan %s endorsed by Director PPDD %s%s and forwarded to Chief for approval.')
                             % (rec.name, self.env.user.name, memo_msg))
            rec._notify_role_users('group_eds_admin', _('Annual L&D Plan %s requires Chief approval.') % rec.name)

    def action_director_return_wizard(self):
        """Director PPDD returns plan to Team Leader or Creator with justification remarks."""
        self.ensure_one()
        self._require_stage_actor('director')
        return {
            'name': _('Return Plan from Director'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.plan.return.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_plan_id': self.id,
                'default_target_state': 'team_leader_review',
                'default_stage_name': 'Director Return to Team Leader',
            }
        }

    def action_chief_approve(self):
        """Chief approves and publishes the plan; auto-activates downstream training sessions."""
        for rec in self:
            rec._require_stage_actor('chief')
            if rec.state != 'chief_approval':
                raise UserError(_('Only plans pending Chief approval can be approved.'))
            rec.approver_id = self.env.user.id
            rec.approved_by_id = self.env.user.id
            rec.approval_date = fields.Datetime.now()
            rec._write_workflow_values({'state': 'published'})
            rec._log_approval_step('chief_approval', 'published', rec.review_remarks or _('Approved and Published by Chief'))
            rec._activate_downstream()
            rec.message_post(body=_(
                "🎉 Annual L&D Plan %s has been <b>APPROVED and PUBLISHED</b> by Chief (%s). "
                "Downstream course delivery sessions are now activated for participant nomination."
            ) % (rec.name, self.env.user.name))
            rec._notify_role_users('group_eds_officer', _('Annual L&D Plan %s is published and active.') % rec.name)

    def action_chief_return_wizard(self):
        """Chief returns plan to Director with justification remarks."""
        self.ensure_one()
        self._require_stage_actor('chief')
        return {
            'name': _('Return Plan from Chief'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.plan.return.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_plan_id': self.id,
                'default_target_state': 'director_review',
                'default_stage_name': 'Chief Return to Director',
            }
        }

    def action_return_plan_from_wizard(self, target_state, reason):
        """Execute return transition and notify all stakeholders."""
        self.ensure_one()
        allowed = {
            'team_leader_review': ('team_leader', {'draft'}),
            'director_review': ('director', {'team_leader_review', 'draft'}),
            'chief_approval': ('chief', {'director_review'}),
        }
        stage_info = allowed.get(self.state)
        if not stage_info or target_state not in stage_info[1]:
            raise UserError(_('This return destination is not valid for the current plan stage.'))
        self._require_stage_actor(stage_info[0])
        if not reason or not reason.strip():
            raise UserError(_('Return remarks are required.'))
        old_state_label = dict(self._fields['state'].selection).get(self.state, self.state)
        new_state_label = dict(self._fields['state'].selection).get(target_state, target_state)
        self.last_return_reason = reason
        self._log_approval_step(self.state, target_state, _("RETURNED: %s") % reason)
        self._write_workflow_values({'state': target_state})
        self.message_post(body=_(
            "⚠️ <b>Annual Plan Returned</b> from <b>%s</b> to <b>%s</b>.<br/>"
            "<b>Justification / Remarks:</b> %s<br/>"
            "<b>Actioned By:</b> %s"
        ) % (old_state_label, new_state_label, reason, self.env.user.name))
        recipients = [self.creator_id, self.team_leader_id, self.reviewer_id]
        partner_ids = [u.partner_id.id for u in recipients if u and u.partner_id]
        if partner_ids:
            self.message_post(
                body=_("Attention: Annual Plan %s was returned for revision: %s") % (self.name, reason),
                partner_ids=partner_ids
            )

    # Legacy method compatibility
    def action_submit_director(self):
        return self.action_submit_to_team_leader()

    def action_director_approve(self):
        return self.action_director_forward()

    def action_cpco_approve(self):
        return self.action_chief_approve()

    def action_publish(self):
        return self.action_chief_approve()

    def _activate_downstream(self):
        """Create a draft session for each planned line so scheduling/nomination can start."""
        for line in self.line_ids.filtered(lambda l: not l.session_ids):
            line._create_default_session()

    def action_amend(self):
        """Published -> Amended: reopens the plan for authorized addenda."""
        for rec in self:
            rec._require_manager()
            if rec.state != 'published':
                raise UserError(_('Only published plans can be amended.'))
            rec._write_workflow_values({'state': 'amended'})
            rec._log_approval_step('published', 'amended', _('Plan reopened for addenda'))
            rec.message_post(body=_('Annual plan %s reopened for amendments - approved unscheduled '
                                    'requests will be appended as addenda.') % rec.name)

    def action_re_publish(self):
        """Amended -> Published: closes the amendment window again."""
        for rec in self:
            rec._require_manager()
            if rec.state != 'amended':
                raise UserError(_('Only amended plans can be re-published.'))
            rec._write_workflow_values({'state': 'published'})
            rec._activate_downstream()
            rec._log_approval_step('amended', 'published', _('Re-published after amendments'))
            rec.message_post(body=_('Annual plan %s re-published after amendments.') % rec.name)

    def action_view_sessions(self):
        """Open the sessions belonging to this plan ( monitoring)."""
        self.ensure_one()
        session_ids = self.line_ids.mapped('session_ids').ids
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'eds.session',
            'view_mode': 'list,form',
            'domain': [('id', 'in', session_ids)],
            'context': {'default_plan_id': self.id},
        }

    def unlink(self):
        for rec in self:
            if rec.state in ('published', 'amended'):
                raise UserError(_('Published/amended annual plans cannot be deleted.'))
            if rec.approval_history_ids:
                rec.approval_history_ids.with_context(eds_bypass_history_guard=True).unlink()
        return super().unlink()


class EdsAnnualPlanLine(models.Model):
    """One program line of the annual plan (/025).

    Carries the scheduled month, delivery method, allocated budget and the delivery
    status used by the monthly/quarterly planned-vs-actual variance report.
    """
    _name = 'eds.annual.plan.line'
    _description = 'Annual L&D Plan Line'
    _rec_name = 'program_name'
    _order = 'plan_id, scheduled_month, id'

    plan_id = fields.Many2one('eds.annual.plan', string='Annual Plan', required=True,
                              ondelete='cascade', index=True)
    course_id = fields.Many2one('eds.course', string='Training Program',
                                domain=[('status', 'in', ('draft', 'active'))])
    course_demand_id = fields.Many2one(
        'eds.tna.cycle.course.line', string='Source TNA Course Demand',
        ondelete='set null', readonly=True,
        help='Keeps the selected employee and source evidence connected to this plan program.')
    program_name = fields.Char(string='Program Name',
                                help='Used when the program is not in the course catalog '
                                     '(e.g. unscheduled-request addenda, /076).')
    program_category = fields.Selection([
        ('induction', 'Induction Program'),
        ('compliance', 'Compliance'),
        ('leadership', 'Leadership'),
        ('technical_functional', 'Technical / Functional'),
        ('digital_it', 'Digital & IT'),
        ('soft_skills', 'Soft Skills'),
        ('risk_audit', 'Risk & Audit'),
        ('customer_service', 'Customer Service'),
        ('other', 'Other'),
    ], string='Program Category', default='technical_functional')
    training_category = fields.Selection([
        ('in_house', 'In-house'),
        ('local_external', 'Local External'),
        ('international', 'International'),
        ('e_learning', 'E-Learning'),
    ], string='Training Category', default='in_house')
    target_audience = fields.Selection([
        ('bod', 'BoD (Board of Directors)'),
        ('smc', 'SMC (Senior Management Committee)'),
        ('mlm', 'MLM (Middle Level Management)'),
        ('below_mlm', 'Staff Below MLM'),
        ('all_staff', 'All Staff'),
    ], string='Target Group', default='all_staff')
    quarter = fields.Selection([
        ('q1', 'Q1 (Jul–Sep)'),
        ('q2', 'Q2 (Oct–Dec)'),
        ('q3', 'Q3 (Jan–Mar)'),
        ('q4', 'Q4 (Apr–Jun)'),
        ('unallocated', 'Q1–Q4 / TBD (Unallocated)'),
    ], string='Quarter', compute='_compute_quarter', store=True, readonly=False)
    duration_days = fields.Integer(string='Duration (Days)', default=1)
    planned_participants = fields.Integer(string='Planned Participants', default=25)
    num_sessions = fields.Integer(string='Number of Sessions', default=1)
    est_provider_cost_per_pax = fields.Monetary(
        string='Est. Provider Cost per Person per Session (ETB)',
        currency_field='budget_currency_id', default=0.0)
    total_provider_cost = fields.Monetary(
        string='Total Est. Provider Cost (ETB)', currency_field='budget_currency_id',
        compute='_compute_cost_breakdown', store=True)
    est_venue_cost_per_pax_day = fields.Monetary(
        string='Est. Venue/Lunch/Refreshment per Person per Day (ETB)',
        currency_field='budget_currency_id', default=0.0)
    total_venue_cost = fields.Monetary(
        string='Total Est. Venue/Lunch/Refreshment (ETB)', currency_field='budget_currency_id',
        compute='_compute_cost_breakdown', store=True)

    scheduled_date = fields.Date(
        string='Scheduled Month',
        help='Target month / planned start date for the program execution.')
    scheduled_month = fields.Char(
        string='Scheduled Month (YYYY-MM)', compute='_compute_scheduled_month',
        store=True, readonly=False,
        help='Month the program is planned for, e.g. 2026-10.')
    delivery_method = fields.Selection([
        ('internal', 'Internal Delivery'),
        ('local_external', 'Local External Provider'),
        ('international', 'International Provider'),
    ], string='Delivery Method', default='internal')
    budget_line_ids = fields.One2many(
        'eds.annual.plan.budget.line', 'plan_line_id', string='Itemized Budget Lines')
    manual_budget_allocated = fields.Monetary(
        string='Manual Budget Allocation (ETB)', currency_field='budget_currency_id', default=0.0,
        help='Used only when no itemized prices or legacy provider/venue rates are entered.')
    budget_allocated = fields.Monetary(string='Budget Allocated (ETB)',
                                       currency_field='budget_currency_id',
                                       compute='_compute_cost_breakdown', store=True, readonly=False)
    budget_currency_id = fields.Many2one(
        'res.currency', string='Program Currency', required=True,
        default=lambda self: self.env.company.currency_id,
        help='International programs default to USD. Select another currency if needed.')
    status = fields.Selection([
        ('planned', 'Planned'),
        ('scheduled', 'Scheduled'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
        ('delayed', 'Delayed'),
    ], string='Status', default='planned', required=True)
    session_ids = fields.One2many('eds.session', 'plan_line_id', string='Sessions')
    session_count = fields.Integer(string='Session Count', compute='_compute_session_count')
    planned_vs_actual = fields.Float(
        string='Planned vs Actual (%)', compute='_compute_planned_vs_actual', store=True,
        help='Percentage of this program’s sessions that have actually been delivered.')

    # Plan vs Actual Performance Tracking (aligned with Plan_vs_Actual template)
    actual_participants = fields.Integer(
        string='Actual Participants', compute='_compute_actual_metrics', store=True)
    participant_variance = fields.Integer(
        string='Participant Variance (Planned − Actual)', compute='_compute_actual_metrics', store=True)
    actual_cost = fields.Monetary(
        string='Actual Cost (ETB)', currency_field='budget_currency_id',
        compute='_compute_actual_metrics', store=True)
    cost_variance = fields.Monetary(
        string='Cost Variance (Planned − Actual)', currency_field='budget_currency_id',
        compute='_compute_actual_metrics', store=True)
    cost_utilization_pct = fields.Float(
        string='Cost Utilisation %', compute='_compute_actual_metrics', store=True)
    actual_start_date = fields.Date(
        string='Actual Start Date', compute='_compute_actual_metrics', store=True)
    actual_end_date = fields.Date(
        string='Actual End Date', compute='_compute_actual_metrics', store=True)
    remark = fields.Char(string='Remark')

    is_addendum = fields.Boolean(
        string='Addendum', default=False,
        help='Added through an approved unscheduled training request.')
    notes = fields.Text(string='Notes')

    @api.depends('scheduled_date', 'scheduled_month')
    def _compute_quarter(self):
        for rec in self:
            month_num = None
            if rec.scheduled_date:
                month_num = rec.scheduled_date.month
            elif rec.scheduled_month and '-' in rec.scheduled_month:
                try:
                    month_num = int(rec.scheduled_month.split('-')[1])
                except (ValueError, IndexError):
                    month_num = None
            if month_num in (7, 8, 9):
                rec.quarter = 'q1'
            elif month_num in (10, 11, 12):
                rec.quarter = 'q2'
            elif month_num in (1, 2, 3):
                rec.quarter = 'q3'
            elif month_num in (4, 5, 6):
                rec.quarter = 'q4'
            elif not rec.quarter:
                rec.quarter = 'unallocated'

    @api.depends('planned_participants', 'num_sessions', 'duration_days', 'est_provider_cost_per_pax',
                 'est_venue_cost_per_pax_day', 'course_id.duration_days', 'budget_line_ids.total_amount',
                 'manual_budget_allocated')
    def _compute_cost_breakdown(self):
        for rec in self:
            days = rec.duration_days or (rec.course_id and rec.course_id.duration_days) or 1
            participants = rec.planned_participants or 0
            sessions = rec.num_sessions or 1
            rec.total_provider_cost = participants * sessions * rec.est_provider_cost_per_pax
            rec.total_venue_cost = participants * days * sessions * rec.est_venue_cost_per_pax_day
            if rec.budget_line_ids.filtered(lambda line: line.unit_price):
                rec.budget_allocated = sum(rec.budget_line_ids.mapped('total_amount'))
            elif rec.total_provider_cost or rec.total_venue_cost:
                rec.budget_allocated = rec.total_provider_cost + rec.total_venue_cost
            else:
                rec.budget_allocated = rec.manual_budget_allocated

    @api.depends('scheduled_date')
    def _compute_scheduled_month(self):
        for rec in self:
            if rec.scheduled_date:
                rec.scheduled_month = rec.scheduled_date.strftime('%Y-%m')
            elif not rec.scheduled_month:
                rec.scheduled_month = False

    @api.onchange('scheduled_month')
    def _onchange_scheduled_month(self):
        if self.scheduled_month and not self.scheduled_date:
            try:
                y, m = (int(x) for x in self.scheduled_month.split('-'))
                self.scheduled_date = date(y, m, 1)
            except Exception:
                pass

    @api.onchange('scheduled_date')
    def _onchange_scheduled_date(self):
        if self.scheduled_date:
            self.scheduled_month = self.scheduled_date.strftime('%Y-%m')

    @api.depends('session_ids')
    def _compute_session_count(self):
        for rec in self:
            rec.session_count = len(rec.session_ids)

    @api.depends('session_ids', 'session_ids.status')
    def _compute_planned_vs_actual(self):
        for rec in self:
            rec.planned_vs_actual = round(
                len(rec.session_ids.filtered(lambda s: s.status == 'completed')) * 100.0
                / len(rec.session_ids), 2) if rec.session_ids else 0.0

    @api.depends('session_ids', 'session_ids.enrollment_ids', 'session_ids.enrollment_ids.state',
                 'session_ids.date_start', 'session_ids.date_end',
                 'session_ids.cost_ids.amount', 'session_ids.cost_ids.currency_id',
                 'session_ids.cost_ids.payment_state', 'session_ids.cost_ids.payment_date',
                 'planned_participants',
                 'budget_allocated', 'budget_currency_id')
    def _compute_actual_metrics(self):
        for rec in self:
            sessions = rec.session_ids
            # One employee may attend several sessions of the same program.
            participant_ids = set()
            start_dates = []
            end_dates = []
            for s in sessions:
                participant_ids.update(s.enrollment_ids.filtered(
                    lambda e: e.state in ('enrolled', 'completed')).mapped('employee_id').ids)
                if s.date_start:
                    start_dates.append(s.date_start.date())
                if s.date_end:
                    end_dates.append(s.date_end.date())

            rec.actual_participants = len(participant_ids)
            rec.participant_variance = (rec.planned_participants or 0) - len(participant_ids)

            # Paid costs are converted before addition; summing USD and ETB
            # amounts directly produced misleading plan variance figures.
            actual_spent = 0.0
            target_currency = rec.budget_currency_id or rec.plan_id.company_id.currency_id
            for cost in sessions.mapped('cost_ids').filtered(lambda c: c.payment_state == 'paid'):
                source_currency = cost.currency_id or rec.plan_id.company_id.currency_id
                if source_currency != target_currency:
                    actual_spent += source_currency._convert(
                        cost.amount, target_currency, rec.plan_id.company_id,
                        cost.payment_date or fields.Date.to_date(cost.write_date)
                        or fields.Date.context_today(rec))
                else:
                    actual_spent += cost.amount

            rec.actual_cost = actual_spent
            rec.cost_variance = (rec.budget_allocated or 0.0) - actual_spent
            rec.cost_utilization_pct = (actual_spent / rec.budget_allocated * 100.0) if rec.budget_allocated > 0 else 0.0

            rec.actual_start_date = min(start_dates) if start_dates else False
            rec.actual_end_date = max(end_dates) if end_dates else False

    @api.onchange('course_id')
    def _onchange_course_id(self):
        if self.course_id:
            self.program_name = self.course_id.name
            self.delivery_method = self.course_id.recommended_source or 'internal'

    @api.model
    def _default_currency_for_delivery(self, delivery_method):
        if delivery_method == 'international':
            return self.env['res.currency'].search([('name', '=', 'USD')], limit=1) or self.env.company.currency_id
        return self.env.company.currency_id

    @api.onchange('delivery_method')
    def _onchange_delivery_currency(self):
        if self.delivery_method == 'international' and self.budget_currency_id == self.env.company.currency_id:
            self.budget_currency_id = self._default_currency_for_delivery('international')
        elif self.delivery_method != 'international' and not self.budget_currency_id:
            self.budget_currency_id = self.env.company.currency_id

    def init(self):
        self.env.cr.execute("""
            UPDATE eds_annual_plan_line AS line
               SET budget_currency_id = CASE
                   WHEN line.delivery_method = 'international'
                   THEN COALESCE((SELECT id FROM res_currency WHERE name = 'USD' LIMIT 1), company.currency_id)
                   ELSE company.currency_id END
              FROM eds_annual_plan AS plan
              JOIN res_company AS company ON company.id = plan.company_id
             WHERE line.plan_id = plan.id AND line.budget_currency_id IS NULL
        """)

    def _create_default_session(self):
        """Create one draft session for this line (used on publication, )."""
        self.ensure_one()
        if self.session_ids:
            return self.session_ids[0]
        start = self.scheduled_date or date.today()
        if not self.scheduled_date and self.scheduled_month:
            try:
                y, m = (int(x) for x in self.scheduled_month.split('-'))
                start = date(y, m, 1)
            except (ValueError, TypeError):
                pass
        duration_days = self.course_id.duration_days or 1
        # The session model resolves the capacity default from EDS settings itself.
        return self.env['eds.session'].create({
            'plan_line_id': self.id,
            'course_id': self.course_id.id if self.course_id else False,
            'program_name': self.program_name,
            'date_start': start,
            'date_end': start + timedelta(days=duration_days - 1),
            'duration_hours': duration_days * 8.0,
        })

    def _init_default_budget_lines(self):
        """Populate default budget items: Hotel, Per Diem, Vendor, Transportation."""
        BudgetLine = self.env['eds.annual.plan.budget.line']
        for rec in self:
            if not rec.budget_line_ids:
                defaults = [
                    {'name': _('Hotel / Accommodation'), 'unit_price': 0.0, 'is_per_employee': True, 'is_general': False},
                    {'name': _('Per Diem / Daily Allowance'), 'unit_price': 0.0, 'is_per_employee': True, 'is_general': False},
                    {'name': _('Vendor / Facilitator Fee'), 'unit_price': 0.0, 'is_per_employee': False, 'is_general': True},
                    {'name': _('Transportation'), 'unit_price': 0.0, 'is_per_employee': False, 'is_general': True},
                ]
                lines_to_create = []
                for item in defaults:
                    lines_to_create.append({
                        'plan_line_id': rec.id,
                        'name': item['name'],
                        'unit_price': item['unit_price'],
                        'is_per_employee': item['is_per_employee'],
                        'is_general': item['is_general'],
                    })
                BudgetLine.create(lines_to_create)

    def action_load_default_budget_lines(self):
        for rec in self:
            rec._init_default_budget_lines()

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        for vals in vals_list:
            if not self.env.su and vals.get('plan_id'):
                self.env['eds.annual.plan'].browse(vals['plan_id'])._check_can_edit_content()
            if not vals.get('budget_currency_id'):
                vals['budget_currency_id'] = self._default_currency_for_delivery(
                    vals.get('delivery_method')).id
            if 'budget_allocated' in vals:
                vals.setdefault('manual_budget_allocated', vals.pop('budget_allocated'))
        records = super().create(vals_list)
        for rec in records:
            if not rec.budget_line_ids:
                rec._init_default_budget_lines()
        return records

    def write(self, vals):
        if not self.env.su:
            self.mapped('plan_id')._check_can_edit_content()
        vals = dict(vals)
        if 'delivery_method' in vals and 'budget_currency_id' not in vals:
            vals['budget_currency_id'] = self._default_currency_for_delivery(
                vals['delivery_method']).id
        if 'budget_allocated' in vals:
            vals.setdefault('manual_budget_allocated', vals.pop('budget_allocated'))
        return super().write(vals)

    def unlink(self):
        if not self.env.su:
            self.mapped('plan_id')._check_can_edit_content()
        return super().unlink()

    def _write_delivery_status(self, status):
        """Session lifecycle updates may change delivery status on an approved plan."""
        return super(EdsAnnualPlanLine, self).write({'status': status})


class EdsAnnualPlanBudgetLine(models.Model):
    """Itemized budget expense line for an Annual Plan Line (/025).

    Supports Hotel, Per Diem, Vendor, Transportation, etc.
    Checkbox 'is_per_employee' auto-multiplies by participant count.
    Checkbox 'is_general' adds as fixed total budget.
    """
    _name = 'eds.annual.plan.budget.line'
    _description = 'Annual Plan Program Budget Item'
    _order = 'id asc'

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            plan_lines = self.env['eds.annual.plan.line'].browse([
                vals['plan_line_id'] for vals in vals_list if vals.get('plan_line_id')])
            plan_lines.mapped('plan_id')._check_can_edit_content()
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            self.mapped('plan_line_id.plan_id')._check_can_edit_content()
        return super().write(vals)

    def unlink(self):
        if not self.env.su:
            self.mapped('plan_line_id.plan_id')._check_can_edit_content()
        return super().unlink()

    plan_line_id = fields.Many2one(
        'eds.annual.plan.line', string='Program Line', required=True, ondelete='cascade', index=True)
    name = fields.Char(string='Expense / Budget Line Name', required=True)
    unit_price = fields.Monetary(
        string='Price / Rate (ETB)', currency_field='currency_id', default=0.0)
    is_per_employee = fields.Boolean(
        string='Per Employee', default=False,
        help='If checked, this rate is multiplied by the number of planned participants.')
    is_general = fields.Boolean(
        string='General / Fixed', default=True,
        help='Fixed total expenditure regardless of participant count.')
    currency_id = fields.Many2one('res.currency', related='plan_line_id.budget_currency_id', readonly=True)
    total_amount = fields.Monetary(
        string='Total Amount (ETB)', currency_field='currency_id',
        compute='_compute_total_amount', store=True)
    notes = fields.Char(string='Notes / Description')

    @api.onchange('is_per_employee')
    def _onchange_is_per_employee(self):
        if self.is_per_employee:
            self.is_general = False
        else:
            self.is_general = True

    @api.onchange('is_general')
    def _onchange_is_general(self):
        if self.is_general:
            self.is_per_employee = False
        else:
            self.is_per_employee = True

    @api.depends('unit_price', 'is_per_employee', 'plan_line_id.planned_participants')
    def _compute_total_amount(self):
        for rec in self:
            participants = (rec.plan_line_id.planned_participants or 0)
            if rec.is_per_employee:
                rec.total_amount = rec.unit_price * participants
            else:
                rec.total_amount = rec.unit_price
