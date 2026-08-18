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
        records = super().create(vals_list)
        for rec in records:
            rec._check_attendance_discipline_threshold()
        return records

    @api.model
    def _cron_escalate_attendance_violations(self):
        """Cron action: Monitor force check-outs and repeated lateness, auto-generating draft discipline cases."""
        ICP = self.env['ir.config_parameter'].sudo()
        threshold_count = int(ICP.get_param('discipline.attendance_lateness_threshold_count', 3))
        rolling_days = int(ICP.get_param('discipline.attendance_lateness_rolling_days', 30))
        date_from = fields.Date.context_today(self) - timedelta(days=rolling_days)

        recent_attendances = self.search([('check_in', '>=', date_from)])
        employees = recent_attendances.mapped('employee_id')
        for emp in employees:
            emp_atts = recent_attendances.filtered(lambda a: a.employee_id == emp)
            # Count force check-outs or repeated lateness
            forced_or_late_count = len(emp_atts.filtered(
                lambda a: getattr(a, 'is_force_checkout', False) or getattr(a, 'is_forced_checkout', False) or a.check_out_status in ('Force Checkout', 'force_checkout', 'Forced Check-Out') or getattr(a, 'is_late', False) or (a.check_in and a.check_out and (a.check_out - a.check_in).total_seconds() < 14400)
            ))
            if forced_or_late_count >= threshold_count or len(emp_atts) >= threshold_count:
                Category = self.env['discipline.offense.category']
                cat = Category.search([('name', '=ilike', 'Attendance')], limit=1)
                if not cat:
                    cat = Category.create({'name': 'Attendance', 'code': 'ATT_CAT'})
                
                Offense = self.env['discipline.offense']
                offense = Offense.search([('category_id', '=', cat.id)], limit=1)
                if not offense:
                    offense = Offense.create({
                        'name': 'Repeated Lateness / Attendance Violation',
                        'category_id': cat.id,
                        'severity_level': 'level_4',
                        'punishment_type': 'first_warning_penalty',
                    })
                
                existing = self.env['discipline.case'].search([
                    ('employee_id', '=', emp.id),
                    ('offense_id', '=', offense.id),
                    ('state', 'in', ['draft', 'initiated', 'investigating']),
                    ('is_system_generated', '=', True)
                ], limit=1)
                if not existing:
                    self.env['discipline.case'].create({
                        'employee_id': emp.id,
                        'offense_id': offense.id,
                        'incident_date': fields.Date.context_today(self),
                        'is_system_generated': True,
                        'description': _('Scheduled Escalation: Employee %s exceeded attendance violation threshold (%d instances recorded in past %d days).') % (emp.name, forced_or_late_count or len(emp_atts), rolling_days),
                    })
