# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError, AccessError


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

    active = fields.Boolean(default=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('state', 'draft') != 'draft' and not self.env.su:
                raise AccessError(_('New courses must start as drafts.'))
            if vals.get('code', _('New')) == _('New'):
                vals['code'] = self.env['ir.sequence'].next_by_code('lms.course') or _('New')
        return super(LmsCourse, self).create(vals_list)

    def write(self, vals):
        target = vals.get('state')
        if target:
            allowed = {
                'draft': {'review'}, 'review': {'draft', 'published'},
                'published': {'review', 'archived'}, 'archived': set(),
            }
            for rec in self:
                if target != rec.state and target not in allowed.get(rec.state, set()):
                    raise UserError(_('Invalid course transition: %s to %s.') % (rec.state, target))
                if target == 'published' and not rec.lesson_ids:
                    raise UserError(_('Add at least one lesson before publishing.'))
                if target == 'published' and rec.has_post_assessment and not rec.post_assessment_id:
                    raise UserError(_('Configure the post-course assessment before publishing.'))
                if target == 'published' and rec.has_pre_assessment and not rec.pre_assessment_id:
                    raise UserError(_('Configure the pre-course assessment before publishing.'))
            if target in ('published', 'archived') and not (
                self.env.su or self.env.user.has_group('learning_management.group_lms_manager')
            ):
                raise AccessError(_('Only LMS managers can publish or archive courses.'))
            if target == 'published':
                vals = dict(vals, is_latest_version=True)
            elif target == 'archived':
                vals = dict(vals, is_latest_version=False)
        return super(LmsCourse, self).write(vals)

    @api.depends('lesson_ids', 'lesson_ids.duration_minutes')
    def _compute_lesson_stats(self):
        for rec in self:
            rec.total_lessons = len(rec.lesson_ids)
            rec.total_duration_minutes = sum(l.duration_minutes for l in rec.lesson_ids)

    def _compute_enrollment_stats(self):
        for rec in self:
            enrolled = len(rec.enrollment_ids)
            completed = len(rec.enrollment_ids.filtered(lambda e: e.state == 'completed'))
            rec.total_enrolled = enrolled
            rec.total_completed = completed
            rec.completion_rate = (completed / float(enrolled) * 100.0) if enrolled > 0 else 0.0

    # Lifecycle Actions
    def action_submit_for_review(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft courses can be submitted.'))
            if not rec.lesson_ids:
                raise UserError(_('Please add at least one lesson before submitting this course for review.'))
            rec.write({'state': 'review'})
            rec.message_post(body=_('Course submitted for quality review and publication approval.'))

    def action_publish(self):
        for rec in self:
            if rec.state != 'review':
                raise UserError(_('Only reviewed courses can be published.'))
            rec.write({'state': 'published', 'is_latest_version': True})
            # FR-LMS-011: Automatically retire/archive superseded version so learners cannot self-enroll/view older version
            if rec.previous_version_id and rec.previous_version_id.state != 'archived':
                rec.previous_version_id.write({'state': 'archived', 'is_latest_version': False})
                rec.previous_version_id.message_post(body=_('Course superseded by new version %s (v%s) and archived from learner self-service.') % (rec.code, rec.version))
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
        assessments = self.pre_assessment_id | self.post_assessment_id | self.lesson_ids.mapped('assessment_id')
        for assessment in assessments:
            assessment_map[assessment.id] = assessment.copy({'course_id': new_course.id}).id
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
    video_url = fields.Char(string='Internal Streaming Endpoint URL', help='https://media.bunnabanksc.com/videos/aml_part1.mp4')
    video_duration_seconds = fields.Integer(string='Video Length (Seconds)', default=600)

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

    def action_open_document(self):
        self.ensure_one()
        if self.lesson_type != 'document':
            raise UserError(_('This lesson does not contain a document.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/lms/lesson/%s/document' % self.id,
            'target': 'new',
        }
