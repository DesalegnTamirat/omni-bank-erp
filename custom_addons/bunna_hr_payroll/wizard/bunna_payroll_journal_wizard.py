# -*- coding: utf-8 -*-

from collections import defaultdict
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class BunnaPayrollJournalWizard(models.TransientModel):
    _name = 'bunna.payroll.journal.wizard'
    _description = 'Generate Bunna Payroll CBS Journal Entries'

    period_id = fields.Many2one(
        'hr.payroll.period',
        string='Payroll Period',
        required=True,
        domain="[('state', '=', 'open')]",
        help='Select the payroll period for which to generate CBS journal entries.'
    )
    payment_date = fields.Date(
        string='Posting Date / Value Date',
        required=True,
        default=fields.Date.context_today
    )
    overwrite_existing = fields.Boolean(
        string='Overwrite Existing Entries for this Period',
        default=True,
        help='If checked, existing draft journal entries for this period will be deleted before generating new ones.'
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        active_model = self.env.context.get('active_model')

        period = False
        if active_model == 'hr.payroll.period' and active_id:
            period = self.env['hr.payroll.period'].browse(active_id)
            if period.state != 'open':
                period = False
        elif self.env.context.get('default_period_id'):
            period = self.env['hr.payroll.period'].browse(self.env.context.get('default_period_id'))
            if period.state != 'open':
                period = False
        else:
            # Default to the currently open period, or last period with done slips
            period = self.env['hr.payroll.period'].search([('state', '=', 'open')], limit=1)





        if period:
            res['period_id'] = period.id
            res['payment_date'] = period.payment_date or fields.Date.context_today(self)

        return res

    @api.onchange('period_id')
    def _onchange_period_id(self):
        if self.period_id and self.period_id.payment_date:
            self.payment_date = self.period_id.payment_date

    def _get_ou_info(self, employee, version):
        """Helper to extract operating unit, sol_id, and CBS report_code."""
        ou = (employee and employee.default_operating_unit_id) or (version and getattr(version, 'operating_unit_id', False))
        ou_id = ou.id if ou else False
        ou_name = ou.name if ou else 'Head Office / Unassigned'
        sol = str(ou.sol_id or '100').strip() if ou else '100'

        report_code = '0'
        if sol == '100' and ou:
            if hasattr(ou, 'code') and ou.code:
                report_code = str(ou.code.code)
            else:
                rc = self.env['hr.report.code'].sudo().search([('name', '=', ou.name)], limit=1)
                report_code = str(rc.code) if rc else '100'

        return ou, ou_id, ou_name, sol, report_code

    def action_generate_journal_entries(self):
        self.ensure_one()
        period = self.period_id
        if period.state == 'closed':
            raise UserError(_("Cannot generate CBS journal entries for a closed payroll period ('%s'). Finalized/closed periods are locked in viewing mode.") % period.name)

        # Find payslips in done status for this period
        payslips = self.env['hr.payslip'].sudo().search([
            ('period_id', '=', period.id),
            ('state', '=', 'done')
        ])

        if not payslips:
            raise UserError(_(
                "No payslips in 'Done' status were found for period '%s'.\n\n"
                "Journal entries can only be generated for confirmed payslips. "
                "Please verify that the payslips/batches for this period are computed and confirmed (Done)."
            ) % period.name)

        # Clear existing entries if requested
        if self.overwrite_existing:
            self.env['bunna.payroll.journal.entry'].sudo().search([
                ('period_id', '=', period.id)
            ]).unlink()

        entries_to_create = []

        # Aggregator dictionary for GL summary lines:
        # key: (group_code, flag, ou_id, ou_name, sol_id, report_code, account, account_name, particular) -> total amount
        gl_aggregates = defaultdict(float)

        # Pre-fetch all payslip lines for confirmed payslips
        lines = payslips.mapped('line_ids').filtered(lambda l: l.total > 0)

        # ─────────────────────────────────────────────────────────────────
        # GROUP 10: BASE PAYROLL ACCOUNTING (Earnings, Taxes, Net Clearing, Deductions)
        # Gross Earnings (Debits) = Net Salary + All Deductions + Taxes (Credits)
        # ─────────────────────────────────────────────────────────────────
        intermediate_codes = {'GROSS', 'TAXINC', 'TOTEXE', 'UNPAID', 'TAXABLE'}

        # Pre-fetch Cash Indemnity adjustment lines strictly for the current period
        rule_ciab = self.env['hr.salary.rule'].sudo().search([('code', '=', 'CIAB')], limit=1)
        rule_ciab_id = rule_ciab.id if rule_ciab else False

        ci_domain = [
            ('employee_id', 'in', payslips.mapped('employee_id').ids),
            ('active', '=', True),
            ('adjustment_id.active', '=', True),
            '|', '|', '|',
            ('code', 'in', ('CIA', 'CIA-ALL', 'CASH_INDEMNITY', 'CIAB')),
            ('adjustment_id.code', 'in', ('CIA', 'CIA-ALL', 'CASH_INDEMNITY', 'CIAB')),
            ('adjustment_id.name', 'ilike', 'Cash Indemnity'),
            ('ciamount', '>', 0)
        ]
        period_conds = []
        if 'payroll_period_id' in self.env['hr.payroll.adjustment.line']._fields:
            period_conds.append(('payroll_period_id', '=', period.id))
        elif 'payroll_period_id' in self.env['hr.payroll.adjustment']._fields:
            period_conds.append(('adjustment_id.payroll_period_id', '=', period.id))

        if 'period_id' in self.env['hr.payroll.adjustment.line']._fields:
            period_conds.append(('period_id', '=', period.id))
        elif 'period_id' in self.env['hr.payroll.adjustment']._fields:
            period_conds.append(('adjustment_id.period_id', '=', period.id))

        if period.name:
            period_conds.append(('adjustment_id.name', 'ilike', period.name))

        if period_conds:
            ci_period_filter = ['|'] * (len(period_conds) - 1)
            ci_period_filter.extend(period_conds)
            ci_domain.extend(ci_period_filter)

        ci_adj_lines = self.env['hr.payroll.adjustment.line'].sudo().search(ci_domain)
        ci_emp_adj_map = defaultdict(list)
        for al in ci_adj_lines:
            ci_emp_adj_map[al.employee_id.id].append(al)

        for line in lines:
            rule = line.salary_rule_id
            if not rule:
                continue
            rule_code = (rule.code or '').strip().upper()
            cat_code = (rule.category_id.code or '').strip().upper() if rule.category_id else ''

            if rule_code in intermediate_codes:
                continue

            slip = line.slip_id
            ou, ou_id, ou_name, sol, report_code = self._get_ou_info(slip.employee_id, slip.version_id)
            is_ifb = bool(ou and getattr(ou, 'is_ifb', False))
            line_amt = line.total

            if line_amt <= 0:
                continue

            # CIAB is a deduction funding the Cash Indemnity Payable pool (0127020305 or IFB equivalent)
            # It must ALWAYS post as a CREDIT (C) to CIAB payable
            if rule_code == 'CIAB':
                acc_ciab = rule.get_rule_account_credit(is_ifb=is_ifb)
                ciab_code = acc_ciab.code if acc_ciab else '0127020305'
                ciab_name = acc_ciab.name if acc_ciab else "CASH INDEMNITY ALLOWANCE PAYABLE"
                full_acc = f"{sol}{ciab_code}"
                key = ('10', 'C', ou_id, ou_name, sol, report_code, full_acc, ciab_name, ciab_name, rule.id)
                gl_aggregates[key] += line_amt
                continue

            acc_deb = rule.get_rule_account_debit(is_ifb=is_ifb)
            acc_cred = rule.get_rule_account_credit(is_ifb=is_ifb)

            if acc_deb:
                acc_code = acc_deb.code or '0155010010'
                acc_name = acc_deb.name or rule.name
                full_acc = f"{sol}{acc_code}"
                key = ('10', 'D', ou_id, ou_name, sol, report_code, full_acc, acc_name, acc_name, rule.id)
                gl_aggregates[key] += line_amt
            if acc_cred:
                acc_code = acc_cred.code or '0155010010'
                acc_name = acc_cred.name or rule.name
                full_acc = f"{sol}{acc_code}"
                key = ('10', 'C', ou_id, ou_name, sol, report_code, full_acc, acc_name, acc_name, rule.id)
                gl_aggregates[key] += line_amt
            if not acc_deb and not acc_cred:
                # Infer side if not configured on rule
                if cat_code in ('BASIC', 'ALW'):
                    acc_code = '0155010010'
                    acc_name = rule.name
                    full_acc = f"{sol}{acc_code}"
                    key = ('10', 'D', ou_id, ou_name, sol, report_code, full_acc, acc_name, acc_name, rule.id)
                    gl_aggregates[key] += line_amt
                elif cat_code in ('NET', 'TAX', 'DED', 'Emp_cont', 'ADHDED') or rule_code in ('NET', 'TAX', 'PF', 'OD', 'PENSION', 'LU', 'ASBEZA', 'CIAB', 'COD'):
                    acc_code = '0155010010'
                    acc_name = rule.name if cat_code != 'NET' else 'Net Salary Clearing'
                    full_acc = f"{sol}{acc_code}"
                    key = ('10', 'C', ou_id, ou_name, sol, report_code, full_acc, acc_name, acc_name, rule.id)
                    gl_aggregates[key] += line_amt

        # ── Group 10: Cash Indemnity Clearing
        # In Group 10, CIAB (1,481.82) is credited to 0127020305 (or IFB GL).
        # Net Salary (NET) includes tax_amount (501.14) and cia_salary (480.68) to offset CIAB.
        # To balance Group 10 and clear the Cash Indemnity pool,
        # the clearing account is debited by sal_amt (Salary Clearing) and tax_amt (Tax Clearing).
        # The remaining balance is debited in Group 50 to pay the cashier.
        for slip in payslips:
            emp_lines = ci_emp_adj_map.get(slip.employee_id.id, [])
            sal_amt = sum(al.salary_amount for al in emp_lines if al.salary_amount) if emp_lines else 0.0
            tax_amt = sum(al.tax_amount for al in emp_lines if al.tax_amount) if emp_lines else 0.0

            if sal_amt <= 0 and tax_amt <= 0:
                emp_adj_fallback = self.env['hr.payroll.adjustment.line'].sudo().search([
                    ('employee_id', '=', slip.employee_id.id),
                    ('active', '=', True),
                    ('adjustment_id.active', '=', True),
                    '|', '|',
                    ('code', 'in', ('CIA', 'CIA-ALL', 'CASH_INDEMNITY', 'CIAB')),
                    ('adjustment_id.code', 'in', ('CIA', 'CIA-ALL', 'CASH_INDEMNITY', 'CIAB')),
                    ('adjustment_id.name', 'ilike', 'Cash Indemnity')
                ], order='id desc')
                if emp_adj_fallback:
                    sal_amt = sum(al.salary_amount for al in emp_adj_fallback if al.salary_amount)
                    tax_amt = sum(al.tax_amount for al in emp_adj_fallback if al.tax_amount)

            if sal_amt <= 0 and tax_amt <= 0:
                continue

            ou, ou_id, ou_name, sol, report_code = self._get_ou_info(slip.employee_id, slip.version_id)
            is_ifb = bool(ou and getattr(ou, 'is_ifb', False))
            acc_ciab = rule_ciab.get_rule_account_credit(is_ifb=is_ifb) if rule_ciab else False
            ci_clearing_code = acc_ciab.code if acc_ciab else '0127020305'
            ci_clearing_name = acc_ciab.name if acc_ciab else "CASH INDEMNITY ALLOWANCE PAYABLE"

            if sal_amt > 0:
                key_d = ('10', 'D', ou_id, ou_name, sol, report_code, f"{sol}{ci_clearing_code}", ci_clearing_name, "Cash Indemnity - Salary Clearing", rule_ciab_id)
                gl_aggregates[key_d] += sal_amt

            if tax_amt > 0:
                key_d = ('10', 'D', ou_id, ou_name, sol, report_code, f"{sol}{ci_clearing_code}", ci_clearing_name, "Cash Indemnity - Tax Clearing", rule_ciab_id)
                gl_aggregates[key_d] += tax_amt

        # ─────────────────────────────────────────────────────────────────
        # GROUP 20: NET SALARY DISBURSEMENT
        # ─────────────────────────────────────────────────────────────────
        for slip in payslips:
            net_line = slip.line_ids.filtered(lambda l: (l.salary_rule_id.category_id.code or '').strip().upper() == 'NET' or (l.code or '').strip().upper() == 'NET')
            if not net_line or net_line[0].total <= 0:
                continue

            amt = net_line[0].total
            rule = net_line[0].salary_rule_id
            ou, ou_id, ou_name, sol, report_code = self._get_ou_info(slip.employee_id, slip.version_id)
            is_ifb = bool(ou and getattr(ou, 'is_ifb', False))

            gl_acc = (rule.get_rule_account_credit(is_ifb=is_ifb) if rule else False) or (rule.get_rule_account_debit(is_ifb=is_ifb) if rule else False)
            gl_code = gl_acc.code if gl_acc else '0155010010'
            gl_name = gl_acc.name if gl_acc else 'Net Salary Clearing'
            full_gl = f"{sol}{gl_code}"

            rule_id_net = rule.id if rule else False

            # Aggregate Debit (track rule_id so per-rule balance can pinpoint imbalance)
            key = ('20', 'D', ou_id, ou_name, sol, report_code, full_gl, gl_name, gl_name, rule_id_net)
            gl_aggregates[key] += amt

            # Individual Credit to Employee
            version = slip.version_id
            emp = slip.employee_id
            emp_account = (version and version.salary_account) or emp.salary_account or '1000127020390'
            emp_id_str = emp.employee_identification or ''
            particular = f"Net Salary - {emp_id_str} - {emp.name}"

            entries_to_create.append({
                'period_id': period.id,
                'operating_unit_id': ou_id,
                'work_unit_id': ou_id,
                'ou_name': ou_name,
                'sol_id': sol,
                'report_code': report_code,
                'account': emp_account,
                'account_name': 'Salary Account',
                'particular': particular,
                'flag': 'C',
                'amount': amt,
                'currency': 'ETB',
                'group_code': '20',
                'salary_rule_id': rule_id_net,
                'employee_id': emp.id,
                'employee_identification': emp_id_str,
                'payslip_id': slip.id,
                'date': self.payment_date,
                'company_id': self.company_id.id,
            })

        # Helper function for groups 30 to 70:
        def process_deduction_group(group_code, rule_code, account_field, account_label, particular_prefix, default_acc=False, is_global_credit=False, global_acc=None):
            captured_rule_id = False  # Track the salary rule that drives this group
            for slip in payslips:
                line = slip.line_ids.filtered(lambda l: (l.code or '').strip().upper() == rule_code)
                if not line or line[0].total <= 0:
                    continue

                amt = line[0].total
                rule = line[0].salary_rule_id
                captured_rule_id = rule.id if rule else False
                ou, ou_id, ou_name, sol, report_code = self._get_ou_info(slip.employee_id, slip.version_id)
                is_ifb = bool(ou and getattr(ou, 'is_ifb', False))

                gl_acc = (rule.get_rule_account_credit(is_ifb=is_ifb) if rule else False) or (rule.get_rule_account_debit(is_ifb=is_ifb) if rule else False)
                gl_code = gl_acc.code if gl_acc else '0155010010'
                gl_name = gl_acc.name if gl_acc else f"{rule_code} Clearing"
                full_gl = f"{sol}{gl_code}"

                # Aggregate Debit per branch — keyed with rule_id for per-rule balance checking
                key = (group_code, 'D', ou_id, ou_name, sol, report_code, full_gl, gl_name, gl_name, captured_rule_id)
                gl_aggregates[key] += amt

                version = slip.version_id
                emp = slip.employee_id
                emp_id_str = emp.employee_identification or ''

                if not is_global_credit:
                    dest_acc = (version and getattr(version, account_field, False)) or getattr(emp, account_field, False) or default_acc
                    entries_to_create.append({
                        'period_id': period.id,
                        'operating_unit_id': ou_id,
                        'work_unit_id': ou_id,
                        'ou_name': ou_name,
                        'sol_id': sol,
                        'report_code': report_code,
                        'account': dest_acc,
                        'account_name': account_label,
                        'particular': f"{particular_prefix} - {emp_id_str} - {emp.name}",
                        'flag': 'C',
                        'amount': amt,
                        'currency': 'ETB',
                        'group_code': group_code,
                        'salary_rule_id': captured_rule_id,
                        'employee_id': emp.id,
                        'employee_identification': emp_id_str,
                        'payslip_id': slip.id,
                        'date': self.payment_date,
                        'company_id': self.company_id.id,
                    })

            if is_global_credit:
                # Sum total for global master credit account
                total_global = sum(gl_aggregates[k] for k in gl_aggregates if k[0] == group_code and k[1] == 'D')
                if total_global > 0:
                    entries_to_create.append({
                        'period_id': period.id,
                        'operating_unit_id': False,
                        'work_unit_id': 0,
                        'ou_name': 'Head Office / Global',
                        'sol_id': '100',
                        'report_code': '0',
                        'account': global_acc,
                        'account_name': account_label,
                        'particular': particular_prefix,
                        'flag': 'C',
                        'amount': total_global,
                        'currency': 'ETB',
                        'group_code': group_code,
                        'salary_rule_id': captured_rule_id,
                        'date': self.payment_date,
                        'company_id': self.company_id.id,
                    })

        # ── Group 30: Overdraft (OD)
        process_deduction_group('30', 'OD', 'od_account', 'OD Account', 'OD Deduction')

        # ── Group 40: Provident Fund (PF)
        process_deduction_group('40', 'PF', 'pf_account', 'PF Account', 'PF Contribution', default_acc='1000127020390')

        # ── Group 50: Cash Indemnity (CIAB)
        # 3. 0127020305 CASH INDEMNITY ALLOWANCE PAYABLE debited by cia_amount, credited to employee's Cash Indemnity Account
        for slip in payslips:
            emp = slip.employee_id
            emp_lines = ci_emp_adj_map.get(emp.id, [])
            cia_amt = sum(al.ciamount for al in emp_lines if al.ciamount)
            if not cia_amt:
                cia_line = slip.line_ids.filtered(lambda l: (l.code or '').strip().upper() in ('CIA', 'CIA-ALL'))
                cia_amt = cia_line[0].total if cia_line else 0.0

            if cia_amt <= 0:
                continue

            ou, ou_id, ou_name, sol, report_code = self._get_ou_info(emp, slip.version_id)
            is_ifb = bool(ou and getattr(ou, 'is_ifb', False))
            acc_ciab = rule_ciab.get_rule_account_credit(is_ifb=is_ifb) if rule_ciab else False
            ci_clearing_code = acc_ciab.code if acc_ciab else '0127020305'
            ci_clearing_name = acc_ciab.name if acc_ciab else "CASH INDEMNITY ALLOWABLE PAYABLE"

            # Debit clearing account by cia_amount
            key = ('50', 'D', ou_id, ou_name, sol, report_code, f"{sol}{ci_clearing_code}", ci_clearing_name, "Cash Indemnity Allowance", rule_ciab_id)
            gl_aggregates[key] += cia_amt

            # Credit employee's Cash Indemnity Account
            emp_id_str = emp.employee_identification or ''
            dest_acc = (emp_lines and emp_lines[0].bank_account) or (slip.version_id and getattr(slip.version_id, 'indemnity_account', False)) or getattr(emp, 'indemnity_account', False) or (slip.version_id and slip.version_id.salary_account) or emp.salary_account or '1000127020390'

            entries_to_create.append({
                'period_id': period.id,
                'operating_unit_id': ou_id,
                'work_unit_id': ou_id,
                'ou_name': ou_name,
                'sol_id': sol,
                'report_code': report_code,
                'account': dest_acc,
                'account_name': 'Cash Indemnity Account',
                'particular': f"Cash Indemnity - {emp_id_str} - {emp.name}",
                'flag': 'C',
                'amount': round(cia_amt, 2),
                'currency': 'ETB',
                'group_code': '50',
                'salary_rule_id': rule_ciab_id,
                'employee_id': emp.id,
                'employee_identification': emp_id_str,
                'payslip_id': slip.id,
                'date': self.payment_date,
                'company_id': self.company_id.id,
            })

        # ── Group 60: ASBEZA
        process_deduction_group('60', 'ASBEZA', 'asbeza_account', 'ASBEZA Account', 'ASBEZA')

        # ── Group 70: Labour Union (LU)
        process_deduction_group('70', 'LU', None, 'Labour Union', 'Labour Union contribution', is_global_credit=True, global_acc='1019523000264')

        # ─────────────────────────────────────────────────────────────────
        # GROUP 80: COURT ORDER DEDUCTIONS (COD)
        # ─────────────────────────────────────────────────────────────────
        for slip in payslips:
            line = slip.line_ids.filtered(lambda l: (l.code or '').strip().upper() == 'COD')
            if not line or line[0].total <= 0:
                continue

            amt = line[0].total
            rule = line[0].salary_rule_id
            ou, ou_id, ou_name, sol, report_code = self._get_ou_info(slip.employee_id, slip.version_id)
            is_ifb = bool(ou and getattr(ou, 'is_ifb', False))

            gl_acc = (rule.get_rule_account_credit(is_ifb=is_ifb) if rule else False) or (rule.get_rule_account_debit(is_ifb=is_ifb) if rule else False)
            gl_code = gl_acc.code if gl_acc else '0155010010'
            gl_name = gl_acc.name if gl_acc else 'Court Deduction Clearing'
            full_gl = f"{sol}{gl_code}"

            key = ('80', 'D', ou_id, ou_name, sol, report_code, full_gl, gl_name, gl_name, rule.id if rule else False)
            gl_aggregates[key] += amt

            emp = slip.employee_id
            emp_id_str = emp.employee_identification or ''

            adj_line = self.env['hr.payroll.adjustment.line'].sudo().search([
                ('employee_id', '=', emp.id),
                ('active', '=', True),
                ('adjustment_id.active', '=', True),
                '|', ('code', '=', 'COD'), ('adjustment_id.code', '=', 'COD')
            ], limit=1)

            dest_acc = adj_line.bank_account if adj_line and adj_line.bank_account else '1000127020390'

            entries_to_create.append({
                'period_id': period.id,
                'operating_unit_id': ou_id,
                'work_unit_id': ou_id,
                'ou_name': ou_name,
                'sol_id': sol,
                'report_code': report_code,
                'account': dest_acc,
                'account_name': 'Court Deduction',
                'particular': f"Court Deduction - {emp_id_str} - {emp.name}",
                'flag': 'C',
                'amount': amt,
                'currency': 'ETB',
                'group_code': '80',
                'salary_rule_id': rule.id if rule else False,
                'employee_id': emp.id,
                'employee_identification': emp_id_str,
                'payslip_id': slip.id,
                'date': self.payment_date,
                'company_id': self.company_id.id,
            })

        # ─────────────────────────────────────────────────────────────────
        # GROUP 90: OTHER DEDUCTIONS (OTHER)
        # ─────────────────────────────────────────────────────────────────
        other_credits = defaultdict(float)
        other_rule_id = False  # capture the salary rule_id for group 90

        for slip in payslips:
            line = slip.line_ids.filtered(lambda l: (l.code or '').strip().upper() == 'OTHER')
            if not line or line[0].total <= 0:
                continue

            amt = line[0].total
            rule = line[0].salary_rule_id
            other_rule_id = rule.id if rule else False
            ou, ou_id, ou_name, sol, report_code = self._get_ou_info(slip.employee_id, slip.version_id)
            is_ifb = bool(ou and getattr(ou, 'is_ifb', False))

            gl_acc = (rule.get_rule_account_credit(is_ifb=is_ifb) if rule else False) or (rule.get_rule_account_debit(is_ifb=is_ifb) if rule else False)
            gl_code = gl_acc.code if gl_acc else '0155010010'
            gl_name = gl_acc.name if gl_acc else 'Other Deduction Clearing'
            full_gl = f"{sol}{gl_code}"

            key = ('90', 'D', ou_id, ou_name, sol, report_code, full_gl, gl_name, gl_name, other_rule_id)
            gl_aggregates[key] += amt

            adj_lines = self.env['hr.payroll.adjustment.line'].sudo().search([
                ('employee_id', '=', slip.employee_id.id),
                ('active', '=', True),
                ('adjustment_id.active', '=', True),
                '|', ('code', '=', 'OTHER'), ('adjustment_id.code', '=', 'OTHER')
            ])

            if adj_lines:
                for al in adj_lines:
                    dest = al.bank_account or '1000127020390'
                    ckey = (ou_id, ou_name, sol, report_code, dest)
                    other_credits[ckey] += al.amount
            else:
                dest = '1000127020390'
                ckey = (ou_id, ou_name, sol, report_code, dest)
                other_credits[ckey] += amt

        for (ou_id, ou_name, sol, report_code, dest_acc), oamt in other_credits.items():
            entries_to_create.append({
                'period_id': period.id,
                'operating_unit_id': ou_id,
                'work_unit_id': ou_id,
                'ou_name': ou_name,
                'sol_id': sol,
                'report_code': report_code,
                'account': dest_acc,
                'account_name': 'Other Deduction',
                'particular': f"Other Deduction - {dest_acc}",
                'flag': 'C',
                'amount': oamt,
                'currency': 'ETB',
                'group_code': '90',
                'salary_rule_id': other_rule_id,
                'date': self.payment_date,
                'company_id': self.company_id.id,
            })

        # ─────────────────────────────────────────────────────────────────
        # CONVERT ALL GL AGGREGATES INTO FINAL JOURNAL ENTRIES
        # ─────────────────────────────────────────────────────────────────
        for (grp, flag, ou_id, ou_name, sol, report_code, full_acc, acc_name, particular, rule_id), tot_amt in gl_aggregates.items():
            if tot_amt <= 0:
                continue
            entries_to_create.append({
                'period_id': period.id,
                'operating_unit_id': ou_id,
                'work_unit_id': ou_id,
                'ou_name': ou_name,
                'sol_id': sol,
                'report_code': report_code,
                'account': full_acc,
                'account_name': acc_name,
                'particular': particular,
                'flag': flag,
                'amount': round(tot_amt, 2),
                'currency': 'ETB',
                'group_code': grp,
                'salary_rule_id': rule_id or False,
                'date': self.payment_date,
                'company_id': self.company_id.id,
            })

        # Bulk create all records
        if entries_to_create:
            created = self.env['bunna.payroll.journal.entry'].sudo().create(entries_to_create)
            # Trigger balance compute for is_group_unbalanced and group_balance_diff
            created._compute_group_balance()
        else:
            created = self.env['bunna.payroll.journal.entry']

        # Return window action opening the generated entries
        action = self.env['ir.actions.actions']._for_xml_id('bunna_hr_payroll.action_bunna_payroll_journal_entry')
        action['domain'] = [('period_id', '=', period.id)]
        action['context'] = {
            'search_default_group_by_group_code': 1,
            'default_period_id': period.id,
        }

        # Check for unbalanced groups and warn the user / auto-filter
        # Use group-level for the alert (meaningful CBS unit) but entry-level for the filter
        unbalanced = created.filtered('is_group_unbalanced')
        unbalanced_groups = sorted(set(unbalanced.mapped('group_code')))
        if unbalanced_groups:
            grp_labels = dict(self.env['bunna.payroll.journal.entry']._fields['group_code'].selection)
            grp_names = ', '.join(grp_labels.get(g, g) for g in unbalanced_groups)
            action['name'] = _(
                "CBS Journal Entries: %s - UNBALANCED GROUPS: %s"
            ) % (period.name, grp_names)
            # Auto-filter to only unbalanced entry rows so user can identify the culprit rules
            action['context']['search_default_filter_unbalanced'] = 1
        else:
            action['name'] = _(
                "CBS Journal Entries: %s (%d records) - All Groups Balanced"
            ) % (period.name, len(entries_to_create))

        return action
