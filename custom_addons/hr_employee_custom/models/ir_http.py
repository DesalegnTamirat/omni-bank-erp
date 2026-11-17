# -*- coding: utf-8 -*-
import json
import logging
from odoo import models, api, SUPERUSER_ID
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
        uid = request.session.uid if (request and hasattr(request, 'session') and request.session) else None
        sid = request.session.sid if (request and hasattr(request, 'session') and request.session) else None

        if uid and sid:
            user = request.env['res.users'].sudo().browse(uid)
            if user.exists() and not user._is_public():
                path = request.httprequest.path if (request and request.httprequest) else ''

                # Single Active Session Check (Option A: Kick out duplicate logins)
                if not any(path.startswith(prefix) for prefix in (
                    '/web/session/logout',
                    '/web/login',
                    '/web/static',
                    '/web/assets',
                    '/web/image',
                    '/web/binary',
                )):
                    SessionModel = request.env['user.active.session'].sudo()
                    if not SessionModel.is_session_valid(uid, sid):
                        _logger.warning("Single Session Enforcement: terminating session sid=%s for user=%s (%s)", sid, user.login, user.id)
                        request.session.logout()
                        content_type = request.httprequest.content_type or ''
                        is_ajax = (
                            getattr(request.httprequest, 'is_json', False)
                            or 'json' in content_type
                            or path.startswith(('/web/webclient', '/web/dataset', '/web/action', '/web/session', '/web/manifest'))
                        )
                        if is_ajax:
                            from werkzeug.wrappers import Response
                            body = json.dumps({
                                'jsonrpc': '2.0',
                                'id': None,
                                'error': {
                                    'code': 401,
                                    'message': 'Session Expired',
                                    'data': {
                                        'message': (
                                            'Your session has expired or was terminated because your account was '
                                            'logged in from another device or browser.'
                                        ),
                                    }
                                }
                            })
                            return Response(body, status=200, content_type='application/json')
                        from werkzeug.utils import redirect
                        return redirect('/web/login?reason=concurrent_session', code=302)
                    else:
                        SessionModel.register_or_update_active(uid, sid)


            if not user.has_group('base.group_system'):
                # External candidates / portal users never have employee contracts; always allow portal/ATS
                if not user.has_group('base.group_user'):
                    return super()._dispatch(endpoint)

                routing = getattr(endpoint, 'routing', {}) or {}
                # Any route defined with website=True is a frontend/website/ATS page — always allowed
                if routing.get('website', False):
                    return super()._dispatch(endpoint)

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

    @api.model
    def session_info(self):
        result = super().session_info()
        from odoo.tools import config
        result['idle_logout_timeout'] = int(config.get('idle_logout_timeout', 420))
        result['idle_logout_warning'] = int(config.get('idle_logout_warning', 30))
        return result