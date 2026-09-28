# -*- coding: utf-8 -*-
{
    'name': "Bunna Learning Management System (LMS)",
    'summary': "Structured digital training platform, secure video streaming, learning paths, quizzes, automated certification, and compliance analytics.",
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Learning',
    'author': 'Bunna Bank S.C.',
    'website': 'https://www.bunnabanksc.com',
    'license': 'LGPL-3',
    'description': """
Bunna Bank Learning Management System (LMS)
===========================================
Operationalizes BRD Part 3 Module 2 requirements for employee training and compliance learning:
- Course creation and lifecycle management (Draft, Review, Published, Superseded/Archived).
- Structured Learning Paths with linear or optional/branched prerequisite pathways.
- Internal secure video hosting with chunked/adaptive range streaming (no YouTube dependency).
- Anti-cheat learning controls: anti-skip fast-forward prevention, resume capability, and mandatory completion gates.
- Timed assessment engine: randomized question pools, attempt caps, cooldown intervals, and automated instant grading.
- Automatic PDF certificate generation with unique security verification hash and public online validation page.
- Direct integration bridges to core HR: pushes completions into hr.training.history and attaches certificates to hr.employee.document.
- Branch and department compliance matrix analytics (AML/CFT, Cyber Security, etc.).
- Gamification: Best Scorer of the Month, training points ledger, and course completion badges.
    """,
    'depends': [
        'base',
        'auth_ldap',
        'auth_totp',
        'hr',
        'mail',
        'portal',
        'hr_employee_custom',
        'competency_management',
        'knowledge_management',
        'recognition_engine',
    ],
    'data': [
        'security/lms_security_groups.xml',
        'security/lms_security_rules.xml',
        'security/ir.model.access.csv',
        'data/lms_sequence.xml',
        'data/lms_default_data.xml',
        'views/lms_category_views.xml',
        'views/lms_course_views.xml',
        'views/lms_learning_path_views.xml',
        'views/lms_assignment_views.xml',
        'views/lms_enrollment_views.xml',
        'views/lms_assessment_views.xml',
        'views/lms_certificate_views.xml',
        'views/lms_analytics_views.xml',
        'views/lms_gamification_views.xml',
        'views/lms_templates.xml',
        'reports/lms_certificate_report_templates.xml',
        'views/res_config_settings_views.xml',
        'views/lms_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'learning_management/static/src/scss/lms_style.scss',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
