# -*- coding: utf-8 -*-

from . import archive_mixin
from . import upgrade_mail_patch
from . import hr_employee_no_track
from . import acting_position_rule
# from . import applicant_assessment  # moved to custom_recruitment
# from . import applicant_shortlist  # moved to custom_recruitment
# from . import assessment_criteria  # moved to custom_recruitment
# from . import blacklist_pool  # moved to custom_recruitment
# from . import candidate_shortlist  # moved to custom_recruitment
from . import company_manpower_plan
from . import disciplinary_action
from . import disciplinary_outcome
from . import discipline_action
from . import employee_acting_service_request
# from . import employee_attendance_details  # disabled: attendance feature not active
from . import employee_demotion
from . import employee_increment_setup
from . import employee_job
from . import employee_service_request
from . import employee_transfer_service_request
from . import guarentees_details
# from . import hr_attendance  # disabled: attendance feature not active
from . import hr_awards
# hr_payroll_structure_type must load before hr_contract, since hr_contract.py
# contains a class with `_inherit = 'hr.payroll.structure.type'`, and that
# model is defined (via _name) in hr_payroll_structure_type.py rather than
# coming from a dependency.
from . import hr_payroll_structure
from . import hr_payroll_structure_type
from . import hr_contract
from . import hr_contract_type
# hr_contract (above) must load before any file below that does
# `_inherit = 'hr.contract'`, since this module defines hr.contract itself
# instead of depending on the stock hr_contract addon.
from . import emp_probation
from . import history
from . import hr_department
from . import hr_employee_contract
from . import hr_employee_contract_history
from . import hr_employee_grade
from . import hr_employee_hrMaster
from . import hr_employee_insurance
from . import hr_employee_master
from . import hr_employee_pension
from . import hr_employee_transfer_history
from . import hr_job
from . import hr_job_history
from . import hr_leave
# operating_unit must load before hr_operating_unit, since hr_operating_unit.py
# does `_inherit = 'operating.unit'` on the model defined (via `_name`) here —
# merged in from the standalone 'operating_unit' module.
from . import operating_unit_job_position
from . import operating_unit
# from . import hr_payroll_adjustments  # disabled: payroll/accounting feature not active
from . import resource_calendar
from . import hr_employee_vehicle
from . import res_users
from . import hr_qualification_info_employee
from . import hr_reinstated_history
# from . import hr_salary_history  # disabled: accounting/payroll feature not active
# from . import hr_timesheet_cost_history  # disabled: accounting/payroll feature not active
from . import hr_training_history
from . import increment
from . import inherit2
# from . import internal_job_position  # moved to custom_recruitment
# from . import internal_recruitment  # moved to custom_recruitment
# from . import interview_assessment  # moved to custom_recruitment
from . import job_history
# from . import job_vacancy  # moved to custom_recruitment
from . import leave_request
from . import leave_request_managr
from . import penalty_and_allowances
from . import re_instating
from . import recruitment_competency
from . import recruitment_experience
# from . import recruitment_process_external  # moved to custom_recruitment
# from . import recruitment_process_internal  # moved to custom_recruitment
from . import recruitment_qualifications
# from . import regularization  # disabled: attendance feature not active
from . import report_code
# from . import salary_details  # disabled: accounting/payroll feature not active
# from . import selected_external  # moved to custom_recruitment
# from . import selected_internal  # moved to custom_recruitment
from . import service_award
from . import service_request_type
# from . import staff_attendance_details  # disabled: attendance feature not active
from . import supplementary
from . import transfer_form
from . import vacancy_workunit
from . import work_unit_manpower_plan

