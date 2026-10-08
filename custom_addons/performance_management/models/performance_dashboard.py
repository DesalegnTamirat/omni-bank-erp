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
            counts = {'draft': 0, 'notified': 0, 'accepted': 0, 'confirmed': 0, 'rejected': 0, 'total': len(records)}
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
                    'title': 'Division & Unit (Tier 2)',
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

            score = getattr(app, 'employee_score', 0.0) or 0.0
            rating = getattr(app, 'performance_rating', False) or 'Not Rated'

            if score > 0 or state in ('accepted', 'confirmed'):
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
        app_completion_rate = round((app_counts.get('confirmed', 0) / total_app_count * 100), 1) if total_app_count > 0 else 0.0

        total_sc_count = len(all_scorecards)
        sc_completion_rate = round(((sc_counts.get('confirmed', 0) + sc_counts.get('appraisal_started', 0)) / total_sc_count * 100), 1) if total_sc_count > 0 else 0.0

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

        return {
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
