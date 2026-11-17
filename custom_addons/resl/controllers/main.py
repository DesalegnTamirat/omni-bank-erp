# -*- coding: utf-8 -*-
import json

from werkzeug.exceptions import Forbidden, NotFound

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import request
from odoo.tools import file_open

PAGE = 'resl/static/agreement/index.html'


class ReslAgreementController(http.Controller):

    def _loan(self, loan_id):
        loan = request.env['resl.loan'].browse(loan_id).exists()
        if not loan:
            raise NotFound()
        loan.check_access('read')          # AccessError -> 403
        return loan

    def _render_page(self, cfg):
        cfg['csrf'] = request.csrf_token()
        with file_open(PAGE, 'rb') as fh:
            html = fh.read().decode('utf-8')
        payload = json.dumps(cfg, ensure_ascii=False).replace('</', '<\\/')
        html = html.replace('/*CONFIG*/null', payload, 1)
        return request.make_response(html, headers=[
            ('Content-Type', 'text/html; charset=utf-8'),
            ('Cache-Control', 'no-store'),
        ])

    @http.route('/resl/agreement/new', type='http', auth='user')
    def agreement_page_new(self, amt='0', term='1', agreed='', **kw):
        """Part A of a request that does not exist yet (opened from the New
        form). Read-only: nothing is created or saved here."""
        try:
            amount, months = float(amt), int(float(term))
        except ValueError:
            amount, months = 0.0, 1
        cfg = request.env['resl.loan']._agr_config_new(amount, months, agreed=(agreed == '1'))
        return self._render_page(cfg)

    @http.route('/resl/agreement/<int:loan_id>', type='http', auth='user')
    def agreement_page(self, loan_id, g=None, **kw):
        loan = self._loan(loan_id)
        # requestor: not before the guarantor(s) accepted
        if not loan._agr_requester_unlocked():
            raise Forbidden("The agreement is available after the guarantee has been accepted.")
        loan._agr_mark_viewed()
        cfg = loan._agr_config(int(g) if (g or '').isdigit() else None)
        # ?print=1 (only honoured for approvers / admins): open the print dialog
        cfg['autoPrint'] = bool(kw.get('print')) and bool(cfg.get('canPrint'))
        return self._render_page(cfg)

    @http.route('/resl/agreement/<int:loan_id>/save', type='http', auth='user',
                methods=['POST'], csrf=True)
    def agreement_save(self, loan_id, payload='{}', **kw):
        loan = self._loan(loan_id)
        try:
            data = json.loads(payload)
            errors = loan.agr_save(
                data.get('role'), data.get('values'), data.get('sigs'), data.get('lineId') or None)
            return request.make_json_response({'ok': True, 'errors': errors})
        except (UserError, AccessError) as e:
            return request.make_json_response({'ok': False, 'message': str(e)})

    @http.route('/resl/agreement/<int:loan_id>/upload', type='http', auth='user',
                methods=['POST'], csrf=True)
    def agreement_upload(self, loan_id, **kw):
        loan = self._loan(loan_id)
        f = request.httprequest.files.get('file')
        if not f:
            return request.make_json_response({'ok': False, 'message': 'No file.'})
        try:
            loan.agr_add_file(f.filename or 'file', f.mimetype, f.read())
            return request.make_json_response({'ok': True, 'files': loan._agr_files()})
        except (UserError, AccessError) as e:
            return request.make_json_response({'ok': False, 'message': str(e)})

    @http.route('/resl/agreement/page_img/<int:config_id>/<int:page_num>', type='http', auth='user')
    def agreement_page_image(self, config_id, page_num, **kw):
        import base64
        config = request.env['resl.pdf.config'].sudo().browse(config_id).exists()
        if not config:
            raise NotFound()
        fld = f'page_{page_num}_image'
        data = getattr(config, fld, False)
        if not data:
            return request.redirect(f'/resl/static/agreement/page{page_num}.png')
        return request.make_response(
            base64.b64decode(data),
            headers=[
                ('Content-Type', 'image/png'),
                ('Cache-Control', 'no-store'),
            ]
        )

    @http.route(['/resl/agreement/config_pdf', '/resl/agreement/config_pdf/<int:config_id>'], type='http', auth='user')
    def agreement_config_pdf(self, config_id=None, **kw):
        import base64
        if config_id:
            config = request.env['resl.pdf.config'].sudo().browse(config_id).exists()
        else:
            config = request.env['resl.pdf.config'].sudo().search([('is_active', '=', True)], limit=1)
            if not config:
                config = request.env['resl.pdf.config'].sudo().search([], limit=1)
        if not config or not config.agreement_pdf:
            raise NotFound()
        data = base64.b64decode(config.agreement_pdf)
        filename = config.agreement_pdf_filename or 'agreement_template.pdf'
        return request.make_response(
            data,
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition', f'inline; filename="{filename}"'),
                ('Cache-Control', 'no-store'),
            ]
        )