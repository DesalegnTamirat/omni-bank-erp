# -*- coding: utf-8 -*-
import os
import base64
import logging
from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

class EmployeeDocumentBulkAPI(http.Controller):
    # Base folder containing employee folders
    BASE_PATH = '/erpshare/sample_doc'

    @http.route('/api/employee/doc/check', type='http', auth='public', methods=['GET'], csrf=False)
    def check_endpoint(self, **kwargs):
        dbname = request.env.cr.dbname
        return Response(f"Employee upload document API is running on database: {dbname}", status=200)

    @http.route('/api/employee/upload_employee_documents', type='http', auth='user', methods=['POST'], csrf=False)
    def upload_missing_docs(self, **kwargs):
        HrEmployeeDocument = request.env['hr.employee.document'].sudo()
        Attachment = request.env['ir.attachment'].sudo()

        uploaded = skipped = missing = 0
        errors = []
        dbname = request.env.cr.dbname

        _logger.info("🔹 Running document upload on DB: %s", dbname)

        all_docs = HrEmployeeDocument.search([])
        _logger.info("🔹 Total documents found: %s", len(all_docs))

        for doc in all_docs:
            emp = doc.employee_ref
            if not emp:
                skipped += 1
                errors.append(f"Document {doc.id} skipped: No employee reference")
                _logger.warning("⚠️ Skipping doc %s — No employee reference", doc.id)
                continue

            emp_id_folder = getattr(emp, 'employee_identification', None)
            if not emp_id_folder:
                skipped += 1
                errors.append(f"Employee {emp.id} has no identification")
                _logger.warning("⚠️ Employee %s has no identification", emp.id)
                continue

            emp_folder = os.path.join(self.BASE_PATH, emp_id_folder)
            if not os.path.isdir(emp_folder):
                missing += 1
                errors.append(f"Employee {emp_id_folder} folder not found: {emp_folder}")
                _logger.warning("⚠️ Missing folder for Employee %s: %s", emp_id_folder, emp_folder)
                continue

            # Get document type from document_type field (Many2one)
            doc_type = getattr(doc.document_type, 'name', None)
            if not doc_type:
                skipped += 1
                errors.append(f"Document {doc.id} has no document_type, skipping")
                _logger.warning("⚠️ Document %s has no document_type", doc.id)
                continue
            doc_type = doc_type.upper().strip()

            emp_id_clean = str(emp_id_folder).strip()

            # Expected file format: <DOC_TYPE><EMPLOYEE_ID>.pdf
            pdf_found = None
            if os.path.exists(emp_folder):
                for fname in os.listdir(emp_folder):
                    if not fname.lower().endswith(".pdf"):
                        continue
                    base_name = os.path.splitext(fname)[0].upper()
                    expected_name = f"{doc_type}{emp_id_clean}"
                    if base_name == expected_name:
                        pdf_found = os.path.join(emp_folder, fname)
                        _logger.info("✅ Matched %s → %s", doc_type, fname)
                        break

            if not pdf_found:
                missing += 1
                errors.append(f"❌ Missing PDF for Employee {emp_id_folder}: expected '{doc_type}{emp_id_clean}.pdf'")
                _logger.warning("❌ Missing PDF for Employee %s: expected '%s%s.pdf'", emp_id_folder, doc_type, emp_id_clean)
                continue

            # Skip if already attached
            existing = Attachment.search([
                ('res_model', '=', 'hr.employee.document'),
                ('res_id', '=', doc.id)
            ], limit=1)
            if existing:
                skipped += 1
                _logger.info("⏩ Already attached: %s", pdf_found)
                continue

            try:
                with open(pdf_found, "rb") as f:
                    encoded = base64.b64encode(f.read())

                attachment = Attachment.create({
                    'name': os.path.basename(pdf_found),
                    'res_model': 'hr.employee.document',
                    'res_id': doc.id,
                    'datas': encoded,
                    'mimetype': 'application/pdf',
                    'description': f'Auto-uploaded from {emp_id_folder} via API',
                })

                # Link in doc_attach_rel if not already linked
                request.env.cr.execute("""
                    SELECT 1 FROM doc_attach_rel WHERE doc_id = %s AND attach_id3 = %s
                """, (doc.id, attachment.id))
                if not request.env.cr.fetchone():
                    request.env.cr.execute("""
                        INSERT INTO doc_attach_rel (doc_id, attach_id3)
                        VALUES (%s, %s)
                    """, (doc.id, attachment.id))

                uploaded += 1
                _logger.info("📎 Uploaded and linked: %s", pdf_found)

            except Exception as e:
                errors.append(f"❌ Error uploading {pdf_found}: {str(e)}")
                _logger.error("❌ Error uploading %s: %s", pdf_found, str(e))

        request.env.cr.commit()
        _logger.info("🔸 Upload completed — Uploaded: %s, Skipped: %s, Missing: %s", uploaded, skipped, missing)

        return request.make_json_response({
            "database": dbname,
            "status": "success",
            "uploaded": uploaded,
            "skipped": skipped,
            "missing": missing,
            "errors": errors,
        }, status=200)
