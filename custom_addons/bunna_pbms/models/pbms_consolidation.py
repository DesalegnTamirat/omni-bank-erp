# -*- coding: utf-8 -*-
from odoo import fields, models, tools, _
from odoo.exceptions import UserError


class PbmsConsolidationLine(models.Model):
    """Bank-wide consolidation of every planning category.

    Implemented as a PostgreSQL VIEW (_auto=False) over the single unified
    ``pbms.planning.category`` table, so consolidation is a plain indexed
    scan / GROUP BY in SQL rather than a UNION of several format tables.
    Always consistent with the source table - no cron / write override needed.
    """
    _name = "pbms.consolidation.line"
    _description = "Plan & Budget Consolidation (read-only view)"
    _auto = False
    _order = "org_unit_id, source_model"

    org_unit_id = fields.Many2one("operating.unit", readonly=True)
    district_id = fields.Many2one("operating.unit", readonly=True)
    org_unit_type = fields.Selection(
        [
            ("branch", "Branch"),
            ("sub_branch", "Sub-Branch"),
            ("head_office", "Head Office"),
            ("regional_office", "Regional Office"),
            ("district_office", "District Office"),
            ("service_center", "Service Center"),
            ("other", "Other"),
        ],
        readonly=True,
    )
    cycle_id = fields.Many2one("pbms.planning.cycle", readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    source_model = fields.Selection(
        [
            ("deposit", "Deposit Mobilization"),
            ("customer_base", "Customer Base"),
            ("fx", "FX Mobilization"),
            ("digital_banking", "Digital Banking"),
            ("general_expense", "General Expense"),
            ("manpower", "Manpower Requirement"),
            ("fixed_asset", "Fixed Asset Requirement"),
        ],
        readonly=True,
    )
    account_name = fields.Char(readonly=True)
    state = fields.Selection(
        [
            ("draft", "Draft"), ("submitted", "Submitted"),
            ("returned", "Returned for Revision"),
            ("district_approved", "District Approved"),
            ("district_endorsed", "District Endorsed"),
            ("ho_reviewed", "Head Office Reviewed"), ("approved", "Approved"),
        ],
        readonly=True,
    )
    currency_id = fields.Many2one("res.currency", readonly=True)
    create_uid = fields.Many2one("res.users", readonly=True)

    # Monthly fields for consolidation (Float ensures no currency prefix 'Br ' is shown)
    m01 = fields.Float(readonly=True, string="Jul")
    m02 = fields.Float(readonly=True, string="Aug")
    m03 = fields.Float(readonly=True, string="Sep")
    m04 = fields.Float(readonly=True, string="Oct")
    m05 = fields.Float(readonly=True, string="Nov")
    m06 = fields.Float(readonly=True, string="Dec")
    m07 = fields.Float(readonly=True, string="Jan")
    m08 = fields.Float(readonly=True, string="Feb")
    m09 = fields.Float(readonly=True, string="Mar")
    m10 = fields.Float(readonly=True, string="Apr")
    m11 = fields.Float(readonly=True, string="May")
    m12 = fields.Float(readonly=True, string="Jun")

    # Quarterly totals
    quarter1_total = fields.Float(readonly=True)
    quarter2_total = fields.Float(readonly=True)
    quarter3_total = fields.Float(readonly=True)
    quarter4_total = fields.Float(readonly=True)
    annual_total = fields.Float(readonly=True)

    # Line count for itemized categories
    line_count = fields.Integer(readonly=True, string="Number of Lines")

    # Total estimated amount for fixed asset
    total_estimated_amount = fields.Float(readonly=True, string="Total Estimated Amount")

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    p.id AS id,
                    p.create_uid AS create_uid,
                    p.org_unit_id AS org_unit_id,
                    p.district_id AS district_id,
                    p.org_unit_type AS org_unit_type,
                    p.cycle_id AS cycle_id,
                    p.company_id AS company_id,
                    p.category AS source_model,
                    COALESCE(
                        CASE
                            WHEN p.category = 'deposit' THEN COALESCE(dt.name || CASE WHEN p.plan_category IS NOT NULL THEN ' - ' || p.plan_category ELSE '' END, dt.name, 'Deposit Mobilization')
                            WHEN p.category = 'customer_base' THEN COALESCE(dt.name || CASE WHEN p.base_type IS NOT NULL THEN ' - ' || p.base_type ELSE '' END, dt.name, 'Customer Base')
                            WHEN p.category = 'fx' THEN COALESCE(fx.name, 'FX Mobilization')
                            WHEN p.category = 'digital_banking' THEN COALESCE(ch.name, 'Digital Banking')
                            WHEN p.category = 'general_expense' THEN COALESCE(ea.name, 'General Expense')
                            WHEN p.category = 'manpower' THEN 'Manpower'
                            WHEN p.category = 'fixed_asset' THEN 'Fixed Asset'
                        END, '') AS account_name,
                    p.state AS state,
                    p.currency_id AS currency_id,
                    -- Monthly fields (directly from the planning category)
                    p.m01 AS m01,
                    p.m02 AS m02,
                    p.m03 AS m03,
                    p.m04 AS m04,
                    p.m05 AS m05,
                    p.m06 AS m06,
                    p.m07 AS m07,
                    p.m08 AS m08,
                    p.m09 AS m09,
                    p.m10 AS m10,
                    p.m11 AS m11,
                    p.m12 AS m12,
                    -- Quarterly totals (computed in the category model)
                    p.quarter1_total AS quarter1_total,
                    p.quarter2_total AS quarter2_total,
                    p.quarter3_total AS quarter3_total,
                    p.quarter4_total AS quarter4_total,
                    p.annual_total AS annual_total,
                    -- Line count for itemized categories
                    p.line_count AS line_count,
                    -- Total estimated amount for fixed asset
                    p.total_estimated_amount AS total_estimated_amount
                FROM pbms_planning_category p
                LEFT JOIN pbms_deposit_type dt ON dt.id = p.deposit_type_id
                LEFT JOIN pbms_fx_source_type fx ON fx.id = p.fx_source_type
                LEFT JOIN pbms_digital_channel ch ON ch.id = p.channel_id
                LEFT JOIN pbms_expense_account ea ON ea.id = p.expense_account_id
                WHERE p.active = True
                  AND p.org_unit_type IN ('district_office', 'head_office', 'regional_office')
            )
        """)

    def action_export_excel(self):
        """Export bank-wide consolidation lines with official Bunna Bank branding to Excel (.xlsx).
        Headers are formatted with the official Bunna brand color (#541718) and white text.
        """
        if not self:
            raise UserError(_("No consolidation records selected for export."))

        import base64
        import io
        try:
            import xlsxwriter
        except ImportError:
            raise UserError(_("The 'xlsxwriter' Python library is required. Please install it on the server."))

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})

        # Bunna Bank branding formats
        BUNNA_BURGUNDY = '#541718'
        BUNNA_DARK_BORDER = '#3D1011'

        fmt_bank_title = wb.add_format({
            'bold': True, 'font_size': 14, 'font_color': BUNNA_BURGUNDY, 'font_name': 'Segoe UI',
            'align': 'center', 'valign': 'vcenter'
        })
        fmt_doc_title = wb.add_format({
            'bold': True, 'font_size': 12, 'font_color': BUNNA_BURGUNDY, 'font_name': 'Segoe UI',
            'align': 'center', 'valign': 'vcenter'
        })
        fmt_subtitle = wb.add_format({
            'bold': True, 'font_size': 10, 'font_color': '#425727', 'font_name': 'Segoe UI',
            'align': 'center', 'valign': 'vcenter'
        })
        fmt_meta = wb.add_format({
            'font_size': 9, 'font_color': '#666666', 'font_name': 'Segoe UI',
            'align': 'center', 'valign': 'vcenter'
        })
        fmt_th = wb.add_format({
            'bold': True, 'bg_color': BUNNA_BURGUNDY, 'font_color': '#FFFFFF',
            'font_size': 10, 'font_name': 'Segoe UI', 'align': 'center', 'valign': 'vcenter',
            'text_wrap': True, 'border': 1, 'border_color': BUNNA_DARK_BORDER
        })
        fmt_cell_text = wb.add_format({
            'font_size': 9, 'font_name': 'Segoe UI', 'valign': 'vcenter',
            'border': 1, 'border_color': '#D9D9D9'
        })
        fmt_cell_center = wb.add_format({
            'font_size': 9, 'font_name': 'Segoe UI', 'valign': 'vcenter', 'align': 'center',
            'border': 1, 'border_color': '#D9D9D9'
        })
        fmt_cell_num = wb.add_format({
            'font_size': 9, 'font_name': 'Segoe UI', 'valign': 'vcenter', 'align': 'right',
            'num_format': '#,##0.00', 'border': 1, 'border_color': '#D9D9D9'
        })
        fmt_cell_int = wb.add_format({
            'font_size': 9, 'font_name': 'Segoe UI', 'valign': 'vcenter', 'align': 'right',
            'num_format': '#,##0', 'border': 1, 'border_color': '#D9D9D9'
        })
        fmt_tot_label = wb.add_format({
            'bold': True, 'bg_color': BUNNA_BURGUNDY, 'font_color': '#FFFFFF',
            'font_size': 10, 'font_name': 'Segoe UI', 'valign': 'vcenter', 'align': 'left',
            'border': 1, 'border_color': BUNNA_DARK_BORDER
        })
        fmt_tot_num = wb.add_format({
            'bold': True, 'bg_color': BUNNA_BURGUNDY, 'font_color': '#FFFFFF',
            'font_size': 10, 'font_name': 'Segoe UI', 'valign': 'vcenter', 'align': 'right',
            'num_format': '#,##0.00', 'border': 1, 'border_color': BUNNA_DARK_BORDER
        })
        fmt_tot_int = wb.add_format({
            'bold': True, 'bg_color': BUNNA_BURGUNDY, 'font_color': '#FFFFFF',
            'font_size': 10, 'font_name': 'Segoe UI', 'valign': 'vcenter', 'align': 'right',
            'num_format': '#,##0', 'border': 1, 'border_color': BUNNA_DARK_BORDER
        })

        # Cycle & date info
        primary_cycle = self[0].cycle_id if self and self[0].cycle_id else False
        cycle_name = primary_cycle.name if primary_cycle and primary_cycle.name else "FY 2026/27"

        # Sheet: Bank-Wide Consolidation Overview
        ws = wb.add_worksheet("Consolidation Overview")
        ws.freeze_panes(6, 5)

        total_cols = 25
        ws.merge_range(0, 0, 0, total_cols, "Bunna Bank S.C.", fmt_bank_title)
        ws.merge_range(1, 0, 1, total_cols, "Plan & Budget Management System (PBMS)", fmt_doc_title)
        ws.merge_range(2, 0, 2, total_cols, f"Bank-Wide Plan & Budget Consolidation - {cycle_name}", fmt_subtitle)
        ws.merge_range(3, 0, 3, total_cols, f"Generated on {fields.Date.today()}", fmt_meta)

        headers = [
            "Org Unit", "District", "Unit Type", "Planning Category",
            "Account Description", "Planning Cycle", "Status",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
            "Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Q1 Total", "Q2 Total", "Q3 Total", "Q4 Total",
            "Annual Total", "Lines", "Est. Amount"
        ]
        for ci, h in enumerate(headers):
            ws.write(5, ci, h, fmt_th)

        row_cur = 6
        for rec in self:
            unit_name = rec.org_unit_id.display_name if rec.org_unit_id else ""
            dist_name = rec.district_id.name if rec.district_id else ""
            unit_type = dict(rec._fields["org_unit_type"].selection).get(rec.org_unit_type, rec.org_unit_type or "")
            cat_label = dict(rec._fields["source_model"].selection).get(rec.source_model, rec.source_model or "")
            acc_name = rec.account_name or ""
            cyc_name = rec.cycle_id.name if rec.cycle_id else ""
            st_label = dict(rec._fields["state"].selection).get(rec.state, rec.state or "")

            ws.write(row_cur, 0, unit_name, fmt_cell_text)
            ws.write(row_cur, 1, dist_name, fmt_cell_text)
            ws.write(row_cur, 2, unit_type, fmt_cell_center)
            ws.write(row_cur, 3, cat_label, fmt_cell_text)
            ws.write(row_cur, 4, acc_name, fmt_cell_text)
            ws.write(row_cur, 5, cyc_name, fmt_cell_center)
            ws.write(row_cur, 6, st_label, fmt_cell_center)

            # Monthly fields (no currency prefix)
            m_vals = [
                rec.m01 or 0.0, rec.m02 or 0.0, rec.m03 or 0.0, rec.m04 or 0.0,
                rec.m05 or 0.0, rec.m06 or 0.0, rec.m07 or 0.0, rec.m08 or 0.0,
                rec.m09 or 0.0, rec.m10 or 0.0, rec.m11 or 0.0, rec.m12 or 0.0
            ]
            for mi, mv in enumerate(m_vals):
                ws.write(row_cur, 7 + mi, mv, fmt_cell_num)

            # Quarterly totals
            ws.write(row_cur, 19, rec.quarter1_total or 0.0, fmt_cell_num)
            ws.write(row_cur, 20, rec.quarter2_total or 0.0, fmt_cell_num)
            ws.write(row_cur, 21, rec.quarter3_total or 0.0, fmt_cell_num)
            ws.write(row_cur, 22, rec.quarter4_total or 0.0, fmt_cell_num)
            ws.write(row_cur, 23, rec.annual_total or 0.0, fmt_cell_num)
            ws.write(row_cur, 24, rec.line_count or 0, fmt_cell_int)
            ws.write(row_cur, 25, rec.total_estimated_amount or 0.0, fmt_cell_num)

            row_cur += 1

        # Summary total row
        ws.write(row_cur, 0, "TOTAL", fmt_tot_label)
        for ci in range(1, 7):
            ws.write(row_cur, ci, "", fmt_tot_label)

        if row_cur > 6:
            import xlsxwriter.utility
            for ci in range(7, 24):
                c_letter = xlsxwriter.utility.xl_col_to_name(ci)
                ws.write_formula(row_cur, ci, f"=SUM({c_letter}7:{c_letter}{row_cur})", fmt_tot_num)
            c_lines = xlsxwriter.utility.xl_col_to_name(24)
            ws.write_formula(row_cur, 24, f"=SUM({c_lines}7:{c_lines}{row_cur})", fmt_tot_int)
            c_est = xlsxwriter.utility.xl_col_to_name(25)
            ws.write_formula(row_cur, 25, f"=SUM({c_est}7:{c_est}{row_cur})", fmt_tot_num)
        else:
            for ci in range(7, 24):
                ws.write(row_cur, ci, 0.0, fmt_tot_num)
            ws.write(row_cur, 24, 0, fmt_tot_int)
            ws.write(row_cur, 25, 0.0, fmt_tot_num)

        # Column widths
        ws.set_column(0, 0, 26)
        ws.set_column(1, 1, 18)
        ws.set_column(2, 2, 16)
        ws.set_column(3, 3, 22)
        ws.set_column(4, 4, 28)
        ws.set_column(5, 5, 14)
        ws.set_column(6, 6, 14)
        for ci in range(7, 19):
            ws.set_column(ci, ci, 13)
        for ci in range(19, 24):
            ws.set_column(ci, ci, 15)
        ws.set_column(24, 24, 10)
        ws.set_column(25, 25, 16)

        wb.close()
        output.seek(0)
        file_data = output.getvalue()

        file_name = f"Bunna_Bank_Consolidation_Export_{cycle_name.replace('/', '-')}.xlsx"

        attachment = self.env["ir.attachment"].create({
            "name": file_name,
            "type": "binary",
            "datas": base64.b64encode(file_data),
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        })
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }