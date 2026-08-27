# -*- coding: utf-8 -*-
import logging
from datetime import timedelta
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class HrAttendanceDisciplineDecoupled(models.Model):
    _inherit = 'hr.attendance'

    def _check_attendance_violations(self):
        """Pure attendance violation logger and supervisor notification engine.
        Does NOT directly create discipline cases or modify payroll payloads.
        Discipline cases and payroll deductions are handled strictly in their respective modules.
        """
        for attendance in self:
            employee = attendance.employee_id
            if not employee:
                continue

            # Skip technical failure or operational disruption
            if attendance.check_in_status in ('Technical Failure', 'Operational Disruption') or                attendance.check_out_status in ('Technical Failure', 'Operational Disruption'):
                continue

            notif_log = self.env['hr.attendance.notification.log']

            # Supervisor notification on late check-in
            if attendance.check_in_status == 'Late' and employee.parent_id and employee.parent_id.user_id:
                if notif_log.log_and_check(employee.id, 'violation_supervisor'):
                    today = fields.Date.context_today(self)
                    self.env['mail.activity'].sudo().create({
                        'res_model_id': self.env.ref('hr_attendance.model_hr_attendance').id,
                        'res_id': attendance.id,
                        'user_id': employee.parent_id.user_id.id,
                        'summary': _('Attendance Alert: %s Late Check-in') % employee.name,
                        'note': _('Employee %s checked in late on %s.') % (employee.name, today),
                        'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                    })

            # Supervisor notification on force checkout
            if attendance.is_force_checkout and employee.parent_id and employee.parent_id.user_id:
                if notif_log.log_and_check(employee.id, 'violation_supervisor'):
                    self.env['mail.activity'].sudo().create({
                        'res_model_id': self.env.ref('hr_attendance.model_hr_attendance').id,
                        'res_id': attendance.id,
                        'user_id': employee.parent_id.user_id.id,
                        'summary': _('Attendance Alert: %s Force Checkout') % employee.name,
                        'note': _('Employee %s was automatically force checked out.') % employee.name,
                        'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                    })
