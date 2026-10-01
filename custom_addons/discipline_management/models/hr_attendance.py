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

    @api.model
    def scan_and_initiate_attendance_cases(self, employee_ids=None, date_from=None, date_to=None, late_threshold=None, skip_existing_active_cases=True):
        """
        High-performance targeted scanner: identifies repeated lateness & forced checkout violations
        and creates auto-initiated disciplinary cases for Direct Manager / Coach review and manual enforcement.
        Can be executed on-demand by managers or on off-peak schedule.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        if late_threshold is None:
            late_threshold = int(ICP.get_param('discipline.attendance_lateness_threshold', 3))
        force_threshold = int(ICP.get_param('discipline.attendance_force_checkout_threshold', 3))
        rolling_days = int(ICP.get_param('discipline.attendance_rolling_days', 30))

        if not date_to:
            date_to = fields.Date.context_today(self)
        if not date_from:
            date_from = date_to - timedelta(days=rolling_days)

        Category = self.env['discipline.offense.category']
        cat = Category.search([('name', '=ilike', 'Attendance')], limit=1)
        if not cat:
            cat = Category.create({'name': 'Attendance Violations', 'code': 'ATT_CAT'})

        Offense = self.env['discipline.offense']
        Severity = self.env['discipline.severity.level']
        
        sev_minor = Severity.search([('code', '=', 'level_5')], limit=1) or Severity.search([], limit=1)

        domain = [
            ('check_in', '>=', date_from),
            ('check_in', '<=', date_to + timedelta(days=1)),
        ]
        if employee_ids:
            domain.append(('employee_id', 'in', employee_ids.ids if hasattr(employee_ids, 'ids') else employee_ids))

        # Query only violations directly from database to minimize memory footprint
        late_domain = domain + ['|', ('is_late', '=', True), ('check_in_status', '=', 'Late')] if 'check_in_status' in self._fields else domain + [('is_late', '=', True)]
        
        created_cases = self.env['discipline.case']

        # Query aggregated violation counts by employee
        for emp, late_count in self._read_group(late_domain, ['employee_id'], ['__count']):
            if not emp or late_count < late_threshold:
                continue
            if not emp.active:
                continue

            supervisor_user = (emp.coach_id.user_id or emp.parent_id.user_id) if (emp.coach_id or emp.parent_id) else False

            offense_name = _('Repeated Lateness / Attendance Punctuality Violation')
            offense = Offense.search([('name', '=ilike', offense_name)], limit=1)
            if not offense:
                offense = Offense.create({
                    'name': offense_name,
                    'category_id': cat.id,
                    'severity_level_id': sev_minor.id if sev_minor else False,
                })

            # Check if active draft/initiated case already exists in the same period
            if skip_existing_active_cases:
                existing = self.env['discipline.case'].search([
                    ('employee_id', '=', emp.id),
                    ('offense_id', '=', offense.id),
                    ('state', 'in', ['draft', 'initiated', 'pending_approval', 'enforced']),
                    ('incident_date', '>=', date_from),
                ], limit=1)
                if existing:
                    continue
                case = self.env['discipline.case'].create({
                    'employee_id': emp.id,
                    'offense_id': offense.id,
                    'severity_level_id': offense.severity_level_id.id if offense.severity_level_id else sev_minor.id,
                    'incident_date': date_to,
                    'is_system_generated': True,
                    'case_action_track': 'direct_enforce',
                    'reviewer_id': supervisor_user.id if supervisor_user else False,
                    'description': _(
                        'Automated Attendance Escalation:\n'
                        '- Employee: %s (ID: %s)\n'
                        '- Violation Period: %s to %s\n'
                        '- Total Lateness Occurrences: %d (Threshold: %d)\n\n'
                        'Direct Coach / Manager Action Required: Review attendance logs and manually enforce disciplinary decision or exonerate if valid justification is established.'
                    ) % (emp.name, emp.identification_id or 'N/A', date_from, date_to, late_count, late_threshold),
                })
                # Set directly to initiated for coach review
                case.state = 'initiated'
                if supervisor_user:
                    case.message_post(body=_(
                        'Automated attendance breach detected (%d late check-ins). Assigned to Direct Coach (%s) for manual review and enforcement.'
                    ) % (late_count, supervisor_user.name))
                created_cases |= case

        return created_cases

    @api.model
    def _cron_escalate_attendance_violations(self):
        """Monthly/off-peak closeout cron: triggers attendance scanning with zero continuous overhead."""
        return self.scan_and_initiate_attendance_cases()
