# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID

def post_init_hook(env):
    """Clean up and enforce strict menu security group assignments after module installation/upgrade."""
    menu_map = {
        'competency_management.menu_competency_dictionary': ['competency_management.group_competency_employee'],
        'competency_management.menu_competency_cluster': ['competency_management.group_competency_officer'],
        'competency_management.menu_competency_role_mapping': ['competency_management.group_competency_employee'],
        'competency_management.menu_my_competency_assessments': ['competency_management.group_competency_employee'],
        'competency_management.menu_my_competency_evaluations': ['competency_management.group_competency_employee'],
        'competency_management.menu_competency_assessments': ['competency_management.group_competency_supervisor'],
        'competency_management.menu_competency_assessment_cycles': ['competency_management.group_competency_officer'],
        'competency_management.menu_competency_reports_categ': ['competency_management.group_competency_supervisor'],
        'competency_management.menu_competency_report_wizard': ['competency_management.group_competency_supervisor'],
        'competency_management.menu_competency_tna_analytics_report': ['competency_management.group_competency_supervisor'],
        'competency_management.menu_competency_coverage_report': ['competency_management.group_competency_supervisor'],
        'competency_management.menu_competency_config_categ': ['competency_management.group_competency_officer'],
        'competency_management.menu_competency_matrix_config': ['competency_management.group_competency_officer'],
        'competency_management.menu_competency_360_config': ['competency_management.group_competency_officer'],
        'competency_management.menu_competency_director_peer_config': ['competency_management.group_competency_officer'],
        'competency_management.menu_competency_rating_models': ['competency_management.group_competency_officer'],
        'competency_management.menu_competency_skills_test': ['competency_management.group_competency_supervisor'],
        'competency_management.menu_competency_team_gap_dashboard': ['competency_management.group_competency_supervisor'],
        'competency_management.menu_competency_dashboard_snapshot': ['competency_management.group_competency_supervisor'],
    }
    for xml_id, group_xml_ids in menu_map.items():
        try:
            menu = env.ref(xml_id, raise_if_not_found=False)
            if menu:
                groups = [env.ref(g_xml, raise_if_not_found=False).id for g_xml in group_xml_ids if env.ref(g_xml, raise_if_not_found=False)]
                menu.write({'group_ids': [(6, 0, groups)]})
        except Exception:
            pass

    # Auto-seed all directorate positions into competency.director.peer.config with empty peers
    try:
        env['competency.director.peer.config'].action_generate_director_records()
    except Exception:
        pass

