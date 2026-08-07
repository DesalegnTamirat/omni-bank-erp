# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class CustomWebController(http.Controller):

    @http.route('/', type='http', auth="user", website=True)
    def index(self, **kw):
        # Check if the user belongs to your custom group
        # Replace 'bank_custom_website' with your actual module's technical name
        if not request.env.user.has_group('bank_custom_website.group_custom_viewer'):
            # If they don't have the group, raise AccessError or redirect to a 'Forbidden' page
            return request.render("website.403")  # Odoo's built-in Access Denied page

        return request.render("bank_custom_website.hello_page_template", {
            'user_name': request.env.user.name
        })

    @http.route('/hello-odoo', type='http', auth='public', website=True)
    def hello_page(self, **kwargs):
        # Dynamically fetch current user name, default to 'Guest' if not logged in
        user_name = request.env.user.name if request.env.user.id != request.env.ref('base.public_user').id else 'Guest'

        # Pass data to the QWeb template
        return request.render('bunna_custom_web_page.hello_page_template', {
            'user_name': user_name,
        })

    class WebsiteHome(http.Controller):
        @http.route('/', type='http', auth="public", website=True)
        def index(self, **kw):
            # This tells Odoo to render your template at the root URL
            return request.render("bunna_custom_web_page.hello_page_template", {
                'user_name': request.env.user.name
            })

    class JobsController(http.Controller):
        @http.route('/jobs', type='http', auth="public", website=True)
        def jobs_page(self, **kw):
            return request.render("bunna_custom_web_page.jobs_coming_soon_template")

    @http.route('/courses', type='http', auth="public", website=True)
    def courses_page(self, **kw):
        return request.render("bunna_custom_web_page.courses_coming_soon_template")

    @http.route('/tender', type='http', auth="public", website=True)
    def tender_page(self, **kw):
        return request.render("bunna_custom_web_page.tender_coming_soon_template")

    @http.route('/policies', type='http', auth="public", website=True)
    def policies_page(self, **kw):
        return request.render("bunna_custom_web_page.policies_page_template")

    @http.route('/faq', type='http', auth="public", website=True)
    def faq_page(self, **kw):
        return request.render("bunna_custom_web_page.faq_page_template")

    @http.route('/odoo/employee-service-requests/new', type='http', auth='user', website=True)
    def redirect_to_employee_service_request(self, **kwargs):
        # We need to redirect to the proper backend action for creating a new employee.service.request
        action = request.env.ref('hr_employee_custom.action_employee_service_request', raise_if_not_found=False)
        if not action:
            return request.redirect('/odoo')
        
        # Build the url to redirect to the web client
        url = f"/odoo/action-{action.id}/new"
        
        # Append any query parameters to the new url
        query_string = request.httprequest.query_string.decode('utf-8')
        if query_string:
            url = f"{url}?{query_string}"
        
        return request.redirect(url)