# -*- coding: utf-8 -*-
{
    "name": "Bunna Bank - Plan and Budget Management System (PBMS)",
    "version": "19.0.1.0.0",
    "category": "Accounting/Budgeting",
    "summary": "Automates Bunna Bank's Annual Business Plan & Budget preparation, "
                "review, consolidation and approval workflow.",
    "description": """
Plan and Budget Management System (PBMS)
=========================================
Implements the BRD "Plan and Budget Management System (PBMS)" for the
Strategic Planning and Performance Management Directorate (SPPMD) of
Bunna Bank.

Core capabilities:
-------------------
* Organizational hierarchy: Branch -> District Office -> Head Office,
  reused directly from the Bank's existing HR module (hr_employee_custom)
  via its `operating.unit` model, rather than duplicating a separate org
  structure. PBMS does not create or configure org units itself.
* Annual Planning Cycle (period July-June) that all planning lines belong
  to, with configurable submission deadlines used by the reminder cron.
* A single reusable workflow mixin (pbms.plan.line.mixin) that every
  planning format (Deposit, Customer Base, FX, Digital Banking, General
  Expense, Manpower, Fixed Asset) inherits, giving them all the same
  4-stage approval workflow (Draft -> Submitted -> District Review ->
  Head Office Review -> Approved / Returned) for free, plus the same
  12-month target grid, automatic net/cumulative/quarterly/annual
  calculations, validation rules and audit trail.
* Automatic consolidation model that rolls figures up from Branch to
  District to Bank level using read_group (no per-record Python loops),
  kept in a materialized, indexed table for fast dashboard/report reads.
* OWL 2 dashboard (client action) showing submission/approval progress
  and KPI/budget summaries side by side, backed by a couple of
  read_group RPCs rather than loading full recordsets to the browser.
* Excel import/export wizard matching the Bank's existing BB-APF formats
  (requires the optional Python package 'openpyxl' on the server).
* QWeb PDF report for the consolidated plan & budget document.
* Deadline / pending-review notifications via a scheduled action using
  mail.activity + Odoo's notification/inbox channel.
""",
    "author": "Bunna Bank / SPPMD",
    "website": "",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        "web",
        "hr_employee_custom",
    ],
    "data": [
        "security/pbms_security.xml",
        "security/ir.model.access.csv",
        "data/pbms_master_data.xml",
        "data/pbms_planning_config_data.xml",
        "data/pbms_cron.xml",
        "data/pbms_mail_templates.xml",
        "wizard/pbms_review_action_wizard_views.xml",
        "wizard/pbms_excel_import_wizard_views.xml",
        "wizard/pbms_target_cascade_wizard_views.xml",
        "wizard/pbms_exceptional_action_wizard_views.xml",
        "views/planing_categories_view.xml",
        "views/pbms_planning_config_views.xml",
        "views/pbms_planning_cycle_views.xml",
        "views/pbms_consolidation_views.xml",
        "views/pbms_master_data_views.xml",
        "views/pbms_dashboard_views.xml",
        "views/pbms_exceptional_workforce_views.xml",
        "views/pbms_menus.xml",
        "report/pbms_consolidated_report.xml",
        "report/pbms_consolidated_report_templates.xml",
    ],
    "assets": {
        "web.assets_backend": [
            # Chart.js must load before pbms_dashboard.js, which calls the
            # global `Chart` constructor.
            "https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js",
            "bunna_pbms/static/src/js/pbms_dashboard.js",
            "bunna_pbms/static/src/js/pbms_list_renderer_patch.js",
            "bunna_pbms/static/src/xml/**/*.xml",
            "bunna_pbms/static/src/scss/**/*.scss",
        ],
        "web.assets_backend_lazy": [
            # Graph views and GraphRenderer are lazy-loaded in Odoo 19 (web.assets_backend_lazy).
            # Putting graph color patches here prevents missing dependency errors during initial boot in developer mode.
            "bunna_pbms/static/src/js/pbms_graph_colors.js",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
