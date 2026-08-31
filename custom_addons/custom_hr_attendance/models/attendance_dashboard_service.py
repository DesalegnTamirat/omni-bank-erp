# -*- coding: utf-8 -*-
import datetime
import math
import pytz
from odoo import api, fields, models, _


class HrAttendanceDashboardService(models.Model):
    _inherit = 'hr.attendance'

    # ------------------------------------------------------------------
    # Main Client Action Entry Point
    # ------------------------------------------------------------------
    @api.model
    def get_attendance_dashboard(
        self,
        filter_type='today',
        specific_date=None,
        dept_or_dist_id=None,
        ou_id=None,
        personal_period='this_month',
        personal_start=None,
        personal_end=None,
        *args,
        **kwargs,
    ):
        """Aggregate KPI/chart data for the Attendance Dashboard client action
        strictly for a single specific date for Corporate, and for personal_period for Personal.
        Enforces merged District/Directorate hierarchy and dynamic branch scoping.
        """
        user = self.env.user
        employee = user.employee_id
        if not employee:
            employee = self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)

        user_tz_name = user.tz or 'Africa/Addis_Ababa'
        try:
            local_tz = pytz.timezone(user_tz_name)
        except Exception:
            local_tz = pytz.timezone('Africa/Addis_Ababa')

        today = fields.Date.context_today(self)
        target_date = self._resolve_target_date(filter_type, specific_date, today)

        # Compute UTC range [start_dt, end_dt] for the full 24h of target_date in local tz
        start_local = local_tz.localize(datetime.datetime.combine(target_date, datetime.time.min))
        end_local = local_tz.localize(datetime.datetime.combine(target_date, datetime.time.max))
        start_utc = start_local.astimezone(pytz.utc).replace(tzinfo=None)
        end_utc = end_local.astimezone(pytz.utc).replace(tzinfo=None)

        # 1. Resolve Access Level & Scoped Permissions
        access_info = self._resolve_user_access_level(user, employee)
        has_corporate_access = access_info['has_corporate_access']
        access_level = access_info['access_level']

        # 2. Get Hierarchy Filter Options for Frontend Selectors (Merged Districts & Directorates)
        filter_options = self._get_hierarchy_filter_options(access_info, dept_or_dist_id=dept_or_dist_id)

        # 3. Resolve Effective Employee IDs for Corporate Scope
        scoped_emp_ids = None
        if has_corporate_access:
            scoped_emp_ids = self._get_scoped_employee_ids(
                access_info,
                dept_or_dist_id=dept_or_dist_id,
                ou_id=ou_id,
            )

        cr = self.env.cr

        # 4. Corporate Stats (Only computed if user has access)
        kpi = {'total': 0, 'present': 0, 'late': 0, 'leave': 0, 'absent': 0}
        progress = []
        workunit = []

        if has_corporate_access:
            total = self._dashboard_total_employees(cr, scoped_emp_ids)
            present, late = self._dashboard_present_and_late(cr, start_utc, end_utc, scoped_emp_ids)
            leave = self._dashboard_on_leave(cr, target_date, scoped_emp_ids)
            absent = max(0, total - present - leave)
            kpi = {
                'total': total,
                'present': present,
                'late': late,
                'leave': leave,
                'absent': absent,
            }
            progress = self._dashboard_hourly_progress(cr, start_utc, end_utc, local_tz, scoped_emp_ids)
            workunit = self._dashboard_workunit_breakdown(cr, start_utc, end_utc, scoped_emp_ids)

        # 5. Personal Dashboard Stats
        personal_summary = self._dashboard_personal_summary(
            local_tz, target_date, personal_period, personal_start, personal_end, employee
        )

        return {
            'today': target_date.strftime('%A, %B %d, %Y'),
            'target_date': str(target_date),
            'filter_type': filter_type,
            'has_corporate_access': has_corporate_access,
            'access_level': access_level,
            'user_role_label': access_info['role_label'],
            'filter_options': filter_options,
            'active_filters': {
                'dept_or_dist_id': dept_or_dist_id or False,
                'ou_id': ou_id or False,
            },
            'kpi': kpi,
            'progress': progress,
            'workunit': workunit,
            'personal_summary': personal_summary,
        }

    # ------------------------------------------------------------------
    # Hierarchy & Access Level Resolution
    # ------------------------------------------------------------------
    def _resolve_user_access_level(self, user, employee):
        """Determine the organizational access level:
        - 'admin': Full bank-wide visibility & all filters (CEO / HR Attendance Manager / System Admin)
        - 'chief': Scoped to Directorates / Districts under Chief's hierarchy
        - 'district_or_dept': Scoped to District or Directorate, can filter child OUs
        - 'ou_manager': Scoped to their Operating Unit / Branch
        - 'employee': Individual only, no corporate dashboard
        """
        is_admin = (
            (hasattr(user, '_is_admin') and user._is_admin()) or
            (hasattr(user, '_is_system') and user._is_system()) or
            user.has_group('hr_attendance.group_hr_attendance_manager') or
            user.has_group('base.group_system') or
            user.id == 2
        )

        if is_admin:
            return {
                'access_level': 'admin',
                'has_corporate_access': True,
                'role_label': _('Administrator / Bank-Wide Access'),
                'employee': employee,
                'managed_districts': [],
                'managed_ous': [],
                'managed_depts': [],
            }

        if not employee:
            return {
                'access_level': 'employee',
                'has_corporate_access': False,
                'role_label': _('Employee View'),
                'employee': False,
                'managed_districts': [],
                'managed_ous': [],
                'managed_depts': [],
            }

        job_title = (employee.job_id.name or '').strip().lower()

        # Check if Chief / C-Level Executive
        is_chief = (
            'chief' in job_title or
            'ceo' in job_title or
            'president' in job_title or
            'vice president' in job_title or
            'executive director' in job_title
        )

        # Check if managing District or Regional Office
        managed_district_ous = self.env['operating.unit'].sudo().search([
            ('manager_id', '=', employee.id),
            ('work_unit_type', 'in', ['district_office', 'regional_office'])
        ])

        # Check if managing any Operating Unit (Branch / Head Office / Sub-branch)
        managed_all_ous = self.env['operating.unit'].sudo().search([
            ('manager_id', '=', employee.id)
        ])

        # Check if managing a Department / Directorate
        managed_depts = self.env['hr.department'].sudo().search([
            ('manager_id', '=', employee.id)
        ])

        # Check if has subordinates
        has_subordinates = bool(self.env['hr.employee'].sudo().search([
            '|', ('parent_id', '=', employee.id), ('attendance_manager_id', '=', user.id)
        ], limit=1))

        if is_chief:
            return {
                'access_level': 'chief',
                'has_corporate_access': True,
                'role_label': _('Chief / Executive Hierarchy'),
                'employee': employee,
                'managed_districts': managed_district_ous.ids,
                'managed_ous': managed_all_ous.ids,
                'managed_depts': managed_depts.ids,
            }

        if managed_district_ous or managed_depts:
            return {
                'access_level': 'district_or_dept',
                'has_corporate_access': True,
                'role_label': _('District / Directorate Management'),
                'employee': employee,
                'managed_districts': managed_district_ous.ids,
                'managed_ous': managed_all_ous.ids,
                'managed_depts': managed_depts.ids,
            }

        if managed_all_ous or has_subordinates:
            return {
                'access_level': 'ou_manager',
                'has_corporate_access': True,
                'role_label': _('Operating Unit / Branch Manager'),
                'employee': employee,
                'managed_districts': [],
                'managed_ous': managed_all_ous.ids or ([employee.default_operating_unit_id.id] if employee.default_operating_unit_id else []),
                'managed_depts': [],
            }

        # Regular employee with no management role
        return {
            'access_level': 'employee',
            'has_corporate_access': False,
            'role_label': _('Employee'),
            'employee': employee,
            'managed_districts': [],
            'managed_ous': [],
            'managed_depts': [],
        }

    # ------------------------------------------------------------------
    # Hierarchy Dropdown Options Builder (Merged Districts & Directorates)
    # ------------------------------------------------------------------
    def _get_hierarchy_filter_options(self, access_info, dept_or_dist_id=None):
        """Build merged selection lists for District / Directorate and child Operating Units."""
        level = access_info['access_level']
        if level == 'employee':
            return {'districts_and_directorates': [], 'operating_units': []}

        ou_model = self.env['operating.unit'].sudo()
        dept_model = self.env['hr.department'].sudo()

        # 1. Districts (Operating Units of type district_office / regional_office)
        district_domain = [('work_unit_type', 'in', ['district_office', 'regional_office'])]
        if level == 'district_or_dept' and access_info.get('managed_districts'):
            district_domain.append(('id', 'in', access_info['managed_districts']))
        elif level == 'ou_manager':
            district_domain = [('id', '=', -1)]

        raw_districts = ou_model.search_read(district_domain, ['id', 'name'], order='name asc')

        # 2. Directorates (Head Office Departments / Directorates / Head Office OUs)
        dept_domain = [('active', '=', True)]
        if level == 'district_or_dept' and access_info.get('managed_depts'):
            dept_domain.append(('id', 'in', access_info['managed_depts']))
        elif level == 'ou_manager':
            dept_domain = [('id', '=', -1)]

        raw_depts = dept_model.search_read(dept_domain, ['id', 'name'], order='name asc')

        ho_ou_domain = [('work_unit_type', '=', 'head_office')]
        if level == 'district_or_dept' and access_info.get('managed_ous'):
            ho_ou_domain.append(('id', 'in', access_info['managed_ous']))
        elif level == 'ou_manager':
            ho_ou_domain = [('id', '=', -1)]

        raw_ho_ous = ou_model.search_read(ho_ou_domain, ['id', 'name'], order='name asc')

        # Build Merged List
        merged_list = []
        # Add Districts
        for d in raw_districts:
            merged_list.append({
                'id': f"dist_{d['id']}",
                'name': f"📍 {d['name']}",
                'group': 'Districts',
                'raw_name': d['name'],
            })

        # Add Directorates
        seen_names = set()
        for d in raw_depts:
            clean_name = d['name'].strip()
            if clean_name.lower() not in seen_names:
                merged_list.append({
                    'id': f"dept_{d['id']}",
                    'name': f"🏛️ {clean_name}",
                    'group': 'Directorates',
                    'raw_name': clean_name,
                })
                seen_names.add(clean_name.lower())

        for ho in raw_ho_ous:
            clean_name = ho['name'].strip()
            if clean_name.lower() not in seen_names:
                merged_list.append({
                    'id': f"ou_{ho['id']}",
                    'name': f"🏛️ {clean_name}",
                    'group': 'Directorates',
                    'raw_name': clean_name,
                })
                seen_names.add(clean_name.lower())

        # 3. Operating Units / Branches (Scoped when a District or Directorate is chosen)
        ou_domain = [('work_unit_type', 'in', ['branch', 'sub_branch', 'service_center', 'head_office', 'other'])]

        if dept_or_dist_id:
            dept_dist_str = str(dept_or_dist_id).strip()
            if dept_dist_str.startswith('dist_'):
                d_id = int(dept_dist_str.replace('dist_', ''))
                ou_domain.append('|')
                ou_domain.append(('parent_unit', '=', d_id))
                ou_domain.append(('id', '=', d_id))
            elif dept_dist_str.startswith('ou_'):
                ou_real_id = int(dept_dist_str.replace('ou_', ''))
                ou_domain.append(('id', '=', ou_real_id))
            elif dept_dist_str.startswith('dept_'):
                real_dept_id = int(dept_dist_str.replace('dept_', ''))
                ou_domain.append(('department', '=', real_dept_id))
        elif level == 'district_or_dept':
            if access_info.get('managed_districts'):
                ou_domain.append(('parent_unit', 'in', access_info['managed_districts']))
            elif access_info.get('managed_depts'):
                ou_domain.append(('department', 'in', access_info['managed_depts']))
        elif level == 'ou_manager':
            ou_domain.append(('id', 'in', access_info['managed_ous']))

        operating_units = ou_model.search_read(ou_domain, ['id', 'name', 'parent_unit', 'work_unit_type'], order='name asc')

        return {
            'districts_and_directorates': merged_list,
            'operating_units': operating_units,
        }

    # ------------------------------------------------------------------
    # Employee Scope Resolver for SQL Queries
    # ------------------------------------------------------------------
    def _get_scoped_employee_ids(self, access_info, dept_or_dist_id=None, ou_id=None):
        """Compute the list of employee IDs allowed according to access level and active filters."""
        level = access_info['access_level']
        employee = access_info.get('employee')
        emp_model = self.env['hr.employee'].sudo()

        domain = [('active', '=', True)]

        # Specific filters chosen by user
        if ou_id:
            try:
                domain.append(('default_operating_unit_id', '=', int(ou_id)))
            except Exception:
                pass
        elif dept_or_dist_id:
            try:
                val = str(dept_or_dist_id).strip()
                if val.startswith('dist_'):
                    dist_id = int(val.replace('dist_', ''))
                    child_ous = self.env['operating.unit'].sudo().search([
                        '|', ('id', '=', dist_id), ('parent_unit', '=', dist_id)
                    ]).ids
                    domain.append(('default_operating_unit_id', 'in', child_ous))
                elif val.startswith('dept_'):
                    d_id = int(val.replace('dept_', ''))
                    child_depts = self.env['hr.department'].sudo().search([
                        '|', ('id', '=', d_id), ('parent_id', '=', d_id)
                    ]).ids
                    domain.append(('department_id', 'in', child_depts))
                elif val.startswith('ou_'):
                    ho_id = int(val.replace('ou_', ''))
                    child_ous = self.env['operating.unit'].sudo().search([
                        '|', ('id', '=', ho_id), ('parent_unit', '=', ho_id)
                    ]).ids
                    domain.append(('default_operating_unit_id', 'in', child_ous))
                else:
                    d_id = int(val)
                    domain.append(('default_operating_unit_id', '=', d_id))
            except Exception:
                pass

        # Role-based restriction if no specific filter applied
        if level == 'ou_manager' and not ou_id:
            allowed_ous = access_info.get('managed_ous') or []
            if allowed_ous:
                domain.append(('default_operating_unit_id', 'in', allowed_ous))
            elif employee:
                sub_ids = emp_model.search([('parent_id', '=', employee.id)]).ids
                domain.append(('id', 'in', sub_ids + [employee.id]))

        elif level == 'district_or_dept' and not (dept_or_dist_id or ou_id):
            allowed_districts = access_info.get('managed_districts') or []
            allowed_depts = access_info.get('managed_depts') or []
            ou_sub_ids = []
            if allowed_districts:
                ou_sub_ids = self.env['operating.unit'].sudo().search([
                    '|', ('id', 'in', allowed_districts), ('parent_unit', 'in', allowed_districts)
                ]).ids
            conditions = []
            if ou_sub_ids:
                conditions.append(('default_operating_unit_id', 'in', ou_sub_ids))
            if allowed_depts:
                conditions.append(('department_id', 'in', allowed_depts))
            if len(conditions) == 2:
                domain.extend(['|', conditions[0], conditions[1]])
            elif conditions:
                domain.append(conditions[0])

        return emp_model.search(domain).ids

    # ------------------------------------------------------------------
    # Target Date Helper
    # ------------------------------------------------------------------
    def _resolve_target_date(self, filter_type, specific_date, today):
        if filter_type == 'yesterday':
            return today - datetime.timedelta(days=1)
        if specific_date:
            try:
                return fields.Date.to_date(specific_date)
            except Exception:
                pass
        return today

    # ------------------------------------------------------------------
    # Corporate Query Helper Methods (Scoped)
    # ------------------------------------------------------------------
    def _dashboard_total_employees(self, cr, scoped_emp_ids=None):
        if scoped_emp_ids is not None:
            if not scoped_emp_ids:
                return 0
            cr.execute("""
                SELECT COUNT(DISTINCT he.id)
                FROM hr_employee he
                WHERE he.active = true AND he.id = ANY(%s)
            """, (scoped_emp_ids,))
        else:
            cr.execute("""
                SELECT COUNT(DISTINCT he.id)
                FROM hr_employee he
                WHERE he.active = true
            """)
        row = cr.fetchone()
        return (row[0] if row else 0) or 0

    def _dashboard_present_and_late(self, cr, start_utc, end_utc, scoped_emp_ids=None):
        if scoped_emp_ids is not None:
            if not scoped_emp_ids:
                return 0, 0
            cr.execute("""
                SELECT
                    COUNT(DISTINCT employee_id),
                    COUNT(DISTINCT employee_id) FILTER (WHERE check_in_status = 'Late')
                FROM hr_attendance
                WHERE check_in >= %s AND check_in <= %s
                  AND employee_id = ANY(%s)
            """, (start_utc, end_utc, scoped_emp_ids))
        else:
            cr.execute("""
                SELECT
                    COUNT(DISTINCT employee_id),
                    COUNT(DISTINCT employee_id) FILTER (WHERE check_in_status = 'Late')
                FROM hr_attendance
                WHERE check_in >= %s AND check_in <= %s
            """, (start_utc, end_utc))
        present, late = cr.fetchone()
        return present or 0, late or 0

    def _dashboard_on_leave(self, cr, target_date, scoped_emp_ids=None):
        if scoped_emp_ids is not None:
            if not scoped_emp_ids:
                return 0
            cr.execute("""
                SELECT COUNT(DISTINCT employee_id)
                FROM hr_leave
                WHERE state = 'validate'
                  AND date_from::date <= %s
                  AND date_to::date >= %s
                  AND employee_id = ANY(%s)
            """, (target_date, target_date, scoped_emp_ids))
        else:
            cr.execute("""
                SELECT COUNT(DISTINCT employee_id)
                FROM hr_leave
                WHERE state = 'validate'
                  AND date_from::date <= %s
                  AND date_to::date >= %s
            """, (target_date, target_date))
        row = cr.fetchone()
        return (row[0] if row else 0) or 0

    def _dashboard_hourly_progress(self, cr, start_utc, end_utc, local_tz, scoped_emp_ids=None):
        if scoped_emp_ids is not None:
            if not scoped_emp_ids:
                return [
                    {'label': '06:00', 'count': 0},
                    {'label': '08:00', 'count': 0},
                    {'label': '10:00', 'count': 0},
                    {'label': '12:00', 'count': 0},
                    {'label': '14:00', 'count': 0},
                    {'label': '17:00', 'count': 0},
                ]
            cr.execute("""
                SELECT check_in, employee_id
                FROM hr_attendance
                WHERE check_in >= %s AND check_in <= %s
                  AND employee_id = ANY(%s)
                ORDER BY check_in ASC
            """, (start_utc, end_utc, scoped_emp_ids))
        else:
            cr.execute("""
                SELECT check_in, employee_id
                FROM hr_attendance
                WHERE check_in >= %s AND check_in <= %s
                ORDER BY check_in ASC
            """, (start_utc, end_utc))
        rows = cr.fetchall()

        hourly_counts = {}
        for check_in_utc, emp_id in rows:
            if not check_in_utc:
                continue
            loc_dt = pytz.utc.localize(check_in_utc).astimezone(local_tz)
            hour_str = loc_dt.strftime('%H:00')
            if hour_str not in hourly_counts:
                hourly_counts[hour_str] = set()
            hourly_counts[hour_str].add(emp_id)

        sorted_hours = sorted(hourly_counts.keys())
        if not sorted_hours:
            return [
                {'label': '06:00', 'count': 0},
                {'label': '07:00', 'count': 0},
                {'label': '08:00', 'count': 0},
                {'label': '09:00', 'count': 0},
                {'label': '10:00', 'count': 0},
                {'label': '12:00', 'count': 0},
                {'label': '14:00', 'count': 0},
                {'label': '17:00', 'count': 0},
            ]

        return [{'label': h, 'count': len(hourly_counts[h])} for h in sorted_hours]

    def _dashboard_workunit_breakdown(self, cr, start_utc, end_utc, scoped_emp_ids=None):
        if scoped_emp_ids is not None:
            if not scoped_emp_ids:
                return [{'unit': 'No Data', 'count': 0}]
            cr.execute("""
                SELECT
                    CASE
                        WHEN ou.work_unit_type = 'head_office' THEN 'Head Office'
                        WHEN ou.work_unit_type IN ('area_office', 'district_office') THEN ou.name
                        WHEN ou.work_unit_type = 'branch' THEN COALESCE(pou.name, ou.name)
                        ELSE COALESCE(ou.name, 'Other')
                    END AS unit,
                    COUNT(DISTINCT a.employee_id)
                FROM hr_attendance a
                JOIN hr_employee e ON a.employee_id = e.id
                JOIN operating_unit ou ON e.default_operating_unit_id = ou.id
                LEFT JOIN operating_unit pou ON ou.parent_unit = pou.id
                WHERE a.check_in >= %s AND a.check_in <= %s
                  AND a.employee_id = ANY(%s)
                GROUP BY unit
                ORDER BY 2 DESC
            """, (start_utc, end_utc, scoped_emp_ids))
        else:
            cr.execute("""
                SELECT
                    CASE
                        WHEN ou.work_unit_type = 'head_office' THEN 'Head Office'
                        WHEN ou.work_unit_type IN ('area_office', 'district_office') THEN ou.name
                        WHEN ou.work_unit_type = 'branch' THEN COALESCE(pou.name, ou.name)
                        ELSE COALESCE(ou.name, 'Other')
                    END AS unit,
                    COUNT(DISTINCT a.employee_id)
                FROM hr_attendance a
                JOIN hr_employee e ON a.employee_id = e.id
                JOIN operating_unit ou ON e.default_operating_unit_id = ou.id
                LEFT JOIN operating_unit pou ON ou.parent_unit = pou.id
                WHERE a.check_in >= %s AND a.check_in <= %s
                GROUP BY unit
                ORDER BY 2 DESC
            """, (start_utc, end_utc))
        rows = cr.fetchall()
        return [{'unit': unit, 'count': count} for unit, count in rows] if rows else [{'unit': 'Head Office', 'count': 0}]

    # ------------------------------------------------------------------
    # Personal Dashboard Summary Engine (Bunna Bank Metrics)
    # ------------------------------------------------------------------
    def _dashboard_personal_summary(
        self, local_tz, target_date, date_range='this_month', start_date=None, end_date=None, employee=None
    ):
        if not employee:
            return {'has_employee': False}

        today = fields.Date.context_today(self)
        if date_range == 'today':
            s_d, e_d = today, today
        elif date_range == 'yesterday':
            y = today - datetime.timedelta(days=1)
            s_d, e_d = y, y
        elif date_range == 'this_week':
            s_d = today - datetime.timedelta(days=today.weekday())
            e_d = s_d + datetime.timedelta(days=6)
        elif date_range == 'custom' and start_date and end_date:
            try:
                s_d = fields.Date.to_date(start_date)
                e_d = fields.Date.to_date(end_date)
            except Exception:
                s_d = target_date.replace(day=1)
                e_d = today
        else:  # this_month
            s_d = target_date.replace(day=1)
            if target_date.month == 12:
                e_d = datetime.date(target_date.year, 12, 31)
            else:
                e_d = datetime.date(target_date.year, target_date.month + 1, 1) - datetime.timedelta(days=1)

        range_s_utc = local_tz.localize(datetime.datetime.combine(s_d, datetime.time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        range_e_utc = local_tz.localize(datetime.datetime.combine(e_d, datetime.time.max)).astimezone(pytz.utc).replace(tzinfo=None)

        range_atts = self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', range_s_utc),
            ('check_in', '<=', range_e_utc)
        ], order='check_in desc')

        # Card 1: Total Worked Hours & Target Hours
        period_worked_hours = round(sum(att.worked_hours or 0.0 for att in range_atts), 2)
        period_predefined_hours = round(sum((att.pre_defined_lateness or 0.0) + (getattr(att, 'pre_approved_early_checkout', 0.0) or 0.0) for att in range_atts), 2)
        period_compensable_hours = round(period_worked_hours + period_predefined_hours + sum((att.acknowledged_late or 0.0) + (att.acknowledged_exit or 0.0) for att in range_atts), 2)
        period_days = (e_d - s_d).days + 1
        target_hours = 160.0 if (date_range == 'this_month' or period_days > 14) else round(period_days * 8.0, 1)
        worked_hours_pct = min(100.0, round((period_compensable_hours / max(1.0, target_hours)) * 100, 1))
        avg_daily_hours = round(period_worked_hours / max(1, period_days), 1)

        # Card 2: Cumulative Late Hours & Punctuality Rating
        period_late_hours_float = sum(att.late_time_hour or 0.0 for att in range_atts)
        period_late_count = sum(1 for att in range_atts if att.check_in_status == 'Late')
        period_leave_count = sum(1 for att in range_atts if 'Rest' in (att.check_in_status or ''))
        period_normal_count = sum(1 for att in range_atts if (att.check_in_status in ('Normal', 'On-Time', 'On Time') or not att.check_in_status))
        total_sessions = len(range_atts)
        punctuality_score = round(((total_sessions - period_late_count) / max(1, total_sessions)) * 100, 1) if total_sessions > 0 else 100.0

        late_hrs_int = int(period_late_hours_float)
        late_mins_int = int(round((period_late_hours_float - late_hrs_int) * 60))
        late_hours_formatted = f"{late_hrs_int:02d}:{late_mins_int:02d}"

        # Card 3: Offenses & Shift-Aware Absence Evaluation
        force_checkout_count = sum(1 for att in range_atts if (att.check_out_status in ('Force Checkout', 'force_checkout', 'Forced Check-Out') or getattr(att, 'is_force_checkout', False) or getattr(att, 'is_forced_checkout', False)))
        eval_end_d = min(e_d, today)

        def _get_att_work_date(a):
            if getattr(a, 'work_date', False):
                return a.work_date
            if not a.check_in:
                return None
            dt_loc = pytz.utc.localize(a.check_in).astimezone(local_tz) if not a.check_in.tzinfo else a.check_in.astimezone(local_tz)
            return (dt_loc - datetime.timedelta(days=1)).date() if dt_loc.hour < 4 else dt_loc.date()

        now_dt = fields.Datetime.context_timestamp(employee, fields.Datetime.now())
        current_float = now_dt.hour + (now_dt.minute / 60.0)

        # Date-by-date absence evaluation
        full_day_absent = 0
        missed_sessions_count = 0
        cur_d = s_d
        while cur_d <= eval_end_d:
            d_shift = employee._get_employee_shift_info(target_date=cur_d) if hasattr(employee, '_get_employee_shift_info') else None
            is_day_off = bool(d_shift.get('is_day_off')) if d_shift else (cur_d.weekday() == 6)

            # Check approved leave on cur_d
            on_leave = False
            if 'hr.leave' in self.env:
                on_leave = self.env['hr.leave'].sudo().search_count([
                    ('employee_id', '=', employee.id),
                    ('state', '=', 'validate'),
                    ('date_from', '<=', datetime.datetime.combine(cur_d, datetime.time.max)),
                    ('date_to', '>=', datetime.datetime.combine(cur_d, datetime.time.min))
                ]) > 0

            if not is_day_off and not on_leave:
                d_atts = [a for a in range_atts if _get_att_work_date(a) == cur_d]
                m_start = d_shift.get('start_time', 8.0) if d_shift else 8.0
                m_end = d_shift.get('lunch_out_time', 12.0) if d_shift else 12.0
                a_end = d_shift.get('end_time', 17.0) if d_shift else 17.0

                if cur_d < today:
                    if not d_atts:
                        full_day_absent += 1
                    elif d_shift and d_shift.get('has_lunch_break'):
                        has_morning = any(a.shift_end_float <= (m_end + 0.1) or (a.check_in and pytz.utc.localize(a.check_in).astimezone(local_tz).hour < int(m_end)) for a in d_atts if a.check_in)
                        has_afternoon = any(a.shift_start_float >= (m_end - 0.1) or (a.check_in and pytz.utc.localize(a.check_in).astimezone(local_tz).hour >= int(m_end)) for a in d_atts if a.check_in)
                        if not has_morning: missed_sessions_count += 1
                        if not has_afternoon: missed_sessions_count += 1
                elif cur_d == today:
                    # For today: only evaluate if shift/session has already elapsed
                    if not d_atts:
                        if current_float >= a_end:
                            full_day_absent += 1
                        elif d_shift and d_shift.get('has_lunch_break') and current_float >= m_end:
                            missed_sessions_count += 1
                    elif d_shift and d_shift.get('has_lunch_break'):
                        has_morning = any(a.shift_end_float <= (m_end + 0.1) or (a.check_in and pytz.utc.localize(a.check_in).astimezone(local_tz).hour < int(m_end)) for a in d_atts if a.check_in)
                        has_afternoon = any(a.shift_start_float >= (m_end - 0.1) or (a.check_in and pytz.utc.localize(a.check_in).astimezone(local_tz).hour >= int(m_end)) for a in d_atts if a.check_in)
                        if not has_morning and current_float >= m_end: missed_sessions_count += 1
                        if not has_afternoon and current_float >= a_end: missed_sessions_count += 1

            cur_d += datetime.timedelta(days=1)

        absent_count = full_day_absent + round(missed_sessions_count * 0.5, 1)

        # Card 4: Approvals
        acknowledged_count = sum(1 for att in range_atts if (getattr(att, 'is_acknowledged', False) or (getattr(att, 'acknowledged_late', 0.0) or 0.0) > 0 or (getattr(att, 'acknowledged_exit', 0.0) or 0.0) > 0))
        predefined_count = 0
        if 'attendance.preapproval' in self.env:
            predefined_count = self.env['attendance.preapproval'].sudo().search_count([
                ('employee_id', '=', employee.id),
                ('date', '>=', s_d),
                ('date', '<=', e_d),
                ('state', '=', 'approved')
            ])

        # Personal Status Donut SVG
        total_p_samples = max(1, period_normal_count + period_late_count + period_leave_count + absent_count)
        p_pct_normal = round((period_normal_count / total_p_samples) * 100, 1)
        p_pct_late = round((period_late_count / total_p_samples) * 100, 1)
        p_pct_leave = round((period_leave_count / total_p_samples) * 100, 1)
        p_pct_absent = round((absent_count / total_p_samples) * 100, 1)

        c = 251.32
        p_p_dash = round((p_pct_normal / 100.0) * c, 2)
        p_l_dash = round((p_pct_late / 100.0) * c, 2)
        p_lv_dash = round((p_pct_leave / 100.0) * c, 2)
        p_a_dash = round((p_pct_absent / 100.0) * c, 2)

        p_p_off = 0.0
        p_l_off = round(-(p_p_dash), 2)
        p_lv_off = round(-(p_p_dash + p_l_dash), 2)
        p_a_off = round(-(p_p_dash + p_l_dash + p_lv_dash), 2)

        # Progression Points (3-status bars)
        period_weeks = math.ceil(period_days / 7.0)
        raw_blocks = []
        if period_days <= 10:
            cur = s_d
            while cur <= e_d:
                raw_blocks.append({'label': cur.strftime('%b %d'), 'start_date': cur, 'end_date': cur})
                cur += datetime.timedelta(days=1)
        elif period_weeks <= 10:
            wk_start = s_d
            wk_idx = 1
            while wk_start <= e_d:
                wk_end = min(e_d, wk_start + datetime.timedelta(days=6))
                lbl = f"Wk {wk_idx} ({wk_start.strftime('%b %d')}-{wk_end.strftime('%d')})"
                raw_blocks.append({'label': lbl, 'start_date': wk_start, 'end_date': wk_end})
                wk_start = wk_end + datetime.timedelta(days=1)
                wk_idx += 1
        else:
            cur_m = datetime.date(s_d.year, s_d.month, 1)
            while cur_m <= e_d:
                if cur_m.month == 12:
                    next_m = datetime.date(cur_m.year + 1, 1, 1)
                else:
                    next_m = datetime.date(cur_m.year, cur_m.month + 1, 1)
                m_end = min(e_d, next_m - datetime.timedelta(days=1))
                m_start = max(s_d, cur_m)
                raw_blocks.append({'label': m_start.strftime('%b %Y'), 'start_date': m_start, 'end_date': m_end})
                cur_m = next_m

        progression_points = []
        max_bar_h = 1.0
        for block in raw_blocks:
            b_s_utc = local_tz.localize(datetime.datetime.combine(block['start_date'], datetime.time.min)).astimezone(pytz.utc).replace(tzinfo=None)
            b_e_utc = local_tz.localize(datetime.datetime.combine(block['end_date'], datetime.time.max)).astimezone(pytz.utc).replace(tzinfo=None)
            b_atts = [a for a in range_atts if a.check_in and b_s_utc <= a.check_in <= b_e_utc]
            w_h = round(sum(a.worked_hours or 0.0 for a in b_atts), 2)
            l_h = round(sum(a.late_time_hour or 0.0 for a in b_atts), 2)
            b_days = (block['end_date'] - block['start_date']).days + 1
            
            # Count only elapsed or past working days
            past_working_days = sum(1 for d in (block['start_date'] + datetime.timedelta(days=i) for i in range(b_days)) if d.weekday() != 6 and d < today)
            if block['start_date'] <= today <= block['end_date'] and today.weekday() != 6:
                # Include today only if today's shift cutoff has passed
                t_shift = employee._get_employee_shift_info(target_date=today) if hasattr(employee, '_get_employee_shift_info') else None
                t_end = t_shift.get('end_time', 17.0) if t_shift else 17.0
                if current_float >= t_end:
                    past_working_days += 1

            comp_h = w_h + round(sum((a.pre_defined_lateness or 0.0) + (getattr(a, 'pre_approved_early_checkout', 0.0) or 0.0) + (a.acknowledged_late or 0.0) + (a.acknowledged_exit or 0.0) for a in b_atts), 2)
            expected_past_hours = past_working_days * 8.0
            a_h = max(0.0, round(expected_past_hours - comp_h, 2)) if past_working_days > 0 else 0.0
            a_days = round(a_h / 8.0, 1)
            a_days_formatted = int(a_days) if (a_days % 1 == 0) else a_days
            max_bar_h = max(max_bar_h, w_h, l_h, a_h)
            progression_points.append({
                'date_label': block['label'],
                'worked_hours': w_h,
                'late_hours': l_h,
                'absent_hours': a_h,
                'absent_days': a_days_formatted,
            })

        num_blocks = max(1, len(progression_points))
        bar_width_px = 38 if num_blocks <= 3 else (28 if num_blocks <= 5 else (20 if num_blocks <= 7 else 14))
        prog_svg_points = []
        for pt in progression_points:
            prog_svg_points.append({
                'date_label': pt['date_label'],
                'worked_hours': pt['worked_hours'],
                'late_hours': pt['late_hours'],
                'absent_hours': pt['absent_hours'],
                'absent_days': pt['absent_days'],
                'w_pct': round((pt['worked_hours'] / max_bar_h) * 100, 1),
                'l_pct': round((pt['late_hours'] / max_bar_h) * 100, 1),
                'a_pct': round((pt['absent_hours'] / max_bar_h) * 100, 1),
                'bar_width_px': bar_width_px,
            })

        logs = []
        for att in range_atts:
            dt_in = pytz.utc.localize(att.check_in).astimezone(local_tz) if att.check_in else None
            dt_out = pytz.utc.localize(att.check_out).astimezone(local_tz) if att.check_out else None
            logs.append({
                'id': att.id,
                'date': dt_in.strftime('%Y-%m-%d') if dt_in else '',
                'check_in': dt_in.strftime('%I:%M %p') if dt_in else '-',
                'check_out': dt_out.strftime('%I:%M %p') if dt_out else ('Active Session' if not att.check_out else '-'),
                'worked_hours': round(att.worked_hours or 0.0, 2),
                'check_in_status': att.check_in_status or 'Normal',
            })

        return {
            'has_employee': True,
            'employee_name': employee.name,
            'job_title': employee.job_id.name if employee.job_id else 'Staff',
            'department': employee.department_id.name if employee.department_id else '',
            'period_worked_hours': period_worked_hours,
            'target_hours': target_hours,
            'worked_hours_pct': worked_hours_pct,
            'avg_daily_hours': avg_daily_hours,
            'punctuality_score': punctuality_score,
            'late_hours_formatted': late_hours_formatted,
            'late_count': period_late_count,
            'normal_count': period_normal_count,
            'leave_count': period_leave_count,
            'absent_count': absent_count,
            'offenses': {
                'force_checkout': force_checkout_count,
                'absent': absent_count,
                'late': period_late_count,
            },
            'approvals': {
                'acknowledged': acknowledged_count,
                'predefined': predefined_count,
            },
            'personal_donut_svg': {
                'circumference': c,
                'pct_normal': p_pct_normal,
                'pct_late': p_pct_late,
                'pct_leave': p_pct_leave,
                'pct_absent': p_pct_absent,
                'p_dash': f"{p_p_dash} {c}", 'p_off': p_p_off,
                'l_dash': f"{p_l_dash} {c}", 'l_off': p_l_off,
                'lv_dash': f"{p_lv_dash} {c}", 'lv_off': p_lv_off,
                'a_dash': f"{p_a_dash} {c}", 'a_off': p_a_off,
            },
            'progression_points': prog_svg_points,
            'recent_logs': logs,
        }

    # ------------------------------------------------------------------
    # On-Demand Absence & Attendance Query Helpers (For Reports, Discipline & Payroll)
    # ------------------------------------------------------------------
    @api.model
    def get_employee_absent_dates(self, employee_id, start_date, end_date):
        """Compute the list of unexcused absent dates for a specific employee over a date range.
        Excludes approved leaves and Sundays/rest days. Zero cron required.
        """
        s_d = fields.Date.to_date(start_date)
        e_d = fields.Date.to_date(end_date)
        if not (employee_id and s_d and e_d and s_d <= e_d):
            return []

        # 1. Get all check-in dates for employee in range
        s_dt = datetime.datetime.combine(s_d, datetime.time.min)
        e_dt = datetime.datetime.combine(e_d, datetime.time.max)
        atts = self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee_id),
            ('check_in', '>=', s_dt),
            ('check_in', '<=', e_dt),
        ])
        checked_dates = set()
        for a in atts:
            if a.check_in:
                checked_dates.add(a.check_in.date())

        # 2. Get approved leave dates
        leaves = self.env['hr.leave'].sudo().search([
            ('employee_id', '=', employee_id),
            ('state', '=', 'validate'),
            ('date_from', '<=', e_dt),
            ('date_to', '>=', s_dt),
        ])
        leave_dates = set()
        for l in leaves:
            cur_l = max(s_d, l.date_from.date())
            end_l = min(e_d, l.date_to.date())
            while cur_l <= end_l:
                leave_dates.add(cur_l)
                cur_l += datetime.timedelta(days=1)

        # 3. Evaluate calendar working days
        absent_dates = []
        cur = s_d
        while cur <= e_d:
            # Skip Sunday (weekday 6)
            if cur.weekday() != 6:
                if cur not in checked_dates and cur not in leave_dates:
                    absent_dates.append(str(cur))
            cur += datetime.timedelta(days=1)

        return absent_dates

    @api.model
    def get_operating_unit_absent_employees(self, ou_id, target_date=None):
        """Retrieve the list of absent employees for an Operating Unit on a given date.
        Zero cron required.
        """
        t_d = fields.Date.to_date(target_date) if target_date else fields.Date.context_today(self)
        emp_model = self.env['hr.employee'].sudo()
        employees = emp_model.search([
            ('active', '=', True),
            ('default_operating_unit_id', '=', int(ou_id))
        ])
        if not employees:
            return []

        emp_ids = employees.ids
        t_s = datetime.datetime.combine(t_d, datetime.time.min)
        t_e = datetime.datetime.combine(t_d, datetime.time.max)

        # Check-in employee IDs today
        att_emp_ids = set(self.env['hr.attendance'].sudo().search([
            ('employee_id', 'in', emp_ids),
            ('check_in', '>=', t_s),
            ('check_in', '<=', t_e),
        ]).mapped('employee_id.id'))

        # Approved leave employee IDs today
        leave_emp_ids = set(self.env['hr.leave'].sudo().search([
            ('employee_id', 'in', emp_ids),
            ('state', '=', 'validate'),
            ('date_from', '<=', t_e),
            ('date_to', '>=', t_s),
        ]).mapped('employee_id.id'))

        absent_list = []
        for emp in employees:
            if emp.id not in att_emp_ids and emp.id not in leave_emp_ids:
                absent_list.append({
                    'id': emp.id,
                    'name': emp.name,
                    'job_title': emp.job_id.name if emp.job_id else '',
                    'work_email': emp.work_email or '',
                    'work_phone': emp.work_phone or '',
                })

        return absent_list

    @api.model
    def get_payroll_attendance_summary(self, employee_id, start_date, end_date):
        """Clean data endpoint for Payroll to pull attendance metrics without pushing penalties."""
        s_d = fields.Date.to_date(start_date)
        e_d = fields.Date.to_date(end_date)
        s_dt = datetime.datetime.combine(s_d, datetime.time.min)
        e_dt = datetime.datetime.combine(e_d, datetime.time.max)

        atts = self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee_id),
            ('check_in', '>=', s_dt),
            ('check_in', '<=', e_dt),
        ])

        worked_hours = round(sum(a.worked_hours or 0.0 for a in atts), 2)
        late_hours = round(sum(a.late_time_hour or 0.0 for a in atts), 2)
        force_checkout_count = sum(1 for a in atts if a.is_force_checkout)
        absent_dates = self.get_employee_absent_dates(employee_id, start_date, end_date)

        return {
            'employee_id': employee_id,
            'start_date': str(s_d),
            'end_date': str(e_d),
            'worked_hours': worked_hours,
            'late_hours': late_hours,
            'force_checkout_count': force_checkout_count,
            'absent_days_count': len(absent_dates),
            'absent_dates': absent_dates,
        }
