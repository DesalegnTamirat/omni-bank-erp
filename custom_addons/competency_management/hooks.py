# -*- coding: utf-8 -*-
from odoo import api, SUPERUSER_ID

def post_init_hook(env):
    """Clean up and enforce strict menu security group assignments after module installation/upgrade.

    Also handles:
    - Creating the 4-scale rating model if missing (search-or-create, not re-seeded on upgrade).
    - Removing the 5-scale rating model if it still exists from old seed data.
    - Ensuring the singleton competency.matrix.config record exists.
    """
    # ── 0. Clean up stale ir.model.data entries for removed seed records ──────
    # These XML IDs were removed from competency_seed_data.xml.
    # Deleting their ir.model.data rows prevents Odoo from trying to re-link
    # or warn about orphaned XML IDs on upgrade.
    stale_xml_ids = [
        ('competency_management', 'rating_model_5_scale'),
        ('competency_management', 'default_competency_matrix_config'),
        # These were previously act_window; now replaced by *_server IDs as ir.actions.server
        ('competency_management', 'action_competency_matrix_guidelines_config'),
        ('competency_management', 'action_competency_360_config'),
    ]
    for module_name, xml_id_name in stale_xml_ids:
        try:
            stale = env['ir.model.data'].search([
                ('module', '=', module_name),
                ('name', '=', xml_id_name),
            ], limit=1)
            if stale:
                stale.unlink()
        except Exception:
            pass

    # ── 1. Menu Security Group Assignments ───────────────────────────────────
    menu_map = {
        'competency_management.menu_competency_dictionary': ['competency_management.group_competency_employee'],
        'competency_management.menu_competency_cluster': ['competency_management.group_competency_officer'],
        'competency_management.menu_competency_role_mapping': ['competency_management.group_competency_employee'],
        'competency_management.menu_my_competency_assessments': ['competency_management.group_competency_employee'],
        'competency_management.menu_my_competency_evaluations': ['competency_management.group_competency_employee'],
        'competency_management.menu_competency_assessments': ['competency_management.group_competency_supervisor'],
        'competency_management.menu_competency_assessment_cycles': ['competency_management.group_competency_officer'],
        'competency_management.menu_competency_reports_categ': ['competency_management.group_competency_officer'],
        'competency_management.menu_competency_report_wizard': ['competency_management.group_competency_officer'],
        'competency_management.menu_competency_tna_analytics_report': ['competency_management.group_competency_officer'],
        'competency_management.menu_competency_config_categ': ['competency_management.group_competency_officer'],
        'competency_management.menu_competency_matrix_config': ['competency_management.group_competency_officer'],
        'competency_management.menu_competency_360_config': ['competency_management.group_competency_officer'],
        'competency_management.menu_competency_director_peer_config': ['competency_management.group_competency_officer'],
        'competency_management.menu_competency_rating_models': ['competency_management.group_competency_officer'],
        'competency_management.menu_competency_skills_test': ['competency_management.group_competency_supervisor'],
        'competency_management.menu_competency_dashboard_snapshot': ['competency_management.group_competency_officer'],
    }
    for xml_id, group_xml_ids in menu_map.items():
        try:
            menu = env.ref(xml_id, raise_if_not_found=False)
            if menu:
                groups = [env.ref(g_xml, raise_if_not_found=False).id for g_xml in group_xml_ids if env.ref(g_xml, raise_if_not_found=False)]
                menu.write({'group_ids': [(6, 0, groups)]})
        except Exception:
            pass

    # Clean up removed reporting menus from DB
    removed_menu_xml_ids = [
        'competency_management.menu_competency_coverage_report',
        'competency_management.menu_competency_team_gap_dashboard',
    ]
    for m_xml in removed_menu_xml_ids:
        try:
            m = env.ref(m_xml, raise_if_not_found=False)
            if m:
                m.unlink()
        except Exception:
            pass

    # ── 2. Ensure 4-Scale Rating Model exists (search-or-create) ─────────────
    # Using search-or-create in the hook (not just XML seed data) means:
    # if the record is deleted from the DB and the module is upgraded,
    # this hook WILL recreate it — but only on an explicit upgrade, not silently.
    # Change the hook to not recreate if you want full manual control.
    try:
        RatingModel = env['competency.rating.model']
        rating_4scale = RatingModel.search([('code', '=', '4SCALE')], limit=1)
        if not rating_4scale:
            rating_4scale = RatingModel.create({
                'name': '4-Point Proficiency Scale',
                'code': '4SCALE',
                'max_rating': 4,
                'description': 'Standard 4-Level scale (Level 1 - Basic, Level 2 - Intermediate, Level 3 - Advanced, Level 4 - Expert)',
                'line_ids': [
                    (0, 0, {'level': '1', 'name': 'Level 1 - Basic', 'sequence': 10}),
                    (0, 0, {'level': '2', 'name': 'Level 2 - Intermediate', 'sequence': 20}),
                    (0, 0, {'level': '3', 'name': 'Level 3 - Advanced', 'sequence': 30}),
                    (0, 0, {'level': '4', 'name': 'Level 4 - Expert', 'sequence': 40}),
                ],
            })
    except Exception:
        pass

    # ── 3. Remove 5-Scale Rating Model if it exists (from old seed data) ─────
    try:
        RatingModel = env['competency.rating.model']
        rating_5scale = RatingModel.search([('code', '=', '5SCALE')], limit=1)
        if rating_5scale:
            # Only delete if no competency is using it
            competencies_using_it = env['competency.competency'].search(
                [('rating_model_id', '=', rating_5scale.id)], limit=1
            )
            if not competencies_using_it:
                rating_5scale.unlink()
    except Exception:
        pass

    # ── 4. Ensure singleton competency.matrix.config exists ──────────────────
    try:
        env['competency.matrix.config'].get_active_config()
    except Exception:
        pass

