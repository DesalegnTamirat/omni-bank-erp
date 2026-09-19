# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


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
    pool_ids = fields.Many2many('lms.question.pool', string='Question Pools')
    fixed_question_ids = fields.Many2many('lms.question', string='Fixed Question Bank')

    shuffle_questions = fields.Boolean(string='Shuffle Question Order', default=True)
    shuffle_answers = fields.Boolean(string='Shuffle Answer Choices', default=True)

    instructions = fields.Html(string='Candidate Examination Instructions', required=True)

    active = fields.Boolean(default=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code', _('New')) == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('lms.assessment') or _('New')
        return super(LmsAssessment, self).create(vals_list)

    def action_start_exam(self, enrollment=None):
        """Prepares a new exam session for the current user and enrollment."""
        self.ensure_one()
        user = self.env.user
        emp = user.employee_id
        if not emp:
            raise UserError(_('No employee record associated with current user account.'))

        # Check training completion gate for post-assessments (FR-LMS-012)
        if self.assessment_type == 'post_course' and enrollment:
            not_done = enrollment.lesson_progress_ids.filtered(lambda lp: lp.state != 'completed' and lp.lesson_id.is_mandatory)
            if not_done:
                raise UserError(_('Training Completion Gate: You must complete all mandatory lessons and videos in this course before taking the final assessment.'))

        # Check attempt limits (FR-LMS-016)
        attempts = self.env['lms.exam.session'].search([
            ('assessment_id', '=', self.id),
            ('employee_id', '=', emp.id),
            ('state', 'in', ['submitted', 'passed', 'failed']),
        ])
        if self.max_attempts > 0 and len(attempts) >= self.max_attempts:
            raise UserError(_('You have exhausted the maximum allowed attempts (%d) for this assessment.') % self.max_attempts)

        # Create session
        session = self.env['lms.exam.session'].create_session_for_learner(self, emp, enrollment)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'lms.exam.session',
            'res_id': session.id,
            'view_mode': 'form',
            'target': 'current',
        }
