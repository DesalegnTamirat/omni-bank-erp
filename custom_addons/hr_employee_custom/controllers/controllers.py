# -*- coding: utf-8 -*-
import logging
from odoo import http, SUPERUSER_ID, _, tools
from odoo.http import request
from odoo.addons.web.controllers.home import Home, SIGN_UP_REQUEST_PARAMS
from odoo.addons.web.controllers.session import Session

_logger = logging.getLogger(__name__)


class BunnaEmployeeHome(Home):

    def _login_redirect(self, uid, redirect=None):
        """
        Redirect user to unregistered notice page only if attempting to access backend
        apps without active master data (hr.employee) and contract data (hr.version).
        Frontend / ATS / Website access (such as /jobs) must remain accessible.
        """
        if uid and uid != SUPERUSER_ID:
            user = request.env['res.users'].sudo().browse(uid)
            if not user.has_group('base.group_system'):
                if not user._has_valid_employee_and_contract():
                    # If user is navigating to frontend/ATS/website (e.g. /jobs, /my), honor the redirect
                    if redirect and not any(redirect.startswith(p) for p in ('/web', '/odoo', '/scoped_app')):
                        return redirect
                    # Candidates / portal users: always direct to jobs or their intended page
                    if not user.has_group('base.group_user'):
                        return redirect or '/jobs'
                    # Internal employees attempting to access backend apps without a contract:
                    return '/web/unregistered_employee'
        return super()._login_redirect(uid, redirect=redirect)

    @http.route('/', type='http', auth="public", website=True, sitemap=True)
    def index(self, s_action=None, db=None, **kw):
        """
        The root website route is a frontend page and should not redirect to the
        unregistered employee notice page.
        """
        return super().index(s_action=s_action, db=db, **kw)

    @http.route(['/web', '/odoo', '/odoo/<path:subpath>', '/scoped_app/<path:subpath>'], type='http', auth="none", readonly=Home._web_client_readonly)
    def web_client(self, s_action=None, **kw):
        """
        Intercept backend web client access for logged-in users with missing records.
        """
        if request.session.uid and request.session.uid != SUPERUSER_ID:
            user = request.env['res.users'].sudo().browse(request.session.uid)
            if not user._has_valid_employee_and_contract():
                return request.redirect('/web/unregistered_employee', 303)
        return super().web_client(s_action=s_action, **kw)

    @http.route('/web/unregistered_employee', type='http', auth='user', website=True, sitemap=False)
    def unregistered_employee(self, **kw):
        """
        Informational landing page showing notice when user has no active hr.employee or hr.version.
        """
        user = request.env.user
        if user._has_valid_employee_and_contract():
            return request.redirect('/web')

        status = user._get_employee_validation_status()
        return request.render('hr_employee_custom.unregistered_employee_notice', {
            'user_name': user.name,
            'user_login': user.login,
            'has_employee': not status.get('missing_master', False),
            'has_contract': not status.get('missing_contract', False),
        })

    @http.route('/web/login', type='http', auth="public")
    def web_login(self, redirect=None, **kw):
        if request.httprequest.method == 'POST':
            login = request.params.get('login', '').strip()
            password = request.params.get('password', '')
            force_logout = bool(request.params.get('force_logout'))

            if login and password:
                try:
                    auth_info = request.env['res.users'].sudo()._login(
                        {'type': 'password', 'login': login, 'password': password},
                        {'interactive': True}
                    )
                    uid = auth_info.get('uid') if isinstance(auth_info, dict) else None
                    if uid:
                        SessionModel = request.env['user.active.session'].sudo()
                        active_sessions = SessionModel.search([
                            ('user_id', '=', uid),
                            ('is_active', '=', True)
                        ])
                        if active_sessions and force_logout:
                            _logger.info("User %s requested force logout — unlinking %d active session(s).", uid, len(active_sessions))
                            active_sessions.unlink()
                        elif active_sessions and not force_logout:
                            curr_sid = request.session.sid
                            if not (curr_sid and any(SessionModel._is_same_session(s.sid, curr_sid) for s in active_sessions)):
                                _logger.info("Duplicate login attempt for user %s. Showing force logout prompt.", uid)
                                if request.env.uid is None:
                                    if request.session.uid is None:
                                        request.env["ir.http"]._auth_method_public()
                                    else:
                                        request.update_env(user=request.session.uid)

                                values = {k: v for k, v in request.params.items() if k in SIGN_UP_REQUEST_PARAMS}
                                try:
                                    values['databases'] = http.db_list()
                                except Exception:
                                    values['databases'] = None
                                if not tools.config.get('list_db', True):
                                    values['disable_database_manager'] = True

                                values['error'] = _("You are currently logged in on another device or browser.")
                                values['show_force_logout_prompt'] = True
                                values['login'] = login
                                values['password'] = password
                                response = request.render('web.login', values)
                                response.headers['Cache-Control'] = 'no-cache'
                                response.headers['X-Frame-Options'] = 'SAMEORIGIN'
                                return response
                except Exception as e:
                    _logger.debug("Credentials check in custom web_login failed: %s", e)
                    pass

        response = super().web_login(redirect=redirect, **kw)

        if request.session.uid and request.session.sid:
            try:
                request._save_session()
            except Exception as e:
                _logger.debug("request._save_session exception in web_login: %s", e)

            if hasattr(response, 'set_cookie'):
                from odoo.http import get_session_max_inactivity
                try:
                    response.set_cookie(
                        'session_id',
                        request.session.sid,
                        max_age=get_session_max_inactivity(request.env),
                        httponly=True
                    )
                except Exception as e:
                    _logger.debug("response.set_cookie exception in web_login: %s", e)

            user = request.env['res.users'].sudo().browse(request.session.uid)
            if user.exists() and not user._is_public():
                ip = request.httprequest.remote_addr if (request and hasattr(request, 'httprequest')) else None
                user_agent = request.httprequest.headers.get('User-Agent') if (request and hasattr(request, 'httprequest')) else None
                reg = request.env['user.active.session'].sudo().register_or_update_active(
                    request.session.uid,
                    request.session.sid,
                    ip_address=ip,
                    user_agent=user_agent
                )
                _logger.info("web_login registered active session record: %s with sid=%s", reg, request.session.sid)

        if hasattr(response, 'qcontext') and isinstance(response.qcontext, dict):
            if request.params.get('reason') == 'concurrent_session':
                response.qcontext['error'] = _("You have been logged out because your account was accessed from another device.")
            if not response.qcontext.get('login'):
                response.qcontext['login'] = request.params.get('login', '') or request.session.get('auth_login', '')

        return response


class BunnaSession(Session):

    @http.route('/web/session/destroy', type='jsonrpc', auth='user', readonly=True)
    def destroy(self):
        uid = request.session.uid
        sid = request.session.sid
        if uid or sid:
            request.env['user.active.session'].sudo().terminate_session(sid=sid, user_id=uid)
        return super().destroy()

    @http.route('/web/session/logout', type='http', auth='none', readonly=True)
    def logout(self, redirect='/odoo'):
        uid = request.session.uid
        sid = request.session.sid
        if uid or sid:
            request.env['user.active.session'].sudo().terminate_session(sid=sid, user_id=uid)
        return super().logout(redirect=redirect)




