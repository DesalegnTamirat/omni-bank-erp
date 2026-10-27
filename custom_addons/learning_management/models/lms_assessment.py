from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class LmsAssessment(models.Model):
    """
    Assessment & Quiz Engine (FR-LMS-012 to FR-LMS-017).
    Supports diagnostic pre-tests, post-course gating assessments, timed exams,
    randomized question pools, attempt caps, and instant auto-grading.
    """
    _name = 'lms.assessment'
    _description = 'LMS Course Assessment / Exam'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Assessment Title', required=True, tracking=True)
    code = fields.Char(string='Exam Code', readonly=True, copy=False, default=lambda self: _('New'))
    course_id = fields.Many2one('lms.course', string='Associated Course', tracking=True)

    assessment_type = fields.Selection([
        ('post_course', 'Post-Course Final Assessment (Certification Gate)'),
        ('pre_course', 'Pre-Course Diagnostic Assessment'),
        ('module_quiz', 'Mid-Module Checkpoint Quiz'),
    ], string='Assessment Type', default='post_course', required=True, tracking=True)

    # Timing & Limits (FR-LMS-014, FR-LMS-016)
    is_timed = fields.Boolean(string='Timed Assessment', default=True)
    duration_minutes = fields.Integer(
        string='Time Limit (Minutes)',
        default=30,
        help='Learners have this amount of time before the exam automatically submits.'
    )

    pass_score_percentage = fields.Float(
        string='Passing Score Threshold (%)',
        default=70.0,
        required=True,
        tracking=True
    )
    max_attempts = fields.Integer(
        string='Maximum Attempt Limit',
        default=3,
        help='Maximum number of attempts allowed before failure lockout (FR-LMS-016).'
    )
    cooldown_hours = fields.Float(
        string='Cooldown Period Between Retries (Hours)',
        default=1.0,
        help='Mandatory waiting time before a failed learner can attempt the test again.'
    )

    # Question Sourcing & Randomization (FR-LMS-015)
    use_random_pool = fields.Boolean(
        string='Draw Random Questions from Category Pools',
        default=True,
        help='Generates a unique randomized question snapshot for each learner attempt.'
    )
    questions_per_session = fields.Integer(string='Questions per Attempt', default=10)
    pool_ids = fields.Many2many(
        'lms.question.pool', string='Question Pools',
        groups='learning_management.group_lms_instructor',
    )
    fixed_question_ids = fields.Many2many(
        'lms.question', string='Fixed Question Bank',
        groups='learning_management.group_lms_instructor',
    )

    shuffle_questions = fields.Boolean(string='Shuffle Question Order', default=True)
    # Reserved for a future per-attempt answer-order snapshot. Do not expose
    # this as an active exam control until the order is actually implemented.
    shuffle_answers = fields.Boolean(string='Shuffle Answer Choices', default=False)

    instructions = fields.Html(string='Candidate Examination Instructions', required=True)

    active = fields.Boolean(default=True)

    _revision_fields = frozenset({
        'name', 'course_id', 'assessment_type', 'is_timed', 'duration_minutes',
        'pass_score_percentage', 'max_attempts', 'cooldown_hours',
        'use_random_pool', 'questions_per_session', 'pool_ids',
        'fixed_question_ids', 'shuffle_questions', 'shuffle_answers',
        'instructions', 'active',
    })

    def _validate_for_publication(self):
        for assessment in self:
            if not assessment.instructions or not assessment.instructions.strip():
                raise UserError(_('Add instructions to assessment "%s".') % assessment.name)
            if not 0 < assessment.pass_score_percentage <= 100:
                raise UserError(_('Assessment passing score must be between 0 and 100 percent.'))
            if assessment.max_attempts < 0 or assessment.cooldown_hours < 0:
                raise UserError(_('Assessment attempt limits and cooldown cannot be negative.'))
            if assessment.use_random_pool and assessment.pool_ids:
                questions = assessment.pool_ids.mapped('question_ids').filtered('active')
                if assessment.questions_per_session <= 0 or len(questions) < assessment.questions_per_session:
                    raise UserError(_('Add enough active questions to the selected pools for "%s".') % assessment.name)
            else:
                questions = assessment.fixed_question_ids.filtered('active')
            if not questions:
                raise UserError(_('Add an active question bank to assessment "%s".') % assessment.name)
            questions._validate_for_publication()

    @api.constrains('is_timed', 'duration_minutes')
    def _check_timed_duration(self):
        for assessment in self:
            if assessment.is_timed and assessment.duration_minutes <= 0:
                raise ValidationError(_('Timed assessments need a positive duration.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not self.env.su and vals.get('course_id'):
                course = self.env['lms.course'].browse(vals['course_id'])
                if course.state != 'draft':
                    raise UserError(_('Assessments can only be added to draft courses.'))
            if vals.get('code', _('New')) == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('lms.assessment') or _('New')
        return super(LmsAssessment, self).create(vals_list)

    def write(self, vals):
        if not self.env.su and self._revision_fields.intersection(vals):
            target = self.env['lms.course'].browse(vals['course_id']) if vals.get('course_id') else False
            if any((rec.course_id and rec.course_id.state != 'draft')
                   or (target and target.state != 'draft') for rec in self):
                raise UserError(_('Create a course revision to edit a reviewed or published assessment.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.su and any((rec.course_id and rec.course_id.state != 'draft')
                                   or self.env['lms.exam.session'].sudo().search_count([
                                       ('assessment_id', '=', rec.id),
                                   ]) for rec in self):
            raise UserError(_('Reviewed assessments and recorded exam attempts must be retained.'))
        return super().unlink()

    def _validate_learner_attempt(self, employee, enrollment):
        """Apply course and curriculum gates even for a direct exam-session create."""
        self.ensure_one()
        course = self.course_id
        if not self.active or not course:
            raise UserError(_('This assessment is not available for this course.'))
        if (not enrollment or enrollment.employee_id != employee
                or enrollment.course_id != course
                or enrollment.state not in ('enrolled', 'in_progress')):
            raise UserError(_('An active enrollment in this course is required for the assessment.'))
        if not enrollment._course_available_for_learning():
            raise UserError(_('This assessment is not available for this course version.'))
        if enrollment.is_locked:
            raise UserError(_('This course is locked. Complete prerequisite courses in the learning path first.'))
        if course.has_pre_assessment and not enrollment.pre_assessment_passed and self.assessment_type != 'pre_course':
            raise UserError(_('Pass the pre-course assessment before accessing other assessments.'))
        if self.assessment_type == 'pre_course':
            if not course.has_pre_assessment or (course.pre_assessment_id and course.pre_assessment_id != self):
                raise UserError(_('This is not the configured pre-course assessment.'))
        elif self.assessment_type == 'post_course':
            if not course.has_post_assessment or (course.post_assessment_id and course.post_assessment_id != self):
                raise UserError(_('This is not the configured post-course assessment.'))
            # Use the actual curriculum even when the learner cannot yet read
            # a lesson through its record rule.
            incomplete = course.sudo().lesson_ids.filtered('is_mandatory') - enrollment.sudo().completed_lesson_ids
            if incomplete:
                raise UserError(_('You must complete all lessons before taking this exam. Incomplete: %s') % ', '.join(incomplete.mapped('name')))
        elif self.assessment_type == 'module_quiz':
            lessons = course.sudo().lesson_ids
            quiz_lessons = lessons.filtered(lambda lesson: lesson.assessment_id == self)
            if not quiz_lessons:
                raise UserError(_('This quiz is not part of the enrolled course.'))
            prior_lessons = lessons[:lessons.ids.index(quiz_lessons[0].id)].filtered('is_mandatory')
            if prior_lessons - enrollment.sudo().completed_lesson_ids:
                raise UserError(_('Complete earlier mandatory lessons before taking this quiz.'))

    def action_start_exam(self, enrollment=None):
        """Prepares a new exam session for the current user and enrollment."""
        self.ensure_one()
        user = self.env.user
        emp = user.employee_id
        if not emp:
            raise UserError(_('No employee record associated with current user account.'))

        # Fix 4: Resolve enrollment from current user if not passed
        if not enrollment and self.course_id:
            enrollment = self.env['lms.enrollment'].search([
                ('employee_id', '=', emp.id),
                ('course_id', '=', self.course_id.id),
                ('state', 'in', ('enrolled', 'in_progress')),
            ], order='attempt_number desc, id desc', limit=1)

        if not enrollment and self.course_id:
            # Keep the exhausted-attempt message useful after the final failed
            # exam has closed its enrollment. A later renewal has a fresh cap.
            latest = self.env['lms.enrollment'].search([
                ('employee_id', '=', emp.id),
                ('course_id', '=', self.course_id.id),
            ], order='attempt_number desc, id desc', limit=1)
            if latest and self.max_attempts > 0:
                prior_attempts = self.env['lms.exam.session'].search_count(
                    self.env['lms.exam.session']._attempt_domain(
                        self.id, emp.id, latest.id,
                    ) + [('state', 'in', ['submitted', 'passed', 'failed'])]
                )
                if prior_attempts >= self.max_attempts:
                    raise UserError(_('You have exhausted the maximum allowed attempts (%d) for this assessment.') % self.max_attempts)
            raise UserError(_("You must be enrolled in %s to take this exam.") % self.course_id.name)

        # Report an exhausted attempt cap even after its final failed attempt
        # has moved the enrollment to the failed state.
        attempt_domain = self.env['lms.exam.session']._attempt_domain(
            self.id, emp.id, enrollment.id if enrollment else False,
        )
        attempts = self.env['lms.exam.session'].search(attempt_domain + [
            ('state', 'in', ['submitted', 'passed', 'failed']),
        ])
        if self.max_attempts > 0 and len(attempts) >= self.max_attempts:
            raise UserError(_('You have exhausted the maximum allowed attempts (%d) for this assessment.') % self.max_attempts)

        self._validate_learner_attempt(emp, enrollment)

        # Fix 7: Check attempt cooldown (FR-LMS-016)
        if self.cooldown_hours > 0:
            last_session = self.env['lms.exam.session'].search(attempt_domain + [
                ('state', 'in', ['submitted', 'passed', 'failed']),
            ], order='end_time desc', limit=1)
            if last_session and last_session.end_time:
                earliest_allowed = last_session.end_time + timedelta(hours=self.cooldown_hours)
                if fields.Datetime.now() < earliest_allowed:
                    raise UserError(_("Cooldown period active. You can retry after %s.") % earliest_allowed.strftime('%Y-%m-%d %H:%M:%S'))

        # Create session
        session = self.env['lms.exam.session'].create_session_for_learner(self, emp, enrollment)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'lms.exam.session',
            'res_id': session.id,
            'view_mode': 'form',
            'target': 'current',
        }
