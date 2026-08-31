{
    'name': 'HR Leave Request Custom',
    'version': '19.0.1.0.4',
    'summary': 'Custom Leave Request extension for hr.holidays (Time Off)',
    'description': """
        Extends the standard Time Off (hr.holidays) module with additional
        fields required for the custom Leave Request form.
    """,
    'category': 'Human Resources/Time Off',
    'author': 'Abel Wondmeneh',
    'depends': [
        'base',
        'hr',
        'hr_holidays',
        'hr_employee_custom',  # Your custom employee module
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/hr_holidays_custom_views.xml',
        'views/hr_leave_type_custom_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}