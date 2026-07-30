# from odoo import http


# class HrEmployeeCustom(http.Controller):
#     @http.route('/hr_employee_custom/hr_employee_custom', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/hr_employee_custom/hr_employee_custom/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('hr_employee_custom.listing', {
#             'root': '/hr_employee_custom/hr_employee_custom',
#             'objects': http.request.env['hr_employee_custom.hr_employee_custom'].search([]),
#         })

#     @http.route('/hr_employee_custom/hr_employee_custom/objects/<model("hr_employee_custom.hr_employee_custom"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('hr_employee_custom.object', {
#             'object': obj
#         })

