# -*- coding: utf-8 -*-
{
    'name': 'Custom HR Attendance Management',

    'summary': (
        'Enterprise HR Attendance Management with Discipline Integration and Payroll Readiness for Odoo 19'
    ),

    'description': """
        Custom HR Attendance Management

        This module extends Odoo HR Attendance with:
            - Overtime tracking and balance computation
            - Job position based attendance exceptions
            - Location based attendance exceptions
            - Attendance pre-approval workflow
            - Configurable attendance reasons
            - Operating Unit based access control
            - Attendance analytics and summary wizard
            - Discipline integration (auto-flag repeated lateness / force checkout)
            - Rolling O(1) violation counters per employee
            - Payroll payload readiness (attendance.payroll.payload)
            - Session-cached ERP access gate (optional)
            """,

    'author': 'Desalegn & Abeza',
    'website': 'https://bunnabanksc.com/',
    'license': '',

    'category': 'Human Resources',
    'version': '19.0.3.0.0',

    'depends': [
        'hr',
        'hr_attendance',
        'mail',
        'hr_employee_custom',
        'hr_holidays',
        'discipline_management',
    ],

    'data': [
        # Security
        'security/hr_attendance_security.xml',
        'security/ir.model.access.csv',
        'security/hr_attendance_record_rules.xml',

        # Views
        'views/attendance_preapproval_views.xml',
        'views/location_based_exception_views.xml',
        'views/job_shift_views.xml',
        'views/job_position_exception_views.xml',
        'views/job_position_roster_exception_views.xml',
        'views/hr_employee_discipline_profile_views.xml',
        'views/hr_attendance_view.xml',
        'views/hr_attendance_reason_view.xml',
        'views/res_config_settings_views.xml',
        'views/over_time_views.xml',
        'views/hr_employee_views.xml',
        # Reports
        'views/overtime_report_views.xml',
        'views/job_position_exception_report_views.xml',
        'views/attendance_preapproval_report_views.xml',
        'views/acknowledged_attendance_report_views.xml',
        'views/force_checkout_history_views.xml',
        # Wizards
        'wizard/generate_detail_employee_attendance_report.xml',
        'wizard/manager_daily_attendance_wizard.xml',
        # Discipline flag wizard
        'wizard/hr_attendance_flag_wizard.xml',
        # Manual attendance entry wizard
        'wizard/hr_attendance_manual_wizard.xml',
        'views/generated_employee_attendance_details.xml',
        # Menus
        'views/menu_views.xml',
        'views/hide_regular_views.xml',
        # Static Data
        'data/job_shift_data.xml',
        'data/hr_attendance_reason_data.xml',
        'data/sql_functions.xml',
        # Discipline Offense Seeds (loaded after discipline_management data)
        'data/discipline_offense_attendance_data.xml',
        # Scheduled Actions
        'data/ir_cron_data.xml',
    ],

    'demo': [],

    'assets': {
        'web.assets_backend': [
            'custom_hr_attendance/static/src/my_attendance/my_attendance.js',
            'custom_hr_attendance/static/src/my_attendance/my_attendance.xml',
            'custom_hr_attendance/static/src/my_attendance/my_attendance.scss',
            'custom_hr_attendance/static/src/gate_guard/gate_guard.js',
        ],
    },

    'installable': True,
    'post_init_hook': 'post_init_hook',
}
