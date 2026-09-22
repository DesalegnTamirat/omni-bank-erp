# -*- coding: utf-8 -*-
from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EdsCourse(models.Model):
    """Training program / course catalog entry (-013, ...013, ).

    A course links to the approved competency framework () with a required
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
        help='Course-to-competency mapping with required proficiency ().')
    curriculum_ids = fields.One2many('eds.curriculum', 'course_id', string='Curriculum Versions')
    current_curriculum_id = fields.Many2one(
        'eds.curriculum', string='Current Curriculum', compute='_compute_current_curriculum')
    target_audience_ids = fields.Many2many(
        'hr.job', string='Target Audience (Job Positions)')
    prerequisite_course_ids = fields.Many2many(
        'eds.course', 'eds_course_prereq_rel', 'course_id', 'prerequisite_id',
        string='Prerequisite Courses')
    min_tenure_months = fields.Integer(
        string='Minimum Service Tenure (Months)', default=0,
        help='Minimum tenure required in bank service before nomination eligibility.')
    development_request_ids = fields.One2many(
        'eds.course.development.request', 'course_id', string='Development Requests')
    development_request_count = fields.Integer(
        string='Development Requests', compute='_compute_counts')
    curriculum_count = fields.Integer(string='Curriculums', compute='_compute_counts')

    # Task 7: training materials with approval gate ()
    material_ids = fields.One2many('eds.material', 'course_id', string='Training Materials')
    material_count = fields.Integer(string='Materials', compute='_compute_counts')

    # Competency Framework Architecture & Outcomes Engine
    competency_count = fields.Integer(string='Mapped Competencies', compute='_compute_competency_stats', store=True)
    target_pillar_summary = fields.Char(string='Target Competency Pillars', compute='_compute_competency_stats', store=True)
    learning_outcomes = fields.Html(
        string='Expected Learning Outcomes & Behavioral Objectives',
        help='Auto-compiled from mapped competencies and their proficiency level behavioral indicators.')

    # ── Training delivery sourcing recommendation () ─────────────────
    recommended_source = fields.Selection([
        ('internal', 'Internal Delivery'),
        ('local_external', 'External Local Provider'),
        ('international', 'External International Provider'),
    ], string='Recommended Delivery Source', tracking=True,
        help='Recommended by the L&D officer with justification ().')
    sourcing_justification = fields.Text(
        string='Sourcing Justification',
        help='Why this delivery source is recommended ().')
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
        """officer submits the recommended delivery source for Director PPDD review."""
        for rec in self:
            if rec.sourcing_state != 'draft':
                raise UserError(_('The sourcing recommendation was already submitted.'))
            if not rec.recommended_source:
                raise UserError(_('Select the recommended delivery source first ().'))
            if not rec.sourcing_justification:
                raise UserError(_('Enter the sourcing justification before submission ().'))
            rec.sourcing_state = 'director_review'
            rec.message_post(body=_('Sourcing recommendation %s submitted for Director PPDD review '
                                    '().') % rec.recommended_source)

    def action_record_sourcing_decision(self):
        """Director PPDD records the sourcing decision."""
        for rec in self:
            rec._require_manager()
            if rec.sourcing_state != 'director_review':
                raise UserError(_('Only recommendations under Director review can be decided.'))
            if not rec.sourcing_decision:
                raise UserError(_('Record the Director PPDD decision first ().'))
            rec.write({'sourcing_state': 'decided',
                       'sourcing_decision_date': date.today(),
                       'sourcing_decided_by_id': self.env.user.id})
            rec.message_post(body=_('Director PPDD decision for %s: %s ().')
                             % (rec.name, rec.sourcing_decision))

    @api.depends('curriculum_ids', 'curriculum_ids.state')
    def _compute_current_curriculum(self):
        for rec in self:
            # Newest record = newest version (version strings must not be sorted
            # lexicographically: 'v1.10' would sort before 'v1.2').
            approved = rec.curriculum_ids.filtered(lambda c: c.state == 'approved')
            rec.current_curriculum_id = approved.sorted('id', reverse=True).ids[0] if approved else False

    @api.depends('curriculum_ids', 'development_request_ids', 'material_ids', 'competency_line_ids')
    def _compute_counts(self):
        for rec in self:
            rec.curriculum_count = len(rec.curriculum_ids)
            rec.development_request_count = len(rec.development_request_ids)
            rec.material_count = len(rec.material_ids)

    @api.depends('competency_line_ids', 'competency_line_ids.competency_id', 'competency_line_ids.competency_pillar')
    def _compute_competency_stats(self):
        for rec in self:
            rec.competency_count = len(rec.competency_line_ids)
            pillars = set(rec.competency_line_ids.mapped('competency_pillar'))
            pillar_names = [p.capitalize() for p in pillars if p]
            rec.target_pillar_summary = ", ".join(pillar_names) if pillar_names else _("Not Specified")

    def action_generate_learning_objectives(self):
        """Auto-compile course description, syllabus, and expected behavioral learning outcomes from mapped competencies."""
        for rec in self:
            if not rec.competency_line_ids:
                raise UserError(_("Please map at least one competency to this course before generating learning outcomes."))
            
            outcomes_html = ["<div class='o_eds_learning_outcomes' style='font-family: inherit; line-height: 1.6;'>"]
            outcomes_html.append("<div class='alert alert-info mb-3'><strong>%s:</strong> %s</div>" % (
                _("Course Curriculum Competency Alignment"),
                _("Upon completion of this course, participants will demonstrate the following proficiency standards aligned with the Bunna Bank Competency Framework.")
            ))
            
            for line in rec.competency_line_ids:
                comp = line.competency_id
                lvl_label = dict(line._fields['required_level'].selection).get(line.required_level, line.required_level)
                pillar_raw = getattr(comp, 'pillar', 'technical') or 'technical'
                pillar_label = pillar_raw.capitalize()
                
                outcomes_html.append("<div style='margin-bottom: 14px; padding: 12px 16px; background: #ffffff; border: 1px solid #e0e0e0; border-left: 5px solid #726732; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);'>")
                outcomes_html.append("<div class='d-flex justify-content-between align-items-center mb-1'>")
                outcomes_html.append("<h5 style='margin:0; color: #1d2b32;'><strong>%s</strong> <span style='font-size: 12px; color: #666;'>[%s]</span></h5>" % (comp.name, pillar_label))
                outcomes_html.append("<span class='badge bg-primary' style='font-size: 12px; padding: 4px 8px;'>Target: %s</span>" % lvl_label)
                outcomes_html.append("</div>")
                
                if comp.description:
                    outcomes_html.append("<p style='margin: 4px 0 8px 0; font-size: 13px; color: #555;'><em>%s</em></p>" % comp.description)
                if line.behavioral_indicators:
                    outcomes_html.append("<div style='font-size: 13px; color: #222; background: #fdfdfd; padding: 8px 12px; border-radius: 4px; border: 1px dashed #d5d5d5;'>")
                    outcomes_html.append("<strong>%s:</strong><br/>%s" % (_("Demonstrated Behavioral Indicators"), line.behavioral_indicators.replace('\n', '<br/>')))
                    outcomes_html.append("</div>")
                outcomes_html.append("</div>")
            
            outcomes_html.append("</div>")
            rec.learning_outcomes = "".join(outcomes_html)
            rec.message_post(body=_("Course learning objectives and behavioral indicators successfully auto-compiled from %d mapped competencies.") % len(rec.competency_line_ids))

    def action_view_materials(self):
        self.ensure_one()
        return {
            'name': _('Training Materials'),
            'type': 'ir.actions.act_window',
            'res_model': 'eds.material',
            'view_mode': 'list,form',
            'domain': [('course_id', '=', self.id)],
            'context': {'default_course_id': self.id},
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code', _('New')) == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('eds.course') or _('New')
        return super().create(vals_list)

    def action_activate(self):
        for rec in self:
            rec.status = 'active'
            rec.message_post(body=_('Course %s activated.') % rec.name)

    def action_suspend(self):
        for rec in self:
            rec.status = 'suspended'
            rec.message_post(body=_('Course %s suspended.') % rec.name)

    def action_retire(self):
        for rec in self:
            rec.status = 'retired'
            rec.message_post(body=_('Course %s retired.') % rec.name)

    def _require_manager(self):
        if not (self.env.su or self.env.user.has_group('employee_development_system.group_eds_manager')
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('This step requires L&D Manager authority ().'))


class EdsCourseCompetencyLine(models.Model):
    """Course -> competency mapping with target proficiency level and behavioral indicators."""
    _name = 'eds.course.competency.line'
    _description = 'Course Competency Mapping Line'
    _order = 'course_id, competency_id'

    course_id = fields.Many2one('eds.course', string='Course', required=True, ondelete='cascade')
    competency_id = fields.Many2one(
        'competency.competency', string='Competency', required=True, ondelete='cascade')
    competency_code = fields.Char(related='competency_id.code', string='Code', readonly=True)
    competency_pillar = fields.Selection(
        related='competency_id.pillar', string='Pillar', store=True, readonly=True)
    required_level = fields.Selection([
        ('1', 'Level 1 - Basic'),
        ('2', 'Level 2 - Intermediate'),
        ('3', 'Level 3 - Advanced'),
        ('4', 'Level 4 - Expert'),
    ], string='Target Proficiency Level', default='3', required=True,
        help='Proficiency standard participants will achieve upon successfully completing this course.')
    weight_pct = fields.Float(string='Weight in Course (%)', default=100.0)
    level_definition = fields.Text(string='Level Definition', compute='_compute_level_indicators', store=True)
    behavioral_indicators = fields.Text(
        string='Demonstrated Behavioral Indicators', compute='_compute_level_indicators', store=True,
        help='Behavioral outcomes expected from the official Bunna Bank Competency Framework for this proficiency level.')
    notes = fields.Text(string='Learning Focus / Module Scope')

    @api.constrains('course_id', 'competency_id')
    def _check_unique_course_competency(self):
        for rec in self:
            if rec.course_id and rec.competency_id:
                domain = [('course_id', '=', rec.course_id.id), ('competency_id', '=', rec.competency_id.id), ('id', '!=', rec.id)]
                if self.search_count(domain) > 0:
                    raise ValidationError(_("The competency '%s' is already mapped to this course.") % rec.competency_id.name)

    @api.depends('competency_id', 'required_level')
    def _compute_level_indicators(self):
        for rec in self:
            if rec.competency_id and rec.required_level:
                prof_level = self.env['competency.proficiency.level'].search([
                    ('competency_id', '=', rec.competency_id.id),
                    ('level', '=', rec.required_level)
                ], limit=1)
                if prof_level:
                    rec.level_definition = prof_level.definition or ''
                    rec.behavioral_indicators = prof_level.behavioral_indicators or ''
                else:
                    rec.level_definition = ''
                    rec.behavioral_indicators = ''
            else:
                rec.level_definition = ''
                rec.behavioral_indicators = ''


class EdsCourseDevelopmentRequest(models.Model):
    """Request to develop a course from approved TNA needs (-014, ).

    Converted from approved TNA entries; carries an SLA deadline computed from the
    configurable working-day SLA (default 10 working days, ). On approval the
    request converts to an `eds.course` with competency mapping lines ().
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
        help='Created when the request is approved and converted ().')
    assigned_officer_id = fields.Many2one(
        'res.users', string='Assigned Officer',
        default=lambda self: self.env.user, tracking=True)
    competency_gap_ids = fields.Many2many(
        'competency.competency', string='Competency Gaps',
        help='Competencies to be covered, derived from the TNA needs ().')
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
        help='Computed from the course development SLA in settings (default 10 working days, ).')
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

    # ── Workflow (/013/014) ──────────────────────────────────────────
    def action_start_development(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft requests can start development.'))
            rec.state = 'in_development'
            rec.message_post(body=_('Development of %s started. SLA deadline: %s ().')
                             % (rec.name, rec.sla_deadline))

    def action_submit(self):
        for rec in self:
            if rec.state != 'in_development':
                raise UserError(_('Only requests in development can be submitted.'))
            if not rec.expected_outcomes:
                raise UserError(_('Expected learning outcomes are required before submission.'))
            rec.state = 'submitted'
            rec.message_post(body=_('Development request %s submitted for approval ().')
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
        """Approved -> Done: create the `eds.course` with competency mapping (/012)."""
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
            body=_('Course %s created from development request %s ().') % (course.code, self.name))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'eds.course',
            'res_id': course.id,
            'view_mode': 'form',
        }

    # ── SLA escalation () ────────────────────────────────────────────
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
                body=_('SLA BREACHED (): Development request %s missed its SLA deadline of %s. '
                       'Notify the L&D Team Leader for escalation.') % (req.name, req.sla_deadline),
                partner_ids=partner_ids)
            req.last_reminder_date = today
        return True

    def _require_manager(self):
        if not (self.env.su or self.env.user.has_group('employee_development_system.group_eds_manager')
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('This step requires L&D Manager authority ().'))
