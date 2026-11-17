# -*- coding: utf-8 -*-
{
    'name': 'Bunna HR Announcements',
    'version': '19.0.1.10.0',
    'summary': 'Post and revoke text announcements shown on the Bunna website.',
    'category': 'Website',
    'author': 'EAD Team',
    'depends': ['website', 'mail', 'bunna_custom_web_page'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/announcement_data.xml',
        'views/announcement_views.xml',
        'views/website_templates.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
