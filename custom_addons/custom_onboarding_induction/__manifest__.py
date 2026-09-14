# -*- coding: utf-8 -*-
{
    'name': 'Onboarding and Induction Management System',
    'version': '19.0.1.0.0',
    'category': 'Human Resources',
    'summary': 'Standalone BRD-aligned Onboarding and Corporate Induction Management System for Bunna Bank S.C.',
    'description': """
        Module 14: Onboarding and Induction Management System
        =====================================================
        This module provides a centralized, automated, and auditable framework for integrating
        newly hired employees into Bunna Bank S.C., fully decoupled into:

        1. Corporate Induction Management (PPDD/POMD Orientation & LMS System)
        2. Workplace Onboarding Management (POMD Pre-Boarding Gate, IT Alerts, Buddy Support, Work Unit Tasks, Evaluations)

        Includes strict Segregation of Duties (SoD) enforcement across approval hierarchies.
    """,
    'author': 'EAD Team',
    'website': 'https://www.bunnabanksc.com',
    'depends': [
        'base',
        'hr',
        'mail',
        'hr_employee_custom',
        'custom_recruitment',
    ],
    'data': [
        'security/onboarding_induction_security.xml',
        'security/ir.model.access.csv',
        'data/onboarding_induction_sequence.xml',
        'data/onboarding_induction_template_data.xml',
        'views/hr_onboarding_dashboard_action.xml',
        'views/hr_dashboard.xml',
        'views/hr_config_views.xml',
        'views/hr_induction.xml',
        'views/hr_onboarding.xml',
        'views/onboarding_induction_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'custom_onboarding_induction/static/src/onboarding_dashboard/onboarding_dashboard.css',
            'custom_onboarding_induction/static/src/onboarding_dashboard/onboarding_dashboard.xml',
            'custom_onboarding_induction/static/src/onboarding_dashboard/onboarding_dashboard.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
