# -*- coding: utf-8 -*-
{
    'name': "Succession Management",
    'summary': "Dedicated Succession Management Module: Critical Positions, Talent Pools, Successor Assessment and Governance.",
    'version': '19.0.1.0.0',
    'category': 'Human Resources',
    'author': 'Taresa',
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
- Successor Pipeline management: identify and group potential successors per critical position.
- Successor Candidate nomination with system-assisted readiness scoring.
- Competency Gap analysis for successor candidates (from competency_management module).
- PMS score integration for candidate eligibility.
- Configurable assessment (exam / interview / PMS weights, waivers, manual result entry, final score & pass mark).
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
        'custom_recruitment',
    ],
    'data': [
        'security/succession_security.xml',
        'security/ir.model.access.csv',
        'data/succession_cron.xml',
        'data/succession_sequence.xml',
        'data/succession_lookup_data.xml',
        'data/succession_readiness_data.xml',
        'data/succession_assessment_config_data.xml',
        'data/succession_assessment_data.xml',
        'views/succession_dashboard_action.xml',
        'views/succession_critical_position_views.xml',
        'views/succession_readiness_level_views.xml',
        'views/succession_assessment_views.xml',
        'views/succession_candidate_plan_wizard_views.xml',
        'views/succession_candidate_assessment_wizard_views.xml',
        'views/succession_candidate_set_readiness_wizard_views.xml',
        'views/succession_candidate_views.xml',
        'views/succession_development_plan_views.xml',
        'views/succession_plan_early_completion_wizard_views.xml',
        'views/succession_plan_extension_wizard_views.xml',
        'views/succession_plan_completion_wizard_views.xml',
        'views/succession_dashboard_views.xml',
        'views/succession_candidate_invitation_views.xml',
        'views/succession_auto_match_wizard_views.xml',
        'views/succession_candidate_nomination_wizard_views.xml',
        'views/succession_career_discussion_views.xml',
        'views/succession_ninebox_cell_views.xml',
        'views/succession_lookup_views.xml',
        'views/succession_configuration_views.xml',
        'views/succession_reporting_views.xml',
        'views/succession_report_wizard_views.xml',
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
            'bunna_succession_management/static/src/css/auto_match_table.css',
            'bunna_succession_management/static/src/js/auto_match_select_all.js',
            'bunna_succession_management/static/src/js/critical_position_form_notifications.js',
            'bunna_succession_management/static/src/js/eval_modal_actions.js',
            'bunna_succession_management/static/src/xml/auto_match_select_all.xml',
            'bunna_succession_management/static/src/css/succession_reports_hub.css',
            'bunna_succession_management/static/src/js/succession_reports_hub.js',
            'bunna_succession_management/static/src/xml/succession_reports_hub.xml',
            'bunna_succession_management/static/src/js/group_selection.js',
            'bunna_succession_management/static/src/xml/group_selection.xml',
        ],
    },
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
}
