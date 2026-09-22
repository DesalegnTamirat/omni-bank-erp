# -*- coding: utf-8 -*-
import base64
import logging
from datetime import datetime
from odoo import http, _
from odoo.http import request, Response
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
            doc.check_access_rights('read')
            doc.check_access_rule('read')
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

        if not doc.file_data:
            return request.not_found()

        raw_bytes = base64.b64decode(doc.file_data)
        filename = doc.file_name or f"KMS_Document_{doc.code}.pdf"
        mimetype = doc.mimetype or 'application/pdf'

        # Apply Dynamic Watermarking if enabled for PDF (FR-KMS-015)
        if doc.require_watermark and doc.is_pdf:
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

        # Apply Session-Bound Symmetric Encryption (FR-KMS-016 & FR-KMS-015 non-PDF protection)
        # Non-PDF files are encrypted so they cannot be released unprotected; PDF files are encrypted if require_encryption is True or requested.
        is_encrypted = doc.require_encryption or (not doc.is_pdf) or (kwargs.get('encrypt') == '1')
        if is_encrypted:
            raw_bytes = encrypt_document_data(raw_bytes, doc.id, user.id)
            if not filename.endswith('.enc'):
                filename = f"{filename}.enc"
            mimetype = 'application/octet-stream'

        # Log download audit event
        doc._log_audit_action('download', f"Downloaded by {user.name} (encrypted={is_encrypted})")
        doc.sudo().write({'download_count': doc.download_count + 1})

        headers = [
            ('Content-Type', mimetype),
            ('Content-Disposition', f'attachment; filename="{filename}"'),
            ('Content-Length', len(raw_bytes)),
            ('X-KMS-Encrypted', '1' if is_encrypted else '0'),
            ('Cache-Control', 'no-cache, no-store, must-revalidate'),
            ('Pragma', 'no-cache'),
            ('Expires', '0'),
        ]
        return Response(raw_bytes, headers=headers)

    @http.route(['/kms/document/<int:doc_id>/view'], type='http', auth='user', methods=['GET', 'POST'], csrf=False)
    def kms_view_document(self, doc_id, **kwargs):
        """Inline browser document viewer with symmetric on-the-fly decryption (FR-KMS-016, FR-KMS-018)."""
        user = request.env.user
        doc = request.env['kms.document'].browse(doc_id)

        try:
            doc.check_access_rights('read')
            doc.check_access_rule('read')
        except AccessError:
            return request.render('http_routing.403', {'message': _('Access Denied: You do not have permission to view this document.')})

        if not doc.exists() or not doc.file_data:
            return request.not_found()

        raw_bytes = base64.b64decode(doc.file_data)
        filename = doc.file_name or "document.pdf"
        mimetype = doc.mimetype or 'application/pdf'

        # If an encrypted payload was sent to the viewer or decrypt route was requested
        if request.httprequest.data:
            try:
                raw_bytes = decrypt_document_data(request.httprequest.data, doc.id, user.id)
            except Exception as e:
                _logger.warning("Failed to decrypt user-supplied payload: %s", e)
                return request.render('http_routing.403', {'message': _('Decryption failed: Token invalid or session mismatch.')})

        # Apply Dynamic Watermarking for inline PDF viewing
        if doc.require_watermark and doc.is_pdf:
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

        # Log view audit event
        doc._log_audit_action('view', f"Viewed inline by {user.name}")
        doc.sudo().write({'view_count': doc.view_count + 1})

        headers = [
            ('Content-Type', mimetype),
            ('Content-Disposition', f'inline; filename="{filename}"'),
            ('Content-Length', len(raw_bytes)),
        ]
        return Response(raw_bytes, headers=headers)

