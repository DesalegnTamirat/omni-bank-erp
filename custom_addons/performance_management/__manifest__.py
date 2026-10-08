{
    'name': 'Performance Management',
    'version': '1.0',
    'summary': 'Custom module to measure employee and work unit performance.',
    'post_init_hook': 'post_init_hook',
    'description': """
Custom module to measure employee and work unit performance.

## Step 1: Corporate Score Card

- Define corporate scorecard planning periods.
""",
    'author': 'Your Company',
    'website': '',
    'depends': [
        'base',
        'mail',
        'hr_employee_custom',
    ],
    'data': [
        'security/performance_security.xml',
        'security/ir.model.access.csv',
        'views/corporate_scorecard_views.xml',
        'views/populate_corporate_scorecard_wizard_views.xml',
        'views/corporate_appraisal_views.xml',
        'views/populate_corporate_appraisal_wizard.xml',
        'views/performance_objective_views.xml',
        'views/performance_job_objective.xml',
        'views/performance_job_template_views.xml',
        'views/performance_job_measure_bulk_views.xml',
        'views/populate_t2_scorecard_wizard_views.xml',
        'views/automatic_scorecard_notify_wizard_views.xml',
        'views/t2_scorecard.xml',
        'views/t3_scorecard.xml',
        'views/populate_t3_scorecard_wizard_views.xml',
        'views/t2_appraisal_views.xml',
        'views/populate_t2_appraisal_wizard_views.xml',
        'views/t3_appraisal_views.xml',
        'views/populate_t3_appraisal_wizard_views.xml',
        'views/performance_rejection_wizard_views.xml',
        'views/performance_menus.xml',
        'views/performance_dashboard_views.xml',
        'views/performance_master_data_views.xml',
        'data/performance_perspective_data.xml',
        'data/pms_ranking_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'performance_management/static/src/css/performance_management.css',
            'performance_management/static/src/js/performance_dashboard.js',
            'performance_management/static/src/xml/performance_dashboard.xml',
        ],
    },
    'application': True,
    'installable': True,
    'license': 'LGPL-3',
}