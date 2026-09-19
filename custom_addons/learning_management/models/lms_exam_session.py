# -*- coding: utf-8 -*-
import random
from datetime import datetime, timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError


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

    line_ids = fields.One2many('lms.exam.session.line', 'session_id', string='Question Lines')

    @api.depends('assessment_id', 'employee_id', 'attempt_number')
    def _compute_name(self):
        for rec in self:
            rec.name = f"{rec.assessment_id.name or 'Exam'} - {rec.employee_id.name or ''} (Attempt #{rec.attempt_number})"

    @api.depends('start_time', 'assessment_id.duration_minutes')
    def _compute_deadline(self):
        for rec in self:
            if rec.start_time and rec.assessment_id.is_timed:
                rec.deadline_time = rec.start_time + timedelta(minutes=rec.assessment_id.duration_minutes or 30)
            else:
                rec.deadline_time = False

    @api.model
    def create_session_for_learner(self, assessment, employee, enrollment=None):
        """Builds randomized question snapshot for the candidate (FR-LMS-015)."""
        previous_attempts = self.search_count([
            ('assessment_id', '=', assessment.id),
            ('employee_id', '=', employee.id),
        ])
        attempt_no = previous_attempts + 1

        selected_questions = []
        if assessment.use_random_pool and assessment.pool_ids:
            all_pool_questions = self.env['lms.question'].search([('pool_id', 'in', assessment.pool_ids.ids)])
            pool_q_list = list(all_pool_questions)
            sample_size = min(assessment.questions_per_session or 10, len(pool_q_list))
            selected_questions = random.sample(pool_q_list, sample_size)
        elif assessment.fixed_question_ids:
            selected_questions = list(assessment.fixed_question_ids)

        if assessment.shuffle_questions:
            random.shuffle(selected_questions)

        session = self.create({
            'assessment_id': assessment.id,
            'enrollment_id': enrollment.id if enrollment else False,
            'employee_id': employee.id,
            'attempt_number': attempt_no,
            'start_time': fields.Datetime.now(),
            'state': 'in_progress',
        })

        # Create session lines
        for q in selected_questions:
            self.env['lms.exam.session.line'].create({
                'session_id': session.id,
                'question_id': q.id,
            })

        return session

    def action_submit_and_grade(self):
        """Auto-evaluates question answers, calculates percentage, and determines pass/fail (FR-LMS-017)."""
        for rec in self:
            total_earned = 0.0
            total_available = 0.0

            for line in rec.line_ids:
                q = line.question_id
                weight = q.points or 1.0
                total_available += weight

                correct_ids = set(q.answer_ids.filtered(lambda a: a.is_correct).ids)
                selected_ids = set(line.selected_answer_ids.ids)

                if q.question_type in ('single_choice', 'true_false'):
                    is_correct = (correct_ids == selected_ids) and len(selected_ids) == 1
                else:  # multiple_choice
                    is_correct = (correct_ids == selected_ids)

                line.is_correct = is_correct
                line.points_earned = weight if is_correct else 0.0
                total_earned += line.points_earned

            score_pct = (total_earned / total_available * 100.0) if total_available > 0 else 0.0
            passed = score_pct >= rec.assessment_id.pass_score_percentage

            rec.write({
                'score_points': total_earned,
                'max_points': total_available,
                'score_percentage': score_pct,
                'is_passed': passed,
                'end_time': fields.Datetime.now(),
                'state': 'passed' if passed else 'failed',
            })

            # If passed post-assessment, certify enrollment
            if passed and rec.enrollment_id and rec.assessment_id.assessment_type == 'post_course':
                rec.enrollment_id.action_mark_completed_and_certify(score_pct)
            elif not passed and rec.enrollment_id and rec.assessment_id.assessment_type == 'post_course':
                attempts = self.search_count([
                    ('assessment_id', '=', rec.assessment_id.id),
                    ('employee_id', '=', rec.employee_id.id),
                    ('state', 'in', ['passed', 'failed']),
                ])
                if rec.assessment_id.max_attempts > 0 and attempts >= rec.assessment_id.max_attempts:
                    rec.enrollment_id.write({'state': 'failed'})


class LmsExamSessionLine(models.Model):
    """Candidate answer line for a specific exam question."""
    _name = 'lms.exam.session.line'
    _description = 'Exam Session Answer Line'
    _order = 'id'

    session_id = fields.Many2one('lms.exam.session', string='Session', required=True, ondelete='cascade', index=True)
    question_id = fields.Many2one('lms.question', string='Question', required=True, ondelete='cascade')
    selected_answer_ids = fields.Many2many('lms.question.answer', string='Selected Options')
    is_correct = fields.Boolean(string='Is Correct', default=False)
    points_earned = fields.Float(string='Points Earned', default=0.0)
