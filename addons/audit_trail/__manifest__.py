# -*- coding: utf-8 -*-
{
    'name': 'Audit Trail (CBS-Style)',
    'version': '19.0.1.0.0',
    'category': 'Tools',
    'summary': 'Full audit log — tracks create, write, unlink on all configured models',
    'description': """
        CBS-style Audit Trail for Odoo 19
        ===================================
        - Tracks every Create / Write / Unlink action
        - Records: Module, Model, Record ID, Record Name,
          Field, Old Value, New Value, User, Date/Time, IP
        - Admin UI to enable/disable auditing per model
        - Searchable & filterable audit log view
        - Export to Excel / PDF
        - Access controlled by security groups
    """,
    'author': 'Your Company',
    'depends': ['base', 'mail'],
    'data': [
        'security/audit_security.xml',
        'security/ir.model.access.csv',
        'data/audit_rule_data.xml',
        'views/audit_log_views.xml',
        'views/audit_rule_views.xml',
        'views/audit_menu.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'post_init_hook': 'post_init_hook',
}
