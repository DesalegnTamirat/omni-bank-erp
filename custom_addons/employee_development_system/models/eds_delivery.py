# -*- coding: utf-8 -*-
"""Task 7 - Attendance & Delivery Tracking (/041/045, ...045).

Delivery-time models consumed by the trainer and L&D officer:
  - eds.session.attendance   per-participant attendance with computed per-program %
                             (feeds the 80% certification rule, Task 10)
  - eds.material             course training material with quality review +
                             Director PPDD approval gate ()
  - eds.feedback             daily participant feedback lines ()
  - eds.assessment           pre/post assessment scores (shared with Task 8 L1/L2)
  - eds.international.training + .travel.line / .report   international flow with
                             entitlement validation (service years) and travel
                             arrangements ()
"""
from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class EdsSessionAttendance(models.Model):
    """Per-participant attendance on a session ().

    `attendance_percentage` is computed *per program* (all sessions of the same
    course) so it feeds directly into the certification eligibility rule
    (default >= 80%, Task 10). Immutable after recording: the model is wired into
    the `audit_trail` module (data/eds_audit_rules.xml) so any later edit is
    logged with user / old value / new value (business rule §6).
    """
    _name = 'eds.session.attendance'
    _description = 'Session Attendance Record'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'session_id, employee_id'
    _rec_name = 'name'

    _track_audit = True  # documented intent; enforced via audit.rule in data/

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    session_id = fields.Many2one('eds.session', string='Session', required=True,
                                 ondelete='cascade', index=True, tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Participant', required=True,
                                  tracking=True)
    job_position_id = fields.Many2one('hr.job', string='Job Position',
                                      related='employee_id.job_position', readonly=True)
    department_id = fields.Many2one('hr.department', string='Department',
                                    related='employee_id.department_id', readonly=True)
    attendance_date = fields.Date(string='Attendance Date', default=fields.Date.context_today)
    attended = fields.Boolean(string='Attended', default=True, tracking=True)
    hours_attended = fields.Float(string='Hours Attended', default=0.0)
    notes = fields.Text(string='Notes')
    recorded_by = fields.Many2one('res.users', string='Recorded By',
                                  default=lambda self: self.env.user, readonly=True,
                                  copy=False)
    attendance_percentage = fields.Float(
        string='Program Attendance %', compute='_compute_program_attendance', store=True,
        digits=(5, 2),
        help='Attended sessions / total sessions of this program for the participant '
             '().')
    meets_min_attendance = fields.Boolean(
        string='Meets Minimum Attendance', compute='_compute_program_attendance', store=True,
        help='True when the program attendance % is >= the configurable threshold '
             '(default 80%, ) - feeds certification eligibility (Task 10).')
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)

    _session_employee_uniq = models.Constraint(
        'UNIQUE(session_id, employee_id)',
        'Attendance is already recorded for this participant on this session!',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.session.attendance') or _('New')
        return super().create(vals_list)

    @api.depends('session_id.course_id', 'employee_id', 'attended')
    def _compute_program_attendance(self):
        """Program (course) attendance % across all its sessions ().

        Total = attendance records of the participant on any session of the same
        course; attended = the subset marked as attended. A participant with no
        records yet computes 0% until a session is recorded.
        """
        for rec in self:
            course = rec.session_id.course_id
            if not course or not rec.employee_id:
                rec.attendance_percentage = 0.0
                rec.meets_min_attendance = False
                continue
            records = self.search([
                ('employee_id', '=', rec.employee_id.id),
                ('session_id.course_id', '=', course.id),
            ])
            total = len(records)
            attended = len(records.filtered('attended'))
            rec.attendance_percentage = round(attended * 100.0 / total, 2) if total else 0.0
            threshold = rec._get_float_param('eds.min_attendance_pct', 80.0)
            rec.meets_min_attendance = bool(total) and rec.attendance_percentage >= threshold

    @api.model
    def _get_float_param(self, key, default):
        try:
            return float(self.env['ir.config_parameter'].sudo().get_param(key, str(default)))
        except ValueError:
            return default


class EdsMaterial(models.Model):
    """Training material with quality review + Director PPDD approval ().

    A session whose course has materials cannot be confirmed until at least one
    material version is approved - enforced on `eds.session.action_confirm`.
    """
    _name = 'eds.material'
    _description = 'Training Material'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'course_id, id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    course_id = fields.Many2one('eds.course', string='Training Program', required=True,
                                ondelete='cascade', index=True, tracking=True)
    title = fields.Char(string='Material Title', required=True, tracking=True)
    material_type = fields.Selection([
        ('manual', 'Training Manual'),
        ('presentation', 'Presentation / Slides'),
        ('handout', 'Handout'),
        ('video', 'Video / E-Learning'),
        ('case_study', 'Case Study'),
        ('examination', 'Examination / Assessment'),
        ('other', 'Other'),
    ], string='Material Type', default='manual', tracking=True)
    version = fields.Char(string='Version', default='v1.0', tracking=True)
    document = fields.Binary(string='Document')
    filename = fields.Char(string='Filename')
    description = fields.Text(string='Description')

    # Two-stage gate (): L&D quality review first, then Director PPDD.
    quality_state = fields.Selection([
        ('draft', 'Draft'),
        ('in_review', 'In Quality Review'),
        ('quality_approved', 'Quality Approved'),
        ('rejected', 'Rejected'),
    ], string='Quality Review', default='draft', required=True, tracking=True)
    approval_state = fields.Selection([
        ('not_required', 'Approval Not Required'),
        ('pending', 'Pending Submission'),
        ('submitted', 'Submitted - Director PPDD'),
        ('director_approved', 'Director PPDD Approved'),
        ('rejected', 'Rejected'),
    ], string='Director Approval', default='not_required', required=True, tracking=True)
    is_approved = fields.Boolean(
        string='Approved', compute='_compute_is_approved', store=True,
        help='True when the quality review passed and (if submitted) the Director '
             'PPDD approval is granted - the session confirmation gate ().')

    reviewed_by = fields.Many2one('res.users', string='Quality Reviewed By', readonly=True)
    reviewed_date = fields.Date(string='Quality Review Date', readonly=True)
    approved_by = fields.Many2one('res.users', string='Director Approved By', readonly=True)
    approved_date = fields.Date(string='Director Approval Date', readonly=True)
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)

    @api.depends('quality_state', 'approval_state')
    def _compute_is_approved(self):
        for rec in self:
            rec.is_approved = bool(
                rec.quality_state == 'quality_approved'
                and rec.approval_state in ('not_required', 'director_approved'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.material') or _('New')
        return super().create(vals_list)

    def _require_group(self, group_xml_id):
        if not (self.env.su or self.env.user.has_group('employee_development_system.' + group_xml_id)):
            raise UserError(_('You do not have the required authority for this step.'))

    def action_submit_quality_review(self):
        """Draft -> In Quality Review (L&D quality check)."""
        for rec in self:
            if rec.quality_state != 'draft':
                raise UserError(_('Only draft materials can be submitted to quality review.'))
            if not rec.document:
                raise UserError(_('Attach the material document before submitting it for '
                                  'quality review.'))
            rec.quality_state = 'in_review'
            rec.message_post(body=_('Material %s submitted for quality review ().')
                             % rec.title)

    def action_approve_quality(self):
        """In Review -> Quality Approved (L&D Manager / Admin)."""
        for rec in self:
            rec._require_group('group_eds_manager')
            if rec.quality_state != 'in_review':
                raise UserError(_('Only materials in quality review can be quality-approved.'))
            rec.write({'quality_state': 'quality_approved',
                       'reviewed_by': self.env.user.id,
                       'reviewed_date': date.today()})
            rec.message_post(body=_('Material %s passed the quality review ().')
                             % rec.title)

    def action_submit_director_approval(self):
        """Quality Approved -> Submitted to Director PPDD ()."""
        for rec in self:
            if rec.quality_state != 'quality_approved':
                raise UserError(_('Approve the quality review before the Director PPDD step '
                                  '().'))
            if rec.approval_state == 'director_approved':
                continue
            rec.approval_state = 'submitted'
            rec.message_post(body=_('Material %s submitted for Director PPDD approval '
                                    '().') % rec.title)

    def action_director_approve(self):
        """Submitted -> Director PPDD Approved (L&D Manager / Admin)."""
        for rec in self:
            rec._require_group('group_eds_manager')
            if rec.approval_state != 'submitted':
                raise UserError(_('Only materials submitted to the Director PPDD can be '
                                  'finally approved.'))
            rec.write({'approval_state': 'director_approved',
                       'approved_by': self.env.user.id,
                       'approved_date': date.today()})
            rec.message_post(body=_('Material %s approved by Director PPDD - session '
                                    'confirmation gate released ().') % rec.title)

    def action_reject(self):
        """Reject at any pre-approval stage (mandatory feedback in chatter)."""
        for rec in self:
            if rec.quality_state == 'rejected' or rec.approval_state == 'rejected':
                raise UserError(_('This material is already rejected.'))
            if rec.quality_state == 'in_review':
                rec.quality_state = 'rejected'
            elif rec.approval_state == 'submitted':
                rec.approval_state = 'rejected'
            else:
                raise UserError(_('Only materials under review can be rejected.'))
            rec.message_post(body=_('Material %s was rejected ().') % rec.title)


class EdsFeedback(models.Model):
    """Daily participant feedback line captured during delivery ()."""
    _name = 'eds.feedback'
    _description = 'Daily Participant Feedback'
    _order = 'feedback_date desc, id desc'
    _rec_name = 'id'

    session_id = fields.Many2one('eds.session', string='Session', required=True,
                                 ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', string='Participant', required=True)
    feedback_date = fields.Date(string='Date', default=fields.Date.context_today)
    day_number = fields.Integer(string='Day')
    trainer_id = fields.Many2one('eds.trainer', string='Trainer / Facilitator')
    rating = fields.Selection([
        ('1', '1 - Poor'),
        ('2', '2 - Fair'),
        ('3', '3 - Good'),
        ('4', '4 - Very Good'),
        ('5', '5 - Excellent'),
    ], string='Rating', required=True)
    topic = fields.Char(string='Topic / Content Covered')
    comment = fields.Text(string='Comment')
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)

    @api.constrains('day_number')
    def _check_day_number(self):
        for rec in self:
            if rec.day_number and rec.day_number < 1:
                raise ValidationError(_('The training day number must be positive.'))


class EdsAssessment(models.Model):
    """Pre/post training assessment score (, ).

    Single model shared by delivery (Task 7) and the Level-2 evaluation engine
    (Task 8): `eds.evaluation.level2` links pre/post records through this model
    and computes the learning gain. `passed` compares the score against the
    configurable threshold (default 60%, ).
    """
    _name = 'eds.assessment'
    _description = 'Pre / Post Training Assessment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'session_id, employee_id, assessment_type'
    _rec_name = 'id'

    _track_audit = True  # documented intent; enforced via audit.rule in data/

    session_id = fields.Many2one('eds.session', string='Session', required=True,
                                 ondelete='cascade', index=True, tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Participant', required=True,
                                  tracking=True)
    assessment_type = fields.Selection([
        ('pre', 'Pre-Training Assessment'),
        ('post', 'Post-Training Assessment'),
        ('skills_test', 'Practical Skills Test'),
    ], string='Assessment Type', default='pre', required=True, tracking=True)
    score = fields.Float(string='Score (0-100)', digits=(5, 2), tracking=True)
    passed = fields.Boolean(string='Passed', compute='_compute_passed', store=True,
                            help='Score >= the configurable Level-2 pass threshold '
                                 '(default 60%, ).')
    threshold = fields.Float(string='Pass Threshold %', compute='_compute_passed', store=True)
    assessment_date = fields.Date(string='Assessment Date', default=fields.Date.context_today)
    uploaded_by = fields.Many2one('res.users', string='Uploaded By',
                                  default=lambda self: self.env.user, readonly=True,
                                  help='External trainers may upload scores '
                                       '(/037).')
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)

    _session_employee_type_uniq = models.Constraint(
        'UNIQUE(session_id, employee_id, assessment_type)',
        'This participant already has an assessment of this type for the session!',
    )
    _score_range = models.Constraint(
        'CHECK(score >= 0 AND score <= 100)',
        'The assessment score must be between 0 and 100!',
    )

    @api.depends('score')
    def _compute_passed(self):
        threshold = self._get_float_param('eds.level2_pass_threshold', 60.0)
        for rec in self:
            rec.threshold = threshold
            rec.passed = bool(rec.score and rec.score >= threshold)

    @api.model
    def _get_float_param(self, key, default):
        try:
            return float(self.env['ir.config_parameter'].sudo().get_param(key, str(default)))
        except ValueError:
            return default


class EdsInternationalTraining(models.Model):
    """International training facilitation ().

    Lightweight workflow covering entitlement validation (minimum service months),
    travel/per-diem arrangements, post-training reports and knowledge sharing.
    Per the plan this is the stretch-scope piece of Task 7 - implemented as a
    simple state machine + attachment lines, not a full travel module.
    """
    _name = 'eds.international.training'
    _description = 'International Training'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    session_id = fields.Many2one('eds.session', string='Session', required=True,
                                 ondelete='cascade', index=True, tracking=True)
    program_name = fields.Char(string='Program', related='session_id.program_name',
                               readonly=True)
    country = fields.Char(string='Host Country', tracking=True)
    institution = fields.Char(string='Host Institution / Provider', tracking=True)
    description = fields.Text(string='Scope / Objective')
    cost_estimate = fields.Monetary(string='Estimated Cost', tracking=True)
    currency_id = fields.Many2one('res.currency', string='Currency',
                                  default=lambda self: self.env.company.currency_id)
    approval_state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('completed', 'Completed'),
    ], string='Status', default='draft', required=True, tracking=True)
    approved_by = fields.Many2one('res.users', string='Approved By', readonly=True)
    approved_date = fields.Date(string='Approval Date', readonly=True)

    # Entitlement validation ( service-years rule reused for international).
    # Stored `entitlement_valid` and non-stored `entitlement_issues` use separate
    # compute methods to keep the store flags consistent for the ORM recomputation.
    entitlement_valid = fields.Boolean(
        string='Entitlement Valid', compute='_compute_entitlement_valid', store=True,
        help='All enrolled participants meet the minimum service requirement.')
    entitlement_issues = fields.Text(
        string='Entitlement Issues', compute='_compute_entitlement_issues')

    travel_arrangements_ids = fields.One2many(
        'eds.international.travel.line', 'training_id', string='Travel Arrangements',
        help='Visa, insurance, flight, per-diem, accommodation and authorization lines.')
    travel_total = fields.Monetary(
        string='Travel Arrangements Total', compute='_compute_travel_total', store=True,
        currency_field='currency_id')
    reports_ids = fields.One2many(
        'eds.international.report', 'training_id', string='Reports & Knowledge Sharing')
    post_training_report_count = fields.Integer(
        string='Post-Training Reports', compute='_compute_report_counts')
    knowledge_sharing_count = fields.Integer(string='Knowledge Sharing Records',
                                             compute='_compute_report_counts')
    workplace_application_tracking = fields.Text(
        string='Workplace Application Tracking',
        help='How the participant applies the new skills at the workplace ().')
    workplace_application_completed = fields.Boolean(string='Application Verified')
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)

    def _get_entitlement_issues(self):
        """Every enrolled participant must meet the minimum service period.

        Uses `hr.employee.service_start_date` (falling back to `service_hire_date`).
        Returns a human-readable issue list (or False when all enrolled qualify).
        """
        self.ensure_one()
        min_months = self._get_int_param('eds.sponsorship_min_service_months', 12)
        today = date.today()
        if not self.session_id:
            return _('No session linked.')
        enrolled = self.session_id.enrollment_ids.filtered(lambda e: e.state == 'enrolled')
        issues = []
        for enrollment in enrolled:
            employee = enrollment.employee_id.sudo()
            start = employee.service_start_date or employee.service_hire_date
            if not start:
                issues.append(_('%s: no service start date recorded.') % employee.name)
                continue
            months = (today - start).days / 30.0
            if months < min_months:
                issues.append(_('%s: only %.0f month(s) of service (minimum %s).')
                              % (employee.name, months, min_months))
        return '\n'.join(issues) if issues else False

    @api.depends('session_id', 'session_id.enrollment_ids',
                 'session_id.enrollment_ids.state')
    def _compute_entitlement_valid(self):
        for rec in self:
            rec.entitlement_valid = not bool(rec._get_entitlement_issues())

    @api.depends('session_id', 'session_id.enrollment_ids',
                 'session_id.enrollment_ids.state')
    def _compute_entitlement_issues(self):
        for rec in self:
            rec.entitlement_issues = rec._get_entitlement_issues()

    @api.depends('travel_arrangements_ids', 'travel_arrangements_ids.amount')
    def _compute_travel_total(self):
        for rec in self:
            rec.travel_total = sum(rec.travel_arrangements_ids.mapped('amount'))

    @api.depends('reports_ids', 'reports_ids.report_type')
    def _compute_report_counts(self):
        for rec in self:
            rec.post_training_report_count = len(
                rec.reports_ids.filtered(lambda r: r.report_type == 'post_training'))
            rec.knowledge_sharing_count = len(
                rec.reports_ids.filtered(lambda r: r.report_type == 'knowledge_sharing'))

    @api.model
    def _get_int_param(self, key, default):
        try:
            return int(self.env['ir.config_parameter'].sudo().get_param(key, str(default)))
        except ValueError:
            return default

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.international.training') or _('New')
        return super().create(vals_list)

    def _require_manager(self):
        if not (self.env.su or self.env.user.has_group('employee_development_system.group_eds_manager')
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('This step requires L&D Manager authority.'))

    def action_submit(self):
        """Draft -> Submitted: enforce entitlement before the approval chain ()."""
        for rec in self:
            if rec.approval_state != 'draft':
                raise UserError(_('Only draft international trainings can be submitted.'))
            if not rec.entitlement_valid:
                raise UserError(_('Entitlement validation failed ():\n%s')
                                % (rec.entitlement_issues or _('No enrolled participants.')))
            rec.approval_state = 'submitted'
            rec.message_post(body=_('International training %s submitted for approval '
                                    '().') % rec.name)

    def action_approve(self):
        """Submitted -> Approved (L&D Manager / Admin)."""
        for rec in self:
            rec._require_manager()
            if rec.approval_state != 'submitted':
                raise UserError(_('Only submitted international trainings can be approved.'))
            rec.write({'approval_state': 'approved',
                       'approved_by': self.env.user.id,
                       'approved_date': date.today()})
            rec.message_post(body=_('International training %s approved ().') % rec.name)

    def action_complete(self):
        """Approved -> Completed: requires the post-training deliverables ()."""
        for rec in self:
            if rec.approval_state != 'approved':
                raise UserError(_('Only approved international trainings can be completed.'))
            if not rec.reports_ids:
                raise UserError(_('Record at least the post-training report before '
                                  'completing the international training ().'))
            rec.approval_state = 'completed'
            rec.message_post(body=_('International training %s completed - post-training '
                                    'deliverables recorded ().') % rec.name)


class EdsInternationalTravelLine(models.Model):
    """Travel arrangement line: visa, insurance, flight, per-diem, authorization."""
    _name = 'eds.international.travel.line'
    _description = 'International Travel Arrangement'
    _order = 'training_id, id'

    training_id = fields.Many2one('eds.international.training', string='International Training',
                                  required=True, ondelete='cascade', index=True)
    arrangement_type = fields.Selection([
        ('visa', 'Visa'),
        ('insurance', 'Travel Insurance'),
        ('flight', 'Flight'),
        ('per_diem', 'Per-Diem'),
        ('accommodation', 'Accommodation'),
        ('authorization', 'Authorization'),
        ('other', 'Other'),
    ], string='Arrangement Type', required=True)
    description = fields.Char(string='Description')
    amount = fields.Monetary(string='Amount', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Currency',
                                  related='training_id.currency_id', readonly=True)
    status = fields.Selection([
        ('planned', 'Planned'),
        ('booked', 'Booked'),
        ('completed', 'Completed'),
    ], string='Status', default='planned')
    attachment = fields.Binary(string='Attachment')
    filename = fields.Char(string='Filename')
    notes = fields.Text(string='Notes')


class EdsInternationalReport(models.Model):
    """Post-training report or knowledge-sharing record ()."""
    _name = 'eds.international.report'
    _description = 'International Training Report / Knowledge Sharing'
    _order = 'report_date desc, id desc'

    training_id = fields.Many2one('eds.international.training', string='International Training',
                                  required=True, ondelete='cascade', index=True)
    report_type = fields.Selection([
        ('post_training', 'Post-Training Report'),
        ('knowledge_sharing', 'Knowledge Sharing'),
    ], string='Type', required=True, default='post_training')
    title = fields.Char(string='Title', required=True)
    report_date = fields.Date(string='Date', default=fields.Date.context_today)
    document = fields.Binary(string='Document')
    filename = fields.Char(string='Filename')
    notes = fields.Text(string='Notes')
