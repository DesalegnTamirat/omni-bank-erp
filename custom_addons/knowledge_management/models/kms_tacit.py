# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class KmsKnowledgeSession(models.Model):
    """
    Knowledge Capture Sessions (FR-KMS-029).
    Schedules and captures expert interviews, exit debriefs, and project retrospectives
    to systematically convert undocumented tacit expertise into permanent organizational knowledge.
    """
    _name = 'kms.knowledge.session'
    _description = 'Knowledge Capture Session'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'session_date desc, id desc'

    name = fields.Char(string='Session Title', required=True, tracking=True)
    cop_id = fields.Many2one('kms.cop', string='Community of Practice Space', tracking=True)
    session_type = fields.Selection([
        ('expert_interview', 'Subject Matter Expert (SME) Interview'),
        ('exit_debrief', 'Staff Exit / Transfer Knowledge Handover'),
        ('project_retro', 'Project / Incident Retrospective'),
        ('brown_bag', 'Brown-Bag / Tech Talk Session'),
        ('masterclass', 'Internal Masterclass / Case Clinic'),
    ], string='Session Format', required=True, default='expert_interview', tracking=True)

    expert_id = fields.Many2one('hr.employee', string='Knowledge Sharer / Expert', required=True, tracking=True)
    facilitator_id = fields.Many2one('hr.employee', string='Facilitator / Interviewer', tracking=True)
    attendee_ids = fields.Many2many(
        'hr.employee',
        'kms_session_attendee_rel',
        'session_id',
        'employee_id',
        string='Attendees / Participants'
    )

    session_date = fields.Datetime(string='Session Date & Time', default=fields.Datetime.now, required=True, tracking=True)
    duration_hours = fields.Float(string='Duration (Hours)', default=1.0)
    location = fields.Char(string='Venue / Meeting Link', default='Bunna HQ Learning Room / Teams')

    summary = fields.Html(string='Executive Brief & Context', required=True)
    key_takeaways = fields.Html(string='Tacit Insights & Core Know-How Captured', required=True)
    action_items = fields.Html(string='Recommended Institutional Action Items')
    recording_url = fields.Char(string='Internal Media / Recording Stream Link')

    state = fields.Selection([
        ('planned', 'Scheduled / Planned'),
        ('completed', 'Completed & Documented'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='planned', tracking=True)

    attachment_ids = fields.Many2many(
        'ir.attachment',
        'kms_session_attachment_rel',
        'session_id',
        'attachment_id',
        string='Artifacts & Slides'
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super(KmsKnowledgeSession, self).create(vals_list)
        for rec in records:
            try:
                self.env['kms.audit.log'].log_audit_event(
                    action='upload',
                    resource_type='tacit_session',
                    resource_name=rec.name,
                    details=f"Created knowledge capture session '{rec.name}' ({rec.session_type})"
                )
            except Exception:
                pass
        return records

    def action_complete_session(self):
        for rec in self:
            rec.write({'state': 'completed'})
            rec.message_post(body=_('Knowledge capture session completed and tacit insights documented.'))
            try:
                self.env['kms.audit.log'].log_audit_event(
                    action='approve',
                    resource_type='tacit_session',
                    resource_name=rec.name,
                    details=f"Completed knowledge capture session '{rec.name}'"
                )
            except Exception:
                pass
            # Award points to expert and facilitator
            if rec.expert_id and rec.expert_id.user_id:
                self.env['kms.contributor.point'].award_points(
                    rec.expert_id.user_id,
                    points=15,
                    source='session_delivery',
                    description=f'Delivered tacit knowledge session: {rec.name}'
                )


class KmsLessonLearned(models.Model):
    """
    Lessons Learned Repository (FR-KMS-030).
    Structured repository capturing project/incident reviews, root-cause analyses,
    operational challenges, and reusable mitigation recommendations.
    """
    _name = 'kms.lesson.learned'
    _description = 'Lesson Learned'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(string='Lesson Title', required=True, tracking=True)
    code = fields.Char(string='Reference Code', readonly=True, copy=False, default=lambda self: _('New'))
    cop_id = fields.Many2one('kms.cop', string='Related Community of Practice')
    category_id = fields.Many2one('kms.category', string='Operational Category', required=True, tracking=True)
    tag_ids = fields.Many2many('kms.tag', string='Tags')

    project_initiative = fields.Char(string='Project / Initiative / Incident Name', required=True, tracking=True)
    department_id = fields.Many2one('hr.department', string='Originating Department', tracking=True)
    operating_unit_id = fields.Many2one('operating.unit', string='Operating Unit / Branch')
    author_id = fields.Many2one(
        'hr.employee',
        string='Documented By',
        required=True,
        default=lambda self: self.env.user.employee_id,
        tracking=True
    )
    incident_date = fields.Date(string='Event / Incident Date', default=fields.Date.context_today)

    severity_impact = fields.Selection([
        ('low', 'Low / Informational'),
        ('medium', 'Medium / Process Bottleneck'),
        ('high', 'High / Operational Risk'),
        ('critical', 'Critical / Compliance or Financial Impact'),
    ], string='Impact Severity', default='medium', required=True, tracking=True)

    event_summary = fields.Text(string='Incident / Activity Overview', required=True)
    root_cause = fields.Text(string='Root Cause Analysis (Why it happened)', required=True)
    what_went_well = fields.Text(string='Positive Takeaways & What Went Well')
    challenges_faced = fields.Text(string='Challenges & Roadblocks Encountered')
    key_lesson = fields.Html(string='Institutional Lesson Learned', required=True)
    mitigation_recommendation = fields.Html(string='Preventive / Corrective Recommendations', required=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('reviewed', 'Validated & Approved'),
        ('archived', 'Archived'),
    ], string='Status', default='draft', tracking=True, index=True)

    vote_ids = fields.One2many('kms.lesson.learned.vote', 'lesson_id', string='Votes')
    helpful_votes = fields.Integer(string='Helpful Votes', compute='_compute_helpful_votes', store=True)

    @api.depends('vote_ids')
    def _compute_helpful_votes(self):
        for rec in self:
            rec.helpful_votes = len(rec.vote_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code', _('New')) == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('kms.lesson.learned') or _('New')
        records = super(KmsLessonLearned, self).create(vals_list)
        for rec in records:
            try:
                self.env['kms.audit.log'].log_audit_event(
                    action='upload',
                    resource_type='lesson_learned',
                    resource_name=f"{rec.code} - {rec.name}",
                    details=f"Documented lesson learned '{rec.name}' for {rec.project_initiative}"
                )
            except Exception:
                pass
        return records

    def action_approve(self):
        for rec in self:
            rec.write({'state': 'reviewed'})
            rec.message_post(body=_('Lesson learned validated and published to the bank repository.'))
            try:
                self.env['kms.audit.log'].log_audit_event(
                    action='approve',
                    resource_type='lesson_learned',
                    resource_name=f"{rec.code} - {rec.name}",
                    details=f"Validated and approved lesson learned '{rec.name}'"
                )
            except Exception:
                pass
            if rec.author_id and rec.author_id.user_id:
                self.env['kms.contributor.point'].award_points(
                    rec.author_id.user_id,
                    points=10,
                    source='lesson_learned',
                    description=f'Contributed validated lesson learned: {rec.name} ({rec.code})'
                )

    def action_vote_helpful(self):
        Vote = self.env['kms.lesson.learned.vote']
        for rec in self:
            existing = Vote.search([('lesson_id', '=', rec.id), ('user_id', '=', self.env.uid)], limit=1)
            if existing:
                existing.unlink()
            else:
                Vote.create({
                    'lesson_id': rec.id,
                    'user_id': self.env.uid,
                })
                try:
                    self.env['kms.audit.log'].log_audit_event(
                        action='modify',
                        resource_type='lesson_learned',
                        resource_name=f"{rec.code} - {rec.name}",
                        details=f"Voted helpful on lesson learned '{rec.name}'"
                    )
                except Exception:
                    pass


class KmsLessonLearnedVote(models.Model):
    """Vote record preventing multiple votes on a lesson learned entry by the same user (FR-KMS-030)."""
    _name = 'kms.lesson.learned.vote'
    _description = 'Lesson Learned Helpful Vote'

    lesson_id = fields.Many2one('kms.lesson.learned', string='Lesson Learned', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', string='User', required=True, ondelete='cascade', default=lambda self: self.env.user, index=True)

    _unique_lesson_user = models.Constraint(
        'unique(lesson_id, user_id)',
        'A user can only vote once per lesson learned entry!',
    )


class KmsMentoringTrack(models.Model):
    """
    Mentoring & Knowledge Transfer Tracking (FR-KMS-031).
    Tracks bilateral knowledge transfer pairings between experienced mentors and newer staff,
    including knowledge transfer roadmaps, meeting milestones, and final completion sign-off.
    """
    _name = 'kms.mentoring.track'
    _description = 'Mentoring & Knowledge Transfer Tracking'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_date desc'

    name = fields.Char(string='Track Title', required=True, tracking=True)
    mentor_id = fields.Many2one('hr.employee', string='Designated Mentor (Expert)', required=True, tracking=True)
    mentee_id = fields.Many2one('hr.employee', string='Mentee (Knowledge Recipient)', required=True, tracking=True)
    department_id = fields.Many2one('hr.department', string='Department')

    transfer_focus = fields.Text(string='Knowledge Transfer Objectives & Domain Focus', required=True)
    start_date = fields.Date(string='Program Start Date', default=fields.Date.context_today, required=True)
    target_end_date = fields.Date(string='Target Completion Date', required=True)
    actual_end_date = fields.Date(string='Actual Completion Date', readonly=True)

    state = fields.Selection([
        ('draft', 'Planned / Agreement Draft'),
        ('in_progress', 'Active Mentoring Cycle'),
        ('completed', 'Knowledge Handover Completed'),
        ('terminated', 'Early Terminated'),
    ], string='Status', default='draft', tracking=True)

    milestone_ids = fields.One2many('kms.mentoring.milestone', 'mentoring_id', string='Transfer Milestones')
    overall_evaluation = fields.Text(string='Final Mentor Evaluation & Handover Sign-off')

    def action_start(self):
        self.write({'state': 'in_progress'})

    def action_complete(self):
        for rec in self:
            rec.write({
                'state': 'completed',
                'actual_end_date': fields.Date.context_today(self),
            })
            rec.message_post(body=_('Mentoring and knowledge transfer cycle successfully concluded and signed off.'))
            if rec.mentor_id and rec.mentor_id.user_id:
                self.env['kms.contributor.point'].award_points(
                    rec.mentor_id.user_id,
                    points=25,
                    source='mentoring_signoff',
                    description=f'Completed knowledge transfer mentoring for {rec.mentee_id.name}'
                )


class KmsMentoringMilestone(models.Model):
    _name = 'kms.mentoring.milestone'
    _description = 'Mentoring Transfer Milestone'
    _order = 'target_date asc'

    mentoring_id = fields.Many2one('kms.mentoring.track', string='Mentoring Plan', required=True, ondelete='cascade')
    name = fields.Char(string='Milestone Topic / Goal', required=True)
    target_date = fields.Date(string='Target Date', required=True)
    completion_date = fields.Date(string='Date Completed')
    is_achieved = fields.Boolean(string='Achieved & Verified', default=False)
    notes = fields.Text(string='Meeting Notes / Verification Evidence')
