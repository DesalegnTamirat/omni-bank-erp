# -*- coding: utf-8 -*-
{
    'name':     'HR Resignation',
    'version':  '19.0.6.0.8',
    'category': 'Human Resources',
    'summary':  (
        'End-to-end separation workflow: request -> manager -> POMD/HR -> '
        'configurable digital clearance -> settlement -> certificate. '
        'Supports voluntary resignation, retirement, medical, probation '
        'termination, and employer-initiated separation.'
    ),
    'author':   'Bunna Bank',
    'license':  'LGPL-3',
    'depends': [
        'hr',
        'hr_employee_custom',
        'hr_leave_request_custom',
        'mail',
        'resl',
    ],
    'data': [
        'data/cbs_config_data.xml',
        # -- 1. Security groups -------------------------------------------
        'security/hr_resignation_security.xml',
        'security/ir.model.access.csv',

        # -- 2. Sequences & cron ------------------------------------------
        'data/ir_sequence_data.xml',
        'data/ir_cron_data.xml',

        # -- 3. Seed / configuration data ---------------------------------
        'data/clearance_config_data.xml',
        'data/exit_interview_data.xml',
        'data/hr_tax_bracket_data.xml',

        # -- 4. Wizards ---------------------------------------------------
        'wizard/hr_resignation_reject_wizard_views.xml',
        'wizard/hr_clearance_reject_wizard_views.xml',
        'wizard/hr_settlement_return_wizard_views.xml',

        # -- 5. Report ----------------------------------------------------
        'report/certificate_of_release.xml',
        'report/settlement_statement.xml',
        'report/exit_interview_report.xml',

        # -- 6. Views -----------------------------------------------------
        'views/hr_tax_bracket_views.xml',
        'views/hr_resignation_views.xml',
        'views/hr_resignation_dashboard_views.xml',
        'views/hr_separation_type_views.xml',
        'views/hr_clearance_config_views.xml',
        'views/hr_resignation_clearance_views.xml',
        'views/hr_exit_interview_views.xml',
        'views/hr_exit_interview_portal_templates.xml',
        'views/exit_interview_dashboard_views.xml',
        'views/hr_exit_analytics_views.xml',
        'views/hr_exit_dashboard_template.xml',
        'views/hr_settlement_views.xml',

        # -- 7. Menu ------------------------------------------------------
        'views/menu.xml',
        'views/hr_cash_indemnity_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hr_resignation/static/src/css/hr_resignation_dashboard.scss',
            'hr_resignation/static/src/css/exit_interview_dashboard.scss',
            'hr_resignation/static/src/js/hr_resignation_dashboard.js',
            'hr_resignation/static/src/xml/hr_resignation_dashboard.xml',
            'hr_resignation/static/src/js/exit_interview_dashboard.js',
            'hr_resignation/static/src/xml/exit_interview_dashboard.xml',
        ],
    },
    'installable': True,
    'application': True,
}
