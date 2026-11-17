# -*- coding: utf-8 -*-
from datetime import date, timedelta
from html import escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from .eds_currency_policy import currency_for_delivery, validate_delivery_currency
from .eds_action_notification import clear_action_activities, notify_action


class EdsAnnualPlan(models.Model):
    """Annual Learning & Development Plan and Calendar.

    The approved TNA needs and approved curricula are assembled into a draft annual
    plan (/) within the calendar SLA, routed through the
    Director PPDD -> CPCO -> SMC approval chain and published. Publishing
    auto-activates the downstream sessions so nominations can start. Approved
    unscheduled training requests amend the published plan as addenda
   . Delivery is monitored with planned-vs-actual variance
    per line.
    """
    _name = 'eds.annual.plan'
    _description = 'Annual L&D Plan & Calendar'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    def init(self):
        """Make the bank-wide official-plan rule safe under concurrent reviews."""
        self.env.cr.execute("""
            SELECT fiscal_year, array_agg(id ORDER BY id)
              FROM eds_annual_plan
             WHERE state IN (
                'team_leader_review', 'director_review', 'chief_approval',
                'published', 'amended'
             )
             GROUP BY fiscal_year
            HAVING count(*) > 1
             ORDER BY fiscal_year
             LIMIT 10
        """)
        duplicates = self.env.cr.fetchall()
        if duplicates:
            details = ', '.join('%s: %s' % (year, ids) for year, ids in duplicates)
            raise ValidationError(_(
                'Cannot enforce one official annual plan per year. Resolve the '
                'existing duplicate fiscal years before upgrading EDS: %s') % details)
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS eds_annual_plan_official_year_uniq
            ON eds_annual_plan (fiscal_year)
            WHERE state IN (
                'team_leader_review', 'director_review', 'chief_approval',
                'published', 'amended'
            )
        """)

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    active = fields.Boolean(default=True, tracking=True)
    fiscal_year = fields.Char(
        string='Fiscal Year', required=True, index=True, readonly=True,
        default=lambda self: str(fields.Date.context_today(self).year), tracking=True)
    line_ids = fields.One2many('eds.annual.plan.line', 'plan_id', string='Plan Lines')
    restrict_tna_cycles = fields.Boolean(
        string='Only Selected TNA Cycles',
        help='When enabled, Generate Calendar uses only the selected closed TNA cycles '
             'from this fiscal year. Leave off to use all closed cycles from this year.')
    selected_tna_cycle_ids = fields.Many2many(
        'eds.tna.cycle', 'eds_annual_plan_tna_cycle_rel', 'plan_id', 'cycle_id',
        string='TNA Cycles for Calendar',
        domain="[('year', '=', fiscal_year), ('state', '=', 'closed'), ('company_id', '=', company_id)]")
    line_count = fields.Integer(string='Programs', compute='_compute_counts')
    delivered_count = fields.Integer(string='Delivered', compute='_compute_counts')
    budget_total = fields.Monetary(
        string='Budget Total', compute='_compute_budget', store=True,
        currency_field='budget_currency_id')
    budget_currency_id = fields.Many2one('res.currency', related='company_id.currency_id',
                                         readonly=True)
    budget_by_currency_html = fields.Html(
        string='Budget by Currency', compute='_compute_budget_by_currency_html')
    execution_rate = fields.Float(
        string='Execution Rate (%)', compute='_compute_execution_rate', store=True,
        help='Share of plan lines whose sessions have been delivered.')
    calendar_generation_date = fields.Date(string='Calendar Generated On', readonly=True)
    calendar_sla_deadline = fields.Date(
        string='Calendar SLA Deadline', compute='_compute_calendar_sla', store=True,
        help='Computed from the calendar SLA in settings (default 5 working days).')
    sla_breached = fields.Boolean(
        string='SLA Breached', compute='_compute_calendar_sla', store=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft (Creation)'),
        ('team_leader_review', 'Team Leader Review (Checker)'),
        ('director_review', 'Director Review'),
        ('chief_approval', 'Chief Approval'),
        ('published', 'Published'),
        ('amended', 'Amended'),
        ('archived', 'Archived'),
    ], string='Status', default='draft', required=True, tracking=True)

    # Reviewers are recorded after they act; the workflow routes to EDS roles.
    creator_id = fields.Many2one('res.users', string='Created By', default=lambda self: self.env.user, tracking=True)
    team_leader_id = fields.Many2one('res.users', string='Team Leader (Checker)', readonly=True, tracking=True)
    reviewer_id = fields.Many2one('res.users', string='Director PPDD', readonly=True, tracking=True)
    approver_id = fields.Many2one('res.users', string='Chief / Approver', readonly=True, tracking=True)
    endorser_id = fields.Many2one('res.users', string='Endorser', readonly=True, tracking=True)
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
        help='Approved unscheduled training requests appended as addenda.')
    amendment_count = fields.Integer(string='Amendment Count', compute='_compute_counts')
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.constrains('selected_tna_cycle_ids', 'fiscal_year', 'company_id')
    def _check_selected_tna_cycles(self):
        for plan in self:
            invalid = plan.with_context(active_test=False).selected_tna_cycle_ids.filtered(
                lambda cycle: (
                    cycle.state not in ('closed', 'archived')
                    or (cycle.state == 'archived' and plan.state == 'draft')
                    or cycle.year != plan.fiscal_year
                    or cycle.company_id != plan.company_id))
            if invalid:
                raise ValidationError(_(
                    'Selected TNA cycles must be closed and belong to this plan year and company. '
                    'Previously linked archived cycles remain in approved plan history.'))

    def _calendar_tna_cycles(self):
        self.ensure_one()
        cycles = self.env['eds.tna.cycle'].search([
            ('year', '=', self.fiscal_year), ('state', '=', 'closed'),
            ('company_id', '=', self.company_id.id),
        ])
        if self.restrict_tna_cycles:
            if not self.selected_tna_cycle_ids:
                raise UserError(_('Select at least one closed TNA cycle for this plan year.'))
            cycles &= self.selected_tna_cycle_ids
        return cycles

    def _planning_catalog_courses(self):
        """Catalog choices from the same closed, selected demand as the calendar."""
        self.ensure_one()
        if self.restrict_tna_cycles and not self.selected_tna_cycle_ids:
            return self.env['eds.course'].browse()
        demands = self._calendar_tna_cycles().mapped('course_summary_ids').filtered(
            lambda demand: demand.selected_for_planning
            and demand.total_employees > 0 and demand.course_id)
        return demands.mapped('course_id')

    def _selected_tna_demands(self):
        self.ensure_one()
        cycles = self._calendar_tna_cycles()
        for cycle in cycles.filtered(
                lambda rec: rec.course_demand_dirty or not rec.course_demand_last_sync):
            cycle._sync_course_demand()
        return cycles.mapped('course_summary_ids').filtered(
            lambda demand: demand.selected_for_planning and demand.total_employees > 0)

    def _reconcile_tna_plan_lines(self, demands):
        """Keep draft TNA-derived lines aligned with the chosen cycle/course scope."""
        self.ensure_one()
        for line in self.line_ids:
            current = line.course_demand_ids | line.course_demand_id
            if not current:
                continue  # A manually entered plan line is not generated TNA demand.
            retained = current & demands
            if len(retained) == len(current):
                continue
            if line.session_ids or line.budget_allocated or line.status != 'planned':
                raise UserError(_(
                    'Plan line %s has a session, entered budget or delivery progress. '
                    'Review it before excluding its TNA cycle or course.') % line.program_name)
            if not retained:
                line.unlink()
            else:
                retained.check_access('read')
                line.write({
                    'course_demand_id': retained[0].id,
                    'course_demand_ids': [(6, 0, retained.ids)],
                    'planned_participants': len(set(retained.sudo().mapped('employee_ids').ids)),
                })

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
            'request_count': sum(sum(
                demand.request_count for demand in
                (line.course_demand_ids | line.course_demand_id)) for line in lines),
            'by_method': by_method,
            'currency_totals': sorted(currency_totals.items(), key=lambda item: item[0].name),
        }

    @api.depends('line_ids.budget_allocated', 'line_ids.budget_currency_id')
    def _compute_budget_by_currency_html(self):
        for plan in self:
            totals = plan._get_preview_summary()['currency_totals']
            if not totals:
                plan.budget_by_currency_html = '<p>No program budgets entered yet.</p>'
                continue
            cards = ''.join(
                '<div class="o_eds_currency_total">'
                '<span>Total in %s</span><strong>%s</strong></div>'
                % (escape(currency.name), '{:,.2f}'.format(amount))
                for currency, amount in totals
            )
            plan.budget_by_currency_html = '<div class="o_eds_currency_totals">%s</div>' % cards

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
        current_year = str(fields.Date.context_today(self).year)
        for vals in vals_list:
            if not self.env.su:
                if vals.get('state', 'draft') != 'draft':
                    raise UserError(_('Annual plans must start as drafts and follow the approval workflow.'))
                if vals.get('fiscal_year', current_year) != current_year:
                    raise UserError(_('New annual plans must use the current fiscal year (%s).') % current_year)
                vals['fiscal_year'] = current_year
                vals['creator_id'] = self.env.user.id
                for field_name in ('team_leader_id', 'reviewer_id', 'approver_id',
                                   'endorser_id', 'approved_by_id', 'approval_date'):
                    vals.pop(field_name, None)
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
        for rec in self:
            if rec.state == 'draft':
                allowed = user == rec.creator_id or manager
            elif rec.state == 'team_leader_review':
                allowed = user.id in rec._stage_role_users('team_leader').ids and user != rec.creator_id
            elif rec.state == 'director_review':
                allowed = (user.id in rec._stage_role_users('director').ids
                           and user not in (rec.creator_id, rec.team_leader_id))
            elif rec.state == 'chief_approval':
                allowed = (user.id in rec._stage_role_users('chief').ids
                           and user not in (rec.creator_id, rec.team_leader_id, rec.reviewer_id))
            elif rec.state == 'amended':
                allowed = manager
            else:
                allowed = False
            if not allowed:
                raise UserError(_('You cannot edit the content of this plan at its current approval stage.'))

    def write(self, vals):
        selected_before = ({
            plan.id: set(plan.with_context(active_test=False).selected_tna_cycle_ids.ids)
            for plan in self
        } if 'selected_tna_cycle_ids' in vals else {})
        if not self.env.su:
            if 'state' in vals:
                raise UserError(_('Use the annual plan review actions to change its status.'))
            if 'active' in vals:
                raise UserError(_('Use Archive Plan to remove an annual plan from active screens.'))
            if 'fiscal_year' in vals and any(rec.fiscal_year != vals['fiscal_year'] for rec in self):
                raise UserError(_('The fiscal year is fixed when the annual plan is created.'))
            if {'creator_id', 'team_leader_id', 'reviewer_id', 'approver_id',
                'endorser_id', 'approved_by_id', 'approval_date',
                'last_return_reason'}.intersection(vals):
                raise UserError(_('Approval participants and results are recorded by workflow actions.'))
            content_fields = {
                'company_id', 'line_ids', 'amendment_ids', 'notes',
                'review_remarks', 'ceo_memo_attachment', 'ceo_memo_filename',
                'restrict_tna_cycles', 'selected_tna_cycle_ids',
            }
            if content_fields.intersection(vals):
                self._check_can_edit_content()
        result = super().write(vals)
        if selected_before:
            for plan in self:
                added = plan.with_context(active_test=False).selected_tna_cycle_ids.filtered(
                    lambda cycle: cycle.id not in selected_before[plan.id])
                if any(cycle.state != 'closed' or not cycle.active for cycle in added):
                    raise ValidationError(_(
                        'Archived TNA cycles cannot be newly selected for an annual plan.'))
        return result

    def _write_workflow_values(self, vals):
        """Write audit fields only after a review action has checked the actor's role."""
        return super(EdsAnnualPlan, self).write(vals)

    # ── Calendar generation ───────────────────────────────────
    def action_generate_calendar(self):
        """Build this year's draft calendar from courses explicitly selected in TNA."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('The calendar can only be generated while the plan is a draft.'))
        selected = self._selected_tna_demands()
        if not selected:
            raise UserError(_(
                'Select courses on a closed TNA cycle for assessment year %s before generating this calendar.')
                % self.fiscal_year)
        missing_catalog = selected.filtered(lambda demand: not demand.course_id)
        if missing_catalog:
            raise UserError(_(
                'Add these selected training needs to the course catalog and link them '
                'to their TNA demand before generating the calendar: %s')
                % ', '.join(sorted({(demand.course_name or _('Unnamed course')).strip()
                                    for demand in missing_catalog})))
        self._reconcile_tna_plan_lines(selected)
        created = self._add_course_demands(selected)
        self.calendar_generation_date = date.today()
        self.message_post(
            body=_('Calendar generated for %s - %d programs added. SLA deadline: %s.')
            % (self.name, created, self.calendar_sla_deadline))
        return {
            'type': 'ir.actions.client', 'tag': 'bunna_refresh_form',
            'params': {'res_model': self._name, 'res_id': self.id},
        }

    def _add_course_demands(self, demands):
        """Merge matching courses from closed cycles, counting each employee once."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('TNA demand can be added only while the annual plan is a draft.'))
        valid = demands.filtered(lambda demand:
            demand.cycle_id.state == 'closed'
            and demand.cycle_id.active
            and demand.cycle_id.year == self.fiscal_year
            and demand.cycle_id.company_id == self.company_id)
        if len(valid) != len(demands):
            raise UserError(_('Only closed TNA cycles from this plan year and company may feed the annual plan.'))
        if any(not demand.selected_for_planning or demand.total_employees <= 0 for demand in valid):
            raise UserError(_('Only selected course demand with eligible employees may feed the annual plan.'))
        if any(not demand.course_id for demand in valid):
            raise UserError(_('Every planned training program must be selected from the course catalog.'))
        grouped = {}
        for demand in valid:
            key = demand.course_id.id
            grouped.setdefault(key, self.env['eds.tna.cycle.course.line'])
            grouped[key] |= demand
        created = 0
        for key, selected in grouped.items():
            sample = selected[0]
            line = self.line_ids.filtered(lambda item:
                item.course_id.id == key)[:1]
            existing = (line.course_demand_ids | line.course_demand_id).filtered(
                lambda demand: demand.cycle_id.state == 'closed'
                and demand.cycle_id.active
                and demand.cycle_id.year == self.fiscal_year
                and demand.cycle_id.company_id == self.company_id
                and demand.selected_for_planning
                and demand.total_employees > 0) if line else selected.browse()
            combined = existing | selected
            combined.check_access('read')
            participants = len(set(combined.sudo().mapped('employee_ids').ids))
            if line:
                line.write({
                    'course_demand_id': combined[0].id,
                    'course_demand_ids': [(6, 0, combined.ids)],
                    'planned_participants': participants,
                })
                continue
            course = sample.course_id
            line = self.env['eds.annual.plan.line'].create({
                'plan_id': self.id,
                'course_demand_id': sample.id,
                'course_demand_ids': [(6, 0, combined.ids)],
                'course_id': course.id,
                'delivery_method': course.recommended_source or 'internal',
                'target_audience': course.target_audience or 'all_staff',
                'duration_days': sample.duration_days or 1,
                'planned_participants': participants,
                'quarter': sample.target_quarter or 'q1',
            })
            line._init_default_budget_lines()
            created += 1
        return created

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
            'user_id': self.env.user.id,
            'state_from': state_from,
            'state_to': state_to,
            'comment': comment or _('Moved %s -> %s') % (state_from, state_to),
        })

    def _require_manager(self):
        if not (self.env.su or self.env.user.has_group('employee_development_system.group_eds_manager')
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('This approval step requires L&D Manager authority.'))

    def _stage_role_users(self, stage):
        """Use the EDS-wide role for this approval stage."""
        self.ensure_one()
        roles = {
            'team_leader': 'group_eds_team_leader',
            'director': 'group_eds_director',
            'chief': 'group_eds_chief',
        }
        role_id = roles[stage]

        def members(xml_id):
            group = self.env.ref('employee_development_system.' + xml_id,
                                 raise_if_not_found=False)
            return (group.sudo().user_ids if group else self.env['res.users']).filtered(
                lambda user: user.active and not user.share
                and self.company_id in user.company_ids)

        return members(role_id)

    def _notify_stage_users(self, stage, message, exclude_user_ids=None):
        """Send the review request to every eligible member of the stage role."""
        self.ensure_one()
        excluded = set(exclude_user_ids or [])
        recipients = self._stage_role_users(stage).filtered(
            lambda user: user.id not in excluded)
        if not recipients:
            raise UserError(_(
                'No eligible %s reviewer can act on this plan. Assign another active user '
                'to the EDS role with access to %s.')
                % (stage.replace('_', ' ').title(), self.company_id.name))
        clear_action_activities(self)
        title = {
            'team_leader': _('Annual plan: Team Leader review'),
            'director': _('Annual plan: Director review'),
            'chief': _('Annual plan: Chief approval'),
        }[stage]
        notify_action(self, recipients, title, message)
        return recipients

    def _notify_role_users(self, group_xml_id, message, exclude_user_ids=None,
                           require_recipients=False):
        """Notify every active user in an EDS role who can access this company."""
        self.ensure_one()
        group = self.env.ref('employee_development_system.' + group_xml_id, raise_if_not_found=False)
        excluded = set(exclude_user_ids or [])
        recipients = (group.user_ids if group else self.env['res.users']).filtered(
            lambda user: user.active and not user.share
            and self.company_id in user.company_ids and user.id not in excluded)
        if require_recipients and not recipients:
            raise UserError(_(
                'No eligible EDS reviewer is available for this plan. Assign another active '
                'user to the required EDS role who has access to %s.') % self.company_id.name)
        partner_ids = recipients.mapped('partner_id').ids
        self.message_post(body=message, partner_ids=partner_ids)
        return recipients

    def _require_stage_actor(self, stage):
        self.ensure_one()
        if self.env.su:
            return
        user = self.env.user
        if stage == 'creator':
            has_role = user.has_group('employee_development_system.group_eds_officer')
        else:
            has_role = user.id in self._stage_role_users(stage).ids
        if not has_role:
            raise UserError(_('Your EDS role cannot perform this approval step.'))
        if self.company_id not in user.company_ids:
            raise UserError(_('Your user does not have access to the plan company.'))
        if stage == 'creator' and user != self.creator_id:
            raise UserError(_('Only the plan creator can submit it for review.'))
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
            rec._reconcile_tna_plan_lines(rec._selected_tna_demands())
            if not rec.line_ids:
                raise UserError(_('Please add courses/programs to the plan before submitting.'))
            rec._write_workflow_values({
                'state': 'team_leader_review',
                'team_leader_id': False,
                'reviewer_id': False,
                'approver_id': False,
                'last_return_reason': False,
            })
            rec._log_approval_step('draft', 'team_leader_review', _('Submitted for Team Leader review.'))
            rec.message_post(body=_('Annual plan %s submitted to Team Leader (Checker) for review.') % rec.name)
            rec._notify_stage_users(
                'team_leader', _('Annual L&D Plan %s is pending Team Leader review.') % rec.name,
                exclude_user_ids=[rec.creator_id.id])

    def action_team_leader_forward(self):
        """Team Leader (Checker) edits/verifies and forwards to Director."""
        for rec in self:
            rec._require_stage_actor('team_leader')
            if rec.state != 'team_leader_review':
                raise UserError(_('Only plans under Team Leader review can be forwarded.'))
            comment = (rec.review_remarks or '').strip()
            rec._write_workflow_values({
                'team_leader_id': self.env.user.id,
                'reviewer_id': False,
                'approver_id': False,
                'state': 'director_review',
                'review_remarks': False,
                'last_return_reason': False,
            })
            rec._log_approval_step('team_leader_review', 'director_review', comment or _('Verified by Team Leader'))
            rec.message_post(body=_('Annual plan %s verified by Team Leader %s and forwarded to Director PPDD.')
                             % (rec.name, self.env.user.name))
            rec._notify_stage_users(
                'director',
                _('Annual L&D Plan %s is pending Director PPDD review. Team Leader remarks: %s')
                % (rec.name, comment or _('None')),
                exclude_user_ids=[rec.creator_id.id, rec.team_leader_id.id])

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
            }
        }

    def action_director_forward(self):
        """Director PPDD reviews, attaches optional CEO memo, and forwards to Chief."""
        for rec in self:
            rec._require_stage_actor('director')
            if rec.state != 'director_review':
                raise UserError(_('Only plans under Director review can be forwarded to the Chief.'))
            comment = (rec.review_remarks or '').strip()
            rec._write_workflow_values({
                'reviewer_id': self.env.user.id,
                'approver_id': False,
                'state': 'chief_approval',
                'review_remarks': False,
                'last_return_reason': False,
            })
            memo_msg = _(" (with CEO signature memo attached)") if rec.ceo_memo_attachment else ""
            rec._log_approval_step('director_review', 'chief_approval',
                                   (comment or _('Endorsed by Director')) + memo_msg)
            rec.message_post(body=_('Annual plan %s endorsed by Director PPDD %s%s and forwarded to Chief for approval.')
                             % (rec.name, self.env.user.name, memo_msg))
            rec._notify_stage_users(
                'chief',
                _('Annual L&D Plan %s requires Chief approval. Director remarks: %s')
                % (rec.name, comment or _('None')),
                exclude_user_ids=[rec.creator_id.id, rec.team_leader_id.id, rec.reviewer_id.id])

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
            }
        }

    def action_chief_approve(self):
        """Chief approves and publishes the plan; auto-activates downstream training sessions."""
        for rec in self:
            rec._require_stage_actor('chief')
            if rec.state != 'chief_approval':
                raise UserError(_('Only plans pending Chief approval can be approved.'))
            comment = (rec.review_remarks or '').strip()
            rec._write_workflow_values({
                'approver_id': self.env.user.id,
                'approved_by_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
                'state': 'published',
                'review_remarks': False,
                'last_return_reason': False,
            })
            rec._log_approval_step('chief_approval', 'published',
                                   comment or _('Approved and Published by Chief'))
            clear_action_activities(rec)
            rec._activate_downstream()
            rec.message_post(body=_(
                "🎉 Annual L&D Plan %s has been <b>APPROVED and PUBLISHED</b> by Chief (%s). "
                "Downstream course delivery sessions are now activated for participant nomination."
            ) % (rec.name, self.env.user.name))
            notify_action(
                rec, (rec.creator_id | rec.reviewer_id | rec.team_leader_id),
                _('Annual plan approved'),
                _('Annual L&D Plan %s is published and active. Chief remarks: %s')
                % (rec.name, comment or _('None')), action_required=False)

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
            }
        }

    def action_return_plan_from_wizard(self, reason):
        """Return to the preceding stage inferred from the current review state."""
        self.ensure_one()
        return_route = {
            'team_leader_review': ('team_leader', 'draft'),
            'director_review': ('director', 'team_leader_review'),
            'chief_approval': ('chief', 'director_review'),
        }
        stage_info = return_route.get(self.state)
        if not stage_info:
            raise UserError(_('Only plans under review can be returned.'))
        target_state = stage_info[1]
        self._require_stage_actor(stage_info[0])
        if not reason or not reason.strip():
            raise UserError(_('Return remarks are required.'))
        old_state_label = dict(self._fields['state'].selection).get(self.state, self.state)
        new_state_label = dict(self._fields['state'].selection).get(target_state, target_state)
        old_state = self.state
        actor_field = {
            'team_leader_review': 'team_leader_id',
            'director_review': 'reviewer_id',
            'chief_approval': 'approver_id',
        }[old_state]
        self._log_approval_step(old_state, target_state, _("RETURNED: %s") % reason)
        self._write_workflow_values({
            'state': target_state,
            actor_field: self.env.user.id,
            'last_return_reason': reason,
            'review_remarks': False,
        })
        self.message_post(body=_(
            "⚠️ <b>Annual Plan Returned</b> from <b>%s</b> to <b>%s</b>.<br/>"
            "<b>Justification / Remarks:</b> %s<br/>"
            "<b>Actioned By:</b> %s"
        ) % (old_state_label, new_state_label, reason, self.env.user.name))
        message = _("Annual Plan %s was returned for revision: %s") % (self.name, reason)
        if target_state == 'draft':
            clear_action_activities(self)
            notify_action(self, self.creator_id, _('Annual plan returned for revision'), message)
        elif target_state == 'team_leader_review':
            if self.team_leader_id in self._stage_role_users('team_leader'):
                clear_action_activities(self)
                notify_action(self, self.team_leader_id,
                              _('Annual plan returned to Team Leader'), message)
            else:
                self._notify_stage_users(
                    'team_leader', message,
                    exclude_user_ids=[self.creator_id.id, self.reviewer_id.id])
        else:
            if self.reviewer_id in self._stage_role_users('director'):
                clear_action_activities(self)
                notify_action(self, self.reviewer_id,
                              _('Annual plan returned to Director'), message)
            else:
                self._notify_stage_users(
                    'director', message,
                    exclude_user_ids=[self.creator_id.id, self.team_leader_id.id,
                                      self.approver_id.id])

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
        for line in self.line_ids.filtered(lambda l: l.course_id and not l.session_ids):
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

    def action_archive(self):
        """Retire a plan without deleting its lines, approvals, or delivery links."""
        for rec in self:
            rec._require_manager()
            if rec.state == 'archived':
                continue
            previous_state = rec.state
            rec._write_workflow_values({'state': 'archived', 'active': False})
            rec._log_approval_step(
                previous_state, 'archived',
                _('Annual plan archived; historical records are retained.'))
            clear_action_activities(rec)
            rec.message_post(body=_(
                'Annual plan %s was archived from %s. Its approval and delivery '
                'history remain available for audit.') % (rec.name, previous_state))
        # The web action client expects the resolved ``views`` list. Reading
        # the configured EDS action supplies it without granting users access
        # to edit or browse Odoo's action metadata.
        return self.env.ref(
            'employee_development_system.action_eds_annual_plan').sudo().read()[0]

    def unlink(self):
        self.action_archive()
        return True


class EdsAnnualPlanLine(models.Model):
    """One program line of the annual plan.

    Carries the scheduled month, delivery method, allocated budget and the delivery
    status used by the monthly/quarterly planned-vs-actual variance report.
    """
    _name = 'eds.annual.plan.line'
    _description = 'Annual L&D Plan Line'
    _rec_name = 'program_name'
    _order = 'plan_id, scheduled_month, create_date desc, id desc'

    plan_id = fields.Many2one('eds.annual.plan', string='Annual Plan', required=True,
                              ondelete='cascade', index=True)
    course_id = fields.Many2one('eds.course', string='Training Program',
                                domain=[('status', 'in', ('draft', 'active'))])
    unscheduled_request_id = fields.Many2one(
        'eds.unscheduled.request', string='Approved Unscheduled Request',
        readonly=True, ondelete='set null', index=True)
    course_demand_id = fields.Many2one(
        'eds.tna.cycle.course.line', string='Source TNA Course Demand',
        ondelete='set null', readonly=True,
        help='Keeps the selected employee and source evidence connected to this plan program.')
    course_demand_ids = fields.Many2many(
        'eds.tna.cycle.course.line', 'eds_plan_line_course_demand_rel',
        'plan_line_id', 'demand_id', string='Source TNA Cycles', readonly=True,
        help='All selected course demand lines from closed cycles in the plan year.')
    available_tna_course_ids = fields.Many2many(
        'eds.course', compute='_compute_available_tna_course_ids',
        string='Available TNA Courses',
        help='Courses selected for planning in closed TNA cycles from this plan year. '
             'When Only Selected TNA Cycles is enabled, only those cycles are used.')
    course_identity_locked = fields.Boolean(
        compute='_compute_course_identity_locked',
        help='The program identity comes from the chosen catalog course or TNA demand.')
    source_cycle_names = fields.Char(
        string='Source TNA Cycles', compute='_compute_source_cycle_names')

    @api.depends('plan_id', 'plan_id.fiscal_year', 'plan_id.company_id',
                 'plan_id.restrict_tna_cycles', 'plan_id.selected_tna_cycle_ids')
    def _compute_available_tna_course_ids(self):
        courses_by_plan = {}
        for line in self:
            plan = line.plan_id
            if plan and plan not in courses_by_plan:
                courses_by_plan[plan] = plan._planning_catalog_courses()
            line.available_tna_course_ids = courses_by_plan.get(
                plan, self.env['eds.course'].browse())

    @api.depends('course_id', 'course_demand_id', 'course_demand_ids')
    def _compute_course_identity_locked(self):
        for line in self:
            line.course_identity_locked = bool(
                line.course_id or line.course_demand_id or line.course_demand_ids)

    @api.depends('course_demand_id', 'course_demand_ids')
    def _compute_source_cycle_names(self):
        for line in self:
            cycles = (line.course_demand_ids | line.course_demand_id).mapped('cycle_id')
            line.source_cycle_names = ', '.join(cycles.mapped('name'))

    @api.constrains('course_demand_id', 'course_demand_ids', 'plan_id')
    def _check_course_demand_cycles(self):
        for line in self:
            for demand in line.course_demand_ids | line.course_demand_id:
                if (demand.cycle_id.state not in ('closed', 'archived')
                        or demand.cycle_id.year != line.plan_id.fiscal_year
                        or demand.cycle_id.company_id != line.plan_id.company_id):
                    raise ValidationError(_(
                        'A plan line may use course demand only from closed TNA cycles '
                        'in the same fiscal year and company. Existing archived cycle '
                        'links remain for history.'))

    def _check_new_closed_course_demands(self, previous=None):
        """Keep archived demand as history, never add it to a new plan line."""
        previous = previous or {}
        for line in self:
            old_ids = previous.get(line.id, set())
            added = (line.course_demand_ids | line.course_demand_id).filtered(
                lambda demand: demand.id not in old_ids)
            if any(demand.cycle_id.state != 'closed' or not demand.cycle_id.active
                   for demand in added):
                raise ValidationError(_(
                    'Only active, closed TNA cycles may supply new annual plan demand.'))
    program_name = fields.Char(string='Program Name',
                               help='Internal display name copied from the catalog course.')
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
        string='Est. Provider Cost per Person per Session',
        currency_field='budget_currency_id', default=0.0)
    total_provider_cost = fields.Monetary(
        string='Total Est. Provider Cost', currency_field='budget_currency_id',
        compute='_compute_cost_breakdown', store=True)
    est_venue_cost_per_pax_day = fields.Monetary(
        string='Est. Venue/Lunch/Refreshment per Person per Day',
        currency_field='budget_currency_id', default=0.0)
    total_venue_cost = fields.Monetary(
        string='Total Est. Venue/Lunch/Refreshment', currency_field='budget_currency_id',
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
    vendor_selection_ids = fields.One2many(
        'eds.course.vendor.selection', 'plan_line_id', string='Vendor Sourcing')
    actual_delivery_method = fields.Selection([
        ('internal', 'Internal / ToT'),
        ('local_external', 'Local External'),
        ('international', 'International'),
        ('mixed', 'Mixed Delivery'),
    ], string='Actual / Chosen Delivery', compute='_compute_execution_delivery')
    delivery_change_reason = fields.Char(
        string='Delivery Change Reason', compute='_compute_execution_delivery')
    budget_line_ids = fields.One2many(
        'eds.annual.plan.budget.line', 'plan_line_id', string='Itemized Budget Lines')
    manual_budget_allocated = fields.Monetary(
        string='Manual Budget Allocation', currency_field='budget_currency_id', default=0.0,
        help='Used only when no itemized prices or legacy provider/venue rates are entered.')
    budget_allocated = fields.Monetary(string='Budget Allocated',
                                       currency_field='budget_currency_id',
                                       compute='_compute_cost_breakdown', store=True, readonly=True)
    budget_allocated_display = fields.Char(
        string='Budget Allocated', compute='_compute_budget_allocated_display', readonly=True)
    budget_currency_id = fields.Many2one(
        'res.currency', string='Program Currency', required=True,
        default=lambda self: currency_for_delivery(self.env, 'internal'),
        help='Internal and local external programs use ETB. International programs default to USD; other currencies are allowed.')
    status = fields.Selection([
        ('planned', 'Planned'),
        ('scheduled', 'Scheduled'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
        ('delayed', 'Delayed'),
    ], string='Status', default='planned', required=True)
    session_ids = fields.One2many('eds.session', 'plan_line_id', string='Sessions')
    session_count = fields.Integer(string='Session Count', compute='_compute_session_count', store=True)
    fiscal_year = fields.Char(related='plan_id.fiscal_year', string='Fiscal Year', store=True, index=True)
    plan_state = fields.Selection(related='plan_id.state', string='Plan Status', store=True, index=True)
    is_completed = fields.Boolean(
        string='Course Completed', default=False, copy=False,
        help='Marked as completed once all sessions for this program have finished.')
    planned_vs_actual = fields.Float(
        string='Planned vs Actual (%)', compute='_compute_planned_vs_actual', store=True,
        help='Percentage of this program’s sessions that have actually been delivered.')

    # Plan vs Actual Performance Tracking (aligned with Plan_vs_Actual template)
    actual_participants = fields.Integer(
        string='Actual Participants', compute='_compute_actual_metrics', store=True)
    participant_variance = fields.Integer(
        string='Participant Variance (Planned − Actual)', compute='_compute_actual_metrics', store=True)
    actual_cost = fields.Monetary(
        string='Actual Cost', currency_field='budget_currency_id',
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

    @api.depends('session_ids.delivery_method', 'session_ids.status',
                 'vendor_selection_ids.state', 'vendor_selection_ids.delivery_method',
                 'vendor_selection_ids.delivery_change_reason')
    def _compute_execution_delivery(self):
        for line in self:
            methods = set(line.session_ids.filtered(
                lambda session: session.status != 'cancelled').mapped('delivery_method'))
            sourced = line.vendor_selection_ids.filtered(
                lambda selection: selection.state == 'awarded').sorted('id', reverse=True)[:1]
            if not methods and sourced:
                methods = {sourced.delivery_method}
            line.actual_delivery_method = (
                'mixed' if len(methods) > 1 else next(iter(methods), False))
            line.delivery_change_reason = sourced.delivery_change_reason if sourced else False

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

    @api.depends('budget_allocated', 'budget_currency_id',
                 'budget_currency_id.symbol', 'budget_currency_id.decimal_places')
    def _compute_budget_allocated_display(self):
        for rec in self:
            currency = rec.budget_currency_id
            symbol = (currency.symbol or currency.name) if currency else ''
            decimals = currency.decimal_places if currency else 2
            amount = f'{rec.budget_allocated or 0.0:,.{decimals}f}'
            rec.budget_allocated_display = f'{symbol} {amount}'.strip()

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

    def action_toggle_completed(self):
        for rec in self:
            if not rec.is_completed:
                if rec.session_count < 1:
                    raise UserError(_(
                        'Course "%s" cannot be marked as completed because at least one training session must be conducted first (Current Sessions: 0).'
                    ) % (rec.course_id.name or rec.program_name or _('Training Program')))
                rec.sudo().write({'is_completed': True, 'status': 'delivered'})
            else:
                rec.sudo().write({'is_completed': False, 'status': 'scheduled' if rec.session_count else 'planned'})
        return True

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
                    lambda e: e.state in ('enrolled', 'completed', 'incomplete'))
                    .mapped('employee_id').ids)
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
            self.program_category = self.course_id.program_category
            self.delivery_method = self.course_id.recommended_source or 'internal'
            self._onchange_delivery_currency()

    @api.model
    def _default_currency_for_delivery(self, delivery_method):
        return currency_for_delivery(self.env, delivery_method)

    @api.onchange('delivery_method')
    def _onchange_delivery_currency(self):
        if self.delivery_method != 'international' or not self.budget_currency_id or self.budget_currency_id.name == 'ETB':
            self.budget_currency_id = self._default_currency_for_delivery(self.delivery_method)

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
        """Create one draft session for this line (used on publication)."""
        self.ensure_one()
        if not self.course_id:
            raise UserError(_(
                'Add this program to the course catalog and select the course before creating a training session.'))
        active_session = self.session_ids.filtered(lambda session: session.status != 'cancelled')[:1]
        if active_session:
            return active_session
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
            'source_type': 'unscheduled' if self.unscheduled_request_id else 'annual_plan',
            'unscheduled_request_id': self.unscheduled_request_id.id or False,
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
            if not vals.get('course_id'):
                raise ValidationError(_(
                    'Select a training program from the course catalog before adding a plan line.'))
            if not self.env.su and vals.get('plan_id'):
                self.env['eds.annual.plan'].browse(vals['plan_id'])._check_can_edit_content()
            method = vals.get('delivery_method') or 'internal'
            if vals.get('budget_currency_id'):
                validate_delivery_currency(self.env, method, vals['budget_currency_id'])
            else:
                vals['budget_currency_id'] = self._default_currency_for_delivery(method).id
            if 'budget_allocated' in vals:
                vals.setdefault('manual_budget_allocated', vals.pop('budget_allocated'))
            course = self.env['eds.course'].browse(vals['course_id'])
            vals['program_name'] = course.name
            vals['program_category'] = course.program_category
        records = super().create(vals_list)
        records._check_new_closed_course_demands()
        if not self.env.su:
            records._check_planning_course_scope()
        for rec in records:
            if not rec.budget_line_ids:
                rec._init_default_budget_lines()
        return records

    def write(self, vals):
        previous_demands = ({
            line.id: (set() if 'plan_id' in vals else
                      set((line.course_demand_ids | line.course_demand_id).ids))
            for line in self
        } if {'course_demand_id', 'course_demand_ids', 'plan_id'} & vals.keys() else {})
        if 'course_id' in vals and not vals['course_id']:
            raise ValidationError(_('A plan line must have a catalog training program.'))
        if 'program_name' in vals and 'course_id' not in vals:
            raise ValidationError(_('Program name comes from the selected catalog course.'))
        if not self.env.su:
            content_fields = {
                'plan_id', 'course_id', 'program_name', 'program_category',
                'training_category', 'delivery_method', 'target_audience',
                'planned_participants', 'budget_allocated', 'manual_budget_allocated',
                'budget_currency_id', 'scheduled_quarter', 'scheduled_month',
                'scheduled_date', 'course_demand_id', 'course_demand_ids',
            }
            if content_fields & vals.keys():
                self.mapped('plan_id')._check_can_edit_content()
            if {'course_id', 'program_name', 'program_category'} & vals.keys():
                locked = self.filtered(lambda line:
                    line.course_id or line.course_demand_id or line.course_demand_ids)
                changed = locked.filtered(lambda line:
                    ('course_id' in vals and (vals['course_id'] or False) != line.course_id.id)
                    or ('program_name' in vals and vals['program_name'] != line.program_name)
                    or ('program_category' in vals
                        and vals['program_category'] != line.program_category))
                if changed:
                    raise UserError(_(
                        'The training program, name and category are fixed for an existing '
                        'catalog or TNA program. Add a separate plan line if needed.'))
        vals = dict(vals)
        if vals.get('course_id'):
            course = self.env['eds.course'].browse(vals['course_id'])
            vals['program_name'] = course.name
            vals['program_category'] = course.program_category
        if 'delivery_method' in vals and 'budget_currency_id' not in vals:
            vals['budget_currency_id'] = self._default_currency_for_delivery(vals['delivery_method']).id
        if {'delivery_method', 'budget_currency_id'} & vals.keys():
            for line in self:
                validate_delivery_currency(
                    self.env, vals.get('delivery_method', line.delivery_method),
                    vals.get('budget_currency_id', line.budget_currency_id.id))
        if 'budget_allocated' in vals:
            vals.setdefault('manual_budget_allocated', vals.pop('budget_allocated'))
        result = super().write(vals)
        if previous_demands:
            self._check_new_closed_course_demands(previous_demands)
        if not self.env.su and {'course_id', 'plan_id', 'is_addendum'} & vals.keys():
            self._check_planning_course_scope()
        return result

    def _check_planning_course_scope(self):
        for line in self:
            if (line.course_id and not line.is_addendum
                    and line.course_id not in line.plan_id._planning_catalog_courses()):
                raise ValidationError(_(
                    'Training Program must be a course selected for planning in a '
                    'closed TNA cycle from this plan year.'))

    def unlink(self):
        if not self.env.su:
            self.mapped('plan_id')._check_can_edit_content()
        return super().unlink()

    def _write_delivery_status(self, status):
        """Session lifecycle updates may change delivery status on an approved plan."""
        return super(EdsAnnualPlanLine, self).write({'status': status})


class EdsAnnualPlanBudgetLine(models.Model):
    """Itemized budget expense line for an Annual Plan Line.

    Supports Hotel, Per Diem, Vendor, Transportation, etc.
    Checkbox 'is_per_employee' auto-multiplies by participant count.
    Checkbox 'is_general' adds as fixed total budget.
    """
    _name = 'eds.annual.plan.budget.line'
    _description = 'Annual Plan Program Budget Item'
    _order = 'create_date desc, id desc'

    @staticmethod
    def _with_matching_budget_basis(vals):
        """Keep the hidden fixed flag opposite a single changed basis switch."""
        vals = dict(vals)
        if 'is_per_employee' in vals and 'is_general' not in vals:
            vals['is_general'] = not vals['is_per_employee']
        elif 'is_general' in vals and 'is_per_employee' not in vals:
            vals['is_per_employee'] = not vals['is_general']
        return vals

    def init(self):
        # Preserve existing calculations while correcting legacy rows in which
        # both switches (or neither switch) were saved before validation existed.
        self.env.cr.execute("""
            UPDATE eds_annual_plan_budget_line
               SET is_general = NOT is_per_employee
             WHERE is_general = is_per_employee
        """)

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._with_matching_budget_basis(vals) for vals in vals_list]
        if not self.env.su:
            plan_lines = self.env['eds.annual.plan.line'].browse([
                vals['plan_line_id'] for vals in vals_list if vals.get('plan_line_id')])
            plan_lines.mapped('plan_id')._check_can_edit_content()
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            self.mapped('plan_line_id.plan_id')._check_can_edit_content()
        return super().write(self._with_matching_budget_basis(vals))

    def unlink(self):
        if not self.env.su:
            self.mapped('plan_line_id.plan_id')._check_can_edit_content()
        return super().unlink()

    plan_line_id = fields.Many2one(
        'eds.annual.plan.line', string='Program Line', required=True, ondelete='cascade', index=True)
    name = fields.Char(string='Expense / Budget Line Name', required=True)
    unit_price = fields.Float(string='Price / Rate', digits=(16, 2), default=0.0)
    is_per_employee = fields.Boolean(
        string='Per Employee', default=False,
        help='If checked, this rate is multiplied by the number of planned participants.')
    is_general = fields.Boolean(
        string='General / Fixed', default=True,
        help='Fixed total expenditure regardless of participant count.')
    currency_id = fields.Many2one('res.currency', related='plan_line_id.budget_currency_id', readonly=True)
    total_amount = fields.Float(
        string='Total Amount', digits=(16, 2), compute='_compute_total_amount', store=True)
    notes = fields.Char(string='Notes / Description')
    remark = fields.Text(
        string='Remark / Justification',
        help='Context for this specific expense item, separate from its description.')

    @api.onchange('is_per_employee', 'unit_price')
    def _onchange_is_per_employee(self):
        self.is_general = not self.is_per_employee
        self._compute_total_amount()

    @api.onchange('is_general')
    def _onchange_is_general(self):
        self.is_per_employee = not self.is_general
        self._compute_total_amount()

    @api.constrains('is_per_employee', 'is_general')
    def _check_budget_basis(self):
        for rec in self:
            if rec.is_per_employee == rec.is_general:
                raise ValidationError(_(
                    'Choose exactly one budget basis: Per Employee or General (Fixed).'))

    @api.depends('unit_price', 'is_per_employee', 'plan_line_id.planned_participants')
    def _compute_total_amount(self):
        for rec in self:
            # An inline budget row on a new plan line has no plan_line_id yet.
            # The parent form supplies its current participant count in context.
            participants = (rec.plan_line_id.planned_participants if rec.plan_line_id else
                            rec.env.context.get('budget_planned_participants', 0)) or 0
            if rec.is_per_employee:
                rec.total_amount = rec.unit_price * participants
            else:
                rec.total_amount = rec.unit_price
