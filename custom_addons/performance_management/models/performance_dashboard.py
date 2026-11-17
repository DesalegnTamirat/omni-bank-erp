# -*- coding: utf-8 -*-
from odoo import models, fields, api
from collections import defaultdict


class PerformanceDashboard(models.Model):
    _name = 'performance.dashboard'
    _description = 'Performance Dashboard Data Engine'

    @api.model
    def get_dashboard_data(self, filters=None):
        filters = filters or {}
        fiscal_year_id = filters.get('fiscal_year_id')
        appraisal_period_id = filters.get('appraisal_period_id')
        tier = filters.get('tier', 'all')
        operating_unit_id = filters.get('operating_unit_id')
        department_id = filters.get('department_id')

        # 1. Fetch available filter options and user role
        user = self.env.user
        emp = user.employee_id
        is_admin = user.has_group('performance_management.group_performance_admin') or user.has_group('base.group_system') or self.env.is_admin()
        is_planning = user.has_group('performance_management.group_performance_planning')
        is_hr = user.has_group('performance_management.group_performance_hr')

        is_t2_manager = False
        is_t3_manager = False
        tier_readonly = False
        operating_unit_readonly = False
        user_role_label = 'Enterprise Monitoring (Planning & HR)'
        ou_rec = None

        if not (is_admin or is_planning or is_hr):
            # Check if user is a Tier 2 Manager (manages an operating unit or holds a T2 scorecard)
            managed_ous = self.env['operating.unit'].search([('manager_id', '=', emp.id)]) if emp else self.env['operating.unit']
            is_t2_sc_holder = self.env['t2.scorecard'].search_count([('employee_id', '=', emp.id)]) > 0 if emp else False
            
            if managed_ous or is_t2_sc_holder:
                is_t2_manager = True
                tier = 't2'
                tier_readonly = True
                operating_unit_readonly = True
                user_role_label = 'Work Unit Monitoring (Tier 2 Manager)'
                ou_rec = managed_ous[0] if managed_ous else (emp.default_operating_unit_id or (emp.operating_unit_ids and emp.operating_unit_ids[0]))
                operating_unit_id = ou_rec.id if ou_rec else None
            else:
                is_t3_manager = True
                tier = 't3'
                tier_readonly = True
                operating_unit_readonly = True
                user_role_label = 'Team Monitoring (Tier 3 Manager)'
                ou_rec = emp.default_operating_unit_id if (emp and emp.default_operating_unit_id) else (emp.operating_unit_ids[0] if (emp and emp.operating_unit_ids) else False)
                operating_unit_id = ou_rec.id if ou_rec else None

        FiscalYear = self.env['performance.fiscal.year']
        Period = self.env['appraisal.period']
        OperatingUnit = self.env['operating.unit']
        Department = self.env['hr.department']

        all_fy = FiscalYear.search([], order='id desc')
        all_periods = Period.search([], order='id asc')
        if operating_unit_readonly and ou_rec:
            all_ou = ou_rec
        else:
            all_ou = OperatingUnit.search([], order='name asc')
        all_dept = Department.search([], order='name asc')

        if not fiscal_year_id and all_fy:
            fiscal_year_id = all_fy[0].id

        # Determine if Department Filter should be displayed:
        # 1. Managers (Tier 2 and Tier 3) monitor work units/teams, so department filter is not applicable.
        # 2. When a Branch operating unit is selected, department filter is not applicable.
        is_manager = is_t2_manager or is_t3_manager

        current_ou = None
        if operating_unit_id and operating_unit_id != 'all':
            try:
                current_ou = OperatingUnit.browse(int(operating_unit_id))
            except (ValueError, TypeError):
                pass
        elif ou_rec:
            current_ou = ou_rec

        is_branch = bool(current_ou and getattr(current_ou, 'work_unit_type', False) in ('branch', 'sub_branch', 'service_center'))
        show_department_filter = not is_manager and not is_branch

        if not show_department_filter:
            department_id = None

        # 2. Build domain helper
        def build_domain(model_name):
            domain = []
            if fiscal_year_id and fiscal_year_id != 'all':
                try:
                    domain.append(('fiscal_year_id', '=', int(fiscal_year_id)))
                except (ValueError, TypeError):
                    pass
            if appraisal_period_id and appraisal_period_id != 'all':
                try:
                    domain.append(('appraisal_period_id', '=', int(appraisal_period_id)))
                except (ValueError, TypeError):
                    pass
            if operating_unit_id and operating_unit_id != 'all':
                if 'operating_unit_id' in self.env[model_name]._fields:
                    try:
                        domain.append(('operating_unit_id', '=', int(operating_unit_id)))
                    except (ValueError, TypeError):
                        pass
            if show_department_filter and department_id and department_id != 'all':
                if 'department_id' in self.env[model_name]._fields:
                    try:
                        domain.append(('department_id', '=', int(department_id)))
                    except (ValueError, TypeError):
                        pass

            # Manager specific filtering:
            if is_t3_manager and emp:
                if model_name in ('t3.scorecard', 't3.appraisal'):
                    domain.extend(['|', '|', ('manager_id', '=', emp.id), ('employee_id.parent_id', '=', emp.id), ('employee_id.coach_id', '=', emp.id)])
            elif is_t2_manager and emp:
                if model_name in ('t2.scorecard', 't2.appraisal'):
                    if not operating_unit_id:
                        domain.append(('employee_id', '=', emp.id))

            return domain

        # Helper to compute status counts
        def get_status_counts(records, is_scorecard=False):
            counts = {'draft': 0, 'notified': 0, 'accepted': 0, 'auto_accepted': 0, 'confirmed': 0, 'rejected': 0, 'total': len(records)}
            for r in records:
                st = r.state or 'draft'
                if is_scorecard and st == 'appraisal_started':
                    counts['confirmed'] = counts.get('confirmed', 0) + 1
                elif st in counts:
                    counts[st] += 1
                else:
                    counts[st] = counts.get(st, 0) + 1
            return counts

        # 3. Retrieve Tier-Specific Records
        t1_sc_records = []
        t1_app_records = []
        t2_sc_records = []
        t2_app_records = []
        t3_sc_records = []
        t3_app_records = []

        if not is_t2_manager and not is_t3_manager:
            try:
                t1_sc_records = self.env['corporate.scorecard'].search(build_domain('corporate.scorecard'))
                t1_app_records = self.env['corporate.appraisal'].search(build_domain('corporate.appraisal'))
            except Exception:
                pass

        if not is_t3_manager:
            try:
                t2_sc_records = self.env['t2.scorecard'].search(build_domain('t2.scorecard'))
                t2_app_records = self.env['t2.appraisal'].search(build_domain('t2.appraisal'))
            except Exception:
                pass

        if not is_t2_manager:
            try:
                t3_sc_records = self.env['t3.scorecard'].search(build_domain('t3.scorecard'))
                t3_app_records = self.env['t3.appraisal'].search(build_domain('t3.appraisal'))
            except Exception:
                pass

        # Build Tier Governance Breakdown Data
        tier_governance = {
            'planning': {
                'tier1': {
                    'title': 'Corporate (Tier 1)',
                    'subtitle': 'Enterprise Strategic Execution',
                    'model_sc': 'corporate.scorecard',
                    'model_app': 'corporate.appraisal',
                    'scorecards': get_status_counts(t1_sc_records, is_scorecard=True),
                    'appraisals': get_status_counts(t1_app_records, is_scorecard=False),
                },
                'tier2': {
                    'title': 'Work Units (Tier 2)',
                    'subtitle': 'Work Unit Cascaded Goals',
                    'model_sc': 't2.scorecard',
                    'model_app': 't2.appraisal',
                    'scorecards': get_status_counts(t2_sc_records, is_scorecard=True),
                    'appraisals': get_status_counts(t2_app_records, is_scorecard=False),
                }
            },
            'hr': {
                'tier3': {
                    'title': 'Individual Employee (Tier 3)',
                    'subtitle': 'Employee Operational Performance',
                    'model_sc': 't3.scorecard',
                    'model_app': 't3.appraisal',
                    'scorecards': get_status_counts(t3_sc_records, is_scorecard=True),
                    'appraisals': get_status_counts(t3_app_records, is_scorecard=False),
                }
            }
        }

        # 4. Filtered combined lists based on selected tier
        all_scorecards = []
        all_appraisals = []

        if tier in ('all', 't1'):
            for r in t1_sc_records:
                all_scorecards.append(('corporate.scorecard', 'Tier 1', r))
            for r in t1_app_records:
                all_appraisals.append(('corporate.appraisal', 'Tier 1', r))

        if tier in ('all', 't2'):
            for r in t2_sc_records:
                all_scorecards.append(('t2.scorecard', 'Tier 2', r))
            for r in t2_app_records:
                all_appraisals.append(('t2.appraisal', 'Tier 2', r))

        if tier in ('all', 't3'):
            for r in t3_sc_records:
                all_scorecards.append(('t3.scorecard', 'Tier 3', r))
            for r in t3_app_records:
                all_appraisals.append(('t3.appraisal', 'Tier 3', r))

        # Overall Scorecard Counts & Funnel
        sc_counts = {'draft': 0, 'notified': 0, 'accepted': 0, 'confirmed': 0, 'rejected': 0, 'appraisal_started': 0}
        for _, _, sc in all_scorecards:
            state = sc.state or 'draft'
            sc_counts[state] = sc_counts.get(state, 0) + 1

        # Overall Appraisal Counts, Scores, and Ratings
        app_counts = {'draft': 0, 'notified': 0, 'accepted': 0, 'confirmed': 0, 'rejected': 0}
        total_score_sum = 0.0
        scored_appraisal_count = 0
        rating_counts = defaultdict(int)
        dept_scores = defaultdict(lambda: {'sum': 0.0, 'count': 0})
        ou_scores = defaultdict(lambda: {'sum': 0.0, 'count': 0})

        rejections_list = []
        pending_list = []
        top_performers = []

        for model_name, tier_name, app in all_appraisals:
            state = app.state or 'draft'
            app_counts[state] = app_counts.get(state, 0) + 1

            score = (getattr(app, 'average_score', False) if getattr(app, 'work_unit_score', 0.0) else False) or getattr(app, 'employee_score', 0.0) or 0.0
            rating = getattr(app, 'performance_rating', False) or 'Not Rated'

            if score > 0 or state in ('accepted', 'auto_accepted', 'confirmed'):
                total_score_sum += score
                scored_appraisal_count += 1
                if rating:
                    rating_counts[rating] += 1

                dept_name = app.department_id.name if 'department_id' in app._fields and app.department_id else 'Corporate / General'
                dept_scores[dept_name]['sum'] += score
                dept_scores[dept_name]['count'] += 1

                ou_name = ''
                if 'operating_unit_id' in app._fields and app.operating_unit_id:
                    ou_name = app.operating_unit_id.name
                elif app.employee_id:
                    if hasattr(app.employee_id, 'default_operating_unit_id') and app.employee_id.default_operating_unit_id:
                        ou_name = app.employee_id.default_operating_unit_id.name
                    elif hasattr(app.employee_id, 'operating_unit_ids') and app.employee_id.operating_unit_ids:
                        ou_name = app.employee_id.operating_unit_ids[0].name
                if not ou_name:
                    ou_name = 'Head Office'

                ou_scores[ou_name]['sum'] += score
                ou_scores[ou_name]['count'] += 1

                top_performers.append({
                    'id': app.id,
                    'model': model_name,
                    'tier': tier_name,
                    'name': getattr(app, 'name', 'Appraisal'),
                    'employee_name': app.employee_id.name if app.employee_id else 'N/A',
                    'job_title': app.job_id.name if 'job_id' in app._fields and app.job_id else '',
                    'operating_unit': ou_name,
                    'department': dept_name,
                    'score': round(score, 2),
                    'rating': rating,
                    'state': state,
                })

            # Rejections
            if state == 'rejected':
                ou_name = app.operating_unit_id.name if 'operating_unit_id' in app._fields and app.operating_unit_id else ''
                if not ou_name and app.employee_id and hasattr(app.employee_id, 'default_operating_unit_id') and app.employee_id.default_operating_unit_id:
                    ou_name = app.employee_id.default_operating_unit_id.name
                rejections_list.append({
                    'id': app.id,
                    'model': model_name,
                    'tier': tier_name,
                    'type': 'Appraisal',
                    'name': getattr(app, 'name', 'Appraisal'),
                    'employee_name': app.employee_id.name if app.employee_id else 'N/A',
                    'manager_name': app.manager_id.name if 'manager_id' in app._fields and app.manager_id else (app.employee_id.coach_id.name if app.employee_id and app.employee_id.coach_id else 'N/A'),
                    'operating_unit': ou_name or 'N/A',
                    'rejection_reason': app.rejection_reason or 'No reason provided',
                })

            # Pending acceptance
            if state == 'notified':
                ou_name = app.operating_unit_id.name if 'operating_unit_id' in app._fields and app.operating_unit_id else ''
                if not ou_name and app.employee_id and hasattr(app.employee_id, 'default_operating_unit_id') and app.employee_id.default_operating_unit_id:
                    ou_name = app.employee_id.default_operating_unit_id.name
                pending_list.append({
                    'id': app.id,
                    'model': model_name,
                    'tier': tier_name,
                    'type': 'Appraisal',
                    'name': getattr(app, 'name', 'Appraisal'),
                    'employee_name': app.employee_id.name if app.employee_id else 'N/A',
                    'manager_name': app.manager_id.name if 'manager_id' in app._fields and app.manager_id else (app.employee_id.coach_id.name if app.employee_id and app.employee_id.coach_id else 'N/A'),
                    'operating_unit': ou_name or 'N/A',
                    'accept_by': str(app.accept_by) if 'accept_by' in app._fields and app.accept_by else 'N/A',
                    'score': round(score, 2),
                })

        # Also collect scorecard rejections & pending
        for model_name, tier_name, sc in all_scorecards:
            ou_name = sc.operating_unit_id.name if 'operating_unit_id' in sc._fields and sc.operating_unit_id else ''
            if not ou_name and sc.employee_id and hasattr(sc.employee_id, 'default_operating_unit_id') and sc.employee_id.default_operating_unit_id:
                ou_name = sc.employee_id.default_operating_unit_id.name
            if sc.state == 'rejected':
                rejections_list.append({
                    'id': sc.id,
                    'model': model_name,
                    'tier': tier_name,
                    'type': 'Scorecard',
                    'name': getattr(sc, 'planning_name', getattr(sc, 'name', 'Scorecard')),
                    'employee_name': sc.employee_id.name if sc.employee_id else 'N/A',
                    'manager_name': sc.manager_id.name if 'manager_id' in sc._fields and sc.manager_id else (sc.employee_id.coach_id.name if sc.employee_id and sc.employee_id.coach_id else 'N/A'),
                    'operating_unit': ou_name or 'N/A',
                    'rejection_reason': sc.rejection_reason or 'No reason provided',
                })
            elif sc.state == 'notified':
                pending_list.append({
                    'id': sc.id,
                    'model': model_name,
                    'tier': tier_name,
                    'type': 'Scorecard',
                    'name': getattr(sc, 'planning_name', getattr(sc, 'name', 'Scorecard')),
                    'employee_name': sc.employee_id.name if sc.employee_id else 'N/A',
                    'manager_name': sc.manager_id.name if 'manager_id' in sc._fields and sc.manager_id else (sc.employee_id.coach_id.name if sc.employee_id and sc.employee_id.coach_id else 'N/A'),
                    'operating_unit': ou_name or 'N/A',
                    'accept_by': str(sc.accept_by) if 'accept_by' in sc._fields and sc.accept_by else 'N/A',
                    'score': 0.0,
                })

        # Sort top performers
        top_performers.sort(key=lambda x: x['score'], reverse=True)
        top_5_performers = top_performers[:5]
        bottom_5_performers = [p for p in reversed(top_performers) if p['score'] > 0][:5]

        avg_enterprise_score = round((total_score_sum / scored_appraisal_count), 2) if scored_appraisal_count > 0 else 0.0
        total_app_count = len(all_appraisals)
        app_completion_rate = round(((app_counts.get('accepted', 0) + app_counts.get('auto_accepted', 0) + app_counts.get('confirmed', 0)) / total_app_count * 100), 1) if total_app_count > 0 else 0.0

        total_sc_count = len(all_scorecards)
        sc_completion_rate = round(((sc_counts.get('accepted', 0) + sc_counts.get('auto_accepted', 0) + sc_counts.get('confirmed', 0) + sc_counts.get('appraisal_started', 0)) / total_sc_count * 100), 1) if total_sc_count > 0 else 0.0

        # Perspective breakdown (Target vs Accomplished)
        perspective_data = defaultdict(lambda: {'target': 0.0, 'accomplished': 0.0, 'weight': 0.0})
        for _, _, app in all_appraisals:
            for line in app.line_ids:
                p_name = line.perspective_name or (line.perspective_id.name if line.perspective_id else 'General')
                perspective_data[p_name]['target'] += (line.target or 0.0)
                perspective_data[p_name]['accomplished'] += (line.uploaded_value or 0.0)
                perspective_data[p_name]['weight'] += (line.weight or 0.0)

        persp_labels = list(perspective_data.keys()) or ['Financial', 'Stakeholder', 'Internal Process', 'Learning & Growth']
        persp_targets = [round(perspective_data[p]['target'], 1) for p in persp_labels]
        persp_accomplished = [round(perspective_data[p]['accomplished'], 1) for p in persp_labels]

        # Department ranking data
        dept_labels = []
        dept_avg_scores = []
        for d_name, d_val in sorted(dept_scores.items(), key=lambda item: item[1]['sum'] / max(1, item[1]['count']), reverse=True)[:8]:
            dept_labels.append(d_name)
            dept_avg_scores.append(round(d_val['sum'] / max(1, d_val['count']), 1))

        # Operating Unit ranking data
        ou_labels = []
        ou_avg_scores = []
        for ou_name, ou_val in sorted(ou_scores.items(), key=lambda item: item[1]['sum'] / max(1, item[1]['count']), reverse=True)[:8]:
            ou_labels.append(ou_name)
            ou_avg_scores.append(round(ou_val['sum'] / max(1, ou_val['count']), 1))

        # Standard ranking categories for Bell Curve
        ranking_categories = ['Outstanding', 'Excellent', 'Satisfactory', 'Unsatisfactory']
        bell_curve_data = [
            rating_counts.get('Outstanding', 0) + rating_counts.get('outstanding', 0),
            rating_counts.get('Excellent', 0) + rating_counts.get('excellent', 0),
            rating_counts.get('Satisfactory', 0) + rating_counts.get('satisfactory', 0),
            rating_counts.get('Unsatisfactory', 0) + rating_counts.get('unsatisfactory', 0),
        ]

        # -----------------------------------------------------------
        # Position & Manager Scorecard Coverage Tracking
        # -----------------------------------------------------------
        # Collect Tier 1 (Corporate / CEO) Operating Units and Jobs to exclude from Tier 2 & Tier 3
        t1_ou_ids = set()
        t1_job_ids = set()
        for cs in self.env['corporate.scorecard'].sudo().search([]):
            if cs.operating_unit_id:
                t1_ou_ids.add(cs.operating_unit_id.id)
            if cs.employee_id:
                if getattr(cs.employee_id, 'default_operating_unit_id', False):
                    t1_ou_ids.add(cs.employee_id.default_operating_unit_id.id)
                if cs.employee_id.job_id:
                    t1_job_ids.add(cs.employee_id.job_id.id)
            if cs.job_id:
                t1_job_ids.add(cs.job_id.id)

        def is_t1_operating_unit(ou_rec):
            if ou_rec.id in t1_ou_ids:
                return True
            ou_n = (ou_rec.name or '').strip().lower()
            ou_c = (getattr(ou_rec, 'code', '') or '').strip().lower()
            return (
                ou_n in ['chief executive office', 'ceo', 'office of the ceo', 'chief executive officer']
                or 'chief executive' in ou_n
                or ou_c in ['ceo', 'ce']
            )

        def is_t1_job(job_rec):
            if job_rec.id in t1_job_ids:
                return True
            j_n = (job_rec.name or '').strip().lower()
            return (
                j_n in ['chief executive officer', 'ceo', 'chief executive officer (ceo)', 'chief executive']
                or 'chief executive' in j_n
            )

        # Tier 3: Distinct Job Positions Coverage (Excluding CEO)
        emp_domain = [('active', '=', True), ('job_id', '!=', False)]
        if operating_unit_id and operating_unit_id != 'all':
            try:
                emp_domain.append(('default_operating_unit_id', '=', int(operating_unit_id)))
            except (ValueError, TypeError):
                pass
        if show_department_filter and department_id and department_id != 'all':
            try:
                emp_domain.append(('department_id', '=', int(department_id)))
            except (ValueError, TypeError):
                pass
        if is_t3_manager and emp:
            emp_domain.extend(['|', '|', ('parent_id', '=', emp.id), ('coach_id', '=', emp.id), ('id', '=', emp.id)])

        active_employees = self.env['hr.employee'].sudo().search(emp_domain)
        job_emp_map = defaultdict(list)
        for e in active_employees:
            if e.job_id:
                job_emp_map[e.job_id.id].append(e)

        # Collect T3 scorecards for the selected period / filters
        t3_scorecard_jobs = set()
        t3_sc_job_counts = defaultdict(int)
        for sc in t3_sc_records:
            if sc.job_id:
                t3_scorecard_jobs.add(sc.job_id.id)
                t3_sc_job_counts[sc.job_id.id] += 1

        t3_all_positions = []
        t3_covered_positions = []
        t3_uncovered_positions = []

        job_ids = list(job_emp_map.keys())
        if job_ids:
            jobs = self.env['hr.job'].sudo().browse(job_ids)
            for j in jobs.sorted(lambda x: (x.name or '').lower()):
                # Exclude CEO job position from Tier 3
                if is_t1_job(j):
                    continue
                emp_count = len(job_emp_map[j.id])
                sc_count = t3_sc_job_counts.get(j.id, 0)
                has_sc = (j.id in t3_scorecard_jobs) or (sc_count > 0)
                dept_name = j.department_id.name if j.department_id else (job_emp_map[j.id][0].department_id.name if job_emp_map[j.id][0].department_id else 'General')
                pos_info = {
                    'id': j.id,
                    'title': j.name or 'Unnamed Job Position',
                    'department': dept_name,
                    'employee_count': emp_count,
                    'scorecard_count': sc_count,
                    'has_scorecard': has_sc,
                    'status': 'Covered' if has_sc else 'Missing Scorecard',
                }
                t3_all_positions.append(pos_info)
                if has_sc:
                    t3_covered_positions.append(pos_info)
                else:
                    t3_uncovered_positions.append(pos_info)

        t3_total_positions = len(t3_all_positions)
        t3_covered_count = len(t3_covered_positions)
        t3_uncovered_count = len(t3_uncovered_positions)
        t3_coverage_pct = round((t3_covered_count / t3_total_positions * 100), 1) if t3_total_positions > 0 else 0.0

        # Tier 2: Operating Units / Managers Coverage (Excluding CEO / Chief Executive Office)
        ou_search_domain = [('active', '=', True)]
        if operating_unit_id and operating_unit_id != 'all':
            try:
                ou_search_domain.append(('id', '=', int(operating_unit_id)))
            except (ValueError, TypeError):
                pass

        all_active_ous = self.env['operating.unit'].sudo().search(ou_search_domain)
        t2_scorecard_ous = set()
        t2_sc_ou_map = {}
        t2_sc_ou_id_map = {}
        for sc in t2_sc_records:
            if sc.operating_unit_id:
                t2_scorecard_ous.add(sc.operating_unit_id.id)
                t2_sc_ou_map[sc.operating_unit_id.id] = sc.state or 'draft'
                t2_sc_ou_id_map[sc.operating_unit_id.id] = sc.id

        t2_all_units = []
        t2_covered_units = []
        t2_uncovered_units = []

        wut_dict = dict(self.env['operating.unit']._fields['work_unit_type'].selection) if 'work_unit_type' in self.env['operating.unit']._fields else {}

        for ou in all_active_ous.sorted(lambda x: (x.name or '').lower()):
            # Exclude Chief Executive Office (Tier 1 Corporate OU) from Tier 2
            if is_t1_operating_unit(ou):
                continue
            has_sc = ou.id in t2_scorecard_ous
            mgr_name = ou.manager_id.name if ou.manager_id else 'No Manager Assigned'
            wut_label = wut_dict.get(getattr(ou, 'work_unit_type', ''), getattr(ou, 'work_unit_type', 'Operating Unit') or 'Operating Unit')
            unit_info = {
                'id': ou.id,
                'title': ou.name or 'Unnamed Operating Unit',
                'work_unit_type': wut_label,
                'manager_name': mgr_name,
                'has_scorecard': has_sc,
                'status': 'Covered' if has_sc else 'Missing Scorecard',
                'state': t2_sc_ou_map.get(ou.id, 'none'),
                'scorecard_id': t2_sc_ou_id_map.get(ou.id, False),
            }
            t2_all_units.append(unit_info)
            if has_sc:
                t2_covered_units.append(unit_info)
            else:
                t2_uncovered_units.append(unit_info)

        t2_total_units = len(t2_all_units)
        t2_covered_count = len(t2_covered_units)
        t2_uncovered_count = len(t2_uncovered_units)
        t2_coverage_pct = round((t2_covered_count / t2_total_units * 100), 1) if t2_total_units > 0 else 0.0

        # Tier 1: Corporate / CEO
        t1_has_sc = len(t1_sc_records) > 0
        t1_state = t1_sc_records[0].state if t1_has_sc else 'none'
        t1_state_label = dict(self.env['corporate.scorecard']._fields['state'].selection).get(t1_state, t1_state) if t1_has_sc and 'state' in self.env['corporate.scorecard']._fields else 'Not Created'
        t1_ceo_info = {
            'id': t1_sc_records[0].id if t1_has_sc else False,
            'title': 'Chief Executive Officer (CEO)',
            'role': 'Enterprise Leadership',
            'department': 'Corporate Executive Office',
            'manager_name': 'Board of Directors',
            'employee_count': 1,
            'scorecard_count': 1 if t1_has_sc else 0,
            'has_scorecard': t1_has_sc,
            'status': 'Covered' if t1_has_sc else 'Missing Scorecard',
            'state': t1_state,
            'state_label': t1_state_label,
            'scorecard_id': t1_sc_records[0].id if t1_has_sc else False,
        }
        t1_all = [t1_ceo_info]
        t1_covered = [t1_ceo_info] if t1_has_sc else []
        t1_uncovered = [] if t1_has_sc else [t1_ceo_info]

        return {
            'position_coverage': {
                'tier1': {
                    'ceo': t1_ceo_info,
                    'all': t1_all,
                    'covered': t1_covered,
                    'uncovered': t1_uncovered,
                    'covered_count': 1 if t1_has_sc else 0,
                    'uncovered_count': 0 if t1_has_sc else 1,
                    'total': 1,
                    'coverage_pct': 100.0 if t1_has_sc else 0.0,
                },
                'tier2': {
                    'all': t2_all_units,
                    'covered': t2_covered_units,
                    'uncovered': t2_uncovered_units,
                    'covered_count': t2_covered_count,
                    'uncovered_count': t2_uncovered_count,
                    'total': t2_total_units,
                    'coverage_pct': t2_coverage_pct,
                },
                'tier3': {
                    'all': t3_all_positions,
                    'covered': t3_covered_positions,
                    'uncovered': t3_uncovered_positions,
                    'covered_count': t3_covered_count,
                    'uncovered_count': t3_uncovered_count,
                    'total': t3_total_positions,
                    'coverage_pct': t3_coverage_pct,
                },
            },
            'filters': {
                'fiscal_years': [{'id': fy.id, 'name': fy.name} for fy in all_fy],
                'appraisal_periods': [{'id': p.id, 'name': p.name, 'code': p.code} for p in all_periods],
                'operating_units': [{'id': ou.id, 'name': ou.name} for ou in all_ou],
                'departments': [{'id': d.id, 'name': d.name} for d in all_dept],
                'selected_fiscal_year_id': fiscal_year_id,
                'selected_appraisal_period_id': appraisal_period_id,
                'selected_tier': tier,
                'selected_operating_unit_id': operating_unit_id,
                'selected_department_id': department_id,
                'tier_readonly': tier_readonly,
                'operating_unit_readonly': operating_unit_readonly,
                'user_role_label': user_role_label,
                'is_manager': is_manager,
                'show_department_filter': show_department_filter,
            },
            'kpis': {
                'total_scorecards': total_sc_count,
                'sc_completion_rate': sc_completion_rate,
                'total_appraisals': total_app_count,
                'app_completion_rate': app_completion_rate,
                'average_score': avg_enterprise_score,
                'pending_count': len(pending_list),
                'rejected_count': len(rejections_list),
                'confirmed_appraisals': app_counts.get('confirmed', 0),
            },
            'tier_governance': tier_governance,
            'funnel': {
                'scorecards': sc_counts,
                'appraisals': app_counts,
            },
            'charts': {
                'bell_curve': {
                    'labels': ranking_categories,
                    'data': bell_curve_data,
                },
                'perspective': {
                    'labels': persp_labels,
                    'target': persp_targets,
                    'accomplished': persp_accomplished,
                },
                'department_scores': {
                    'labels': dept_labels,
                    'data': dept_avg_scores,
                },
                'ou_scores': {
                    'labels': ou_labels,
                    'data': ou_avg_scores,
                }
            },
            'tables': {
                'top_performers': top_5_performers,
                'bottom_performers': bottom_5_performers,
                'rejections': rejections_list[:15],
                'pending': pending_list[:15],
            }
        }
