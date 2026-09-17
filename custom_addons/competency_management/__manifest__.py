# -*- coding: utf-8 -*-
{
    'name': "Competency Management System",
    'summary': "Competency dictionary, job role mapping, 360 evaluations, and TNA gap analytics.",
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Competency',
    'author': 'Desalegn & Abeza',
    'website': 'https://www.bunnabanksc.com',
    'license': 'LGPL-3',
    'description': """
Competency Management System
============================
Operationalizes organizational competency frameworks across job roles, multi-rater assessments, and gap analytics.

Features:
- Competency Dictionary & Role-Competency Mapping (Core, Leadership, Technical).
- Multi-Source 360 Evaluations (Self, Peer, Subordinate, Supervisor).
- Interactive Analytics Dashboard & Training Needs Analysis (TNA) Gap Reporting.
- QWeb PDF & Excel Exports for competency matrices, individual profiles, and team gaps.
    """,
    'depends': [
        'base',
        'hr',
        'mail',
        'portal',
        'hr_employee_custom',
    ],
    'data': [
        'security/competency_security.xml',
        'security/ir.model.access.csv',
        'data/competency_sequence.xml',
        'data/competency_seed_data.xml',
        'data/competency_cron.xml',
        'views/competency_competency_views.xml',
        'views/competency_cluster_views.xml',
        'views/competency_role_mapping_views.xml',
        'views/competency_coverage_report_views.xml',
        'views/competency_assessment_views.xml',
        'views/competency_dashboard_views.xml',
        'views/competency_matrix_config_views.xml',
        'views/competency_director_peer_config_views.xml',
        'views/competency_report_templates.xml',
        'wizards/competency_role_mapping_clone_wizard_views.xml',
        'wizards/competency_report_wizard_views.xml',
        'views/competency_dashboard_snapshot_views.xml',
        'views/competency_skills_test_views.xml',
        'views/competency_team_dashboard_views.xml',
        'views/competency_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'competency_management/static/src/scss/competency_dashboard.scss',
            'competency_management/static/src/js/competency_dashboard.js',
            'competency_management/static/src/xml/competency_dashboard.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
}
