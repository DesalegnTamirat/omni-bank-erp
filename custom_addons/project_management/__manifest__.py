# -*- coding: utf-8 -*-
{
    'name': 'Project Management',
    'version': '19.0.2.0.0',
    'category': 'Services/Project',
    'summary': 'Enterprise Initiative, Project, Milestone, Deliverable & Task Management',
    'description': """
Enterprise Project & Task Management (Standalone Odoo 19)
=========================================================
A complete 6-tier project management system:
Initiative -> Project -> Milestone -> Deliverable -> Task -> Sub-task

Features:
- Executive Analytics & Interactive Real-Time Dashboard (OWL 2)
- Strategic Initiatives (Programs, Corporate Alignment, Strategic Sources)
- Projects with Deliverables, Milestones, Budget, Capacity, Risk Register, Dependencies
- Standalone Deliverables & Work Packages with Weight Rollups
- Separation of Project Tasks and Non-Project (General / Operational) Tasks
- Subtasks with individual timelines and weight percentages
- Task Dependencies (Blocked By & Blocking indicators)
- Progress & Work Logging with Multi-Level Weighted Rollup Engine
- Role-based security & governance (Managers, Coordinators, Members)
- Interactive Kanban Boards, Lists, Calendar Timelines, and Forms
    """,
    'author': 'Derese',
    'depends': [
        'base',
        'mail',
        'web',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'data/ir_sequence_data.xml',
        'data/default_stages_data.xml',
        'views/dashboard_views.xml',
        'views/strategic_source_views.xml',
        'views/strategic_objective_views.xml',
        'views/initiative_views.xml',
        'views/milestone_views.xml',
        'views/deliverable_views.xml',
        'views/project_views.xml',
        'views/task_views.xml',
        'views/stage_views.xml',
        'views/tag_views.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            ('include', 'web.chartjs_lib'),
            'project_management/static/src/scss/**/*',
            'project_management/static/src/components/dashboard/**/*',
            'project_management/static/src/components/project_state_selection/**/*',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
