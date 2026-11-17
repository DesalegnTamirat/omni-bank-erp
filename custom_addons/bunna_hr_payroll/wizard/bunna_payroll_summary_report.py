# -*- coding: utf-8 -*-

import io
import csv
import base64
import logging
from datetime import datetime, date
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class BunnaPayrollSummaryReportWizard(models.TransientModel):
    _name = 'bunna.payroll.summary.report.wizard'
    _description = 'Payroll Summary Report Wizard'

    @api.model
    def _default_period(self):
        period = self.env['hr.payroll.period'].search([('state', '=', 'open')], limit=1)
        if not period:
            period = self.env['hr.payroll.period'].search([], order='date_from desc', limit=1)
        return period

    period_id = fields.Many2one(
        'hr.payroll.period',
        string='Payroll Period',
        required=True,
        default=_default_period,
        help='Select the payroll period to report on.'
    )
    date_from = fields.Date(
        string='Start Date',
        related='period_id.date_from',
        readonly=False,
        store=True,
    )
    date_to = fields.Date(
        string='End Date',
        related='period_id.date_to',
        readonly=False,
        store=True,
    )
    payment_date = fields.Date(
        string='Date of Payment',
        related='period_id.payment_date',
        readonly=False,
        store=True,
    )
    payslip_run_id = fields.Many2one(
        'hr.payslip.run',
        string='Payslip Batch',
        domain="[('period_id', '=', period_id)]",
        help='Optionally filter by a specific payslip batch, or leave empty for all batches.'
    )
    state = fields.Selection([
        ('all', 'All (Draft & Done)'),
        ('done', 'Done Only'),
        ('draft', 'Draft Only'),
    ], string='Payslip Status', default='all', required=True)

    line_ids = fields.One2many(
        'bunna.payroll.summary.report.line',
        'wizard_id',
        string='Report Lines'
    )
    total_employees = fields.Integer(string='Total Employees', compute='_compute_totals')
    total_gross = fields.Float(string='Total Gross', digits=(16, 2), compute='_compute_totals')
    total_tax = fields.Float(string='Total Tax', digits=(16, 2), compute='_compute_totals')
    total_pension_emp = fields.Float(string='Total Pension (7%)', digits=(16, 2), compute='_compute_totals')
    total_pension_bnk = fields.Float(string='Total Pension (11%)', digits=(16, 2), compute='_compute_totals')
    total_deductions = fields.Float(string='Total Deductions', digits=(16, 2), compute='_compute_totals')
    total_net = fields.Float(string='Total Net Salary', digits=(16, 2), compute='_compute_totals')

    @api.depends('line_ids')
    def _compute_totals(self):
        for wiz in self:
            lines = wiz.line_ids
            wiz.total_employees = len(lines)
            wiz.total_gross = sum(lines.mapped('gross'))
            wiz.total_tax = sum(lines.mapped('income_tax'))
            wiz.total_pension_emp = sum(lines.mapped('pension_emp'))
            wiz.total_pension_bnk = sum(lines.mapped('pension_bnk'))
            wiz.total_deductions = sum(lines.mapped('total_ded'))
            wiz.total_net = sum(lines.mapped('net'))

    @api.onchange('period_id')
    def _onchange_period_id(self):
        if self.period_id:
            self.date_from = self.period_id.date_from
            self.date_to = self.period_id.date_to
            self.payment_date = self.period_id.payment_date
            self.payslip_run_id = False

    def _get_field_expr(self, table_name, col_name, table_alias):
        """Returns a safe SQL text extraction expression for JSONB or VARCHAR columns."""
        self.env.cr.execute("""
            SELECT data_type 
            FROM information_schema.columns 
            WHERE table_name = %s AND column_name = %s
        """, (table_name, col_name))
        row = self.env.cr.fetchone()
        if not row:
            return "''"
        data_type = str(row[0]).lower()
        lang = self.env.lang or 'en_US'
        if data_type in ('json', 'jsonb'):
            return f"COALESCE({table_alias}.{col_name}->>'{lang}', {table_alias}.{col_name}->>'en_US', {table_alias}.{col_name}::text, '')"
        else:
            return f"COALESCE({table_alias}.{col_name}, '')"

    def _get_report_data(self):
        """Ultra-fast bulk SQL query grouping payslip lines horizontally with full aggregate protection."""
        self.ensure_one()

        where_clauses = ["p.period_id = %s"]
        params = [self.period_id.id]

        if self.state == 'done':
            where_clauses.append("p.state = 'done'")
        elif self.state == 'draft':
            where_clauses.append("p.state = 'draft'")
        else:
            where_clauses.append("p.state != 'cancel'")

        if self.payslip_run_id:
            where_clauses.append("p.payslip_run_id = %s")
            params.append(self.payslip_run_id.id)

        where_sql = " AND ".join(where_clauses)

        # Dynamic schema detection for employee columns
        self.env.cr.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'hr_employee'
              AND column_name IN ('default_operating_unit_id', 'operating_unit_id', 'department_id', 'bank_account_id')
        """)
        emp_cols = {row[0] for row in self.env.cr.fetchall()}

        emp_expr = self._get_field_expr('hr_employee', 'name', 'e')

        if 'default_operating_unit_id' in emp_cols:
            ou_join = "LEFT JOIN operating_unit ou ON ou.id = e.default_operating_unit_id"
            ou_expr = self._get_field_expr('operating_unit', 'name', 'ou')
        elif 'operating_unit_id' in emp_cols:
            ou_join = "LEFT JOIN operating_unit ou ON ou.id = e.operating_unit_id"
            ou_expr = self._get_field_expr('operating_unit', 'name', 'ou')
        else:
            ou_join = ""
            ou_expr = "''"

        if 'department_id' in emp_cols:
            dept_join = "LEFT JOIN hr_department d ON d.id = e.department_id"
            dept_expr = self._get_field_expr('hr_department', 'name', 'd')
        else:
            dept_join = ""
            dept_expr = "''"

        if 'bank_account_id' in emp_cols:
            bank_join = "LEFT JOIN res_partner_bank ba ON ba.id = e.bank_account_id"
            bank_expr = self._get_field_expr('res_partner_bank', 'acc_number', 'ba')
        else:
            bank_join = ""
            bank_expr = "''"

        query = f"""
            SELECT
                p.id AS slip_id,
                p.employee_id,
                MAX(COALESCE(NULLIF(e.barcode, ''), NULLIF(e.identification_id, ''), e.id::text)) AS emp_code,
                MAX({emp_expr}) AS emp_name,
                MAX(COALESCE(r.name, 'No Batch')) AS batch_name,
                MAX({dept_expr}) AS dept_name,
                MAX({ou_expr}) AS ou_name,
                MAX({bank_expr}) AS bank_acc,
                p.date_from,
                p.date_to,
                p.state,
                SUM(CASE WHEN pl.code = 'BASIC' THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS basic,
                SUM(CASE WHEN pl.code = 'HOUSERENT' THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS house_rent,
                SUM(CASE WHEN pl.code = 'FUEL' THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS fuel,
                SUM(CASE WHEN pl.code = 'RA' THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS rep_alw,
                SUM(CASE WHEN pl.code = 'TRANSPORT' THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS transport,
                SUM(CASE WHEN pl.code = 'HARDSHIP' THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS hardship,
                SUM(CASE WHEN pl.code = 'CIA' THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS cia,
                SUM(CASE WHEN pl.code = 'MOBILE' THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS mobile,
                SUM(CASE WHEN pl.code = 'ACTING' THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS acting,
                SUM(CASE WHEN pl.code = 'DISTURB' THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS disturb,
                SUM(CASE WHEN pl.code IN ('OT', 'OVERTIME') THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS overtime,
                SUM(CASE WHEN pl.code = 'GROSS' THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS gross,
                SUM(CASE WHEN pl.code = 'TOTEXE' THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS totexe,
                SUM(CASE WHEN pl.code = 'TAXINC' THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS taxinc,
                SUM(CASE WHEN pl.code = 'IT' THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS income_tax,
                SUM(CASE WHEN pl.code = 'PENSION' THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS pension_emp,
                SUM(CASE WHEN pl.code = 'PENSION_BNK' THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS pension_bnk,
                SUM(CASE WHEN pl.code = 'PF' THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS pf,
                SUM(CASE WHEN pl.code = 'CIAB' THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS ciab,
                SUM(CASE WHEN pl.code = 'CS' THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS cost_sharing,
                SUM(CASE WHEN pl.code = 'LU' THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS labour_union,
                SUM(CASE WHEN pl.code = 'PENALTY' THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS penalty,
                SUM(CASE WHEN pl.code = 'COD' THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS cod,
                SUM(CASE WHEN pl.code IN ('OTHER', 'OD', 'ASBEZA') THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS other_ded,
                SUM(CASE WHEN pl.code = 'NET' THEN COALESCE(pl.amount, 0.0) ELSE 0 END) AS net
            FROM hr_payslip p
            JOIN hr_employee e ON e.id = p.employee_id
            LEFT JOIN hr_payslip_run r ON r.id = p.payslip_run_id
            {dept_join}
            {ou_join}
            {bank_join}
            LEFT JOIN hr_payslip_line pl ON pl.slip_id = p.id
            WHERE {where_sql}
            GROUP BY p.id, p.employee_id, p.date_from, p.date_to, p.state
            ORDER BY MAX(r.name), MAX(e.name)
        """
        self.env.cr.execute(query, tuple(params))
        rows = self.env.cr.dictfetchall()

        # Helper to ensure any JSON/dict return is safely converted to clean string
        def clean_str(val):
            if isinstance(val, dict):
                lang = self.env.lang or 'en_US'
                return str(val.get(lang) or val.get('en_US') or next(iter(val.values()), ''))
            return str(val or '')

        # Calculate other allowances & total deductions dynamically
        for r in rows:
            r['emp_name'] = clean_str(r.get('emp_name'))
            r['dept_name'] = clean_str(r.get('dept_name'))
            r['ou_name'] = clean_str(r.get('ou_name'))
            r['bank_acc'] = clean_str(r.get('bank_acc'))

            all_alw_explicit = (
                r['basic'] + r['house_rent'] + r['fuel'] + r['rep_alw'] +
                r['transport'] + r['hardship'] + r['cia'] + r['mobile'] +
                r['acting'] + r['disturb'] + r['overtime']
            )
            r['other_alw'] = max(0.0, r['gross'] - all_alw_explicit)

            ded_sum = (
                r['income_tax'] + r['pension_emp'] + r['ciab'] +
                r['cost_sharing'] + r['labour_union'] + r['penalty'] +
                r['cod'] + r['other_ded']
            )
            r['total_ded'] = ded_sum if ded_sum > 0 else max(0.0, r['gross'] - r['net'])

        return rows

    def _populate_lines(self):
        """Populates the transient line records for interactive list view."""
        self.ensure_one()
        self.line_ids.unlink()

        rows = self._get_report_data()
        if not rows:
            raise UserError(_("No payslips found for period '%s' matching the selected criteria.") % self.period_id.name)

        lines_val = []
        payment_date = self.payment_date or self.period_id.payment_date or self.date_to
        for r in rows:
            lines_val.append({
                'wizard_id': self.id,
                'slip_id': r['slip_id'],
                'employee_id': r['employee_id'],
                'employee_code': r['emp_code'],
                'employee_name': r['emp_name'],
                'batch_name': r['batch_name'],
                'operating_unit_name': r.get('ou_name', ''),
                'department_name': r.get('dept_name', ''),
                'period_id': self.period_id.id,
                'period_name': self.period_id.name,
                'date_from': r['date_from'],
                'date_to': r['date_to'],
                'payment_date': payment_date,
                'state': r['state'],
                'bank_acc': r.get('bank_acc', ''),
                'basic': r['basic'],
                'house_rent': r['house_rent'],
                'fuel': r['fuel'],
                'rep_alw': r['rep_alw'],
                'transport': r['transport'],
                'hardship': r['hardship'],
                'cia': r['cia'],
                'mobile': r['mobile'],
                'acting': r['acting'],
                'disturb': r['disturb'],
                'overtime': r['overtime'],
                'other_alw': r['other_alw'],
                'gross': r['gross'],
                'totexe': r['totexe'],
                'taxinc': r['taxinc'],
                'income_tax': r['income_tax'],
                'pension_emp': r['pension_emp'],
                'pension_bnk': r['pension_bnk'],
                'pf': r['pf'],
                'ciab': r['ciab'],
                'cost_sharing': r['cost_sharing'],
                'labour_union': r['labour_union'],
                'penalty': r['penalty'],
                'cod': r['cod'],
                'other_ded': r['other_ded'],
                'total_ded': r['total_ded'],
                'net': r['net'],
            })

        self.env['bunna.payroll.summary.report.line'].create(lines_val)

    def action_view_list(self):
        """Displays all payslip horizontal information in an interactive Tree/List view."""
        self.ensure_one()
        self._populate_lines()
        list_view = self.env.ref('bunna_hr_payroll.view_bunna_payroll_summary_report_line_list', raise_if_not_found=False)
        return {
            'name': _('Payroll Summary (%s)') % self.period_id.name,
            'type': 'ir.actions.act_window',
            'res_model': 'bunna.payroll.summary.report.line',
            'view_mode': 'list',
            'views': [(list_view.id if list_view else False, 'list')],
            'domain': [('wizard_id', '=', self.id)],
            'context': dict(self.env.context, group_by='batch_name'),
            'target': 'current',
        }

    def action_export_excel(self):
        """Generates an Excel (.xlsx or .csv) file with full horizontal payslip data."""
        self.ensure_one()
        rows = self._get_report_data()
        if not rows:
            raise UserError(_("No payslips found for period '%s' matching the selected criteria.") % self.period_id.name)

        payment_date_str = str(self.payment_date or self.period_id.payment_date or self.date_to)

        headers = [
            "No.", "Employee ID", "Employee Name", "Payslip Batch", "Branch / Unit", "Department",
            "Period", "Start Date", "End Date", "Payment Date", "Status", "Bank Account",
            "Basic Salary", "Housing Alw", "Fuel Alw", "Rep Alw", "Transport Alw",
            "Hardship Alw", "CIA", "Mobile Alw", "Acting Alw", "Disturbance",
            "Overtime", "Other Alw", "Gross Salary", "Tax Exemption", "Taxable Income",
            "Income Tax (PAYE)", "Pension 7% (Emp)", "Pension 11% (Bank)", "Provident Fund (2%)",
            "CIA (Bank)", "Cost Sharing", "Labour Union", "Disciplinary Penalty",
            "Court / Other Ded", "Other Deductions", "Total Deductions", "Net Salary"
        ]

        if xlsxwriter:
            output = io.BytesIO()
            workbook = xlsxwriter.Workbook(output, {'in_memory': True})
            worksheet = workbook.add_worksheet('Payroll Summary')

            # Formatting
            title_fmt = workbook.add_format({
                'bold': True, 'font_size': 14, 'font_color': '#541718', 'align': 'left', 'valign': 'vcenter'
            })
            subtitle_fmt = workbook.add_format({
                'bold': True, 'font_size': 11, 'font_color': '#333333', 'align': 'left', 'valign': 'vcenter'
            })
            meta_fmt = workbook.add_format({
                'font_size': 9, 'font_color': '#666666', 'italic': True
            })
            header_fmt = workbook.add_format({
                'bold': True, 'font_size': 9, 'font_color': '#FFFFFF', 'bg_color': '#541718',
                'align': 'center', 'valign': 'vcenter', 'border': 1, 'border_color': '#3b1011', 'text_wrap': True
            })
            cell_fmt = workbook.add_format({
                'font_size': 9, 'align': 'left', 'valign': 'vcenter', 'border': 1, 'border_color': '#E0E0E0'
            })
            cell_center_fmt = workbook.add_format({
                'font_size': 9, 'align': 'center', 'valign': 'vcenter', 'border': 1, 'border_color': '#E0E0E0'
            })
            cell_num_fmt = workbook.add_format({
                'font_size': 9, 'align': 'right', 'valign': 'vcenter', 'num_format': '#,##0.00', 'border': 1, 'border_color': '#E0E0E0'
            })
            total_label_fmt = workbook.add_format({
                'bold': True, 'font_size': 9, 'font_color': '#541718', 'bg_color': '#F8F9FA',
                'align': 'right', 'valign': 'vcenter', 'border': 1, 'border_color': '#BDBDBD'
            })
            total_num_fmt = workbook.add_format({
                'bold': True, 'font_size': 9, 'font_color': '#541718', 'bg_color': '#F8F9FA',
                'align': 'right', 'valign': 'vcenter', 'num_format': '#,##0.00', 'border': 1, 'border_color': '#BDBDBD'
            })

            # Title Block
            worksheet.write(0, 0, "BUNNA BANK S.C.", title_fmt)
            worksheet.write(1, 0, f"PAYROLL SUMMARY REPORT - {self.period_id.name}", subtitle_fmt)
            run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            worksheet.write(2, 0, f"Period: {self.date_from} to {self.date_to} | Payment Date: {payment_date_str} | Generated: {run_ts}", meta_fmt)

            # Write Headers
            header_row = 4
            worksheet.set_row(header_row, 28)
            for col_idx, col_name in enumerate(headers):
                worksheet.write(header_row, col_idx, col_name, header_fmt)

            # Data rows
            row = header_row + 1
            num_start_col = 12
            for idx, r in enumerate(rows, start=1):
                worksheet.write(row, 0, idx, cell_center_fmt)
                worksheet.write(row, 1, r['emp_code'], cell_center_fmt)
                worksheet.write(row, 2, r['emp_name'], cell_fmt)
                worksheet.write(row, 3, r['batch_name'], cell_fmt)
                worksheet.write(row, 4, r.get('ou_name', ''), cell_fmt)
                worksheet.write(row, 5, r.get('dept_name', ''), cell_fmt)
                worksheet.write(row, 6, self.period_id.name, cell_center_fmt)
                worksheet.write(row, 7, str(r['date_from']), cell_center_fmt)
                worksheet.write(row, 8, str(r['date_to']), cell_center_fmt)
                worksheet.write(row, 9, payment_date_str, cell_center_fmt)
                worksheet.write(row, 10, r['state'].upper(), cell_center_fmt)
                worksheet.write(row, 11, r.get('bank_acc', ''), cell_fmt)

                # Numbers (col 12 to 38)
                num_vals = [
                    r['basic'], r['house_rent'], r['fuel'], r['rep_alw'], r['transport'],
                    r['hardship'], r['cia'], r['mobile'], r['acting'], r['disturb'],
                    r['overtime'], r['other_alw'], r['gross'], r['totexe'], r['taxinc'],
                    r['income_tax'], r['pension_emp'], r['pension_bnk'], r['pf'],
                    r['ciab'], r['cost_sharing'], r['labour_union'], r['penalty'],
                    r['cod'], r['other_ded'], r['total_ded'], r['net']
                ]
                for c_offset, val in enumerate(num_vals):
                    worksheet.write(row, num_start_col + c_offset, float(val or 0.0), cell_num_fmt)
                row += 1

            # Total Row
            worksheet.write(row, 0, "", total_label_fmt)
            worksheet.write(row, 1, "", total_label_fmt)
            worksheet.write(row, 2, f"Total ({len(rows)} Employees)", total_label_fmt)
            for c in range(3, num_start_col):
                worksheet.write(row, c, "", total_label_fmt)

            start_row = header_row + 2
            end_row = row
            for c_offset in range(len(num_vals)):
                col_letter = xlsxwriter.utility.xl_col_to_name(num_start_col + c_offset)
                formula = f"=SUM({col_letter}{start_row}:{col_letter}{end_row})"
                worksheet.write_formula(row, num_start_col + c_offset, formula, total_num_fmt)

            worksheet.freeze_panes(header_row + 1, 4)
            worksheet.autofilter(header_row, 0, row - 1, len(headers) - 1)
            workbook.close()
            output.seek(0)

            filename = f"Payroll_Summary_{self.period_id.name.replace(' ', '_')}_{self.date_to}.xlsx"
            attachment = self.env['ir.attachment'].sudo().create({
                'name': filename,
                'type': 'binary',
                'datas': base64.b64encode(output.getvalue()),
                'res_model': self._name,
                'res_id': self.id,
                'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            })
        else:
            # Fallback to UTF-8-SIG CSV (native Excel compatible)
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(headers)
            for idx, r in enumerate(rows, start=1):
                writer.writerow([
                    idx, r['emp_code'], r['emp_name'], r['batch_name'], r.get('ou_name', ''), r.get('dept_name', ''),
                    self.period_id.name, str(r['date_from']), str(r['date_to']),
                    payment_date_str, r['state'].upper(), r.get('bank_acc', ''),
                    f"{r['basic']:.2f}", f"{r['house_rent']:.2f}", f"{r['fuel']:.2f}",
                    f"{r['rep_alw']:.2f}", f"{r['transport']:.2f}", f"{r['hardship']:.2f}",
                    f"{r['cia']:.2f}", f"{r['mobile']:.2f}", f"{r['acting']:.2f}",
                    f"{r['disturb']:.2f}", f"{r['overtime']:.2f}", f"{r['other_alw']:.2f}",
                    f"{r['gross']:.2f}", f"{r['totexe']:.2f}", f"{r['taxinc']:.2f}",
                    f"{r['income_tax']:.2f}", f"{r['pension_emp']:.2f}", f"{r['pension_bnk']:.2f}",
                    f"{r['pf']:.2f}", f"{r['ciab']:.2f}", f"{r['cost_sharing']:.2f}",
                    f"{r['labour_union']:.2f}", f"{r['penalty']:.2f}", f"{r['cod']:.2f}",
                    f"{r['other_ded']:.2f}", f"{r['total_ded']:.2f}", f"{r['net']:.2f}",
                ])
            filename = f"Payroll_Summary_{self.period_id.name.replace(' ', '_')}_{self.date_to}.csv"
            attachment = self.env['ir.attachment'].sudo().create({
                'name': filename,
                'type': 'binary',
                'datas': base64.b64encode(output.getvalue().encode('utf-8-sig')),
                'res_model': self._name,
                'res_id': self.id,
                'mimetype': 'text/csv',
            })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def action_print_pdf(self):
        """Generates the printable landscape PDF report."""
        self.ensure_one()
        self._populate_lines()
        return self.env.ref('bunna_hr_payroll.action_report_payroll_summary_pdf').report_action(self)


class BunnaPayrollSummaryReportLine(models.TransientModel):
    _name = 'bunna.payroll.summary.report.line'
    _description = 'Payroll Summary Report Line'
    _order = 'batch_name, employee_name'

    wizard_id = fields.Many2one('bunna.payroll.summary.report.wizard', string='Wizard', ondelete='cascade', index=True)
    slip_id = fields.Many2one('hr.payslip', string='Payslip', readonly=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', readonly=True)
    employee_code = fields.Char(string='Employee ID', readonly=True)
    employee_name = fields.Char(string='Employee Name', readonly=True)
    batch_name = fields.Char(string='Payslip Batch', readonly=True)
    operating_unit_name = fields.Char(string='Branch / Operating Unit', readonly=True)
    department_name = fields.Char(string='Department', readonly=True)
    period_id = fields.Many2one('hr.payroll.period', string='Payroll Period', readonly=True)
    period_name = fields.Char(string='Period', readonly=True)
    date_from = fields.Date(string='Start Date', readonly=True)
    date_to = fields.Date(string='End Date', readonly=True)
    payment_date = fields.Date(string='Date of Payment', readonly=True)
    state = fields.Char(string='Status', readonly=True)
    bank_acc = fields.Char(string='Bank Account No', readonly=True)

    # Earnings & Allowances
    basic = fields.Float(string='Basic Salary', digits=(16, 2), readonly=True)
    house_rent = fields.Float(string='Housing Alw', digits=(16, 2), readonly=True)
    fuel = fields.Float(string='Fuel Alw', digits=(16, 2), readonly=True)
    rep_alw = fields.Float(string='Rep Alw', digits=(16, 2), readonly=True)
    transport = fields.Float(string='Transport Alw', digits=(16, 2), readonly=True)
    hardship = fields.Float(string='Hardship Alw', digits=(16, 2), readonly=True)
    cia = fields.Float(string='CIA', digits=(16, 2), readonly=True)
    mobile = fields.Float(string='Mobile Alw', digits=(16, 2), readonly=True)
    acting = fields.Float(string='Acting Alw', digits=(16, 2), readonly=True)
    disturb = fields.Float(string='Disturbance', digits=(16, 2), readonly=True)
    overtime = fields.Float(string='Overtime', digits=(16, 2), readonly=True)
    other_alw = fields.Float(string='Other Alw', digits=(16, 2), readonly=True)
    gross = fields.Float(string='Gross Salary', digits=(16, 2), readonly=True)

    # Tax & Exemption
    totexe = fields.Float(string='Tax Exemption', digits=(16, 2), readonly=True)
    taxinc = fields.Float(string='Taxable Income', digits=(16, 2), readonly=True)

    # Deductions
    income_tax = fields.Float(string='Income Tax (PAYE)', digits=(16, 2), readonly=True)
    pension_emp = fields.Float(string='Pension 7%', digits=(16, 2), readonly=True)
    ciab = fields.Float(string='CIA (Bank)', digits=(16, 2), readonly=True)
    cost_sharing = fields.Float(string='Cost Sharing', digits=(16, 2), readonly=True)
    labour_union = fields.Float(string='Labour Union', digits=(16, 2), readonly=True)
    penalty = fields.Float(string='Disciplinary Penalty', digits=(16, 2), readonly=True)
    cod = fields.Float(string='Court / Other Ded', digits=(16, 2), readonly=True)
    other_ded = fields.Float(string='Other Deductions', digits=(16, 2), readonly=True)
    total_ded = fields.Float(string='Total Deductions', digits=(16, 2), readonly=True)

    # Employer Contributions
    pension_bnk = fields.Float(string='Pension 11% (Bank)', digits=(16, 2), readonly=True)
    pf = fields.Float(string='Provident Fund 2%', digits=(16, 2), readonly=True)

    # Net
    net = fields.Float(string='Net Salary', digits=(16, 2), readonly=True)
