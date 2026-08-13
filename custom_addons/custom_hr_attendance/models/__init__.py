# -*- coding: utf-8 -*-
from . import res_config_settings
from . import hr_attendance
from . import attendance_preapproval
from . import job_shift
from . import job_position_exception
from . import job_position_roster_exception
from . import location_based_exception
from . import hr_attendance_reason
from . import over_time
from . import over_time_consumption
from . import over_time_leave
from . import over_time_leave_manager


from . import generate_employee_attendance_details
from . import over_time_report
from . import job_position_exception_report
from . import attendance_preapproval_report
from . import acknowledged_attendance_report
from . import res_users
from . import restrict_checkin
from . import attendance_payroll_payload
# Rolling violation counters on hr.employee (must load before discipline_case_attendance)
from . import hr_employee_counters
# Discipline integration: case creation and violation counter processing
from . import discipline_case_attendance
# ERP access gate: session-cached check-in enforcement (feature-flagged, OFF by default)
from . import ir_http
from . import hr_attendance_notification_log

# from . import test
