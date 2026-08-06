# -*- coding: utf-8 -*-
from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EdsCourse(models.Model):
    """Training program / course catalog entry (FREDS011-013, FR-EDS-011...013, FR-EDS-017).

    A course links to the approved competency framework (FREDS012) with a required
    proficiency level per competency, and carries its curriculum version(s).
    """
    _name = 'eds.course'
    _description = 'Training Course / Program'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'code, name'
    _rec_name = 'name'

    code = fields.Char(string='Course Code', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    name = fields.Char(string='Course Name', required=True, tracking=True)
    category = fields.Selection([
        ('developmental', 'Developmental'),
        ('values_ethics', 'Values & Ethics'),
        ('technical_compliance', 'Technical / Compliance'),
    ], string='Category', default='developmental', required=True, tracking=True)
    delivery_method = fields.Selection([
        ('internal', 'Internal Delivery'),
        ('local_external', 'Local External Provider'),
        ('international', 'International Provider'),
    ], string='Delivery Method', default='internal', tracking=True)
    duration_days = fields.Integer(string='Duration (Days)', default=1, tracking=True)
    schedule = fields.Text(string='Schedule / Frequency')
    description = fields.Text(string='Description')
    version = fields.Char(string='Current Version', default='v1.0', tracking=True)
    status = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('suspended', 'Suspended'),
        ('retired', 'Retired'),
    ], string='Status', default='draft', tracking=True)

    competency_line_ids = fields.One2many(
        'eds.course.competency.line', 'course_id', string='Competency Mapping',
        help='Course-to-competency mapping with required proficiency (FREDS012).')
    curriculum_ids = fields.One2many('eds.curriculum', 'course_id', string='Curriculum Versions')
    current_curriculum_id = fields.Many2one(
        'eds.curriculum', string='Current Curriculum', compute='_compute_current_curriculum')
    target_audience_ids = fields.Many2many(
        'hr.job', string='Target Audience (Job Positions)')
    prerequisite_course_ids = fields.Many2many(
        'eds.course', 'eds_course_prereq_rel', 'course_id', 'prerequisite_id',
        string='Prerequisite Courses')
    development_request_ids = fields.One2many(
        'eds.course.development.request', 'course_id', string='Development Requests')
    development_request_count = fields.Integer(
        string='Development Requests', compute='_compute_counts')
    curriculum_count = fields.Integer(string='Curriculums', compute='_compute_counts')

    # ── Training delivery sourcing recommendation (FREDS027) ─────────────────
    recommended_source = fields.Selection([
        ('internal', 'Internal Delivery'),
        ('local_external', 'External Local Provider'),
        ('international', 'External International Provider'),
    ], string='Recommended Delivery Source', tracking=True,
        help='Recommended by the L&D officer with justification (FREDS027).')
    sourcing_justification = fields.Text(
        string='Sourcing Justification',
        help='Why this delivery source is recommended (FREDS027).')
    sourcing_state = fields.Selection([
        ('draft', 'Not Recommended'),
        ('director_review', 'Director PPDD Review'),
        ('decided', 'Decision Recorded'),
    ], string='Sourcing Status', default='draft', tracking=True)
    sourcing_decision = fields.Selection([
        ('internal', 'Approve - Internal Delivery'),
        ('local_external', 'Approve - External Local Provider'),
        ('international', 'Approve - External International Provider'),
        ('reject', 'Reject Recommendation'),
    ], string='Director PPDD Decision', tracking=True)
    sourcing_decision_date = fields.Date(string='Decision Date', readonly=True)
    sourcing_decided_by_id = fields.Many2one('res.users', string='Decided By', readonly=True)

    def action_submit_sourcing(self):
        """FREDS027: officer submits the recommended delivery source for Director PPDD review."""
        for rec in self:
            if rec.sourcing_state != 'draft':
                raise UserError(_('The sourcing recommendation was already submitted.'))
            if not rec.recommended_source:
                raise UserError(_('Select the recommended delivery source first (FREDS027).'))
            if not rec.sourcing_justification:
                raise UserError(_('Enter the sourcing justification before submission (FREDS027).'))
            rec.sourcing_state = 'director_review'
            rec.message_post(body=_('Sourcing recommendation %s submitted for Director PPDD review '
                                    '(FREDS027).') % rec.recommended_source)

    def action_record_sourcing_decision(self):
        """FREDS027: Director PPDD records the sourcing decision."""
        for rec in self:
            rec._require_manager()
            if rec.sourcing_state != 'director_review':
                raise UserError(_('Only recommendations under Director review can be decided.'))
            if not rec.sourcing_decision:
                raise UserError(_('Record the Director PPDD decision first (FREDS027).'))
            rec.write({'sourcing_state': 'decided',
                       'sourcing_decision_date': date.today(),
                       'sourcing_decided_by_id': self.env.user.id})
            rec.message_post(body=_('Director PPDD decision for %s: %s (FREDS027).')
                             % (rec.name, rec.sourcing_decision))

    @api.depends('curriculum_ids', 'curriculum_ids.state')
    def _compute_current_curriculum(self):
        for rec in self:
            # Newest record = newest version (version strings must not be sorted
            # lexicographically: 'v1.10' would sort before 'v1.2').
            approved = rec.curriculum_ids.filtered(lambda c: c.state == 'approved')
            rec.current_curriculum_id = approved.sorted('id', reverse=True).ids[0] if approved else False

    @api.depends('curriculum_ids', 'development_request_ids')
    def _compute_counts(self):
        for rec in self:
            rec.curriculum_count = len(rec.curriculum_ids)
            rec.development_request_count = len(rec.development_request_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code', _('New')) == _('New'):
                vals['code'] = self.env['ir.sequence'].sudo().next_by_code('eds.course') or _('New')
        return super().create(vals_list)

    def action_mark_active(self):
        for rec in self:
            if rec.status != 'draft':
                raise UserError(_('Only draft courses can be activated.'))
            rec.status = 'active'
            rec.message_post(body=_('Course %s activated.') % rec.name)

    def action_suspend(self):
        for rec in self:
            if rec.status not in ('draft', 'active'):
                raise UserError(_('Only draft or active courses can be suspended.'))
            rec.status = 'suspended'
            rec.message_post(body=_('Course %s suspended.') % rec.name)

    def action_retire(self):
        for rec in self:
            if rec.status not in ('draft', 'active', 'suspended'):
                raise UserError(_('This course is already retired.'))
            rec.status = 'retired'
            rec.message_post(body=_('Course %s retired.') % rec.name)

    def _require_manager(self):
        if not (self.env.su or self.env.user.has_group('employee_development_system.group_eds_manager')
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('This step requires L&D Manager authority (FREDS027).'))


class EdsCourseCompetencyLine(models.Model):
    """Course -> competency mapping with the required proficiency level (FREDS012)."""
    _name = 'eds.course.competency.line'
    _description = 'Course Competency Mapping Line'

    course_id = fields.Many2one('eds.course', string='Course', required=True, ondelete='cascade')
    competency_id = fields.Many2one(
        'competency.competency', string='Competency', required=True, ondelete='cascade')
    required_level = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Required Proficiency Level', default='3', required=True)
    notes = fields.Text(string='Notes')

    _sql_constraints = [
        ('course_competency_uniq', 'unique(course_id, competency_id)',
         'This competency is already mapped to the course!'),
    ]


class EdsCourseDevelopmentRequest(models.Model):
    """Request to develop a course from approved TNA needs (FREDS011-014, FR-EDS-017).

    Converted from approved TNA entries; carries an SLA deadline computed from the
    configurable working-day SLA (default 10 working days, FREDS014). On approval the
    request converts to an `eds.course` with competency mapping lines (FREDS012).
    """
    _name = 'eds.course.development.request'
    _description = 'Course Development Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    tna_entry_ids = fields.Many2many(
        'eds.tna.entry', 'eds_dev_req_tna_rel', 'dev_request_id', 'tna_entry_id',
        string='Source TNA Needs',
        domain=[('state', 'in', ('approved', 'converted'))])
    course_id = fields.Many2one(
        'eds.course', string='Course', readonly=True,
        help='Created when the request is approved and converted (FREDS011).')
    assigned_officer_id = fields.Many2one(
        'res.users', string='Assigned Officer',
        default=lambda self: self.env.user, tracking=True)
    competency_gap_ids = fields.Many2many(
        'competency.competency', string='Competency Gaps',
        help='Competencies to be covered, derived from the TNA needs (FREDS012).')
    target_job_ids = fields.Many2many('hr.job', string='Target Job Positions')
    required_proficiency = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Required Proficiency', default='3')
    expected_outcomes = fields.Text(string='Expected Learning Outcomes')
    sla_deadline = fields.Date(
        string='SLA Deadline', compute='_compute_sla_deadline', store=True,
        help='Computed from the course development SLA in settings (default 10 working days, FREDS014).')
    sla_breached = fields.Boolean(
        string='SLA Breached', compute='_compute_sla_breached', store=True, tracking=True)
    last_reminder_date = fields.Date(string='Last SLA Reminder', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_development', 'In Development'),
        ('submitted', 'Submitted for Approval'),
        ('approved', 'Approved'),
        ('done', 'Done'),
    ], string='Status', default='draft', required=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.depends('create_date')
    def _compute_sla_deadline(self):
        for rec in self:
            if rec.create_date:
                days = rec._get_int_param('eds.curriculum_sla_days', 10)
                rec.sla_deadline = self.env['eds.tna.cycle']._add_working_days(
                    rec.create_date.date(), days)
            else:
                rec.sla_deadline = False

    @api.depends('sla_deadline', 'state')
    def _compute_sla_breached(self):
        today = date.today()
        for rec in self:
            rec.sla_breached = bool(
                rec.sla_deadline and rec.sla_deadline < today
                and rec.state in ('draft', 'in_development', 'submitted'))

    @api.model
    def _get_int_param(self, key, default):
        try:
            return int(self.env['ir.config_parameter'].sudo().get_param(key, str(default)))
        except ValueError:
            return default

    @api.onchange('tna_entry_ids')
    def _onchange_tna_entry_ids(self):
        comps = self.tna_entry_ids.mapped('competency_id').filtered('id')
        jobs = self.tna_entry_ids.mapped('job_position_id').filtered('id')
        if comps:
            self.competency_gap_ids = [(6, 0, comps.ids)]
        if jobs:
            self.target_job_ids = [(6, 0, jobs.ids)]
        if self.tna_entry_ids and not self.expected_outcomes:
            self.expected_outcomes = '\n'.join(
                '• %s' % (e.justification or e.name) for e in self.tna_entry_ids[:5])

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.course.development.request') or _('New')
        return super().create(vals_list)

    # ── Workflow (FREDS011/013/014) ──────────────────────────────────────────
    def action_start_development(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft requests can start development.'))
            rec.state = 'in_development'
            rec.message_post(body=_('Development of %s started. SLA deadline: %s (FREDS014).')
                             % (rec.name, rec.sla_deadline))

    def action_submit(self):
        for rec in self:
            if rec.state != 'in_development':
                raise UserError(_('Only requests in development can be submitted.'))
            if not rec.expected_outcomes:
                raise UserError(_('Expected learning outcomes are required before submission.'))
            rec.state = 'submitted'
            rec.message_post(body=_('Development request %s submitted for approval (FREDS017).')
                             % rec.name)

    def action_approve(self):
        for rec in self:
            rec._require_manager()
            if rec.state != 'submitted':
                raise UserError(_('Only submitted development requests can be approved.'))
            rec.state = 'approved'
            rec.message_post(body=_('Development request %s approved. Ready to convert to a course.')
                             % rec.name)

    def action_convert_to_course(self):
        """Approved -> Done: create the `eds.course` with competency mapping (FREDS011/012)."""
        self.ensure_one()
        if self.state not in ('approved', 'done'):
            raise UserError(_('Only approved development requests can be converted to courses.'))
        if self.course_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'eds.course',
                'res_id': self.course_id.id,
                'view_mode': 'form',
            }
        course = self.env['eds.course'].create({
            'name': self.name,
            'delivery_method': 'internal',
            'competency_line_ids': [(0, 0, {
                'competency_id': comp.id,
                'required_level': self.required_proficiency or '3',
            }) for comp in self.competency_gap_ids],
            'target_audience_ids': [(6, 0, self.target_job_ids.ids)],
        })
        self.write({'course_id': course.id, 'state': 'done'})
        for entry in self.tna_entry_ids:
            entry.write({'state': 'converted', 'converted_course_ref': course.code})
        self.message_post(
            body=_('Course %s created from development request %s (FREDS011).') % (course.code, self.name))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'eds.course',
            'res_id': course.id,
            'view_mode': 'form',
        }

    # ── SLA escalation (FREDS014) ────────────────────────────────────────────
    @api.model
    def _cron_course_sla_check(self):
        """Daily: notify the L&D Team Leader when a development request breaches its SLA.

        The stored `sla_breached` flag only refreshes on write, so the cron searches the
        deadline directly - otherwise requests whose deadline passes between writes would
        never be escalated."""
        today = date.today()
        requests = self.search([
            ('sla_deadline', '<', today),
            ('state', 'in', ('draft', 'in_development', 'submitted')),
        ])
        requests._compute_sla_breached()
        manager_group = self.env.ref('employee_development_system.group_eds_manager', raise_if_not_found=False)
        recipients = manager_group.user_ids if manager_group else self.env['res.users']
        partner_ids = recipients.filtered('partner_id').mapped('partner_id').ids
        for req in requests:
            if req.last_reminder_date and (today - req.last_reminder_date).days < 7:
                continue
            req.message_post(
                body=_('SLA BREACHED (FREDS014): Development request %s missed its SLA deadline of %s. '
                       'Notify the L&D Team Leader for escalation.') % (req.name, req.sla_deadline),
                partner_ids=partner_ids)
            req.last_reminder_date = today
        return True

    def _require_manager(self):
        if not (self.env.su or self.env.user.has_group('employee_development_system.group_eds_manager')
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('This step requires L&D Manager authority (FREDS011).'))
