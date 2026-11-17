# -*- coding: utf-8 -*-
from odoo import models, api, fields, _
from datetime import date, timedelta, datetime, time


class DisciplineCaseDashboard(models.Model):
    _inherit = 'discipline.case'

    @api.model
    def get_filter_hierarchy(self):
        """
        Return statutory organizational hierarchy matching Bunna Bank's real structure.
        - Clean professional labels with NO employee count badges (no '(3,140 Staff)', etc.).
        - Bank-wide statutory split:
            1. Head Office: CEO direct directorates + Chief Offices (Executive Wings) and subordinate directorates/divisions.
            2. Regional Districts: Governed under Chief Retail & Branch Banking Officer, 11 District Offices,
               each with District Office Workers (HQ staff) and subordinate branches (linked via parent_unit).
        - Segregated access per role (Admin/CEO, Chief Retail, HO Chiefs, District Directors, Line Coaches, Employees).
        """
        user = self.env.user
        EmpModel = self.env['hr.employee'].sudo()
        OUModel = self.env['operating.unit'].sudo()
        DeptModel = self.env['hr.department'].sudo()

        ceo_user = EmpModel.get_ceo_user()
        cpco_user = EmpModel.get_cpco_user()
        sec_user = EmpModel.get_secretary_user()

        is_ceo = bool((ceo_user and user.id == ceo_user.id) or user.has_group('discipline_management.group_discipline_ceo'))
        is_cpco = bool((cpco_user and user.id == cpco_user.id) or user.has_group('discipline_management.group_discipline_cpco'))
        is_admin = bool(user.has_group('discipline_management.group_discipline_admin') or user._is_superuser())
        is_auditor = bool(user.has_group('discipline_management.group_discipline_auditor'))
        is_director_group = bool(user.has_group('discipline_management.group_discipline_director'))
        is_pomd = bool(user.has_group('discipline_management.group_discipline_pomd') or user.has_group('discipline_management.group_discipline_pomd_director'))

        user_role = EmpModel.get_user_hierarchy_role(user)
        is_global_governance = is_ceo or is_cpco or is_admin or is_auditor or is_pomd

        emp = user.employee_id.sudo() if user.employee_id else False
        all_subs = []
        direct_subs = []
        if emp:
            direct_subs = emp.child_ids.ids
            all_subs = EmpModel.search([('id', 'child_of', emp.id)]).ids

        is_secretary_only = bool(user.has_group('discipline_management.group_discipline_secretary') and not is_global_governance)
        is_employee_only = bool(
            (user_role == 'employee' or is_secretary_only) and
            len(direct_subs) == 0 and
            len(all_subs) <= 1 and
            not is_global_governance
        )
        is_district_dir = bool(emp and emp.job_id and 'district' in (emp.job_id.name or '').lower())
        is_chief_retail = bool(user_role == 'chief' and emp and 'retail' in (emp.job_id.name or '').lower())

        # 1. Build all 11 District Offices with their linked subordinate branches (operating.unit parent_unit)
        dist_ous = OUModel.search([('work_unit_type', '=', 'district_office')], order='name asc')
        district_offices = []
        branches_by_district = {}
        for d in dist_ous:
            d_key = f"dist_{d.id}"
            district_offices.append({
                'id': d_key,
                'name': d.name,  # Clean name: NO staff counts!
                'ou_id': d.id,
            })
            child_branches = OUModel.search([('parent_unit', '=', d.id)], order='name asc')
            branches_by_district[d_key] = [
                {'id': f"branch_{b.id}", 'name': b.name, 'ou_id': b.id}
                for b in child_branches
            ]

        # 2. Build Head Office: Chief Offices (Executive Wings) & Subordinate Directorates
        chief_emps = EmpModel.search([
            '|', ('job_id.name', 'ilike', 'Chief'), ('job_id.name', 'ilike', 'Deputy Chief')
        ], order='name asc')
        chief_offices = []
        directorates_by_chief = {}
        for c in chief_emps:
            if 'Executive' in (c.job_id.name or ''):
                continue
            c_key = f"chief_{c.id}"
            wing_name = c.job_id.name if c.job_id else c.name
            chief_offices.append({
                'id': c_key,
                'name': wing_name,  # Clean name: NO staff counts!
                'emp_id': c.id,
            })
            sub_dirs = EmpModel.search([
                ('parent_id', '=', c.id),
                ('job_id.name', 'ilike', 'Director')
            ], order='name asc')
            directorates_by_chief[c_key] = [
                {
                    'id': f"dir_{sd.id}",
                    'name': sd.job_id.name if sd.job_id else sd.name,
                    'emp_id': sd.id,
                    'ou_id': sd.operating_unit_id.id if sd.operating_unit_id else False,
                }
                for sd in sub_dirs if 'District' not in (sd.job_id.name or '')
            ]

        # 3. Direct CEO Directorates (Statutory Wings reporting directly to CEO)
        ceo_user_rec = EmpModel.get_ceo_user()
        ceo_emp = ceo_user_rec.employee_id if ceo_user_rec and ceo_user_rec.employee_id else EmpModel.search([('job_id.name', 'ilike', 'Chief Executive Officer')], limit=1)
        ceo_dirs = EmpModel.search([
            ('parent_id', '=', ceo_emp.id),
            ('job_id.name', 'ilike', 'Director')
        ], order='name asc') if ceo_emp else []
        direct_ceo_directorates = [
            {
                'id': f"dir_{d.id}",
                'name': d.job_id.name if d.job_id else d.name,
                'emp_id': d.id,
                'ou_id': d.operating_unit_id.id if d.operating_unit_id else False,
            }
            for d in ceo_dirs
        ]

        # 4. Role Segregation and Allowed Levels
        allowed_levels = []
        user_district_branches = []
        user_district_key = ""
        user_district_name = ""

        if is_district_dir and emp:
            # Detect District Director's specific district
            user_dist_ou = emp.operating_unit_id if emp.operating_unit_id and emp.operating_unit_id.work_unit_type == 'district_office' else False
            if not user_dist_ou and emp.department_id:
                user_dist_ou = OUModel.search([('name', '=', emp.department_id.name), ('work_unit_type', '=', 'district_office')], limit=1)
            if not user_dist_ou:
                for d in dist_ous:
                    if d.name.lower() in (emp.job_id.name or '').lower() or (emp.department_id and d.name.lower() in emp.department_id.name.lower()):
                        user_dist_ou = d
                        break

            if user_dist_ou:
                user_district_key = f"dist_{user_dist_ou.id}"
                user_district_name = user_dist_ou.name
                user_district_branches = branches_by_district.get(user_district_key, [])

            allowed_levels = [
                {'id': 'district_all', 'name': _('District-Wide (Office Workers & Branches)')},
                {'id': 'district_hq', 'name': _('District Office Workers Only (HQ)')},
                {'id': 'district_branch', 'name': _('Subordinate Branches')},
                {'id': 'direct_reports', 'name': _('Direct Reports Only')},
                {'id': 'needs_intervention', 'name': _('⚡ Needs District Action')},
            ]

        elif is_global_governance:
            allowed_levels = [
                {'id': 'corporate', 'name': _('Bank-wide (Corporate)')},
                {'id': 'head_office', 'name': _('🏛️ Head Office')},
                {'id': 'districts', 'name': _('🗺️ Regional Districts & Branches')},
                {'id': 'needs_intervention', 'name': _('⚡ Needs Executive Action')},
            ]

        elif is_chief_retail or (user_role == 'chief' and emp and 'retail' in (emp.job_id.name or '').lower()):
            allowed_levels = [
                {'id': 'corporate', 'name': _('All Retail Network')},
                {'id': 'districts', 'name': _('🗺️ Regional Districts & Branches')},
                {'id': 'directorates', 'name': _('Retail Directorates')},
                {'id': 'direct_reports', 'name': _('Direct Reports Only')},
                {'id': 'needs_intervention', 'name': _('⚡ Needs My Escalation / Action')},
            ]

        elif user_role == 'chief':
            allowed_levels = [
                {'id': 'corporate', 'name': _('My Executive Wing')},
                {'id': 'directorates', 'name': _('Subordinate Directorates')},
                {'id': 'direct_reports', 'name': _('Direct Reports Only')},
                {'id': 'needs_intervention', 'name': _('⚡ Needs My Action')},
            ]

        elif user_role == 'director' or is_director_group:
            allowed_levels = [
                {'id': 'corporate', 'name': _('Directorate-Wide')},
                {'id': 'direct_reports', 'name': _('Direct Reports Only')},
                {'id': 'needs_intervention', 'name': _('⚡ Needs Directorate Action')},
            ]

        elif is_employee_only:
            allowed_levels = [
                {'id': 'corporate', 'name': _('My Disciplinary Records')},
            ]

        else:
            # Branch Manager / Line Coach
            allowed_levels = [
                {'id': 'corporate', 'name': _('Branch Team')},
                {'id': 'direct_reports', 'name': _('Direct Reports Only')},
                {'id': 'needs_intervention', 'name': _('⚡ Needs My Coach Action')},
            ]

        return {
            'allowed_levels': allowed_levels,
            'chief_offices': chief_offices,
            'direct_ceo_directorates': direct_ceo_directorates,
            'directorates_by_chief': directorates_by_chief,
            'district_offices': district_offices,
            'branches_by_district': branches_by_district,
            'district_branches': user_district_branches,
            'user_district_key': user_district_key,
            'user_district_name': user_district_name,
            'user_role': user_role,
            'is_district_dir': is_district_dir,
            'is_chief_retail': is_chief_retail,
            'is_employee_only': is_employee_only,
            'is_global_governance': is_global_governance,
        }

    @api.model
    def get_dashboard_data(self, date_from=False, date_to=False, department_id=None, unit_id=None, period='month', hierarchy_scope='all_hierarchy', level='corporate', entity_id='', search_term='', sub_unit_id=''):
        """
        Enterprise HR Governance, Ethics & Compliance Analytics API for Bunna Bank S.C.
        Supports statutory organizational hierarchy scoping:
        - Bank-wide (Corporate)
        - Head Office (Chief Offices, Direct CEO Directorates, Subordinate Directorates)
        - Regional Districts (11 District Offices, District HQ Workers, Subordinate Branches)
        - District Director Scoping (District HQ vs Branches vs Single Branch)
        """
        today = fields.Date.context_today(self)
        self = self.sudo()

        # 1. Date Range Filtering
        if period and period != 'custom':
            if period == 'today':
                date_from = today
                date_to = today
            elif period == 'week':
                date_from = today - timedelta(days=today.weekday())
                date_to = today
            elif period == 'month':
                date_from = today.replace(day=1)
                date_to = today
            elif period == 'quarter':
                q_month = ((today.month - 1) // 3) * 3 + 1
                date_from = today.replace(month=q_month, day=1)
                date_to = today
            elif period == 'ytd':
                date_from = today.replace(month=1, day=1)
                date_to = today
            elif period == '30d':
                date_from = today - timedelta(days=30)
                date_to = today
            elif period == 'all':
                date_from = False
                date_to = False

        if isinstance(date_from, str) and date_from:
            try:
                date_from = fields.Date.from_string(date_from)
            except Exception:
                pass
        if isinstance(date_to, str) and date_to:
            try:
                date_to = fields.Date.from_string(date_to)
            except Exception:
                pass

        # 1.1 User Governance Roles & Scoping (Dynamic Organizational Hierarchy)
        user = self.env.user
        EmpModel = self.env['hr.employee'].sudo()
        OUModel = self.env['operating.unit'].sudo()
        DeptModel = self.env['hr.department'].sudo()

        ceo_user = EmpModel.get_ceo_user()
        cpco_user = EmpModel.get_cpco_user()
        sec_user = EmpModel.get_secretary_user()

        is_ceo = bool((ceo_user and user.id == ceo_user.id) or user.has_group('discipline_management.group_discipline_ceo'))
        is_cpco = bool((cpco_user and user.id == cpco_user.id) or user.has_group('discipline_management.group_discipline_cpco'))
        is_admin = bool(user.has_group('discipline_management.group_discipline_admin') or user._is_superuser())
        is_auditor = bool(user.has_group('discipline_management.group_discipline_auditor'))
        is_director_group = bool(user.has_group('discipline_management.group_discipline_director'))
        is_pomd = bool(user.has_group('discipline_management.group_discipline_pomd') or user.has_group('discipline_management.group_discipline_pomd_director'))

        user_role = EmpModel.get_user_hierarchy_role(user)
        if user_role in ('ceo', 'chief'):
            is_executive = True
            is_director = True
        elif user_role == 'director' or is_director_group:
            is_executive = is_ceo or is_cpco or is_admin
            is_director = True
        else:
            is_executive = is_ceo or is_cpco or is_admin
            is_director = False

        is_global_governance = is_ceo or is_cpco or is_admin or is_auditor or is_pomd

        emp = user.employee_id.sudo() if user.employee_id else False
        hierarchy_team_count = 0
        direct_reports_count = 0
        user_title = emp.job_id.name if emp and emp.job_id else ''
        user_department = emp.department_id.name if emp and emp.department_id else ''

        direct_subs = []
        all_subs = []
        if emp:
            direct_subs = emp.child_ids.ids
            direct_reports_count = len(direct_subs)
            all_subs = EmpModel.search([('id', 'child_of', emp.id)]).ids
            hierarchy_team_count = len(all_subs)

        is_secretary_only = bool(user.has_group('discipline_management.group_discipline_secretary') and not is_global_governance)
        is_employee_only = bool(
            (user_role == 'employee' or is_secretary_only) and
            direct_reports_count == 0 and
            hierarchy_team_count <= 1 and
            not is_global_governance
        )
        is_district_dir = bool(emp and emp.job_id and 'district' in (emp.job_id.name or '').lower())
        is_manager_only = not (is_executive or is_auditor or is_director or is_employee_only)

        total_bank_employees = EmpModel.search_count([('active', '=', True)])
        if is_global_governance:
            hierarchy_team_count = total_bank_employees

        show_hierarchy_filter = bool(not is_employee_only and (direct_reports_count > 0 or hierarchy_team_count > 1 or is_global_governance))
        show_unit_filter = bool(is_global_governance or user_role in ('ceo', 'chief'))

        # 1.2 Statutory Hierarchy Scope Resolution
        target_emp_ids = None
        target_ou_ids = None
        target_dept_ids = None
        filter_district_hq_only = False
        selected_ou_id = None
        selected_dept_id = None
        selected_branch_id = None
        selected_emp_subs = None

        if is_district_dir and emp:
            # District Director view: strictly scoped to their district
            user_dist_ou = emp.operating_unit_id if emp.operating_unit_id and emp.operating_unit_id.work_unit_type == 'district_office' else False
            if not user_dist_ou and emp.department_id:
                user_dist_ou = OUModel.search([('name', '=', emp.department_id.name), ('work_unit_type', '=', 'district_office')], limit=1)
            if not user_dist_ou:
                for d in OUModel.search([('work_unit_type', '=', 'district_office')]):
                    if d.name.lower() in (emp.job_id.name or '').lower() or (emp.department_id and d.name.lower() in emp.department_id.name.lower()):
                        user_dist_ou = d
                        break

            dist_ou_id = user_dist_ou.id if user_dist_ou else False
            dist_dept = DeptModel.search([('name', '=', user_dist_ou.name)], limit=1) if user_dist_ou else emp.department_id
            child_branch_ids = OUModel.search([('parent_unit', '=', dist_ou_id)]).ids if dist_ou_id else []

            if level == 'district_hq':
                filter_district_hq_only = True
                target_ou_ids = [dist_ou_id] if dist_ou_id else []
                target_dept_ids = [dist_dept.id] if dist_dept else []
            elif level == 'district_branch':
                if sub_unit_id and str(sub_unit_id).startswith('branch_'):
                    b_id = int(str(sub_unit_id).replace('branch_', ''))
                    target_ou_ids = [b_id]
                elif sub_unit_id and str(sub_unit_id).isdigit():
                    target_ou_ids = [int(sub_unit_id)]
                else:
                    target_ou_ids = child_branch_ids
            elif level == 'direct_reports':
                hierarchy_scope = 'direct_reports'
            elif level == 'needs_intervention':
                hierarchy_scope = 'needs_intervention'
            else:
                # District-Wide (District Office Workers + all Child Branches)
                target_ou_ids = ([dist_ou_id] if dist_ou_id else []) + child_branch_ids
                target_dept_ids = [dist_dept.id] if dist_dept else []

        elif level == 'districts':
            if entity_id:
                dist_ou_id = int(str(entity_id).replace('dist_', ''))
                dist_ou = OUModel.browse(dist_ou_id)
                dist_dept = DeptModel.search([('name', '=', dist_ou.name)], limit=1)
                child_branch_ids = OUModel.search([('parent_unit', '=', dist_ou_id)]).ids

                if sub_unit_id == 'district_hq':
                    filter_district_hq_only = True
                    target_ou_ids = [dist_ou_id]
                    target_dept_ids = [dist_dept.id] if dist_dept else []
                elif sub_unit_id and str(sub_unit_id).startswith('branch_'):
                    b_id = int(str(sub_unit_id).replace('branch_', ''))
                    target_ou_ids = [b_id]
                elif sub_unit_id and str(sub_unit_id).isdigit():
                    target_ou_ids = [int(sub_unit_id)]
                else:
                    # All District (District Office Workers + All Subordinate Branches)
                    target_ou_ids = [dist_ou_id] + child_branch_ids
                    target_dept_ids = [dist_dept.id] if dist_dept else []
            else:
                # All 11 Districts & Branches
                all_dist_ous = OUModel.search([('work_unit_type', '=', 'district_office')])
                all_branch_ous = OUModel.search([('parent_unit', 'in', all_dist_ous.ids)])
                target_ou_ids = all_dist_ous.ids + all_branch_ous.ids
                target_dept_ids = DeptModel.search([('name', 'ilike', 'District')]).ids

        elif level == 'head_office':
            if entity_id:
                if str(entity_id).startswith('chief_'):
                    c_id = int(str(entity_id).replace('chief_', ''))
                    if sub_unit_id and str(sub_unit_id).startswith('dir_'):
                        sd_id = int(str(sub_unit_id).replace('dir_', ''))
                        target_emp_ids = EmpModel.search([('id', 'child_of', sd_id)]).ids
                    elif sub_unit_id and str(sub_unit_id).startswith('ou_'):
                        target_ou_ids = [int(str(sub_unit_id).replace('ou_', ''))]
                    else:
                        target_emp_ids = EmpModel.search([('id', 'child_of', c_id)]).ids
                elif str(entity_id).startswith('dir_'):
                    d_id = int(str(entity_id).replace('dir_', ''))
                    target_emp_ids = EmpModel.search([('id', 'child_of', d_id)]).ids
                elif str(entity_id).startswith('ou_'):
                    target_ou_ids = [int(str(entity_id).replace('ou_', ''))]
            else:
                # All Head Office units
                ho_ous = OUModel.search([('work_unit_type', 'in', ['head_office', 'directorate', 'division'])])
                target_ou_ids = ho_ous.ids

        elif level == 'directorates' and entity_id:
            if str(entity_id).startswith('dir_'):
                d_id = int(str(entity_id).replace('dir_', ''))
                target_emp_ids = EmpModel.search([('id', 'child_of', d_id)]).ids
            elif str(entity_id).startswith('ou_'):
                target_ou_ids = [int(str(entity_id).replace('ou_', ''))]

        elif level == 'needs_intervention':
            hierarchy_scope = 'needs_intervention'
        elif level == 'direct_reports':
            hierarchy_scope = 'direct_reports'

        # Legacy filter normalization
        effective_filter = entity_id or unit_id or department_id
        if effective_filter and target_emp_ids is None and target_ou_ids is None and target_dept_ids is None:
            filter_str = str(effective_filter).strip()
            if filter_str.startswith('chief_'):
                try:
                    c_id = int(filter_str.replace('chief_', ''))
                    target_emp_ids = EmpModel.search([('id', 'child_of', c_id)]).ids
                except ValueError:
                    pass
            elif filter_str.startswith('dist_'):
                try:
                    raw_id = int(filter_str.replace('dist_', ''))
                    d_ou = OUModel.browse(raw_id)
                    child_branches = OUModel.search([('parent_unit', '=', raw_id)]).ids
                    target_ou_ids = [raw_id] + child_branches
                except ValueError:
                    pass
            elif filter_str.startswith('dir_'):
                try:
                    raw_id = int(filter_str.replace('dir_', ''))
                    target_emp_ids = EmpModel.search([('id', 'child_of', raw_id)]).ids
                except ValueError:
                    pass
            elif filter_str.startswith('ou_'):
                try:
                    target_ou_ids = [int(filter_str.replace('ou_', ''))]
                except ValueError:
                    pass
            elif filter_str.startswith('branch_'):
                try:
                    target_ou_ids = [int(filter_str.replace('branch_', ''))]
                except ValueError:
                    pass

        # Helper to apply statutory scoping across all discipline models
        def apply_scoping(dom, ou_field='operating_unit_id', dept_field='department_id', emp_field='employee_id'):
            if filter_district_hq_only:
                if target_ou_ids and target_dept_ids:
                    dom.extend(['&', (ou_field, 'in', target_ou_ids), (dept_field, 'in', target_dept_ids)])
                elif target_ou_ids:
                    dom.append((ou_field, 'in', target_ou_ids))
            elif target_emp_ids is not None:
                dom.append((emp_field, 'in', target_emp_ids))
            elif target_ou_ids or target_dept_ids:
                clauses = []
                if target_ou_ids:
                    clauses.append((ou_field, 'in', target_ou_ids))
                    clauses.append((f"{emp_field}.operating_unit_id", 'in', target_ou_ids))
                if target_dept_ids:
                    clauses.append((dept_field, 'in', target_dept_ids))
                    clauses.append((f"{emp_field}.department_id", 'in', target_dept_ids))
                if len(clauses) == 1:
                    dom.append(clauses[0])
                elif len(clauses) > 1:
                    dom.extend(['|'] * (len(clauses) - 1) + clauses)

        # Build Base Case Domain
        base_case_domain = []
        if date_from:
            base_case_domain.append(('incident_date', '>=', date_from))
        if date_to:
            base_case_domain.append(('incident_date', '<=', date_to))

        apply_scoping(base_case_domain, ou_field='operating_unit_id', dept_field='department_id', emp_field='employee_id')

        if search_term and str(search_term).strip():
            s_val = str(search_term).strip()
            base_case_domain.extend([
                '|', '|', '|',
                ('name', 'ilike', s_val),
                ('employee_id.name', 'ilike', s_val),
                ('description', 'ilike', s_val),
                ('punishment_type', 'ilike', s_val),
            ])

        # Apply Dynamic Hierarchy Scoping
        if is_employee_only:
            if emp:
                base_case_domain.append(('employee_id', '=', emp.id))
            else:
                base_case_domain.append(('employee_id', '=', -1))
        elif is_global_governance and hierarchy_scope != 'needs_intervention':
            pass
        elif hierarchy_scope == 'needs_intervention':
            intervention_subdomain = [
                '|', '|', '|',
                '&', ('state', '=', 'submitted_director'), ('director_id', '=', user.id),
                '&', ('state', '=', 'submitted_chief'), ('chief_id', '=', user.id),
                '&', ('state', '=', 'pending_approval'), ('approver_id', '=', user.id),
                '&', ('case_action_track', '=', 'direct_enforce'), ('state', 'in', ('draft', 'initiated')),
            ]
            if not is_global_governance and emp:
                base_case_domain.append(('employee_id', 'in', all_subs or [emp.id]))
            base_case_domain.extend(intervention_subdomain)
        elif hierarchy_scope == 'direct_reports':
            if emp:
                target_ids = direct_subs + [emp.id]
                base_case_domain.append(('employee_id', 'in', target_ids))
        elif is_district_dir:
            # Already scoped by target_ou_ids/target_dept_ids above
            pass
        else:
            # Default for Chief/Director/Manager
            if not is_global_governance and emp:
                base_case_domain.extend([
                    '|', '|',
                    ('employee_id', 'in', all_subs),
                    ('chief_id', '=', user.id),
                    ('director_id', '=', user.id)
                ])

        # 2. Executive Primary KPI Metrics & Pipeline Stages (Optimized via Single read_group)
        state_counts = {}
        total_cases = 0
        for st, cnt in self._read_group(base_case_domain, groupby=['state'], aggregates=['__count']):
            state_counts[st] = cnt
            total_cases += cnt

        active_states = [
            'initiated', 'submitted_director', 'submitted_chief', 'ceo_review',
            'investigating', 'chairman_review', 'committee_review',
            'pending_approval', 'appealed'
        ]
        active_cases = sum(state_counts.get(s, 0) for s in active_states)
        pending_approval = state_counts.get('pending_approval', 0)
        enforced_cases = state_counts.get('enforced', 0)
        closed_cases = state_counts.get('closed', 0)
        sla_breached = self.search_count(base_case_domain + [('is_sla_exceeded', '=', True)])

        sla_compliance_rate = 100.0
        if total_cases > 0:
            sla_compliance_rate = round(max(0.0, ((total_cases - sla_breached) / float(total_cases)) * 100.0), 1)

        # 3. Staff Categories & Action Tracks (Optimized via read_group)
        mgr_counts = dict(self._read_group(base_case_domain, groupby=['is_managerial'], aggregates=['__count']))
        managerial_cases = mgr_counts.get(True, 0)
        non_managerial_cases = mgr_counts.get(False, 0)
        managerial_pct = round((managerial_cases / float(total_cases) * 100.0), 1) if total_cases > 0 else 0.0
        non_managerial_pct = round((non_managerial_cases / float(total_cases) * 100.0), 1) if total_cases > 0 else 0.0

        track_counts = dict(self._read_group(base_case_domain, groupby=['case_action_track'], aggregates=['__count']))
        coach_track_cases = track_counts.get('direct_enforce', 0) + track_counts.get('direct_line_manager', 0)
        committee_track_cases = track_counts.get('committee_escalation', 0)
        coach_track_pct = round((coach_track_cases / float(total_cases) * 100.0), 1) if total_cases > 0 else 0.0
        committee_track_pct = round((committee_track_cases / float(total_cases) * 100.0), 1) if total_cases > 0 else 0.0

        # 4. Multi-Stage Lifecycle Pipeline Funnel (Direct from state_counts dictionary)
        pipeline_stages = {
            'initiated': state_counts.get('draft', 0) + state_counts.get('submitted', 0) + state_counts.get('initiated', 0),
            'investigation': state_counts.get('investigating', 0) + state_counts.get('hearing', 0),
            'committee_review': state_counts.get('committee_review', 0),
            'pending_approval': state_counts.get('pending_approval', 0),
            'enforced': state_counts.get('enforced', 0),
            'appealed': state_counts.get('appealed', 0),
            'closed': state_counts.get('closed', 0),
        }

        # 5. Precautionary Suspensions (Statutory Labor Proclamation 1156/2019 Art. 27 — Strictly Without Pay)
        susp_model = self.env.get('discipline.suspension')
        active_suspensions = 0
        suspensions_approaching_limit = 0  # Suspensions running >= 20 days
        suspensions_over_limit = 0  # Suspensions exceeding 30-day statutory limit
        if susp_model is not None:
            # Operational mandate: Live active suspensions are never hidden by period date filters
            susp_domain = [('state', 'in', ['active', 'extended'])]
            if is_employee_only:
                susp_domain.append(('employee_id', '=', emp.id if emp else -1))
            elif not is_global_governance and emp:
                susp_domain.append(('employee_id', 'in', all_subs or [emp.id]))

            apply_scoping(susp_domain, ou_field='case_id.operating_unit_id', dept_field='department_id', emp_field='employee_id')

            active_susp_recs = susp_model.search(susp_domain)
            active_suspensions = len(active_susp_recs)
            for s in active_susp_recs:
                s_date = s.start_date or (s.create_date.date() if s.create_date else today)
                days_running = (today - s_date).days
                if days_running > 30:
                    suspensions_over_limit += 1
                elif days_running >= 20:
                    suspensions_approaching_limit += 1

        # 6. Appeals Breakdown (Decoupled Real-Time Under Review vs Period Decided)
        appeal_model = self.env.get('discipline.appeal')
        pending_appeals = 0
        decided_appeals_count = 0
        upheld_count = 0
        reduced_count = 0
        overturned_count = 0
        appeal_stages = {
            'draft': 0,
            'submitted': 0,
            'under_review': 0,
            'committee_review': 0,
            'decided': 0,
            'total': 0,
        }
        if appeal_model is not None:
            app_base = []
            if is_employee_only:
                app_base.append(('employee_id', '=', emp.id if emp else -1))
            elif not is_global_governance and emp:
                app_base.append(('employee_id', 'in', all_subs or [emp.id]))

            apply_scoping(app_base, ou_field='case_id.operating_unit_id', dept_field='case_id.department_id', emp_field='employee_id')

            # Live active appeals (under review today)
            live_app_counts = dict(appeal_model._read_group(app_base, groupby=['state'], aggregates=['__count']))
            pending_appeals = live_app_counts.get('submitted', 0) + live_app_counts.get('under_review', 0) + live_app_counts.get('committee_review', 0)

            # Period-filtered appeals for velocity tracking
            app_period = list(app_base)
            if date_from:
                app_period.append(('submission_date', '>=', date_from))
            if date_to:
                app_period.append(('submission_date', '<=', date_to))

            app_state_counts = dict(appeal_model._read_group(app_period, groupby=['state'], aggregates=['__count']))
            appeal_stages['total'] = sum(app_state_counts.values())
            appeal_stages['draft'] = app_state_counts.get('draft', 0)
            appeal_stages['submitted'] = app_state_counts.get('submitted', 0)
            appeal_stages['under_review'] = app_state_counts.get('under_review', 0)
            appeal_stages['committee_review'] = app_state_counts.get('committee_review', 0)
            appeal_stages['decided'] = app_state_counts.get('decided', 0)
            decided_appeals_count = appeal_stages['decided']

            outcome_counts = dict(appeal_model._read_group(app_period + [('state', '=', 'decided')], groupby=['decision_outcome'], aggregates=['__count']))
            upheld_count = outcome_counts.get('upheld', 0)
            reduced_count = outcome_counts.get('penalty_reduced', 0)
            overturned_count = outcome_counts.get('overturned', 0)

        # 7. Investigations Audit Breakdown (Decoupled Real-Time In-Progress)
        inv_model = self.env.get('discipline.investigation')
        active_investigations = 0
        investigation_stages = {
            'draft': 0,
            'assigned': 0,
            'manager_review': 0,
            'director_review': 0,
            'executive_submitted': 0,
            'approved': 0,
            'total': 0,
        }
        if inv_model is not None:
            inv_base = []
            if is_employee_only:
                inv_base.append(('employee_id', '=', emp.id if emp else -1))
            elif not is_global_governance and emp:
                inv_base.append(('employee_id', 'in', all_subs or [emp.id]))

            apply_scoping(inv_base, ou_field='case_id.operating_unit_id', dept_field='case_id.department_id', emp_field='employee_id')

            # Live active investigations
            live_inv_counts = dict(inv_model._read_group(inv_base, groupby=['state'], aggregates=['__count']))
            active_investigations = sum(cnt for st, cnt in live_inv_counts.items() if st not in ['approved', 'cancelled'])

            # Period-filtered investigations
            inv_period = list(inv_base)
            if date_from:
                inv_period.append(('investigation_date', '>=', date_from))
            if date_to:
                inv_period.append(('investigation_date', '<=', date_to))

            inv_state_counts = dict(inv_model._read_group(inv_period, groupby=['state'], aggregates=['__count']))
            investigation_stages['total'] = sum(inv_state_counts.values())
            investigation_stages['draft'] = inv_state_counts.get('draft', 0)
            investigation_stages['assigned'] = inv_state_counts.get('assigned', 0)
            investigation_stages['manager_review'] = inv_state_counts.get('manager_review', 0)
            investigation_stages['director_review'] = inv_state_counts.get('director_review', 0)
            investigation_stages['executive_submitted'] = inv_state_counts.get('submitted_ceo', 0) + inv_state_counts.get('forwarded_cpco', 0)
            investigation_stages['approved'] = inv_state_counts.get('approved', 0)

        # 8. Committee Meetings & Live Hearing Schedule Agenda (Optimized via read_group)
        comm_model = self.env.get('discipline.committee.meeting')
        active_committee_meetings = 0
        committee_stages = {
            'draft': 0,
            'scheduled': 0,
            'in_progress': 0,
            'completed': 0,
            'total': 0,
        }
        upcoming_meetings = []
        if comm_model is not None:
            comm_domain = []
            if is_employee_only:
                comm_domain.append(('employee_id', '=', emp.id if emp else -1))
            elif not is_global_governance and emp:
                comm_domain.append(('employee_id', 'in', all_subs or [emp.id]))

            apply_scoping(comm_domain, ou_field='case_id.operating_unit_id', dept_field='department_id', emp_field='employee_id')

            # Live active committee meetings
            live_comm_counts = dict(comm_model._read_group(comm_domain, groupby=['state'], aggregates=['__count']))
            active_committee_meetings = live_comm_counts.get('scheduled', 0) + live_comm_counts.get('in_progress', 0)

            # Period-filtered meetings
            comm_period = list(comm_domain)
            if date_from:
                comm_period.append(('meeting_date', '>=', fields.Datetime.to_string(datetime.combine(date_from, time.min))))
            if date_to:
                comm_period.append(('meeting_date', '<=', fields.Datetime.to_string(datetime.combine(date_to, time.max))))

            comm_state_counts = dict(comm_model._read_group(comm_period, groupby=['state'], aggregates=['__count']))
            committee_stages['total'] = sum(comm_state_counts.values())
            committee_stages['draft'] = comm_state_counts.get('draft', 0)
            committee_stages['scheduled'] = comm_state_counts.get('scheduled', 0)
            committee_stages['in_progress'] = comm_state_counts.get('in_progress', 0)
            committee_stages['completed'] = comm_state_counts.get('completed', 0)

            meeting_recs = comm_model.search(
                comm_domain + [('state', 'in', ['scheduled', 'in_progress', 'draft'])],
                order='meeting_date asc, id desc',
                limit=5
            )
            for m in meeting_recs:
                upcoming_meetings.append({
                    'id': m.id,
                    'name': m.name or _('Session'),
                    'case_id': m.case_id.id if m.case_id else False,
                    'case_name': m.case_id.name if m.case_id else _('Unassigned Case'),
                    'employee_name': m.employee_id.name if m.employee_id else (m.case_id.employee_id.name if m.case_id and m.case_id.employee_id else _('Employee')),
                    'meeting_date': fields.Datetime.to_string(m.meeting_date) if m.meeting_date else False,
                    'location': m.location or _('HR Boardroom'),
                    'quorum_reached': bool(getattr(m, 'is_quorum_reached', False) or getattr(m, 'quorum_reached', False)),
                    'state': m.state,
                    'state_label': dict(comm_model._fields['state'].selection).get(m.state, m.state),
                })

        # 9. Statutory SLA & Case Aging Surveillance (Article 33.11 Mandate)
        active_case_data = self.search_read(
            base_case_domain + [('state', 'in', active_states)],
            ['incident_date', 'create_date', 'is_sla_exceeded']
        )
        aging_under_7 = 0
        aging_7_to_15 = 0
        aging_16_to_30 = 0
        aging_over_30 = 0

        for cdata in active_case_data:
            inc_d = cdata.get('incident_date')
            cr_d = cdata.get('create_date')
            start_d = inc_d or (cr_d.date() if hasattr(cr_d, 'date') else today)
            days_open = (today - start_d).days
            if cdata.get('is_sla_exceeded') or days_open > 30:
                aging_over_30 += 1
            elif days_open <= 7:
                aging_under_7 += 1
            elif days_open <= 15:
                aging_7_to_15 += 1
            else:
                aging_16_to_30 += 1

        # 10. Sanction Severity Matrix (Pyramid Distribution)
        sev_counts = dict(self._read_group(base_case_domain, groupby=['severity_level'], aggregates=['__count']))
        severity_matrix = []
        sev_labels = {
            'level_1': _('Level 1 — Critical (Dismissal / Separation)'),
            'level_2': _('Level 2 — Severe (Final Written Warning)'),
            'level_3': _('Level 3 — Moderate (Second Warning + Penalty)'),
            'level_4': _('Level 4 — Minor (First Warning + Penalty)'),
            'level_5': _('Level 5 — Caution (Recorded Verbal Warning)'),
        }
        sev_colors = {
            'level_1': '#541718',  # Bunna Crimson Maroon
            'level_2': '#7a2325',  # Bunna Dark Crimson
            'level_3': '#c17540',  # Bunna Terracotta Amber
            'level_4': '#726732',  # Bunna Antique Gold
            'level_5': '#425727',  # Bunna Olive Green
        }
        for s_code, s_label in sev_labels.items():
            cnt = sev_counts.get(s_code, 0)
            pct = round((cnt / float(total_cases) * 100.0), 1) if total_cases > 0 else 0.0
            severity_matrix.append({
                'code': s_code,
                'label': s_label,
                'count': cnt,
                'percentage': pct,
                'color': sev_colors.get(s_code, '#541718'),
            })

        # 11. Misconduct Offense Breakdown (Categorical Pareto using Odoo 19 _read_group)
        misconduct_breakdown = []
        try:
            for offense, cnt in self._read_group(base_case_domain, groupby=['offense_id'], aggregates=['__count'], limit=8, order='__count desc'):
                c_name = offense.name if offense else _('General Compliance / Policy')
                pct = round((cnt / float(total_cases) * 100.0), 1) if total_cases > 0 else 0.0
                misconduct_breakdown.append({
                    'name': c_name,
                    'count': cnt,
                    'percentage': pct,
                })
        except Exception:
            pass

        # 12. Directorate & Work-Unit Hotspots (Ethics Risk Heatmap using Odoo 19 _read_group)
        department_hotspots = []
        dept_colors = ['#541718', '#7a2325', '#c17540', '#726732', '#425727', '#1d2b32']
        try:
            for idx, (dept, cnt) in enumerate(self._read_group(base_case_domain, groupby=['department_id'], aggregates=['__count'], limit=6, order='__count desc')):
                d_name = dept.name if dept else _('Headquarters / General')
                pct = round((cnt / float(total_cases) * 100.0), 1) if total_cases > 0 else 0.0
                department_hotspots.append({
                    'id': dept.id if dept else False,
                    'name': d_name,
                    'count': cnt,
                    'percentage': pct,
                    'color': dept_colors[idx % len(dept_colors)],
                })
        except Exception:
            pass

        # 13. Financial & Payroll Sanction Governance Breakdown
        payroll_model = self.env.get('discipline.payroll.penalty')
        payroll_data = {
            'pending_count': 0,
            'pending_amount': 0.0,
            'transmitted_count': 0,
            'transmitted_amount': 0.0,
            'deducted_count': 0,
            'deducted_amount': 0.0,
            'cancelled_count': 0,
            'cancelled_amount': 0.0,
            'refund_count': 0,
            'refund_amount': 0.0,
            'total_recovery': 0.0,
            'total_sanctions_amount': 0.0,
            'total_penalties_count': 0,
        }
        if payroll_model is not None:
            pen_domain = []
            if date_from:
                pen_domain.append(('effective_date', '>=', date_from))
            apply_scoping(pen_domain, ou_field='case_id.operating_unit_id', dept_field='case_id.department_id', emp_field='employee_id')

            try:
                # Group by transaction_type and state to get counts and sums in 1 database query
                grouped_pens = payroll_model._read_group(
                    pen_domain,
                    groupby=['transaction_type', 'state'],
                    aggregates=['__count', 'calculated_amount:sum']
                )
                for tx_type, st, cnt, amt_sum in grouped_pens:
                    amt = round(amt_sum or 0.0, 2)
                    if tx_type == 'deduction':
                        if st == 'pending':
                            payroll_data['pending_count'] += cnt
                            payroll_data['pending_amount'] += amt
                        elif st == 'transferred':
                            payroll_data['transmitted_count'] += cnt
                            payroll_data['transmitted_amount'] += amt
                        elif st == 'deducted':
                            payroll_data['deducted_count'] += cnt
                            payroll_data['deducted_amount'] += amt
                        elif st == 'cancelled':
                            payroll_data['cancelled_count'] += cnt
                            payroll_data['cancelled_amount'] += amt
                    elif tx_type == 'refund':
                        if st != 'cancelled':
                            payroll_data['refund_count'] += cnt
                            payroll_data['refund_amount'] += amt

                payroll_data['pending_amount'] = round(payroll_data['pending_amount'], 2)
                payroll_data['transmitted_amount'] = round(payroll_data['transmitted_amount'], 2)
                payroll_data['deducted_amount'] = round(payroll_data['deducted_amount'], 2)
                payroll_data['cancelled_amount'] = round(payroll_data['cancelled_amount'], 2)
                payroll_data['refund_amount'] = round(payroll_data['refund_amount'], 2)

                payroll_data['total_recovery'] = round(payroll_data['transmitted_amount'] + payroll_data['deducted_amount'], 2)
                payroll_data['total_sanctions_amount'] = round(payroll_data['pending_amount'] + payroll_data['transmitted_amount'] + payroll_data['deducted_amount'], 2)
                payroll_data['total_penalties_count'] = payroll_data['pending_count'] + payroll_data['transmitted_count'] + payroll_data['deducted_count']
            except Exception:
                pass

        # 14. Real Organizational Units & Subordinate Districts Options (Categorized Groups)
        unit_groups = []
        unit_label = _('Organizational Unit')

        if is_global_governance:
            # 1. 🏢 Chief Offices / Executive Wings
            chief_options = []
            chief_emps = self.env['hr.employee'].sudo().search([
                '|', ('job_id.name', 'ilike', 'Chief'), ('job_id.name', 'ilike', 'Deputy Chief')
            ], order='name asc')
            for c in chief_emps:
                # Exclude CEO from dropdown wings list since CEO is the whole bank
                if 'Executive' in (c.job_id.name or ''):
                    continue
                subs_cnt = EmpModel.search_count([('id', 'child_of', c.id)])
                wing_name = c.job_id.name if c.job_id else c.name
                chief_options.append({
                    'id': f'chief_{c.id}',
                    'name': f'{wing_name} ({subs_cnt} Staff)',
                })

            if chief_options:
                unit_groups.append({
                    'group': _('🏢 Chief Offices / Executive Wings'),
                    'options': chief_options,
                })

            # 2. 🗺️ District Offices (from hr.department with staff)
            dist_options = []
            dist_depts = self.env['hr.department'].sudo().search([
                ('name', 'ilike', 'District')
            ], order='name asc')
            for d in dist_depts:
                staff_cnt = EmpModel.search_count([('department_id', '=', d.id)])
                if staff_cnt > 0:
                    dist_options.append({
                        'id': f'dept_{d.id}',
                        'name': f'{d.name} ({staff_cnt} Staff)',
                    })

            if dist_options:
                unit_groups.append({
                    'group': _('🗺️ District Offices'),
                    'options': dist_options,
                })

            # 3. 📂 Operating Directorates (all 33 Directorates in operating.unit)
            dir_options = []
            ou_records = self.env['operating.unit'].sudo().search([
                ('name', 'ilike', 'Directorate')
            ], order='name asc')
            for ou in ou_records:
                dir_options.append({
                    'id': f'ou_{ou.id}',
                    'name': ou.name,
                })

            if dir_options:
                unit_groups.append({
                    'group': _('📂 Operating Directorates'),
                    'options': dir_options,
                })

            unit_label = _('Organizational Unit')

        elif user_role == 'chief':
            # Chief Retail & Branch Banking Officer (Eskindir Dibekulu)
            # 1. 🗺️ My District Offices
            dist_options = []
            sub_dept_ids = [e.department_id.id for e in self.env['hr.employee'].sudo().browse(all_subs) if e.department_id]
            dist_depts = self.env['hr.department'].sudo().search([
                ('id', 'in', sub_dept_ids),
                ('name', 'ilike', 'District')
            ], order='name asc')
            for d in dist_depts:
                staff_cnt = EmpModel.search_count([('department_id', '=', d.id)])
                if staff_cnt > 0:
                    dist_options.append({
                        'id': f'dept_{d.id}',
                        'name': f'{d.name} ({staff_cnt} Staff)',
                    })

            if dist_options:
                unit_groups.append({
                    'group': _('🗺️ My District Offices'),
                    'options': dist_options,
                })

            # 2. 📂 Retail Directorates
            dir_options = []
            ou_subs = self.env['operating.unit'].sudo().search([
                ('name', 'ilike', 'Directorate'),
                '|', ('name', 'ilike', 'Retail'), ('name', 'ilike', 'Branch Banking')
            ], order='name asc')
            for ou in ou_subs:
                dir_options.append({
                    'id': f'ou_{ou.id}',
                    'name': ou.name,
                })

            if dir_options:
                unit_groups.append({
                    'group': _('📂 Retail Directorates'),
                    'options': dir_options,
                })

            unit_label = _('My Districts & Units')
        else:
            unit_groups = []
            unit_label = ''

        # Flatten options for backwards compatibility
        unit_options = []
        for g in unit_groups:
            unit_options.extend(g['options'])

        show_unit_filter = bool(show_unit_filter and unit_groups)
        department_options = unit_options

        # 15. Appeal Outcome Ratios
        appeal_audit = {
            'total_decided': decided_appeals_count,
            'upheld_count': upheld_count,
            'upheld_pct': round((upheld_count / float(decided_appeals_count) * 100.0), 1) if decided_appeals_count > 0 else 0.0,
            'reduced_count': reduced_count,
            'reduced_pct': round((reduced_count / float(decided_appeals_count) * 100.0), 1) if decided_appeals_count > 0 else 0.0,
            'overturned_count': overturned_count,
            'overturned_pct': round((overturned_count / float(decided_appeals_count) * 100.0), 1) if decided_appeals_count > 0 else 0.0,
        }

        # 16. Pre-Formatted Chart Datasets for Chart.js
        chart_data = {
            'severity': {
                'labels': [m['label'] for m in severity_matrix],
                'data': [m['count'] for m in severity_matrix],
                'colors': [m['color'] for m in severity_matrix],
                'total': sum(m['count'] for m in severity_matrix),
            },
            'categories': {
                'labels': [_('Managerial Staff'), _('Non-Managerial Staff'), _('Direct Coach Track'), _('Committee Track')],
                'data': [managerial_cases, non_managerial_cases, coach_track_cases, committee_track_cases],
                'colors': ['#541718', '#425727', '#726732', '#c17540'],
            },
            'departments': {
                'labels': [d['name'] for d in department_hotspots],
                'data': [d['count'] for d in department_hotspots],
                'colors': [d['color'] for d in department_hotspots],
            },
            'misconduct': {
                'labels': [m['name'] for m in misconduct_breakdown[:6]],
                'data': [m['count'] for m in misconduct_breakdown[:6]],
                'percentages': [m['percentage'] for m in misconduct_breakdown[:6]],
                'colors': ['#541718', '#7a2325', '#a85d2c', '#c17540', '#726732', '#425727'],
            }
        }

        # 17. 12-Month Case Velocity & Resolution Trends (Single aggregated query)
        cur_year, cur_month = today.year, today.month
        month_keys = []
        month_labels = []
        for i in range(11, -1, -1):
            m = cur_month - i
            y = cur_year
            while m <= 0:
                m += 12
                y -= 1
            start_m = date(y, m, 1)
            if m == 12:
                end_m = date(y, 12, 31)
            else:
                end_m = date(y, m + 1, 1) - timedelta(days=1)
            month_keys.append((start_m, end_m))
            month_labels.append(start_m.strftime('%b %Y'))

        start_period = month_keys[0][0]
        trend_unit_domain = []
        apply_scoping(trend_unit_domain, ou_field='operating_unit_id', dept_field='department_id', emp_field='employee_id')

        trend_domain = [('incident_date', '>=', start_period), ('incident_date', '<=', today)] + trend_unit_domain

        month_state_counts = {}
        try:
            for m_date, st, cnt in self._read_group(
                trend_domain,
                groupby=['incident_date:month', 'state'],
                aggregates=['__count']
            ):
                key = m_date.strftime('%Y-%m') if hasattr(m_date, 'strftime') else str(m_date)[:7]
                month_state_counts[(key, st)] = cnt
        except Exception:
            month_state_counts = {}

        opened_series = []
        resolved_series = []
        appealed_series = []

        for start_m, end_m in month_keys:
            m_key = start_m.strftime('%Y-%m')
            opened_cnt = sum(cnt for (k, _st), cnt in month_state_counts.items() if k == m_key)
            resolved_cnt = sum(cnt for (k, st), cnt in month_state_counts.items() if k == m_key and st in ('enforced', 'closed'))
            appealed_cnt = sum(cnt for (k, st), cnt in month_state_counts.items() if k == m_key and st == 'appealed')
            opened_series.append(opened_cnt)
            resolved_series.append(resolved_cnt)
            appealed_series.append(appealed_cnt)

        velocity_trend = {
            'labels': month_labels,
            'opened': opened_series,
            'resolved': resolved_series,
            'appealed': appealed_series,
        }

        # 18. Executive Action Priority Watchlist
        watch_domain = [
            ('state', 'not in', ['draft', 'closed'])
        ]
        apply_scoping(watch_domain, ou_field='operating_unit_id', dept_field='department_id', emp_field='employee_id')
        all_active_cases = self.search(watch_domain, order='is_sla_exceeded desc, id desc', limit=40)

        # Batch preload active suspensions for watchlist to eliminate N+1 queries
        active_susp_cases = set()
        if all_active_cases:
            try:
                susp_recs = self.env['discipline.suspension'].search([
                    ('case_id', 'in', all_active_cases.ids),
                    ('state', 'in', ['active', 'extended'])
                ])
                active_susp_cases = set(susp_recs.mapped('case_id.id'))
            except Exception:
                pass

        action_watchlist = []
        for case in all_active_cases:
            start_d = case.incident_date or (case.create_date.date() if case.create_date else today)
            days_open = (today - start_d).days

            risk_level = 'info'
            risk_badge = _('In Review')
            action_req = _('Workflow review in progress')
            priority_score = 10

            has_susp = case.id in active_susp_cases

            if case.is_sla_exceeded or days_open > 30:
                risk_level = 'danger'
                risk_badge = _('Deadline Exceeded (%s d)') % days_open
                action_req = _('Legal Decision Deadline exceeded. Immediate case determination required.')
                priority_score = 100
            elif case.state in ('pending_approval', 'ceo_review'):
                risk_level = 'danger'
                risk_badge = _('Pending CEO/CPCO Approval')
                action_req = _('Sanction decision awaiting final executive sign-off.')
                priority_score = 90
            elif has_susp:
                risk_level = 'warning'
                risk_badge = _('Active Suspension (%s d)') % days_open
                action_req = _('Precautionary suspension active. Conclude proceedings within 30-day cap.')
                priority_score = 80
            elif case.state == 'appealed':
                risk_level = 'purple'
                risk_badge = _('Appellate Review')
                action_req = _('Employee appeal filed. Awaiting CEO review or committee remand.')
                priority_score = 70
            elif days_open > 20:
                risk_level = 'warning'
                risk_badge = _('Approaching SLA (%s d)') % days_open
                action_req = _('Case open over 20 days. Expedite hearing to prevent SLA breach.')
                priority_score = 60
            elif case.state in ('submitted_director', 'submitted_chief', 'chairman_review'):
                risk_level = 'info'
                risk_badge = _('Management Review')
                action_req = _('Submitted for supervisor endorsement / committee scheduling.')
                priority_score = 40
            else:
                priority_score = 20

            state_label = dict(case._fields['state'].selection).get(case.state, case.state)
            punish_val = case.decided_punishment_type or case.punishment_type
            punish_label = dict(case._fields['punishment_type'].selection).get(punish_val, _('Pending Sanction'))

            action_watchlist.append({
                'id': case.id,
                'name': case.name,
                'employee_name': case.employee_id.name if case.employee_id else _('Unassigned'),
                'department_name': case.department_id.name if case.department_id else _('General'),
                'case_type': _('Managerial') if case.is_managerial else _('Non-Managerial'),
                'is_managerial': case.is_managerial,
                'state': case.state,
                'stage_label': state_label,
                'punishment_label': punish_label,
                'days_active': days_open,
                'risk_level': risk_level,
                'risk_badge': risk_badge,
                'action_required': action_req,
                'priority_score': priority_score,
            })

        action_watchlist.sort(key=lambda x: (x['priority_score'], x['days_active']), reverse=True)
        action_watchlist = action_watchlist[:8]

        # 19. Directorate Compliance & Sanction Risk Matrix (Single aggregated query)
        risk_matrix = []
        try:
            dept_stats = {}
            for dept, sev, is_mgr, count in self._read_group(
                base_case_domain,
                groupby=['department_id', 'severity_level', 'is_managerial'],
                aggregates=['__count']
            ):
                d_id = dept.id if dept else False
                d_name = dept.name if dept else _('Unassigned Directorate')
                if d_id not in dept_stats:
                    dept_stats[d_id] = {
                        'id': d_id,
                        'name': d_name,
                        'total': 0,
                        'l1': 0,
                        'l2': 0,
                        'l3': 0,
                        'l4': 0,
                        'l5': 0,
                        'managerial': 0,
                        'non_managerial': 0,
                    }
                dept_stats[d_id]['total'] += count
                if sev == 'level_1':
                    dept_stats[d_id]['l1'] += count
                elif sev == 'level_2':
                    dept_stats[d_id]['l2'] += count
                elif sev == 'level_3':
                    dept_stats[d_id]['l3'] += count
                elif sev == 'level_4':
                    dept_stats[d_id]['l4'] += count
                elif sev == 'level_5':
                    dept_stats[d_id]['l5'] += count

                if is_mgr:
                    dept_stats[d_id]['managerial'] += count
                else:
                    dept_stats[d_id]['non_managerial'] += count

            risk_matrix = sorted(dept_stats.values(), key=lambda r: r['total'], reverse=True)
        except Exception:
            risk_matrix = []
        except Exception:
            pass

        # Personal Employee Governance & Compliance Records
        employee_cases_list = []
        employee_standing = {
            'status': 'good_standing',
            'status_label': _('Good Standing / Clear Conduct Record'),
            'status_class': 'success',
            'has_active_sanction': False,
            'active_sanction_name': '',
            'active_sanction_date': '',
            'expiration_date': '',
            'days_remaining': 0,
            'is_eligible_promotion': True,
            'promotion_eligibility_text': _('Fully Eligible for Promotion & Internal Transfer'),
        }

        if is_employee_only and emp:
            emp_cases = self.search([('employee_id', '=', emp.id)], order='incident_date desc, id desc')
            for c in emp_cases:
                offense_name = c.offense_id.name if c.offense_id else (c.legal_article_display or _('General Compliance / Policy'))
                employee_cases_list.append({
                    'id': c.id,
                    'name': c.name,
                    'incident_date': str(c.incident_date) if c.incident_date else '',
                    'offense_name': offense_name,
                    'sanction': c.executive_summary_sanction or _('Pending Determination'),
                    'state': c.state,
                    'state_label': dict(c._fields['state'].selection).get(c.state, c.state),
                    'is_enforced': c.state == 'enforced',
                    'is_in_progress': c.state in active_states,
                    'stage_deadline': str(c.stage_deadline) if c.stage_deadline else '',
                })

            enforced_cases_emp = emp_cases.filtered(lambda x: x.state == 'enforced')
            if enforced_cases_emp:
                latest_enforced = enforced_cases_emp[0]
                enf_date = latest_enforced.incident_date or (latest_enforced.create_date.date() if latest_enforced.create_date else today)
                exp_date = enf_date + timedelta(days=365)
                days_left = (exp_date - today).days
                if days_left > 0:
                    employee_standing['status'] = 'sanction_active'
                    employee_standing['status_label'] = _('Active Sanction in Effect')
                    employee_standing['status_class'] = 'danger'
                    employee_standing['has_active_sanction'] = True
                    employee_standing['active_sanction_name'] = latest_enforced.executive_summary_sanction or _('Written Warning')
                    employee_standing['active_sanction_date'] = str(enf_date)
                    employee_standing['expiration_date'] = str(exp_date)
                    employee_standing['days_remaining'] = days_left
                    employee_standing['is_eligible_promotion'] = False
                    employee_standing['promotion_eligibility_text'] = _('Restricted until %s (Active Warning Period)') % str(exp_date)

        # 1.6 Dedicated Secretary Follow-up Suite (Tracking & Expiration Prevention)
        secretary_followup = {}
        executive_boss_name = False
        executive_boss_title = False

        if is_secretary_only:
            exec_user = user.discipline_effective_boss_id
            if exec_user:
                executive_boss_name = exec_user.name
                exec_emp = exec_user.employee_id.sudo() if exec_user.employee_id else False
                executive_boss_title = (exec_emp.job_id.name if exec_emp and exec_emp.job_id else getattr(exec_emp, 'job_name', False)) or ''
                if not executive_boss_title and getattr(exec_emp, 'job_position', False):
                    executive_boss_title = exec_emp.job_position.name or ''

                followup_domain = ['|', '|', '|',
                    ('current_stage_authority_user_id', '=', exec_user.id),
                    ('director_id', '=', exec_user.id),
                    ('chief_id', '=', exec_user.id),
                    ('approver_id', '=', exec_user.id)
                ]
            else:
                followup_domain = [('id', '=', 0)]

            CaseModel_sudo = self.env['discipline.case'].sudo().with_context(is_tracker_followup=True)
            all_followup = CaseModel_sudo.search(followup_domain, order='stage_deadline asc, id desc')
            active_followup = all_followup.filtered(lambda c: c.state not in ('enforced', 'closed', 'appealed', 'revoked'))
            pending_boss = active_followup.filtered(lambda c: c.current_stage_authority_user_id.id == exec_user.id) if exec_user else CaseModel_sudo
            approaching = active_followup.filtered(lambda c: c.sla_status == 'warning')
            overdue = active_followup.filtered(lambda c: c.sla_status == 'overdue')

            st_dict = dict(self.env['discipline.case']._fields['state'].selection) if 'state' in self.env['discipline.case']._fields else {}
            cases_list = []
            for c in active_followup[:20]:
                cases_list.append({
                    'id': c.id,
                    'name': c.name or '',
                    'employee_name': c.employee_id.sudo().name if c.employee_id else '',
                    'operating_unit': c.operating_unit_id.sudo().name if c.operating_unit_id else (c.department_id.sudo().name if c.department_id else ''),
                    'from_display': c.case_flow_from_display or (c.reported_by_id.sudo().name if c.reported_by_id else ''),
                    'to_display': c.case_flow_to_display or (c.current_stage_authority_name or ''),
                    'flow_briefing': c.case_flow_verbal_briefing or '',
                    'current_stage': st_dict.get(c.state, c.state or ''),
                    'current_authority': c.current_stage_authority_name or '',
                    'is_boss_desk': bool(exec_user and c.current_stage_authority_user_id.id == exec_user.id),
                    'stage_deadline': c.stage_deadline.strftime('%b %d, %Y') if c.stage_deadline else '',
                    'days_in_stage': c.days_in_stage,
                    'sla_countdown': c.sla_countdown_display or '',
                    'sla_status': c.sla_status or 'on_track',
                })

            secretary_followup = {
                'total_cases': len(all_followup),
                'active_cases': len(active_followup),
                'pending_boss_action': len(pending_boss),
                'approaching_deadline': len(approaching),
                'overdue_cases': len(overdue),
                'cases_list': cases_list,
            }

        return {
            'period': period,
            'date_from': str(date_from) if date_from else '',
            'date_to': str(date_to) if date_to else '',
            'department_id': department_id,
            'kpis': {
                'total_cases': total_cases,
                'in_progress_cases': active_cases,
                'active_cases': active_cases,
                'pending_approval': pending_approval,
                'enforced_cases': enforced_cases,
                'closed_cases': closed_cases,
                'sla_breached': sla_breached,
                'sla_compliance_rate': sla_compliance_rate,
                'active_suspensions': active_suspensions,
                'suspensions_approaching_limit': suspensions_approaching_limit,
                'suspensions_over_limit': suspensions_over_limit,
                'suspensions_without_pay': active_suspensions,
                'suspensions_with_pay': 0,
                'pending_appeals': pending_appeals,
                'active_investigations': active_investigations,
                'active_committee_meetings': active_committee_meetings,
                'payroll_pending_count': payroll_data['pending_count'],
                'payroll_pending_amount': payroll_data['pending_amount'],
                'payroll_total_recovery': payroll_data['total_recovery'],
                'payroll_total_sanctions': payroll_data['total_sanctions_amount'],
                'managerial_cases': managerial_cases,
                'managerial_pct': managerial_pct,
                'non_managerial_cases': non_managerial_cases,
                'non_managerial_pct': non_managerial_pct,
                'coach_track_cases': coach_track_cases,
                'coach_track_pct': coach_track_pct,
                'committee_track_cases': committee_track_cases,
                'committee_track_pct': committee_track_pct,
            },
            'pipeline_stages': pipeline_stages,
            'investigation_stages': investigation_stages,
            'appeal_stages': appeal_stages,
            'committee_stages': committee_stages,
            'upcoming_meetings': upcoming_meetings,
            'sla_aging': {
                'under_7': aging_under_7,
                'from_7_to_15': aging_7_to_15,
                'from_16_to_30': aging_16_to_30,
                'over_30_breached': aging_over_30,
                'active_total': active_cases,
            },
            'severity_matrix': severity_matrix,
            'misconduct_breakdown': misconduct_breakdown,
            'department_hotspots': department_hotspots,
            'appeal_audit': appeal_audit,
            'payroll_governance': payroll_data,
            'department_options': department_options,
            'unit_options': unit_options,
            'unit_groups': unit_groups,
            'unit_label': unit_label,
            'level': level,
            'selected_entity_id': entity_id or effective_filter or '',
            'selected_sub_unit_id': sub_unit_id or '',
            'search_term': search_term or '',
            'selectedPeriod': period,
            'show_unit_filter': show_unit_filter,
            'selected_unit_id': effective_filter or '',
            'is_employee_only': is_employee_only,
            'employee_compliance': {
                'warning_count': emp.disciplinary_warning_count if emp else 0,
                'last_action_date': fields.Date.to_string(emp.last_disciplinary_date) if emp and emp.last_disciplinary_date else False,
                'is_suspended': emp.is_suspended if emp else False,
                'suspension_type': emp.suspension_type if emp else False,
                'is_ineligible': emp.is_ineligible_for_promotion_transfer if emp else False,
            } if is_employee_only else {},
            'employee_cases': employee_cases_list,
            'employee_standing': employee_standing,
            'is_governance_user': is_global_governance,
            'is_executive': is_executive,
            'is_secretary': is_secretary_only,
            'executive_boss_name': executive_boss_name,
            'executive_boss_title': executive_boss_title,
            'secretary_followup': secretary_followup,
            'is_auditor': is_auditor,
            'is_director': is_director,
            'is_manager_only': is_manager_only,
            'show_hierarchy_filter': show_hierarchy_filter,
            'selectedHierarchyScope': hierarchy_scope,
            'hierarchy_team_count': hierarchy_team_count,
            'direct_reports_count': direct_reports_count,
            'user_role': user_role,
            'user_title': user_title,
            'user_department': user_department,
            'chart_data': chart_data,
            'velocity_trend': velocity_trend,
            'action_watchlist': action_watchlist,
            'risk_matrix': risk_matrix,
            'active_date_from': fields.Date.to_string(date_from) if date_from else False,
            'active_date_to': fields.Date.to_string(date_to) if date_to else False,
        }
