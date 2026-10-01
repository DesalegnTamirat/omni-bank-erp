# -*- coding: utf-8 -*-
from odoo import fields, models, tools


class PbmsConsolidationLine(models.Model):
    """Bank-wide consolidation of every monthly-grid planning format
    (Deposit, General Expense, ... - and any new one added later, see
    UNION list below).

    Deliberately implemented as a PostgreSQL VIEW (_auto=False) rather
    than a synced/duplicated table:
      * always consistent with the source tables - no cron / write
        override needed to keep a copy in sync, which also removes an
        entire class of "stale dashboard" bugs;
      * consolidation is push-down to SQL (UNION ALL + the underlying
        indexed org_unit_id/cycle_id/state columns), so a bank-level
        aggregate query is one indexed scan per source table, not N
        ORM read_group calls stitched together in Python;
      * adding a new monthly-grid planning format later is a one-line
        addition to the UNION in init().
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
    quarter1_total = fields.Monetary(readonly=True)
    quarter2_total = fields.Monetary(readonly=True)
    quarter3_total = fields.Monetary(readonly=True)
    quarter4_total = fields.Monetary(readonly=True)
    annual_total = fields.Monetary(readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    d.id AS id,
                    d.org_unit_id AS org_unit_id,
                    d.district_id AS district_id,
                    d.org_unit_type AS org_unit_type,
                    d.cycle_id AS cycle_id,
                    d.company_id AS company_id,
                    'deposit' AS source_model,
                    dt.name AS account_name,
                    d.state AS state,
                    d.currency_id AS currency_id,
                    d.quarter1_total AS quarter1_total,
                    d.quarter2_total AS quarter2_total,
                    d.quarter3_total AS quarter3_total,
                    d.quarter4_total AS quarter4_total,
                    d.annual_total AS annual_total
                FROM pbms_deposit_plan d
                JOIN pbms_deposit_type dt ON dt.id = d.deposit_type_id

                UNION ALL

                SELECT
                    (c.id + 2000000000) AS id,
                    c.org_unit_id AS org_unit_id,
                    c.district_id AS district_id,
                    c.org_unit_type AS org_unit_type,
                    c.cycle_id AS cycle_id,
                    c.company_id AS company_id,
                    'customer_base' AS source_model,
                    dt2.name || ' - ' || c.base_type AS account_name,
                    c.state AS state,
                    c.currency_id AS currency_id,
                    c.quarter1_total AS quarter1_total,
                    c.quarter2_total AS quarter2_total,
                    c.quarter3_total AS quarter3_total,
                    c.quarter4_total AS quarter4_total,
                    c.annual_total AS annual_total
                FROM pbms_customer_base_plan c
                JOIN pbms_deposit_type dt2 ON dt2.id = c.deposit_type_id

                UNION ALL

                SELECT
                    (fx.id + 3000000000) AS id,
                    fx.org_unit_id AS org_unit_id,
                    fx.district_id AS district_id,
                    fx.org_unit_type AS org_unit_type,
                    fx.cycle_id AS cycle_id,
                    fx.company_id AS company_id,
                    'fx' AS source_model,
                    fx.fx_source_type AS account_name,
                    fx.state AS state,
                    fx.currency_id AS currency_id,
                    fx.quarter1_total AS quarter1_total,
                    fx.quarter2_total AS quarter2_total,
                    fx.quarter3_total AS quarter3_total,
                    fx.quarter4_total AS quarter4_total,
                    fx.annual_total AS annual_total
                FROM pbms_fx_plan fx

                UNION ALL

                SELECT
                    (db.id + 4000000000) AS id,
                    db.org_unit_id AS org_unit_id,
                    db.district_id AS district_id,
                    db.org_unit_type AS org_unit_type,
                    db.cycle_id AS cycle_id,
                    db.company_id AS company_id,
                    'digital_banking' AS source_model,
                    ch.name AS account_name,
                    db.state AS state,
                    db.currency_id AS currency_id,
                    db.quarter1_total AS quarter1_total,
                    db.quarter2_total AS quarter2_total,
                    db.quarter3_total AS quarter3_total,
                    db.quarter4_total AS quarter4_total,
                    db.annual_total AS annual_total
                FROM pbms_digital_banking_plan db
                JOIN pbms_digital_channel ch ON ch.id = db.channel_id

                UNION ALL

                SELECT
                    (g.id + 1000000000) AS id,
                    g.org_unit_id AS org_unit_id,
                    g.district_id AS district_id,
                    g.org_unit_type AS org_unit_type,
                    g.cycle_id AS cycle_id,
                    g.company_id AS company_id,
                    'general_expense' AS source_model,
                    ea.name AS account_name,
                    g.state AS state,
                    g.currency_id AS currency_id,
                    g.quarter1_total AS quarter1_total,
                    g.quarter2_total AS quarter2_total,
                    g.quarter3_total AS quarter3_total,
                    g.quarter4_total AS quarter4_total,
                    g.annual_total AS annual_total
                FROM pbms_general_expense_plan g
                JOIN pbms_expense_account ea ON ea.id = g.expense_account_id
            )
        """)
