# -*- coding: utf-8 -*-
import datetime
import math
import pytz
import re
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


class HrAttendanceDashboardService(models.Model):
    _inherit = 'hr.attendance'

    @staticmethod
    def _extract_division_name(raw_name):
        if not raw_name:
            return ''
        if isinstance(raw_name, dict):
            raw_name = raw_name.get('en_US') or list(raw_name.values())[0] or ''
        name = str(raw_name).strip()
        # Clean Manager / Acting Manager prefixes
        cleaned = re.sub(r'^(acting\s+)?manager\s*[-–:]\s*', '', name, flags=re.IGNORECASE).strip()
        return cleaned

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
        division_emp_id=None,
        *args,
        **kwargs,
    ):
        """Aggregate KPI/chart data for the Attendance Dashboard client action
        strictly for a single specific date for Corporate, and for personal_period for Personal.
        Enforces dynamic Head Office & Branch hierarchy and clean role scoping.
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
        role_type = access_info.get('role_type', 'employee')

        # Determine effective office and operating unit filter
        office_id = kwargs.get('office_id') or dept_or_dist_id
        division_emp_id = division_emp_id or kwargs.get('division_emp_id')

        # 2. Get Hierarchy Filter Options for Frontend Selectors
        filter_options = self._get_hierarchy_filter_options(
            access_info, office_id=office_id, ou_id=ou_id, division_emp_id=division_emp_id
        )

        # 3. Resolve Effective Employee IDs for Corporate Scope
        scoped_emp_ids = None
        if has_corporate_access:
            scoped_emp_ids = self._get_scoped_employee_ids(
                access_info,
                office_id=office_id,
                ou_id=ou_id,
                division_emp_id=division_emp_id,
            )

        cr = self.env.cr

        # 4. Corporate Stats (Only computed if user has access)
        kpi = {
            'total': 0, 'present_on_time': 0, 'preapproved_count': 0, 'late_unexcused': 0,
            'leave': 0, 'absent': 0, 'pending_preapproval_count': 0, 'acknowledged_count': 0,
            'force_checkout_count': 0, 'session_am_pct': '0%', 'session_pm_pct': '0%',
            'present': 0, 'late': 0,
        }
        progress = []
        workunit = []

        if has_corporate_access:
            kpi = self._dashboard_corporate_kpis(cr, start_utc, end_utc, target_date, scoped_emp_ids)
            progress = self._dashboard_hourly_progress(cr, start_utc, end_utc, local_tz, scoped_emp_ids)
            workunit = self._dashboard_workunit_breakdown(
                cr, start_utc, end_utc, scoped_emp_ids, role_type=role_type, office_id=office_id
            )

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
                'office_id': office_id or False,
                'dept_or_dist_id': office_id or False,
                'ou_id': ou_id or False,
                'division_emp_id': division_emp_id or False,
            },
            'kpi': kpi,
            'progress': progress,
            'workunit': workunit,
            'personal_summary': personal_summary,
        }

    # ------------------------------------------------------------------
    # Hierarchy & Access Level Resolution
    # ------------------------------------------------------------------
    def _get_hierarchy_employee_ids(self, employee_id):
        """Recursively get the employee ID and all their descendant subordinate employee IDs
        following parent_id, coach_id, and attendance_manager_id relationships, as well
        as direct operating units or departments managed by this employee.
        """
        if not employee_id:
            return []
        if hasattr(employee_id, 'id'):
            employee_id = employee_id.id
        cr = self.env.cr
        # 1. Recursive tree via parent_id (strict line of management command) and direct attendance_manager_id
        cr.execute("""
            WITH RECURSIVE sub_tree AS (
                SELECT id, parent_id, user_id
                FROM hr_employee
                WHERE id = %s AND active = true
                UNION
                SELECT e.id, e.parent_id, e.user_id
                FROM hr_employee e
                INNER JOIN sub_tree st ON (
                    e.parent_id = st.id 
                    OR (st.user_id IS NOT NULL AND e.attendance_manager_id = st.user_id)
                )
                WHERE e.active = true
            )
            SELECT id FROM sub_tree;
        """, (employee_id,))
        hierarchy_ids = set(r[0] for r in cr.fetchall())

        # 2. Operating units explicitly managed by this employee (e.g. Branch / Unit Managers)
        cr.execute("""
            SELECT e.id 
            FROM hr_employee e
            JOIN operating_unit ou ON e.default_operating_unit_id = ou.id
            WHERE ou.manager_id = %s AND e.active = true
        """, (employee_id,))
        for r in cr.fetchall():
            hierarchy_ids.add(r[0])

        return list(hierarchy_ids)

    def _resolve_user_access_level(self, user, employee):
        """Determine the organizational access level and specific managerial role:
        - 'admin': Full bank-wide visibility (CEO / HR Attendance Manager / System Admin)
        - 'district_director': Manager of a District Office (manages branch managers)
        - 'director': Manager of a Head Office Directorate (manages division managers)
        - 'division_manager': Manager of a Head Office Division (e.g. Eyob)
        - 'branch_manager': Manager of a Branch (e.g. Dagne)
        - 'employee': Individual only, no corporate dashboard
        """
        is_system_admin = (user.id == 2 or user.has_group('base.group_system'))
        is_attendance_admin = user.has_group('hr_attendance.group_hr_attendance_manager')

        if is_system_admin:
            return {
                'access_level': 'admin',
                'role_type': 'admin',
                'has_corporate_access': True,
                'role_label': _('Administrator / Bank-Wide Access'),
                'employee': employee,
                'hierarchy_employee_ids': None,
                'division_name': '',
            }

        if not employee:
            if is_attendance_admin:
                return {
                    'access_level': 'admin',
                    'role_type': 'admin',
                    'has_corporate_access': True,
                    'role_label': _('HR Attendance Administrator / Bank-Wide Access'),
                    'employee': False,
                    'hierarchy_employee_ids': None,
                    'division_name': '',
                }
            return {
                'access_level': 'employee',
                'role_type': 'employee',
                'has_corporate_access': False,
                'role_label': _('Employee View'),
                'employee': False,
                'hierarchy_employee_ids': [],
                'division_name': '',
            }

        # Resolve hierarchy-based scope
        hierarchy_ids = self._get_hierarchy_employee_ids(employee.id)
        has_subordinates = len(hierarchy_ids) > 1

        # 1. Non-managers (no subordinates)
        if not has_subordinates:
            # HR Attendance Administrators with an employee profile get Bank-Wide Access
            if is_attendance_admin:
                return {
                    'access_level': 'admin',
                    'role_type': 'admin',
                    'has_corporate_access': True,
                    'role_label': _('HR Attendance Administrator / Bank-Wide Access'),
                    'employee': employee,
                    'hierarchy_employee_ids': None,
                    'division_name': '',
                }
            # Regular individual employee: personal view only
            return {
                'access_level': 'employee',
                'role_type': 'employee',
                'has_corporate_access': False,
                'role_label': _('Employee'),
                'employee': employee,
                'hierarchy_employee_ids': [employee.id],
                'division_name': '',
            }

        # 2. Managers (has_subordinates is True)
        job_obj = getattr(employee, 'job_id', False) or getattr(employee, 'job_position', False)
        raw_job_title = (job_obj.name or getattr(employee, 'job_name', '') or '') if job_obj else ''
        if isinstance(raw_job_title, dict):
            raw_job_title = raw_job_title.get('en_US') or list(raw_job_title.values())[0] or ''
        job_title = str(raw_job_title).strip().lower()

        ou = employee.default_operating_unit_id
        ou_type = ou.work_unit_type if ou else ''

        division_name = ''
        is_ceo = any(k in job_title for k in ['chief executive officer', 'ceo', 'president']) and 'deputy' not in job_title and 'vice' not in job_title

        if is_ceo:
            return {
                'access_level': 'admin',
                'role_type': 'admin',
                'has_corporate_access': True,
                'role_label': _('Executive Office (CEO)'),
                'employee': employee,
                'hierarchy_employee_ids': None,
                'division_name': '',
            }
        elif any(k in job_title for k in ['chief', 'deputy chief', 'vice president', 'executive director']):
            role_type = 'chief'
            role_label = _('Executive / Chief Office')
        elif ou_type == 'district_office' or any(k in job_title for k in ['district director', 'director-district', 'director i- east', 'director i- west', 'director i- hawassa', 'director i-']):
            role_type = 'district_director'
            role_label = _('District Office Management')
        elif ou_type == 'head_office' and any(k in job_title for k in ['director', 'directorate']) and 'division' not in job_title:
            role_type = 'director'
            role_label = _('Directorate Management (Head Office)')
        elif ou_type == 'head_office' and ('division' in job_title or 'manager-' in job_title or 'manager -' in job_title):
            role_type = 'division_manager'
            division_name = self._extract_division_name(raw_job_title) or 'Division'
            role_label = _('Division Management (Head Office)')
        elif ou_type == 'branch' or 'branch manager' in job_title:
            role_type = 'branch_manager'
            role_label = _('Branch Management')
        elif is_attendance_admin:
            return {
                'access_level': 'admin',
                'role_type': 'admin',
                'has_corporate_access': True,
                'role_label': _('HR Attendance Administrator / Bank-Wide Access'),
                'employee': employee,
                'hierarchy_employee_ids': None,
                'division_name': '',
            }
        else:
            # Fallback: check if subordinates reside in a single branch unit
            cr = self.env.cr
            cr.execute("""
                SELECT DISTINCT e.default_operating_unit_id, ou.work_unit_type
                FROM hr_employee e
                LEFT JOIN operating_unit ou ON e.default_operating_unit_id = ou.id
                WHERE e.id = ANY(%s) AND e.active = true AND e.default_operating_unit_id IS NOT NULL
            """, (hierarchy_ids,))
            sub_ous = cr.fetchall()
            if len(sub_ous) == 1 and sub_ous[0][1] == 'branch':
                role_type = 'branch_manager'
                role_label = _('Branch Management')
            else:
                role_type = 'hierarchy_manager'
                role_label = _('Team / Unit Management')

        return {
            'access_level': 'hierarchy_manager',
            'role_type': role_type,
            'has_corporate_access': True,
            'role_label': role_label,
            'employee': employee,
            'hierarchy_employee_ids': hierarchy_ids,
            'division_name': division_name,
            'chief_office_name': ou.name if ou else 'Chief Office',
        }

    # ------------------------------------------------------------------
    # Hierarchy Filter Options Builder
    # ------------------------------------------------------------------
    def _get_hierarchy_filter_options(self, access_info, office_id=None, ou_id=None, division_emp_id=None, dept_or_dist_id=None):
        level = access_info['access_level']
        role_type = access_info.get('role_type', 'employee')
        if level == 'employee':
            return {
                'role_type': 'employee',
                'is_locked_unit': True,
                'locked_unit_label': 'Employee View',
                'locked_unit_name': '',
                'locked_unit_count': 0,
                'has_sub_filters': False,
                'sub_filter_label': '',
                'sub_filter_options': [],
                'offices': [],
                'operating_units': [],
                'districts_and_directorates': [],
            }

        hierarchy_ids = access_info.get('hierarchy_employee_ids') or []
        employee = access_info.get('employee')
        ou_model = self.env['operating.unit'].sudo()
        emp_model = self.env['hr.employee'].sudo()

        # 1. Branch Manager / Division Manager / Team Leader / Hierarchy Manager: Single locked unit
        if role_type in ('branch_manager', 'division_manager', 'hierarchy_manager'):
            if role_type == 'division_manager':
                unit_name = access_info.get('division_name') or (employee.default_operating_unit_id.name or 'Division').strip()
                unit_label = _('Managed Division')
            elif role_type == 'branch_manager':
                unit_name = (employee.default_operating_unit_id.name or 'Branch').strip() if employee else 'Branch'
                unit_label = _('Managed Branch')
            else:
                unit_name = (employee.default_operating_unit_id.name or access_info.get('chief_office_name') or 'Managed Unit').strip() if employee else 'Managed Unit'
                unit_label = _('Managed Team / Unit')

            return {
                'role_type': role_type,
                'is_locked_unit': True,
                'locked_unit_label': unit_label,
                'locked_unit_name': unit_name,
                'locked_unit_count': len(hierarchy_ids),
                'has_sub_filters': False,
                'sub_filter_label': '',
                'sub_filter_options': [],
                'offices': [],
                'operating_units': [],
                'districts_and_directorates': [],
            }

        # 3. District Director: Locked District + Branch Dropdown
        if role_type == 'district_director':
            district_name = (employee.default_operating_unit_id.name or 'District Office').strip() if employee else 'District'
            dist_ou_id = employee.default_operating_unit_id.id if employee else False
            child_ou_ids = self._get_operating_unit_and_descendant_ids(dist_ou_id)
            child_branches = ou_model.search([
                ('id', 'in', child_ou_ids),
                ('id', '!=', dist_ou_id),
                ('work_unit_type', 'in', ['branch', 'sub_branch', 'service_center', 'area_office'])
            ], order='name asc')
            sub_filter_options = [{'id': '', 'name': _('All District Branches (%s Branches)') % len(child_branches)}]
            for b in child_branches:
                sub_filter_options.append({'id': str(b.id), 'name': f'📍 {b.name.strip()}'})

            return {
                'role_type': 'district_director',
                'is_locked_unit': False,
                'locked_office_name': district_name,
                'has_sub_filters': True,
                'sub_filter_label': _('Branch:'),
                'sub_filter_options': sub_filter_options,
                'offices': [],
                'operating_units': sub_filter_options,
                'districts_and_directorates': [],
            }

        # 4. Directorate Director: Locked Directorate + Division Dropdown
        if role_type == 'director':
            dir_name = (employee.default_operating_unit_id.name or 'Directorate').strip() if employee else 'Directorate'
            sub_div_managers = emp_model.search([
                ('active', '=', True),
                '|', ('parent_id', '=', employee.id), ('coach_id', '=', employee.id)
            ])
            sub_filter_options = [{'id': '', 'name': _('All Divisions')}]
            for m in sub_div_managers:
                job_obj = getattr(m, 'job_id', False) or getattr(m, 'job_position', False)
                job_name = (job_obj.name or getattr(m, 'job_name', '')) if job_obj else ''
                clean_name = self._extract_division_name(job_name)
                if clean_name and clean_name != 'Office Assistant':
                    sub_filter_options.append({'id': f'div_{m.id}', 'name': f'💼 {clean_name} ({m.name})'})

            return {
                'role_type': 'director',
                'is_locked_unit': False,
                'locked_office_name': dir_name,
                'has_sub_filters': True,
                'sub_filter_label': _('Division:'),
                'sub_filter_options': sub_filter_options,
                'offices': [],
                'operating_units': sub_filter_options,
                'districts_and_directorates': [],
            }

        # 5. Chief Officer (e.g. Chief People and Culture Officer, Chief Information & Digital Officer)
        if role_type == 'chief':
            chief_name = access_info.get('chief_office_name') or 'Chief Office'
            hierarchy_ids = access_info.get('hierarchy_employee_ids') or []
            cr = self.env.cr
            cr.execute("""
                SELECT ou.id, ou.name, count(e.id) as emp_count
                FROM hr_employee e
                JOIN operating_unit ou ON e.default_operating_unit_id = ou.id
                WHERE e.id = ANY(%s) AND e.active = true
                GROUP BY ou.id, ou.name
                ORDER BY emp_count DESC, ou.name ASC
            """, (hierarchy_ids,))
            chief_ous = cr.fetchall()
            sub_filter_options = [{'id': '', 'name': _('All Directorates & Units (%d Staff)') % len(hierarchy_ids)}]
            for ou_id, ou_name, emp_cnt in chief_ous:
                sub_filter_options.append({
                    'id': str(ou_id),
                    'name': f"🏛️ {ou_name.strip()} ({emp_cnt} Staff)"
                })
            return {
                'role_type': 'chief',
                'is_locked_unit': False,
                'locked_office_name': chief_name,
                'has_sub_filters': True,
                'sub_filter_label': _('Directorate:'),
                'sub_filter_type': 'operating_unit',
                'sub_filter_options': sub_filter_options,
                'offices': [],
                'operating_units': sub_filter_options,
                'districts_and_directorates': [],
            }

        # Strict Security Boundary: Only CEO or verified System Admin can ever receive Bank-Wide Cascade!
        if role_type != 'admin':
            unit_name = (employee.default_operating_unit_id.name or 'Managed Unit').strip() if employee else 'Managed Unit'
            return {
                'role_type': role_type,
                'is_locked_unit': True,
                'locked_unit_label': _('Managed Unit'),
                'locked_unit_name': unit_name,
                'locked_unit_count': len(hierarchy_ids),
                'has_sub_filters': False,
                'sub_filter_label': '',
                'sub_filter_options': [],
                'offices': [],
                'operating_units': [],
                'districts_and_directorates': [],
            }

        # 6. Admin / CEO: Full Multi-Tier Cascade
        offices = [{'id': '', 'name': _('All Offices / Districts')}, {'id': 'ho', 'name': '🏛️ Head Office'}]
        districts = ou_model.search([
            ('work_unit_type', 'in', ['district_office', 'regional_office'])
        ], order='name asc')
        for d in districts:
            offices.append({'id': f'dist_{d.id}', 'name': f'📍 {d.name.strip()}'})

        ou_domain = [('work_unit_type', 'in', ['branch', 'sub_branch', 'service_center', 'head_office', 'other'])]
        effective_office = office_id or dept_or_dist_id
        if effective_office == 'ho':
            ou_domain.append(('work_unit_type', '=', 'head_office'))
        elif effective_office and str(effective_office).startswith('dist_'):
            dist_real_id = int(str(effective_office).replace('dist_', ''))
            child_ous = self._get_operating_unit_and_descendant_ids(dist_real_id)
            ou_domain.append(('id', 'in', child_ous))

        raw_ous = ou_model.search_read(ou_domain, ['id', 'name', 'work_unit_type'], order='name asc')
        operating_units = [{'id': '', 'name': _('All Operating Units')}]
        for u in raw_ous:
            operating_units.append({'id': str(u['id']), 'name': u['name'].strip()})

        return {
            'role_type': 'admin',
            'is_locked_unit': False,
            'locked_office_name': '',
            'has_sub_filters': True,
            'sub_filter_label': _('Operating Unit:'),
            'sub_filter_options': operating_units,
            'offices': offices,
            'operating_units': operating_units,
            'districts_and_directorates': offices,
        }

    # ------------------------------------------------------------------
    # Hierarchical Operating Unit Resolver (Recursive Descendants)
    # ------------------------------------------------------------------
    def _get_operating_unit_and_descendant_ids(self, ou_id):
        """Recursively retrieve an Operating Unit and all its descendant Operating Units."""
        if not ou_id:
            return []
        if isinstance(ou_id, (list, tuple, set)):
            try:
                root_ids = [int(x) for x in ou_id if str(x).isdigit()]
            except Exception:
                return []
            if not root_ids:
                return []
            cr = self.env.cr
            cr.execute("""
                WITH RECURSIVE ou_tree AS (
                    SELECT id FROM operating_unit WHERE id = ANY(%s)
                    UNION
                    SELECT ou.id FROM operating_unit ou
                    JOIN ou_tree t ON ou.parent_unit = t.id
                )
                SELECT id FROM ou_tree;
            """, (root_ids,))
            return [r[0] for r in cr.fetchall()]
        try:
            root_id = int(ou_id)
        except Exception:
            return []

        cr = self.env.cr
        cr.execute("""
            WITH RECURSIVE ou_tree AS (
                SELECT id FROM operating_unit WHERE id = %s
                UNION
                SELECT ou.id FROM operating_unit ou
                JOIN ou_tree t ON ou.parent_unit = t.id
            )
            SELECT id FROM ou_tree;
        """, (root_id,))
        return [r[0] for r in cr.fetchall()]

    # ------------------------------------------------------------------
    # Employee Scope Resolver for SQL Queries
    # ------------------------------------------------------------------
    def _get_scoped_employee_ids(self, access_info, office_id=None, ou_id=None, division_emp_id=None, dept_or_dist_id=None):
        role_type = access_info.get('role_type')
        hierarchy_ids = access_info.get('hierarchy_employee_ids') or []
        emp_model = self.env['hr.employee'].sudo()

        if role_type in ('branch_manager', 'division_manager', 'hierarchy_manager'):
            return hierarchy_ids

        if role_type == 'director':
            if division_emp_id and str(division_emp_id).startswith('div_'):
                div_mgr_id = int(str(division_emp_id).replace('div_', ''))
                return self._get_hierarchy_employee_ids(div_mgr_id)
            return hierarchy_ids

        if role_type == 'chief':
            if ou_id:
                try:
                    scoped_ou_ids = self._get_operating_unit_and_descendant_ids(ou_id)
                    return emp_model.search([
                        ('active', '=', True),
                        ('id', 'in', hierarchy_ids),
                        ('default_operating_unit_id', 'in', scoped_ou_ids)
                    ]).ids
                except Exception:
                    pass
            return hierarchy_ids

        if role_type == 'district_director':
            if ou_id:
                try:
                    scoped_ou_ids = self._get_operating_unit_and_descendant_ids(ou_id)
                    return emp_model.search([
                        ('active', '=', True),
                        ('id', 'in', hierarchy_ids),
                        ('default_operating_unit_id', 'in', scoped_ou_ids)
                    ]).ids
                except Exception:
                    pass
            return hierarchy_ids

        # Admin / Bank-Wide Access
        domain = [('active', '=', True)]
        if role_type != 'admin' and hierarchy_ids:
            domain.append(('id', 'in', hierarchy_ids))

        effective_office = office_id or dept_or_dist_id
        if ou_id:
            try:
                scoped_ou_ids = self._get_operating_unit_and_descendant_ids(ou_id)
                domain.append(('default_operating_unit_id', 'in', scoped_ou_ids))
            except Exception:
                pass
        elif effective_office:
            try:
                val = str(effective_office).strip()
                if val == 'ho':
                    ho_ous = self.env['operating.unit'].sudo().search([('work_unit_type', '=', 'head_office')]).ids
                    domain.append(('default_operating_unit_id', 'in', ho_ous))
                elif val.startswith('dist_'):
                    dist_id = int(val.replace('dist_', ''))
                    child_ous = self._get_operating_unit_and_descendant_ids(dist_id)
                    domain.append(('default_operating_unit_id', 'in', child_ous))
            except Exception:
                pass

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

    def _dashboard_corporate_kpis(self, cr, start_utc, end_utc, target_date, scoped_emp_ids):
        """Computes comprehensive KPIs reflecting the new attendance system:
        - Total Workforce
        - On-Time Present (Normal arrival within grace window)
        - Pre-Approved Exceptions (Pre-defined lateness / Pre-approved early departure)
        - Unexcused Late (Actionable unapproved delay)
        - On Leave (Active HR Leave)
        - Absent / Unregistered (No punch recorded today)
        - Pending Preapprovals (Awaiting manager action)
        - Acknowledged Cases
        - Force Checkouts
        - Session AM / PM Coverage Percentages
        """
        if not scoped_emp_ids:
            return {
                'total': 0, 'present_on_time': 0, 'preapproved_count': 0, 'late_unexcused': 0,
                'leave': 0, 'absent': 0, 'pending_preapproval_count': 0, 'acknowledged_count': 0,
                'force_checkout_count': 0, 'session_am_pct': '0%', 'session_pm_pct': '0%',
                'present': 0, 'late': 0,
            }

        total = self._dashboard_total_employees(cr, scoped_emp_ids)

        # 1. Query attendance rows for target date
        cr.execute("""
            SELECT
                COUNT(DISTINCT a.employee_id) AS checked_in_count,
                COUNT(DISTINCT a.employee_id) FILTER (
                    WHERE a.check_in_status = 'Pre-Defined Lateness'
                       OR (a.pre_defined_lateness IS NOT NULL AND a.pre_defined_lateness > 0)
                       OR a.check_out_status = 'Pre-Approved Early Checkout'
                       OR (a.pre_approved_early_checkout IS NOT NULL AND a.pre_approved_early_checkout > 0)
                       OR a.in_mode = 'predefined'
                       OR a.out_mode = 'predefined'
                       OR a.pre_defined_attendance_id IS NOT NULL
                ) AS preapproved_count,
                COUNT(DISTINCT a.employee_id) FILTER (
                    WHERE a.check_in_status IN ('Late', 'Very Late')
                      AND (a.pre_defined_lateness IS NULL OR a.pre_defined_lateness = 0)
                      AND a.check_in_status != 'Pre-Defined Lateness'
                      AND (a.pre_defined_attendance_id IS NULL OR a.pre_approved_early_checkout IS NULL OR a.pre_approved_early_checkout = 0)
                      AND (a.is_acknowledged IS NOT TRUE AND a.in_mode != 'acknowledged')
                ) AS unexcused_late,
                COUNT(DISTINCT a.employee_id) FILTER (
                    WHERE a.is_acknowledged = TRUE
                       OR a.in_mode = 'acknowledged'
                       OR a.out_mode = 'acknowledged'
                       OR (a.acknowledged_late IS NOT NULL AND a.acknowledged_late > 0)
                       OR (a.acknowledged_exit IS NOT NULL AND a.acknowledged_exit > 0)
                       OR a.check_in_status ILIKE '%%Acknowledged%%'
                       OR a.check_out_status ILIKE '%%Acknowledged%%'
                ) AS acknowledged_count,
                COUNT(DISTINCT a.employee_id) FILTER (
                    WHERE a.check_out_status = 'Force Checkout' OR a.is_force_checkout = TRUE
                ) AS force_count,
                COUNT(DISTINCT a.employee_id) FILTER (
                    WHERE (a.check_in AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Addis_Ababa')::time < '12:30:00'::time
                ) AS am_count,
                COUNT(DISTINCT a.employee_id) FILTER (
                    WHERE (a.check_in AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Addis_Ababa')::time >= '12:30:00'::time
                ) AS pm_count
            FROM hr_attendance a
            WHERE a.check_in >= %s AND a.check_in <= %s
              AND a.employee_id = ANY(%s)
        """, (start_utc, end_utc, scoped_emp_ids))
        row = cr.fetchone() or (0, 0, 0, 0, 0, 0, 0)
        checked_in_unique = row[0] or 0
        preapproved = row[1] or 0
        unexcused_late = row[2] or 0
        acknowledged = row[3] or 0
        force_count = row[4] or 0
        am_count = row[5] or 0
        pm_count = row[6] or 0

        # 2. Leave count
        leave = self._dashboard_on_leave(cr, target_date, scoped_emp_ids)

        # 3. Absent count: Staff with neither check-in nor validated leave
        absent = max(0, total - checked_in_unique - leave)

        # 4. On-time / Validated normal count: checked-in staff not preapproved and not unexcused late
        on_time = max(0, checked_in_unique - preapproved - unexcused_late)

        # 4. Pending Preapproval Requests
        cr.execute("""
            SELECT COUNT(id)
            FROM attendance_preapproval
            WHERE state = 'requested'
              AND employee_id = ANY(%s)
        """, (scoped_emp_ids,))
        pending_row = cr.fetchone()
        pending_count = (pending_row[0] if pending_row else 0) or 0

        # Session Percentages
        am_pct = round((am_count / total * 100), 1) if total > 0 else 0
        pm_pct = round((pm_count / total * 100), 1) if total > 0 else 0

        return {
            'total': total,
            'present_on_time': on_time,
            'preapproved_count': preapproved,
            'late_unexcused': unexcused_late,
            'leave': leave,
            'absent': absent,
            'pending_preapproval_count': pending_count,
            'acknowledged_count': acknowledged,
            'force_checkout_count': force_count,
            'session_am_pct': f'{am_pct}%',
            'session_pm_pct': f'{pm_pct}%',
            # Backward compatibility
            'present': checked_in_unique,
            'late': unexcused_late,
        }

    def _dashboard_on_leave(self, cr, target_date, scoped_emp_ids=None):
        # Check global public holiday
        dow_str = str(target_date.weekday())
        try:
            with cr.savepoint():
                cr.execute("""
                    SELECT id FROM resource_calendar_leaves
                    WHERE resource_id IS NULL
                      AND work_unit_type IS NULL
                      AND (
                          (day_of_week IS NOT NULL AND day_of_week = %s)
                          OR ((date_from AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Addis_Ababa')::date <= %s AND (date_to AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Addis_Ababa')::date >= %s)
                      )
                    LIMIT 1
                """, (dow_str, target_date, target_date))
                if cr.fetchone():
                    return self._dashboard_total_employees(cr, scoped_emp_ids)
        except Exception:
            pass

        if scoped_emp_ids is not None:
            if not scoped_emp_ids:
                return 0
            cr.execute("""
                SELECT COUNT(DISTINCT employee_id)
                FROM hr_leave
                WHERE state = 'validate'
                  AND COALESCE(request_date_from, (date_from AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Addis_Ababa')::date) <= %s
                  AND COALESCE(request_date_to, (date_to AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Addis_Ababa')::date) >= %s
                  AND employee_id = ANY(%s)
            """, (target_date, target_date, scoped_emp_ids))
        else:
            cr.execute("""
                SELECT COUNT(DISTINCT employee_id)
                FROM hr_leave
                WHERE state = 'validate'
                  AND COALESCE(request_date_from, (date_from AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Addis_Ababa')::date) <= %s
                  AND COALESCE(request_date_to, (date_to AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Addis_Ababa')::date) >= %s
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

    def _dashboard_workunit_breakdown(self, cr, start_utc, end_utc, scoped_emp_ids=None, role_type=None, office_id=None):
        if not scoped_emp_ids:
            return [{'unit': 'No Data', 'count': 0}]

        # 1. Branch Manager, Division Manager, or Hierarchy Manager (Team Leader): Breakdown by Job Position within unit!
        if role_type in ('branch_manager', 'division_manager', 'hierarchy_manager'):
            cr.execute("""
                SELECT
                    COALESCE(job.name->>'en_US', job.name::text, 'Staff') AS unit,
                    COUNT(DISTINCT a.employee_id) AS count
                FROM hr_attendance a
                JOIN hr_employee e ON a.employee_id = e.id
                LEFT JOIN hr_job job ON e.job_position = job.id
                WHERE a.check_in >= %s AND a.check_in <= %s
                  AND a.employee_id = ANY(%s)
                GROUP BY unit
                ORDER BY 2 DESC
            """, (start_utc, end_utc, scoped_emp_ids))
            rows = cr.fetchall()
            return [{'unit': unit, 'count': count} for unit, count in rows] if rows else [{'unit': 'Staff', 'count': 0}]

        # 2. Chief: Breakdown by Directorates under this Chief
        if role_type == 'chief':
            cr.execute("""
                SELECT
                    ou.name AS unit,
                    COUNT(DISTINCT a.employee_id) AS count
                FROM hr_attendance a
                JOIN hr_employee e ON a.employee_id = e.id
                JOIN operating_unit ou ON e.default_operating_unit_id = ou.id
                WHERE a.check_in >= %s AND a.check_in <= %s
                  AND a.employee_id = ANY(%s)
                GROUP BY ou.name
                ORDER BY 2 DESC
            """, (start_utc, end_utc, scoped_emp_ids))
            rows = cr.fetchall()
            return [{'unit': unit, 'count': count} for unit, count in rows] if rows else [{'unit': 'Directorates', 'count': 0}]

        # 3. District Director or filtered to a specific District: Breakdown by Branch!
        if role_type == 'district_director' or (office_id and str(office_id).startswith('dist_')):
            cr.execute("""
                SELECT
                    COALESCE(ou.name, 'Branch') AS unit,
                    COUNT(DISTINCT a.employee_id) AS count
                FROM hr_attendance a
                JOIN hr_employee e ON a.employee_id = e.id
                JOIN operating_unit ou ON e.default_operating_unit_id = ou.id
                WHERE a.check_in >= %s AND a.check_in <= %s
                  AND a.employee_id = ANY(%s)
                GROUP BY unit
                ORDER BY 2 DESC
            """, (start_utc, end_utc, scoped_emp_ids))
            rows = cr.fetchall()
            return [{'unit': unit, 'count': count} for unit, count in rows] if rows else [{'unit': 'Branches', 'count': 0}]

        # 4. Filtered to Head Office: Breakdown by HO Directorates / Departments
        if office_id == 'ho' or role_type == 'director':
            cr.execute("""
                SELECT
                    COALESCE(ou.name, 'Head Office Unit') AS unit,
                    COUNT(DISTINCT a.employee_id) AS count
                FROM hr_attendance a
                JOIN hr_employee e ON a.employee_id = e.id
                JOIN operating_unit ou ON e.default_operating_unit_id = ou.id
                WHERE a.check_in >= %s AND a.check_in <= %s
                  AND a.employee_id = ANY(%s)
                  AND ou.work_unit_type = 'head_office'
                GROUP BY unit
                ORDER BY 2 DESC
            """, (start_utc, end_utc, scoped_emp_ids))
            rows = cr.fetchall()
            return [{'unit': unit, 'count': count} for unit, count in rows] if rows else [{'unit': 'Directorates', 'count': 0}]

        # 5. Bank-Level Macro View (When 'All Offices' is selected):
        # Cleanly divide into '🏛️ Head Office' vs each District Office!
        cr.execute("""
            SELECT
                CASE
                    WHEN ou.work_unit_type = 'head_office' THEN '🏛️ Head Office'
                    WHEN ou.work_unit_type IN ('district_office', 'regional_office') THEN ou.name
                    WHEN ou.work_unit_type = 'branch' AND pou.id IS NOT NULL THEN pou.name
                    WHEN ou.work_unit_type = 'branch' THEN ou.name
                    ELSE 'Other Operating Units'
                END AS unit,
                COUNT(DISTINCT a.employee_id) AS count
            FROM hr_attendance a
            JOIN hr_employee e ON a.employee_id = e.id
            JOIN operating_unit ou ON e.default_operating_unit_id = ou.id
            LEFT JOIN operating_unit pou ON ou.parent_unit = pou.id
            WHERE a.check_in >= %s AND a.check_in <= %s
              AND a.employee_id = ANY(%s)
            GROUP BY 1
            ORDER BY 2 DESC
        """, (start_utc, end_utc, scoped_emp_ids))
        rows = cr.fetchall()
        return [{'unit': unit, 'count': count} for unit, count in rows] if rows else [{'unit': 'Offices', 'count': 0}]

    # ------------------------------------------------------------------
    # Drill-Down RPC Method
    # ------------------------------------------------------------------
    @api.model
    def get_dashboard_drilldown(
        self,
        metric_type='total',
        filter_type='today',
        specific_date=None,
        office_id=None,
        ou_id=None,
        division_emp_id=None,
        dept_or_dist_id=None,
        **kwargs
    ):
        """Returns detailed employee list for interactive modal drill-down."""
        user = self.env.user
        employee = user.employee_id or self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        access_info = self._resolve_user_access_level(user, employee)
        if not access_info.get('has_corporate_access'):
            return {'records': [], 'count': 0, 'title': 'Access Restricted'}

        today = fields.Date.context_today(self)
        target_date = self._resolve_target_date(filter_type, specific_date, today)

        user_tz_name = user.tz or 'Africa/Addis_Ababa'
        try:
            local_tz = pytz.timezone(user_tz_name)
        except Exception:
            local_tz = pytz.timezone('Africa/Addis_Ababa')

        start_local = local_tz.localize(datetime.datetime.combine(target_date, datetime.time.min))
        end_local = local_tz.localize(datetime.datetime.combine(target_date, datetime.time.max))
        start_utc = start_local.astimezone(pytz.utc).replace(tzinfo=None)
        end_utc = end_local.astimezone(pytz.utc).replace(tzinfo=None)

        effective_office = office_id or dept_or_dist_id
        scoped_emp_ids = self._get_scoped_employee_ids(
            access_info, office_id=effective_office, ou_id=ou_id, division_emp_id=division_emp_id
        )
        if not scoped_emp_ids:
            return {'records': [], 'count': 0, 'title': 'No Staff in Scope'}

        cr = self.env.cr
        records = []

        if metric_type == 'pending':
            cr.execute("""
                SELECT
                    p.id,
                    e.id as emp_id,
                    COALESCE(NULLIF(e.employee_identification, ''), NULLIF(e.identification_id, ''), e.id::text) AS emp_ident,
                    e.name AS emp_name,
                    COALESCE(j.name->>'en_US', j.name::text, '') AS job_title,
                    ou.name AS work_unit,
                    to_char(p.date, 'Mon DD, YYYY') AS punch_in,
                    p.time_range AS punch_out,
                    COALESCE(p.approval_reason, 'No reason specified') AS detail_text,
                    CASE 
                        WHEN p.exception_type = 'predefined_late' THEN 'Pending Late Request'
                        ELSE 'Pending Early Departure'
                    END AS status_label,
                    'amber' AS status_color
                FROM attendance_preapproval p
                JOIN hr_employee e ON p.employee_id = e.id
                LEFT JOIN hr_job j ON e.job_position = j.id
                LEFT JOIN operating_unit ou ON e.default_operating_unit_id = ou.id
                WHERE p.state = 'requested'
                  AND p.employee_id = ANY(%s)
                ORDER BY p.date ASC, p.id DESC
            """, (scoped_emp_ids,))
            for r in cr.dictfetchall():
                records.append({
                    'id': r['id'],
                    'emp_id': r['emp_id'],
                    'name': r['emp_name'],
                    'employee_identification': r['emp_ident'],
                    'job_title': r['job_title'],
                    'work_unit': r['work_unit'],
                    'punch_in': r['punch_in'],
                    'punch_out': r['punch_out'],
                    'detail_text': r['detail_text'],
                    'status_label': r['status_label'],
                    'status_color': r['status_color'],
                })
            return {'records': records, 'count': len(records), 'title': 'Pending Preapproval Requests'}

        elif metric_type == 'absent':
            cr.execute("""
                SELECT
                    e.id as emp_id,
                    COALESCE(NULLIF(e.employee_identification, ''), NULLIF(e.identification_id, ''), e.id::text) AS emp_ident,
                    e.name AS emp_name,
                    COALESCE(j.name->>'en_US', j.name::text, '') AS job_title,
                    ou.name AS work_unit
                FROM hr_employee e
                LEFT JOIN hr_job j ON e.job_position = j.id
                LEFT JOIN operating_unit ou ON e.default_operating_unit_id = ou.id
                WHERE e.id = ANY(%s) AND e.active = true
                  AND e.id NOT IN (
                      SELECT employee_id FROM hr_attendance WHERE check_in >= %s AND check_in <= %s
                  )
                  AND e.id NOT IN (
                      SELECT employee_id FROM hr_leave 
                      WHERE state = 'validate'
                        AND COALESCE(request_date_from, (date_from AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Addis_Ababa')::date) <= %s
                        AND COALESCE(request_date_to, (date_to AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Addis_Ababa')::date) >= %s
                  )
                ORDER BY e.name ASC
            """, (scoped_emp_ids, start_utc, end_utc, target_date, target_date))
            for r in cr.dictfetchall():
                records.append({
                    'id': r['emp_id'],
                    'emp_id': r['emp_id'],
                    'name': r['emp_name'],
                    'employee_identification': r['emp_ident'],
                    'job_title': r['job_title'],
                    'work_unit': r['work_unit'],
                    'punch_in': 'No Punch Recorded',
                    'punch_out': '—',
                    'detail_text': 'Scheduled shift with missing check-in',
                    'status_label': 'Absent',
                    'status_color': 'red',
                })
            return {'records': records, 'count': len(records), 'title': 'Absent / Unregistered Staff'}

        elif metric_type == 'leave':
            cr.execute("""
                SELECT
                    l.id,
                    e.id as emp_id,
                    COALESCE(NULLIF(e.employee_identification, ''), NULLIF(e.identification_id, ''), e.id::text) AS emp_ident,
                    e.name AS emp_name,
                    COALESCE(j.name->>'en_US', j.name::text, '') AS job_title,
                    ou.name AS work_unit,
                    to_char(COALESCE(l.request_date_from, l.date_from::date), 'Mon DD') || ' - ' || to_char(COALESCE(l.request_date_to, l.date_to::date), 'Mon DD') AS punch_in,
                    COALESCE(lt.name->>'en_US', lt.name::text, 'Leave') AS detail_text
                FROM hr_leave l
                JOIN hr_employee e ON l.employee_id = e.id
                LEFT JOIN hr_leave_type lt ON l.holiday_status_id = lt.id
                LEFT JOIN hr_job j ON e.job_position = j.id
                LEFT JOIN operating_unit ou ON e.default_operating_unit_id = ou.id
                WHERE l.state = 'validate'
                  AND COALESCE(l.request_date_from, (l.date_from AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Addis_Ababa')::date) <= %s
                  AND COALESCE(l.request_date_to, (l.date_to AT TIME ZONE 'UTC' AT TIME ZONE 'Africa/Addis_Ababa')::date) >= %s
                  AND l.employee_id = ANY(%s)
                ORDER BY e.name ASC
            """, (target_date, target_date, scoped_emp_ids))
            for r in cr.dictfetchall():
                records.append({
                    'id': r['id'],
                    'emp_id': r['emp_id'],
                    'name': r['emp_name'],
                    'employee_identification': r['emp_ident'],
                    'job_title': r['job_title'],
                    'work_unit': r['work_unit'],
                    'punch_in': r['punch_in'],
                    'punch_out': 'Approved Leave',
                    'detail_text': r['detail_text'],
                    'status_label': 'On Leave',
                    'status_color': 'purple',
                })
            return {'records': records, 'count': len(records), 'title': 'Employees On Approved Leave'}

        # Attendances query
        where_cond = "a.check_in >= %s AND a.check_in <= %s AND a.employee_id = ANY(%s)"
        params = [start_utc, end_utc, scoped_emp_ids]

        if metric_type == 'present_normal':
            where_cond += """
                AND a.check_in_status = 'Normal'
                AND (a.pre_defined_lateness IS NULL OR a.pre_defined_lateness = 0)
                AND (a.pre_approved_early_checkout IS NULL OR a.pre_approved_early_checkout = 0)
                AND (a.out_mode != 'predefined' OR a.out_mode IS NULL)
                AND (a.in_mode != 'predefined' OR a.in_mode IS NULL)
                AND a.pre_defined_attendance_id IS NULL
            """
        elif metric_type == 'preapproved':
            where_cond += """
                AND (
                    a.check_in_status = 'Pre-Defined Lateness'
                    OR (a.pre_defined_lateness IS NOT NULL AND a.pre_defined_lateness > 0)
                    OR a.check_out_status = 'Pre-Approved Early Checkout'
                    OR (a.pre_approved_early_checkout IS NOT NULL AND a.pre_approved_early_checkout > 0)
                    OR a.in_mode = 'predefined'
                    OR a.out_mode = 'predefined'
                    OR a.pre_defined_attendance_id IS NOT NULL
                )
            """
        elif metric_type == 'late_unexcused':
            where_cond += """
                AND a.check_in_status IN ('Late', 'Very Late')
                AND (a.pre_defined_lateness IS NULL OR a.pre_defined_lateness = 0)
                AND a.check_in_status != 'Pre-Defined Lateness'
                AND (a.pre_defined_attendance_id IS NULL OR a.pre_approved_early_checkout IS NULL OR a.pre_approved_early_checkout = 0)
            """
        elif metric_type == 'acknowledged':
            where_cond += """
                AND (
                    a.is_acknowledged = TRUE
                    OR a.in_mode = 'acknowledged'
                    OR a.out_mode = 'acknowledged'
                    OR (a.acknowledged_late IS NOT NULL AND a.acknowledged_late > 0)
                    OR (a.acknowledged_exit IS NOT NULL AND a.acknowledged_exit > 0)
                    OR a.check_in_status ILIKE '%%Acknowledged%%'
                    OR a.check_out_status ILIKE '%%Acknowledged%%'
                )
            """
        elif metric_type == 'force':
            where_cond += "AND (a.check_out_status = 'Force Checkout' OR a.is_force_checkout = TRUE)"

        sql = f"""
            SELECT
                a.id,
                e.id as emp_id,
                COALESCE(NULLIF(e.employee_identification, ''), NULLIF(e.identification_id, ''), e.id::text) AS emp_ident,
                e.name AS emp_name,
                COALESCE(j.name->>'en_US', j.name::text, '') AS job_title,
                ou.name AS work_unit,
                to_char(a.check_in AT TIME ZONE 'Africa/Addis_Ababa', 'HH12:MI AM') AS in_time,
                CASE 
                    WHEN a.check_out IS NOT NULL THEN to_char(a.check_out AT TIME ZONE 'Africa/Addis_Ababa', 'HH12:MI AM')
                    ELSE 'Ongoing'
                END AS out_time,
                a.check_in_status,
                a.check_out_status,
                a.is_acknowledged,
                a.pre_defined_lateness,
                a.pre_approved_early_checkout,
                a.late_time_hour,
                a.early_exit_hour,
                a.in_mode,
                a.out_mode,
                a.pre_defined_attendance_id
            FROM hr_attendance a
            JOIN hr_employee e ON a.employee_id = e.id
            LEFT JOIN hr_job j ON e.job_position = j.id
            LEFT JOIN operating_unit ou ON e.default_operating_unit_id = ou.id
            WHERE {where_cond}
            ORDER BY a.check_in DESC
        """
        cr.execute(sql, tuple(params))
        for r in cr.dictfetchall():
            status_label = r['check_in_status'] or 'Present'
            status_color = 'slate'
            detail_text = ''

            is_pre_exit = (r['pre_approved_early_checkout'] or 0) > 0 or r['out_mode'] == 'predefined'
            is_pre_late = (r['pre_defined_lateness'] or 0) > 0 or r['in_mode'] == 'predefined' or r['check_in_status'] == 'Pre-Defined Lateness'

            is_ack = r.get('is_acknowledged') or r.get('in_mode') == 'acknowledged' or r.get('out_mode') == 'acknowledged'

            if is_ack:
                status_label = 'Acknowledged Attendance'
                status_color = 'emerald'
                detail_text = f"Formally regularized ({r['check_in_status'] or 'Approved'})"
            elif is_pre_exit and is_pre_late:
                status_label = 'Pre-Approved (Late & Exit)'
                status_color = 'sky'
                detail_text = f"Preapproved late + {int(round(r['pre_approved_early_checkout'] * 60))}m early exit"
            elif is_pre_exit:
                status_label = 'Pre-Approved Early Exit'
                status_color = 'sky'
                detail_text = f"Approved departure {int(round(r['pre_approved_early_checkout'] * 60))}m early"
            elif is_pre_late:
                status_label = 'Pre-Approved Lateness'
                status_color = 'sky'
                detail_text = f"Approved arrival {int(round((r['pre_defined_lateness'] or 0) * 60))}m late"
            elif r['check_in_status'] in ('Late', 'Very Late'):
                status_label = r['check_in_status']
                status_color = 'amber'
                delay_mins = int(round((r['late_time_hour'] or 0) * 60))
                detail_text = f"{delay_mins} mins unexcused arrival delay" if delay_mins > 0 else 'Late Arrival'
            elif r['check_in_status'] == 'Normal':
                status_label = 'Normal (On-Time)'
                status_color = 'emerald'
                detail_text = 'Punctual check-in within grace period'

            if r['check_out_status'] == 'Force Checkout':
                detail_text += ' • Force Closed'

            records.append({
                'id': r['id'],
                'emp_id': r['emp_id'],
                'name': r['emp_name'],
                'employee_identification': r['emp_ident'],
                'job_title': r['job_title'],
                'work_unit': r['work_unit'],
                'punch_in': r['in_time'],
                'punch_out': r['out_time'],
                'detail_text': detail_text,
                'status_label': status_label,
                'status_color': status_color,
            })

        titles_map = {
            'total': 'Total Workforce Attendance Records',
            'present_normal': 'On-Time Present Staff',
            'preapproved': 'Pre-Approved Attendance Exceptions',
            'late_unexcused': 'Unexcused Late Check-Ins',
            'acknowledged': 'Acknowledged Attendance Cases',
            'force': 'Force Checkout Records',
        }
        return {'records': records, 'count': len(records), 'title': titles_map.get(metric_type, 'Employee Attendance Records')}

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

        # Query approved leaves (hr.leave) in range
        range_leaves = self.env['hr.leave'].sudo().search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'validate'),
            ('date_from', '<=', datetime.datetime.combine(e_d, datetime.time.max)),
            ('date_to', '>=', datetime.datetime.combine(s_d, datetime.time.min)),
        ])
        period_leave_days = sum(l.number_of_days or 1.0 for l in range_leaves)
        period_leave_hours = round(period_leave_days * 8.0, 2)
        period_leave_count = len(range_leaves)

        now_dt = fields.Datetime.context_timestamp(employee, fields.Datetime.now())
        current_float = now_dt.hour + (now_dt.minute / 60.0)

        # Helper to compute live or stored worked hours for any attendance
        def _get_effective_att_worked_hours(att):
            if att.check_out and (att.worked_hours or 0.0) > 0:
                return att.worked_hours
            if not att.check_in:
                return 0.0
            dt_in_loc = pytz.utc.localize(att.check_in).astimezone(local_tz) if not att.check_in.tzinfo else att.check_in.astimezone(local_tz)
            dt_out_loc = (pytz.utc.localize(att.check_out).astimezone(local_tz) if not att.check_out.tzinfo else att.check_out.astimezone(local_tz)) if att.check_out else now_dt
            
            w_date = (dt_in_loc - datetime.timedelta(days=1)).date() if dt_in_loc.hour < 4 else dt_in_loc.date()
            sh = employee._get_employee_shift_info(target_date=w_date) if hasattr(employee, '_get_employee_shift_info') else {}
            s_s = att.shift_start_float or sh.get('start_time', 8.0)
            s_e = att.shift_end_float or sh.get('end_time', 17.0)
            has_l = sh.get('has_lunch_break', False)
            l_out = sh.get('lunch_out_time', 12.0) if has_l else 12.0
            l_dur = sh.get('lunch_duration', 1.0) if has_l else 0.0
            l_end = l_out + l_dur

            start_secs = int(round(float(s_s) * 3600.0))
            end_secs = int(round(float(s_e) * 3600.0))
            s_start_dt = dt_in_loc.replace(hour=(start_secs % 86400) // 3600, minute=((start_secs % 3600) // 60), second=start_secs % 60, microsecond=0)
            s_end_dt = dt_in_loc.replace(hour=(end_secs % 86400) // 3600, minute=((end_secs % 3600) // 60), second=end_secs % 60, microsecond=0)
            if s_e < s_s:
                s_end_dt += datetime.timedelta(days=1)

            eff_in = max(dt_in_loc, s_start_dt)
            eff_out = min(dt_out_loc, s_end_dt)
            if eff_out > eff_in:
                raw_h = (eff_out - eff_in).total_seconds() / 3600.0
                in_flt = dt_in_loc.hour + (dt_in_loc.minute / 60.0)
                out_flt = dt_out_loc.hour + (dt_out_loc.minute / 60.0)
                ded_l = l_dur if (has_l and in_flt < l_out and out_flt > l_end) else 0.0
                return max(0.0, round(raw_h - ded_l, 2))
            return 0.0

        # Compute dynamic expected target hours across the period
        def _get_day_expected_hours(target_d):
            d_shift = employee._get_employee_shift_info(target_date=target_d) if hasattr(employee, '_get_employee_shift_info') else None
            if not d_shift or d_shift.get('is_day_off'):
                return 0.0
            s_s = d_shift.get('start_time', 8.0)
            s_e = d_shift.get('end_time', 17.0)
            has_l = d_shift.get('has_lunch_break', False)
            l_dur = d_shift.get('lunch_duration', 1.0) if has_l else 0.0
            s_e_adj = (s_e + 24.0) if s_e < s_s else s_e
            return max(0.0, round((s_e_adj - s_s) - l_dur, 2))

        calc_cur = s_d
        total_sched_expected = 0.0
        while calc_cur <= e_d:
            total_sched_expected += _get_day_expected_hours(calc_cur)
            calc_cur += datetime.timedelta(days=1)

        period_days = (e_d - s_d).days + 1
        target_hours = round(total_sched_expected, 1) if total_sched_expected > 0 else (160.0 if (date_range == 'this_month' or period_days > 14) else round(period_days * 8.0, 1))

        # Card 1: Total Worked Hours & Target Hours
        period_worked_hours = round(sum(_get_effective_att_worked_hours(att) for att in range_atts), 2)
        period_predefined_hours = round(sum((att.pre_defined_lateness or 0.0) + (getattr(att, 'pre_approved_early_checkout', 0.0) or 0.0) for att in range_atts), 2)
        period_compensable_hours = round(period_worked_hours + period_leave_hours + period_predefined_hours, 2)
        worked_hours_pct = min(100.0, round((period_compensable_hours / max(1.0, target_hours)) * 100, 1))
        avg_daily_hours = round(period_worked_hours / max(1, period_days), 1)

        # Card 2: Cumulative Late Hours & Punctuality Rating
        period_late_hours_float = sum(att.late_time_hour or 0.0 for att in range_atts)
        period_late_count = sum(1 for att in range_atts if att.check_in_status in ('Late', 'Very Late', 'Acknowledged Lateness'))
        period_early_exit_count = sum(1 for att in range_atts if (att.early_exit_hour or 0.0) > 0.02 or att.check_out_status in ('Early Exit', 'Acknowledged Early Exit', 'early_exit'))
        period_early_exit_hours = round(sum(att.early_exit_hour or 0.0 for att in range_atts), 2)
        period_normal_count = sum(1 for att in range_atts if (att.check_in_status in ('Normal', 'On-Time', 'On Time', 'Acknowledged Check-In') or not att.check_in_status))
        
        # Session Punctuality: Requires On-Time Check-In AND On-Time Check-Out (no early exit or force checkout)
        punctual_sessions = sum(1 for att in range_atts if (att.check_in_status in ('Normal', 'On-Time', 'On Time', 'Acknowledged Check-In') or not att.check_in_status) and (att.early_exit_hour or 0.0) <= 0.02 and att.check_out_status not in ('Early Exit', 'Acknowledged Early Exit', 'Force Checkout', 'force_checkout'))
        total_sessions = len(range_atts)
        punctuality_score = round((punctual_sessions / max(1, total_sessions)) * 100, 1) if total_sessions > 0 else 0.0

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

        def _att_dt_float(dt_val):
            if not dt_val:
                return 0.0
            ts = pytz.utc.localize(dt_val).astimezone(local_tz) if dt_val.tzinfo is None else dt_val.astimezone(local_tz)
            return ts.hour + ts.minute / 60.0 + ts.second / 3600.0

        # -------------------------------------------------------------
        # OPTION A: PURE SESSION-LEVEL BREAKDOWN
        # Respects:
        # 1. Lunch break configuration (enable_lunch_break)
        # 2. Shift has_lunch_break flag
        # 3. Saturday full day for branches vs Saturday half day for Head Office & District Offices
        # 4. Sunday & Public Holidays as Days Off
        # -------------------------------------------------------------
        session_on_time_count = 0
        session_late_count = 0
        session_leave_count = 0
        session_absent_count = 0

        cur_d = s_d
        while cur_d <= eval_end_d:
            d_shift = employee._get_employee_shift_info(target_date=cur_d) if hasattr(employee, '_get_employee_shift_info') else None
            is_day_off = bool(d_shift.get('is_day_off')) if d_shift else (cur_d.weekday() == 6)
            on_leave = bool(d_shift.get('is_on_leave')) if d_shift else False
            is_half_day_leave = bool(d_shift.get('is_half_day_leave')) if d_shift else False
            leave_period = d_shift.get('half_day_period') if d_shift else None

            # Fallback leave check if not already populated on d_shift
            if not on_leave and 'hr.leave' in self.env and hasattr(employee, '_is_leave_matching_date'):
                matching_leaves = self.env['hr.leave'].sudo().search([
                    ('employee_id', '=', employee.id),
                    ('state', '=', 'validate'),
                    ('date_from', '<=', datetime.datetime.combine(cur_d, datetime.time.max)),
                    ('date_to', '>=', datetime.datetime.combine(cur_d, datetime.time.min))
                ]).filtered(lambda l: employee._is_leave_matching_date(l, cur_d))
                if matching_leaves:
                    l_rec = matching_leaves[0]
                    on_leave = True
                    is_half_day_leave = bool(getattr(l_rec, 'request_unit_half', False) or getattr(l_rec, 'half_day', False) or (getattr(l_rec, 'number_of_days', 1.0) == 0.5))
                    leave_period = getattr(l_rec, 'single_half_day_period', False) or getattr(l_rec, 'request_date_from_period', 'am')

            if not is_day_off:
                has_lunch = bool(d_shift.get('has_lunch_break', False)) if d_shift else False
                m_start = d_shift.get('start_time', 8.0) if d_shift else 8.0
                m_end = d_shift.get('lunch_out_time', 12.0) if d_shift else 12.0
                a_end = d_shift.get('end_time', 17.0) if d_shift else 17.0
                d_atts = [a for a in range_atts if _get_att_work_date(a) == cur_d]

                if has_lunch:
                    # TWO SESSIONS: Morning Session & Afternoon Session
                    # 1. Morning Session
                    is_m_elapsed = (cur_d < today) or (cur_d == today and (current_float >= m_end or any(a.check_in for a in d_atts)))
                    if is_m_elapsed:
                        if on_leave and (not is_half_day_leave or leave_period == 'am'):
                            session_leave_count += 1
                        else:
                            m_atts = [a for a in d_atts if a.shift_end_float <= (m_end + 0.1) or (a.check_in and _att_dt_float(a.check_in) < (m_end - 0.01))]
                            if m_atts:
                                if m_atts[0].check_in_status in ('Late', 'Very Late', 'Acknowledged Lateness'):
                                    session_late_count += 1
                                else:
                                    session_on_time_count += 1
                            else:
                                session_absent_count += 1

                    # 2. Afternoon Session
                    is_a_elapsed = (cur_d < today) or (cur_d == today and (current_float >= a_end or any((a.shift_start_float and a.shift_start_float >= (m_end - 0.1)) or (a.check_in and _att_dt_float(a.check_in) >= (m_end - 0.01)) for a in d_atts)))
                    if is_a_elapsed:
                        if on_leave and (not is_half_day_leave or leave_period == 'pm'):
                            session_leave_count += 1
                        else:
                            a_atts = [a for a in d_atts if (a.shift_start_float and a.shift_start_float >= (m_end - 0.1)) or (a.check_in and _att_dt_float(a.check_in) >= (m_end - 0.01))]
                            if a_atts:
                                if a_atts[0].check_in_status in ('Late', 'Very Late', 'Acknowledged Lateness'):
                                    session_late_count += 1
                                else:
                                    session_on_time_count += 1
                            else:
                                session_absent_count += 1
                else:
                    # ONE SESSION: Continuous Single Shift / Saturday Half-Day for HO/Districts / Lunch disabled
                    is_s_elapsed = (cur_d < today) or (cur_d == today and (current_float >= a_end or any(a.check_in for a in d_atts)))
                    if is_s_elapsed:
                        if on_leave:
                            session_leave_count += 1
                        else:
                            if d_atts:
                                if d_atts[0].check_in_status in ('Late', 'Very Late', 'Acknowledged Lateness'):
                                    session_late_count += 1
                                else:
                                    session_on_time_count += 1
                            else:
                                session_absent_count += 1

            cur_d += datetime.timedelta(days=1)

        # Pure Session-Level Total and Rates (Option A)
        total_p_samples = session_on_time_count + session_late_count + session_leave_count + session_absent_count
        p_pct_normal = round((session_on_time_count / float(total_p_samples)) * 100, 1) if total_p_samples > 0 else 0.0
        p_pct_late = round((session_late_count / float(total_p_samples)) * 100, 1) if total_p_samples > 0 else 0.0
        p_pct_leave = round((session_leave_count / float(total_p_samples)) * 100, 1) if total_p_samples > 0 else 0.0
        p_pct_absent = round((session_absent_count / float(total_p_samples)) * 100, 1) if total_p_samples > 0 else 0.0

        # Donut Center Attendance Rate (Attended sessions vs Total Elapsed Sessions)
        attended_sessions = session_on_time_count + session_late_count
        attendance_rate = min(100.0, max(0.0, round((attended_sessions / float(total_p_samples)) * 100, 1))) if total_p_samples > 0 else 0.0

        # Card 3 Offenses Absence count: aligns with missed sessions
        absent_count = session_absent_count

        # Card 4: Approvals
        acknowledged_count = sum(1 for att in range_atts if (getattr(att, 'is_acknowledged', False) or (getattr(att, 'acknowledged_late', 0.0) or 0.0) > 0 or (getattr(att, 'acknowledged_exit', 0.0) or 0.0) > 0))
        predefined_count = 0
        if 'attendance.preapproval' in self.env:
            predefined_count = self.env['attendance.preapproval'].sudo().search_count([
                ('employee_id', '=', employee.id),
                ('date', '>=', s_d),
                ('date', '<=', e_d),
                ('state', '=', 'approved'),
                ('is_utilized', '=', True),
            ])

        # Personal Status Donut SVG
        c = 251.32
        p_p_dash = round((p_pct_normal / 100.0) * c, 2)
        p_l_dash = round((p_pct_late / 100.0) * c, 2)
        p_lv_dash = round((p_pct_leave / 100.0) * c, 2)
        p_a_dash = round((p_pct_absent / 100.0) * c, 2)

        p_p_off = 0.0
        p_l_off = round(-(p_p_dash), 2)
        p_lv_off = round(-(p_p_dash + p_l_dash), 2)
        p_a_off = round(-(p_p_dash + p_l_dash + p_lv_dash), 2)
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
            w_h = round(sum(_get_effective_att_worked_hours(a) for a in b_atts), 2)
            l_h = round(sum(a.late_time_hour or 0.0 for a in b_atts), 2)
            b_days = (block['end_date'] - block['start_date']).days + 1
            
            # Sum expected hours for past/elapsed working days in this block
            expected_past_hours = 0.0
            for i in range(b_days):
                b_date = block['start_date'] + datetime.timedelta(days=i)
                if b_date < today:
                    expected_past_hours += _get_day_expected_hours(b_date)
                elif b_date == today:
                    t_shift = employee._get_employee_shift_info(target_date=today) if hasattr(employee, '_get_employee_shift_info') else {}
                    t_end = t_shift.get('end_time', 17.0) if t_shift else 17.0
                    if current_float >= t_end:
                        expected_past_hours += _get_day_expected_hours(today)

            b_leaves = [l for l in range_leaves if l.date_from and l.date_to and l.date_from.date() <= block['end_date'] and l.date_to.date() >= block['start_date']]
            b_leave_h = round(sum((l.number_of_days or 1.0) * 8.0 for l in b_leaves), 2)
            comp_h = w_h + b_leave_h + round(sum((a.pre_defined_lateness or 0.0) + (getattr(a, 'pre_approved_early_checkout', 0.0) or 0.0) for a in b_atts), 2)
            a_h = max(0.0, round(expected_past_hours - comp_h, 2)) if expected_past_hours > 0 else 0.0
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
            
            in_st = att.check_in_status or 'Normal'
            out_st = att.check_out_status or ('Active Session' if not att.check_out else 'Normal')
            if (att.early_exit_hour or 0.0) > 0.02 and out_st in ('Normal', False, ''):
                out_st = 'Early Exit'
            
            status_parts = []
            if in_st not in ('Normal', 'On-Time', 'On Time'):
                l_str = f" ({int(att.late_time_hour):02d}:{int(round((att.late_time_hour - int(att.late_time_hour))*60)):02d})" if att.late_time_hour else ""
                status_parts.append(f"{in_st}{l_str}")
            if out_st not in ('Normal', False, ''):
                e_str = f" ({int(att.early_exit_hour):02d}:{int(round((att.early_exit_hour - int(att.early_exit_hour))*60)):02d})" if att.early_exit_hour else ""
                status_parts.append(f"{out_st}{e_str}")
            
            full_status = " / ".join(status_parts) if status_parts else "On-Time (Normal)"

            logs.append({
                'id': att.id,
                'date': dt_in.strftime('%Y-%m-%d') if dt_in else '',
                'check_in': dt_in.strftime('%I:%M %p') if dt_in else '-',
                'check_out': dt_out.strftime('%I:%M %p') if dt_out else ('Active Session' if not att.check_out else '-'),
                'worked_hours': round(_get_effective_att_worked_hours(att), 2),
                'check_in_status': full_status,
            })

        return {
            'has_employee': True,
            'employee_name': employee.name,
            'job_title': employee.job_id.name if employee.job_id else 'Staff',
            'department': employee.department_id.name if employee.department_id else '',
            'period_worked_hours': period_worked_hours,
            'period_compensable_hours': period_compensable_hours,
            'period_leave_hours': period_leave_hours,
            'target_hours': target_hours,
            'worked_hours_pct': worked_hours_pct,
            'avg_daily_hours': avg_daily_hours,
            'punctuality_score': punctuality_score,
            'attendance_rate': attendance_rate,
            'compliance_label': '',
            'compliance_badge': '',
            'late_hours_formatted': late_hours_formatted,
            'late_count': session_late_count,
            'early_exit_count': period_early_exit_count,
            'early_exit_hours': period_early_exit_hours,
            'normal_count': session_on_time_count,
            'leave_count': session_leave_count,
            'absent_count': session_absent_count,
            'total_sessions_count': total_p_samples,
            'offenses': {
                'force_checkout': force_checkout_count,
                'absent': session_absent_count,
                'late': session_late_count,
                'early_exit': period_early_exit_count,
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
    def _check_payroll_attendance_access(self, employee_id=None, ou_id=None):
        """Enforce strict access control: only system administrators, HR managers/officers,
        payroll managers, or the employee's direct line of management can access absence data.
        """
        user = self.env.user
        if user.id == 2 or user.has_group('base.group_system') or \
           user.has_group('hr_attendance.group_hr_attendance_manager') or \
           user.has_group('hr_attendance.group_hr_attendance_officer'):
            return True
        if employee_id and user.employee_id and user.employee_id.id == employee_id:
            return True
        if employee_id and user.employee_id:
            sub_ids = self._get_hierarchy_employee_ids(user.employee_id.id)
            if employee_id in sub_ids:
                return True
        if ou_id and user.employee_id:
            emp_ou = user.employee_id.default_operating_unit_id
            if emp_ou and emp_ou.id == int(ou_id):
                sub_ids = self._get_hierarchy_employee_ids(user.employee_id.id)
                if len(sub_ids) > 1:
                    return True
        raise AccessError(_("Access Denied: You do not have permission to view attendance or absence records for this employee / unit."))

    @api.model
    def _get_employee_absent_dates(self, employee_id, start_date, end_date):
        """Compute the list of unexcused absent dates for a specific employee over a date range.
        Excludes approved leaves, public holidays, and rostered/weekend rest days.
        """
        self._check_payroll_attendance_access(employee_id=employee_id)
        s_d = fields.Date.to_date(start_date)
        e_d = fields.Date.to_date(end_date)
        if not (employee_id and s_d and e_d and s_d <= e_d):
            return []

        emp = self.env['hr.employee'].sudo().browse(employee_id)
        if not emp.exists():
            return []

        # 1. Get all check-in dates for employee in range (local Addis Ababa date)
        s_dt = datetime.datetime.combine(s_d, datetime.time.min)
        e_dt = datetime.datetime.combine(e_d, datetime.time.max)
        atts = self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee_id),
            ('check_in', '>=', s_dt),
            ('check_in', '<=', e_dt),
        ])
        tz = pytz.timezone('Africa/Addis_Ababa')
        checked_dates = set()
        for a in atts:
            if a.check_in:
                local_checkin = pytz.utc.localize(a.check_in).astimezone(tz)
                checked_dates.add(local_checkin.date())

        # 2. Get approved leave dates
        leaves = self.env['hr.leave'].sudo().search([
            ('employee_id', '=', employee_id),
            ('state', '=', 'validate'),
            ('date_from', '<=', e_dt),
            ('date_to', '>=', s_dt),
        ])
        leave_dates = set()
        for l in leaves:
            l_start = getattr(l, 'leave_start_date', False) or getattr(l, 'request_date_from', False) or (l.date_from.date() if l.date_from else s_d)
            l_end = getattr(l, 'leave_end_date', False) or getattr(l, 'request_date_to', False) or (l.date_to.date() if l.date_to else e_d)
            cur_l = max(s_d, l_start)
            end_l = min(e_d, l_end)
            while cur_l <= end_l:
                leave_dates.add(cur_l)
                cur_l += datetime.timedelta(days=1)

        # 3. Get public bank holidays
        calendar = emp.resource_calendar_id or emp.company_id.resource_calendar_id
        holiday_dates = set()
        pub_leaves = self.env['resource.calendar.leaves'].sudo().search([
            ('date_from', '<=', e_dt),
            ('date_to', '>=', s_dt),
            '|', ('calendar_id', '=', False), ('calendar_id', '=', calendar.id if calendar else False)
        ])
        for pl in pub_leaves:
            cur_p = max(s_d, pl.date_from.date())
            end_p = min(e_d, pl.date_to.date())
            while cur_p <= end_p:
                holiday_dates.add(cur_p)
                cur_p += datetime.timedelta(days=1)

        # 4. Working schedule determination
        calendar_weekdays = set()
        if calendar and calendar.attendance_ids:
            try:
                calendar_weekdays = set(int(a.dayofweek) for a in calendar.attendance_ids)
            except Exception:
                calendar_weekdays = set()

        ou_type = emp.default_operating_unit_id.work_unit_type if emp.default_operating_unit_id else ''
        is_ho = (ou_type == 'head_office')

        absent_dates = []
        cur = s_d
        while cur <= e_d:
            w_day = cur.weekday()
            # If calendar defines specific working weekdays, respect it directly
            if calendar_weekdays:
                if w_day not in calendar_weekdays:
                    cur += datetime.timedelta(days=1)
                    continue
            else:
                # Standard schedule fallback: Sunday always off, Saturday off for Head Office
                if w_day == 6:
                    cur += datetime.timedelta(days=1)
                    continue
                if is_ho and w_day == 5:
                    cur += datetime.timedelta(days=1)
                    continue

            # Public holidays are non-working
            if cur in holiday_dates:
                cur += datetime.timedelta(days=1)
                continue
            # If not checked in and not on approved leave, it is an unexcused absence
            if cur not in checked_dates and cur not in leave_dates:
                absent_dates.append(str(cur))
            cur += datetime.timedelta(days=1)

        return absent_dates

    @api.model
    def _get_operating_unit_absent_employees(self, ou_id, target_date=None):
        """Retrieve the list of absent employees for an Operating Unit on a given date."""
        self._check_payroll_attendance_access(ou_id=ou_id)
        t_d = fields.Date.to_date(target_date) if target_date else fields.Date.context_today(self)
        emp_model = self.env['hr.employee'].sudo()
        scoped_ou_ids = self._get_operating_unit_and_descendant_ids(ou_id)
        employees = emp_model.search([
            ('active', '=', True),
            ('default_operating_unit_id', 'in', scoped_ou_ids)
        ])
        if not employees:
            return []

        emp_ids = employees.ids
        t_s = datetime.datetime.combine(t_d, datetime.time.min)
        t_e = datetime.datetime.combine(t_d, datetime.time.max)

        att_emp_ids = set(self.env['hr.attendance'].sudo().search([
            ('employee_id', 'in', emp_ids),
            ('check_in', '>=', t_s),
            ('check_in', '<=', t_e),
        ]).mapped('employee_id.id'))

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
    def _get_payroll_attendance_summary(self, employee_id, start_date, end_date):
        """Clean data endpoint for Payroll to pull attendance metrics without pushing penalties."""
        self._check_payroll_attendance_access(employee_id=employee_id)
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
        absent_dates = self._get_employee_absent_dates(employee_id, start_date, end_date)

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
