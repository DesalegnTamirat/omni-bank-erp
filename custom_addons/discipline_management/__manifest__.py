# -*- coding: utf-8 -*-
{
    'name': 'Discipline Management System',
    'version': '19.0.2.0.0',
    'category': 'Human Resources/Discipline',
    'summary': 'Manage employee misconduct, disciplinary cases, investigations, committee decisions, suspensions, appeals, and payroll deductions.',
    'description': """
Discipline Management System (Bunna Bank ERP HR Upgrade)
=========================================================
Key Features:
- Standard Offense Classification (Level 1 Dismissal to Level 5 Minor Warning).
- Segregation of duties (Initiator != Reviewer != Approver).
- Workflow routing & Dismissal approval restriction to higher authorities (CEO vs CPCO).
- SLA Escalation and tracking.
- Investigation finding recording & evidence attachment management.
- Disciplinary Committee scheduling, participant notification, voting, and quorum validation.
- Automated Decision Enforcement (Warning letters PDF, payroll deductions, demotion, separation workflow).
- Payroll Integration (Salary penalty deduction tracking & get_payroll_transmission_payload integration contract).
- Analytics Data API (get_discipline_analytics_payload integration contract).
- Suspension Management (Max 30 working days, with/without pay, automated tracking, monthly penalty generation).
- Appeal & Review Process (10 calendar days submission window enforcement, appeal committee routing).
- Disciplinary History tracking per employee and Recruitment/Promotion eligibility checks.
- Formal Case Revocation with mandatory justification and immutable original record audit log.
    """,
    'author': 'Desalegn & Abeza',
    'website': 'https://www.bunnabanksc.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'hr',
        'hr_employee_custom',
        'hr_attendance',
        'mail',
    ],
    'data': [
        'security/discipline_security.xml',
        'security/ir.model.access.csv',
        'data/discipline_sequence.xml',
        'data/discipline_severity_level_data.xml',
        'data/bunna_regulation_seed_data.xml',
        'data/discipline_cron.xml',
        'views/discipline_severity_level_views.xml',
        'views/discipline_offense_views.xml',
        'views/discipline_case_views.xml',
        'views/discipline_investigation_views.xml',
        'views/discipline_committee_views.xml',
        'views/discipline_suspension_views.xml',
        'views/discipline_appeal_views.xml',
        'views/discipline_payroll_views.xml',
        'views/hr_employee_views.xml',
        'views/discipline_dashboard_views.xml',
        'wizards/discipline_revocation_wizard_views.xml',
        'report/discipline_report_templates.xml',
        'report/discipline_reports.xml',
        'views/discipline_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'discipline_management/static/src/css/discipline_dashboard.css',
            'discipline_management/static/src/js/discipline_dashboard.js',
            'discipline_management/static/src/xml/discipline_dashboard.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
