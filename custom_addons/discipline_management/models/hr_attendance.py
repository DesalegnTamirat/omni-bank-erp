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
    def scan_and_initiate_attendance_cases(
        self,
        employee_ids=None,
        date_from=None,
        date_to=None,
        violation_type='all',
        late_minutes_threshold=None,
        absence_warning_consecutive_days=None,
        absence_dismissal_consecutive_days=None,
        absence_cumulative_days_threshold=None,
        enable_force_checkout=None,
        force_threshold=None,
        skip_existing_active_cases=True
    ):
        """
        Enterprise Attendance & Absence Disciplinary Evaluation Engine:
        1. Cumulative Late Time (Minutes duration) evaluation.
        2. Unexcused Absence evaluation:
           - Consecutive >= 5 days -> Level 1 (Dismissal / Committee Escalation per Art 33.8 / 10.7)
           - Consecutive >= 3 days -> Level 2 (Final Warning / Direct Enforce per Art 33.7 / 10.3.3)
           - Cumulative >= 2 days -> Level 4 (First Warning / Direct Enforce per Art 33.5 / 10.4.1)
        3. Force Check-Out evaluation (Configurable master toggle).
        """
        ICP = self.env['ir.config_parameter'].sudo()

        if late_minutes_threshold is None:
            late_minutes_threshold = int(ICP.get_param('discipline.attendance_late_minutes_threshold', 60))
        if absence_warning_consecutive_days is None:
            absence_warning_consecutive_days = int(ICP.get_param('discipline.absence_warning_consecutive_days', 3))
        if absence_dismissal_consecutive_days is None:
            absence_dismissal_consecutive_days = int(ICP.get_param('discipline.absence_dismissal_consecutive_days', 5))
        if absence_cumulative_days_threshold is None:
            absence_cumulative_days_threshold = int(ICP.get_param('discipline.absence_cumulative_days_threshold', 2))
        if enable_force_checkout is None:
            enable_force_checkout = ICP.get_param('discipline.enable_force_checkout_discipline', 'False').lower() in ('true', '1')
        if force_threshold is None:
            force_threshold = int(ICP.get_param('discipline.attendance_force_checkout_threshold', 3))

        rolling_days = int(ICP.get_param('discipline.attendance_rolling_days', 30))

        if not date_to:
            date_to = fields.Date.context_today(self)
        if not date_from:
            date_from = date_to - timedelta(days=rolling_days)

        target_employees = self.env['hr.employee'].browse(
            employee_ids.ids if hasattr(employee_ids, 'ids') else (employee_ids or [])
        ).filtered('active') if employee_ids else self.env['hr.employee'].search([('active', '=', True)])

        if not target_employees:
            return self.env['discipline.case']

        Category = self.env['discipline.offense.category']
        cat = Category.search([('name', '=ilike', 'Attendance%')], limit=1)
        if not cat:
            cat = Category.create({'name': 'Attendance & Punctuality Misconduct', 'code': 'ATT_CAT'})

        Offense = self.env['discipline.offense']
        Severity = self.env['discipline.severity.level']

        sev_l1 = Severity.search([('code', '=', 'level_1')], limit=1)
        sev_l2 = Severity.search([('code', '=', 'level_2')], limit=1)
        sev_l4 = Severity.search([('code', '=', 'level_4')], limit=1)
        sev_l5 = Severity.search([('code', '=', 'level_5')], limit=1) or Severity.search([], limit=1)

        created_cases = self.env['discipline.case']

        # -------------------------------------------------------------
        # 1. EVALUATE CUMULATIVE LATE TIME (MINUTES)
        # -------------------------------------------------------------
        if violation_type in ('all', 'late') and late_minutes_threshold > 0:
            late_offense_name = _('Repeated Lateness / Excessive Cumulative Lost Time')
            late_offense = Offense.search([('name', '=ilike', late_offense_name)], limit=1)
            if not late_offense:
                late_offense = Offense.create({
                    'name': late_offense_name,
                    'category_id': cat.id,
                    'severity_level_id': sev_l5.id if sev_l5 else False,
                })

            att_domain = [
                ('employee_id', 'in', target_employees.ids),
                ('check_in', '>=', date_from),
                ('check_in', '<=', date_to + timedelta(days=1)),
            ]
            if 'check_in_status' in self._fields:
                att_domain.append('|')
                att_domain.append(('is_late', '=', True))
                att_domain.append(('check_in_status', '=', 'Late'))
            else:
                att_domain.append(('is_late', '=', True))

            late_attendances = self.search(att_domain)
            emp_late_map = {}
            for a in late_attendances:
                emp_id = a.employee_id.id
                if emp_id not in emp_late_map:
                    emp_late_map[emp_id] = {'mins': 0.0, 'count': 0, 'emp': a.employee_id}
                # Resolve minutes from late_time_hour or is_late flag
                l_h = getattr(a, 'late_time_hour', 0.0) or 0.0
                m = l_h if l_h > 12.0 else (l_h * 60.0)
                if m <= 0.0:
                    m = 30.0  # default 30 mins when flagged late without explicit duration
                emp_late_map[emp_id]['mins'] += m
                emp_late_map[emp_id]['count'] += 1

            for emp_id, data in emp_late_map.items():
                total_mins = round(data['mins'], 1)
                if total_mins < late_minutes_threshold:
                    continue

                emp = data['emp']
                supervisor_user = (emp.coach_id.user_id or emp.parent_id.user_id) if (emp.coach_id or emp.parent_id) else False

                if skip_existing_active_cases:
                    existing = self.env['discipline.case'].search([
                        ('employee_id', '=', emp.id),
                        ('offense_id', '=', late_offense.id),
                        ('state', 'in', ['draft', 'initiated', 'pending_approval', 'enforced']),
                        ('incident_date', '>=', date_from),
                    ], limit=1)
                    if existing:
                        continue

                hours = int(total_mins // 60)
                rem_mins = int(round(total_mins % 60))
                time_str = f"{hours}h {rem_mins}m" if hours > 0 else f"{rem_mins} minutes"

                case = self.env['discipline.case'].create({
                    'employee_id': emp.id,
                    'offense_id': late_offense.id,
                    'severity_level_id': late_offense.severity_level_id.id if late_offense.severity_level_id else sev_l5.id,
                    'incident_date': date_to,
                    'is_system_generated': True,
                    'case_action_track': 'direct_enforce',
                    'reviewer_id': supervisor_user.id if supervisor_user else False,
                    'description': _(
                        'Automated Attendance Escalation — Cumulative Tardiness:\n'
                        '- Employee: %s (ID: %s)\n'
                        '- Violation Period: %s to %s\n'
                        '- Total Cumulative Late Time: %s (%d minutes)\n'
                        '- Policy Late Time Threshold: %d minutes\n'
                        '- Total Lateness Occurrences: %d\n\n'
                        'Regulatory Citation: Bank Disciplinary Policy Article 10.4.1 / CBA Article 33.5.\n'
                        'Direct Coach / Manager Action Required: Review attendance punch records and manually enforce disciplinary decision or exonerate if justified.'
                    ) % (emp.name, emp.identification_id or 'N/A', date_from, date_to, time_str, int(total_mins), late_minutes_threshold, data['count']),
                })
                case.state = 'initiated'
                if supervisor_user:
                    case.message_post(body=_(
                        'Cumulative tardiness breach detected (%s lost across %d incidents). Assigned to Direct Coach (%s) for review and enforcement.'
                    ) % (time_str, data['count'], supervisor_user.name))
                created_cases |= case

        # -------------------------------------------------------------
        # 2. EVALUATE UNEXCUSED ABSENCES (CONSECUTIVE & CUMULATIVE)
        # -------------------------------------------------------------
        if violation_type in ('all', 'absence'):
            # Pre-create/fetch regulatory absence offenses
            off_abandonment = Offense.search([('name', '=ilike', '%Abandonment%')], limit=1) or Offense.create({
                'name': _('Unexcused Absence Exceeding 5 Consecutive Days (Job Abandonment)'),
                'category_id': cat.id,
                'severity_level_id': sev_l1.id if sev_l1 else False,
            })
            off_prolonged = Offense.search([('name', '=ilike', '%Prolonged%')], limit=1) or Offense.create({
                'name': _('Prolonged Unexcused Absence (3+ Consecutive Days)'),
                'category_id': cat.id,
                'severity_level_id': sev_l2.id if sev_l2 else False,
            })
            off_unexcused = Offense.search([('name', '=ilike', '%Unexcused Absence from Duty%')], limit=1) or Offense.create({
                'name': _('Unexcused Absence from Duty / Post'),
                'category_id': cat.id,
                'severity_level_id': sev_l4.id if sev_l4 else (sev_l5.id if sev_l5 else False),
            })

            # Calculate working calendar days in period (excluding Sunday / weekday 6)
            cur_day = date_from
            period_work_days = []
            while cur_day <= date_to:
                if cur_day.weekday() != 6:
                    period_work_days.append(cur_day)
                cur_day += timedelta(days=1)

            if period_work_days:
                # Batch fetch check-ins for target employees in period
                all_atts = self.search([
                    ('employee_id', 'in', target_employees.ids),
                    ('check_in', '>=', date_from),
                    ('check_in', '<=', date_to + timedelta(days=1)),
                ])
                emp_checkin_dates = {}
                for a in all_atts:
                    if a.check_in:
                        c_date = a.check_in.date()
                        emp_checkin_dates.setdefault(a.employee_id.id, set()).add(c_date)

                # Batch fetch validated leaves
                Leave = self.env['hr.leave'].sudo()
                all_leaves = Leave.search([
                    ('employee_id', 'in', target_employees.ids),
                    ('state', '=', 'validate'),
                    ('date_from', '<=', date_to + timedelta(days=1)),
                    ('date_to', '>=', date_from),
                ])
                emp_leave_dates = {}
                for l in all_leaves:
                    l_start = max(date_from, l.date_from.date())
                    l_end = min(date_to, l.date_to.date())
                    c_l = l_start
                    while c_l <= l_end:
                        emp_leave_dates.setdefault(l.employee_id.id, set()).add(c_l)
                        c_l += timedelta(days=1)

                for emp in target_employees:
                    checkins = emp_checkin_dates.get(emp.id, set())
                    leaves = emp_leave_dates.get(emp.id, set())

                    # Determine unexcused absent dates
                    absent_days = [d for d in period_work_days if d not in checkins and d not in leaves]
                    if not absent_days:
                        continue

                    # Calculate consecutive runs
                    absent_days_sorted = sorted(absent_days)
                    consecutive_runs = []
                    current_run = []
                    for d in absent_days_sorted:
                        if not current_run:
                            current_run.append(d)
                        else:
                            # If adjacent calendar day or adjacent over weekend
                            diff = (d - current_run[-1]).days
                            if diff == 1 or (diff == 2 and current_run[-1].weekday() == 5):  # Sat -> Mon
                                current_run.append(d)
                            else:
                                consecutive_runs.append(current_run)
                                current_run = [d]
                    if current_run:
                        consecutive_runs.append(current_run)

                    max_consecutive = max(len(r) for r in consecutive_runs) if consecutive_runs else 0
                    total_absent = len(absent_days_sorted)

                    target_offense = False
                    target_severity = False
                    action_track = 'direct_enforce'
                    escalation_tier_label = ''
                    citation = ''

                    if max_consecutive >= absence_dismissal_consecutive_days:
                        target_offense = off_abandonment
                        target_severity = sev_l1
                        action_track = 'committee_escalation'
                        escalation_tier_label = _('Level 1 Critical — Job Abandonment / Dismissal')
                        citation = _('Labor Proclamation & CBA Article 33.8 / Managerial Policy Article 10.7 (Summary Dismissal)')
                    elif max_consecutive >= absence_warning_consecutive_days:
                        target_offense = off_prolonged
                        target_severity = sev_l2
                        action_track = 'direct_enforce'
                        escalation_tier_label = _('Level 2 Major — Prolonged Absence (Final Warning)')
                        citation = _('CBA Article 33.7 / Managerial Policy Article 10.3.3 (Final Written Warning & Fine)')
                    elif total_absent >= absence_cumulative_days_threshold:
                        target_offense = off_unexcused
                        target_severity = sev_l4
                        action_track = 'direct_enforce'
                        escalation_tier_label = _('Level 4 Minor — Unexcused Absence (Written Warning)')
                        citation = _('CBA Article 33.5.1(መ) / Managerial Policy Article 10.4.1')

                    if not target_offense:
                        continue

                    supervisor_user = (emp.coach_id.user_id or emp.parent_id.user_id) if (emp.coach_id or emp.parent_id) else False

                    if skip_existing_active_cases:
                        existing = self.env['discipline.case'].search([
                            ('employee_id', '=', emp.id),
                            ('offense_id', '=', target_offense.id),
                            ('state', 'in', ['draft', 'initiated', 'pending_approval', 'enforced']),
                            ('incident_date', '>=', date_from),
                        ], limit=1)
                        if existing:
                            continue

                    dates_str = ', '.join(d.strftime('%Y-%m-%d') for d in absent_days_sorted[:10])
                    if len(absent_days_sorted) > 10:
                        dates_str += f" ... (+{len(absent_days_sorted) - 10} more days)"

                    case = self.env['discipline.case'].create({
                        'employee_id': emp.id,
                        'offense_id': target_offense.id,
                        'severity_level_id': target_severity.id if target_severity else target_offense.severity_level_id.id,
                        'incident_date': date_to,
                        'is_system_generated': True,
                        'case_action_track': action_track,
                        'reviewer_id': supervisor_user.id if supervisor_user else False,
                        'description': _(
                            'Automated Disciplinary Escalation — Unexcused Absence:\n'
                            '- Employee: %s (ID: %s)\n'
                            '- Violation Period: %s to %s\n'
                            '- Escalation Tier: %s\n'
                            '- Maximum Consecutive Unexcused Days: %d\n'
                            '- Total Unexcused Absent Days in Period: %d\n'
                            '- Absent Dates: %s\n\n'
                            'Regulatory Statutory Citation: %s\n'
                            'Action Required: %s'
                        ) % (
                            emp.name,
                            emp.identification_id or 'N/A',
                            date_from,
                            date_to,
                            escalation_tier_label,
                            max_consecutive,
                            total_absent,
                            dates_str,
                            citation,
                            _('Formal Hearing & Executive Committee Escalation.') if action_track == 'committee_escalation' else _('Direct Coach / Line Manager Review & Manual Enforcement.')
                        ),
                    })
                    case.state = 'initiated'
                    if supervisor_user:
                        case.message_post(body=_(
                            'Unexcused absence breach detected (%d consecutive / %d total absent days). Escalated under track [%s].'
                        ) % (max_consecutive, total_absent, action_track))
                    created_cases |= case

        # -------------------------------------------------------------
        # 3. EVALUATE FORCE CHECK-OUT (CONFIGURABLE)
        # -------------------------------------------------------------
        if violation_type in ('all', 'force_checkout') and enable_force_checkout and force_threshold > 0:
            force_offense_name = _('Repeated Failure to Check-Out / Force Check-Out Violation')
            force_offense = Offense.search([('name', '=ilike', force_offense_name)], limit=1)
            if not force_offense:
                force_offense = Offense.create({
                    'name': force_offense_name,
                    'category_id': cat.id,
                    'severity_level_id': sev_l5.id if sev_l5 else False,
                })

            force_domain = [
                ('employee_id', 'in', target_employees.ids),
                ('check_in', '>=', date_from),
                ('check_in', '<=', date_to + timedelta(days=1)),
                ('is_force_checkout', '=', True),
            ]
            for emp, f_count in self._read_group(force_domain, ['employee_id'], ['__count']):
                if not emp or f_count < force_threshold:
                    continue
                supervisor_user = (emp.coach_id.user_id or emp.parent_id.user_id) if (emp.coach_id or emp.parent_id) else False

                if skip_existing_active_cases:
                    existing = self.env['discipline.case'].search([
                        ('employee_id', '=', emp.id),
                        ('offense_id', '=', force_offense.id),
                        ('state', 'in', ['draft', 'initiated', 'pending_approval', 'enforced']),
                        ('incident_date', '>=', date_from),
                    ], limit=1)
                    if existing:
                        continue

                case = self.env['discipline.case'].create({
                    'employee_id': emp.id,
                    'offense_id': force_offense.id,
                    'severity_level_id': force_offense.severity_level_id.id if force_offense.severity_level_id else sev_l5.id,
                    'incident_date': date_to,
                    'is_system_generated': True,
                    'case_action_track': 'direct_enforce',
                    'reviewer_id': supervisor_user.id if supervisor_user else False,
                    'description': _(
                        'Automated Attendance Escalation — Force Check-Out Violations:\n'
                        '- Employee: %s (ID: %s)\n'
                        '- Violation Period: %s to %s\n'
                        '- Force Check-Out Count: %d (Threshold: %d)\n\n'
                        'Direct Coach / Manager Action Required: Verify gate/biometric logs and enforce administrative compliance warning.'
                    ) % (emp.name, emp.identification_id or 'N/A', date_from, date_to, f_count, force_threshold),
                })
                case.state = 'initiated'
                if supervisor_user:
                    case.message_post(body=_(
                        'Force check-out threshold exceeded (%d events). Assigned to Coach (%s) for verification.'
                    ) % (f_count, supervisor_user.name))
                created_cases |= case

        return created_cases

    @api.model
    def _cron_escalate_attendance_violations(self):
        """Monthly/off-peak closeout cron: triggers comprehensive attendance and absence scanning."""
        return self.scan_and_initiate_attendance_cases()
