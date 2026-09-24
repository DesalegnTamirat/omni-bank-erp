# -*- coding: utf-8 -*-
from datetime import date, datetime
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class LmsEnrollment(models.Model):
    """
    Learner Course Enrollment & Completion Engine (FR-LMS-007 to FR-LMS-012).
    Enforces lesson progression gates, tracks completion percentages, manages certificates,
    and bridges records to core HR employee master data.
    """
    _name = 'lms.enrollment'
    _description = 'Course Enrollment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'enrollment_date desc'

    name = fields.Char(string='Enrollment Reference', compute='_compute_name', store=True)
    employee_id = fields.Many2one('hr.employee', string='Learner / Employee', required=True, tracking=True, index=True)
    user_id = fields.Many2one('res.users', related='employee_id.user_id', string='User Account', readonly=True, store=True)
    department_id = fields.Many2one('hr.department', related='employee_id.department_id', string='Department', store=True, readonly=True)
    operating_unit_id = fields.Many2one('operating.unit', related='employee_id.default_operating_unit_id', string='Branch / Unit', store=True, readonly=True)

    course_id = fields.Many2one('lms.course', string='Course', required=True, tracking=True, index=True)
    assignment_id = fields.Many2one('lms.course.assignment', string='Assignment Campaign', ondelete='set null')

    is_mandatory = fields.Boolean(string='Mandatory', default=False, tracking=True)
    enrollment_date = fields.Date(string='Enrolled Date', default=fields.Date.context_today, required=True)
    due_date = fields.Date(string='Due Date', tracking=True)
    completion_date = fields.Date(string='Completion Date', readonly=True, copy=False)
    is_overdue = fields.Boolean(string='Overdue', compute='_compute_is_overdue', store=True)

    # Progress & Completion Gates (FR-LMS-007, FR-LMS-012)
    state = fields.Selection([
        ('enrolled', 'Enrolled / Not Started'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed & Certified'),
        ('failed', 'Failed Attempts Exceeded'),
    ], string='Status', default='enrolled', tracking=True, required=True, index=True)

    progress_percentage = fields.Float(string='Course Progress (%)', compute='_compute_progress', store=True)
    completed_lessons_count = fields.Integer(string='Completed Lessons Count', compute='_compute_progress', store=True)
    total_lessons_count = fields.Integer(string='Total Lessons', compute='_compute_progress', store=True)

    # Assessment Gates
    pre_assessment_passed = fields.Boolean(string='Pre-Assessment Passed', default=False)
    post_assessment_passed = fields.Boolean(string='Final Assessment Passed', default=False)
    final_score_percentage = fields.Float(string='Final Test Score (%)', readonly=True)

    # Issued Certificate Linkage (FR-LMS-018)
    certificate_id = fields.Many2one('lms.certificate', string='Earned Certificate', readonly=True, copy=False)

    completed_lesson_ids = fields.Many2many(
        'lms.lesson',
        string='Completed Lessons',
        compute='_compute_completed_lessons',
    )
    is_locked = fields.Boolean(
        string='Locked by Prerequisites',
        compute='_compute_is_locked',
    )

    lesson_progress_ids = fields.One2many('lms.lesson.progress', 'enrollment_id', string='Lesson Progress Logs')

    _emp_course_uniq = models.Constraint(
        'UNIQUE(employee_id, course_id)',
        'Employee is already enrolled in this course!'
    )

    @api.depends('employee_id', 'course_id')
    def _compute_name(self):
        for rec in self:
            rec.name = f"{rec.employee_id.name or ''} - {rec.course_id.name or ''}"

    @api.depends('due_date', 'state')
    def _compute_is_overdue(self):
        today = date.today()
        for rec in self:
            rec.is_overdue = bool(rec.due_date and rec.due_date < today and rec.state not in ('completed', 'failed'))

    @api.depends('lesson_progress_ids.state', 'course_id.lesson_ids')
    def _compute_progress(self):
        for rec in self:
            total = len(rec.course_id.lesson_ids)
            rec.total_lessons_count = total
            if total > 0:
                completed = len(rec.lesson_progress_ids.filtered(lambda lp: lp.state == 'completed'))
                rec.completed_lessons_count = completed
                rec.progress_percentage = (completed / float(total)) * 100.0
            else:
                rec.completed_lessons_count = 0
                rec.progress_percentage = 0.0

    @api.depends('lesson_progress_ids.state', 'lesson_progress_ids.lesson_id')
    def _compute_completed_lessons(self):
        for rec in self:
            rec.completed_lesson_ids = rec.lesson_progress_ids.filtered(lambda lp: lp.state == 'completed').mapped('lesson_id')

    @api.depends('employee_id', 'course_id')
    def _compute_is_locked(self):
        for rec in self:
            locked = False
            if rec.employee_id and rec.course_id:
                path = rec.assignment_id.learning_path_id if rec.assignment_id else None
                path_courses = self.env['lms.learning.path.course'].search([('course_id', '=', rec.course_id.id)])
                if path:
                    path_courses = path_courses.filtered(lambda pc: pc.path_id == path)

                for pc in path_courses:
                    # 1. Explicit branched prerequisites (FR-LMS-002)
                    if pc.prerequisite_course_ids:
                        done_prereqs = self.env['lms.enrollment'].search([
                            ('employee_id', '=', rec.employee_id.id),
                            ('course_id', 'in', pc.prerequisite_course_ids.ids),
                            ('state', '=', 'completed'),
                        ]).mapped('course_id')
                        if len(done_prereqs) < len(pc.prerequisite_course_ids):
                            locked = True
                            break

                    # 2. Sequential stage prerequisites (FR-LMS-002)
                    prior_pcs = pc.path_id.path_course_ids.filtered(
                        lambda p: p.sequence < pc.sequence and not p.is_optional_branch and p.course_id != rec.course_id
                    )
                    if prior_pcs:
                        prior_course_ids = prior_pcs.mapped('course_id.id')
                        completed_count = self.env['lms.enrollment'].search_count([
                            ('employee_id', '=', rec.employee_id.id),
                            ('course_id', 'in', prior_course_ids),
                            ('state', '=', 'completed'),
                        ])
                        if completed_count < len(prior_course_ids):
                            enrolled_in_prior = self.env['lms.enrollment'].search_count([
                                ('employee_id', '=', rec.employee_id.id),
                                ('course_id', 'in', prior_course_ids),
                            ])
                            if enrolled_in_prior > 0 or (rec.assignment_id and rec.assignment_id.learning_path_id):
                                locked = True
                                break
            rec.is_locked = locked

    @api.model_create_multi
    def create(self, vals_list):
        records = super(LmsEnrollment, self).create(vals_list)
        for rec in records:
            rec._initialize_lesson_progress()
        return records

    def _initialize_lesson_progress(self):
        """Pre-populates lesson progress entries for each lesson in the course."""
        for rec in self:
            for lesson in rec.course_id.lesson_ids:
                existing = self.env['lms.lesson.progress'].search([
                    ('enrollment_id', '=', rec.id),
                    ('lesson_id', '=', lesson.id)
                ], limit=1)
                if not existing:
                    self.env['lms.lesson.progress'].create({
                        'enrollment_id': rec.id,
                        'lesson_id': lesson.id,
                        'employee_id': rec.employee_id.id,
                        'state': 'not_started',
                    })

    def action_start_course(self):
        for rec in self:
            if rec.is_locked:
                raise UserError(_("This course is locked. Complete prerequisite courses in the learning path first."))
            if rec.course_id.has_pre_assessment and not rec.pre_assessment_passed:
                raise UserError(_("You must pass the pre-assessment before accessing course content."))
            if rec.state == 'enrolled':
                rec.write({'state': 'in_progress'})

    def action_mark_completed_and_certify(self, score_pct=100.0):
        """Invoked when learner completes all lessons and passes post-assessment."""
        for rec in self:
            today = fields.Date.context_today(self)
            rec.write({
                'state': 'completed',
                'completion_date': today,
                'final_score_percentage': score_pct,
                'post_assessment_passed': True,
            })
            self.env['lms.enrollment'].invalidate_model(['is_locked'])
            rec.message_post(body=_('Course completed successfully with score of %.1f%%.') % score_pct)

            # Issue Certificate (FR-LMS-018)
            if rec.course_id.issue_certificate and not rec.certificate_id:
                cert = self.env['lms.certificate'].issue_certificate(rec, score_pct)
                rec.write({'certificate_id': cert.id})

            # Award Gamification Points (FR-REC-001)
            if rec.employee_id and rec.employee_id.user_id:
                self.env['lms.gamification.point'].award_points(
                    rec.employee_id.user_id,
                    points=50 if score_pct >= 90 else 30,
                    source='course_complete',
                    description=f'Completed course: {rec.course_id.name} ({score_pct:.1f}%)'
                )

    @api.model
    def cron_send_overdue_reminders(self):
        """
        Automated daily cron to send notifications for overdue or nearing-deadline mandatory courses (FR-LMS-028).
        Notifies learner and their direct manager via chatter/activity.
        """
        today = fields.Date.context_today(self)
        active_enrollments = self.search([
            ('is_mandatory', '=', True),
            ('state', 'in', ['enrolled', 'in_progress']),
            ('due_date', '!=', False),
        ])

        for enrollment in active_enrollments:
            emp = enrollment.employee_id
            mgr = emp.parent_id
            course_name = enrollment.course_id.name

            if enrollment.due_date < today:
                days_overdue = (today - enrollment.due_date).days
                body = _(
                    "MANDATORY TRAINING OVERDUE: '%(course)s' was due on %(due)s (%(days)d days overdue). "
                    "Please complete immediately to maintain regulatory compliance."
                ) % {
                    'course': course_name,
                    'due': enrollment.due_date,
                    'days': days_overdue,
                }
                partner_ids = [p.id for p in [emp.user_id.partner_id, mgr.user_id.partner_id] if p]
                enrollment.message_post(
                    body=body,
                    subject=_("Mandatory Course Overdue: %s") % course_name,
                    partner_ids=partner_ids,
                )
            elif (enrollment.due_date - today).days <= 3:
                days_left = (enrollment.due_date - today).days
                body = _(
                    "UPCOMING DEADLINE: Mandatory course '%(course)s' is due in %(days)d day(s) (deadline: %(due)s)."
                ) % {
                    'course': course_name,
                    'days': days_left,
                    'due': enrollment.due_date,
                }
                partner_ids = [emp.user_id.partner_id.id] if emp.user_id.partner_id else []
                enrollment.message_post(
                    body=body,
                    subject=_("Reminder: Mandatory Course Due Soon - %s") % course_name,
                    partner_ids=partner_ids,
                )


class LmsLessonProgress(models.Model):
    """
    Per-Lesson Anti-Cheat Watch Time and Resume State Tracker (FR-LMS-007, FR-LMS-008, FR-LMS-009).
    Records watched seconds, enforces anti-seeking bounds, and logs completion.
    """
    _name = 'lms.lesson.progress'
    _description = 'Lesson Learning Progress'
    _order = 'enrollment_id, lesson_id'

    enrollment_id = fields.Many2one('lms.enrollment', string='Course Enrollment', required=True, ondelete='cascade', index=True)
    lesson_id = fields.Many2one('lms.lesson', string='Lesson', required=True, ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', string='Learner', required=True)

    state = fields.Selection([
        ('not_started', 'Not Started'),
        ('in_progress', 'Watching / In Progress'),
        ('completed', 'Completed'),
    ], string='Progress Status', default='not_started', required=True)

    # Anti-Cheat & Resume Engine (FR-LMS-008, FR-LMS-009)
    max_watched_seconds = fields.Integer(string='Max Legitimate Watched Second', default=0)
    last_position_seconds = fields.Integer(string='Resume Timestamp (Seconds)', default=0)
    total_seconds_watched = fields.Integer(string='Cumulative Time Spent (Seconds)', default=0)
    watch_percentage = fields.Float(string='Watched %', compute='_compute_watch_percentage', store=True)

    date_completed = fields.Datetime(string='Completion Timestamp', readonly=True)

    _enroll_lesson_uniq = models.Constraint(
        'UNIQUE(enrollment_id, lesson_id)',
        'Lesson progress record must be unique per enrollment!'
    )

    @api.depends('max_watched_seconds', 'lesson_id.video_duration_seconds')
    def _compute_watch_percentage(self):
        for rec in self:
            duration = rec.lesson_id.video_duration_seconds or 600
            if duration > 0:
                rec.watch_percentage = min(100.0, (rec.max_watched_seconds / float(duration)) * 100.0)
            else:
                rec.watch_percentage = 100.0 if rec.state == 'completed' else 0.0

    def update_progress(self, current_time, duration=None):
        """
        Called by video player heartbeat controller to record legitimate watch seconds.
        Authoritative duration is strictly derived from lesson_id.video_duration_seconds (FR-LMS-007).
        """
        self.ensure_one()
        auth_duration = self.lesson_id.video_duration_seconds or 600
        tolerance = 5  # Allow small buffer for player clock drift
        max_valid_time = auth_duration + tolerance

        # Clamp client current_time to non-negative and not exceeding nominal duration + tolerance
        current_time = max(0, min(int(current_time), max_valid_time))

        # Anti-skip guard: cannot jump more than 10 seconds ahead of max_watched_seconds
        if current_time > self.max_watched_seconds + 10 and self.lesson_id.prevent_fast_forward:
            allowed_pos = self.max_watched_seconds
        else:
            allowed_pos = current_time
            if current_time > self.max_watched_seconds:
                self.max_watched_seconds = min(current_time, auth_duration)

        self.last_position_seconds = allowed_pos
        self.total_seconds_watched += 5

        if self.state == 'not_started':
            self.state = 'in_progress'
            if self.enrollment_id.state == 'enrolled':
                self.enrollment_id.state = 'in_progress'

        # Check if mandatory watch percentage is reached using authoritative duration (FR-LMS-007)
        req_pct = self.lesson_id.min_watch_percentage or 90.0
        curr_pct = (self.max_watched_seconds / float(auth_duration)) * 100.0 if auth_duration > 0 else 100.0

        if curr_pct >= req_pct and self.state != 'completed':
            self.mark_completed()

        return {'allowed_position': allowed_pos, 'is_completed': self.state == 'completed'}

    def mark_completed(self):
        for rec in self:
            rec.write({
                'state': 'completed',
                'date_completed': fields.Datetime.now()
            })
            if rec.enrollment_id.state == 'enrolled':
                rec.enrollment_id.write({'state': 'in_progress'})
            # If all lessons completed and course has no post-assessment, certify now
            all_done = all(lp.state == 'completed' for lp in rec.enrollment_id.lesson_progress_ids)
            if all_done and not rec.enrollment_id.course_id.has_post_assessment:
                rec.enrollment_id.action_mark_completed_and_certify(100.0)
