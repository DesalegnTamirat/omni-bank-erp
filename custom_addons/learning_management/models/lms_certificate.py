# -*- coding: utf-8 -*-
import uuid
import hashlib
from datetime import date
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError


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
        months = course.certificate_validity_months or 12
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

        # Bridge 1: Automatically push to core HR hr.training.history (FR-LMS-022)
        try:
            th = self.env['hr.training.history'].create({
                'employee_id': enrollment.employee_id.id,
                'training_name': course.name,
                'training_type': 'Online E-Learning (LMS)',
                'institution_name': 'Bunna Bank S.C. E-Academy',
                'start_date': enrollment.enrollment_date,
                'end_date': today,
                'status': 'completed',
                'comments': f"Certified online with score of {score_pct:.1f}%. Cert No: {cert_num}",
            })
            cert.hr_training_history_id = th.id
        except Exception as e:
            cert.message_post(body=_('Warning: Could not link to hr.training.history: %s') % e)

        # Bridge 2: Attach to hr.employee.document (FR-LMS-022)
        try:
            doc_type = self.env['hr.document.type'].search([('name', 'ilike', 'Training')], limit=1)
            if not doc_type:
                doc_type = self.env['hr.document.type'].search([], limit=1)

            if doc_type:
                emp_doc = self.env['hr.employee.document'].create({
                    'name': f"Training Certificate - {course.name}",
                    'employee_ref': enrollment.employee_id.id,
                    'document_type': doc_type.id,
                    'description': f"Issued by Bunna LMS on {today}. Verification Code: {vcode}",
                })
                cert.hr_employee_document_id = emp_doc.id
        except Exception as e:
            cert.message_post(body=_('Warning: Could not link to hr.employee.document: %s') % e)

        return cert

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
