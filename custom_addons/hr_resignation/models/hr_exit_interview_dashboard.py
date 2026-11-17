# -*- coding: utf-8 -*-
from odoo import api, fields, models
from collections import Counter
import re
import logging

_logger = logging.getLogger(__name__)


class HrExitInterviewDashboard(models.AbstractModel):
    _name = 'hr.exit.interview.dashboard'
    _description = 'Exit Interview Dashboard Data'

    # ─── DOMAIN BUILDERS ─────────────────────────────────────────────────────

    @api.model
    def _get_work_unit_domain(self, ou_val, prefix=''):
        """
        Build a robust domain to match an interview or line by work unit / operating unit.
        prefix: '' for hr.exit.interview, 'interview_id.' for hr.exit.interview.line.
        """
        if not ou_val or ou_val == 'all':
            return []

        clauses = [
            (f"{prefix}employee_id.department_id.name", "=", ou_val),
            (f"{prefix}employee_id.default_operating_unit_id.name", "=", ou_val),
            (f"{prefix}employee_id.department_id.operating_unit_id.name", "=", ou_val),
            (f"{prefix}employee_id.operating_unit_ids.name", "=", ou_val),
            (f"{prefix}resignation_id.operating_unit_id.name", "=", ou_val),
            (f"{prefix}resignation_id.department_id.name", "=", ou_val),
        ]
        if 'operating_unit_id' in self.env['hr.employee']._fields:
            clauses.append((f"{prefix}employee_id.operating_unit_id.name", "=", ou_val))

        domain = ['|'] * (len(clauses) - 1)
        domain.extend(clauses)
        return domain

    @api.model
    def _get_position_domain(self, pos_val, prefix=''):
        """
        Build a domain matching an employee's job position.
        prefix: '' for hr.exit.interview, 'interview_id.' for hr.exit.interview.line.
        """
        if not pos_val or pos_val == 'all':
            return []

        clauses = [
            (f"{prefix}employee_id.job_id.name", "=", pos_val),
            (f"{prefix}employee_id.job_position.name", "=", pos_val),
        ]
        domain = ['|'] * (len(clauses) - 1)
        domain.extend(clauses)
        return domain

    # ─── FILTER OPTIONS ──────────────────────────────────────────────────────

    @api.model
    def get_filter_options(self):
        """Return distinct values for the filter dropdowns."""
        ou_names = set()

        # 1. Operating units (Work Units)
        if 'operating.unit' in self.env:
            ous = self.env['operating.unit'].search([])
            ou_names.update(ou.name for ou in ous if ou.name)

        # 2. Departments (Work Units / Directorates / Divisions)
        if 'hr.department' in self.env:
            depts = self.env['hr.department'].search([])
            ou_names.update(d.name for d in depts if d.name)

        # 3. Work units from interviews and resignations
        interviews = self.env['hr.exit.interview'].search([])
        for iv in interviews:
            emp = iv.employee_id
            if emp:
                if emp.department_id and emp.department_id.name:
                    ou_names.add(emp.department_id.name)
                if hasattr(emp, 'default_operating_unit_id') and emp.default_operating_unit_id and emp.default_operating_unit_id.name:
                    ou_names.add(emp.default_operating_unit_id.name)
                if hasattr(emp, 'operating_unit_ids') and emp.operating_unit_ids:
                    ou_names.update(ou.name for ou in emp.operating_unit_ids if ou.name)
            resig = iv.resignation_id
            if resig:
                if hasattr(resig, 'operating_unit_id') and resig.operating_unit_id and resig.operating_unit_id.name:
                    ou_names.add(resig.operating_unit_id.name)
                if hasattr(resig, 'department_id') and resig.department_id and resig.department_id.name:
                    ou_names.add(resig.department_id.name)

        ou_opts = [{'value': d, 'label': d} for d in sorted(ou_names)]

        # Separation types (All active ones)
        sep_types = set()
        if 'hr.separation.type' in self.env:
            stypes = self.env['hr.separation.type'].search([])
            sep_types.update(s.name for s in stypes if s.name)
        for iv in interviews:
            if iv.resignation_id and iv.resignation_id.resignation_type_id and iv.resignation_id.resignation_type_id.name:
                sep_types.add(iv.resignation_id.resignation_type_id.name)
        sep_opts = [{'value': s, 'label': s} for s in sorted(sep_types)]

        # Job positions
        positions = set()
        all_jobs = self.env['hr.job'].search([])
        positions.update(j.name for j in all_jobs if j.name)
        for iv in interviews:
            emp = iv.employee_id
            if emp:
                if emp.job_id and emp.job_id.name:
                    positions.add(emp.job_id.name)
                elif hasattr(emp, 'job_position') and emp.job_position and emp.job_position.name:
                    positions.add(emp.job_position.name)
        pos_opts = [{'value': p, 'label': p} for p in sorted(positions)]

        return {
            'operating_units': ou_opts,
            'separation_types': sep_opts,
            'positions': pos_opts,
        }

    # ─── MAIN ANALYTICS ──────────────────────────────────────────────────────

    @api.model
    def get_analytics_data(self, filters=None):
        """
        Compute all analytics for the dashboard.
        filters: dict with optional keys:
            operating_unit - work unit or operating unit name
            position     - job position name
            sep_type     - separation type name
        """
        if filters is None:
            filters = {}

        # ── Build domain ────────────────────────────────────────────────────
        domain = [('state', '=', 'completed')]
        all_domain = [('resignation_id', '!=', False)]

        ou_val = filters.get('operating_unit', '')
        if ou_val and ou_val != 'all':
            ou_domain = self._get_work_unit_domain(ou_val)
            domain.extend(ou_domain)
            all_domain.extend(ou_domain)

        pos_val = filters.get('position', '')
        if pos_val and pos_val != 'all':
            pos_domain = self._get_position_domain(pos_val)
            domain.extend(pos_domain)
            all_domain.extend(pos_domain)

        sep_val = filters.get('sep_type', '')
        if sep_val and sep_val != 'all':
            sep_clause = ('resignation_id.resignation_type_id.name', '=', sep_val)
            domain.append(sep_clause)
            all_domain.append(sep_clause)

        interviews = self.env['hr.exit.interview'].search(domain)
        total = len(interviews)

        all_count = self.env['hr.exit.interview'].search_count(all_domain)
        completion_pct = round(total / all_count * 100) if all_count else 0
        if completion_pct > 100:
            completion_pct = 100

        if total == 0:
            return {
                'kpis': {
                    'total': 0,
                    'completion_pct': 0,
                    'recommend_pct': 0,
                    'regrettable_pct': 0,
                    'avg_sat': '—',
                    'avg_tenure': '—',
                    'avg_tenure_median': '—',
                },
                'bars': [],
                'keeps': [],
                'donuts': [],
                'cg': "#e5e7eb 0% 100%",
                'likerts': [],
                'yes_no': [],
                'text_qs': [],
                'interviews': [],
            }

        lines = self.env['hr.exit.interview.line'].search(
            [('interview_id', 'in', interviews.ids)])

        # ── Helpers ─────────────────────────────────────────────────────────
        def q_lines(keyword, q_type=None):
            kw = keyword.lower()
            res = [l for l in lines if kw in (l.question_name or '').lower()]
            if q_type:
                res = [l for l in res if l.question_type == q_type]
            return res

        def choice_tally(line_list):
            counts = {}
            for l in line_list:
                opts = []
                if l.answer:
                    if l.question_type == 'checkbox':
                        opts = [x.strip() for x in l.answer.split(',')]
                    else:
                        opts = [l.answer]
                for o in opts:
                    if isinstance(o, list) and len(o) > 0:
                        o = o[0]
                    if isinstance(o, dict):
                        o = o.get('en_US') or o.get('en') or next(iter(o.values()), str(o))
                    if isinstance(o, (list, dict)):
                        o = str(o)

                    if not isinstance(o, str):
                        o = str(o)

                    counts[o] = counts.get(o, 0) + 1
            return counts

        # ── KPIs ─────────────────────────────────────────────────────────────

        # Would recommend — question: "Would you recommend Bunna Bank as a good place to work?"
        # Answer types: boolean (yes/no), custom (Highly recommend, Recommend, etc.)
        rec_lines = q_lines('recommend')
        positive_answers = {'yes', 'agree', 'highly recommend', 'recommend'}
        rec_yes = sum(
            1 for l in rec_lines
            if (l.boolean_value or '').lower() == 'yes'
            or (l.answer or '').lower() in positive_answers
            or any(w in (l.answer or '').lower() for w in ('recommend',))
        )
        recommend_pct = round(rec_yes / len(rec_lines) * 100) if rec_lines else 0

        # Regrettable exits (High performance rating from resignation)
        regrettable_count = sum(
            1 for i in interviews
            if i.resignation_id and
            getattr(i.resignation_id, 'performance_rating', None) in ('high', 'excellent')
        )
        regrettable_pct = round(regrettable_count / total * 100) if total else 0

        # Avg tenure
        from datetime import date
        tenure_months = []
        for i in interviews:
            emp = i.employee_id
            if emp.date_start:
                ref = i.interview_date or date.today()
                months = (ref.year - emp.date_start.year) * 12 + \
                         (ref.month - emp.date_start.month)
                if months > 0:
                    tenure_months.append(months)

        if tenure_months:
            avg_m = sum(tenure_months) / len(tenure_months)
            sorted_m = sorted(tenure_months)
            mid = len(sorted_m) // 2
            med_m = sorted_m[mid]
            avg_yrs = f"{avg_m / 12:.1f} yrs"
            med_yrs = f"Median {med_m / 12:.1f}"
        else:
            avg_yrs = '—'
            med_yrs = '—'

        # Avg satisfaction (all rating/satisfaction questions)
        all_ratings = []
        rating_map = {'excellent': 5, 'good': 4, 'fair': 3, 'poor': 1,
                      'very_satisfied': 5, 'satisfied': 4, 'neutral': 3,
                      'dissatisfied': 2, 'very_dissatisfied': 1}
        for l in lines:
            if l.question_type == 'rating' and l.rating_value:
                v = rating_map.get(l.rating_value)
                if v:
                    all_ratings.append(v)
            elif l.question_type == 'satisfaction' and l.satisfaction_value:
                v = rating_map.get(l.satisfaction_value)
                if v:
                    all_ratings.append(v)

        avg_sat = round(sum(all_ratings) / len(all_ratings), 1) if all_ratings else 0.0

        # ── Primary reason for leaving ────────────────────────────────────
        # Matches: "What is the MAIN reason you are leaving? (select all that apply)"
        reason_keywords = ['main reason', 'reason you are leaving', 'reason for leaving',
                           'primary reason', 'why leaving']
        reason_lines = []
        for kw in reason_keywords:
            reason_lines = q_lines(kw)
            if reason_lines:
                break

        reason_tally = choice_tally(reason_lines)
        # Also catch text answers
        for l in reason_lines:
            if l.question_type == 'text' and l.text_value:
                reason_tally[l.text_value.strip()] = reason_tally.get(l.text_value.strip(), 0) + 1

        bars = sorted(
            [{'l': k, 'v': round(v / total * 100)} for k, v in reason_tally.items()],
            key=lambda x: x['v'], reverse=True
        )[:8]

        # ── What would have kept you ──────────────────────────────────────
        # Matches: "Is there anything the company could have done differently to retain you?"
        keep_keywords = ['retain you', 'kept you', 'keep you', 'differently to retain',
                         'could have done', 'retained', 'retain']
        keep_lines = []
        for kw in keep_keywords:
            keep_lines = q_lines(kw)
            if keep_lines:
                break

        keep_tally = choice_tally(keep_lines)
        # Also catch text answers for open-ended keep questions
        for l in keep_lines:
            if l.question_type == 'text' and l.text_value and l.text_value.strip():
                keep_tally[l.text_value.strip()[:60]] = keep_tally.get(l.text_value.strip()[:60], 0) + 1

        keeps = sorted(
            [{'l': k, 'v': round(v / total * 100)} for k, v in keep_tally.items()],
            key=lambda x: x['v'], reverse=True
        )[:6]

        # ── Destination / Sector ─────────────────────────────────────────
        # Matches: "Which sector will you be joining next?"
        dest_keywords = ['sector will you', 'joining next', 'going next', 'next sector',
                         'sector', 'destination', 'next employer']
        dest_lines = []
        for kw in dest_keywords:
            dest_lines = q_lines(kw)
            if dest_lines:
                break

        dest_tally = choice_tally(dest_lines)
        donut_colors = ['#425727', '#c17540', '#726732', '#1d2b32', '#541718', '#1e2917']
        donuts = []
        total_dest = sum(dest_tally.values()) or 1
        for idx, (k, v) in enumerate(sorted(dest_tally.items(), key=lambda x: x[1], reverse=True)[:6]):
            donuts.append({
                'l': k,
                'v': round(v / total_dest * 100),
                'c': donut_colors[idx % len(donut_colors)],
            })

        # Build conic-gradient string for donut
        cg_parts = []
        acc = 0
        for d in donuts:
            end = acc + d['v']
            cg_parts.append(f"{d['c']} {acc}% {end}%")
            acc = end
        cg = ','.join(cg_parts) if cg_parts else '#e5e7eb 0% 100%'

        # ── Satisfaction / Likert ─────────────────────────────────────────
        # Group all rating/satisfaction/agreement questions
        q_groups = {}
        for l in lines:
            if l.question_type in ('rating', 'satisfaction', 'agreement'):
                qn = l.question_name or ''
                if isinstance(qn, dict): qn = qn.get('en_US', str(qn))
                qn = str(qn).strip()
                if qn not in q_groups:
                    q_groups[qn] = {'type': l.question_type, 'vals': []}
                v = None
                if l.question_type == 'rating':
                    v = rating_map.get(l.rating_value)
                elif l.question_type == 'satisfaction':
                    v = rating_map.get(l.satisfaction_value)
                elif l.question_type == 'agreement':
                    ag = {'strongly_agree': 5, 'agree': 4, 'disagree': 2, 'strongly_disagree': 1}
                    v = ag.get(l.agreement_value)
                if v:
                    q_groups[qn]['vals'].append(v)

        likerts = []
        for qn, data in q_groups.items():
            vals = data['vals']
            if not vals:
                continue
            avg_v = sum(vals) / len(vals)
            # Distribution across 5 buckets (Likert 1-5)
            dist = [0, 0, 0, 0, 0]
            for v in vals:
                idx = min(max(int(v) - 1, 0), 4)
                dist[idx] += 1
            pct_dist = [round(d / len(vals) * 100) for d in dist]
            likerts.append({
                'id': qn,  # Unique key for XML
                'l': qn[:50],  # Truncated string for UI
                'm': round(avg_v, 1),
                'vals': pct_dist,
            })
        likerts = likerts[:6]

        # ── Yes / No questions ────────────────────────────────────────────
        yes_no_qs = {}
        for l in lines:
            if l.question_type in ('boolean', 'boolean_agree'):
                qn = l.question_name or ''
                if isinstance(qn, dict): qn = qn.get('en_US', str(qn))
                qn = str(qn).strip()
                if qn not in yes_no_qs:
                    yes_no_qs[qn] = {'yes': 0, 'no': 0}
                v = (l.boolean_value or '').lower()
                if v == 'yes':
                    yes_no_qs[qn]['yes'] += 1
                elif v == 'no':
                    yes_no_qs[qn]['no'] += 1

        yes_no = []
        for qn, counts in yes_no_qs.items():
            total_yn = counts['yes'] + counts['no']
            if total_yn == 0:
                continue
            yes_pct = round(counts['yes'] / total_yn * 100)
            yes_no.append({
                'id': qn,  # Unique key for XML
                'l': qn[:55],  # Truncated string for UI
                'yes': yes_pct,
                'no': 100 - yes_pct
            })

        # ── Text questions (Grouped) ──────────────────────────────────────
        text_qs_dict = {}
        for l in lines:
            if l.question_type == 'text' and l.text_value and len(l.text_value.strip()) > 5:
                qn = l.question_name or ''
                if isinstance(qn, dict): qn = qn.get('en_US', str(qn))
                qn = str(qn).strip()
                if qn not in text_qs_dict:
                    text_qs_dict[qn] = {'count': 0, 'sample': []}
                text_qs_dict[qn]['count'] += 1
                if len(text_qs_dict[qn]['sample']) < 5:
                    text_qs_dict[qn]['sample'].append(l.text_value.strip()[:180])

        text_qs = []
        for i, (qn, data) in enumerate(text_qs_dict.items()):
            text_qs.append({
                'id': i,
                'l': qn,
                'count': data['count'],
                'sample': data['sample']
            })

        # ── Interview list for the table ──────────────────────────────────
        interview_list = []
        for i in interviews:
            emp = i.employee_id
            pos_name = (emp.job_id.name if emp.job_id else False) or (emp.job_position.name if hasattr(emp, 'job_position') and emp.job_position else False) or '—'
            dept_name = emp.department_id.name if emp.department_id else ''
            ou_name = (
                (emp.default_operating_unit_id.name if hasattr(emp, 'default_operating_unit_id') and emp.default_operating_unit_id else False)
                or (emp.department_id.operating_unit_id.name if emp.department_id and hasattr(emp.department_id, 'operating_unit_id') and emp.department_id.operating_unit_id else False)
                or (i.resignation_id.operating_unit_id.name if i.resignation_id and hasattr(i.resignation_id, 'operating_unit_id') and i.resignation_id.operating_unit_id else False)
                or ''
            )
            interview_list.append({
                'id': i.id,
                'name': emp.name or '—',
                'emp_id': str(emp.barcode or i.id),
                'position': pos_name,
                'department': dept_name or ou_name or '—',
                'work_unit': ou_name or dept_name or '—',
                'date': i.interview_date.strftime('%d %b %Y') if i.interview_date else '—',
                'state': i.state,
                'resignation_id': i.resignation_id.id if i.resignation_id else False,
            })

        return {
            'kpis': {
                'total': total,
                'completion_pct': completion_pct,
                'recommend_pct': recommend_pct,
                'regrettable_pct': regrettable_pct,
                'avg_sat': avg_sat,
                'avg_tenure': avg_yrs,
                'avg_tenure_median': med_yrs,
            },
            'bars': bars,
            'keeps': keeps,
            'donuts': donuts,
            'cg': cg,
            'likerts': likerts,
            'yes_no': yes_no,
            'text_qs': text_qs,
            'interviews': interview_list,
        }
    @api.model
    def get_employee_report(self, interview_id):
        interview = self.env['hr.exit.interview'].browse(interview_id)
        if not interview.exists():
            return None

        emp = interview.employee_id
        resig = interview.resignation_id

        # Group lines
        q_reason = []
        q_rating = []
        for line in interview.line_ids:
            item = {
                'id': line.id,
                'question': line.question_name,
                'answer': line.answer,
                'type': line.question_type,
                'type_label': dict(line._fields['question_type'].selection).get(line.question_type, ''),
                'options': [],
                'rating_val': 0
            }
            if line.question_type in ('rating', 'satisfaction'):
                val = getattr(line, f"{line.question_type}_value", '')
                map_val = {'excellent': 5, 'good': 4, 'fair': 3, 'poor': 2, 'very_poor': 1}
                sat_map = {'very_satisfied': 5, 'satisfied': 4, 'neutral': 3, 'dissatisfied': 2, 'very_dissatisfied': 1}
                item['rating_val'] = map_val.get(val, 0) if line.question_type == 'rating' else sat_map.get(val, 0)
                q_rating.append(item)
            elif line.question_type == 'agreement':
                val = line.agreement_value
                ag_map = {'strongly_agree': 5, 'agree': 4, 'neutral': 3, 'disagree': 2, 'strongly_disagree': 1}
                item['rating_val'] = ag_map.get(val, 0)
                q_rating.append(item)
            else:
                # Custom, text, etc
                if line.question_type in ('custom', 'checkbox'):
                    # Mock options since we don't have historical option choices easily
                    item['options'] = [{'name': line.answer, 'selected': True}]
                q_reason.append(item)

        pos_name = (emp.job_id.name if emp.job_id else False) or (emp.job_position.name if hasattr(emp, 'job_position') and emp.job_position else False) or 'N/A'
        dept_name = emp.department_id.name if emp.department_id else 'N/A'
        branch_name = (
            (emp.department_id.operating_unit_id.name if emp.department_id and hasattr(emp.department_id, 'operating_unit_id') and emp.department_id.operating_unit_id else False)
            or (emp.default_operating_unit_id.name if hasattr(emp, 'default_operating_unit_id') and emp.default_operating_unit_id else False)
            or (resig.operating_unit_id.name if resig and hasattr(resig, 'operating_unit_id') and resig.operating_unit_id else False)
            or dept_name
        )

        return {
            'id': interview.id, 'emp_name': emp.name,
            'emp_id': emp.barcode or 'N/A',
            'job': pos_name,
            'dept': dept_name,
            'branch': branch_name,
            'sep_type': resig.resignation_type_id.name if resig and resig.resignation_type_id else 'N/A',
            'tenure': '0 Years' if not getattr(emp, 'first_contract_date', None) and not emp.date_start else 'N/A',
            'last_day': resig.release_date.strftime('%d %b %Y') if resig and resig.release_date else 'N/A',
            'questions_reason': q_reason,
            'questions_rating': q_rating,
        }
