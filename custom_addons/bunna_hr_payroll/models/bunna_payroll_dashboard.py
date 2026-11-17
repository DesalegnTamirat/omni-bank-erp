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


class BunnaPayrollDashboard(models.AbstractModel):
    """Payroll Process Dashboard backend service for Bunna Bank ERP."""
    _name = 'bunna.payroll.dashboard'
    _description = 'Bunna Payroll Process Dashboard Service'

    @api.model
    def get_dashboard_data(self, period_id=None):
        """Aggregate end-to-end payroll process data, KPIs, process stepper,
        CBS Finacle balance matrix, and department distributions.
        """
        Period = self.env['hr.payroll.period'].sudo()
        all_periods = Period.search([], order='date_from desc, id desc')

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
            # Prefer currently open period, else latest
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
        # 3. Payslips & Batches Aggregations for this Period
        # -------------------------------------------------------------
        payslips = self.env['hr.payslip'].sudo().search([('period_id', '=', pid)])
        total_slips = len(payslips)
        done_slips = len(payslips.filtered(lambda s: s.state == 'done'))
        waiting_slips = len(payslips.filtered(lambda s: s.state == 'verify'))
        draft_slips = len(payslips.filtered(lambda s: s.state == 'draft'))
        cancelled_slips = len(payslips.filtered(lambda s: s.state == 'cancel'))

        batches = self.env['hr.payslip.run'].sudo().search([('period_id', '=', pid)])
        total_batches = len(batches)
        done_batches = len(batches.filtered(lambda b: b.state in ('close', 'done')))
        draft_batches = len(batches.filtered(lambda b: b.state == 'draft'))

        # Financial totals from payslip lines
        slip_ids = payslips.ids
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

        if slip_ids:
            self.env.cr.execute("""
                SELECT 
                    pl.code,
                    rc.code as cat_code,
                    SUM(pl.amount) as line_sum
                FROM hr_payslip_line pl
                LEFT JOIN hr_salary_rule_category rc ON rc.id = pl.category_id
                WHERE pl.slip_id IN %s
                GROUP BY pl.code, rc.code
            """, (tuple(slip_ids),))

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
                if code_u in ('TAX', 'INCOME_TAX', 'PAYE'):
                    tax_amount += val
                elif code_u in ('PEN_EMP', 'PENSION', 'PENSION_EMP', 'PENSION7'):
                    pension_emp += val
                elif code_u in ('PEN_COMP', 'PENSION_COMP', 'PENSION11'):
                    pension_comp += val
                elif code_u in ('PF_EMP', 'PF5', 'PROVIDENT_FUND'):
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

        # If gross was not explicitly computed, calculate as basic + allowances
        if gross_salary == 0.0 and (basic_salary > 0 or total_allowance > 0):
            gross_salary = basic_salary + total_allowance

        if total_deduction == 0.0 and (gross_salary > net_salary > 0):
            total_deduction = gross_salary - net_salary

        total_employer_cost = gross_salary + pension_comp + pf_comp
        unique_employees = len(set(payslips.mapped('employee_id').ids))

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

        # Also check if cbs_integration is enabled in DB
        self.env.cr.execute("""
            SELECT count(*) FROM cbs_integration WHERE environment = 'CBS' AND status = 'true';
        """)
        cbs_config_active = bool((self.env.cr.fetchone() or [0])[0] > 0)

        # -------------------------------------------------------------
        # 6. End-to-End Payroll Process Stepper (6 Stages)
        # -------------------------------------------------------------
        # Stage 1: Setup
        st1_done = selected_period.state in ('open', 'closed')
        # Stage 2: CBS Sync
        st2_done = od_asbeza_synced or cash_indemnity_synced or (total_slips > 0)
        # Stage 3: Batch Gen
        st3_done = total_batches > 0
        # Stage 4: Calculation
        st4_done = total_slips > 0 and (done_slips == total_slips)
        # Stage 5: CBS Journal
        st5_done = total_entries_count > 0 and cbs_is_balanced
        # Stage 6: Close
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
        # 7. Employee Payroll Coverage & Eligibility Intelligence
        # -------------------------------------------------------------
        # 1. Total Active Employees in Company
        company_id = selected_period.company_id.id if selected_period.company_id else self.env.company.id
        all_active_employees = self.env['hr.employee'].sudo().search([
            ('active', '=', True),
            '|', ('company_id', '=', False), ('company_id', '=', company_id)
        ])
        total_active_emp_count = len(all_active_employees)

        # 2. Employees With Payslip in this Period
        slip_emp_ids = set(payslips.mapped('employee_id').ids)
        emp_with_slip_count = len(slip_emp_ids)

        # 3. Employees Without Payslip in this Period
        missing_emp_records = all_active_employees.filtered(lambda e: e.id not in slip_emp_ids)
        emp_without_slip_count = len(missing_emp_records)

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

        for emp in missing_emp_records:
            versions = self.env['hr.version'].sudo().search([
                ('employee_id', '=', emp.id),
            ], order='contract_date_start desc, id desc')

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
                overlapping = versions.filtered(lambda v: (
                    (not v.contract_date_start or (p_to and v.contract_date_start <= p_to)) and
                    (not v.contract_date_end or (p_from and v.contract_date_end >= p_from))
                ))

                if overlapping:
                    active_running = overlapping.filtered(lambda v: v.active and v.state in ('open', 'running', 'draft'))
                    if active_running:
                        reason_key = 'unbatched_eligible'
                        reason_label = _('Eligible (Not in Batch)')
                        reason_badge = 'bpd-pill-warning'
                        v_name = active_running[0].name or _("Contract")
                        details = _('Has active contract (%s), but not included in any payslip batch.') % v_name
                    else:
                        reason_key = 'draft_contract'
                        reason_label = _('Contract Inactive / Cancelled')
                        reason_badge = 'bpd-pill-error'
                        details = _('Contract exists but is inactive or cancelled.')
                else:
                    latest_v = versions[0]
                    if latest_v.contract_date_start and p_to and latest_v.contract_date_start > p_to:
                        reason_key = 'future_hire'
                        reason_label = _('New Hire (After Period)')
                        reason_badge = 'bpd-pill-info'
                        details = _('Hired on %s (after period end %s).') % (latest_v.contract_date_start, p_to)
                    elif latest_v.contract_date_end and p_from and latest_v.contract_date_end < p_from:
                        reason_key = 'contract_ended'
                        reason_label = _('Separated Before Period')
                        reason_badge = 'bpd-pill-secondary'
                        details = _('Contract ended on %s (prior to period start %s).') % (latest_v.contract_date_end, p_from)
                    else:
                        reason_key = 'no_contract'
                        reason_label = _('No Active Period Contract')
                        reason_badge = 'bpd-pill-secondary'
                        details = _('No contract covering period dates.')

            missing_breakdown[reason_key] = missing_breakdown.get(reason_key, 0) + 1

            missing_employees_list.append({
                'id': emp.id,
                'name': emp.name,
                'department': emp.department_id.name if emp.department_id else _('Unassigned'),
                'job': emp.job_id.name if emp.job_id else _('N/A'),
                'reason_key': reason_key,
                'reason_label': reason_label,
                'reason_badge': reason_badge,
                'details': details,
            })

        # 4. Proportional (Prorated) Payslips Detection
        proportional_slips_list = []
        for slip in payslips:
            emp = slip.employee_id
            v = slip.version_id
            if not v:
                try:
                    v_ids = self.env['hr.payslip'].sudo().get_versions(emp, slip.date_from, slip.date_to)
                    if v_ids:
                        v = self.env['hr.version'].sudo().browse(v_ids[0])
                except Exception:
                    v = False

            is_proportional = False
            prop_reasons = []

            # Check mid-month hire
            if v and v.contract_date_start and p_from and v.contract_date_start > p_from:
                is_proportional = True
                prop_reasons.append(_("Joined mid-period: %s") % v.contract_date_start)

            # Check mid-month separation
            if v and v.contract_date_end and p_to and v.contract_date_end < p_to:
                is_proportional = True
                prop_reasons.append(_("Left mid-period: %s") % v.contract_date_end)

            # Check worked days lines
            worked_days_records = slip.worked_days_line_ids
            total_worked_days = sum(worked_days_records.mapped('number_of_days')) if worked_days_records else 0
            if p_from and p_to:
                period_calendar_days = (p_to - p_from).days + 1
                if 0 < total_worked_days < 20 and period_calendar_days >= 20:
                    is_proportional = True
                    prop_reasons.append(_("%s days worked") % int(total_worked_days))

            # Query net salary for slip
            net_amt = 0.0
            self.env.cr.execute("""
                SELECT COALESCE(SUM(pl.amount), 0)
                FROM hr_payslip_line pl
                JOIN hr_salary_rule_category rc ON rc.id = pl.category_id
                WHERE pl.slip_id = %s AND (rc.code = 'NET' OR pl.code = 'NET')
            """, (slip.id,))
            row = self.env.cr.fetchone()
            if row:
                net_amt = float(row[0] or 0.0)

            if is_proportional:
                proportional_slips_list.append({
                    'id': slip.id,
                    'number': slip.number or _('Draft Slip'),
                    'employee_id': emp.id,
                    'employee_name': emp.name,
                    'department': emp.department_id.name if emp.department_id else _('Unassigned'),
                    'reason': " & ".join(prop_reasons) if prop_reasons else _('Prorated period'),
                    'contract_start': str(v.contract_date_start) if v and v.contract_date_start else '',
                    'contract_end': str(v.contract_date_end) if v and v.contract_date_end else '',
                    'worked_days': total_worked_days or 'N/A',
                    'net_amount': round(net_amt, 2),
                })

        proportional_count = len(proportional_slips_list)

        # -------------------------------------------------------------
        # 8. Recent Batches Table (Top 5)
        # -------------------------------------------------------------
        recent_batches = []
        for b in batches[:5]:
            b_slips = b.slip_ids
            b_net = sum(b_slips.mapped('net_salary')) if hasattr(b_slips, 'net_salary') else 0.0
            if b_net == 0.0 and b_slips:
                self.env.cr.execute("""
                    SELECT COALESCE(SUM(pl.amount), 0)
                    FROM hr_payslip_line pl
                    JOIN hr_salary_rule_category rc ON rc.id = pl.category_id
                    WHERE pl.slip_id IN %s AND (rc.code = 'NET' OR pl.code = 'NET')
                """, (tuple(b_slips.ids),))
                b_net = float(self.env.cr.fetchone()[0] or 0.0)

            recent_batches.append({
                'id': b.id,
                'name': b.name,
                'state': b.state,
                'state_label': dict(b._fields['state'].selection).get(b.state, b.state),
                'slip_count': len(b_slips),
                'net_amount': b_net,
                'date_start': str(b.date_start) if b.date_start else '',
                'date_end': str(b.date_end) if b.date_end else '',
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
