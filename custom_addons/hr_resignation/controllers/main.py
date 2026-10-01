# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

class HrResignationController(http.Controller):
    
    @http.route('/hr_resignation/dashboard', type='http', auth='user')
    def exit_interview_dashboard(self, **kwargs):
        # We can dynamically pass data here in the future
        # For now, it just renders the template which contains the beautiful UI
        return request.render('hr_resignation.custom_exit_dashboard_template', {})
