# -*- coding: utf-8 -*-
{
    'name': "Custom Recruitment",
    'summary': "Recruitment, Job Vacancy and Applicant management, split out of hr_employee_custom "
               "for independent maintenance.",
    'description': """
Custom Recruitment
===================
This module contains all recruitment / job-vacancy related functionality that
used to live inside `hr_employee_custom`:

- Job Vacancy Form (job.vacancy) and its supporting delegation/panel/hiring
  status sub-models, plus the BB Internal / BB External applicant references.
- Internal Job Position (employee vacancy self-application) flow.
- Internal & External Recruitment process (eligibility, notification,
  selection, panels and delegation teams).
- Applicant / Interview Assessment, Assessment Criteria.
- Applicant & Candidate Shortlists, Blacklist Pool.
- Job Acceptance portal templates.
- Related wizards (Internal/External Candidates, Notify Internal/External
  Candidates) and the Committee Minute report for Job Vacancy.
- Probation Management (hr.employee.probation): 60/75-day duration by
  employee category, 5-day-prior supervisor notification, and
  Satisfactory/Unsatisfactory/Discipline-Issue outcome recording
  (BRD .
- Employee-Initiated Transfer Process (employee.transfer.request): grade/
  position restriction, 1-year service rule, discipline-based eligibility
  and score deduction, Exchange Transfer support, employee withdrawal, and
  post-approval refusal flagging to HR (BRD .
- Transfer Ranking Algorithm and Committee Minutes (employee.transfer.request
  scoring + transfer.committee.minutes / transfer.committee.minutes.line):
  weighted Transfer Suitability Score (Application Date 20%, Total
  Experience 20%, Service in Current Location 20%, PMS Score 40%), discipline
  deduction, ranked list, and a printable Transfer Committee Minutes report
  (BRD .

It depends on `hr_employee_custom` for shared HR master-data models such as
Operating Unit, Employee Grade and the custom fields added on hr.employee.

Note: a small number of "Recruitment Criteria" lookup lists (Recruitment
Qualification / Competency / Experience) and the Vacancy Workunit SQL view
remain in `hr_employee_custom` because they are also used directly by
Employee/Job/Applicant extensions that are not recruitment-specific
(hr_qualification_info_job, hr_experience_info_job, hr_competencies_info_job,
hr_new_department_info_job). Moving them here would create a circular module
dependency, so they were intentionally left in place.
    """,
    'version': '19.0.1.0.0',
    'category': 'Human Resources',
    'author': 'Bunna Bank',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'hr',
        'hr_recruitment',
        'mail',
        'portal',
        'website',
        'hr_employee_custom',
        'discipline_management',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/recruitment_security_rules.xml',
        'views/recruitment_master_data.xml',

        # -- Data / Sequences --
        'data/bb_external.xml',
        'data/bb_internal_external.xml',
        'data/hr_job_vacancy.xml',
        'data/employee_transfer_probation.xml',
        'data/recruitment_request_sequence.xml',
        'data/recruitment_scoring_data.xml',
        'data/recruitment_master_seed_data.xml',

        # -- Reports (must load before views referencing their actions) --
        'reports/minute_template.xml',
        'reports/transfer_minute_template.xml',

        # -- Menus Root (must load first so parent menus exist early) --
        'views/menu_recruitment_root.xml',

        # -- Dashboard --
        'views/recruitment_dashboard_action.xml',

        # -- Recruitment Criteria / Internal Job Position --
        'views/internal_job_position_views.xml',

        # -- Portal --
        'views/acceptance_portal.xml',

        # -- Core Recruitment Views --
        'views/applicant_assessment.xml',
        'views/applicant_shortlist.xml',
        'views/assessment_criteria.xml',
        'views/candidate_shortlist.xml',
        'views/blacklist_pool.xml',
        'views/eligible_employees_external.xml',
        'views/eligible_employees_internal.xml',
        'views/internal_recruitment.xml',

        'views/interview_assessment.xml',
        'views/job_vacancy.xml',
        'views/recruitment_process_external.xml',
        'views/external_default_criteria_views.xml',
        'views/recruitment_process_internal.xml',
        'views/selected_external.xml',
        'views/selected_internal.xml',
        'views/hr_applicant_views.xml',
        'views/employee_probation.xml',
        'views/employee_transfer.xml',
        'views/transfer_ranking.xml',
        'views/transfer_config_settings.xml',
        'views/job_vacancy_competency_views.xml',
        'views/employee_education_views.xml',
        # -- Recruitment Request Management  --
        'views/recruitment_request.xml',

        # -- Scoring Engine, Offer Management, Application Window, Blacklist (FRS 5,6,9,11) --
        'views/recruitment_scoring_views.xml',
        'views/talent_roster_views.xml',
        'data/talent_roster_cron.xml',

        # -- Wizards (views + actions only; menu items are in menu_recruitment.xml) --
        'wizards/external_candidates.xml',
        'wizards/internal_candidates.xml',
        'wizards/notify_internal_candidates.xml',
        'wizards/talent_roster_wizard.xml',

        # -- Menus (must load AFTER wizards so action refs resolve) --
        'views/menu_recruitment.xml',
    ],
    'installable': True,
    'application': False,
    'assets': {
        'web.assets_backend': [
            'custom_recruitment/static/src/recruitment_dashboard/recruitment_dashboard.css',
            'custom_recruitment/static/src/recruitment_dashboard/recruitment_dashboard.xml',
            'custom_recruitment/static/src/recruitment_dashboard/recruitment_dashboard.js',
        ],
    },
}
