# -*- coding: utf-8 -*-

from . import bonus_transfer_wizard
from . import compute_bonus_wizard
from . import contract_wizard
from . import copy_manpower_plan
from . import copy_manpower_plan_wizard
from . import dynamic_fields
# from . import external_candidates  # moved to custom_recruitment
from . import generate_employee_attendance_report
from . import hr_leave_allocation_accrual_calculator
# from . import hr_work_entry_regeneration_wizard  # commented out: entirely depends on 'hr.work.entry' model, which does not exist (hr_work_entry module not installed)
from . import increment_transfer_wizard
# from . import internal_candidates  # moved to custom_recruitment
from . import net_salary_payment_wizard
# from . import notify_external_candidates  # moved to custom_recruitment
# from . import notify_internal_candidates  # moved to custom_recruitment
from . import post_processing_salary_information
from . import preprocessing_salary_information
from . import print_employee_report
from . import reset_employee_login_wizard
from . import reset_login
from . import salary_details_wizard
from . import service_request_completion_wizard
from . import service_request_rejection_wizard
from . import transaction_api
