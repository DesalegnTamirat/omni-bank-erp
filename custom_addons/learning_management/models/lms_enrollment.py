# -*- coding: utf-8 -*-
from markupsafe import Markup, escape
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class LmsEnrollment(models.Model):
    """
    Learner Course Enrollment & Completion Engine (FR-LMS-007 to FR-LMS-012).
    Enforces lesson progression gates, tracks completion percentages, manages certificates,
    and bridges records to core HR employee master data.
    """
    _name = 'lms.enrollment'
    _description = 'Course Enrollment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'state desc, completion_date desc, enrollment_date desc'

    name = fields.Char(string='Enrollment Reference', compute='_compute_name', store=True)
    employee_id = fields.Many2one('hr.employee', string='Learner / Employee', required=True, tracking=True, index=True)
    user_id = fields.Many2one('res.users', related='employee_id.user_id', string='User Account', readonly=True, store=True)
    department_id = fields.Many2one('hr.department', related='employee_id.department_id', string='Department', store=True, readonly=True)
    operating_unit_id = fields.Many2one('operating.unit', related='employee_id.default_operating_unit_id', string='Branch / Unit', store=True, readonly=True)

    course_id = fields.Many2one('lms.course', string='Course', required=True, tracking=True, index=True)
    course_has_pre_assessment = fields.Boolean(related='course_id.has_pre_assessment', readonly=True)
    course_has_post_assessment = fields.Boolean(related='course_id.has_post_assessment', readonly=True)
    assignment_id = fields.Many2one('lms.course.assignment', string='Assignment Campaign', ondelete='set null')

    is_mandatory = fields.Boolean(string='Mandatory', default=False, tracking=True)
    enrollment_date = fields.Date(string='Enrolled Date', default=fields.Date.context_today, required=True)
    attempt_number = fields.Integer(string='Enrollment Attempt', default=1, required=True,
                                    readonly=True, copy=False, index=True)
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
    threshold_50_notified = fields.Boolean(string='50% Milestone Notified', default=False, copy=False)
    threshold_100_notified = fields.Boolean(string='100% Milestone Notified', default=False, copy=False)
    last_upcoming_reminder_date = fields.Date(readonly=True, copy=False)
    last_overdue_reminder_date = fields.Date(readonly=True, copy=False)

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

    _emp_course_attempt_uniq = models.Constraint(
        'UNIQUE(employee_id, course_id, attempt_number)',
        'An enrollment attempt already exists for this employee and course!'
    )

    def init(self):
        """Remove the old one-enrollment-per-course key on module upgrade."""
        self.env.cr.execute(
            'ALTER TABLE lms_enrollment DROP CONSTRAINT IF EXISTS '
            'lms_enrollment_emp_course_uniq'
        )

    @api.depends('employee_id', 'course_id')
    def _compute_name(self):
        for rec in self:
            rec.name = f"{rec.employee_id.name or ''} - {rec.course_id.name or ''}"

    @api.depends('due_date', 'state')
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
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

    @api.depends('employee_id', 'course_id', 'assignment_id')
    def _compute_is_locked(self):
        employee_ids = self.mapped('employee_id').ids
        related_enrollments = self.sudo().search([('employee_id', 'in', employee_ids)]) if employee_ids else self.browse()
        enrollments_by_employee = {}
        for enrollment in related_enrollments:
            enrollments_by_employee.setdefault(enrollment.employee_id.id, self.browse())
            enrollments_by_employee[enrollment.employee_id.id] |= enrollment
        stages = self.env['lms.learning.path.course'].sudo()
        candidate_stages = stages.search([('course_id', 'in', self.mapped('course_id').ids)]) if self else stages
        stages_by_course = {}
        for stage in candidate_stages:
            stages_by_course.setdefault(stage.course_id.id, stages)
            stages_by_course[stage.course_id.id] |= stage
        for rec in self:
            locked = False
            if rec.employee_id and rec.course_id:
                # Read path configuration internally: learners have no access
                # to assignment targeting or draft learning paths.
                path = rec.assignment_id.sudo().learning_path_id if rec.assignment_id else False
                enrollments = enrollments_by_employee.get(rec.employee_id.id, self.browse())
                enrolled_courses = enrollments.mapped('course_id')
                completed_courses = enrollments.filtered(
                    lambda enrollment: enrollment.state == 'completed'
                ).mapped('course_id')
                if path:
                    path_courses = path.sudo().path_course_ids.filtered(
                        lambda stage: stage.course_id == rec.course_id
                    )
                else:
                    # A manually enrolled learner can also be following a
                    # path. Infer that only when they are enrolled in an
                    # earlier or explicit prerequisite course in that path.
                    candidates = stages_by_course.get(rec.course_id.id, stages)
                    path_courses = candidates.filtered(lambda stage: (
                        stage.path_id.active and bool((
                            stage.prerequisite_course_ids |
                            stage.path_id.path_course_ids.filtered(
                                lambda prior: prior.sequence < stage.sequence
                                and not prior.is_optional_branch
                            ).mapped('course_id')
                        ) & enrolled_courses)
                    ))

                for stage in path_courses:
                    if stage.prerequisite_course_ids - completed_courses:
                        locked = True
                        break
                    prior_courses = stage.path_id.path_course_ids.filtered(
                        lambda prior: prior.sequence < stage.sequence
                        and not prior.is_optional_branch
                        and prior.course_id != rec.course_id
                    ).mapped('course_id')
                    if (prior_courses - completed_courses) and (
                        path or prior_courses & enrolled_courses
                    ):
                        locked = True
                        break
            rec.is_locked = locked

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.user.has_group('learning_management.group_lms_manager'):
            if any(set(vals) & {'state', 'completion_date', 'post_assessment_passed',
                                'pre_assessment_passed', 'final_score_percentage', 'certificate_id'}
                   for vals in vals_list):
                raise AccessError(_('Learners cannot set enrollment completion fields.'))
        # Lock the employee row so concurrent assignment jobs cannot choose the
        # same next attempt number. A completed attempt remains audit history.
        allocated = {}
        for course_id in sorted({vals['course_id'] for vals in vals_list if vals.get('course_id')}):
            # Assignment dispatch runs with sudo, so enforce this at creation.
            self.env.cr.execute('SELECT id FROM lms_course WHERE id = %s FOR SHARE', (course_id,))
            course = self.env['lms.course'].sudo().browse(course_id)
            course.invalidate_recordset(['state', 'is_latest_version', 'active'])
            if course.state != 'published' or not course.is_latest_version or not course.active:
                raise UserError(_('New enrollment requires an active, latest published course.'))
        for vals in vals_list:
            employee_id, course_id = vals.get('employee_id'), vals.get('course_id')
            if not employee_id or not course_id:
                continue
            key = (employee_id, course_id)
            if key not in allocated:
                self.env.cr.execute(
                    'SELECT id FROM hr_employee WHERE id = %s FOR UPDATE', (employee_id,)
                )
                self.env.cr.execute(
                    'SELECT COALESCE(MAX(attempt_number), 0) FROM lms_enrollment '
                    'WHERE employee_id = %s AND course_id = %s', key
                )
                allocated[key] = self.env.cr.fetchone()[0]
            allocated[key] += 1
            vals['attempt_number'] = allocated[key]
            active = self.sudo().search([
                ('employee_id', '=', employee_id), ('course_id', '=', course_id),
                ('state', 'in', ('enrolled', 'in_progress')),
            ], limit=1)
            if active or allocated[key] > 1 and any(
                other is not vals and other.get('employee_id') == employee_id
                and other.get('course_id') == course_id for other in vals_list
            ):
                raise UserError(_('An active enrollment already exists for this course.'))
        records = super(LmsEnrollment, self).create(vals_list)
        todo_activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        for rec in records:
            rec._initialize_lesson_progress()
            # Notify learner via chatter with direct link
            due_txt = _(" Please complete it before %s.") % rec.due_date if rec.due_date else ""
            msg_text = _("You have been enrolled in the course '%(course)s'.%(due)s") % {
                'course': rec.course_id.name,
                'due': due_txt,
            }
            action_link = f"/web#id={rec.id}&model=lms.enrollment"
            body = Markup(f"""<p>{escape(msg_text)}</p>
<div style="margin-top: 10px;">
    <a href="{action_link}" style="background-color: #541718; color: #FFFFFF; padding: 6px 14px; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 12px; display: inline-block;">🎓 Start Learning / Open Course</a>
</div>""")
            partner_ids = [rec.user_id.partner_id.id] if rec.user_id and rec.user_id.partner_id else []
            rec.message_post(
                body=body,
                subject=_("Course Enrollment: %s") % rec.course_id.name,
                partner_ids=partner_ids,
            )
            # Schedule To-Do activity if user account is linked
            if rec.user_id and todo_activity_type:
                deadline = rec.due_date or fields.Date.today()
                note_label = _("Mandatory Course Enrollment") if rec.is_mandatory else _("Course Enrollment")
                note = Markup(f"""<p>{escape(note_label)}: <b>{escape(rec.course_id.name or '')}</b></p>
<div style="margin-top: 8px;">
    <a href="{action_link}" style="background-color: #541718; color: #FFFFFF; padding: 6px 14px; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 12px; display: inline-block;">🎓 Start Learning / Open Course</a>
</div>""")
                rec.activity_schedule(
                    activity_type_id=todo_activity_type.id,
                    summary=_("Complete Course: %s") % rec.course_id.name,
                    note=note,
                    date_deadline=deadline,
                    user_id=rec.user_id.id,
                )
        return records

    def write(self, vals):
        if not self.env.su and {'employee_id', 'course_id'}.intersection(vals):
            raise UserError(_('An enrollment belongs to its original learner and course version. Create a new enrollment instead.'))
        if (not self.env.su and vals.get('state') in ('enrolled', 'in_progress')
                and any(rec.state in ('completed', 'failed') for rec in self)):
            raise UserError(_('A finished enrollment cannot be reopened. Create a new attempt.'))
        protected = {'state', 'completion_date', 'post_assessment_passed',
                     'pre_assessment_passed', 'final_score_percentage', 'certificate_id',
                     'threshold_50_notified', 'threshold_100_notified',
                     'employee_id', 'course_id', 'assignment_id', 'is_mandatory',
                     'enrollment_date', 'due_date', 'is_overdue',
                     'last_upcoming_reminder_date', 'last_overdue_reminder_date',
                     'lesson_progress_ids', 'progress_percentage',
                     'completed_lessons_count', 'total_lessons_count'}
        if (protected.intersection(vals) and not self.env.su
                and not self.env.user.has_group('learning_management.group_lms_manager')):
            raise AccessError(_('Learners cannot alter enrollment completion fields.'))
        return super().write(vals)

    def _course_available_for_learning(self):
        """Retirement closes intake but honors an existing learner's course."""
        self.ensure_one()
        course = self.course_id
        return bool(course.active and (
            (course.state == 'published' and course.is_latest_version)
            or (course.state == 'archived'
                and self.state in ('enrolled', 'in_progress', 'completed'))
        ))

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

    def _check_progress_milestones(self):
        """Check and send chatter notifications when learner hits 50% or 100% progress thresholds."""
        for rec in self:
            partner_ids = [rec.user_id.partner_id.id] if rec.user_id and rec.user_id.partner_id else []
            action_link = f"/web#id={rec.id}&model=lms.enrollment"
            if rec.progress_percentage >= 50.0 and not rec.threshold_50_notified:
                rec.threshold_50_notified = True
                msg_text = _("Milestone Reached: You have reached %.1f%% progress in '%s'!") % (
                    rec.progress_percentage, rec.course_id.name
                )
                body = Markup(f"""<p>{escape(msg_text)}</p>
<div style="margin-top: 10px;">
    <a href="{action_link}" style="background-color: #541718; color: #FFFFFF; padding: 6px 14px; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 12px; display: inline-block;">📈 View Course Progress</a>
</div>""")
                rec.message_post(
                    body=body,
                    subject=_("Course Progress: 50% Milestone Reached"),
                    partner_ids=partner_ids,
                )
            if rec.progress_percentage >= 100.0 and not rec.threshold_100_notified:
                rec.threshold_100_notified = True
                msg_text = _("Course Progress: You have completed 100%% of the lessons in '%s'!") % rec.course_id.name
                body = Markup(f"""<p>{escape(msg_text)}</p>
<div style="margin-top: 10px;">
    <a href="{action_link}" style="background-color: #541718; color: #FFFFFF; padding: 6px 14px; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 12px; display: inline-block;">📈 View Course Progress</a>
</div>""")
                rec.message_post(
                    body=body,
                    subject=_("Course Progress: 100% Milestone Reached"),
                    partner_ids=partner_ids,
                )

    def action_start_course(self):
        self.ensure_one()
        if self.state not in ('enrolled', 'in_progress'):
            raise UserError(_('Only an active enrollment can be started.'))
        if not self._course_available_for_learning():
            raise UserError(_('This course is not currently available.'))
        if self.is_locked:
            raise UserError(_("This course is locked. Complete prerequisite courses in the learning path first."))
        if self.course_id.has_pre_assessment and not self.pre_assessment_passed:
            raise UserError(_("You must pass the pre-assessment before accessing course content."))
        if self.state == 'enrolled':
            self.sudo().write({'state': 'in_progress'})
        for lesson in self.course_id.lesson_ids:
            progress = self.lesson_progress_ids.filtered(lambda item: item.lesson_id == lesson)
            if progress and progress.state != 'completed':
                return progress.action_open_lesson()
        return False

    def _create_recertification_enrollment(self, due_date=None):
        """Start a new learning attempt while retaining prior completion evidence."""
        self.ensure_one()
        if self.state != 'completed':
            raise UserError(_('Only a completed enrollment can be renewed.'))
        course = self._current_recertification_course()
        if not course:
            raise UserError(_('Publish the current course version before renewal.'))
        mandatory = self.is_mandatory or course.is_mandatory
        if due_date is None and mandatory:
            today = fields.Date.context_today(self)
            expiry_date = self.certificate_id.expiry_date if self.certificate_id else False
            due_date = fields.Date.add(max(today, expiry_date or today), days=30)
        active = self.sudo().search([
            ('employee_id', '=', self.employee_id.id), ('course_id', '=', course.id),
            ('state', 'in', ('enrolled', 'in_progress')),
        ], order='attempt_number desc, id desc', limit=1)
        if active:
            update = {}
            if mandatory and not active.is_mandatory:
                update['is_mandatory'] = True
            if due_date and (not active.due_date or due_date < active.due_date):
                update['due_date'] = due_date
            if update:
                active.sudo().write(update)
            return active
        return self.sudo().create({
            'employee_id': self.employee_id.id,
            'course_id': course.id,
            'assignment_id': self.assignment_id.id if self.assignment_id and course.id == self.course_id.id else False,
            'is_mandatory': mandatory,
            'due_date': due_date or False,
        })

    def _current_recertification_course(self):
        """Follow approved revisions, never a draft sibling or retired version."""
        self.ensure_one()
        source = self.course_id.sudo()
        if source.state == 'published' and source.is_latest_version and source.active:
            return source
        seen = set(source.ids)
        frontier = source
        while frontier:
            successors = self.env['lms.course'].sudo().search([
                ('previous_version_id', 'in', frontier.ids),
                ('state', 'in', ('published', 'archived')),
            ])
            successors = successors.filtered(lambda course: course.id not in seen)
            current = successors.filtered(
                lambda course: course.state == 'published' and course.is_latest_version and course.active
            )
            if current:
                return current[:1]
            seen.update(successors.ids)
            frontier = successors
        return self.env['lms.course']

    def action_create_recertification(self):
        self.ensure_one()
        if not self.env.su and not self.env.user.has_group('learning_management.group_lms_manager'):
            if self.employee_id != self.env.user.employee_id:
                raise AccessError(_('You may only renew your own enrollment.'))
            cert = self.certificate_id
            today = fields.Date.context_today(self)
            if not cert:
                raise UserError(_('Ask an LMS manager to arrange a repeat of this course.'))
            if (cert and cert.state == 'valid' and
                    (not cert.expiry_date or cert.expiry_date > fields.Date.add(today, days=30))):
                raise UserError(_('This certificate is not yet due for renewal.'))
        renewal = self._create_recertification_enrollment()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Course Renewal'),
            'res_model': 'lms.enrollment',
            'res_id': renewal.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_start_pre_assessment(self):
        self.ensure_one()
        if not self.course_id.has_pre_assessment or not self.course_id.pre_assessment_id:
            raise UserError(_('This course has no configured pre-course assessment.'))
        return self.course_id.pre_assessment_id.action_start_exam(self)

    def action_start_post_assessment(self):
        self.ensure_one()
        if not self.course_id.has_post_assessment or not self.course_id.post_assessment_id:
            raise UserError(_('This course has no configured post-course assessment.'))
        return self.course_id.post_assessment_id.action_start_exam(self)

    def action_mark_completed_and_certify(self, score_pct=100.0):
        """Invoked when learner completes all lessons and passes post-assessment."""
        for rec in self:
            if rec.state == 'completed':
                continue
            if not self.env.su and not self.env.user.has_group('learning_management.group_lms_manager'):
                if rec.employee_id != self.env.user.employee_id:
                    raise AccessError(_('You may only complete your own enrollment.'))
            if not rec._course_available_for_learning() or rec.state not in ('enrolled', 'in_progress'):
                raise UserError(_('Only active enrollments on available course versions can be completed.'))
            if rec.is_locked:
                raise UserError(_('This enrollment cannot be completed in its current state.'))
            if rec.course_id.has_pre_assessment and not rec.pre_assessment_passed:
                raise UserError(_('The pre-course assessment must be passed first.'))
            required = rec.course_id.lesson_ids.filtered('is_mandatory')
            completed = rec.lesson_progress_ids.filtered(
                lambda p: p.state == 'completed' and p.lesson_id in required
            ).mapped('lesson_id')
            if not rec.lesson_progress_ids.filtered(lambda p: p.state == 'completed'):
                raise UserError(_('Complete a course lesson before certification.'))
            if required - completed:
                raise UserError(_('Complete all mandatory lessons before certification.'))
            if rec.course_id.has_post_assessment:
                assessment = rec.course_id.post_assessment_id
                exam_domain = [
                    ('employee_id', '=', rec.employee_id.id),
                    ('enrollment_id', '=', rec.id),
                    ('assessment_id.course_id', '=', rec.course_id.id),
                    ('assessment_id.assessment_type', '=', 'post_course'),
                    ('state', '=', 'passed'),
                ]
                if assessment:
                    exam_domain.append(('assessment_id', '=', assessment.id))
                passed_exam = self.env['lms.exam.session'].sudo().search(
                    exam_domain, order='end_time desc, id desc', limit=1
                )
                if not passed_exam:
                    raise UserError(_('Pass the post-course assessment before certification.'))
                score_pct = passed_exam.score_percentage
            else:
                score_pct = 100.0
            today = fields.Date.context_today(self)
            rec.sudo().write({
                'state': 'completed',
                'completion_date': today,
                'final_score_percentage': score_pct,
                'post_assessment_passed': True,
            })
            self.env['lms.enrollment'].invalidate_model(['is_locked'])
            rec.sudo()._check_progress_milestones()
            rec.message_post(
                body=_('Course completed successfully with score of %.1f%%.') % score_pct,
                subject=_('Course Completed: %s') % rec.course_id.name,
                partner_ids=[rec.user_id.partner_id.id]
                if rec.user_id and rec.user_id.partner_id else [],
            )

            # Issue Certificate (FR-LMS-018)
            if rec.course_id.issue_certificate and not rec.certificate_id:
                cert = self.env['lms.certificate'].sudo().issue_certificate(rec.sudo(), score_pct)
                rec.sudo().write({'certificate_id': cert.id})

            # Award Gamification Points (FR-REC-001)
            employee_user = rec.employee_id.sudo().user_id if rec.employee_id else False
            if employee_user:
                self.env['lms.gamification.point'].sudo()._award_points(
                    employee_user,
                    points=50 if score_pct >= 90 else 30,
                    source='course_complete',
                    description=f'Completed course: {rec.course_id.name} ({score_pct:.1f}%)'
                )
            if self.env.registry.get('eds.lms.routing'):
                routings = self.env['eds.lms.routing'].sudo().search([
                    ('lms_ref', '=', str(rec.course_id.id)), ('sync_state', '=', 'synced'),
                ])
                routings.action_reconcile_lms()

    @api.model
    def cron_send_overdue_reminders(self):
        """
        Automated daily cron to send notifications for overdue or nearing-deadline mandatory courses (FR-LMS-028).
        Notifies learner and their direct manager via chatter/activity.
        """
        today = fields.Date.context_today(self)
        # A stored field cannot depend on the passage of time. Refresh it on
        # the daily job so list badges and the compliance SQL view stay current.
        self.flush_model(['due_date', 'state', 'is_overdue'])
        self.env.cr.execute("""
            UPDATE lms_enrollment
               SET is_overdue = (due_date IS NOT NULL AND due_date < %s
                                 AND state NOT IN ('completed', 'failed'))
             WHERE is_overdue IS DISTINCT FROM
                   (due_date IS NOT NULL AND due_date < %s
                    AND state NOT IN ('completed', 'failed'))
        """, (today, today))
        self.invalidate_model(['is_overdue'])
        params = self.env['ir.config_parameter'].sudo()

        def positive_days(name, default, allow_zero=False):
            try:
                value = int(params.get_param(name, str(default)))
            except (ValueError, TypeError):
                value = default
            return max(0 if allow_zero else 1, min(value, 365))

        reminder_days = positive_days('learning_management.reminder_days_before_due', 3, allow_zero=True)
        upcoming_interval = positive_days('learning_management.upcoming_reminder_interval_days', 3)
        overdue_interval = positive_days('learning_management.overdue_reminder_interval_days', 7)
        notify_manager = str(params.get_param('learning_management.notify_manager_on_overdue', 'True')).lower() in (
            '1', 'true', 'yes'
        )
        domain = [
            ('is_mandatory', '=', True),
            ('state', 'in', ['enrolled', 'in_progress']),
            ('due_date', '<=', fields.Date.add(today, days=reminder_days)),
        ]
        last_id = 0
        while True:
            batch = self.sudo().search(domain + [('id', '>', last_id)], order='id', limit=500)
            if not batch:
                break
            last_id = batch[-1].id
            for enrollment in batch:
                enrollment._send_due_reminder(today, reminder_days, upcoming_interval,
                                              overdue_interval, notify_manager)

    def _send_due_reminder(self, today, reminder_days, upcoming_interval, overdue_interval, notify_manager):
        self.ensure_one()
        enrollment = self
        if not enrollment.due_date:
            return
        if enrollment.due_date < today:
            last_sent = enrollment.last_overdue_reminder_date
            if last_sent and (today - last_sent).days < overdue_interval:
                return
        else:
            last_sent = enrollment.last_upcoming_reminder_date
            if last_sent and (today - last_sent).days < upcoming_interval:
                return

        if enrollment.due_date < today or 0 <= (enrollment.due_date - today).days <= reminder_days:
            emp = enrollment.employee_id
            mgr = emp.parent_id
            course_name = enrollment.course_id.name

            action_link = f"/web#id={enrollment.id}&model=lms.enrollment"
            button_html = f"""<div style="margin-top: 10px;">
    <a href="{action_link}" style="background-color: #541718; color: #FFFFFF; padding: 6px 14px; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 12px; display: inline-block;">⚠️ Resume Course Now</a>
</div>"""

            if enrollment.due_date < today:
                days_overdue = (today - enrollment.due_date).days
                msg_text = _(
                    "MANDATORY TRAINING OVERDUE: '%(course)s' was due on %(due)s (%(days)d days overdue). "
                    "Please complete immediately to maintain regulatory compliance."
                ) % {
                    'course': course_name,
                    'due': enrollment.due_date,
                    'days': days_overdue,
                }
                body = Markup(f"<p>{escape(msg_text)}</p>{button_html}")
                partners = [emp.user_id.partner_id]
                if notify_manager and mgr.user_id:
                    partners.append(mgr.user_id.partner_id)
                partner_ids = [partner.id for partner in partners if partner]
                enrollment.message_post(
                    body=body,
                    subject=_("Mandatory Course Overdue: %s") % course_name,
                    partner_ids=partner_ids,
                )
                enrollment.sudo().last_overdue_reminder_date = today
            elif 0 <= (enrollment.due_date - today).days <= reminder_days:
                days_left = (enrollment.due_date - today).days
                msg_text = _(
                    "UPCOMING DEADLINE: Mandatory course '%(course)s' is due in %(days)d day(s) (deadline: %(due)s)."
                ) % {
                    'course': course_name,
                    'days': days_left,
                    'due': enrollment.due_date,
                }
                body = Markup(f"<p>{escape(msg_text)}</p>{button_html}")
                partner_ids = [emp.user_id.partner_id.id] if emp.user_id.partner_id else []
                enrollment.message_post(
                    body=body,
                    subject=_("Reminder: Mandatory Course Due Soon - %s") % course_name,
                    partner_ids=partner_ids,
                )
                enrollment.sudo().last_upcoming_reminder_date = today


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
    lesson_type = fields.Selection(related='lesson_id.lesson_type', readonly=True)
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
    last_heartbeat_at = fields.Datetime(string='Last Video Heartbeat', copy=False)
    watch_percentage = fields.Float(string='Watched %', compute='_compute_watch_percentage', store=True)

    date_completed = fields.Datetime(string='Completion Timestamp', readonly=True)
    opened_at = fields.Datetime(string='Last Opened', readonly=True, copy=False)
    acknowledged_at = fields.Datetime(string='Review Acknowledged At', readonly=True, copy=False)
    completion_method = fields.Selection([
        ('video_watch', 'Video Watch Threshold'),
        ('quiz_pass', 'Passed Quiz'),
        ('learner_acknowledgment', 'Learner Confirmed Review'),
        ('manager_override', 'Manager Completion Correction'),
    ], string='Completion Evidence', readonly=True, copy=False)

    _enroll_lesson_uniq = models.Constraint(
        'UNIQUE(enrollment_id, lesson_id)',
        'Lesson progress record must be unique per enrollment!'
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.user.has_group('learning_management.group_lms_manager'):
            raise AccessError(_('Lesson progress is created by enrollment only.'))
        return super().create(vals_list)

    def write(self, vals):
        protected = {'state', 'employee_id', 'enrollment_id', 'lesson_id',
                     'max_watched_seconds', 'last_position_seconds',
                     'total_seconds_watched', 'last_heartbeat_at', 'date_completed',
                     'opened_at', 'acknowledged_at', 'completion_method'}
        if (protected.intersection(vals) and not self.env.su
                and not self.env.user.has_group('learning_management.group_lms_manager')):
            raise AccessError(_('Lesson progress is updated by the learning workflow only.'))
        return super().write(vals)

    @api.depends('max_watched_seconds', 'lesson_id.video_duration_seconds')
    def _compute_watch_percentage(self):
        for rec in self:
            duration = rec.lesson_id.video_duration_seconds or 600
            if duration > 0:
                rec.watch_percentage = min(100.0, (rec.max_watched_seconds / float(duration)) * 100.0)
            else:
                rec.watch_percentage = 100.0 if rec.state == 'completed' else 0.0

    def _check_learning_access(self, allow_completed=False):
        for rec in self:
            progress = rec.sudo()
            enrollment = progress.enrollment_id
            course = enrollment.course_id
            lesson = progress.lesson_id
            if (not self.env.su and not self.env.user.has_group('learning_management.group_lms_manager')
                    and progress.employee_id != self.env.user.employee_id):
                raise AccessError(_('You can only update your own lesson progress.'))
            if (progress.employee_id != enrollment.employee_id or lesson.course_id != course
                    or enrollment.state not in (('enrolled', 'in_progress', 'completed') if allow_completed else ('enrolled', 'in_progress'))
                    or not enrollment._course_available_for_learning()):
                raise UserError(_('This lesson is not available in an active course enrollment.'))
            if enrollment.is_locked:
                raise UserError(_('Complete prerequisite courses before starting this lesson.'))
            if course.has_pre_assessment and not enrollment.pre_assessment_passed:
                raise UserError(_('Pass the pre-course assessment before accessing lessons.'))
            lessons = course.lesson_ids
            prior = lessons[:lessons.ids.index(lesson.id)].filtered('is_mandatory')
            if prior - enrollment.completed_lesson_ids:
                raise UserError(_('Complete earlier mandatory lessons before progressing.'))

    def action_open_lesson(self):
        """Open the next learning activity from the enrollment's progress list."""
        self.ensure_one()
        self._check_learning_access(allow_completed=True)
        lesson = self.lesson_id
        if lesson.lesson_type in ('text', 'document'):
            self.sudo().opened_at = fields.Datetime.now()
        if lesson.lesson_type == 'video':
            return {
                'type': 'ir.actions.act_url',
                'url': '/lms/video/%s/player' % lesson.id,
                'target': 'new',
            }
        if lesson.lesson_type == 'document':
            return lesson.action_open_document()
        if lesson.lesson_type == 'quiz':
            if not lesson.assessment_id:
                raise UserError(_('Configure an assessment for this quiz lesson.'))
            return lesson.assessment_id.action_start_exam(self.enrollment_id)
        return {
            'name': lesson.name,
            'type': 'ir.actions.act_window',
            'res_model': 'lms.lesson',
            'res_id': lesson.id,
            'views': [(self.env.ref('learning_management.view_lms_lesson_learner_form').id, 'form')],
            'target': 'current',
        }

    def update_progress(self, current_time, duration=None):
        """
        Called by video player heartbeat controller to record legitimate watch seconds.
        Authoritative duration is strictly derived from lesson_id.video_duration_seconds (FR-LMS-007).
        """
        self.ensure_one()
        self._check_learning_access()
        auth_duration = self.lesson_id.video_duration_seconds or 600
        try:
            current_time = max(0, min(int(float(current_time)), auth_duration))
        except (TypeError, ValueError, OverflowError):
            raise UserError(_('Invalid video position.'))
        now = fields.Datetime.now()
        elapsed = max(0, (now - self.last_heartbeat_at).total_seconds()) if self.last_heartbeat_at else 5
        credit = min(10, int(elapsed))
        max_watched = self.max_watched_seconds
        total_watched = self.total_seconds_watched
        # The server clock, not the client playback position, bounds credited progress.
        if current_time > max_watched + credit + 2 and self.lesson_id.prevent_fast_forward:
            allowed_pos = max_watched
        else:
            allowed_pos = current_time
            if current_time > max_watched:
                advanced = min(current_time - max_watched, credit)
                max_watched += advanced
                total_watched += advanced

        progress_vals = {
            'max_watched_seconds': max_watched,
            'total_seconds_watched': total_watched,
            'last_position_seconds': allowed_pos,
            'last_heartbeat_at': now,
        }
        started = self.state == 'not_started'
        if started:
            progress_vals['state'] = 'in_progress'
        # The learner has passed _check_learning_access above. Persist only the
        # server-calculated heartbeat fields through this workflow; direct
        # learner writes to those fields remain blocked by write().
        self.sudo().write(progress_vals)
        if started and self.enrollment_id.state == 'enrolled':
            self.enrollment_id.sudo().write({'state': 'in_progress'})

        # Check if mandatory watch percentage is reached using authoritative duration (FR-LMS-007)
        req_pct = self.lesson_id.min_watch_percentage or 90.0
        curr_pct = (max_watched / float(auth_duration)) * 100.0 if auth_duration > 0 else 100.0

        if curr_pct >= req_pct and self.state != 'completed':
            self.mark_completed()

        return {'allowed_position': allowed_pos, 'is_completed': self.state == 'completed'}

    def mark_completed(self):
        for rec in self:
            if rec.state == 'completed':
                continue
            rec._check_learning_access()
            if rec.lesson_id.lesson_type == 'video':
                duration = rec.lesson_id.video_duration_seconds or 600
                required_seconds = duration * (rec.lesson_id.min_watch_percentage or 90.0) / 100.0
                if rec.max_watched_seconds < required_seconds:
                    raise UserError(_('Watch the required portion of the video first.'))
            if rec.lesson_id.lesson_type == 'quiz':
                if not rec.lesson_id.assessment_id:
                    raise UserError(_('Configure an assessment for this quiz lesson.'))
                passed = self.env['lms.exam.session'].sudo().search_count([
                    ('enrollment_id', '=', rec.enrollment_id.id),
                    ('assessment_id', '=', rec.lesson_id.assessment_id.id),
                    ('state', '=', 'passed'),
                ])
                if not passed:
                    raise UserError(_('Pass the lesson quiz before completing it.'))
            manager_override = (
                (self.env.su or self.env.user.has_group('learning_management.group_lms_manager'))
                and rec.employee_id != self.env.user.employee_id
            )
            if (rec.lesson_id.lesson_type in ('text', 'document')
                    and not rec.opened_at and not manager_override):
                raise UserError(_('Open the lesson before confirming that you reviewed it.'))
            method = {
                'video': 'video_watch',
                'quiz': 'quiz_pass',
                'text': 'learner_acknowledgment',
                'document': 'learner_acknowledgment',
            }[rec.lesson_id.lesson_type]
            if manager_override and method == 'learner_acknowledgment':
                method = 'manager_override'
            now = fields.Datetime.now()
            rec.sudo().write({
                'state': 'completed',
                'date_completed': now,
                'completion_method': method,
                'acknowledged_at': now if method == 'learner_acknowledgment' else False,
            })
            if rec.enrollment_id.state == 'enrolled':
                rec.enrollment_id.sudo().write({'state': 'in_progress'})
            # Trigger milestone checks on enrollment (50% / 100%)
            rec.enrollment_id.sudo()._check_progress_milestones()
            # If all lessons completed and course has no post-assessment, certify now
            all_done = all(lp.state == 'completed' for lp in rec.enrollment_id.lesson_progress_ids)
            if all_done and not rec.enrollment_id.course_id.has_post_assessment:
                rec.enrollment_id.action_mark_completed_and_certify(100.0)
