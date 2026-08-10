# -*- coding: utf-8 -*-
{
    'name': "Employee Development System (EDS)",
    'summary': "Classroom training management: TNA, curriculum, annual L&D plan, sessions, "
               "nomination, delivery, evaluation (L1-L4), certification, budget, sponsorship, "
               "staff education and internship.",
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Employee Development',
    'author': 'Desalegn & Abeza',
    'website': 'https://www.bunnabanksc.com',
    'license': 'LGPL-3',
    'description': """
Employee Development System (EDS)
=================================
Classroom training and talent development management system covering:
  - Training Needs Analysis (TNA) capture and consolidation
  - Course catalog and curriculum management
  - Trainer profile and qualification registry
  - Session scheduling and venue booking
  - Nomination, approval, and enrollment workflows
  - Attendance and delivery tracking
  - Multi-level evaluation engines (Levels 1 to 4)
  - Completion and certification management
  - Budget and cost tracking
  - Reporting and analytics dashboards
  - Staff education assistance and sponsorship
  - Internship facilitation
    """,
    'depends': [
        'base',
        'hr',
        'mail',
        'portal',
        'hr_employee_custom',
        'competency_management',
        'audit_trail',
    ],
    'data': [
        'security/eds_security.xml',
        'security/ir.model.access.csv',
        'data/eds_sequences.xml',
        'data/eds_seed_data.xml',
        'data/eds_cron.xml',
        'data/eds_audit_rules.xml',
        'views/res_config_settings_views.xml',
        'views/eds_consolidation_views.xml',
        'wizards/eds_consolidation_wizard_views.xml',
        'views/eds_curriculum_views.xml',
        'views/eds_course_views.xml',
        'views/eds_trainer_views.xml',
        'views/eds_procurement_views.xml',
        'views/eds_annual_plan_views.xml',
        'views/eds_session_views.xml',
        'views/eds_unscheduled_views.xml',
        'views/eds_nomination_views.xml',
        'wizards/eds_nomination_wizard_views.xml',
        'views/eds_delivery_views.xml',
        'views/eds_tna_views.xml',
        'views/eds_evaluation_views.xml',
        'views/eds_certificate_views.xml',
        'views/eds_budget_views.xml',
        'views/eds_sponsorship_education_views.xml',
        'views/eds_internship_views.xml',
        'views/eds_integration_views.xml',
        'views/eds_report_views.xml',
        'views/hr_employee_views.xml',
        'views/eds_menus.xml',
        'report/eds_tna_register.xml',
        'report/eds_certificate_template.xml',
        'report/eds_reports.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
