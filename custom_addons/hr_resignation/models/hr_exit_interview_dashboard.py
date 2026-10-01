# -*- coding: utf-8 -*-
from odoo import api, fields, models
from collections import Counter
import re
import logging

_logger = logging.getLogger(__name__)


class HrExitInterviewDashboard(models.AbstractModel):
    _name = 'hr.exit.interview.dashboard'
    _description = 'Exit Interview Dashboard Data'

    # ─── FILTER OPTIONS ──────────────────────────────────────────────────────

    @api.model
    def get_filter_options(self):
        """Return distinct values for the filter dropdowns."""
        interviews = self.env['hr.exit.interview'].search([])

        # Work units (Operating Units)
        if 'operating.unit' in self.env:
            ous = self.env['operating.unit'].search([])
            ou_names = sorted(set(ou.name for ou in ous if ou.name))
        else:
            ou_names = []
        ou_opts = [{'value': d, 'label': d} for d in ou_names]

        # Separation types (All active ones)
        if 'hr.separation.type' in self.env:
            stypes = self.env['hr.separation.type'].search([])
            sep_types = sorted(set(s.name for s in stypes if s.name))
        else:
            sep_types = sorted(set(
                i.resignation_id.resignation_type_id.name
                for i in interviews
                if i.resignation_id and i.resignation_id.resignation_type_id
            ))
        sep_opts = [{'value': s, 'label': s} for s in sep_types]

        # Job positions
        all_jobs = self.env['hr.job'].search([])
        positions = sorted(set(j.name for j in all_jobs if j.name))
        pos_opts = [{'value': p, 'label': p} for p in positions]

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
            quarter      - e.g. "Q3 2026"
            department   - department name string
            position     - job position name
            sep_type     - separation type name
        """
        if filters is None:
            filters = {}

        # ── Build domain ────────────────────────────────────────────────────
        domain = [('state', '=', 'completed')]

        ou_val = filters.get('operating_unit', '')
        if ou_val and ou_val != 'all':
            domain.append(('employee_id.department_id.operating_unit_id.name', '=', ou_val))

        pos_val = filters.get('position', '')
        if pos_val and pos_val != 'all':
            domain.append(('employee_id.job_id.name', '=', pos_val))

        sep_val = filters.get('sep_type', '')
        if sep_val and sep_val != 'all':
            domain.append(('resignation_id.resignation_type_id.name', '=', sep_val))

        interviews = self.env['hr.exit.interview'].search(domain)
        total = len(interviews)

        # Total submitted (all, not just filtered) for completion %
        all_count = self.env['hr.exit.interview'].search_count(
            [('resignation_id', '!=', False)])
        completion_pct = round(total / all_count * 100) if all_count else 0

        if total == 0:
            return {
                'kpis': {
                    'total': 0,
                    'completion_pct': 0,
                    'recommend_pct': 0,
                    'regrettable_pct': 0,
                    'avg_tenure': '—',
                    'avg_tenure_median': '—',
                },
                'bars': [],
                'keeps': [],
                'donuts': [],
                'likerts': [],
                'yes_no': [],
                'themes': [],
                'quotes': [],
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

        # ── Top themes (from text answers) ────────────────────────────────
        stop_words = {
            'the', 'a', 'to', 'and', 'was', 'is', 'in', 'of', 'for',
            'it', 'my', 'i', 'with', 'that', 'this', 'on', 'not',
            'have', 'be', 'as', 'but', 'are', 'at', 'very', 'they',
            'we', 'our', 'has', 'had', 'been', 'more', 'also', 'me',
            'from', 'would', 'could', 'bank', 'bunna', 'work',
        }
        words = []
        all_text_vals = []
        for l in lines:
            if l.question_type == 'text' and l.text_value and len(l.text_value.strip()) > 5:
                all_text_vals.append(l.text_value.strip())
                cleaned = re.sub(r'[^a-zA-Z\s]', '', l.text_value).lower()
                for w in cleaned.split():
                    if w not in stop_words and len(w) > 3:
                        words.append(w.capitalize())

        word_counts = Counter(words)
        themes = []
        for idx, (w, c) in enumerate(word_counts.most_common(10)):
            if c >= 1:
                size = 'lg' if idx < 2 else 'md' if idx < 4 else 'sm'
                themes.append({'t': w, 'n': c, 'size': size})

        # ── Quotes (sample from text answers) ────────────────────────────
        quotes = []
        for idx, txt in enumerate(all_text_vals[:5]):
            if len(txt) > 20:
                quotes.append({'id': idx, 'text': txt[:180]})

        # ── Interview list for the table ──────────────────────────────────
        interview_list = []
        for i in interviews:
            emp = i.employee_id
            interview_list.append({
                'id': i.id,
                'name': emp.name or '—',
                'emp_id': str(emp.barcode or i.id),
                'position': emp.job_id.name or '—',
                'department': emp.department_id.name or '—',
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
            'themes': themes,
            'quotes': quotes,
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

        return {
            'emp_name': emp.name,
            'emp_id': emp.barcode or 'N/A',
            'job': emp.job_id.name or 'N/A',
            'dept': emp.department_id.name or 'N/A',
            'branch': emp.department_id.operating_unit_id.name or 'N/A',
            'sep_type': resig.resignation_type_id.name if resig and resig.resignation_type_id else 'N/A',
            'tenure': '0 Years' if not emp.first_contract_date else 'N/A', # Mock
            'last_day': resig.release_date.strftime('%d %b %Y') if resig and resig.release_date else 'N/A',
            'questions_reason': q_reason,
            'questions_rating': q_rating,
        }
