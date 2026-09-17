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
    is_late = fields.Boolean(string='Late Check-In', default=False)
    is_force_checkout = fields.Boolean(string='Force Check-Out', default=False)

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
        """ORM-level safety net: blocks any attendance record creation for employees under active WITHOUT PAY suspension."""
        for att in self:
            if att.employee_id.is_suspended and att.employee_id.suspension_type == 'without_pay':
                raise ValidationError(_(
                    "Attendance record cannot be created.\n\n"
                    "Employee '%s' is currently under active Without Pay disciplinary suspension.\n"
                    "Please resolve the disciplinary case before recording attendance."
                ) % att.employee_id.name)

    def _check_attendance_discipline_threshold(self):
        """Per-record threshold check for attendance violations."""
        for att in self:
            rolling_days = 30
            date_from = fields.Date.context_today(self) - timedelta(days=rolling_days)
            recent_count = self.search_count([
                ('employee_id', '=', att.employee_id.id),
                ('check_in', '>=', date_from),
            ])
            if recent_count >= 3:
                self._cron_escalate_attendance_violations()

    @api.model_create_multi
    def create(self, vals_list):
        # Pure attendance record creation (no synchronous discipline case triggers on hot path)
        return super().create(vals_list)

    @api.model
    def _cron_escalate_attendance_violations(self):
        """Cron action: Monitor repeated lateness, forced check-outs, and consecutive absences, auto-generating disciplinary cases."""
        ICP = self.env['ir.config_parameter'].sudo()
        late_threshold = int(ICP.get_param('discipline.attendance_lateness_threshold', 3))
        force_threshold = int(ICP.get_param('discipline.attendance_force_checkout_threshold', 3))
        rolling_days = int(ICP.get_param('discipline.attendance_rolling_days', 30))
        absence_warning_days = int(ICP.get_param('discipline.absence_warning_consecutive_days', 3))
        absence_dismissal_days = int(ICP.get_param('discipline.absence_dismissal_consecutive_days', 5))
        date_from = fields.Date.context_today(self) - timedelta(days=rolling_days)

        Category = self.env['discipline.offense.category']
        cat = Category.search([('name', '=ilike', 'Attendance')], limit=1)
        if not cat:
            cat = Category.create({'name': 'Attendance', 'code': 'ATT_CAT'})

        Offense = self.env['discipline.offense']
        Severity = self.env['discipline.severity.level']
        
        sev_minor = Severity.search([('code', '=', 'level_5')], limit=1) or Severity.search([], limit=1)
        sev_warning = Severity.search([('code', '=', 'level_2')], limit=1) or sev_minor
        sev_dismissal = Severity.search([('code', '=', 'level_1')], limit=1) or sev_minor

        recent_attendances = self.search([('check_in', '>=', date_from)])
        employees = recent_attendances.mapped('employee_id')
        for emp in employees:
            emp_atts = recent_attendances.filtered(lambda a: a.employee_id == emp)
            late_count = len(emp_atts.filtered(lambda a: getattr(a, 'check_in_status', '') == 'Late' or getattr(a, 'is_late', False)))
            force_count = len(emp_atts.filtered(lambda a: getattr(a, 'is_force_checkout', False) or getattr(a, 'is_forced_checkout', False)))
            supervisor_user = (emp.coach_id.user_id or emp.parent_id.user_id) if (emp.coach_id or emp.parent_id) else False

            # Check Lateness / Force Checkout threshold
            if late_count >= late_threshold or force_count >= force_threshold:
                offense_name = 'Repeated Lateness Violation' if late_count >= late_threshold else 'Repeated Forced Check-Out Violation'
                offense = Offense.search([('name', '=ilike', offense_name)], limit=1)
                if not offense:
                    offense = Offense.create({
                        'name': offense_name,
                        'category_id': cat.id,
                        'severity_level_id': sev_minor.id if sev_minor else False,
                    })

                existing = self.env['discipline.case'].search([
                    ('employee_id', '=', emp.id),
                    ('offense_id', '=', offense.id),
                    ('state', 'in', ['draft', 'initiated']),
                    ('is_system_generated', '=', True)
                ], limit=1)

                if not existing:
                    case = self.env['discipline.case'].create({
                        'employee_id': emp.id,
                        'offense_id': offense.id,
                        'severity_level_id': offense.severity_level_id.id if offense.severity_level_id else sev_minor.id,
                        'incident_date': fields.Date.context_today(self),
                        'is_system_generated': True,
                        'case_action_track': 'direct_enforce',
                        'reviewer_id': supervisor_user.id if supervisor_user else False,
                        'description': _(
                            'Automated Attendance Escalation: Employee %s accumulated %d lateness and %d forced checkout violations in the past %d days. '
                            'Review and direct enforcement by Coach/Supervisor required.'
                        ) % (emp.name, late_count, force_count, rolling_days),
                    })
                    if supervisor_user:
                        case.activity_schedule(
                            'mail.mail_activity_data_todo',
                            summary=_('Disciplinary Action Required: Attendance Violation (%s)') % emp.name,
                            note=_('Employee %s has breached the attendance threshold. Please review the case and enforce disciplinary action.') % emp.name,
                            user_id=supervisor_user.id
                        )
