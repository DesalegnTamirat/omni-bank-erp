# -*- coding: utf-8 -*-
{
    'name': "Assessment System Management",
    'summary': "Module 3: Exam System (Written Assessment) + Competency-Based Interview System (CBIS)",
    'description': """
Assessment Management System (Module 3)
=======================================
Comprehensive, enterprise-grade candidate assessment platform for Bunna Bank:

1. Rules & Configuration Engine:
   - Dynamic non-hardcoded Weight Distribution matrix (External, Internal, Transfer).
   - Invariant: Weights strictly sum to 100%.
   - Mandatory 50% minimum passing score floor per component (BR-AMS-05).
   - Configurable late lockout windows and grading SLAs.

2. Written Exam System (EXM):
   - Central Question Bank with PDF import pipeline and approval review queue.
   - Dynamic Exam generation with seeded question & option randomization.
   - Secure browser delivery & proctoring engine (copy/paste blocking, screenshot prevention, tab-switch detection, auto-save every 30s).
   - Instant auto-scoring and manual essay grading queue with a 3-working-day SLA watchdog.
   - Automated anti-cheat disqualification engine and ESS candidate appeal workflow.
   - Anonymized HR portal result publication (Candidate ID only) with candidate view tracking.

3. Competency-Based Interview System (CBIS):
   - Competency library with STAR / STARR / Likert evaluation methods.
   - Interview scheduling with panel auto-provisioning and external document verification gate.
   - Interviewer dashboard with live evaluation forms, draft/submit workflow, and absent tracking.
   - Event-driven evaluation auto-locking when all assigned panel members submit.
   - Composite ranking reports with official interviewer signature blocks (PDF) and CSV exports.

4. Transfer Assessment Management:
   - Automatic workflow trigger on ESS transfer request submission.
   - Transfer scoring matrix (PMS + Application Date + Experience + Location Service + Recommendation).
   - Integration with Recruitment Transfer Ranking Algorithm.
    """,
    'version': '19.0.2.0.0',
    'category': 'Human Resources',
    'author': 'EAD Team',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'hr',
        'hr_recruitment',
        'mail',
        'portal',
        'website',
        'custom_recruitment',
        'competency_management',
    ],
    'data': [
        'security/assessment_security_groups.xml',
        'security/ir.model.access.csv',
        'security/assessment_security_rules.xml',
        'data/interview_session_sequence.xml',
        'data/exam_sequences.xml',
        'data/assessment_weight_profiles.xml',
        'data/assessment_cron_data.xml',
        'reports/assessment_ranking_report.xml',
        'reports/assessment_ranking_template.xml',
        'wizards/exam_generation_wizard_views.xml',
        'views/assessment_rules_views.xml',
        'views/cbis_competency_views.xml',
        'views/exam_question_bank_views.xml',
        'views/exam_definition_views.xml',
        'views/exam_session_views.xml',
        'views/exam_grading_views.xml',
        'views/exam_disqualification_views.xml',
        'views/assessment_publication_views.xml',
        'views/cbis_interview_views.xml',
        'views/transfer_assessment_views.xml',
        'views/exam_portal_templates.xml',
        'views/assessment_criteria.xml',
        'views/applicant_assessment.xml',
        'views/interview_rate_sheet_views.xml',
        'views/assessment_dashboard_views.xml',
        'views/my_panel_assignments_views.xml',
        'views/transfer_config_settings_views.xml',
        'views/menu_assessment.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'assessment_system/static/src/assessment_dashboard/assessment_dashboard.scss',
            'assessment_system/static/src/assessment_dashboard/assessment_dashboard.js',
            'assessment_system/static/src/assessment_dashboard/assessment_dashboard.xml',
        ],
    },
    'installable': True,
    'application': True,
}
