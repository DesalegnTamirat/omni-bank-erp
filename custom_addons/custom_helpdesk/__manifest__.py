# -*- coding: utf-8 -*-
{
    'name': 'Custom Helpdesk',
    'summary': 'Unified Bunna Bank Contact Center Helpdesk Management & SLA Tracking',
    'description': '''
Custom Helpdesk Management
==========================
Enterprise Helpdesk solution designed for Bunna Bank Contact Center Operations:
- Service Families, Categories, Sub-Categories & Classification
- CIF & Account Number Customer Identification & Segmentation
- NBE Complaint Management & Ethics Investigation
- Knowledge Base & SOP Article Publishing Workflow
- OLA / SLA Management & Service Delivery Time (SDT)
- Helpdesk Teams, Stages, Channels, Tags & Ticket Lifecycle
- Interactive Modern Dashboard Analytics
''',
    'version': '19.0.1.0.0',
    'category': 'Services/Helpdesk',
    'author': 'Bunna Bank CC & Digital Customer Acquisition Directorate',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'portal', 'resource', 'rating', 'hr'],
    'data': [
        'security/helpdesk_security.xml',
        'security/helpdesk_sla_security.xml',
        'security/ir.model.access.csv',
        'data/helpdesk_data.xml',
        'views/helpdesk_service_family_views.xml',
        'views/helpdesk_knowledge_views.xml',
        'views/helpdesk_ticket_complaint_views.xml',
        'views/helpdesk_ticket_main_views.xml',
        'views/helpdesk_menu_parents.xml',
        'views/helpdesk_sla_report.xml',
        'views/helpdesk_sla_views.xml',
        'views/helpdesk_ticket.xml',
        'views/helpdesk_ticket_category_views.xml',
        'views/helpdesk_ticket_channel_views.xml',
        'views/helpdesk_ticket_sla.xml',
        'views/helpdesk_ticket_stage_views.xml',
        'views/helpdesk_ticket_tag_views.xml',
        'views/helpdesk_ticket_team.xml',
        'views/helpdesk_ticket_team_view.xml',
        'views/helpdesk_ticket_team_views.xml',
        'views/helpdesk_ticket_type.xml',
        'views/helpdesk_ticket_view.xml',
        'views/helpdesk_ticket_views.xml',
        'views/res_config_settings_views.xml',
        'views/res_partner_views.xml',
        'wizards/helpdesk_ticket_duplicate_wizard_views.xml',
        'views/helpdesk_dashboard_action.xml',
        'views/helpdesk_ticket_menu.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'custom_helpdesk/static/src/js/new_ticket.esm.js',
        ],
        'web.assets_backend': [
            'custom_helpdesk/static/src/views/helpdesk_dashboard/helpdesk_dashboard.css',
            'custom_helpdesk/static/src/views/**/*.esm.js',
            'custom_helpdesk/static/src/views/**/*.xml',
        ],
    },
    'installable': True,
    'application': True,
}
