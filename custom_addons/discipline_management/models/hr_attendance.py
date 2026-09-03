# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    is_suspended_attendance = fields.Boolean(
        string='Recorded Under Disciplinary Suspension',
        compute='_compute_is_suspended_attendance',
        store=True
    )
    suspension_notes = fields.Char(string='Suspension Attendance Note')

    @api.depends('employee_id', 'check_in')
    def _compute_is_suspended_attendance(self):
        for att in self:
            if att.employee_id and att.employee_id.is_suspended:
                att.is_suspended_attendance = True
                att.suspension_notes = _('Employee is under active disciplinary suspension (%s).') % att.employee_id.suspension_type
            else:
                att.is_suspended_attendance = False
                att.suspension_notes = False

    @api.constrains('employee_id', 'check_in')
    def _check_unpaid_suspension_attendance(self):
        """ORM-level safety net: blocks attendance recording for employees under active WITHOUT PAY suspension."""
        for att in self:
            if att.employee_id.is_suspended and att.employee_id.suspension_type == 'without_pay':
                raise ValidationError(_(
                    "Attendance record cannot be created.\n\n"
                    "Employee '%s' is currently under active Without Pay disciplinary suspension.\n"
                    "Please resolve the disciplinary case before recording attendance."
                ) % att.employee_id.name)

    @api.model_create_multi
    def create(self, vals_list):
        return super().create(vals_list)

    # -------------------------------------------------------------------------
    # Attendance Discipline Automation (Checkout, Lateness, Absenteeism)
    # -------------------------------------------------------------------------
    @api.model
    def _cron_escalate_attendance_violations(self):
        """Monitors checkout, lateness, and absenteeism thresholds, auto-initiates discipline cases,

        and routes them directly to the employee's Coach/Manager with action reminders.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        lateness_threshold = int(ICP.get_param('discipline.attendance_lateness_threshold', 3))
        checkout_threshold = int(ICP.get_param('discipline.attendance_checkout_threshold', 3))
        rolling_days = int(ICP.get_param('discipline.attendance_rolling_days', 30))
        date_from = fields.Date.context_today(self) - timedelta(days=rolling_days)

        recent_attendances = self.search([('check_in', '>=', date_from)])
        employees = recent_attendances.mapped('employee_id')

        # Cache category and default severity
        Category = self.env['discipline.offense.category']
        att_cat = Category.search([('name', '=ilike', 'Attendance')], limit=1)
        if not att_cat:
            att_cat = Category.create({'name': 'Attendance Violations', 'code': 'ATT_VIOLATION'})

        sev_level_4 = self.env['discipline.severity.level'].search([('code', '=', 'level_4')], limit=1) or self.env['discipline.severity.level'].search([], limit=1)
        sev_level_5 = self.env['discipline.severity.level'].search([('code', '=', 'level_5')], limit=1) or sev_level_4

        Offense = self.env['discipline.offense']

        for emp in employees:
            emp_atts = recent_attendances.filtered(lambda a: a.employee_id == emp)
            coach_user = (emp.coach_id.user_id or emp.parent_id.user_id) if (emp.coach_id or emp.parent_id) else False

            # 1. Lateness Threshold Check
            late_atts = emp_atts.filtered(lambda a: getattr(a, 'is_late', False) or (getattr(a, 'late_time_hour', 0.0) or 0.0) > 0.0)
            if len(late_atts) >= lateness_threshold:
                offense_late = Offense.search([('name', '=ilike', 'Repeated Lateness / Tardiness')], limit=1)
                if not offense_late:
                    offense_late = Offense.create({
                        'name': 'Repeated Lateness / Tardiness',
                        'category_id': att_cat.id,
                        'severity_level_id': sev_level_4.id if sev_level_4 else False,
                    })
                self._create_or_remind_attendance_case(
                    emp=emp,
                    offense=offense_late,
                    sev_level=sev_level_4,
                    violation_type='lateness',
                    count=len(late_atts),
                    rolling_days=rolling_days,
                    coach_user=coach_user
                )

            # 2. Checkout Irregularity / Forced Checkout Threshold Check
            checkout_atts = emp_atts.filtered(
                lambda a: getattr(a, 'is_forced_checkout', False) or (a.check_in and not a.check_out) or (a.check_in and a.check_out and (a.check_out - a.check_in).total_seconds() < 14400)
            )
            if len(checkout_atts) >= checkout_threshold:
                offense_checkout = Offense.search([('name', '=ilike', 'Forced Checkout / Checkout Irregularity')], limit=1)
                if not offense_checkout:
                    offense_checkout = Offense.create({
                        'name': 'Forced Checkout / Checkout Irregularity',
                        'category_id': att_cat.id,
                        'severity_level_id': sev_level_4.id if sev_level_4 else False,
                    })
                self._create_or_remind_attendance_case(
                    emp=emp,
                    offense=offense_checkout,
                    sev_level=sev_level_4,
                    violation_type='checkout',
                    count=len(checkout_atts),
                    rolling_days=rolling_days,
                    coach_user=coach_user
                )

    @api.model
    def _create_or_remind_attendance_case(self, emp, offense, sev_level, violation_type, count, rolling_days, coach_user):
        """Create draft/initiated attendance case and remind the coach."""
        today = fields.Date.context_today(self)
        existing = self.env['discipline.case'].search([
            ('employee_id', '=', emp.id),
            ('offense_id', '=', offense.id),
            ('state', 'in', ['draft', 'initiated', 'escalated_director', 'escalated_chief']),
            ('is_system_generated', '=', True),
            ('incident_date', '>=', today - timedelta(days=rolling_days))
        ], limit=1)

        labels = {
            'lateness': _('Repeated Lateness'),
            'checkout': _('Forced Checkout / Irregular Checkouts'),
            'absence': _('Unauthorized Absence'),
        }
        type_label = labels.get(violation_type, _('Attendance Violation'))

        if not existing:
            desc = _(
                'System Generated Attendance Case:\n'
                'Employee %s has reached the threshold for %s with %d violations recorded within the past %d days.\n'
                'Designated Coach / Line Manager is requested to review the circumstances, edit punishment/details if necessary, and decide or escalate.'
            ) % (emp.name, type_label, count, rolling_days)

            case = self.env['discipline.case'].create({
                'employee_id': emp.id,
                'offense_id': offense.id,
                'severity_level_id': sev_level.id if sev_level else False,
                'incident_date': today,
                'is_system_generated': True,
                'is_attendance_case': True,
                'attendance_violation_type': violation_type,
                'description': desc,
                'state': 'initiated',
            })
            if coach_user:
                case.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('Attendance Discipline Review: %s (%s)') % (emp.name, type_label),
                    note=_('Employee %s reached the %s threshold (%d instances). Please review, adjust punishment if required, and decide or escalate.') % (emp.name, type_label, count),
                    user_id=coach_user.id,
                    date_deadline=today + timedelta(days=3)
                )
                case.message_post(body=_('Case assigned to Coach / Line Manager %s for review.') % coach_user.name)
        else:
            # Remind coach on existing pending case
            if coach_user:
                existing.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('REMINDER: Attendance Discipline Case %s for %s') % (existing.name, emp.name),
                    note=_('Disciplinary case %s remains pending your decision or escalation.') % existing.name,
                    user_id=coach_user.id,
                    date_deadline=today + timedelta(days=2)
                )

