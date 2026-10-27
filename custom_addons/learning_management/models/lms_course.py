# -*- coding: utf-8 -*-
from urllib.parse import urlsplit

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError, AccessError


def external_media_url_allowed(url, allowed_hosts):
    """Use one URL policy for course approval and the playback endpoint."""
    if not url or any(ord(char) < 32 or ord(char) == 127 for char in url):
        return False
    try:
        parsed = urlsplit(url)
        hosts = {host.strip().lower() for host in (allowed_hosts or '').split(',') if host.strip()}
        return (parsed.scheme.lower() == 'https' and bool(parsed.hostname)
                and parsed.hostname.lower() in hosts and not parsed.username
                and not parsed.password)
    except ValueError:
        return False


class LmsCourse(models.Model):
    """
    Core LMS Course Management (FR-LMS-001, FR-LMS-010, FR-LMS-011).
    Houses syllabus, modules, learning control policies, assessments, and certifications.
    """
    _name = 'lms.course'
    _description = 'LMS Training Course'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, name'

    name = fields.Char(string='Course Title', required=True, tracking=True, index=True)
    code = fields.Char(string='Course Code', readonly=True, copy=False, default=lambda self: _('New'), index=True)
    sequence = fields.Integer(default=10)
    category_id = fields.Many2one('lms.category', string='Course Category', required=True, tracking=True, index=True)
    description = fields.Html(string='Course Description & Syllabus', required=True)
    learning_objectives = fields.Html(string='Key Learning Outcomes & Objectives')
    cover_image = fields.Binary(string='Course Banner Image', attachment=True)

    # Scoping & Targeting
    target_department_ids = fields.Many2many('hr.department', string='Target Departments')
    target_job_ids = fields.Many2many('hr.job', string='Target Job Positions')
    target_grade_ids = fields.Many2many('employee.grade', string='Target Employee Grades')

    # Competency Framework Linkage (from competency_management)
    competency_ids = fields.Many2many(
        'competency.competency',
        'lms_course_competency_rel',
        'course_id',
        'competency_id',
        string='Targeted Competencies',
        help='Competencies developed and certified upon passing this course.'
    )

    # Course Settings & Policies
    is_mandatory = fields.Boolean(
        string='Mandatory Course',
        default=False,
        tracking=True,
        help='If mandatory, employee dashboards and compliance matrix reports flag overdue status.'
    )
    estimated_duration_hours = fields.Float(string='Estimated Duration (Hours)', default=1.0)
    pass_score_percentage = fields.Float(string='Passing Score Threshold (%)', default=70.0, required=True)

    # Assessment Linkage (FR-LMS-012, FR-LMS-013)
    has_pre_assessment = fields.Boolean(string='Requires Pre-Course Diagnostic Assessment', default=False)
    pre_assessment_id = fields.Many2one('lms.assessment', string='Pre-Course Diagnostic Assessment')

    has_post_assessment = fields.Boolean(string='Requires Post-Course Final Assessment', default=True)
    post_assessment_id = fields.Many2one('lms.assessment', string='Post-Course Final Assessment')

    # Certification Configuration (FR-LMS-018, FR-LMS-019, FR-LMS-020)
    issue_certificate = fields.Boolean(string='Issue Certificate on Completion', default=True)
    certificate_template_id = fields.Many2one('lms.certificate.template', string='Certificate Template')
    certificate_validity_months = fields.Integer(
        string='Certificate Validity (Months)',
        default=12,
        help='0 for lifetime / no expiry. Standard compliance certifications typically expire in 12 or 24 months.'
    )

    # Lifecycle State Machine
    state = fields.Selection([
        ('draft', 'Draft Shell'),
        ('review', 'Under Review & Approval'),
        ('published', 'Published & Active'),
        ('archived', 'Archived / Superseded'),
    ], string='Course Status', default='draft', tracking=True, required=True, index=True)

    # Versioning (FR-LMS-011)
    version = fields.Char(string='Version', default='1.0', required=True)
    is_latest_version = fields.Boolean(string='Latest Active Version', default=True)
    previous_version_id = fields.Many2one('lms.course', string='Superseded Version', readonly=True, copy=False)
    revision_notes = fields.Text(string='Revision Changelog')

    # Structure: Sections and Lessons
    section_ids = fields.One2many('lms.course.section', 'course_id', string='Course Curriculum Sections')
    lesson_ids = fields.One2many('lms.lesson', 'course_id', string='All Lessons')
    library_item_ids = fields.Many2many(
        'kms.digital.library', 'lms_kms_library_course_rel', 'course_id', 'library_id',
        string='Related Library Resources',
    )
    total_lessons = fields.Integer(string='Total Lessons Count', compute='_compute_lesson_stats', store=True)
    total_duration_minutes = fields.Float(string='Total Duration (Minutes)', compute='_compute_lesson_stats', store=True)

    # Enrollments & Analytics
    enrollment_ids = fields.One2many('lms.enrollment', 'course_id', string='Enrollments')
    total_enrolled = fields.Integer(string='Enrolled Learners', compute='_compute_enrollment_stats')
    total_completed = fields.Integer(string='Completed Learners', compute='_compute_enrollment_stats')
    completion_rate = fields.Float(string='Completion Rate (%)', compute='_compute_enrollment_stats')

    instructor_id = fields.Many2one(
        'hr.employee',
        string='Lead Instructor / Course Owner',
        required=True,
        default=lambda self: self.env.user.employee_id
    )
    reviewer_id = fields.Many2one(
        'res.users', string='Assigned Approval Reviewer', tracking=True, copy=False,
        help='An LMS manager who receives the course approval activity.'
    )

    active = fields.Boolean(default=True)

    _revision_fields = frozenset({
        'name', 'code', 'category_id', 'description', 'learning_objectives', 'cover_image',
        'target_department_ids', 'target_job_ids', 'target_grade_ids',
        'competency_ids', 'is_mandatory', 'estimated_duration_hours',
        'pass_score_percentage', 'has_pre_assessment', 'pre_assessment_id',
        'has_post_assessment', 'post_assessment_id', 'issue_certificate',
        'certificate_template_id', 'certificate_validity_months', 'version',
        'previous_version_id', 'revision_notes', 'section_ids', 'lesson_ids',
        'library_item_ids', 'library_resource_ids', 'instructor_id',
        'reviewer_id', 'active', 'sequence',
    })

    def _validate_for_publication(self):
        """Check the actual material, not just the presence of curriculum rows."""
        for rec in self:
            if not rec.lesson_ids:
                raise UserError(_('Add at least one lesson before publishing.'))
            if not rec.description or not rec.description.strip():
                raise UserError(_('Add a course description before publishing.'))
            if not 0 < rec.pass_score_percentage <= 100:
                raise UserError(_('Course passing score must be between 0 and 100 percent.'))
            if rec.has_post_assessment and not rec.post_assessment_id:
                raise UserError(_('Configure the post-course assessment before publishing.'))
            if rec.has_pre_assessment and not rec.pre_assessment_id:
                raise UserError(_('Configure the pre-course assessment before publishing.'))
            for assessment, expected_type in (
                (rec.pre_assessment_id if rec.has_pre_assessment else False, 'pre_course'),
                (rec.post_assessment_id if rec.has_post_assessment else False, 'post_course'),
            ):
                if assessment:
                    if assessment.course_id != rec or assessment.assessment_type != expected_type:
                        raise UserError(_('An assessment must belong to this course and have the correct type.'))
                    assessment._validate_for_publication()
            for lesson in rec.lesson_ids:
                lesson._validate_for_publication()

    def _validate_reviewer(self):
        for rec in self:
            reviewer = rec.reviewer_id
            if not reviewer or not reviewer.active or not reviewer.has_group('learning_management.group_lms_manager'):
                raise UserError(_('Choose an active LMS manager as the approval reviewer.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('state', 'draft') != 'draft' and not self.env.su:
                raise AccessError(_('New courses must start as drafts.'))
            if vals.get('code', _('New')) == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('lms.course') or _('New')
        return super(LmsCourse, self).create(vals_list)

    def write(self, vals):
        if (not self.env.su and vals.get('state') == 'published'
                and self._revision_fields.intersection(vals)):
            raise UserError(_('Publish the reviewed content without changing it in the approval action.'))
        if not self.env.su and self._revision_fields.intersection(vals):
            for rec in self:
                if rec.state in ('review', 'published', 'archived'):
                    raise UserError(_('Return a review to draft, or create a new revision to edit published course content.'))
        if 'is_latest_version' in vals and not (
            self.env.su or self.env.user.has_group('learning_management.group_lms_manager')
        ):
            raise AccessError(_('Only LMS managers may change course version visibility.'))
        if (not self.env.su and 'is_latest_version' in vals
                and vals.get('state') != 'archived'
                and any(rec.state in ('published', 'archived') for rec in self)):
            raise UserError(_('Version visibility changes when a course is archived or superseded.'))
        target = vals.get('state')
        publishing = self.filtered(lambda rec: rec.state != 'published') if target == 'published' else self.browse()
        if target in ('published', 'archived') and not (
            self.env.su or self.env.user.has_group('learning_management.group_lms_manager')
        ):
            raise AccessError(_('Only LMS managers can publish or archive courses.'))
        if target:
            # Serialize competing revisions of the same predecessor before
            # checking whether another successor has already gone live.
            if publishing:
                predecessor_ids = [rec.previous_version_id.id for rec in publishing if rec.previous_version_id]
                if len(predecessor_ids) != len(set(predecessor_ids)):
                    raise UserError(_('Publish one revision of a course at a time.'))
                for predecessor_id in sorted(predecessor_ids):
                    self.env.cr.execute('SELECT id FROM lms_course WHERE id = %s FOR UPDATE', (predecessor_id,))
                publishing.mapped('previous_version_id').invalidate_recordset(['state', 'is_latest_version'])
            allowed = {
                'draft': {'review'}, 'review': {'draft', 'published'},
                'published': {'archived'}, 'archived': set(),
            }
            for rec in self:
                if target != rec.state and target not in allowed.get(rec.state, set()):
                    raise UserError(_('Invalid course transition: %s to %s.') % (rec.state, target))
                if target == 'published':
                    predecessor = rec.previous_version_id
                    if predecessor:
                        if predecessor == rec:
                            raise UserError(_('A course cannot supersede itself.'))
                        if self.sudo().search_count([
                            ('previous_version_id', '=', predecessor.id),
                            ('state', '=', 'published'), ('id', '!=', rec.id),
                        ]):
                            raise UserError(_('Another revision of this course has already been published.'))
                    if not self.env.su:
                        rec._validate_reviewer()
                        if rec.reviewer_id != self.env.user:
                            raise AccessError(_('Only the assigned reviewer may approve this course.'))
                    rec._validate_for_publication()
                if target == 'review' and not self.env.su:
                    rec._validate_reviewer()
            if target == 'published':
                vals = dict(vals, is_latest_version=True)
            elif target == 'archived':
                vals = dict(vals, is_latest_version=False)
        result = super(LmsCourse, self).write(vals)
        if publishing:
            for rec in publishing:
                predecessor = rec.previous_version_id
                if predecessor and predecessor.state != 'archived':
                    predecessor.write({'state': 'archived', 'is_latest_version': False})
                    predecessor.message_post(body=_(
                        'Course superseded by new version %s (v%s) and archived from learner self-service.'
                    ) % (rec.code, rec.version))
        return result

    def unlink(self):
        if not self.env.su and any(rec.state != 'draft' for rec in self):
            raise UserError(_('Reviewed and published courses must be retained for the learning record.'))
        return super().unlink()

    @api.depends('lesson_ids', 'lesson_ids.duration_minutes')
    def _compute_lesson_stats(self):
        for rec in self:
            rec.total_lessons = len(rec.lesson_ids)
            rec.total_duration_minutes = sum(l.duration_minutes for l in rec.lesson_ids)

    def _compute_enrollment_stats(self):
        counts = {}
        if self.ids:
            for course, state, count in self.env['lms.enrollment']._read_group(
                [('course_id', 'in', self.ids)], ['course_id', 'state'], ['__count']
            ):
                bucket = counts.setdefault(course.id, {'enrolled': 0, 'completed': 0})
                bucket['enrolled'] += count
                if state == 'completed':
                    bucket['completed'] += count
        for rec in self:
            enrolled = counts.get(rec.id, {}).get('enrolled', 0)
            completed = counts.get(rec.id, {}).get('completed', 0)
            rec.total_enrolled = enrolled
            rec.total_completed = completed
            rec.completion_rate = (completed / float(enrolled) * 100.0) if enrolled > 0 else 0.0

    # Lifecycle Actions
    def action_submit_for_review(self):
        manager_group = self.env.ref('learning_management.group_lms_manager')
        todo = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft courses can be submitted.'))
            if not rec.lesson_ids:
                raise UserError(_('Please add at least one lesson before submitting this course for review.'))
            reviewer = rec.reviewer_id
            if not reviewer:
                reviewer = self.env.user if (
                    not self.env.su and self.env.user.has_group('learning_management.group_lms_manager')
                ) else self.env['res.users'].search([
                    ('group_ids', 'in', manager_group.id), ('active', '=', True),
                ], order='id', limit=1)
            if not reviewer or not reviewer.active or not reviewer.has_group('learning_management.group_lms_manager'):
                raise UserError(_('Choose an active LMS manager as the approval reviewer.'))
            rec.reviewer_id = reviewer
            rec.write({'state': 'review'})
            rec.message_post(
                body=_('Course submitted to %s for quality review and publication approval.') % reviewer.name,
                partner_ids=reviewer.partner_id.ids,
            )
            if todo and not rec.activity_ids.filtered(
                lambda activity: activity.user_id == reviewer and activity.activity_type_id == todo
            ):
                rec.activity_schedule(
                    activity_type_id=todo.id,
                    summary=_('Review course for publication: %s') % rec.name,
                    user_id=reviewer.id,
                )

    def action_publish(self):
        for rec in self:
            if rec.state != 'review':
                raise UserError(_('Only reviewed courses can be published.'))
            rec.write({'state': 'published', 'is_latest_version': True})
            rec.message_post(body=_('Course approved and published. Now active on learner dashboards.'))

    def action_return_draft(self):
        self.write({'state': 'draft'})

    def action_archive(self):
        self.write({'state': 'archived', 'is_latest_version': False})

    def action_create_new_version(self):
        """Creates an updated course version and archives older for historical audit (FR-LMS-011)."""
        self.ensure_one()
        if self.state != 'published':
            raise UserError(_('Only published courses can be revised.'))
        current_ver = self.version or '1.0'
        try:
            parts = current_ver.split('.')
            new_ver = f"{parts[0]}.{int(parts[1]) + 1}" if len(parts) == 2 else f"{current_ver}.1"
        except Exception:
            new_ver = f"{current_ver}-rev"

        new_course = self.copy({
            'name': self.name,
            'version': new_ver,
            'state': 'draft',
            'previous_version_id': self.id,
            'revision_notes': _('Revision based on %s (v%s)') % (self.code, self.version),
            'is_latest_version': False,
        })
        assessment_map = {}
        question_map = {}
        pool_map = {}
        assessments = self.pre_assessment_id | self.post_assessment_id | self.lesson_ids.mapped('assessment_id')
        for assessment in assessments:
            revised = assessment.copy({
                'course_id': new_course.id,
                'fixed_question_ids': [(5, 0, 0)],
                'pool_ids': [(5, 0, 0)],
            })
            assessment_map[assessment.id] = revised.id
            for pool in assessment.pool_ids:
                if pool.id not in pool_map:
                    pool_map[pool.id] = pool.copy({'question_ids': []})
                for question in pool.question_ids:
                    if question.id not in question_map:
                        question_map[question.id] = question.copy({
                            'pool_id': pool_map[pool.id].id, 'answer_ids': [],
                        })
                        for answer in question.answer_ids:
                            answer.copy({'question_id': question_map[question.id].id})
            for question in assessment.fixed_question_ids:
                if question.id not in question_map:
                    question_map[question.id] = question.copy({'pool_id': False, 'answer_ids': []})
                    for answer in question.answer_ids:
                        answer.copy({'question_id': question_map[question.id].id})
            revised.write({
                'pool_ids': [(6, 0, [pool_map[pool.id].id for pool in assessment.pool_ids])],
                'fixed_question_ids': [(6, 0, [question_map[q.id].id for q in assessment.fixed_question_ids])],
            })
        new_course.write({
            'pre_assessment_id': assessment_map.get(self.pre_assessment_id.id, False),
            'post_assessment_id': assessment_map.get(self.post_assessment_id.id, False),
        })
        # A revision must carry its curriculum; One2many records are not copied
        # automatically by the ORM.
        section_map = {}
        for section in self.section_ids:
            section_map[section.id] = section.copy({'course_id': new_course.id}).id
        for lesson in self.lesson_ids:
            lesson.copy({
                'course_id': new_course.id,
                'section_id': section_map.get(lesson.section_id.id, False),
                'assessment_id': assessment_map.get(lesson.assessment_id.id, False),
            })
        self.message_post(body=_('Initiated new course version: %s (v%s)') % (new_course.code, new_ver))
        return {
            'name': _('Course Revision'),
            'type': 'ir.actions.act_window',
            'res_model': 'lms.course',
            'view_mode': 'form',
            'res_id': new_course.id,
            'target': 'current',
        }

    def action_view_enrollments(self):
        self.ensure_one()
        return {
            'name': _('Course Enrollments - %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'lms.enrollment',
            'view_mode': 'list,form',
            'domain': [('course_id', '=', self.id)],
            'context': {'default_course_id': self.id},
        }

    def action_view_completed_enrollments(self):
        self.ensure_one()
        action = self.action_view_enrollments()
        action['name'] = _('Completed Enrollments - %s') % self.name
        action['domain'] = [('course_id', '=', self.id), ('state', '=', 'completed')]
        return action


class LmsCourseSection(models.Model):
    """Syllabus Chapter / Section within a course."""
    _name = 'lms.course.section'
    _description = 'Course Curriculum Section'
    _order = 'course_id, sequence, id'

    name = fields.Char(string='Section Title', required=True)
    sequence = fields.Integer(string='Order Sequence', default=10)
    course_id = fields.Many2one('lms.course', string='Course', required=True, ondelete='cascade', index=True)
    lesson_ids = fields.One2many('lms.lesson', 'section_id', string='Lessons in Section')
    description = fields.Text(string='Section Overview')

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            for vals in vals_list:
                course = self.env['lms.course'].browse(vals.get('course_id'))
                if course.state != 'draft':
                    raise UserError(_('Curriculum sections can only be added to draft courses.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            target = self.env['lms.course'].browse(vals['course_id']) if vals.get('course_id') else False
            if any(rec.course_id.state != 'draft' or (target and target.state != 'draft') for rec in self):
                raise UserError(_('Return the course to draft or create a revision to edit sections.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.su and any(rec.course_id.state != 'draft' for rec in self):
            raise UserError(_('Published curriculum sections cannot be deleted.'))
        return super().unlink()


class LmsLesson(models.Model):
    """
    Modular Lesson Component (FR-LMS-004 to FR-LMS-009).
    Supports internal video hosting (stored file or streaming URL), PDF slide decks, rich HTML text, and quiz gates.
    Enforces anti-skip restrictions and completion percentages.
    """
    _name = 'lms.lesson'
    _description = 'Course Lesson / Module'
    _order = 'course_id, section_id, sequence, id'

    name = fields.Char(string='Lesson Title', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    course_id = fields.Many2one('lms.course', string='Course', required=True, ondelete='cascade', index=True)
    section_id = fields.Many2one('lms.course.section', string='Curriculum Section', ondelete='cascade', domain="[('course_id', '=', course_id)]")

    lesson_type = fields.Selection([
        ('video', 'Internal Video Lesson'),
        ('document', 'Document / PDF Slide Deck'),
        ('text', 'Rich Text Article / Guide'),
        ('quiz', 'Assessment / Quiz Gate'),
    ], string='Content Format', required=True, default='video')

    is_mandatory = fields.Boolean(
        string='Mandatory Lesson',
        default=True,
        help='Learner must complete this lesson to advance to subsequent lessons or final assessment.'
    )
    duration_minutes = fields.Float(string='Estimated Duration (Minutes)', default=10.0)

    # Video Hosting & Control Mechanisms (FR-LMS-004 to FR-LMS-008)
    video_source_type = fields.Selection([
        ('file', 'Direct Video File Upload (Internal Storage)'),
        ('url', 'Internal Media Server / Stream URL'),
    ], string='Video Hosting Source', default='file')

    video_file = fields.Binary(
        string='Video File (MP4/WebM)', attachment=True,
        groups='learning_management.group_lms_instructor',
    )
    video_filename = fields.Char(string='Video Filename')
    video_url = fields.Char(
        string='Internal Streaming Endpoint URL',
        help='https://media.bunnabanksc.com/videos/aml_part1.mp4',
        groups='learning_management.group_lms_instructor',
    )
    video_duration_seconds = fields.Integer(
        string='Video Length (Seconds)',
        default=0,
        help='Enter the actual media duration before publishing. This value controls watch credit and lesson completion.',
    )

    prevent_fast_forward = fields.Boolean(
        string='Prevent Fast-Forward / Seeking',
        default=True,
        help='Anti-Cheat: Disables seeking ahead on progress bar until video is fully watched (FR-LMS-008).'
    )
    min_watch_percentage = fields.Float(
        string='Minimum Watch Percentage Required (%)',
        default=90.0,
        help='Percentage of video duration the learner must watch before lesson is credited as complete.'
    )

    # Document / Slide Material
    document_file = fields.Binary(
        string='Slide Deck / PDF Document', attachment=True,
        groups='learning_management.group_lms_instructor',
    )
    document_filename = fields.Char(string='Document Filename')

    # Rich Text Material
    html_content = fields.Html(string='Lesson Article & Reading Content')

    # Assessment Gate Linkage (FR-LMS-012)
    assessment_id = fields.Many2one('lms.assessment', string='Linked Assessment / Quiz')

    _min_watch_percentage_range = models.Constraint(
        'CHECK(min_watch_percentage >= 0 AND min_watch_percentage <= 100)',
        'Minimum watch percentage must be between 0% and 100%!'
    )

    def _validate_for_publication(self):
        for lesson in self:
            if lesson.section_id and lesson.section_id.course_id != lesson.course_id:
                raise UserError(_('A lesson section must belong to the same course.'))
            if lesson.lesson_type == 'video':
                if lesson.video_source_type == 'file' and not lesson.video_file:
                    raise UserError(_('Upload a video for lesson "%s" before publishing.') % lesson.name)
                if lesson.video_source_type == 'url' and not lesson.video_url:
                    raise UserError(_('Add a video URL for lesson "%s" before publishing.') % lesson.name)
                if lesson.video_source_type == 'url':
                    allowed_hosts = self.env['ir.config_parameter'].sudo().get_param(
                        'learning_management.media_allowed_hosts', ''
                    )
                    if not external_media_url_allowed(lesson.video_url, allowed_hosts):
                        raise UserError(_(
                            'Configure an approved HTTPS internal media host for lesson "%s" before publishing.'
                        ) % lesson.name)
                if lesson.video_duration_seconds <= 0:
                    raise UserError(_('Enter the actual video duration in seconds for lesson "%s" before publishing.') % lesson.name)
            elif lesson.lesson_type == 'document' and not lesson.document_file:
                raise UserError(_('Upload a document for lesson "%s" before publishing.') % lesson.name)
            elif lesson.lesson_type == 'text' and not lesson.html_content:
                raise UserError(_('Add reading content for lesson "%s".') % lesson.name)
            elif lesson.lesson_type == 'quiz':
                assessment = lesson.assessment_id
                if (not assessment or assessment.course_id != lesson.course_id
                        or assessment.assessment_type != 'module_quiz'):
                    raise UserError(_('Link quiz lesson "%s" to a module quiz in this course.') % lesson.name)
                assessment._validate_for_publication()

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            for vals in vals_list:
                course = self.env['lms.course'].browse(vals.get('course_id'))
                if course.state != 'draft':
                    raise UserError(_('Lessons can only be added to draft courses.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            target = self.env['lms.course'].browse(vals['course_id']) if vals.get('course_id') else False
            if any(rec.course_id.state != 'draft' or (target and target.state != 'draft') for rec in self):
                raise UserError(_('Return the course to draft or create a revision to edit lessons.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.su and any(rec.course_id.state != 'draft' for rec in self):
            raise UserError(_('Published lessons cannot be deleted.'))
        return super().unlink()

    def action_open_document(self):
        self.ensure_one()
        if self.lesson_type != 'document':
            raise UserError(_('This lesson does not contain a document.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/lms/lesson/%s/document' % self.id,
            'target': 'new',
        }
