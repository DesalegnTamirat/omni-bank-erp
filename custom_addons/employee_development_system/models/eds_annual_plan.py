# -*- coding: utf-8 -*-
from datetime import date, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class EdsAnnualPlan(models.Model):
    """Annual Learning & Development Plan and Calendar (-026, ...022).

    The approved TNA needs and approved curricula are assembled into a draft annual
    plan (/) within the calendar SLA, routed through the
    Director PPDD -> CPCO -> SMC approval chain and published (). Publishing
    auto-activates the downstream sessions so nominations can start. Approved
    unscheduled training requests amend the published plan as addenda
    (, /076). Delivery is monitored with planned-vs-actual variance
    per line ().
    """
    _name = 'eds.annual.plan'
    _description = 'Annual L&D Plan & Calendar'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    fiscal_year = fields.Char(string='Fiscal Year', required=True,
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
        help='Share of plan lines whose sessions have been delivered ().')
    calendar_generation_date = fields.Date(string='Calendar Generated On', readonly=True)
    calendar_sla_deadline = fields.Date(
        string='Calendar SLA Deadline', compute='_compute_calendar_sla', store=True,
        help='Computed from the calendar SLA in settings (default 5 working days, ).')
    sla_breached = fields.Boolean(
        string='SLA Breached', compute='_compute_calendar_sla', store=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('director_review', 'Director PPDD Review'),
        ('cpco_endorsement', 'CPCO Endorsement'),
        ('smc_approval', 'SMC Approval'),
        ('published', 'Published'),
        ('amended', 'Amended'),
    ], string='Status', default='draft', required=True, tracking=True)

    # Segregation of duties (): reviewer != endorser != approver
    reviewer_id = fields.Many2one('res.users', string='Reviewer (Director PPDD)', tracking=True)
    endorser_id = fields.Many2one('res.users', string='Endorser (CPCO)', tracking=True)
    approver_id = fields.Many2one('res.users', string='Approver (SMC)', tracking=True)
    approved_by_id = fields.Many2one('res.users', string='Approved By', readonly=True)
    approval_date = fields.Datetime(string='Approval Date', readonly=True)
    approval_history_ids = fields.One2many(
        'eds.approval.history', 'annual_plan_id', string='Approval History',
        domain=[('model', '=', 'eds.annual.plan')])

    amendment_ids = fields.One2many(
        'eds.unscheduled.request', 'annual_plan_id', string='Amendments',
        help='Approved unscheduled training requests appended as addenda (/075/076).')
    amendment_count = fields.Integer(string='Amendments', compute='_compute_counts')
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.depends('line_ids', 'line_ids.status')
    def _compute_counts(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)
            rec.delivered_count = len(rec.line_ids.filtered(lambda l: l.status == 'delivered'))
            rec.amendment_count = len(rec.amendment_ids)

    @api.depends('line_ids.budget_allocated')
    def _compute_budget(self):
        for rec in self:
            rec.budget_total = sum(rec.line_ids.mapped('budget_allocated'))

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
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.annual.plan') or _('New')
        return super().create(vals_list)

    # ── Calendar generation (/020) ───────────────────────────────────
    def action_generate_calendar(self):
        """build the draft calendar from the approved TNA + approved curricula.

        Each approved curriculum contributes its course as a plan line; approved TNA
        needs that were not converted to a catalog course contribute a program line
        (free text). Runs within the calendar SLA (default 5 working days).
        """
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('The calendar can only be generated while the plan is a draft.'))
        curricula = self.env['eds.curriculum'].search(
            [('state', '=', 'approved'), ('active', '=', True)])
        courses = curricula.mapped('course_id')
        courses |= self.env['eds.course'].search(
            [('status', '=', 'active'), ('id', 'not in', courses.ids)])
        created = 0
        for course in courses:
            if self.line_ids.filtered(lambda l: l.course_id == course):
                continue
            self.write({'line_ids': [(0, 0, {
                'course_id': course.id,
                'program_name': course.name,
                'delivery_method': course.delivery_method,
            })]})
            created += 1
        # Approved TNA needs not yet converted to a course (e.g. externally sourced).
        # Only Classroom (+ the classroom part of Blended) is actioned in EDS;
        # pure e-learning needs route to the LMS instead ( business rule).
        for entry in self.env['eds.tna.entry'].search([
            ('state', '=', 'approved'),
            ('delivery_mode', 'in', ('classroom', 'blended')),
            ('proposed_program', '!=', False),
            ('converted_course_ref', '=', False),
        ]):
            if not entry.proposed_program:
                continue
            if self.line_ids.filtered(lambda l: l.program_name == entry.proposed_program):
                continue
            self.write({'line_ids': [(0, 0, {
                'program_name': entry.proposed_program,
                'delivery_method': 'internal',
            })]})
            created += 1
        self.calendar_generation_date = date.today()
        self.message_post(
            body=_('Calendar generated for %s - %d programs added. SLA deadline: %s ().')
            % (self.name, created, self.calendar_sla_deadline))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'eds.annual.plan',
            'res_id': self.id,
            'view_mode': 'form',
        }

    @api.model
    def _add_approved_curriculum(self, curriculum):
        """ hook called when a curriculum is CPCO-approved: insert its course
        into the current draft annual plan."""
        plan = self.search([
            ('fiscal_year', '=', str(date.today().year)),
            ('state', '=', 'draft'),
        ], limit=1)
        if not plan:
            plan = self.create({'fiscal_year': str(date.today().year)})
        if not plan.line_ids.filtered(lambda l: l.course_id == curriculum.course_id):
            plan.write({'line_ids': [(0, 0, {
                'course_id': curriculum.course_id.id,
                'program_name': curriculum.course_id.name,
                'delivery_method': curriculum.course_id.delivery_method,
            })]})
        return plan

    # ── Approval chain with segregation of duties () ─────────────────
    def _check_segregation(self):
        """Reviewer != Endorser != Approver ()."""
        self.ensure_one()
        users = [self.reviewer_id.id, self.endorser_id.id, self.approver_id.id]
        present = [u for u in users if u]
        if len(present) != len(set(present)):
            raise ValidationError(_(
                'Segregation of Duties Violation (): Reviewer, Endorser and '
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
            raise UserError(_('This approval step requires L&D Manager authority ().'))

    def action_submit_director(self):
        """Draft -> Director PPDD Review."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft plans can be submitted to Director review.'))
            if not rec.line_ids:
                raise UserError(_('Generate the calendar before submitting the plan for approval.'))
            rec.state = 'director_review'
            rec._log_approval_step('draft', 'director_review')
            rec.message_post(body=_('Annual plan %s submitted to Director PPDD review.')
                             % rec.name)

    def action_director_approve(self):
        """Director PPDD Review -> CPCO Endorsement."""
        for rec in self:
            rec._require_manager()
            if rec.state != 'director_review':
                raise UserError(_('Only plans under Director review can be endorsed by CPCO.'))
            rec.reviewer_id = self.env.user.id
            rec._check_segregation()
            rec.state = 'cpco_endorsement'
            rec._log_approval_step('director_review', 'cpco_endorsement')
            rec.message_post(body=_('Annual plan %s approved by Director PPDD, sent to CPCO endorsement.')
                             % rec.name)

    def action_cpco_approve(self):
        """CPCO Endorsement -> SMC Approval."""
        for rec in self:
            rec._require_manager()
            if rec.state != 'cpco_endorsement':
                raise UserError(_('Only CPCO-endorsed plans can move to SMC approval.'))
            rec.endorser_id = self.env.user.id
            rec._check_segregation()
            rec.state = 'smc_approval'
            rec._log_approval_step('cpco_endorsement', 'smc_approval')
            rec.message_post(body=_('Annual plan %s endorsed by CPCO, submitted to SMC for approval.')
                             % rec.name)

    def action_publish(self):
        """SMC Approval -> Published: activates the downstream sessions."""
        for rec in self:
            rec._require_manager()
            if rec.state != 'smc_approval':
                raise UserError(_('Only SMC-approved plans can be published.'))
            rec.approver_id = self.env.user.id
            rec._check_segregation()
            rec.write({
                'state': 'published',
                'approved_by_id': self.env.user.id,
                'approval_date': fields.Datetime.now(),
            })
            rec._log_approval_step('smc_approval', 'published', _('Published by SMC'))
            rec._activate_downstream()
            rec.message_post(body=_('Annual plan %s published - sessions are now open for nomination '
                                    '().') % rec.name)

    def _activate_downstream(self):
        """Create a draft session for each planned line so scheduling/nomination can start."""
        for line in self.line_ids.filtered(lambda l: not l.session_ids):
            line._create_default_session()

    def action_amend(self):
        """Published -> Amended: reopens the plan for authorized addenda ()."""
        for rec in self:
            rec._require_manager()
            if rec.state != 'published':
                raise UserError(_('Only published plans can be amended.'))
            rec.state = 'amended'
            rec._log_approval_step('published', 'amended', _('Plan reopened for addenda'))
            rec.message_post(body=_('Annual plan %s reopened for amendments - approved unscheduled '
                                    'requests will be appended as addenda ().') % rec.name)

    def action_re_publish(self):
        """Amended -> Published: closes the amendment window again."""
        for rec in self:
            rec._require_manager()
            if rec.state != 'amended':
                raise UserError(_('Only amended plans can be re-published.'))
            rec.state = 'published'
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
                raise UserError(_('Published/amended annual plans cannot be deleted ().'))
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
    _order = 'plan_id, scheduled_month, id'

    plan_id = fields.Many2one('eds.annual.plan', string='Annual Plan', required=True,
                              ondelete='cascade', index=True)
    course_id = fields.Many2one('eds.course', string='Training Program',
                                domain=[('status', 'in', ('draft', 'active'))])
    program_name = fields.Char(string='Program Name',
                               help='Used when the program is not in the course catalog '
                                    '(e.g. unscheduled-request addenda, /076).')
    scheduled_month = fields.Char(
        string='Scheduled Month (YYYY-MM)',
        help='Month the program is planned for, e.g. 2026-09. Free text keeps planning '
             'flexible ().')
    delivery_method = fields.Selection([
        ('internal', 'Internal Delivery'),
        ('local_external', 'Local External Provider'),
        ('international', 'International Provider'),
    ], string='Delivery Method', default='internal')
    target_employee_segment = fields.Char(string='Target Employee Segment')
    budget_allocated = fields.Monetary(string='Budget Allocated',
                                       currency_field='budget_currency_id')
    budget_currency_id = fields.Many2one('res.currency', related='plan_id.budget_currency_id',
                                         readonly=True)
    status = fields.Selection([
        ('planned', 'Planned'),
        ('scheduled', 'Scheduled'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
        ('delayed', 'Delayed'),
    ], string='Status', default='planned', required=True)
    session_ids = fields.One2many('eds.session', 'plan_line_id', string='Sessions')
    session_count = fields.Integer(string='Sessions', compute='_compute_session_count')
    planned_vs_actual = fields.Float(
        string='Planned vs Actual (%)', compute='_compute_planned_vs_actual', store=True,
        help='Percentage of this program\u2019s sessions that have actually been delivered '
             '().')
    is_addendum = fields.Boolean(
        string='Addendum', default=False,
        help='Added through an approved unscheduled training request (/076).')
    notes = fields.Text(string='Notes')

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

    @api.onchange('course_id')
    def _onchange_course_id(self):
        if self.course_id:
            self.program_name = self.course_id.name
            self.delivery_method = self.course_id.delivery_method

    def _create_default_session(self):
        """Create one draft session for this line (used on publication, )."""
        self.ensure_one()
        if self.session_ids:
            return self.session_ids[0]
        start = date.today()
        if self.scheduled_month:
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
