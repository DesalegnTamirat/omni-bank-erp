# -*- coding: utf-8 -*-
##############################################################################
#
#    ERP Artists
#    Copyright (C) 2025-TODAY ERP Artists (<https://www.erpartists.com>).
#    Author: ERP Artists (<https://www.erpartists.com>)
#
##############################################################################
{
    "name": "Bunna Bank Contact Center & Helpdesk Management",
    "version": "19.0.3.0.0",
    "category": "Sales Service",
    "summary": """Bunna Bank Contact Center (CC) Hub: Finacle CBS lookup, 3-tier Service Catalogue,
    NBE Regulatory Complaint & Ethics tracking, OLA engine with SDT, multi-tier escalation,
    and agent availability.""",
    "description": """
Bunna Bank Contact Center (CC) & Service Management Hub
======================================================
Empowering Bunna Bank's omnichannel contact center with banking intelligence:
- Operating units & branches integration.
- Finacle CBS account & CIF verification.
- 3-tier Service Catalogue (Family -> Service -> Sub-Category).
- NBE Regulatory Complaint handling & Root Cause Analysis.
- Operational Level Agreements (OLA) with Service Delivery Time (SDT).
- 2nd-level specialist escalation workflow with automated notifications.
- Knowledge Base with standard operating procedures (SOPs).
- Agent availability & duty status routing.
- Real-time Bunna Bank branded OWL dashboard.
""",
    "author": "ERP Artists & Bunna Bank IT Team",
    "website": "https://www.erpartists.com",
    "license": "LGPL-3",
    "depends": [
        "mail",
        "portal",
        "rating",
        "analytic",
        "hr_employee_custom",
    ],
    "data": [
        "security/helpdesk_security.xml",
        "security/ir.model.access.csv",
        "data/helpdesk_data.xml",
        "data/helpdesk_rating_data.xml",
        "data/helpdesk_catalogue_data.xml",
        "data/helpdesk_operation_data.xml",
        "views/helpdesk_ticket_case_type_views.xml",
        "views/helpdesk_ticket_customer_type_views.xml",
        "views/res_partner_views.xml",
        "views/res_users_views.xml",
        "views/res_config_settings_views.xml",
        "views/helpdesk_service_catalogue_views.xml",
        "views/helpdesk_ola_views.xml",
        "views/helpdesk_knowledge_views.xml",
        "views/helpdesk_ticket_templates.xml",
        "views/helpdesk_team_operation_views.xml",
        "views/helpdesk_ticket_team_views.xml",
        "views/helpdesk_ticket_stage_views.xml",
        "views/helpdesk_ticket_category_views.xml",
        "views/helpdesk_ticket_channel_views.xml",
        "views/helpdesk_ticket_tag_views.xml",
        "views/helpdesk_ticket_views.xml",
        "views/helpdesk_sla_views.xml",
        "views/helpdesk_reporting_views.xml",
        "views/helpdesk_dashboard_views.xml",
        "wizards/helpdesk_ticket_duplicate_wizard_views.xml",
        "wizards/helpdesk_ticket_merge_wizard_views.xml",
        "wizards/helpdesk_ticket_convert_wizard_views.xml",
        "wizards/helpdesk_ticket_escalate_wizard_views.xml",
        "views/helpdesk_ticket_menu.xml",
    ],
    "demo": ["demo/helpdesk_demo.xml"],
    "assets": {
        "web.assets_frontend": [
            "bunna_helpdesk/static/src/js/new_ticket.esm.js",
        ],
        "web.assets_backend": [
            "bunna_helpdesk/static/src/scss/**/*.scss",
            "bunna_helpdesk/static/src/views/**/*.esm.js",
            "bunna_helpdesk/static/src/views/**/*.xml",
        ],
        "web.assets_unit_tests": [
            "bunna_helpdesk/static/tests/**/*.test.js",
        ],
    },
    'images': [
        'static/description/banner.png',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'price': 0.00,
    'currency': 'USD',
}
