# -*- coding: utf-8 -*-
{
    'name': "Competency Management System",
    'summary': "Integrated Competency Framework: dictionary, role mapping, assessment, gap analysis and IDP.",
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Competency',
    'author': 'Desalegn & Abeza',
    'website': 'https://www.bunnabanksc.com',
    'license': 'LGPL-3',
    'description': """
Competency Management System (Bunna Bank ERP HR Upgrade)
========================================================
Support module for the Employee Development System (EDS). Operationalizes the
Bank's Integrated Competency Framework (Core / Leadership / Technical pillars,
Basic / Intermediate / Advanced / Expert proficiency levels).

Key Features:
- Competency Framework & Dictionary administration with version control.
- Role-Competency Mapping (Job Position + Grade) as master reference.
- Competency Assessment cycles (self / supervisor / 360 / skills test) with
  evidence, comments, gap computation, approval workflow and locking.
- Individual Development Plans (IDP) with activities and review checkpoints.
- Integration hooks for EDS (TNA input), Recruitment (eligibility) and the
  employee master (smart buttons).
    """,
    'depends': [
        'base',
        'hr',
        'mail',
        'portal',
        'hr_employee_custom',
    ],
    'data': [
        'security/competency_security.xml',
        'security/ir.model.access.csv',
        'data/competency_sequence.xml',
        'data/competency_seed_data.xml',
        'views/competency_framework_views.xml',
        'views/competency_competency_views.xml',
        'views/competency_role_mapping_views.xml',
        'views/competency_assessment_views.xml',
        'views/competency_idp_views.xml',
        'views/hr_employee_views.xml',
        'views/competency_menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
