# -*- coding: utf-8 -*-
from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


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
    ], string='Program Category', default='technical_functional', tracking=True)
    target_audience = fields.Selection([
        ('bod', 'BoD (Board of Directors)'),
        ('smc', 'SMC (Senior Management Committee)'),
        ('mlm', 'MLM (Middle Level Management)'),
        ('below_mlm', 'Staff Below MLM'),
        ('all_staff', 'All Staff'),
    ], string='Target Audience Group', default='all_staff', tracking=True)
    delivery_method = fields.Selection([
        ('internal', 'Internal Delivery'),
        ('local_external', 'Local External Provider'),
        ('international', 'International Provider'),
    ], string='Delivery Method', default='internal', tracking=True)
    delivery_place = fields.Selection([
        ('local', 'Local'),
        ('international', 'International'),
    ], string='Delivery Place', default='local', tracking=True)
    duration_days = fields.Integer(string='Duration (Days)', default=1, tracking=True)
    schedule = fields.Selection([
        ('annual', 'Annual (Once a Year)'),
        ('semi_annual', 'Semi-Annual (Twice a Year)'),
        ('quarterly', 'Quarterly (Every 3 Months)'),
        ('monthly', 'Monthly'),
        ('on_demand', 'On-Demand / As Needed'),
        ('continuous', 'Continuous / Rolling'),
    ], string='Schedule / Frequency', default='annual', tracking=True,
       help='Planned operational cadence or frequency of conducting this course.')
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
    department_ids = fields.Many2many(
        'hr.department', 'eds_course_department_rel', 'course_id', 'department_id',
        string='Target Departments', help='Leave empty if course applies to all departments.')
    operating_unit_ids = fields.Many2many(
        'operating.unit', 'eds_course_operating_unit_rel', 'course_id', 'operating_unit_id',
        string='Target Operating Units / Branches', help='Leave empty if course applies to all operating units.')
    target_audience_ids = fields.Many2many(
        'hr.job', string='Target Job Positions',
        help='Leave empty if course applies to all job positions.')
    target_scope = fields.Selection([
        ('all', 'Bank-Wide (All Employees)'),
        ('targeted', 'Targeted Scope'),
    ], string='Target Scope', compute='_compute_target_scope', store=True)

    # Customizable Certificate Template Fields
    certificate_title = fields.Char(string='Certificate Title', default='Certificate of Completion')
    certificate_body_text = fields.Text(
        string='Certificate Body Content',
        default="This is to certify that {employee_name} has successfully completed the training program '{course_name}' with satisfactory attendance and evaluation performance.")
    certificate_signatory_name = fields.Char(string='Authorized Signatory Name')
    certificate_signatory_title = fields.Char(string='Authorized Signatory Title', default='Director - People Performance & Development')

    # Linked Evaluation & Assessment Instruments
    level1_instrument_id = fields.Many2one(
        'eds.evaluation.instrument', string='Level 1 Reaction Questionnaire',
        domain="[('instrument_type', '=', 'level1')]")
    level2_instrument_id = fields.Many2one(
        'eds.evaluation.instrument', string='Level 2 Assessment Questionnaire',
        domain="[('instrument_type', '=', 'level2')]")
    level3_instrument_id = fields.Many2one(
        'eds.evaluation.instrument', string='Level 3 Behavioral Questionnaire',
        domain="[('instrument_type', '=', 'level3')]")

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

    @api.depends('department_ids', 'operating_unit_ids', 'target_audience_ids')
    def _compute_target_scope(self):
        for rec in self:
            if rec.department_ids or rec.operating_unit_ids or rec.target_audience_ids:
                rec.target_scope = 'targeted'
            else:
                rec.target_scope = 'all'

    def is_applicable_for_employee(self, employee):
        """Check if course applies to the given employee based on unit/dept/job targeting."""
        self.ensure_one()
        if not employee:
            return True
        if self.target_scope == 'all':
            return True
        if self.department_ids and employee.department_id and employee.department_id not in self.department_ids:
            return False
        if self.operating_unit_ids:
            emp_ou = getattr(employee, 'default_operating_unit_id', False)
            if emp_ou and emp_ou not in self.operating_unit_ids:
                return False
        if self.target_audience_ids:
            emp_job = getattr(employee, 'job_position', False) or employee.job_id
            if emp_job and emp_job not in self.target_audience_ids:
                return False
        return True

    @api.onchange('department_ids')
    def _onchange_department_ids(self):
        """Top of hierarchy: Department -> Operating Unit -> Job Position.
        - If department(s) selected:
          Operating units are filtered to only those belonging to the selected department(s).
          Any currently selected operating units not belonging to the department(s) are cleared.
          Target jobs are filtered to those belonging to the selected department(s).
        - If no department selected:
          All operating units are available ([]).
        """
        ou_domain = self.env['eds.hr.compat'].get_operating_unit_domain(departments=self.department_ids)
        if self.department_ids:
            if self.operating_unit_ids and ou_domain:
                valid_ous = self.operating_unit_ids.filtered(
                    lambda u: self.env['eds.hr.compat'].is_operating_unit_in_departments(u, self.department_ids)
                )
                if len(valid_ous) != len(self.operating_unit_ids):
                    self.operating_unit_ids = valid_ous
            job_domain = self.env['eds.hr.compat'].get_job_domain(
                departments=self.department_ids, operating_units=self.operating_unit_ids
            )
            if self.target_audience_ids:
                valid_jobs = self.target_audience_ids.filtered(
                    lambda j: not j.department_id or j.department_id in self.department_ids
                )
                if len(valid_jobs) != len(self.target_audience_ids):
                    self.target_audience_ids = valid_jobs
            return {'domain': {'operating_unit_ids': ou_domain, 'target_audience_ids': job_domain}}
        else:
            job_domain = self.env['eds.hr.compat'].get_job_domain(operating_units=self.operating_unit_ids)
            return {'domain': {'operating_unit_ids': [], 'target_audience_ids': job_domain}}

    @api.onchange('operating_unit_ids')
    def _onchange_operating_unit_ids(self):
        """Middle of hierarchy: Operating Unit -> Job Position.
        Filter target job positions based on selected operating units and departments.
        """
        job_domain = self.env['eds.hr.compat'].get_job_domain(
            departments=self.department_ids, operating_units=self.operating_unit_ids
        )
        return {'domain': {'target_audience_ids': job_domain}}

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
                
                comp_desc = getattr(comp, 'definition', False) or getattr(comp, 'description', False)
                if comp_desc:
                    outcomes_html.append("<p style='margin: 4px 0 8px 0; font-size: 13px; color: #555;'><em>%s</em></p>" % comp_desc)
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

    def action_set_to_draft(self):
        for rec in self:
            rec._require_manager()
            rec.status = 'draft'
            rec.message_post(body=_('Course %s reset to Draft for revision.') % rec.name)

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

    def action_open_indicators(self):
        """Open modal dialog with full competency definition and level behavioral indicators."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Behavioral Indicators & Guidance: %s') % (self.competency_id.name if self.competency_id else ''),
            'res_model': 'eds.course.competency.line',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(self.env.ref('employee_development_system.view_eds_course_competency_line_form').id, 'form')],
            'target': 'new',
        }


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
