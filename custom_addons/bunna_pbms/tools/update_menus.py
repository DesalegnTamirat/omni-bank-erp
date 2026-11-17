# -*- coding: utf-8 -*-
with open('views/pbms_menus.xml', 'r', encoding='utf-8') as f:
    text = f.read()

snippet = """    <!-- Dynamic Workflows & Access Configuration Sub-Menu -->
    <menuitem id="menu_pbms_dynamic_workflow_config_parent"
              name="Workflows &amp; Access Controls"
              parent="menu_pbms_config"
              sequence="1"
              groups="bunna_pbms.group_pbms_manager"/>

    <menuitem id="menu_pbms_config_categories"
              name="1. Planning Categories Configuration"
              parent="menu_pbms_dynamic_workflow_config_parent"
              action="action_pbms_category_definition"
              sequence="10"
              groups="bunna_pbms.group_pbms_manager"/>

    <menuitem id="menu_pbms_config_privileges"
              name="2. Privileges Configuration"
              parent="menu_pbms_dynamic_workflow_config_parent"
              action="action_pbms_privilege"
              sequence="20"
              groups="bunna_pbms.group_pbms_manager"/>

    <menuitem id="menu_pbms_config_roles"
              name="3. Roles and Responsibilities Configuration"
              parent="menu_pbms_dynamic_workflow_config_parent"
              action="action_pbms_role_definition"
              sequence="30"
              groups="bunna_pbms.group_pbms_manager"/>

    <menuitem id="menu_pbms_config_workflows"
              name="4. Organizational Workflow Configuration"
              parent="menu_pbms_dynamic_workflow_config_parent"
              action="action_pbms_workflow_definition"
              sequence="40"
              groups="bunna_pbms.group_pbms_manager"/>

    <menuitem id="menu_pbms_config_category_workflow_map"
              name="5. Category-to-Workflow Mapping"
              parent="menu_pbms_dynamic_workflow_config_parent"
              action="action_pbms_category_workflow_mapping"
              sequence="50"
              groups="bunna_pbms.group_pbms_manager"/>

    <menuitem id="menu_pbms_config_workflow_steps"
              name="6. Workflow Steps &amp; Transitions"
              parent="menu_pbms_dynamic_workflow_config_parent"
              action="action_pbms_workflow_step"
              sequence="60"
              groups="bunna_pbms.group_pbms_manager"/>

    <menuitem id="menu_pbms_config_privilege_assignments"
              name="7. User and Group Privilege Assignments"
              parent="menu_pbms_dynamic_workflow_config_parent"
              action="action_pbms_privilege_assignment"
              sequence="70"
              groups="bunna_pbms.group_pbms_manager"/>

"""

target = '    <menuitem id="menu_pbms_planning_config"'
if target in text:
    new_text = text.replace(target, snippet + target, 1)
    with open('views/pbms_menus.xml', 'w', encoding='utf-8') as f:
        f.write(new_text)
    print('Updated successfully')
else:
    print('Target not found')
