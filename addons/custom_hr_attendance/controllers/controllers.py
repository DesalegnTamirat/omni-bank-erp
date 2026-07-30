# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

from odoo.addons.hr_attendance.controllers.main import HrAttendance


class BunnaMyAttendance(http.Controller):
    """Backs the full-page 'Check In / Check Out' screen (menu_check_in_out).

    Odoo 19 dropped the old personal 'My Attendances' page in favour of the
    top-right systray icon only. Bunna Bank wants the legacy full-page
    greet-screen back as its own menu item, so we re-expose the same data/
    action that the systray widget uses (see hr_attendance.controllers.main.
    HrAttendance) through two small endpoints, without touching core.
    """

    @http.route('/custom_hr_attendance/my_attendance_data', type='jsonrpc', auth='user', readonly=True)
    def my_attendance_data(self):
        """Read-only snapshot for the current user's employee (name, avatar,
        checked in/out state, hours today...). Does NOT toggle attendance."""
        employee = request.env.user.employee_id
        return HrAttendance._get_employee_info_response(employee)

    @http.route('/custom_hr_attendance/my_attendance_toggle', type='jsonrpc', auth='user')
    def my_attendance_toggle(self, latitude=False, longitude=False):
        """Check the current user's employee in or out instantly, then return the
        snapshot for screen refresh."""
        employee = request.env.user.employee_id
        employee._attendance_action_change()
        return HrAttendance._get_employee_info_response(employee)
