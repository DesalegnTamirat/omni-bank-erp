# -*- coding: utf-8 -*-
{
    'name': "Bunna Knowledge Management System (KMS)",
    'summary': "Governed document repository, digital library, tacit knowledge capture, Communities of Practice, and SME directory.",
    'version': '19.0.1.0.0',
    'category': 'Human Resources/Knowledge',
    'author': 'Bunna Bank S.C.',
    'website': 'https://www.bunnabanksc.com',
    'license': 'LGPL-3',
    'description': """
Bunna Bank Knowledge Management System (KMS)
============================================
Operationalizes BRD Part 3 Module 1 requirements for institutional knowledge management:
- Centralized governed document repository for Policies, SOPs, Manuals, and Regulatory Directives.
- Strict 4-stage version control and multi-level approval workflows (Draft, Review, Approved, Archived).
- Curated Digital Library of e-books, whitepapers, banking industry studies, and training reference catalogs.
- Tacit knowledge mechanisms: Communities of Practice (CoP), Knowledge Capture Sessions, Lessons Learned, and Mentoring Tracking.
- Bank-wide Subject Matter Expert (SME) & Skill Directory mapped to organizational competencies.
- Interactive Q&A discussion forums with peer upvoting and accepted answers.
- Enterprise security: Dynamic on-the-fly PDF watermarking, strict view-only flags, RBAC download restrictions, and immutable audit logs.
- Gamification: Best Contributor of the Month recognition and knowledge contribution points.
    """,
    'depends': [
        'base',
        'auth_ldap',
        'auth_totp',
        'hr',
        'mail',
        'portal',
        'hr_employee_custom',
        'competency_management',
        'recognition_engine',
    ],
    'data': [
        'security/kms_security_groups.xml',
        'security/kms_security_rules.xml',
        'security/ir.model.access.csv',
        'data/kms_sequence.xml',
        'data/kms_default_data.xml',
        'data/kms_ldap_data.xml',
        'views/kms_category_views.xml',
        'views/kms_document_views.xml',
        'views/kms_digital_library_views.xml',
        'views/kms_cop_views.xml',
        'views/kms_tacit_views.xml',
        'views/kms_forum_views.xml',
        'views/kms_expert_views.xml',
        'views/kms_audit_views.xml',
        'views/kms_gamification_views.xml',
        'views/kms_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'knowledge_management/static/src/scss/kms_style.scss',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'post_init_hook': '_kms_post_init_hook',
}
