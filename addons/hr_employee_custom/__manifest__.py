# -*- coding: utf-8 -*-
{
    'name': "HR Employee Custom Extensions",
    'summary': "Adds Employee Grades and Levels configurations and mandatory fields.",
    'version': '19.0.1.0.0',
    'category': 'Human Resources',
    'author': 'Bunna Bank',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'base_setup',
        'hr',
        'hr_attendance',
        'hr_holidays',
        'hr_homeworking',
        'hr_org_chart',
        'hr_recruitment',
        'mail',
        'portal',
        'website',
        'website_hr_recruitment',

    ],
    'data': [

        'security/security.xml',

        'security/operating_unit_security.xml',
        'security/security_hr_contract.xml',
        'security/ir.model.access.csv',

        # -- Contract --
        'data/hr_contract_data.xml',
        'views/hr_contract_views.xml',
        'views/hr_contract_history_views.xml',
        'wizards/contract_wizard.xml',

        # -- Employee Master --
        'views/hr_department_views.xml',
        'views/hr_operating_unit_views.xml',
        # Merged from the standalone 'operating_unit' module.
        'data/operating_unit_data.xml',
        'views/res_users_operating_unit_views.xml',
        'views/hr_employee_grade_views.xml',
        'views/hr_job_history_views.xml',
        'views/employee_job.xml',
        'views/employee_grade.xml',
        'views/history_views.xml',
        'views/hr_job.xml',
        'views/job_history.xml',


        'views/recruitment_qualifications.xml',
        'views/recruitment_competency.xml',
        'views/recruitment_experience.xml',
        'data/hr_job_data.xml',

        # -- Menu (edited to only reference the active items above) --

        # -- Discipline / Bonus & Penalty --
        'views/disciplinary_sequence.xml',
        'security/security_disciplinary.xml',
        'views/discipline_action.xml',
        'views/discipline_appeal.xml',
        'views/disciplinary_outcome.xml',
        'views/bonus_penalty_views.xml',
        'views/bonus_penalty.xml',
        'views/category_view.xml',
        'views/discipline_penalty_rule.xml',
        'wizards/bonus_transfer_wizard.xml',
        'wizards/compute_bonus_wizard.xml',

        # -- Service Request --
        'security/security_service_request.xml',
        'data/employee_service_request_sequence.xml',
        'data/emp_service_req.xml',
        'data/employee_self_service_sequence.xml',
        'views/service_request_type_views.xml',
        'views/service_request_views.xml',
        'views/service_request.xml',
        'views/employee_ser_request.xml',
        'wizards/completion_wizard_views.xml',
        'wizards/rejection_wizard_views.xml',

        # -- Guarantees / Supplementary Role --
        'views/guarentees_details_views.xml',
        'views/guarentee_details.xml',
        'views/supplementary.xml',

        # -- Transfer / Re-instating / Demotion / Part-time --
        'data/emp_transfer_form.xml',
        'views/transfer_form_views.xml',
        'views/transform_form.xml',
        'views/hr_transfer_history_views.xml',
        'views/re_instating_views.xml',
        'views/re_instating.xml',
        'views/hr_reinstated_history_views.xml',
        'views/employee_demotion_views.xml',
        'views/employee_demotion.xml',
        'views/part_time_employment_views.xml',
        'views/part_time_employement.xml',

        # -- Probation --
        'data/prob_sequence.xml',
        'views/emp_probation.xml',
        'views/probation_assessment_form.xml',

        # -- Increment --
        'views/increment.xml',
        'views/employee_increment_setup.xml',
        'wizards/increment_transfer_wizard.xml',

        # -- Insurance / Training / Report Codes / Service Award --
        'views/hr_employee_insurance_views.xml',
        'views/hr_training_history_views.xml',
        'views/report_code_views.xml',
        'views/service_award.xml',
        'views/award_received.xml',

        # -- Manpower Plan --
        'views/company_manpower_plan.xml',
        'views/work_unit_manpower_plan.xml',
        'views/manpower_details.xml',
        'wizards/copy_manpower_plan_wizard_views.xml',
        'wizards/copy_manpower_plan.xml',

        # -- Leave / Misc data --
        'data/discipline_seq.xml',
        'data/leave_request.xml',
        'data/supp_role.xml',
        'views/hr_payroll_structure_views.xml',

        # -- Reports (HR letters) --
        'reports/acting_assignment.xml',
        'reports/acting_assignment_managerial.xml',
        'reports/acting_termination.xml',
        'reports/mangerial_different_location.xml',
        'reports/mangerial_same_location.xml',
        # 'reports/minute_template.xml',  # moved to custom_recruitment
        'reports/non_mangerial_different_location.xml',
        'reports/non_mangerial_same_location.xml',
        'reports/permanent_letters.xml',
        'reports/probation_termination.xml',
        'reports/promotion_letter.xml',
        'reports/promotion_revocation.xml',
        'reports/release_format.xml',
        'reports/report.xml',
        'reports/transfer_letter.xml',
        'reports/employee_experience_letter.xml',

        # -- Misc utility wizards --
        'wizards/reset_employee_login_wizard_views.xml',
        'wizards/reset_login.xml',
        'wizards/print_employee_report_views.xml',
        'views/employee_history.xml',
        'views/hr_employee_master_views.xml',

        # ══════════════════════════════════════════════════════════
        # DISABLED — Attendance (module not available in Odoo 19)
        # and Payroll/Salary/Accounting (hr.salary.rule-related).
        # Re-add when those modules/features are available again.
        # ══════════════════════════════════════════════════════════

        # -- Attendance --
        # 'security/security_attendance_regular.xml',
        # 'views/category_attendance_regular.xml',
        # 'views/employee_attendance_details.xml',
        # 'views/regularization_views.xml',
        # 'views/staff_attendance_details.xml',
        # 'wizards/generate_employee_attendance_report.xml',

        # -- Allowance / Payroll / Salary (accounting / hr.salary.rule) --
        # 'views/emp_allowance.xml',
        # 'views/salary_rules.xml',
        # 'views/payroll_adj.xml',
        # 'data/payroll_adjustments_seq.xml',
        # 'wizards/net_salary_payment_wizard.xml',
        # 'wizards/post_processing_salary_information.xml',
        # 'wizards/preprocessing_salary_information.xml',
        # 'wizards/salary_details_wizard.xml',
        # 'views/hr_salary_history_views.xml',
        # 'views/hr_timesheet_cost_history_views.xml',
        'views/menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hr_employee_custom/static/src/css/hr_employee_custom.css',
        ],
    },
    'installable': True,
    'application': False,
}
