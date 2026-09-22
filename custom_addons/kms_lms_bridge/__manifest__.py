# -*- coding: utf-8 -*-
{
    'name': "Bunna Bank - KMS & LMS Knowledge Bridge",
    'summary': "Bidirectional linkage connecting digital library resources and lessons learned to LMS courses.",
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Knowledge',
    'author': 'Bunna Bank S.C.',
    'website': 'https://www.bunnabanksc.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'knowledge_management',
        'learning_management',
    ],
    'data': [
        'views/kms_lms_bridge_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
