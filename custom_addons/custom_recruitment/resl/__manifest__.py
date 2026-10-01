{
    'name': 'OD Staff Loan',
    'version': '19.0.1.1.0',
    'summary': 'Staff Loan Request & Guarantee with Replacement Flow',
    'description': "Employee Loan and Guarantor Management",
    'category': 'Human Resources',
    'author': 'Abel Wondmeneh',
    'website': 'https://bunnabanksc.com',
    'depends': ['hr', 'base', 'mail','hr_employee_custom'],
    'data': [
        # Sequences & security
        'data/resl_sequence.xml',
        'security/resl_groups.xml',
        'security/ir.model.access.csv',
        'security/resl_rules.xml',

        # Core views
        'wizard/resl_loan_replacement_wizard.xml',
        'views/resl_loan_replacement_log_views.xml',
        'views/guarantor_lookup_wizard_views.xml',
        'views/resl_disbursement_wizard_views.xml',
        'views/resl_loan_views.xml',
        'views/hr_employee_inherit_views.xml',
        'views/resl_menu.xml',
    ],
    'demo': [],
    'assets': {
        'web.assets_backend': [
            'resl/static/src/scss/resl_backend.scss',
            'resl/static/src/js/find_guarantor_button.js',
            'resl/static/src/xml/find_guarantor_button.xml',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
    'post_init_hook': 'assign_resl_groups',
    'web_icon': 'resl/static/description/icon.png',
}