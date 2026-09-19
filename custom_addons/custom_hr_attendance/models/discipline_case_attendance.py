# -*- coding: utf-8 -*-
import logging
from datetime import timedelta
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class HrAttendanceDisciplineDecoupled(models.Model):
    _inherit = 'hr.attendance'

    def _process_attendance_violation_counters(self):
        """
        Increment rolling violation counters on hr.employee.discipline.profile
        and trigger supervisor mail.activity notifications.
        Protected by try/except to never block or roll back the check-in transaction.
        """
        for attendance in self:
            try:
                employee = attendance.employee_id
                if not employee:
                    continue

                # Skip technical failure or operational disruption
                if attendance.check_in_status in ('Technical Failure', 'Operational Disruption') or \
                   attendance.check_out_status in ('Technical Failure', 'Operational Disruption'):
                    continue

                # 1. Late or Very Late Check-in counter increment
                if attendance.check_in_status in ('Late', 'Very Late'):
                    employee._increment_late_count()

                # 2. Force Checkout counter increment
                if attendance.is_force_checkout:
                    employee._increment_force_checkout_count()

                # 3. Trigger supervisor notifications
                attendance._check_attendance_violations()
            except Exception as e:
                _logger.exception("Error processing attendance violation counters for attendance %s: %s", attendance.id, e)

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
            if attendance.check_in_status in ('Technical Failure', 'Operational Disruption') or \
               attendance.check_out_status in ('Technical Failure', 'Operational Disruption'):
                continue

            notif_log = self.env['hr.attendance.notification.log'].sudo()

            model_id = self.env['ir.model']._get_id('hr.attendance')
            act_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
            act_type_id = act_type.id if act_type else self.env['mail.activity.type'].search([], limit=1).id

            # Supervisor notification on late / very late check-in
            if attendance.check_in_status in ('Late', 'Very Late') and employee.parent_id and employee.parent_id.user_id:
                if notif_log.log_and_check(employee.id, 'violation_supervisor'):
                    today = fields.Date.context_today(self)
                    status_label = attendance.check_in_status
                    act = self.env['mail.activity'].sudo().create({
                        'res_model_id': model_id,
                        'res_id': attendance.id,
                        'user_id': employee.parent_id.user_id.id,
                        'summary': _('Attendance Alert: %s Late Check-in (%s)') % (employee.name, status_label),
                        'note': _('Employee %s checked in %s on %s (Late hours: %.2f).') % (
                            employee.name, status_label.lower(), today, attendance.late_time_hour or 0.0
                        ),
                        'activity_type_id': act_type_id,
                    })

            # Supervisor notification on force checkout
            if attendance.is_force_checkout and employee.parent_id and employee.parent_id.user_id:
                if notif_log.log_and_check(employee.id, 'violation_supervisor'):
                    self.env['mail.activity'].sudo().create({
                        'res_model_id': model_id,
                        'res_id': attendance.id,
                        'user_id': employee.parent_id.user_id.id,
                        'summary': _('Attendance Alert: %s Force Checkout') % employee.name,
                        'note': _('Employee %s was automatically force checked out.') % employee.name,
                        'activity_type_id': act_type_id,
                    })
