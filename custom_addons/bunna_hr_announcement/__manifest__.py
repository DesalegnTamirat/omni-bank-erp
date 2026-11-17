# -*- coding: utf-8 -*-
{
    'name': 'Bunna HR Announcements',
    'version': '19.0.2.3.8',
    'summary': 'Post and revoke text announcements shown on the Bunna website.',
    'category': 'Website',
    'author': 'EAD Team',
    'depends': ['website', 'mail', 'bunna_custom_web_page'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/announcement_data.xml',
        'data/announcement_cron.xml',
        'views/announcement_views.xml',
        'views/dashboard_views.xml',
        'views/website_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'bunna_hr_announcement/static/src/css/announcement_status.css',
            'bunna_hr_announcement/static/src/dashboard/dashboard.css',
            'bunna_hr_announcement/static/src/dashboard/dashboard.js',
            'bunna_hr_announcement/static/src/dashboard/dashboard.xml',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
