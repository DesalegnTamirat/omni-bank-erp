# -*- coding: utf-8 -*-
import base64
from odoo import http, fields, _
from odoo.http import request, content_disposition
from odoo.exceptions import AccessError


class PortalCertificateController(http.Controller):
    """Employee Portal & Public Verification Controller for Bunna Bank Certificates."""

    @http.route(['/my/certificates'], type='http', auth='user', website=True)
    def portal_my_certificates(self, **kw):
        """Displays all completion certificates earned by the logged-in employee."""
        user = request.env.user
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        certificates = request.env['eds.certificate'].sudo().search([
            ('employee_id', '=', employee.id if employee else 0),
            ('state', '=', 'issued')
        ], order='issue_date desc, id desc')

        values = {
            'employee': employee,
            'certificates': certificates,
            'page_name': 'my_certificates',
        }
        return request.render('employee_development_system.portal_my_certificates_template', values)

    @http.route(['/my/certificates/download/<int:cert_id>/<string:file_type>'], type='http', auth='user')
    def portal_download_certificate(self, cert_id, file_type, **kw):
        """Secure download endpoint for PDF or PNG certificate assets."""
        user = request.env.user
        cert = request.env['eds.certificate'].sudo().browse(cert_id)
        if not cert.exists():
            return request.not_found()

        # Security check: User must own the certificate or belong to EDS Officer/Manager/Admin group
        is_owner = cert.employee_id and cert.employee_id.user_id and cert.employee_id.user_id.id == user.id
        is_officer = user.has_group('employee_development_system.group_eds_officer')
        is_admin = user.has_group('employee_development_system.group_eds_admin')

        if not (is_owner or is_officer or is_admin):
            raise AccessError(_("You are not authorized to download this certificate."))

        if file_type == 'image':
            if not cert.certificate_image:
                cert.generate_certificate_image()
            data = base64.b64decode(cert.certificate_image)
            filename = cert.certificate_image_filename or f"{cert.code}.png"
            mimetype = 'image/png'
        else:
            if not cert.file:
                cert.generate_certificate_pdf()
            data = base64.b64decode(cert.file) if cert.file else b''
            filename = cert.file_name or f"{cert.code}.pdf"
            mimetype = 'application/pdf'

        return request.make_response(
            data,
            headers=[
                ('Content-Type', mimetype),
                ('Content-Disposition', content_disposition(filename)),
                ('Content-Length', len(data)),
            ]
        )

    @http.route(['/eds/certificate/verify/<string:token>', '/certificate/verify/<string:token>'], type='http', auth='public', website=True)
    def public_verify_certificate(self, token, **kw):
        """Public certificate verification page (accessible via QR code or verification link)."""
        clean_token = (token or '').strip()
        # Search by verification token, or code fallback
        cert = request.env['eds.certificate'].sudo().search([
            '|',
            ('verification_token', '=', clean_token),
            ('code', '=ilike', clean_token),
        ], limit=1)

        values = {
            'cert': cert,
            'token': clean_token,
            'is_valid': bool(cert and cert.state == 'issued'),
            'is_void': bool(cert and cert.state == 'void'),
            'found': bool(cert),
        }
        return request.render('employee_development_system.portal_certificate_verify_template', values)

    @http.route(['/eds/certificate/verify'], type='http', auth='public', website=True)
    def public_verify_search(self, cno=None, **kw):
        """Public search page allowing manual certificate number entry."""
        if cno:
            return request.redirect(f"/eds/certificate/verify/{cno.strip()}")
        return request.render('employee_development_system.portal_certificate_verify_template', {
            'cert': False,
            'token': '',
            'found': False,
        })
