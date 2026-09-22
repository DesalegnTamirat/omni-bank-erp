# -*- coding: utf-8 -*-
{
    'name': 'Bunna Bank - Unified Recognition & Gamification Engine',
    'summary': 'Unified gamification points ledger, leaderboard, and monthly awards across KMS and LMS.',
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Gamification',
    'author': 'Bunna Bank S.C.',
    'website': 'https://www.bunnabanksc.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'hr',
        'mail',
    ],
    'data': [
        'security/recognition_security_groups.xml',
        'security/ir.model.access.csv',
        'views/recognition_point_views.xml',
        'views/recognition_award_views.xml',
        'views/recognition_menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
