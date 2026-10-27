# -*- coding: utf-8 -*-
import base64
import io
import logging
import mimetypes
from datetime import datetime
from html import escape as html_escape
from PyPDF2 import PdfReader, PdfWriter
from werkzeug.http import dump_options_header
from odoo import http, _
from odoo.http import request, Response, content_disposition
from odoo.exceptions import AccessError
from ..utils.watermarker import add_watermark_to_pdf
from ..utils.encryption import encrypt_document_data, decrypt_document_data

_logger = logging.getLogger(__name__)


class KmsDocumentController(http.Controller):

    @http.route(['/kms/document/<int:doc_id>/download'], type='http', auth='user')
    def kms_download_document(self, doc_id, **kwargs):
        """
        Secure Document Download with Dynamic PDF Watermarking and Session Encryption (FR-KMS-014, FR-KMS-015, FR-KMS-016, FR-KMS-017).
        Enforces:
        - Read permission / record rules check
        - View-only check (blocks download if strict view-only)
        - Role-based download permission check
        - Dynamic PDF stamping of downloader identity, department, and timestamp
        - Session-bound symmetric encryption for non-PDF files and encrypted-policy documents
        - Non-editable audit logging
        """
        user = request.env.user
        doc = request.env['kms.document'].browse(doc_id)

        try:
            doc.check_access('read')
        except AccessError:
            return request.render('http_routing.403', {'message': _('Access Denied: You do not have permission to access this document.')})

        if not doc.exists():
            return request.not_found()

        # View-only restriction check
        if doc.is_view_only and not user.has_group('knowledge_management.group_kms_manager'):
            doc._log_audit_action('access_denied', 'Download blocked: Document is marked View-Only')
            return request.render('http_routing.403', {'message': _('This document is designated as View-Only. Downloading is prohibited by policy.')})

        # Role-based download permissions check
        if doc.allowed_download_group_ids:
            user_groups = user.group_ids
            if not any(g in user_groups for g in doc.allowed_download_group_ids) and not user.has_group('knowledge_management.group_kms_manager'):
                doc._log_audit_action('access_denied', 'Download blocked: Role not permitted')
                return request.render('http_routing.403', {'message': _('Your assigned role does not have download permissions for this document.')})

        if not doc.sudo().file_data:
            return request.not_found()

        if len(doc.sudo().file_data) > 50 * 1024 * 1024 * 4 // 3:
            return Response(_('This file exceeds the protected-download size limit.'), status=413)
        raw_bytes = base64.b64decode(doc.sudo().file_data)
        filename = doc.file_name or f"KMS_Document_{doc.code}.pdf"
        mimetype = doc.mimetype or 'application/pdf'

        # Apply Dynamic Watermarking if enabled for PDF (FR-KMS-015)
        if (doc.require_watermark or doc.state == 'approved') and doc.is_pdf:
            emp = user.employee_id
            emp_name = emp.name if emp else user.name
            emp_code = emp.barcode or emp.identification_id or f"UID-{user.id}"
            dept_name = emp.department_id.name if (emp and emp.department_id) else "Bunna Bank"
            timestamp_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
            classification = doc.classification_id.name if doc.classification_id else (doc.classification or "INTERNAL")

            watermark_lines = [
                f"BUNNA BANK S.C. - {classification.upper()} DOCUMENT",
                f"Downloaded By: {emp_name} ({emp_code})",
                f"Dept: {dept_name} | Date: {timestamp_str}",
                "UNAUTHORIZED COPYING OR DISTRIBUTION IS STRICTLY PROHIBITED"
            ]

            try:
                watermarked_bytes = add_watermark_to_pdf(raw_bytes, watermark_lines)
                raw_bytes = watermarked_bytes
            except Exception as e:
                _logger.error("Error applying watermark to doc %s: %s", doc.id, e)
                return Response(_('Protected download is temporarily unavailable.'), status=503)

        # Determine active session ID or explicit token for session-binding (FR-KMS-016)
        session_id = None
        if hasattr(request, 'session') and request.session:
            session_id = getattr(request.session, 'sid', None)

        # Apply Session-Bound Symmetric Encryption (FR-KMS-016 & FR-KMS-015 non-PDF protection)
        # Note on office document watermarking (FR-KMS-015):
        # Dynamic visual watermarking operates on PDF vector streams via reportlab/pypdf.
        # For non-PDF binary office files (.docx, .xlsx, .pptx), full session-bound encryption
        # is strictly enforced (is_encrypted = True) so that office binaries can never leave the bank
        # server in an unprotected raw state.
        # Every downloadable copy is encrypted, including public/internal PDFs.
        # The older per-document flag remains for compatibility with existing data.
        is_encrypted = True
        if is_encrypted:
            raw_bytes = encrypt_document_data(raw_bytes, doc.id, user.id, session_id=session_id, env=request.env)
            if not filename.endswith('.enc'):
                filename = f"{filename}.enc"
            mimetype = 'application/octet-stream'

        # Log download audit event
        doc._log_audit_action('download', f"Downloaded by {user.name} (encrypted={is_encrypted})", strict=True)
        request.env.cr.execute(
            'UPDATE kms_document SET download_count = COALESCE(download_count, 0) + 1 WHERE id = %s',
            (doc.id,),
        )
        doc.invalidate_recordset(['download_count'])

        headers = [
            ('Content-Type', mimetype),
            ('Content-Disposition', content_disposition(filename)),
            ('Content-Length', len(raw_bytes)),
            ('X-KMS-Encrypted', '1' if is_encrypted else '0'),
            ('Cache-Control', 'no-cache, no-store, must-revalidate'),
            ('Pragma', 'no-cache'),
            ('Expires', '0'),
            ('X-Content-Type-Options', 'nosniff'),
        ]
        return Response(raw_bytes, headers=headers)

    @http.route(['/kms/document/<int:doc_id>/view'], type='http', auth='user', methods=['GET', 'POST'], csrf=False)
    def kms_view_document(self, doc_id, **kwargs):
        """Inline browser document viewer with symmetric on-the-fly decryption (FR-KMS-016, FR-KMS-018)."""
        user = request.env.user
        doc = request.env['kms.document'].browse(doc_id)

        try:
            doc.check_access('read')
        except AccessError:
            return request.render('http_routing.403', {'message': _('Access Denied: You do not have permission to view this document.')})

        if not doc.exists() or not doc.sudo().file_data:
            return request.not_found()

        if not doc.is_pdf:
            # A safe, partial view for text-bearing Office files. Never render the
            # uploaded Office/HTML binary on the bank's browser origin.
            preview = (doc.content_text or '')[:30_000]
            if not preview:
                return Response(_('No extractable text preview is available for this file.'), status=415)
            doc._log_audit_action('view', f'Viewed text preview by {user.name}', strict=True)
            request.env.cr.execute(
                'UPDATE kms_document SET view_count = COALESCE(view_count, 0) + 1 WHERE id = %s',
                (doc.id,),
            )
            doc.invalidate_recordset(['view_count'])
            heading = html_escape(doc.name)
            viewer = html_escape(user.name)
            content = html_escape(preview)
            page = (f'<!doctype html><html><meta charset="utf-8"><title>{heading}</title>'
                    f'<body><h1>{heading}</h1><p>Preview for {viewer} · '
                    f'{datetime.utcnow():%Y-%m-%d %H:%M} UTC</p><pre>{content}</pre>'
                    '<p>Text preview only. Formatting and embedded content are omitted.</p></body></html>')
            return Response(page, headers=[
                ('Content-Type', 'text/html; charset=utf-8'),
                ('Cache-Control', 'private, no-store'),
                ('Content-Security-Policy', "default-src 'none'"),
                ('X-Content-Type-Options', 'nosniff'),
            ])

        if len(doc.sudo().file_data) > 50 * 1024 * 1024 * 4 // 3:
            return Response(_('This PDF exceeds the protected-view size limit.'), status=413)
        raw_bytes = base64.b64decode(doc.sudo().file_data)
        filename = doc.file_name or "document.pdf"
        mimetype = doc.mimetype or 'application/pdf'

        # If an encrypted payload was sent to the viewer or decrypt route was requested
        if request.httprequest.data:
            session_id = None
            if hasattr(request, 'session') and request.session:
                session_id = getattr(request.session, 'sid', None)
            try:
                raw_bytes = decrypt_document_data(
                    request.httprequest.data, doc.id, user.id,
                    session_id=session_id, env=request.env
                )
            except Exception as e:
                _logger.warning("Failed to decrypt user-supplied payload: %s", e)
                return request.render('http_routing.403', {'message': _('Decryption failed: Token invalid or session mismatch.')})

        if kwargs.get('preview') == '1':
            try:
                reader = PdfReader(io.BytesIO(raw_bytes), strict=False)
                writer = PdfWriter()
                writer.add_page(reader.pages[0])
                out = io.BytesIO()
                writer.write(out)
                raw_bytes = out.getvalue()
                filename = f'preview-{filename}'
            except Exception as exc:
                _logger.warning('Could not prepare PDF preview for doc %s: %s', doc.id, exc)
                return Response(_('PDF preview is unavailable for this file.'), status=415)

        # Apply Dynamic Watermarking for inline PDF viewing
        if doc.require_watermark or doc.state == 'approved':
            emp = user.employee_id
            emp_name = emp.name if emp else user.name
            emp_code = emp.barcode or emp.identification_id or f"UID-{user.id}"
            dept_name = emp.department_id.name if (emp and emp.department_id) else "Bunna Bank"
            timestamp_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
            classification = doc.classification_id.name if doc.classification_id else (doc.classification or "INTERNAL")

            watermark_lines = [
                f"BUNNA BANK S.C. - {classification.upper()} DOCUMENT",
                f"Viewed By: {emp_name} ({emp_code})",
                f"Dept: {dept_name} | Date: {timestamp_str}",
                "UNAUTHORIZED COPYING OR DISTRIBUTION IS STRICTLY PROHIBITED"
            ]
            try:
                raw_bytes = add_watermark_to_pdf(raw_bytes, watermark_lines)
            except Exception as e:
                _logger.error("Error applying watermark for inline view of doc %s: %s", doc.id, e)
                return Response(_('Protected document view is temporarily unavailable.'), status=503)

        # Log view audit event
        doc._log_audit_action('view', f"Viewed inline by {user.name}", strict=True)
        request.env.cr.execute(
            'UPDATE kms_document SET view_count = COALESCE(view_count, 0) + 1 WHERE id = %s',
            (doc.id,),
        )
        doc.invalidate_recordset(['view_count'])

        headers = [
            ('Content-Type', mimetype),
            ('Content-Disposition', dump_options_header('inline', {'filename': filename})),
            ('Content-Length', len(raw_bytes)),
            ('Cache-Control', 'private, no-store'),
            ('X-Content-Type-Options', 'nosniff'),
        ]
        return Response(raw_bytes, headers=headers)


class KmsDigitalLibraryController(http.Controller):
    """Deliver catalog files through a checked, auditable route."""

    @staticmethod
    def _serve_resource(resource_id, download):
        resource = request.env['kms.digital.library'].browse(resource_id)
        try:
            resource.check_access('read')
        except AccessError:
            return request.render('http_routing.403', {
                'message': _('You do not have permission to access this library resource.'),
            })
        if not resource.exists() or resource.is_external_link:
            return request.not_found()
        if not resource.active and not request.env.user.has_group('knowledge_management.group_kms_manager'):
            return request.not_found()

        encoded = resource.sudo().file_data
        if not encoded:
            return request.not_found()
        filename = resource.file_name or 'library-resource'
        mimetype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        if not download and mimetype != 'application/pdf' and resource.preview_text:
            # Mobile-friendly text preview of Office/plain-text uploads. The
            # original binary is never rendered as active browser content.
            resource._log_audit_action('view', f'Viewed text preview: {resource.name}', strict=True)
            request.env.cr.execute(
                'UPDATE kms_digital_library SET view_count = COALESCE(view_count, 0) + 1 WHERE id = %s',
                (resource.id,),
            )
            resource.invalidate_recordset(['view_count'])
            title = html_escape(resource.name)
            viewer = html_escape(request.env.user.name)
            content = html_escape(resource.preview_text[:30_000])
            page = (f'<!doctype html><html><meta charset="utf-8"><title>{title}</title>'
                    f'<body><h1>{title}</h1><p>Preview for {viewer}</p><pre>{content}</pre>'
                    '<p>Text preview only. Formatting and embedded content are omitted.</p></body></html>')
            return Response(page, headers=[
                ('Content-Type', 'text/html; charset=utf-8'),
                ('Cache-Control', 'private, no-store'),
                ('Content-Security-Policy', "default-src 'none'"),
                ('X-Content-Type-Options', 'nosniff'),
            ])
        if len(encoded) > 50 * 1024 * 1024 * 4 // 3:
            return Response(_('This library file exceeds the protected delivery size limit.'), status=413)
        payload = base64.b64decode(encoded)

        # Only PDF is rendered inline. Other uploaded formats are delivered as
        # attachments so browser-executable content cannot run on this origin.
        download = download or mimetype != 'application/pdf'
        if download:
            session_id = getattr(request.session, 'sid', None) if getattr(request, 'session', None) else None
            # Negative IDs separate library tokens from governed-document IDs.
            payload = encrypt_document_data(
                payload, -resource.id, request.env.user.id,
                session_id=session_id, env=request.env,
            )
            filename = f'{filename}.enc'
            mimetype = 'application/octet-stream'
        action = 'download' if download else 'view'
        resource._log_audit_action(action, f'{action.title()}ed digital library resource: {resource.name}', strict=True)
        counter = 'download_count' if download else 'view_count'
        request.env.cr.execute(
            f'UPDATE kms_digital_library SET {counter} = COALESCE({counter}, 0) + 1 WHERE id = %s',
            (resource.id,),
        )
        resource.invalidate_recordset([counter])

        disposition = (content_disposition(filename) if download else
                       dump_options_header('inline', {'filename': filename}))
        return Response(payload, headers=[
            ('Content-Type', mimetype),
            ('Content-Disposition', disposition),
            ('Content-Length', len(payload)),
            ('Cache-Control', 'private, no-store'),
            ('X-Content-Type-Options', 'nosniff'),
            ('X-KMS-Encrypted', '1' if download else '0'),
        ])

    @http.route('/kms/library/<int:resource_id>/view', type='http', auth='user', methods=['GET'])
    def kms_view_library_resource(self, resource_id, **kwargs):
        return self._serve_resource(resource_id, download=False)

    @http.route('/kms/library/<int:resource_id>/download', type='http', auth='user', methods=['GET'])
    def kms_download_library_resource(self, resource_id, **kwargs):
        return self._serve_resource(resource_id, download=True)

