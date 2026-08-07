# -*- coding: utf-8 -*-
{
    'name': 'Bunna Custom Website Module',
    'version': '19.0.1.0.0',
    'summary': 'Adds a dynamic frontend page and custom website menu.',
    'category': 'Website',
    'author': 'EAD Team',
    'depends': ['base', 'web', 'website'],
    'data': [
        'views/templates.xml',
    ],

    'assets': {
        'web.assets_backend': [
            'bunna_custom_web_page/static/src/user_menu_patch.js',
            ('before', 'web/static/src/scss/primary_variables.scss',
             'bunna_custom_web_page/static/src/scss/primary_variables.scss'),
            'bunna_custom_web_page/static/src/scss/website_overrides.scss',
        ],
        'web.assets_frontend': [
            ('before', 'website/static/src/scss/primary_variables.scss',
             'bunna_custom_web_page/static/src/scss/primary_variables.scss'),
            'bunna_custom_web_page/static/src/scss/website_overrides.scss',
        ],
    },

    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}