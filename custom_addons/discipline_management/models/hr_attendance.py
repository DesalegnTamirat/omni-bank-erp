# -*- coding: utf-8 -*-
from datetime import timedelta, datetime, time
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


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
            emp = att.sudo().employee_id
            if emp and emp.is_suspended and emp.suspension_type == 'without_pay':
                raise ValidationError(_(
                    "Attendance record cannot be created.\n\n"
                    "Employee '%s' is currently under active Without Pay disciplinary suspension.\n"
                    "Please resolve the disciplinary case before recording attendance."
                ) % emp.name)

    @api.model
    def _get_public_holiday_dates(self, date_from, date_to):
        """Return set of global public holiday dates in [date_from, date_to]."""
        holiday_dates = set()
        CalLeave = self.env.get('resource.calendar.leaves')
        if CalLeave is not None:
            dt_start = datetime.combine(date_from, time.min)
            dt_end = datetime.combine(date_to, time.max)
            pub_leaves = CalLeave.sudo().search([
                ('resource_id', '=', False),
                ('date_from', '<=', dt_end),
                ('date_to', '>=', dt_start),
            ])
            for pl in pub_leaves:
                s_d = max(date_from, pl.date_from.date())
                e_d = min(date_to, pl.date_to.date())
                c_d = s_d
                while c_d <= e_d:
                    holiday_dates.add(c_d)
                    c_d += timedelta(days=1)
        return holiday_dates

    @api.model
    def _get_employee_scheduled_work_days(self, emp, date_from, date_to, public_holidays=None, weekly_rosters=None, roster_exceptions=None):
        """
        Determine the exact required working dates for an employee in [date_from, date_to]:
        - Standard staff: Monday to Saturday (weekday 0..5), excluding Sunday (weekday 6) and public holidays.
        - Shift / Roster staff: Checks my.shift.schedule.line, job.position.roster.exception.line, and
          resource.calendar (including Sunday dayofweek == '6') so shift workers scheduled on Sunday
          have Sunday counted as a working day, and weekday shift rest days are excluded.
        Returns tuple: (sorted_work_dates_list, is_shift_worker_bool, schedule_summary_str)
        """
        if public_holidays is None:
            public_holidays = self._get_public_holiday_dates(date_from, date_to)

        emp_sudo = emp.sudo()
        is_shift_worker = False
        sunday_working_dates = set()
        shift_off_dates = set()
        explicit_shift_work_dates = set()

        # 1. Check job.position.weekly.roster (Weekly Shift Roster)
        if weekly_rosters is not None:
            w_rosters = weekly_rosters
        else:
            WeeklyRoster = self.env.get('job.position.weekly.roster')
            w_rosters = []
            if WeeklyRoster is not None:
                w_rosters = WeeklyRoster.sudo().search([
                    ('employee_id', '=', emp_sudo.id),
                    ('active', '=', True),
                    ('status', '=', 'active'),
                    ('start_date', '<=', date_to),
                    ('end_date', '>=', date_from),
                ])
        if w_rosters:
            day_field_map = {
                0: 'mon_type',
                1: 'tue_type',
                2: 'wed_type',
                3: 'thu_type',
                4: 'fri_type',
                5: 'sat_type',
                6: 'sun_type',
            }
            for wr in w_rosters:
                is_shift_worker = True
                cur_wr_date = max(date_from, wr.start_date)
                end_wr_date = min(date_to, wr.end_date or (wr.start_date + timedelta(days=6)))
                while cur_wr_date <= end_wr_date:
                    weekday = cur_wr_date.weekday()
                    type_field = day_field_map.get(weekday)
                    sched_type = getattr(wr, type_field, 'day_off') if type_field else 'day_off'
                    if sched_type == 'day_off':
                        shift_off_dates.add(cur_wr_date)
                        explicit_shift_work_dates.discard(cur_wr_date)
                        sunday_working_dates.discard(cur_wr_date)
                    elif sched_type == 'shift':
                        explicit_shift_work_dates.add(cur_wr_date)
                        shift_off_dates.discard(cur_wr_date)
                        if weekday == 6:
                            sunday_working_dates.add(cur_wr_date)
                    cur_wr_date += timedelta(days=1)

        # 2. Check job.position.roster.exception.line if installed (Overrides weekly roster)
        if roster_exceptions is not None:
            r_lines = roster_exceptions
        else:
            RosterLine = self.env.get('job.position.roster.exception.line')
            r_lines = []
            if RosterLine is not None:
                r_lines = RosterLine.sudo().search([
                    ('employee_id', '=', emp_sudo.id),
                    ('date', '>=', date_from),
                    ('date', '<=', date_to),
                    ('roster_id.active', '=', True),
                    ('roster_id.status', '=', 'active'),
                ])
        if r_lines:
            is_shift_worker = True
            for rl in r_lines:
                stype = (rl.schedule_type or '').lower()
                if stype in ('off', 'day_off', 'rest', 'leave', 'holiday') or (not rl.shift_id and 'work' not in stype and 'shift' not in stype):
                    shift_off_dates.add(rl.date)
                    explicit_shift_work_dates.discard(rl.date)
                    sunday_working_dates.discard(rl.date)
                else:
                    explicit_shift_work_dates.add(rl.date)
                    shift_off_dates.discard(rl.date)
                    if rl.date.weekday() == 6:
                        sunday_working_dates.add(rl.date)

        # 3. Check employee's resource_calendar_id for Sunday working schedule
        cal = emp_sudo.resource_calendar_id
        cal_works_sunday = False
        cal_work_weekdays = {0, 1, 2, 3, 4, 5}  # Default Mon-Sat
        if cal and cal.attendance_ids:
            cal_days = {int(a.dayofweek) for a in cal.attendance_ids if a.dayofweek and a.dayofweek.isdigit()}
            if 6 in cal_days:
                cal_works_sunday = True
                is_shift_worker = True
                cal_work_weekdays = cal_days

        work_days = []
        cur_day = date_from
        while cur_day <= date_to:
            if cur_day in public_holidays and cur_day not in explicit_shift_work_dates:
                cur_day += timedelta(days=1)
                continue
            if cur_day in shift_off_dates:
                cur_day += timedelta(days=1)
                continue
            if cur_day in explicit_shift_work_dates or cur_day in sunday_working_dates:
                work_days.append(cur_day)
            elif cur_day.weekday() == 6:
                if cal_works_sunday:
                    work_days.append(cur_day)
            else:
                if cur_day.weekday() in cal_work_weekdays:
                    work_days.append(cur_day)
            cur_day += timedelta(days=1)

        if is_shift_worker:
            if sunday_working_dates or cal_works_sunday:
                sched_label = _('Shift Schedule (Sunday Working Shift Included)')
            else:
                sched_label = _('Shift / Roster Schedule')
        else:
            sched_label = _('Standard Mon–Sat Working Schedule')

        return work_days, is_shift_worker, sched_label

    @api.model
    def _compute_max_consecutive_work_days(self, absent_dates, scheduled_work_days):
        """
        Compute maximum consecutive unexcused working days for an employee.
        Two absent dates are consecutive working days if they are adjacent in scheduled_work_days
        (bridging across non-working Sundays for Mon-Sat staff, or bridging across scheduled rest days for shift staff,
        while counting Sunday as a required workday if the shift worker was scheduled on Sunday).
        """
        if not absent_dates or not scheduled_work_days:
            return 0
        work_index = {d: idx for idx, d in enumerate(scheduled_work_days)}
        absent_sorted = sorted(d for d in absent_dates if d in work_index)
        if not absent_sorted:
            return 0

        max_run = 1
        current_run = 1
        for i in range(1, len(absent_sorted)):
            prev_d = absent_sorted[i - 1]
            curr_d = absent_sorted[i]
            if work_index[curr_d] == work_index[prev_d] + 1:
                current_run += 1
                if current_run > max_run:
                    max_run = current_run
            else:
                current_run = 1
        return max_run

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
        skip_existing_active_cases=True,
        ignore_disabled_setting=False
    ):
        """
        Shift-Aware Attendance & Absence Disciplinary Evaluation Engine creating dedicated
        `discipline.attendance.case` records:
        1. Cumulative Late Time (Minutes duration) -> Pending Coach Action (`coach_review`)
        2. Unexcused Absence evaluation (Mon-Sat + Shift Sunday aware):
           - Consecutive >= 5 working days -> Pending Director Review (`director_review`) -> POMD Enforcement
           - Consecutive >= 3 working days -> Pending Coach Action (`coach_review`)
           - Cumulative >= 2 working days -> Pending Coach Action (`coach_review`)
        3. Force Check-Out evaluation -> Pending Coach Action (`coach_review`)
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

        CaseModel = self.env['discipline.attendance.case'].sudo()
        is_enabled = ICP.get_param('discipline.enable_attendance_discipline_cases', 'False').lower() in ('true', '1')
        if not is_enabled and not ignore_disabled_setting:
            return CaseModel

        if not date_to:
            date_to = fields.Date.context_today(self)
        if not date_from:
            date_from = date_to - timedelta(days=rolling_days)

        target_employees = False
        if employee_ids:
            target_employees = self.env['hr.employee'].sudo().browse(
                employee_ids.ids if hasattr(employee_ids, 'ids') else (employee_ids or [])
            ).filtered('active')
            if target_employees:
                self.env.cr.execute("""
                    SELECT DISTINCT he.id 
                    FROM hr_employee he
                    JOIN hr_version hv ON hv.employee_id = he.id
                    WHERE he.id IN %s AND he.active = true AND hv.active = true
                """, [tuple(target_employees.ids)])
                valid_ids = {r[0] for r in self.env.cr.fetchall()}
                if valid_ids:
                    target_employees = target_employees.filtered(lambda e: e.id in valid_ids)
        else:
            self.env.cr.execute("""
                SELECT DISTINCT he.id 
                FROM hr_employee he
                JOIN hr_version hv ON hv.employee_id = he.id
                WHERE he.active = true AND hv.active = true
            """)
            rows = self.env.cr.fetchall()
            if rows:
                target_employees = self.env['hr.employee'].sudo().browse([r[0] for r in rows])
            else:
                target_employees = self.env['hr.employee'].sudo().search([('active', '=', True)])

        if not target_employees:
            return CaseModel

        Category = self.env['discipline.offense.category'].sudo()
        cat = Category.search([('code', '=', 'ATT')], limit=1) or Category.search([('name', '=ilike', 'Attendance%')], limit=1)
        if not cat:
            cat = Category.create({'name': 'Attendance & Timekeeping (የስራ ሰዓትና መገኘት)', 'code': 'ATT'})

        Offense = self.env['discipline.offense'].sudo()
        Severity = self.env['discipline.severity.level'].sudo()

        sev_l1 = Severity.search([('code', '=', 'level_1')], limit=1)
        sev_l2 = Severity.search([('code', '=', 'level_2')], limit=1)
        sev_l4 = Severity.search([('code', '=', 'level_4')], limit=1)
        sev_l5 = Severity.search([('code', '=', 'level_5')], limit=1) or Severity.search([], limit=1)

        created_cases = CaseModel
        public_holidays = self._get_public_holiday_dates(date_from, date_to)
        flagged_employee_ids = set()

        # Pre-fetch shift rosters and exceptions in bulk for high performance
        WeeklyRoster = self.env.get('job.position.weekly.roster')
        weekly_rosters_by_emp = {}
        if WeeklyRoster is not None:
            all_w_rosters = WeeklyRoster.sudo().search([
                ('employee_id', 'in', target_employees.ids),
                ('active', '=', True),
                ('status', '=', 'active'),
                ('start_date', '<=', date_to),
                ('end_date', '>=', date_from),
            ])
            for wr in all_w_rosters:
                weekly_rosters_by_emp.setdefault(wr.employee_id.id, []).append(wr)

        RosterLine = self.env.get('job.position.roster.exception.line')
        roster_exceptions_by_emp = {}
        if RosterLine is not None:
            all_r_lines = RosterLine.sudo().search([
                ('employee_id', 'in', target_employees.ids),
                ('date', '>=', date_from),
                ('date', '<=', date_to),
                ('roster_id.active', '=', True),
                ('roster_id.status', '=', 'active'),
            ])
            for rl in all_r_lines:
                roster_exceptions_by_emp.setdefault(rl.employee_id.id, []).append(rl)

        emp_schedule_cache = {}

        def get_cached_schedule(target_emp):
            emp_id = target_emp.id
            if emp_id not in emp_schedule_cache:
                w_list = weekly_rosters_by_emp.get(emp_id, [])
                r_list = roster_exceptions_by_emp.get(emp_id, [])
                emp_schedule_cache[emp_id] = self._get_employee_scheduled_work_days(
                    target_emp, date_from, date_to, public_holidays,
                    weekly_rosters=w_list, roster_exceptions=r_list
                )
            return emp_schedule_cache[emp_id]

        # -------------------------------------------------------------
        # 1. EVALUATE UNEXCUSED ABSENCES (SHIFT-AWARE CONSECUTIVE & CUMULATIVE)
        # -------------------------------------------------------------
        if violation_type in ('all', 'absence'):
            off_abandonment = Offense.search([('name', '=ilike', '%Abandonment%')], limit=1)
            if not off_abandonment:
                off_abandonment = Offense.create({
                    'name': _('Unexcused Absence Exceeding 5 Consecutive Days (Job Abandonment)'),
                    'category_id': cat.id,
                    'severity_level_id': sev_l1.id if sev_l1 else False,
                })

            off_prolonged = Offense.search([('name', '=ilike', '%Prolonged%')], limit=1)
            if not off_prolonged:
                off_prolonged = Offense.create({
                    'name': _('Prolonged Unexcused Absence (3+ Consecutive Days)'),
                    'category_id': cat.id,
                    'severity_level_id': sev_l2.id if sev_l2 else False,
                })

            off_unexcused = Offense.search([('name', '=ilike', '%Unexcused Absence from Duty%')], limit=1)
            if not off_unexcused:
                off_unexcused = Offense.create({
                    'name': _('Unexcused Absence from Duty / Post'),
                    'category_id': cat.id,
                    'severity_level_id': sev_l4.id if sev_l4 else (sev_l5.id if sev_l5 else False),
                })

            all_atts = self.search([
                ('employee_id', 'in', target_employees.ids),
                '|',
                '&', ('check_in', '>=', date_from), ('check_in', '<=', date_to + timedelta(days=1)),
                '&', ('work_date', '>=', date_from), ('work_date', '<=', date_to),
            ])
            emp_checkin_dates = {}
            for a in all_atts:
                if a.check_in:
                    emp_checkin_dates.setdefault(a.employee_id.id, set()).add(a.check_in.date())
                if getattr(a, 'work_date', False):
                    emp_checkin_dates.setdefault(a.employee_id.id, set()).add(a.work_date)

            Leave = self.env['hr.leave'].sudo()
            all_leaves = Leave.search([
                ('employee_id', 'in', target_employees.ids),
                ('state', '=', 'validate'),
                ('date_from', '<=', date_to + timedelta(days=1)),
                ('date_to', '>=', date_from),
            ])
            emp_leave_dates = {}
            for l in all_leaves:
                l_start = max(date_from, l.date_from.date() if hasattr(l.date_from, 'date') else l.date_from)
                l_end = min(date_to, l.date_to.date() if hasattr(l.date_to, 'date') else l.date_to)
                c_l = l_start
                while c_l <= l_end:
                    emp_leave_dates.setdefault(l.employee_id.id, set()).add(c_l)
                    c_l += timedelta(days=1)

            today = fields.Date.context_today(self)
            # Unexcused absences strictly evaluate completed days (<= yesterday)
            # because 'today' is currently active and shifts/afternoon hours are still pending.
            absence_eval_date_to = min(date_to, today - timedelta(days=1))

            if absence_eval_date_to >= date_from:
                for emp in target_employees:
                    work_days, is_shift, sched_label = get_cached_schedule(emp)
                    # Filter work days strictly to completed days
                    completed_work_days = [d for d in work_days if d <= absence_eval_date_to]
                    if not completed_work_days:
                        continue

                    checkins = emp_checkin_dates.get(emp.id, set())
                    leaves = emp_leave_dates.get(emp.id, set())

                    absent_days = [d for d in completed_work_days if d not in checkins and d not in leaves]
                    if not absent_days:
                        continue

                    max_consecutive = self._compute_max_consecutive_work_days(absent_days, completed_work_days)
                    total_absent = len(absent_days)

                    target_offense = False
                    target_severity = False
                    att_vtype = False
                    target_state = 'coach_review'

                    if max_consecutive >= absence_dismissal_consecutive_days:
                        target_offense = off_abandonment
                        target_severity = sev_l1
                        att_vtype = 'absence_dismissal'
                        target_state = 'director_review'
                    elif max_consecutive >= absence_warning_consecutive_days:
                        target_offense = off_prolonged
                        target_severity = sev_l2
                        att_vtype = 'absence_prolonged'
                        target_state = 'coach_review'
                    elif total_absent >= absence_cumulative_days_threshold:
                        target_offense = off_unexcused
                        target_severity = sev_l4
                        att_vtype = 'absence_minor'
                        target_state = 'coach_review'

                    if not target_offense:
                        continue

                    flagged_employee_ids.add(emp.id)

                    if skip_existing_active_cases:
                        existing = CaseModel.search([
                            ('employee_id', '=', emp.id),
                            ('state', 'in', ['draft', 'coach_review', 'director_review', 'pomd_review', 'enforced']),
                            ('date_from', '<=', date_to),
                            ('date_to', '>=', date_from),
                        ], limit=1)
                        if existing:
                            # Dynamic Escalation & Update for Active Ongoing Absence Cases
                            if existing.state in ('draft', 'coach_review', 'director_review'):
                                dates_str = ', '.join(d.strftime('%Y-%m-%d') for d in absent_days[:12])
                                if len(absent_days) > 12:
                                    dates_str += f" (+{len(absent_days) - 12} more)"

                                # Threshold crossed: 5+ consecutive working days -> Dismissal (escalates to Director Review)
                                if max_consecutive >= absence_dismissal_consecutive_days and existing.violation_type != 'absence_dismissal':
                                    prior_vtype_label = dict(CaseModel._fields['violation_type'].selection).get(existing.violation_type, existing.violation_type)
                                    existing.write({
                                        'violation_type': 'absence_dismissal',
                                        'offense_id': off_abandonment.id,
                                        'severity_level_id': sev_l1.id if sev_l1 else False,
                                        'state': 'director_review',
                                        'absent_dates_summary': dates_str,
                                        'absent_days_count': total_absent,
                                        'max_consecutive_days': max_consecutive,
                                        'date_to': absence_eval_date_to,
                                        'incident_date': absence_eval_date_to,
                                    })
                                    existing._compute_sanction_details()
                                    msg = Markup(_(
                                        '<strong>🚨 Automated Escalation to Dismissal Review (≥ %d Consecutive Days):</strong><br/>'
                                        '• Ongoing unexcused absences accumulated from <strong>%s</strong> to <strong>%d consecutive working days</strong> (Total absent: %d days).<br/>'
                                        '• <strong>Prior Stage:</strong> Coach Review (%s)<br/>'
                                        '• <strong>New Stage:</strong> Escalated to <strong>Pending Director Review</strong>.<br/>'
                                        '• <strong>Action Required:</strong> Directorate Director to review and forward to POMD for dismissal enforcement.'
                                    ) % (
                                        absence_dismissal_consecutive_days,
                                        prior_vtype_label,
                                        max_consecutive,
                                        total_absent,
                                        existing.name,
                                    ))
                                    existing.message_post(body=msg)
                                    created_cases |= existing

                                # Ongoing absences increased but still within warning/coach stage
                                elif max_consecutive > existing.max_consecutive_days or total_absent > existing.absent_days_count:
                                    existing.write({
                                        'absent_dates_summary': dates_str,
                                        'absent_days_count': total_absent,
                                        'max_consecutive_days': max_consecutive,
                                        'date_to': absence_eval_date_to,
                                        'incident_date': absence_eval_date_to,
                                    })
                                    existing._compute_sanction_details()
                                    existing.message_post(body=Markup(_(
                                        '<strong>ℹ️ Ongoing Absence Update:</strong><br/>'
                                        'Unexcused absences accumulated to <strong>%d days</strong> (Max consecutive: %d days). Evaluation period updated to %s.'
                                    ) % (total_absent, max_consecutive, absence_eval_date_to)))
                                    created_cases |= existing

                            continue

                    dates_str = ', '.join(d.strftime('%Y-%m-%d') for d in absent_days[:12])
                    if len(absent_days) > 12:
                        dates_str += f" (+{len(absent_days) - 12} more)"

                    case = CaseModel.create({
                        'employee_id': emp.id,
                        'is_attendance_case': True,
                        'violation_type': att_vtype,
                        'offense_id': target_offense.id,
                        'severity_level_id': target_severity.id if target_severity else False,
                        'incident_date': absence_eval_date_to,
                        'date_from': date_from,
                        'date_to': absence_eval_date_to,
                        'absent_dates_summary': dates_str,
                        'absent_days_count': total_absent,
                        'max_consecutive_days': max_consecutive,
                        'is_shift_worker': is_shift,
                        'shift_schedule_summary': sched_label,
                        'state': target_state,
                        'description': _(
                            'Automated Attendance Escalation — Unexcused Working Day Absences:\n'
                            '- Employee: %s (ID: %s)\n'
                            '- Applied Schedule: %s\n'
                            '- Period: %s to %s\n'
                            '- Max Consecutive Unexcused Working Days: %d\n'
                            '- Total Unexcused Absent Days: %d (%s)\n'
                            '- Routing: %s'
                        ) % (
                            emp.name,
                            emp.identification_id or 'N/A',
                            sched_label,
                            date_from,
                            absence_eval_date_to,
                            max_consecutive,
                            total_absent,
                            dates_str,
                            _('Directorate Director Notified -> Escalated for Dismissal Enforcement.')
                            if att_vtype == 'absence_dismissal'
                            else _('Direct Coach Review (Enforce Warning/Fine, or Adjust with Approved Leave).'),
                        ),
                    })
                    created_cases |= case

        # -------------------------------------------------------------
        # 2. EVALUATE CUMULATIVE LATE TIME (MINUTES)
        # -------------------------------------------------------------
        if violation_type in ('all', 'late') and late_minutes_threshold > 0:
            late_offense = Offense.search([('name', '=ilike', '%Lateness%')], limit=1)
            if not late_offense:
                late_offense = Offense.create({
                    'name': _('Repeated Lateness Violation (ተደጋጋሚ የማርፈድ ጥፋት)'),
                    'category_id': cat.id,
                    'severity_level_id': sev_l5.id if sev_l5 else (sev_l4.id if sev_l4 else False),
                    'punishment_type': 'verbal_warning',
                    'penalty_percentage': 0.0,
                })

            att_domain = [
                ('employee_id', 'in', target_employees.ids),
                ('check_in', '>=', date_from),
                ('check_in', '<=', date_to + timedelta(days=1)),
            ]
            if 'check_in_status' in self._fields:
                att_domain.append('|')
                att_domain.append(('is_late', '=', True))
                att_domain.append(('check_in_status', 'in', ['Late', 'Very Late']))
            else:
                att_domain.append(('is_late', '=', True))

            if 'is_acknowledged' in self._fields:
                att_domain.append(('is_acknowledged', '!=', True))
            if 'check_in_status' in self._fields:
                att_domain.append(('check_in_status', '!=', 'Acknowledged Lateness'))

            late_attendances = self.search(att_domain)
            emp_late_map = {}
            for a in late_attendances:
                if getattr(a, 'is_acknowledged', False) or getattr(a, 'check_in_status', '') == 'Acknowledged Lateness':
                    continue
                emp_id = a.employee_id.id
                if emp_id not in emp_late_map:
                    emp_late_map[emp_id] = {'mins': 0.0, 'count': 0, 'emp': a.employee_id}
                l_h = getattr(a, 'late_time_hour', 0.0) or 0.0
                m = l_h if l_h > 12.0 else (l_h * 60.0)
                if m <= 0.0:
                    m = 30.0
                emp_late_map[emp_id]['mins'] += m
                emp_late_map[emp_id]['count'] += 1

            for emp_id, data in emp_late_map.items():
                if emp_id in flagged_employee_ids:
                    # Skip lateness if employee already has an unexcused absence case in this period
                    continue

                total_mins = round(data['mins'], 1)
                if total_mins < late_minutes_threshold:
                    continue

                emp = data['emp']
                if skip_existing_active_cases:
                    existing = CaseModel.search([
                        ('employee_id', '=', emp.id),
                        ('state', 'in', ['draft', 'coach_review', 'director_review', 'pomd_review', 'enforced']),
                        ('date_from', '<=', date_to),
                        ('date_to', '>=', date_from),
                    ], limit=1)
                    if existing:
                        flagged_employee_ids.add(emp.id)
                        if existing.violation_type == 'late' and existing.state == 'coach_review' and total_mins > existing.late_minutes_total:
                            existing.write({
                                'late_minutes_total': total_mins,
                                'late_occurrences_count': data['count'],
                                'date_to': date_to,
                                'incident_date': date_to,
                            })
                            existing._compute_sanction_details()
                            existing.message_post(body=Markup(_(
                                '<strong>ℹ️ Cumulative Lateness Update:</strong><br/>'
                                'Late time increased to <strong>%s</strong> (%d check-in occurrences). Period extended to %s.'
                            ) % (time_str, data['count'], date_to)))
                        continue

                hours = int(total_mins // 60)
                rem_mins = int(round(total_mins % 60))
                time_str = f"{hours}h {rem_mins}m" if hours > 0 else f"{rem_mins} minutes"
                _w_days, is_shift, sched_label = get_cached_schedule(emp)

                case = CaseModel.create({
                    'employee_id': emp.id,
                    'is_attendance_case': True,
                    'violation_type': 'late',
                    'offense_id': late_offense.id,
                    'severity_level_id': late_offense.severity_level_id.id if late_offense.severity_level_id else (sev_l5.id if sev_l5 else False),
                    'incident_date': date_to,
                    'date_from': date_from,
                    'date_to': date_to,
                    'late_minutes_total': total_mins,
                    'late_occurrences_count': data['count'],
                    'is_shift_worker': is_shift,
                    'shift_schedule_summary': sched_label,
                    'state': 'coach_review',
                    'description': _(
                        'Automated Attendance Escalation — Cumulative Tardiness:\n'
                        '- Employee: %s (ID: %s)\n'
                        '- Violation Period: %s to %s\n'
                        '- Total Cumulative Late Time: %s (%d minutes across %d occurrences)\n'
                        '- Policy Threshold: %d minutes\n'
                        '- Direct Coach Action: Enforce Warning/Penalty, or adjust absent/late time with approved leave.'
                    ) % (emp.name, emp.identification_id or 'N/A', date_from, date_to, time_str, int(total_mins), data['count'], late_minutes_threshold),
                })
                flagged_employee_ids.add(emp.id)
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
                    'severity_level_id': sev_l4.id if sev_l4 else (sev_l5.id if sev_l5 else False),
                    'punishment_type': 'verbal_warning',
                    'penalty_percentage': 0.0,
                })

            force_domain = [
                ('employee_id', 'in', target_employees.ids),
                ('check_in', '>=', date_from),
                ('check_in', '<=', date_to + timedelta(days=1)),
                ('is_force_checkout', '=', True),
            ]
            if 'is_acknowledged' in self._fields:
                force_domain.append(('is_acknowledged', '!=', True))
            for emp, f_count in self._read_group(force_domain, ['employee_id'], ['__count']):
                if not emp or f_count < force_threshold:
                    continue
                if emp.id in flagged_employee_ids:
                    continue
                if skip_existing_active_cases:
                    existing = CaseModel.search([
                        ('employee_id', '=', emp.id),
                        ('state', 'in', ['draft', 'coach_review', 'director_review', 'pomd_review', 'enforced']),
                        ('date_from', '<=', date_to),
                        ('date_to', '>=', date_from),
                    ], limit=1)
                    if existing:
                        continue

                _w_days, is_shift, sched_label = get_cached_schedule(emp)

                case = CaseModel.create({
                    'employee_id': emp.id,
                    'is_attendance_case': True,
                    'violation_type': 'force_checkout',
                    'offense_id': force_offense.id,
                    'severity_level_id': force_offense.severity_level_id.id if force_offense.severity_level_id else (sev_l5.id if sev_l5 else False),
                    'incident_date': date_to,
                    'date_from': date_from,
                    'date_to': date_to,
                    'force_checkout_count': f_count,
                    'is_shift_worker': is_shift,
                    'shift_schedule_summary': sched_label,
                    'state': 'coach_review',
                    'description': _(
                        'Automated Attendance Escalation — Force Check-Out Violations:\n'
                        '- Employee: %s (ID: %s)\n'
                        '- Period: %s to %s\n'
                        '- Force Check-Out Count: %d (Threshold: %d)'
                    ) % (emp.name, emp.identification_id or 'N/A', date_from, date_to, f_count, force_threshold),
                })
                flagged_employee_ids.add(emp.id)
                created_cases |= case

        return created_cases

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_attendance_discipline_cases()
        return records

    def write(self, vals):
        res = super().write(vals)
        if any(k in vals for k in ('is_acknowledged', 'check_in', 'check_out', 'work_date')):
            self._sync_attendance_discipline_cases()
        return res

    def _sync_attendance_discipline_cases(self):
        """Automatically re-verify open attendance disciplinary cases when an attendance punch is created or acknowledged."""
        CaseModel = self.env.get('discipline.attendance.case')
        if CaseModel is None:
            return
        for att in self:
            emp = att.employee_id
            if not emp:
                continue
            d = att.check_in.date() if att.check_in else getattr(att, 'work_date', False)
            if not d:
                continue
            active_cases = CaseModel.sudo().search([
                ('employee_id', '=', emp.id),
                ('state', 'in', ['coach_review', 'director_review', 'pomd_review']),
                ('date_from', '<=', d),
                ('date_to', '>=', d),
            ])
            for c in active_cases:
                c.action_recheck_leave_coverage(silent=True)

    @api.model
    def _cron_escalate_attendance_violations(self):
        """Nightly scheduled cron (01:30 AM): triggers shift-aware attendance and absence scanning."""
        ICP = self.env['ir.config_parameter'].sudo()
        if not ICP.get_param('discipline.enable_attendance_discipline_cases', 'False').lower() in ('true', '1'):
            return False

        today = fields.Date.context_today(self)
        yesterday = today - timedelta(days=1)

        # Check for system launch / initial start date
        launch_date_str = ICP.get_param('discipline.system_launch_date', False)
        launch_date = fields.Date.from_string(launch_date_str) if launch_date_str else False

        rolling_days = int(ICP.get_param('discipline.attendance_rolling_days', 30))
        computed_date_from = yesterday - timedelta(days=rolling_days)

        if launch_date and computed_date_from < launch_date:
            date_from = launch_date
        else:
            date_from = computed_date_from

        date_to = yesterday
        if date_from > date_to:
            return False

        return self.scan_and_initiate_attendance_cases(date_from=date_from, date_to=date_to)
