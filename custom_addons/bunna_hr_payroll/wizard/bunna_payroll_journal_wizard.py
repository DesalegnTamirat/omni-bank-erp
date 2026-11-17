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
        intermediate_codes = {'GROSS', 'TAXINC'}

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

            if rule.account_debit:
                acc_code = rule.account_debit.code or '0155010010'
                acc_name = rule.account_debit.name or rule.name
                full_acc = f"{sol}{acc_code}"
                key = ('10', 'D', ou_id, ou_name, sol, report_code, full_acc, acc_name, acc_name)
                gl_aggregates[key] += line.total
            if rule.account_credit:
                acc_code = rule.account_credit.code or '0155010010'
                acc_name = rule.account_credit.name or rule.name
                full_acc = f"{sol}{acc_code}"
                key = ('10', 'C', ou_id, ou_name, sol, report_code, full_acc, acc_name, acc_name)
                gl_aggregates[key] += line.total
            if not rule.account_debit and not rule.account_credit:
                # Infer side if not configured on rule
                if cat_code in ('BASIC', 'ALW'):
                    acc_code = '0155010010'
                    acc_name = rule.name
                    full_acc = f"{sol}{acc_code}"
                    key = ('10', 'D', ou_id, ou_name, sol, report_code, full_acc, acc_name, acc_name)
                    gl_aggregates[key] += line.total
                elif cat_code in ('NET', 'TAX', 'DED', 'Emp_cont', 'ADHDED') or rule_code in ('NET', 'TAX', 'PF', 'OD', 'PENSION', 'LU', 'ASBEZA', 'CIAB', 'COD'):
                    acc_code = '0155010010'
                    acc_name = rule.name if cat_code != 'NET' else 'Net Salary Clearing'
                    full_acc = f"{sol}{acc_code}"
                    key = ('10', 'C', ou_id, ou_name, sol, report_code, full_acc, acc_name, acc_name)
                    gl_aggregates[key] += line.total

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

            gl_acc = rule.account_credit or rule.account_debit
            gl_code = gl_acc.code if gl_acc else '0155010010'
            gl_name = gl_acc.name if gl_acc else 'Net Salary Clearing'
            full_gl = f"{sol}{gl_code}"

            # Aggregate Debit
            key = ('20', 'D', ou_id, ou_name, sol, report_code, full_gl, gl_name, gl_name)
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
                'employee_id': emp.id,
                'employee_identification': emp_id_str,
                'payslip_id': slip.id,
                'date': self.payment_date,
                'company_id': self.company_id.id,
            })

        # Helper function for groups 30 to 70:
        def process_deduction_group(group_code, rule_code, account_field, account_label, particular_prefix, default_acc=False, is_global_credit=False, global_acc=None):
            for slip in payslips:
                line = slip.line_ids.filtered(lambda l: (l.code or '').strip().upper() == rule_code)
                if not line or line[0].total <= 0:
                    continue

                amt = line[0].total
                rule = line[0].salary_rule_id
                ou, ou_id, ou_name, sol, report_code = self._get_ou_info(slip.employee_id, slip.version_id)

                gl_acc = rule.account_credit or rule.account_debit
                gl_code = gl_acc.code if gl_acc else '0155010010'
                gl_name = gl_acc.name if gl_acc else f"{rule_code} Clearing"
                full_gl = f"{sol}{gl_code}"

                # Aggregate Debit per branch
                key = (group_code, 'D', ou_id, ou_name, sol, report_code, full_gl, gl_name, gl_name)
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
                        'date': self.payment_date,
                        'company_id': self.company_id.id,
                    })

        # ── Group 30: Overdraft (OD)
        process_deduction_group('30', 'OD', 'od_account', 'OD Account', 'OD Deduction')

        # ── Group 40: Provident Fund (PF)
        process_deduction_group('40', 'PF', 'pf_account', 'PF Account', 'PF Contribution', default_acc='1000127020390')

        # ── Group 50: Cash Indemnity (CIAB)
        process_deduction_group('50', 'CIAB', 'indemnity_account', 'Cash Indemnity Account', 'Cash Indemnity', default_acc='1000127020390')

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

            gl_acc = rule.account_credit or rule.account_debit
            gl_code = gl_acc.code if gl_acc else '0155010010'
            gl_name = gl_acc.name if gl_acc else 'Court Deduction Clearing'
            full_gl = f"{sol}{gl_code}"

            key = ('80', 'D', ou_id, ou_name, sol, report_code, full_gl, gl_name, gl_name)
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

        for slip in payslips:
            line = slip.line_ids.filtered(lambda l: (l.code or '').strip().upper() == 'OTHER')
            if not line or line[0].total <= 0:
                continue

            amt = line[0].total
            rule = line[0].salary_rule_id
            ou, ou_id, ou_name, sol, report_code = self._get_ou_info(slip.employee_id, slip.version_id)

            gl_acc = rule.account_credit or rule.account_debit
            gl_code = gl_acc.code if gl_acc else '0155010010'
            gl_name = gl_acc.name if gl_acc else 'Other Deduction Clearing'
            full_gl = f"{sol}{gl_code}"

            key = ('90', 'D', ou_id, ou_name, sol, report_code, full_gl, gl_name, gl_name)
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
                'date': self.payment_date,
                'company_id': self.company_id.id,
            })

        # ─────────────────────────────────────────────────────────────────
        # CONVERT ALL GL AGGREGATES INTO FINAL JOURNAL ENTRIES
        # ─────────────────────────────────────────────────────────────────
        for (grp, flag, ou_id, ou_name, sol, report_code, full_acc, acc_name, particular), tot_amt in gl_aggregates.items():
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
                'date': self.payment_date,
                'company_id': self.company_id.id,
            })

        # Bulk create all records
        if entries_to_create:
            self.env['bunna.payroll.journal.entry'].sudo().create(entries_to_create)

        # Return window action opening the generated entries
        action = self.env['ir.actions.actions']._for_xml_id('bunna_hr_payroll.action_bunna_payroll_journal_entry')
        action['domain'] = [('period_id', '=', period.id)]
        action['context'] = {
            'search_default_group_by_group_code': 1,
            'default_period_id': period.id,
        }
        action['name'] = _("CBS Journal Entries: %s (%d records)") % (period.name, len(entries_to_create))
        return action
