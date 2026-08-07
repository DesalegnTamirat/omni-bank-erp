# -*- coding: utf-8 -*-
import logging
from datetime import timedelta
from odoo import models, api, fields, _

_logger = logging.getLogger(__name__)


class DisciplineCaseAttendance(models.Model):
    """
    Attendance-side inherit of discipline.case.
    Provides the factory method _create_from_attendance, called by the attendance
    module when a violation threshold is exceeded.

    Segregation of duties is preserved: this method only sets the case to
    'initiated' state. A human reviewer and approver are still required
    to progress the case — nothing here bypasses discipline_management's workflow.
    """
    _inherit = 'discipline.case'

    @api.model
    def _create_from_attendance(self, employee_id, kind, attendance_id):
        """
        Creates and initiates a discipline case triggered by an attendance violation.
        Called asynchronously from the attendance hot path after threshold is reached.

        kind: 'lateness', 'force_checkout', or 'absence'
        attendance_id: the hr.attendance record ID that triggered this case (0 for absence).
        Returns the created discipline.case record, or None if the offense is not found.
        """
        kind_map = {
            'lateness': 'custom_hr_attendance.offense_repeated_lateness',
            'force_checkout': 'custom_hr_attendance.offense_repeated_force_checkout',
            'absence': 'custom_hr_attendance.offense_repeated_absence',
        }
        offense_xmlid = kind_map.get(kind, 'custom_hr_attendance.offense_repeated_lateness')
        offense = self.env.ref(offense_xmlid, raise_if_not_found=False)
        if not offense:
            _logger.warning(
                "Discipline offense '%s' not found. Skipping attendance case creation for employee %s.",
                offense_xmlid, employee_id
            )
            return None

        kind_labels = {
            'lateness': _('Repeated Lateness'),
            'force_checkout': _('Repeated Force Checkout'),
            'absence': _('Repeated Absence'),
        }
        kind_label = kind_labels.get(kind, kind)
        case = self.create({
            'employee_id': employee_id,
            'offense_id': offense.id,
            'description': _(
                'Automatically flagged by the Attendance module: violation threshold for %s exceeded.\n'
                'Source attendance record ID: %s.\n'
                'Human review and approval are required before enforcement.'
            ) % (kind_label, attendance_id),
            'reference': 'ATT-%s' % attendance_id,
        })

        # Move to 'initiated' state: the system is the initiator only.
        # Reviewer and approver must be different users (segregation of duties enforced by discipline.case).
        if hasattr(case, 'action_initiate'):
            case.action_initiate()

        _logger.info(
            "Attendance discipline case %s created for employee %s (kind=%s, attendance=%s).",
            case.name, employee_id, kind, attendance_id
        )
        return case


class HrAttendanceViolationProcessor(models.Model):
    """
    Attendance-side violation counter processing logic.

    Extends hr.attendance with _process_attendance_violation_counters, which is
    called by _enqueue_attendance_side_effects after check-in/check-out.

    Architecture note:
    - Counter increment: synchronous single-row SQL UPDATE (O(1) via hr_employee_counters.py).
    - Threshold check + case creation: synchronous but fast (only reads integer field
      already incremented by SQL above, no search queries).
    - The discipline case create+initiate is done within this call but is acceptable
      because it only triggers when threshold is crossed (rare event relative to
      total check-ins), not on every single check-in.
    """
    _inherit = 'hr.attendance'

    def _process_attendance_violation_counters(self):
        """
        Increments rolling violation counters and creates a discipline case when
        the configured threshold is exceeded.

        Called by _enqueue_attendance_side_effects after each check-in/check-out.
        This is the ONLY place in the attendance module that writes to the
        violation counters, ensuring a single authoritative code path.
        """
        self.ensure_one()
        employee = self.employee_id
        if not employee:
            return

        # Skip technical failure or operational disruption
        if self.check_in_status in ('Technical Failure', 'Operational Disruption') or \
           self.check_out_status in ('Technical Failure', 'Operational Disruption'):
            return

        params = self.env['ir.config_parameter'].sudo()

        notif_log = self.env['hr.attendance.notification.log']

        # --- LATE CHECK-IN COUNTER ---
        if self.check_in_status == 'Late':
            lateness_threshold = int(params.get_param(
                'hr_attendance.lateness_violation_threshold', 3
            ))
            new_count = employee._increment_late_count()
            _logger.debug(
                "Employee %s late count: %d / %d threshold.",
                employee.name, new_count, lateness_threshold
            )

            # FR-ATT-028: Notify Supervisor on late check-in violation
            if employee.parent_id and employee.parent_id.user_id:
                if notif_log.log_and_check(employee.id, 'violation_supervisor'):
                    self.env['mail.activity'].sudo().create({
                        'res_model_id': self.env.ref('hr_attendance.model_hr_attendance').id,
                        'res_id': self.id,
                        'user_id': employee.parent_id.user_id.id,
                        'summary': _('Attendance Violation: %s Late Check-in') % employee.name,
                        'note': _('Employee %s checked in late on %s.') % (employee.name, fields.Date.context_today(self)),
                        'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                    })

            if new_count >= lateness_threshold:
                employee._reset_late_count()
                self.env['discipline.case'].sudo()._create_from_attendance(
                    employee.id, 'lateness', self.id
                )

                # FR-ATT-029: HR Escalation on threshold breach
                if notif_log.log_and_check(employee.id, 'violation_hr_escalation'):
                    # Target configured HR user or fallback to managers
                    escalation_user_id = params.get_param('hr_attendance.escalation_hr_user_id')
                    target_users = self.env['res.users'].browse(int(escalation_user_id)) if escalation_user_id and escalation_user_id.isdigit() else self.env.ref('hr_attendance.group_hr_attendance_manager').users
                    for hr_user in target_users:
                        self.env['mail.activity'].sudo().create({
                            'res_model_id': self.env.ref('hr_attendance.model_hr_attendance').id,
                            'res_id': self.id,
                            'user_id': hr_user.id,
                            'summary': _('ESCALATION: Lateness Threshold Exceeded for %s') % employee.name,
                            'note': _('Employee %s has reached %d late check-ins. Discipline case initiated.') % (employee.name, lateness_threshold),
                            'activity_type_id': self.env.ref('mail.mail_activity_data_warning', raise_if_not_found=False) or self.env.ref('mail.mail_activity_data_todo').id,
                        })

        # --- FORCE CHECKOUT COUNTER ---
        if self.is_force_checkout:
            force_checkout_threshold = int(params.get_param(
                'hr_attendance.force_checkout_violation_threshold', 2
            ))
            new_count = employee._increment_force_checkout_count()
            _logger.debug(
                "Employee %s force checkout count: %d / %d threshold.",
                employee.name, new_count, force_checkout_threshold
            )

            # FR-ATT-028: Notify Supervisor on force checkout violation
            if employee.parent_id and employee.parent_id.user_id:
                if notif_log.log_and_check(employee.id, 'violation_supervisor'):
                    self.env['mail.activity'].sudo().create({
                        'res_model_id': self.env.ref('hr_attendance.model_hr_attendance').id,
                        'res_id': self.id,
                        'user_id': employee.parent_id.user_id.id,
                        'summary': _('Attendance Violation: %s Force Checkout') % employee.name,
                        'note': _('Employee %s was automatically force checked out.') % employee.name,
                        'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                    })

            if new_count >= force_checkout_threshold:
                employee._reset_force_checkout_count()
                self.env['discipline.case'].sudo()._create_from_attendance(
                    employee.id, 'force_checkout', self.id
                )

                # FR-ATT-029: HR Escalation on force checkout threshold breach
                if notif_log.log_and_check(employee.id, 'violation_hr_escalation'):
                    escalation_user_id = params.get_param('hr_attendance.escalation_hr_user_id')
                    target_users = self.env['res.users'].browse(int(escalation_user_id)) if escalation_user_id and escalation_user_id.isdigit() else self.env.ref('hr_attendance.group_hr_attendance_manager').users
                    for hr_user in target_users:
                        self.env['mail.activity'].sudo().create({
                            'res_model_id': self.env.ref('hr_attendance.model_hr_attendance').id,
                            'res_id': self.id,
                            'user_id': hr_user.id,
                            'summary': _('ESCALATION: Force Checkout Threshold Exceeded for %s') % employee.name,
                            'note': _('Employee %s has reached %d force checkouts. Discipline case initiated.') % (employee.name, force_checkout_threshold),
                            'activity_type_id': self.env.ref('mail.mail_activity_data_warning', raise_if_not_found=False) or self.env.ref('mail.mail_activity_data_todo').id,
                        })



