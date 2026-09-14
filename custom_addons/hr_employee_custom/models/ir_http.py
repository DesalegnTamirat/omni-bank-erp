# -*- coding: utf-8 -*-
import json
import logging
from odoo import models, SUPERUSER_ID
from odoo.http import request

_logger = logging.getLogger(__name__)

# Backend routes that must remain accessible for session management, login, logout, static files, and the notice page
_UNREGISTERED_EXEMPT_PREFIXES = (
    '/web/unregistered_employee',
    '/web/session/logout',
    '/web/session',
    '/web/login',
    '/web/static',
    '/web/assets',
    '/web/image',
    '/web/binary',
)

# Frontend / ATS / Website prefixes that should NEVER be blocked by the employee notice
_FRONTEND_EXEMPT_PREFIXES = (
    '/jobs',
    '/job',
    '/my',
    '/ats',
    '/tender',
    '/policies',
    '/faqs',
    '/contactus',
    '/contact',
    '/aboutus',
    '/website',
)


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _dispatch(cls, endpoint):
        user = request.env.user if (request and request.env and request.env.user) else None
        if user and not user._is_public() and user.id != SUPERUSER_ID and not user.has_group('base.group_system'):
            # External candidates / portal users never have employee contracts; always allow portal/ATS
            if not user.has_group('base.group_user'):
                return super()._dispatch(endpoint)

            routing = getattr(endpoint, 'routing', {}) or {}
            # Any route defined with website=True is a frontend/website/ATS page — always allowed
            if routing.get('website', False):
                return super()._dispatch(endpoint)

            path = request.httprequest.path if (request and request.httprequest) else ''

            # Allow root website ('/') and any frontend / ATS routes
            if path == '/' or any(path.startswith(p) for p in _FRONTEND_EXEMPT_PREFIXES):
                return super()._dispatch(endpoint)

            # Allow exempt technical / static paths
            if any(path.startswith(prefix) for prefix in _UNREGISTERED_EXEMPT_PREFIXES):
                return super()._dispatch(endpoint)

            # Only block backend apps access when contract/master data is missing
            if not user._has_valid_employee_and_contract():
                content_type = request.httprequest.content_type or ''
                if 'json' in content_type:
                    from werkzeug.wrappers import Response
                    body = json.dumps({
                        'jsonrpc': '2.0',
                        'id': None,
                        'error': {
                            'code': 403,
                            'message': 'Access Restricted',
                            'data': {
                                'message': (
                                    'Your employee profile is not yet configured. '
                                    'Please contact your HR administrator.'
                                ),
                            }
                        }
                    })
                    return Response(body, status=200, content_type='application/json')
                from werkzeug.utils import redirect
                return redirect('/web/unregistered_employee', code=302)
        return super()._dispatch(endpoint)

    @classmethod
    def _post_dispatch(cls, response):
        super()._post_dispatch(response)
        if request and request.httprequest and hasattr(response, 'headers'):
            path = request.httprequest.path or ''
            # Prevent browsers from caching authenticated ATS and portal pages in bfcache
            if path.startswith(('/my/candidate', '/my/recruitment', '/jobs')):
                response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
                response.headers['Pragma'] = 'no-cache'
                response.headers['Expires'] = '0'
        return response