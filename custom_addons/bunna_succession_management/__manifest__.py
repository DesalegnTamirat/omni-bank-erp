# -*- coding: utf-8 -*-
{
    'name': "Succession Management",
    'summary': "Dedicated Succession Management Module: Critical Positions, Talent Pools, Successor Assessment and Governance.",
    'version': '19.0.1.0.0',
    'category': 'Human Resources',
    'author': 'Bunna Bank',
    'website': 'https://www.bunnabanksc.com',
    'license': 'LGPL-3',
    'description': """
Succession Management System (Bunna Bank ERP HR Upgrade)
=========================================================
A dedicated, highly confidential module for managing organizational succession
continuity for critical and leadership positions. Strictly accessible to
PPDD (People Performance & Development Directorate) and SPMC.

EXCLUDED from this module (per business decision):
- Career Path (handled in Employee Master via bunna_career_path)
- Internal Mobility
- 9-Box Talent Integration

Key Features:
- Critical Position Register with risk classification and SPMC approval workflow.
- Talent Pool management: identify and group potential successors per critical position.
- Successor Candidate nomination with system-assisted readiness scoring.
- Competency Gap analysis for successor candidates (from competency_management module).
- PMS score integration for candidate eligibility.
- Successor Development Plans: targeted interventions to get candidates to 'Ready Now'.
- Governance: PPDD and SPMC approval workflows with complete, immutable audit trail.
- Reporting: Bench Strength, Succession Risk Matrix, and Pipeline Coverage reports.
- RBAC: Employees have ZERO visibility into this module.
    """,
    'depends': [
        'base',
        'hr',
        'mail',
        'hr_employee_custom',      # Career Path models live here
        'competency_management',
    ],
    'data': [
        'security/succession_security.xml',
        'security/ir.model.access.csv',
        'data/succession_cron.xml',
        'views/succession_dashboard_action.xml',
        'views/succession_critical_position_views.xml',
        'views/succession_talent_pool_views.xml',
        'views/succession_candidate_views.xml',
        'views/succession_development_plan_views.xml',
        'views/succession_dashboard_views.xml',
        'views/succession_auto_match_wizard_views.xml',
        'views/succession_workforce_plan_views.xml',
        'views/succession_ninebox_cell_views.xml',
        'views/res_config_settings_views.xml',
        'views/succession_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'bunna_succession_management/static/src/css/succession_dashboard.css',
            'bunna_succession_management/static/src/js/succession_dashboard.js',
            'bunna_succession_management/static/src/xml/succession_dashboard.xml',
            'bunna_succession_management/static/src/css/nine_box_grid.css',
            'bunna_succession_management/static/src/js/nine_box_grid.js',
            'bunna_succession_management/static/src/xml/nine_box_grid.xml',
        ],
    },
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
}
