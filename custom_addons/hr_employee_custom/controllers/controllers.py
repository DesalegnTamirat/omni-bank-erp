# -*- coding: utf-8 -*-
from odoo import http, SUPERUSER_ID, _
from odoo.http import request
from odoo.addons.web.controllers.home import Home


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
