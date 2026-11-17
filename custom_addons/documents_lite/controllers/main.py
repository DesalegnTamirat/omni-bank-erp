import json

from odoo import _, http
from odoo.exceptions import AccessError, UserError
from odoo.http import request


PREVIEW_AS_TEXT = {'application/json', 'application/xml', 'application/xhtml+xml'}


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

        The download flag only governs explicit downloads, a browser cannot show a file
        without receiving it. Risky types are served as plain text and, apart from PDF,
        inside a CSP sandbox so an uploaded HTML/SVG file can never run scripts.
        """
        doc = request.env['dms.document'].browse(doc_id).exists()
        try:
            if not doc or not doc.file:
                return request.not_found()
            doc.check_access('read')
        except AccessError:
            return request.not_found()
        stream = request.env['ir.binary']._get_stream_from(doc, 'file', filename_field='file_name')
        response = stream.get_response(as_attachment=False)
        mimetype = (doc.mimetype or '').lower()
        if (mimetype.startswith('text/') and mimetype != 'text/plain') or mimetype in PREVIEW_AS_TEXT:
            response.headers['Content-Type'] = 'text/plain; charset=utf-8'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'private, no-store'
        if mimetype != 'application/pdf':
            response.headers['Content-Security-Policy'] = 'sandbox'
        return response
