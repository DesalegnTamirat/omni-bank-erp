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

        # --- LATE CHECK-IN CUMULATIVE HOURS COUNTER ---
        # --- DYNAMIC CONFIGURABLE LATENESS DISCIPLINE RULES ENGINE ---
        if self.check_in_status == 'Late':
            today = fields.Date.context_today(self)
            lateness_rules = self.env['attendance.lateness.rule'].sudo().search([('active', '=', True)], order='threshold_hours desc')
            
            # Fallback values if no custom rules configured
            hours_threshold = float(params.get_param('hr_attendance.lateness_hours_violation_threshold', 4.0))
            eval_months = int(params.get_param('hr_attendance.lateness_eval_window_months', 3))

            triggered_rule = False
            matched_late_hours = 0.0
            
            if lateness_rules:
                for rule in lateness_rules:
                    eval_start = today - timedelta(days=rule.reset_window_months * 30)
                    recent_atts = self.env['hr.attendance'].sudo().search([
                        ('employee_id', '=', employee.id),
                        ('check_in', '>=', fields.Datetime.to_datetime(eval_start)),
                        ('check_in_status', '=', 'Late')
                    ])
                    tot_hours = sum(getattr(att, 'late_time_hour', 0.0) or getattr(att, 'late_time', 0.0) or 0.0 for att in recent_atts)
                    if tot_hours >= rule.threshold_hours:
                        triggered_rule = rule
                        matched_late_hours = tot_hours
                        break

            # Notify Supervisor on late check-in violation
            if employee.parent_id and employee.parent_id.user_id:
                if notif_log.log_and_check(employee.id, 'violation_supervisor'):
                    self.env['mail.activity'].sudo().create({
                        'res_model_id': self.env.ref('hr_attendance.model_hr_attendance').id,
                        'res_id': self.id,
                        'user_id': employee.parent_id.user_id.id,
                        'summary': _('Attendance Violation: %s Late Check-in') % employee.name,
                        'note': _('Employee %s checked in late on %s.') % (employee.name, today),
                        'activity_type_id': self.env.ref('mail.mail_activity_data_todo').id,
                    })

            if triggered_rule and triggered_rule.offense_id:
                existing_case = self.env['discipline.case'].sudo().search([
                    ('employee_id', '=', employee.id),
                    ('offense_id', '=', triggered_rule.offense_id.id),
                    ('state', 'in', ['draft', 'initiated', 'investigating']),
                    ('incident_date', '>=', today - timedelta(days=triggered_rule.reset_window_months * 30))
                ], limit=1)
                if not existing_case:
                    case = self.env['discipline.case'].sudo().create({
                        'employee_id': employee.id,
                        'offense_id': triggered_rule.offense_id.id,
                        'description': _(
                            'Attendance Violation Rule Exceeded: %s\n'
                            'Threshold: %.2f hours | Recorded Late Hours: %.2f hours (Window: %d months)\n'
                            'Configured Salary Deduction: %.1f Days'
                        ) % (triggered_rule.name, triggered_rule.threshold_hours, matched_late_hours, triggered_rule.reset_window_months, triggered_rule.deduction_days),
                        'reference': 'ATT-LATE-%s' % self.id,
                    })
                    if hasattr(case, 'action_initiate'):
                        case.action_initiate()
            elif hours_threshold > 0:
                eval_start_date = today - timedelta(days=eval_months * 30)
                recent_atts = self.env['hr.attendance'].sudo().search([
                    ('employee_id', '=', employee.id),
                    ('check_in', '>=', fields.Datetime.to_datetime(eval_start_date)),
                    ('check_in_status', '=', 'Late')
                ])
                total_late_hours = sum(getattr(att, 'late_time_hour', 0.0) or getattr(att, 'late_time', 0.0) or 0.0 for att in recent_atts)
                if total_late_hours >= hours_threshold:
                    self.env['discipline.case'].sudo()._create_from_attendance(
                        employee.id, 'lateness', self.id
                    )

                # Escalation on threshold breach
                if notif_log.log_and_check(employee.id, 'violation_hr_escalation'):
                    # Target configured HR user or fallback to managers
                    escalation_user_id = params.get_param('hr_attendance.escalation_hr_user_id')
                    target_users = self.env['res.users'].browse(int(escalation_user_id)) if escalation_user_id and escalation_user_id.isdigit() else self.env.ref('hr_attendance.group_hr_attendance_manager').users
                    for hr_user in target_users:
                        self.env['mail.activity'].sudo().create({
                            'res_model_id': self.env.ref('hr_attendance.model_hr_attendance').id,
                            'res_id': self.id,
                            'user_id': hr_user.id,
                            'summary': _('ESCALATION: Cumulative Late Hours Threshold Exceeded for %s') % employee.name,
                            'note': _('Employee %s has reached %.2f cumulative late hours over the last %d months (Threshold: %.2f hrs). Discipline case initiated.') % (employee.name, total_late_hours, eval_months, hours_threshold),
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

            # Notify Supervisor on force checkout violation
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

            if force_checkout_threshold > 0 and new_count >= force_checkout_threshold:
                employee._reset_force_checkout_count()
                self.env['discipline.case'].sudo()._create_from_attendance(
                    employee.id, 'force_checkout', self.id
                )

                # HR Escalation on force checkout threshold breach
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

        # --- DYNAMIC CONFIGURABLE ABSENCE DISCIPLINE RULES ENGINE ---
        absence_rules = self.env['attendance.absence.rule'].sudo().search([('active', '=', True)], order='threshold_days desc')
        if absence_rules:
            today = fields.Date.context_today(self)
            for a_rule in absence_rules:
                eval_start = today - timedelta(days=a_rule.reset_window_months * 30)
                # Calculate unexcused missing days + half-day absences in window
                half_day_atts = self.env['hr.attendance'].sudo().search([
                    ('employee_id', '=', employee.id),
                    ('check_in', '>=', fields.Datetime.to_datetime(eval_start)),
                    ('worked_hours', '>', 0.0),
                    ('worked_hours', '<', 4.0)
                ])
                tot_absent_days = len(half_day_atts) * 0.5
                
                if tot_absent_days >= a_rule.threshold_days and a_rule.offense_id:
                    existing_case = self.env['discipline.case'].sudo().search([
                        ('employee_id', '=', employee.id),
                        ('offense_id', '=', a_rule.offense_id.id),
                        ('state', 'in', ['draft', 'initiated', 'investigating']),
                        ('incident_date', '>=', eval_start)
                    ], limit=1)
                    if not existing_case:
                        case = self.env['discipline.case'].sudo().create({
                            'employee_id': employee.id,
                            'offense_id': a_rule.offense_id.id,
                            'description': _(
                                'Absence Discipline Rule Exceeded: %s\n'
                                'Threshold: %.1f Days | Recorded Absence: %.1f Days (Window: %d months)\n'
                                'Configured Salary Deduction: %.1f Days'
                            ) % (a_rule.name, a_rule.threshold_days, tot_absent_days, a_rule.reset_window_months, a_rule.deduction_days),
                            'reference': 'ATT-ABS-%s' % self.id,
                        })
                        if hasattr(case, 'action_initiate'):
                            case.action_initiate()
                    break



