# -*- coding: utf-8 -*-
# Part of Bunna Bank ERP HR Upgrade. See LICENSE file for full copyright and licensing details.

{
    'name': 'Payroll Processing and Compensation Management System',
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Payroll',
    'summary': 'Enterprise Effective-Date-Driven Payroll Engine with Multi-Segment Proration, Statutory Compliance, and Full ERP Integration.',
    'description': """
Enterprise Payroll Processing and Compensation Management System
================================================================

Key Architectural Capabilities:
-------------------------------
* **Effective-Date-Driven Processing**: All payroll calculations are strictly anchored to approved HR action effective dates.
* **Automatic Multi-Segment Proration**: Dynamic time-slicing for mid-month transfers, promotions, demotions, increments, and joiners.
* **Single Source of Truth**: Seamless automated integration with Attendance, Discipline, Resignation/Clearance, and Contracts.
* **Regulatory & Statutory Compliance**: Accurate Ethiopian progressive tax brackets, Pension scheme (7% EE / 11% ER), and non-taxable allowances.
* **Hardship Allowance Engine**: Location code based tier mapping and segmented proration across branch transfers.
* **Acting Allowance Lifecycle**: Managerial acting assignment duration tracker enforcing Month 1 (0%), Month 2-6 (100%), Month 7+ (Stop payment).
* **Retroactive Adjustments**: Automated virtual recalculation across historical locked payslips with itemized arrears and recoveries.
* **Cut-Off Enforcement & Governance**: Hard cutoff locking with audited override workflows and a 3-tier approval hierarchy (Initiation -> Verification -> Final Approval).
* **Pre-Flight Exception & Simulation**: Real-time dry-run financial simulations and comprehensive pre-finalization exception scanning.
* **Downstream Integration**: Automated General Ledger (GL) journal entries by Operating Unit/Branch and CBS/ACH direct credit payment batch generation.
""",
    'author': 'Bunna Bank IT / ERP Development Team',
    'website': 'https://www.bunnabanksc.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'hr',
        'hr_employee_custom',
        'custom_hr_attendance',
        'discipline_management',
        'hr_resignation',
        'mail',
    ],
    'data': [
        'security/payroll_security.xml',
        'security/ir.model.access.csv',
        'data/payroll_sequence.xml',
        'data/ethiopian_tax_pension_data.xml',
        'data/hardship_allowance_tier_data.xml',
        'data/payroll_cron.xml',
        'wizards/hr_payslip_by_employees_views.xml',
        'wizards/payroll_simulation_wizard_views.xml',
        'wizards/payroll_cutoff_override_wizard_views.xml',
        'wizards/payroll_retroactive_wizard_views.xml',
        'wizards/payroll_cbs_export_wizard_views.xml',
        'views/hr_payroll_period_views.xml',
        'views/hr_salary_rule_views.xml',
        'views/hr_payroll_structure_views.xml',
        'views/hr_payslip_views.xml',
        'views/hr_payslip_segment_views.xml',
        'views/hr_payslip_run_views.xml',
        'views/hr_hardship_allowance_views.xml',
        'views/hr_acting_allowance_views.xml',
        'views/hr_payroll_retroactive_views.xml',
        'views/hr_payroll_increment_views.xml',
        'views/hr_payroll_bonus_views.xml',
        'views/hr_payroll_cutoff_override_views.xml',
        'views/hr_payroll_exception_views.xml',
        'views/hr_payroll_audit_log_views.xml',
        'views/payroll_cbs_export_views.xml',
        'views/hr_employee_payroll_views.xml',
        'report/payslip_report_template.xml',
        'report/payroll_summary_report.xml',
        'report/payroll_variance_report.xml',
        'report/statutory_tax_pension_report.xml',
        'report/payroll_increment_report.xml',
        'report/payroll_bonus_report.xml',
        'report/payroll_reports.xml',
        'views/payroll_dashboard_views.xml',
        'views/payroll_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'payroll/static/src/css/payroll_dashboard.css',
            'payroll/static/src/js/payroll_dashboard.js',
            'payroll/static/src/xml/payroll_dashboard.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
