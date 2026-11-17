# -*- coding: utf-8 -*-
import os
import io
import base64
import uuid
import logging
from markupsafe import Markup, escape
from PIL import Image, ImageDraw, ImageFont
from psycopg2 import IntegrityError

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

from .eds_action_notification import (
    clear_action_activities, notify_action, push_action_popup, role_users,
)
from .eds_employee_projection import safe_employee_web_read

_logger = logging.getLogger(__name__)


class EdsCertificateRule(models.Model):
    _name = 'eds.certificate.rule'
    _description = 'EDS Certification Policy / Rule'
    _inherit = ['mail.thread']
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Rule Name', required=True)
    category = fields.Selection([
        ('developmental', 'Developmental'),
        ('values_ethics', 'Values & Ethics'),
        ('technical_compliance', 'Technical & Compliance'),
    ], string='Course Category Target', required=True)
    require_attendance = fields.Boolean(string='Require Attendance Minimum', default=True)
    min_attendance_pct = fields.Float(string='Minimum Attendance (%)', default=80.0)
    require_level2_pass = fields.Boolean(string='Require Level 2 Post-Assessment Pass', default=True)
    min_level2_score = fields.Float(string='Minimum Level 2 Score (%)', default=60.0)
    active = fields.Boolean(default=True)
    notes = fields.Text(string='Policy Notes')

    @api.constrains('min_attendance_pct', 'min_level2_score')
    def _check_percentages(self):
        for rule in self:
            if not 0.0 <= rule.min_attendance_pct <= 100.0:
                raise ValidationError(_('Minimum attendance must be between 0 and 100 percent.'))
            if not 0.0 <= rule.min_level2_score <= 100.0:
                raise ValidationError(_('Minimum Level 2 score must be between 0 and 100 percent.'))


class EdsCertificate(models.Model):
    _name = 'eds.certificate'
    _description = 'EDS Training Completion Certificate'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    def web_read(self, specification):
        return safe_employee_web_read(
            self, specification, super().web_read, ('employee_id',))

    code = fields.Char(string='Certificate Number', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    employee_id = fields.Many2one('hr.employee', string='Participant', required=True, index=True, tracking=True)
    session_id = fields.Many2one('eds.session', string='Training Session', required=True, ondelete='cascade', index=True, tracking=True)
    company_id = fields.Many2one('res.company', related='session_id.company_id', store=True, readonly=True)
    course_id = fields.Many2one('eds.course', related='session_id.course_id', string='Course', store=True, index=True)
    issue_date = fields.Date(string='Issue Date', readonly=True, copy=False, tracking=True)
    provider_snapshot_taken = fields.Boolean(readonly=True, copy=False)
    delivery_method_at_issue = fields.Selection([
        ('internal', 'Internal / ToT'),
        ('local_external', 'Local External'),
        ('international', 'International'),
    ], string='Delivery Type at Issue', readonly=True, copy=False)
    provider_name_at_issue = fields.Char(string='Provider at Issue', readonly=True, copy=False)
    provider_logo_at_issue = fields.Image(
        string='Provider Logo at Issue', attachment=True, readonly=True, copy=False)
    is_eligible = fields.Boolean(string='Eligible for Certification', compute='_compute_eligibility', store=False)
    eligibility_reason = fields.Text(string='Eligibility Details', compute='_compute_eligibility', store=False)
    
    # Generated Assets
    file = fields.Binary(string='Certificate File (PDF)', attachment=True)
    file_name = fields.Char(string='PDF Filename', compute='_compute_filenames', store=True)
    certificate_image = fields.Binary(string='Certificate Image (PNG)', attachment=True)
    certificate_image_filename = fields.Char(string='Image Filename', compute='_compute_filenames', store=True)
    
    # Verification & Security
    verification_token = fields.Char(string='Verification Token', readonly=True, copy=False, index=True)
    verification_url = fields.Char(string='Public Verification URL', compute='_compute_verification_url')
    
    issued_by = fields.Many2one('res.users', string='Issued By', readonly=True, copy=False)
    delivery_status = fields.Selection([
        ('pending', 'Pending'),
        ('notified', 'Employee Notified'),
        ('needs_contact', 'Employee Contact Needed'),
    ], string='Delivery Status', default='pending', readonly=True, copy=False, tracking=True)
    ready_notified = fields.Boolean(string='Issuance Queue Notified', readonly=True, copy=False)
    
    # HR Editable Certificate Content
    certificate_title = fields.Char(string='Certificate Title', compute='_compute_certificate_content', store=True, readonly=False)
    certificate_body_text = fields.Text(string='Certificate Body', compute='_compute_certificate_content', store=True, readonly=False)
    training_dates_text = fields.Char(string='Training Dates', compute='_compute_dates_text', store=True, readonly=False)
    
    # Signatories matching Bunna Bank Layout
    prepared_by_name = fields.Char(string='Prepared By', default='Talent Development Specialist', tracking=True)
    prepared_by_title = fields.Char(string='Prepared By Title', default='Talent Development Specialist')
    signatory_name = fields.Char(string='Approved By', compute='_compute_certificate_content', store=True, readonly=False, tracking=True)
    signatory_title = fields.Char(string='Approved By Title', compute='_compute_certificate_content', store=True, readonly=False)

    state = fields.Selection([
        ('pending', 'Pending Eligibility Check'),
        ('issued', 'Issued'),
        ('void', 'Voided'),
    ], string='Status', default='pending', required=True, index=True, tracking=True)

    def _require_group(self, group_xml_id):
        if not (self.env.su or self.env.user.has_group('employee_development_system.' + group_xml_id)
                or self.env.user.has_group('employee_development_system.group_eds_admin')):
            raise UserError(_('You do not have the required authority for this step.'))

    @api.depends('code')
    def _compute_filenames(self):
        for rec in self:
            safe_code = (rec.code or 'Certificate').replace('/', '_').replace(' ', '_')
            rec.file_name = f"{safe_code}.pdf"
            rec.certificate_image_filename = f"{safe_code}.png"

    @api.model
    def _format_session_dates(self, session):
        if not session or not session.date_start:
            return ''
        start = fields.Datetime.context_timestamp(self, session.date_start).date()
        end = (fields.Datetime.context_timestamp(self, session.date_end).date()
               if session.date_end else start)
        if start == end:
            return f"{start.strftime('%B')} {start.day}, {start.year}"
        if start.month == end.month and start.year == end.year:
            return (f"{start.strftime('%B')} {start.day} to "
                    f"{end.strftime('%B')} {end.day}, {end.year}")
        return (f"{start.strftime('%B')} {start.day}, {start.year} to "
                f"{end.strftime('%B')} {end.day}, {end.year}")

    @api.model
    def _format_certificate_date(self, value):
        date_value = fields.Date.to_date(value)
        return (f"{date_value.strftime('%B')} {date_value.day}, {date_value.year}"
                if date_value else '')

    @api.depends('session_id.date_start', 'session_id.date_end')
    def _compute_dates_text(self):
        for rec in self:
            rec.training_dates_text = rec._format_session_dates(rec.session_id)

    def _certificate_delivery_details(self):
        """Use issued snapshots; legacy/pending records retain the live session fallback."""
        self.ensure_one()
        session = self.session_id
        method = (self.delivery_method_at_issue if self.provider_snapshot_taken
                  else session.delivery_method)
        if method not in ('local_external', 'international'):
            return method, False, False
        if self.provider_snapshot_taken:
            return method, self.provider_name_at_issue, self.provider_logo_at_issue
        provider = session.awarded_provider_id
        return method, provider.name if provider else False, provider.certificate_logo if provider else False

    @api.model
    def _report_delivery_details(self, document):
        if document._name == 'eds.certificate':
            return document._certificate_delivery_details()
        if document._name == 'eds.session':
            if document.delivery_method in ('local_external', 'international'):
                provider = document.awarded_provider_id
                return (document.delivery_method, provider.name if provider else False,
                        provider.certificate_logo if provider else False)
            return document.delivery_method, False, False
        return 'internal', False, False

    def _snapshot_delivery_details(self):
        for rec in self:
            session = rec.session_id
            method = session.delivery_method
            provider = session.awarded_provider_id if method in ('local_external', 'international') else False
            if method in ('local_external', 'international') and not provider:
                raise ValidationError(_(
                    'Select the actual provider on the external session before issuing its certificate.'))
            rec.write({
                'provider_snapshot_taken': True,
                'delivery_method_at_issue': method,
                'provider_name_at_issue': provider.name if provider else False,
                'provider_logo_at_issue': provider.certificate_logo if provider else False,
            })

    def _formatted_issue_date(self):
        self.ensure_one()
        return self._format_certificate_date(self.issue_date)

    @api.depends('verification_token')
    def _compute_verification_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for rec in self:
            if rec.verification_token:
                rec.verification_url = f"{base_url}/eds/certificate/verify/{rec.verification_token}"
            else:
                rec.verification_url = False

    @api.depends('session_id', 'course_id', 'employee_id', 'training_dates_text')
    def _compute_certificate_content(self):
        for rec in self:
            session = rec.session_id
            course = rec.course_id or (session and session.course_id)
            rec.certificate_title = (session and session.certificate_title) or (course and course.certificate_title) or _("CERTIFICATE OF PARTICIPATION")
            raw_body = (session and session.certificate_body_text) or (course and course.certificate_body_text) or _(
                "For completing the training titled “{course_name}” conducted from {dates_text}."
            )
            emp_name = rec.employee_id.sudo().name if rec.employee_id else _("Participant")
            c_name = (course.name if course else (session.program_name if session else _("Training Course")))
            d_text = rec.training_dates_text or rec._format_session_dates(session)
            rec.certificate_body_text = raw_body.replace("{employee_name}", emp_name).replace("{course_name}", c_name).replace("{dates_text}", d_text)
            
            # Signatories
            rec.signatory_name = (session and session.certificate_signatory_name) or (course and course.certificate_signatory_name) or _("Director, PPDD")
            rec.signatory_title = (session and session.certificate_signatory_title) or (course and course.certificate_signatory_title) or _("Director - People Performance & Development")

    @api.constrains('session_id', 'employee_id', 'state')
    def _check_unique_session_emp_cert(self):
        for rec in self:
            if rec.session_id and rec.employee_id and rec.state != 'void':
                domain = [
                    ('session_id', '=', rec.session_id.id),
                    ('employee_id', '=', rec.employee_id.id),
                    ('state', '!=', 'void'),
                    ('id', '!=', rec.id),
                ]
                if self.search_count(domain) > 0:
                    raise ValidationError(_("An active certificate record already exists for participant %s in session %s.") % (
                        rec.employee_id.sudo().name, rec.session_id.name
                    ))

    def init(self):
        # The ORM check gives a readable error; this index closes its concurrent-create race.
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS eds_certificate_active_session_employee_uniq
            ON eds_certificate (session_id, employee_id)
            WHERE state <> 'void'
        """)

    @api.model_create_multi
    def create(self, vals_list):
        active_pairs = set()
        for vals in vals_list:
            pair = (vals.get('session_id'), vals.get('employee_id'))
            if not all(pair) or vals.get('state', 'pending') == 'void':
                continue
            if pair in active_pairs or self.sudo().search_count([
                    ('session_id', '=', pair[0]),
                    ('employee_id', '=', pair[1]),
                    ('state', '!=', 'void')]):
                raise ValidationError(_(
                    'An active certificate record already exists for this participant and session.'))
            active_pairs.add(pair)
        for vals in vals_list:
            if vals.get('code', _('New')) == _('New'):
                vals['code'] = self.env['ir.sequence'].sudo().next_by_code('eds.certificate') or _('New')
            if not vals.get('verification_token'):
                vals['verification_token'] = uuid.uuid4().hex
        try:
            with self.env.cr.savepoint():
                return super(EdsCertificate, self).create(vals_list)
        except IntegrityError as exc:
            if exc.diag.constraint_name == 'eds_certificate_active_session_employee_uniq':
                raise ValidationError(_(
                    'An active certificate record already exists for this participant and session.')) from exc
            raise

    @api.model
    def _sync_session_candidates(self, session):
        """Create one pending certificate per completed participant, even before Level 2 is ready."""
        sessions = session if hasattr(session, '_name') else self.env['eds.session'].browse(session)
        Certificate = self.sudo()
        for training in sessions.filtered(lambda row: row.status == 'completed'):
            completed = training.enrollment_ids.filtered(lambda row: row.state == 'completed')
            for enrollment in completed.sorted('id'):
                # Recheck after locking: a second completion worker may have
                # created the candidate while this transaction was waiting.
                self.env.cr.execute(
                    'SELECT id FROM eds_enrollment WHERE id = %s FOR UPDATE',
                    (enrollment.id,))
                if not Certificate.search_count([
                        ('session_id', '=', training.id),
                        ('employee_id', '=', enrollment.employee_id.id)]):
                    Certificate.create({
                        'session_id': training.id,
                        'employee_id': enrollment.employee_id.id,
                    })
            candidates = Certificate.search([
                ('session_id', '=', training.id),
                ('employee_id', 'in', completed.mapped('employee_id').ids),
                ('state', '=', 'pending'),
                ('ready_notified', '=', False),
            ])
            for candidate in candidates:
                candidate._compute_eligibility()
                if not candidate.is_eligible:
                    continue
                officers = role_users(candidate, 'group_eds_officer', 'group_eds_manager')
                if officers:
                    notify_action(
                        candidate, officers, _('Issue training certificate'),
                        _('The certificate for %s in %s is eligible and ready for issuance.')
                        % (candidate.employee_id.sudo().name, training.name))
                    candidate.ready_notified = True

    def _compute_eligibility(self):
        # Pre-fetch rules in batch
        all_rules = self.env['eds.certificate.rule'].sudo().search(
            [('active', '=', True)], order='id asc')
        rules_by_category = {r.category: r for r in all_rules}

        # Pre-fetch attendance and level2 evaluations for all records in batch
        session_emp_pairs = [(rec.session_id.id, rec.employee_id.id) for rec in self if rec.session_id and rec.employee_id]
        attendance_map = {}
        l2_map = {}

        if session_emp_pairs:
            session_ids = list({s_id for s_id, _ in session_emp_pairs})
            emp_ids = list({e_id for _, e_id in session_emp_pairs})
            attendances = self.env['eds.session.attendance'].sudo().search([
                ('session_id', 'in', session_ids),
                ('employee_id', 'in', emp_ids),
            ])
            for att in attendances:
                key = (att.session_id.id, att.employee_id.id)
                total, present = attendance_map.get(key, (0, 0))
                attendance_map[key] = (total + 1, present + int(att.attended))

            l2_evals = self.env['eds.evaluation.level2'].sudo().search([
                ('session_id', 'in', session_ids),
                ('employee_id', 'in', emp_ids),
            ])
            for l2 in l2_evals:
                l2_map[(l2.session_id.id, l2.employee_id.id)] = l2

        accepted_by_session = {
            session.id: set(session.sudo()._accepted_attendance_enrollments().mapped('employee_id').ids)
            for session in self.mapped('session_id')
        }
        completed_by_session = {
            session.id: set(session.sudo().enrollment_ids.filtered(
                lambda enrollment: enrollment.state == 'completed').mapped('employee_id').ids)
            for session in self.mapped('session_id')
        }
        periods_by_session = {
            session.id: len(session._attendance_slots())
            for session in self.mapped('session_id')
        }

        for rec in self:
            if not rec.session_id or not rec.employee_id:
                rec.is_eligible = False
                rec.eligibility_reason = _("Missing session or participant data.")
                continue

            if rec.session_id.status != 'completed':
                rec.is_eligible = False
                rec.eligibility_reason = _('The training session has not been completed.')
                continue

            if rec.employee_id.id not in accepted_by_session.get(rec.session_id.id, set()):
                rec.is_eligible = False
                rec.eligibility_reason = _(
                    'The employee has not accepted this training session.')
                continue

            if rec.employee_id.id not in completed_by_session.get(rec.session_id.id, set()):
                rec.is_eligible = False
                rec.eligibility_reason = _('The participant has not completed this training session.')
                continue

            category = rec.course_id.category if rec.course_id else 'developmental'
            rule = rules_by_category.get(category)
            require_attendance = rule.require_attendance if rule else True
            min_att = rule.min_attendance_pct if rule else 80.0
            req_l2 = rule.require_level2_pass if rule else True
            min_l2 = rule.min_level2_score if rule else 60.0

            recorded_periods, present_periods = attendance_map.get(
                (rec.session_id.id, rec.employee_id.id), (0, 0))
            scheduled_periods = periods_by_session[rec.session_id.id]
            total_periods = max(recorded_periods, scheduled_periods)
            att_pct = (round(present_periods * 100.0 / total_periods, 2)
                       if total_periods else 0.0)

            l2_eval = l2_map.get((rec.session_id.id, rec.employee_id.id))
            post_score = (l2_eval.post_test_pct if l2_eval.score_entry_mode
                          else l2_eval.post_score) if l2_eval else 0.0
            if l2_eval and l2_eval.score_entry_mode:
                l2_is_final = bool(
                    l2_eval.state == 'evaluated' and l2_eval.score_confirmed)
            else:
                # Historical linked assessments remain valid for certificates.
                l2_is_final = bool(
                    l2_eval and l2_eval.state == 'evaluated' and
                    l2_eval.pre_assessment_id and l2_eval.post_assessment_id and
                    all(assessment.entry_method == 'score_only' or assessment.state == 'graded'
                        for assessment in (l2_eval.pre_assessment_id | l2_eval.post_assessment_id)))
            l2_is_pass = bool(l2_is_final and l2_eval.passed and post_score >= min_l2)

            reasons = []
            eligible = True

            if require_attendance and att_pct < min_att:
                eligible = False
                reasons.append(_("Attendance %.1f%% below required %.1f%%.") % (att_pct, min_att))
            elif require_attendance:
                reasons.append(_("Attendance %.1f%% meets requirement (≥%.1f%%).") % (att_pct, min_att))
            else:
                reasons.append(_('This course category does not require a minimum attendance percentage.'))

            if req_l2:
                if not l2_is_pass:
                    eligible = False
                    reasons.append(_(
                        'Level 2 must be evaluated and passed with a final post-assessment score of at least %.1f%%.'
                    ) % min_l2)
                else:
                    reasons.append(_("Level 2 score %.1f%% passed (≥%.1f%%).") % (post_score, min_l2))

            rec.is_eligible = eligible
            rec.eligibility_reason = "\n".join(reasons)

    # ── Image Generation Engine (matches photo_2026-10-05_16-59-13.jpg) ─────────
    def _get_font(self, font_name, size):
        candidates = [
            f"/usr/share/fonts/truetype/dejavu/{font_name}.ttf",
            f"/usr/share/fonts/truetype/roboto/unhinted/{font_name}.ttf",
            f"C:/Windows/Fonts/{font_name}.ttf",
            f"C:/Windows/Fonts/{font_name.lower()}.ttf",
            "C:/Windows/Fonts/georgia.ttf",
            "C:/Windows/Fonts/times.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
        for p in candidates:
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except Exception:
                    pass
        try:
            return ImageFont.truetype(font_name, size)
        except Exception:
            return ImageFont.load_default()

    def generate_certificate_image(self):
        """Generates high-resolution certificate image matching official Bunna Bank layout."""
        self.ensure_one()
        bg_relative = os.path.join(
            os.path.dirname(__file__), '..', 'static', 'src', 'img', 'eds_certificate_bg.png'
        )
        bg_path = os.path.abspath(bg_relative)
        if not os.path.exists(bg_path):
            _logger.warning("Certificate background template not found at %s", bg_path)
            # Create a blank white canvas if bg missing
            im = Image.new('RGB', (868, 617), (255, 255, 255))
        else:
            im = Image.open(bg_path).convert('RGB')

        draw = ImageDraw.Draw(im)
        width, height = im.size
        _delivery_method, provider_name, provider_logo = self._certificate_delivery_details()

        if provider_logo:
            try:
                logo = Image.open(io.BytesIO(base64.b64decode(provider_logo))).convert('RGBA')
                logo.thumbnail((88, 70), Image.Resampling.LANCZOS)
                x_logo = width - 67 - logo.width
                y_logo = 62 + (70 - logo.height) // 2
                im.paste(logo, (x_logo, y_logo), logo)
            except (OSError, ValueError) as exc:
                _logger.warning('Could not draw certificate provider logo: %s', exc)

        # Official colors
        color_text = (30, 30, 30)
        color_cno = (20, 20, 20)
        color_maroon = (114, 28, 36)

        # Fonts
        font_cno = self._get_font("DejaVuSans-Bold", 13)
        font_pres = self._get_font("DejaVuSerif", 16)
        font_name = self._get_font("DejaVuSerif-Bold", 24)
        font_body = self._get_font("DejaVuSerif", 14)
        font_sign_label = self._get_font("DejaVuSans-Bold", 12)
        font_sign_val = self._get_font("DejaVuSans", 11)

        # Cover the fixed heading in the Bunna background so the course or
        # session certificate title is reflected in the downloadable image.
        title = (self.certificate_title or _('Certificate of Participation')).upper()
        draw.rectangle((195, 83, 665, 132), fill=(250, 250, 250))
        for size in (20, 18, 16, 14):
            title_font = self._get_font('DejaVuSerif-Bold', size)
            title_width = draw.textbbox((0, 0), title, font=title_font)[2]
            if title_width <= 450:
                break
        draw.text((205 + (450 - title_width) / 2, 99), title,
                  fill=color_text, font=title_font)

        # 1. CNO (Top right)
        cno_text = f"CNO: {self.code}"
        bbox_cno = draw.textbbox((0, 0), cno_text, font=font_cno)
        w_cno = bbox_cno[2] - bbox_cno[0]
        draw.text((815 - w_cno, 145), cno_text, fill=color_cno, font=font_cno)

        # 2. "This Certificate is proudly presented to"
        pres_text = "This Certificate is proudly presented to"
        bbox_pres = draw.textbbox((0, 0), pres_text, font=font_pres)
        w_pres = bbox_pres[2] - bbox_pres[0]
        draw.text(((width - w_pres) / 2, 185), pres_text, fill=color_text, font=font_pres)

        # 3. Participant Name (prominent bold serif maroon)
        name_text = self.employee_id.sudo().name or _("Participant")
        bbox_name = draw.textbbox((0, 0), name_text, font=font_name)
        w_name = bbox_name[2] - bbox_name[0]
        draw.text(((width - w_name) / 2, 240), name_text, fill=color_maroon, font=font_name)

        # 4. Training Title and Dates
        course_name = self.course_id.name or (self.session_id and self.session_id.program_name) or _("Training Course")
        dates_text = self.training_dates_text or ""
        body_text = self.certificate_body_text or (
            f"For completing the training titled “{course_name}” conducted from {dates_text}.")
        body_text = (body_text.replace('{employee_name}', name_text)
                    .replace('{course_name}', course_name)
                    .replace('{dates_text}', dates_text)
                    .replace('{provider_name}', provider_name or ''))
        
        words = body_text.split()
        for font_size in range(14, 8, -1):
            font_body = self._get_font('DejaVuSerif', font_size)
            lines = []
            cur_line = []
            for word in words:
                test_line = ' '.join(cur_line + [word])
                if cur_line and draw.textbbox((0, 0), test_line, font=font_body)[2] > 720:
                    lines.append(' '.join(cur_line))
                    cur_line = [word]
                else:
                    cur_line.append(word)
            if cur_line:
                lines.append(' '.join(cur_line))
            if len(lines) <= 4:
                break

        y_body = 280
        for l in lines:
            bw = draw.textbbox((0, 0), l, font=font_body)[2]
            draw.text(((width - bw) / 2, y_body), l, fill=color_text, font=font_body)
            y_body += 17

        detail_y = max(y_body + 5, 355)
        if dates_text and dates_text.casefold() not in body_text.casefold():
            dates_line = _('Training dates: %s') % dates_text
            dates_width = draw.textbbox((0, 0), dates_line, font=font_sign_val)[2]
            draw.text(((width - dates_width) / 2, detail_y), dates_line,
                      fill=color_text, font=font_sign_val)
            detail_y += 20
        if provider_name and provider_name.casefold() not in body_text.casefold():
            delivered_by = _('Delivered by %s') % provider_name
            provider_font = self._get_font('DejaVuSerif-Bold', 12)
            provider_width = draw.textbbox((0, 0), delivered_by, font=provider_font)[2]
            draw.text(((width - provider_width) / 2, detail_y),
                      delivered_by, fill=color_maroon, font=provider_font)

        # 5. Signatures (Left & Right)
        draw.line([(85, 400), (255, 400)], fill=(80, 80, 80), width=1)
        draw.line([(530, 400), (700, 400)], fill=(80, 80, 80), width=1)

        prep_name = self.prepared_by_name or _("Talent Development Specialist")
        prep_title = self.prepared_by_title or _("Talent Development Specialist")
        draw.text((85, 410), f"Prepared by: {prep_name}", fill=color_text, font=font_sign_label)
        draw.text((85, 430), f"[{prep_title}]", fill=(90, 90, 90), font=font_sign_val)

        app_name = self.signatory_name or _("Director, PPDD")
        app_title = self.signatory_title or _("Director, People Performance & Development")
        draw.text((530, 410), f"Approved by: {app_name}", fill=color_text, font=font_sign_label)
        draw.text((530, 430), f"[{app_title}]", fill=(90, 90, 90), font=font_sign_val)

        issue_text = _('Date of Issue: %s') % self._formatted_issue_date()
        issue_width = draw.textbbox((0, 0), issue_text, font=font_sign_label)[2]
        draw.text((width - 70 - issue_width, 457), issue_text,
                  fill=color_text, font=font_sign_label)

        # Save buffer
        buf = io.BytesIO()
        im.save(buf, format='PNG', quality=95)
        image_bytes = buf.getvalue()
        self.certificate_image = base64.b64encode(image_bytes)
        return image_bytes

    def generate_certificate_pdf(self):
        """Generates print-ready vector PDF matching the template."""
        self.ensure_one()
        report_action = self.env.ref('employee_development_system.action_report_eds_certificate', raise_if_not_found=False)
        if report_action:
            pdf_content, _format = self.env['ir.actions.report']._render_qweb_pdf(
                'employee_development_system.action_report_eds_certificate', [self.id]
            )
            self.file = base64.b64encode(pdf_content)
            return pdf_content
        raise UserError(_('The certificate PDF report is unavailable. Ask an administrator to restore its report action.'))

    def _notify_employee_certificate_issued(self):
        """Delivers congratulations notification to employee with download links and attachments."""
        self.ensure_one()
        employee = self.employee_id.sudo()
        employee_user = employee.user_id
        partner_ids = []
        if employee.work_contact_id:
            partner_ids.append(employee.work_contact_id.id)
        if employee_user and employee_user.active and employee_user.partner_id:
            if employee_user.partner_id.id not in partner_ids:
                partner_ids.append(employee_user.partner_id.id)

        if not partner_ids:
            self.delivery_status = 'needs_contact'
            if self.issued_by:
                notify_action(
                    self, self.issued_by, _('Certificate delivery needs follow-up'),
                    _('Certificate %s was issued, but the employee has no linked contact for a notification.') % self.code)
            return False

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        view_link = f"{base_url}/my/certificates"
        download_img_url = f"{base_url}/my/certificates/download/{self.id}/image"
        download_pdf_url = f"{base_url}/my/certificates/download/{self.id}/pdf"
        verify_url = self.verification_url or f"{base_url}/eds/certificate/verify/{self.verification_token}"

        course_name = self.course_id.name or (self.session_id and self.session_id.program_name) or _("Training Course")
        body_html = Markup(f"""
<div style="font-family: Arial, sans-serif; padding: 15px; border-left: 4px solid #721c24; background-color: #fcfcfc;">
    <h3 style="color: #721c24; margin-top: 0;">🎉 Congratulations, {escape(self.employee_id.sudo().name or '')}!</h3>
    <p>Your official Bunna Bank <strong>Certificate of Participation</strong> has been issued for successfully completing <strong>{escape(course_name)}</strong>.</p>
    <div style="background-color: #ffffff; padding: 12px; border: 1px solid #e0e0e0; border-radius: 6px; margin: 15px 0;">
        <p style="margin: 4px 0;"><strong>Certificate Number:</strong> <span style="font-family: monospace; font-size: 14px; color: #721c24;">{escape(self.code)}</span></p>
        <p style="margin: 4px 0;"><strong>Issue Date:</strong> {self.issue_date.strftime('%B %d, %Y') if self.issue_date else ''}</p>
        <p style="margin: 4px 0;"><strong>Training Dates:</strong> {escape(self.training_dates_text or '')}</p>
    </div>
    <div style="margin-top: 15px;">
        <a href="{download_img_url}" style="background-color: #721c24; color: #FFFFFF; padding: 8px 16px; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 13px; display: inline-block; margin-right: 8px;">🖼️ Download Certificate Image (.png)</a>
        <a href="{download_pdf_url}" style="background-color: #17a2b8; color: #FFFFFF; padding: 8px 16px; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 13px; display: inline-block; margin-right: 8px;">📄 Download PDF (.pdf)</a>
        <a href="{view_link}" style="background-color: #6c757d; color: #FFFFFF; padding: 8px 16px; text-decoration: none; border-radius: 4px; font-weight: bold; font-size: 13px; display: inline-block; margin-right: 8px;">🎓 View in My Portal</a>
        <a href="{verify_url}" target="_blank" style="color: #721c24; text-decoration: underline; font-size: 12px; display: inline-block; margin-top: 8px;">🛡️ Public Verification Link</a>
    </div>
</div>
        """)

        # Attach image and PDF to message
        attachments = []
        if self.certificate_image:
            att_img = self.env['ir.attachment'].create({
                'name': self.certificate_image_filename or f"{self.code}.png",
                'type': 'binary',
                'datas': self.certificate_image,
                'res_model': self._name,
                'res_id': self.id,
                'mimetype': 'image/png',
            })
            attachments.append(att_img.id)
        if self.file:
            att_pdf = self.env['ir.attachment'].create({
                'name': self.file_name or f"{self.code}.pdf",
                'type': 'binary',
                'datas': self.file,
                'res_model': self._name,
                'res_id': self.id,
                'mimetype': 'application/pdf',
            })
            attachments.append(att_pdf.id)

        self.with_context(eds_popup_managed=True).message_post(
            body=body_html,
            partner_ids=partner_ids,
            attachment_ids=attachments,
            message_type='notification',
            subtype_xmlid='mail.mt_comment',
            author_id=self.env.user.partner_id.id,
        )
        if employee_user and employee_user.active:
            push_action_popup(
                self, employee_user,
                _('Certificate issued'),
                _('Your certificate for %s is ready to view or download.') % course_name)
        self.delivery_status = ('notified' if employee_user and employee_user.active
                                else 'needs_contact')
        if self.delivery_status == 'needs_contact' and self.issued_by:
            notify_action(
                self, self.issued_by, _('Certificate delivery needs follow-up'),
                _('Certificate %s has no active employee account for the portal notification.') % self.code)
        return self.delivery_status == 'notified'

    def action_issue(self):
        with self.env.cr.savepoint():
            for rec in self:
                rec._require_group('group_eds_officer')
                if rec.state != 'pending':
                    raise UserError(_("Only certificates pending eligibility check can be issued."))
                rec._compute_eligibility()
                if not rec.is_eligible:
                    raise ValidationError(_(
                        "Cannot issue certificate: participant is not eligible.\n%s") % rec.eligibility_reason)

                if not rec.verification_token:
                    rec.verification_token = uuid.uuid4().hex

                rec._snapshot_delivery_details()
                rec.issue_date = fields.Date.context_today(self)

                # Both files must exist before an employee receives a download notice.
                rec.generate_certificate_image()
                pdf_content = rec.generate_certificate_pdf()
                if not pdf_content or not rec.file:
                    raise UserError(_(
                        'The certificate PDF could not be generated; the certificate remains pending.'))
                rec.write({'state': 'issued', 'issued_by': self.env.user.id})
                clear_action_activities(rec)
                rec._notify_employee_certificate_issued()

    def action_void(self):
        for rec in self:
            rec._require_group('group_eds_manager')
            if rec.state != 'issued':
                raise UserError(_("Only issued certificates can be voided."))
            rec.state = 'void'
            # The partial unique index must see the void state before a
            # replacement can be created in this transaction.
            rec.flush_recordset(['state'])
            rec.message_post(body=_("Certificate %s voided.") % rec.code)
            message = _(
                'Your certificate %s for %s has been voided. Contact L&D if you need clarification.'
            ) % (rec.code, rec.course_id.name or
                 (rec.session_id and rec.session_id.program_name) or _('training'))
            employee = rec.employee_id.sudo()
            if employee.user_id:
                notify_action(rec, employee.user_id,
                              _('Training certificate voided'), message,
                              action_required=False)
            elif employee.work_contact_id:
                rec.message_post(body=message,
                                 partner_ids=employee.work_contact_id.ids,
                                 author_id=self.env.user.partner_id.id)

    def action_download_image(self):
        self.ensure_one()
        if not self.certificate_image:
            self.generate_certificate_image()
        return {
            'type': 'ir.actions.act_url',
            'url': f"/my/certificates/download/{self.id}/image",
            'target': 'self',
        }

    def action_download_pdf(self):
        self.ensure_one()
        if not self.file:
            self.generate_certificate_pdf()
        return {
            'type': 'ir.actions.act_url',
            'url': f"/my/certificates/download/{self.id}/pdf",
            'target': 'self',
        }

    def action_regenerate_assets(self):
        """Allows Officer or Admin to regenerate image and PDF assets if dates/signatories changed."""
        for rec in self:
            rec._require_group('group_eds_officer')
            rec.generate_certificate_image()
            if not rec.generate_certificate_pdf() or not rec.file:
                raise UserError(_('The certificate PDF could not be regenerated.'))
        return True
