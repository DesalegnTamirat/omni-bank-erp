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
Employee Development System (EDS) - Enterprise L&D Management
==============================================================
Comprehensive banking Learning & Development management suite for Bunna Bank:
  - Training Needs Analysis (TNA) capture, consolidation, and weighted prioritization
  - Annual L&D Plan & Calendar creation, quarterly budgeting, and plan-vs-actual variance tracking
  - Course catalog, modular curriculum architecture, and external provider register
  - Trainer profile, qualification scoring, and venue resource scheduling
  - Session scheduling, nomination workflows, automated rosters, and QR attendance
  - Kirkpatrick 4-Level evaluation engine (Reaction, Learning, Behavior, ROI)
  - Dynamic completion certificate generation with bank watermark, portal downloads, and verification
  - External training provider performance appraisals and strategic learning partnerships
  - Employee sponsorship programs, higher education assistance, and internship clearance
  - Seamless system integrations with LMS, PMS, Payroll, and General Ledger
    """,
    'depends': [
        'base',
        'hr',
        'mail',
        'portal',
        'hr_employee_custom',
        'competency_management',
        'performance_management',
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
        'views/eds_dashboard_views.xml',
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
        'wizards/eds_attendance_import_views.xml',
        'wizards/eds_assessment_import_views.xml',
        'wizards/eds_level1_import_views.xml',
        'wizards/eds_gap_import_views.xml',
        'wizards/eds_pms_gap_import_views.xml',
        'wizards/eds_tna_exclude_wizard_views.xml',
        'wizards/eds_template_import_wizard_views.xml',
        'views/eds_delivery_views.xml',
        'views/eds_knowledge_sharing_views.xml',
        'views/eds_tna_views.xml',
        'views/eds_evaluation_views.xml',
        'views/eds_certificate_views.xml',
        'views/portal_certificate_templates.xml',
        'views/eds_budget_views.xml',
        'views/eds_sponsorship_education_views.xml',
        'views/eds_internship_views.xml',
        'views/eds_integration_views.xml',
        'views/eds_report_views.xml',
        'views/hr_employee_views.xml',
        'views/eds_workplace_learning_views.xml',
        'views/eds_idp_views.xml',
        'views/eds_assessment_center_views.xml',
        'views/eds_partnership_views.xml',
        'views/eds_menus.xml',
        'report/eds_tna_register.xml',
        'report/eds_certificate_template.xml',
        'report/eds_reports.xml',
        'report/eds_level1_report.xml',
        'report/eds_level2_report.xml',
        'report/eds_level3_report.xml',
        'report/eds_vrs_report.xml',
        'report/eds_trainer_profile_report.xml',
        'report/eds_unscheduled_report.xml',
        'report/eds_level4_report.xml',
        'report/eds_knowledge_sharing_report.xml',
        'report/eds_vendor_appraisal_report.xml',
        'report/eds_internship_appraisal_report.xml',
        'report/eds_sponsorship_application_report.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
