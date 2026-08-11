# -*- coding: utf-8 -*-
{
    'name': 'Attendance Dashboard',
    'version': '19.0.1.0.0',
    'summary': 'HR Attendance Dashboard with KPIs and Charts',
    'description': """
        Attendance Dashboard
        =====================
        KPI cards (Total / Present / Late / On Leave / Absent), a same-day
        or date-range check-in progress line, and an attendance-by-operating
        -unit bar chart, with a Today / Yesterday / This Week / This Month /
        This Year filter.

        Ported from the Odoo 14 version of this module to Odoo 19:
            - Client action rebuilt as an OWL 2 component (the old
              odoo.define/AbstractAction/qweb-key stack no longer exists
              in Odoo 19).
            - Charts now use Odoo 19's own bundled Chart.js 4 (web.chartjs_lib)
              instead of a vendored Chart.js 2.8 copy, so no duplicate chart
              library is ever downloaded to the browser.
            - Dashboard KPI query merged from 2 aggregate scans into 1 using
              a FILTERed aggregate, cutting one DB round trip per load.
    """,
    'category': 'Human Resources',
    'author': 'Desalegn & Abeza',
    'website': 'https://bunnabanksc.com/',
    'license': 'LGPL-3',

    # hr_holidays: hr.leave is queried directly by table name in the KPI
    #   query, so it must be installed for that table to exist.
    # custom_hr_attendance: provides hr.attendance.check_in_status (Late)
    #   used by the Late KPI.
    # hr_employee_custom: provides hr.employee.default_operating_unit_id
    #   and the operating.unit model used by the work-unit breakdown chart.
    'depends': [
        'hr',
        'hr_attendance',
        'hr_holidays',
        'hr_employee_custom',
        'custom_hr_attendance',
    ],

    'data': [
        'views/attendance_dashboard_view.xml',
    ],

    'assets': {
        'web.assets_backend': [
            'attendance_dashboard/static/src/attendance_dashboard/*.js',
            'attendance_dashboard/static/src/attendance_dashboard/*.xml',
            'attendance_dashboard/static/src/attendance_dashboard/*.scss',
        ],
    },

    'installable': True,
    'application': False,
}
