import base64
import io
import json
import logging
import os
import tempfile

from odoo import _, http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

_logger = logging.getLogger(__name__)

PREVIEW_AS_TEXT = {'application/json', 'application/xml', 'application/xhtml+xml'}
WORD_MIMETYPES = (
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/msword',
)

try:
    import mammoth
except ImportError:
    mammoth = None

try:
    import pythoncom
    import win32com.client
except ImportError:
    win32com = None


def _convert_word_to_pdf(raw_bytes, ext):
    """Attempt converting Word doc bytes to PDF using MS Word COM (Windows)."""
    if not win32com or os.name != 'nt':
        return None
    temp_dir = tempfile.gettempdir()
    temp_in = os.path.join(temp_dir, f'dms_in_{os.getpid()}_{id(raw_bytes)}.{ext}')
    temp_out = os.path.join(temp_dir, f'dms_out_{os.getpid()}_{id(raw_bytes)}.pdf')
    word = None
    try:
        with open(temp_in, 'wb') as f:
            f.write(raw_bytes)
        pythoncom.CoInitialize()
        word = win32com.client.Dispatch('Word.Application')
        word.Visible = False
        doc = word.Documents.Open(os.path.abspath(temp_in), ReadOnly=True)
        # 17 = wdExportFormatPDF
        doc.ExportAsFixedFormat(os.path.abspath(temp_out), 17)
        doc.Close(False)
        word.Quit()
        word = None
        pythoncom.CoUninitialize()
        if os.path.exists(temp_out):
            with open(temp_out, 'rb') as f:
                pdf_data = f.read()
            return pdf_data
    except Exception as exc:
        _logger.warning("Word to PDF COM conversion error: %s", exc)
        try:
            if word:
                word.Quit()
            pythoncom.CoUninitialize()
        except Exception:
            pass
    finally:
        for p in (temp_in, temp_out):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
    return None


def _convert_docx_to_html(raw_bytes):
    """Convert .docx bytes to clean HTML using mammoth."""
    if not mammoth:
        return None
    try:
        buf = io.BytesIO(raw_bytes)
        result = mammoth.convert_to_html(buf)
        return result.value
    except Exception as exc:
        _logger.warning("Mammoth docx to html conversion error: %s", exc)
        return None


class DmsController(http.Controller):

    @http.route('/dms/upload', type='http', methods=['POST'], auth='user')
    def upload(self, folder_id=None, res_model=None, res_id=None, **kw):
        """Multi-file upload from the kanban / list drop zone and Upload button."""
        files = request.httprequest.files.getlist('ufile')
        try:
            Folder = request.env['dms.folder']
            folder = Folder.browse(int(folder_id)).exists() if folder_id and folder_id != 'false' else Folder
            res_id = int(res_id) if res_id and res_id != 'false' else False
            if res_model in (None, 'false', ''):
                res_model = False
            if res_model:
                if res_model not in request.env or not res_id:
                    raise UserError(_('Invalid linked record.'))
                request.env[res_model].browse(res_id).check_access('read')
            if not files:
                raise UserError(_('No file received.'))
            docs = request.env['dms.document'].dms_create_from_upload(
                files, folder=folder or None, res_model=res_model, res_id=res_id)
            return request.make_json_response({'success': True, 'ids': docs.ids})
        except (AccessError, UserError) as exc:
            return request.make_json_response({'error': {'message': str(exc)}})

    # -------------------------------------------------------- password verify
    @http.route('/dms/verify_password', type='jsonrpc', auth='user', methods=['POST'])
    def verify_password(self, document_id, password, **kw):
        """Check a document password. Returns {'ok': True/False}."""
        doc = request.env['dms.document'].browse(int(document_id)).exists()
        if not doc:
            return {'ok': False, 'error': 'Document not found.'}
        if not doc.file_password:
            return {'ok': True}
        return {'ok': password == doc.file_password}

    # ---------------------------------------------------- download guard
    @http.route('/dms/download/<int:doc_id>', type='http', auth='user', methods=['GET'])
    def guarded_download(self, doc_id, **kw):
        """Download route that respects allow_download flag."""
        doc = request.env['dms.document'].browse(doc_id).exists()
        try:
            if not doc or not doc.file:
                return request.not_found()
        except AccessError:
            return request.not_found()
        if not doc._dms_can_download():
            return request.make_json_response(
                {'error': 'Downloading this document is not allowed.'}, status=403)
        stream = request.env['ir.binary']._get_stream_from(doc, 'file', filename_field='file_name')
        response = stream.get_response(as_attachment=True)
        response.headers['Cache-Control'] = 'no-store'
        return response

    # ---------------------------------------------------------- inline preview
    @http.route('/dms/preview/<int:doc_id>', type='http', auth='user', methods=['GET'], readonly=True)
    def preview(self, doc_id, **kw):
        """Serve the file inline so the browser shows it instead of downloading it.

        Supports PDF, images, text, and converts Word (.doc/.docx) into PDF or styled HTML.
        """
        doc = request.env['dms.document'].browse(doc_id).exists()
        try:
            if not doc or not doc.file:
                return request.not_found()
            doc.check_access('read')
        except AccessError:
            return request.not_found()

        ext = (doc.extension or '').lower()
        mimetype = (doc.mimetype or '').lower()
        is_word = ext in ('doc', 'docx') or mimetype in WORD_MIMETYPES

        if is_word:
            raw_bytes = base64.b64decode(doc.file)
            # 1. Try converting to PDF first (exact pagination like PDF)
            pdf_bytes = _convert_word_to_pdf(raw_bytes, ext or 'docx')
            if pdf_bytes:
                response = request.make_response(
                    pdf_bytes,
                    headers=[
                        ('Content-Type', 'application/pdf'),
                        ('Content-Disposition', 'inline; filename="%s.pdf"' % (doc.name or 'document')),
                        ('X-Content-Type-Options', 'nosniff'),
                        ('Cache-Control', 'private, no-store'),
                    ]
                )
                return response
            
            # 2. Fallback: Convert to clean responsive HTML
            html_body = _convert_docx_to_html(raw_bytes)
            if html_body:
                full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    line-height: 1.6;
    color: #212529;
    background-color: #525659;
    padding: 24px;
    margin: 0;
  }}
  .doc-container {{
    max-width: 820px;
    margin: 0 auto;
    background: #ffffff;
    padding: 48px 60px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.25);
    border-radius: 4px;
    min-height: 100vh;
  }}
  table {{
    border-collapse: collapse;
    width: 100%;
    margin: 16px 0;
  }}
  th, td {{
    border: 1px solid #dee2e6;
    padding: 8px 12px;
    text-align: left;
  }}
  th {{
    background-color: #f8f9fa;
  }}
  img {{
    max-width: 100%;
    height: auto;
  }}
</style>
</head>
<body>
<div class="doc-container">
{html_body}
</div>
</body>
</html>"""
                response = request.make_response(
                    full_html.encode('utf-8'),
                    headers=[
                        ('Content-Type', 'text/html; charset=utf-8'),
                        ('Content-Disposition', 'inline'),
                        ('X-Content-Type-Options', 'nosniff'),
                        ('Cache-Control', 'private, no-store'),
                    ]
                )
                return response

        stream = request.env['ir.binary']._get_stream_from(doc, 'file', filename_field='file_name')
        response = stream.get_response(as_attachment=False)
        if (mimetype.startswith('text/') and mimetype != 'text/plain') or mimetype in PREVIEW_AS_TEXT:
            response.headers['Content-Type'] = 'text/plain; charset=utf-8'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'private, no-store'
        if mimetype != 'application/pdf':
            response.headers['Content-Security-Policy'] = 'sandbox'
        return response
