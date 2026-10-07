# -*- coding: utf-8 -*-
import os
import io
import base64
import uuid
import logging
from markupsafe import Markup, escape
from PIL import Image, ImageDraw, ImageFont

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class EdsCertificateRule(models.Model):
    _name = 'eds.certificate.rule'
    _description = 'EDS Certification Policy / Rule'
    _inherit = ['mail.thread']

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


class EdsCertificate(models.Model):
    _name = 'eds.certificate'
    _description = 'EDS Training Completion Certificate'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    code = fields.Char(string='Certificate Number', required=True, copy=False, readonly=True, default=lambda self: _('New'))
    employee_id = fields.Many2one('hr.employee', string='Participant', required=True, index=True, tracking=True)
    session_id = fields.Many2one('eds.session', string='Training Session', required=True, ondelete='cascade', index=True, tracking=True)
    course_id = fields.Many2one('eds.course', related='session_id.course_id', string='Course', store=True, index=True)
    issue_date = fields.Date(string='Issue Date', default=fields.Date.context_today, required=True, tracking=True)
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
    
    issued_by = fields.Many2one('res.users', string='Issued By', default=lambda self: self.env.user)
    
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

    @api.depends('session_id.date_start', 'session_id.date_end')
    def _compute_dates_text(self):
        for rec in self:
            sess = rec.session_id
            if sess and sess.date_start and sess.date_end:
                d1 = sess.date_start
                d2 = sess.date_end
                if d1.month == d2.month and d1.year == d2.year:
                    rec.training_dates_text = f"{d1.strftime('%B %d')} - {d2.strftime('%d, %Y')}"
                else:
                    rec.training_dates_text = f"{d1.strftime('%b %d, %Y')} - {d2.strftime('%b %d, %Y')}"
            elif sess and sess.date_start:
                rec.training_dates_text = sess.date_start.strftime('%B %d, %Y')
            else:
                rec.training_dates_text = fields.Date.context_today(self).strftime('%B %d, %Y')

    @api.depends('verification_token')
    def _compute_verification_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for rec in self:
            if rec.verification_token:
                rec.verification_url = f"{base_url}/eds/certificate/verify/{rec.verification_token}"
            else:
                rec.verification_url = False

    @api.depends('session_id', 'course_id', 'employee_id')
    def _compute_certificate_content(self):
        for rec in self:
            session = rec.session_id
            course = rec.course_id or (session and session.course_id)
            rec.certificate_title = (session and session.certificate_title) or (course and course.certificate_title) or _("CERTIFICATE OF PARTICIPATION")
            raw_body = (session and session.certificate_body_text) or (course and course.certificate_body_text) or _(
                "For completing the training titled “{course_name}” conducted from {dates_text}."
            )
            emp_name = rec.employee_id.name if rec.employee_id else _("Participant")
            c_name = (course.name if course else (session.program_name if session else _("Training Course")))
            d_text = rec.training_dates_text or (session and session.date_start and session.date_start.strftime('%B %d, %Y')) or ''
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
                        rec.employee_id.name, rec.session_id.name
                    ))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code', _('New')) == _('New'):
                vals['code'] = self.env['ir.sequence'].sudo().next_by_code('eds.certificate') or _('New')
            if not vals.get('verification_token'):
                vals['verification_token'] = uuid.uuid4().hex
        return super(EdsCertificate, self).create(vals_list)

    def _compute_eligibility(self):
        # Pre-fetch rules in batch
        all_rules = self.env['eds.certificate.rule'].sudo().search([('active', '=', True)])
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
                attendance_map[(att.session_id.id, att.employee_id.id)] = att

            l2_evals = self.env['eds.evaluation.level2'].sudo().search([
                ('session_id', 'in', session_ids),
                ('employee_id', 'in', emp_ids),
            ])
            for l2 in l2_evals:
                l2_map[(l2.session_id.id, l2.employee_id.id)] = l2

        for rec in self:
            if not rec.session_id or not rec.employee_id:
                rec.is_eligible = False
                rec.eligibility_reason = _("Missing session or participant data.")
                continue

            category = rec.course_id.category if rec.course_id else 'developmental'
            rule = rules_by_category.get(category)
            min_att = rule.min_attendance_pct if rule else 80.0
            req_l2 = rule.require_level2_pass if rule else True
            min_l2 = rule.min_level2_score if rule else 60.0

            attendance = attendance_map.get((rec.session_id.id, rec.employee_id.id))
            att_pct = attendance.attendance_percentage if attendance else 0.0

            l2_eval = l2_map.get((rec.session_id.id, rec.employee_id.id))
            post_score = l2_eval.post_score if l2_eval else 0.0
            l2_is_pass = (l2_eval.passed if l2_eval else False) or (post_score >= min_l2)

            reasons = []
            eligible = True

            if att_pct < min_att:
                eligible = False
                reasons.append(_("Attendance %.1f%% below required %.1f%%.") % (att_pct, min_att))
            else:
                reasons.append(_("Attendance %.1f%% meets requirement (≥%.1f%%).") % (att_pct, min_att))

            if req_l2:
                if not l2_eval or not l2_is_pass or post_score < min_l2:
                    eligible = False
                    reasons.append(_("Level 2 post-assessment score %.1f%% below required %.1f%%.") % (post_score, min_l2))
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
        name_text = self.employee_id.name or _("Participant")
        bbox_name = draw.textbbox((0, 0), name_text, font=font_name)
        w_name = bbox_name[2] - bbox_name[0]
        draw.text(((width - w_name) / 2, 240), name_text, fill=color_maroon, font=font_name)

        # 4. Training Title and Dates
        course_name = self.course_id.name or (self.session_id and self.session_id.program_name) or _("Training Course")
        dates_text = self.training_dates_text or ""
        body_text = f"For completing the training titled “{course_name}” conducted from {dates_text}."
        
        words = body_text.split()
        lines = []
        cur_line = []
        for w in words:
            test_line = ' '.join(cur_line + [w])
            bw = draw.textbbox((0, 0), test_line, font=font_body)[2]
            if bw > 720 and cur_line:
                lines.append(' '.join(cur_line))
                cur_line = [w]
            else:
                cur_line.append(w)
        if cur_line:
            lines.append(' '.join(cur_line))

        y_body = 290
        for l in lines:
            bw = draw.textbbox((0, 0), l, font=font_body)[2]
            draw.text(((width - bw) / 2, y_body), l, fill=color_text, font=font_body)
            y_body += 22

        # 5. Signatures (Left & Right)
        draw.line([(85, 365), (255, 365)], fill=(80, 80, 80), width=1)
        draw.line([(530, 365), (700, 365)], fill=(80, 80, 80), width=1)

        prep_name = self.prepared_by_name or _("Talent Development Specialist")
        prep_title = self.prepared_by_title or _("Talent Development Specialist")
        draw.text((85, 375), f"Prepared by: {prep_name}", fill=color_text, font=font_sign_label)
        draw.text((85, 395), f"[{prep_title}]", fill=(90, 90, 90), font=font_sign_val)

        app_name = self.signatory_name or _("Director, PPDD")
        app_title = self.signatory_title or _("Director, People Performance & Development")
        draw.text((530, 375), f"Approved by: {app_name}", fill=color_text, font=font_sign_label)
        draw.text((530, 395), f"[{app_title}]", fill=(90, 90, 90), font=font_sign_val)

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
        return None

    def _notify_employee_certificate_issued(self):
        """Delivers congratulations notification to employee with download links and attachments."""
        self.ensure_one()
        partner_ids = []
        if self.employee_id and self.employee_id.work_contact_id:
            partner_ids.append(self.employee_id.work_contact_id.id)
        if self.employee_id and self.employee_id.user_id and self.employee_id.user_id.partner_id:
            if self.employee_id.user_id.partner_id.id not in partner_ids:
                partner_ids.append(self.employee_id.user_id.partner_id.id)

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        view_link = f"{base_url}/my/certificates"
        download_img_url = f"{base_url}/my/certificates/download/{self.id}/image"
        download_pdf_url = f"{base_url}/my/certificates/download/{self.id}/pdf"
        verify_url = self.verification_url or f"{base_url}/eds/certificate/verify/{self.verification_token}"

        course_name = self.course_id.name or (self.session_id and self.session_id.program_name) or _("Training Course")
        body_html = Markup(f"""
<div style="font-family: Arial, sans-serif; padding: 15px; border-left: 4px solid #721c24; background-color: #fcfcfc;">
    <h3 style="color: #721c24; margin-top: 0;">🎉 Congratulations, {escape(self.employee_id.name or '')}!</h3>
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

        self.message_post(
            body=body_html,
            partner_ids=partner_ids,
            attachment_ids=attachments,
            message_type='notification',
            subtype_xmlid='mail.mt_comment',
        )

    def action_issue(self):
        for rec in self:
            rec._require_group('group_eds_officer')
            if rec.state != 'pending':
                raise UserError(_("Only certificates pending eligibility check can be issued."))
            rec._compute_eligibility()
            if not rec.is_eligible:
                raise ValidationError(_("Cannot issue certificate: participant is not eligible.\n%s") % rec.eligibility_reason)
            
            if not rec.verification_token:
                rec.verification_token = uuid.uuid4().hex

            rec.state = 'issued'
            rec.issue_date = fields.Date.context_today(self)
            
            # Generate Image and PDF
            rec.generate_certificate_image()
            try:
                rec.generate_certificate_pdf()
            except Exception as e:
                _logger.warning("Could not pre-render certificate PDF on issue: %s", str(e))

            # Deliver notification to employee
            rec._notify_employee_certificate_issued()

    def action_void(self):
        for rec in self:
            rec._require_group('group_eds_manager')
            if rec.state != 'issued':
                raise UserError(_("Only issued certificates can be voided."))
            rec.state = 'void'
            rec.message_post(body=_("Certificate %s voided.") % rec.code)

    def action_download_image(self):
        self.ensure_one()
        if not self.certificate_image:
            self.generate_certificate_image()
        return {
            'type': 'ir.actions.act_url',
            'url': f"/web/content/eds.certificate/{self.id}/certificate_image/{self.certificate_image_filename}?download=true",
            'target': 'self',
        }

    def action_download_pdf(self):
        self.ensure_one()
        if not self.file:
            self.generate_certificate_pdf()
        return {
            'type': 'ir.actions.act_url',
            'url': f"/web/content/eds.certificate/{self.id}/file/{self.file_name}?download=true",
            'target': 'self',
        }

    def action_regenerate_assets(self):
        """Allows Officer or Admin to regenerate image and PDF assets if dates/signatories changed."""
        for rec in self:
            rec._require_group('group_eds_officer')
            rec.generate_certificate_image()
            try:
                rec.generate_certificate_pdf()
            except Exception as e:
                _logger.warning("Error regenerating certificate PDF: %s", str(e))
        return True
