# -*- coding: utf-8 -*-
{
    'name': "Competency Management System",
    'summary': "Integrated Competency Framework: dictionary, role mapping, assessment, gap analysis and IDP.",
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Competency',
    'author': 'Desalegn & Abeza',
    'website': 'https://www.bunnabanksc.com',
    'license': 'LGPL-3',
    'description': """
Competency Management System (Bunna Bank ERP HR Upgrade)
========================================================
Support module for the Employee Development System (EDS). Operationalizes the
Bank's Integrated Competency Framework (Core / Leadership / Technical pillars,
Basic / Intermediate / Advanced / Expert proficiency levels).

Key Features:
- Competency Framework & Dictionary administration with version control.
- Competency Clusters bundling related competencies with required minimum proficiency.
- Role-Competency Mapping (Job Position + Grade) with bulk clone-and-adapt wizard and coverage report.
- Multi-Source Competency Assessment (self / supervisor / 360 anonymized feedback / skills test) with
  achievement status (Exceeds/Meets/Below), gap priority, approval workflow and locking.
- Team Competency Gap Dashboard & Industry/Internal Benchmarking Comparison reports.
- Individual Development Plans (IDP) with activities, review checkpoints, and LMS course auto-recommendations.
- Data Quality & Governance automated validator cron.
- Integration API methods for Recruitment candidate screening (FR-COM-029), EDS (TNA input), and Employee Master smart buttons.
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
        'views/competency_skills_test_views.xml',
        'views/competency_team_dashboard_views.xml',
        'views/competency_dashboard_snapshot_views.xml',
        'views/competency_dashboard_views.xml',
        'views/competency_matrix_config_views.xml',
        'views/competency_report_templates.xml',
        'views/hr_employee_views.xml',
        'wizards/competency_role_mapping_clone_wizard_views.xml',
        'wizards/competency_report_wizard_views.xml',
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
}
