# -*- coding: utf-8 -*-
"""Attendance and delivery tracking.

Delivery-time records managed by L&D staff:
  - eds.session.attendance   per-participant attendance with computed per-program %
                             (feeds the 80% certification rule)
  - eds.material             course training material with quality review +
                             Director PPDD approval gate
  - eds.feedback             daily participant feedback lines
  - eds.assessment           pre/post assessment scores (shared with  L1/L2)
  - eds.international.training + .travel.line / .report   international flow with
                             entitlement validation (service years) and travel
                             arrangements
"""
import base64
import binascii
from datetime import date
from pathlib import PurePath
from urllib.parse import urlparse

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from .eds_action_notification import clear_action_activities, notify_action, notify_role_action
from .eds_employee_projection import safe_employee_web_read


_EDS_ALLOWED_FILE_EXTENSIONS = {
    '.pdf', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tiff', '.tif', '.svg',
}
_MATERIAL_FILE_EXTENSIONS = {
    'manual': _EDS_ALLOWED_FILE_EXTENSIONS,
    'presentation': _EDS_ALLOWED_FILE_EXTENSIONS,
    'handout': _EDS_ALLOWED_FILE_EXTENSIONS,
    'case_study': _EDS_ALLOWED_FILE_EXTENSIONS,
    'examination': _EDS_ALLOWED_FILE_EXTENSIONS,
    'other': _EDS_ALLOWED_FILE_EXTENSIONS,
}


class EdsSessionAttendance(models.Model):
    """Per-participant attendance on a session.

    `attendance_percentage` is computed for this session's scheduled periods
    so another delivery of the same course cannot affect certification
    (default >= 80%). Immutable after recording: the model is wired into
    the `audit_trail` module (data/eds_audit_rules.xml) so any later edit is
    logged with user / old value / new value (business rule §6).
    """
    _name = 'eds.session.attendance'
    _description = 'Session Attendance Record'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'session_id, attendance_date, attendance_slot, employee_id'
    _rec_name = 'name'

    def web_read(self, specification):
        return safe_employee_web_read(
            self, specification, super().web_read, ('employee_id',))

    _track_audit = True  # documented intent; enforced via audit.rule in data/

    name = fields.Char(string='Reference', required=True, readonly=True, copy=False,
                       default=lambda self: _('New'))
    session_id = fields.Many2one('eds.session', string='Session', required=True,
                                 ondelete='cascade', index=True, tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Participant', required=True,
                                  index=True, tracking=True)
    job_position_id = fields.Many2one('hr.job', string='Job Position',
                                      related='employee_id.job_position', readonly=True)
    department_id = fields.Many2one('hr.department', string='Department',
                                    related='employee_id.department_id', readonly=True)
    attendance_date = fields.Date(string='Attendance Date', default=fields.Date.context_today,
                                  index=True)
    attendance_slot = fields.Selection([
        ('day', 'Daily'), ('morning', 'Morning'), ('afternoon', 'Afternoon'),
    ], string='Period', default='day', required=True, index=True)
    attended = fields.Boolean(string='Present', default=False, tracking=True)
    hours_attended = fields.Float(
        string='Hours Attended', compute='_compute_hours_attended', store=True,
        readonly=True, help='Calculated from the session timetable when present.')
    notes = fields.Text(string='Notes')
    recorded_by = fields.Many2one('res.users', string='Recorded By',
                                  default=lambda self: self.env.user, readonly=True,
                                  copy=False)
    attendance_percentage = fields.Float(
        string='Session Attendance %', compute='_compute_program_attendance', store=True,
        digits=(5, 2),
        help='Present periods / scheduled periods of this session for the participant.')
    meets_min_attendance = fields.Boolean(
        string='Meets Minimum Attendance', compute='_compute_program_attendance', store=True,
        help='True when this session attendance meets the configured minimum '
             '(default 80%).')
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)

    _session_employee_date_slot_uniq = models.Constraint(
        'UNIQUE(session_id, employee_id, attendance_date, attendance_slot)',
        'Attendance is already recorded for this participant in this session period!',
    )

    @api.onchange('session_id')
    def _onchange_session_attendance_period(self):
        for rec in self:
            if rec.session_id:
                slots = rec.session_id._attendance_slots()
                if slots:
                    rec.attendance_date, rec.attendance_slot = slots[0][:2]

    @api.constrains('session_id', 'attendance_date', 'attendance_slot')
    def _check_attendance_slot(self):
        slots_by_session = {}
        for rec in self:
            if not rec.session_id:
                continue
            if rec.session_id.id not in slots_by_session:
                slots_by_session[rec.session_id.id] = {
                    (day, slot) for day, slot, _hours in rec.session_id._attendance_slots()}
            if (rec.attendance_date, rec.attendance_slot) not in slots_by_session[rec.session_id.id]:
                raise ValidationError(_(
                    'Choose a date and period scheduled for this training session.'))

    @api.depends('attended', 'attendance_date', 'attendance_slot',
                 'session_id.date_start', 'session_id.date_end', 'session_id.attendance_mode')
    def _compute_hours_attended(self):
        slots_by_session = {}
        for rec in self:
            if rec.session_id.id not in slots_by_session:
                slots_by_session[rec.session_id.id] = {
                    (day, slot): hours for day, slot, hours in rec.session_id._attendance_slots()}
            rec.hours_attended = (
                slots_by_session[rec.session_id.id].get(
                    (rec.attendance_date, rec.attendance_slot), 0.0)
                if rec.attended else 0.0)

    @api.constrains('session_id', 'employee_id')
    def _check_employee_enrolled(self):
        for rec in self:
            if rec.session_id and rec.employee_id:
                enrolled_emps = rec.session_id._accepted_attendance_enrollments().mapped(
                    'employee_id')
                if rec.employee_id not in enrolled_emps:
                    raise ValidationError(_(
                        'Participant Error: Employee %s is not an enrolled participant in session %s.'
                    ) % (rec.employee_id.sudo().name, rec.session_id.name))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.session.attendance') or _('New')
        records = super().create(vals_list)
        if not self.env.context.get('eds_defer_attendance_refresh'):
            records._refresh_program_attendance()
            records.mapped('session_id')._sync_attendance_summaries()
        return records

    def write(self, vals):
        watched = {'session_id', 'employee_id', 'attended', 'attendance_date', 'attendance_slot'}
        refresh = bool(watched & vals.keys()) and not self.env.context.get(
            'eds_defer_attendance_refresh')
        old_sessions = self.mapped('session_id') if refresh else self.env['eds.session']
        before = ({(row.employee_id.id, row.session_id.id) for row in self}
                  if refresh else set())
        result = super().write(vals)
        if before:
            after = {(row.employee_id.id, row.session_id.id) for row in self}
            self._refresh_program_attendance(before | after)
            (old_sessions | self.mapped('session_id'))._sync_attendance_summaries()
        return result

    def unlink(self):
        sessions = self.mapped('session_id')
        pairs = {(row.employee_id.id, row.session_id.id) for row in self}
        result = super().unlink()
        self._refresh_program_attendance(pairs)
        if sessions:
            sessions._sync_attendance_summaries()
        return result

    def action_delete_record(self):
        """Delete this individual attendance record."""
        self.ensure_one()
        self.check_access('read')
        session = self.session_id
        session._require_ld_delivery_access()
        session.check_access('write')
        emp_name = self.employee_id.sudo().name
        # Attendance deletion belongs to the authorized session workflow.
        # Do not grant broad unlink access to the attendance model.
        self.sudo().unlink()
        return {
            'type': 'ir.actions.client',
            'tag': 'bunna_refresh_form',
            'params': {
                'res_model': session._name,
                'res_id': session.id,
                'title': _('Attendance Record Deleted'),
                'message': _('Attendance record for %s has been deleted.') % emp_name,
                'type': 'success',
            }
        }

    def _refresh_program_attendance(self, pairs=None):
        pairs = pairs or {(row.employee_id.id, row.session_id.id) for row in self}
        pairs = {(employee_id, session_id) for employee_id, session_id in pairs
                 if employee_id and session_id}
        if not pairs:
            return
        candidates = self.search([
            ('employee_id', 'in', list({employee_id for employee_id, _session_id in pairs})),
            ('session_id', 'in', list({session_id for _employee_id, session_id in pairs})),
        ])
        candidates.filtered(
            lambda row: (row.employee_id.id, row.session_id.id) in pairs
        )._compute_program_attendance()

    @api.depends('session_id', 'employee_id', 'attended', 'attendance_date', 'attendance_slot',
                 'session_id.date_start', 'session_id.date_end', 'session_id.attendance_mode')
    def _compute_program_attendance(self):
        """Attendance percentage for this session's scheduled periods."""
        threshold = self._get_float_param('eds.min_attendance_pct', 80.0)
        valid_recs = self.filtered(lambda r: r.session_id and r.employee_id)
        if not valid_recs:
            for rec in self:
                rec.attendance_percentage = 0.0
                rec.meets_min_attendance = False
            return

        pairs = {(r.employee_id.id, r.session_id.id) for r in valid_recs}
        periods_by_session = {
            session.id: len(session._attendance_slots())
            for session in valid_recs.mapped('session_id')
        }
        all_records = self.search([
            ('employee_id', 'in', list({employee_id for employee_id, _session_id in pairs})),
            ('session_id', 'in', list({session_id for _employee_id, session_id in pairs})),
        ])
        counts = {}
        for r in all_records:
            key = (r.employee_id.id, r.session_id.id)
            if key not in pairs:
                continue
            tot, att = counts.get(key, (0, 0))
            counts[key] = (tot + 1, att + (1 if r.attended else 0))

        for rec in self:
            if not rec.session_id or not rec.employee_id:
                rec.attendance_percentage = 0.0
                rec.meets_min_attendance = False
                continue
            recorded, present = counts.get((rec.employee_id.id, rec.session_id.id), (0, 0))
            scheduled = periods_by_session[rec.session_id.id]
            total = max(recorded, scheduled)
            rec.attendance_percentage = round(present * 100.0 / total, 2) if total else 0.0
            rec.meets_min_attendance = bool(total) and rec.attendance_percentage >= threshold

    @api.model
    def _get_float_param(self, key, default):
        try:
            return float(self.env['ir.config_parameter'].sudo().get_param(key, str(default)))
        except ValueError:
            return default


class EdsSessionAttendanceSummary(models.Model):
    """Aggregated attendance summary per participant for a session."""
    _name = 'eds.session.attendance.summary'
    _description = 'Participant Attendance Summary & Report'
    _order = 'session_id, employee_id'
    _rec_name = 'employee_id'

    def web_read(self, specification):
        return safe_employee_web_read(
            self, specification, super().web_read, ('employee_id',))

    session_id = fields.Many2one('eds.session', string='Session', required=True,
                                 ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', string='Participant', required=True,
                                  index=True)
    department_id = fields.Many2one('hr.department', string='Department',
                                    related='employee_id.department_id', readonly=True)
    job_position_id = fields.Many2one('hr.job', string='Job Position',
                                      related='employee_id.job_position', readonly=True)
    work_unit_id = fields.Many2one('operating.unit', string='Work Unit',
                                   related='employee_id.default_operating_unit_id', readonly=True)
    total_slots = fields.Integer(string='Total Sessions / Slots', readonly=True,
                                 help='Total scheduled attendance sessions or slots.')
    present_count = fields.Integer(string='Present Count', readonly=True,
                                   help='Number of sessions/slots marked present.')
    absent_count = fields.Integer(string='Absent Count', readonly=True,
                                   help='Number of recorded sessions/slots marked absent.')
    unrecorded_count = fields.Integer(string='Unrecorded Count', readonly=True,
                                      help='Scheduled sessions/slots with no attendance mark yet.')
    attendance_percentage = fields.Float(string='Attendance %', digits=(5, 2), readonly=True,
                                         help='Percentage of scheduled sessions attended.')
    min_threshold = fields.Float(string='Required %', default=80.0, readonly=True)
    meets_min_attendance = fields.Boolean(string='Meets Minimum Attendance', readonly=True,
                                          help='True if attendance percentage meets or exceeds the required threshold.')
    status = fields.Selection([
        ('meets', 'Meets Minimum'),
        ('below', 'Below Minimum'),
    ], string='Status', readonly=True)
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)

    _session_employee_uniq = models.Constraint(
        'UNIQUE(session_id, employee_id)',
        'Summary already exists for this participant in this session!',
    )

class EdsMaterial(models.Model):
    """Course material shared through a scheduled session with its audience."""
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
    visibility = fields.Selection([
        ('staff', 'L&D Staff Only'),
        ('trainers', 'Assigned Trainers and L&D'),
        ('participants', 'Accepted Participants, Assigned Trainers and L&D'),
    ], string='Who Can Open', default='participants', required=True, tracking=True,
        help='Accepted participants see shared materials in their training invitation after the session is scheduled. Assigned trainers see trainer and participant materials on their session. L&D can see all materials.')
    source_kind = fields.Selection([
        ('attachment', 'Upload to EDS'),
        ('link', 'Managed Link (LMS / Internal)'),
    ], string='Content Source', default='attachment', required=True, tracking=True,
        help='Upload documents and slides to EDS, or link to content already managed in LMS or another bank system. Videos use links.')
    document = fields.Binary(string='Material File (PDF or Image)', attachment=True)
    filename = fields.Char(string='Filename')
    resource_url = fields.Char(
        string='Managed Resource URL', tracking=True,
        help='Use a full http(s) URL or an internal path such as /lms/lesson/123/document or /lms/video/123/player. Access to linked content remains controlled by its source system.')
    description = fields.Text(string='Description')

    # Two-stage gate: L&D quality review first, then Director PPDD.
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
             'PPDD approval is granted - the session confirmation gate.')

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

    @api.onchange('material_type')
    def _onchange_material_type(self):
        if self.material_type == 'video':
            self.source_kind = 'link'
            self.document = False
            self.filename = False
        elif self.material_type == 'examination':
            self.visibility = 'staff'

    @api.onchange('source_kind')
    def _onchange_source_kind(self):
        if self.source_kind == 'link':
            self.document = False
            self.filename = False
        else:
            self.resource_url = False

    @api.model
    def _check_upload_size(self, encoded):
        if not encoded:
            return
        max_mb_param = self.env['ir.config_parameter'].sudo().get_param('eds.max_upload_size_mb', 10)
        try:
            max_mb = int(max_mb_param)
            if max_mb < 1:
                max_mb = 10
        except (ValueError, TypeError):
            max_mb = 10
        max_bytes = max_mb * 1024 * 1024
        try:
            value = encoded.encode('ascii') if isinstance(encoded, str) else encoded
            if len(value) > 4 * ((max_bytes + 2) // 3) + 4:
                raise ValidationError(_('Training material files cannot exceed %s MB.') % max_mb)
            size = len(base64.b64decode(value, validate=True))
        except (UnicodeEncodeError, TypeError, binascii.Error, ValueError) as exc:
            raise ValidationError(_('The uploaded material is not a valid file.')) from exc
        if size > max_bytes:
            raise ValidationError(_('Training material files cannot exceed %s MB.') % max_mb)

    @api.model
    def _check_file_extension(self, material_type, filename):
        extension = PurePath(filename or '').suffix.lower()
        allowed = _MATERIAL_FILE_EXTENSIONS.get(material_type, set())
        if extension not in allowed:
            raise ValidationError(_('%s files must use one of these extensions: %s') % (
                material_type.replace('_', ' ').title(), ', '.join(sorted(allowed))))

    @api.constrains('document', 'filename', 'resource_url', 'source_kind',
                    'material_type', 'quality_state', 'approval_state')
    def _check_content_source(self):
        for rec in self:
            if rec.material_type == 'video' and rec.source_kind != 'link':
                raise ValidationError(_('Video and e-learning materials must link to an LMS lesson or managed streaming resource.'))
            if rec.source_kind == 'attachment':
                if rec.resource_url:
                    raise ValidationError(_('Choose one content source: an EDS attachment or a managed link.'))
                if rec._has_content():
                    rec._check_file_extension(rec.material_type, rec.filename)
            else:
                if rec.document:
                    raise ValidationError(_('Choose one content source: an EDS attachment or a managed link.'))
                if rec.resource_url:
                    url = rec.resource_url.strip()
                    parsed = urlparse(url)
                    internal = url.startswith('/') and not url.startswith('//') and not url.startswith('/\\')
                    web_url = parsed.scheme in ('http', 'https') and bool(parsed.netloc)
                    if not (internal or web_url):
                        raise ValidationError(_('Use a valid http(s) URL or an internal path beginning with /.'))
            if rec.quality_state in ('in_review', 'quality_approved'):
                rec._ensure_source_present()

    def _ensure_source_present(self):
        for rec in self:
            if rec.source_kind == 'attachment' and not rec.document:
                raise ValidationError(_('Attach the material file before submitting it for quality review.'))
            if rec.source_kind == 'link' and not rec.resource_url:
                raise ValidationError(_('Enter the LMS or internal resource link before submitting it for quality review.'))

    def action_open_source(self):
        self.ensure_one()
        self.check_access('read')
        self._ensure_source_present()
        return {
            'type': 'ir.actions.act_url',
            'url': (f'/web/content/eds.material/{self.id}/document?download=false'
                    if self.source_kind == 'attachment' else self.resource_url),
            'target': 'new',
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('material_type') == 'video' and 'source_kind' not in vals:
                vals['source_kind'] = 'link'
            if vals.get('material_type') == 'examination' and 'visibility' not in vals:
                vals['visibility'] = 'staff'
            if vals.get('resource_url'):
                vals['resource_url'] = vals['resource_url'].strip()
            self._check_upload_size(vals.get('document'))
            if vals.get('document') and vals.get('source_kind', 'attachment') == 'attachment':
                self._check_file_extension(vals.get('material_type', 'manual'), vals.get('filename'))
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code(
                    'eds.material') or _('New')
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('resource_url'):
            vals = dict(vals, resource_url=vals['resource_url'].strip())
        self._check_upload_size(vals.get('document'))
        if {'document', 'filename', 'material_type', 'source_kind'} & vals.keys():
            for rec in self:
                if vals.get('source_kind', rec.source_kind) != 'attachment':
                    continue
                has_file = bool(vals['document']) if 'document' in vals else rec._has_content()
                if has_file:
                    self._check_file_extension(
                        vals.get('material_type', rec.material_type),
                        vals.get('filename', rec.filename),
                    )
        if any(name in vals for name in (
            'title', 'material_type', 'version', 'source_kind', 'document',
            'filename', 'resource_url', 'description',
        )):
            vals = dict(vals, quality_state='draft', approval_state='not_required',
                        reviewed_by=False, reviewed_date=False,
                        approved_by=False, approved_date=False)
        return super().write(vals)

    def _has_content(self):
        self.ensure_one()
        return bool(self.with_context(bin_size=True).document if self.source_kind == 'attachment'
                    else self.resource_url)

    def _can_open_for_session(self, session, user):
        """Keep model files private; the delivery route checks each viewer."""
        self.ensure_one()
        if not self._has_content() or self.course_id != session.course_id:
            return False
        if user.has_group('employee_development_system.group_eds_officer'):
            return True
        if self.visibility in ('trainers', 'participants') and session.status != 'cancelled':
            if session.trainer_ids.filtered(
                lambda trainer: trainer.employee_id.sudo().user_id.id == user.id
                or trainer.external_partner_id == user.partner_id
            ):
                return True
        if self.visibility == 'participants' and session.status in (
            'scheduled', 'ongoing', 'rescheduled', 'completed',
        ):
            return bool(self.env['eds.enrollment'].sudo().search_count([
                ('session_id', '=', session.id),
                ('employee_id.user_id', '=', user.id),
                ('state', 'in', ('enrolled', 'completed', 'incomplete')),
            ]))
        return False

    def _can_open_for_user(self, user):
        """Check the viewer against matching sessions without scanning all of them."""
        self.ensure_one()
        if not self._has_content():
            return False
        if user.has_group('employee_development_system.group_eds_officer'):
            return True
        if self.visibility in ('trainers', 'participants'):
            trainers = self.env['eds.trainer'].sudo().search([
                '|', ('employee_id.user_id', '=', user.id),
                ('external_partner_id', '=', user.partner_id.id),
            ])
            if trainers and self.env['eds.session'].sudo().search_count([
                ('course_id', '=', self.course_id.id),
                ('trainer_ids', 'in', trainers.ids),
                ('status', '!=', 'cancelled'),
                ('company_id', 'in', user.company_ids.ids),
            ]):
                return True
        if self.visibility == 'participants':
            return bool(self.env['eds.enrollment'].sudo().search_count([
                ('session_id.course_id', '=', self.course_id.id),
                ('session_id.status', 'in', ('scheduled', 'ongoing', 'rescheduled', 'completed')),
                ('session_id.company_id', 'in', user.company_ids.ids),
                ('employee_id.user_id', '=', user.id),
                ('state', 'in', ('enrolled', 'completed', 'incomplete')),
            ]))
        return False

    def _require_group(self, group_xml_id):
        if not (self.env.su or self.env.user.has_group('employee_development_system.' + group_xml_id)):
            raise UserError(_('You do not have the required authority for this step.'))

    def action_submit_quality_review(self):
        """Draft -> In Quality Review (L&D quality check)."""
        for rec in self:
            if rec.quality_state != 'draft':
                raise UserError(_('Only draft materials can be submitted to quality review.'))
            rec._ensure_source_present()
            rec.quality_state = 'in_review'
            rec.message_post(body=_('Material %s submitted for quality review.')
                             % rec.title)
            notify_role_action(
                rec, 'group_eds_manager', 'group_eds_admin',
                _('Review training material'),
                _('Training material %s needs quality review.') % rec.title)

    def action_approve_quality(self):
        """In Review -> Quality Approved (L&D Manager / Admin)."""
        for rec in self:
            rec._require_group('group_eds_manager')
            if rec.quality_state != 'in_review':
                raise UserError(_('Only materials in quality review can be quality-approved.'))
            rec.write({'quality_state': 'quality_approved',
                       'reviewed_by': self.env.user.id,
                       'reviewed_date': date.today()})
            rec.message_post(body=_('Material %s passed the quality review.')
                             % rec.title)
            clear_action_activities(rec)
            notify_action(
                rec, rec.create_uid, _('Training material quality approved'),
                _('Training material %s passed quality review.') % rec.title,
                action_required=False)

    def action_submit_director_approval(self):
        """Quality Approved -> Submitted to Director PPDD."""
        for rec in self:
            if rec.quality_state != 'quality_approved':
                raise UserError(_('Approve the quality review before the Director PPDD step '
                                  '().'))
            if rec.approval_state == 'director_approved':
                continue
            rec.approval_state = 'submitted'
            rec.message_post(body=_('Material %s submitted for Director PPDD approval '
                                    '().') % rec.title)
            notify_role_action(
                rec, 'group_eds_director', None,
                _('Approve training material'),
                _('Training material %s needs Director approval.') % rec.title)

    def action_director_approve(self):
        """Submitted -> Director PPDD Approved."""
        for rec in self:
            rec._require_group('group_eds_director')
            if rec.approval_state != 'submitted':
                raise UserError(_('Only materials submitted to the Director PPDD can be '
                                  'finally approved.'))
            rec.write({'approval_state': 'director_approved',
                       'approved_by': self.env.user.id,
                       'approved_date': date.today()})
            rec.message_post(body=_('Material %s approved by Director PPDD - session '
                                    'confirmation gate released.') % rec.title)
            clear_action_activities(rec)
            notify_action(
                rec, rec.create_uid | rec.reviewed_by,
                _('Training material approved'),
                _('Training material %s is approved for training delivery.') % rec.title,
                action_required=False)

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
            rec.message_post(body=_('Material %s was rejected.') % rec.title)
            clear_action_activities(rec)
            notify_action(
                rec, rec.create_uid, _('Training material returned'),
                _('Training material %s was rejected and needs revision.') % rec.title)


class EdsFeedback(models.Model):
    """Daily participant feedback line captured during delivery."""
    _name = 'eds.feedback'
    _description = 'Daily Participant Feedback'
    _order = 'feedback_date desc, id desc'
    _rec_name = 'id'

    def web_read(self, specification):
        return safe_employee_web_read(
            self, specification, super().web_read, ('employee_id',))

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

    @api.constrains('session_id', 'employee_id')
    def _check_employee_enrolled(self):
        for rec in self:
            if rec.session_id and rec.employee_id:
                enrolled_emps = rec.session_id.enrollment_ids.filtered(
                    lambda e: e.state in ('enrolled', 'completed', 'incomplete')
                ).mapped('employee_id')
                if enrolled_emps and rec.employee_id not in enrolled_emps:
                    raise ValidationError(_(
                        'Participant Error: Employee %s is not an enrolled participant in session %s.'
                    ) % (rec.employee_id.sudo().name, rec.session_id.name))


class EdsAssessment(models.Model):
    """Pre/post assessment, with itemized responses or a legacy score.

    Single model shared by delivery  and the Level-2 evaluation engine
    : `eds.evaluation.level2` links pre/post records through this model
    and computes the learning gain. `passed` compares the score against the
    configurable threshold (default 60%).
    """
    _name = 'eds.assessment'
    _description = 'Pre / Post Training Assessment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'session_id, employee_id, assessment_type'
    _rec_name = 'id'

    def web_read(self, specification):
        return safe_employee_web_read(
            self, specification, super().web_read, ('employee_id',))

    _track_audit = True  # documented intent; enforced via audit.rule in data/

    session_id = fields.Many2one('eds.session', string='Session', required=True,
                                 ondelete='cascade', index=True, tracking=True)
    employee_id = fields.Many2one('hr.employee', string='Participant', required=True,
                                  index=True, tracking=True)
    assessment_type = fields.Selection([
        ('pre', 'Pre-Training Assessment'),
        ('post', 'Post-Training Assessment'),
        ('skills_test', 'Practical Skills Test'),
    ], string='Assessment Type', default='pre', required=True, tracking=True)
    answer_ids = fields.One2many('eds.assessment.answer', 'assessment_id',
                                 string='Question Answers')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('distributed', 'Awaiting Employee'),
        ('submitted', 'Awaiting Grading'),
        ('graded', 'Graded'),
    ], default='draft', required=True, tracking=True)
    entry_method = fields.Selection([
        ('score_only', 'Legacy Score Only'),
        ('manual', 'Entered by L&D'),
        ('import', 'Imported Responses'),
        ('employee', 'Employee Responses'),
    ], default='score_only', required=True, tracking=True,
        help='Existing score-only records remain available; new itemized assessments '
             'use the same question and grading workflow regardless of source.')
    score = fields.Float(string='Score (0-100)', digits=(5, 2), tracking=True)
    passed = fields.Boolean(string='Passed', compute='_compute_passed', store=True,
                            help='Score >= the configurable Level-2 pass threshold '
                                 '(default 60%).')
    threshold = fields.Float(string='Pass Threshold %', compute='_compute_passed', store=True)
    assessment_date = fields.Date(string='Assessment Date', default=fields.Date.context_today)
    uploaded_by = fields.Many2one('res.users', string='Uploaded By',
                                  default=lambda self: self.env.user, readonly=True,
                                  help='L&D staff member who entered or imported the score.')
    distributed_at = fields.Datetime(string='Distributed At', readonly=True, copy=False)
    submitted_at = fields.Datetime(string='Submitted At', readonly=True, copy=False)
    graded_at = fields.Datetime(string='Graded At', readonly=True, copy=False)
    taken_over_at = fields.Datetime(string='Taken Over By L&D At', readonly=True, copy=False)
    taken_over_by = fields.Many2one('res.users', string='Taken Over By',
                                    readonly=True, copy=False)
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

    def _is_assessment_staff(self):
        return self.env.su or self.env.user.has_group(
            'employee_development_system.group_eds_officer')

    def _question_bank(self):
        self.ensure_one()
        questions = self.env['eds.assessment.question'].search([
            ('session_id', '=', self.session_id.id),
            ('assessment_type', '=', self.assessment_type),
        ])
        if not questions and self._is_assessment_staff():
            questions = self.env['eds.assessment.question'].seed_from_instrument(
                self.session_id, self.assessment_type)
        return questions

    def action_load_questions(self):
        """Add missing question rows for manual entry without replacing responses."""
        if not self._is_assessment_staff():
            raise AccessError(_('Only L&D staff may prepare assessment questions.'))
        answer_model = self.env['eds.assessment.answer']
        for assessment in self:
            if assessment.assessment_type not in ('pre', 'post'):
                raise ValidationError(_('Question responses are available for pre/post assessments.'))
            questions = assessment._question_bank()
            if not questions:
                raise ValidationError(_(
                    'Add pre/post questions to this session or publish a Level 2 course instrument first.'
                ))
            if assessment.entry_method == 'score_only' and assessment.score:
                raise ValidationError(_(
                    'This assessment already has a legacy score. Keep that result, or '
                    'explicitly replace it through the response import workflow.'
                ))
            existing_ids = set(assessment.answer_ids.mapped('question_id').ids)
            missing = questions.filtered(lambda question: question.id not in existing_ids)
            if missing:
                answer_model.create([{
                    'assessment_id': assessment.id,
                    'question_id': question.id,
                } for question in missing])
            if assessment.entry_method == 'score_only':
                assessment.write({'entry_method': 'manual'})
        if len(self) == 1:
            return {
                'type': 'ir.actions.client', 'tag': 'bunna_refresh_form',
                'params': {'res_model': self._name, 'res_id': self.id},
            }
        return True

    @api.model
    def distribute_for_session(self, session, assessment_type):
        """Open questions for linked participants; return only newly invited rows.

        Calling this again does not change or re-notify a participant who was
        already invited, submitted, or graded. Staff can record results manually
        for participants without an active internal user account.
        """
        if not self._is_assessment_staff():
            raise AccessError(_('Only L&D staff may distribute assessments.'))
        session.ensure_one()
        if assessment_type not in ('pre', 'post'):
            raise ValidationError(_('Only pre and post assessments can be distributed.'))
        # Serialize simultaneous button clicks for this session. The second
        # transaction searches after the first has committed and therefore
        # returns no newly distributed rows or duplicate notifications.
        self.env.cr.execute(
            'SELECT id FROM eds_session WHERE id = %s FOR UPDATE', [session.id])
        questions = self.env['eds.assessment.question'].seed_from_instrument(
            session, assessment_type)
        if not questions:
            raise ValidationError(_(
                'Add %s questions to this session or publish a Level 2 course instrument before distribution.'
            ) % assessment_type)
        participants = session._accepted_attendance_enrollments().filtered(
            lambda enrollment: enrollment.state in ('enrolled', 'completed')
            and enrollment.employee_id.sudo().user_id
            and enrollment.employee_id.sudo().user_id.active
            and not enrollment.employee_id.sudo().user_id.share
        ).mapped('employee_id')
        if not participants:
            raise ValidationError(_(
                'No enrolled participant has an active internal user account. '
                'Enter or import their answers through L&D instead.'
            ))
        newly_distributed = self.browse()
        for employee in participants:
            assessment = self.search([
                ('session_id', '=', session.id),
                ('employee_id', '=', employee.id),
                ('assessment_type', '=', assessment_type),
            ], limit=1)
            if assessment:
                if assessment.state in ('distributed', 'submitted', 'graded'):
                    continue
                if (assessment.entry_method == 'score_only'
                        or assessment.score or assessment.answer_ids.filtered(
                        lambda line: (line.answer_text or '').strip() or line.is_graded)):
                    # A pre-existing manual/import/legacy result belongs to staff.
                    continue
                assessment.action_load_questions()
            else:
                assessment = self.create({
                    'session_id': session.id,
                    'employee_id': employee.id,
                    'assessment_type': assessment_type,
                    'company_id': session.company_id.id,
                    'entry_method': 'employee',
                })
                assessment.action_load_questions()
            assessment.write({
                'entry_method': 'employee',
                'state': 'distributed',
                'distributed_at': fields.Datetime.now(),
            })
            newly_distributed |= assessment
        return newly_distributed

    def _validate_itemized_answers(self, *, require_grades=False):
        for assessment in self:
            questions = assessment._question_bank()
            if not questions:
                raise ValidationError(_(
                    'Add questions for the %s assessment before submitting results.'
                ) % assessment.assessment_type)
            lines = assessment.answer_ids
            if set(lines.mapped('question_id').ids) != set(questions.ids):
                raise ValidationError(_(
                    'Answer every question in the %s assessment for %s.'
                ) % (assessment.assessment_type, assessment.employee_id.sudo().name))
            for line in lines:
                if not (line.answer_text or '').strip():
                    raise ValidationError(_(
                        'An answer is required for every assessment question (%s).'
                    ) % line.question_id.question_text)
                if require_grades and not line.is_graded:
                    raise ValidationError(_(
                        'Grade every answer before finalizing the assessment (%s).'
                    ) % line.question_id.question_text)
                if require_grades and not (0 <= line.awarded_points <= line.question_id.max_points):
                    raise ValidationError(_(
                        'Awarded points are outside the permitted range for %s.'
                    ) % line.question_id.question_text)

    def action_submit_answers(self):
        for assessment in self:
            if (assessment.entry_method != 'employee'
                    or assessment.state != 'distributed'
                    or assessment.employee_id.sudo().user_id.id != self.env.uid):
                raise AccessError(_('You can submit only your own distributed assessment.'))
            assessment._validate_itemized_answers()
            assessment.sudo().write({
                'state': 'submitted',
                'submitted_at': fields.Datetime.now(),
            })
        if len(self) == 1:
            return {
                'type': 'ir.actions.client',
                'tag': 'bunna_refresh_form',
                'params': {
                    'res_model': self._name,
                    'res_id': self.id,
                    'title': _('Submitted Successfully'),
                    'message': _('Assessment answers submitted successfully.'),
                    'type': 'success',
                },
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Submitted Successfully'),
                'message': _('Assessment answers submitted successfully.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_take_over_manual_entry(self):
        """Let L&D finish a distributed form while keeping employee answers."""
        if not self._is_assessment_staff():
            raise AccessError(_('Only L&D staff may take over an assessment.'))
        for assessment in self:
            if assessment.state != 'distributed' or assessment.entry_method != 'employee':
                raise ValidationError(_(
                    'Only an assessment awaiting employee answers can be taken over.'
                ))
            answered_count = len(assessment.answer_ids.filtered(
                lambda line: (line.answer_text or '').strip()))
            employee_user = assessment.employee_id.sudo().user_id
            assessment.write({
                'entry_method': 'manual',
                'state': 'submitted',
                'score': 0.0,
                'taken_over_at': fields.Datetime.now(),
                'taken_over_by': self.env.user.id,
            })
            # The original notification remains in Inbox as history, but the
            # action can no longer be completed by the employee.
            pending = assessment.activity_ids.filtered(
                lambda activity: activity.user_id == employee_user
                and (activity.summary or '').startswith('EDS action:'))
            if pending:
                pending.sudo().unlink()
            assessment.with_context(eds_popup_managed=True).message_post(
                body=_('L&D took over this assessment; %d existing employee '
                       'answer(s) were preserved for staff completion and grading.')
                % answered_count,
                subtype_xmlid='mail.mt_note',
            )
        return True

    def action_finalize(self):
        if not self._is_assessment_staff():
            raise AccessError(_('Only L&D staff may grade assessments.'))
        for assessment in self:
            if assessment.assessment_type not in ('pre', 'post'):
                raise ValidationError(_('Only pre/post assessments use itemized grading.'))
            assessment._validate_itemized_answers(require_grades=True)
            total = sum(assessment.answer_ids.mapped('question_id.max_points'))
            if total <= 0:
                raise ValidationError(_('Assessment maximum points must be positive.'))
            awarded = sum(assessment.answer_ids.mapped('awarded_points'))
            assessment.with_context(eds_assessment_finalize=True).write({
                'entry_method': ('manual' if assessment.entry_method == 'score_only'
                                 else assessment.entry_method),
                'score': round(100.0 * awarded / total, 2),
                'state': 'graded',
                'graded_at': fields.Datetime.now(),
                'assessment_date': fields.Date.context_today(assessment),
            })
        return True

    def action_finalize_skills_test(self):
        """Keep the existing practical-test score workflow usable."""
        if not self._is_assessment_staff():
            raise AccessError(_('Only L&D staff may record practical skills tests.'))
        for assessment in self:
            if assessment.assessment_type != 'skills_test':
                raise ValidationError(_('This action is only for practical skills tests.'))
            assessment.write({
                'state': 'graded',
                'graded_at': fields.Datetime.now(),
            })
        return True

    def action_reopen_skills_test(self):
        if not self._is_assessment_staff():
            raise AccessError(_('Only L&D staff may reopen practical skills tests.'))
        for assessment in self:
            if assessment.assessment_type != 'skills_test' or assessment.state != 'graded':
                raise ValidationError(_('Only a graded practical skills test can be reopened.'))
            assessment.write({'state': 'draft', 'graded_at': False})
        return True

    def _sync_level2_evaluation(self):
        """Keep the learning-gain record linked to entered pre/post scores."""
        evaluation_model = self.env['eds.evaluation.level2'].sudo()
        for assessment in self.filtered(lambda row: row.assessment_type in ('pre', 'post')):
            evaluation = evaluation_model.search([
                ('session_id', '=', assessment.session_id.id),
                ('employee_id', '=', assessment.employee_id.id),
            ], limit=1)
            field_name = 'pre_assessment_id' if assessment.assessment_type == 'pre' else 'post_assessment_id'
            if evaluation:
                evaluation.write({field_name: assessment.id})
            else:
                evaluation_model.create({
                    'session_id': assessment.session_id.id,
                    'employee_id': assessment.employee_id.id,
                    field_name: assessment.id,
                })

    @api.model_create_multi
    def create(self, vals_list):
        # Reject unauthorized callers before inspecting assessment content.
        self.check_access('create')
        normalized_vals = []
        for source_vals in vals_list:
            vals = dict(source_vals)
            if vals.get('assessment_type') == 'skills_test':
                vals['entry_method'] = 'score_only'
            if vals.get('session_id'):
                session = self.env['eds.session'].browse(vals['session_id'])
                company_id = session.company_id.id or False
                if vals.get('company_id') not in (None, company_id):
                    raise ValidationError(_(
                        'The assessment company must match its training session.'
                    ))
                vals['company_id'] = company_id
            if (vals.get('assessment_type', 'pre') in ('pre', 'post')
                    and vals.get('entry_method', 'score_only') == 'score_only'
                    and vals.get('score')
                    and (not self.env.su or (
                        vals.get('session_id')
                        and self.env['eds.assessment.question'].search_count([
                            ('session_id', '=', vals['session_id']),
                            ('assessment_type', '=', vals.get('assessment_type', 'pre')),
                        ])))):
                raise ValidationError(_(
                    'Record each question and answer, then finalize the assessment. '
                    'A new score-only result cannot be entered by L&D.'
                ))
            if (vals.get('entry_method', 'score_only') != 'score_only'
                    and vals.get('state') == 'graded'):
                raise ValidationError(_('Use Finalize to grade an itemized assessment.'))
            if (vals.get('entry_method', 'score_only') != 'score_only'
                    and vals.get('score')):
                raise ValidationError(_(
                    'An itemized assessment starts without a score. Grade its '
                    'question answers and use Finalize to calculate the result.'
                ))
            normalized_vals.append(vals)
        records = super().create(normalized_vals)
        records._sync_level2_evaluation()
        return records

    def write(self, vals):
        vals = dict(vals)
        if ('score' in vals and any(row.assessment_type == 'skills_test'
                                    and row.state == 'graded' for row in self)
                and vals.get('state') != 'draft'):
            raise ValidationError(_(
                'Reopen the practical skills test before changing its score.'
            ))
        if ('score' in vals and not self.env.su
                and any(row.entry_method == 'score_only'
                        and row.assessment_type in ('pre', 'post') for row in self)
                and not (vals.get('state') == 'graded'
                         and vals.get('entry_method') not in (None, 'score_only'))
                and not (self.env.context.get('eds_replace_legacy_score')
                         and vals.get('entry_method') not in (None, 'score_only')
                         and not vals['score'])):
            raise ValidationError(_(
                'L&D cannot edit a score-only pre/post result. Record each answer '
                'and finalize, or explicitly replace the legacy result by import.'
            ))
        if 'session_id' in vals and not vals['session_id']:
            raise ValidationError(_('An assessment must belong to a training session.'))
        if 'session_id' in vals or 'company_id' in vals:
            session = (self.env['eds.session'].browse(vals['session_id'])
                       if vals.get('session_id') else False)
            for assessment in self:
                target_session = session or assessment.session_id
                target_company_id = target_session.company_id.id or False
                if 'company_id' in vals and vals['company_id'] != target_company_id:
                    raise ValidationError(_(
                        'The assessment company must match its training session.'
                    ))
            if 'session_id' in vals and 'company_id' not in vals:
                vals['company_id'] = session.company_id.id or False
        old_identity = {}
        if {'session_id', 'employee_id', 'assessment_type'} & vals.keys():
            for assessment in self:
                if assessment.answer_ids:
                    raise ValidationError(_(
                        'An assessment with question answers cannot change its session, '
                        'participant, or type. Create a new assessment instead.'
                    ))
                old_identity[assessment.id] = (
                    assessment.session_id.id,
                    assessment.employee_id.id,
                    assessment.assessment_type,
                )
        if not self._is_assessment_staff():
            for assessment in self:
                if (assessment.employee_id.sudo().user_id.id != self.env.uid
                        or assessment.state != 'distributed'
                        or assessment.entry_method != 'employee'):
                    raise AccessError(_('This assessment is not open for your answers.'))
                if set(vals) - {'answer_ids', 'state'}:
                    raise AccessError(_('Employees may edit only their assessment answers.'))
                if 'state' in vals and vals['state'] != 'submitted':
                    raise AccessError(_('Employees may only submit their own answers.'))
                for command in vals.get('answer_ids', []):
                    if (len(command) < 3 or command[0] != 1
                            or command[1] not in assessment.answer_ids.ids
                            or set(command[2]) != {'answer_text'}):
                        raise AccessError(_(
                            'Employees may update only their existing answer text.'
                        ))
        vals = dict(vals)
        if not self._is_assessment_staff() and vals.get('state') == 'submitted':
            # A direct RPC write must produce the same timestamp as the button.
            vals['submitted_at'] = fields.Datetime.now()
        if vals.get('entry_method') == 'score_only' and any(
                row.entry_method != 'score_only' for row in self):
            raise ValidationError(_('An itemized assessment cannot become a score-only record.'))
        if (vals.get('entry_method') not in (None, 'score_only')
                and not self.env.context.get('eds_replace_legacy_score')
                and any(row.entry_method == 'score_only' and row.score for row in self)):
            raise ValidationError(_(
                'This record contains a legacy score. Explicitly replace it through '
                'the response import workflow before switching to itemized grading.'
            ))
        itemized = any(
            vals.get('entry_method', row.entry_method) != 'score_only'
            and vals.get('assessment_type', row.assessment_type) != 'skills_test'
            for row in self
        )
        if vals.get('state') == 'graded':
            if len(self) != 1:
                raise ValidationError(_('Finalize each assessment separately.'))
            target_type = vals.get('assessment_type', self.assessment_type)
            if not itemized and target_type != 'skills_test':
                raise ValidationError(_('Finalize each itemized assessment separately.'))
            if target_type != 'skills_test':
                self._validate_itemized_answers(require_grades=True)
                total = sum(self.answer_ids.mapped('question_id.max_points'))
                if total <= 0:
                    raise ValidationError(_('Assessment maximum points must be positive.'))
                vals['score'] = round(
                    100.0 * sum(self.answer_ids.mapped('awarded_points')) / total, 2)
        elif itemized:
            if 'score' in vals and vals['score']:
                raise ValidationError(_('The itemized score is calculated from graded answers.'))
            if ('score' in vals and any(row.state == 'graded' for row in self)
                    and vals.get('state') not in ('draft', 'distributed', 'submitted')):
                raise ValidationError(_(
                    'Reopen a graded assessment before clearing its calculated score.'
                ))
            if ('entry_method' in vals or 'state' in vals or 'score' in vals) and (
                    vals.get('state') in ('draft', 'distributed', 'submitted')
                    or any(row.entry_method == 'score_only' for row in self)):
                vals['score'] = 0.0
                if (vals.get('entry_method') and 'state' not in vals
                        and any(row.entry_method == 'score_only' for row in self)):
                    vals['state'] = 'draft'
        result = super().write(vals)
        if {'session_id', 'employee_id', 'assessment_type'} & vals.keys():
            evaluation_model = self.env['eds.evaluation.level2'].sudo()
            for assessment in self:
                old_session, old_employee, old_type = old_identity[assessment.id]
                if old_type in ('pre', 'post'):
                    old_field = ('pre_assessment_id' if old_type == 'pre'
                                 else 'post_assessment_id')
                    previous = evaluation_model.search([
                        ('session_id', '=', old_session),
                        ('employee_id', '=', old_employee),
                        (old_field, '=', assessment.id),
                    ])
                    if previous:
                        previous.write({old_field: False, 'state': 'draft'})
            self._sync_level2_evaluation()
        if {'score', 'state', 'entry_method'} & vals.keys():
            evaluation_model = self.env['eds.evaluation.level2'].sudo()
            for assessment in self.filtered(lambda row: row.assessment_type in ('pre', 'post')):
                evaluated = evaluation_model.search([
                    ('session_id', '=', assessment.session_id.id),
                    ('employee_id', '=', assessment.employee_id.id),
                    ('state', '=', 'evaluated'),
                ])
                if evaluated:
                    evaluated.write({'state': 'draft'})
        if not self._is_assessment_staff() and vals.get('state') == 'submitted':
            self._validate_itemized_answers()
        return result

    @api.constrains('session_id', 'employee_id', 'assessment_type', 'entry_method')
    def _check_employee_enrolled(self):
        for rec in self:
            if rec.session_id and rec.employee_id:
                enrolled_emps = rec.session_id._accepted_attendance_enrollments().filtered(
                    lambda enrollment: enrollment.state in ('enrolled', 'completed')
                ).mapped('employee_id')
                if (rec.entry_method != 'score_only' and rec.assessment_type in ('pre', 'post')
                        and rec.employee_id not in enrolled_emps):
                    raise ValidationError(_(
                        'Participant Error: %s must have an accepted enrollment '
                        'in session %s before itemized assessment answers are recorded.'
                    ) % (rec.employee_id.sudo().name, rec.session_id.name))
                if enrolled_emps and rec.employee_id not in enrolled_emps:
                    raise ValidationError(_(
                        'Participant Error: Employee %s is not an enrolled participant in session %s.'
                    ) % (rec.employee_id.sudo().name, rec.session_id.name))

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
    """International training facilitation.

    Lightweight workflow covering entitlement validation (minimum service months),
    travel/per-diem arrangements, post-training reports and knowledge sharing.
    Per the plan this is the stretch-scope piece of  - implemented as a
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
                                  default=lambda self: self.env['res.currency'].search([('name', '=', 'USD')], limit=1))
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
        help='How the participant applies the new skills at the workplace.')
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
        """Draft -> Submitted: enforce entitlement before the approval chain."""
        for rec in self:
            if rec.approval_state != 'draft':
                raise UserError(_('Only draft international trainings can be submitted.'))
            if not rec.entitlement_valid:
                raise UserError(_('Entitlement validation failed:\n%s')
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
            rec.message_post(body=_('International training %s approved.') % rec.name)

    def action_complete(self):
        """Approved -> Completed: requires the post-training deliverables."""
        for rec in self:
            if rec.approval_state != 'approved':
                raise UserError(_('Only approved international trainings can be completed.'))
            if not rec.reports_ids:
                raise UserError(_('Record at least the post-training report before '
                                  'completing the international training.'))
            rec.approval_state = 'completed'
            rec.message_post(body=_('International training %s completed - post-training '
                                    'deliverables recorded.') % rec.name)


class EdsInternationalTravelLine(models.Model):
    """Travel arrangement line: visa, insurance, flight, per-diem, authorization."""
    _name = 'eds.international.travel.line'
    _description = 'International Travel Arrangement'
    _order = 'training_id, create_date desc, id desc'

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
    attachment = fields.Binary(string='Attachment', attachment=True)
    filename = fields.Char(string='Filename')
    notes = fields.Text(string='Notes')


class EdsInternationalReport(models.Model):
    """Post-training report or knowledge-sharing record."""
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
    document = fields.Binary(string='Document', attachment=True)
    filename = fields.Char(string='Filename')
    notes = fields.Text(string='Notes')


class EdsKnowledgeSharing(models.Model):
    """Post-Training Knowledge Sharing & Action Debrief Form."""
    _name = 'eds.knowledge.sharing'
    _description = 'Post-Training Knowledge Sharing & Action Debrief'

    def web_read(self, specification):
        return safe_employee_web_read(
            self, specification, super().web_read, ('employee_id',))
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'session_date desc, id desc'

    name = fields.Char(string='Debrief Ref', required=True, copy=False, default=lambda self: _('New'))
    employee_id = fields.Many2one('hr.employee', string='Participant', required=True, tracking=True)
    department_id = fields.Many2one('hr.department', string='Department', related='employee_id.department_id', store=True)
    session_id = fields.Many2one('eds.session', string='Training Session', tracking=True)
    course_id = fields.Many2one('eds.course', string='Course / Program', tracking=True)
    training_type = fields.Selection([
        ('local_specialized', 'Local Specialized / External Program'),
        ('international', 'Overseas / International Program'),
        ('internal_tot', 'Internal ToT / Advanced Cohort'),
    ], string='Training Category', default='local_specialized', required=True)
    completion_date = fields.Date(string='Training Completion Date', required=True, default=fields.Date.context_today)
    debrief_deadline = fields.Date(string='Knowledge Transfer Deadline (30 Days)', compute='_compute_deadline', store=True)
    session_date = fields.Date(string='Debrief Session Date', default=fields.Date.context_today)
    
    # Debrief Execution Details
    target_audience = fields.Char(string='Target Peer Audience / Branch Units', required=True, default='Department / Branch Team Members')
    attendees_count = fields.Integer(string='Number of Peer Attendees', default=5)
    key_takeaways = fields.Text(string='Key Banking Knowledge & Insights Acquired', required=True)
    workplace_action_plan = fields.Text(string='Action Plan / Recommended Process Improvements', required=True)
    materials_deposited = fields.Boolean(string='Training Materials Deposited with L&D Library', default=True)
    presentation_file = fields.Binary(string='Debrief Presentation Slides / Summary', attachment=True)
    presentation_filename = fields.Char(string='Presentation Filename')

    # Signatures
    sign_employee = fields.Char(string='Employee Signoff')
    sign_manager = fields.Char(string='Line Manager / Department Head Signoff')
    sign_officer = fields.Char(string='L&D Officer Verification')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('scheduled', 'Debrief Scheduled'),
        ('completed', 'Completed & Verified'),
    ], string='Status', default='draft', required=True, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('eds.knowledge.sharing') or _('New')
        return super().create(vals_list)

    @api.depends('completion_date')
    def _compute_deadline(self):
        for rec in self:
            if rec.completion_date:
                rec.debrief_deadline = fields.Date.add(rec.completion_date, days=30)
            else:
                rec.debrief_deadline = False

    def action_schedule(self):
        for rec in self:
            rec.state = 'scheduled'

    def action_complete(self):
        for rec in self:
            rec.state = 'completed'
            rec.message_post(body=_("Knowledge transfer debrief completed and verified by L&D."))

    def action_print_form(self):
        """Prints Form Knowledge Sharing & Debrief Form."""
        self.ensure_one()
        return self.env.ref('employee_development_system.action_report_eds_knowledge_sharing').report_action(self)
