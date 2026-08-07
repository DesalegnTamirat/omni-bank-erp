{
    'name': 'Custom Planning',
    'version': '19.0.1.0.0',
    'summary': 'Custom Planning Module - Plan Version, Fiscal Year & Man Power Planning',
    'description': """
Custom Planning Module
=======================
This module implements a sample custom Planning workflow with:

1. Dashboard tab (placeholder, to be built later)
2. Configuration tab
   - Fiscal Year master (e.g. 2021-2022, 2023-2024) with auto Start/End dates
     (01-Jul-YYYY to 30-Jun-YYYY+1) and duplicate-definition validation.
   - Plan Version with Plan Status (Pending / Draft / Notify / Approve),
     linked Fiscal Year, and auto-populated Plan Start/End Date.
3. Planning tab
   - Company Man Power: overall man power planning for the company.
   - Work Unit Man Power: Work Unit + Plan Version + Fiscal Year driven
     man power planning with an approval workflow
     (Draft -> Initiated -> Approved / Rejected) based on the
     organizational hierarchy (Work Unit's approving manager).

NOTE: This is a starter / sample scaffold intended to be reviewed and
revalidated with the functional team before being extended further.
    """,
    'category': 'Human Resources/Planning',
    'author': 'Your Company',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['base', 'hr', 'mail','hr_employee_custom'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'security/planning_rules.xml',
        'views/fiscal_year_views.xml',
        'views/work_unit_manpower_views.xml',
        'views/dashboard_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
