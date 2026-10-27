# -*- coding: utf-8 -*-
import random
import logging
from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


class LmsExamSession(models.Model):
    """
    Candidate Examination Attempt & Auto-Grading Session (FR-LMS-014, FR-LMS-017).
    Manages timed candidate sessions, answer captures, auto-scoring, and pass/fail evaluation.
    """
    _name = 'lms.exam.session'
    _description = 'LMS Exam Candidate Attempt'
    _order = 'start_time desc'

    name = fields.Char(string='Attempt Reference', compute='_compute_name', store=True)
    assessment_id = fields.Many2one('lms.assessment', string='Assessment', required=True, ondelete='cascade', index=True)
    enrollment_id = fields.Many2one('lms.enrollment', string='Course Enrollment', ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', string='Candidate / Employee', required=True, index=True)

    attempt_number = fields.Integer(string='Attempt #', default=1)
    start_time = fields.Datetime(string='Exam Start Timestamp', default=fields.Datetime.now, required=True)
    end_time = fields.Datetime(string='Submission Timestamp')
    deadline_time = fields.Datetime(string='Time Limit Expiry', compute='_compute_deadline', store=True)

    state = fields.Selection([
        ('in_progress', 'Exam In Progress'),
        ('submitted', 'Submitted / Graded'),
        ('passed', 'Passed Successfully'),
        ('failed', 'Failed (Passing Threshold Not Met)'),
    ], string='Status', default='in_progress', required=True, index=True)

    # Automated Scoring Results (FR-LMS-017)
    score_points = fields.Float(string='Score Achieved', readonly=True)
    max_points = fields.Float(string='Max Available Points', readonly=True)
    score_percentage = fields.Float(string='Final Score (%)', readonly=True)
    is_passed = fields.Boolean(string='Passed Exam', default=False, readonly=True)

    # Policies are captured at the start so a later configuration change cannot
    # extend a running attempt or alter its passing score. The flag preserves
    # legacy sessions created before these snapshots existed.
    exam_policy_snapshotted = fields.Boolean(default=False, readonly=True, copy=False)
    pass_score_at_start = fields.Float(readonly=True, copy=False)
    is_timed_at_start = fields.Boolean(readonly=True, copy=False)
    duration_minutes_at_start = fields.Integer(readonly=True, copy=False)

    line_ids = fields.One2many('lms.exam.session.line', 'session_id', string='Question Lines')

    @api.model
    def _attempt_domain(self, assessment_id, employee_id, enrollment_id):
        """An enrollment is one certification cycle with its own exam allowance."""
        return [
            ('assessment_id', '=', assessment_id),
            ('employee_id', '=', employee_id),
            ('enrollment_id', '=', enrollment_id or False),
        ]

    @api.depends('assessment_id', 'employee_id', 'attempt_number')
    def _compute_name(self):
        for rec in self:
            rec.name = f"{rec.assessment_id.name or 'Exam'} - {rec.employee_id.name or ''} (Attempt #{rec.attempt_number})"

    @api.depends('start_time', 'assessment_id.duration_minutes', 'assessment_id.is_timed',
                 'exam_policy_snapshotted', 'is_timed_at_start', 'duration_minutes_at_start')
    def _compute_deadline(self):
        for rec in self:
            timed = rec.is_timed_at_start if rec.exam_policy_snapshotted else rec.assessment_id.is_timed
            duration = (rec.duration_minutes_at_start if rec.exam_policy_snapshotted
                        else rec.assessment_id.duration_minutes)
            if rec.start_time and timed:
                rec.deadline_time = rec.start_time + timedelta(minutes=duration or 30)
            else:
                rec.deadline_time = False

    @api.model_create_multi
    def create(self, vals_list):
        # Serialize starts for one learner/assessment before checking active
        # sessions and attempt limits. Locks are ordered for bulk imports.
        attempt_keys = [(int(vals['assessment_id']), int(vals['employee_id']))
                        for vals in vals_list if vals.get('assessment_id') and vals.get('employee_id')]
        if len(attempt_keys) != len(set(attempt_keys)):
            raise UserError(_('Start only one session per learner and assessment at a time.'))
        for assessment_id, employee_id in sorted(set(attempt_keys)):
            self.env.cr.execute('SELECT pg_advisory_xact_lock(%s, %s)', (assessment_id, employee_id))
        if not self.env.su:
            for vals in vals_list:
                if vals.get('state', 'in_progress') != 'in_progress' or any(
                    key in vals for key in ('score_points', 'max_points', 'score_percentage',
                                             'is_passed', 'end_time', 'deadline_time',
                                             'line_ids', 'exam_policy_snapshotted',
                                             'pass_score_at_start', 'is_timed_at_start',
                                             'duration_minutes_at_start')
                ):
                    raise AccessError(_('Exam results are set by grading only.'))
        if not self.env.su and not self.env.user.has_group('learning_management.group_lms_manager'):
            for vals in vals_list:
                if vals.get('employee_id') != self.env.user.employee_id.id:
                    raise AccessError(_('You may only start your own exam.'))
                if not vals.get('enrollment_id') or not vals.get('assessment_id'):
                    raise AccessError(_('The exam must belong to your active course enrollment.'))
                enrollment = self.env['lms.enrollment'].browse(vals['enrollment_id'])
                assessment = self.env['lms.assessment'].browse(vals['assessment_id'])
                assessment._validate_learner_attempt(self.env.user.employee_id, enrollment)
                vals['start_time'] = fields.Datetime.now()
                vals['attempt_number'] = self.search_count(self._attempt_domain(
                    assessment.id, self.env.user.employee_id.id, enrollment.id,
                ) + [
                    ('state', 'in', ['submitted', 'passed', 'failed']),
                ]) + 1
        for vals in vals_list:
            assessment_id = vals.get('assessment_id')
            employee_id = vals.get('employee_id')
            if assessment_id and employee_id:
                assessment = self.env['lms.assessment'].browse(assessment_id)
                attempt_domain = self._attempt_domain(
                    assessment_id, employee_id, vals.get('enrollment_id'),
                )
                vals['exam_policy_snapshotted'] = True
                vals['pass_score_at_start'] = assessment.pass_score_percentage
                vals['is_timed_at_start'] = assessment.is_timed
                vals['duration_minutes_at_start'] = assessment.duration_minutes
                if self.search_count(attempt_domain + [
                    ('state', '=', 'in_progress'),
                ]):
                    raise UserError(_('Resume the exam already in progress before starting another attempt.'))
                if assessment.max_attempts > 0:
                    cnt = self.search_count(attempt_domain + [
                        ('state', 'in', ['submitted', 'passed', 'failed']),
                    ])
                    if cnt >= assessment.max_attempts:
                        raise UserError(_('You have exhausted the maximum allowed attempts (%d) for this assessment.') % assessment.max_attempts)
                if assessment.cooldown_hours > 0:
                    last_session = self.search(attempt_domain + [
                        ('state', 'in', ['submitted', 'passed', 'failed']),
                    ], order='end_time desc, id desc', limit=1)
                    if (last_session.end_time and fields.Datetime.now()
                            < last_session.end_time + timedelta(hours=assessment.cooldown_hours)):
                        raise UserError(_('Cooldown period active. Retry after %s.') % last_session.end_time)
        sessions = super().create(vals_list)
        if not self.env.su:
            for session in sessions:
                session._generate_question_lines()
        return sessions

    def _generate_question_lines(self):
        """Create the randomized question snapshot for one new attempt."""
        self.ensure_one()
        if (not self.env.su and not self.env.user.has_group('learning_management.group_lms_manager')
                and self.employee_id != self.env.user.employee_id):
            raise AccessError(_('You may only prepare your own exam.'))
        if self.state != 'in_progress':
            raise UserError(_('Only an active exam can receive questions.'))
        if self.line_ids:
            return
        assessment = self.assessment_id.sudo()
        if assessment.use_random_pool and assessment.pool_ids:
            pool_questions = self.env['lms.question'].sudo().search([
                ('pool_id', 'in', assessment.pool_ids.ids),
            ])
            count = min(assessment.questions_per_session or 10, len(pool_questions))
            selected_questions = random.sample(list(pool_questions), count)
        else:
            selected_questions = list(assessment.fixed_question_ids)
        if not selected_questions:
            raise UserError(_('Configure at least one question before starting this assessment.'))
        if assessment.shuffle_questions:
            random.shuffle(selected_questions)
        for question in selected_questions:
            self.env['lms.exam.session.line'].sudo().create({
                'session_id': self.id,
                'question_id': question.id,
            })

    @api.model
    def create_session_for_learner(self, assessment, employee, enrollment=None):
        """Builds randomized question snapshot for the candidate (FR-LMS-015)."""
        if not self.env.su and not self.env.user.has_group('learning_management.group_lms_manager'):
            assessment._validate_learner_attempt(employee, enrollment)
        attempt_domain = self._attempt_domain(
            assessment.id, employee.id, enrollment.id if enrollment else False,
        )
        active_session = self.search(attempt_domain + [
            ('state', '=', 'in_progress'),
        ], order='id desc', limit=1)
        if active_session:
            return active_session
        previous_attempts = self.search_count(attempt_domain + [
            ('state', 'in', ['submitted', 'passed', 'failed']),
        ])
        if assessment.max_attempts > 0 and previous_attempts >= assessment.max_attempts:
            raise UserError(_('You have exhausted the maximum allowed attempts (%d) for this assessment.') % assessment.max_attempts)
        attempt_no = previous_attempts + 1

        session = self.create({
            'assessment_id': assessment.id,
            'enrollment_id': enrollment.id if enrollment else False,
            'employee_id': employee.id,
            'attempt_number': attempt_no,
            'start_time': fields.Datetime.now(),
            'state': 'in_progress',
        })

        session._generate_question_lines()

        return session

    def write(self, vals):
        protected = {'state', 'score_points', 'max_points', 'score_percentage',
                     'is_passed', 'employee_id', 'assessment_id', 'enrollment_id',
                     'start_time', 'deadline_time', 'end_time', 'attempt_number',
                     'exam_policy_snapshotted', 'pass_score_at_start',
                     'is_timed_at_start', 'duration_minutes_at_start'}
        if protected.intersection(vals) and not self.env.su:
            raise AccessError(_('Exam results are set by grading only.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.su:
            raise AccessError(_('Exam attempts are retained for the learning record.'))
        return super().unlink()

    def action_submit_and_grade(self):
        """Auto-evaluates question answers, calculates percentage, and determines pass/fail (FR-LMS-017)."""
        for rec in self:
            if rec.state != 'in_progress':
                raise UserError(_('This exam has already been submitted.'))
            if not self.env.su and not self.env.user.has_group('learning_management.group_lms_manager'):
                if rec.employee_id != self.env.user.employee_id:
                    raise AccessError(_('You may only submit your own exam.'))
            total_earned = 0.0
            total_available = 0.0

            for line in rec.line_ids:
                q = line.question_id
                weight = line.points_at_start if line.question_snapshotted else (q.points or 1.0)
                total_available += weight

                correct_ids = set(
                    line.sudo().correct_answer_ids_at_start.ids if line.question_snapshotted
                    else q.sudo().answer_ids.filtered('is_correct').ids
                )
                selected_ids = set(line.selected_answer_ids.ids)

                question_type = line.question_type_at_start if line.question_snapshotted else q.question_type
                if question_type in ('single_choice', 'true_false'):
                    is_correct = (correct_ids == selected_ids) and len(selected_ids) == 1
                else:  # multiple_choice
                    is_correct = (correct_ids == selected_ids)

                earned = weight if is_correct else 0.0
                line.sudo().write({'is_correct': is_correct, 'points_earned': earned})
                total_earned += earned

            score_pct = (total_earned / total_available * 100.0) if total_available > 0 else 0.0
            pass_score = (rec.pass_score_at_start if rec.exam_policy_snapshotted
                          else rec.assessment_id.pass_score_percentage)
            passed = bool(total_available) and score_pct >= pass_score

            rec.sudo().write({
                'score_points': total_earned,
                'max_points': total_available,
                'score_percentage': score_pct,
                'is_passed': passed,
                'end_time': fields.Datetime.now(),
                'state': 'passed' if passed else 'failed',
            })

            enrollment = rec.enrollment_id or (
                rec.assessment_id.course_id and self.env['lms.enrollment'].search([
                    ('employee_id', '=', rec.employee_id.id),
                    ('course_id', '=', rec.assessment_id.course_id.id),
                ], limit=1)
            )

            # The quiz lesson has no learner-facing completion button. Credit
            # it only from a passed, enrollment-bound attempt, and let the
            # normal lesson workflow enforce ownership and curriculum order.
            if (passed and rec.enrollment_id
                    and rec.assessment_id.assessment_type == 'module_quiz'):
                quiz_progress = rec.enrollment_id.lesson_progress_ids.filtered(
                    lambda progress: progress.employee_id == rec.employee_id
                    and progress.lesson_id.lesson_type == 'quiz'
                    and progress.lesson_id.assessment_id == rec.assessment_id
                    and progress.lesson_id.course_id == rec.enrollment_id.course_id
                    and progress.state != 'completed'
                )
                # A course can contain more than one lesson linked to the same
                # assessment. One pass credits the first unlocked lesson only;
                # a later quiz must not roll back grading while its preceding
                # mandatory activities are still incomplete.
                lessons = rec.enrollment_id.course_id.lesson_ids
                completed_lessons = rec.enrollment_id.completed_lesson_ids
                for lesson in lessons:
                    progress = quiz_progress.filtered(lambda item: item.lesson_id == lesson)
                    if not progress:
                        continue
                    prior_required = lessons[:lessons.ids.index(lesson.id)].filtered('is_mandatory')
                    if prior_required - completed_lessons:
                        continue
                    progress.mark_completed()
                    break

            # Pre-course diagnostic assessment handling (FR-LMS-013)
            if enrollment and rec.assessment_id.assessment_type == 'pre_course':
                if passed:
                    enrollment.sudo().write({'pre_assessment_passed': True})
                    enrollment.message_post(body=_('Pre-course diagnostic assessment passed with score %.1f%%.') % score_pct)
                else:
                    enrollment.message_post(body=_('Pre-course diagnostic assessment failed with score %.1f%% (Passing threshold: %.1f%%).') % (score_pct, pass_score))

            # If passed post-assessment, certify enrollment
            if passed and enrollment and rec.assessment_id.assessment_type == 'post_course':
                enrollment.action_mark_completed_and_certify(score_pct)
            elif not passed and enrollment and rec.assessment_id.assessment_type == 'post_course':
                attempts = self.search_count(self._attempt_domain(
                    rec.assessment_id.id, rec.employee_id.id,
                    rec.enrollment_id.id if rec.enrollment_id else False,
                ) + [
                    ('state', 'in', ['passed', 'failed']),
                ])
                if rec.assessment_id.max_attempts > 0 and attempts >= rec.assessment_id.max_attempts:
                    enrollment.sudo().write({'state': 'failed'})

    @api.model
    def cron_submit_expired_exams(self):
        """Submit timed attempts using answers recorded before their deadline."""
        expired = self.sudo().search([
            ('state', '=', 'in_progress'),
            ('deadline_time', '!=', False),
            ('deadline_time', '<=', fields.Datetime.now()),
        ], limit=100)
        for session in expired:
            try:
                with self.env.cr.savepoint():
                    session.action_submit_and_grade()
            except Exception:
                _logger.exception('Could not auto-submit LMS exam session %s', session.id)


class LmsExamSessionLine(models.Model):
    """Candidate answer line for a specific exam question."""
    _name = 'lms.exam.session.line'
    _description = 'Exam Session Answer Line'
    _order = 'id'

    session_id = fields.Many2one('lms.exam.session', string='Session', required=True, ondelete='cascade', index=True)
    question_id = fields.Many2one('lms.question', string='Question', required=True, ondelete='cascade')
    question_text = fields.Html(string='Question Text', readonly=True, copy=False)
    question_snapshotted = fields.Boolean(default=False, readonly=True, copy=False)
    question_type_at_start = fields.Selection([
        ('single_choice', 'Single Choice'),
        ('multiple_choice', 'Multiple Choice'),
        ('true_false', 'True / False'),
    ], readonly=True, copy=False)
    points_at_start = fields.Float(readonly=True, copy=False)
    correct_answer_ids_at_start = fields.Many2many(
        'lms.question.answer', 'lms_exam_line_correct_answer_rel',
        'line_id', 'answer_id', string='Correct Choices at Start',
        readonly=True, copy=False, groups='learning_management.group_lms_instructor',
    )
    selected_answer_ids = fields.Many2many('lms.question.answer', string='Selected Options')
    is_correct = fields.Boolean(string='Is Correct', default=False)
    points_earned = fields.Float(string='Points Earned', default=0.0)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.user.has_group('learning_management.group_lms_manager'):
            raise AccessError(_('Exam questions are assigned by the exam workflow.'))
        for vals in vals_list:
            if vals.get('question_id'):
                question = self.env['lms.question'].sudo().browse(vals['question_id'])
                vals['question_text'] = question.question_text
                vals['question_snapshotted'] = True
                vals['question_type_at_start'] = question.question_type
                vals['points_at_start'] = question.points or 1.0
                vals['correct_answer_ids_at_start'] = [
                    (6, 0, question.answer_ids.filtered('is_correct').ids),
                ]
        return super().create(vals_list)

    def write(self, vals):
        snapshots = {'session_id', 'question_id', 'question_text', 'question_snapshotted',
                     'question_type_at_start', 'points_at_start', 'correct_answer_ids_at_start'}
        if snapshots.intersection(vals) and not self.env.su:
            raise AccessError(_('Exam question snapshots cannot be changed.'))
        if 'selected_answer_ids' in vals:
            for line in self:
                if line.session_id.state != 'in_progress':
                    raise UserError(_('Answers cannot be changed after exam submission.'))
                if line.session_id.deadline_time and fields.Datetime.now() >= line.session_id.deadline_time:
                    raise UserError(_('The exam time limit has expired. Submit the recorded answers.'))
        if not self.env.su and not self.env.user.has_group('learning_management.group_lms_manager'):
            if set(vals) != {'selected_answer_ids'}:
                raise AccessError(_('Only answer selection can be changed during an exam.'))
            for line in self:
                if (line.session_id.state != 'in_progress'
                        or line.session_id.employee_id != self.env.user.employee_id):
                    raise AccessError(_('You may only answer your own active exam.'))
        result = super().write(vals)
        if 'selected_answer_ids' in vals:
            for line in self:
                if line.sudo().selected_answer_ids - line.sudo().question_id.answer_ids:
                    raise UserError(_('Selected answers must belong to the exam question.'))
        return result

    def unlink(self):
        if not self.env.su:
            raise AccessError(_('Assigned exam questions cannot be removed.'))
        return super().unlink()
