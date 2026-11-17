with open(r"d:\projects\odoo19\custom_addons\bunna_pbms\security\pbms_security.xml", "r", encoding="utf-8") as f:
    lines = f.readlines()

new_lines = []
skip = False
for line in lines:
    if '<record id="rule_plan_district"' in line:
        new_lines.append(line)
        new_lines.append('        <field name="name">PBMS Plan: direct child operating units (District Reviewer)</field>\n')
        new_lines.append('        <field name="model_id" ref="model_pbms_planning_category"/>\n')
        new_lines.append('        <field name="domain_force">\n')
        new_lines.append("            ['|',\n")
        new_lines.append("                ('org_unit_id', 'in', user._pbms_operating_unit_ids()),\n")
        new_lines.append("                '&amp;',\n")
        new_lines.append("                    ('state', '!=', 'draft'),\n")
        new_lines.append("                    '&amp;',\n")
        new_lines.append("                        '!', '&amp;', ('state', '=', 'chief_review'), ('district_reviewer_id', '=', False),\n")
        new_lines.append("                        '|',\n")
        new_lines.append("                            ('district_id', 'in', user._pbms_operating_unit_ids()),\n")
        new_lines.append("                            '|',\n")
        new_lines.append("                                ('org_unit_id', 'in', user._pbms_child_operating_unit_ids()),\n")
        new_lines.append("                                ('org_unit_id.parent_unit', 'in', user._pbms_operating_unit_ids())]\n")
        new_lines.append('        </field>\n')
        new_lines.append('        <field name="groups" eval="[(4, ref(\'group_pbms_district_reviewer\'))]"/>\n')
        new_lines.append('    </record>\n')
        skip = True
    elif skip and '</record>' in line:
        skip = False
    elif not skip:
        new_lines.append(line)

with open(r"d:\projects\odoo19\custom_addons\bunna_pbms\security\pbms_security.xml", "w", encoding="utf-8") as f:
    f.writelines(new_lines)
print("Updated pbms_security.xml successfully")
