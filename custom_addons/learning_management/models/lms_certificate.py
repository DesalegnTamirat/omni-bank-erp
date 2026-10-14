# -*- coding: utf-8 -*-
import uuid
import hashlib
import base64
import logging
from datetime import date
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


class LmsCertificateTemplate(models.Model):
    """Customizable Certificate Template (FR-LMS-019)."""
    _name = 'lms.certificate.template'
    _description = 'LMS Certificate Template'
    _order = 'name'

    name = fields.Char(string='Template Title', required=True)
    header_text = fields.Char(string='Header Title', default='CERTIFICATE OF ACHIEVEMENT')
    subtitle_text = fields.Char(string='Subtitle', default='BUNNA BANK S.C. LEARNING & DEVELOPMENT')
    body_text = fields.Html(
        string='Certificate Body Text',
        default="<p>This is to certify that <strong>${learner_name}</strong> has successfully completed the corporate training program in <strong>${course_name}</strong> and demonstrated verified mastery of required competencies.</p>"
    )
    signatory_1_name = fields.Char(string='First Signatory Name', default='Chief Human Resources Officer')
    signatory_1_title = fields.Char(string='First Signatory Title', default='People Performance & Development')
    signatory_1_signature = fields.Binary(string='Signatory 1 Digital Signature', attachment=True)

    signatory_2_name = fields.Char(string='Second Signatory Name', default='Chief Executive Officer')
    signatory_2_title = fields.Char(string='Second Signatory Title', default='Bunna Bank S.C.')
    signatory_2_signature = fields.Binary(string='Signatory 2 Digital Signature', attachment=True)

    logo = fields.Binary(string='Institutional Crest / Logo', attachment=True)
    active = fields.Boolean(default=True)


class LmsCertificate(models.Model):
    """
    Issued Certification Record with QR/Hash Verification (FR-LMS-018, FR-LMS-020, FR-LMS-021, FR-LMS-022).
    Automatically routes completion records to core HR employee master data (`hr.training.history`
    and `hr.employee.document`).
    """
    _name = 'lms.certificate'
    _description = 'LMS Issued Training Certificate'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'issue_date desc'

    name = fields.Char(string='Certificate Number', readonly=True, copy=False, default=lambda self: _('New'), index=True)
    verification_code = fields.Char(string='Security Verification Hash', readonly=True, copy=False, index=True)
    verification_url = fields.Char(string='Verification URL', compute='_compute_verification_url')

    employee_id = fields.Many2one('hr.employee', string='Certified Employee', required=True, tracking=True, index=True)
    department_id = fields.Many2one('hr.department', related='employee_id.department_id', string='Department', store=True, readonly=True)
    operating_unit_id = fields.Many2one('operating.unit', related='employee_id.default_operating_unit_id', string='Branch / Unit', store=True, readonly=True)

    course_id = fields.Many2one('lms.course', string='Course', required=True, tracking=True, index=True)
    enrollment_id = fields.Many2one('lms.enrollment', string='Enrollment Reference', ondelete='set null')
    template_id = fields.Many2one('lms.certificate.template', string='Visual Template')

    issue_date = fields.Date(string='Issuance Date', default=fields.Date.context_today, required=True, tracking=True)
    expiry_date = fields.Date(string='Expiry Date', tracking=True)
    score_percentage = fields.Float(string='Score Achieved (%)', readonly=True)

    state = fields.Selection([
        ('valid', 'Active & Valid'),
        ('expired', 'Expired (Recertification Due)'),
        ('revoked', 'Revoked / Invalidated'),
    ], string='Certification Status', default='valid', tracking=True, required=True, index=True)

    # Core HR Bridge References (FR-LMS-022)
    hr_training_history_id = fields.Many2one('hr.training.history', string='Linked HR Training History', readonly=True)
    hr_employee_document_id = fields.Many2one('hr.employee.document', string='Linked Employee Document', readonly=True)

    certificate_pdf = fields.Binary(string='Certificate PDF File', attachment=True)
    certificate_filename = fields.Char(string='Certificate Filename')
    delivery_state = fields.Selection([
        ('pending', 'Pending'), ('complete', 'Complete'), ('error', 'Needs Retry'),
    ], default='pending', readonly=True, string='PDF / HR Delivery')
    delivery_error = fields.Text(string='Delivery Error', readonly=True)

    @api.depends('verification_code')
    def _compute_verification_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for rec in self:
            if rec.verification_code:
                rec.verification_url = f"{base_url}/lms/certificate/verify/{rec.verification_code}"
            else:
                rec.verification_url = False

    @api.model
    def issue_certificate(self, enrollment, score_pct):
        """Issues certificate, calculates expiry, generates hash, and bridges to core HR."""
        course = enrollment.course_id
        today = date.today()
        months = course.certificate_validity_months
        exp_date = today + relativedelta(months=months) if months > 0 else False

        # Generate unique verification hash
        raw_token = f"{enrollment.employee_id.id}-{course.id}-{today.isoformat()}-{uuid.uuid4().hex}"
        vcode = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()[:16].upper()
        cert_num = self.env['ir.sequence'].next_by_code('lms.certificate') or _('New')

        cert = self.create({
            'name': cert_num,
            'verification_code': vcode,
            'employee_id': enrollment.employee_id.id,
            'course_id': course.id,
            'enrollment_id': enrollment.id,
            'template_id': course.certificate_template_id.id if course.certificate_template_id else False,
            'issue_date': today,
            'expiry_date': exp_date,
            'score_percentage': score_pct,
            'state': 'valid',
            'certificate_filename': f"Bunna_Cert_{cert_num.replace('/', '_')}.pdf",
        })

        cert.action_retry_delivery()
        return cert

    def action_retry_delivery(self):
        """Finish missing PDF and HR artifacts without creating duplicates."""
        if not self.env.su and not self.env.user.has_group('learning_management.group_lms_manager'):
            raise AccessError(_('Only LMS managers may retry certificate delivery.'))
        for cert in self:
            errors = []
            if not cert.certificate_pdf:
                try:
                    with self.env.cr.savepoint():
                        pdf_bytes, _ = self.env['ir.actions.report']._render_qweb_pdf(
                            'learning_management.report_lms_certificate', [cert.id]
                        )
                        if not pdf_bytes:
                            raise UserError(_('The certificate report returned an empty PDF.'))
                        cert.sudo().certificate_pdf = base64.b64encode(pdf_bytes)
                except Exception as exc:
                    _logger.exception('Certificate %s PDF rendering failed', cert.id)
                    errors.append(_('PDF: %s') % exc)
            if not cert.hr_training_history_id:
                try:
                    with self.env.cr.savepoint():
                        enrollment = cert.enrollment_id
                        history = self.env['hr.training.history'].sudo().create({
                            'employee_id': cert.employee_id.id,
                            'training_name': cert.course_id.name,
                            'training_type': 'Online E-Learning (LMS)',
                            'institution_name': 'Bunna Bank S.C. E-Academy',
                            'start_date': enrollment.enrollment_date if enrollment else cert.issue_date,
                            'end_date': cert.issue_date,
                            'status': 'completed',
                            'comments': _('Certified online with score %.1f%%. Cert No: %s') % (
                                cert.score_percentage, cert.name),
                        })
                        cert.sudo().hr_training_history_id = history.id
                except Exception as exc:
                    _logger.exception('Certificate %s HR history sync failed', cert.id)
                    errors.append(_('HR history: %s') % exc)
            if not cert.hr_employee_document_id:
                try:
                    with self.env.cr.savepoint():
                        if not cert.certificate_pdf:
                            raise UserError(_('Render the certificate PDF before creating the HR document.'))
                        doc_type = self.env['hr.document.type'].sudo().search(
                            [('name', 'ilike', 'Training')], limit=1
                        ) or self.env['hr.document.type'].sudo().search([], limit=1)
                        if not doc_type:
                            raise UserError(_('Configure an HR training document type.'))
                        employee_document = self.env['hr.employee.document'].sudo().create({
                            'name': _('Training Certificate - %s') % cert.course_id.name,
                            'employee_ref': cert.employee_id.id,
                            'document_type': doc_type.id,
                            'description': _('Issued by LMS on %s. Verification: %s') % (
                                cert.issue_date, cert.verification_code),
                            'attachment': cert.certificate_pdf or False,
                            'attachment_filename': cert.certificate_filename,
                        })
                        cert.sudo().hr_employee_document_id = employee_document.id
                except Exception as exc:
                    _logger.exception('Certificate %s HR document sync failed', cert.id)
                    errors.append(_('HR document: %s') % exc)
            cert.sudo().write({
                'delivery_state': 'error' if errors else 'complete',
                'delivery_error': '\n'.join(errors) if errors else False,
            })

    @api.model
    def cron_retry_delivery(self):
        self.sudo().search([('delivery_state', '!=', 'complete')], limit=100).action_retry_delivery()

    @api.model
    def cron_check_certificate_expiry(self):
        """Cron scheduled task to transition expired certifications (FR-LMS-020)."""
        today = date.today()
        expired_certs = self.search([
            ('state', '=', 'valid'),
            ('expiry_date', '!=', False),
            ('expiry_date', '<', today)
        ])
        for cert in expired_certs:
            cert.write({'state': 'expired'})
            cert.message_post(body=_('Certification validity has expired. Recertification required.'))
