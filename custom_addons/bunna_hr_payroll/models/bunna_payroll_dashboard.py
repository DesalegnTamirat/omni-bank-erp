# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

GROUP_NAMES = {
    '10': 'Operating Units / Branches',
    '20': 'Cost Sharing',
    '30': 'Labour Union',
    '40': 'Pension Contribution (7% + 11%)',
    '50': 'Provident Fund (5% / 2% + 10%)',
    '60': 'Income Tax (PAYE)',
    '70': 'Staff Loan Deductions',
    '80': 'Sundry / Other Creditors',
    '90': 'Net Salary / Staff Accounts',
}


def _extract_name(val, fallback=''):
    if not val:
        return fallback
    if isinstance(val, dict):
        return val.get('en_US') or val.get('en') or next(iter(val.values()), fallback)
    if isinstance(val, str):
        if val.startswith('{') and val.endswith('}'):
            try:
                import json
                parsed = json.loads(val)
                if isinstance(parsed, dict):
                    return parsed.get('en_US') or parsed.get('en') or next(iter(parsed.values()), fallback)
            except Exception:
                pass
        return val
    return str(val)


class BunnaPayrollDashboard(models.AbstractModel):
    """Payroll Process Dashboard backend service for Bunna Bank ERP."""
    _name = 'bunna.payroll.dashboard'
    _description = 'Bunna Payroll Process Dashboard Service'

    @api.model
    def get_dashboard_data(self, period_id=None):
        """Aggregate end-to-end payroll process data, KPIs, process stepper,
        CBS Finacle balance matrix, and department distributions.
        Highly optimized with bulk SQL aggregations for 4000+ employees.
        """
        Period = self.env['hr.payroll.period'].sudo()
        all_periods = Period.with_context(active_test=False).search([], order='date_from desc, id desc')

        if not all_periods:
            return {
                'has_data': True,
                'no_periods_configured': True,
                'all_periods': [],
                'selected_period': {
                    'id': False,
                    'name': _('No Periods Configured'),
                    'fiscal_year': 'N/A',
                    'code': '',
                    'state': 'draft',
                    'date_from': '',
                    'date_to': '',
                    'payment_date': '',
                    'schedule_pay': 'Monthly',
                    'period_type': 'HR Period',
                },
                'overall_progress': 0,
                'stepper': [],
                'kpis': {
                    'gross_salary': 0, 'net_salary': 0, 'total_deductions': 0, 'basic_salary': 0,
                    'total_allowances': 0, 'total_employer_cost': 0, 'tax_amount': 0, 'pension_emp': 0,
                    'pension_comp': 0, 'pf_emp': 0, 'pf_comp': 0, 'od_asbeza_amount': 0,
                    'cash_indemnity_amount': 0, 'cost_sharing_amount': 0, 'labour_union_amount': 0,
                    'loans_amount': 0, 'total_employees': 0, 'total_slips': 0, 'done_slips': 0,
                    'waiting_slips': 0, 'draft_slips': 0, 'cancelled_slips': 0, 'total_batches': 0,
                    'done_batches': 0, 'draft_batches': 0,
                },
                'cbs_journal': {'total_entries': 0, 'total_debit': 0, 'total_credit': 0, 'difference': 0, 'is_balanced': False, 'groups': []},
                'cbs_integration': {'active': False, 'od_asbeza_synced': False, 'cash_indemnity_synced': False},
                'coverage': {
                    'total_workforce': 0, 'with_slip_count': 0, 'with_slip_percentage': 0,
                    'without_slip_count': 0, 'without_slip_percentage': 0, 'proportional_count': 0,
                    'missing_breakdown': {}, 'missing_employees': [], 'proportional_slips': [],
                },
                'recent_batches': [],
            }

        selected_period = False
        if period_id:
            try:
                pid_int = int(period_id)
                selected_period = Period.browse(pid_int)
                if not selected_period.exists():
                    selected_period = False
            except (ValueError, TypeError):
                selected_period = False

        if not selected_period:
            open_periods = all_periods.filtered(lambda p: p.state == 'open')
            selected_period = open_periods[0] if open_periods else all_periods[0]

        pid = selected_period.id

        # -------------------------------------------------------------
        # 1. Periods List for Dropdown Selector
        # -------------------------------------------------------------
        periods_list = []
        for p in all_periods:
            periods_list.append({
                'id': p.id,
                'name': p.name or _("Period %s") % p.id,
                'fiscal_year': p.fiscal_year or '',
                'state': p.state or 'draft',
                'state_display': (p.state or 'draft').upper(),
                'is_selected': p.id == pid,
            })

        # -------------------------------------------------------------
        # 2. Selected Period Overview
        # -------------------------------------------------------------
        schedule_pay_val = selected_period.schedule_pay
        if schedule_pay_val and hasattr(selected_period._fields.get('schedule_pay'), 'selection'):
            schedule_pay_label = dict(selected_period._fields['schedule_pay'].selection).get(schedule_pay_val, schedule_pay_val)
        else:
            schedule_pay_label = schedule_pay_val or 'Monthly'

        period_type_val = selected_period.period_type
        if period_type_val and hasattr(selected_period._fields.get('period_type'), 'selection'):
            period_type_label = dict(selected_period._fields['period_type'].selection).get(period_type_val, period_type_val)
        else:
            period_type_label = period_type_val or 'HR Period'

        period_info = {
            'id': selected_period.id,
            'name': selected_period.name or '',
            'fiscal_year': selected_period.fiscal_year or 'N/A',
            'code': selected_period.code or '',
            'state': selected_period.state or 'draft',
            'date_from': str(selected_period.date_from) if selected_period.date_from else '',
            'date_to': str(selected_period.date_to) if selected_period.date_to else '',
            'payment_date': str(selected_period.payment_date) if selected_period.payment_date else '',
            'schedule_pay': schedule_pay_label,
            'period_type': period_type_label,
        }

        # -------------------------------------------------------------
        # 3. Payslips & Batches Aggregations for this Period (Single Query)
        # -------------------------------------------------------------
        self.env.cr.execute("""
            SELECT state, COUNT(*)
            FROM hr_payslip
            WHERE period_id = %s
            GROUP BY state
        """, (pid,))
        slip_counts = dict(self.env.cr.fetchall())
        done_slips = slip_counts.get('done', 0)
        waiting_slips = slip_counts.get('verify', 0)
        draft_slips = slip_counts.get('draft', 0)
        cancelled_slips = slip_counts.get('cancel', 0)
        total_slips = sum(slip_counts.values())

        self.env.cr.execute("""
            SELECT state, COUNT(*)
            FROM hr_payslip_run
            WHERE period_id = %s
            GROUP BY state
        """, (pid,))
        batch_counts = dict(self.env.cr.fetchall())
        done_batches = batch_counts.get('close', 0) + batch_counts.get('done', 0)
        draft_batches = batch_counts.get('draft', 0)
        total_batches = sum(batch_counts.values())

        # Financial totals from payslip lines (One bulk aggregation query)
        gross_salary = 0.0
        net_salary = 0.0
        basic_salary = 0.0
        total_allowance = 0.0
        total_deduction = 0.0
        tax_amount = 0.0
        pension_emp = 0.0
        pension_comp = 0.0
        pf_emp = 0.0
        pf_comp = 0.0
        od_asbeza_amount = 0.0
        cash_indemnity_amount = 0.0
        cost_sharing_amount = 0.0
        labour_union_amount = 0.0
        loans_amount = 0.0

        if total_slips > 0:
            self.env.cr.execute("""
                SELECT 
                    pl.code,
                    rc.code as cat_code,
                    SUM(pl.amount) as line_sum
                FROM hr_payslip_line pl
                JOIN hr_payslip p ON p.id = pl.slip_id
                LEFT JOIN hr_salary_rule_category rc ON rc.id = pl.category_id
                WHERE p.period_id = %s
                GROUP BY pl.code, rc.code
            """, (pid,))

            for code, cat_code, line_sum in self.env.cr.fetchall():
                val = float(line_sum or 0.0)
                code_u = (code or '').upper()
                cat_u = (cat_code or '').upper()

                if cat_u == 'GROSS' or code_u == 'GROSS':
                    gross_salary += val
                elif cat_u == 'NET' or code_u == 'NET':
                    net_salary += val
                elif cat_u == 'BASIC' or code_u in ('BASIC', 'BASE'):
                    basic_salary += val
                elif cat_u == 'ALW':
                    total_allowance += val
                elif cat_u in ('DED', 'ADHDED'):
                    total_deduction += val

                # Detailed rule breakdowns
                if code_u in ('TAX', 'INCOME_TAX', 'PAYE', 'IT'):
                    tax_amount += val
                elif code_u in ('PEN_EMP', 'PENSION', 'PENSION_EMP', 'PENSION7'):
                    pension_emp += val
                elif code_u in ('PEN_COMP', 'PENSION_COMP', 'PENSION11', 'PENSION_BNK'):
                    pension_comp += val
                elif code_u in ('PF_EMP', 'PF5', 'PROVIDENT_FUND', 'PF'):
                    pf_emp += val
                elif code_u in ('PF_COMP', 'PF10', 'PROVIDENT_FUND_COMP'):
                    pf_comp += val
                elif code_u in ('OD', 'ASBEZA'):
                    od_asbeza_amount += val
                elif code_u in ('CIA', 'CIA-ALL', 'CIAB', 'CASH_INDEMNITY'):
                    cash_indemnity_amount += val
                elif code_u in ('CS', 'COST_SHARING'):
                    cost_sharing_amount += val
                elif code_u in ('LU', 'LABOUR_UNION'):
                    labour_union_amount += val
                elif 'LOAN' in code_u or 'STAFF_LOAN' in code_u:
                    loans_amount += val

        if gross_salary == 0.0 and (basic_salary > 0 or total_allowance > 0):
            gross_salary = basic_salary + total_allowance

        if total_deduction == 0.0 and (gross_salary > net_salary > 0):
            total_deduction = gross_salary - net_salary

        total_employer_cost = gross_salary + pension_comp + pf_comp

        self.env.cr.execute("""
            SELECT COUNT(DISTINCT employee_id)
            FROM hr_payslip
            WHERE period_id = %s AND employee_id IS NOT NULL
        """, (pid,))
        unique_employees = (self.env.cr.fetchone() or [0])[0]

        # -------------------------------------------------------------
        # 4. CBS Finacle Journal Entries Audit & Matrix
        # -------------------------------------------------------------
        self.env.cr.execute("""
            SELECT 
                group_code,
                flag,
                COUNT(*),
                COALESCE(SUM(amount), 0)
            FROM bunna_payroll_journal_entry
            WHERE period_id = %s
            GROUP BY group_code, flag
            ORDER BY group_code, flag
        """, (pid,))

        journal_rows = self.env.cr.fetchall()
        groups_dict = {}
        total_debit = 0.0
        total_credit = 0.0
        total_entries_count = 0

        for gcode, flag, count, amt in journal_rows:
            gcode = str(gcode or '').strip()
            total_entries_count += count
            f_amt = float(amt or 0.0)
            if gcode not in groups_dict:
                groups_dict[gcode] = {
                    'group_code': gcode,
                    'group_name': GROUP_NAMES.get(gcode, _("Group %s") % gcode),
                    'debit': 0.0,
                    'credit': 0.0,
                    'count': 0,
                }
            groups_dict[gcode]['count'] += count
            if flag == 'D':
                groups_dict[gcode]['debit'] += f_amt
                total_debit += f_amt
            elif flag == 'C':
                groups_dict[gcode]['credit'] += f_amt
                total_credit += f_amt

        journal_groups = []
        for gcode in sorted(groups_dict.keys()):
            g = groups_dict[gcode]
            diff = round(abs(g['debit'] - g['credit']), 2)
            g['difference'] = diff
            g['is_balanced'] = diff == 0.0
            journal_groups.append(g)

        cbs_diff = round(abs(total_debit - total_credit), 2)
        cbs_is_balanced = (cbs_diff == 0.0) and (total_debit > 0)

        # -------------------------------------------------------------
        # 5. Pre-Payroll CBS Adjustments Integration Status
        # -------------------------------------------------------------
        od_asbeza_synced = bool(od_asbeza_amount > 0)
        cash_indemnity_synced = bool(cash_indemnity_amount > 0)

        cbs_config_active = False
        try:
            self.env.cr.execute("""
                SELECT count(*) FROM cbs_integration WHERE environment = 'CBS' AND status = 'true';
            """)
            cbs_config_active = bool((self.env.cr.fetchone() or [0])[0] > 0)
        except Exception:
            cbs_config_active = False

        # -------------------------------------------------------------
        # 6. End-to-End Payroll Process Stepper (6 Stages)
        # -------------------------------------------------------------
        st1_done = selected_period.state in ('open', 'closed')
        st2_done = od_asbeza_synced or cash_indemnity_synced or (total_slips > 0)
        st3_done = total_batches > 0
        st4_done = total_slips > 0 and (done_slips == total_slips)
        st5_done = total_entries_count > 0 and cbs_is_balanced
        st6_done = selected_period.state == 'closed'

        completed_steps = sum([1 for s in (st1_done, st2_done, st3_done, st4_done, st5_done, st6_done) if s])
        overall_progress = int(round((completed_steps / 6.0) * 100))

        stepper = [
            {
                'step': 1,
                'id': 'period_setup',
                'title': _('Period Setup'),
                'subtitle': _('Fiscal year %s') % (selected_period.fiscal_year or ''),
                'status': 'completed' if st1_done else 'active',
                'icon': 'fa-calendar-check-o',
                'desc': _('Period status: %s') % selected_period.state.capitalize(),
                'action_name': 'open_period_form',
            },
            {
                'step': 2,
                'id': 'cbs_sync',
                'title': _('CBS Sync'),
                'subtitle': _('OD, ASBEZA & Indemnity'),
                'status': 'completed' if st2_done else ('active' if st1_done else 'pending'),
                'icon': 'fa-cloud-download',
                'desc': _('OD/ASBEZA: %s | Indemnity: %s') % (
                    _('Synced') if od_asbeza_synced else _('Ready'),
                    _('Synced') if cash_indemnity_synced else _('Ready')
                ),
                'action_name': 'open_period_form' if selected_period.state == 'closed' else 'open_fetch_indemnity_wizard',
            },
            {
                'step': 3,
                'id': 'batches',
                'title': _('Batch Generation'),
                'subtitle': _('%s Batches created') % total_batches,
                'status': 'completed' if st3_done else ('active' if st2_done else 'pending'),
                'icon': 'fa-sitemap',
                'desc': _('%s Done / %s Draft') % (done_batches, draft_batches),
                'action_name': 'open_batches_list' if selected_period.state == 'closed' else 'open_auto_batch_wizard',
            },
            {
                'step': 4,
                'id': 'payslips',
                'title': _('Payslip Computation'),
                'subtitle': _('%s of %s confirmed') % (done_slips, total_slips),
                'status': 'completed' if st4_done else ('active' if st3_done else 'pending'),
                'icon': 'fa-calculator',
                'desc': _('%s Done, %s Draft/Waiting') % (done_slips, draft_slips + waiting_slips),
                'action_name': 'open_payslips_list',
            },
            {
                'step': 5,
                'id': 'cbs_journal',
                'title': _('CBS Finacle Entries'),
                'subtitle': _('%s entries generated') % total_entries_count,
                'status': 'completed' if st5_done else ('active' if st4_done else 'pending'),
                'icon': 'fa-balance-scale',
                'desc': _('Balanced: %s (Diff: %s ETB)') % (_('YES') if cbs_is_balanced else _('NO'), cbs_diff),
                'action_name': 'open_journal_entries_list' if selected_period.state == 'closed' else 'open_journal_wizard',
            },
            {
                'step': 6,
                'id': 'closure',
                'title': _('Disbursement & Close'),
                'subtitle': _('Period Finalization'),
                'status': 'completed' if st6_done else ('active' if st5_done else 'pending'),
                'icon': 'fa-lock',
                'desc': _('Period Closed & Archived') if st6_done else (_('Ready to close') if st5_done else _('Pending steps')),
                'action_name': 'open_period_form' if selected_period.state == 'closed' else 'close_period_action',
            },
        ]

        # -------------------------------------------------------------
        # 7. Employee Payroll Coverage & Eligibility Intelligence (Bulk Queries)
        # -------------------------------------------------------------
        company_id = selected_period.company_id.id if selected_period.company_id else self.env.company.id

        # 1. Total Active Employees in Company
        self.env.cr.execute("""
            SELECT COUNT(*)
            FROM hr_employee
            WHERE active = true AND (company_id IS NULL OR company_id = %s)
        """, (company_id,))
        total_active_emp_count = (self.env.cr.fetchone() or [0])[0]

        # 2. Employees With Payslip in this Period
        emp_with_slip_count = unique_employees

        # 3. Employees Without Payslip in this Period (Bulk SQL)
        missing_emps = []
        try:
            self.env.cr.execute("""
                SELECT 
                    e.id,
                    e.name,
                    d.name AS dept_raw,
                    e.job_name AS job_raw
                FROM hr_employee e
                LEFT JOIN hr_department d ON d.id = e.department_id
                WHERE e.active = true
                  AND (e.company_id IS NULL OR e.company_id = %s)
                  AND e.id NOT IN (
                      SELECT DISTINCT employee_id 
                      FROM hr_payslip 
                      WHERE period_id = %s AND employee_id IS NOT NULL
                  )
                ORDER BY e.name
            """, (company_id, pid))
            missing_emps = self.env.cr.fetchall()
        except Exception as e:
            _logger.warning("Could not fetch missing employees for dashboard: %s", e)
            missing_emps = []
        emp_without_slip_count = len(missing_emps)

        missing_breakdown = {
            'no_contract': 0,
            'unbatched_eligible': 0,
            'future_hire': 0,
            'contract_ended': 0,
            'draft_contract': 0,
        }
        missing_employees_list = []
        p_from = selected_period.date_from
        p_to = selected_period.date_to

        missing_emp_ids = [r[0] for r in missing_emps]
        versions_by_emp = {}
        if missing_emp_ids:
            self.env.cr.execute("""
                SELECT 
                    employee_id,
                    id,
                    name,
                    contract_date_start,
                    contract_date_end,
                    active,
                    state
                FROM hr_version
                WHERE employee_id IN %s
                ORDER BY employee_id, contract_date_start DESC NULLS LAST, id DESC
            """, (tuple(missing_emp_ids),))
            for v_row in self.env.cr.fetchall():
                emp_id = v_row[0]
                if emp_id not in versions_by_emp:
                    versions_by_emp[emp_id] = []
                versions_by_emp[emp_id].append({
                    'id': v_row[1],
                    'name': v_row[2],
                    'contract_date_start': v_row[3],
                    'contract_date_end': v_row[4],
                    'active': v_row[5],
                    'state': v_row[6],
                })

        for emp_id, emp_name, dept_raw, job_raw in missing_emps:
            dept_name = _extract_name(dept_raw, _('Unassigned'))
            job_name = _extract_name(job_raw, _('N/A'))
            versions = versions_by_emp.get(emp_id, [])

            reason_key = 'no_contract'
            reason_label = _('No Contract Defined')
            reason_badge = 'bpd-pill-error'
            details = _('Employee has no contract/version record.')

            if not versions:
                reason_key = 'no_contract'
                reason_label = _('No Contract Defined')
                reason_badge = 'bpd-pill-error'
                details = _('No contract record found in HR.')
            else:
                overlapping = [
                    v for v in versions if (
                        (not v['contract_date_start'] or (p_to and v['contract_date_start'] <= p_to)) and
                        (not v['contract_date_end'] or (p_from and v['contract_date_end'] >= p_from))
                    )
                ]

                if overlapping:
                    active_running = [
                        v for v in overlapping if v['active'] and v['state'] in ('open', 'running', 'draft')
                    ]
                    if active_running:
                        reason_key = 'unbatched_eligible'
                        reason_label = _('Eligible (Not in Batch)')
                        reason_badge = 'bpd-pill-warning'
                        v_name = active_running[0]['name'] or _("Contract")
                        details = _('Has active contract (%s), but not included in any payslip batch.') % v_name
                    else:
                        reason_key = 'draft_contract'
                        reason_label = _('Contract Inactive / Cancelled')
                        reason_badge = 'bpd-pill-error'
                        details = _('Contract exists but is inactive or cancelled.')
                else:
                    latest_v = versions[0]
                    if latest_v['contract_date_start'] and p_to and latest_v['contract_date_start'] > p_to:
                        reason_key = 'future_hire'
                        reason_label = _('New Hire (After Period)')
                        reason_badge = 'bpd-pill-info'
                        details = _('Hired on %s (after period end %s).') % (latest_v['contract_date_start'], p_to)
                    elif latest_v['contract_date_end'] and p_from and latest_v['contract_date_end'] < p_from:
                        reason_key = 'contract_ended'
                        reason_label = _('Separated Before Period')
                        reason_badge = 'bpd-pill-secondary'
                        details = _('Contract ended on %s (prior to period start %s).') % (latest_v['contract_date_end'], p_from)
                    else:
                        reason_key = 'no_contract'
                        reason_label = _('No Active Period Contract')
                        reason_badge = 'bpd-pill-secondary'
                        details = _('No contract covering period dates.')

            missing_breakdown[reason_key] = missing_breakdown.get(reason_key, 0) + 1

            missing_employees_list.append({
                'id': emp_id,
                'name': emp_name,
                'department': dept_name,
                'job': job_name,
                'reason_key': reason_key,
                'reason_label': reason_label,
                'reason_badge': reason_badge,
                'details': details,
            })

        # 4. Proportional (Prorated) Payslips Detection (Single Bulk SQL Query)
        proportional_slips_list = []
        period_calendar_days = ((p_to - p_from).days + 1) if (p_from and p_to) else 30

        prop_rows = []
        try:
            self.env.cr.execute("""
                SELECT 
                    p.id,
                    p.number,
                    e.id,
                    e.name,
                    d.name AS dept_raw,
                    v.contract_date_start,
                    v.contract_date_end,
                    COALESCE(wd.total_days, 0),
                    COALESCE(net.amount, 0)
                FROM hr_payslip p
                JOIN hr_employee e ON e.id = p.employee_id
                LEFT JOIN hr_department d ON d.id = e.department_id
                LEFT JOIN hr_version v ON v.id = p.version_id
                LEFT JOIN (
                    SELECT payslip_id, SUM(number_of_days) as total_days
                    FROM hr_payslip_worked_days
                    GROUP BY payslip_id
                ) wd ON wd.payslip_id = p.id
                LEFT JOIN (
                    SELECT pl.slip_id, SUM(pl.amount) as amount
                    FROM hr_payslip_line pl
                    LEFT JOIN hr_salary_rule_category rc ON rc.id = pl.category_id
                    WHERE pl.code = 'NET' OR rc.code = 'NET'
                    GROUP BY pl.slip_id
                ) net ON net.slip_id = p.id
                WHERE p.period_id = %s
                  AND (
                      (v.contract_date_start IS NOT NULL AND %s IS NOT NULL AND v.contract_date_start > %s)
                      OR (v.contract_date_end IS NOT NULL AND %s IS NOT NULL AND v.contract_date_end < %s)
                      OR (COALESCE(wd.total_days, 0) > 0 AND COALESCE(wd.total_days, 0) < 20 AND %s >= 20)
                  )
                ORDER BY p.id
            """, (pid, p_from, p_from, p_to, p_to, period_calendar_days))
            prop_rows = self.env.cr.fetchall()
        except Exception as e:
            _logger.warning("Error fetching proportional slips: %s", e)
            prop_rows = []

        for row in prop_rows:
            slip_id, slip_num, emp_id, emp_name, dept_raw, c_start, c_end, worked_days, net_amt = row
            dept_name = _extract_name(dept_raw, _('Unassigned'))
            slip_num = slip_num or _('Draft Slip')
            prop_reasons = []
            if c_start and p_from and c_start > p_from:
                prop_reasons.append(_("Joined mid-period: %s") % c_start)
            if c_end and p_to and c_end < p_to:
                prop_reasons.append(_("Left mid-period: %s") % c_end)
            if 0 < worked_days < 20 and period_calendar_days >= 20:
                prop_reasons.append(_("%s days worked") % int(worked_days))

            proportional_slips_list.append({
                'id': slip_id,
                'number': slip_num,
                'employee_id': emp_id,
                'employee_name': emp_name,
                'department': dept_name,
                'reason': " & ".join(prop_reasons) if prop_reasons else _('Prorated period'),
                'contract_start': str(c_start) if c_start else '',
                'contract_end': str(c_end) if c_end else '',
                'worked_days': worked_days or 'N/A',
                'net_amount': round(float(net_amt or 0.0), 2),
            })

        proportional_count = len(proportional_slips_list)

        # -------------------------------------------------------------
        # 8. Recent Batches Table (Top 5 - Single Bulk SQL Query)
        # -------------------------------------------------------------
        self.env.cr.execute("""
            SELECT 
                b.id,
                b.name,
                b.state,
                b.date_start,
                b.date_end,
                COUNT(p.id) as slip_count,
                COALESCE(SUM(net.amount), 0) as net_amount
            FROM hr_payslip_run b
            LEFT JOIN hr_payslip p ON p.payslip_run_id = b.id
            LEFT JOIN (
                SELECT pl.slip_id, SUM(pl.amount) as amount
                FROM hr_payslip_line pl
                LEFT JOIN hr_salary_rule_category rc ON rc.id = pl.category_id
                WHERE pl.code = 'NET' OR rc.code = 'NET'
                GROUP BY pl.slip_id
            ) net ON net.slip_id = p.id
            WHERE b.period_id = %s
            GROUP BY b.id, b.name, b.state, b.date_start, b.date_end
            ORDER BY b.id DESC
            LIMIT 5
        """, (pid,))
        batch_rows = self.env.cr.fetchall()
        recent_batches = []
        state_labels = {
            'draft': _('Draft'),
            'close': _('Closed'),
            'done': _('Confirmed'),
            'cancel': _('Cancelled'),
        }
        for b_id, b_name, b_state, b_dstart, b_dend, b_slip_count, b_net in batch_rows:
            recent_batches.append({
                'id': b_id,
                'name': b_name or '',
                'state': b_state,
                'state_label': state_labels.get(b_state, (b_state or '').capitalize()),
                'slip_count': b_slip_count,
                'net_amount': round(float(b_net or 0.0), 2),
                'date_start': str(b_dstart) if b_dstart else '',
                'date_end': str(b_dend) if b_dend else '',
            })

        # Return full payload
        return {
            'has_data': True,
            'all_periods': periods_list,
            'selected_period': period_info,
            'overall_progress': overall_progress,
            'stepper': stepper,
            'kpis': {
                'gross_salary': round(gross_salary, 2),
                'net_salary': round(net_salary, 2),
                'total_deductions': round(total_deduction, 2),
                'basic_salary': round(basic_salary, 2),
                'total_allowances': round(total_allowance, 2),
                'total_employer_cost': round(total_employer_cost, 2),
                'tax_amount': round(tax_amount, 2),
                'pension_emp': round(pension_emp, 2),
                'pension_comp': round(pension_comp, 2),
                'pf_emp': round(pf_emp, 2),
                'pf_comp': round(pf_comp, 2),
                'od_asbeza_amount': round(od_asbeza_amount, 2),
                'cash_indemnity_amount': round(cash_indemnity_amount, 2),
                'cost_sharing_amount': round(cost_sharing_amount, 2),
                'labour_union_amount': round(labour_union_amount, 2),
                'loans_amount': round(loans_amount, 2),
                'total_employees': unique_employees,
                'total_slips': total_slips,
                'done_slips': done_slips,
                'waiting_slips': waiting_slips,
                'draft_slips': draft_slips,
                'cancelled_slips': cancelled_slips,
                'total_batches': total_batches,
                'done_batches': done_batches,
                'draft_batches': draft_batches,
            },
            'cbs_journal': {
                'total_entries': total_entries_count,
                'total_debit': round(total_debit, 2),
                'total_credit': round(total_credit, 2),
                'difference': cbs_diff,
                'is_balanced': cbs_is_balanced,
                'groups': journal_groups,
            },
            'cbs_integration': {
                'active': cbs_config_active,
                'od_asbeza_synced': od_asbeza_synced,
                'cash_indemnity_synced': cash_indemnity_synced,
            },
            'coverage': {
                'total_workforce': total_active_emp_count,
                'with_slip_count': emp_with_slip_count,
                'with_slip_percentage': round((emp_with_slip_count / total_active_emp_count * 100), 1) if total_active_emp_count > 0 else 0,
                'without_slip_count': emp_without_slip_count,
                'without_slip_percentage': round((emp_without_slip_count / total_active_emp_count * 100), 1) if total_active_emp_count > 0 else 0,
                'proportional_count': proportional_count,
                'missing_breakdown': missing_breakdown,
                'missing_employees': missing_employees_list,
                'proportional_slips': proportional_slips_list,
            },
            'recent_batches': recent_batches,
        }


class HrPayrollPeriod(models.Model):
    _inherit = 'hr.payroll.period'

    @api.model
    def get_payroll_dashboard_data(self, period_id=None):
        """Bridge method to expose dashboard metrics on hr.payroll.period."""
        return self.env['bunna.payroll.dashboard'].get_dashboard_data(period_id=period_id)
